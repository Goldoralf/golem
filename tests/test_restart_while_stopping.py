# SPDX-License-Identifier: GPL-3.0-or-later
"""Relancer golem PENDANT le ⏻ « Stop golem » (2026-10-10) : le bridge mourant répondait encore « ok », le
lanceur n'ouvrait qu'une fenêtre sur lui — « Bridge link lost » jusqu'à une seconde relance."""
import pytest

from provision import desktop


def test_pendant_un_arret_la_sante_ne_dit_plus_ok():
    from fastapi.testclient import TestClient
    from bridge import app as A
    from bridge.state import state
    c = TestClient(A.app)
    try:
        state.stopping = True
        assert c.get("/api/health").json() == {"ok": False, "stopping": True}
    finally:
        state.stopping = False
    assert c.get("/api/health").json()["ok"] is True


def test_le_lanceur_attend_la_fin_de_l_arret(monkeypatch):
    seq = iter([{"stopping": True}, {"stopping": True}, None])
    monkeypatch.setattr(desktop, "bridge_health", lambda port: next(seq, None))
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    assert desktop.wait_stopped(8770) is True
    assert desktop.bridge_answers(8770) is False                       # personne : le lanceur démarre un bridge neuf


def test_un_arret_qui_ne_finit_pas_est_dit(monkeypatch):
    monkeypatch.setattr(desktop, "bridge_health", lambda port: {"stopping": True})
    monkeypatch.setattr(desktop, "reaper_running", lambda: True)       # REAPER demande « enregistrer ? »
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    assert desktop.wait_stopped(8770, seconds=1) is False
    monkeypatch.setattr(desktop, "venv_python", lambda: desktop.Path(desktop.sys.executable))
    monkeypatch.setattr(desktop, "_launcher_lock", lambda: True)       # pas le vrai verrou du dossier REAPER
    with pytest.raises(RuntimeError, match="still stopping"):
        desktop.start(window=True)
