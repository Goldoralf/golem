# SPDX-License-Identifier: GPL-3.0-or-later
"""NAM 0.7.15 bâti par golem (2026-10-22) : les versions officielles 0.7.14/0.7.15 ne publient aucun binaire et 0.7.13
ne lit pas les captures A2 — le 0.7.15 bâti depuis le tag amont les lit (mesuré). Épinglé dans les deux pins.json,
posé PAR-DESSUS l'officiel ; l'A2 n'est refusée que là où ce build n'est pas posé."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pins(osn):
    return json.load(open(os.path.join(ROOT, "provision", osn, "pins.json"), encoding="utf-8"))


def test_les_deux_pins_portent_le_build_golem():
    win, mac = _pins("windows"), _pins("macos")
    for p in (win, mac):
        assert p["nam_golem"]["version"] == "0.7.15" and re.fullmatch(r"[0-9a-f]{64}", p["nam_golem"]["sha256"])
        assert p["nam_golem"]["url"].startswith("https://github.com/Goldoralf/golem-binaries/releases/download/nam-0.7.15-golem/")
    assert re.fullmatch(r"[0-9a-f]{64}", win["nam_golem"]["replaces_sha256"])     # seule la DLL du 0.7.13 officiel est remplacée


def test_l_installeur_windows_ne_remplace_que_l_officiel():
    s = open(os.path.join(ROOT, "provision", "windows", "install-system.ps1"), encoding="utf-8-sig").read()
    assert "$pins.nam_golem.replaces_sha256" in s and "CheckSha $gz $pins.nam_golem.sha256" in s
    assert "kept as is (A2 captures stay unavailable)" in s and "golem-nam-version.txt" in s


def test_l_a2_n_est_refusee_que_sans_le_build_golem(monkeypatch):
    from bridge import rig
    monkeypatch.setattr(rig, "_platform", lambda: "win32")
    monkeypatch.setattr(rig, "_nam_golem_version", lambda: "")
    assert rig.nam_unreadable() == ["SlimmableContainer"]
    monkeypatch.setattr(rig, "_nam_golem_version", lambda: "0.7.15")
    assert rig.nam_unreadable() == []
    monkeypatch.setattr(rig, "_platform", lambda: "linux")
    assert rig.nam_unreadable() == []


def test_golem_rig_accepte_l_etat_0_7_15_et_regle_slim():
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    assert 'fields[2] ~= "0.7.15"' in lua and "function set_nam_slim(tr, fx)" in lua
    assert lua.count("set_nam_slim(tr, fx)") >= 3                          # la définition + le cœur + les blocs NAM
