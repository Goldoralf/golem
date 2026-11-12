# SPDX-License-Identifier: GPL-3.0-or-later
"""Deux blocs Linux rendus PORTABLES par un JSFX maison (2026-10-22, docs/platforms.md §5) : « delay-tape » (Calf
Vintage Delay sous Linux) et « eq-para » (x42-eq). Sous Windows (et macOS pour delay-tape), la table de l'OS nomme
golem_tapedelay.jsfx / golem_eq.jsfx, qui reprennent les NOMS et les BORNES des paramètres du plugin Linux : les
presets ne changent pas, golem_rig résout chaque potard par le nom du slider et l'écrit en BRUT.

Avant : 16 objets d'usine perdaient leur EQ et 10 leur écho sous Windows. Ce test garde le catalogue, les tables et
les JSFX d'accord, et fait jouer un rappel Windows au vrai moteur (lupa, REAPER factice)."""
import copy
import json
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SLIDER = re.compile(r"^slider(\d+):(?:(\w+)=)?([-\d.]+)<([-\d.]+),([-\d.]+),([-\d.]+)(?:\{([^}]*)\})?>(.*)$")
BLOCKS = {"delay-tape": ("golem_tapedelay", "td_"), "eq-para": ("golem_eq", "eq_"),
          "reverb-shimmer": ("golem_shimmer", "sh_"), "grit": ("golem_grit", "gr_"),
          "wah": ("golem_wah", "wh_"), "wah-color": ("golem_colwah", "cw_"), "autowah": ("golem_autowah", "aw_"),
          "chorus": ("golem_chorus", "ch_"), "tremolo": ("golem_tremolo", "tr_"), "phaser": ("golem_phaser", "ph_"),
          "octaver": ("golem_octaver", "oc_"), "flanger": ("golem_flanger", "fl_"), "rotary": ("golem_rotary", "ro_"),
          "limiter": ("golem_limiter", "li_"), "vibrato": ("golem_vibrato", "vb_"), "eq-graphic": ("golem_geq", "ge_"),
          "delay-echo": ("golem_echocat", "ec_")}
EFFECTS = {e["type"]: e for e in json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"),
                                                 encoding="utf-8"))["effects"]}


def _table(name):
    return json.load(open(os.path.join(ROOT, "library", "catalog", f"effects-{name}.json"), encoding="utf-8"))["effects"]


def _src(stem):
    return open(os.path.join(ROOT, "reaper", "Effects", f"{stem}.jsfx"), encoding="utf-8").read()


def _sliders(stem):
    out = []
    for line in _src(stem).splitlines():
        m = SLIDER.match(line.strip())
        if m:
            idx, var, dflt, lo, hi, _step, enum, name = m.groups()
            out.append({"idx": int(idx), "var": var, "default": float(dflt), "min": float(lo), "max": float(hi),
                        "options": enum.split(",") if enum else None, "name": name.strip()})
    return out


@pytest.mark.parametrize("btype", sorted(BLOCKS))
def test_chaque_potard_du_catalogue_nomme_un_slider_aux_memes_unites(btype):
    stem, _ = BLOCKS[btype]
    sl = {s["name"]: s for s in _sliders(stem)}
    for p in EFFECTS[btype]["params"]:
        s = sl.get(p["name"])
        assert s, f"{btype}.{p['id']} : aucun slider « {p['name']} » dans {stem}.jsfx"
        if p.get("type") == "enum" and p["map"]["mode"] == "norm":
            # un choix écrit en NORMALISÉ (types de modules de Prisma) : index / (n - 1) sur un slider à liste 0..n-1
            assert s["options"] == p["options"] and (s["min"], s["max"]) == (0, len(p["options"]) - 1), p["id"]
            continue
        assert p["map"]["mode"] == "raw", p["id"]                     # écrit en brut : le slider porte l'unité native
        # une table d'OS qui RENOMME le paramètre lui rend une correspondance sans échelle (golem_rig.lua) : le JSFX du
        # limiteur prend des ms, l'x42 de Linux/macOS des secondes (catalogue v34)
        scale = 1 if p["id"] in (_table("windows")[btype].get("params") or {}) else p["map"].get("scale", 1)
        if p.get("type") == "enum":
            vals = p.get("values") or list(range(len(p["options"])))
            assert s["min"] <= min(vals) and max(vals) <= s["max"], p["id"]
            if s["options"]:
                assert s["options"] == p["options"], p["id"]           # index de l'option = valeur brute
        elif p.get("type") == "bool":
            assert (s["min"], s["max"]) == (0, 1), p["id"]
        else:
            assert s["min"] <= p["min"] * scale and p["max"] * scale <= s["max"], (p["id"], s, p)


