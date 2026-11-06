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
TAPE_PARAMS = {0: "Time", 1: "Regen", 2: "Freq", 3: "Reso", 4: "Flutter", 5: "Dry/Wet"}


def test_les_blocs_calf_restent_et_les_nouveaux_existent():
    assert EFFECTS["phaser"]["plugin"] == "Calf Phaser" and EFFECTS["delay-tape"]["plugin"] == "Calf Vintage Delay"
    assert EFFECTS["phaser-js"]["plugin"] == "JS: guitar/phaser"
    assert EFFECTS["delay-tape-aw"]["plugin"] == "VST: TapeDelay2 (airwindows)"
    for t in ("phaser-js", "delay-tape-aw"):
        # validés le 2026-10-03 (banc de figeage Windows + écoute du mainteneur) : offerts à l'IA de golem.fm
        assert "bench" not in EFFECTS[t] and not EFFECTS[t].get("quarantine")


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


def test_le_tape_delay_ses_temps_et_son_dry_wet():
    e = EFFECTS["delay-tape-aw"]
    assert e.get("defaults") == "compile"                     # son défaut à lui = écho seul, sans le son direct
    by = {p["id"]: p for p in e["params"]}
    for p in e["params"]:
        assert TAPE_PARAMS[p["map"]["idx"]] == p["name"] and p["map"]["mode"] == "raw"
    t = by["time"]
    for opt, a in zip(t["options"], t["values"]):            # 2 s / (25·A⁴ + 1) à 44,1 kHz
        ms = float(opt.split()[0]) * (1000 if opt.endswith(" s") else 1)
        assert abs(2000 / (25 * a ** 4 + 1) - ms) / ms < 0.01, opt
    assert by["mix"]["default"] <= 50                         # au-dessus de 50 % le son direct baisse


def test_windows_et_aliases():
    assert WIN["unmapped"]["phaser-js"]["family"] == "reaper-jsfx"
    assert WIN["effects"]["delay-tape-aw"]["plugin"] == EFFECTS["delay-tape-aw"]["plugin"]
    src = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    for t in ("phaser-js", "delay-tape-aw"):                  # une ligne : blockstatus et check-block-stall la lisent
        assert re.search(r'^\s*\["%s"\]\s*=\s*\{[^}\n]*\},' % re.escape(t), src, re.M), t


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
