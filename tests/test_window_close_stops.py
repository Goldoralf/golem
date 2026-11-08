# SPDX-License-Identifier: GPL-3.0-or-later
"""La croix de la fenêtre arrête golem desktop (décision du 2026-11-08, docs/ui-architecture.md §5).

Sous Windows, fermer un logiciel par sa croix le ferme : la fenêtre de golem fermée laissait REAPER et le bridge
tourner sans rien à l'écran. Ce qui reste vrai : « Continue on a tablet » ferme la fenêtre SANS arrêter golem,
`golem server` n'a pas de fenêtre, Linux garde son lanceur, et un WebSocket coupé sans que la fenêtre parte n'arrête
rien. Aucun processus réel n'est touché."""
import asyncio
import sys
import time
from pathlib import Path

import pytest

from bridge import machine

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def desktop(monkeypatch):
    machine._reset_for_tests()
    monkeypatch.delenv("GOLEM_MACHINE_DRY", raising=False)
    monkeypatch.setenv("GOLEM_LAUNCH", "desktop")
    monkeypatch.setattr(sys, "platform", "win32")
    yield
    machine._reset_for_tests()


def _closed_since(seconds):
    machine.window_opened()
    machine.window_closed()
    return time.monotonic() + seconds


def test_la_croix_arrete_golem_desktop_apres_le_delai():
    t = _closed_since(0)
    assert not machine.close_stops_golem(now=t + 1)                       # une page qui se recharge se reconnecte avant
    assert machine.close_stops_golem(now=t + machine.CLOSE_STOP_S + 0.1)


def test_une_fenetre_encore_ouverte_n_arrete_rien():
    machine.window_opened()
    machine.window_opened()
    machine.window_closed()
    assert not machine.close_stops_golem(now=time.monotonic() + 60)


def test_continuer_sur_une_tablette_n_arrete_pas_golem():
    t = _closed_since(0)
    machine.window_detached()
    assert not machine.close_stops_golem(now=t + 60)
    machine.window_opened()                                                 # rouverte : sa croix arrête de nouveau
    machine.window_closed()
    assert machine.close_stops_golem(now=time.monotonic() + machine.CLOSE_STOP_S + 0.1)


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_golem_desktop_sur_les_trois_systemes(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    t = _closed_since(0)
    assert machine.close_stops_golem(now=t + machine.CLOSE_STOP_S + 0.1)


@pytest.mark.parametrize("launch", ["server", None])
def test_ni_golem_server_ni_l_autostart(monkeypatch, launch):
    """L'autostart d'une boîte dédiée lance `golem server` (provision/autostart) : GOLEM_LAUNCH=server."""
    if launch:
        monkeypatch.setenv("GOLEM_LAUNCH", launch)
    else:
        monkeypatch.delenv("GOLEM_LAUNCH", raising=False)
    t = _closed_since(0)
    assert not machine.close_stops_golem(now=t + 60)


def test_jamais_avant_une_premiere_fenetre():
    assert not machine.close_stops_golem(now=time.monotonic() + 60)


# ── le déclenchement (bridge/app.py) ─────────────────────────────────────────────────────────────────
@pytest.fixture
def app(monkeypatch):
    from bridge import app as A
    from provision import desktop as D
    calls = []
    monkeypatch.setattr(A.routes_dev, "_ui_quit_desktop", lambda full: calls.append(full) or {"ok": True})
    monkeypatch.setattr(A.machine_mod, "close_stops_golem", lambda now=None: True)
    monkeypatch.setattr(A.state, "stopping", False, raising=False)
    return A, D, calls


def test_la_fenetre_partie_arrete_golem_par_le_chemin_du_bouton_stop(app, monkeypatch):
    A, D, calls = app
    monkeypatch.setattr(D, "app_window_pids", lambda: [])
    assert A.stop_if_window_closed() is True
    assert calls == [True] and A.state.stopping is True


def test_un_websocket_coupe_sans_que_la_fenetre_parte_n_arrete_rien(app, monkeypatch):
    A, D, calls = app
    monkeypatch.setattr(D, "app_window_pids", lambda: [4242])
    assert A.stop_if_window_closed() is False
    assert calls == [] and A.state.stopping is False


def test_deja_en_train_de_s_arreter(app, monkeypatch):
    A, D, calls = app
    monkeypatch.setattr(D, "app_window_pids", lambda: [])
    monkeypatch.setattr(A.state, "stopping", True, raising=False)
    assert A.stop_if_window_closed() is False and calls == []


def test_fermer_sans_stop_marque_la_fermeture_voulue(monkeypatch):
    """« Continue on a tablet » : /api/ui/quit sans `stop`."""
    from bridge import routes_dev
    monkeypatch.setattr(routes_dev, "_ui_quit_desktop", lambda full: {"ok": True})
    machine.window_opened()
    asyncio.run(routes_dev.ui_quit(None))
    machine.window_closed()
    assert not machine.close_stops_golem(now=time.monotonic() + 60)


def test_echap_ne_ferme_plus_la_fenetre():
    """Fermer arrête maintenant golem : Échap, pressé par réflexe, ne doit plus le faire."""
    html = (ROOT / "app" / "device.html").read_text(encoding="utf-8")
    handler = html[html.index("addEventListener('keydown'"):]
    handler = handler[:handler.index("});") + 3]
    assert "Escape" in handler and "quit()" not in handler


# ── Linux : le profil dédié de provision/golem, où qu'il soit (snap compris) ─────────────────────────
@pytest.mark.parametrize("ps, alive", [
    ("/usr/bin/chromium --app=http://127.0.0.1:8770/app/device.html --user-data-dir=/home/u/.local/share/golem/browser --window-size=1024,664", True),
    ("/snap/chromium/123/usr/lib/chromium-browser/chrome --user-data-dir=/home/u/snap/chromium/common/golem/browser", True),
    ("/usr/bin/google-chrome --user-data-dir=/home/u/.config/google-chrome", False),        # le navigateur personnel
    ("/usr/bin/firefox", False),
])
def test_linux_reconnait_la_fenetre_de_golem_seulement(monkeypatch, ps, alive):
    import subprocess
    from bridge import app as A
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": ps + "\n"})())
    assert A._window_alive() is alive
