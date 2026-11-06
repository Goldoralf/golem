# SPDX-License-Identifier: GPL-3.0-or-later
"""Paquet autonome et contrôles du lecteur golem Capture (aucun import du trainer)."""
import base64
import copy
import hashlib
import json
import math
from pathlib import Path
import re

from . import config as C

FORMAT = "golem-capture-1"
MAX_CONTROLS = 32
_cache = {}


def validate(bundle):
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise ValueError("Not a golem capture module")
    controls, stages = bundle.get("controls"), bundle.get("stages")
    if not isinstance(controls, list) or not 1 <= len(controls) <= MAX_CONTROLS:
        raise ValueError("A capture needs 1 to 32 controls")
    ids = {}
    for slot, c in enumerate(controls):
        if not isinstance(c, dict) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", str(c.get("id", ""))) or c["id"] in ids:
            raise ValueError("Invalid or duplicate capture control id")
        if not isinstance(c.get("name"), str) or not c["name"] or c.get("kind", "knob") not in ("knob", "toggle"):
            raise ValueError("Invalid capture control")
        lo, hi, v = c.get("min", 0), c.get("max", 1), c.get("default")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (lo, hi, v)) or not lo <= v <= hi or lo >= hi:
            raise ValueError("Invalid capture control range")
        if c.get("kind") == "toggle" and (lo, hi, v) not in ((0, 1, 0), (0, 1, 1)):
            raise ValueError("Capture switches use 0 or 1")
        ids[c["id"]] = {**c, "slot": slot, "min": lo, "max": hi}
    if not isinstance(stages, list) or not 1 <= len(stages) <= 8:
        raise ValueError("A capture needs 1 to 8 stages")
    used = set()
    for stage in stages:
        model = stage.get("model") or {}
        if model.get("architecture") not in ("HyperWaveNet", "WaveNet") or model.get("sample_rate") != 48000:
            raise ValueError("Capture stages need 48 kHz WaveNet models")
        weights = model.get("weights")
        if not isinstance(weights, list) or not 1 <= len(weights) <= 2_000_000 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in weights):
            raise ValueError("Invalid capture weights")
        specs = (model.get("config") or {}).get("params", []) if model["architecture"] == "HyperWaveNet" else []
        targets = stage.get("controls")
        if not isinstance(targets, list) or len(targets) != len(specs) or len(set(targets)) != len(targets):
            raise ValueError("Stage controls do not match the NAM parameters")
        for target, spec in zip(targets, specs):
            ctl = ids.get(target)
            if not ctl or ctl.get("kind", "knob") != "knob" or ctl["min"] < spec["min"] - 1e-6 or ctl["max"] > spec["max"] + 1e-6:
                raise ValueError("Capture controls exceed the trained range")
            used.add(target)
        if "enable" in stage:
            ctl = ids.get(stage["enable"])
            if not ctl or ctl.get("kind") != "toggle":
                raise ValueError("Stage enable must be a captured switch")
            used.add(stage["enable"])
    if used != set(ids):
        raise ValueError("Every capture control must reach a stage")
    return list(ids.values())


def load(path):
    path = Path(path)
    stat = path.stat()
    if stat.st_size > 32 * 1024 * 1024:
        raise ValueError("Capture module exceeds 32 MiB")
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _cache:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        controls = validate(bundle)
        if len(_cache) > 32:
            _cache.clear()
        _cache[key] = (bundle, controls)
    return _cache[key]


def entry_controls(block):
    from .resolver import _resolve
    path = _resolve(block.get("ref"), {}, block.get("model")) if block.get("ref") else None
    if not path or Path(path).suffix.lower() != ".gcap":
        return []
    return load(path)[1]


def hydrate(preset):
    """Les descripteurs dérivés voyagent avec le document ; preset_view reste pur et partageable."""
    from . import store
    for block, _ in store.all_blocks(preset):
        candidate = (str(block.get("ref", "")).startswith("cap-module-") or block.get("capture_controls")
                     or (block.get("origin") or {}).get("mode") == "parametric")
        if candidate and block.get("ref") and block.get("type") in ("amp", "amp-nam", "pedal-nam"):
            controls = entry_controls(block)
            if controls:
                block["capture_controls"] = controls
            else:
                block.pop("capture_controls", None)
    return preset


