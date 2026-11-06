# SPDX-License-Identifier: GPL-3.0-or-later
"""Un second changement audio pendant que REAPER redémarre pour le premier (2026-10-18, un testeur Windows) : le
message DIT où en est le changement en cours, au lieu d'un « already in progress » qui ressemblait à une panne."""
import time

import pytest

from bridge import desktop_audio as DA


def test_le_message_dit_ou_en_est_le_changement_en_cours(monkeypatch):
    assert DA._lock.acquire(blocking=False)
    try:
        monkeypatch.setattr(DA, "_status", {"phase": "waiting_for_reaper", "error": None})
        monkeypatch.setattr(DA, "_started", time.time() - 42)
        assert DA.status()["busy"] is True
        with pytest.raises(RuntimeError) as e:
            DA.start_apply({})
        msg = str(e.value)
        assert "waiting for REAPER to close" in msg and "42 s" in msg and "try again" in msg
    finally:
        DA._lock.release()
    assert DA.status()["busy"] is False


def _actual(bsize, rate, inp, out, ident="ASIO Focusrite USB ASIO"):
    return {"MODE": "ASIO", "IDENT_IN": ident, "BSIZE": str(bsize), "SRATE": str(rate),
            "INPUT_LATENCY_SAMPLES": str(inp), "OUTPUT_LATENCY_SAMPLES": str(out)}


def test_un_pilote_qui_garde_son_buffer_est_signale(monkeypatch):
    monkeypatch.setattr(DA.sys, "platform", "win32")
    # le cas du testeur : buffer 192 demandé à 48 kHz (~8 ms attendus), le pilote déclare 40 ms
    got = DA.driver_override(_actual(192, 48000, 960, 960))
    assert got == {"reported_ms": 40.0, "expected_ms": 8.0, "driver": "Focusrite USB ASIO"}


def test_un_pilote_honnete_ne_declenche_rien(monkeypatch):
    monkeypatch.setattr(DA.sys, "platform", "win32")
    assert DA.driver_override(_actual(128, 48000, 200, 230)) is None        # ~9 ms pour 5,3 ms nominaux : normal
    assert DA.driver_override({"BSIZE": "128", "SRATE": "48000"}) is None   # rien de déclaré : rien à dire


def test_core_audio_n_a_pas_de_panneau_de_pilote(monkeypatch):
    # MacBook Air, micro + haut-parleurs intégrés : 71 ms déclarés à 256 — l'écran conseillait Focusrite Control / ASIO
    monkeypatch.setattr(DA.sys, "platform", "darwin")
    assert DA.driver_override({"MODE": "CoreAudio", "IDENT_IN": "CoreAudio Microphone MacBook Air", "BSIZE": "256",
                               "SRATE": "48000", "INPUT_LATENCY_SAMPLES": "1809", "OUTPUT_LATENCY_SAMPLES": "1620"}) is None
