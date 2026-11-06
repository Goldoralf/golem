# SPDX-License-Identifier: GPL-3.0-or-later
"""Un `in_sel` nu (« usb », les lanes Keys des presets d'usine) n'est pas l'USB 1 : c'est le port où le moteur trouve le
meilleur appareil du rôle (vital.lane_port) — le Designer, le Riff et le veto par mode lisent ce numéro."""
from bridge import devices, vital


def _rack(monkeypatch):
    # chez Alex : rien en USB 1, le MPK en USB 2
    monkeypatch.setattr(devices, "bindings", lambda: {"usb2": {"enabled": True, "device": "MPK mini", "roles": ["keys", "pads"]}})
    monkeypatch.setattr(vital, "midi_input_for", lambda role=None, in_sel=None: "hw:MPK" if role != "drums" else None)
    monkeypatch.setattr(vital, "_hw_of", lambda name: "hw:MPK" if name == "MPK mini" else None)


def test_usb_nu_suit_le_moteur(monkeypatch):
    _rack(monkeypatch)
    assert vital.lane_port("keys", "usb") == 2
    assert vital.lane_port("keys", None) == 2


def test_un_port_nomme_reste_le_sien(monkeypatch):
    _rack(monkeypatch)
    assert vital.lane_port("keys", "usb3") == 3


def test_rien_de_branche_pour_le_role(monkeypatch):
    _rack(monkeypatch)
    assert vital.lane_port("drums", "usb") is None
