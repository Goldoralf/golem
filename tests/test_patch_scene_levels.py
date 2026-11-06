# SPDX-License-Identifier: GPL-3.0-or-later
"""Le niveau par lane d'une scène voyage avec le patch, et le dépôt ne l'efface pas (retour
golem.fm, 2026-09-14). `scenes[].lanes` a deux vies — les mutes legacy et les NIVEAUX par lane —
et deux fonctions les confondaient : `scenes_of` ignorait `lanes[<lane>].level`, `_inject_scenes`
faisait `pop("lanes")` en posant des branches. `.venv/bin/python -m pytest tests/test_patch_scene_levels.py -q`"""
from bridge import patches as P
from bridge.store import scene_branches, scene_lane_level


def _chain():
    return {"pre": [{"id": "g1", "type": "gate"}],
            "split": {"mode": "merge", "branches": [{"id": "lane-a", "blocks": [{"id": "a1", "type": "amp"}]},
                                                    {"id": "lane-b", "blocks": [{"id": "a2", "type": "amp"}]}]},
            "post": []}


def _preset(lane_id="guitar-try"):
    return {"id": "sandbox-try", "lanes_v": 2,
            "lanes": [{"id": lane_id, "role": "guitar", "chain": _chain()}],
            "scenes": [{"id": "A", "name": "Fuzzy Lead", "blocks": {}, "params": {},
                        "lanes": {lane_id: {"level": 3}}, "branches": {"lane-b": {"mute": True}}}]}


def test_scenes_of_emporte_le_niveau_par_lane_et_les_mutes():
    out = P.scenes_of(_preset(), "guitar-try")
    assert out == [{"id": "A", "name": "Fuzzy Lead", "branches": {"lane-b": {"mute": True}}, "level": 3}]


def test_scene_branches_lit_les_deux_noms_sans_prendre_un_niveau_pour_un_mute():
    sc = {"branches": {"lane-b": {"mute": True}}, "lanes": {"guitar": {"level": 3}, "lane-a": {"mute": True}}}
    assert scene_branches(sc) == {"lane-a": {"mute": True}, "lane-b": {"mute": True}}
    assert scene_lane_level(sc, "guitar") == 3 and scene_lane_level(sc, "lane-a") is None


def test_inject_garde_le_niveau_du_morceau_et_pose_celui_du_patch():
    song = {"scenes": [{"id": "A", "blocks": {}, "params": {},
                        "lanes": {"voice": {"level": -4}, "lane-a": {"mute": True}}}]}
    patch_scenes = [{"id": "A", "branches": {"lane-b": {"mute": True}}, "level": 3},
                    {"id": "B", "name": "Solo", "level": 5}]
    created = P._inject_scenes(song, "guitar", patch_scenes, _chain())
    a, b = song["scenes"]
    assert a["branches"] == {"lane-b": {"mute": True}}          # le mute legacy de lane-a est remplacé (branche du patch)
    assert a["lanes"] == {"voice": {"level": -4}, "guitar": {"level": 3}}   # le niveau voix du MORCEAU survit
    assert a["levels"] == {"guitar": 3}
    assert created == ["B"] and b["lanes"]["guitar"]["level"] == 5 and b["name"] == "Solo"
