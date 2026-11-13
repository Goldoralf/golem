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
    n = 0
    for e in CAT["effects"]:
        for p in e["params"]:
            for old, new in (p.get("renamed") or {}).items():
                n += 1
                assert old not in p["options"], (e["type"], p["id"], old)
                assert new in p["options"], (e["type"], p["id"], new)
    assert n >= 8
    t = _param("delay-tape", "time")
    old_values = {"1/4": 1, "1/2": 2, "3/4": 3, "1 bar": 4}                # catalogue 30 : options → valeurs brutes
    for old, ticks in old_values.items():
        assert t["values"][t["options"].index(t["renamed"][old])] == ticks, old   # le SON ne change pas
    # les défauts sont ceux de Calf (3 et 5 ticks) : ce que joue un preset qui ne nomme pas le réglage
    assert t["values"][t["options"].index(t["default"])] == 3
    r = _param("delay-tape", "time_r")
    assert r["values"][r["options"].index(r["default"])] == 5


def test_seuls_les_blocs_du_type_sont_reecrits_y_compris_leurs_etats_et_scenes():
    doc = {"lanes": [{"chain": {"post": [{"id": "tape", "type": "delay-tape", "params": {"time": "1/4", "time_r": "1 bar"}},
                                         {"id": "dly", "type": "delay", "params": {"time": "1/4"}}]},
                      "states": [{"params": {"tape": {"time": "3/4"}, "dly": {"time": "1/4"}}}]}],
           "scenes": [{"params": {"tape": {"time_r": "1/2"}, "dly": {"time": "1/8"}}}]}
    assert R.apply(doc) == 4
    post = doc["lanes"][0]["chain"]["post"]
    assert post[0]["params"] == {"time": "16th", "time_r": "quarter"}
    assert post[1]["params"] == {"time": "1/4"}                                      # le Delay garde son « 1/4 »
    assert doc["lanes"][0]["states"][0]["params"] == {"tape": {"time": "dotted 8th"}, "dly": {"time": "1/4"}}
    assert doc["scenes"][0]["params"]["tape"] == {"time_r": "8th"}
    again = copy.deepcopy(doc)
    assert R.apply(again) == 0 and again == doc                                      # idempotent


def test_un_preset_de_bloc_sans_id_et_les_chargements_du_bridge():
    bp = {"type": "delay-tape", "params": {"time": "1/2"}}
    assert R.apply(bp) == 1 and bp["params"]["time"] == "8th"
    src = {f: open(os.path.join(ROOT, "bridge", f), encoding="utf-8").read()
           for f in ("store.py", "patches.py", "routes_content.py", "app.py")}
    assert "option_renames.apply(p)" in src["store.py"]                             # presets (load ET save)
    assert "option_renames.apply(doc)" in src["patches.py"]
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
