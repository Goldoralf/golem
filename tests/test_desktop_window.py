# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop backend launches stay hidden and scoped to the GoleM session."""
import json
import subprocess
import sys

import pytest

from provision import desktop


@pytest.mark.skipif(sys.platform != "win32", reason="Windows startup flags")
def test_windows_launch_hides_window_and_registers_own_pid(tmp_path, monkeypatch):
    marker = tmp_path / "backend-pids.json"
    monkeypatch.setattr(desktop, "_backend_pids_file", lambda: marker)
    seen = []

    class Process:
        pid = 12345

    def popen(args, **kwargs):
        seen.append((args, kwargs))
        return Process()

    monkeypatch.setattr(desktop.subprocess, "Popen", popen)
    desktop.launch_reaper(["C:/Program Files/REAPER/reaper.exe", "-nosplash"])
    startup = seen[0][1]["startupinfo"]
    assert startup.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startup.wShowWindow == 0
    assert json.loads(marker.read_text(encoding="ascii")) == [12345]
    desktop.unregister_reaper_pid(12345)
    assert json.loads(marker.read_text(encoding="ascii")) == []


def test_macos_launch_uses_hidden_app_bundle(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    seen = []
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda args, **kwargs: seen.append(args))
    desktop.launch_reaper(["/Applications/REAPER.app/Contents/MacOS/REAPER", "-nosplash", "-new"])
    assert seen == [["open", "-j", "-a", "/Applications/REAPER.app", "--args", "-nosplash", "-new"]]
