# SPDX-License-Identifier: GPL-3.0-or-later
"""La BANQUE de la boîte à rythmes pour le Golem Engine (docs/ardour-plan.md §7d, lot 3). Pur : testé en CI.

Sous REAPER, golem_drums.lua lit lui-même les .mid des grooves et le descripteur du kit. Ici le veilleur n'a rien à
lire : le bridge joint à la commande `drums`/`play` ce qu'il faut — chaque groove déjà DÉPLIÉ en événements, et le
plugin du kit. Mêmes règles que golem_drums.lua (parse_midi, apply_notemap, read_kit) :
  - résolution interne 960 ticks par noire ; seuls les note-on comptent (un kit de batterie joue en one-shot) ;
  - la mesure vient du PREMIER chiffrage rencontré (défaut 4/4) ; la longueur est arrondie à la mesure SUPÉRIEURE ;
  - un groove illisible devient un slot MUET d'une mesure (le pied ne tombe pas sur un trou dans la banque) ;
  - un kit non General MIDI reçoit les grooves (GM) traduits par `notemap` (note GM -> note du kit, -1 = se taire).
"""
import json
import os

PPQ = 960
MAX_EVENTS = 2000            # par groove (le slot de la mémoire partagée du séquenceur en tient 2046)
MAX_SLOTS = 14               # grooves + fills d'un bloc (la mémoire partagée du séquenceur)


def _vlq(data, i):
    v = 0
    while i < len(data):
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if b < 0x80:
            break
    return v, i


