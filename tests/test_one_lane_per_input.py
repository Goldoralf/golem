# SPDX-License-Identifier: GPL-3.0-or-later
"""Une entrée, une lane (2026-10-10, patch « full vst ») : golem_rig pose UNE piste par entrée ; deux lanes sur IN 2
reconstruisaient la même piste et la lane voix vide effaçait les VST de la guitare à chaque rebuild, sans un mot."""
from bridge import scene_bake


def _p(pid, inp, blocks, midi=False):
    return {"id": pid, "input": inp, "midi": midi, "_lane_name": pid.title(), "chain": [{"type": "x"}] * blocks}


def test_la_lane_qui_porte_les_blocs_garde_l_entree_l_autre_est_dite():
    un = []
    kept = scene_bake._one_lane_per_input([_p("voice", 2, 0), _p("guitar", 2, 3), _p("keys", 3, 0, midi=True)], un)
    assert [p["id"] for p in kept] == ["guitar", "keys"]
    assert un == [{"id": "voice", "name": "Voice", "input": "2", "reason": "IN 2 is already played by lane « Guitar »"}]
    assert all("_lane_name" not in p for p in kept)


def test_a_egalite_la_premiere_et_des_entrees_distinctes_ne_bougent_pas():
    un = []
    assert [p["id"] for p in scene_bake._one_lane_per_input([_p("a", 1, 1), _p("b", 1, 1), _p("c", 2, 0)], un)] == ["a", "c"]
    assert [u["id"] for u in un] == ["b"]
    split = {"id": "s", "input": 4, "chain": [{"split": {"branches": [{"blocks": [1, 2]}, {"blocks": [3]}]}}]}
    assert scene_bake._path_blocks(split) == 3
