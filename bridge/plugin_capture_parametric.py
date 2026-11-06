# SPDX-License-Identifier: GPL-3.0-or-later
"""Captures de plusieurs réglages VST -> un HyperWaveNet et des réglages NAM portables.

Le moteur courant lit des NAM fixes. Le modèle paramétrique conserve les interactions entre
potards ; chaque réglage demandé est matérialisé en WaveNet avant le rappel normal du bloc.
L'entraîneur tiers reste dans un environnement séparé de celui des captures fixes.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import random
import re
import subprocess
import threading
import time

from . import plugin_capture as P

TRAINER_REV = "a3684411076be69dab53505df14922487697f2cf"
TRAINER_URL = "https://github.com/phillipmself/neural-amp-modeler-parametric"
MAX_CONTROLS = 12
MAX_CAPTURES = 512
WORKER = Path(__file__).resolve().parents[1] / "tools" / "nam-parametric-worker.py"
_setup = {"state": "idle"}
_bake_lock = threading.Lock()
_signal_cache = {}


def home() -> Path:
    return P.train_home().parent / "nam-parametric"


def python() -> Path:
    return P._venv_python(home() / "venv")


def environment() -> dict:
    marker = home() / "trainer-revision"
    try:
        ready = python().is_file() and marker.read_text().strip() == TRAINER_REV
    except OSError:
        ready = False
    missing = [] if ready else ["Parametric NAM trainer"]
    if not _signal_ready():
        missing.append("NAM training signal v3_0_0.wav")
    return {"ready": not missing, "trainer_ready": ready, "missing": missing, "home": str(home())}


def _signal_ready() -> bool:
    source = P.train_home() / "v3_0_0.wav"
    try:
        stat = source.stat()
        signature = (str(source), stat.st_mtime_ns, stat.st_size, P.V3_MD5)
        if _signal_cache.get("signature") != signature:
            _signal_cache.update(signature=signature, valid=hashlib.md5(source.read_bytes()).hexdigest() == P.V3_MD5)
        return bool(_signal_cache.get("valid"))
    except OSError:
        return False


def setup_status() -> dict:
    return dict(_setup)


def start_setup() -> dict:
    with P._lock:
        if _setup.get("state") == "running" or P.setup_status().get("state") == "running":
            return {"ok": False, "error": "Capture tools are already being installed"}
        if P.status().get("state") in ("render", "train", "test", "install", "cancelling"):
            return {"ok": False, "error": "A capture is already running"}
        _setup.clear()
        _setup.update(state="running", msg="Creating the parametric capture environment…", started=time.time())
    threading.Thread(target=_setup_worker, daemon=True).start()
    return {"ok": True}


def _setup_worker() -> None:
    try:
        import venv
        home().mkdir(parents=True, exist_ok=True)
        venv.EnvBuilder(with_pip=True).create(home() / "venv")
        def run(args):
            import os
            env = dict(os.environ, SETUPTOOLS_SCM_PRETEND_VERSION="0.13.0+golemparametric")
            r = subprocess.run([str(x) for x in args], capture_output=True, text=True, env=env, creationflags=P.NO_WINDOW)
            if r.returncode:
                (home() / "setup.log").write_text(r.stdout + r.stderr, encoding="utf-8")
                raise RuntimeError("Parametric trainer installation failed; see " + str(home() / "setup.log"))
        if P._has_nvidia():
            _setup.update(msg="Installing PyTorch with CUDA…")
            run([python(), "-m", "pip", "install", "torch", "--index-url", "https://download.pytorch.org/whl/cu128"])
        _setup.update(msg="Installing the pinned parametric NAM trainer…")
        run([python(), "-m", "pip", "install", f"{TRAINER_URL}/archive/{TRAINER_REV}.zip"])
        run([python(), WORKER, "probe"])
        (home() / "trainer-revision").write_text(TRAINER_REV, encoding="ascii")
        src = P.train_home() / "v3_0_0.wav"
        if not _signal_ready():
            _setup.update(msg="Downloading the NAM training signal…")
            src.parent.mkdir(parents=True, exist_ok=True)
            P._download(P.V3_URL, src, P.V3_MD5)
        _setup.update(state="done", msg="Parametric capture tools ready")
    except Exception as e:
        _setup.update(state="error", error=str(e), msg=str(e))


def _number(v, label: str) -> float:
    if isinstance(v, bool):
        raise ValueError(label + " must be a finite number")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(label + " must be a finite number") from None
    if not math.isfinite(f):
        raise ValueError(label + " must be a finite number")
    return f


def _integer(v, label: str, lo: int, hi: int) -> int:
    f = _number(v, label)
    if not f.is_integer() or not lo <= f <= hi:
        raise ValueError(f"{label} must be an integer between {lo} and {hi}")
    return int(f)


def candidates(params: list, recipe: dict) -> list:
    # Les interrupteurs, sections et effets traduits restent figés. Leur balayage pourrait
    # rallumer un chorus ou retirer un ampli pendant que le modèle croit apprendre son gain.
    fixed = set((recipe.get("full") or {}).get("off") or {})
    for t in recipe.get("translate", []):
        fixed.update(s["from"] for s in t.get("params", {}).values() if "from" in s)
    out = []
    for p in params:
        name = str(p.get("name") or "")
        why = None
        if name in fixed:
            why = "Rebuilt or fixed by the capture recipe"
        elif p.get("toggle") or p.get("step", 0) > 0:
            why = "Switch or stepped parameter; keep it fixed for this capture"
        elif re.search(r"(?i)\b(active|bypass|type|mode|section|midi|program|preset)\b", name):
            why = "Keep switches and effect selection fixed"
        elif re.search(r"(?i)\b(chorus|phaser|delay|reverb|gate|pitch|wow|oct|dly|rev|phsr|chr)\b", name):
            why = "Time or pitch effect; not part of a static NAM capture"
        out.append({**p, "available": why is None, "why": why})
    return out


def check(block: str, plugin: str) -> dict:
    env = environment()
    verdict = P.check(block, plugin, training_env=env)
    verdict["controls"] = candidates(P._live_params(block), P.recipe_for(plugin) or {})
    verdict["max_controls"] = MAX_CONTROLS
    return verdict


def plan(spec: dict, params: list, recipe: dict) -> dict:
    """Plan reproductible : centre, bornes, combinaisons LHS et positions de validation distinctes."""
    if not isinstance(spec, dict):
        raise ValueError("A control capture plan is required")
    knobs = spec.get("controls")
    if not isinstance(knobs, list) or not 1 <= len(knobs) <= MAX_CONTROLS:
        raise ValueError(f"Choose between 1 and {MAX_CONTROLS} continuous controls")
    live = {p["i"]: p for p in candidates(params, recipe)}
    controls, seen, names = [], set(), set()
    for k in knobs:
        if not isinstance(k, dict):
            raise ValueError("Invalid control")
        i = _integer(k.get("i"), "Control index", 0, 100000)
        p = live.get(i)
        if not p or not p.get("available"):
            raise ValueError("Control unavailable: " + str((p or {}).get("name", i)))
        name = p["name"]
        if i in seen or name in names:
            raise ValueError("Choose distinct, uniquely named controls")
        seen.add(i)
        names.add(name)
        lo, hi = _number(k.get("min", 0), "Minimum"), _number(k.get("max", 1), "Maximum")
        if not 0 <= lo < hi <= 1:
            raise ValueError("Control ranges must satisfy 0 ≤ min < max ≤ 1")
        controls.append({"i": i, "name": name, "min": lo, "max": hi,
                         "default": min(hi, max(lo, _number(p.get("value"), "Current value")))})
    d = len(controls)
    count = _integer(spec.get("samples", max(32, 15 * d)), "Training samples", 2 * d + 3, 448)
    holdout = _integer(spec.get("validation", max(8, 3 * d)), "Validation samples", 2, 64)
    if count + holdout > MAX_CAPTURES:
        raise ValueError(f"At most {MAX_CAPTURES} captures per job")
    seed = _integer(spec.get("seed", 0), "Seed", 0, 2147483647)
    rng = random.Random(seed)
    points, used = [], set()
    def add(values, split):
        values = [round(v, 8) for v in values]
        key = tuple(values)
        if key in used:
            return False
        used.add(key)
        points.append({"id": f"{split}-{sum(p['split'] == split for p in points):04d}", "split": split,
                       "values": {k["name"]: v for k, v in zip(controls, values)}})
        return True
    center = [k["default"] for k in controls]
    add(center, "train")
    for j, k in enumerate(controls):
        for v in (k["min"], k["max"]):
            x = list(center)
            x[j] = v
            add(x, "train")
    for edge in ("min", "max"):
        add([k[edge] for k in controls], "train")
    for split, total in (("train", count), ("validation", holdout)):
        attempts = 0
        while sum(p["split"] == split for p in points) < total:
            n = total - sum(p["split"] == split for p in points)
            columns = []
            for k in controls:
                bins = list(range(n))
                rng.shuffle(bins)
                columns.append([k["min"] + (k["max"] - k["min"]) * (b + rng.random()) / n for b in bins])
            for values in zip(*columns):
                add(values, split)
            attempts += 1
            if attempts > 10:
                raise ValueError("Control range is too narrow to sample distinct settings")
    return {"version": 1, "controls": controls, "points": points, "samples": count,
            "validation": holdout, "seed": seed, "trainer_revision": TRAINER_REV}


def start(block: str, plugin: str, patch: str, spec: dict, *, name=None, dest="new", new_patch=None,
          confirmed=False, gear=None) -> dict:
    with P._lock:
        if P.status().get("state") in ("render", "train", "test", "install", "cancelling"):
            return {"ok": False, "error": "A capture is already running"}
        if _setup.get("state") == "running":
            return {"ok": False, "error": "Capture tools are still being installed"}
        c = check(block, plugin)
        if not c["ok"]:
            return {"ok": False, "error": c["why"]}
        if not c.get("recipe") and (not confirmed or gear not in ("amp", "amp-cab")):
            return {"ok": False, "error": "Check the plugin and say whether its cab is in the sound"}
        if dest not in ("new", "replace"):
            return {"ok": False, "error": "Unknown capture destination"}
        recipe = P.recipe_for(plugin) or P.generic_recipe(plugin, gear)
        try:
            capture_plan = plan(spec, c["controls"], recipe)
            epochs = _integer(spec.get("epochs", 100), "Epochs", 1, 2000)
            state = P._live_state(block)
        except (ValueError, RuntimeError) as e:
            return {"ok": False, "error": str(e)}
        name = str(name or f"{patch} — controls").strip()[:80]
        signature = hashlib.sha256(json.dumps([plugin, state, capture_plan, recipe], sort_keys=True).encode()).hexdigest()[:20]
        work = home().parent / "captures" / f"{P._slug(name)}-parametric-{signature}"
        P._cancel.clear()
        P._job.clear()
        P._set(state="render", msg="Capturing the selected controls…", block=block, plugin=plugin,
               patch=patch, name=name, mode="parametric", dest=dest, new_patch=str(new_patch or f"{patch} — controls")[:80],
               started=time.time(), work=str(work), result=None, error=None, progress={"done": 0, "total": len(capture_plan["points"])},
               captured_params={p["name"]: p.get("display") for p in c["controls"]})
    threading.Thread(target=_worker, args=(block, plugin, name, work, capture_plan, recipe, state, epochs), daemon=True).start()
    return {"ok": True, "job": P.status()}


def _save(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def acquire(work: Path, plugin: str, state: dict, recipe: dict, capture_plan: dict) -> dict:
    """Rend chaque réglage dans un REAPER de banc et journalise les sorties complètes pour la reprise."""
    work.mkdir(parents=True, exist_ok=True)
    _save(work / "plan.json", capture_plan)
    _save(work / "state.json", state)
    data = {"type": "parametric", "common": {"delay": 0}, "train": [], "validation": []}
    # Signaux ET positions distincts pour la validation : elle mesure la généralisation.
    source = P.train_home() / "v3_0_0.wav"
    if hashlib.md5(source.read_bytes()).hexdigest() != P.V3_MD5:
        raise RuntimeError("The NAM v3 training signal checksum does not match; reinstall the capture signal")
    signal, rate = P.read_wav(source)
    if rate != P.SR or len(signal) < 90 * rate:
        raise RuntimeError("The standard NAM v3 signal at 48 kHz is required")
    for split, start, stop in (("train", 10, 48), ("validation", 70, 79)):
        P.write_wav(work / f"input-{split}.wav", signal[start * rate:stop * rate], rate)
    for n, point in enumerate(capture_plan["points"]):
        P._check_cancel()
        pw = work / point["id"]
        pw.mkdir(exist_ok=True)
        controls = [{"i": k["i"], "name": k["name"], "value": point["values"][k["name"]]} for k in capture_plan["controls"]]
        receipt = pw / "render.json"
        expected = {str(p["i"]): p["value"] for p in controls}
        valid = False
        if receipt.is_file() and (pw / "target.wav").is_file():
            try:
                previous = json.loads(receipt.read_text(encoding="utf-8"))
                valid = previous.get("requested") == expected and previous.get("sha256") == hashlib.sha256((pw / "target.wav").read_bytes()).hexdigest()
            except (ValueError, OSError):
                pass
        if not valid:
            P._set(state="render", msg=f"Capturing controls {n + 1}/{len(capture_plan['points'])} ({point['split']})…",
                   progress={"done": n, "total": len(capture_plan["points"])})
            r = P.render(plugin, state["chunk"], recipe["full"]["off"], work / f"input-{point['split']}.wav",
                         pw, "target", controls=controls)
            actual = {str(i): v for i, v in r.get("controls", {}).items()}
            if set(actual) != set(expected) or any(abs(actual[i] - v) > 1e-6 for i, v in expected.items()):
                raise RuntimeError("The plugin did not keep the requested control values")
            y, sr = P.read_wav(pw / "target.wav")
            duration = 38 if point["split"] == "train" else 9
            if sr != P.SR or len(y) != duration * P.SR or not all(math.isfinite(v) for v in y):
                raise RuntimeError("Invalid or incomplete capture audio")
            peak = max((abs(v) for v in y), default=0)
            if peak < 1e-3:
                raise RuntimeError("A control setting rendered silence; raise its minimum or keep that control fixed")
            if peak > 10:
                raise RuntimeError("A control setting is too hot; lower the plugin output or restrict the control range")
            # Aucun nivellement par position : le réseau doit apprendre les différences de niveau.
            _save(receipt, {"requested": expected, "actual": actual, "set": r.get("set"), "peak": peak,
                            "sha256": hashlib.sha256((pw / "target.wav").read_bytes()).hexdigest()})
        data[point["split"]].append({"x_path": str((work / f"input-{point['split']}.wav").resolve()),
                                     "y_path": str((pw / "target.wav").resolve()), "params": point["values"],
                                     "ny": 8192})
        _save(work / "data.json", data)
        P._set(progress={"done": n + 1, "total": len(capture_plan["points"])})
    return data


def model_config(controls: list) -> dict:
    # Le WaveNet classique est volontaire : chaque réglage peut se convertir sans approximation
    # au schéma 0.5.4 lu par le NAM VST3 déjà utilisé sur les postes Windows et macOS.
    layers = []
    for inp, channels, head, bias in ((1, 16, 8, False), (16, 8, 1, True)):
        layers.append({"input_size": inp, "condition_size": 1, "channels": channels, "kernel_size": 3,
                       "dilations": [2 ** i for i in range(10)], "activation": "Tanh", "gated": False,
                       "head": {"out_channels": head, "kernel_size": 1, "bias": bias}})
    specs = [{"name": k["name"], "min": k["min"], "max": k["max"], "default": k["default"], "type": "continuous"} for k in controls]
    return {"net": {"name": "HyperWaveNet", "config": {"layers": layers, "head_scale": 0.02,
             "sample_rate": P.SR, "params": specs,
             "hypernet": {"hidden_sizes": [16], "activation": "Tanh", "selector": {"exclude_suffixes": ["_conv.weight"]}}}},
            "loss": {"val_loss": "esr"}, "optimizer": {"lr": 0.002},
            "lr_scheduler": {"class": "ExponentialLR", "kwargs": {"gamma": 0.994}}}


def _worker(block, plugin, name, work, capture_plan, recipe, state, epochs):
    try:
        acquire(work, plugin, state, recipe, capture_plan)
        _save(work / "model.json", model_config(capture_plan["controls"]))
        P._check_cancel()
        P._set(state="train", msg="Training control interactions; validating on unseen settings…")
        r = P._run([python(), WORKER, "train", work, epochs], low_priority=True)
        (work / "train.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode:
            raise RuntimeError("Parametric training failed; see " + str(work / "train.log"))
        metrics = json.loads((work / "metrics.json").read_text(encoding="utf-8"))
        if not math.isfinite(metrics["worst_esr"]):
            raise RuntimeError("The parametric model produced non-finite validation output")
        P._set(state="test", msg="Checking the default setting in this computer's NAM…", test=metrics)
        P.legacy_nam(work / "output" / "model.nam", work / "capture.nam")
        pc = P.playback_check(work / "capture.nam", work / "playcheck", reference=work / "output" / "model.nam", python_exe=python())
        _save(work / "playback.json", pc)
        if not pc.get("ok"):
            raise RuntimeError("The default setting does not play correctly in NAM")
        P._check_cancel()
        P._set(state="install", msg="Adding the model and its controls to your library…")
        core = install(work, capture_plan, recipe, plugin, block, name, metrics)
        _save(work / "done.json", {"core": core, "validation": metrics})
        P._set(state="done", msg="Control capture ready", train={"parametric": {"validation_esr": metrics["worst_esr"]}},
               warning=("Some unseen settings have ESR above 0.1. Narrow the ranges or add captures before relying on this model."
                        if metrics["worst_esr"] > 0.1 else None),
               result={"name": name, "mode": "parametric", "core": core, "validation": metrics,
                       "controls": capture_plan["controls"]})
    except Exception as e:
        if P._cancel.is_set():
            P._set(state="cancelled", msg="Control capture cancelled", error=None)
        else:
            P.log.warning(f"capture paramétrique échouée : {e}")
            P._set(state="error", msg=str(e), error=str(e))


def install(work: Path, capture_plan: dict, recipe: dict, plugin: str, block: str, name: str, metrics: dict) -> list:
    import shutil
    block_type = {"amp-cab": "amp", "amp": "amp-nam", "pedal": "pedal-nam"}.get(recipe["full"]["gear"])
    if block_type is None:
        raise ValueError("Unsupported parametric capture gear")
    digest = hashlib.sha256((work / "output" / "model_parametric.nam").read_bytes()).hexdigest()[:12]
    slug = f"{P._slug(name)[:40]}-{digest}"
    rel_folder = Path("assets") / "models" / "captures" / slug
    folder = P.ROOT / rel_folder
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(work / "output" / "model_parametric.nam", folder / "parametric.nam.tmp")
    (folder / "parametric.nam.tmp").replace(folder / "parametric.nam")
    parametric = {"file": (rel_folder / "parametric.nam").as_posix(), "controls": capture_plan["controls"],
                  "capture_settings": recipe["full"].get("off", {}),
                  "trainer_revision": TRAINER_REV, "validation": metrics,
                  "reference_loudness": (json.loads((work / "capture.nam").read_text(encoding="utf-8")).get("metadata") or {}).get("loudness")}
    P._check_cancel()
    entry = P.install(work / "capture.nam", {"name": name, "slug": slug,
                      "gear": recipe["full"]["gear"], "vendor": recipe.get("vendor"),
                      "plugin": plugin, "patch": P.status().get("patch"), "block": block, "mode": "parametric",
                      "part": "full", "test": metrics, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "private": True,
                      "parametric": parametric, "controls": {k["name"]: k["default"] for k in capture_plan["controls"]}})
    # La sortie jouable est maintenant le modèle vivant ; le snapshot reste disponible à l'export.
    from . import capture_module as CM
    source = json.loads((folder / "parametric.nam").read_text(encoding="utf-8"))
    bundle = CM.build(name, [{"id": "full", "name": name, "model": source}])
    bundle["gear"] = recipe["full"]["gear"]
    _save(folder / "module.gcap", bundle)
    entry["capture_module"] = {"format": CM.FORMAT, "controls": CM.validate(bundle), "excluded": []}
    entry["models"].insert(0, {"id": entry["id"] + "-live", "name": "Live controls", "arch": "parametric",
                               "file": (rel_folder / "module.gcap").as_posix(),
                               "controls": {k["name"]: k["default"] for k in capture_plan["controls"]}})
    from .store import _read_json, _write_json_atomic
    cat = _read_json(P.C.CATALOG, {"tones": []})
    cat["tones"] = [entry if str(t.get("id")) == str(entry["id"]) else t for t in cat.get("tones", [])]
    _write_json_atomic(P.C.CATALOG, cat)
    return [{"type": block_type, "ref": entry["id"],
             "model": entry["models"][0]["id"], "label": name,
             "origin": {"kind": "vst-capture", "plugin": plugin, "patch": P.status().get("patch"),
                        "mode": "parametric", "part": "full", "at": time.strftime("%Y-%m-%d")}}]


def _entry(ref: str) -> dict:
    from .store import _read_json
    cat = _read_json(P.C.CATALOG, {"tones": []})
    entry = next((t for t in cat.get("tones", []) if str(t.get("id")) == str(ref)), None)
    if not entry or not entry.get("parametric"):
        raise ValueError("No parametric model for this capture")
    return entry


def model_status(ref: str, model=None) -> dict:
    entry = _entry(ref)
    chosen = next((m for m in entry["models"] if m.get("id") == model), entry["models"][0])
    env = environment()
    return {"controls": entry["parametric"]["controls"], "values": chosen.get("controls", {}),
            "ready": env.get("trainer_ready", env["ready"]), "validation": entry["parametric"]["validation"]}


def model_file(ref: str) -> Path:
    from .resolver import _asset_path
    path = _asset_path(_entry(ref)["parametric"]["file"])
    if not path or not Path(path).is_file():
        raise ValueError("Parametric model file is missing")
    return Path(path)


def bake(ref: str, values: dict) -> dict:
    """Un réglage continu -> NAM fixe compatible, avant de remplacer le modèle du bloc."""
    from .store import _read_json, _write_json_atomic
    if not isinstance(values, dict):
        raise ValueError("Control values must be an object")
    with _bake_lock:
        entry = _entry(ref)
        controls = entry["parametric"]["controls"]
        if set(values) != {k["name"] for k in controls}:
            raise ValueError("Provide every captured control, and no extra controls")
        coords = {k["name"]: _number(values[k["name"]], k["name"]) for k in controls}
        if any(not k["min"] <= coords[k["name"]] <= k["max"] for k in controls):
            raise ValueError("Stay inside the captured control ranges")
        src = model_file(ref)
        digest = hashlib.sha256(src.read_bytes() + json.dumps(coords, sort_keys=True).encode()).hexdigest()[:24]
        mid = f"{entry['id']}-knobs-{digest}"
        existing = next((m for m in entry["models"] if m["id"] == mid), None)
        if existing and (P.ROOT / existing["file"]).is_file():
            return {"ok": True, "model": mid, "values": coords}
        env = environment()
        if not env.get("trainer_ready", env["ready"]):
            raise ValueError("Install the parametric capture tools on this computer to change its controls")
        folder = src.parent / "knobs" / digest
        folder.mkdir(parents=True, exist_ok=True)
        _save(folder / "values.json", coords)
        r = subprocess.run([str(python()), str(WORKER), "bake", str(src), str(folder / "values.json"), str(folder)],
                           capture_output=True, text=True, timeout=120, creationflags=P.NO_WINDOW)
        if r.returncode:
            (folder / "bake.log").write_text(r.stdout + r.stderr, encoding="utf-8")
            raise RuntimeError("Could not prepare this control setting; see " + str(folder / "bake.log"))
        snapshot = P.legacy_nam(folder / "model.nam", folder / "snapshot.nam")
        # La compile normalise les amplis via metadata.loudness. Tous les réglages doivent
        # garder la MÊME référence, sinon elle annulerait les changements du potard Volume.
        metadata = snapshot.setdefault("metadata", {})
        loudness = entry["parametric"].get("reference_loudness")
        if loudness is None:
            metadata.pop("loudness", None)
        else:
            metadata["loudness"] = loudness
        _save(folder / "snapshot.nam", snapshot)
        model = {"id": mid, "name": ", ".join(f"{k} {v * 100:.1f}%" for k, v in coords.items()),
                 "file": (folder / "snapshot.nam").relative_to(P.ROOT).as_posix(), "size": "standard", "arch": "1", "controls": coords}
        # Relire après le sous-processus : un autre téléchargement peut avoir enrichi le catalogue.
        cat = _read_json(P.C.CATALOG, {"tones": []})
        current = next((t for t in cat["tones"] if str(t.get("id")) == str(ref)), None)
        if current is None:
            raise ValueError("The capture was removed while preparing its controls")
        current["models"] = [m for m in current["models"] if m["id"] != mid] + [model]
        _write_json_atomic(P.C.CATALOG, cat)
        return {"ok": True, "model": mid, "values": coords}
