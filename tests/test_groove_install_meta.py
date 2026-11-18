# SPDX-License-Identifier: GPL-3.0-or-later
"""Un groove reçu de golem.fm avec son usage, son pack et sa correspondance de notes (bridge/grooves.py install, job
`groove-install`, décidé par le mainteneur le 2026-11-18) ; et le miroir qui dit si un kit joue ici."""
import json
import os

import pytest

from bridge import grooves


def _mid(notes=(36, 38)):
    """Un fichier MIDI minimal, format 0, une piste : note on/off pour chaque note, canal 10."""
    ev = b""
    for n in notes:
        ev += bytes([0x00, 0x99, n, 100, 0x30, 0x89, n, 0])
    trk = ev + b"\x00\xff\x2f\x00"
    return b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + (96).to_bytes(2, "big") \
        + b"MTrk" + len(trk).to_bytes(4, "big") + trk


@pytest.fixture
def box(tmp_path, monkeypatch):
    d = tmp_path / "grooves"
    d.mkdir()
    monkeypatch.setattr(grooves, "GROOVES_DIR", str(d))
    monkeypatch.setattr(grooves, "ORIG_DIR", str(d / ".orig"))
    monkeypatch.setattr(grooves, "_sync_soon", lambda: None)
    for name in ("_META", "META_PATH", "INDEX"):
        if hasattr(grooves, name) and isinstance(getattr(grooves, name), str):
            monkeypatch.setattr(grooves, name, str(d / "index.json"))
    return d


def _index(box):
    try:
        return json.load(open(box / "index.json"))
    except OSError:
        return {}


def test_l_usage_le_pack_et_la_correspondance_voyagent_avec_le_fichier(box):
    raw = _mid((22, 38))
    r = grooves.install("SD3 Death Metal - Fills - 70.mid", raw, use="fill", pack="SD3 Death Metal / Fills", mapping={"22": 42})
    assert r["ok"] and r["groove"] == {"id": r["groove"]["id"], "use": "fill", "pack": "SD3 Death Metal / Fills", "remapped": True}
    gid = r["groove"]["id"]
    assert (box / ".orig" / (gid + ".mid")).read_bytes() == raw                     # l'original, à l'octet près
    played = (box / (gid + ".mid")).read_bytes()
    assert played != raw and bytes([0x99, 42, 100]) in played and bytes([0x99, 22, 100]) not in played
    e = _index(box)[gid]
    assert e["use"] == "fill" and e["pack"] == "SD3 Death Metal / Fills" and e["remap"] == {"22": 42}


def test_une_reinstallation_repart_de_zero(box):
    a, b = _mid((22, 38)), _mid((36, 44))
    gid = grooves.install("g.mid", a, use="fill", pack="P", mapping={"22": 42})["groove"]["id"]
    r = grooves.install("g.mid", b)                                                 # le même id, sans rien d'autre
    assert r["ok"] and r["groove"]["remapped"] is False and r["groove"]["use"] is None
    assert (box / (gid + ".mid")).read_bytes() == b and not (box / ".orig" / (gid + ".mid")).exists()
    assert gid not in _index(box)                                                   # ni l'ancien usage, ni l'ancienne table


def test_les_refus_se_disent_et_rien_n_est_ecrit(box):
    assert "use: one of" in grooves.install("g.mid", _mid(), use="solo")["error"]
    assert "0..127" in grooves.install("g.mid", _mid(), mapping={"22": 300})["error"]
    assert "remap" in grooves.install("g.mid", _mid(), mapping={"x": 1})["error"]
    assert "Standard MIDI" in grooves.install("g.mid", b"nope")["error"]
    assert not list(box.glob("*.mid"))


def test_le_job_passe_les_trois_champs(box, monkeypatch):
    from bridge import tones_jobs as J
    monkeypatch.setattr(J, "_blob_bytes", lambda job, tmp: _mid((22,)))
    r = J._groove_install({"action": "groove-install", "sha": "s", "name": "a b.mid", "use": "intro", "pack": "X", "remap": {"22": 36}})
    assert r["groove"]["use"] == "intro" and r["groove"]["pack"] == "X" and r["groove"]["remapped"] is True
    r = J._groove_install({"action": "groove-install", "sha": "s", "name": "plain.mid"})      # comme avant : le nom seul
    assert r["groove"]["id"] == "plain" and r["groove"]["remapped"] is False
    with pytest.raises(RuntimeError, match="use: one of"):
        J._groove_install({"action": "groove-install", "sha": "s", "name": "c.mid", "use": "nope"})


def test_le_miroir_dit_si_un_kit_joue_ici(monkeypatch):
    from bridge import engine, kits, tones_sync as TS

    class Eng:
        id = "ardour"
    monkeypatch.setattr(kits, "availability", lambda kit, inv=None: (True, None))
    monkeypatch.setattr(engine, "get", lambda: Eng())
    assert TS.kit_available({"engine": "avldrums"}) == (True, None)
    ok, why = TS.kit_available({"engine": "drumgizmo"})
    assert ok is False and "Golem Engine" in why                                    # ce moteur ne joue pas DrumGizmo
    Eng.id = "reaper"
    assert TS.kit_available({"engine": "drumgizmo"}) == (True, None)
    monkeypatch.setattr(kits, "availability", lambda kit, inv=None: (False, "its samples are not installed on this machine"))
    assert TS.kit_available({"engine": "sfz"}) == (False, "its samples are not installed on this machine")
