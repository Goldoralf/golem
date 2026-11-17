# SPDX-License-Identifier: GPL-3.0-or-later
"""La banque de la boîte à rythmes du Golem Engine (bridge/engine/drum_bank.py, docs/ardour-plan.md §7d lot 3) : les
grooves dépliés comme golem_drums.lua les lit, le plugin du kit, et le `play` que l'adaptateur complète."""
import json
import os

import pytest

from bridge.engine import ardour as A
from bridge.engine import drum_bank as D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def smf(track, division=480):
    return b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big") + division.to_bytes(2, "big") \
        + b"MTrk" + len(track).to_bytes(4, "big") + track


def test_un_groove_est_deplie_a_960_ticks_et_arrondi_a_la_mesure():
    track = bytes([0, 0xFF, 0x58, 4, 3, 2, 24, 8,            # chiffrage 3/4
                   0, 0x99, 36, 100,                          # grosse caisse au tick 0
                   0x83, 0x60, 38, 90,                        # +480 (une noire) : caisse claire, statut courant
                   0x83, 0x60, 0x89, 38, 0,                   # un note-off : ignoré
                   0x87, 0x40, 0x99, 42, 0,                   # +960 : note-on vélocité 0 = un note-off, ignoré
                   0, 0xFF, 0x2F, 0])
    s = D.parse_midi(smf(track))
    assert s["bar"] == 3 * 960 and s["events"] == [[0, 36, 100], [960, 38, 90]]
    assert s["len"] == 2 * s["bar"]                            # 4 noires jouées : arrondi à la mesure SUPÉRIEURE
    with pytest.raises(ValueError):
        D.parse_midi(b"RIFF....")
    with pytest.raises(ValueError):
        D.parse_midi(smf(b"", division=0x8000 | 25))           # division SMPTE


def test_un_kit_non_gm_recoit_les_grooves_traduits():
    slot = {"len": 3840, "bar": 3840, "events": [[0, 36, 100], [480, 42, 80], [960, 51, 70]]}
    out = D.apply_notemap(slot, {"36": 35, "42": -1})
    assert out["events"] == [[0, 35, 100], [960, 51, 70]]      # traduite, tue, inchangée
    assert D.apply_notemap(slot, None) is slot


def test_la_banque_d_un_play(tmp_path):
    (tmp_path / "a.mid").write_bytes(smf(bytes([0, 0x99, 36, 100, 0, 0xFF, 0x2F, 0])))
    b, skipped = D.bank(str(tmp_path), ["a.mid", "absent.mid"], ["a.mid"])
    assert b["ppq"] == 960 and b["patterns"] == 2 and [len(s["events"]) for s in b["slots"]] == [1, 0, 1]
    assert b["slots"][1] == D.silent_slot() and len(skipped) == 1 and skipped[0].startswith("absent.mid")
    many, skipped = D.bank(str(tmp_path), ["a.mid"] * 20, [])
    assert len(many["slots"]) == D.MAX_SLOTS and "beyond" in skipped[-1]


def test_les_grooves_d_usine_se_lisent():
    import glob
    files = glob.glob(os.path.join(ROOT, "library", "factory", "grooves", "*.mid"))
    assert files
    for f in files:
        s = D.parse_midi(open(f, "rb").read())
        assert s["events"] and s["len"] % s["bar"] == 0 and all(0 <= e[0] < s["len"] for e in s["events"]), os.path.basename(f)


def test_le_plugin_du_kit(tmp_path):
    avl = {"black-pearl": "urn:avl#BlackPearl"}
    kits = tmp_path / "library" / "kits"
    kits.mkdir(parents=True)
    (kits / "k-avl.json").write_text(json.dumps({"id": "k-avl", "engine": "avldrums", "bank": "black-pearl"}))
    (kits / "k-pads.json").write_text(json.dumps({"id": "k-pads", "engine": "rs5k", "pads": [
        {"note": 36, "sample": "s/kick.wav", "mode": "oneshot", "level": -3}]}))
    (kits / "k-dg.json").write_text(json.dumps({"id": "k-dg", "engine": "drumgizmo"}))
    assert D.kit_plugin(str(tmp_path), "k-avl", avl) == ({"lv2": "urn:avl#BlackPearl"}, None)
    p, why = D.kit_plugin(str(tmp_path), "k-pads.json", avl)
    assert why is None and p["lv2"] == D.SFIZZ and p["write"]["prop"] == D.SFIZZ_FILE
    assert f"sample={tmp_path}/s/kick.wav key=36 volume=-3 loop_mode=one_shot" in p["write"]["text"]
    assert D.kit_plugin(str(tmp_path), "k-dg", avl) == (None, "kit engine drumgizmo is not on this engine yet")
    assert D.kit_plugin(str(tmp_path), "nope", avl)[1] == "kit nope not found"
    p, _ = D.kit_plugin(str(tmp_path), '["s/a.wav", "s/b.wav"]', avl)       # une liste de samples nue : notes GM dans l'ordre
    assert "key=36" in p["write"]["text"] and "key=38" in p["write"]["text"]


