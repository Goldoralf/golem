# SPDX-License-Identifier: GPL-3.0-or-later
"""« Dropouts » voit les xruns de REAPER sous Linux (2026-11-24) : golem_clock.lua les publie dans .clock.json."""
import json
import sys

from bridge import config as C
from bridge.engine.reaper import ReaperEngine


def _witness(tmp_path, **kw):
    (tmp_path / ".clock.json").write_text(json.dumps({"ticks": 1, "t": 1.0, "on": True, **kw}), encoding="utf-8")


def test_les_xruns_de_reaper_sont_lus_dans_le_temoin(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    e = ReaperEngine()
    assert e.xruns() is None                            # pas de témoin : on ne sait pas
    _witness(tmp_path)                                  # ancien golem_clock, sans le champ
    assert e.xruns() is None
    _witness(tmp_path, xruns=4)
    assert e.xruns() == 4


def test_un_temoin_illisible_rend_la_derniere_valeur(monkeypatch, tmp_path):
    # un None ferait retomber le total au noyau seul, et la lecture suivante passerait pour une rafale
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "platform", "linux")
    e = ReaperEngine()
    _witness(tmp_path, xruns=3)
    assert e.xruns() == 3
    (tmp_path / ".clock.json").write_text("{", encoding="utf-8")
    assert e.xruns() == 3
    (tmp_path / ".clock.json").unlink()
    assert e.xruns() == 3


def test_windows_et_macos_ne_comptent_pas_deux_fois(monkeypatch, tmp_path):
    # golem_desktop_audio.lua les compte déjà là-bas (monitors._read_kernel_xruns)
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    _witness(tmp_path, xruns=9)
    for plat in ("win32", "darwin"):
        monkeypatch.setattr(sys, "platform", plat)
        assert ReaperEngine().xruns() is None
