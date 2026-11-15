# SPDX-License-Identifier: GPL-3.0-or-later
"""Library ▸ Drums (docs/drums-library.md, 2026-11-14) : lire un groove de toute forme, son usage, une note inconnue
associée à une pièce, le dessin d'un kit, l'état de ses démos, l'écoute d'un groove sur un kit."""
import json
import struct

import pytest

from bridge import drum_preview as D
from bridge import grooves as G


def _vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def smf(hits, end_tick, ppq=480, sig=(4, 2), bpm=None, ch=9):
    """hits = [(tick, note)] ; la fin de piste tombe à end_tick (un silence final reste une mesure)."""
    ev = [(0, b"\xff\x58\x04" + bytes([sig[0], sig[1], 24, 8]))]
    if bpm:
        ev.append((0, b"\xff\x51\x03" + struct.pack(">I", int(60e6 / bpm))[1:]))
    for t, n in hits:
        ev += [(t, bytes([0x90 | ch, n, 100])), (t + 10, bytes([0x80 | ch, n, 0]))]
    ev.sort(key=lambda e: e[0])
    trk, last = b"", 0
    for t, m in ev:
        trk += _vlq(t - last) + m
        last = t
    trk += _vlq(end_tick - last) + b"\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(trk)) + trk


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "GROOVES_DIR", str(tmp_path))
    monkeypatch.setattr(G, "_META", str(tmp_path / "index.json"))
    monkeypatch.setattr(G, "ORIG_DIR", str(tmp_path / ".orig"))
    return tmp_path


def test_the_length_comes_from_the_meter_and_the_end_of_track(lib):
    # une mesure de 4/4 dont la fin est un silence : 1 mesure, pas « ce que touche la dernière frappe »
    p = lib / "one.mid"
    p.write_bytes(smf([(0, 36), (480, 38)], end_tick=1920))
    a = G.analyze(str(p))
    assert (a["meter"], a["bars"], a["played"], a["unknown"]) == ("4/4", 1, False, [])
    # 6/8 : la mesure fait trois noires ; deux mesures
    q = lib / "six.mid"
    q.write_bytes(smf([(0, 36), (240 * 3, 38), (1440, 36)], end_tick=2880, sig=(6, 3), bpm=60))
    a = G.analyze(str(q))
    assert (a["meter"], a["bars"], a["bpm"]) == ("6/8", 2, 60.0)


def test_a_played_groove_and_an_unknown_note_are_said(lib):
    p = lib / "var.mid"
    hits = [(i * 480 + (37 if i % 2 else 0), 36) for i in range(16)] + [(i * 480 + 45, 60) for i in range(16)]
    p.write_bytes(smf(hits, end_tick=7680, bpm=206))
    a = G.analyze(str(p))
    assert a["played"] and a["unknown"] == [60] and a["bpm"] == 206.0 and a["bars"] == 4
    assert G.guess_use("variation_03", dict(a, bars=8)) == "oneshot"
    assert G.guess_use("rock-fill", a) == "fill" and G.guess_use("rock-verse", dict(a, played=False)) == "loop"


def test_an_unknown_note_is_remapped_in_the_file_and_the_original_comes_back(lib):
    p = lib / "var.mid"
    raw = smf([(0, 36), (480, 60), (960, 60)], end_tick=1920)
    p.write_bytes(raw)
    assert G.remap("var", {60: 51})["ok"]
    a = G.analyze(str(p))
    assert a["voices"] == {36: 1, 51: 2} and a["unknown"] == []
    assert (lib / ".orig" / "var.mid").read_bytes() == raw
    assert G._read_meta()["var"]["remap"] == {"60": 51}
    assert G.remap("var", {})["ok"]
    assert p.read_bytes() == raw and "remap" not in G._read_meta()["var"]
    G.delete_groove("var")
    assert not (lib / ".orig" / "var.mid").exists()


def test_the_use_of_a_groove_is_kept_and_checked(lib):
    (lib / "g.mid").write_bytes(smf([(0, 36)], end_tick=1920))
    assert G.set_use("g", "fill")["ok"] and G._read_meta()["g"]["use"] == "fill"
    assert not G.set_use("g", "verse")["ok"]
    assert not G.set_use("nope", "loop")["ok"]
    assert [x["use"] for x in G.list_grooves()] == ["fill"]


def test_a_factory_groove_is_never_remapped(lib):
    (lib / "f.mid").write_bytes(smf([(0, 60)], end_tick=1920))
    G._write_meta({"f": {"factory": True}})
    assert not G.remap("f", {60: 51})["ok"]


