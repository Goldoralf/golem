# SPDX-License-Identifier: GPL-3.0-or-later
"""Les BANKS DE SONS (docs/patches.md §7, lot 4) et la liste au pied du MODE. Ce que ces tests gardent :
une setlist porte `kind`, fixé à la création, et ne mélange jamais morceaux et sons ; une ligne de bank joue
`patch:<id>` et porte toujours un titre ; supprimer un patch libère sa ligne sans l'effacer ; une bank reçue
de golem.fm garde sa nature ; un mode met SA liste au pied en entrant, et dit quand elle a disparu ; la puce se
compile d'après la liste AU PIED, pas d'après fcb-banks.json."""
import json
import os
import sys

import pytest

from bridge import config as C, modes, patches as P, recall, setlists as SL


@pytest.fixture
def rack(tmp_path, monkeypatch):
    sdir = tmp_path / "setlists"; sdir.mkdir()
    pdir = tmp_path / "patches"; pdir.mkdir()
    cdir = tmp_path / "config"; cdir.mkdir()
    monkeypatch.setattr(C, "SETLISTS_DIR", str(sdir))
    monkeypatch.setattr(C, "CONFIG_DIR", str(cdir))
    monkeypatch.setattr(P, "PATCHES_DIR", str(pdir))
    P._cache.clear()
    for pid, name in (("doom", "Doom"), ("clean", "Clean Twin")):
        json.dump({"id": pid, "name": name, "role": "guitar", "chain": {"chain": [{"id": "g-1", "type": "gate"}]}, "scenes": []},
                  open(pdir / f"{pid}.json", "w"))
    return tmp_path


def test_une_bank_de_sons_joue_des_patches_et_porte_leurs_titres(rack):
    b = SL.create("My sounds", kind="sounds")
    assert b["kind"] == "sounds" and b["lines"] == []
    b = SL.add_patches(b["id"], ["doom", "clean"])
    assert [ln["patch"] for ln in b["lines"]] == ["doom", "clean"]
    assert [ln["title"] for ln in b["lines"]] == ["Doom", "Clean Twin"]              # titre toujours présent
    assert b["presets"] == ["patch:doom", "patch:clean"]                            # ce que le pied rappelle
    assert all("preset" not in ln for ln in b["lines"])


def test_morceaux_et_sons_ne_se_melangent_jamais(rack):
    songs = SL.create("Covers")
    assert songs["kind"] == "songs"                                                 # le défaut, tout ce qui existe
    with pytest.raises(ValueError, match="sound list"):
        SL.add_patches(songs["id"], ["doom"])
    bank = SL.create("Sounds", kind="sounds")
    with pytest.raises(ValueError, match="setlist of songs"):
        SL.add_songs(bank["id"], ["bs:1"])
    assert SL.add_line(bank["id"], title="A song", preset="paper-kite") is None
    with pytest.raises(ValueError, match="setlist of songs"):
        SL.set_presets(SL.load(bank["id"]), ["paper-kite"])
    with pytest.raises(ValueError, match="sound list"):
        SL.set_presets(SL.load(songs["id"]), ["patch:doom"])
    reordered = SL.set_presets(SL.load(SL.add_patches(bank["id"], ["doom", "clean"])["id"]), ["patch:clean", "patch:doom"])
    assert [ln["patch"] for ln in reordered["lines"]] == ["clean", "doom"]          # le pied réordonne une bank


def test_un_slot_de_bank_rappelle_le_patch(rack, monkeypatch):
    b = SL.add_patches(SL.create("Sounds", kind="sounds")["id"], ["doom"])
    SL.set_active(b["id"])
    assert recall._fcb_slot_pid(0) == "patch:doom"
    assert recall.slot_of_preset("patch:doom") == 0


def test_supprimer_un_patch_libere_sa_ligne_sans_leffacer(rack):
    b = SL.add_patches(SL.create("Sounds", kind="sounds")["id"], ["doom", "clean"])
    assert P.delete_patch("doom") is True
    b = SL.load(b["id"])
    assert len(b["lines"]) == 2 and "patch" not in b["lines"][0] and b["lines"][0]["title"] == "Doom"
    assert b["presets"] == ["", "patch:clean"]


def test_une_bank_recue_de_golem_fm_garde_sa_nature(rack):
    sl, _rep = SL.merge_push({"id": "gfm-bank", "name": "From the web", "kind": "sounds", "rev": 1,
                              "lines": [{"id": "l1", "rev": 1, "patch": "doom", "title": "Doom"}]})
    assert sl["kind"] == "sounds" and sl["presets"] == ["patch:doom"]


# ── la liste au pied du MODE ──────────────────────────────────────────────────────────────────
def test_foot_list_se_valide_contre_les_listes_du_rack(rack):
    b = SL.create("Sounds", kind="sounds")
    assert modes.validate_update({"foot_list": b["id"]}) == []
    assert modes.validate_update({"foot_list": None}) == []
    assert modes.validate_update({"foot_list": "nope"})[0][0] == "foot_list"
    assert modes.validate_update({"foot_list": 3})[0][0] == "foot_list"
    m = modes.apply_update({"id": "studio"}, {"foot_list": b["id"]})
    assert m["foot_list"] == b["id"] and modes.doc(m)["foot_list"] == b["id"]
    assert "foot_list" not in modes.apply_update(m, {"foot_list": ""})             # "" = le mode ne touche pas au pied


