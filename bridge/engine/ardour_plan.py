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
    if m.startswith("port:"):                             # un port du moteur nommé tel quel (un banc, la carte factice)
        return m
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


ZONE_PARAMS = (("zone_lo", "Zone Low", 0), ("zone_hi", "Zone High", 127), ("transpose", "Transpose", 0))


def plan_zone(b):
    """La ZONE DE CLAVIER d'un instrument (note basse, note haute, transposition) : le filtre MIDI « golem Zone » (DSP
    Lua, portage de reaper/Effects/note-zone.jsfx), posé DEVANT l'instrument, toujours actif. `shadow` : il appartient
    au bloc de l'instrument, pas au patch."""
    pm = b.get("params") or {}
    params = []
    for pid, label, dflt in ZONE_PARAMS:
        try:
            v = float(pm.get(pid, dflt))
        except (TypeError, ValueError):
            v = float(dflt)
        params.append({"pid": pid, "label": label, "value": v})
    return {"id": f"{b.get('id')}~zone", "type": "note-zone", "plugin": {"lua": "golem Zone"}, "files": {},
            "enabled": True, "params": params, "known": [], "shadow": True}


# les configurations nommées de l'arpégiateur (reaper/Scripts/golem_rig.lua, ARP_CONFIGS) : pas par temps, mode
# (0 descend, 1 monte, 3 monte puis descend), octaves en plus
ARP_CONFIGS = {"Up 1/4": (1, 1, 0), "Up 1/8": (2, 1, 0), "Down 1/8": (2, 0, 0), "Up-Down 1/8": (2, 3, 0),
               "Up 1/16": (4, 1, 0), "Down 1/16": (4, 0, 0), "Up-Down 1/16": (4, 3, 0), "Up 2 oct": (2, 1, 1)}


def plan_arp(b):
    """L'ARPÉGIATEUR d'un instrument : « golem Arp » (DSP Lua), posé entre la zone et l'instrument, TOUJOURS là —
    « Off » le rend transparent, une scène l'allume sans rebuild (sous REAPER il faut le poser, donc reconstruire).
    Son tempo (`bpm`) est posé par le veilleur depuis celui du morceau."""
    cfg = ARP_CONFIGS.get(str((b.get("params") or {}).get("arp")))
    rate, mode, octs = cfg or (2, 1, 0)
    params = [{"pid": "arp", "label": "On", "value": 1 if cfg else 0}, {"pid": "arp_rate", "label": "Rate", "value": rate},
              {"pid": "arp_mode", "label": "Mode", "value": mode}, {"pid": "arp_oct", "label": "Octaves", "value": octs},
              {"pid": "arp_len", "label": "Length", "value": 0.7}]
    return {"id": f"{b.get('id')}~arp", "type": "arp", "plugin": {"lua": "golem Arp"}, "files": {}, "enabled": True,
            "params": params, "known": [], "shadow": True, "bpm": "BPM"}


def pads_sfz(pads):
    """Le kit de pads en SFZ, pour sfizz (sous REAPER : un ReaSamplOmatic5000 par pad). (texte, refus)
    `oneshot` : le sample va au bout ; `gate` : il s'arrête au relâché ; `toggle` (un coup lance, le suivant arrête)
    n'existe pas en SFZ : joué en oneshot, et dit."""
    lines, skipped = ["// golem pads kit — written by golem for the Golem Engine", "<group> ampeg_release=0.03"], []
    for pad in pads or []:
        mode = pad.get("mode") or "gate"
        opts = f"sample={pad['file']} key={int(pad['note'])} volume={float(pad.get('level') or 0):g}"
        if mode in ("oneshot", "toggle"):
            opts += " loop_mode=one_shot"
        if mode == "toggle":
            skipped.append(f"pad {pad['note']}: toggle plays as a one-shot on this engine")
        lines.append("<region> " + opts)
    return "\n".join(lines) + "\n", skipped


