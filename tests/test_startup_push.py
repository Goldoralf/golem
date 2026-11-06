# SPDX-License-Identifier: GPL-3.0-or-later
"""L'accueil au démarrage se voit TOUT DE SUITE à l'écran (2026-11-06) : chaque route le pousse par le WebSocket —
`state.touch()` seul ne poussait rien, et « ⌂ Open at startup » semblait sans effet jusqu'au redémarrage."""
import asyncio

from bridge import app as A, routes_startup as R, startup_home as SH


def test_chaque_route_de_l_accueil_pousse_l_etat(monkeypatch):
    pushed = []

    async def bcast():
        pushed.append(1)
    monkeypatch.setattr(A, "_broadcast", bcast)
    monkeypatch.setattr(SH, "set_policy", lambda p: {"policy": p})
    monkeypatch.setattr(SH, "set_home", lambda b: {"home": b})
    monkeypatch.setattr(SH, "clear_home", lambda: {"home": None})
    asyncio.run(R.startup_policy({"policy": "last"}))
    asyncio.run(R.startup_home_set({"kind": "patch", "id": "patch:x"}))
    asyncio.run(R.startup_home_clear())
    assert pushed == [1, 1, 1]
