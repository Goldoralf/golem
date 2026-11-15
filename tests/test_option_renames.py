# SPDX-License-Identifier: GPL-3.0-or-later
"""Les étiquettes d'un choix renommées au catalogue (bridge/option_renames.py, catalogue 31, 2026-10-22).

Le Tape Delay disait « 1/4 » pour un tick de Calf — une DOUBLE CROCHE. Les étiquettes disent désormais ce qui joue
(« 16th », « 8th », « dotted 8th », « quarter »…) et les documents qui portent les anciennes sont réécrits au
chargement : le son ne change pas, seule l'étiquette devient vraie. Sans cette migration, golem_rig (index_of) ne
trouverait plus l'étiquette et jouerait l'option 0 à tous les presets existants."""
import copy
import json
import os

from bridge import option_renames as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = json.load(open(os.path.join(ROOT, "library", "catalog", "effects.json"), encoding="utf-8"))


def _param(btype, pid):
    e = next(e for e in CAT["effects"] if e["type"] == btype)
    return next(p for p in e["params"] if p["id"] == pid)


def test_une_ancienne_etiquette_n_est_jamais_une_option_et_garde_sa_valeur():
    """La garantie qui rend la réécriture pure : aucune ambiguïté entre un document ancien et un nouveau."""
    for e in CAT["effects"]:
        for p in e["params"]:
            for old, new in (p.get("renamed") or {}).items():
                assert old not in p["options"], (e["type"], p["id"], old)
                assert new in p["options"], (e["type"], p["id"], new)
    # le seul bloc qui avait renommé ses choix (delay-tape, catalogue 31) est retiré en v48 : ses étiquettes, anciennes
    # et nouvelles, se traduisent toujours en seizièmes au moment de la retraite
    assert R._TAPE_16THS["1/4"] == R._TAPE_16THS["16th"] == 1 and R._TAPE_16THS["1 bar"] == R._TAPE_16THS["quarter"] == 4


def test_seuls_les_blocs_du_type_sont_reecrits_y_compris_leurs_etats_et_scenes():
    # catalogue v48 : un delay-tape d'avant le catalogue 31 devient le Delay de golem-fx (modèle Tape) ; ses scènes et
    # états ne gardent que ce qu'ils changent ; le Delay voisin n'est pas touché
    doc = {"lanes": [{"chain": {"post": [{"id": "tape", "type": "delay-tape", "params": {"time": "1/4", "time_r": "1 bar"}},
                                         {"id": "dly", "type": "delay", "params": {"time": "1/4"}}]},
                      "states": [{"params": {"tape": {"time": "3/4"}, "dly": {"time": "1/4"}}}]}],
           "scenes": [{"params": {"tape": {"mix": 20}, "dly": {"time": "1/8"}}}]}
    assert R.apply(doc) == 1
    post = doc["lanes"][0]["chain"]["post"]
    assert post[0] == {"id": "tape", "type": "delay", "params": {"model": "Tape", "time": "1/16", "stereo": "Ping-Pong"}}
    assert post[1]["params"] == {"time": "1/4"}                                      # le Delay garde son « 1/4 »
    assert doc["lanes"][0]["states"][0]["params"] == {"tape": {"time": "1/8•"}, "dly": {"time": "1/4"}}
    assert doc["scenes"][0]["params"]["tape"] == {"mix": 20.0}
    again = copy.deepcopy(doc)
    assert R.apply(again) == 0 and again == doc                                      # idempotent


def test_un_preset_de_bloc_sans_id_et_les_chargements_du_bridge():
    bp = {"type": "delay-tape", "params": {"time": "1/2"}}
    assert R.apply(bp) == 1 and bp == {"type": "delay", "params": {"model": "Tape", "time": "1/8"}}
    src = {f: open(os.path.join(ROOT, "bridge", f), encoding="utf-8").read()
           for f in ("store.py", "patches.py", "routes_content.py", "app.py")}
    assert "option_renames.apply(p)" in src["store.py"]                             # presets (load ET save)
    assert "option_renames.apply(doc)" in src["patches.py"] and "option_renames.apply(d)" in src["patches.py"]   # get ET liste
    assert src["routes_content.py"].count("option_renames.apply(bp)") == 2            # liste et défauts des presets de bloc
    assert "option_renames.apply(preset)" in src["app.py"] and "option_renames.apply(doc)" in src["app.py"]


def test_plus_aucun_objet_livre_ne_porte_une_ancienne_etiquette():
    import glob
    for f in glob.glob(os.path.join(ROOT, "library", "factory", "*", "*.json")) + \
            glob.glob(os.path.join(ROOT, "library", "block-presets", "*", "*.json")):
        doc = json.load(open(f, encoding="utf-8"))
        assert R.apply(doc) == 0, os.path.relpath(f, ROOT)


