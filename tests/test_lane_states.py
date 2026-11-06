# SPDX-License-Identifier: GPL-3.0-or-later
"""Les ÉTATS de lane (docs/band-scenes.md §3, lot 1 — 2026-09-15) : une lane porte ses états nommés,
une scène en pointe un par lane. Au lot 1 la table plate de la scène reste la vérité du son : la
migration ne change rien au bake, elle donne une identité et un NOM à ce que chaque scène fait à
chaque lane — et le dépôt d'un patch garde les noms de ses scènes (« Pick », « Fuzz »).
`.venv/bin/python -m pytest tests/test_lane_states.py -q`"""
import json

from bridge import patches, scene_bake, store


def _v2():
    return {"id": "kite", "name": "Paper Kite", "lanes_v": 2,
            "lanes": [
                {"id": "guitar-1", "role": "guitar", "name": "Guitar 1", "in_sel": "1",
                 "chain": {"pre": [{"id": "wh", "type": "whammy-dt"}, {"id": "muff", "type": "pedal-nam", "bypass": True}],
                           "split": {"mode": "fanout", "branches": [{"id": "g-a", "blocks": [{"id": "amp-c", "type": "amp"}]},
                                                                    {"id": "g-b", "blocks": [{"id": "amp-d", "type": "amp"}]}]},
                           "post": [{"id": "tape", "type": "delay-tape", "bypass": True, "params": {"mix": 20}}]}},
                {"id": "bass-1", "role": "bass", "name": "Bass 1", "in_sel": "2",
                 "chain": {"pre": [{"id": "b-comp", "type": "comp"}, {"id": "b-drive", "type": "drive", "bypass": True}], "split": None, "post": []}}],
            "scenes": [
                {"id": "A", "name": "Intro", "blocks": {}, "params": {}, "branches": {"g-b": {"mute": True}}},
                {"id": "B", "name": "Verse", "blocks": {"muff": True, "b-drive": False}, "params": {"tape": {"mix": 35}}, "branches": {"g-a": {"mute": True}},
                 "lanes": {"bass-1": {"level": -1}}},
                {"id": "C", "blocks": {"b-drive": True, "tape": True}},
            ],
            "config": {"gen": {"blocks": []}, "rec": {"blocks": []}, "arr": {"blocks": []}}}


def test_migration_cree_un_etat_nomme_par_lane_et_par_scene_sans_changer_le_son():
    p = store.migrate_config(json.loads(json.dumps(_v2())))
    ref = store.migrate_config(json.loads(json.dumps(_v2())))
    g = next(L for L in p["lanes"] if L["id"] == "guitar-1"); b = next(L for L in p["lanes"] if L["id"] == "bass-1")
    assert [st["name"] for st in g["states"]] == ["Intro", "Verse", "C"]           # nom de la scène, sinon sa lettre
    assert [st["id"] for st in b["states"]] == ["st-bass-1-A", "st-bass-1-B", "st-bass-1-C"]
    assert all(st["implicit"] for st in g["states"])
    # chaque scène pointe SON état, et l'état porte la tranche de la lane : rien d'une autre lane
    scB = next(s for s in p["scenes"] if s["id"] == "B")
    assert scB["lanes"]["guitar-1"]["state"] == "st-guitar-1-B" and scB["lanes"]["bass-1"] == {"level": -1, "state": "st-bass-1-B"}
    stB = next(st for st in g["states"] if st["id"] == "st-guitar-1-B")
    assert stB["blocks"] == {"muff": True} and stB["params"] == {"tape": {"mix": 35}} and stB["branches"] == {"g-a": {"mute": True}}
    assert next(st for st in b["states"] if st["id"] == "st-bass-1-B")["blocks"] == {"b-drive": False}
    # le bake est identique avec ou sans états (la table plate reste la vérité au lot 1)
    for sid in ("A", "B", "C"):
        assert scene_bake.to_paths_preset(p, sid) == scene_bake.to_paths_preset(ref, sid)
    # idempotent
    again = store.migrate_config(json.loads(json.dumps(p)))
    assert again["lanes"] == p["lanes"] and again["scenes"] == p["scenes"]


