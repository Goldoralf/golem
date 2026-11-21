# SPDX-License-Identifier: GPL-3.0-or-later
"""Bloc Grit (distorsion multibande) joué par gfx-grit (catalogue v51, docs/golem-fx-migration.md §4).

Le bloc garde son type ; Prisma et golem_grit.jsfx ne le jouent plus. Les réglages dont l'UNITÉ a changé ont changé
d'id (`was` au catalogue) : `lo_v1` (loi de Prisma) -> `lo_amt1` (loi de gfx-grit, selon le type de l'emplacement),
`lo_gain` (%) -> `lo_lvl` (dB). bridge/option_renames.py convertit au chargement un document qui porte encore les
anciens ids. Ce test garde le catalogue, la table du moteur, le descripteur de golem-fx, les presets et la conversion
d'accord."""
import copy
import json
import os

import pytest

from bridge import golem_fx
from bridge import option_renames as R

ROOT = os.path.join(os.path.dirname(__file__), "..")
BANDS = {"lo": "Low", "lm": "Low Mid", "hm": "High Mid", "hi": "High"}


def _json(*path):
    return json.load(open(os.path.join(ROOT, *path), encoding="utf-8"))


def _grit():
    c = _json("library", "catalog", "effects.json")
    return c, next(e for e in c["effects"] if e["type"] == "grit")


def test_l_entree_est_celle_d_un_bloc_golem_fx():
    c, e = _grit()
    assert c["catalog_version"] >= 51 and "was" in c["_units_comment"]
    assert e["category"] == "lofi" and e["plugin"] == "VST3: GoleM FX Grit (GoleM)"
    assert e["quarantine"].startswith("golem-fx only")
    spec = _json("library", "catalog", "effects-golem-engine.json")["effects"]["grit"]
    assert spec["golem_fx"] is True and bytes.fromhex(spec["vst3"]).decode() == "GoleMFxGrit00001"
    for osname in ("windows", "macos"):
        assert "unsupported" in _json("library", "catalog", f"effects-{osname}.json")["effects"]["grit"]
    assert not os.path.exists(os.path.join(ROOT, "reaper", "Effects", "golem_grit.jsfx"))
    assert "Prisma" not in open(os.path.join(ROOT, "reaper", "Scripts", "golem_rig.lua"), encoding="utf-8").read()


def test_chaque_reglage_du_catalogue_est_un_reglage_du_plugin_aux_memes_bornes():
    _, e = _grit()
    desc, _ = golem_fx.descriptor_for("grit")
    by_name = {p["name"]: p for p in desc["params"].values()}
    for p in e["params"]:
        d = by_name[p["name"]]
        if p.get("type") == "bool":
            assert d["kind"] == "bool" and p["default"] == bool(d["default"])
        else:
            assert (p["min"], p["max"], p["default"]) == (d["min"], d["max"], d["default"]), p["id"]
    front = [p["id"] for p in e["params"][:5]]
    assert front == desc["front"] == ["wet", "quality", "drive", "focus", "level"]


def test_un_ancien_id_n_est_jamais_un_nouveau():
    """La garantie qui rend la conversion pure : aucun id de la feuille (catalogue + descripteur) n'est un ancien id."""
    _, e = _grit()
    was = {p["was"]: p["id"] for p in e["params"] if p.get("was")}
    assert was == {**{f"{b}_v{i}": f"{b}_amt{i}" for b in BANDS for i in (1, 2)}, **{f"{b}_gain": f"{b}_lvl" for b in BANDS}}
    params, sheet = golem_fx.merged("grit", e["params"])
    ids = {d["id"] for d in params}
    assert sheet and not (set(was) & ids) and set(was.values()) <= ids
    assert not any(i.startswith("gfx_") for i in ids)                 # aucun id du descripteur ne heurte le catalogue
    # les types des modules gardent leur id et leurs 23 premiers choix ; Tube et Fuzz s'ajoutent à la fin
    m = next(d for d in params if d["id"] == "hm_m1")
    assert m["options"][:3] == ["Off", "Soft clip", "Hard clip"] and m["options"][-2:] == ["Tube", "Fuzz"] and len(m["options"]) == 25


