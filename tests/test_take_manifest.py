# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que `take.json` GRAVE — le contrat avec golem.fm (message-maestrium-lot-b.md §4).

Une prise dit par-dessus quoi elle a été jouée (backing, standard, looper), qui jouait sur
quelle entrée, et à quel instant ABSOLU elle a commencé. Ces champs sont gelés au stop et
jamais réécrits : s'ils sont faux, ils sont faux pour toujours.
Lancer : .venv/bin/python -m pytest tests/test_take_manifest.py -q
"""
import json
import os
import struct

import pytest

from bridge import monitors, takes


def _bwf_wav(path, seconds=1, rate=48000, ch=2, bits=24, time_ref=3134352000):
    """WAV avec chunk `bext` (comme Reaper) : c'est `time_reference` qui aligne les lanes."""
    byte_rate = rate * ch * bits // 8
    data = b"\0" * (byte_rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, ch, rate, byte_rate, ch * bits // 8, bits)
    bext = bytearray(602)
    bext[338:346] = struct.pack("<II", time_ref & 0xFFFFFFFF, time_ref >> 32)
    chunks = b"bext" + struct.pack("<I", len(bext)) + bytes(bext)
    chunks += b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)


@pytest.fixture
def prise(tmp_path, monkeypatch):
    from bridge import config as C
    from bridge.state import state
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    os.makedirs(tmp_path / "presets")
    d = tmp_path / "recordings" / "perf-20260907-140000"
    d.mkdir(parents=True)
    _bwf_wav(d / "Input-1.wav")
    _bwf_wav(d / "Mix.wav")
    monkeypatch.setattr(state, "preset_id", "frusciante-bssm", raising=False)
    monkeypatch.setattr(state, "preset_name", "Frusciante BSSM", raising=False)
    monkeypatch.setattr(state, "scene_id", "verse", raising=False)
    monkeypatch.setattr(state, "inputmap", {"inputs": [
        {"ch": "1", "role": "guitar", "label": "Guitar", "person": "alex"},
        {"ch": "2", "role": "voice", "label": "Voice", "person": "smith"},
        {"ch": "3", "role": "bass", "label": "Bass"}]}, raising=False)
    monkeypatch.setattr(state, "mode", {"id": "rehearsal", "name": "Rehearsal"}, raising=False)
    monkeypatch.setattr(monitors, "stamp_bwf", lambda *a, **k: True)   # le WAV a déjà son bext
    monitors.PERF_CTX.clear(); monitors.PERF_MARKS.clear(); monitors.PERF_FLAGS.clear()
    return {"file": os.path.join("recordings", "perf-20260907-140000"),
            "started_at": "2026-09-07T14:00:00"}, str(d)


def _man(d):
    return json.load(open(os.path.join(d, "take.json")))


def test_le_standard_est_le_miroir_du_backing(prise):
    cur, d = prise
    monitors.PERF_CTX["standard"] = {"id": "blue-bossa", "title": "Blue Bossa",
                                     "played": True, "bars": 32}
    monitors._take_manifest(cur)
    assert _man(d)["standard"] == {"id": "blue-bossa", "title": "Blue Bossa",
                                   "played": True, "bars": 32}


def test_le_looper_dit_lesquelles_ont_tourne(prise):
    cur, d = prise
    monitors.PERF_CTX["looper"] = {"active": True, "loops": ["Rhythm", "Lead"]}
    monitors._take_manifest(cur)
    assert _man(d)["looper"]["loops"] == ["Rhythm", "Lead"]


def test_sans_contexte_les_champs_sont_nuls_pas_absents(prise):
    """`None` dit « il n'y en avait pas » ; golem.fm en tire `source: free` sans deviner."""
    cur, d = prise
    m = (monitors._take_manifest(cur), _man(d))[1]
    assert m["standard"] is None and m["looper"] is None and m["backing"] is None


def test_qui_jouait_sur_quelle_entree(prise):
    """`people` est PARALLÈLE à `roles` : les libellés restent des chaînes, lisibles par les
    89 prises déjà sur le disque et par routes_content._labels."""
    cur, d = prise
    monitors._take_manifest(cur)
    m = _man(d)
    assert m["people"] == {"1": "alex", "2": "smith"}      # l'entrée 3 n'a personne : absente
    assert m["roles"]["1"] == "Guitar" and isinstance(m["roles"]["1"], str)


def test_lheure_absolue_sans_toucher_a_lheure_de_la_salle(prise):
    """`started_at` reste NAÏVE — c'est ce qu'on lit au mur. L'instant absolu vit à côté."""
    import time as t
    cur, d = prise
    monitors._take_manifest(cur)
    m = _man(d)
    assert m["started_at"] == "2026-09-07T14:00:00"        # intacte
    attendu = int(t.mktime(t.strptime("2026-09-07T14:00:00", "%Y-%m-%dT%H:%M:%S")) * 1000)
    assert m["started_epoch_ms"] == attendu
    assert m["started_at_utc"].endswith("Z")


def test_lancre_dechantillon_et_la_frequence(prise):
    """`bwf_time_reference` aligne les lanes entre elles — et la vidéo sur la timeline du web."""
    cur, d = prise
    monitors._take_manifest(cur)
    m = _man(d)
    assert m["bwf_time_reference"] == 3134352000
    assert m["sample_rate"] == 48000


def test_le_mode_machine_remonte_dans_lindex(prise, monkeypatch):
    cur, d = prise
    monitors._take_manifest(cur)
    monkeypatch.setattr(takes, "RECORDINGS", os.path.dirname(d))
    row = takes.index()[0]
    assert row["machine_mode"] == "rehearsal"


def test_la_prise_dit_ce_quelle_est(prise, monkeypatch):
    """`kind` gravé au REC depuis le mode : Rehearsal → rehearsal, Gig → gig, Show → show (2026-09-08)."""
    from bridge.state import state
    cur, d = prise
    monitors._take_manifest(cur)
    assert _man(d)["kind"] == "rehearsal"
    monkeypatch.setattr(state, "mode", {"id": "gig", "name": "Gig", "take_kind": "gig"}, raising=False)
    monitors._take_manifest(cur)
    assert _man(d)["kind"] == "gig"
    monkeypatch.setattr(state, "mode", {"id": "show", "name": "Show"}, raising=False)   # sans le champ : la règle par l'id
    monitors._take_manifest(cur)
    assert _man(d)["kind"] == "show"


def test_une_prise_davant_derive_son_kind_du_mode(prise, monkeypatch):
    cur, d = prise
    monitors._take_manifest(cur)
    m = _man(d); m.pop("kind"); m["machine_mode"] = "gig"
    json.dump(m, open(os.path.join(d, "take.json"), "w"))
    monkeypatch.setattr(takes, "RECORDINGS", os.path.dirname(d))
    assert takes.index()[0]["kind"] == "gig"
