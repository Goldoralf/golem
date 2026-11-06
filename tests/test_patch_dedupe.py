# SPDX-License-Identifier: GPL-3.0-or-later
"""P0 de l'audit 2026-09-08 : un dépôt de patch renomme les ids qui collisionnent avec les autres
lanes ; la sauvegarde d'un preset refuse un doublon."""
from bridge import patches, store


def _preset():
    return {"id": "p", "guitar": {"pre": [{"id": "comp-1", "type": "comp"}], "split": {"branches": [{"id": "clean", "blocks": [{"id": "amp-1", "type": "amp"}]}]},
                                  "post": [{"id": "delay-1", "type": "delay"}, {"id": "delay-2", "type": "delay"}]},
            "voice": {"chain": [{"id": "old-1", "type": "eq"}]}, "keys": {"chain": []},
            "config": {"gen": {"blocks": [{"id": "smp", "type": "sample"}]}},
            "scenes": [{"id": "A", "blocks": {"comp-1": True, "delay-1": False}, "params": {}}]}


def test_depot_renomme_les_collisions_chaine_et_scenes():
    chain = {"chain": [{"id": "comp-1", "type": "comp", "foot": 6}, {"id": "delay-1", "type": "delay"}, {"id": "eq-1", "type": "eq"}]}
    scenes = [{"id": "A", "blocks": {"comp-1": False, "delay-1": True, "eq-1": True}, "params": {"delay-1": {"mix": 0.3}}}]
    taken = patches._taken_outside(_preset(), "voice")
    assert "old-1" not in taken and {"comp-1", "delay-1", "delay-2", "smp"} <= taken   # la lane visée est libre
    c2, s2, ren = patches._dedupe(chain, scenes, taken)
    assert ren == {"comp-1": "comp-2", "delay-1": "delay-3"}                          # delay-2 existait déjà
    assert [b["id"] for b in c2["chain"]] == ["comp-2", "delay-3", "eq-1"] and c2["chain"][0]["foot"] == 6
    assert s2[0]["blocks"] == {"comp-2": False, "delay-3": True, "eq-1": True} and s2[0]["params"] == {"delay-3": {"mix": 0.3}}
    assert scenes[0]["blocks"]["comp-1"] is False                                     # l'original du patch n'est pas muté


def test_apply_to_produit_un_preset_sans_doublon(monkeypatch):
    doc = {"id": "vx", "name": "Voice", "role": "voice",
           "chain": {"chain": [{"id": "comp-1", "type": "comp"}, {"id": "delay-1", "type": "delay"}]},
           "scenes": [{"id": "A", "blocks": {"comp-1": False, "delay-1": True}}]}
    monkeypatch.setattr(patches, "get_patch", lambda pid: doc)
    p, realm, lost, added, _sk = patches.apply_to(_preset(), "vx")
    assert realm == "voice" and store.duplicate_block_ids(p) == []
    ids = [b["id"] for b in p["voice"]["chain"]]
    assert ids == ["comp-2", "delay-3"]
    sc = p["scenes"][0]
    assert sc["blocks"]["comp-1"] is True and sc["blocks"]["comp-2"] is False        # la guitare garde SON état
    assert sc["blocks"]["delay-1"] is False and sc["blocks"]["delay-3"] is True


def test_duplicate_block_ids_toutes_lanes():
    p = _preset(); p["voice"]["chain"].append({"id": "comp-1", "type": "comp"}); p["config"]["gen"]["blocks"].append({"id": "amp-1", "type": "x"})
    assert store.duplicate_block_ids(p) == ["amp-1", "comp-1"]
    assert store.duplicate_block_ids(_preset()) == []


def test_scene_lanes_devient_branches_a_la_lecture():
    """Lot 0 de l'audit 2026-09-08 : `scenes[].lanes` (mute par branche) s'appelle `branches`."""
    p = {"scenes": [{"id": "A", "lanes": {"dirty": {"mute": True}}}, {"id": "B", "branches": {"clean": {"mute": True}}, "lanes": {"x": {"mute": True}}}]}
    store.migrate_scene_branches(p)
    assert p["scenes"][0] == {"id": "A", "branches": {"dirty": {"mute": True}}}
    assert p["scenes"][1]["branches"] == {"clean": {"mute": True}} and "lanes" in p["scenes"][1]   # déjà migré : on ne touche pas
    assert store.scene_branches({"lanes": {"d": {"mute": True}}}) == {"d": {"mute": True}}
    assert store.scene_branches({"branches": {}, "lanes": {"d": {"mute": True}}}) == {"d": {"mute": True}}