def test_l_adaptateur_complete_le_play(tmp_path):
    kits = tmp_path / "library" / "kits"
    kits.mkdir(parents=True)
    (kits / "k.json").write_text(json.dumps({"id": "k", "engine": "rs5k", "pads": [{"note": 36, "sample": "s/k.wav"}]}))
    (tmp_path / "g.mid").write_bytes(smf(bytes([0, 0x99, 36, 100, 0, 0xFF, 0x2F, 0])))
    out = A.drums_play({"action": "drums", "op": "play", "block": "d", "kit": "k", "patterns": ["g.mid"], "fills": [], "idx": 0},
                       root=str(tmp_path), out_dir=str(tmp_path))
    assert out["bank"]["patterns"] == 1 and out["bank"]["slots"][0]["events"] == [[0, 36, 100]]
    path = out["kit_plugin"]["files"][D.SFIZZ_FILE]
    assert out["kit_plugin"]["lv2"] == D.SFIZZ and os.path.isfile(path) and "key=36" in open(path).read()
    out = A.drums_play({"action": "drums", "op": "play", "block": "d", "kit": "absent", "patterns": [], "fills": []},
                       root=str(tmp_path), out_dir=str(tmp_path))
    assert "kit_plugin" not in out and out["kit_error"] == "kit absent not found"      # dit, et le séquenceur tourne quand même


# ── la backing : les stems décodés une fois pour le moteur (bridge/engine/ardour.py, backing_load) ───────────────────
def test_les_stems_d_une_backing_sont_decodes_une_fois_dans_le_cache(tmp_path):
    import shutil
    import subprocess
    import wave
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg absent")
    song = tmp_path / "song"
    song.mkdir()
    for name in ("drums", "bass"):                           # deux des six stems, en mp3 44,1 kHz
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1:sample_rate=44100",
                        "-ac", "2", str(song / f"{name}.mp3")], check=True)
    cache = tmp_path / "cache"
    out = A.backing_load({"action": "backing", "op": "load", "slug": "s", "dir": str(song), "mix": {"bass": {"mute": 1}}},
                         rate=48000, cache_dir=str(cache))
    assert "dir" not in out and set(out["files"]) == {"drums", "bass"} and out["mix"] == {"bass": {"mute": 1}}
    with wave.open(out["files"]["drums"]) as w:
        assert w.getframerate() == 48000 and w.getnchannels() == 2 and abs(w.getnframes() - 48000) < 4800   # à la fréquence du moteur
    stamp = os.path.getmtime(out["files"]["drums"])
    again = A.backing_load({"action": "backing", "op": "load", "slug": "s", "dir": str(song)}, rate=48000, cache_dir=str(cache))
    assert again["files"] == out["files"] and os.path.getmtime(again["files"]["drums"]) == stamp     # déjà décodé : repris
    assert A.backing_load({"op": "load", "slug": "s", "dir": str(tmp_path / "absent")}, cache_dir=str(cache))["dir"]   # rien à décoder : tel quel
    for i in range(A.BACKING_KEEP + 2):                       # le cache ne garde que les dernières chansons
        other = tmp_path / f"song{i}"
        other.mkdir()
        shutil.copy(song / "drums.mp3", other / "drums.mp3")
        os.utime(other / "drums.mp3", (1000 + i, 1000 + i))
        A.backing_load({"op": "load", "slug": f"s{i}", "dir": str(other)}, cache_dir=str(cache))
    assert len(os.listdir(cache)) == A.BACKING_KEEP


def test_un_sample_lance_part_avec_ses_chemins_absolus_et_ses_durees(tmp_path):
    import wave
    from bridge.engine import ardour as A
    p = tmp_path / "assets" / "samples" / "hit.wav"
    p.parent.mkdir(parents=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(48000)
        w.writeframes(b"\0\0" * 24000)                                  # 0,5 s
    cmd = A.sample_play({"action": "sample", "op": "play", "block": "b", "idx": 1,
                         "samples": ["assets/samples/hit.wav", str(p), "assets/samples/missing.wav"]}, root=str(tmp_path))
    assert cmd["files"] == [str(p), str(p), str(tmp_path / "assets" / "samples" / "missing.wav")]   # l'ordre et les index ne bougent pas
    assert cmd["durs"][0] == cmd["durs"][1] == 0.6 and cmd["durs"][2] == 0.0                    # la durée, plus une marge ; absent : 0
    assert cmd["idx"] == 1 and cmd["samples"][0] == "assets/samples/hit.wav"                    # la commande d'origine est intacte
