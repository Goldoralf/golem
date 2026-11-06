# SPDX-License-Identifier: GPL-3.0-or-later
"""Le PATCH DE KIT — un patch batterie porte le kit entier (docs/drums-kit.md §6.7).

« sans créer N patchs de batterie ». Ce que ces tests gardent :
  - les autres rôles ne changent pas d'un octet (`elements` absent = tout comme avant) ;
  - un élément sans lane est SAUTÉ ET NOMMÉ, jamais perdu en silence ;
  - « éléments sautés » ne voyage pas dans « scènes perdues » — deux natures, deux champs.
"""
import json
import os

import pytest

from bridge import patches as P


@pytest.fixture
def kit_preset():
    """Un preset avec un groupe de trois éléments, plus une lane de guitare pour vérifier
    qu'on ne déborde jamais du groupe."""
    def lane(lid, el, ch):
        return {"id": lid, "role": "drums", "in_sel": ch, "name": el,
                "drumset": "mps", "drumset_module": "millenium-mps1000", "element": el,
                "chain": {"pre": [], "split": None, "post": []}}
    return {"id": "song", "name": "Song", "lanes_v": 2, "scenes": [{"id": "A", "name": "base"}],
            "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1",
                       "chain": {"pre": [], "split": None, "post": []}},
                      lane("kick", "kick", "2"), lane("snare", "snare", "3"),
                      lane("mix", "kit-mix", "7-8")]}


def _write_patch(tmp_dir, doc):
    os.makedirs(tmp_dir, exist_ok=True)
    with open(os.path.join(tmp_dir, doc["id"] + ".json"), "w", encoding="utf8") as fh:
        json.dump(doc, fh)
    P._cache.clear()


@pytest.fixture
def kit_patch(tmp_path, monkeypatch):
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    doc = {"id": "marcs-kit", "name": "Marc's kit", "role": "drums", "elements": [
        {"element": "kick", "chain": {"pre": [{"id": "g1", "type": "gate"}], "split": None, "post": []}},
        {"element": "snare", "chain": {"pre": [{"id": "c1", "type": "comp"}], "split": None, "post": []}},
        {"element": "ride", "chain": {"pre": [{"id": "e1", "type": "eq"}], "split": None, "post": []}},
    ]}
    _write_patch(d, doc)
    return doc


def test_un_patch_de_kit_se_reconnait():
    assert P.is_kit_patch({"role": "drums", "elements": [{"element": "kick"}]}) is True
    assert P.is_kit_patch({"role": "drums", "chain": {}}) is False
    assert P.is_kit_patch({"role": "drums", "elements": []}) is False


def test_chaque_element_va_sur_SA_lane(kit_preset, kit_patch):
    p, realm, lost, added, skipped = P.apply_to(kit_preset, "marcs-kit")
    by = {L["id"]: L for L in p["lanes"]}
    assert [b["type"] for b in by["kick"]["chain"]["pre"]] == ["gate"]
    assert [b["type"] for b in by["snare"]["chain"]["pre"]] == ["comp"]
    # la guitare n'est pas touchée : un patch de kit ne déborde pas de son groupe
    assert by["guitar-1"]["chain"]["pre"] == []
    assert lost == []


def test_un_element_sans_lane_est_SAUTE_ET_NOMME(kit_preset, kit_patch):
    """Le batteur a câblé kick et snare, pas le ride. Il doit le LIRE."""
    _p, _realm, _lost, _added, skipped = P.apply_to(kit_preset, "marcs-kit")
    assert skipped == ["ride"]


def test_les_elements_sautes_ne_sont_PAS_des_scenes_perdues(kit_preset, kit_patch):
    """Deux natures, deux champs : « 1 scene lost » pour un ride non câblé serait un mensonge."""
    _p, _realm, lost, _added, skipped = P.apply_to(kit_preset, "marcs-kit")
    assert skipped and lost == []