# ── TYPE RETIRÉ (catalogue v40) : le flanger Calf devient le seul flanger, valeurs converties ──
def test_le_flanger_calf_devient_le_flanger_valeurs_converties():
    doc = {"lanes": [{"chain": {"pre": [{"id": "fl", "type": "flanger",
                                         "params": {"rate": 0.15, "depth": 5.5, "feedback": 0.85}}]}}],
           "scenes": [{"id": "B", "params": {"fl": {"feedback": 0.25}}}]}
    assert R.apply(doc) >= 1
    b = doc["lanes"][0]["chain"]["pre"][0]
    assert b["type"] == "flanger-js"
    assert b["params"] == {"rate": 0.15, "length": 6.0, "feedback": -1.4, "wet": -6.0, "dry": 0.0}
    assert doc["scenes"][0]["params"]["fl"]["feedback"] == -12.0
    before = json.dumps(doc)
    R.apply(doc)
    assert json.dumps(doc) == before                    # idempotent


def test_le_flanger_retire_n_est_plus_au_catalogue_et_le_flanger_reste():
    types = {e["type"] for e in json.load(open(R.C.EFFECTS))["effects"]}
    assert "flanger" not in types and "flanger-js" in types
    assert set(R.RETIRED).isdisjoint(types)


def test_un_feedback_negatif_garde_son_signe_par_la_polarite():
    doc = [{"id": "f", "type": "flanger", "params": {"rate": 0.3, "depth": 2, "feedback": -0.6}}]
    R.apply(doc)
    assert doc[0]["params"]["fb_polarity"] == "Inverted" and doc[0]["params"]["feedback"] == -4.4


def test_chaque_bloc_retire_va_vers_une_pedale_golem_fx_qui_connait_chaque_reglage_traduit():
    # catalogue v48 (2026-11-15, golem-fx docs/legacy-blocks.md) : chaque ancien type quitte le catalogue ; sa traduction
    # n'écrit que des réglages du bloc d'arrivée (catalogue ou descripteur golem-fx), dans leurs bornes ou leurs choix
    types = {e["type"]: e for e in CAT["effects"]}
    plugins = json.load(open(os.path.join(ROOT, "library", "catalog", "golem-fx-plugins.json"), encoding="utf-8"))["plugins"]
    desc = {b: p["descriptor"] for p in plugins.values() for b in p["descriptor"].get("blocks") or []}
    full = {"chorus-js": {"length": 20, "voices": 3, "rate": 0.8, "wet": -6, "dry": 0},
            "phaser": {"rate": 0.4, "depth": 4000, "stages": "8", "feedback": 0.3},
            "delay-tape": {"time": "5 16ths", "time_r": "dotted 8th", "tempo": 100, "feedback": 40, "mix": 30, "medium": "Old Tape"},
            "delay-tape-aw": {"time": "1.5 s", "regen": 35, "tone": 50, "reso": 0, "flutter": 15, "mix": 30},
            "delay-echo": {"time": 100, "repeats": 40, "mix": 50, "input": 25, "head1": True, "head2": True, "head3": False},
            "eq-para": {"lowcut_on": True, "lowcut": 110, "bass": 2, "f1": 160, "g1": -3, "f2": 1500, "g2": 3, "f3": 4000, "g3": 1, "treble": -1},
            "surge-spring": {"size": 0.5, "decay": 0.55, "refl": 0.5, "damp": 0.45, "mix": 0.35},
            "boost": {"drive": 45, "level": 65, "treble": 1, "bass": -1, "mid": 2},
            "pitch-spectral": {"shift": -5, "formant_comp": True},
            "rezfilter": {"freq": 0.5, "res": 0.6, "env": 0.4, "attack": 0.35, "release": 0.5, "lfodepth": 0.3, "lforate": 0.3},
            "freeze": {"freeze": True, "mix": 80, "decay": 0.6}}
    assert set(full) == set(R.RETIRED) - {"flanger"}
    for old, pm in list(full.items()) + [("boost", {"drive": 10, "level": 70})]:
        assert old not in types, old
        to, conv = R._retire_type(old, pm)
        out = conv(dict(pm))
        known = {p["id"]: p for p in types[to]["params"]}
        gfx = desc[to]["params"]
        for k, v in out.items():
            d = known.get(k)
            if d is None:
                assert k in gfx, (old, to, k)
                g = gfx[k]
                if g.get("options"):
                    assert v in g["options"], (old, k, v)
                elif g["kind"] == "float":
                    assert g["min"] <= v <= g["max"], (old, k, v)
            elif d.get("type") == "enum":
                assert v in d["options"] or v in (gfx.get(k) or {}).get("options", []), (old, k, v)
            elif d.get("type") != "bool" and d.get("min") is not None:
                assert d["min"] <= v <= d["max"], (old, k, v)
    assert R._retire_type("boost", {"drive": 10})[0] == "shem" and R._retire_type("boost", {"drive": 40})[0] == "emet"
