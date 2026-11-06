# SPDX-License-Identifier: GPL-3.0-or-later
"""Index des prises + retag partiel (bridge/takes.py) — sans Reaper, sans serveur.
Lancer : .venv/bin/python -m pytest tests/test_takes.py -q"""
import json
import os
import struct

import pytest

from bridge import takes


def _wav(path, seconds=3, rate=48000, ch=1, bits=24, bext=False):
    """WAV minimal (BWF optionnel : chunk `bext` AVANT `fmt `, comme Reaper avec l'horodatage)."""
    byte_rate = rate * ch * bits // 8
    data = b"\0" * (byte_rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, ch, rate, byte_rate, ch * bits // 8, bits)
    chunks = b""
    if bext:
        chunks += b"bext" + struct.pack("<I", 602) + b"\0" * 602
    chunks += b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)


@pytest.fixture
def rec(tmp_path, monkeypatch):
    monkeypatch.setattr(takes, "RECORDINGS", str(tmp_path))
    monkeypatch.setattr(takes, "_read_band", lambda: {
        "band": {"id": "night-shift", "name": "Night Shift", "source": "local-temporary"},
        "bands": [{"id": "night-shift", "name": "Night Shift"},
                  {"id": "b_haw6vqzh5u", "name": "Night Shift", "source": "cache"}]})
    # multipiste avec manifeste complet, taguée
    d = tmp_path / "perf-20260804-192024"; d.mkdir()
    _wav(d / "Input-1.wav", 2); _wav(d / "DI-Sandbox-Input-1.wav", 2)
    (d / "MIDI-Input-3.mid").write_bytes(b"MThd")
    json.dump({"kind": "take", "mode": "tracks_di", "started_at": "2026-08-04T19:20:24",
               "ended_at": "2026-08-04T19:23:19", "session": "2026-08-04T18:07:56",
               "preset_name": "Frusciante BSSM",
               "band": {"id": "night-shift", "name": "Night Shift", "source": "local-temporary"},
               "files": ["DI-Sandbox-Input-1.wav", "Input-1.wav", "MIDI-Input-3.mid"]},
              open(d / "take.json", "w"))
    # multipiste SANS manifeste (bug d'avant le 2026-08-02)
    d2 = tmp_path / "perf-20260731-100735"; d2.mkdir()
    _wav(d2 / "Input-1.wav", 5, bext=True)
    # .wav à plat, nom Reaper, sans sidecar
    _wav(tmp_path / "02-Sandbox #Input 2-260726_1807.wav", 4)
    # une prise déjà montée : hors index
    d3 = tmp_path / "perf-20260801-120000"; d3.mkdir()
    _wav(d3 / "Input-1.wav", 1)
    json.dump({"kind": "take", "started_at": "2026-08-01T12:00:00", "ended_at": "2026-08-01T12:00:01",
               "band": {"id": "night-shift"}, "upload": {"state": "done", "rec_id": 7}},
              open(d3 / "take.json", "w"))
    (tmp_path / "notes.txt").write_text("pas une prise")
    return tmp_path


def test_uid_is_stable_and_conform():
    assert takes.uid_of("perf-20260804-192024") == "perf-20260804-192024"
    u = takes.uid_of("02-Sandbox #Input 2-260726_1807.wav")
    assert u == "02-sandbox-input-2-260726_1807"
    import re
    assert re.match(r"^[a-z0-9][a-z0-9._-]{0,63}$", u)
    assert takes.uid_of("###.wav") == "take"


def test_started_at_from_names():
    assert takes.started_at_of("perf-20260804-192024") == "2026-08-04T19:20:24"
    assert takes.started_at_of("02-Sandbox #Input 2-260726_1807.wav") == "2026-07-26T18:07:00"
    assert takes.started_at_of("12-Recording-260726_1804-01.wav") == "2026-07-26T18:04:00"
    assert takes.started_at_of("perf-x", {"started_at": "2026-01-01T00:00:00"}) == "2026-01-01T00:00:00"
    assert takes.started_at_of("whatever.wav") is None


