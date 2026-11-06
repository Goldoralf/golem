# SPDX-License-Identifier: GPL-3.0-or-later
"""Régression 2026-10-15 → 2026-10-23 : une prise de « Rooftop Prowl » sans la guitare (IN 2), ni en piste ni dans le
Mix. Les presets d'usine portent un bloc Rec figé « IN 1 oui, IN 2 non » ; chaque écriture du brouillon ou sauvegarde
de l'un d'eux recopiait ces cases dans config/recorder.json. Seule une case réellement changée doit y monter."""
import pytest
from bridge import store


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "recorder.json"))
    monkeypatch.setattr(store, "CLICK_CFG", str(tmp_path / "click.json"))
    monkeypatch.setattr(store, "COMPO_CFG", str(tmp_path / "compo.json"))
    store.save_recorder_cfg({"in1": True, "in2": True, "usb": False})
    return tmp_path


def _preset(pid, **rec):
    return {"id": pid, "config": {"gen": {"blocks": []},
                                  "rec": {"blocks": [{"id": "rec-global", "type": "rec", "params": dict(rec)}]}}}


def _set(p, **rec):
    next(b for b in p["config"]["rec"]["blocks"] if b["type"] == "rec")["params"].update(rec)
    return p


def test_un_preset_d_usine_ouvert_ne_decoche_plus_la_guitare(cfg):
    factory = _preset("factory-chill-jazz", in1=True, in2=False, usb=False)        # tel que sur le disque
    store.save_recorder_cfg_from(factory, prev=_preset("paper-kite", in1=True, in2=True))   # on le CHARGE
    assert store.load_recorder_cfg()["in2"] is True
    store.save_recorder_cfg_from(factory, prev=factory)                              # on l'édite ailleurs
    assert store.load_recorder_cfg()["in2"] is True


def test_une_case_cochee_dans_la_feuille_vaut_toujours(cfg):
    before = _preset("p", in1=True, in2=True, usb=False)
    after = _set(_preset("p", in1=True, in2=True, usb=False), in1=False)
    store.save_recorder_cfg_from(after, prev=before)
    got = store.load_recorder_cfg()
    assert got["in1"] is False and got["in2"] is True                                # seule la case touchée


def test_sans_brouillon_d_avant_l_extraction_reste_entiere(cfg):
    # migrate_config (1re rencontre d'un Rec legacy) et les appels historiques passent sans `prev`
    store.save_recorder_cfg_from(_preset("p", in1=False, in2=True, usb=True))
    got = store.load_recorder_cfg()
    assert (got["in1"], got["in2"], got["usb"]) == (False, True, True)
