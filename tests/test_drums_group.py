# SPDX-License-Identifier: GPL-3.0-or-later
"""Le GROUPE DE BATTERIE — N entrées, un instrument (docs/drums-kit.md §6).

Ce que ces tests gardent, et qui s'est déjà perdu ailleurs :
  - les trois champs de lane SURVIVENT à la normalisation (un `patch_from` s'était perdu comme ça) ;
  - `audio_outs` est VALIDÉ quand il est là, et ABSENT ne veut pas dire « pas de master » ;
  - un descripteur d'avant le 2026-09-20 reste valide (le champ est additif).
"""
import json
import os

import pytest

from bridge import drumkits, store


# ── les trois champs de lane ─────────────────────────────────────────────────────────────────
def _preset(lanes):
    return {"id": "t", "name": "T", "lanes_v": 2, "lanes": lanes}


def test_les_trois_champs_du_groupe_survivent_a_la_normalisation():
    p = _preset([{"id": "kick", "role": "drums", "in_sel": "1",
                  "drumset": "mps", "drumset_module": "millenium-mps1000", "element": "kick"}])
    L = store.lanes_of(p)[0]
    assert L["drumset"] == "mps"
    assert L["drumset_module"] == "millenium-mps1000"
    assert L["element"] == "kick"


def test_une_lane_ordinaire_ne_gagne_pas_les_champs_du_groupe():
    """Absents, pas vides : un `element: ""` sur une lane de guitare ferait croire à un groupe."""
    L = store.lanes_of(_preset([{"id": "g", "role": "guitar", "in_sel": "1"}]))[0]
    for k in ("drumset", "drumset_module", "element"):
        assert k not in L


def test_un_champ_vide_ou_non_chaine_est_ignore():
    L = store.lanes_of(_preset([{"id": "g", "role": "drums", "in_sel": "1",
                                 "drumset": "  ", "element": 12, "drumset_module": None}]))[0]
    assert "drumset" not in L and "element" not in L and "drumset_module" not in L


def test_le_kit_mix_est_une_paire_stereo():
    """Le reste du kit sort du master : une PAIRE liée, et `stereo` doit suivre."""
    L = store.lanes_of(_preset([{"id": "mix", "role": "drums", "in_sel": "7-8",
                                 "drumset": "mps", "element": "kit-mix"}]))[0]
    assert L["stereo"] is True
    assert L["element"] == "kit-mix"


def test_kit_mix_n_est_pas_un_element_de_kit():
    """Deux vocabulaires, jamais mélangés : `kit-mix` nomme le master, pas une peau."""
    assert drumkits.KIT_MIX not in drumkits.ELEMENTS


# ── audio_outs ───────────────────────────────────────────────────────────────────────────────
def _desc(**kw):
    d = {"id": "x", "kind": "drumkit", "schema": 1, "name": "X",
         "identity": {"brand": "a", "model": "b", "connection": "usb", "usb_names": []},
         "channel": 10, "map": {"36": "kick", "38": "snare"},
         "hihat": {"cc": 4, "open_value": 0, "closed_value": 127, "positions": 3,
                   "bands": [33, 66], "notes": "distinct"},
         "choke": "none",
         "provenance": {"source": "manual", "confidence": "reported", "note": "n"}}
    d.update(kw)
    return d


def test_audio_outs_absent_reste_valide():
    """Additif : les onze descripteurs écrits avant le 2026-09-20 n'ont pas ce champ."""
    assert drumkits.validate(_desc(), "x") == []


def test_audio_outs_valide_accepte():
    assert drumkits.validate(_desc(audio_outs={"master": "stereo", "direct": 8,
                                               "assignable": True, "default": ["kick", "snare"]}), "x") == []


@pytest.mark.parametrize("ao, bout", [
    ({"master": "quad", "direct": 0, "assignable": False}, "master"),
    ({"master": "stereo", "direct": 99, "assignable": False}, "direct"),
    ({"master": "stereo", "direct": 2}, "assignable"),
    ({"master": "stereo", "direct": 2, "assignable": True, "default": ["kick", "nope"]}, "default[1]"),
    ({"master": "stereo", "direct": 1, "assignable": True, "default": ["kick", "snare"]}, "2 entries"),
    ({"master": None, "direct": 0, "assignable": False}, "no output at all"),
])
def test_audio_outs_mal_forme_refuse(ao, bout):
    probs = drumkits.validate(_desc(audio_outs=ao), "x")
    assert any(bout in p for p in probs), probs


def test_absent_ne_veut_pas_dire_declare():
    """« personne n'a rempli ce champ » ≠ « ce module n'a qu'un master » — l'écran doit pouvoir
    dire lequel des deux, sinon il affirme à la place du descripteur."""
    a = drumkits.audio_outs_of(_desc())
    assert a["declared"] is False and a["master"] == "stereo" and a["direct"] == 0
    b = drumkits.audio_outs_of(_desc(audio_outs={"master": "stereo", "direct": 0, "assignable": False}))
    assert b["declared"] is True


def test_proposition_generique_dite_comme_telle():
    a = drumkits.audio_outs_of(_desc(audio_outs={"master": "stereo", "direct": 3, "assignable": True}))
    assert a["generic"] is True and a["default"] == ["kick", "snare", "hh-closed"]
    b = drumkits.audio_outs_of(_desc(audio_outs={"master": "stereo", "direct": 2, "assignable": True,
                                                 "default": ["snare", "kick"]}))
    assert b["generic"] is False and b["default"] == ["snare", "kick"]


def test_default_ne_depasse_jamais_le_nombre_de_sorties():
    a = drumkits.audio_outs_of(_desc(audio_outs={"master": "stereo", "direct": 2, "assignable": True,
                                                 "default": ["kick", "snare", "ride"]}))
    assert len(a["default"]) == 2


# ── les descripteurs du dépôt ────────────────────────────────────────────────────────────────
def test_tous_les_descripteurs_du_depot_restent_valides():
    assert len(drumkits.load_all(strict=True)) >= 11


def test_les_sorties_relevees_sont_la():
    """Trois modules ont une source lue (§6.4) ; les autres n'affirment rien, et c'est voulu."""
    outs = {k: drumkits.audio_outs_of(drumkits.get(k)) for k in
            ("alesis-nitro", "alesis-strike", "millenium-mps1000")}
    assert outs["alesis-nitro"]["direct"] == 0 and outs["alesis-nitro"]["declared"] is True
    assert outs["alesis-strike"]["direct"] == 7
    assert outs["millenium-mps1000"]["direct"] == 8


def test_le_listing_porte_les_sorties():
    rows = {r["id"]: r for r in drumkits.listing()}
    assert rows["millenium-mps1000"]["audio_outs"]["direct"] == 8
    assert rows["roland-td"]["audio_outs"]["declared"] is False