def table_def(spec, d):
    """La définition catalogue d'un paramètre TELLE QUE le plugin de la table la reçoit : son nom (`params` de la table),
    et pour un paramètre RENOMMÉ l'unité du catalogue — la règle de golem_rig pour les tables d'OS, étendue : ni
    l'échelle (gfx-limiter : la release en ms, l'x42 en secondes), ni la courbe de REAPER (gfx-delay : feedback et mix
    en % bruts, pas le pct_db de ReaDelay), et une énumération part par son RANG, pas par les `values` du plugin de
    REAPER (le temps du delay : 0.75 noire pour ReaDelay)."""
    labels = spec.get("params") or {}
    dd = dict(d, name=labels.get(d["id"]) or d.get("name"))
    if d["id"] in labels:
        dd["map"] = {k: v for k, v in (d.get("map") or {}).items() if k not in ("scale", "curve")}
        dd["map"]["mode"] = "raw"
        dd.pop("values", None)
    return dd


def plan_capture(b, spec):
    """Une CAPTURE PILOTABLE (docs/capture-module.md) : le compileur a fait du bloc un `capture-module`, avec son
    fichier d'état (`capture_chunk`, le JSON {"bundle": …} en base64) et ses valeurs normalisées dans l'ordre de ses
    contrôles. Ici le lecteur est le LV2 golem Capture (native/capture-lv2) : 32 contrôles « Control NN », et la
    capture donnée comme un fichier — l'adaptateur le décode à côté (bridge/engine/ardour.py, write_captures)."""
    if not b.get("capture_chunk"):
        return None, [{"id": b.get("id"), "type": b.get("type"), "why": "capture file missing"}]
    values = list(b.get("capture_values") or [])[:32]
    params = [{"pid": f"c{i}", "label": f"Control {i + 1:02d}", "value": max(0.0, min(1.0, float(v)))} for i, v in enumerate(values)]
    blk = {"id": b.get("id"), "type": b.get("type"), "plugin": {"lv2": spec["lv2"]}, "files": {}, "enabled": not b.get("bypass"),
           "params": params, "known": [{"pid": e["pid"], "label": e["label"]} for e in params],
           "capture": {"chunk": b["capture_chunk"], "prop": spec["capture"]}}
    if b.get("foot") is not None:
        blk["foot"] = b["foot"]
    return blk, []


def plan_host(b):
    """Le bloc VST HOST (docs/platforms.md §6.1) : un plugin installé, désigné par son NOM tel que l'inventaire le
    donne (« VST3: Nom (Éditeur) » — la forme de REAPER, que le veilleur reprend : un patch passe d'un moteur à
    l'autre). Le moteur n'héberge que du VST3. Ses potards sont les `knobs` du bloc (`{i, name}`), leur valeur
    normalisée dans `params` sous « p<i> » ; le veilleur les retrouve par leur nom d'abord, par leur rang sinon.
    Son état natif (`_vst_chunk`) part avec lui."""
    name = str(b.get("plugin") or "")
    if not re.match(r"^VST3i?:", name):
        why = "only VST3 plugins are hosted on the Golem Engine" if name else "no plugin chosen"
        return None, [{"id": b.get("id"), "type": "vst-host", "why": why}]
    skipped, params, known = [], [], []
    values = b.get("params") or {}
    for k in b.get("knobs") or []:
        if not isinstance(k, dict) or not isinstance(k.get("i"), int) or isinstance(k.get("i"), bool) or k["i"] < 0:
            continue
        pid = f"p{k['i']}"
        known.append({"pid": pid, "index": k["i"], "name": str(k.get("name") or "")})
        v = values.get(pid)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            params.append({"pid": pid, "index": k["i"], "name": str(k.get("name") or ""), "norm": max(0.0, min(1.0, float(v)))})
    blk = {"id": b.get("id"), "type": "vst-host", "plugin": {"host": name}, "files": {}, "enabled": not b.get("bypass"),
           "params": params, "known": known}
    # l'ÉTAT NATIF capturé (sous REAPER comme ici : `_vst_chunk`) : l'adaptateur en fait un preset VST3 que le veilleur
    # charge avant les potards (bridge/engine/ardour.py, write_host_states)
    if isinstance(values.get("_vst_chunk"), str) and values["_vst_chunk"]:
        blk["host_state"] = {"chunk": values["_vst_chunk"], "plugin": name}
    if values.get("_clap_chunk"):
        skipped.append({"id": b.get("id"), "param": "state", "why": "a CLAP state cannot be loaded into a VST3 plugin"})
    if b.get("foot") is not None:
        blk["foot"] = b["foot"]
    return blk, skipped


