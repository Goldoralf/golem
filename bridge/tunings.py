# SPDX-License-Identifier: GPL-3.0-or-later
"""Les ACCORDAGES (2026-10-08) — la table library/catalog/tunings.json est une COPIE de celle de
golem.fm (frontend/src/lib/harmony/tunings.ts, TUNING_PRESETS) : mêmes id, mêmes libellés, MIDI de la
corde grave à l'aiguë. Le bloc Tuner d'une lane porte `params.tuning` (un de ces id) ; l'accordeur de
/live en tire ses cordes (6, 7 ou 8 pour une guitare, 4 ou 5 pour une basse).

La liste proposée suit le RÔLE de la lane : une basse ne se voit pas proposer un accordage 7 cordes."""
import json
import os

from . import config as C

PATH = os.path.join(C.ROOT, "library", "catalog", "tunings.json")
FAMILIES = {"guitar": ("6-string", "7-string", "8-string"), "bass": ("bass-4", "bass-5")}
_cache = {"mtime": None, "doc": None}


def load():
    try:
        mt = os.path.getmtime(PATH)
    except OSError:
        return {"tunings": [], "defaults": {}}
    if _cache["mtime"] != mt:
        with open(PATH, encoding="utf-8") as f:
            _cache["doc"] = json.load(f)
        _cache["mtime"] = mt
    return _cache["doc"]


def kind_of(role):
    """guitar | bass — tout ce qui n'est pas une basse s'accorde comme une guitare."""
    return "bass" if role == "bass" else "guitar"


def for_role(role):
    """Les accordages proposés à une lane de ce rôle, dans l'ordre de golem.fm."""
    fams = FAMILIES[kind_of(role)]
    return [t for t in load().get("tunings") or [] if t.get("family") in fams]


def resolve(tid, role):
    """L'accordage d'id `tid` s'il convient au rôle, sinon le défaut du rôle. Jamais None si la table existe."""
    lst = for_role(role)
    hit = next((t for t in lst if t.get("id") == tid), None)
    if hit:
        return hit
    dflt = (load().get("defaults") or {}).get(kind_of(role))
    return next((t for t in lst if t.get("id") == dflt), lst[0] if lst else None)
