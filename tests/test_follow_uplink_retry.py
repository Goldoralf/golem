# SPDX-License-Identifier: GPL-3.0-or-later
"""L'uplink golem.fm ne se reconnecte jamais en rafale (2026-11-03 : 1 220 connexions en 5 min). Fermeture propre
immédiate → backoff croissant ; 4409 (une autre connexion de ce golem a pris le lien) → motif dit, essai lent."""
import asyncio
import sys
import types

import pytest

from bridge import follow_uplink as fu
from bridge import golemfm


class _Stop(BaseException):   # pas attrapée par le « except Exception » de la boucle
    pass


class _WS:
    """Un lien que le serveur ferme aussitôt, proprement (code 1000)."""
    close_code, close_reason = 1000, ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _run(monkeypatch, connect, n_sleeps):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= n_sleeps:
            raise _Stop

    async def idle_sender(*a):
        await asyncio.Event().wait()

    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://fm.example", "tok"))
    monkeypatch.setattr(fu, "_sender", idle_sender)
    monkeypatch.setattr(fu.asyncio, "sleep", fake_sleep)
    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=connect))
    with pytest.raises(_Stop):
        asyncio.run(fu.run())
    return sleeps


def test_fermeture_propre_immediate_attend_de_plus_en_plus(monkeypatch):
    sleeps = _run(monkeypatch, lambda *a, **k: _WS(), 5)
    assert sleeps == [1, 2, 4, 8, 10]
    assert fu.LINKED["ok"] is False


def test_4409_remplace_attend_longtemps_et_le_dit(monkeypatch):
    class Closed(Exception):
        rcvd = types.SimpleNamespace(code=fu.UPLINK_REPLACED)

    def connect(*a, **k):
        raise Closed("replaced by another connection of this golem")

    sleeps = _run(monkeypatch, connect, 2)
    assert sleeps == [fu.REPLACED_RETRY_S, fu.REPLACED_RETRY_S]
    assert fu.REPLACED_RETRY_S >= 60
    assert "another connection of this golem" in fu.LINKED["why"]