@pytest.mark.parametrize("btype", sorted(BLOCKS))
def test_le_jsfx_respecte_les_pieges_du_depot(btype):
    stem, prefix = BLOCKS[btype]
    src = _src(stem)
    head = src[:src.index("\n@init")]
    for line in head.splitlines():                                     # rien ne s'exécute avant @init
        t = line.strip()
        assert not t or t.startswith(("//", "desc:", "slider", "in_pin:", "out_pin:", "options:")), t
    assert "SPDX-License-Identifier: MIT" in head
    for s in _sliders(stem):
        assert s["var"].startswith(prefix), s                          # EEL2 insensible à la casse : tout est préfixé
        # minimum négatif = bipolaire pour REAPER ; toléré seulement SYMÉTRIQUE (la même droite que la linéaire)
        assert s["min"] >= 0 or s["min"] == -s["max"], s
    idx = [s["idx"] for s in _sliders(stem)]
    assert idx == list(range(1, len(idx) + 1))                         # on AJOUTE, on n'insère jamais
    # EEL2 ne lit pas la notation exponentielle : « 1e-6 » est une erreur de compilation que REAPER n'empêche pas —
    # le JSFX se pose quand même, en erreur, et le son passe À SEC (banc du 2026-10-22 : les trois wahs rendaient
    # le bruit blanc tel quel). Un nombre s'écrit en décimal.
    code = "\n".join(l.split("//", 1)[0] for l in src.splitlines())
    assert not re.search(r"\b\d+(\.\d+)?[eE][-+]?\d+\b", code), stem
    assert re.search(r"^\|? *`%s\.jsfx`" % stem, open(os.path.join(ROOT, "docs", "licence.md"), encoding="utf-8").read(), re.M)


def test_les_tables_nomment_le_jsfx_par_son_chemin():
    win, mac = _table("windows"), _table("macos")
    for btype, (stem, _) in BLOCKS.items():
        assert {k: v for k, v in win[btype].items() if k != "params"} == {"plugin": f"JS:golem/{stem}",
                                                                          "note": win[btype]["note"]}, btype
        if btype not in ("eq-para", "limiter"):                    # macOS résout l'x42-eq / x42-dpl que l'on installe soi-même
            assert mac[btype] == {"plugin": f"JS:golem/{stem}", "note": mac[btype]["note"]}, btype


def test_le_bridge_juge_un_jsfx_strict_a_son_fichier(monkeypatch):
    """Le nom affiché d'un JSFX (« JS: GoleM Tape Delay … ») ne contient pas son chemin : sans ce garde, le bridge
    déclarait « plugin not installed » un bloc que golem_rig pose très bien."""
    import sys
    from bridge import blockstatus as B
    monkeypatch.setattr(sys, "platform", "win32")
    inv = {"names": {"golem tape delay -- the delay-tape block on windows and macos"},
           "qualified_names": {"js: golem tape delay -- the delay-tape block on windows and macos"},
           "idents": {"golem/golem_tapedelay.jsfx"}}
    assert B._in_inventory("JS:golem/golem_tapedelay", inv, strict=True)
    assert not B._in_inventory("JS:golem/golem_eq", inv, strict=True)


# ── le vrai moteur, sous Windows ─────────────────────────────────────────────────────────────────────────────
def _patch():
    """Le patch de banc du moteur (tests/test_rig_lua.py), avec les deux blocs en fin de chaîne."""
    from tests.test_rig_lua import PATCH
    p = copy.deepcopy(PATCH)
    p["lanes"][0]["chain"]["post"] += [
        {"id": "peq", "type": "eq-para", "params": {"lowcut_on": True, "lowcut": 110, "f2": 1500, "g2": 3, "g1": -2.5,
                                                    "treble": -1}},
        {"id": "tape", "type": "delay-tape", "params": {"time": "8th", "feedback": 35, "mix": 22, "medium": "Old Tape"}},
        {"id": "shim", "type": "reverb-shimmer", "params": {"mix": 30, "decay": 6, "shimmer": 40, "pitch": 5, "hicut": 6000}},
        {"id": "grit", "type": "grit", "params": {"hm_m1": "Sample divide", "hm_v1": 24, "hm_m2": "Gain", "hm_v2": 53,
                                                 "x2": 50, "wet": 100}},
        {"id": "cry", "type": "wah", "params": {"wah": 0.7, "volume": -3}},
        {"id": "mwah", "type": "wah-color", "params": {"model": "Vox V847", "wah": 0.4, "freq": 120, "mix": 80, "mode": "auto"}},
        {"id": "awah", "type": "autowah", "params": {"wah": 0.6}},
        {"id": "cho", "type": "chorus", "params": {"rate": 0.6, "depth": 4, "mix": 0.4}},
        {"id": "trem", "type": "tremolo", "params": {"rate": 5, "depth": 0.6, "wave": "Triangle"}},
        {"id": "phs", "type": "phaser", "params": {"rate": 0.4, "depth": 4000, "stages": "8", "feedback": 0.3}},
        {"id": "oct", "type": "octaver", "params": {"direct": 1, "octave1": 0.6, "octave2": 0}},
        {"id": "flg", "type": "flanger", "params": {"rate": 0.3, "depth": 2, "feedback": 0.6}},
        {"id": "rot", "type": "rotary", "params": {"speed": "fast", "mic": 70, "spacing": 50, "depth": 60}},
        {"id": "lim", "type": "limiter", "params": {"threshold": -6, "release": 80}},
        {"id": "vib", "type": "vibrato", "params": {"depth": 0.4, "speed": 5}},
        {"id": "geq", "type": "eq-graphic", "params": {"g1": -3, "g6": 4, "g11": -12}},
        {"id": "echo", "type": "delay-echo", "params": {"time": 100, "repeats": 40, "mix": 50, "head1": True, "head3": True}}]
    return p


