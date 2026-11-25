# SPDX-License-Identifier: GPL-3.0-or-later
"""Carte son ACTIVE débranchée : le rack dit laquelle, et garde sa réparation pour le retour.

Vécu le 2026-09-21 : le rack démarrait avec `hw:iTwo` dans reaper.ini alors que la Volt était
branchée — Reaper affichait « ALSA: error opening input device », l'écran du rack rien. Et le
chien de garde brûlait son unique `audio_reset` sur une carte absente."""
import pytest

from bridge import commands, monitors
from bridge.state import state


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(monitors.sys, "platform", "linux")
    sent = []
    monkeypatch.setattr(commands, "write_command", lambda cmd: sent.append(cmd))
    monkeypatch.setattr(state, "cards", {"active": "iTwo", "active_present": False,
                                         "active_name": "PreSonus AudioBox iTwo"})
    monkeypatch.setattr(state, "perf", {})
    monkeypatch.setitem(monitors._AUDIO_FIX, "tried", False)
    monkeypatch.setattr(monitors, "_engine_overloaded", lambda: None)   # le moteur de la machine qui teste n'y entre pas
    return sent


def test_carte_absente_on_dit_laquelle_et_on_ne_tente_rien(rig):
    for _ in range(3):
        a = monitors._audio_recover(False, "audio thread stalled — sound card lost?")
    assert a["ok"] is False and a["card"] == "PreSonus AudioBox iTwo"
    assert "not connected" in a["why"]
    assert rig == [] and monitors._AUDIO_FIX["tried"] is False


def test_au_rebranchement_la_tentative_part(rig):
    monitors._audio_recover(False, "stalled")
    state.cards = {**state.cards, "active_present": True}
    a = monitors._audio_recover(False, "stalled")
    assert rig == [{"action": "audio_reset"}] and a["fix"] == "recovering…"


def test_carte_presente_rien_ne_change(rig):
    state.cards = {**state.cards, "active_present": True}
    assert monitors._audio_recover(True, "")["ok"] is True


def test_desktop_ignores_linux_alsa_card(rig, monkeypatch):
    monkeypatch.setattr(monitors.sys, "platform", "win32")
    assert monitors._active_card_missing() is None


def test_moteur_sature_on_ne_rouvre_pas_la_carte(rig, monkeypatch):
    # rack 2026-11-24 (i5-3337U, Golem Engine, « Chill Jazz » à 100 % DSP) : chaque calage rouvrait la carte, 22 fois
    state.cards = {**state.cards, "active_present": True}
    monkeypatch.setattr(monitors, "_engine_overloaded", lambda: 100.0)
    for _ in range(3):
        a = monitors._audio_recover(False, "audio thread stalled — sound card lost?")
    assert rig == [] and monitors._AUDIO_FIX["tried"] is False
    assert a["ok"] is False and a["overload"] is True and "overloaded" in a["why"]
    monkeypatch.setattr(monitors, "_engine_overloaded", lambda: None)   # la charge retombe, le calage reste : on tente
    assert monitors._audio_recover(False, "stalled")["fix"] == "recovering…" and rig == [{"action": "audio_reset"}]


def test_la_surcharge_se_lit_dans_la_charge_dsp_du_moteur(monkeypatch):
    from bridge import engine

    class E:
        def __init__(self, load):
            self.load = load

        def audio(self):
            return {} if self.load is None else {"dsp_load": self.load}

    for load, want in ((100, 100.0), (95, 95.0), (60, None), (None, None)):
        monkeypatch.setattr(engine, "get", lambda e=E(load): e)
        assert monitors._engine_overloaded() == want


