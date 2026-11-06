# SPDX-License-Identifier: GPL-3.0-or-later
"""Les INSTANTANÉS de setlist (docs/setlists.md §7, audit 2026-10-15). Ce que ces tests gardent : une ligne de bank
de sons (`patch:<id>`) est figée comme PATCH et revient comme patch — jamais en preset `patch<id>.json` ; les lignes
(titre, bpm, arrangement) sont figées avec l'ordre ; un son modifié depuis l'instantané n'est JAMAIS écrasé sans
`overwrite` — les conflits reviennent AVANT toute écriture ; les erreurs dites à l'API sont en anglais."""
import json
import os

import pytest

from bridge import config as C, patches as P, setlists as SL, store


@pytest.fixture
def rack(tmp_path, monkeypatch):
    for d in ("setlists", "presets", "patches", "config"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path / "setlists"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(SL, "SNAP_DIR", str(tmp_path / "setlists" / "snapshots"))
    monkeypatch.setattr(P, "PATCHES_DIR", str(tmp_path / "patches"))
    # les configs des blocs singletons (Rec, Click, Compo) sont des chemins figés à l'import de store : CONFIG_DIR
    # redirigé ne les suit pas, et enregistrer un preset créait config/recorder.json, compo.json et click.json du dépôt
    for k, name in (("RECORDER_CFG", "recorder.json"), ("CLICK_CFG", "click.json"), ("COMPO_CFG", "compo.json")):
        monkeypatch.setattr(store, k, str(tmp_path / "config" / name))
    P._cache.clear()
    json.dump({"id": "doom", "name": "Doom", "role": "guitar", "chain": {"chain": [{"id": "g-1", "type": "gate"}]},
               "scenes": []}, open(tmp_path / "patches" / "doom.json", "w"))
    store._write_json_atomic(os.path.join(C.PRESETS_DIR, "kite.json"), {"id": "kite", "name": "Paper Kite"})
    return tmp_path


def _frozen(rack, snid):
    return json.load(open(rack / "setlists" / "snapshots" / f"{snid}.json"))


def test_une_bank_de_sons_fige_et_rend_ses_patches(rack):
    b = SL.add_patches(SL.create("Sounds", kind="sounds")["id"], ["doom"])
    snap = SL.snapshot(b["id"])
    assert snap["ok"] and snap["frozen"] == 1
    d = _frozen(rack, snap["id"])
    assert d["presets"][0]["id"] == "patch:doom" and d["presets"][0]["patch"]["name"] == "Doom"
    os.remove(rack / "patches" / "doom.json"); P._cache.clear()
    r = SL.restore(snap["id"])
    assert r["ok"] and r["patches"] == ["doom"] and r["presets"] == []
    assert P.get_patch("doom")["name"] == "Doom"
    assert not os.path.exists(rack / "presets" / "patchdoom.json")              # jamais un preset fantôme
    sl = SL.load(r["setlist"])
    assert sl["kind"] == "sounds" and sl["presets"] == ["patch:doom"]


def test_un_ancien_instantane_ne_fabrique_pas_de_preset_patch(rack):
    """Avant le correctif, `patch:doom` était figé en preset composé : on ne le restaure PAS en `patchdoom.json`."""
    os.makedirs(SL.SNAP_DIR)
    json.dump({"id": "old", "kind": "snapshot", "of": "s", "name": "Old", "order": ["patch:doom"],
               "presets": [{"id": "patch:doom", "preset": {"id": "patch:doom", "name": "Doom"}}], "missing": []},
              open(os.path.join(SL.SNAP_DIR, "old.json"), "w"))
    r = SL.restore("old")
    assert r["ok"] and r["skipped"] == ["patch:doom"] and r["presets"] == []
    assert os.listdir(rack / "presets") == ["kite.json"]
    assert SL.load(r["setlist"])["presets"] == ["patch:doom"]


def test_les_lignes_sont_figees_avec_l_ordre(rack):
    sl = SL.create("Gig", ["kite"])
    sl["lines"][0].update(title="Paper Kite (live)", bpm=93, arrangement={"params": {"sections": [{"name": "Intro"}]}})
    sl = SL.save(sl)
    snap = SL.snapshot(sl["id"])
    sl["lines"][0].update(title="changed", bpm=120)
    SL.save(sl)
    r = SL.restore(snap["id"])
    ln = SL.load(r["setlist"])["lines"][0]
    assert (ln["title"], ln["bpm"], ln["preset"]) == ("Paper Kite (live)", 93, "kite")
    assert ln["arrangement"]["params"] == {"sections": [{"name": "Intro"}]}
    assert ln["id"] != sl["lines"][0]["id"]                                       # liste neuve, ids neufs


def test_un_conflit_est_dit_avant_d_ecraser(rack):
    sl = SL.create("Gig", ["kite"])
    snap = SL.snapshot(sl["id"])
    store._write_json_atomic(os.path.join(C.PRESETS_DIR, "kite.json"), {"id": "kite", "name": "Edited since"})
    n_lists = len(SL.list_all())
    r = SL.restore(snap["id"])
    assert not r["ok"] and r["conflicts"] == ["kite"] and "overwritten" in r["error"]
    assert store.load_preset("kite")["name"] == "Edited since"                 # rien n'a été écrit
    assert len(SL.list_all()) == n_lists                                         # ni setlist créée
    r = SL.restore(snap["id"], overwrite=True)
    assert r["ok"] and r["overwritten"] == ["kite"]
    assert store.load_preset("kite")["name"] == "Paper Kite"


def test_un_patch_modifie_est_un_conflit(rack):
    b = SL.add_patches(SL.create("Sounds", kind="sounds")["id"], ["doom"])
    snap = SL.snapshot(b["id"])
    P._write({**P.get_patch("doom"), "name": "Doom v2"})
    r = SL.restore(snap["id"])
    assert not r["ok"] and r["conflicts"] == ["patch:doom"]
    assert P.get_patch("doom")["name"] == "Doom v2"


def test_sans_changement_pas_de_conflit(rack):
    snap = SL.snapshot(SL.create("Gig", ["kite"])["id"])
    assert SL.restore(snap["id"])["ok"]


def test_les_erreurs_dites_a_l_api_sont_en_anglais(rack):
    assert SL.snapshot("nope")["error"] == "setlist not found"
    assert SL.restore("nope")["error"] == "snapshot not found"
    assert SL.set_active("nope")["error"] == "unknown setlist: nope"
    assert SL.remove("nope")["error"] == "setlist not found"
    sl = SL.create("Gig", [])
    SL.set_active(sl["id"])
    assert "on the pedalboard" in SL.remove(sl["id"])["error"]