def test_un_etat_suit_la_table_plate_et_une_scene_supprimee_libere_son_etat_implicite():
    p = store.migrate_config(json.loads(json.dumps(_v2())))
    scB = next(s for s in p["scenes"] if s["id"] == "B")
    scB["blocks"]["muff"] = False                       # le Designer édite la scène (lot 1 : écriture plate)
    p["scenes"] = [s for s in p["scenes"] if s["id"] != "C"]
    p = store.migrate_config(p)
    g = next(L for L in p["lanes"] if L["id"] == "guitar-1")
    assert next(st for st in g["states"] if st["id"] == "st-guitar-1-B")["blocks"] == {"muff": False}
    assert [st["id"] for st in g["states"]] == ["st-guitar-1-A", "st-guitar-1-B"]   # C, implicite, retiré


def test_le_depot_d_un_patch_garde_les_noms_de_ses_scenes_comme_etats():
    p = store.migrate_config(json.loads(json.dumps(_v2())))
    doc = {"id": "bass-pick", "name": "Bass pick", "role": "bass",
           "chain": {"pre": [{"id": "pc", "type": "comp"}, {"id": "pd", "type": "drive", "bypass": True}], "split": None, "post": []},
           "scenes": [{"id": "A", "name": "Pick", "blocks": {"pd": False}},
                      {"id": "B", "name": "Fuzz", "blocks": {"pd": True}, "level": -1},
                      {"id": "D", "name": "Fingers", "blocks": {"pc": False}}]}
    from bridge import patches as P
    import types
    orig = P.get_patch
    P.get_patch = lambda pid: doc if pid == "bass-pick" else orig(pid)
    try:
        q, realm, lost, added, _sk = P.apply_to(p, "bass-pick", lane="bass-1")
    finally:
        P.get_patch = orig
    assert realm == "bass-1" and added == ["D"] and not lost
    q = store.migrate_config(q)
    b = next(L for L in q["lanes"] if L["id"] == "bass-1")
    assert [(st["id"], st["name"]) for st in b["states"]] == [("st-bass-1-A", "Pick"), ("st-bass-1-B", "Fuzz"), ("st-bass-1-D", "Fingers"), ("st-bass-1-C", "C")]
    assert not any(st.get("implicit") for st in b["states"][:3])   # déposés = explicites
    by = {s["id"]: s for s in q["scenes"]}
    assert by["A"]["lanes"]["bass-1"]["state"] == "st-bass-1-A" and by["D"]["lanes"]["bass-1"]["state"] == "st-bass-1-D"
    assert by["C"]["lanes"]["bass-1"]["state"] == "st-bass-1-C"    # scène du morceau que le patch n'a pas : implicite
    # la scène D du morceau, créée par le dépôt, garde le nom du patch (§18) ; le guitariste n'y perd rien
    assert by["D"]["name"] == "Fingers" and by["D"]["lanes"]["guitar-1"]["state"] == "st-guitar-1-D"
    # la table plate dit la même chose que l'état (lot 1)
    assert by["B"]["blocks"].get("pd") is True and next(st for st in b["states"] if st["id"] == "st-bass-1-B")["blocks"] == {"pd": True}
    # un état explicite survit à la suppression de sa scène
    q["scenes"] = [s for s in q["scenes"] if s["id"] != "D"]
    q = store.migrate_config(q)
    assert "st-bass-1-D" in {st["id"] for st in next(L for L in q["lanes"] if L["id"] == "bass-1")["states"]}


def test_la_fiche_publie_l_etat_par_lane_et_par_scene():
    p = store.migrate_config(json.loads(json.dumps(_v2())))
    fiche = store.preset_summary(p)
    rows = {s["id"]: s["lanes"] for s in fiche["scenes"]}
    assert [(r["id"], r["role"], r["state"]) for r in rows["B"]] == [("guitar-1", "guitar", "Verse"), ("bass-1", "bass", "Verse")]
    assert rows["B"][1]["level"] == -1 and rows["B"][0]["glyph_type"] in ("pedal-nam", "amp")
    assert rows["A"][0]["mute"] is False                          # une branche mutée sur deux : la lane joue
    # legacy (hors v2) : pas de lignes, rien ne casse
    assert store.preset_summary({"id": "x", "guitar": {"pre": []}, "scenes": [{"id": "A"}]})["scenes"][0]["lanes"] == []


