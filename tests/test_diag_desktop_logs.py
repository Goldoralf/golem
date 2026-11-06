# SPDX-License-Identifier: GPL-3.0-or-later
"""Le paquet diag sous macOS / Windows : les journaux que golem écrit, pas journald (premier Mac réel, 2026-11-04)."""
import os
import time

from bridge import diag


def test_macos_bundle_carries_bridge_launcher_and_a_recent_reaper_crash(tmp_path, monkeypatch):
    res = tmp_path / "REAPER"
    (res / "GoleM" / "logs").mkdir(parents=True)
    (res / "GoleM" / "logs" / "bridge.log").write_text("golem.boot I démarré\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / "Library" / "Logs" / "DiagnosticReports").mkdir(parents=True)
    (home / "Library" / "Logs" / "GoleM-launcher.log").write_text("golem is running\n", encoding="utf-8")
    old = home / "Library" / "Logs" / "DiagnosticReports" / "REAPER-2026-10-01.ips"
    old.write_text("old crash\n", encoding="utf-8")
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    (home / "Library" / "Logs" / "DiagnosticReports" / "REAPER-2026-11-04.ips").write_text("new crash\n", encoding="utf-8")
    monkeypatch.setattr(diag.sys, "platform", "darwin")
    monkeypatch.setattr(diag.C, "reaper_resource_dir", lambda: str(res))
    monkeypatch.setenv("HOME", str(home))
    logs, missing = diag.collect_logs(3600, sc=lambda ln: ln)
    assert "démarré" in logs["bridge.log"] and "running" in logs["launcher.log"]
    assert logs["reaper-crash.ips"].strip() == "new crash"
    assert missing == [] and not any("journald" in m or "apport" in m for m in missing)


def test_a_missing_desktop_log_is_said(tmp_path, monkeypatch):
    monkeypatch.setattr(diag.sys, "platform", "darwin")
    monkeypatch.setattr(diag.C, "reaper_resource_dir", lambda: str(tmp_path / "none"))
    monkeypatch.setenv("HOME", str(tmp_path))
    _logs, missing = diag.collect_logs(3600, sc=lambda ln: ln)
    assert "bridge.log" in missing and "launcher.log" in missing
