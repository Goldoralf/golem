# SPDX-License-Identifier: GPL-3.0-or-later
"""Les incidents et comment ils ont fini (docs/assistant.md §3.1) : un fait surveillé qui passe au rouge ouvre un
incident ; il se ferme par `outside` (revenu sans rien de golem), `restart` (REAPER ou le bridge ont redémarré) ou
`action` (une réparation vérifiée) ; un tap facultatif dit ce qui l'a réparé ; la chronologie et le paquet de
session ne portent que des types et des codes. `.venv/bin/python -m pytest tests/test_incidents.py -q`"""
import json

import pytest

from bridge import config as C, diag, incidents as I
from bridge.state import state


@pytest.fixture
def rack(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(diag, "_scrubber", None)
    monkeypatch.setattr(I, "_bridge_start", lambda: 0.0)
    monkeypatch.setattr(state, "reaper_gen", 3)
    I._green.clear()
    return tmp_path


def _f(fid, level, text="x"):
    return {"id": fid, "level": level, "text": text, "name": fid}


def _twice(facts):
    """Deux passages de Health : un fait doit être rouge deux fois de suite pour ouvrir un incident."""
    I.observe(facts); I.observe(facts)


def _timeline(rack):
    p = rack / "diag" / "timeline.ndjson"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_un_fait_rouge_ouvre_un_incident_et_revient_tout_seul_en_outside(rack):
    I.observe([_f("dropouts", "bad", "14 in the last 10 min")])
    assert I.items() == [], "un seul passage rouge n'ouvre rien"
    I.observe([_f("dropouts", "bad", "15 in the last 10 min")])
    its = I.items()
    assert len(its) == 1 and its[0]["state"] == "open" and its[0]["detail"] == "15 in the last 10 min"
    I.observe([_f("dropouts", "ok")])
    assert I.items()[0]["state"] == "open", "un seul passage vert ne ferme pas (pas de clignotement)"
    I.observe([_f("dropouts", "ok")])
    inc = I.items()[0]
    assert inc["state"] == "closed" and inc["resolved_by"] == "outside" and inc["after_s"] >= 0


def test_un_orange_qui_ne_merite_pas_un_incident_n_en_ouvre_pas(rack):
    _twice([_f("dropouts", "warn"), _f("setlist", "warn"), _f("environment", "warn")])
    assert I.items() == [], "dropouts : rouge seulement ; setlist et environnement disent un état, pas une panne"
    _twice([_f("pedalboard", "warn")])
    assert I.items()[0]["code"] == "pedalboard"


def test_revenu_apres_un_redemarrage_de_reaper_c_est_restart(rack, monkeypatch):
    _twice([_f("engine", "bad")])
    monkeypatch.setattr(state, "reaper_gen", 5)
    I.observe([_f("engine", "ok")]); I.observe([_f("engine", "ok")])
    assert I.items()[0]["resolved_by"] == "restart"


def test_une_reparation_verifiee_ferme_par_action_et_garde_son_retour_arriere(rack):
    _twice([_f("dropouts", "bad")])
    iid = I.items()[0]["id"]
    rec = {"id": "f1", "action": "set_buffer", "params": {"size": 192}, "by": "button", "label": "Raise the buffer",
           "undo": {"action": "set_buffer", "params": {"size": 128}}, "text": "0 dropouts in 2 min"}
    I.fix_started(iid, rec)
    assert I.items()[0]["state"] == "verifying"
    I.observe([_f("dropouts", "ok")]); I.observe([_f("dropouts", "ok")])
    assert I.items()[0]["state"] == "verifying", "pendant la vérification, c'est la réparation qui conclut"
    I.fix_done(iid, rec, True)
    inc = I.items()[0]
    assert inc["resolved_by"] == "action" and inc["action"] == "set_buffer" and inc["by"] == "button"
    assert inc["undo"] == {"action": "set_buffer", "params": {"size": 128}}
    assert inc["attempts"][0]["ok"] is True


def test_une_reparation_ratee_rouvre_l_incident_et_garde_la_tentative(rack):
    _twice([_f("dropouts", "bad")])
    iid = I.items()[0]["id"]
    rec = {"id": "f1", "action": "set_buffer", "params": {"size": 192}, "by": "assistant", "text": "5 dropouts"}
    I.fix_started(iid, rec)
    I.fix_done(iid, rec, False)
    inc = I.items()[0]
    assert inc["state"] == "open" and inc["attempts"] == [{**inc["attempts"][0], "ok": False, "by": "assistant"}]


def test_le_tap_facultatif_ne_vaut_que_pour_un_incident_revenu_tout_seul(rack):
    _twice([_f("pedalboard", "warn")]); _twice([_f("pedalboard", "ok")])
    iid = I.items()[0]["id"]
    assert I.hint(iid, "cable")["hint"] == "cable"
    with pytest.raises(ValueError):
        I.hint(iid, "magic")
    _twice([_f("engine", "bad")])
    eng = next(i for i in I.items() if i["code"] == "engine")
    with pytest.raises(ValueError):
        I.hint(eng["id"], "cable")


def test_un_controle_a_la_demande_ouvre_et_ferme_son_incident(rack):
    I.probe("silence", "input", True, "No sound: input", "No signal reaches the input tracks.")
    I.probe("silence", "input", True, "No sound: input")
    assert len([i for i in I.items() if i["kind"] == "silence"]) == 1, "un seul incident ouvert par contrôle"
    I.probe("silence", "downstream", False)
    assert I.items()[0]["state"] == "closed"
    I.probe("first_check", "foot", True, "The pedalboard did not answer", match_code=True)
    I.probe("first_check", "input", False, match_code=True)
    assert next(i for i in I.items() if i["code"] == "foot")["state"] == "open", "un autre geste ne ferme pas celui-là"


def test_la_chronologie_et_le_paquet_ne_portent_que_des_types_et_des_codes(rack):
    _twice([_f("playing", "bad", "« Set Léa » · 1 file not loaded")])
    _twice([_f("playing", "ok")])
    _twice([_f("disk", "warn")])
    rows = _timeline(rack)
    assert [r["type"] for r in rows] == ["incident", "incident", "resolution", "incident"]
    assert "Léa" not in json.dumps(rows), "le titre et le détail restent sur la machine"
    s = I.summary(rows)
    assert s["opened"] == 2 and s["resolved"] == {"outside": 1} and s["open"][0]["code"] == "disk"
    picked = diag._pick("incidents", s)
    assert diag.violations({"incidents": picked}) == []


def test_au_demarrage_du_bridge_reaper_qui_tarde_n_est_pas_une_panne(rack, monkeypatch):
    import time
    monkeypatch.setattr(I, "_bridge_start", lambda: time.time() - 10)
    _twice([_f("engine", "warn", "started but is not answering the bridge")])
    assert I.items() == [], "constaté le 2026-10-20 : un incident à chaque reload"
    monkeypatch.setattr(I, "_bridge_start", lambda: time.time() - 60)
    _twice([_f("engine", "warn")])
    assert I.items()[0]["code"] == "engine"


def test_golem_fm_coupe_dix_secondes_n_est_pas_un_incident_et_ne_demande_pas_cable_ou_gain(rack):
    for _ in range(11):
        I.observe([_f("golemfm", "warn")])
    assert I.items() == [], "un service réseau doit rester rouge une minute"
    I.observe([_f("golemfm", "warn")])
    inc = I.items()[0]
    assert inc["code"] == "golemfm" and inc["hintable"] is False
    _twice([_f("golemfm", "ok")])
    with pytest.raises(ValueError):
        I.hint(inc["id"], "cable")
    _twice([_f("audio", "bad")]); _twice([_f("audio", "ok")])
    assert next(i for i in I.items() if i["code"] == "audio")["hintable"] is True
