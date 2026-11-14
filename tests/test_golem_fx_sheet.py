# SPDX-License-Identifier: GPL-3.0-or-later
"""La feuille golem FX (docs/golem-fx-sheet.md) : les réglages d'un bloc joué par golem-fx, tels que sa pédale les
prévoit, fondus avec le catalogue — bridge/golem_fx.py, le compilateur et le plan du Golem Engine."""
import json
import os

from bridge import golem_fx
from bridge.engine import ardour_plan as P

CAT = {e["type"]: e for e in json.load(open(golem_fx.C.ROOT + "/library/catalog/effects.json"))["effects"]}


def test_la_face_avant_du_chorus_et_les_ids_du_catalogue_gardes():
    params, sheet = golem_fx.merged("chorus", CAT["chorus"]["params"])
    ids = [d["id"] for d in params if not d.get("hidden")]
    assert sheet["front"] == ids[:len(sheet["front"])]
    assert {"rate", "depth", "mix", "warmth", "profile", "mode"} <= set(sheet["front"])
    rate = next(d for d in params if d["id"] == "rate")
    assert rate["min"] == CAT["chorus"]["params"][0]["min"] and "engine_only" not in rate     # le catalogue reste
    warmth = next(d for d in params if d["id"] == "warmth")
    assert warmth["engine_only"] == "golem" and warmth["map"] == {"mode": "raw"} and warmth["gfx"]["id"] == "warmth"
    mode = next(d for d in params if d["id"] == "mode")
    assert mode["type"] == "enum" and mode["default"] == mode["options"][0]


def test_un_id_golem_fx_qui_heurte_le_catalogue_est_prefixe(monkeypatch):
    desc = {"front": ["mix", "time"], "groups": [{"id": "g", "name": "G", "custom": "g_custom", "params": ["g_custom", "x"]}],
            "params": {"mix": {"name": "Mix", "kind": "float", "min": 0, "max": 100},
                       "time": {"name": "Time (ms)", "kind": "float", "min": 1, "max": 2000, "unit": "ms"},
                       "g_custom": {"name": "Custom", "kind": "bool", "default": 0},
                       "x": {"name": "X", "kind": "float", "min": 0, "max": 1, "depends": {"param": "g_custom", "equals": True}}}}
    monkeypatch.setattr(golem_fx, "descriptor_for", lambda t: (desc, {"golem_fx": True, "params": {"mix": "Mix"}}))
    cat = [{"id": "mix", "name": "Wet", "min": 0, "max": 1}, {"id": "time", "name": "Delay", "type": "enum", "options": ["1/4"]}]
    params, sheet = golem_fx.merged("x", cat)
    by = {d["id"]: d for d in params}
    assert by["mix"]["min"] == 0 and by["mix"]["max"] == 1          # même nom de plugin : le potard du catalogue
    assert "gfx_time" in by and by["gfx_time"]["unit"] == "ms"      # « time » existe au catalogue avec un autre sens
    assert by["time"].get("hidden") is True                         # le potard du catalogue que le plugin n'a pas
    assert by["x"]["depends"] == {"g_custom": True} and by["x"]["gfx"]["group"] == "g"
    assert sheet["groups"][0]["custom"] == "g_custom"


def test_le_plan_du_golem_engine_ecrit_les_reglages_de_la_pedale():
    blk, skipped = P.plan_block({"id": "c", "type": "chorus", "params": {"rate": 1.2, "warmth": 70, "mode": "Dual I"}},
                                P.load_catalog(), P.load_table())
    got = {e["label"]: e for e in blk["params"]}
    assert got["Warmth"]["value"] == 70 and got["Mode"]["value"] == 1 and got["Rate"]["value"] == 1.2, skipped


def test_le_compilateur_retire_les_reglages_de_la_pedale_la_ou_golem_fx_ne_joue_pas(monkeypatch):
    from bridge import compile_rig, rig
    blocks = [{"id": "c", "type": "chorus", "params": {"rate": 1.2, "warmth": 70}}]
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: set())
    compile_rig._drop_engine_only(blocks)
    assert blocks[0]["params"] == {"rate": 1.2}
    blocks = [{"id": "c", "type": "chorus", "params": {"rate": 1.2, "warmth": 70}}]
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: {"chorus"})
    compile_rig._drop_engine_only(blocks)
    assert blocks[0]["params"] == {"rate": 1.2, "warmth": 70}


def test_les_blocs_du_seul_golem_fx_ne_vivent_que_la_ou_golem_fx_joue(monkeypatch):
    # met, emet, shem (catalogue v43) : aucun plugin d'origine — en quarantaine partout, sauf là où golem-fx les joue
    from bridge import rig
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: set())
    q = rig.quarantined_types()
    only = ("met", "emet", "shem", "golem-double", "glitch")
    assert set(only) <= set(q) and all(q[t].startswith("golem-fx only") for t in only)
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: set(only))
    assert not set(only) & set(rig.quarantined_types())


