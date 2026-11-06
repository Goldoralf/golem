# SPDX-License-Identifier: GPL-3.0-or-later
"""ensure_volume (2026-10-07, Paper Kite dans le Designer) : le volume système se cherche dans TOUTES les
lanes et se pose sur la lane GUITARE par son rôle — pas sur la première lane de la liste, que le Designer
retrie selon les entrées de la carte (voix en tête -> second `volume-sys` -> compile refusée)."""
import copy

from bridge import store


def _p(lanes):
    return {"lanes_v": store.LANES_V, "lanes": lanes}


def _lane(id_, role, blocks):
    return {"id": id_, "role": role, "midi": False, "chain": {"pre": blocks, "split": None, "post": []}}


def _vols(p):
    return {L["id"]: sum(1 for b in store.rich_chain(L["chain"])["pre"] + store.rich_chain(L["chain"])["post"]
                         if b.get("type") == "volume") for L in p["lanes"]}


def test_un_volume_deja_sur_la_guitare_n_est_pas_double_quand_la_voix_est_en_tete():
    p = _p([_lane("voice-1", "voice", [{"type": "eq", "id": "e"}]),
            _lane("guitar-1", "guitar", [{"type": "volume", "id": "volume-sys"}])])
    assert _vols(store.ensure_volume(copy.deepcopy(p))) == {"voice-1": 0, "guitar-1": 1}


def test_sans_volume_il_va_sur_la_lane_guitare_par_son_role():
    p = _p([_lane("voice-1", "voice", []), _lane("guitar-1", "guitar", [])])
    assert _vols(store.ensure_volume(p)) == {"voice-1": 0, "guitar-1": 1}


def test_sans_guitare_la_premiere_lane_audio():
    p = _p([_lane("voice-1", "voice", []), _lane("bass-1", "bass", [])])
    assert _vols(store.ensure_volume(p)) == {"voice-1": 1, "bass-1": 0}
