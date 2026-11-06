# SPDX-License-Identifier: GPL-3.0-or-later
"""Bloc Grit (Prisma, distorsion multibande — docs/blocks-doctrine.md addendum quinquies) : l'entrée
du catalogue est écrite depuis la SOURCE du plugin (processor.cpp), pas depuis une lecture
fxparams — ce test garde la forme cohérente (noms de paramètres = ceux que Prisma déclare, énumération
des 22 modules + Off, presets d'usine qui ne nomment que des paramètres existants)."""

import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
MODULES = ["Off", "Soft clip", "Hard clip", "Heavy", "Asym", "Rectify", "Fold", "Sine fold", "Zero cross", "Bit crush",
           "Sample divide", "DC", "Width", "Gain", "Pan", "Lowpass", "Highpass", "Peak", "Dry/wet", "Stereo rectify",
           "Stereo DC", "Ring mod", "Cabinet"]          # processor.h, toid(), MODULE_COUNT = 22


def _grit():
    c = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json")))
    e = next(e for e in c["effects"] if e["type"] == "grit")
    return c, e


def test_l_entree_suit_la_source_de_prisma():
    c, e = _grit()
    assert "lofi" in c["categories"] and e["category"] == "lofi" and e["plugin"] == "Prisma"
    ids = [p["id"] for p in e["params"]]
    assert len(ids) == len(set(ids)) == 25
    names = {p["name"] for p in e["params"]}
    # les noms que JUCE publie : "<Band> Module <k> Type|Value", "<Band> Gain", "<Band> Crossover", "Wet", "Quality"
    for band in ("Low", "Low Mid", "High Mid", "High"):
        assert {f"{band} Module 1 Type", f"{band} Module 1 Value", f"{band} Module 2 Type", f"{band} Module 2 Value", f"{band} Gain"} <= names
    assert {"Low Mid Crossover", "High Mid Crossover", "High Crossover", "Wet", "Quality"} <= names
    assert "Low Crossover" not in names                     # la bande 0 n'a pas de crossover (b >= 1)
    for p in e["params"]:
        if p.get("type") == "enum":
            # LU au fxparams (2026-09-14) : le VST3 JUCE publie « Module n Type » NORMALISÉ 0..1 (23 crans) —
            # un raw 10 (Sample divide) tombait sur « Cabinet » (clamp à 1.0). Mode norm, sans `values`.
            assert p["options"] == MODULES and "values" not in p and p["map"] == {"mode": "norm"}
        elif p.get("type") == "bool":
            assert p["id"] == "quality" and p["default"] is False      # zéro latence en live
        else:
            assert p["map"] == {"mode": "raw", "scale": 0.01} and 0 <= p["default"] <= 100
    assert "status" not in e                                 # VALIDÉ sur le rig le 2026-09-14 (fxparams, deux rebuilds, pdc 0)


def test_les_presets_d_usine_ne_nomment_que_des_parametres_existants():
    _, e = _grit()
    ids = {p["id"]: p for p in e["params"]}
    d = os.path.join(ROOT, "library", "block-presets", "grit")
    names = sorted(fn[:-5] for fn in os.listdir(d) if fn.endswith(".json"))
    assert names == ["broken", "grit", "megaphone", "telephone"]
    defaults = 0
    for fn in names:
        bp = json.load(open(os.path.join(d, fn + ".json")))
        assert bp["type"] == "grit" and bp["factory"] is True and set(bp["params"]) == set(ids)
        for k, v in bp["params"].items():
            p = ids[k]
            if p.get("type") == "enum":
                assert v in p["options"], (fn, k, v)
            elif p.get("type") == "bool":
                assert isinstance(v, bool)
            else:
                assert p["min"] <= v <= p["max"], (fn, k, v)
        defaults += bool(bp.get("default"))
    assert defaults == 1                                     # un seul défaut à l'ajout (Grit)


def test_la_recette_d_installation_epingle_un_commit_et_ne_fabrique_pas_la_version_payante():
    s = open(os.path.join(ROOT, "provision", "install-prisma.sh")).read()
    assert "VSTS_COMMIT=\"5062b597b01d11507ed60ac9a7e0e7ad6dcfd63f\"" in s
    assert "-DBANNERTYPE=0" in s and "BANNERTYPE=2" not in s
    assert "--target Prisma_VST3" in s
