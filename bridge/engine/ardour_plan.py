# SPDX-License-Identifier: GPL-3.0-or-later
"""Le plan MOTEUR du Golem Engine (docs/ardour-plan.md §7b, lot A2.0) : le plan compilé `<id>.rig.json` (le même que
REAPER lit) + le catalogue + la table library/catalog/effects-golem-engine.json -> ce que le veilleur Lua exécute
sans rien résoudre lui-même (presets/.engine-plan.json). Pur : aucun moteur, testé en CI.

Topologie, depuis les rôles du plan :
  - `main` / `pre` : une PISTE audio, entrée `input` de la carte (system:capture_N) ;
  - `branch` : un BUS alimenté par la piste `pre` qui l'envoie (`sends_to`), sortie vers son `merge` ;
  - `merge` : un BUS alimenté par ses branches (`folder_of`), sortie `out_sel` ; `merge_gain` = son gain ;
  - une lane MIDI (`midi`) : une PISTE MIDI (kind `midi`), son clavier = le nom court de la carte ALSA que le compileur a
    choisie (`midi_in` « hw:II » -> « MPK Mini Mk II », /proc/asound/cards), son canal = `midi_ch[midi_role]` ;
    l'instrument est son premier bloc (piano = sfizz). Le veilleur n'ouvre QUE ce clavier (jamais la prise DIN).
  Le dossier de REAPER n'existe pas ici : les liens sont des connexions de ports, posées par le veilleur.
Paramètres, la règle de golem_rig.lua (apply_params) : la valeur du bloc dans l'unité du catalogue, bornée par
min/max, × `map.scale` ; en mode `raw` c'est la valeur du port, en mode `norm` c'est la valeur AFFICHÉE visée —
pour un LV2 ou un DSP Lua d'Ardour, affichée = brute. Une option d'énumération vise sa `values[i]` si elle existe,
sinon son rang (raw) ou son rang normalisé (norm, converti par le veilleur avec les bornes du port). `pct_db` et
`pow` décrivent des plugins REAPER / golem-fx : refusés ici, avec la raison.
"""
import json
import os
import re

from .. import config as C

TABLE = os.path.join(C.ROOT, "library", "catalog", "effects-golem-engine.json")
CATALOG = os.path.join(C.ROOT, "library", "catalog", "effects.json")
NOT_HERE = "not on the Golem Engine yet"


def load_table(path=None):
    with open(path or TABLE, encoding="utf-8") as f:
        return (json.load(f) or {}).get("effects") or {}


def load_catalog(path=None):
    with open(path or CATALOG, encoding="utf-8") as f:
        return {e["type"]: e for e in (json.load(f) or {}).get("effects") or [] if e.get("type")}


def out_ports(out_sel):
    """'1-2' -> [1, 2] ; '2' -> [2] ; rien -> [1, 2] (le défaut de golem_rig.route_monitor)."""
    s = str(out_sel or "").strip()
    if "-" in s:
        a, b = s.split("-", 1)
        if a.isdigit() and b.isdigit():
            return [int(a), int(b)]
    if s.isdigit():
        return [int(s)]
    return [1, 2]


CARDS = "/proc/asound/cards"


def midi_device(midi_in, cards_text=None):
    """« hw:II » -> « MPK Mini Mk II » : le nom court de la carte ALSA, celui que le séquenceur donne au clavier (le
    veilleur l'ouvre par préfixe). None si la carte n'est pas là (clavier débranché) ou si `midi_in` n'est pas « hw:… »."""
    m = str(midi_in or "")
    if not m.startswith("hw:"):
        return None
    cid = m[3:].split(",")[0]
    if cards_text is None:
        try:
            with open(CARDS, encoding="utf-8") as f:
                cards_text = f.read()
        except OSError:
            return None
    for line in cards_text.splitlines():
        mm = re.match(r"\s*(\d+)\s+\[(.+?)\s*\]:\s*\S+\s+-\s+(.+)$", line)
        if mm and (mm.group(2) == cid or mm.group(1) == cid):
            return mm.group(3).strip()
    return None


