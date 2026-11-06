# SPDX-License-Identifier: GPL-3.0-or-later
"""reaper/Scripts/__startup.lua : un script qui casse AU CHARGEMENT ne coupe plus les suivants (audit macOS 2026-11-04)."""
import os

import pytest

lupa = pytest.importorskip("lupa")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STARTUP = os.path.join(ROOT, "reaper", "Scripts", "__startup.lua")


def test_a_script_that_fails_to_load_is_logged_and_the_next_ones_still_load(tmp_path):
    res, root = tmp_path / "res", tmp_path / "root"
    (res / "Scripts" / "golem").mkdir(parents=True)
    (root / "reaper" / "Scripts").mkdir(parents=True)
    (root / "presets").mkdir()
    (res / "golem-root.txt").write_text(str(root) + "\n", encoding="utf-8")
    scripts = root / "reaper" / "Scripts"
    (scripts / "golem_watch.lua").write_text("error('veilleur cassé')\n", encoding="utf-8")
    (scripts / "golem_tuner.lua").write_text("LOADED[#LOADED + 1] = 'tuner'\n", encoding="utf-8")
    (scripts / "golem_midi.lua").write_text("LOADED[#LOADED + 1] = 'midi'\n", encoding="utf-8")
    L = lupa.LuaRuntime()
    L.execute("LOADED = {}")
    L.globals().RES = str(res)
    L.execute("""
      reaper = {
        GetResourcePath = function() return RES end,
        GetOS = function() return "macOS-arm64" end,
        defer = function(fn) end,
        file_exists = function(p) local f = io.open(p, "r"); if f then f:close(); return true end; return false end,
      }""")
    L.execute(open(STARTUP, encoding="utf-8").read())
    assert list(L.globals().LOADED.values()) == ["tuner", "midi"]
    log = (root / "presets" / ".lua-errors.log").read_text(encoding="utf-8")
    assert "golem_watch.lua" in log and "veilleur cassé" in log
