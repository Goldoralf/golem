# SPDX-License-Identifier: GPL-3.0-or-later
"""Les noms de scènes d'un patch survivent à l'enregistrement (§13 bis, corrigé 2026-09-08).

Un patch généré par l'IA vit seul : ses « Creepy Intro / Main Riff » n'ont pas de morceau où
vivre. scenes_of les garde ; _inject_scenes ne les impose jamais à un morceau.
"""
import json
import os

from bridge import patches


def _preset():
    return {
        "id": "p1", "name": "P1",
        "guitar": {"pre": [{"type": "comp", "id": "comp-1"}],
                   "split": {"branches": [{"id": "clean", "blocks": [{"type": "amp", "id": "amp-clean", "ref": 19}]},
                                          {"id": "dirty", "blocks": [{"type": "amp", "id": "amp-dirty", "ref": 6298}]}]},
                   "post": [{"type": "delay", "id": "delay-1"}]},
        "scenes": [
            {"id": "A", "name": "Creepy Intro", "blocks": {"delay-1": True}, "lanes": {"clean": {"mute": False}, "dirty": {"mute": True}}, "levels": {"guitar": -4}},   # `lanes` LEGACY : doit se lire encore
            {"id": "B", "name": "  ", "blocks": {"delay-1": False}, "levels": {"guitar": -2}},   # nom vide = pas de nom
            {"id": "C", "blocks": {"comp-1": False}, "levels": {"guitar": 0}},
        ],
    }


def test_scenes_of_garde_le_nom():
    sl = patches.scenes_of(_preset(), "guitar")
    by = {e["id"]: e for e in sl}
    assert by["A"]["name"] == "Creepy Intro"
    assert "name" not in by["B"]          # un nom blanc n'est pas un nom
    assert "name" not in by["C"]
    assert by["A"]["branches"] == {"clean": {"mute": False}, "dirty": {"mute": True}} and "lanes" not in by["A"]


def test_create_puis_relecture_conserve_les_noms(tmp_path, monkeypatch):
    monkeypatch.setattr(patches, "PATCHES_DIR", str(tmp_path))
    doc = patches.create_from_lane(_preset(), "guitar", name="ZZ test")
    again = json.load(open(os.path.join(str(tmp_path), doc["id"] + ".json")))
    assert [s.get("name") for s in again["scenes"]] == ["Creepy Intro", None, None]


def test_inject_n_impose_jamais_un_nom_au_morceau():
    song = _preset()
    song["scenes"][0]["name"] = "Verse"          # le morceau a SON nom
    song["scenes"][2].pop("name", None)            # C n'a pas de nom
    slice_ = [{"id": "A", "name": "Creepy Intro", "blocks": {"delay-1": False}},
              {"id": "C", "name": "Bridge Swoosh", "blocks": {"comp-1": True}}]
    created = patches._inject_scenes(song, "guitar", slice_, patches.chain_of(song, "guitar"))
    assert created == []                                       # A et C existent : rien de créé
    assert song["scenes"][0]["name"] == "Verse"                 # gardé
    assert song["scenes"][0]["blocks"]["delay-1"] is False      # le comportement, lui, est injecté
    assert "name" not in song["scenes"][2]                      # pas inventé non plus
    assert song["scenes"][2]["blocks"]["comp-1"] is True