def param_entry(defn, value):
    """(entrée {pid, label, value|norm}, raison du refus)."""
    mp = defn.get("map") or {}
    mode = mp.get("mode") or "norm"
    if mp.get("curve") or mode == "pow":
        return None, f"mode {mp.get('curve') or mode} is not available on this engine"
    out = {"pid": defn["id"], "label": defn.get("name") or defn["id"]}
    kind = defn.get("type")
    if kind == "enum" and defn.get("dynamic") and not defn.get("options"):
        return None, "content resolved by the compiler, no port carries it"   # le .sfz du piano, la banque DX7…
    if kind == "enum":
        opts = defn.get("options") or []
        idx = opts.index(value) if value in opts else 0
        vals = defn.get("values")
        if vals and idx < len(vals):
            out["value"] = vals[idx]
        elif mode == "raw":
            out["value"] = idx
        else:
            out["norm"] = idx / max(1, len(opts) - 1)
        return out, None
    if kind == "bool":
        b = 1 if value and value != 0 else 0
        out["value" if mode == "raw" else "norm"] = b
        return out, None
    if kind in ("kitref", "midilist"):
        return None, "content resolved by the compiler, no port carries it"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, "value is not a number"
    lo, hi = defn.get("min"), defn.get("max")
    if lo is not None and v < float(lo):
        v = float(lo)
    if hi is not None and v > float(hi):
        v = float(hi)
    if mp.get("scale") is not None:
        v *= float(mp["scale"])
    out["value"] = v
    return out, None


def plugin_of(spec):
    """Le plugin d'une entrée de la table : LV2 (URI), VST3 (identifiant de classe, lu par le scanner d'Ardour) ou DSP
    Lua d'Ardour (nom). Un drum kit = son moteur (avldrums), le traducteur venant avec le moteur."""
    if spec.get("lv2"):
        return {"lv2": spec["lv2"]}
    if spec.get("vst3"):
        return {"vst3": spec["vst3"]}
    if spec.get("avldrums"):
        return {"lv2": next(iter(spec["avldrums"].values()))}
    return {"lua": spec.get("lua")}


def plan_drumkit(b, spec):
    """Un bloc Drum Kit = DEUX blocs moteur, comme golem_rig le pose sous REAPER : le traducteur (module -> kit,
    charleston ; toujours actif, il porte la table) puis le kit avldrums de la banque. Le kit, lui, suit le bypass."""
    bank, eng = b.get("kit_bank"), b.get("kit_engine")
    uri = (spec.get("avldrums") or {}).get(bank) if eng == "avldrums" else None
    if not uri:
        return [], [{"id": b.get("id"), "type": "drumkit", "why": f"kit engine {eng or '?'} ({bank or b.get('kit_id')}) "
                                                                   f"is {NOT_HERE}"}]
    trans = {"id": f"{b.get('id')}~trans", "type": "drumtrans", "plugin": {"lua": spec["translator"]}, "files": {},
             "enabled": True, "params": [], "known": [],
             "drumtrans": {"map": list(b.get("drum_map") or [-1] * 128)[:128], "hh": b.get("drum_hh") or {},
                           "chan": b.get("drum_chan") or 10}}
    kit = {"id": b.get("id"), "type": "drumkit", "plugin": {"lv2": uri}, "files": {}, "enabled": not b.get("bypass"),
           "params": [], "known": []}
    if b.get("foot") is not None:
        kit["foot"] = b["foot"]
    return [trans, kit], []


