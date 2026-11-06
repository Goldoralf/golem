# SPDX-License-Identifier: GPL-3.0-or-later
"""« Ask golem » (docs/assistant.md §5–§8) : absent sans appairage ou quand le mode le coupe ; rien ne part sans
consentement ; ce qui part est une liste blanche (ni preset, ni chanson, ni personne — le scrubber des rapports) avec
le registre de la machine ; la proposition de golem.fm est revalidée contre le registre et la garde ; les refus de
golem.fm sont dits tels quels, le 403 du scope demande de réappairer. `.venv/bin/python -m pytest tests/test_assistant.py -q`"""
import json

import pytest

from bridge import assistant as A, config as C, diag, fixes as F, health
from bridge.state import state

PRESET = "Set Léa"


@pytest.fixture
def rack(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(diag, "_scrubber", diag.Scrubber(names=["Léa"], presets=[PRESET], songs=[]))
    monkeypatch.setattr(diag, "_scrubber_at", 1e18)
    import bridge.golemfm as G
    monkeypatch.setattr(G, "_cfg", lambda: ("http://127.0.0.1:8000", "gmt_secret_token_123456"))
    monkeypatch.setattr(F, "_buffer_sizes", lambda: [64, 128, 192, 256])
    monkeypatch.setattr(F, "_bsize", lambda: 128)
    from bridge import reamp
    monkeypatch.setattr(reamp, "busy_reason", lambda idle=True: None)
    monkeypatch.setattr(health, "facts", lambda fresh=False: {"verdict": {"level": "bad", "counts": {"bad": 1}}, "facts": [
        {"id": "playing", "name": "Playing", "level": "ok", "text": f"« {PRESET} » · 3 files loaded and checked"},
        {"id": "dropouts", "name": "Dropouts", "level": "bad", "text": "14 in the last 10 min",
         "repair": {"action": "set_buffer", "params": {"size": 192}}}]})
    monkeypatch.setattr(state, "mode", {"id": "studio", "name": "Home", "services": {}})
    F._run.update(cur=None, last=None)
    return tmp_path


def test_absent_sans_appairage_ou_quand_le_mode_le_coupe(rack, monkeypatch):
    assert A.status() == {"available": True, "why": None, "consent": False}
    monkeypatch.setattr(state, "mode", {"id": "gig", "name": "Gig", "services": {"assistant": False}})
    assert A.status()["available"] is False and A.status()["why"] == "off in Gig mode"
    import bridge.golemfm as G
    monkeypatch.setattr(G, "_cfg", lambda: ("", ""))
    assert "pair" in A.status()["why"]


def test_rien_ne_part_sans_consentement(rack, monkeypatch):
    sent = []
    monkeypatch.setattr(A, "_post", lambda body: sent.append(body) or (200, {"answer": "x"}))
    r = A.ask("it crackles")
    assert r["ok"] is False and r["error"] == "consent" and sent == []
    A.consent(True)
    assert A.ask("it crackles")["ok"] is True and len(sent) == 1
    A.consent(False)
    assert A.status()["consent"] is False


def test_ce_qui_part_est_une_liste_blanche_avec_le_registre(rack):
    body = A.payload("it crackles on scene B", [{"q": "hi", "a": "hello", "extra": "x"}])
    blob = json.dumps(body, ensure_ascii=False)
    assert PRESET not in blob and "gmt_secret" not in blob, "ni le preset joué, ni le jeton"
    assert set(body) == {"question", "history", "facts", "verdicts", "actions", "context", "busy", "lang"}
    assert body["history"] == [{"q": "hi", "a": "hello"}]
    assert {a["name"] for a in body["actions"]} == set(F.ACTIONS), "le registre de la machine, entier"
    assert all(set(a) == {"name", "label", "description", "risk", "params", "live_allowed", "help"} for a in body["actions"])
    assert all("/" in h for a in body["actions"] for h in a["help"]), "les ids d'aide de golem.fm, <section>/<page>"
    assert next(f for f in body["facts"] if f["id"] == "dropouts")["repair"] == "set_buffer"
    assert body["lang"] == "auto", "golem.fm répond dans la langue de la question"


def test_la_proposition_est_revalidee_contre_le_registre_et_la_garde(rack):
    ok = A.check_answer({"answer": "Raise the buffer.", "cites": ["golem/health", "../etc/passwd", "x"],
                         "propose": {"action": "set_buffer", "params": {"size": 192}, "why": "dropouts"}}, None)
    assert ok["cites"] == ["golem/health"] and ok["propose"]["action"] == "set_buffer" and ok["propose"]["blocked"] is None
    assert ok["propose"]["label"] == "Raise the buffer"
    low = A.check_answer({"answer": "a", "propose": {"action": "set_buffer", "params": {"size": 64}}}, None)
    assert low["propose"]["label"] == "Lower the buffer", "le sens du changement, pas un libellé figé"
    assert "dropped" in A.check_answer({"answer": "a", "propose": {"action": "rm_rf", "params": {}}}, None)
    assert "dropped" in A.check_answer({"answer": "a", "propose": {"action": "set_buffer", "params": {"size": 100}}}, None)
    busy = A.check_answer({"answer": "a", "propose": {"action": "set_buffer", "params": {"size": 192}}}, "a take is recording")
    assert "propose" not in busy and "not while a take is recording" in busy["dropped"]
    read = A.check_answer({"answer": "a", "propose": {"action": "silence_hunt", "params": {}}}, "a take is recording")
    assert read["propose"]["action"] == "silence_hunt", "lire reste permis pendant qu'on joue"
    assert len(A.check_answer({"answer": "a", "cites": ["a/b", "c/d", "e/f", "g/h", "i/j"]}, None)["cites"]) == 4


def test_les_refus_de_golem_fm_sont_dits_tels_quels(rack, monkeypatch):
    A.consent(True)
    monkeypatch.setattr(A, "_post", lambda body: (403, {"detail": "Device token missing scope 'assistant:ask'"}))
    r = A.ask("hello")
    assert r["ok"] is False and r["error"] == "repair" and "Pair it again" in r["message"]
    monkeypatch.setattr(A, "_post", lambda body: (429, {"detail": {"error": "rate_limited", "message": "Too many questions.", "retry_after": 30}}))
    r = A.ask("hello")
    assert r == {"ok": False, "error": "rate_limited", "message": "Too many questions.", "retry_after": 30}
    monkeypatch.setattr(A, "_post", lambda body: (402, {"detail": {"error": "plan_required", "message": "Your plan has no assistant."}}))
    assert A.ask("hello")["message"] == "Your plan has no assistant."
    rows = [r for r in diag._read_timeline() if r["type"] == "assist"]
    assert [r["error"] for r in rows] == ["repair", "rate_limited", "plan_required"]
    assert "hello" not in json.dumps(rows), "jamais le texte de la question dans les rapports"