def prepare(block):
    """Transforme seulement le PLAN audio : le preset conserve un unique bloc à capture."""
    path = block.get("file")
    if not path or Path(path).suffix.lower() != ".gcap":
        return
    bundle, controls = load(path)
    values = block.get("params") or {}
    normalized = []
    for c in controls:
        v = values.get(c["id"], c["default"])
        if isinstance(v, bool) and c.get("kind") == "toggle":
            v = int(v)
        if not isinstance(v, (int, float)) or not math.isfinite(v) or not c["min"] <= v <= c["max"]:
            raise ValueError(f"Stay inside the captured range of {c['name']}")
        if c.get("kind") == "toggle" and v not in (0, 1):
            raise ValueError("A capture switch must be 0 or 1")
        normalized.append((v - c["min"]) / (c["max"] - c["min"]))
    block["type"] = "capture-module"
    block["capture_controls"] = controls
    block["capture_values"] = normalized
    # L'état initial est stocké à côté du plan ; les scènes n'envoient que les potards.
    data = json.dumps({"bundle": bundle}, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(data).hexdigest()
    folder = Path(C.ROOT) / "assets" / ".cache" / "capture-modules"
    folder.mkdir(parents=True, exist_ok=True)
    chunk = folder / (digest + ".b64")
    if not chunk.is_file():
        tmp = chunk.with_suffix(".tmp")
        tmp.write_bytes(base64.b64encode(data)); tmp.replace(chunk)
    block["capture_chunk"] = chunk.as_posix()
    block["params"] = {"_capture_chunk": chunk.as_posix(), "_capture_values": normalized}
    block.pop("file", None)


def build(name, components, *, excluded=()):
    """Assemble les vrais modèles appris en un fichier, jamais les états du VST source."""
    controls, stages = [], []
    for component in components:
        prefix = component["id"]
        model = copy.deepcopy(component["model"])
        targets = []
        enable = component.get("switch")
        if enable:
            controls.append({"id": prefix + "_on", "name": enable, "kind": "toggle", "min": 0, "max": 1,
                             "default": int(component.get("enabled", False)), "group": component["name"]})
        for spec in (model.get("config") or {}).get("params", []):
            cid = prefix + "_" + re.sub(r"[^a-z0-9]+", "_", spec["name"].lower()).strip("_")
            targets.append(cid)
            controls.append({"id": cid, "name": spec["name"], "min": spec["min"], "max": spec["max"],
                             "default": spec["default"], "group": component["name"], "kind": "knob"})
        stage = {"name": component["name"], "model": model, "controls": targets}
        if enable:
            stage["enable"] = prefix + "_on"
        stages.append(stage)
    bundle = {"format": FORMAT, "name": name, "controls": controls, "stages": stages,
              "excluded": list(excluded), "requires_original_plugin": False}
    validate(bundle)
    return bundle


def install(bundle):
    """Installe un paquet de données, sans code exécutable fourni par son auteur."""
    from .store import _read_json, _write_json_atomic
    controls = validate(bundle)
    raw = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("Capture module exceeds 32 MiB")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    ref = "cap-module-" + digest
    rel = "assets/models/captures/" + ref + "/module.gcap"
    path = Path(C.ROOT) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw); tmp.replace(path)
    entry = {"id": ref, "title": bundle.get("name") or "Captured plugin", "amp": bundle.get("name"), "gear": bundle.get("gear", "amp-cab"),
             "models": [{"id": ref, "name": "Live controls", "file": rel, "arch": "parametric"}],
             "capture_module": {"controls": controls, "excluded": bundle.get("excluded", []), "format": FORMAT},
             "source": "capture", "private": True}
    cat = _read_json(C.CATALOG, {"tones": []})
    cat["tones"] = [t for t in cat.get("tones", []) if t.get("id") != ref] + [entry]
    _write_json_atomic(C.CATALOG, cat)
    return entry