def test_un_preset_sans_groupe_recoit_le_kit_sur_ses_entrees_libres(kit_patch, monkeypatch):
    """CORRIGÉ le 2026-09-30 (docs/patches.md §9 bis, garantie 10) : avant, un morceau sans groupe
    REFUSAIT le kit. Maintenant le kit arrive en entier, une lane par élément sur l'entrée libre suivante
    de la carte, dans l'ordre du kit ; les lanes en trop attendent leur carte — jamais deux sur la même."""
    from bridge.state import state
    monkeypatch.setattr(state, "inputmap", {"inputs": [{"ch": "1", "role": "guitar"}, {"ch": "2"}, {"ch": "3"}]}, raising=False)
    plain = {"id": "s", "lanes_v": 2, "scenes": [{"id": "A"}],
             "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1",
                        "chain": {"pre": [], "split": None, "post": []}}]}
    p, _realm, lost, added, skipped = P.apply_to(plain, "marcs-kit")
    kit = [L for L in p["lanes"] if L.get("drumset")]
    els = [e["element"] for e in P.get_patch("marcs-kit")["elements"]]
    assert [L["element"] for L in kit] == els and skipped == []
    ins = [L["in_sel"] for L in kit]
    assert ins[:2] == ["2", "3"] and all(i == "NONE" for i in ins[2:])          # l'entrée 1 est prise
    assert plain["lanes"][0]["id"] == "guitar-1" and len(plain["lanes"]) == 1  # le brouillon d'entrée intact


def test_un_patch_ORDINAIRE_passe_par_le_chemin_d_avant(tmp_path, monkeypatch):
    """La garde du lot D : `elements` absent, rien ne change pour les autres rôles."""
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    _write_patch(d, {"id": "vx", "name": "Vx", "role": "voice",
                     "chain": {"chain": [{"id": "r1", "type": "reverb"}]}})
    song = {"id": "s", "lanes_v": 2, "scenes": [{"id": "A"}],
            "lanes": [{"id": "voice-1", "role": "voice", "in_sel": "2",
                       "chain": {"pre": [], "split": None, "post": []}}]}
    p, realm, _lost, _added, skipped = P.apply_to(song, "vx")
    assert realm == "voice-1" and skipped == []
    assert [b["type"] for b in p["lanes"][0]["chain"]["pre"]] == ["reverb"]


# ── l'écriture ───────────────────────────────────────────────────────────────────────────────
def test_sauver_le_groupe_donne_un_patch_a_elements(kit_preset, tmp_path, monkeypatch):
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    kit_preset["lanes"][1]["chain"]["pre"] = [{"id": "g1", "type": "gate"}]
    doc = P.save_kit_patch("marc", kit_preset, "mps", name="Marc's kit")
    assert doc["role"] == "drums"
    assert [e["element"] for e in doc["elements"]] == ["kick", "snare", "kit-mix"]
    # PAS de `chain` : la porter à vide ferait lire un patch mono-lane aux lecteurs d'avant
    assert "chain" not in doc


def test_une_lane_sans_bloc_reste_dans_le_kit(kit_preset, tmp_path, monkeypatch):
    """Un élément branché sans traitement fait partie du kit — le sauter le ferait disparaître."""
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    kit_preset["lanes"][1]["chain"]["pre"] = [{"id": "g1", "type": "gate"}]
    doc = P.save_kit_patch("marc", kit_preset, "mps")
    assert len(doc["elements"]) == 3


def test_un_kit_SANS_BLOC_se_sauve_quand_meme(kit_preset, tmp_path, monkeypatch):
    """Contrairement à un patch de lane : un kit sans bloc porte déjà le CÂBLAGE (quel élément sur
    quelle entrée), qu'on repose ailleurs d'un geste. Et l'auto-save part juste après « Add 8
    lanes » — refuser là afficherait « patch not saved » sur un kit qu'on vient de poser."""
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    doc = P.save_kit_patch("marc", kit_preset, "mps")
    assert [e["element"] for e in doc["elements"]] == ["kick", "snare", "kit-mix"]


def test_un_preset_sans_groupe_refuse_de_sauver(tmp_path, monkeypatch):
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    plain = {"id": "s", "lanes_v": 2, "lanes": [{"id": "g", "role": "guitar", "in_sel": "1",
                                                 "chain": {"pre": [], "split": None, "post": []}}]}
    with pytest.raises(ValueError, match="no drum kit group"):
        P.save_kit_patch("marc", plain, "mps")


def test_rien_n_a_bouge_pas_de_reecriture(kit_preset, tmp_path, monkeypatch):
    """L'auto-save frappe à chaque touche : réécrire le fichier pour rien userait le disque et
    ferait clignoter le catalogue."""
    d = str(tmp_path / "patches")
    monkeypatch.setattr(P, "PATCHES_DIR", d)
    monkeypatch.setattr(P, "_path", lambda pid: os.path.join(d, P._safe_id(pid) + ".json"))
    P.save_kit_patch("marc", kit_preset, "mps")
    mt = os.path.getmtime(P._path("marc"))
    P.save_kit_patch("marc", kit_preset, "mps")
    assert os.path.getmtime(P._path("marc")) == mt
