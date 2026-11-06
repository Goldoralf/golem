# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 1 de l'audit N lanes (docs/archive/audit-2026-09-08-lanes.md §6) : le preset expose une LISTE de lanes
dérivée du document legacy, et le bake est une boucle sur cette liste. Le test d'or rejoue 24 cas
figés AVANT le refactor (Velvetine réel + deux presets synthétiques) et exige l'identique — à une
différence près, voulue et nommée ici."""
import copy
import json
import os

from bridge import scene_bake as sb
from bridge import store

HERE = os.path.dirname(__file__)


def _golden():
    gold = json.load(open(os.path.join(HERE, "fixtures", "paths-golden-2026-09-08.json")))
    inputs = json.load(open(os.path.join(HERE, "fixtures", "paths-golden-inputs.json")))
    # ⚠ une COPIE figée, pas le preset vivant : le mainteneur l'a renommé sur le rack et le test d'or a cassé
    # pour un nom d'onglet (2026-09-09). Les cas « velvetine/… » ont été regénérés depuis cette copie,
    # après vérification que seul `name` différait.
    inputs["velvetine"] = json.load(open(os.path.join(HERE, "fixtures", "velvetine-golden.json")))
    return gold, inputs


def test_or_le_bake_rejoue_a_l_identique(monkeypatch):
    # 2026-09-17 (docs/drums-kit.md lot 2) : les paths MIDI portent `midi_role` + `in_sel` — le fichier
    # d'or a reçu CES DEUX CLÉS seulement (script ciblé, pas une régénération aveugle)
    monkeypatch.setattr(store, "lanes_of", _no_inputmap(store.lanes_of))
    gold, inputs = _golden()
    seen = 0
    for key, old in gold.items():
        name, sc, u, v = key.split("/")
        if name not in inputs:
            continue
        new = sb.to_paths_preset(copy.deepcopy(inputs[name]), sc, union=(u == "u1"), veto=set(v[1:]))
        for p in new["paths"]:
            assert not (p["id"] in ("voice", "keys") and "level" in p), key   # legacy levels.voice/keys : toujours ignorés
        if name == "synth":
            # 2. VOULU : un `post` sans split n'est plus JETÉ (l'ancien _guitar_path l'ignorait) —
            #    ici d1 apparaît en fin de chaîne ; le Designer ne produit jamais ce cas
            for p in new["paths"]:
                if p["id"] == "guitar":
                    p["chain"] = [b for b in p["chain"] if b.get("id") != "d1"]
        assert new == old, key
        seen += 1
    assert seen >= 8


def _no_inputmap(fn):
    """Le test ne dépend pas de la carte branchée : rôles par défaut."""
    def wrapped(p):
        from bridge import inputmap
        cur = inputmap.current
        inputmap.current = lambda: {}
        try:
            return fn(p)
        finally:
            inputmap.current = cur
    return wrapped


def test_lanes_of_derive_les_trois_royaumes(monkeypatch):
    monkeypatch.setattr(store, "lanes_of", _no_inputmap(store.lanes_of))
    _g, inputs = _golden()
    lanes = store.lanes_of(inputs["synth"])
    assert [L["id"] for L in lanes] == ["guitar", "voice", "keys"]
    g, v, k = lanes
    assert g["key"] == "1" and g["name"] == "Gtr" and g["out_sel"] == "1" and g["input"] == 1 and not g["disabled"]
    assert v["disabled"] and v["in_sel"] == "NONE" and v["chain"]["pre"][0] == {"type": "comp"}   # type nu -> bloc
    assert k["midi"] and k["name"] == "Synth" and k["out_sel"] == "2" and k["role"] == "keys" and k["chain"]["split"] is None
    assert store.lanes_of({"guitar": {"pre": []}})[0]["role"] == "guitar"
    assert store.lanes_of({}) == []


def test_le_niveau_de_scene_s_applique_a_toutes_les_lanes(monkeypatch):
    monkeypatch.setattr(store, "lanes_of", _no_inputmap(store.lanes_of))
    p = {"id": "x", "guitar": {"pre": [{"id": "a", "type": "amp"}]}, "voice": {"chain": [{"id": "v", "type": "eq"}]},
         "keys": {"chain": [{"id": "k", "type": "vital"}]},
         "scenes": [{"id": "A", "levels": {"guitar": -3, "voice": -6}, "lanes": {"keys": {"level": -9}, "voice": {"level": -1}}}]}
    out = {q["id"]: q for q in sb.to_paths_preset(p, "A")["paths"]}
    assert out["guitar"]["level"] == -3 and out["voice"]["level"] == -1 and out["keys"]["level"] == -9   # scene.lanes[id] prime ; levels.voice legacy ignoré
    assert out["keys"]["midi"] is True and "midi" not in out["voice"]


def test_migrate_config_pose_la_liste(monkeypatch):
    monkeypatch.setattr(store, "lanes_of", _no_inputmap(store.lanes_of))
    p = store.migrate_config({"id": "x", "guitar": {"pre": []}, "voice": {"chain": []}, "keys": {"chain": []}, "scenes": []})
    assert [L["id"] for L in p["lanes"]] == ["guitar", "voice", "keys"]


def test_tuner_ecoute_la_lane_qui_porte_le_bloc(monkeypatch):
    """Lot 2 : l'accordeur suit la lane du bloc tuner (In 2 pour une voix/2e guitare), In 1 sinon."""
    monkeypatch.setattr(store, "lanes_of", _no_inputmap(store.lanes_of))
    app = store
    p = {"guitar": {"pre": [{"id": "a", "type": "amp"}]}, "voice": {"chain": [{"id": "t", "type": "tuner", "foot": 3}]}, "keys": {"chain": []}}
    assert app.tuner_input(p) == 2
    assert app.tuner_input({"guitar": {"pre": [{"id": "t", "type": "tuner"}]}}) == 1
    assert app.tuner_input({"guitar": {"pre": []}}) == 1 and app.tuner_input(None) == 1
