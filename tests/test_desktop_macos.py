# SPDX-License-Identifier: GPL-3.0-or-later
"""Sondes macOS (docs/platforms.md, M1) : le parsing partout, les appels réels sur un Mac (CI)."""
import sys
from subprocess import CompletedProcess

import pytest

from bridge import desktop_macos as M
from bridge import monitors, rigstatus

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12000.
Pages active:                            300000.
Pages inactive:                          100000.
Pages speculative:                         8000.
Pages throttled:                              0.
Pages wired down:                         90000.
Pages purgeable:                           5000.
"Translation faults":                 123456789.
"""


def test_vm_stat_reads_its_page_size():
    vm = M.parse_vm_stat(VM_STAT)
    assert vm["page_size"] == 16384
    assert vm["pages"]["pages inactive"] == 100000
    assert vm["pages"]["translation faults"] == 123456789


def test_ram_counts_reclaimable_pages_as_available():
    total = 16 * 1024 ** 3                                  # 16 Gio = 1 048 576 pages de 16 Kio
    ram = M.ram_from(total, M.parse_vm_stat(VM_STAT))
    avail = (12000 + 100000 + 8000 + 5000) * 16384
    assert ram == {"total_mb": 16384, "used_pct": round(100 * (total - avail) / total)}


def test_ram_unreadable_is_none():
    assert M.ram_from(0, None) is None
    assert M.parse_vm_stat("garbage") is None


@pytest.mark.parametrize("s,sec", [("05:07", 307), ("1:02:03", 3723), ("2-01:00:00", 176400),
                                   ("  00:00 ", 0), ("x", None), ("", None)])
def test_ps_etime(s, sec):
    assert M.parse_etime(s) == sec


def test_ps_line():
    assert M.parse_ps(" 512000   1:00:00\n") == {"rss_mb": 524, "uptime_s": 3600}
    assert M.parse_ps("") is None


def test_process_started_from_ps(monkeypatch):
    monkeypatch.setattr(M.subprocess, "run", lambda args, **kw: CompletedProcess(args, 0, "1000 01:40\n", ""))
    monkeypatch.setattr(M.time, "time", lambda: 10_000.0)
    assert M.process_started(42) == 9_900.0


def test_process_started_unreadable_raises(monkeypatch):
    monkeypatch.setattr(M.subprocess, "run", lambda args, **kw: CompletedProcess(args, 1, "", ""))
    with pytest.raises(OSError):
        M.process_started(42)


def test_monitors_uses_ps_on_macos(monkeypatch):
    """Le bug corrigé sous Windows le 2026-10-02 (rig adopté d'un REAPER précédent) attendait sur Mac."""
    monkeypatch.setattr(monitors.sys, "platform", "darwin")
    monkeypatch.setattr(M, "process_started", lambda pid: 123.0)
    assert monitors._process_started(7) == 123.0


def test_health_finds_reaper_by_its_mac_name(monkeypatch):
    from bridge import routes_system
    monkeypatch.setattr(routes_system.sys, "platform", "darwin")
    monkeypatch.setattr(rigstatus.sys, "platform", "darwin")
    monkeypatch.setattr(monitors, "_reaper_pid", lambda: 4242)
    monkeypatch.setattr(M, "process_info", lambda pid: {"rss_mb": 800, "uptime_s": 60})
    monkeypatch.setattr(M, "cpu_pct", lambda interval=0.25: 12.5)
    monkeypatch.setattr(M, "ram", lambda: {"total_mb": 16384, "used_pct": 40})
    out = routes_system.system_health()
    assert out["reaper"] == {"running": True, "pid": 4242, "rss_mb": 800, "uptime_s": 60}
    assert out["cpu_pct"] == 12.5 and out["ram"]["used_pct"] == 40


@pytest.mark.skipif(sys.platform != "darwin", reason="appels système réels : sur un Mac (CI macos-26)")
def test_real_probes_on_a_mac():
    assert 0 <= (M.cpu_pct(0.1) or 0) <= 100
    ram = M.ram()
    assert ram and ram["total_mb"] > 1000 and 0 < ram["used_pct"] < 100
    import os
    assert M.process_info(os.getpid())["rss_mb"] > 0
