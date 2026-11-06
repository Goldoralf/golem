# SPDX-License-Identifier: GPL-3.0-or-later
"""La découpe d'une longue prise (bridge/takecut.py) — sans Reaper, avec de vrais WAV.

Les frontières viennent du JOURNAL (`marks[]`), pas de l'audio : c'est la décision qui porte
tout le chantier. Ce qui est vérifié ici est ce qui abîmerait de la musique — une frontière
parasite qui fabrique un morceau de trois secondes, un segment muet qui coûte un quota, une
re-découpe qui laisse des morceaux fantômes.
Lancer : .venv/bin/python -m pytest tests/test_takecut.py -q
"""
import json
import os
import struct

import pytest

from bridge import takecut, takes


def _wav(path, seconds, rate=8000, ch=1, bits=16, silent=False, time_ref=None):
    byte_rate = rate * ch * bits // 8
    n = byte_rate * seconds // 2
    data = (b"\x00\x00" if silent else b"\x00\x40") * n
    fmt = struct.pack("<HHIIHH", 1, ch, rate, byte_rate, ch * bits // 8, bits)
    chunks = b""
    if time_ref is not None:
        bext = bytearray(602)
        bext[338:346] = struct.pack("<II", time_ref & 0xFFFFFFFF, time_ref >> 32)
        chunks += b"bext" + struct.pack("<I", len(bext)) + bytes(bext)
    chunks += b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)


def _mark(sec, preset, name=None):
    return {"sec": sec, "at": "2026-09-07T20:00:00", "kind": "preset", "value": preset,
            "name": name or preset}


@pytest.fixture
def repete(tmp_path, monkeypatch):
    """Une « répète » de 180 s : trois presets, donc trois morceaux."""
    monkeypatch.setattr(takes, "RECORDINGS", str(tmp_path))
    monkeypatch.setattr(takecut, "song_of", lambda pid: (
        {"slug": "under-the-bridge", "title": "Under the Bridge"} if pid == "frusciante" else None))
    d = tmp_path / "perf-20260907-200000"
    d.mkdir()
    _wav(d / "Mix.wav", 180, time_ref=3134352000)
    _wav(d / "Input-1.wav", 180, time_ref=3134352000)
    json.dump({"kind": "take", "mode": "tracks", "started_at": "2026-09-07T20:00:00",
               "ended_at": "2026-09-07T20:03:00", "session": "sess-20260907-2000",
               "band": {"id": "b_night", "name": "Night Shift", "source": "cache"},
               "preset": "frusciante", "preset_name": "Frusciante BSSM",
               "marks": [_mark(0, "frusciante", "Frusciante BSSM"),
                         _mark(60, "clean-twin", "Clean Twin"),
                         _mark(120, "frusciante", "Frusciante BSSM")],
               "flags": [{"sec": 65.0, "by": "alex"}],
               "files": ["Mix.wav", "Input-1.wav"]}, open(d / "take.json", "w"))
    return str(d)


def _child(tmp, uid):
    return json.load(open(os.path.join(os.path.dirname(tmp), uid, "take.json")))


def test_trois_presets_font_trois_morceaux(repete):
    rep = takecut.cut("perf-20260907-200000")
    assert rep["ok"] and len(rep["uids"]) == 3
    assert rep["uids"] == ["perf-20260907-200000-01", "perf-20260907-200000-02",
                           "perf-20260907-200000-03"]


def test_le_rack_nomme_le_morceau_et_compte_les_passages(repete):
    """« Under the Bridge — take 2 » : le lien preset→chanson naît sur le rack."""
    takecut.cut("perf-20260907-200000")
    c1 = _child(repete, "perf-20260907-200000-01")
    c3 = _child(repete, "perf-20260907-200000-03")
    assert c1["title"] == "Under the Bridge" and c1["take_no"] == 1
    assert c3["title"] == "Under the Bridge — take 2" and c3["take_no"] == 2
    c2 = _child(repete, "perf-20260907-200000-02")
    assert c2["title"] == "Jam · Clean Twin" and c2["song"] is None   # vrai, pas inventé


def test_le_contrat_du_morceau(repete):
    takecut.cut("perf-20260907-200000")
    c2 = _child(repete, "perf-20260907-200000-02")
    assert c2["parent"] == "perf-20260907-200000"
    assert c2["offset_sec"] == 60.0 and c2["duration_sec"] == 60.0
    assert c2["cut"] == {"by": "preset", "at": "recall clean-twin", "confidence": "high"}
    assert c2["session"] == "sess-20260907-2000"          # la session survit à la découpe
    assert c2["band"]["id"] == "b_night"                   # le tag aussi : c'est lui qui route


def test_les_marques_sont_relatives_au_morceau(repete):
    """Une marque à 65 s de la répète est à 5 s du morceau — c'est celle-là qui a du sens."""
    takecut.cut("perf-20260907-200000")
    c2 = _child(repete, "perf-20260907-200000-02")
    assert [f["sec"] for f in c2["flags"]] == [5.0]
    assert [m["sec"] for m in c2["marks"]] == [0.0]


