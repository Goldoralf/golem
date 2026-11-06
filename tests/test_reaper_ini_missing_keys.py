# SPDX-License-Identifier: GPL-3.0-or-later
"""Un reaper.ini neuf n'a pas linux_audio_bsize (REAPER n'écrit une clé que si elle diffère de son défaut) : changer le
buffer dans System ▸ Dashboard répondait « ✗ linux_audio_bsize missing from reaper.ini » sur tout golem neuf
(2026-11-03). La clé absente est AJOUTÉE dans [reaper], jamais refusée ; une clé présente est remplacée."""
import asyncio
import sys

import pytest

from bridge import routes_system as rs


def test_ini_set_ajoute_dans_la_section_reaper():
    t = rs._ini_set("[audio]\nx=1\n[reaper]\nautomute=0\n[other]\ny=2\n", "linux_audio_bsize", 256)
    assert "[reaper]\nlinux_audio_bsize=256\nautomute=0\n" in t
    assert t.index("linux_audio_bsize") < t.index("[other]")


def test_ini_set_remplace_une_seule_fois():
    t = rs._ini_set("[reaper]\nlinux_audio_bsize=128\nlinux_audio_bsize_x=9\n", "linux_audio_bsize", 64)
    assert "linux_audio_bsize=64\n" in t and "linux_audio_bsize=128" not in t and "linux_audio_bsize_x=9" in t


def test_ini_set_sans_section():
    assert rs._ini_set("", "alsa_indev", "hw:iTwo").startswith("[reaper]\nalsa_indev=hw:iTwo\n")


@pytest.mark.skipif(sys.platform != "linux", reason="buffer Linux : reaper.ini")
def test_buffer_accepte_un_ini_sans_la_cle(tmp_path, monkeypatch):
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\nlinux_audio_mode=1\nalsa_indev=hw:iTwo\n", encoding="utf-8")
    monkeypatch.setattr(rs, "REAPER_INI", str(ini))
    calls = {}
    monkeypatch.setattr(rs, "_restart_reaper_async", lambda after_dead=None, why=None: calls.update(f=after_dead))
    from bridge import install_receipt, monitors
    monkeypatch.setattr(install_receipt, "prior", lambda *a, **k: None)
    monkeypatch.setattr(monitors, "xruns_clear", lambda: None)
    r = asyncio.run(rs.audio_buffer({"size": 128}))
    assert isinstance(r, dict) and r["ok"], r
    calls["f"]()                                              # REAPER « mort » : l'ini est réécrit
    assert "linux_audio_bsize=128" in ini.read_text(encoding="utf-8")
