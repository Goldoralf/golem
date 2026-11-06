# SPDX-License-Identifier: GPL-3.0-or-later
"""Plus de pédalier par défaut (2026-11-03) : une install neuve, sans pédalier déclaré ni mesuré, affichait
« FCB1010 · declared, not confirmed » — le pédalier du rack de développement. Elle dit maintenant qu'il n'y en a pas,
et ne le liste pas parmi les contrôleurs ; un pédalier déclaré ou mesuré reste celui qu'on voit."""
from bridge import health, pedalboard as PB


def test_sans_declaration_ni_mesure_aucun_pedalier(monkeypatch):
    monkeypatch.setattr(PB, "_state", lambda: {})
    a = PB.active()
    assert a["source"] == "fallback" and "fcb" not in a["id"].lower()
    f = health._f_pedalboard(type("S", (), {"midi": {}, "pedalboard": {}})())
    assert f["level"] == "wait" and "no pedalboard declared" in f["text"]


def test_un_pedalier_declare_reste_celui_qu_on_voit(monkeypatch):
    known = PB.devices()
    dev = next(iter(known))
    monkeypatch.setattr(PB, "_state", lambda: {"declared": dev})
    a = PB.active()
    assert a["id"] == dev and a["source"] == "declared"
