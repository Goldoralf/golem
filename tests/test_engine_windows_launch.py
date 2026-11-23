# SPDX-License-Identifier: GPL-3.0-or-later
"""LE LANCEMENT DU GOLEM ENGINE SOUS WINDOWS (VM Windows 11 vierge, 2026-11-23).

Lancé par pythonw.exe en DETACHED_PROCESS, run.py n'avait aucune console : le moteur (programme console) s'en ouvrait une
VISIBLE par-dessus golem, et son journal y partait au lieu de golem-engine.log. Il lui faut une console CACHÉE
(CREATE_NO_WINDOW) portée par python.exe — pythonw.exe, programme sans console, ne peut pas en porter."""
import subprocess
import sys

from bridge.engine import ardour as A


def test_run_py_is_never_started_by_pythonw_on_windows(monkeypatch, tmp_path):
    (tmp_path / "python.exe").write_bytes(b"")
    (tmp_path / "pythonw.exe").write_bytes(b"")
    monkeypatch.setattr(A.sys, "platform", "win32")
    monkeypatch.setattr(A.sys, "executable", str(tmp_path / "pythonw.exe"))
    assert A._console_python() == str(tmp_path / "python.exe")
    monkeypatch.setattr(A.sys, "executable", str(tmp_path / "python.exe"))
    assert A._console_python() == str(tmp_path / "python.exe")


def test_elsewhere_the_interpreter_is_kept(monkeypatch):
    monkeypatch.setattr(A.sys, "platform", "linux")
    monkeypatch.setattr(A.sys, "executable", "/x/pythonw.exe")
    assert A._console_python() == "/x/pythonw.exe"


def test_the_engine_gets_a_hidden_console_not_a_detached_process(monkeypatch, tmp_path):
    eng = tmp_path / "golem" / "engine"
    eng.mkdir(parents=True)
    (eng / "run.sh").write_text("")
    (eng / "run.py").write_text("")
    seen = {}
    monkeypatch.setattr(A, "ENGINE_DIR", str(tmp_path))
    monkeypatch.setattr(A, "RUN_LOG", str(tmp_path / "engine.log"))
    monkeypatch.setattr(A.sys, "platform", "win32")
    monkeypatch.setattr(A.ArdourEngine, "stop", lambda self: True)
    monkeypatch.setattr(A.subprocess, "Popen", lambda cmd, **k: seen.update(cmd=cmd, **k))
    A.ArdourEngine().restart("test")
    flags = seen["creationflags"]
    assert flags & 0x08000000                       # CREATE_NO_WINDOW
    assert not flags & 0x00000008                   # plus DETACHED_PROCESS
    assert seen["stdout"] is not None and seen["stderr"] == subprocess.STDOUT


def test_reaper_restarts_without_an_asio_driver_as_golem_desktop_starts_it(monkeypatch):
    """VM Windows 11, 2026-11-23 : sans pilote ASIO, passer du Golem Engine à REAPER échouait sur « Choose an installed
    ASIO driver » (start_apply), alors que `golem desktop` démarre REAPER sans carte. Le redémarrage fait comme lui."""
    from bridge import desktop_audio
    from bridge.engine import reaper as R
    from provision import desktop
    seen = {}
    monkeypatch.setattr(sys, "platform", "win32")          # restart() lit sys.platform (import local)
    monkeypatch.setattr(desktop_audio, "settings", lambda: {"driver": None, "drivers": []})
    monkeypatch.setattr(desktop_audio, "start_apply", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no apply")))
    monkeypatch.setattr(desktop_audio, "_reopen_args", lambda binary, actual: [str(binary), "-nosplash", "-new"])
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(desktop, "reaper_binary", lambda: "reaper.exe")
    monkeypatch.setattr(desktop, "launch_reaper", lambda args, **k: seen.update(args=args))
    out = R.ReaperEngine().restart("switch")
    assert out["ok"] and seen["args"] == ["reaper.exe", "-nosplash", "-new"]