def plan_block(b, catalog, table):
    """(bloc moteur, [refus]) ; (None, [raison]) si le type ne joue pas sur ce moteur."""
    t = b.get("type")
    if t == "vst-host":
        return plan_host(b)
    spec = table.get(t)
    if not spec:
        if (catalog.get(t) or {}).get("engine") == "midi":
            return None, []                             # joué par le bridge (MIDI matériel) : rien à poser, rien à dire
        return None, [{"id": b.get("id"), "type": t, "why": NOT_HERE}]
    if spec.get("capture"):
        return plan_capture(b, spec)
    plugin = plugin_of(spec)
    defs = {p["id"]: p for p in (catalog.get(t) or {}).get("params") or [] if p.get("id")}
    if spec.get("golem_fx"):
        # les réglages de la feuille golem FX (docs/golem-fx-sheet.md) : ceux que seul le plugin golem-fx a
        from .. import golem_fx
        defs = {p["id"]: p for p in golem_fx.merged(t, list(defs.values()))[0]}
    labels = spec.get("params") or {}
    files = {}
    for key, prop in (spec.get("files") or {}).items():
        if b.get(key):
            files[prop] = b[key]
    skipped, params, known = [], [], []
    # ce que le plugin ne reçoit PAS par un port : la zone de clavier (le filtre golem Zone devant lui), et les réglages
    # qu'un instrument attend en MIDI (bridge/engine/keys_midi.py : registration de l'orgue, voix du DX7)
    from . import keys_midi
    elsewhere = set()
    if spec.get("zone"):
        elsewhere |= {z[0] for z in ZONE_PARAMS}
    if spec.get("midi") == "organ":
        elsewhere |= keys_midi.ORGAN_PARAMS
    elif spec.get("midi") == "dx7":
        elsewhere |= {"bank", "patch"}
    if spec.get("preset"):
        elsewhere.add("preset")
    if spec.get("arp"):
        elsewhere.add("arp")
    if spec.get("pads"):
        elsewhere.add("kit")
    for pid, d in defs.items():
        if pid not in elsewhere:
            known.append({"pid": pid, "label": labels.get(pid) or d.get("name") or pid})
    absent = spec.get("absent") or {}
    for pid, value in (b.get("params") or {}).items():
        if pid.startswith("_") or pid in elsewhere:
            continue                                   # métadonnées du compileur (_loud…), ou porté ailleurs
        if pid in absent:
            skipped.append({"id": b.get("id"), "param": pid, "why": absent[pid]})
            continue
        d = defs.get(pid)
        if not d:
            skipped.append({"id": b.get("id"), "param": pid, "why": "unknown parameter"})
            continue
        e, why = param_entry(table_def(spec, d), value)
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
    if spec.get("midi") == "organ":
        blk["midi"] = keys_midi.organ_cc(b.get("params"))
    elif spec.get("midi") == "dx7":
        try:
            with open(b.get("dx7_bank") or "", "rb") as f:
                blk["midi"] = [keys_midi.dx7_voice_sysex(f.read(), b.get("dx7_patch"))]
        except (OSError, ValueError) as e:
            skipped.append({"id": b.get("id"), "param": "bank", "why": f"DX7 cartridge not readable ({e})"})
    if spec.get("pads"):
        # le kit : un fichier SFZ que l'adaptateur écrit (bridge/engine/ardour.py, write_content), chargé par sfizz
        text, notes = pads_sfz(b.get("kit_pads"))
        skipped += [{"id": b.get("id"), "param": "kit", "why": n} for n in notes]
        blk["write"] = {"prop": spec["pads"], "name": f"{b.get('id')}.pads.sfz", "text": text}
    if spec.get("preset") and b.get(spec["preset"].get("from") or ""):
        # l'ÉTAT du plugin (le son d'un synthé) : le fichier que le compileur a écrit ; l'adaptateur en fait un preset
        # VST3 que le veilleur charge (bridge/engine/ardour.py, write_presets)
        blk["preset"] = {"chunk": b[spec["preset"]["from"]], "vendor": spec["preset"]["vendor"],
                         "name": spec["preset"]["name"], "uid": spec["vst3"]}
    return blk, skipped


KEYS_INSTRUMENTS = ("vital", "piano", "organ", "ep", "drumkit")


