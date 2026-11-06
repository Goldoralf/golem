# SPDX-License-Identifier: GPL-3.0-or-later
"""Les batteries arrivent AVEC le rack (docs/drums-kit.md §2, 2026-09-15) : graines versionnées
dans library/kits-factory/, ressemées au démarrage si elles manquent, ni créées ni importées ni
supprimées depuis un écran. Le 2 août, un git rm avait vidé library/kits/ six semaines sans signal."""

import json
import os

from bridge import config as C, kits


def _kits_dir(tmp_path, monkeypatch):
    d = tmp_path / "kits"; d.mkdir()
    monkeypatch.setattr(kits, "KITS_DIR", str(d))
    return d


def test_les_graines_sont_quatre_batteries_valides():
    seeds = {s["id"]: s for s in kits.factory_seeds()}
    assert set(seeds) == {"drums-black-pearl", "drums-red-zeppelin", "drums-blonde-bop", "drums-aasimonster",
                          "pads-house", "pads-lofi", "pads-trap"}   # + les kits de PADS d'usine (2026-10-13)
    for s in seeds.values():
        if s["id"].startswith("pads-"):
            # un kit de PADS d'usine : 16 pads one-shot (banques A et B de l'AKAI), sons livrés sous assets/samples
            assert s["factory"] is True and s["role"] == "pad" and s["engine"] == "rs5k"
            assert [p["note"] for p in s["pads"]] == list(kits.DEFAULT_NOTES)      # GM, au placement MPC
            gm = {"kick": 36, "snare": 38, "hat_closed": 42, "hat_open": 46, "clap": 39, "rim": 37, "tom_mid": 45,
                  "crash": 49, "kick_sub": 35, "hat_pedal": 44, "tom_low": 41, "tom_high": 48, "ride": 51,
                  "crash2": 57, "ride_bell": 53, "cowbell": 56}
            for p in s["pads"]:                                                      # chaque SON sur SA note GM
                snd = os.path.basename(p["sample"])[3:-4]
                assert gm[snd] == p["note"], f"{s['id']} : {snd} sur {p['note']}"
            assert all(p["mode"] == "oneshot" and p["sample"].startswith("assets/samples/kits/") for p in s["pads"])
            assert all(os.path.isfile(os.path.join(C.ROOT, p["sample"])) for p in s["pads"])
            continue
        assert s["factory"] is True and s["role"] == "drum" and s["engine"] in kits.DRUM_ENGINES
    for sid in ("drums-black-pearl", "drums-red-zeppelin", "drums-blonde-bop"):
        assert seeds[sid]["engine"] == "avldrums" and seeds[sid]["bank"] in kits.AVL_BANKS
    a = seeds["drums-aasimonster"]
    assert a["engine"] == "drumgizmo" and len(a["mix"]) == 16 and a["drumkit"].startswith("library/drumkits")


def test_seed_factory_ressemme_ce_qui_manque_et_ne_touche_pas_au_reste(tmp_path, monkeypatch):
    d = _kits_dir(tmp_path, monkeypatch)
    json.dump({"id": "mypads", "name": "Mine", "engine": "rs5k", "pads": []}, open(d / "mypads.json", "w"))
    # un doc du même id posé par l'ancien créateur, sans drapeau : remplacé par la graine
    json.dump({"id": "drums-black-pearl", "name": "BP alias", "engine": "avldrums", "bank": "black-pearl"}, open(d / "drums-black-pearl.json", "w"))
    done = kits.seed_factory()
    assert sorted(done) == ["drums-aasimonster", "drums-black-pearl", "drums-blonde-bop", "drums-red-zeppelin",
                            "pads-house", "pads-lofi", "pads-trap"]
    assert json.load(open(d / "drums-black-pearl.json"))["name"] == "Black Pearl"
    assert json.load(open(d / "mypads.json"))["name"] == "Mine"
    assert kits.seed_factory() == []                                   # idempotent
    ks = {k["id"]: k for k in kits.list_kits()}
    assert ks["drums-aasimonster"]["factory"] is True and ks["mypads"]["factory"] is False


def test_une_batterie_ne_se_supprime_ni_ne_se_cree_depuis_un_ecran(tmp_path, monkeypatch):
    d = _kits_dir(tmp_path, monkeypatch)
    kits.seed_factory()
    r = kits.delete_kit("drums-red-zeppelin")
    assert r["ok"] is False and r.get("factory") is True and (d / "drums-red-zeppelin.json").exists()
    r2 = kits.save_kit({"id": "bp-alias", "name": "alias", "role": "drum", "engine": "avldrums", "bank": "black-pearl"})
    assert r2["ok"] is False and "ships with the rack" in r2["error"]
    assert kits.save_kit({"id": "x", "name": "x", "role": "drum", "engine": "avldrums", "bank": "black-pearl"}, allow_drums=True)["ok"]
    # un kit de pads garde son cycle complet
    assert kits.save_kit({"id": "pads1", "name": "Pads", "engine": "rs5k", "pads": []})["ok"]
    assert kits.delete_kit("pads1")["ok"] is True
