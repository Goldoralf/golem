# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests du cœur pur du modèle rig (bridge/rig.py) : normalize, validate_routing, path_outputs.
Lancer : .venv/bin/python -m pytest tests/ -q  (aucune dépendance à Reaper ni au catalogue)."""
import pytest

from bridge import rig
from bridge.rig import RigError


def _p(**kw):
    """Preset paths minimal valide."""
    base = {"id": "t", "paths": [{"id": "g", "input": 1, "chain": [{"type": "gate"}], "out": 1}]}
    base.update(kw)
    return base


def test_normalize_assigne_ids_uniques():
    p = _p(paths=[{"input": 1, "chain": [{"type": "gate"}, {"type": "gate"}], "out": 1}])
    n = rig.normalize(p)
    ids = [b["id"] for b in rig.iter_blocks(n)]
    assert len(ids) == 2 and len(set(ids)) == 2 and all(i for i in ids)
    assert n["paths"][0]["id"]                      # id de path auto-assigné


def test_normalize_sans_paths_leve():
    with pytest.raises(RigError):
        rig.normalize({"id": "vide"})


def test_normalize_paths_dupliques_leve():
    p = _p(paths=[{"id": "x", "input": 1, "chain": [], "out": 1},
                  {"id": "x", "input": 2, "chain": [], "out": 2}])
    with pytest.raises(RigError):
        rig.normalize(p)


def test_validate_routing_ok_et_carte():
    """LOT 5 (audit N lanes) : la validation regarde le ROUTAGE RÉEL (out_sel, défaut 1-2), pas le
    marqueur `out` — et rend {canal: [paths]}."""
    n = rig.normalize(_p())
    assert rig.validate_routing(n, out_count=2) == {1: ["g"], 2: ["g"]}


def test_validate_routing_sortie_hors_carte():
    """une sortie CHOISIE (out_sel) au-delà de la carte est refusée ; un marqueur `out` élevé ne l'est plus
    (une 3e lane audio ou la lane claviers — marqueur 3 — sortaient en 1-2 et échouaient sur une carte à 2 sorties)."""
    n = rig.normalize(_p(paths=[{"id": "g", "input": 1, "chain": [], "out": 1, "out_sel": "3-4"}]))
    with pytest.raises(RigError):
        rig.validate_routing(n, out_count=2)
    n = rig.normalize(_p(paths=[{"id": "k", "input": 3, "chain": [], "out": 3}]))
    assert rig.validate_routing(n, out_count=2) == {1: ["k"], 2: ["k"]}


def test_validate_routing_sommation_voulue():
    """deux lanes sur la même sortie se SOMMENT (hardware send, trim par lane) : accepté, et listé."""
    n = rig.normalize(_p(paths=[{"id": "g", "input": 1, "chain": [], "out": 1, "out_sel": "1"},
                                {"id": "v", "input": 2, "chain": [], "out": 2, "out_sel": "1"}]))
    assert rig.validate_routing(n, out_count=2) == {1: ["g", "v"]}
    assert rig.out_channels("3-4") == [3, 4] and rig.out_channels("NONE") == [] and rig.out_channels("2") == [2]


def test_path_outputs_fanout():
    """fan-out (merge null) : les sorties sont celles des branches, le path.out est ignoré."""
    path = {"id": "g", "input": 1, "out": None, "chain": [
        {"split": {"merge": None, "branches": [
            {"blocks": [{"type": "cab"}], "out": 1},
            {"blocks": [{"type": "cab"}], "out": 2}]}}]}
    assert rig.path_outputs(path) == [1, 2]


def test_path_outputs_merge_continue():
    """merge {gain} : le split somme, la chaîne continue -> la sortie est path.out."""
    path = {"id": "g", "input": 1, "out": 2, "chain": [
        {"split": {"merge": {"gain": -3}, "branches": [
            {"blocks": [{"type": "cab"}]}, {"blocks": [{"type": "cab"}]}]}}]}
    assert rig.path_outputs(path) == [2]


def test_build_plan_strict_vs_sandbox():
    """strict_out=False (sandbox) tolère une sortie hors carte ; True la refuse. (Depuis le lot 5, deux
    lanes sur la même sortie ne sont plus une faute : la sommation est voulue.)"""
    p = _p(paths=[{"id": "g", "input": 1, "chain": [], "out": 1, "out_sel": "1-2"},
                  {"id": "v", "input": 2, "chain": [], "out": 2, "out_sel": "5-6"}])
    plan = rig.build_plan(p, out_count=2, strict_out=False)
    assert [pp["id"] for pp in plan["paths"]] == ["g", "v"]
    with pytest.raises(RigError):
        rig.build_plan(p, out_count=2, strict_out=True)


def test_quarantine_retire_le_bloc_et_le_dit(monkeypatch):
    """Un plugin qui fait tomber Reaper (GxDetune, 2026-09-07 : tas corrompu, abort au rebuild)
    n'atteint jamais le rig, quel que soit le preset — et jamais en silence."""
    monkeypatch.setattr(rig, "_QUARANTINE", {"detune": "tas corrompu"})
    said = []
    monkeypatch.setattr(rig.log, "warning", lambda msg, *a, **k: said.append(str(msg)))
    out = rig._drop_quarantined([{"type": "comp", "id": "comp-1"}, {"type": "detune", "id": "detune-1"}, {"type": "delay"}])
    assert [b["type"] for b in out] == ["comp", "delay"]
    assert any("QUARANTAINE" in m and "detune-1" in m and "tas corrompu" in m for m in said)


def test_quarantine_vient_du_catalogue():
    """La donnée vit dans effects.json : detune y est marqué depuis le 2026-09-07."""
    rig._QUARANTINE = None
    assert "detune" in rig.quarantined_types()
