# SPDX-License-Identifier: GPL-3.0-or-later
"""Blocs sous macOS (docs/platforms.md, M6) : une table de plugins par OS desktop.

Avant : sous macOS golem_rig cherchait les noms LINUX (Calf, guitarix…) et chargeait les NAM « pédale »
par le chemin LV2 du rack ; le bridge ne lisait la table qu'à Windows ; VST Host était fermé."""
import json
import os

from bridge import blockstatus, routes_content

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "library", "catalog")


def _tables():
    load = lambda n: json.load(open(os.path.join(CAT, n), encoding="utf-8"))
    return load("effects.json"), load("effects-windows.json"), load("effects-macos.json")


def test_the_mac_table_is_complete_like_windows():
    cat, _, mac = _tables()
    types = {e["type"] for e in cat["effects"]}
    mapped, unmapped = set(mac["effects"]), set(mac["unmapped"])
    assert not (mapped & unmapped) and mapped | unmapped == types, sorted(types ^ (mapped | unmapped))
    for t, e in mac["unmapped"].items():
        assert ("why" in e) == (e["family"] == "untested"), t


def test_the_mac_table_rests_on_what_vendors_publish():
    """Révision 2 : chaque refus dit une absence VÉRIFIÉE ; ce qui existe sur Mac garde le nom Windows."""
    _, win, mac = _tables()
    assert mac["revision"] >= 2 and mac["sources"]["checked"] == "2026-10-04"
    for t, e in mac["effects"].items():
        if "unsupported" in e:
            assert "non vérifié" not in e["unsupported"], t
        else:
            assert e.get("plugin") == win["effects"][t].get("plugin"), t      # noms à confirmer au scan
    calf = [t for t, e in mac["effects"].items() if "Calf" in e.get("unsupported", "")]
    gx = [t for t, e in mac["effects"].items() if "guitarix" in e.get("unsupported", "")]
    # 2026-10-22 : delay-tape (Calf) et reverb-shimmer (guitarix) ne sont plus des refus — golem_tapedelay.jsfx et
    # golem_shimmer.jsfx les jouent (test_portable_jsfx_blocks.py) ; le soir, la famille wah (wah, wah-color,
    # autowah) les rejoint : 8 refus guitarix -> 5 ; puis chorus, tremolo, phaser, flanger, rotary : 5 refus Calf -> 0 ;
    # octaver, vibrato, eq-graphic : 5 refus guitarix -> 2 ; delay-echo (golem_echocat) : -> 1 (detune, en quarantaine)
    assert len(calf) == 0 and len(gx) == 1


def test_x42_lv2_resolve_like_the_rack():
    """x42 publie limiter, autotune et eq pour macOS : AUCUNE entrée stricte, le nom Linux du LV2 sert."""
    _, _, mac = _tables()
    for t in ("limiter", "pitch-correct", "eq-para"):
        assert t not in mac["effects"] and mac["unmapped"][t]["family"] == "installed-plugin", t
    assert mac["unmapped"]["drumkit"]["family"] == "installed-plugin"
    assert mac["unmapped"]["vital"]["family"] == "installed-plugin"


def test_bridge_reads_the_table_of_its_os(monkeypatch):
    monkeypatch.setattr(blockstatus.sys, "platform", "darwin")
    assert blockstatus.desktop_table().endswith("effects-macos.json")
    e = blockstatus.effects()
    assert e["reverb"]["windows_strict"] and e["reverb"]["plugin"].startswith("VST3: Dragonfly")
    assert blockstatus.candidates("detune") == []                  # guitarix : unsupported, pas d'alias Linux (les autres sont joues par un JSFX golem depuis le 2026-10-22)
    monkeypatch.setattr(blockstatus.sys, "platform", "linux")
    assert "windows_strict" not in blockstatus.effects()["reverb"]


def test_lua_resolves_by_the_desktop_table_on_both_oses():
    src = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    assert "WINDOWS_FX" not in src
    assert 'local DESKTOP_TABLE = MAC_FX and "effects-macos.json" or "effects-windows.json"' in src
    assert 'local MAC_FX = _GOS:match("^OSX") ~= nil or _GOS:match("^macOS") ~= nil' in src


def test_vst_host_is_offered_on_macos(monkeypatch):
    monkeypatch.setattr(routes_content.sys, "platform", "darwin")
    data = routes_content.get_effects()
    assert data.get("vst_host") and any(e["type"] == "vst-host" for e in data["effects"])
    monkeypatch.setattr(blockstatus.sys, "platform", "darwin")
    inv = {"names": set(), "idents": set(), "qualified_names": {"vst3: surge xt (surge synth team)"}}
    st = blockstatus.block_state({"type": "vst-host", "plugin": "VST3: Surge XT (Surge Synth Team)"},
                                 inv=inv, obs={})
    assert st["state"] != "unavailable", st
    st = blockstatus.block_state({"type": "vst-host", "plugin": "VST3: Gone (X)"}, inv=inv, obs={})
    assert st["why"] == "plugin not installed on this machine"
