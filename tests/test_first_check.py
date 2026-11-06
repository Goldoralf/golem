# SPDX-License-Identifier: GPL-3.0-or-later
"""La vérification de première installation (docs/health.md §2) : à faire tant qu'elle n'a été ni finie ni passée ;
les gestes datés depuis leur départ ; le pédalier compte seulement s'il a répondu APRÈS le départ du geste ; le
bilan ok / partial ; rejouable ; et sa section de diagnostic ne porte que des verdicts et des durées.
`.venv/bin/python -m pytest tests/test_first_check.py -q`"""
import json

import pytest

from bridge import diag, first_check as FC


@pytest.fixture
def rack(tmp_path, monkeypatch):
    from bridge import config as C
    (tmp_path / "config").mkdir()
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    import bridge.foot as foot
    monkeypatch.setattr(foot, "last_heard", lambda: None)
    return tmp_path


def test_a_faire_tant_qu_elle_n_est_ni_finie_ni_passee(rack):
    assert FC.pending() is True and FC.brief() == {"pending": True, "done_at": None, "skipped_at": None, "verdict": None}
    FC.skip()
    assert FC.pending() is False and FC.brief()["skipped_at"]
    FC.reset()
    assert FC.pending() is True, "rejouable depuis Settings ▸ Health"


def test_les_trois_gestes_sont_dates_verifies_et_le_bilan_est_ok(rack, monkeypatch):
    import bridge.foot as foot
    t = FC.begin("input")["at"]
    r = FC.record("input", measured={"peak": 0.685, "input": 2, "role": "guitar"})["result"]
    assert r["ok"] is True and r["peak_db"] == -18.6 and r["took_s"] >= 0, "le vumètre OSC est linéaire en dB (−72…+6)"
    assert r["input"] == 2 and r["role"] == "guitar" and r["gain"] == "good", "l'entrée où l'on a joué, pas IN 1 d'office"
    (rack / "presets" / ".click.json").write_text(json.dumps({"on": True, "ticks": 42}), encoding="utf-8")
    FC.begin("output")
    r = FC.record("output", measured={"heard": True})["result"]
    assert r == {**r, "ok": True, "heard": True, "click_ticks": 42}
    at = FC.begin("foot")["at"]
    monkeypatch.setattr(foot, "last_heard", lambda: at - 5)           # un appui d'AVANT le geste ne compte pas
    r = FC.record("foot")["result"]
    assert r["ok"] is False and r["answered"] is False
    monkeypatch.setattr(foot, "last_heard", lambda: at + 2)
    r = FC.record("foot")["result"]
    assert r["ok"] is True and r["answered"] is True
    f = FC.finish()
    assert f["verdict"] == "ok" and f["took_s"] >= 0 and t <= f["done_at"]
    assert FC.pending() is False and FC.brief()["verdict"] == "ok"


def test_un_signal_trop_faible_est_un_geste_rate_et_le_bilan_partiel(rack):
    FC.begin("input")
    r = FC.record("input", measured={"peak": 0.001})["result"]
    assert r["ok"] is False and r["gain"] is None, "pas de verdict de gain sans signal"
    FC.begin("output")
    assert FC.record("output", measured={"heard": False})["result"] == {**FC.status()["steps"]["output"], "ok": False}
    FC.begin("foot")
    FC.record("foot", ok=False)
    assert FC.finish()["verdict"] == "partial"
    s = FC.status()
    assert s["pending"] is False and set(s["steps"]) == {"input", "output", "foot"} and s["foot_wait_s"] == 30
    assert [a["id"] for a in s["auto"]] == ["engine", "audio", "content", "preset"], "toujours quatre faits automatiques"


def test_le_verdict_de_gain_suit_la_crete_et_l_ecretage_l_emporte(rack):
    assert [FC.gain_of(d) for d in (-30, -12, -1, None)] == ["low", "good", "hot", None]
    assert FC.vu_db(0) is None and FC.vu_db(1) == 6.0 and FC.vu_db(0.5) == -33.0
    assert FC.gain_of(-12, clipped=True) == "hot"
    FC.begin("input")
    r = FC.record("input", measured={"peak": 0.5, "input": 1})["result"]          # −33 dBFS
    assert r["ok"] is True and r["gain"] == "low", "on joue mais faible : le geste passe, le gain est dit"
    FC.begin("input")
    assert FC.record("input", measured={"peak": 0.7, "input": 1, "clipped": True})["result"]["gain"] == "hot"


def test_un_geste_inconnu_est_refuse_et_rejouer_garde_la_passe_d_avant(rack):
    with pytest.raises(ValueError):
        FC.begin("dance")
    with pytest.raises(ValueError):
        FC.record("dance")
    FC.begin("input"); FC.record("input", measured={"peak": 0.7}); FC.finish()
    FC.reset()
    d = json.load(open(rack / "config" / ".first-check.json", encoding="utf-8"))
    assert d["previous"]["steps"]["input"]["ok"] is True and FC.pending() is True


def test_la_section_de_diagnostic_ne_porte_que_des_verdicts_et_des_durees(rack, monkeypatch):
    assert FC.section() is None, "rien tant que rien n'a été fait"
    FC.begin("input"); FC.record("input", measured={"peak": 0.7, "input": 2, "role": "guitar"}); FC.begin("output"); FC.record("output", measured={"heard": True})
    FC.begin("foot"); FC.record("foot", ok=False); FC.finish()
    sec = FC.section()
    assert sec["verdict"] == "partial" and sec["skipped"] is False
    assert set(sec["steps"]["input"]) <= {"ok", "took_s", "peak_db", "input", "role", "gain"} and set(sec["steps"]["foot"]) <= {"ok", "took_s", "answered"}
    # …et elle passe la liste blanche du paquet telle quelle
    picked = diag._pick("first_check", sec)
    assert picked["steps"]["foot"]["ok"] is False and picked["steps"]["input"]["peak_db"] == -17.4
    assert picked["steps"]["input"]["input"] == 2 and picked["steps"]["input"]["gain"] == "good"
    assert picked["steps"]["output"].get("click_ticks") is None          # pas de .click.json ici : dit absent, pas inventé
    assert diag.violations({"first_check": picked}) == []


def test_la_route_couvre_les_cinq_actions(rack):
    from bridge import routes_health as R
    assert R.first_check_act({"action": "begin", "step": "input"})["step"] == "input"
    assert R.first_check_act({"action": "step", "step": "input", "measured": {"peak": 0.7}})["result"]["ok"] is True
    assert R.first_check_act({"action": "finish"})["done_at"]
    assert R.first_check_act({"action": "skip"})["skipped_at"]
    assert R.first_check_act({"action": "reset"})["pending"] is True
    assert R.first_check_act({"action": "fly"}).status_code == 400
    assert R.first_check_act({"action": "step", "step": "dance"}).status_code == 400
    assert R.first_check_status()["pending"] is True