def instrument_kind(block_type):
    """« keys » : un instrument que les touches jouent ; « pads » : le kit de pads ; None : un effet."""
    return "keys" if block_type in KEYS_INSTRUMENTS else "pads" if block_type == "pads" else None


def expand_keys(tr, mch, s):
    """UNE LANE, PLUSIEURS INSTRUMENTS (golem_rig.lua, expand_keys) : deux instruments en série sur une piste
    joueraient les mêmes notes, et un pad jouerait une note dans le synthé. Chaque instrument a SA piste MIDI, sur le
    même clavier, qui n'écoute que SON canal (touches ou pads) ; les effets audio de la lane vont sur un bus qui fait
    leur somme et sort vers la carte, avec le niveau de la scène et la tranche du mixer. Sous REAPER, une piste racine
    reçoit le clavier et renvoie le MIDI ; ici chaque piste s'ouvre directement sur le clavier."""
    name = tr["name"]
    merge = dict(tr, name=name + "#merge", role="merge", kind="bus", input=None, blocks=[])
    merge.pop("midi", None)
    merge["from"] = []
    out, group = [], []
    def flush():
        if not group:
            return
        head = next(b for b in group if not b.get("shadow"))
        ch = mch.get("pads") if head["type"] == "pads" else mch.get("keys")
        child = {"name": f"{name}/{head['id']}", "role": "branch", "kind": "midi", "input": None, "from": [],
                 "mute": False, "blocks": list(group), "gain_db": 0.0, "trim_db": 0.0, "out": None,
                 "midi": dict(tr["midi"], channel=int(ch) if ch else None)}
        merge["from"].append(child["name"])
        out.append(child)
        group.clear()
    src = [b for b in s.get("blocks") or []]
    # les blocs moteur gardent l'ordre du plan ; un instrument emmène ses plugins « ombre » (zone, arp, baffle)
    by_id = {b.get("id"): instrument_kind(b.get("type")) for b in src}
    for blk in tr["blocks"]:
        owner = str(blk["id"]).split("~", 1)[0]
        if by_id.get(owner):                               # un instrument, ou l'ombre d'un instrument
            if group and str(group[0]["id"]).split("~", 1)[0] != owner:
                flush()
            group.append(blk)
        else:
            flush()
            merge["blocks"].append(blk)                   # un effet audio : sur la somme
    flush()
    return [merge] + out