def test_les_formules_sont_celles_de_golem_fx():
    # gfx-grit/README §3.3 : les quatre presets du catalogue convertis
    assert R.grit_amount("Gain", 53) == pytest.approx(65, abs=0.5)
    assert R.grit_amount("Hard clip", 40) == pytest.approx(42, abs=0.5)
    assert R.grit_amount("Soft clip", 25) == pytest.approx(33, abs=0.5)
    assert R.grit_amount("Fold", 35) == pytest.approx(41, abs=0.5)
    assert 16 - 15 * R.grit_amount("Bit crush", 20) / 100 == pytest.approx(7.6, abs=0.05)
    assert 16 - 15 * R.grit_amount("Bit crush", 45) / 100 == pytest.approx(6.1, abs=0.05)
    assert R.grit_amount("Heavy", 55) == 55 and R.grit_amount("Sample divide", 24) == 24 and R.grit_amount("Off", 0) == 0
    assert R.grit_amount("DC", 50) == 50 and R.grit_amount("Stereo DC", 100) == 100 and R.grit_amount("Gain", 0) == 0
    assert R.grit_amount("Zero cross", 50) == pytest.approx(100 * (-25 + 66) / 60, abs=0.01)
    assert (R.grit_level(50), R.grit_level(0), R.grit_level(100)) == (0, -60, 12)
    assert R.grit_level(5) == pytest.approx(-40, abs=0.01) and R.grit_level(15) == pytest.approx(-20.9, abs=0.05)
    for kind in ("Soft clip", "Fold", "Sine fold", "Zero cross", "Bit crush", "Gain", "DC", "Stereo DC", "Peak"):
        vals = [R.grit_amount(kind, v) for v in range(101)]
        assert vals == sorted(vals) and 0 <= vals[0] and vals[-1] <= 100, kind      # monotone, bornée


def test_un_document_ancien_est_converti_une_fois_avec_ses_scenes():
    doc = {"lanes": [{"chain": {"post": [
        {"id": "g", "type": "grit", "params": {"hm_m1": "Sample divide", "hm_v1": 24, "hm_m2": "Gain", "hm_v2": 53,
                                               "lm_m1": "Hard clip", "lm_v1": 40, "lo_gain": 5, "hm_gain": 50, "x2": 63, "wet": 100}},
        {"id": "m", "type": "morph", "params": {"lo_gain": 5}}]},
        "states": [{"params": {"g": {"hm_v2": 70, "hi_gain": 15}}}]}],
        "scenes": [{"params": {"g": {"lm_m1": "Fold"}, "m": {"lo_gain": 7}}},     # change le TYPE : la quantité du bloc, dans la loi de Fold
                   {"params": {"g": {"wet": 50}}}]}
    assert R.apply(doc) > 0
    g = doc["lanes"][0]["chain"]["post"][0]["params"]
    assert g == {"hm_m1": "Sample divide", "hm_amt1": 24.0, "hm_m2": "Gain", "hm_amt2": R.grit_amount("Gain", 53),
                 "lm_m1": "Hard clip", "lm_amt1": R.grit_amount("Hard clip", 40), "lo_lvl": -40.0, "hm_lvl": 0.0, "x2": 63, "wet": 100}
    assert doc["lanes"][0]["chain"]["post"][1]["params"] == {"lo_gain": 5}          # un autre type garde ses ids
    assert doc["lanes"][0]["states"][0]["params"]["g"] == {"hm_amt2": R.grit_amount("Gain", 70), "hi_lvl": R.grit_level(15)}
    assert doc["scenes"][0]["params"] == {"g": {"lm_m1": "Fold", "lm_amt1": R.grit_amount("Fold", 40)}, "m": {"lo_gain": 7}}
    assert doc["scenes"][1]["params"]["g"] == {"wet": 50}
    again = copy.deepcopy(doc)
    assert R.apply(again) == 0 and again == doc                                      # idempotent


def test_un_preset_de_bloc_ancien_et_un_document_nouveau():
    bp = {"type": "grit", "params": {"hi_m1": "Bit crush", "hi_v1": 20, "hi_gain": 100}}
    assert R.apply(bp) == 2 and bp["params"] == {"hi_m1": "Bit crush", "hi_amt1": R.grit_amount("Bit crush", 20), "hi_lvl": 12.0}
    new = {"type": "grit", "params": {"hi_m1": "Fuzz", "hi_amt1": 40, "hi_lvl": -3, "drive": 20}}
    keep = copy.deepcopy(new)
    assert R.apply(new) == 0 and new == keep
    both = {"type": "grit", "params": {"hi_v1": 20, "hi_amt1": 40}}                  # les deux : le nouveau gagne
    R.apply(both)
    assert both["params"] == {"hi_amt1": 40}


