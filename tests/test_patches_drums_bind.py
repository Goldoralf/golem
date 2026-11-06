# SPDX-License-Identifier: GPL-3.0-or-later
"""Une batterie électronique (bloc Drum Kit) se lie en MIDI USB même sans module encore lié (2026-10-13)."""
from bridge import patches as P


def _lane(blocks):
    return {"id": "drums-1", "role": "drums", "chain": {"chain": blocks}}


def test_drumkit_sans_module_attend_sur_usb():
    out = P.bind_input(_lane([{"type": "drumkit", "id": "k"}]), "drums", {"usb": [], "inputs": []})
    assert out["midi"] is True and out["in_sel"] == "usb"


def test_module_lie_gagne():
    imap = {"usb": [{"ch": "usb2", "bound": True, "role": "drums"}], "inputs": []}
    out = P.bind_input(_lane([{"type": "drumkit", "id": "k"}]), "drums", imap)
    assert out["midi"] is True and out["in_sel"] == "usb2"


def test_batterie_audio_sans_entree_reste_refusee():
    import pytest
    with pytest.raises(ValueError):
        P.bind_input(_lane([]), "drums", {"usb": [], "inputs": [], "card": "hw:V276"})