def test_wav_seconds_reads_header_only(tmp_path):
    _wav(tmp_path / "a.wav", 7)
    _wav(tmp_path / "b.wav", 9, bext=True, ch=2)
    assert takes.wav_seconds(str(tmp_path / "a.wav")) == 7
    assert takes.wav_seconds(str(tmp_path / "b.wav")) == 9
    (tmp_path / "c.wav").write_bytes(b"not a wav")
    assert takes.wav_seconds(str(tmp_path / "c.wav")) is None


def test_pending_index(rec):
    p = takes.pending()
    rows = p["pending_takes"]
    assert [r["uid"] for r in rows] == ["perf-20260804-192024", "perf-20260731-100735",
                                        "02-sandbox-input-2-260726_1807"]     # plus récentes d'abord
    assert p["pending_total"] == 3 and p["pending_bytes"] == sum(r["size_bytes"] for r in rows)
    full = rows[0]
    assert full["duration_sec"] == 175 and full["tracks"] == 3 and full["mode"] == "tracks_di"
    assert full["band"] == "night-shift" and full["band_name"] == "Night Shift"
    assert full["session"] == "2026-08-04T18:07:56" and full["preset_name"] == "Frusciante BSSM"
    assert full["upload"] == {"state": "pending"}
    orphan = rows[1]                                   # sans manifeste : dérivé du nom + en-tête WAV
    assert orphan["band"] is None and orphan["started_at"] == "2026-07-31T10:07:35"
    assert orphan["duration_sec"] == 5 and orphan["tracks"] == 1
    flat = rows[2]
    assert flat["mode"] == "mix" and flat["duration_sec"] == 4 and flat["band"] is None
    assert takes.pending(limit=1)["pending_takes"] == rows[:1]
    assert takes.pending(limit=1)["pending_total"] == 3


def test_tag_partial(rec):
    out = takes.tag([
        {"uid": "perf-20260731-100735", "band": "b_haw6vqzh5u"},          # connu (roster cache)
        {"uid": "02-sandbox-input-2-260726_1807", "band": "night-shift"},  # .wav à plat -> sidecar créé
        {"uid": "perf-20260804-192024", "band": None},                    # « Aucun »
        {"uid": "perf-nope", "band": "night-shift"},                    # inconnu : saute seul
        {"uid": "perf-20260804-192024", "band": "b_unknown"},             # groupe inconnu du rack
        "garbage",
    ])
    assert out["tagged"] == ["perf-20260731-100735", "02-sandbox-input-2-260726_1807",
                             "perf-20260804-192024"]
    reasons = {s["uid"]: s["reason"] for s in out["skipped"]}
    assert reasons["perf-nope"] == "unknown_take"
    assert reasons["perf-20260804-192024"] == "band_unknown_on_rack"
    assert reasons[None] == "malformed"
    man = json.load(open(rec / "perf-20260731-100735" / "take.json"))
    assert man["band"] == {"id": "b_haw6vqzh5u", "name": "Night Shift", "source": "cache"}
    assert man["manifest"] == "reconstructed" and man["started_at"] == "2026-07-31T10:07:35"
    side = json.load(open(rec / "02-Sandbox #Input 2-260726_1807.wav.json"))
    assert side["mode"] == "mix" and side["band"]["id"] == "night-shift"
    assert side["band"]["source"] == "local-temporary"     # le retag ne PROMEUT pas la source
    assert json.load(open(rec / "perf-20260804-192024" / "take.json"))["band"] is None
    # le reste du manifeste n'a pas bougé
    assert json.load(open(rec / "perf-20260804-192024" / "take.json"))["preset_name"] == "Frusciante BSSM"
    # et l'index reflète les tags
    by = {r["uid"]: r for r in takes.pending()["pending_takes"]}
    assert by["perf-20260731-100735"]["band"] == "b_haw6vqzh5u"
    assert by["perf-20260804-192024"]["band"] is None
