# SPDX-License-Identifier: GPL-3.0-or-later
"""Un trou court de la télémétrie audio n'est pas une carte débranchée (2026-11-19).

Pendant le rendu des démos sous Windows, REAPER bloque son thread principal 3 à 6 s : le fichier écrit
par golem_desktop_audio.lua vieillit au-delà de 6 s, `actual` est vide, et le bandeau « No sound card »
clignotait alors que la Volt jouait. Un silence plus long reste « scripts muets »."""
import asyncio

import pytest

from bridge import desktop_audio, monitors
from bridge.state import state

VOLT = {"MODE": "ASIO", "IDENT_IN": "ASIO Universal Audio Volt", "IDENT_OUT": "ASIO Universal Audio Volt"}


class _Stop(BaseException):
    # BaseException : la boucle rattrape toute Exception de settings() et réessaie
    pass


def _run(monkeypatch, actuals):
    """Fait tourner _poll_cards sur une suite de lectures `actual` ; rend state.cards après chacune."""
    seen, feed = [], iter(actuals)
    monkeypatch.setattr(monitors.sys, "platform", "win32")
    monkeypatch.setattr(state, "reaper_connected", True)
    monkeypatch.setattr(state, "cards", None, raising=False)

    def settings():
        try:
            return {"driver": "Universal Audio Volt", "actual": next(feed)}
        except StopIteration:
            raise _Stop from None

    async def sleep(_s):
        seen.append(dict(state.cards or {}))

    async def broadcast():
        return None

    monkeypatch.setattr(desktop_audio, "settings", settings)
    monkeypatch.setattr(monitors.asyncio, "sleep", sleep)
    monkeypatch.setattr(monitors, "_broadcast", broadcast)
    with pytest.raises(_Stop):
        asyncio.run(monitors._poll_cards())
    return seen


def test_a_short_telemetry_gap_keeps_the_card_present(monkeypatch):
    seen = _run(monkeypatch, [VOLT, None, None, VOLT])
    assert [s["active_present"] for s in seen] == [True, True, True, True]
    assert not any(s["scripts_stalled"] for s in seen)


def test_before_reaper_first_speaks_the_card_is_unknown_not_missing(monkeypatch):
    """Au démarrage la boucle passe avant la première télémétrie : l'écran de chargement s'effaçait sur « No sound card »."""
    seen = _run(monkeypatch, [None, None, VOLT])
    assert [s["active_present"] for s in seen] == [None, None, True]


def test_a_long_silence_says_scripts_stopped_not_card_missing(monkeypatch):
    seen = _run(monkeypatch, [VOLT, None, None, None])
    assert seen[-1]["scripts_stalled"] is True
    assert seen[-1]["active_present"] is None


def test_a_card_reaper_did_not_open_is_still_missing(monkeypatch):
    other = {**VOLT, "IDENT_IN": "ASIO4ALL v2", "IDENT_OUT": "ASIO4ALL v2"}
    seen = _run(monkeypatch, [other, None])
    assert [s["active_present"] for s in seen] == [False, False]
