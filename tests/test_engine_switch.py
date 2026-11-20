# SPDX-License-Identifier: GPL-3.0-or-later
"""La bascule de moteur (lot E3, bridge/engine/switch.py) avec des moteurs factices : l'ancien s'arrête et rend son port,
le nouveau devient le moteur actif, démarre, répond ; s'il ne répond pas, golem revient seul à l'ancien."""
import asyncio
import time

import pytest

from bridge import engine, engines
from bridge.engine import switch
from bridge.engine.fake import FakeEngine


class Old(FakeEngine):
    id = "old"

    def __init__(self):
        super().__init__()
        self.events = []

    def stop(self, timeout=10.0):
        self.events.append("stop")
        self.up = False
        return True

    def stop_feedback(self):
        self.events.append("feedback-off")

    def start_feedback(self, on_message):
        self.events.append("feedback-on")

    def restart(self, why="requested"):
        self.events.append(f"restart:{why}")
        self.up = True
        return {"ok": True}

    def talking(self):
        return self.up


class New(Old):
    id = "new"
    answers = True

    def restart(self, why="requested"):
        self.events.append(f"restart:{why}")
        self.up = self.answers
        return {"ok": True}


@pytest.fixture
def bench(monkeypatch):
    old = Old()
    prev = engine.use(old)
    monkeypatch.setattr(switch, "START_TIMEOUT_S", 0.5)
    monkeypatch.setattr(switch, "_job", {"phase": "idle"})
    from bridge import recall
    from bridge.state import state
    monkeypatch.setattr(recall, "invalidate_shape", lambda: None)
    monkeypatch.setattr(state, "preset_id", None, raising=False)
    written = []
    monkeypatch.setattr(engines, "write_choice", lambda eid, **k: written.append(eid) or eid)
    yield old, written
    engine.use(prev)


def _until_done(timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if switch.status().get("phase") in ("done", "failed"):
            return switch.status()
        time.sleep(0.02)
    return switch.status()


def test_la_bascule_arrete_l_ancien_et_demarre_le_nouveau(bench):
    old, written = bench
    made = []
    reg = {"new": lambda: made.append(New()) or made[-1]}
    switch.start("new", on_osc=lambda a, b: None, registry=reg)
    st = _until_done()
    assert st["phase"] == "done" and st["from"] == "old" and st["to"] == "new"
    assert old.events == ["stop", "feedback-off"]                       # l'ancien rend son process ET son port
    assert engine.get() is made[0] and made[0].events == ["feedback-on", "restart:switch"]
    assert written == []                                                 # le choix, c'est la route qui l'écrit


def test_un_nouveau_qui_ne_repond_pas_ramene_l_ancien(bench):
    old, written = bench
    New.answers = False
    try:
        switch.start("new", on_osc=lambda a, b: None, registry={"new": New})
        st = _until_done()
    finally:
        New.answers = True
    assert st["phase"] == "failed" and "did not answer" in st["error"]
    assert engine.get() is old and written == ["old"]                    # l'ancien revient, son choix aussi
    assert old.events == ["stop", "feedback-off", "feedback-on", "restart:switch back"]


def test_un_ancien_qui_ne_meurt_pas_annule_la_bascule(bench):
    # 2026-11-20 : le REAPER que la bascule n'arrêtait pas restait sur la carte à côté du Golem Engine — craquements.
    # Jamais deux moteurs sur la carte : le nouveau ne démarre pas, l'ancien reste le moteur, son choix aussi.
    old, written = bench
    old.stop = lambda timeout=10.0: old.events.append("stop") or False
    made = []
    switch.start("new", on_osc=lambda a, b: None, registry={"new": lambda: made.append(New()) or made[-1]})
    st = _until_done()
    assert st["phase"] == "failed" and "did not stop" in st["error"]
    assert made == [] and engine.get() is old and written == ["old"]
    assert old.events == ["stop"]                                        # son retour OSC reste ouvert


def test_reaper_est_ferme_poliment_sous_windows(monkeypatch):
    # la voie Linux (pgrep, /proc) ne voyait aucun REAPER sous Windows et le disait mort sans l'avoir arrêté
    import sys
    from bridge import desktop_audio
    from bridge.engine.reaper import ReaperEngine
    from provision import desktop, desktop_window
    alive = {"up": True}
    calls = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop, "reaper_pids", lambda: {11, 22})
    monkeypatch.setattr(desktop, "bench_reaper_pids", lambda: {22})
    monkeypatch.setattr(desktop, "reaper_running", lambda: alive["up"])
    monkeypatch.setattr(desktop_window, "reaper_hung", lambda pids, seconds=15.0: False)
    monkeypatch.setattr(desktop_window, "force_close_reaper", lambda pids: calls.append(("kill", pids)))
    monkeypatch.setattr(desktop_audio, "save_project_in_place", lambda *a, **k: calls.append(("save",)))

    def close(pids):
        calls.append(("close", pids))
        alive["up"] = False
        return 1
    monkeypatch.setattr(desktop_window, "request_reaper_close", close)
    assert ReaperEngine(link=object()).stop() is True
    assert calls == [("save",), ("close", {11})]                         # jamais le REAPER d'un banc, jamais tué


