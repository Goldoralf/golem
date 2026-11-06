#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capturer un PLUGIN en NAM, sans câble ni carte son — preuve de concept du 2026-10-02.

L'idée  : sous Windows, capturer automatiquement des plugins pour que leur son voyage vers
Linux et macOS, qui ne les ont pas. Ce banc le fait sur un plugin LIBRE (aucune question de licence
pendant qu'on mesure) et répond à deux questions : est-ce que ça marche, et à quel point c'est fidèle.

  1. render : le signal d'entraînement standard NAM (v3, 190 s) traverse le plugin, hors ligne
              (tools/lv2_render.c — sous Windows ce serait REAPER natif + VST3, le chemin de
              tools/check-core-parity.py render-native)
  2. train  : l'entraîneur NAM officiel (`neural-amp-modeler`, venv à part) en WaveNet CLASSIQUE
              « standard » — pas l'A2 que l'entraîneur fait par défaut : l'A2 ne joue pas sous
              Windows (docs/audit-2026-10-01-parite-coeurs-os.md)
  3. test   : une vraie DI et un balayage, passés dans le plugin ET dans la capture (le NAM LV2 du
              rack), comparés comme par check-core-parity (niveau, nul égalisé, pire tiers d'octave)

    ./tools/capture-plugin.py render --plugin /usr/lib/lv2/gx_bossds1.lv2/gx_bossds1.so \\
        --in 1 --out 0 --ctl 2=-2 --ctl 3=0.5 --ctl 4=0.5 --ctl 5=1 --work W
    ./tools/capture-plugin.py train --work W --epochs 100 --threads 8
    ./tools/capture-plugin.py test --work W --di <prise.wav>

L'environnement d'entraînement (torch processeur + neural-amp-modeler) et le signal v3 vivent hors
du dépôt : ~/.cache/golem-build/nam-train (voir docs/plugin-capture.md).
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRAIN_HOME = Path(os.environ.get("GOLEM_NAM_TRAIN", Path.home() / ".cache" / "golem-build" / "nam-train"))
V3 = TRAIN_HOME / "v3_0_0.wav"
NAM_PY = TRAIN_HOME / "venv" / "bin" / "python"              # torch processeur
NAM_PY_CUDA = TRAIN_HOME / "venv-cuda" / "bin" / "python"    # torch CUDA (GPU NVIDIA), s'il est installé

# Le GPU, tel que l'entraîneur NAM le prend lui-même (nam/train/core.py : cuda, sinon mps) :
# CUDA sur un PC à carte NVIDIA, MPS sur un Mac Apple Silicon (le torch standard de macOS le porte).
_PROBE = ("import torch\n"
          "if torch.cuda.is_available(): print('cuda', torch.cuda.get_device_name(0))\n"
          "elif torch.backends.mps.is_available(): print('mps', 'Apple GPU (MPS)')\n"
          "else: print('cpu', 'CPU')")


def trainer_python():
    """Le GPU s'il RÉPOND, sinon le processeur. Un venv CUDA ne suffit pas : pilote non chargé, et torch
    retombe en silence sur le processeur — 47 min au lieu de 4 (mesuré le 2026-10-02).
    Les captures se font sur les PC et les Mac des membres, avec leur carte graphique (le mainteneur,
    2026-10-02) : le rack n'a pas besoin de GPU."""
    for py in (NAM_PY_CUDA, NAM_PY):
        if not py.exists():
            continue
        r = subprocess.run([str(py), "-c", _PROBE], capture_output=True, text=True)
        kind, _, name = ((r.stdout.strip().splitlines() or ["cpu CPU"])[-1]).partition(" ")
        if r.returncode == 0 and kind in ("cuda", "mps"):
            return py, name
    return NAM_PY, "CPU"


def _host(name, src):
    out = TRAIN_HOME / name
    if not out.exists() or out.stat().st_mtime < (ROOT / "tools" / src).stat().st_mtime:
        subprocess.run(["cc", "-O2", "-pthread", str(ROOT / "tools" / src), "-o", str(out), "-ldl", "-lm"], check=True)
    return out


def cmd_render(a):
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    spec = {"plugin": a.plugin, "uri": a.uri, "in": a.inp, "out": a.out, "ctl": a.ctl}
    (work / "plugin.json").write_text(json.dumps(spec, indent=1))
    r = subprocess.run([str(_host("lv2_render", "lv2_render.c")), a.plugin, a.uri, str(V3), str(work / "target.wav"),
                        "--in", str(a.inp), "--out", str(a.out), *sum((["--ctl", c] for c in a.ctl), [])],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode or "ÉCRÊTÉ" in r.stdout:
        raise SystemExit("rendu refusé : " + (r.stderr.strip() or "la sortie écrête — baisser le niveau du plugin"))


# exécuté DANS le venv d'entraînement : l'entraîneur officiel, avec le WaveNet classique à la
# place de son modèle « packed » (A2) par défaut
_TRAIN = r'''
import json, sys, time, torch
from nam.train import core
cfg_path, x, y, outdir, epochs, threads = sys.argv[1:7]
torch.set_num_threads(int(threads))
model_cfg = json.load(open(cfg_path))
model_cfg.pop("_notes", None)
core._get_packed_model_config = lambda: model_cfg
t0 = time.time()
res = core.train(x, y, outdir, epochs=int(epochs), silent=True, modelname="capture")
device = (torch.cuda.get_device_name(0) if torch.cuda.is_available()
          else "Apple GPU (MPS)" if torch.backends.mps.is_available() else "CPU")
if res is None or res.model is None:
    print("ÉCHEC : l'entraîneur a refusé les données (vérifications)"); sys.exit(1)
res.model.net.export(outdir, basename="capture")
esr = res.metadata.validation_esr
print(json.dumps({"validation_esr": esr, "seconds": round(time.time() - t0), "epochs": int(epochs), "device": device}))
'''


def cmd_train(a):
    work = Path(a.work)
    py, device = trainer_python()
    print(f"entraînement sur : {device}")
    if not py.exists() or not V3.exists():
        raise SystemExit(f"environnement d'entraînement absent : {TRAIN_HOME} (venv + v3_0_0.wav)")
    script = work / "_train.py"
    script.write_text(_TRAIN)
    cfg = TRAIN_HOME / "cfg" / "wavenet.json"
    outdir = work / "train"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir()
    # nice : le rack joue peut-être pendant ce temps ; l'entraînement passe après le son
    r = subprocess.run(["nice", "-n", "19", str(py), str(script), str(cfg), str(V3), str(work / "target.wav"),
                        str(outdir), str(a.epochs), str(a.threads)], capture_output=True, text=True)
    tail = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
    if r.returncode or not tail:
        print((r.stdout + r.stderr)[-2500:])
        raise SystemExit("entraînement en échec")
    res = json.loads(tail[-1])
    nam = next(outdir.glob("**/capture.nam"))
    shutil.copyfile(nam, work / "capture.nam")
    res["architecture"] = json.load(open(work / "capture.nam")).get("architecture")
    (work / "train.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res))


def _parity():
    spec = importlib.util.spec_from_file_location("parity", ROOT / "tools" / "check-core-parity.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cmd_test(a):
    work = Path(a.work)
    P = _parity()
    spec = json.loads((work / "plugin.json").read_text())
    tst = work / "test"
    tst.mkdir(exist_ok=True)
    # deux signaux que l'entraînement n'a JAMAIS vus : une vraie prise et un balayage
    fx = tst / "fx"
    fx.mkdir(exist_ok=True)
    x, rate = P.read_first_channel(a.di)
    P.write_f32(fx / "di.wav", [v * 10 ** (a.di_gain / 20) for v in x[:P.SR * 20]])
    import math
    k = 8 / math.log(20000 / 20)
    sweep = [10 ** (-12 / 20) * math.sin(2 * math.pi * 20 * k * (math.exp(t / P.SR / k) - 1)) for t in range(8 * P.SR)]
    P.write_f32(fx / "sweep.wav", sweep + [0.0] * P.SR)
    plug, cap = tst / "plugin", tst / "capture"
    plug.mkdir(exist_ok=True); cap.mkdir(exist_ok=True)
    host = _host("lv2_render", "lv2_render.c")
    nam_host = _host("core_render_lv2", "core_render_lv2.c")
    for sig in ("di", "sweep"):
        subprocess.run([str(host), spec["plugin"], spec["uri"], str(fx / f"{sig}.wav"), str(plug / f"{sig}.wav"),
                        "--in", str(spec["in"]), "--out", str(spec["out"]), *sum((["--ctl", c] for c in spec["ctl"]), [])],
                       check=True, capture_output=True)
        subprocess.run([str(nam_host), "amp", str(fx / f"{sig}.wav"), str(cap / f"{sig}.wav"), str(work / "capture.nam")],
                       check=True, capture_output=True)
    print(f"plugin  = {spec['plugin']} {' '.join(spec['ctl'])}")
    print(f"capture = {work / 'capture.nam'} ({json.loads((work / 'train.json').read_text())})")
    print(f"{'signal':8} {'niveau capture-plugin':>22} {'nul égalisé':>12} {'pire tiers d’oct.':>22}")
    rows = {}
    for sig in ("di", "sweep"):
        p, _ = P.read_first_channel(plug / f"{sig}.wav")
        c, _ = P.read_first_channel(cap / f"{sig}.wav")
        m = P._metrics(p, c)
        rows[sig] = m
        print(f"{sig:8} {m['level_db']:>+19.2f} dB {m['null_db']:>+9.1f} dB {m['band_db']:>+10.2f} dB @ {m['band_hz']:>5.0f} Hz")
    (work / "test.json").write_text(json.dumps(rows, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render")
    p.add_argument("--plugin", required=True)
    p.add_argument("--uri", default="-")
    p.add_argument("--in", dest="inp", type=int, required=True)
    p.add_argument("--out", type=int, required=True)
    p.add_argument("--ctl", action="append", default=[], help="IDX=VAL")
    p.add_argument("--work", required=True)
    p = sub.add_parser("train")
    p.add_argument("--work", required=True)
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--threads", type=int, default=8)
    p = sub.add_parser("test")
    p.add_argument("--work", required=True)
    p.add_argument("--di", required=True)
    p.add_argument("--di-gain", type=float, default=-6.0)
    a = ap.parse_args()
    {"render": cmd_render, "train": cmd_train, "test": cmd_test}[a.cmd](a)


if __name__ == "__main__":
    main()
