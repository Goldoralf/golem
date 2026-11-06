# SPDX-License-Identifier: GPL-3.0-or-later
"""La table Windows est COMPLÈTE (révision 2, 2026-10-02) : chaque type du catalogue est soit sous
`effects` (traduit, ou `unsupported`), soit sous `unmapped` avec sa famille — « absent » ne veut plus
rien dire, et golem.fm peut dire bloc par bloc ce qui existe sous Windows sans le déclarer à la main.
`unmapped` est DESCRIPTIF : golem_rig et le bridge ne lisent que `effects` (une entrée là passerait le
bloc en résolution stricte)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAMILIES = {"reaper-jsfx", "golem-jsfx", "reaper-plugin", "core", "no-plugin", "installed-plugin", "untested"}


def _load():
    cat = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json")))["effects"]
    win = json.load(open(os.path.join(ROOT, "library", "catalog", "effects-windows.json"), encoding="utf-8"))
    return {e["type"] for e in cat}, win


def test_every_catalog_type_is_accounted_for_on_windows():
    types, win = _load()
    mapped, unmapped = set(win["effects"]), set(win["unmapped"])
    assert not (mapped & unmapped)
    assert mapped | unmapped == types, sorted(types ^ (mapped | unmapped))


def test_unmapped_entries_are_well_formed():
    _, win = _load()
    for t, e in win["unmapped"].items():
        assert e["family"] in FAMILIES, t
        assert ("why" in e) == (e["family"] == "untested"), t


def test_the_engine_only_reads_effects():
    src = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    assert "wd.unmapped" not in src and "pairs(wd.effects)" in src
    bs = open(os.path.join(ROOT, "bridge", "blockstatus.py"), encoding="utf-8").read()
    assert "unmapped" not in bs
