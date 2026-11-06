# SPDX-License-Identifier: GPL-3.0-or-later
"""Bloc Kill Switch (JSFX maison golem_killswitch, 2026-09-22) : l'entrée du catalogue et le JSFX sont
deux déclarations du même objet — golem_rig résout chaque potard par le NOM du slider et l'écrit en
valeur BRUTE, la pédale EXP l'écrit en normalisé linéaire. Ce test garde les deux d'accord : noms,
bornes, défauts, énumérations (index = valeur brute), et aucun slider à minimum négatif (bipolaire pour
Reaper : l'EXP y écrirait n'importe quoi — CLAUDE.md)."""

import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
JSFX = os.path.join(ROOT, "reaper", "Effects", "golem_killswitch.jsfx")
SLIDER = re.compile(r"^slider(\d+):(?:(\w+)=)?([-\d.]+)<([-\d.]+),([-\d.]+),([-\d.]+)(?:\{([^}]*)\})?>(.*)$")


def _catalog():
    return json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"), encoding="utf-8"))


def _entry():
    return next(e for e in _catalog()["effects"] if e["type"] == "killswitch")


def _sliders():
    out = {}
    for line in open(JSFX, encoding="utf-8"):
        m = SLIDER.match(line.strip())
        if m:
            _, var, dflt, lo, hi, step, enum, name = m.groups()
            out[name.strip()] = {"var": var, "default": float(dflt), "min": float(lo), "max": float(hi),
                                 "options": enum.split(",") if enum else None}
    return out


def test_le_bloc_est_offert_a_la_guitare_la_basse_et_la_voix_seulement():
    c, e = _catalog(), _entry()
    assert e["roles"] == ["guitar", "bass", "voice"] and e["category"] == "modulation"
    assert e["engine"] == "plugin" and not e.get("quarantine")
    for role in ("bass", "voice"):                       # la catégorie doit être ouverte au rôle
        assert e["category"] in c["role_categories"][role]
    assert "killswitch" not in c["role_blocks"]["drums"]
    assert c["catalog_version"] >= 21


def test_chaque_potard_nomme_un_slider_du_jsfx_avec_les_memes_bornes():
    sl, e = _sliders(), _entry()
    for p in e["params"]:
        s = sl.get(p["name"])
        assert s, f"{p['id']} : aucun slider « {p['name']} » dans le JSFX"
        assert p["map"] == {"mode": "raw"}, p["id"]      # écrit en BRUT, aucun taper
        if p.get("type") == "enum":
            assert s["options"] == p["options"], p["id"]  # index de l'option = valeur brute du slider
            assert s["min"] == 0 and s["max"] == len(p["options"]) - 1
            assert p["options"].index(p["default"]) == s["default"], p["id"]
        else:
            assert (p["min"], p["max"], p["default"]) == (s["min"], s["max"], s["default"]), p["id"]


def test_aucun_slider_a_minimum_negatif():
    for name, s in _sliders().items():
        assert s["min"] >= 0, f"« {name} » est bipolaire pour Reaper (min {s['min']})"


def test_les_potards_a_pedale_et_les_dependances_sont_coherents():
    e = _entry()
    ids = {p["id"]: p for p in e["params"]}
    assert [p["id"] for p in e["params"] if p.get("exp")] == ["depth", "length", "rate"]
    assert e["params"][0]["id"] == "depth"               # la cible du modal Assign = Depth
    for p in e["params"]:
        assert not (p.get("exp") and p.get("type") in ("enum", "bool")), p["id"]
        for k, v in (p.get("depends") or {}).items():
            assert k in ids and v in ids[k]["options"], (p["id"], k, v)


def test_le_jsfx_respecte_les_pieges_du_depot():
    src = open(JSFX, encoding="utf-8").read()
    head = src[:src.index("\n@init")]
    # le code AVANT la première section @ n'est jamais exécuté : seules des déclarations y vivent
    for line in head.splitlines():
        t = line.strip()
        assert not t or t.startswith(("//", "desc:", "slider", "in_pin:", "out_pin:", "options:")), t
    # EEL2 insensible à la casse : chaque variable d'un slider est préfixée
    assert all(s["var"].startswith("ks_") for s in _sliders().values())
    assert "time_precise()" in src and "ext_noinit" in src


def test_golem_rig_sait_poser_le_fichier_meme_hors_cache_jsfx():
    lua = open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()
    alias = lua[lua.index("local ADD_ALIAS"):]
    assert re.search(r'^\s*killswitch\s*=\s*\{\s*"JS:golem/golem_killswitch"', alias, re.M)


def test_les_presets_d_usine_ne_nomment_que_des_parametres_existants():
    ids = {p["id"]: p for p in _entry()["params"]}
    d = os.path.join(ROOT, "library", "block-presets", "killswitch")
    defaults = {}
    for fn in sorted(os.listdir(d)):
        bp = json.load(open(os.path.join(d, fn), encoding="utf-8"))
        assert bp["type"] == "killswitch" and bp["factory"] is True and set(bp["params"]) == set(ids), fn
        assert bp["inst"] in ("guitar", "bass", "voice", "any"), fn
        for k, v in bp["params"].items():
            p = ids[k]
            if p.get("type") == "enum":
                assert v in p["options"], (fn, k, v)
            else:
                assert p["min"] <= v <= p["max"], (fn, k, v)
        if bp.get("default"):
            assert bp["inst"] not in defaults, fn
            defaults[bp["inst"]] = fn
    assert defaults == {"any": "standard.json"}
