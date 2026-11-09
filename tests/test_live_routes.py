# SPDX-License-Identifier: GPL-3.0-or-later
"""Les gestes de scène qui passent par l'écran (page /live) et le lien OSC rapide vers REAPER (bridge/reaper_osc.py).
Audit des tests du 2026-11-09 : `/api/stomp`, `/api/exp`, `/api/live-lock` n'étaient appelées par aucun test, et
reaper_osc.py (pédale EXP, mètres) n'en avait aucun. Aucun REAPER, aucun port ouvert : l'envoi UDP est intercepté."""
import asyncio
import json

import pytest

from bridge import app as A
from bridge.reaper_osc import ReaperLink


@pytest.fixture
def quiet(monkeypatch):
    sent = []

    async def broadcast():
        sent.append("broadcast")
    monkeypatch.setattr(A, "_broadcast", broadcast)
    return sent


def _body(r):
    return json.loads(r.body) if hasattr(r, "body") else r


# ── /api/exp : la pédale bougée à l'écran prend exactement le chemin de la pédale physique ──────────────────────────
def test_exp_va_au_meme_chemin_que_le_pied_et_borne_la_valeur(monkeypatch, quiet):
    got = []
    monkeypatch.setattr(A, "_on_pedal", lambda phys, v: got.append((phys, v)))
    assert asyncio.run(A.exp_set({"pedal": "exp2", "value": 200}))["value"] == 127
    assert asyncio.run(A.exp_set({"pedal": "exp1", "value": -4}))["value"] == 0
    assert asyncio.run(A.exp_set({"pedal": "exp1", "value": "63.6"}))["value"] == 64
    assert got == [("exp2", 127), ("exp1", 0), ("exp1", 64)] and quiet == ["broadcast"] * 3


@pytest.mark.parametrize("body", [{"pedal": "exp3", "value": 10}, {"pedal": "exp1"}, {"pedal": "exp1", "value": "fort"}])
def test_exp_refuse_ce_qui_n_est_pas_une_pedale_ou_une_valeur(monkeypatch, quiet, body):
    monkeypatch.setattr(A, "_on_pedal", lambda *a: pytest.fail("rien ne doit partir"))
    assert asyncio.run(A.exp_set(body)).status_code == 400


# ── /api/stomp : le clic de l'écran est un geste de pied, avec ou sans état absolu ────────────────────────────────
def test_stomp_bascule_ou_pose_un_etat_et_dit_la_source(monkeypatch, quiet):
    got = []
    monkeypatch.setattr(A, "_do_stomp", lambda sw, on, source=None: got.append((sw, on, source)))
    monkeypatch.setattr(A.state, "snapshot", lambda: {"ok": 1})
    asyncio.run(A.stomp({"switch": 7}))                          # bascule
    asyncio.run(A.stomp({"switch": 8, "on": False}))             # état absolu (cue)
    asyncio.run(A.stomp({"block": 9}))                           # ancien nom du champ, encore accepté
    assert got == [(7, None, "ui"), (8, False, "ui"), (9, None, "ui")]


def test_stomp_sans_switch_ne_fait_rien(monkeypatch, quiet):
    monkeypatch.setattr(A, "_do_stomp", lambda *a, **k: pytest.fail("rien ne doit basculer"))
    assert asyncio.run(A.stomp({})).status_code == 400


def test_le_verrou_de_live_se_pose_et_se_dit(monkeypatch, quiet):
    monkeypatch.setattr(A.state, "live_lock", False, raising=False)
    assert asyncio.run(A.live_lock({"on": 1}))["live_lock"] is True and A.state.live_lock is True
    assert asyncio.run(A.live_lock({}))["live_lock"] is False
    assert quiet == ["broadcast", "broadcast"]


# ── reaper_osc : les adresses que golem.ReaperOSC comprend, et rien qui casse si REAPER n'écoute pas ──────────────
class FakeClient:
    def __init__(self, fail=False):
        self.msgs, self.fail = [], fail

    def send_message(self, addr, value):
        if self.fail:
            raise OSError("network unreachable")
        self.msgs.append((addr, value))


def _link(fail=False, host="127.0.0.1"):
    link = ReaperLink(host, 8000, 9000)
    link._client = FakeClient(fail)
    return link


def test_un_parametre_d_fx_part_en_normalise_borne_et_en_index_osc(monkeypatch):
    link = _link()
    link.set_fx_param(3, 0, 11, 1.7)                              # fx/param 0-based côté golem -> 1-based en OSC
    link.set_fx_param(3, 2, 0, -0.2)
    assert link._client.msgs == [("/track/3/fx/1/fxparam/12/value", 1.0), ("/track/3/fx/3/fxparam/1/value", 0.0)]


def test_une_action_numerotee_ou_nommee(monkeypatch):
    link = _link()
    link.trigger_action(40026)
    link.trigger_action("_RS1234abcd")
    link.set_track_mute(5, True)
    assert link._client.msgs == [("/action", 40026), ("/action/str", "_RS1234abcd"), ("/track/5/mute", 1.0)]


def test_reaper_absent_ne_fait_pas_tomber_le_bridge():
    assert _link(fail=True).set_fx_param(1, 0, 0, 0.5) is False


def test_le_lien_n_ecoute_que_la_ou_reaper_parle_et_n_ouvre_rien_a_la_construction():
    """Écouter sur 0.0.0.0 ouvrait un port UDP sans authentification à tout le réseau (Windows : l'invite du
    pare-feu au premier lancement, 2026-10-01) ; ouvrir le port à l'import cassait tout outil lancé à côté."""
    local, remote = _link(), _link(host="192.168.1.20")
    assert local._addr == ("127.0.0.1", 9000) and remote._addr == ("0.0.0.0", 9000)
    assert local._server is None and remote._server is None
