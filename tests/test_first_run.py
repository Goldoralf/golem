# SPDX-License-Identifier: GPL-3.0-or-later
"""L'instrument choisi à l'installation (bridge/first_run.py, écran « What do you play? », 2026-10-27) : l'entrée 1
d'une carte neuve, la banque d'usine au pied, la banque guitare ouverte sur sa première entrée — sans rien écraser."""
import json
import os

import pytest

from bridge import cards, first_run, inputmap, setlists, startup_home as SH


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    monkeypatch.setattr("bridge.config.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(setlists, "ACTIVE_CFG", str(tmp_path / "setlist.json"))
    monkeypatch.setattr(SH, "PATH", str(tmp_path / ".startup.json"))
    monkeypatch.setattr(SH, "_cache", {"mtime": None, "doc": None})
    banks = {"factory-guitar", "factory-bass", "factory-keys", "factory-drums", "factory-voice", "mine"}
    monkeypatch.setattr(setlists, "_path", lambda sid: str(tmp_path / "sl" / f"{sid}.json"))
    os.makedirs(tmp_path / "sl")
    for b in banks:
        (tmp_path / "sl" / f"{b}.json").write_text("{}")
    monkeypatch.setattr(cards, "known", lambda cid: {"id": cid, "inputs": 2, "outputs": 2})
    monkeypatch.setattr(cards, "probe", lambda cid: None)

    def first(instrument):
        (tmp_path / "first-run.json").write_text(json.dumps({"instrument": instrument}))
    first.dir = tmp_path
    return first


def test_guitare_banque_guitare_ouverte_sur_sa_premiere_entree(cfg):
    cfg("guitar")
    done = first_run.apply()
    assert "bank factory-guitar" in done and "startup factory-guitar" in done
    assert setlists.active_id() == "factory-guitar"
    h = SH.get()
    assert h["policy"] == "home" and h["home"] == {"kind": "setlist", "id": "factory-guitar", "name": "Factory Guitar"}
    assert not os.path.exists(cfg.dir / "first-run.json")        # une seule fois
    assert first_run.apply() is None


@pytest.mark.parametrize("inst, in1, in2", [("guitar", "guitar", "voice"), ("bass", "bass", "voice"),
                                            ("voice", "voice", "none"), ("keys", "guitar", "voice"),
                                            ("drums", "guitar", "voice")])
def test_l_entree_1_suit_l_instrument_claviers_et_batterie_restent_guitare(cfg, inst, in1, in2):
    cfg(inst)
    first_run.apply()
    assert first_run.instrument() == inst
    volt = inputmap._seed("hw:V276")
    assert [i["role"] for i in volt["inputs"]] == [in1, in2]
    assert inputmap._seed("hw:Other")["inputs"][0]["role"] == in1


def test_basse_sa_banque_et_pas_d_accueil(cfg):
    cfg("bass")
    first_run.apply()
    assert setlists.active_id() == "factory-bass" and SH.get()["policy"] == "bank0"


def test_une_reinstallation_n_ecrase_ni_la_liste_au_pied_ni_l_accueil(cfg):
    setlists.set_active("mine")
    SH.set_home({"kind": "preset", "id": "velvetine", "name": "Velvetine"})
    cfg("guitar")
    done = first_run.apply()
    assert setlists.active_id() == "mine" and SH.get()["home"]["id"] == "velvetine"
    assert done == ["instrument guitar"] and first_run.instrument() == "guitar"


def test_sans_installateur_rien_ne_change(cfg):
    assert first_run.apply() is None and first_run.instrument() is None
    assert inputmap._seed("hw:Other")["inputs"][0]["role"] == "guitar"


def test_un_instrument_inconnu_est_ignore_et_le_fichier_retire(cfg):
    cfg("theremin")
    assert first_run.apply() == ["unknown instrument 'theremin' ignored"]
    assert first_run.instrument() is None and not os.path.exists(cfg.dir / "first-run.json")
