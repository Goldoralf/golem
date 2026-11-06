# SPDX-License-Identifier: GPL-3.0-or-later
"""La diffusion de l'état aux écrans (bridge/app.py `_broadcast`, 2026-10-20 — « je suis coincé ») : un envoi à la
fois (les diffusions concurrentes se fondent), une erreur d'envoi écarte l'écran ET ferme sa prise (sinon la page garde
un WebSocket muet et ne se reconnecte jamais), et l'erreur est dite. `.venv/bin/python -m pytest tests/test_broadcast.py -q`"""
import asyncio

from bridge import app as A


class FakeWS:
    def __init__(self, fail=False, slow=0.0, log=None):
        self.fail, self.slow, self.log = fail, slow, log if log is not None else []
        self.sent, self.closed = [], None

    async def send_text(self, payload):
        self.log.append(("start", id(self)))
        if self.slow:
            await asyncio.sleep(self.slow)
        self.log.append(("end", id(self)))
        if self.fail:
            raise RuntimeError("Concurrent call to send() is not allowed")
        self.sent.append(payload)

    async def close(self, code=1000):
        self.closed = code


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_un_ecran_dont_l_envoi_echoue_est_ecarte_et_sa_prise_fermee(monkeypatch, caplog):
    monkeypatch.setattr(A, "_bcast", {"lock": None, "pending": False})
    monkeypatch.setattr(A.state, "snapshot", lambda: {"x": 1})
    good, bad = FakeWS(), FakeWS(fail=True)
    monkeypatch.setattr(A, "_clients", {good, bad})
    _run(A._broadcast())
    assert good.sent == ['{"x":1}'] and good in A._clients
    assert bad not in A._clients and bad.closed == 1011, "la prise se ferme : la page voit onclose et se reconnecte"
    assert any("écran écarté" in r.message for r in caplog.records)


def test_les_diffusions_concurrentes_se_fondent_et_ne_se_chevauchent_pas(monkeypatch):
    monkeypatch.setattr(A, "_bcast", {"lock": None, "pending": False})
    n = {"snap": 0}

    def snap():
        n["snap"] += 1
        return {"n": n["snap"]}
    monkeypatch.setattr(A.state, "snapshot", snap)
    log = []
    ws = FakeWS(slow=0.02, log=log)
    monkeypatch.setattr(A, "_clients", {ws})

    async def storm():
        await asyncio.gather(*(A._broadcast() for _ in range(6)))   # six demandes pendant qu'un envoi traîne
    _run(storm())
    # jamais deux envois imbriqués : les « start » et « end » alternent strictement
    assert all(log[i][0] == ("start" if i % 2 == 0 else "end") for i in range(len(log)))
    # et elles se sont fondues : un premier envoi, puis UN seul de rattrapage avec l'état le plus frais
    assert len(ws.sent) == 2 and ws.sent[-1] == '{"n":2}'


def test_un_etat_non_serialisable_est_dit_et_ne_perd_aucun_ecran(monkeypatch, caplog):
    monkeypatch.setattr(A, "_bcast", {"lock": None, "pending": False})
    monkeypatch.setattr(A.state, "snapshot", lambda: {"bad": {1, 2}})
    ws = FakeWS()
    monkeypatch.setattr(A, "_clients", {ws})
    _run(A._broadcast())
    assert ws in A._clients and ws.sent == [] and any("non sérialisable" in r.message for r in caplog.records)
