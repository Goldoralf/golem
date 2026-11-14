# SPDX-License-Identifier: GPL-3.0-or-later
"""JOUER UN SON BRUT DEPUIS LA LIBRARY (« Play it », docs/library-play.md, maquette validée le 2026-11-15).

Une capture (ampli, pédale, baffle, outboard), un son clavier (piano, DX7, orgue, preset Vital) ou un kit de batterie
s'essaie AVEC SON INSTRUMENT, sans patch autour : un rig d'essai d'UNE lane — guitare ou basse sur l'entrée de la carte
qui a ce rôle, clavier ou batterie sur le contrôleur MIDI branché — qui ne porte QUE ce son, émis sous l'id
`library-try` par le chemin de tout rappel (les deux moteurs, REAPER et le Golem Engine, savent le monter). Rien n'est
écrit. Le patch qui jouait est mis de côté ; « Stop » le rappelle (l'id différent force un rebuild).

Sans l'appareil (pas d'entrée guitare sur la carte, aucun contrôleur MIDI branché), on le DIT au lieu de faire semblant.
Le même document, sans liaison, sert à « Add to… ▸ A new patch » (patch_doc)."""
import copy
import re

TRY_ID = "library-try"
BLOCK_ID = "sound"
_TRY = {"item": None, "name": None, "role": None, "device": None, "base": None}


class TryError(Exception):
    """Un essai impossible : le message (anglais) est montré tel quel au musicien."""


# ── ce qu'on essaie : le bloc et son rôle ───────────────────────────────────────────────────────────────────────────
def _tone(ref):
    from . import config as C
    from .store import _read_json
    cat = _read_json(C.CATALOG, {"tones": []}).get("tones") or []
    tones = cat.values() if isinstance(cat, dict) else cat
    return next((t for t in tones if str(t.get("id")) == str(ref)), None)


def resolve(item):
    """(rôle, bloc, nom) pour {capture, model} · {sound} · {kit}. Lève TryError."""
    item = item or {}
    if item.get("capture") is not None:
        from . import playable as PL, audition as A
        t = _tone(item["capture"])
        if not t:
            raise TryError("This capture is not on the rack.")
        models = t.get("models") or []
        m = next((x for x in models if str(x.get("id")) == str(item.get("model"))), None) if item.get("model") else None
        m = m or (models[0] if models else None)
        if not m:
            raise TryError("This capture has no model on the rack.")
        btype = PL.block_for(t.get("gear"), t.get("format") or "nam", t.get("ir_kind"))
        if not btype:
            raise TryError("golem can't play this capture yet.")
        if btype == "preamp-nam":
            btype = A.outboard_type(t)                       # un compresseur capturé joue comme tel
        name = t.get("amp") or t.get("title") or str(t.get("id"))
        role = "bass" if A._is_bass(t) else "guitar"
        return role, {"id": BLOCK_ID, "type": btype, "label": name, "ref": str(t["id"]), "model": str(m["id"]),
                      "params": {}}, f"{name} · {m.get('name') or m['id']}"
    if item.get("sound"):
        from . import sound_preview as SP
        d = SP.describe(item["sound"])
        if isinstance(d, str):
            raise TryError(d[0].upper() + d[1:] + ".")
        return "keys", dict(d["block"], id=BLOCK_ID), d["name"]
    if item.get("kit"):
        from . import kits as K
        k = K.get_kit(item["kit"])
        if not k:
            raise TryError("This kit is not on the rack.")
        if k.get("available") is False:
            raise TryError(k.get("unavailable_why") or "This kit is not on this machine.")
        typ = "drumkit" if k.get("role") == "drum" else "pads"
        return "drums", {"id": BLOCK_ID, "type": typ, "params": {"kit": k["id"]}}, k.get("name") or k["id"]
    raise TryError("Nothing to play.")


def patch_doc(role, block, name):
    """Un patch v2 d'une lane qui ne porte que `block` — l'essai, ou « Add to… ▸ A new patch »."""
    midi = role in ("keys", "drums")
    lid = f"{role}-1"
    return {"id": "library-" + re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")[:40], "name": name, "role": role,
            "kind": "patch", "patch_v": 2, "lanes_v": 2, "bpm": 120, "tags": [], "config": {}, "needs": [], "deps": [],
            "lanes": [{"id": lid, "role": role, "name": name, **({"midi": True} if midi else {}), "stereo": midi,
                       "chain": {"chain": [copy.deepcopy(block)]},
                       "states": [{"id": f"st-{lid}-A", "name": "Raw", "blocks": {}, "params": {}, "branches": {}}]}],
            "scenes": [{"id": "A", "name": "Raw", "lanes": {lid: {"state": f"st-{lid}-A"}}}]}