def test_un_reaper_qui_reste_ouvert_n_est_pas_dit_mort(monkeypatch):
    import sys
    from bridge import desktop_audio
    from bridge.engine.reaper import ReaperEngine
    from provision import desktop, desktop_window
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop, "reaper_pids", lambda: {11})
    monkeypatch.setattr(desktop, "bench_reaper_pids", lambda: set())
    monkeypatch.setattr(desktop, "reaper_running", lambda: True)    # « Save project? » à l'écran
    monkeypatch.setattr(desktop_window, "reaper_hung", lambda pids, seconds=15.0: False)
    monkeypatch.setattr(desktop_window, "request_reaper_close", lambda pids: 1)
    monkeypatch.setattr(desktop_audio, "save_project_in_place", lambda *a, **k: None)
    assert ReaperEngine(link=object())._stop_desktop(0.5) is False


def test_une_bascule_a_la_fois(bench, monkeypatch):
    monkeypatch.setattr(switch, "_job", {"phase": "starting"})
    with pytest.raises(ValueError):
        switch.start("new", registry={"new": New})


def test_pas_de_bascule_pendant_une_prise(bench, monkeypatch):
    from bridge import routes_system
    from bridge.state import state
    monkeypatch.setattr(state, "recording", {"take": "x"}, raising=False)
    monkeypatch.setattr(engines, "current", lambda *a, **k: "reaper")
    r = asyncio.run(routes_system.engine_select({"id": "ardour"}))
    assert r.status_code == 409


def test_le_golem_engine_n_est_choisissable_que_la_ou_il_est_construit(monkeypatch, tmp_path):
    desc = {"selectable": True, "platforms": {"linux": {"available": True, "requires": {
        "env": "GOLEM_ENGINE_DIR", "default": str(tmp_path / "absent"), "file": "golem/engine/run.sh",
        "reason": "Golem Engine is not built on this machine"}}}}
    monkeypatch.delenv("GOLEM_ENGINE_DIR", raising=False)
    assert engines.availability(desc, "linux") == (False, "Golem Engine is not built on this machine")
    run = tmp_path / "built" / "golem" / "engine" / "run.sh"
    run.parent.mkdir(parents=True)
    run.write_text("#!/bin/sh\n")
    monkeypatch.setenv("GOLEM_ENGINE_DIR", str(tmp_path / "built"))
    assert engines.availability(desc, "linux") == (True, None)


def test_app_reaper_suit_le_moteur_actif():
    a, b = FakeEngine(), FakeEngine()
    prev = engine.use(a)
    try:
        proxy = engine.active()
        proxy.transport("play")
        engine.use(b)
        proxy.transport("stop")
    finally:
        engine.use(prev)
    assert a.fast == [("transport", "play")] and b.fast == [("transport", "stop")]


def test_la_bascule_efface_les_temoins_de_l_ancien(bench, monkeypatch, tmp_path):
    from bridge import config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    for n in (".clock.json", ".engine-status.json"):
        (tmp_path / n).write_text("{}")
    switch.start("new", on_osc=lambda a, b: None, registry={"new": New})
    assert _until_done()["phase"] == "done"
    assert not (tmp_path / ".clock.json").exists() and not (tmp_path / ".engine-status.json").exists()


