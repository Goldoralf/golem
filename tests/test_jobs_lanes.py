# SPDX-License-Identifier: GPL-3.0-or-later
"""AUDIT 2026-09-13, M6 (fin) : la file de jobs a DEUX voies, ordonnées par famille.

Un `install` de 200 Mo ne retient pas un `take-tag` ; un `patch-try` attend le `preset-install` qui
le précède ; un job re-proposé par golem.fm pendant qu'il tourne n'est pas lancé deux fois.
"""
import threading, time
import pytest
from bridge import tones_jobs as J


@pytest.fixture
def queue(monkeypatch):
    acked, calls = [], []
    monkeypatch.setattr("bridge.golemfm._cfg", lambda: ("http://x", "tok"))
    pending = {"jobs": []}
    def _req(method, path, body=None, **k):
        if path.startswith("/api/ext/tones/jobs?") or path == "/api/ext/tones/jobs":
            return 200, {"jobs": list(pending["jobs"])}
        if path.endswith("/ack"):
            acked.append((int(path.split("/")[-2]), body["ok"])); return 200, {}
        return 200, {}
    monkeypatch.setattr(J, "_req", _req)
    gate = threading.Event()
    def slow(j): calls.append(("install", j["id"])); gate.wait(5); return "installed"
    def fast(j): calls.append((j["action"], j["id"])); return "done"
    monkeypatch.setattr(J, "_HANDLERS", {"install": slow, "patch-try": fast, "take-tag": fast, "setlist-push": fast})
    J._inflight.clear()
    yield {"pending": pending, "acked": acked, "calls": calls, "gate": gate}
    gate.set(); J.drain()


def test_une_prise_nattend_pas_un_gros_pack(queue):
    queue["pending"]["jobs"] = [{"id": 1, "action": "install", "uid": "t3k:1"}, {"id": 2, "action": "take-tag"}]
    r = J.process()
    assert r["processed"] == 2                                     # les deux sont PRIS
    time.sleep(0.2)
    assert (2, True) in queue["acked"] and (1, True) not in queue["acked"]   # la prise est acquittée, l'install tourne encore
    queue["gate"].set(); assert J.drain()
    assert (1, True) in queue["acked"]


def test_lordre_dune_famille_est_garde(queue):
    queue["pending"]["jobs"] = [{"id": 1, "action": "install", "uid": "t3k:1"}, {"id": 2, "action": "patch-try"}]
    J.process(); time.sleep(0.2)
    assert queue["calls"] == [("install", 1)]                       # patch-try attend l'install
    queue["gate"].set(); assert J.drain()
    assert queue["calls"] == [("install", 1), ("patch-try", 2)]


def test_un_job_repropose_nest_pas_lance_deux_fois(queue):
    queue["pending"]["jobs"] = [{"id": 1, "action": "install", "uid": "t3k:1"}]
    J.process(); time.sleep(0.1)
    r = J.process()                                                 # golem.fm le re-propose : pas acquitté
    assert r["processed"] == 0 and r["inflight"] == 1
    queue["gate"].set(); assert J.drain()
    assert queue["calls"].count(("install", 1)) == 1 and queue["acked"] == [(1, True)]
    assert J.status()["inflight"] == []


def test_les_voies():
    assert J.lane_of("take-upload") == "sync" and J.lane_of("setlist-push") == "sync" and J.lane_of("push-catalog") == "sync"
    for a in ("install", "t3k-install", "patch-try", "preset-install", "recall", "generate-preview", None):
        assert J.lane_of(a) == "rig"


def test_un_payload_qui_porte_id_n_ecrase_pas_le_job(queue):
    """golem.fm aplatit le payload APRÈS l'enveloppe : l'`id` d'une chanson masquait celui du job (2026-10-12).
    `_job`, posé après le payload, gagne ; le handler lit toujours `id` comme l'id du contenu."""
    queue["pending"]["jobs"] = [{"id": "rs:" + "a" * 32, "_job": 7, "action": "patch-try"}]
    J.process(); assert J.drain()
    assert queue["acked"] == [(7, True)]
    assert queue["calls"] == [("patch-try", "rs:" + "a" * 32)]
    J.process(); assert J.drain()                                  # re-proposé : « en cours » par l'id du JOB
    assert queue["calls"] == [("patch-try", "rs:" + "a" * 32)] * 2 and J._inflight == set()