def test_les_presets_d_usine_ne_nomment_que_des_reglages_de_la_feuille():
    _, e = _grit()
    params, _ = golem_fx.merged("grit", e["params"])
    ids = {d["id"]: d for d in params}
    d = os.path.join(ROOT, "library", "block-presets", "grit")
    names = sorted(fn[:-5] for fn in os.listdir(d) if fn.endswith(".json"))
    assert {"broken", "grit", "megaphone", "telephone"} <= set(names) and len(names) == 15
    for fn in names:
        bp = _json("library", "block-presets", "grit", fn + ".json")
        assert bp["type"] == "grit" and bp["factory"] is True and bp["golem_fx_seed"] == "gfx-grit"
        keep = copy.deepcopy(bp)
        assert R.apply(bp) == 0 and bp == keep                                       # déjà dans les nouvelles unités
        for k, v in bp["params"].items():
            p = ids[k]
            if p.get("type") == "enum":
                assert v in p["options"], (fn, k, v)
            elif p.get("type") == "bool":
                assert isinstance(v, bool)
            else:
                assert p["min"] <= v <= p["max"], (fn, k, v)


@pytest.mark.parametrize("os_name", ["Linux", "Win64", "OSX64"])
def test_le_bloc_se_pose_sous_reaper_avec_golem_fx_et_tombe_sans(tmp_path, monkeypatch, os_name):
    """Le vrai moteur (lupa, REAPER factice) : gfx-grit installé, le bloc est posé par son nom REAPER et ses réglages
    partent normalisés sur les bornes du plugin (dB, rang d'un choix sur 25) ; sans golem-fx, la compile le retire."""
    pytest.importorskip("lupa")
    import shutil
    from pathlib import Path
    from bridge import rig
    from tests.test_rig_lua import PATCH, Lab
    root = Path(ROOT)
    plugins = _json("library", "catalog", "golem-fx-plugins.json")["plugins"]
    cid, p = next((k, v) for k, v in plugins.items() if v["name"] == "GoleM FX Grit")
    old = {"id": "g", "type": "grit", "params": {"hm_m1": "Sample divide", "hm_v1": 24, "hm_m2": "Gain", "hm_v2": 53,
                                                "hi_m1": "Fuzz", "lo_gain": 5, "x2": 63, "wet": 80}}
    R.apply(old)                                                       # ce que le chargement d'un vieux preset rend

    def recall(installed):
        lab = Lab(tmp_path / ("with" if installed else "without"), os_name=os_name)
        for f in ("effects-golem-engine.json", "golem-fx-plugins.json"):
            shutil.copy2(root / "library/catalog" / f, lab.root / "library/catalog" / f)
        monkeypatch.setattr(rig, "_golem_fx_installed", lambda: {cid} if installed else set())
        monkeypatch.setattr(rig, "_QUARANTINE", None)
        if installed:
            lab.F.installed[p["reaper"]] = True
            lab.F.specs[p["reaper"]] = lab.L.table_from([lab.L.table_from({"name": k, "min": 0, "max": 1, "def": 0}) for k in p["params"]])
        patch = copy.deepcopy(PATCH)
        patch["lanes"][0]["chain"]["post"] += [copy.deepcopy(old)]
        lab.compile(patch)
        lab.run(action="rig_recall", preset="ci-engine", scene="A")
        return lab, {f.cfg.renamed_name: f for t in lab.F.tracks.values() for f in t.fx.values() if f.cfg.renamed_name}

    lab, fx = recall(True)
    assert fx["golem:g"].name == "VST3: GoleM FX Grit (GoleM)", lab.log()

    def val(label):
        return next(q.val for q in fx["golem:g"].params.values() if q.name == label)
    assert val("High Mid Module 1 Type") == pytest.approx(10 / 24) and val("High Module 1 Type") == pytest.approx(1)
    assert val("High Mid Module 2 Value") == pytest.approx(R.grit_amount("Gain", 53) / 100)
    assert val("Low Gain") == pytest.approx((-40 + 60) / 72)           # −40 dB sur −60…+12
    assert val("Wet") == pytest.approx(0.8) and val("High Mid Crossover") == pytest.approx(0.63)
    _, fx = recall(False)
    assert "golem:g" not in fx
