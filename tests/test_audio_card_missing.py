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