def test_les_trois_pedales_ont_leur_feuille_et_leur_plugin():
    plugins, table = golem_fx._load()
    for t, front in (("met", ["thresh", "hold", "release"]), ("emet", ["gain", "tone_stack", "level"]), ("shem", ["grind"]),
                     ("golem-double", ["shift", "formant", "voice1", "lpf"])):
        params, sheet = golem_fx.merged(t, CAT[t]["params"])
        assert sheet["front"] == front and sheet["groups"], t
        assert os.listdir(os.path.join(golem_fx.C.ROOT, "library", "block-presets", t)), t     # ses presets, semés
        assert plugins[table[t]["vst3"]]["reaper"] == CAT[t]["plugin"], t      # même nom des deux côtés
        assert all("engine_only" not in d for d in params if d["id"] in front), t


def test_golem_double_est_un_bloc_de_voix_dessine_par_la_pedale_golem():
    # v44 : le rack l'appelle golem-double (le nom du produit n'est pas un type) ; golem-fx s'est aligné (56616d1)
    plugins, table = golem_fx._load()
    assert plugins[table["golem-double"]["vst3"]]["crate"] == "gfx-golem"
    e = CAT["golem-double"]
    assert e["roles"] == ["voice"] and e["category"] == "pitch"


def test_glitch_est_un_effet_spectral_sans_preset_ni_pied():
    # v45 (golem-fx aa7851f) : sa face avant = Effect, Amount, Sustain, Mix ; aucune action au pied ; `align` (réglage de
    # préparation, jamais une valeur de scène) reste un réglage expert, et aucun preset d'usine ne l'allume (e2fbdd9)
    plugins, table = golem_fx._load()
    assert plugins[table["glitch"]["vst3"]]["crate"] == "gfx-glitch"
    assert plugins[table["glitch"]["vst3"]]["reaper"] == CAT["glitch"]["plugin"]
    params, sheet = golem_fx.merged("glitch", CAT["glitch"]["params"])
    assert sheet["front"] == ["fx_a", "amt_a", "sustain", "mix"] and sheet["groups"]
    fx = next(d for d in params if d["id"] == "fx_a")
    assert len(fx["options"]) == 30 and fx["default"] == "Ring Hold"
    assert "align" in {d["gfx"]["id"] for d in params if d.get("gfx") and d["gfx"].get("group")}
    d = os.path.join(golem_fx.C.ROOT, "library", "block-presets", "glitch")
    presets = [json.load(open(os.path.join(d, f))) for f in sorted(os.listdir(d))]
    assert [p["id"] for p in presets if p.get("default")] == ["ringing-partials"]
    assert not any(p["params"].get("align") for p in presets)
    assert "foot" not in CAT["glitch"] and "foot_mode" not in CAT["glitch"]


def test_un_preset_de_golem_fx_parle_le_vocabulaire_du_bloc():
    # docs/golem-fx-sheet.md §5 : l'id de la feuille, une liste par son RANG, l'identité du type jamais écrite
    params, bad = golem_fx.preset_params("rotary", {"speed": "Slow"}, CAT["rotary"]["params"])
    assert not bad and params["speed"] == next(d for d in CAT["rotary"]["params"] if d["id"] == "speed")["options"][1]
    params, bad = golem_fx.preset_params("reverb-plate", {"algo": "Plate", "mix": 25}, CAT["reverb-plate"]["params"])
    assert not bad and "algo" not in params and params["mix"] == 25
    _, bad = golem_fx.preset_params("reverb-plate", {"algo": "Hall"}, CAT["reverb-plate"]["params"])
    assert bad                                            # une plaque reste une plaque
    _, bad = golem_fx.preset_params("reverb", {"algo": "Spring"}, CAT["reverb"]["params"])
    assert not bad                                        # la Reverb générique peut changer d'algorithme
    hidden = {d["id"] for d in golem_fx.merged("wah", CAT["wah"]["params"])[0] if d.get("hidden")}
    assert "model" in hidden                              # le Cry Baby ne change pas de modèle dans sa feuille


def test_les_presets_semes_sont_a_jour_et_bien_formes():
    import glob
    seeded = []
    for f in glob.glob(os.path.join(golem_fx.C.ROOT, "library", "block-presets", "*", "*.json")):
        o = json.load(open(f, encoding="utf-8"))
        if o.get("golem_fx_seed"):
            seeded.append(o)
            t = os.path.basename(os.path.dirname(f))
            assert o["type"] == t and o["id"] == os.path.basename(f)[:-5] and o["factory"] is True, f
            assert t in CAT and isinstance(o["params"], dict) and o["params"], f
    assert len(seeded) > 300
    defaults = [(o["type"], o.get("inst") or "any") for o in seeded if o.get("default")]
    assert len(defaults) == len(set(defaults))            # un seul défaut par (type, instrument)


def test_les_presets_de_golem_fx_ne_s_offrent_que_la_ou_golem_fx_joue(monkeypatch):
    from bridge import rig, routes_content as R
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: set())
    ids = {p["id"] for p in R.block_presets_list("reverb")["presets"]}
    assert "cathedral" in ids and "lush-clean-hall" not in ids          # le rack seul : ses presets à lui
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: {"reverb"})
    ids = {p["id"] for p in R.block_presets_list("reverb")["presets"]}
    assert {"cathedral", "lush-clean-hall"} <= ids