def test_entrer_dans_un_mode_met_sa_liste_au_pied_et_dit_quand_elle_a_disparu(rack):
    songs = SL.create("Covers")
    bank = SL.create("Sounds", kind="sounds")
    SL.set_active(songs["id"])
    assert modes.apply_foot_list({"id": "studio", "foot_list": bank["id"]}) == (True, None)
    assert SL.active_id() == bank["id"]
    assert modes.apply_foot_list({"id": "gig"}) == (False, None)                   # pas de foot_list : rien
    ok, why = modes.apply_foot_list({"id": "gig", "name": "Gig", "foot_list": "gone"})
    assert ok is False and "is gone" in why and SL.active_id() == bank["id"]      # le pied garde la sienne


def test_le_mode_pedalboard_met_au_pied_la_banque_de_son_instrument(rack, monkeypatch):
    """2026-10-24, un testeur Windows : Pedalboard (un instrument) mettait « Factory Golem » au pied — des chansons à
    batterie et claviers. `@instrument` = la banque de sons d'usine du premier rôle posé sur la carte (docs/modes.md §2)."""
    from bridge import inputmap
    for sid, name in (("factory-guitar", "Factory Guitar"), ("factory-bass", "Factory Bass")):
        json.dump({"id": sid, "name": name, "kind": "sounds", "presets": []}, open(rack / "setlists" / f"{sid}.json", "w"))
    card = {"inputs": [{"ch": "1", "role": "none"}, {"ch": "2", "role": "none"}, {"ch": "3", "role": "bass"}]}
    monkeypatch.setattr(inputmap, "current", lambda device=None: card)
    assert modes.validate_update({"foot_list": "@instrument"}) == []
    assert modes.resolve_foot_list("@instrument") == "factory-bass"          # la Focusrite d'un bassiste, entrée 3
    SL.set_active("factory-guitar")
    assert modes.apply_foot_list({"id": "pedalboard", "foot_list": "@instrument"}) == (True, None)
    assert SL.active_id() == "factory-bass"
    card["inputs"] = [{"ch": "1", "role": "none"}]                            # aucun rôle : la guitare
    assert modes.resolve_foot_list("@instrument") == "factory-guitar"
    card["inputs"] = [{"ch": "1", "role": "voice"}]                           # banque absente : la guitare aussi
    assert modes.resolve_foot_list("@instrument") == "factory-guitar"
    assert modes.resolve_foot_list("factory-bass") == "factory-bass"          # un id reste un id


def test_le_mode_pedalboard_livre_la_banque_de_l_instrument():
    shipped = json.load(open(os.path.join(C.ROOT, "config", "modes", "pedalboard.json"), encoding="utf-8"))
    assert shipped["foot_list"] == "@instrument"

def test_la_puce_se_compile_dapres_la_liste_au_pied(rack):
    sys.path.insert(0, os.path.join(C.ROOT, "tools", "fcb"))
    import gen_uno2_syx as G
    json.dump({"id": "fcb-banks", "name": "Repertoire", "presets": ["old-song"]}, open(rack / "setlists" / "fcb-banks.json", "w"))
    b = SL.add_patches(SL.create("Sounds", kind="sounds")["id"], ["doom"])
    SL.set_active(b["id"])
    assert G._foot_ids() == ["patch:doom"]                                          # pas fcb-banks.json


def test_le_battement_dit_la_liste_au_pied_du_mode(rack):
    from bridge import rigstatus
    SL.set_active(SL.create("Covers")["id"])                          # une autre liste au pied d'abord
    bank = SL.create("Sounds", kind="sounds")
    modes.apply_foot_list({"id": "studio", "foot_list": bank["id"]})
    assert rigstatus.light()["foot"] == {"applied": True, "why": None, "list": bank["id"]}
    modes.apply_foot_list({"id": "gig", "name": "Gig", "foot_list": "gone"})
    f = rigstatus.light()["foot"]
    assert f["applied"] is False and "is gone" in f["why"] and f["list"] == "gone"   # visible sur golem.fm
    modes.apply_foot_list({"id": "jam"})
    assert "foot" not in rigstatus.light()                                             # rien à dire


def test_une_sound_list_se_pose_sur_la_grille_avec_des_banks_libres(rack):
    """⇅ Banks et la pastille #NN d'une sound list (2026-09-30) : un patch se DÉPLACE vers une bank
    choisie, les trous du milieu restent des banks libres, les titres suivent leur patch."""
    b = SL.add_patches(SL.create("Sounds", kind="sounds")["id"], ["doom", "clean"])
    b = SL.save(SL.set_presets(SL.load(b["id"]), ["patch:doom", "", "", "patch:clean"]))
    b = SL.load(b["id"])
    assert b["presets"] == ["patch:doom", "", "", "patch:clean"]
    assert [ln.get("title") for ln in b["lines"]] == ["Doom", None, None, "Clean Twin"]
    assert all(not ln.get("patch") for ln in b["lines"][1:3])                # libres, pas des patches effacés
