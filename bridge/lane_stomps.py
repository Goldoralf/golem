# SPDX-License-Identifier: GPL-3.0-or-later
"""MA LANE, SUR MON TÉLÉPHONE (docs/band-scenes.md §4, écran 5 — 2026-09-15).

Le pédalier reste au guitariste et commute l'ACCORD du groupe. Chaque musicien, depuis son
téléphone (Companion), voit la scène en cours avec l'état qu'elle choisit pour SA lane, ses blocs
— qu'ils aient un switch ou non — et son niveau de scène, et il BASCULE ses propres blocs. C'est le
seul pouvoir ajouté : ni scène, ni preset, ni volume des autres, ni blocs d'une autre lane.

Pur Python (sans Reaper, sans état global) : le calcul de « ma lane » et la garde du geste. La route
(app.py) y ajoute l'identité de l'appareil, l'état courant et la commande au moteur.

Une bascule vit le temps de la SCÈNE : elle est gardée avec (preset, scène) et ignorée dès que l'un
des deux change — un changement de scène rappelle, dans le moteur, l'état de chaque bloc écrit dans
la scène. Même règle qu'un stomp au pied.
"""
from . import store

# rôle d'un appareil (auth.ROLES) -> rôles de lanes qu'il tient
LANE_ROLES_OF_DEVICE = {"Guitar": ("guitar", "line"), "Bass": ("bass",), "Voice": ("voice",),
                        "Keys": ("keys", "keys-pads"), "Pads": ("pads", "keys-pads"),
                        "Keys + Pads": ("keys", "pads", "keys-pads"),
                        # docs/drums-kit.md lot 0 : la batterie est une lane comme les autres — un appareil
                        # Drums tient la lane `drums` (audio stéréo du module, ou MIDI par USB). « () » lui
                        # donnait ZÉRO lane, ce qui poussait le Companion batteur vers l'onglet Beat.
                        "Drums": ("drums",)}

# ce qu'on ne « bascule » pas depuis un téléphone : le cœur du son (ampli, baffle, instrument), les
# utilitaires système et les SERVICES (ils ont leur propre transport, cf. app.SERVICE_TYPES)
NOT_TOGGLED = {"amp", "amp-nam", "preamp-nam", "cab", "volume", "tuner", "rec", "click", "looper", "backing-track",
               "sample", "drums", "standard", "arrangement", "vital", "piano", "organ", "ep", "pads", "drumkit", "midi-pedal"}
# ⚠ « drums » ci-dessus = le bloc BOÎTE À RYTHMES (lane Players), pas le rôle de lane `drums` (docs/drums-kit.md)


def lane_person(L, imap):
    """La PERSONNE qui tient une lane (docs/devices-people.md, lot A) : celle de son entrée sur la carte
    ACTIVE — audio : l'entrée nommée (rôle, numéro) sinon le canal ; MIDI : le port USB. None sinon.
    `imap` = inputmap.current() (entrées et ports enrichis)."""
    imap = imap or {}
    if L.get("midi"):
        ports = [u for u in imap.get("usb") or [] if u.get("bound")]
        sel = str(L.get("in_sel") or "")
        n = int(sel[3:]) if sel.startswith("usb") and sel[3:].isdigit() else None
        u = next((x for x in ports if x.get("port") == n), None) if n else None
        u = u or next((x for x in ports if L.get("in_role") and x.get("role") == L.get("in_role")), None) or (ports[0] if ports else None)
        return (u or {}).get("person")
    ins = imap.get("inputs") or []
    e = None
    if L.get("in_role") and L.get("in_nth") is not None:
        e = next((x for x in ins if x.get("role") == L["in_role"] and x.get("nth") == L["in_nth"]), None)
    if e is None:
        ch = str(L.get("in_sel") or L.get("input") or "")
        e = next((x for x in ins if str(x.get("ch")) == ch or ch in str(x.get("ch")).split("-")), None)
    return (e or {}).get("person")


def _owns(L, device_role, person, imap):
    """L'appareil tient-il cette lane ? Par la PERSONNE s'il en porte une, sinon par le rôle ; None = le rack en local."""
    if person:
        return lane_person(L, imap) == person
    roles = lane_roles(device_role)
    return roles is None or L.get("role") in roles


def lane_roles(device_role):
    """Les rôles de lanes d'un appareil ; None = pas de restriction (l'écran du rack, en local)."""
    if device_role is None:
        return None
    return LANE_ROLES_OF_DEVICE.get(device_role, ())


def _scene(preset, scene_id):
    scenes = [s for s in (preset or {}).get("scenes") or [] if isinstance(s, dict)]
    return next((s for s in scenes if s.get("id") == scene_id), scenes[0] if scenes else {})


def toggle_of(toggles, preset_id, scene_id, block_id):
    """La bascule vivante d'un bloc pour CE preset et CETTE scène, sinon None."""
    t = (toggles or {}).get(block_id)
    if isinstance(t, dict) and t.get("preset") == preset_id and t.get("scene") == scene_id:
        return bool(t.get("on"))
    return None


