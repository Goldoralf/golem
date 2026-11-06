# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bloc piano joue sous Windows (2026-10-22) : la table le cartographie sur le VST3 de sfizz — que l'installeur
pose (-Sfizz) — et l'installeur propose et télécharge le pack piano (Salamander, empreinte épinglée). macOS reste
« untested » tant qu'aucun Mac ne l'a joué : la raison le dit, elle ne promet pas."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _table(name):
    return json.load(open(os.path.join(ROOT, "library", "catalog", name), encoding="utf-8"))


def test_la_table_windows_cartographie_le_piano_sur_sfizz_vst3():
    win = _table("effects-windows.json")
    assert "piano" not in win["unmapped"]
    assert win["effects"]["piano"]["plugin"] == "VST3i: sfizz (SFZTools)"
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    assert '"VST3i: sfizz (SFZTools)"' in lua and "sfizz_vst3_set_file" in lua     # le nom ET le chargeur


def test_macos_reste_non_teste_et_le_dit():
    mac = _table("effects-macos.json")
    assert mac["unmapped"]["piano"]["family"] == "untested" and "no Mac" in mac["unmapped"]["piano"]["why"]


def test_l_installeur_windows_propose_et_pose_le_pack_piano():
    win = open(os.path.join(ROOT, "installer", "platform_windows.py"), encoding="utf-8").read()
    assert '"packs_unavailable": {"drums":' in win and '"piano": "the piano block does not play on Windows yet"' not in win
    steps = open(os.path.join(ROOT, "installer", "desktop_steps.py"), encoding="utf-8").read()
    assert "def _sound_piano(" in steps and 'if "piano" in (ctx.S.get("packs") or ()):' in steps
    from installer import desktop_steps as DS
    pinned = DS._pinned(ROOT, DS.PIANO_URL)
    assert pinned and len(pinned) == 64                                         # la même empreinte que Linux
    assert DS.PIANO_URL.endswith(DS.PIANO_DIR + ".tar.gz")
