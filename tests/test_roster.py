# SPDX-License-Identifier: GPL-3.0-or-later
"""Réconciliation du roster (bridge/roster.py) — sans serveur, sans disque pour l'essentiel.

Ce qui est vérifié ici est ce qui coûte cher quand ça rate : une synchro qui rebascule
l'espace de la salle, un seed qui ne retrouve pas son id (et 30 prises qui ne montent
jamais), un espace disparu qui laisse le rack sans repli.
Lancer : .venv/bin/python -m pytest tests/test_roster.py -q
"""
import json

import pytest

from bridge import roster, takes


PERSO = {"id": "b_djsqupcj2e", "slug": "earthismyspaceship", "kind": "personal",
         "name": "Earth is my Spaceship",
         "people": [{"id": "alex", "name": "Alex", "roles": ["guitar", "voice"]}]}
BAND = {"id": "b_haw6vqzh5u", "slug": "night-shift", "kind": "band", "name": "Night Shift",
        "people": [{"id": "alex", "name": "Alex", "roles": ["guitar"]},
                   {"id": "sam", "name": "Sam", "roles": ["drums"]}]}
SERVED = {"synced": "2026-09-07T10:00:00Z", "default": PERSO["id"], "bands": [PERSO, BAND]}
SEED = {"id": "night-shift", "name": "Night Shift", "source": "local-temporary"}


def test_le_courant_est_preserve_par_son_id():
    """La synchro remplace le catalogue, pas le choix de la salle."""
    cache = {"band": {"id": BAND["id"], "name": "Night Shift", "source": "cache"}}
    d, rep = roster.reconcile(SERVED, cache)
    assert rep["current"] == BAND["id"] and rep["fallback"] is None
    assert d["band"]["id"] == BAND["id"]
    assert [b["id"] for b in d["bands"]] == [PERSO["id"], BAND["id"]]


def test_les_champs_de_transition_du_serveur_sont_ignores():
    """⚠ Le serveur sert encore `band`/`people` À LA RACINE (ils reprennent `default`, donc le
    rattachement de l'APPAREIL). Les lire ferait rebasculer la salle à chaque synchro."""
    payload = {**SERVED, "band": PERSO, "people": PERSO["people"]}
    cache = {"band": {"id": BAND["id"], "name": "Night Shift", "source": "cache"}}
    d, rep = roster.reconcile(payload, cache)
    assert rep["current"] == BAND["id"]                       # pas PERSO, malgré le payload
    assert [p["id"] for p in d["people"]] == ["alex", "sam"]  # le miroir suit le COURANT


def test_le_seed_retrouve_son_vrai_id():
    """`night-shift` (frappé à la main) -> `b_haw6vqzh5u` (opaque, serveur)."""
    d, rep = roster.reconcile(SERVED, {"band": dict(SEED), "bands": [dict(SEED)]})
    assert rep["readdress"] == {"from": "night-shift", "to": BAND["id"]}
    assert d["band"]["id"] == BAND["id"] and d["band"]["source"] == "cache"


def test_le_seed_matche_malgre_un_tiret():
    """Un seed « night-shift » face à un slug « nightshift » ne doit pas coûter 30 prises."""
    served = {**SERVED, "bands": [PERSO, {**BAND, "slug": "nightshift"}]}
    _, rep = roster.reconcile(served, {"band": dict(SEED)})
    assert rep["readdress"]["to"] == BAND["id"]


def test_deux_candidats_ne_readressent_rien():
    """L'ambiguïté redevient un tap : mieux vaut un espace « inconnu » qu'un mauvais espace."""
    jumeau = {"id": "b_autre", "slug": "night-shift", "kind": "band", "name": "Night Shift"}
    served = {**SERVED, "bands": [PERSO, BAND, jumeau]}
    d, rep = roster.reconcile(served, {"band": dict(SEED)})
    assert rep["readdress"] is None
    assert rep["current"] == PERSO["id"] and rep["fallback"] == "default"   # repli, pas un choix


def test_un_espace_disparu_replie_sur_le_default():
    d, rep = roster.reconcile(SERVED, {"band": {"id": "b_parti", "name": "Ancien",
                                                "source": "cache"}})
    assert rep["fallback"] == "default" and d["band"]["id"] == PERSO["id"]


def test_repli_personal_quand_le_default_est_inconnu():
    served = {**SERVED, "default": "b_inexistant"}
    _, rep = roster.reconcile(served, {"band": {"id": "b_parti", "source": "cache"}})
    assert rep["fallback"] == "personal" and rep["current"] == PERSO["id"]


def test_aucun_groupe_est_un_choix_respecte():
    """« Aucun » veut dire : les prises attendent ici. Une synchro ne le défait pas."""
    d, rep = roster.reconcile(SERVED, {"band": None})
    assert rep["current"] is None and d["band"] is None and d["people"] == []


def test_premier_appairage_prend_le_default():
    d, rep = roster.reconcile(SERVED, {})
    assert rep["current"] == PERSO["id"] and d["band"]["id"] == PERSO["id"]


def test_readdress_des_prises_garde_la_provenance(tmp_path, monkeypatch):
    """Les 30 prises taguées « night-shift » suivent le seed, et disent d'où elles viennent."""
    monkeypatch.setattr(takes, "RECORDINGS", str(tmp_path))
    for name, band in (("perf-20260804-192024", dict(SEED)),
                       ("perf-20260804-193706", dict(SEED)),
                       ("perf-20260804-194000", None)):          # « Aucun » : ne bouge pas
        d = tmp_path / name
        d.mkdir()
        (d / "Input-1.wav").write_bytes(b"RIFF")
        json.dump({"kind": "take", "band": band, "files": ["Input-1.wav"]},
                  open(d / "take.json", "w"))

    tag = {"id": BAND["id"], "name": "Night Shift", "source": "cache"}
    assert takes.readdress("night-shift", tag) == 2

    man = json.load(open(tmp_path / "perf-20260804-192024" / "take.json"))
    assert man["band"] == tag
    assert man["band_history"][0]["band"]["id"] == "night-shift"
    assert man["band_history"][0]["why"] == "seed-readdress"
    assert json.load(open(tmp_path / "perf-20260804-194000" / "take.json"))["band"] is None


def test_sync_hors_ligne_ne_touche_a_rien(monkeypatch, tmp_path):
    """Serveur injoignable : le cache fait foi, et on le dit — on ne l'efface pas."""
    f = tmp_path / ".band.json"
    f.write_text(json.dumps({"band": dict(SEED)}))
    monkeypatch.setattr(roster, "FILE", str(f))
    from bridge import golemfm
    monkeypatch.setattr(golemfm, "band_fetch", lambda: (0, "not paired"))
    rep = roster.sync()
    assert rep["ok"] is False
    assert json.load(open(f))["band"]["id"] == "night-shift"