# ── LOT 3 : l'état PARTAGÉ est la vérité, la table plate son miroir ─────────────────────────────
def _shared():
    """Bass 1 : « Pick » pointé par A et B, « Fuzz » par C. Guitare : implicites."""
    p = store.migrate_config(json.loads(json.dumps(_v2())))
    b = next(L for L in p["lanes"] if L["id"] == "bass-1")
    b["states"] = [{"id": "st-pick", "name": "Pick", "blocks": {"b-drive": False}, "params": {}, "branches": {}},
                   {"id": "st-fuzz", "name": "Fuzz", "blocks": {"b-drive": True}, "params": {"b-comp": {"ratio": 6}}, "branches": {}}]
    for sc, sid in zip(p["scenes"], ("st-pick", "st-pick", "st-fuzz")):
        assert store.assign_lane_state(p, "bass-1", sc["id"], sid)
    return store.migrate_config(p)


def test_un_etat_partage_ecrit_sa_tranche_dans_chaque_scene_qui_le_pointe():
    p = _shared()
    by = {s["id"]: s for s in p["scenes"]}
    assert by["A"]["blocks"].get("b-drive") is False and by["B"]["blocks"].get("b-drive") is False
    assert by["C"]["blocks"].get("b-drive") is True and by["C"]["params"]["b-comp"] == {"ratio": 6}
    # la tranche des AUTRES lanes n'a pas bougé
    assert by["B"]["blocks"].get("muff") is True and by["B"]["params"]["tape"] == {"mix": 35}


def test_editer_une_scene_qui_pointe_un_etat_partage_edite_toutes_les_autres():
    p = _shared()
    by = {s["id"]: s for s in p["scenes"]}
    by["B"]["params"]["b-comp"] = {"ratio": 3}          # un écrivain qui ne connaît que la table plate (golem.fm, un script)
    p = store.migrate_config(p)
    by = {s["id"]: s for s in p["scenes"]}
    st = next(x for x in next(L for L in p["lanes"] if L["id"] == "bass-1")["states"] if x["id"] == "st-pick")
    assert st["params"] == {"b-comp": {"ratio": 3}}
    assert by["A"]["params"]["b-comp"] == {"ratio": 3}   # A suit B : même état, même son
    assert (by["C"].get("params") or {}).get("b-comp") == {"ratio": 6}


def test_deux_scenes_qui_se_contredisent_l_etat_gagne():
    p = _shared()
    by = {s["id"]: s for s in p["scenes"]}
    by["A"]["params"]["b-comp"] = {"ratio": 2}
    by["B"]["params"]["b-comp"] = {"ratio": 9}
    p = store.migrate_config(p)
    by = {s["id"]: s for s in p["scenes"]}
    assert "b-comp" not in by["A"]["params"] and "b-comp" not in by["B"]["params"]   # retour à « Pick » tel qu'écrit


def test_une_lane_coupee_dans_une_scene_part_au_plancher_sans_quitter_le_rig():
    p = _shared()
    by = {s["id"]: s for s in p["scenes"]}
    by["C"]["lanes"]["bass-1"]["mute"] = True
    live_c = scene_bake.to_paths_preset(p, "C", union=True)
    live_a = scene_bake.to_paths_preset(p, "A", union=True)
    bass_c = next(x for x in live_c["paths"] if x["id"] == "bass-1")
    bass_a = next(x for x in live_a["paths"] if x["id"] == "bass-1")
    assert bass_c["level"] == scene_bake.LANE_MUTE_DB and bass_a.get("level") == by["A"]["lanes"]["bass-1"].get("level")
    assert [x["id"] for x in live_c["paths"]] == [x["id"] for x in live_a["paths"]]   # même topologie : bascule sans rebuild