def owned(preset, scene, role=None, person=None, imap=None, stomps=None, toggles=None):
    """Contrôles de MES lanes : même garde d'identité que les bascules du Companion."""
    from . import lane_stomps as LS, store
    sc = LS._scene(preset, scene)
    out = []
    for lane in store.lanes_of(preset) if preset else []:
        if not LS._owns(lane, role, person, imap):
            continue
        for block in store._lane_chain_blocks(lane.get("chain") or {}):
            controls = entry_controls(block)
            if not controls:
                continue
            values = {c["id"]: LS._pval(block, sc, c["id"]) if LS._pval(block, sc, c["id"]) is not None else c["default"] for c in controls}
            for c in controls:
                sw = (block.get("capture_foot") or {}).get(c["id"])
                virtual = block["id"] + "@capture" + str(c["slot"])
                live = LS.toggle_of(toggles, preset["id"], sc.get("id"), virtual)
                if c.get("kind") == "toggle":
                    if live is not None:
                        values[c["id"]] = int(live)
                    elif sw in (stomps or {}):
                        values[c["id"]] = int(bool(stomps[sw]))
            out.append({"block": block["id"], "name": block.get("label") or "Captured plugin", "lane": lane["id"],
                        "controls": controls, "values": values, "foot": block.get("capture_foot") or {}})
    return out


def note_stomp(toggles, ids, on, preset, scene):
    """Une cible capturée garde son état propre, même si elle partage son switch avec une autre lane."""
    out = dict(toggles or {})
    for bid in ids:
        if re.fullmatch(r".+@capture\d+", str(bid)):
            out[bid] = {"on": bool(on), "preset": preset, "scene": scene}
    return out


def write_values(preset, scene, row, values):
    """Valide des valeurs, mémorise la scène, rend les écritures normalisées pour le lecteur."""
    from . import store, sandbox_edit
    if not isinstance(values, dict) or not values:
        raise ValueError("Provide capture control values")
    controls = {c["id"]: c for c in row["controls"]}
    normalized = {}
    for key, v in values.items():
        c = controls.get(key)
        if not c or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not c["min"] <= v <= c["max"]:
            raise ValueError("Stay inside the captured control ranges")
        if c.get("kind") == "toggle" and v not in (0, 1):
            raise ValueError("A capture switch must be 0 or 1")
        normalized[str(c["slot"])] = (v - c["min"]) / (c["max"] - c["min"])

    def put(doc):
        target = next((s for s in doc.get("scenes", []) if s.get("id") == scene), None)
        if not target:
            raise ValueError("The active scene no longer exists")
        if len(doc.get("scenes") or []) == 1:
            block = next((b for b, _ in store.all_blocks(doc) if b.get("id") == row["block"]), None)
            if block is None:
                raise ValueError("The capture block no longer exists")
            # Même règle que le Designer : une scène unique règle la base des futures scènes.
            block.setdefault("params", {}).update(values)
            overrides = (target.get("params") or {}).get(row["block"]) or {}
            for key in values:
                overrides.pop(key, None)
        else:
            target.setdefault("params", {}).setdefault(row["block"], {}).update(values)

    pid = str(preset["id"])
    put(preset)
    if pid.startswith("patch:"):
        from . import patches
        lane = next(L for L in store.lanes_of(preset) if L["id"] == row["lane"])
        patches.save_patch(pid[len("patch:"):], preset, lane["key"])
    elif pid != store.SANDBOX_TRY_ID:
        path = Path(C.PRESETS_DIR) / (store._safe_id(pid) + ".json")
        if not path.is_file():
            raise ValueError("The active preset no longer exists")
        original = store._read_json(path, None)
        if not isinstance(original, dict):
            raise ValueError("Cannot read the active preset")
        put(original)
        store._write_json_atomic(path, original)
    sandbox = Path(C.PRESETS_DIR) / ".sandbox.json"
    buf = store._read_json(sandbox, {}) or {}
    draft = buf.get("preset") or {}
    matches = (pid == store.SANDBOX_TRY_ID or draft.get("id") == pid
               or (pid.startswith("patch:") and (draft.get("__patch") or {}).get("id") == pid[len("patch:"):]))
    if matches:
        put(draft)
        meta = sandbox_edit.after_write(buf, "capture-controls", "capture controls")
        store._write_json_atomic(sandbox, {**buf, "preset": draft, **meta})
    return normalized
