# SPDX-License-Identifier: GPL-3.0-or-later
"""LES RÉPARATIONS DISENT LE MOTEUR QUI TOURNE (VM Windows, 2026-11-23 : « Resync REAPER » proposé pour un Golem Engine
qui ne répondait pas). Le registre est écrit avec « REAPER » ; sous un autre moteur, ses textes portent son nom."""
from bridge import engine, fixes


class _Eng:
    def __init__(self, eid, name):
        self.id, self._name = eid, name

    def descriptor(self):
        return {"name": self._name}


def test_under_the_golem_engine_no_text_names_reaper(monkeypatch):
    monkeypatch.setattr(engine, "get", lambda: _Eng("ardour", "Golem Engine"))
    assert fixes.label_for("osc_refresh") == "Resync Golem Engine"
    plan = fixes.plan("osc_refresh")
    assert plan["ok"] and "REAPER" not in repr(plan) and "Golem Engine" in plan["title"]
    assert not [a for a in fixes.registry() if "REAPER" in a["label"] + a["description"]]


def test_under_reaper_the_texts_are_unchanged(monkeypatch):
    monkeypatch.setattr(engine, "get", lambda: _Eng("reaper", "REAPER"))
    assert fixes.label_for("osc_refresh") == "Resync REAPER"
    assert "REAPER" in fixes.plan("reaper_restart")["why"]
