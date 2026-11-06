# SPDX-License-Identifier: GPL-3.0-or-later
"""Le bloc Arrangement du RIG (docs/arrangement.md §4 bis, 2026-09-16) : la ligne porte les parties,
le preset porte la pédale et la règle d'avance ; la migration remonte la pédale une seule fois.
`.venv/bin/python -m pytest tests/test_arrangement_rig.py -q`"""
import json

import pytest

from bridge import arrangement, config as C, recall, setlists, store


@pytest.fixture
def rack(tmp_path, monkeypatch):
    (tmp_path / "presets").mkdir(); (tmp_path / "setlists").mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path / "setlists"))
    # migrate_foot_to_rig ENREGISTRE le preset, et l'enregistrement écrit les blocs singletons (Rec, Click, Compo) dans
    # leurs configs GLOBALES : sans ça, le test créait config/recorder.json, compo.json et click.json du dépôt (la CI
    # rouge depuis le 2026-10-26, garde de conftest.py)
    for k, name in (("RECORDER_CFG", "recorder.json"), ("CLICK_CFG", "click.json"), ("COMPO_CFG", "compo.json")):
        monkeypatch.setattr(store, k, str(tmp_path / name))
    return tmp_path


def _preset(rack, pid, arr_block=None):
    p = {"id": pid, "name": pid.title(), "lanes": [], "scenes": [{"id": "A", "name": "Intro"}],
         "config": {"gen": {"blocks": []}, "rec": {"blocks": []}}}
    if arr_block:
        p["config"]["arr"] = {"blocks": [arr_block]}
    json.dump(p, open(rack / "presets" / f"{pid}.json", "w"))
    return p


def _setlist(rack, sid, lines):
    json.dump({"id": sid, "name": sid, "lines": lines}, open(rack / "setlists" / f"{sid}.json", "w"))


SECTIONS = {"advance": "bars", "sections": [{"name": "intro", "bars": 4, "scene": "A"}]}


def test_la_pedale_remonte_de_la_chanson_au_rig(rack):
    _preset(rack, "kite")
    _setlist(rack, "covers", [
        {"id": "l1", "preset": "kite", "arrangement": {"type": "arrangement", "id": "arr-line", "foot": 9, "params": SECTIONS}},
        {"id": "l2", "preset": "kite", "arrangement": {"type": "arrangement", "id": "arr-line", "foot": 9, "params": SECTIONS}}])
    done = arrangement.migrate_foot_to_rig()
    assert done == [("kite", 9, 1)]
    blk = arrangement.rig_block(store.load_preset("kite"))
    # le bloc du RIG ne porte JAMAIS de parties : elles sont la chanson (la normalisation du store
    # pose une liste vide, ce qui est la même chose dite autrement)
    assert blk["foot"] == 9 and blk["params"]["advance"] == "bars" and not blk["params"].get("sections")
    assert arrangement.migrate_foot_to_rig() == []                    # idempotente


def test_deux_pedales_pour_le_meme_rig_on_prend_la_plus_frequente(rack):
    _preset(rack, "rig")
    _setlist(rack, "s", [
        {"id": "a", "preset": "rig", "arrangement": {"foot": 7, "params": SECTIONS}},
        {"id": "b", "preset": "rig", "arrangement": {"foot": 9, "params": SECTIONS}},
        {"id": "c", "preset": "rig", "arrangement": {"foot": 9, "params": SECTIONS}}])
    assert arrangement.migrate_foot_to_rig() == [("rig", 9, 2)]        # dit qu'il y en avait deux


def test_un_bloc_qui_a_deja_sa_pedale_n_est_pas_retouche(rack):
    _preset(rack, "rig", {"type": "arrangement", "id": "arr-1", "foot": 6, "params": {"advance": "foot"}})
    _setlist(rack, "s", [{"id": "a", "preset": "rig", "arrangement": {"foot": 9, "params": SECTIONS}}])
    assert arrangement.migrate_foot_to_rig() == []
    assert arrangement.rig_block(store.load_preset("rig"))["foot"] == 6


def test_le_preset_donne_la_pedale_la_ligne_donne_les_parties(rack):
    p = _preset(rack, "rig", {"type": "arrangement", "id": "arr-1", "foot": 9, "params": {"advance": "foot"}})
    line_arr = {"type": "arrangement", "id": "arr-line", "foot": 3, "params": dict(SECTIONS)}
    blk = recall.merge_arrangement(p, line_arr)
    assert blk["foot"] == 9                                            # la pédale du RIG gagne
    assert blk["params"]["advance"] == "foot"                          # la règle du RIG aussi (§6)
    assert blk["params"]["sections"] == SECTIONS["sections"]           # les parties de la CHANSON
    assert blk["id"] == "arr-1"
    # un rig sans bloc : la ligne fait foi telle quelle (rack d'avant la migration)
    assert recall.merge_arrangement(_preset(rack, "old"), line_arr)["foot"] == 3
    # un rig dont le bloc n'a pas de pédale : l'arrangement n'est sur aucun switch
    p2 = _preset(rack, "nofoot", {"type": "arrangement", "id": "arr-1", "params": {}})
    assert "foot" not in recall.merge_arrangement(p2, line_arr)


def test_un_bloc_sans_parties_ne_se_recopie_pas_sur_les_lignes(rack):
    """Le bloc du rig n'a PAS de parties : la vieille migration ne doit pas poser un arrangement vide."""
    _preset(rack, "rig", {"type": "arrangement", "id": "arr-1", "foot": 9, "params": {"advance": "bars"}})
    _setlist(rack, "s", [{"id": "a", "preset": "rig"}])
    assert setlists.migrate_legacy_arrangements() == []
    assert not (setlists.line_by_id("s", "a") or {}).get("arrangement")
