# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop REAPER process health uses native discovery instead of Linux /proc."""
from subprocess import CompletedProcess

from bridge import monitors
from provision import desktop


def test_windows_reaper_pid_from_tasklist(monkeypatch):
    monkeypatch.setattr(monitors.sys, "platform", "win32")
    for raw in (b'"reaper.exe","40064","Console","1","200,000 K"\r\n',
                '"reaper.exe","40064","Console","1","200,000 K"\r\n'.encode("utf-16")):
        monkeypatch.setattr(monitors.subprocess, "run", lambda args, raw=raw, **kwargs:
                            CompletedProcess(args, 0, raw, b""))
        assert monitors._reaper_pid() == 40064


def test_desktop_launcher_detects_utf16_tasklist(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    raw = '"reaper.exe","40064","Console","1","200,000 K"\r\n'.encode("utf-16")
    monkeypatch.setattr(desktop.subprocess, "run", lambda args, **kwargs: CompletedProcess(args, 0, raw, b""))
    assert desktop.reaper_running()


def test_macos_reaper_pid_from_pgrep(monkeypatch):
    monkeypatch.setattr(monitors.sys, "platform", "darwin")
    monkeypatch.setattr(monitors.subprocess, "run", lambda args, **kwargs:
                        CompletedProcess(args, 0, "1234\n", ""))
    assert monitors._reaper_pid() == 1234
