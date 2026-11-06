# SPDX-License-Identifier: GPL-3.0-or-later
"""Ids de BRANCHES uniques entre lanes (retour golem.fm, 2026-09-14) : deux lanes à split sorties du
constructeur portaient toutes deux `lane-a`/`lane-b`, et le mute par branche d'une scène
(`scene.branches[<id>]`, cherché à plat par scene_bake._lane_muted) coupait la branche A de la basse
en coupant la branche claire de la guitare. Deux gardes : le dépôt d'un patch RENOMME les branches
prises ailleurs (comme les blocs), et un preset qui en porte deux est refusé à l'install."""

import json

from bridge import patches as P, store


def _lane(lid, role, a="lane-a", b="lane-b"):
    return {"id": lid, "role": role, "chain": {"pre": [{"type": "gate", "id": f"gate-{lid}"}],
            "split": {"mode": "fanout", "branches": [{"id": a, "blocks": [{"type": "comp", "id": f"comp-{lid}"}]},
                                                     {"id": b, "blocks": [{"type": "delay", "id": f"delay-{lid}"}]}]},
            "post": []}}


def test_duplicate_branch_ids_entre_lanes_pas_dans_une_lane():
    p = {"lanes_v": 2, "scenes": [], "lanes": [_lane("guitar", "guitar"), _lane("bass", "bass")]}
    assert store.duplicate_branch_ids(p) == ["lane-a", "lane-b"]
    p2 = {"lanes_v": 2, "scenes": [], "lanes": [_lane("guitar", "guitar"), _lane("bass", "bass", "lane-a-bass", "lane-b-bass")]}
    assert store.duplicate_branch_ids(p2) == []
    assert store.duplicate_block_ids(p) == []                 # les blocs, eux, étaient uniques : la garde d'avant ne voyait rien


def test_le_depot_renomme_les_branches_prises_et_les_mutes_suivent():
    chain = {"pre": [], "split": {"mode": "fanout", "branches": [{"id": "lane-a", "blocks": [{"type": "comp", "id": "comp-1"}]},
                                                                {"id": "lane-b", "blocks": [{"type": "amp", "id": "amp-1"}]}]}, "post": []}
    scenes = [{"id": "A", "name": "A", "blocks": {}, "params": {}, "branches": {"lane-a": {"mute": True}}},
              {"id": "B", "name": "B", "lanes": {"lane-b": {"mute": True}, "guitar": {"level": -3}}}]
    chain2, scenes2, ren = P._dedupe(json.loads(json.dumps(chain)), scenes, taken=set(), taken_branches={"lane-a", "lane-b"})
    ids = [br["id"] for br in chain2["split"]["branches"]]
    assert ids == ["lane-a-2", "lane-b-2"]
    assert scenes2[0]["branches"] == {"lane-a-2": {"mute": True}}
    assert scenes2[1]["lanes"] == {"lane-b-2": {"mute": True}, "guitar": {"level": -3}}   # le niveau de lane n'est pas une branche
    assert ren == {"branch:lane-a": "lane-a-2", "branch:lane-b": "lane-b-2"}
    # rien de pris ailleurs : rien ne bouge
    _, s3, ren3 = P._dedupe(json.loads(json.dumps(chain)), scenes, taken=set(), taken_branches=set())
    assert ren3 == {} and s3 is scenes


def test_taken_branches_outside_exclut_la_lane_visee():
    p = {"lanes_v": 2, "scenes": [], "lanes": [_lane("guitar", "guitar"), _lane("bass", "bass", "lane-a-bass", "lane-b-bass")]}
    assert P._taken_branches_outside(p, "guitar") == {"lane-a-bass", "lane-b-bass"}
    assert P._taken_branches_outside(p, "bass") == {"lane-a", "lane-b"}