def test_un_flux_mort_a_100_pourcent_n_est_pas_une_surcharge(monkeypatch):
    # rack 2026-11-25 : après « Chill Jazz », le backend ALSA du moteur restait bloqué — 2 560 échantillons en 20 s,
    # `dsp_load` figé à 100 : pris pour une surcharge, il n'était plus jamais rouvert
    import time
    from bridge import engine

    class E:
        def audio(self):
            return {"dsp_load": 100.0, "rate": 48000}

    monkeypatch.setattr(engine, "get", lambda: E())
    now = time.time()
    monkeypatch.setattr(monitors, "_CLOCK_HIST", [(now - 12, 1000), (now - 6, 1500), (now, 2560)])
    assert monitors._engine_overloaded() is None                      # mort : la réouverture repart
    monkeypatch.setattr(monitors, "_CLOCK_HIST", [(now - 12, 0), (now - 6, 200_000), (now, 400_000)])
    assert monitors._engine_overloaded() == 100.0                     # 70 % du temps réel : saturé mais vivant
    monkeypatch.setattr(monitors, "_CLOCK_HIST", [(now - 2, 0), (now, 10)])
    assert monitors._engine_overloaded() == 100.0                     # fenêtre pas encore pleine : on ne conclut pas


def test_flux_mort_apres_la_reouverture_le_moteur_redemarre_une_fois(rig, monkeypatch):
    # rack 2026-11-25 : audio_reset ne ranimait pas le backend ALSA bloqué du Golem Engine ; un moteur relancé, si
    import asyncio
    import time
    from bridge import engine
    restarts = []

    class E:
        id = "ardour"

        def audio(self):
            return {"rate": 48000}

        def restart(self, why="requested"):
            restarts.append(why)

    monkeypatch.setattr(engine, "get", lambda: E())
    monkeypatch.setattr(monitors, "_ENGINE_RESTARTS", [])
    monkeypatch.setattr(state, "rig_loading", None)
    state.cards = {**state.cards, "active_present": True}
    now = time.time()
    monkeypatch.setattr(monitors, "_CLOCK_HIST", [(now - 12, 1000), (now, 1200)])     # mort

    async def run():
        a = monitors._audio_recover(False, "stalled")                 # 1. la carte rouverte
        assert a["fix"] == "recovering…" and rig == [{"action": "audio_reset"}]
        b = monitors._audio_recover(False, "stalled")                 # trop tôt : la réouverture agit encore
        assert "no effect" in b["fix"] and not restarts
        monitors._AUDIO_FIX["tried_at"] = time.time() - 10
        c = monitors._audio_recover(False, "stalled")                 # 2. toujours mort : le moteur redémarre
        assert "restarting" in c["fix"]
        d = monitors._audio_recover(False, "stalled")                 # une fois par 10 min, pas en rond
        assert "no effect" in d["fix"]
        await asyncio.sleep(0.05)

    asyncio.run(run())
    assert restarts == ["audio-dead"]


def test_reaper_n_est_pas_redemarre_par_la_recuperation(rig, monkeypatch):
    import time
    from bridge import engine

    class R:
        id = "reaper"

        def audio(self):
            return {}

    monkeypatch.setattr(engine, "get", lambda: R())
    monkeypatch.setattr(monitors, "_ENGINE_RESTARTS", [])
    monkeypatch.setitem(monitors._AUDIO_FIX, "tried_at", time.time() - 60)
    now = time.time()
    monkeypatch.setattr(monitors, "_CLOCK_HIST", [(now - 12, 1000), (now, 1000)])
    assert monitors._restart_dead_engine() is False


def test_pas_de_redemarrage_pendant_un_montage_ni_au_demarrage(rig, monkeypatch):
    import time
    from bridge import engine

    class E:
        id = "ardour"
        launched_at = 0

        def audio(self):
            return {"rate": 48000}

    e = E()
    monkeypatch.setattr(engine, "get", lambda: e)
    monkeypatch.setattr(monitors, "_ENGINE_RESTARTS", [])
    monkeypatch.setitem(monitors._AUDIO_FIX, "tried_at", time.time() - 60)
    now = time.time()
    monkeypatch.setattr(monitors, "_CLOCK_HIST", [(now - 12, 1000), (now, 1000)])
    monkeypatch.setattr(state, "rig_loading", {"preset": "x"})
    assert monitors._restart_dead_engine() is False
    monkeypatch.setattr(state, "rig_loading", None)
    e.launched_at = time.time() - 20
    assert monitors._restart_dead_engine() is False
