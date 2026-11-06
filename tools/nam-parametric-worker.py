#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adaptateur du fork NAM paramétrique épinglé, exécuté uniquement dans son venv.

Pas de dépendance torch dans le bridge. Les réglages s'exportent en WaveNet standard ;
le modèle complet garde ses potards pour un lecteur HyperWaveNet compatible.
"""
import json
import math
from pathlib import Path
import sys


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_model(path):
    from nam.models.parametric import HyperWaveNet
    data = read(path)
    if data.get("architecture") != "HyperWaveNet":
        raise ValueError("Expected a HyperWaveNet model")
    net = HyperWaveNet.init_from_config({**data["config"], "sample_rate": data.get("sample_rate", 48000)})
    used = net.import_weights(data["weights"])
    if used != len(data["weights"]):
        raise ValueError("Incomplete HyperWaveNet weights")
    net.eval()
    return net


def train(work, epochs):
    import numpy as np
    import pytorch_lightning as pl
    import torch
    from nam.train.parametric import main
    from nam.models.parametric import bake as bake_model, export_parametric
    import soundfile as sf

    pl.seed_everything(0, workers=True)
    torch.set_num_threads(max(1, min(8, torch.get_num_threads())))
    learning = {"train_dataloader": {"batch_size": 16, "shuffle": True, "num_workers": 0, "drop_last": True},
                "val_dataloader": {"batch_size": 16, "num_workers": 0},
                "trainer": {"accelerator": "auto", "devices": 1, "max_epochs": int(epochs),
                            "precision": "32-true", "gradient_clip_val": 1.0,
                            "enable_progress_bar": False, "enable_model_summary": False},
                "threshold_esr": None, "trainer_fit_kwargs": {}, "torch_compile": {"enabled": False}}
    data, model = read(work / "data.json"), read(work / "model.json")
    # Le chargeur NAM refuse |y| >= 1, même en WAV flottant non écrêté.
    # Une seule échelle pour TOUTES les positions, puis compensation aux deux exports.
    peak = max(float(np.max(np.abs(sf.read(c["y_path"], dtype="float32")[0])))
               for split in ("train", "validation") for c in data[split])
    if not math.isfinite(peak) or peak <= 0:
        raise ValueError("Capture audio must be finite and audible")
    scale = min(1.0, 0.9 / peak)
    data.setdefault("common", {})["y_scale"] = scale
    (work / "training-scale.json").write_text(json.dumps({"peak": peak, "scale": scale}), encoding="utf-8")
    output = work / "output"
    output.mkdir(exist_ok=True)
    # Reprise uniquement si modèle, positions, fichiers et échelle sont inchangés.
    try:
        same = read(output / "config_model.json") == model and read(output / "config_data.json") == data
    except (OSError, ValueError):
        same = False
    if same:
        checkpoints = []
        for path in output.rglob("*.ckpt"):
            try:
                checkpoint = torch.load(path, map_location="cpu", weights_only=False)
                checkpoints.append((int(checkpoint["epoch"]), int(checkpoint["global_step"]), path))
            except (OSError, ValueError, RuntimeError, EOFError, KeyError):
                continue  # un disque plein peut laisser un checkpoint incomplet
        if checkpoints:
            epoch, step, path = max(checkpoints, key=lambda item: item[:2])
            learning["trainer_fit_kwargs"]["ckpt_path"] = str(path)
            (work / "resume.json").write_text(json.dumps({"checkpoint": str(path), "epoch": epoch, "step": step}), encoding="utf-8")
            print(f"Resuming parametric training after epoch {epoch + 1}", flush=True)
    main(data, model, learning, output, no_show=True, make_plots=False)
    net = load_model(output / "model_parametric.nam")
    if scale != 1.0:
        # output_scale est l'atténuation d'apprentissage ; le fork applique son inverse.
        bake_model(net, net.nominal_params, output_scale=scale).export(output)
        export_parametric(net, output, basename="model_parametric", output_scale=scale)
        net = load_model(output / "model_parametric.nam")
    metrics = []
    with torch.no_grad():
        for capture in data["validation"]:
            x, sr = sf.read(capture["x_path"], dtype="float32")
            target, sr_y = sf.read(capture["y_path"], dtype="float32")
            if sr != sr_y or sr != 48000 or len(x) != len(target):
                raise RuntimeError("Validation audio does not match")
            params = torch.tensor([capture["params"][p.name] for p in net.param_specs], dtype=torch.float32)
            y = net(torch.from_numpy(x), params, pad_start=True).cpu().numpy()
            esr = float(np.sum((target - y) ** 2) / max(float(np.sum(target ** 2)), 1e-20))
            if not math.isfinite(esr) or not np.isfinite(y).all():
                raise RuntimeError("Non-finite validation output")
            metrics.append({"values": capture["params"], "esr": esr})
    result = {"unseen_settings": metrics, "worst_esr": max(m["esr"] for m in metrics),
              "mean_esr": sum(m["esr"] for m in metrics) / len(metrics)}
    (work / "metrics.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")


def bake(src, values, output):
    import torch
    from nam.models.parametric import bake as bake_model
    torch.set_num_threads(1)
    net = load_model(src)
    bake_model(net, read(values)).export(Path(output))


def main():
    action = sys.argv[1]
    if action == "probe":
        from nam.models.parametric import HyperWaveNet, bake as bake_model  # noqa: F401
        from nam.train.parametric import main as train_main  # noqa: F401
        print("Parametric NAM ready")
    elif action == "train":
        train(Path(sys.argv[2]), int(sys.argv[3]))
    elif action == "bake":
        bake(*sys.argv[2:5])
    else:
        raise ValueError("Unknown parametric worker action")


if __name__ == "__main__":
    main()