def test_lheure_et_lancre_suivent_loffset(repete):
    """Sinon la vidéo du téléphone se poserait au début de la répète, pour tous les morceaux."""
    takecut.cut("perf-20260907-200000")
    c2 = _child(repete, "perf-20260907-200000-02")
    assert c2["started_at"] == "2026-09-07T20:01:00"
    assert c2["bwf_time_reference"] == 3134352000 + 60 * 8000
    seg = takes.wav_info(os.path.join(os.path.dirname(repete),
                                      "perf-20260907-200000-02", "Mix.wav"))
    assert seg["time_reference"] == c2["bwf_time_reference"]   # ⚠ -c copy le PERD sans -write_bext


def test_le_parent_ne_monte_plus_mais_reste_sur_le_disque(repete):
    """La source est gardée jusqu'à validation des frontières : une marque mal placée ne doit
    jamais coûter le morceau."""
    takecut.cut("perf-20260907-200000")
    man = json.load(open(os.path.join(repete, "take.json")))
    assert man["upload"]["state"] == "cut" and man["cut"]["done"] is True
    assert os.path.isfile(os.path.join(repete, "Mix.wav"))
    from bridge import uploader
    assert "perf-20260907-200000" not in uploader.due()
    assert "perf-20260907-200000-02" in uploader.due()     # ce sont les MORCEAUX qui montent


def test_une_frontiere_parasite_est_absorbee(tmp_path, monkeypatch, repete):
    """Deux recalls à 3 s d'intervalle — on cherchait le bon son — ne font pas un morceau."""
    d = repete
    man = json.load(open(os.path.join(d, "take.json")))
    man["marks"] = [_mark(0, "a"), _mark(3, "b"), _mark(60, "c")]
    json.dump(man, open(os.path.join(d, "take.json"), "w"))
    segs = takecut.segments(man, 180)
    assert len(segs) == 2 and segs[0]["duration"] == 60.0     # « b » absorbé par « a »


def test_un_segment_muet_ne_devient_pas_un_morceau(tmp_path, monkeypatch):
    """Les 19 Go de silence du 30/07 ont coûté un ménage ; ils auraient coûté un quota."""
    monkeypatch.setattr(takes, "RECORDINGS", str(tmp_path))
    monkeypatch.setattr(takecut, "song_of", lambda pid: None)
    d = tmp_path / "perf-20260907-210000"
    d.mkdir()
    _wav(d / "Mix.wav", 120, silent=True)
    json.dump({"kind": "take", "started_at": "2026-09-07T21:00:00",
               "ended_at": "2026-09-07T21:02:00", "band": {"id": "b"},
               "marks": [_mark(0, "a"), _mark(60, "b")], "files": ["Mix.wav"]},
              open(d / "take.json", "w"))
    rep = takecut.cut("perf-20260907-210000")
    assert rep["uids"] == [] and len(rep["skipped"]) == 2
    assert all(s["reason"] == "silent" for s in rep["skipped"])


def test_une_prise_dun_seul_morceau_ne_se_decoupe_pas(repete):
    """Le REC coupé au pied entre les morceaux est le geste qu'on encourage : il n'y a alors
    rien à faire, et surtout rien à défaire."""
    man = json.load(open(os.path.join(repete, "take.json")))
    man["marks"] = [_mark(0, "frusciante")]
    json.dump(man, open(os.path.join(repete, "take.json"), "w"))
    rep = takecut.cut("perf-20260907-200000")
    assert rep["ok"] and rep["uids"] == [] and rep["reason"] == "single_song"
    assert json.load(open(os.path.join(repete, "take.json"))).get("cut") is None


def test_recut_remplace_les_morceaux_sans_laisser_de_fantome(repete):
    """La correction du web : deux gestes, fusionner et couper. Le rack re-coupe depuis la
    source — qu'il a gardée exprès."""
    takecut.cut("perf-20260907-200000")
    rep = takecut.cut("perf-20260907-200000",
                      bounds=[{"offset_sec": 0, "duration_sec": 120}])
    assert rep["uids"] == ["perf-20260907-200000-01"]
    assert not os.path.exists(os.path.join(os.path.dirname(repete), "perf-20260907-200000-03"))
    c1 = _child(repete, "perf-20260907-200000-01")
    assert c1["duration_sec"] == 120.0 and c1["cut"]["by"] == "manual"


def test_lindex_annonce_ce_qui_attend_la_decoupe(repete):
    rows = {r["uid"]: r for r in takes.index()}
    r = rows["perf-20260907-200000"]
    assert r["cut_pending"] is True and r["songs_detected"] == 3
    takecut.cut("perf-20260907-200000")
    rows = {r["uid"]: r for r in takes.index()}
    assert rows["perf-20260907-200000"]["cut_pending"] is False
    assert rows["perf-20260907-200000-02"]["parent"] == "perf-20260907-200000"


def test_la_source_se_libere_apres_validation(repete):
    """L'autre moitié de « la source reste » : sans libération, le disque se remplit
    d'originaux dont plus personne n'a besoin — et le disque mord en premier."""
    assert takecut.release_source("perf-20260907-200000")["reason"] == "not_cut"
    takecut.cut("perf-20260907-200000")
    r = takecut.release_source("perf-20260907-200000")
    assert r["ok"] and r["freed_bytes"] > 0
    assert not os.path.exists(os.path.join(repete, "Mix.wav"))
    man = json.load(open(os.path.join(repete, "take.json")))
    assert man["source_released"]["files"] == ["Input-1.wav", "Mix.wav"]
    assert man["cut"]["children"]                       # les morceaux, eux, sont intacts
    assert os.path.isfile(os.path.join(os.path.dirname(repete),
                                       "perf-20260907-200000-02", "Mix.wav"))