# ── l'appareil : ce qui joue le son ─────────────────────────────────────────────────────────────────────────────────
def device(role):
    """{ok, name, why} : l'instrument qui jouera — une entrée de la carte (guitare, basse) ou un contrôleur branché."""
    if role in ("guitar", "bass"):
        from . import inputmap
        from .state import state
        ins = ((state.inputmap or inputmap.current() or {}).get("inputs")) or []
        for want in ((role, "guitar") if role == "bass" else (role,)):
            e = next((x for x in ins if x.get("role") == want), None)
            if e:
                return {"ok": True, "name": f"your {want} on input {e.get('ch')}", "why": None}
        return {"ok": False, "name": None, "why": f"This card has no {role} input. Give an input the {role} role in "
                                               "System ▸ Soundcard, or Listen to the demo."}
    from . import devices
    roles = ("drums", "pads", "keys") if role == "drums" else ("keys",)
    for want in roles:
        d = next((x for x in devices.listing() if x.get("connected") and want in (x.get("roles") or [])), None)
        if d:
            return {"ok": True, "name": d.get("name") or "your controller", "why": None}
    return {"ok": False, "name": None,
            "why": ("No drum pads or electronic kit is plugged in. Plug one (USB or MIDI): Play it lights up, nothing "
                    "to restart." if role == "drums" else
                    "No keyboard is plugged in. Plug one (USB or MIDI): Play it lights up, nothing to restart.")}


# ── l'essai ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def live():
    from . import recall as R
    return R._LAST_EMIT.get("pid") == TRY_ID and _TRY["item"] is not None


def status():
    on = live()
    if not on:
        _TRY.update(item=None, name=None, role=None, device=None, base=None)
    return {"on": on, "item": _TRY["item"], "name": _TRY["name"], "role": _TRY["role"], "device": _TRY["device"]}


def build(item):
    """(document d'essai joué, rôle, nom, appareil) — lève TryError (pas d'appareil, rien à jouer, lane impossible)."""
    from . import patches as P
    role, block, name = resolve(item)
    dev = device(role)
    if not dev["ok"]:
        raise TryError(dev["why"])
    doc = patch_doc(role, block, name)
    if role == "bass" and dev["name"].startswith("your guitar"):
        doc["role"] = doc["lanes"][0]["role"] = "guitar"   # une capture de basse se joue sur l'entrée guitare
    pre = P.as_preset(doc)
    lane = ((pre or {}).get("lanes") or [{}])[0]
    if not pre or lane.get("bind_error") or str(lane.get("in_sel") or "").upper() == "NONE":
        raise TryError(lane.get("bind_error") or "No input of this card can play it.")
    pre = dict(pre, id=TRY_ID, name=f"Try · {name}")
    pre.pop("factory", None)
    return pre, role, name, dev["name"]


async def start(item):
    from . import recall as R
    from .state import state
    if ((state.mode or {}).get("ui") or {}).get("locked"):
        raise TryError("The rack is locked in this mode: unlock it to try a sound.")
    if (state.perf or {}).get("recording"):
        raise TryError("A take is recording: stop it before trying a sound.")
    pre, role, name, dev = build(item)
    err = await R.emit_preset_async(pre, "A")
    if err:
        raise TryError(err)
    _TRY.update(item=item, name=name, role=role, device=dev, base=state.preset_id)
    return status()


async def stop():
    from . import recall as R
    from .state import state
    was = live()
    _TRY.update(item=None, name=None, role=None, device=None, base=None)
    if was and state.preset_id:
        await R.recall_async(state.preset_id, state.scene_id)
    return {"ok": True, "restored": bool(was and state.preset_id)}


def set_param(param, value):
    """Un potard du son essayé, en direct (les macros d'un preset Vital) : la livemap du rig d'essai, puis le moteur
    actif (REAPER ou le Golem Engine) — sans rebuild. Rend False si le bloc ou le potard n'est pas monté."""
    import json
    import os
    from . import config as C, engine
    if not live():
        return False
    try:
        lm = json.load(open(os.path.join(C.PRESETS_DIR, ".livemap.json")))
    except (OSError, ValueError):
        return False
    blk = (lm.get("blocks") or {}).get(BLOCK_ID)
    pm = ((blk or {}).get("params") or {}).get(param)
    if not (blk and pm):
        return False
    pdef = next((p for p in (_fx_def(blk.get("type")).get("params") or []) if p.get("id") == param), {})
    raw = float(value) * float(((pdef.get("map") or {}).get("scale")) or 1)
    lo, hi = pm.get("pmin", 0), pm.get("pmax", 1)
    norm = max(0.0, min(1.0, (raw - lo) / (hi - lo) if hi != lo else 0.0))
    engine.get().set_fx_param(blk["track"], blk["fx"], pm["p"], norm)
    return True


def _fx_def(btype):
    import json
    from . import config as C
    try:
        data = json.load(open(C.EFFECTS))
    except (OSError, ValueError):
        return {}
    return next((e for e in data.get("effects") or [] if e.get("type") == btype), {})
