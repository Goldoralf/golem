# SPDX-License-Identifier: GPL-3.0-or-later
"""Garde-fou Whammy (2026-11-24) : l'appui à distance du pédalier (PC 0-9, canal 16) part sur le MIDI OUT de la
Whammy ; une Whammy en Omni s'allumait à chaque changement de preset. Juste après l'appui, golem redit son état."""
import pytest

from bridge import app, inputmap, midi_out
from bridge.state import state

CFG = {"channel": 1, "default_mode": "↑1 Oct",
       "modes": [{"name": "↑2 Oct", "active_pc": 0, "bypass_pc": 21}, {"name": "↑1 Oct", "active_pc": 1, "bypass_pc": 22},
                 {"name": "↓4th", "active_pc": 5, "bypass_pc": 26}, {"name": "Drop −3", "active_pc": 57, "bypass_pc": 75}]}


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "whammy-dt")
    monkeypatch.setattr(midi_out, "_whammy_cfg", lambda: CFG)
    monkeypatch.setattr(midi_out, "program_change", lambda pc, channel=1: out.append((pc, channel)) or True)
    monkeypatch.setattr(midi_out, "_din_out_off", lambda: False)
    for k, v in (("whammy_on", False), ("whammy_mode", None), ("whammy_drop", None)):
        monkeypatch.setattr(state, k, v)
    return out


def test_whammy_eteinte_l_appui_qui_l_engage_est_suivi_de_son_bypass(sent):
    app._whammy_after_remote_press(5)                       # SW6 -> PC 5 = « ↓4th » actif sur la DT
    assert sent == [(26, 1)]


def test_un_appui_qui_n_est_pas_un_programme_actif_n_envoie_rien(sent):
    app._whammy_after_remote_press(9)
    assert sent == []


def test_whammy_allumee_son_programme_est_redit(sent, monkeypatch):
    monkeypatch.setattr(state, "whammy_on", True)
    monkeypatch.setattr(state, "whammy_mode", "↑2 Oct")
    monkeypatch.setattr(state, "whammy_drop", "Drop −3")
    app._whammy_after_remote_press(6)
    assert sent == [(0, 1), (57, 1)]


def test_sans_whammy_declaree_rien_ne_part(sent, monkeypatch):
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "none")
    app._whammy_after_remote_press(5)
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "whammy-dt")
    monkeypatch.setattr(midi_out, "_whammy_cfg", lambda: {})
    app._whammy_after_remote_press(5)
    assert sent == []


def test_l_appui_a_distance_appelle_le_garde_fou(sent, monkeypatch):
    from bridge import pedalboard
    monkeypatch.setattr(pedalboard, "active", lambda: {"device": {"capabilities": {
        "remote_press": {"supported": True, "channel": 16, "pc_base": 0}}}})
    assert app._led_press(6) is True                        # SW6 -> PC 5 canal 16
    assert sent == [(5, 16), (26, 1)]