def plan_block(b, catalog, table):
    """(bloc moteur, [refus]) ; (None, [raison]) si le type ne joue pas sur ce moteur."""
    t = b.get("type")
    spec = table.get(t)
    if not spec:
        return None, [{"id": b.get("id"), "type": t, "why": NOT_HERE}]
    plugin = plugin_of(spec)
    defs = {p["id"]: p for p in (catalog.get(t) or {}).get("params") or [] if p.get("id")}
    labels = spec.get("params") or {}
    files = {}
    for key, prop in (spec.get("files") or {}).items():
        if b.get(key):
            files[prop] = b[key]
    skipped, params, known = [], [], []
    for pid, d in defs.items():
        known.append({"pid": pid, "label": labels.get(pid) or d.get("name") or pid})
    absent = spec.get("absent") or {}
    for pid, value in (b.get("params") or {}).items():
        if pid.startswith("_"):
            continue                                   # métadonnées du compileur (_loud…)
        if pid in absent:
            skipped.append({"id": b.get("id"), "param": pid, "why": absent[pid]})
            continue
        d = defs.get(pid)
        if not d:
            skipped.append({"id": b.get("id"), "param": pid, "why": "unknown parameter"})
            continue
        e, why = param_entry(dict(d, name=labels.get(pid) or d.get("name")), value)
        if e is None:
            skipped.append({"id": b.get("id"), "param": pid, "why": why})
        else:
            params.append(e)
    blk = {"id": b.get("id"), "type": t, "plugin": plugin, "files": files, "enabled": not b.get("bypass"),
           "params": params, "known": known}
    if spec.get("init"):                                # posés UNE fois à l'ajout (golem_rig FX_INIT), avant les potards
        blk["init"] = [{"pid": f"init:{k}", "label": k, "value": v} for k, v in spec["init"].items()]
    if spec.get("loaded_output"):
        blk["loaded_output"] = spec["loaded_output"]   # témoin de chargement quand le plugin ne renvoie pas son fichier
    if b.get("foot") is not None:
        blk["foot"] = b["foot"]
    return blk, skipped


def build(rig, catalog=None, table=None, cards_text=None):
    """Le plan moteur d'un plan compilé."""
    catalog = load_catalog() if catalog is None else catalog
    table = load_table() if table is None else table
    tracks, skipped = [], []
    for path in rig.get("paths") or []:
        specs = path.get("tracks") or []
        feeds = {}                                      # nom -> [sources]
        for s in specs:
            for dst in s.get("sends_to") or []:
                feeds.setdefault(dst, []).append(s["name"])
            if s.get("folder") == "child" and s.get("folder_of"):
                feeds.setdefault(s["folder_of"], []).append(s["name"])
        for s in specs:
            role = s.get("role")
            blocks = []
            for b in s.get("blocks") or []:
                if b.get("type") == "drumkit" and "drumkit" in table:
                    two, sk = plan_drumkit(b, table["drumkit"])
                    skipped += sk
                    blocks += two
                    continue
                blk, sk = plan_block(b, catalog, table)
                skipped += sk
                if blk:
                    blocks.append(blk)
            midi = bool(s.get("midi")) and role in ("main", "pre")
            tr = {"name": s["name"], "role": role, "kind": "midi" if midi else ("track" if role in ("main", "pre") else "bus"),
                  "input": s.get("input") if role in ("main", "pre") and not midi else None,
                  "from": feeds.get(s["name"], []), "mute": bool(s.get("mute")), "blocks": blocks}
            if midi:
                ch = (s.get("midi_ch") or {}).get(s.get("midi_role") or "keys")
                dev = midi_device(s.get("midi_in"), cards_text)
                tr["midi"] = {"device": dev, "hw": s.get("midi_in"), "channel": int(ch) if ch else None}
                if not dev:
                    skipped.append({"path": path.get("id"), "why": f"no MIDI device plugged for {s.get('midi_in') or 'this lane'}"})
            gain = s.get("merge_gain") if role == "merge" else s.get("level")
            tr["gain_db"] = float(gain) if gain is not None else 0.0
            if role in ("main", "merge"):
                tr["out"] = out_ports(s.get("out_sel"))
            else:
                tr["out"] = None                        # pre -> ses branches, branch -> son merge (par `from`)
            tracks.append(tr)
    return {"preset": rig.get("id"), "tracks": tracks, "skipped": skipped}


def rig_path(preset_id):
    from ..compile_rig import OUT_DIR, file_stem
    return os.path.join(OUT_DIR, f"{file_stem(preset_id)}.rig.json")


def write_plan(preset_id, out_path):
    """Lit le plan compilé du preset, écrit le plan moteur (atomique). Rend le plan."""
    with open(rig_path(preset_id), encoding="utf-8") as f:
        plan = build(json.load(f))
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False)
    os.replace(tmp, out_path)
    return plan
