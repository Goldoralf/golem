# SPDX-License-Identifier: GPL-3.0-or-later
"""Le mode SÉLECTION du pied (appui long switch 1 -> 2 chiffres) : seuil de 1,5 s, et il se MONTRE.

Mesuré le 2026-09-21 par injection sur le rack : SW1 tenu 0,7 s (un retour en scène A un peu
appuyé) faisait entrer en sélection au seuil de 0,5 s, SANS RIEN À L'ÉCRAN ; l'appui suivant sur
SW2 devenait le chiffre « 2 » et la scène B n'arrivait pas — le « deuxième A->B qui accroche » de
Paper Kite. Décision le mainteneur : 1,5 s, et un bandeau avec sa sortie (Cancel).
"""
import json
import os

import pytest

from bridge import config as C
from bridge import foot
from bridge import inputmap

WIRE_CH = 1


def _cc(ch, cc, val):
    return f" 20:0   Control change          {ch}, controller {cc}, value {val}"


def _non(ch, note, vel=127):
    return f" 20:0   Note on                 {ch}, note {note}, velocity {vel}"


@pytest.fixture
def rig(monkeypatch):
    calls = {"scene": [], "recall": [], "select": []}
    r = foot.FootReader(
        on_scene=lambda s: calls["scene"].append(s),
        on_stomp=lambda sw, want=None: None,
        on_recall=lambda slot, source=None: calls["recall"].append((slot, source)),
        on_select=lambda info: calls["select"].append(info),
    )
    monkeypatch.setattr(foot, "_DEVICE",
                        {"device_id": "test", "wire_channel": WIRE_CH, "note_edges": "clean",
                         "note_base": 0, "edge_switches": None})
    monkeypatch.setattr(foot, "_BOUND", {})
    monkeypatch.setattr(foot, "_HEARD", {"t": None})
    monkeypatch.setattr(inputmap, "din_role", lambda kind: "fcb")
    yield r, calls
    r._exit_select()                                  # aucun minuteur ne survit au test


def test_le_contrat_du_depot_demande_un_appui_voulu():
    con = json.load(open(os.path.join(C.ROOT, "config", "pedalboard", "contract.json")))
    assert foot._compile_intent(con)["longpress_s"] >= 1.5


def test_le_mode_se_publie_a_l_entree_a_chaque_chiffre_et_a_la_sortie(rig):
    r, calls = rig
    r._enter_select()
    r.feed(_non(WIRE_CH, 1))                          # SW2 -> chiffre 2
    r.feed(_non(WIRE_CH, 2))                          # SW3 -> chiffre 3 : slot 23
    assert [i and i["digits"] for i in calls["select"]] == [[], [2], None]
    assert calls["recall"] == [(23, "select")]


def test_en_selection_une_scene_devient_un_chiffre_c_est_pour_ca_qu_on_le_montre(rig):
    r, calls = rig
    r._enter_select()
    r.feed(_cc(WIRE_CH, 21, 127))                     # le CC de scène B arrive…
    r.feed(_non(WIRE_CH, 1))                          # …avec la Note du switch 2
    assert calls["scene"] == [] and calls["select"][-1]["digits"] == [2]


def test_cancel_depuis_l_ecran_rend_les_scenes(rig):
    r, calls = rig
    r._enter_select()
    r.cancel_select()
    assert calls["select"][-1] is None
    r.feed(_cc(WIRE_CH, 21, 127))
    assert calls["scene"] == ["B"]
