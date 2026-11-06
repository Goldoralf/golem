# SPDX-License-Identifier: GPL-3.0-or-later
"""Health ▸ Fix — le registre d'actions (docs/assistant.md §3) : rien hors registre, des paramètres bornés, une garde
locale pendant qu'on joue, une réparation à la fois, et une vérification qui conclut ; un fait rouge reçoit l'action
qui lui répond. `.venv/bin/python -m pytest tests/test_fixes.py -q`"""
import asyncio
import time

import pytest

from bridge import config as C, diag, fixes as F, incidents as I
from bridge.state import state


@pytest.fixture
def rack(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(diag, "_scrubber", None)
    monkeypatch.setattr(F, "_buffer_sizes", lambda: [64, 128, 192, 256])
    monkeypatch.setattr(F, "_bsize", lambda: 128)
    from bridge import reamp
    monkeypatch.setattr(reamp, "busy_reason", lambda idle=True: None)
    F._run.update(cur=None, last=None)
    I._green.clear()
    return tmp_path


def test_le_registre_dit_ce_que_la_machine_sait_faire(rack):
    reg = {a["name"]: a for a in F.registry()}
    assert reg["set_buffer"]["params"]["properties"]["size"]["enum"] == [64, 128, 192, 256]
    assert reg["set_buffer"]["risk"] == "modify" and reg["set_buffer"]["live_allowed"] is False
    assert reg["silence_hunt"]["risk"] == "read" and reg["silence_hunt"]["live_allowed"] is True
    assert all(a["description"] and a["risk"] in ("read", "modify", "system") for a in reg.values())
    assert not any(a["live_allowed"] for a in reg.values() if a["risk"] != "read"), "rien qui change la machine pendant qu'on joue"


def test_rien_hors_registre_et_des_parametres_bornes(rack):
    assert F.validate("rm_rf", {})[1] == "unknown action 'rm_rf'"
    assert "one of" in F.validate("set_buffer", {"size": 100})[1]
    assert "integer" in F.validate("set_buffer", {"size": "192"})[1]
    assert "needs" in F.validate("set_buffer", {})[1]
    assert "no parameter" in F.validate("osc_refresh", {"shell": "x"})[1]
    assert "range" in F.validate("silence_hunt", {"seconds": 60})[1]
    assert F.validate("set_buffer", {"size": 192}) == ({"size": 192}, None)


def test_la_feuille_dit_avant_apres_et_ne_lance_rien(rack):
    p = F.plan("set_buffer", {"size": 192})
    assert p["ok"] and p["before"]["value"] == "128 samples" and p["after"]["value"] == "192 samples"
    assert p["after"]["sub"] == "8.0 ms round trip" and p["apply_label"] == "Apply — 192 samples"
    assert "128 samples" in p["undo"] and p["blocked"] is None
    assert F.status() == {"current": None, "last": None}


def test_la_garde_est_locale_pendant_une_prise(rack, monkeypatch):
    from bridge import reamp
    monkeypatch.setattr(reamp, "busy_reason", lambda idle=True: "a take is recording")
    assert F.blocked("set_buffer") == "not while a take is recording"
    assert F.blocked("silence_hunt") is None, "lire reste permis"
    r = asyncio.run(F.apply("set_buffer", {"size": 192}))
    assert r["ok"] is False and r["status"] == 409 and "take" in r["error"]


def test_un_fait_rouge_recoit_l_action_qui_lui_repond(rack, monkeypatch):
    assert F.suggest({"id": "dropouts", "level": "bad"}) == {"action": "set_buffer", "params": {"size": 192}}
    monkeypatch.setattr(F, "_bsize", lambda: 256)
    assert F.suggest({"id": "dropouts", "level": "bad"}) is None, "déjà au plus grand : rien à proposer"
    monkeypatch.setattr(state, "reaper_running", True)
    assert F.suggest({"id": "engine", "level": "warn"})["action"] == "osc_refresh"
    monkeypatch.setattr(state, "reaper_running", False)
    assert F.suggest({"id": "engine", "level": "bad"})["action"] == "reaper_restart"
    monkeypatch.setattr(state, "audio", {"ok": False, "why": "V276 is not connected", "card": "V276"})
    assert F.suggest({"id": "audio", "level": "bad"}) is None, "une carte débranchée se rebranche"
    monkeypatch.setattr(state, "audio", {"ok": False, "why": "the audio thread stopped"})
    assert F.suggest({"id": "audio", "level": "bad"})["action"] == "audio_reset"
    assert F.suggest({"id": "disk", "level": "bad"}) is None
    assert F.suggest({"id": "dropouts", "level": "ok"}) is None


def test_une_reparation_a_la_fois_verifiee_puis_rangee_dans_son_incident(rack, monkeypatch):
    ran = []

    async def run(p):
        ran.append(p)
        return {"ok": True}
    checks = iter([("wait", "checking…"), ("ok", "REAPER answers the bridge")])
    monkeypatch.setitem(F.ACTIONS, "osc_refresh", {**F.ACTIONS["osc_refresh"], "run": run,
                                                   "verify": lambda ctx, now: next(checks)})
    monkeypatch.setattr(F, "VERIFY_POLL_S", 0.01)
    monkeypatch.setattr(I, "_bridge_start", lambda: 0.0)
    eng = [{"id": "engine", "level": "warn", "text": "not answering", "name": "Engine"}]
    I.observe(eng); I.observe(eng)
    iid = I.items()[0]["id"]
    r = asyncio.run(F.apply("osc_refresh", {}, by="doctor", incident=iid))
    assert r["ok"] and ran == [{}]
    t0 = time.time()
    while F.status()["current"] and time.time() - t0 < 3:
        time.sleep(0.02)
    last = F.status()["last"]
    assert last["phase"] == "done" and last["by"] == "doctor" and last["text"] == "REAPER answers the bridge"
    inc = I.items()[0]
    assert inc["resolved_by"] == "action" and inc["action"] == "osc_refresh"
    fix_rows = [r for r in diag._read_timeline() if r["type"] == "fix"]
    assert fix_rows and fix_rows[-1]["verify"] == "ok" and fix_rows[-1]["id"] == iid


def test_une_route_qui_refuse_fait_echouer_la_reparation(rack, monkeypatch):
    from fastapi.responses import JSONResponse

    async def run(p):
        return JSONResponse({"error": "size must be one of [64]"}, status_code=400)
    monkeypatch.setitem(F.ACTIONS, "set_buffer", {**F.ACTIONS["set_buffer"], "run": run})
    r = asyncio.run(F.apply("set_buffer", {"size": 192}))
    assert r["ok"] is False and "size must be" in r["error"] and F.status()["last"]["phase"] == "failed"


def test_le_buffer_dit_dans_quel_sens_il_change(rack):
    """Constaté le 2026-10-20 : golem.fm proposait 192 → 128 pour baisser la latence, affiché « Raise the buffer »."""
    assert F.label_for("set_buffer", {"size": 192}) == "Raise the buffer"
    assert F.label_for("set_buffer", {"size": 64}) == "Lower the buffer"
    low = F.plan("set_buffer", {"size": 64})
    assert low["title"] == "Lower the latency" and "crackles" in low["why"] and low["after"]["sub"] == "2.7 ms round trip"
    assert F.plan("set_buffer", {"size": 192})["title"] == "Fix: audio dropouts"
    assert F.label_for("osc_refresh") == "Resync REAPER"