def test_le_golem_engine_reprend_le_buffer_de_reaper(monkeypatch, tmp_path):
    import json
    from bridge import config as C
    from bridge.engine.ardour import ArdourEngine
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    e = ArdourEngine(link=object())
    e.adopt_audio({"buffer": 192})
    cfg = tmp_path / "config" / "golem-engine.json"
    assert json.loads(cfg.read_text())["buffer"] == 192
    e.adopt_audio({"buffer": 64})                                  # il a désormais le sien : on n'y touche plus
    assert json.loads(cfg.read_text())["buffer"] == 192
    cfg.unlink()
    e.adopt_audio({"buffer": 200})                                 # hors liste : le plus proche au-dessus
    assert json.loads(cfg.read_text())["buffer"] == 256


def test_un_golem_engine_qui_plante_est_relance_trois_fois_au_plus(monkeypatch):
    from bridge import monitors
    eng = New()
    eng.up = False
    prev = engine.use(eng)
    real = asyncio.sleep
    monkeypatch.setattr(monitors.asyncio, "sleep", lambda s: real(0))
    monkeypatch.setattr(monitors, "_CRASH_RESTARTS", [])
    try:
        for _ in range(5):
            eng.up = False
            asyncio.run(monitors._engine_crash_restart())
    finally:
        engine.use(prev)
    assert [e for e in eng.events if e.startswith("restart")] == ["restart:crash"] * 3


def test_reaper_n_est_jamais_relance_par_ce_chemin(monkeypatch):
    from bridge import monitors
    from bridge.engine.reaper import ReaperEngine
    called = []
    r = ReaperEngine(link=object())
    monkeypatch.setattr(r, "restart", lambda why="": called.append(why))
    prev = engine.use(r)
    try:
        asyncio.run(monitors._engine_crash_restart())
    finally:
        engine.use(prev)
    assert called == []


def test_le_boost_cpu_suit_golem_sous_les_deux_moteurs(monkeypatch):
    # 2026-11-13 (le mainteneur) : en économie, le Golem Engine décrochait (80 % de DSP contre 31 %) — boosté tant
    # qu'il tourne ; sous REAPER, la règle du mode seule (Gig et Show)
    from bridge import routes_system as RS
    home, gig = {"name": "Home", "perf_boost": False}, {"name": "Gig", "perf_boost": True}
    # 2026-11-17 (le mainteneur) : le boost SUIT GOLEM, sous les deux moteurs — plus seulement le Golem Engine
    monkeypatch.setattr(RS, "perf_auto", lambda: True)
    monkeypatch.setattr(RS, "on_battery", lambda: False)
    assert RS.wants_boost(home) == (True, "golem is running")
    monkeypatch.setattr(RS, "on_battery", lambda: True)                  # sur batterie : pas d'automatisme…
    assert RS.wants_boost(home) == (False, "on battery") and RS.wants_boost(gig)[0] is True   # …sauf un mode qui l'exige
    monkeypatch.setattr(RS, "on_battery", lambda: False)
    monkeypatch.setattr(RS, "perf_auto", lambda: False)                  # l'interrupteur coupé
    assert RS.wants_boost(home) == (False, "automatic performance mode is off") and RS.wants_boost(gig)[0] is True


def test_une_bascule_de_moteur_regle_le_boost_avant_de_demarrer(monkeypatch):
    from bridge.engine import switch
    calls = []
    monkeypatch.setattr(switch, "_boost", lambda state, why: calls.append(why))
    src = open(switch.__file__, encoding="utf-8").read()
    run = src[src.index("def _run("):src.index("def _boost(")]
    assert run.index("_boost(") < run.index("new.restart(")          # boosté AVANT le démarrage du moteur
    assert "_boost(" in src[src.index("def _revert("):]                # et rendu au retour sur l'ancien


def test_fermer_golem_annonce_l_arret_du_golem_engine_avant_de_l_arreter(monkeypatch):
    # 2026-11-21 : la croix arrêtait le Golem Engine sans intention ; le moniteur y voyait un plantage et le relançait
    # avant la mort du bridge — un moteur orphelin gardait la carte, golem fermé
    from bridge import diag, engines, routes_dev
    from bridge.engine import ardour
    seen = []
    monkeypatch.setattr(engines, "current", lambda *a, **k: "ardour")
    monkeypatch.setattr(diag, "_intents", {})
    monkeypatch.setattr(ardour.ArdourEngine, "stop", lambda self, timeout=10.0: seen.append(diag.peek_intent("reaper")) or True)
    assert routes_dev._stop_golem_engine_for_shutdown() is True
    assert seen == ["shutdown"]
