# SPDX-License-Identifier: GPL-3.0-or-later
"""Le témoin du thread audio (presets/.clock.json, golem_clock.lua) : deux lectures suffisent — des ticks qui avancent
entre deux témoins = la carte joue ; figés = thread audio mort ; `t` figé = la boucle Lua, pas la carte. La première
lecture ne conclut jamais (le moniteur la relit 1,2 s plus tard au lieu d'attendre son cycle de 3 s : l'écran de
chargement, 2026-10-20). `.venv/bin/python -m pytest tests/test_audio_witness.py -q`"""
import json

from bridge import monitors as M


def _witness(tmp_path, ticks, t):
    (tmp_path / ".clock.json").write_text(json.dumps({"ticks": ticks, "t": t, "on": True}), encoding="utf-8")


def test_deux_temoins_suffisent_et_la_premiere_lecture_ne_conclut_pas(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(M, "_CLOCK_W", {"ticks": None, "t": None})
    assert M._audio_alive() == (None, "pas de témoin")
    _witness(tmp_path, 100, 10.0)
    assert M._audio_alive() == (None, "première lecture")
    _witness(tmp_path, 180, 11.0)
    assert M._audio_alive() == (True, "")
    _witness(tmp_path, 180, 12.0)                              # t avance, les ticks non : la carte
    ok, why = M._audio_alive()
    assert ok is False and "stalled" in why
    _witness(tmp_path, 180, 12.0)                              # rien ne bouge : la boucle Lua, pas la carte
    assert M._audio_alive()[0] is None


def test_le_moniteur_relit_vite_apres_la_premiere_lecture():
    """Le code du moniteur porte la relecture courte — pas de boucle à faire tourner ici : on lit la source."""
    import inspect
    src = inspect.getsource(M._monitor_audio)
    i = src.index('why == "première lecture"')
    assert "asyncio.sleep(1.2)" in src[i:i + 200] and "_audio_alive" in src[i:i + 300]
    assert "asyncio.sleep(0.5 if alive is None and not _boot_done() else 3)" in src, "cadence courte tant que la carte n'a pas de verdict au démarrage"
