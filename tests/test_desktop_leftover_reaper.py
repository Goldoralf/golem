# SPDX-License-Identifier: GPL-3.0-or-later
"""Un REAPER de golem resté ouvert, vivant, après l'arrêt du bridge (2026-11-25) : le lanceur le ferme poliment au lieu
de refuser de démarrer (« Close REAPER first ») — et ne touche jamais un REAPER ouvert à la main."""
import sys

import pytest

from provision import desktop
import provision.desktop_window as DW


@pytest.fixture
def win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    return monkeypatch


def test_le_reaper_de_golem_recoit_la_croix_et_se_ferme(win):
    alive = {4242}
    asked = []
    win.setattr(desktop, "_golem_reaper_pids", lambda: set(alive))
    win.setattr(DW, "request_reaper_close", lambda pids: (asked.append(set(pids)), alive.clear(), 1)[-1])
    assert desktop._close_leftover_reaper(wait_s=1) is True
    assert asked == [{4242}]


def test_un_reaper_ouvert_a_la_main_n_est_jamais_touche(win):
    win.setattr(desktop, "_golem_reaper_pids", lambda: set())          # aucun projet de sets/ dans sa ligne de commande
    win.setattr(DW, "request_reaper_close", lambda pids: pytest.fail("a REAPER opened by hand got WM_CLOSE"))
    assert desktop._close_leftover_reaper(wait_s=1) is True


def test_un_reaper_qui_ne_se_ferme_pas_est_dit_et_le_fige_est_termine(win):
    win.setattr(desktop, "_golem_reaper_pids", lambda: {4242})
    win.setattr(DW, "request_reaper_close", lambda pids: 1)
    hung = []
    win.setattr(desktop, "_close_hung_reaper", lambda: hung.append(1) or 0)
    t = iter(range(0, 1000, 10))
    win.setattr(desktop.time, "monotonic", lambda: next(t))
    assert desktop._close_leftover_reaper(wait_s=30) is False, "toujours ouvert : start refusera, avec sa raison"
    assert hung == [1], "un REAPER figé est terminé, un vivant est laissé à l'utilisateur"
