# SPDX-License-Identifier: GPL-3.0-or-later
"""Le rendu d'un bloc drums / standard (docs/preset-preview.md §8) : 8 mesures au tempo du preset, rangées là où la démo
de golem.fm les cherche — calculées et pilotées sans REAPER (le moteur est simulé)."""
import json
import os
import struct

import pytest

from bridge import config as C
from bridge import preview as P


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def _mid(path, hits, div=480, beats=4, bars=1):
    """Un .mid d'une piste : signature `beats`/4, des note-on (noire, note, vélocité), fin à `bars` mesures."""
    ev, last = [(0, b"\xff\x58\x04" + bytes([beats, 2, 24, 8]))], 0
    for q, note, vel in hits:
        ev.append((int(q * div), bytes([0x99, note, vel])))
        ev.append((int(q * div) + 10, bytes([0x89, note, 0])))
    ev.append((bars * beats * div, b"\xff\x2f\x00"))
    body = b""
    for t, data in sorted(ev, key=lambda e: e[0]):
        body += _vlq(t - last) + data
        last = t
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 0, 1, div) + b"MTrk" + struct.pack(">I", len(body)) + body)


def _notes(lines):
    return [ln.split() for ln in lines]


def test_huit_mesures_de_groove_au_tempo_du_preset(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    _mid(tmp_path / "g.mid", [(0, 36, 100), (1, 38, 90), (2, 36, 100), (3, 38, 90)])
    dur, lines = P.drum_lines({"patterns": ["g.mid"]}, bpm=120)
    n = _notes(lines)
    assert len(n) == 8 * 4                                  # le groove d'une mesure, joué huit fois
    assert dur == pytest.approx(P.MIDI_LEAD_IN + 16.0)       # 8 mesures de 4 noires à 120 = 16 s
    assert {x[3] for x in n} == {str(P.DRUMS_CHANNEL)}        # canal 10, comme golem_drums
    assert float(n[0][1]) == pytest.approx(P.MIDI_LEAD_IN)
    assert float(n[-1][1]) == pytest.approx(P.MIDI_LEAD_IN + 15.5)   # dernier temps de la 8e mesure


def test_un_groove_de_deux_mesures_et_la_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    _mid(tmp_path / "w.mid", [(0, 36, 100), (3, 38, 90)], beats=3, bars=2)      # 3/4, deux mesures
    dur, lines = P.drum_lines({"patterns": ["w.mid"]}, bpm=90)
    assert len(lines) == 4 * 2                               # 8 mesures = 4 tours du groove de deux mesures
    assert dur == pytest.approx(P.MIDI_LEAD_IN + 8 * 3 * 60 / 90)


def test_la_sequence_du_bloc_est_suivie(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    _mid(tmp_path / "a.mid", [(0, 36, 100)])
    _mid(tmp_path / "b.mid", [(0, 49, 120)])
    pm = {"patterns": ["a.mid", "b.mid"], "sequence": [{"file": "a.mid", "times": 3}, {"file": "b.mid", "times": 1}]}
    _dur, lines = P.drum_lines(pm, bpm=120)
    assert [x[4] for x in _notes(lines)] == ["36", "36", "36", "49"] * 2


def test_un_bloc_sans_groove_est_refuse():
    with pytest.raises(ValueError):
        P.drum_lines({"patterns": []}, bpm=120)


def _fake_build(events, bar=3840, total=3840 * 4, parts=None):
    def build(slug, **kw):
        assert kw["write"] is False and kw["count_in"] == 0 and kw["click_div"] == 0
        return {"render": {"events": events, "bar_ppq": bar, "len_ppq": total},
                "parts": parts or {"keys": True, "bass": True, "drums": False, "guitar": False}}
    return build


def test_le_standard_part_du_debut_et_reboucle(monkeypatch):
    from bridge import standards as S
    # une grille de 4 mesures : un accord et une basse par mesure
    ev = []
    for bar in range(4):
        t = bar * 3840
        ev += [(t, 60, 80, 0), (t + 1920, 60, 0, 0), (t, 36, 90, 1), (t + 960, 36, 0, 1)]
    monkeypatch.setattr(S, "build", _fake_build(ev))
    dur, parts = P.standard_lines({"standard": "x", "feel": "swing"}, bpm=120)
    assert dur == pytest.approx(P.MIDI_LEAD_IN + 16.0)
    assert set(parts) == {"Standard Keys", "Standard Bass"}
    keys, bass = _notes(parts["Standard Keys"]), _notes(parts["Standard Bass"])
    assert len(keys) == 8 and len(bass) == 8                 # 4 mesures jouées deux fois
    assert {k[3] for k in keys} == {"0"} and {b[3] for b in bass} == {"1"}   # canaux de golem_chordseq
    assert float(keys[4][1]) == pytest.approx(P.MIDI_LEAD_IN + 8.0)          # le 2e tour commence à la mesure 5
    assert float(keys[0][2]) - float(keys[0][1]) == pytest.approx(1.0)      # une blanche à 120


def test_une_partie_coupee_ne_se_rend_pas(monkeypatch):
    from bridge import standards as S
    ev = [(0, 60, 80, 0), (960, 60, 0, 0), (0, 36, 90, 1), (960, 36, 0, 1)]
    monkeypatch.setattr(S, "build", _fake_build(ev, parts={"keys": False, "bass": True}))
    _dur, parts = P.standard_lines({"standard": "x"}, bpm=120)
    assert set(parts) == {"Standard Bass"}


def test_les_notes_au_dela_de_8_mesures_sont_coupees(monkeypatch):
    from bridge import standards as S
    bar = 3840
    ev = [(7 * bar, 60, 80, 0), (9 * bar, 60, 0, 0), (8 * bar, 62, 80, 0), (8 * bar + 10, 62, 0, 0)]
    monkeypatch.setattr(S, "build", _fake_build(ev, total=16 * bar))
    _dur, parts = P.standard_lines({"standard": "x"}, bpm=120)
    keys = _notes(parts["Standard Keys"])
    assert len(keys) == 1                                    # la note de la 9e mesure ne joue pas
    assert float(keys[0][2]) == pytest.approx(P.MIDI_LEAD_IN + 16.0)   # la tenue s'arrête à la fin des 8 mesures


def test_l_adresse_que_cherche_la_demo(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path))
    assert P.block_dir("factory-chill-jazz", 9) == str(tmp_path / "block-factory-chill-jazz" / "9")
    assert P.block_dir("patch:factory-guitar-jazz-clean", "10") == str(tmp_path / "block-patch-factory-guitar-jazz-clean" / "10")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Un preset avec un bloc drums au switch 10, un moteur simulé qui « rend » un WAV."""
    from bridge import drums as D, store
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path / "library" / "previews"))
    monkeypatch.setattr(C, "PREVIEW_FILE", str(tmp_path / ".preview.json"))
    monkeypatch.setattr(C, "DRUMS_FILE", str(tmp_path / ".drums.json"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    _mid(tmp_path / "g.mid", [(0, 36, 100), (2, 38, 90)])
    blk = {"id": "drums", "type": "drums", "foot": 10, "params": {"patterns": ["g.mid"], "kit": "drums-black-pearl"}}
    preset = {"id": "demo", "bpm": 100, "config": {"lane": {"blocks": [blk]}}}
    monkeypatch.setattr(store, "load_preset", lambda pid: preset if pid == "demo" else None)
    monkeypatch.setattr(store, "all_blocks", lambda p: [(blk, "lane")])
    monkeypatch.setattr(D, "switches", lambda p: {10: {"block": "drums"}})
    monkeypatch.setattr(D, "resolve_mix", lambda kit, pm: {})
    sent = []

    def write_command(cmd):
        sent.append(cmd)
        if cmd["action"] == "preview":
            assert os.path.isfile(cmd["midis"].split("|")[0])      # les notes sont écrites AVANT la commande
            with open(cmd["out"], "wb") as f:
                f.write(b"RIFF")
    monkeypatch.setattr(P, "write_command", write_command)
    monkeypatch.setattr(P, "_poll_scene", lambda seq, scene, timeout: sent[-1]["out"])
    monkeypatch.setattr(P, "_peak_db", lambda wav, **kw: -6.0)
    monkeypatch.setattr(P, "_clip_duration", lambda f: 12.0)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)

    def encode(wav, opus, start=0.0):
        with open(opus, "wb") as f:
            f.write(b"OggS")
        return True
    monkeypatch.setattr(P, "_encode_opus", encode)
    return {"sent": sent, "preset": preset, "blk": blk, "tmp": tmp_path}


def test_un_rendu_de_bloc_de_bout_en_bout(rig):
    r = P.render_block("demo", 10, "drums", seq=7)
    assert r["status"] == "rendered" and r["file"] == "library/previews/block-demo/10/drums.opus"
    load, render = rig["sent"]
    assert load == {"action": "drums", "op": "load", "block": "drums", "kit": "drums-black-pearl"}
    assert render["chains"] == "Drums" and render["strip"] == "drumseq" and render["scene"] == "block-10-drums"
    d = rig["tmp"] / "library" / "previews" / "block-demo" / "10"
    meta = json.loads((d / "drums.json").read_text())
    assert meta["bars"] == 8 and meta["bpm"] == 100 and meta["switch"] == 10 and meta["kind"] == "drums"
    assert sorted(os.listdir(d)) == ["drums.json", "drums.opus"]       # ni WAV ni notes laissés derrière
    # GET /api/presets le dit : c'est par là que l'instantané de la démo trouve le clip
    assert P.block_previews("demo")["10"]["drums"]["file"] == r["file"]


def test_un_rendu_a_jour_est_saute_et_un_reglage_change_le_refait(rig):
    assert P.render_block("demo", 10, "drums", seq=1)["status"] == "rendered"
    assert P.render_block("demo", 10, "drums", seq=2) == {"status": "skipped", "reason": "up to date"}
    rig["preset"]["bpm"] = 110
    assert P.render_block("demo", 10, "drums", seq=3)["status"] == "rendered"


def test_un_clip_muet_se_refait_une_fois(rig, monkeypatch):
    peaks, windows = iter([-90.0, -8.0]), []

    def peak(wav, start=None, dur=None):
        windows.append((start, dur))
        return next(peaks)
    monkeypatch.setattr(P, "_peak_db", peak)
    assert P.render_block("demo", 10, "drums", seq=1)["status"] == "rendered"
    kinds = [c["action"] for c in rig["sent"]]
    assert kinds == ["drums", "preview", "drums", "preview"]
    assert rig["sent"][3]["settle"] == 2 * rig["sent"][1]["settle"]
    # la crête se juge sur la 1re mesure (4 noires à 100 BPM = 2,4 s), après l'avance du MIDI
    assert windows[0] == (P.MIDI_LEAD_IN, pytest.approx(2.4))


def test_muet_deux_fois_ce_n_est_pas_un_rendu(rig, monkeypatch):
    monkeypatch.setattr(P, "_peak_db", lambda wav, **kw: -90.0)
    r = P.render_block("demo", 10, "drums", seq=1)
    assert r["status"] == "failed" and "silent" in r["reason"]
    assert not os.path.exists(rig["tmp"] / "library" / "previews" / "block-demo" / "10" / "drums.opus")


@pytest.mark.parametrize("fname,body", [(".drums.json", {"present": True, "blocks": {"drums": {"playing": True}}}),
                                        (".standard.json", {"playing": True})])
def test_jamais_pendant_qu_une_batterie_ou_une_grille_joue(rig, fname, body):
    (rig["tmp"] / fname).write_text(json.dumps(body))
    r = P.render_block("demo", 10, "drums", seq=1)
    assert r["status"] == "skipped" and "playing" in r["reason"]
    assert rig["sent"] == []                                 # pas même le « load » : il toucherait la piste vivante


def test_pas_de_bloc_sur_ce_switch(rig):
    assert P.render_block("demo", 9, "drums", seq=1)["status"] == "skipped"
    assert P.render_block("demo", 10, "arrangement", seq=1)["status"] == "skipped"
    assert rig["sent"] == []
