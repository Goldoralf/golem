# SPDX-License-Identifier: GPL-3.0-or-later
"""Balance — appliquer une lane à toute la setlist (docs/band-scenes.md, écran 6). La lane source
remplace la lane du même rôle ; chaque scène garde son état PAR NOM, chaque bloc son pied, chaque
scène son niveau ; un morceau sans lane de ce rôle, ou à lane MIDI, est exclu et dit pourquoi ; un
tap annule. `.venv/bin/python -m pytest tests/test_lane_apply.py -q`"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from test_lane_states import _v2
from bridge import config as C, lane_apply, scene_bake, store


def _bass_named(p, pick_params, drive_gain):
    b = next(L for L in p["lanes"] if L["id"] == "bass-1")
    b["chain"]["pre"][0]["params"] = pick_params
    b["chain"]["pre"][1]["params"] = {"gain": drive_gain}
    b["chain"]["pre"][1]["foot"] = 8
    store.ensure_lane_states(p)
    b["states"] = [{"id": "st-bass-1-pick", "name": "Pick", "blocks": {"b-drive": False}, "params": {}, "branches": {}},
                   {"id": "st-bass-1-fuzz", "name": "Fuzz", "blocks": {"b-drive": True}, "params": {}, "branches": {}}]
    for sc, sid in zip(p["scenes"], ("st-bass-1-pick", "st-bass-1-fuzz", "st-bass-1-fuzz")):
        store.assign_lane_state(p, "bass-1", sc["id"], sid)
    return store.migrate_config(p)


def _setup(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    src = _bass_named(store.migrate_config(json.loads(json.dumps(_v2()))), {"ratio": 6, "threshold": -22}, 5.2)
    # un autre morceau : même basse, ancien compresseur, états croisés (A=Fuzz, B=Pick), un switch sur le comp
    other = json.loads(json.dumps(_v2())); other["id"] = "zero"; other["name"] = "Zero"
    other = _bass_named(store.migrate_config(other), {"ratio": 4, "threshold": -18}, 6.0)
    for sc, sid in zip(other["scenes"], ("st-bass-1-fuzz", "st-bass-1-pick", "st-bass-1-pick")):
        store.assign_lane_state(other, "bass-1", sc["id"], sid)
    ob = next(L for L in other["lanes"] if L["id"] == "bass-1")
    ob["chain"]["pre"][0]["foot"] = 7
    ob["chain"]["pre"][1].pop("foot", None)
    other["scenes"][1]["lanes"]["bass-1"]["level"] = -4
    other = store.migrate_config(other)
    # un morceau sans basse
    nobass = json.loads(json.dumps(_v2())); nobass["id"] = "muzzle"; nobass["lanes"] = [nobass["lanes"][0]]
    for d in (other, nobass):
        store._write_json_atomic(os.path.join(C.PRESETS_DIR, d["id"] + ".json"), d)
    return src, other


def test_le_plan_dit_ce_qui_change_et_qui_est_exclu(tmp_path, monkeypatch):
    src, _ = _setup(tmp_path, monkeypatch)
    pl = lane_apply.plan(src, "bass-1", [{"preset": "kite"}, {"preset": "zero", "title": "Zero"}, {"preset": "muzzle"}, {"preset": "ghost"}])
    rows = {r["preset"]: r for r in pl["songs"]}
    assert rows["kite"]["why"] == "this song" and rows["ghost"]["why"] == "not on this rack"
    assert rows["muzzle"]["ok"] is False and "no bass lane" in rows["muzzle"]["why"]
    assert rows["zero"]["ok"] and rows["zero"]["states"] == ["Fuzz", "Pick"]
    assert "comp · ratio 4 → 6" in rows["zero"]["changes"] and "drive · gain 6.0 → 5.2" in rows["zero"]["changes"]


def test_appliquer_garde_etats_par_nom_switches_et_niveaux_puis_annuler(tmp_path, monkeypatch):
    src, before = _setup(tmp_path, monkeypatch)
    raw_before = open(os.path.join(C.PRESETS_DIR, "zero.json")).read()
    r = lane_apply.apply(src, "bass-1", ["kite", "zero", "muzzle"])
    assert [a["preset"] for a in r["applied"]] == ["zero"] and r["skipped"][0]["preset"] == "muzzle" and r["undo"]
    z = store.load_preset("zero")
    b = next(L for L in z["lanes"] if L["id"] == "bass-1")
    comp = next(x for x in b["chain"]["pre"] if x["type"] == "comp")
    drive = next(x for x in b["chain"]["pre"] if x["type"] == "drive")
    assert comp["params"] == {"ratio": 6, "threshold": -22} and drive["params"] == {"gain": 5.2}   # le son de la source
    assert comp.get("foot") == 7 and "foot" not in drive                                          # les pieds du morceau
    by = {s["id"]: s for s in z["scenes"]}
    names = {st["id"]: st["name"] for st in b["states"]}
    assert [names[by[k]["lanes"]["bass-1"]["state"]] for k in "ABC"] == ["Fuzz", "Pick", "Pick"]   # chaque scène garde SON état
    assert by["A"]["blocks"].get("b-drive") is True and by["B"]["blocks"].get("b-drive") is False
    assert by["B"]["lanes"]["bass-1"]["level"] == -4                                                # niveaux intacts
    # la guitare n'a pas bougé
    g0 = next(L for L in before["lanes"] if L["id"] == "guitar-1"); g1 = next(L for L in z["lanes"] if L["id"] == "guitar-1")
    assert g0["chain"] == g1["chain"]
    assert scene_bake.to_paths_preset(z, "B")["paths"][0] == scene_bake.to_paths_preset(before, "B")["paths"][0]
    u = lane_apply.undo()
    assert u == {"ok": True, "restored": ["zero"]}
    assert open(os.path.join(C.PRESETS_DIR, "zero.json")).read() == raw_before
    assert lane_apply.undo()["ok"] is False


def test_une_lane_midi_ne_recoit_pas_une_lane_audio():
    src = store.migrate_config(json.loads(json.dumps(_v2())))
    dst = json.loads(json.dumps(_v2()))
    dst["lanes"][1]["midi"] = True
    L, why = lane_apply.target_lane(store.migrate_config(dst), next(x for x in src["lanes"] if x["id"] == "bass-1"))
    assert L is None and "MIDI" in why
