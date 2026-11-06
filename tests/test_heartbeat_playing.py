# SPDX-License-Identifier: GPL-3.0-or-later
"""Le battement porte CE QUI JOUE (demande golem.fm, 2026-09-30) : le preset courant — `patch:<id>` pour un
patch joué (docs/patches.md) —, son nom et la scène. Absent = golem.fm n'affiche rien."""
from bridge import rigstatus
from bridge.state import state


def test_le_battement_porte_le_preset_joue(monkeypatch):
    monkeypatch.setattr(state, "preset_id", "patch:pearl-jam")
    monkeypatch.setattr(state, "preset_name", "⛓ Pearl Jam")     # le préfixe du Designer ne voyage pas
    monkeypatch.setattr(state, "scene_id", "B")
    st = rigstatus.light()
    assert (st["preset_id"], st["preset_name"], st["scene"]) == ("patch:pearl-jam", "Pearl Jam", "B")


def test_rien_ne_joue_se_dit_null(monkeypatch):
    monkeypatch.setattr(state, "preset_id", None)
    monkeypatch.setattr(state, "preset_name", None)
    monkeypatch.setattr(state, "scene_id", None)
    st = rigstatus.light()
    assert st["preset_id"] is None and st["preset_name"] is None and st["scene"] is None
