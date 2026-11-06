# SPDX-License-Identifier: GPL-3.0-or-later
"""Une prise en projet REAPER (bridge/take_rpp.py, 2026-10-11) : une piste par fichier, chemins relatifs,
tempo du manifeste, sample-rate de l'en-tête — et le .rpp écrit DANS le dossier de la prise."""
import json
import os
import wave

import pytest

from bridge import take_rpp as TR


def _wav(path, seconds=1.5, sr=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * seconds))


def test_le_texte_du_projet_une_piste_par_fichier_relatif():
    txt = TR.build_rpp(["01-guitar.wav", "02-voice.wav"], {"bpm": 112, "labels": {"01-guitar": "Guitar 1"}, "started_at": "2026-10-11T22:00:00"},
                       sample_rate=44100, lengths={"01-guitar.wav": 12.5, "02-voice.wav": 12.5}, project_name="perf-x")
    assert txt.startswith('<REAPER_PROJECT 0.1 "7.0/golem" ')
    assert "TEMPO 112 4 4" in txt and "SAMPLERATE 44100 0 0" in txt
    assert txt.count("<TRACK") == 2 and 'NAME "Guitar 1"' in txt and 'NAME "02-voice"' in txt
    assert 'FILE "01-guitar.wav"' in txt and "LENGTH 12.500000" in txt
    assert txt.rstrip().endswith(">")
    assert "TEMPO 120 4 4" in TR.build_rpp(["a.wav"], {"bpm": "huh"})       # tempo illisible : 120, jamais une erreur


def test_export_ecrit_le_rpp_dans_le_dossier_de_la_prise(monkeypatch, tmp_path):
    rec = tmp_path / "recordings"; take = rec / "perf-20261011-220000"; take.mkdir(parents=True)
    _wav(str(take / "01-guitar.wav"), 2.0, 48000); _wav(str(take / "02-voice.wav"), 2.0, 48000)
    (take / "take.json").write_text(json.dumps({"bpm": 100, "labels": {"01-guitar": "Guitar 1", "02-voice": "Voice 1"}}))
    monkeypatch.setattr(TR, "RECORDINGS", str(rec))
    out = TR.export("perf-20261011-220000")
    assert out == str(take / "perf-20261011-220000.rpp")
    txt = open(out, encoding="utf-8").read()
    assert "SAMPLERATE 48000 0 0" in txt and "TEMPO 100 4 4" in txt and 'NAME "Voice 1"' in txt
    assert "LENGTH 2.000000" in txt and 'FILE "02-voice.wav"' in txt and "recordings" not in txt   # relatif, portable
    # une prise en MIX (.wav à plat) : un projet d'une piste, à côté du fichier
    _wav(str(rec / "mix-260726_1807.wav"), 1.0, 44100)
    out2 = TR.export("mix-260726_1807.wav")
    assert out2 == str(rec / "mix-260726_1807.rpp") and "SAMPLERATE 44100 0 0" in open(out2, encoding="utf-8").read()
    with pytest.raises(ValueError):
        TR.export("../etc/passwd")
    with pytest.raises(ValueError):
        TR.export("perf-nope")