def parse_midi(data):
    """Un Standard MIDI File (octets) -> {"len", "bar", "events": [[tick, note, vélocité]]}. Lève ValueError."""
    if len(data) < 14 or data[:4] != b"MThd":
        raise ValueError("not a Standard MIDI File")
    division = int.from_bytes(data[12:14], "big")
    if division >= 0x8000:
        raise ValueError("SMPTE time division is not supported")
    scale = PPQ / (division or PPQ)
    events, max_tick, bar, got_sig = [], 0, 4 * PPQ, False
    pos = 8 + int.from_bytes(data[4:8], "big")
    while pos + 8 <= len(data):
        chunk, n = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "big")
        i, end = pos + 8, min(len(data), pos + 8 + n)
        pos = pos + 8 + n
        if chunk != b"MTrk":
            continue
        tick, running = 0, None
        while i < end:
            delta, i = _vlq(data, i)
            tick += delta
            b = data[i]
            if b >= 0x80:
                running, i = b, i + 1
            else:
                b = running
            if b is None:
                break
            if b == 0xFF:                                  # méta : ne fixe pas le statut courant
                mtype = data[i]
                mlen, i = _vlq(data, i + 1)
                if mtype == 0x58 and mlen >= 2 and not got_sig:
                    bar = int(data[i] * (4 / (2 ** data[i + 1])) * PPQ + 0.5) or 4 * PPQ
                    got_sig = True
                i += mlen
            elif b in (0xF0, 0xF7):
                slen, i = _vlq(data, i)
                i += slen
                running = None
            else:
                hi = b & 0xF0
                if hi == 0x90:
                    note, vel = data[i], data[i + 1]
                    i += 2
                    if vel > 0:
                        events.append([int(tick * scale + 0.5), note, vel])
                elif hi in (0x80, 0xA0, 0xB0, 0xE0):
                    i += 2
                elif hi in (0xC0, 0xD0):
                    i += 1
                else:
                    break                                  # flux corrompu : cette piste s'arrête là
            max_tick = max(max_tick, tick)
    events.sort(key=lambda e: e[0])
    total = int(max_tick * scale + 0.5)
    bars = max(1, -(-(total * 1000 - 1) // (bar * 1000)) if total else 1)
    return {"len": bars * bar, "bar": bar, "events": events[:MAX_EVENTS]}


def silent_slot():
    return {"len": 4 * PPQ, "bar": 4 * PPQ, "events": []}


def apply_notemap(slot, notemap):
    """Les notes GM d'un groove réécrites pour un kit qui ne l'est pas ; -1 = le kit n'a pas cette pièce."""
    if not notemap:
        return slot
    nm = {int(k): int(v) for k, v in notemap.items()}
    out = []
    for tick, note, vel in slot["events"]:
        t = nm.get(note, note)
        if t >= 0:
            out.append([tick, t, vel])
    return dict(slot, events=out)


def bank(root, patterns, fills, notemap=None):
    """La banque d'un `play` : les grooves puis les fills, chacun déplié. (banque, [ce qui n'a pas pu se lire])"""
    slots, skipped = [], []
    files = list(patterns or []) + list(fills or [])
    for rel in files[:MAX_SLOTS]:
        try:
            with open(os.path.join(root, rel), "rb") as f:
                slots.append(apply_notemap(parse_midi(f.read()), notemap))
        except (OSError, ValueError, IndexError) as e:
            slots.append(silent_slot())
            skipped.append(f"{rel}: {e}")
    if len(files) > MAX_SLOTS:
        skipped.append(f"{len(files) - MAX_SLOTS} groove(s) beyond the {MAX_SLOTS} this engine holds")
    return {"ppq": PPQ, "patterns": min(len(patterns or []), MAX_SLOTS), "slots": slots}, skipped


SFIZZ = "http://sfztools.github.io/sfizz"
SFIZZ_FILE = SFIZZ + ":sfzfile"
GM_DEFAULT = (36, 38, 42, 46, 49, 51, 45, 41)        # golem_drums.lua : une liste de samples nue, dans cet ordre


def kit_plugin(root, kit_id, avldrums):
    """Le plugin qui joue ce kit sur le Golem Engine : ({"lv2", "files"?, "write"?}, None) ou (None, raison).
    `avldrums` : la table banque -> URI (library/catalog/effects-golem-engine.json, `drumkit.avldrums`)."""
    from .ardour_plan import pads_sfz
    kid = str(kit_id or "")
    if ".wav" in kid or "[" in kid or "/" in kid:        # une liste de samples nue (un bloc sans kit nommé)
        rels = [r for r in kid.replace("[", " ").replace("]", " ").replace('"', " ").replace(",", " ").split() if r]
        pads = [{"note": GM_DEFAULT[i] if i < len(GM_DEFAULT) else 36 + i, "file": os.path.join(root, r), "mode": "oneshot",
                 "level": 0} for i, r in enumerate(rels)]
        return {"lv2": SFIZZ, "write": {"prop": SFIZZ_FILE, "name": "drums.kit.sfz", "text": pads_sfz(pads)[0]}}, None
    try:
        with open(os.path.join(root, "library", "kits", kid.removesuffix(".json") + ".json"), encoding="utf-8") as f:
            k = json.load(f)
    except (OSError, ValueError):
        return None, f"kit {kid or '?'} not found"
    eng = k.get("engine") or "rs5k"
    if eng == "avldrums":
        uri = (avldrums or {}).get(k.get("bank"))
        return ({"lv2": uri}, None) if uri else (None, f"AVL bank {k.get('bank')} is not on this engine")
    if eng == "sfz":
        path = os.path.join(root, "library", "sfz", k.get("sfz") or "")
        return ({"lv2": SFIZZ, "files": {SFIZZ_FILE: path}}, None) if os.path.isfile(path) else (None, f"{k.get('sfz')} is missing")
    if eng == "rs5k":
        pads = [{"note": p["note"], "file": os.path.join(root, p["sample"]), "mode": p.get("mode") or "oneshot",
                 "level": p.get("level") or 0} for p in k.get("pads") or [] if p.get("sample")]
        return {"lv2": SFIZZ, "write": {"prop": SFIZZ_FILE, "name": f"{k.get('id') or kid}.kit.sfz", "text": pads_sfz(pads)[0]}}, None
    return None, f"kit engine {eng} is not on this engine yet"
