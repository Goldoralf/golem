# SPDX-License-Identifier: GPL-3.0-or-later
"""2026-10-24, un testeur Windows en mode Pedalboard (docs/modes.md §3.1, §3.2) : un son que le mode vide de toutes ses
lanes dit POURQUOI, en anglais (plus « preset sans 'paths' ») ; l'édition d'un mode arrête vraiment la batterie qui
tourne (`stop_orphans` recevait `True`)."""
import json

import pytest

from bridge import inputmap, modes, rig, scene_bake

EMPTY = {"pre": [], "split": None, "post": []}


@pytest.fixture
def guitar_card(monkeypatch):
    card = inputmap.with_nth([{"ch": "1", "role": "none"}, {"ch": "2", "role": "none"}, {"ch": "3", "role": "guitar"}])
    monkeypatch.setattr(inputmap, "current", lambda device=None: {"inputs": card, "usb": []})
    monkeypatch.setattr(modes, "current", lambda: {"id": "pedalboard", "name": "Pedalboard"})


def _patch(*lanes):
    return {"id": "p", "lanes_v": 2, "scenes": [{"id": "A"}], "lanes": list(lanes)}


def test_un_son_vide_par_le_mode_dit_quelle_entree_et_quel_mode(guitar_card):
    p = _patch({"id": "guitar", "role": "guitar", "in_sel": "3", "in_role": "guitar", "in_nth": 1, "chain": EMPTY})
    b = scene_bake.to_paths_preset(p, "A", union=True, veto={"guitar"})
    assert b["paths"] == []
    assert b["why_empty"] == "nothing to play: Guitar 1 is off in mode « Pedalboard » — turn it back on in Settings ▸ Mode"
    with pytest.raises(rig.RigError, match="off in mode « Pedalboard »"):
        rig.normalize(b)


def test_un_son_que_la_carte_ne_peut_pas_prendre_dit_ce_qui_manque(guitar_card):
    p = _patch({"id": "guitar-2", "name": "Rhythm Guitar", "role": "guitar", "in_sel": "2", "in_role": "guitar",
                "in_nth": 2, "chain": EMPTY})
    b = scene_bake.to_paths_preset(p, "A", union=True, veto=set())
    assert b["paths"] == [] and b["why_empty"].startswith("nothing to play: Rhythm Guitar needs Guitar 2")


def test_un_patch_voix_sur_une_carte_sans_entree_voix_dit_pourquoi(guitar_card):
    # mesuré le 2026-10-25 (check-rig-materialize --all) : un patch voix de golem.fm répondait « this sound has no lane »
    from bridge import patches
    doc = {"id": "v", "name": "Vocal", "role": "voice", "chain": {"chain": [{"id": "b1", "type": "gate"}]},
           "scenes": [{"id": "A", "name": "Verse"}]}
    p = patches.as_preset(doc, imap=inputmap.current())
    b = scene_bake.to_paths_preset(p, "A", union=True, veto=set())
    assert b["paths"] == [] and b["why_empty"].startswith("nothing to play: Vocal cannot be mounted: no voice input")
    assert b["unmounted"][0]["id"] == p["lanes"][0]["id"]       # l'onglet de la lane passe à l'orange


def test_un_son_qui_joue_ne_porte_pas_de_raison(guitar_card):
    p = _patch({"id": "guitar", "role": "guitar", "in_sel": "3", "in_role": "guitar", "in_nth": 1, "chain": EMPTY})
    b = scene_bake.to_paths_preset(p, "A", union=True, veto=set())
    assert b["paths"] and "why_empty" not in b
    with pytest.raises(rig.RigError, match="^nothing to play: no lane"):           # un plan vide venu d'ailleurs
        rig.normalize({"id": "x", "paths": []})


def test_editer_un_mode_arrete_la_batterie_que_reaper_dit_en_cours(tmp_path, monkeypatch):
    from bridge import app, config as C, routes_modes, state as S
    drums = tmp_path / ".drums.json"
    drums.write_text(json.dumps({"blocks": {"dm-1": {"playing": True}, "dm-2": {"playing": False}}}))
    monkeypatch.setattr(C, "DRUMS_FILE", str(drums))
    monkeypatch.setattr(S.state, "preset_id", None)
    monkeypatch.setattr(S.state, "mode", {"id": "pedalboard", "services": {"drummachine": False, "standard": False}})
    got, std = {}, []
    monkeypatch.setattr(app._drums_ctl, "stop_orphans", lambda valid, also_playing=None: got.update(valid=valid, playing=also_playing))
    monkeypatch.setattr(app, "_standard_cmd", lambda op, pm: std.append(op))
    monkeypatch.setattr(routes_modes, "_broadcast_later", lambda: None, raising=False)
    try:
        routes_modes._re_veto()
    except Exception:
        pass                                    # la suite (click, ré-émission du rig) n'est pas ce que ce test garde
    assert got == {"valid": set(), "playing": ["dm-1"]}                              # les blocs EN COURS, pas `True`
    assert std == ["stop"]                                                          # la grille s'arrête aussi
