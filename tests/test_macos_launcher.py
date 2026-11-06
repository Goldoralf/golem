# SPDX-License-Identifier: GPL-3.0-or-later
"""Lanceur macOS (docs/platforms.md, M7) : apps dans ~/Applications, prérequis dits."""
import os
import plistlib
from pathlib import Path

from provision import desktop

ROOT = Path(__file__).resolve().parents[1]


def test_three_apps_like_the_windows_shortcuts(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    for old in ("GoleM Phone", "GoleM", "Stop GoleM"):                   # posées par une install d'avant le 2026-10-06
        (tmp_path / f"{old}.app" / "Contents").mkdir(parents=True)
    paths = desktop.mac_shortcuts(tmp_path)
    # deux usages (docs/installer.md §4) : la fenêtre et le server ; la coquille de téléphone est du dev
    # la marque s'écrit golem (2026-10-06) : les anciens noms sont retirés, pas laissés à côté
    assert [Path(p).name for p in paths] == ["golem.app", "golem server.app", "Stop golem.app"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Stop golem.app", "golem server.app", "golem.app"]
    for (name, command, _), p in zip(desktop.MAC_APPS, paths):
        info = plistlib.loads((Path(p) / "Contents" / "Info.plist").read_bytes())
        assert info["CFBundleExecutable"] == "run" and info["CFBundleName"] == name
        run = (Path(p) / "Contents" / "MacOS" / "run").read_bytes()
        assert run.startswith(b"#!/bin/bash\n") and b"\r" not in run
        assert f"-m provision.desktop {command} >>".encode() in run


def test_app_script_quotes_paths_with_spaces_and_quotes():
    s = desktop.mac_app_script("start", root="/Users/w/My GoleM", python="/Users/w/it's/.venv/bin/python")
    assert "cd '/Users/w/My GoleM' || exit 1" in s
    assert "exec '/Users/w/it'\\''s/.venv/bin/python' -m provision.desktop start" in s


def test_missing_reaper_and_nam_are_said_with_the_pinned_urls(tmp_path, monkeypatch):
    monkeypatch.setenv("REAPER_BIN", str(tmp_path / "nope" / "REAPER"))
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)
    missing = desktop.mac_prerequisites()
    assert len(missing) in (1, 2)                      # NAM peut exister dans /Library sur la machine de test
    assert "reaper779_universal.dmg" in missing[0]


def test_the_double_click_installer_is_executable_lf_bash():
    f = ROOT / "install-macos.command"
    data = f.read_bytes()
    assert data.startswith(b"#!/bin/bash\n")
    assert "installer/server.py" in data.decode() and "*.command text eol=lf" in (ROOT / ".gitattributes").read_text()
    if os.name != "nt":
        assert os.access(f, os.X_OK)


def test_autostart_launch_agent_starts_the_server_app(tmp_path, monkeypatch):
    """La boîte dédiée sous macOS (docs/installer.md §4) : un LaunchAgent qui lance GoleM Server.app à
    l'ouverture de session ; off le retire, status le dit."""
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop.Path, "home", classmethod(lambda cls: tmp_path))
    assert desktop.autostart("status") == "autostart: off"
    assert "automatic" in desktop.autostart("on")
    agent = plistlib.loads((tmp_path / "Library" / "LaunchAgents" / "fm.golem.server.plist").read_bytes())
    assert agent["RunAtLoad"] is True
    assert agent["ProgramArguments"] == [str(tmp_path / "Applications" / "golem server.app" / "Contents" / "MacOS" / "run")]
    assert desktop.autostart("status").startswith("autostart: on")
    desktop.autostart("off")
    assert desktop.autostart("status") == "autostart: off"


def test_restart_d_un_server_relance_un_server(monkeypatch):
    """« Update & restart » : le bridge passe son GOLEM_LAUNCH au lanceur — un server revient sans fenêtre."""
    calls = []
    for name in ("stop", "bridge_answers", "reaper_running"):
        monkeypatch.setattr(desktop, name, lambda *a, **k: False)
    monkeypatch.setattr(desktop.time, "sleep", lambda s: None)
    monkeypatch.setattr(desktop, "start", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setenv("GOLEM_LAUNCH", "server")
    desktop.restart()
    monkeypatch.setenv("GOLEM_LAUNCH", "desktop")
    desktop.restart("phone")
    assert calls == [((), {"window": False}), (("phone",), {})]
