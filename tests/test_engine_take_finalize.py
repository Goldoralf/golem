# SPDX-License-Identifier: GPL-3.0-or-later
"""L'assembleur d'une prise du Golem Engine (bridge/engine/take_finalize.py, docs/ardour-plan.md §7d lot 3) : les
fichiers mono par canal du moteur rangés comme une prise de REAPER, les segments d'une prise mise en pause recollés à
leur place, et la prise dite FINIE (ou son erreur) dans presets/.perf.json."""
import json
import shutil
import struct
import wave

import pytest

from bridge.engine import take_finalize as T


def wav(path, value, frames=4800, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", value) * frames)
    return str(path)


def manifest(tmp_path, tracks, mode="tracks_di", file="recordings/perf-x"):
    (tmp_path / "presets").mkdir(exist_ok=True)
    m = tmp_path / "presets" / ".engine-take.json"
    m.write_text(json.dumps({"root": str(tmp_path), "file": file, "mode": mode, "started_at": "2026-11-16T23:00:00",
                             "sample_rate": 48000, "tracks": tracks}))
    return str(m)


def perf(tmp_path):
    return json.loads((tmp_path / "presets" / ".perf.json").read_text())


def test_la_commande_joint_retarde_et_somme():
    segs = [{"pos": 1000, "len": 10, "files": ["/a%L.wav", "/a%R.wav"]}, {"pos": 49000, "len": 10, "files": ["/b%L.wav", "/b%R.wav"]}]
    cmd = T.command(segs, 1000, "/out.wav")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert cmd.count("-i") == 4 and cmd[-1] == "/out.wav"
    # le premier part à l'origine ; chacun est coupé à la longueur de SA région (le fichier du moteur en contient plus)
    assert "[0:a][1:a]join=inputs=2:channel_layout=stereo[j0];[j0]atrim=end_sample=10,anull[s0]" in graph
    assert "[2:a][3:a]join=inputs=2:channel_layout=stereo[j1];[j1]atrim=end_sample=10,adelay=delays=48000S:all=1[s1]" in graph
    assert graph.endswith("[s0][s1]amix=inputs=2:normalize=0:dropout_transition=0[a]") and "[a]" in cmd
    # la reprise part 100 échantillons AVANT la fin du premier segment : le premier est coupé là, rien n'est doublé
    over = T.command([{"pos": 0, "len": 1000, "files": ["/a.wav"]}, {"pos": 900, "len": 500, "files": ["/b.wav"]}], 0, "/o.wav")
    assert "[0:a]atrim=end_sample=900,anull[s0]" in over[over.index("-filter_complex") + 1]
    mono = T.command([{"pos": 0, "files": ["/di.wav"]}], 0, "/o.wav")
    assert mono[mono.index("-filter_complex") + 1] == "[0:a]anull[s0]" and "[s0]" in mono


def test_une_di_mono_d_un_seul_tenant_est_simplement_deplacee(tmp_path):
    src = wav(tmp_path / "golem-rec-DI-1.wav", 1000)
    done, err = T.finalize(manifest(tmp_path, [{"name": "DI-Sandbox-Input-1", "segments": [{"pos": 0, "len": 4800, "files": [src]}]}]),
                           ffmpeg="/nonexistent/ffmpeg")                   # aucun ffmpeg n'est appelé pour elle
    assert done == ["DI-Sandbox-Input-1"] and err == ""
    assert (tmp_path / "recordings" / "perf-x" / "DI-Sandbox-Input-1.wav").is_file() and not (tmp_path / "golem-rec-DI-1.wav").exists()
    assert perf(tmp_path) == {"recording": False, "file": "recordings/perf-x", "started_at": "2026-11-16T23:00:00", "error": ""}


def test_un_fichier_que_le_moteur_tient_ouvert_est_copie_et_la_prise_continue(tmp_path, monkeypatch):
    # Windows : le moteur garde ses fichiers de prise ouverts — ni renommage ni suppression (WinError 32). La prise doit
    # quand même avoir TOUS ses fichiers ; shutil.move levait sur la suppression et perdait le reste de la prise.
    di = wav(tmp_path / "golem-rec-DI-1.wav", 1000)
    drums = wav(tmp_path / "golem-rec-Drums-1.wav", 2000)
    held = {di, drums}
    import os

    def held_guard(real):
        def f(p, *a, **k):
            if str(p) in held:
                raise PermissionError(32, "The process cannot access the file because it is being used by another process")
            return real(p, *a, **k)
        return f
    for name in ("replace", "rename", "remove", "unlink"):         # tous les chemins : shutil.move passe par rename/unlink
        monkeypatch.setattr(os, name, held_guard(getattr(os, name)))
    done, err = T.finalize(manifest(tmp_path, [{"name": "DI-Sandbox-Input-1", "segments": [{"pos": 0, "len": 4800, "files": [di]}]},
                                               {"name": "Drums", "segments": [{"pos": 0, "len": 4800, "files": [drums]}]}]),
                           ffmpeg="/nonexistent/ffmpeg")
    take = tmp_path / "recordings" / "perf-x"
    assert err == "" and done == ["DI-Sandbox-Input-1", "Drums"]
    assert sorted(p.name for p in take.iterdir()) == ["DI-Sandbox-Input-1.wav", "Drums.wav"]   # pas de .part.wav laissé
    with wave.open(str(take / "Drums.wav")) as w:
        assert w.getnframes() == 4800


def test_une_erreur_est_dite_jamais_tue(tmp_path):
    a, b = wav(tmp_path / "m%L.wav", 100), wav(tmp_path / "m%R.wav", 100)
    done, err = T.finalize(manifest(tmp_path, [{"name": "Mix", "segments": [{"pos": 0, "len": 4800, "files": [a, b]}]}]),
                           ffmpeg="/nonexistent/ffmpeg")
    assert done == [] and "could not be assembled" in err
    st = perf(tmp_path)
    assert st["recording"] is False and st["file"] == "" and st["error"] == err
    done, err = T.finalize(manifest(tmp_path, []))
    assert err == "nothing was recorded" and perf(tmp_path)["file"] == ""


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")
def test_les_segments_d_une_prise_en_pause_sont_recolles_a_leur_place(tmp_path):
    # les fichiers portent 2 s de trop (9600 échantillons pour une région de 4800) : seule la région est gardée
    seg = lambda n, pos, v: {"pos": pos, "len": 4800, "files": [wav(tmp_path / f"{n}%L.wav", v, 9600), wav(tmp_path / f"{n}%R.wav", -v, 9600)]}   # noqa: E731
    tracks = [{"name": "Mix", "segments": [seg("m2", 24000 + 500, 2000), seg("m1", 500, 1000)]},     # donnés dans le désordre
              {"name": "DI-Sandbox-Input-1", "segments": [{"pos": 500, "len": 4800, "files": [wav(tmp_path / "d1.wav", 300)]},
                                                         {"pos": 24500, "len": 4800, "files": [wav(tmp_path / "d2.wav", 400)]}]}]
    done, err = T.finalize(manifest(tmp_path, tracks))
    assert err == "" and sorted(done) == ["DI-Sandbox-Input-1", "Mix"]
    with wave.open(str(tmp_path / "recordings" / "perf-x" / "Mix.wav")) as w:
        assert w.getnchannels() == 2 and w.getnframes() == 24000 + 4800      # du 1er échantillon pris au dernier
        frames = w.readframes(w.getnframes())
    at = lambda i: struct.unpack_from("<hh", frames, i * 4)                   # noqa: E731
    assert at(10) == (1000, -1000) and at(6000) == (0, 0) and at(24010) == (2000, -2000)    # segment, trou, segment
    with wave.open(str(tmp_path / "recordings" / "perf-x" / "DI-Sandbox-Input-1.wav")) as w:
        assert w.getnchannels() == 1 and w.getnframes() == 28800             # alignée sur le mix
    # le mix seul : UN fichier à plat, les autres pistes ignorées
    done, err = T.finalize(manifest(tmp_path, [{"name": "Mix", "segments": [seg("m3", 0, 500)]}, {"name": "Input-1", "segments": [seg("i", 0, 5)]}],
                                    mode="mix", file="recordings/perf-y.wav"))
    assert done == ["Mix"] and (tmp_path / "recordings" / "perf-y.wav").is_file()


def test_le_rendu_d_une_demo_va_ou_le_bridge_l_attend_et_se_dit_dans_preview_json(tmp_path):
    src = wav(tmp_path / "golem-rec-Preview.wav", 500)
    out = tmp_path / "library" / "previews" / "patch-x" / "A.wav"
    m = manifest(tmp_path, [{"name": "Preview", "segments": [{"pos": 0, "len": 4800, "files": [src]}]}], mode="preview", file="")
    data = json.loads(open(m).read())
    data["preview"] = {"out": str(out), "seq": 7, "scene": "A"}
    open(m, "w").write(json.dumps(data))
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg absent")
    done, err = T.finalize(m)
    assert done == ["Preview"] and err == "" and out.is_file()
    import wave
    with wave.open(str(out), "rb") as w:                                 # le bridge relit un rendu avec `wave` : du PCM 24 bits
        assert w.getsampwidth() == 3 and w.getnframes() > 0
    st = json.loads((tmp_path / "presets" / ".preview.json").read_text())
    assert st == {"seq": 7, "scene": "A", "done": True, "wav": str(out)}
    assert not (tmp_path / "presets" / ".perf.json").exists()            # une démo n'est pas une prise : son état à elle
    data["tracks"] = []
    open(m, "w").write(json.dumps(data))
    T.finalize(m)
    st = json.loads((tmp_path / "presets" / ".preview.json").read_text())
    assert st["done"] is True and st["wav"] == "" and st["error"] == "nothing was recorded"


def _smf(division, events):
    """Un SMF format 0 minimal : events = [(tick, octets)] ; un méta de nom de piste en tête, comme en écrit le moteur."""
    def vlq(v):
        out = [v & 0x7F]
        while v > 0x7F:
            v >>= 7
            out.append((v & 0x7F) | 0x80)
        return bytes(reversed(out))
    body, last = b"\x00\xff\x03\x02ab", 0
    for tick, msg in events:
        body += vlq(tick - last) + msg
        last = tick
    body += b"\x00\xff\x2f\x00"
    return b"MThd" + (6).to_bytes(4, "big") + b"\x00\x00\x00\x01" + division.to_bytes(2, "big") + b"MTrk" + len(body).to_bytes(4, "big") + body


def test_le_midi_joue_devient_un_fichier_cale_sur_la_prise(tmp_path):
    # deux segments (une prise mise en pause par un rappel) : le moteur écrit en temps musical, 1920 ticks par noire
    a = tmp_path / "a.mid"
    a.write_bytes(_smf(1920, [(0, b"\x90\x3c\x64"), (1920, b"\x80\x3c\x00"), (2880, b"\xb0\x40\x7f")]))
    b = tmp_path / "b.mid"
    b.write_bytes(_smf(1920, [(960, b"\x99\x24\x70"), (1200, b"\x89\x24\x00")]))
    src = wav(tmp_path / "golem-rec-Input-3.wav", 500)
    m = manifest(tmp_path, [
        {"name": "Input-3", "segments": [{"pos": 4800, "len": 4800, "files": [src]}]},
        {"name": "MIDI-Input-3", "midi": True, "bpm": 120, "segments": [
            {"pos": 4800, "len": 96000, "files": [str(a)]}, {"pos": 4800 + 96000, "len": 48000, "files": [str(b)]}]}])
    done, err = T.finalize(m, ffmpeg="/nonexistent/ffmpeg")
    assert err == "" and "MIDI-Input-3" in done
    data = (tmp_path / "recordings" / "perf-x" / "MIDI-Input-3.mid").read_bytes()
    division, evs = T.read_smf(data)
    assert division == 960 and data[22:29] == b"\x00\xff\x51\x03" + (500000).to_bytes(3, "big")      # 120 BPM en tête
    # à 120 BPM une noire = 0,5 s = 960 ticks : le second segment commence 2 s après le premier (96000 éch. à 48 kHz)
    assert evs == [(0, b"\x90\x3c\x64"), (960, b"\x80\x3c\x00"), (1440, b"\xb0\x40\x7f"), (3840 + 480, b"\x99\x24\x70"), (3840 + 600, b"\x89\x24\x00")]


def test_un_clavier_qui_n_a_rien_joue_ne_laisse_pas_de_fichier(tmp_path):
    a = tmp_path / "a.mid"
    a.write_bytes(_smf(1920, [(0, b"\xb0\x7b\x00")]))                    # un all-notes-off, pas une frappe
    src = wav(tmp_path / "golem-rec-Input-3.wav", 500)
    m = manifest(tmp_path, [{"name": "Input-3", "segments": [{"pos": 0, "len": 4800, "files": [src]}]},
                            {"name": "MIDI-Input-3", "midi": True, "bpm": 100, "segments": [{"pos": 0, "len": 4800, "files": [str(a)]}]}])
    done, err = T.finalize(m, ffmpeg="/nonexistent/ffmpeg")
    assert done == ["Input-3"] and err == "" and not (tmp_path / "recordings" / "perf-x" / "MIDI-Input-3.mid").exists()
