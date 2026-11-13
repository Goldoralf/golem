# SPDX-License-Identifier: GPL-3.0-or-later
"""La feuille golem FX (docs/golem-fx-sheet.md) : les réglages d'un bloc joué par golem-fx, tels que sa pédale les
prévoit, fondus avec le catalogue — bridge/golem_fx.py, le compilateur et le plan du Golem Engine."""
import json

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
    assert {"met", "emet", "shem"} <= set(q) and all(q[t].startswith("golem-fx only") for t in ("met", "emet", "shem"))
    monkeypatch.setattr(rig, "_engine_safe_types", lambda: {"met", "emet", "shem"})
    assert not {"met", "emet", "shem"} & set(rig.quarantined_types())


def test_les_trois_pedales_ont_leur_feuille_et_leur_plugin():
    plugins, table = golem_fx._load()
    for t, front in (("met", ["thresh", "hold", "release"]), ("emet", ["gain", "tone_stack", "level"]), ("shem", ["grind"])):
        params, sheet = golem_fx.merged(t, CAT[t]["params"])
        assert sheet["front"] == front and sheet["groups"] and sheet["presets"], t
        assert plugins[table[t]["vst3"]]["reaper"] == CAT[t]["plugin"], t      # même nom des deux côtés
        assert all("engine_only" not in d for d in params if d["id"] in front), t