def test_each_kit_gets_a_drawing_type():
    t = D.kit_type
    assert t({"name": "Aasimonster", "hint": "metal · multi-mic", "role": "drum"}) == "metal"
    assert t({"name": "Blonde Bop", "hint": "jazz · brushes", "role": "drum"}) == "jazz"
    assert t({"name": "Black Pearl", "hint": "rock · ambient", "role": "drum"}) == "vintage"
    assert t({"name": "Red Zeppelin", "hint": "rock · dry", "role": "drum"}) == "rock"   # pas la même photo que Black Pearl
    assert t({"name": "Hybrid r15 MegaKit", "hint": "", "role": "drum"}) == "hybrid"
    assert t({"name": "Studio", "hint": "rock", "role": "drum"}) == "rock"
    assert t({"name": "Trap", "role": "pad", "engine": "rs5k"}) == "pads"


def test_a_short_groove_is_looped_to_four_bars_a_long_one_plays_once(lib):
    p = lib / "one.mid"
    p.write_bytes(smf([(0, 36), (960, 38)], end_tick=1920))
    dur, lines = D.groove_lines(str(p), 120)
    assert len(lines) == 8                                      # 2 frappes × 4 mesures
    from bridge import preview as PV
    assert abs(dur - (PV.MIDI_LEAD_IN + 4 * 4 * 0.5)) < 1e-6        # 4 mesures de 4 noires à 120 BPM
    q = lib / "long.mid"
    q.write_bytes(smf([(i * 1920, 36) for i in range(8)], end_tick=8 * 1920))
    assert len(D.groove_lines(str(q), 120)[1]) == 8


def test_a_kit_demo_is_pending_until_rendered_and_after_its_phrase_changes(monkeypatch, tmp_path):
    from bridge import config as C
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path))
    monkeypatch.setattr(C, "ROOT", "/")
    k = {"id": "drums-x", "role": "drum", "engine": "avldrums", "bank": "x"}
    assert D.demo(k)["status"] == "pending"
    ref = tmp_path / "rock.mid"
    ref.write_bytes(b"v1")
    monkeypatch.setattr(D, "REFS", ("drums/rock",))
    monkeypatch.setattr(D, "_ref_path", lambda r: str(ref))
    d = tmp_path / "kit-drums-x"
    d.mkdir()
    clip = d / "rock.opus"
    clip.write_bytes(b"x")
    import json
    (d / "preview.json").write_text(json.dumps({"fingerprint": D._kit_fp(k), "clips": {"drums/rock": {
        "file": str(clip), "seconds": 9.0, "ref_sha": D._sha(str(ref))}}}))
    assert D.demo(k)["status"] == "ready"
    ref.write_bytes(b"v2 - a new demo phrase")                  # on peut changer les phrases de démo : le clip est à refaire
    assert D.demo(k)["status"] == "pending"
    assert D.demo({"id": "pads-x", "role": "pad", "engine": "rs5k"})["status"] == "none"


def test_a_kit_card_for_golem_fm_says_what_a_drummer_cares_about():
    pads = D.kit_card({"id": "pads-x", "role": "pad", "engine": "rs5k",
                       "pads": [{"note": 36, "sample": "assets/samples/kits/x/01_kick.wav"},
                                {"note": 38, "sample": "assets/samples/kits/x/03_snare.wav"}, {"note": 42}],
                       "source": {"by": "drumsynth (synthèse, ~/code/drumsynth)", "licence": "own — synthesized"}})
    assert pads["type"] == "pads" and pads["samples"] == 2
    assert pads["pads"] == [{"pad": 1, "note": 36, "label": "kick", "sample": "01_kick.wav"},
                            {"pad": 2, "note": 38, "label": "snare", "sample": "03_snare.wav"}]
    assert "~" not in json.dumps(pads) and "synthèse" not in json.dumps(pads)   # une note interne ne part pas telle quelle
    kit = D.kit_card({"id": "drums-aasimonster", "role": "drum", "engine": "drumgizmo", "hint": "metal",
                      "notes": {"kick": 36, "snare": 38}, "mix": [{"name": "OHL", "group": "oh", "gain": 0}]})
    assert kit["type"] == "metal" and kit["pieces"] == ["kick", "snare"] and kit["mics"] == [{"name": "OHL", "group": "oh"}]
    assert kit["credit"]["licence"] == "CC BY 4.0"
    avl = D.kit_card({"id": "drums-x", "role": "drum", "engine": "avldrums", "bank": "x"})
    assert avl["credit"] == {"source": "avldrums.lv2 (AVL Drumkits)"}                # pas de licence inventée


def test_new_samples_in_a_pad_kit_change_its_fingerprint(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    (tmp_path / "a.wav").write_bytes(b"v1")
    k = {"engine": "rs5k", "pads": [{"note": 36, "sample": "a.wav", "mode": "oneshot", "level": 0}]}
    before = D._kit_fp(k)
    (tmp_path / "a.wav").write_bytes(b"v2, a less metallic kick")
    assert D._kit_fp(k) != before
