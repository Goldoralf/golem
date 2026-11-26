# SPDX-License-Identifier: GPL-3.0-or-later
"""L'instrument de chaque entrée guitare/basse dans take.json (docs/transcription.md §4) : l'accordage en MIDI de la
grave à l'aiguë, d'où il vient (riff → tuner → profile → default), le capo dit ou null — rien de deviné en silence."""
import json

from bridge import guitars, store

INPUTS = [{"ch": 1, "role": "guitar", "nth": 1}, {"ch": 2, "role": "bass", "nth": 1}, {"ch": 3, "role": "voice", "nth": 1}]


def _calib(tmp_path, doc):
    p = tmp_path / "string-calib.json"
    p.write_text(json.dumps(doc))
    return str(p)


def test_sans_rien_de_dit_tout_est_default(tmp_path):
    out = guitars.instruments_of(INPUTS, None, None, path=_calib(tmp_path, {}))
    assert set(out) == {"1", "2"}                                        # la voix n'a pas d'entrée
    g, b = out["1"], out["2"]
    assert g["tuning"] == [40, 45, 50, 55, 59, 64] and g["source"] == "default" and g["guitar"] is None
    assert g["tuning_id"] == "6-std" and g["capo"] is None and g["strings"] == 6
    assert b["tuning"] == [28, 33, 38, 43] and b["source"] == "default" and b["frets"] == 20


def test_le_profil_qui_declare_son_accordage(tmp_path):
    path = _calib(tmp_path, {"active": "eight", "eight": {"name": "Eight", "tuning": [64, 30, 35, 40, 45, 50, 55, 59],
                                                           "frets": 24}})
    g = guitars.instruments_of(INPUTS[:1], None, 2, path=path)["1"]
    assert g["tuning"] == [30, 35, 40, 45, 50, 55, 59, 64] and g["source"] == "profile"   # trié, grave d'abord
    assert g["guitar"] == {"id": "eight", "name": "Eight"} and g["frets"] == 24 and g["capo"] == 2
    assert g["tuning_id"] == "8-std"


def test_le_tuner_de_la_lane_passe_avant_le_profil(tmp_path, monkeypatch):
    path = _calib(tmp_path, {"active": "six", "six": {"name": "Six", "tuning": [40, 45, 50, 55, 59, 64]}})
    preset = {"id": "p", "lanes": [{"id": "g1", "in_role": "guitar", "in_nth": 1,
                                    "chain": {"pre": [{"id": "t", "type": "tuner", "params": {"tuning": "drop-d"}}]}}]}
    monkeypatch.setattr(store, "is_v2", lambda p: True)
    monkeypatch.setattr(store, "lanes_of", lambda p: p["lanes"])
    monkeypatch.setattr(store, "all_blocks", lambda p: iter([(p["lanes"][0]["chain"]["pre"][0], "g1")]))
    g = guitars.instruments_of(INPUTS[:1], preset, None, path=path)["1"]
    assert g["tuning"] == [38, 45, 50, 55, 59, 64] and g["source"] == "tuner" and g["tuning_id"] == "drop-d"
    assert g["guitar"] is None                                             # aucun profil n'a cet accordage


def test_l_accordage_du_riff_l_emporte(tmp_path):
    path = _calib(tmp_path, {})
    ins = guitars.instruments_of(INPUTS, None, None, path=path)
    guitars.apply_riff_tuning(ins, [42, 47, 52, 57, 61, 66], path=path)
    assert ins["1"]["source"] == "riff" and ins["1"]["tuning"] == [42, 47, 52, 57, 61, 66]
    assert ins["2"]["source"] == "default"                                 # la basse ne prend pas l'accordage du riff
    assert guitars.apply_riff_tuning(ins, "drop-d") is ins and ins["1"]["source"] == "riff"   # pas du MIDI : ignoré