def build(rig, catalog=None, table=None, cards_text=None):
    """Le plan moteur d'un plan compilé."""
    catalog = load_catalog() if catalog is None else catalog
    table = load_table() if table is None else table
    tracks, skipped = [], []
    for path in rig.get("paths") or []:
        specs = path.get("tracks") or []
        # l'ENTRÉE de la carte de ce path (sa piste main/pre) : la clé d'un gate à clé l'écoute (docs/golem-fx-sheet.md §4)
        lane_input = next((s.get("input") for s in specs if s.get("input") is not None and not s.get("midi")), None)
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
                if blk and (table.get(b.get("type")) or {}).get("zone"):
                    blocks.append(plan_zone(b))
                if blk and (table.get(b.get("type")) or {}).get("arp"):
                    blocks.append(plan_arp(b))             # après la zone : on arpège ce que la zone laisse passer
                if blk:
                    if (table.get(b.get("type")) or {}).get("key") and lane_input is not None:
                        blk["key_input"] = lane_input       # le sidechain du plugin, relié au DI de la lane
                    blocks.append(blk)
                    if b.get("default_ir") and "cab" in table:
                        # une tête SANS baffle sur son path : son baffle par défaut, juste derrière elle (compile_rig le
                        # dit ; REAPER le fond dans le cœur de la piste). Il SUIT la tête — même état dans les scènes,
                        # et au pied (le veilleur bascule « <id>~ir » avec <id>). `shadow` : pas un bloc du patch, il
                        # n'entre pas dans le livemap.
                        ir, sk = plan_block({"id": f"{b.get('id')}~ir", "type": "cab", "file": b["default_ir"],
                                             "bypass": b.get("bypass")}, catalog, table)
                        skipped += sk
                        if ir:
                            ir["shadow"] = True
                            blocks.append(ir)
            midi = bool(s.get("midi")) and role in ("main", "pre")
            split = None                                # une lane MIDI à plusieurs instruments : dépliée plus bas
            tr = {"name": s["name"], "role": role, "kind": "midi" if midi else ("track" if role in ("main", "pre") else "bus"),
                  "input": s.get("input") if role in ("main", "pre") and not midi else None,
                  "from": feeds.get(s["name"], []), "mute": bool(s.get("mute")), "blocks": blocks}
            if midi:
                mch = s.get("midi_ch") or {}
                kinds = [instrument_kind(b.get("type")) for b in s.get("blocks") or []]
                ninstr, npads = kinds.count("keys"), kinds.count("pads")
                # le canal qu'écoute la lane (golem_rig.lua, expand_keys) : celui de son rôle s'il est dit ; sinon les
                # touches pour un instrument seul, les pads pour un kit de pads seul
                ch = mch.get(s.get("midi_role") or "keys")
                if not ch:
                    ch = mch.get("keys") if (ninstr and not npads) else mch.get("pads") if (npads and not ninstr) else None
                dev = midi_device(s.get("midi_in"), cards_text)
                tr["midi"] = {"device": dev, "hw": s.get("midi_in"), "channel": int(ch) if ch else None}
                if not dev:
                    skipped.append({"path": path.get("id"), "why": f"no MIDI device plugged for {s.get('midi_in') or 'this lane'}"})
                if ninstr >= 2 or (mch and ninstr >= 1 and npads >= 1):
                    split = mch
            # comme golem_rig.lua : le NIVEAU de la scène (`level`) sur la piste qui SORT vers la carte (main, merge) —
            # le fader, après les plugins (D_VOL) ; le gain du merge (`merge_gain`) AVANT ses plugins — REAPER le pose en
            # tête de chaîne (Volume Adjustment), ici le trim de la route. Mesuré 2026-11-12 (banc des presets) : le merge
            # ne recevait que son gain, les niveaux de scène (+3, -1 dB…) ne sonnaient pas sur le Golem Engine.
            level = s.get("level") if role in ("main", "merge") else None
            tr["gain_db"] = float(level) if level is not None else 0.0
            tr["trim_db"] = float(s.get("merge_gain") or 0.0) if role == "merge" else 0.0
            if role in ("main", "merge"):
                tr["out"] = out_ports(s.get("out_sel"))
                # la SOURCE du mixer de sorties (bridge/mixer.py : « in<entrée> », la tranche de la lane) — le veilleur
                # y pose le trim du rig par-dessus le niveau de scène
                if path.get("input") is not None:
                    tr["mixer"] = f"in{path['input']}"
            else:
                tr["out"] = None                        # pre -> ses branches, branch -> son merge (par `from`)
            if split is not None:
                tracks += expand_keys(tr, split, s)
            else:
                tracks.append(tr)
    plan = {"preset": rig.get("id"), "tracks": tracks, "skipped": skipped}
    loops = looper_loops(rig)
    if loops is not None:
        plan["looper"] = {"loops": loops}
    return plan


def looper_loops(rig):
    """La table de boucles TELLE QUE LE MOTEUR LA CÂBLE (docs/looper.md §6) : une ligne = une paire du looper, et
    l'ENTRÉE de la lane qu'elle écoute (None : la lane n'est pas dans le preset — la boucle resterait muette, le
    veilleur le dit). La source se résout comme sous REAPER (golem_rig.lua, ensure_looper) : un id de path, un numéro
    d'entrée, ou la lettre d'avant 1/2/k. None : le preset n'a pas de looper."""
    lp = rig.get("looper")
    if not isinstance(lp, dict) or lp.get("enabled") is False:
        return None
    src_in = {"1": 1, "2": 2, "k": 3}
    for path in rig.get("paths") or []:
        pin = next((t.get("input") for t in path.get("tracks") or [] if t.get("input") is not None), path.get("input"))
        if pin is not None and path.get("id"):
            src_in[str(path["id"])] = pin
    rows = lp.get("loops") or [{"src": "1"}, {"src": "2"}, {"src": "k"}]
    out = []
    for r in rows[:4]:
        src = str((r or {}).get("src") or "")
        pin = src_in.get(src)
        if pin is None and src.isdigit():
            pin = int(src)
        out.append({"input": pin})
    return out


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
