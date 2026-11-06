# SPDX-License-Identifier: GPL-3.0-or-later
"""Un switch de la rangée des scènes réservé à un bloc ON/OFF : diode on/off, état ABSOLU.

2026-09-21 : « je clique REC, la diode s'allume, REC se lance ; je reclique, la diode
s'éteint, REC se coupe ». La puce compile ce switch en `effect` (tools/fcb/check-uno2.py le
vérifie) ; ici, la règle du rack et la lecture de l'état."""
from bridge import foot, inputmap, store
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_l_espece_d_un_switch_reserve():
    assert store.claim_species([]) is None
    assert store.claim_species([{"type": "rec"}]) == "toggle"
    assert store.claim_species([{"type": "click"}]) == "toggle"
    assert store.claim_species([{"type": "backing-track"}]) == "gesture"          # tap / double / long
    assert store.claim_species([{"type": "rec"}, {"type": "backing-track"}]) == "toggle"   # la prise
    assert store.claim_species([{"type": "rec"}, {"type": "sample"}]) == "gesture"


def test_le_switch_de_selection_garde_ses_fronts():
    p = {"lanes": [], "config": {"rec": {"blocks": [{"id": "a", "type": "rec", "foot": 1},
                                                     {"id": "b", "type": "click", "foot": 4}]}}}
    assert store.toggle_claim_switches(p, select_switch=1) == [4]


def _reader(monkeypatch, cb):
    r = foot.FootReader(on_scene=cb, on_stomp=lambda sw, want=None: None)
    monkeypatch.setattr(foot, "_DEVICE", {"device_id": "t", "wire_channel": 1, "note_edges": "clean",
                                          "note_base": 0, "edge_switches": None})
    monkeypatch.setattr(foot, "_BOUND", {})
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "fcb")
    return r


def test_le_cc_de_scene_transporte_sa_valeur(monkeypatch):
    seen = []
    r = _reader(monkeypatch, lambda sc, val=None: seen.append((sc, val)))
    r.feed(" 20:0   Control change          1, controller 24, value 127")
    r.feed(" 20:0   Control change          1, controller 24, value 0")
    assert seen == [("E", 127), ("E", 0)]


def test_un_appelant_a_un_argument_reste_servi(monkeypatch):
    seen = []
    r = _reader(monkeypatch, lambda sc: seen.append(sc))
    r.feed(" 20:0   Control change          1, controller 21, value 127")
    assert seen == ["B"]


def test_le_rack_lit_ce_qui_est_flashe_pas_ce_qui_devrait_l_etre():
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    body = src[src.index("def _flashed_effect"):src.index("def _on_foot_scene")]
    assert ".uno2-flashed.json" in src and "effect_switches" in body
    scene = src[src.index("def _on_foot_scene"):src.index("# types SERVICE")]
    assert "_flashed_effect(sw)" in scene and "_do_stomp(sw, want)" in scene