def test_une_scene_renumerotee_ne_vole_pas_l_etat_d_une_autre():
    p = _shared()
    # un id d'état explicite qui porte la lettre d'une scène (« st-bass-1-B ») ne se réutilise pas en implicite
    b = next(L for L in p["lanes"] if L["id"] == "bass-1")
    b["states"].append({"id": "st-bass-1-D", "name": "Fingers", "blocks": {}, "params": {}, "branches": {}})
    p["scenes"].append({"id": "D", "name": "Bridge", "blocks": {}, "params": {}, "branches": {}})
    p = store.migrate_config(p)
    b = next(L for L in p["lanes"] if L["id"] == "bass-1")
    d = next(s for s in p["scenes"] if s["id"] == "D")
    assert d["lanes"]["bass-1"]["state"] == "st-bass-1-D-2"
    assert next(x for x in b["states"] if x["id"] == "st-bass-1-D")["name"] == "Fingers"


def test_une_lane_coupee_n_est_pas_un_mute_de_branche_et_survit_au_depot_d_un_patch(monkeypatch):
    """`scene.lanes[<lane>].mute` a deux sens : ancien mute de branche (sans state ni level) ou lane coupée
    dans la scène (avec state). Déposer un patch sur la basse écartait la coupure de la VOIX."""
    # une carte à trois entrées, la voix sur la sienne : une entrée = une lane (scene_bake._one_lane_per_input) —
    # la voix sur IN 2 avec la basse n'était montée que par accident (la dernière lane écrasait la piste)
    card = {"inputs": [{"ch": "1"}, {"ch": "2"}, {"ch": "3"}]}
    monkeypatch.setattr(store, "_imap", lambda: card)
    monkeypatch.setattr("bridge.inputmap.current", lambda *a, **k: card)
    p = store.migrate_config(json.loads(json.dumps(_v2())))
    p["lanes"].append({"id": "voice-1", "role": "voice", "name": "Voice 1", "in_sel": "3",
                       "chain": {"pre": [{"id": "v-echo", "type": "delay-echo"}], "split": None, "post": []}})
    p = store.migrate_config(p)
    scB = next(s for s in p["scenes"] if s["id"] == "B")
    scB["lanes"]["voice-1"]["mute"] = True
    assert store.is_legacy_branch_mute({"mute": True}) and not store.is_legacy_branch_mute(scB["lanes"]["voice-1"])
    assert "voice-1" not in store.scene_branches(scB)
    doc = {"id": "bp", "name": "Bass pick", "role": "bass",
           "chain": {"pre": [{"id": "pc", "type": "comp"}], "split": None, "post": []},
           "scenes": [{"id": "B", "name": "Pick", "blocks": {"pc": True}}]}
    from bridge import patches as P
    orig = P.get_patch
    P.get_patch = lambda pid: doc if pid == "bp" else orig(pid)
    try:
        q, *_ = P.apply_to(p, "bp", lane="bass-1")
    finally:
        P.get_patch = orig
    q = store.migrate_config(q)
    qB = next(s for s in q["scenes"] if s["id"] == "B")
    assert qB["lanes"]["voice-1"]["mute"] is True and qB["lanes"]["voice-1"]["state"] == "st-voice-1-B"
    live = scene_bake.to_paths_preset(q, "B", union=True)
    assert next(x for x in live["paths"] if x["id"] == "voice-1")["level"] == scene_bake.LANE_MUTE_DB
    # un ANCIEN mute de branche, lui, se lit toujours comme tel
    assert store.scene_branches({"lanes": {"g-a": {"mute": True}}}) == {"g-a": {"mute": True}}


def test_une_coupure_de_lane_sans_state_ne_demenage_pas_dans_les_branches():
    """Un écrivain qui pose `lanes[<lane>].mute` sans `state` (brouillon sans états) : la clé est l'id d'une
    lane du preset, ce n'est donc pas un ancien mute de branche — la migration ne le déplace pas."""
    p = json.loads(json.dumps(_v2()))
    p["scenes"][1] = {"id": "B", "name": "Verse", "blocks": {}, "lanes": {"bass-1": {"mute": True}, "g-a": {"mute": True}}}
    p = store.migrate_config(p)
    scB = next(s for s in p["scenes"] if s["id"] == "B")
    assert scB["lanes"]["bass-1"]["mute"] is True and scB["lanes"]["bass-1"]["state"] == "st-bass-1-B"
    assert scB["branches"] == {"g-a": {"mute": True}} and "g-a" not in scB["lanes"]