def mine(preset, scene_id, device_role, toggles=None, person=None, imap=None):
    """Les lanes de l'appareil dans le preset courant, telles que le téléphone les montre :
    [{id, name, role, state, implicit, level, mute, input, blocks:[{id, type, label, variant, foot, on, live}]}].
    Avec une PERSONNE : ses lignes (toutes les lanes dont l'entrée est à elle) ; sinon le rôle."""
    if not preset:
        return []
    sc = _scene(preset, scene_id)
    rows = {r["id"]: r for r in (store.scene_lane_states(preset).get(sc.get("id")) or [])}
    out = []
    for L in store.lanes_of(preset):
        if not _owns(L, device_role, person, imap):
            continue
        blocks = []
        for b in store._lane_chain_blocks(L.get("chain") or {}):
            if not isinstance(b, dict) or not b.get("id") or b.get("type") in NOT_TOGGLED:
                continue
            base = store._block_on_in_scene({"id": b["id"], "type": b.get("type"), "bypass": bool(b.get("bypass"))},
                                            sc.get("blocks") or {})
            live = toggle_of(toggles, preset.get("id"), sc.get("id"), b["id"])
            blocks.append({"id": b["id"], "type": b.get("type"), "label": b.get("label"), "variant": b.get("variant"),
                           "foot": b.get("foot"), "on": base if live is None else live, "live": live is not None})
        r = rows.get(L["id"]) or {}
        extra = {"instruments": instruments_by_scene(preset, L)} if L.get("midi") else {}
        from . import capture_module as CM
        extra["capture_modules"] = sum(bool(CM.entry_controls(b)) for b in store._lane_chain_blocks(L.get("chain") or {})
                                       if isinstance(b, dict) and b.get("ref"))
        out.append({**extra, "id": L["id"], "name": L.get("name"), "role": L.get("role"), "midi": bool(L.get("midi")),
                    "input": ("USB " + (str(L.get("in_sel"))[3:] or "1")) if L.get("midi") else ("IN " + str(L.get("in_sel"))),
                    "state": r.get("state"), "implicit": r.get("implicit"),
                    "level": r.get("level"), "mute": bool(r.get("mute")), "blocks": blocks})
    return out


INSTRUMENTS = ("vital", "piano", "ep", "organ", "pads", "drumkit")
CONTENT = {"vital": "preset", "piano": "sfz", "ep": "patch", "organ": None, "pads": "kit", "drumkit": "kit"}
INSTRUMENT_NAME = {"vital": "Vital", "piano": "Piano", "ep": "E-Piano", "organ": "Organ", "pads": "Pads", "drumkit": "Drum Kit"}


def _pval(b, sc, k):
    """Valeur d'un paramètre d'un bloc DANS une scène : surcharge de la scène > base du bloc."""
    ov = ((sc.get("params") or {}).get(b.get("id")) or {}) if isinstance(sc, dict) else {}
    return ov.get(k, (b.get("params") or {}).get(k))


def instruments_by_scene(preset, L):
    """Une lane CLAVIER, scène par scène (page Mine d'une ligne clavier) : le son qui joue, son instrument,
    son split et sa transposition — pour que le passage au refrain ne surprenne jamais."""
    out = []
    blocks = [b for b in store._lane_chain_blocks(L.get("chain") or {}) if isinstance(b, dict) and b.get("type") in INSTRUMENTS]
    for sc in (preset or {}).get("scenes") or []:
        if not isinstance(sc, dict):
            continue
        on = [b for b in blocks if store._block_on_in_scene({"id": b.get("id"), "type": b.get("type"), "bypass": bool(b.get("bypass"))}, sc.get("blocks") or {})]
        muted = bool(((sc.get("lanes") or {}).get(L["id"]) or {}).get("mute"))
        b = on[0] if on else None
        row = {"scene": sc.get("id"), "scene_name": sc.get("name"), "muted": muted or b is None}
        if b:
            key = CONTENT.get(b["type"])
            val = _pval(b, sc, key) if key else None
            name = str(val).split("/")[-1].rsplit(".", 1)[0].replace("_", " ") if val else (b.get("label") or INSTRUMENT_NAME.get(b["type"]))
            row.update(name=name, instrument=INSTRUMENT_NAME.get(b["type"], b["type"]),
                       zone_lo=_pval(b, sc, "zone_lo"), zone_hi=_pval(b, sc, "zone_hi"), transpose=_pval(b, sc, "transpose"))
        out.append(row)
    return out


def check_toggle(preset, block_id, device_role, person=None, imap=None):
    """None si l'appareil peut basculer ce bloc, sinon la phrase (anglais : elle s'affiche) qui dit non."""
    if not preset:
        return "no preset is loaded"
    for L in store.lanes_of(preset):
        for b in store._lane_chain_blocks(L.get("chain") or {}):
            if isinstance(b, dict) and b.get("id") == block_id:
                if b.get("type") in NOT_TOGGLED:
                    return "this block is not a pedal you switch"
                if not _owns(L, device_role, person, imap):
                    return "this block is on another musician's lane"
                return None
    return "this block is not in the current preset"
