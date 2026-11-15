# SPDX-License-Identifier: GPL-3.0-or-later
"""Phaser (JSFX) et Tape Delay (Airwindows) — les deux blocs qui existent sous Linux ET sous Windows, à côté
des blocs Calf (Linux seulement). Décision 2026-10-03 : « deux phasers et deux tape delays » sous
Linux, un de chaque sous Windows. Les noms et index viennent de `fxparams` lu dans REAPER le 2026-10-03."""
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
EFFECTS = {e["type"]: e for e in json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"),
                                                 encoding="utf-8"))["effects"]}
WIN = json.load(open(os.path.join(ROOT, "library", "catalog", "effects-windows.json"), encoding="utf-8"))

# fxparams, 2026-10-03 (REAPER 7.27, Windows) — le JSFX est le même fichier sous Linux
PHASER_SLIDERS = {0: ("Rate (Hz)", 0, 10), 1: ("Range Min (Hz)", 40, 20000), 2: ("Range Max (Hz)", 40, 20000),
                  3: ("Feedback (dB)", -120, -1), 4: ("Wet Mix (dB)", -120, 12)}


def test_le_phaser_jsfx_reste_et_les_anciens_sont_retires():
    # catalogue v48 (2026-11-15, « le golem ne tournera qu'avec nos blocs ») : le phaser Calf et les trois tape delays
    # (Calf, Airwindows, GxEchoCat) sont retirés ; un document qui les porte est réécrit au chargement (option_renames)
    assert EFFECTS["phaser-js"]["plugin"] == "JS: guitar/phaser"
    for t in ("phaser", "delay-tape", "delay-tape-aw", "delay-echo"):
        assert t not in EFFECTS and t not in WIN["effects"] and t not in WIN.get("unmapped", {}), t
    assert "bench" not in EFFECTS["phaser-js"] and not EFFECTS["phaser-js"].get("quarantine")


def test_le_phaser_ecrit_en_brut_au_bon_index_et_jamais_un_slider_bipolaire_sous_exp():
    for p in EFFECTS["phaser-js"]["params"]:
        name, lo, hi = PHASER_SLIDERS[p["map"]["idx"]]
        assert p["name"] == name and p["map"]["mode"] == "raw"
        assert lo <= p["min"] and p["max"] <= hi
        if lo < 0:                                            # CLAUDE.md : minimum négatif = taper bipolaire
            assert not p.get("exp"), p["id"]
    # sans `defaults: compile`, un réglage que le preset ne nomme pas garde le défaut DU PLUGIN : le catalogue
    # doit afficher celui-là (vécu au banc du 2026-10-03 : -6 dB affiché, -3 dB joué)
    plugin_defaults = {"rate": 0.5, "low": 440, "high": 1600, "feedback": -3, "wet": 0}
    assert {p["id"]: p["default"] for p in EFFECTS["phaser-js"]["params"]} == plugin_defaults


def test_windows_et_aliases():
    assert WIN["unmapped"]["phaser-js"]["family"] == "reaper-jsfx"
    src = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    # une ligne : blockstatus et check-block-stall la lisent
    assert re.search(r'^\s*\["phaser-js"\]\s*=\s*\{[^}\n]*\},', src, re.M)


def test_le_plugin_est_epingle_par_son_fichier(tmp_path, monkeypatch):
    import hashlib, io, zipfile
    from provision import airwindows as A
    data = b"fake TapeDelay2"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(A.PINS["linux"]["member"], data)
    monkeypatch.setattr(A, "dest_dir", lambda platform=None: tmp_path)
    import pytest
    with pytest.raises(RuntimeError, match="changed upstream"):   # un binaire recompilé n'est pas posé
        A.install("linux", fetch=lambda url: buf.getvalue(), log=lambda *a: None)
    assert not list(tmp_path.iterdir())
    monkeypatch.setitem(A.PINS["linux"], "sha256", hashlib.sha256(data).hexdigest())
    assert A.install("linux", fetch=lambda url: buf.getvalue(), log=lambda *a: None).read_bytes() == data
