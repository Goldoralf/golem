# SPDX-License-Identifier: GPL-3.0-or-later
"""Un seul lanceur à la fois (VM Windows vierge, 2026-10-16) : le bouton de fin de l'installateur lançait le golem,
l'utilisateur le relançait par l'icône pendant le premier démarrage (long), et les deux bridges tombaient."""
import subprocess
import sys
import textwrap

import pytest

from provision import desktop


@pytest.fixture
def rdir(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop, "resource_dir", lambda: tmp_path)
    yield tmp_path
    if desktop._LOCK is not None:
        desktop._LOCK.close()
        desktop._LOCK = None


def test_le_premier_lanceur_prend_le_verrou_un_autre_processus_non(rdir):
    assert desktop._launcher_lock() is True
    # un AUTRE processus (le second clic sur l'icône) ne l'obtient pas
    code = textwrap.dedent(f"""
        import sys; sys.path.insert(0, {str(desktop.ROOT)!r})
        from pathlib import Path
        from provision import desktop
        desktop.resource_dir = lambda: Path({str(rdir)!r})
        print(desktop._launcher_lock())
    """)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "False", out.stderr


def test_le_second_lanceur_attend_puis_ouvre_la_fenetre_sans_demarrer_de_bridge(rdir, monkeypatch):
    monkeypatch.setattr(desktop, "venv_python", lambda: desktop.Path(desktop.sys.executable))
    monkeypatch.setattr(desktop, "_launcher_lock", lambda: False)        # un autre lanceur tient le verrou
    answers = iter([False, False, True])
    monkeypatch.setattr(desktop, "bridge_answers", lambda port: next(answers, True))
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    opened = []
    monkeypatch.setattr(desktop, "open_window", lambda *a, **k: opened.append(a))
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: pytest.fail("a second bridge was started"))
    desktop.start(window=True)
    assert opened


def test_un_premier_demarrage_qui_ne_finit_pas_est_dit(rdir, monkeypatch):
    monkeypatch.setattr(desktop, "venv_python", lambda: desktop.Path(desktop.sys.executable))
    monkeypatch.setattr(desktop, "_launcher_lock", lambda: False)
    monkeypatch.setattr(desktop, "bridge_answers", lambda port: False)
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="still starting"):
        desktop.start(window=True)


def test_un_bridge_vivant_mais_lent_n_est_plus_tue(rdir, monkeypatch, tmp_path):
    """VM Windows vierge, 2026-10-16 : « 100 tours » de 0,1 s faisaient ~10 s ; le premier démarrage d'un Windows neuf
    est plus long, le lanceur tuait un bridge sain et disait « did not start ». Vivant, on l'attend (BRIDGE_START_S)."""
    import urllib.error
    clock = {"t": 0.0}
    monkeypatch.setattr(desktop.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(desktop.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))

    class Bridge:
        done = False

        def poll(self):
            return 0 if self.done else None

        def wait(self):                                       # la session se termine normalement
            self.done = True
            return 0

        def terminate(self):
            pytest.fail("a healthy bridge was killed while it was starting")

    def urlopen(url, timeout=None):
        if clock["t"] < 120:                                  # répond au bout de 2 minutes
            raise urllib.error.URLError("refused")
        return __import__("contextlib").nullcontext()
    monkeypatch.setattr(desktop.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **k: Bridge())
    monkeypatch.setattr(desktop, "venv_python", lambda: desktop.Path(desktop.sys.executable))
    monkeypatch.setattr(desktop, "reaper_binary", lambda: desktop.Path(desktop.sys.executable))
    monkeypatch.setattr(desktop, "_launcher_lock", lambda: True)
    monkeypatch.setattr(desktop, "bridge_health", lambda port: None)
    monkeypatch.setattr(desktop, "bridge_answers", lambda port: False)
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(desktop, "copy_resources", lambda d: None)
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "none.rpp")
    import socket
    with socket.socket() as so:                                  # un port LIBRE : 8770 est le vrai rack de ce poste
        so.bind(("127.0.0.1", 0))
        monkeypatch.setenv("GOLEM_PORT", str(so.getsockname()[1]))
    started = []
    monkeypatch.setattr(desktop, "_bring_up", lambda *a, **k: started.append(clock["t"]))
    monkeypatch.setattr(desktop, "_backend_pids_file", lambda: None)
    desktop.start(window=False)
    assert started and started[0] >= 120