def test_un_rappel_windows_pose_les_deux_jsfx_et_ecrit_les_valeurs_brutes(tmp_path):
    pytest.importorskip("lupa")
    from tests.test_rig_lua import Lab
    lab = Lab(tmp_path, os_name="Win64")
    for btype, (stem, _) in BLOCKS.items():                            # le REAPER factice connaît leurs vrais sliders
        specs = lab.L.table_from([lab.L.table_from({"name": s["name"], "min": s["min"], "max": s["max"],
                                                    "def": s["default"]}) for s in _sliders(stem)])
        lab.F.specs[f"JS:golem/{stem}"] = specs
    lab.compile(_patch())
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    # les FX vivants du REAPER factice (le snapshot ne garde pas les paramètres)
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    assert {"golem:peq", "golem:tape", "golem:shim", "golem:grit", "golem:cry", "golem:mwah", "golem:awah",
            "golem:cho", "golem:trem", "golem:phs", "golem:oct", "golem:flg", "golem:rot",
            "golem:lim", "golem:vib", "golem:geq", "golem:echo"} <= set(fx), lab.log()
    assert fx["golem:peq"].name == "JS:golem/golem_eq" and fx["golem:tape"].name == "JS:golem/golem_tapedelay"

    def val(fid, name):
        return next(p.val for p in fx[fid].params.values() if p.name == name)
    assert (val("golem:peq", "Highpass"), val("golem:peq", "Highpass Frequency")) == (1, 110), lab.log()
    assert (val("golem:peq", "Frequency 2"), val("golem:peq", "Gain 2"), val("golem:peq", "Gain 1")) == (1500, 3, -2.5)
    assert val("golem:peq", "Highshelf Gain") == -1
    assert val("golem:tape", "Time L") == 2                            # « 8th » = 2 ticks (2 doubles croches chez Calf)
    assert val("golem:tape", "Feedback") == pytest.approx(0.35) and val("golem:tape", "Wet") == pytest.approx(0.22)
    assert val("golem:tape", "Medium") == 2
    assert (val("golem:shim", "DRYWET"), val("golem:shim", "T60M"), val("golem:shim", "SHIFT")) ==         (pytest.approx(0.30), 6, 5)
    assert val("golem:shim", "PSDRYWET") == pytest.approx(0.40) and val("golem:shim", "F2") == 6000
    # types de Prisma : choix écrits en NORMALISÉ (index / 22) sur un slider à liste 0..22 -> index brut
    assert val("golem:grit", "High Mid Module 1 Type") == pytest.approx(10)          # Sample divide
    assert val("golem:grit", "High Mid Module 2 Type") == pytest.approx(13)          # Gain
    assert val("golem:grit", "High Mid Module 1 Value") == pytest.approx(0.24)
    assert val("golem:grit", "High Mid Crossover") == pytest.approx(0.5) and val("golem:grit", "Wet") == pytest.approx(1)
    # la famille wah (2026-10-22) : valeurs brutes, un choix par son index dans la liste du slider
    assert (val("golem:cry", "Wah"), val("golem:cry", "Volume")) == (pytest.approx(0.7), -3)
    assert (val("golem:mwah", "MODEL"), val("golem:mwah", "MODE")) == (6, 1)                  # Vox V847, auto
    assert (val("golem:mwah", "WAH"), val("golem:mwah", "FREQ"), val("golem:mwah", "WET_DRY")) == (pytest.approx(0.4), 120, 80)
    assert val("golem:awah", "Wah") == pytest.approx(0.6)
    # chorus / tremolo / phaser (Calf) : valeurs brutes, FX_INIT pose « Dry Amount » = 1 sur le chorus (insert serie)
    assert (val("golem:cho", "Mod Rate"), val("golem:cho", "Mod Depth"), val("golem:cho", "Amount")) == (pytest.approx(0.6), 4, pytest.approx(0.4))
    assert val("golem:cho", "Dry Amount") == 1
    assert (val("golem:trem", "Frequency"), val("golem:trem", "Modulation"), val("golem:trem", "Mode")) == (5, pytest.approx(0.6), 1)
    assert (val("golem:phs", "Mod rate"), val("golem:phs", "Mod depth"), val("golem:phs", "# Stages"), val("golem:phs", "Feedback")) == (pytest.approx(0.4), 4000, 8, pytest.approx(0.3))
    # octaver / flanger / rotary : valeurs brutes ; les % du rotary s'ecrivent 0..1 (scale 0.01)
    assert (val("golem:oct", "DIRECT"), val("golem:oct", "OCTAVE1"), val("golem:oct", "OCTAVE2")) == (1, pytest.approx(0.6), 0)
    assert (val("golem:flg", "Mod rate"), val("golem:flg", "Mod depth"), val("golem:flg", "Feedback")) == (pytest.approx(0.3), 2, pytest.approx(0.6))
    assert (val("golem:rot", "Speed Mode"), val("golem:rot", "Mic Distance"), val("golem:rot", "Tap Spacing"), val("golem:rot", "FM Depth")) == (2, pytest.approx(0.7), pytest.approx(0.5), pytest.approx(0.6))
    assert (val("golem:lim", "Threshold"), val("golem:lim", "Release Time")) == (-6, 80)
    assert (val("golem:vib", "Depth"), val("golem:vib", "Speed")) == (pytest.approx(0.4), 5)
    assert (val("golem:geq", "G1"), val("golem:geq", "G6"), val("golem:geq", "G11")) == (-3, 4, -12)
    # delay-echo : en quarantaine sous Linux (GxEchoCat), joué ici par golem_echocat — les % s'écrivent 0..1
    assert (val("golem:echo", "BPM"), val("golem:echo", "Sustain"), val("golem:echo", "Swell")) == (100, pytest.approx(0.4), pytest.approx(0.5))
    assert (val("golem:echo", "Head 1"), val("golem:echo", "Head 3")) == (1, 1)
    seen = json.loads((lab.root / "presets/.rig-plugins.json").read_text(encoding="utf-8"))["types"]
    assert all(seen[t]["ok"] is True for t in BLOCKS), seen


