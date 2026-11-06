# SPDX-License-Identifier: GPL-3.0-or-later
"""Contre-épreuve optionnelle avec le VRAI entraîneur (sans VST, ni carte son).

GOLEM_PARAMETRIC_TEST_PYTHON=<python du venv paramétrique> pytest -q tests/test_parametric_worker_smoke.py
Entraîne un petit réseau à deux potards, recharge son export, matérialise un réglage inédit et
compare numériquement les deux inférences. Ce test ne mesure pas la fidélité d'un VST réel.
"""
import json
import math
import os
from pathlib import Path
import subprocess

import pytest

from bridge import plugin_capture as P, plugin_capture_parametric as K


@pytest.mark.skipif(not os.environ.get("GOLEM_PARAMETRIC_TEST_PYTHON"), reason="optional parametric trainer environment")
def test_trained_controls_export_and_bake_at_unseen_values(tmp_path):
    controls = [{"i": i, "name": n, "min": 0.1, "max": 0.9, "default": 0.5} for i, n in enumerate(("Gain", "Tone"))]
    model = K.model_config(controls)
    model["net"]["config"]["layers"] = [{"input_size": 1, "condition_size": 1, "channels": 2,
        "kernel_size": 3, "dilations": [1, 2], "activation": "Tanh", "gated": False,
        "head": {"out_channels": 1, "kernel_size": 1, "bias": True}}]
    (tmp_path / "model.json").write_text(json.dumps(model))
    x = [0.15 * math.sin(i * .051) + 0.05 * math.sin(i * .173) for i in range(144000)]
    P.write_wav(tmp_path / "input.wav", x)
    data = {"type": "parametric", "common": {"delay": 0}, "train": [], "validation": []}
    for split, positions in (("train", [(0.1, 0.1), (0.1, 0.9), (0.9, 0.1), (0.9, 0.9)]),
                             ("validation", [(0.25, 0.75), (0.75, 0.25)])):
        for i, (gain, tone) in enumerate(positions):
            target = tmp_path / f"{split}-{i}.wav"
            # WAV flottant > 0 dBFS : doit s'entraîner sans niveler chaque position.
            P.write_wav(target, [3 * math.tanh(v * (1 + 3 * gain)) * (0.5 + tone) for v in x])
            data[split].append({"x_path": str(tmp_path / "input.wav"), "y_path": str(target),
                                "params": {"Gain": gain, "Tone": tone}, "ny": 8192})
    (tmp_path / "data.json").write_text(json.dumps(data))
    script = tmp_path / "check.py"
    script.write_text('''import importlib.util, json, sys, subprocess
from pathlib import Path
import torch
from nam.models import init_from_nam
from nam.models.parametric import bake
from nam.train.parametric import _ParametricLightningModule, _get_parametric_net
spec=importlib.util.spec_from_file_location("worker",sys.argv[1])
worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
work=Path(sys.argv[2])
worker.train(work,1)
net=worker.load_model(work/"output/model_parametric.nam")
values={"Gain":0.33,"Tone":0.66}
folder=work/"baked";folder.mkdir()
(work/"values.json").write_text(json.dumps(values))
subprocess.run([sys.executable,sys.argv[1],"bake",str(work/"output/model_parametric.nam"),str(work/"values.json"),str(folder)],check=True)
fixed=init_from_nam(worker.read(folder/"model.nam"));fixed.eval()
torch.manual_seed(1)
x=torch.randn(2048)*.1
config=worker.read(work/"model.json")
checkpoint=next((work/"output").rglob("*.ckpt"))
trained=_ParametricLightningModule.load_from_checkpoint(checkpoint,**_ParametricLightningModule.parse_config(config))
trained.cpu().eval()
scaled_net=_get_parametric_net(trained)
scale=worker.read(work/"training-scale.json")["scale"]
with torch.no_grad():
 a=net(x,torch.tensor(list(values.values())),pad_start=True)
 scaled=scaled_net(x,torch.tensor(list(values.values())),pad_start=True)
 assert torch.allclose(a,scaled/scale,atol=1e-6,rtol=1e-5),"absolute output level was not restored"
 b=fixed(x,pad_start=True)
 assert torch.isfinite(a).all() and torch.allclose(a,b,atol=1e-6,rtol=1e-5),torch.max(torch.abs(a-b))
 shifted=net(x,torch.tensor([.8,.2]),pad_start=True)
 assert not torch.allclose(a,shifted,atol=1e-8),"control values did not change the learned response"
print("Training, parametric reload, unseen controls and standard WaveNet bake: OK")
''', encoding="utf-8")
    run = subprocess.run([os.environ["GOLEM_PARAMETRIC_TEST_PYTHON"], str(script), str(K.WORKER), str(tmp_path)],
                         capture_output=True, text=True, timeout=180, creationflags=P.NO_WINDOW)
    assert run.returncode == 0, run.stdout + run.stderr
    metrics = json.loads((tmp_path / "metrics.json").read_text())
    scaling = json.loads((tmp_path / "training-scale.json").read_text())
    assert scaling["peak"] > 1 and 0 < scaling["scale"] < 1
    assert len(metrics["unseen_settings"]) == 2 and math.isfinite(metrics["worst_esr"])
    snapshot = P.legacy_nam(tmp_path / "baked" / "model.nam", tmp_path / "snapshot.nam")
    assert snapshot["architecture"] == "WaveNet" and snapshot["version"] == "0.5.4"
