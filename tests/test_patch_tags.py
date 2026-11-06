# SPDX-License-Identifier: GPL-3.0-or-later
"""Un patch se tague comme un preset (2026-09-08) : chaînes libres, dédoublonnées ; le style du
preset d'origine sème le premier tag ; le dépôt dans un morceau n'en hérite pas (le tag suit l'objet)."""
import json
import os

from bridge import patches


def _preset():
    return {"id": "p1", "name": "P1", "style": "Rock",
            "guitar": {"pre": [{"type": "comp", "id": "comp-1"}], "split": None, "post": []},
            "scenes": [{"id": "A", "name": "A", "blocks": {}, "levels": {"guitar": -4}}]}


def test_norm_tags():
    assert patches.norm_tags([" Metal ", "metal", "Metal", "", None, "lead"]) == ["Metal", "metal", "lead"]
    assert patches.norm_tags("Metal") == []


def test_le_style_seme_le_premier_tag_et_la_meta_les_edite(tmp_path, monkeypatch):
    monkeypatch.setattr(patches, "PATCHES_DIR", str(tmp_path))
    doc = patches.create_from_lane(_preset(), "guitar", name="ZZ tags", tags=["clean", "Rock"])
    assert doc["tags"] == ["Rock", "clean"]
    doc = patches.update_meta(doc["id"], tags=["clean", "live"])
    assert json.load(open(os.path.join(str(tmp_path), doc["id"] + ".json")))["tags"] == ["clean", "live"]
    doc = patches.update_meta(doc["id"], name="ZZ tags 2")        # sans `tags` : on n'y touche pas
    assert doc["tags"] == ["clean", "live"]


def test_apply_to_depose_dans_le_brouillon_sans_ecrire(tmp_path, monkeypatch):
    """Le dépôt depuis le Designer est PUR : la lane est remplacée, les scènes du patch injectées,
    les scènes absentes du morceau signalées, rien n'est écrit."""
    monkeypatch.setattr(patches, "PATCHES_DIR", str(tmp_path))
    src = _preset(); src["scenes"].append({"id": "B", "name": "B", "blocks": {"comp-1": False}})
    doc = patches.create_from_lane(src, "guitar", name="ZZ src")
    song = {"id": "song", "name": "Song", "guitar": {"pre": [{"type": "gate", "id": "gate-1"}], "split": None, "post": []},
            "scenes": [{"id": "A", "name": "Verse", "blocks": {"gate-1": False}}]}
    before = dict(song)
    p, realm, lost, added, _sk = patches.apply_to(song, doc["id"])
    assert realm == "guitar" and lost == [] and added == ["B"]   # la scène B est CRÉÉE (2026-09-08)
    assert [b["id"] for b in p["guitar"]["pre"]] == ["comp-1"]
    assert p["scenes"][0]["name"] == "Verse"                 # le morceau garde SES noms
    assert p["scenes"][1]["name"] == "B" and p["scenes"][1]["blocks"] == {"comp-1": False}
    assert song == before                                      # l'original n'est pas muté


def test_l_injection_pose_une_memoire_d_origine_pas_un_lien(tmp_path, monkeypatch):
    monkeypatch.setattr(patches, "PATCHES_DIR", str(tmp_path))
    doc = patches.create_from_lane(_preset(), "guitar", name="ZZ origin")
    song = {"id": "s", "name": "S", "guitar": {"pre": [], "split": None, "post": [], "patch": "vieux-lien"}, "scenes": [{"id": "A"}]}
    p, _, _, _, _ = patches.apply_to(song, doc["id"])
    assert p["guitar"]["patch_from"] == {"id": doc["id"], "name": "ZZ origin"}
    assert "patch" not in p["guitar"]                          # l'ancien lien mort est nettoyé