def test_aucun_jsfx_de_golem_n_a_deux_noms_qui_ne_different_que_par_la_casse():
    """EEL2 ne distingue pas les majuscules : `sh_N = 8` puis `sh_n = 0.35` arrêtait toutes les boucles du Shimmer au
    deuxième échantillon (relecture du 2026-10-22). Commentaires, chaînes et lignes `desc:` sont ignorés."""
    import glob
    bad = {}
    for f in glob.glob(os.path.join(ROOT, "reaper", "Effects", "*.jsfx")):
        src = open(f, encoding="utf-8", errors="replace").read()
        src = re.sub(r"//[^\n]*|/\*.*?\*/|\"[^\"\n]*\"", " ", src, flags=re.S)
        src = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("desc:", "slider", "in_pin", "out_pin", "options:")))
        seen = {}
        for w in set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_.]*\b", src)):
            seen.setdefault(w.lower(), set()).add(w)
        clash = {k: sorted(v) for k, v in seen.items() if len(v) > 1}
        if clash and os.path.basename(f).startswith("golem_"):
            bad[os.path.basename(f)] = clash
    assert not bad, bad


def test_sous_linux_le_limiteur_x42_recoit_des_secondes(tmp_path):
    """Le catalogue v34 : le potard Release reste en ms, l'x42-dpl attend des SECONDES (ports 0,001..1 s) — mesuré par
    tools/check-engine-parity.py le 2026-11-12 : 50 ms partaient en 50 s. Windows garde les ms (test ci-dessus)."""
    pytest.importorskip("lupa")
    from tests.test_rig_lua import PATCH, Lab
    lab = Lab(tmp_path)
    lab.F.specs["x42-dpl - Digital Peak Limiter Mono"] = lab.L.table_from([
        lab.L.table_from({"name": "Threshold", "min": -10, "max": 0, "def": 0}),
        lab.L.table_from({"name": "Release Time", "min": 0.001, "max": 1, "def": 0.01})])
    p = copy.deepcopy(PATCH)
    p["lanes"][0]["chain"]["post"] += [{"id": "lim", "type": "limiter", "params": {"threshold": -6, "release": 80}}]
    lab.compile(p)
    lab.run(action="rig_recall", preset="ci-engine", scene="A")
    fx = {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}
    vals = {q.name: q.val for q in fx["golem:lim"].params.values()}
    assert vals["Threshold"] == -6 and vals["Release Time"] == pytest.approx(0.08), lab.log()
