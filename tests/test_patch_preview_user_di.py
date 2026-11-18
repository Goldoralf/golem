# SPDX-License-Identifier: GPL-3.0-or-later
"""Un patch rendu sur une DI DE L'UTILISATEUR (job patch-preview `di: {sha, filename}`, golem.fm « My DIs », validé par
le mainteneur le 2026-11-18) : convertie en mono 48 kHz, jouée telle quelle, refusée hors 3–30 s, jamais gardée."""
import json
import os
import shutil
import subprocess

import pytest

from bridge import config as C
from bridge import preview as PV
from bridge import tones_jobs as J

ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg absent")


def _tone(tmp_path, secs, name="in.flac", channels=2, rate=44100):
    p = tmp_path / name
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={secs}:sample_rate={rate}",
                    "-ac", str(channels), "-af", "volume=-6dB", str(p)], check=True)
    return p.read_bytes()


@ffmpeg
def test_la_di_est_convertie_mesuree_et_jamais_retouchee_en_niveau(tmp_path):
    r = PV.user_di(_tone(tmp_path, 5), "My take.flac", str(tmp_path / "work"))
    assert r["ok"] and r["label"].startswith("user:") and len(r["label"]) == 5 + 64
    assert abs(r["duration"] - 5.0) < 0.2 and r["peak_db"] is not None
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels,sample_rate,codec_name", "-of", "json", r["path"]],
                          capture_output=True, text=True).stdout
    st = json.loads(info)["streams"][0]
    assert (st["channels"], st["sample_rate"], st["codec_name"]) == (1, "48000", "pcm_s24le")
    assert os.listdir(tmp_path / "work") == [os.path.basename(r["path"])]            # le fichier reçu n'est pas gardé


@ffmpeg
def test_hors_de_3_a_30_secondes_c_est_refuse_avec_une_phrase(tmp_path):
    for secs in (1, 31):
        r = PV.user_di(_tone(tmp_path, secs, f"d{secs}.wav"), "d.wav", str(tmp_path / "w"))
        assert r["ok"] is False and "between 3 and 30 seconds" in r["error"]
    assert not os.listdir(tmp_path / "w")                                            # rien ne reste d'un refus
    assert "wav, flac, mp3, ogg or aiff" in PV.user_di(b"x", "notes.txt", str(tmp_path / "w"))["error"]
    assert "could not be read as audio" in PV.user_di(b"not audio at all", "bad.wav", str(tmp_path / "w"))["error"]


def test_le_plan_prend_un_fichier_a_la_place_d_un_id(tmp_path, monkeypatch):
    di = tmp_path / "di.wav"
    di.write_bytes(b"RIFF")
    preset = {"id": "p", "scenes": [{"id": "A"}, {"id": "B"}]}
    monkeypatch.setattr(PV.store, "load_preset", lambda pid: preset)
    monkeypatch.setattr(PV, "_patch_of", lambda pid: None)
    monkeypatch.setattr(PV, "_scenes_of", lambda p, b: ["A", "B"])
    monkeypatch.setattr(PV, "_role_of", lambda p, k: "guitar")
    monkeypatch.setattr(PV, "resolve_di", lambda *a, **k: (_ for _ in ()).throw(AssertionError("the index was consulted")))
    pl = PV.plan("p", ref="user:abc", di_file=str(di))
    assert pl["ref"] == "user:abc" and pl["refs"] == {"A": "user:abc", "B": "user:abc"} and pl["midi"] is False
    assert pl["dis"] == {"A": str(di), "B": str(di)}
    assert "reference DI missing" in PV.plan("p", ref="user:abc", di_file=str(tmp_path / "gone.wav"))
    assert "no MIDI reference" in PV.plan("p", in_key="k", ref="user:abc", di_file=str(di))   # une DI ne joue pas un clavier


def test_le_job_rend_sur_la_di_envoyee_et_ne_la_garde_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(tmp_path / "previews"))
    os.makedirs(C.PRESETS_DIR)
    lane = {"in_sel": "1", "midi": False}
    monkeypatch.setattr(J, "_trial_preset", lambda job, tmp, pid=None: ({"id": pid, "scenes": [{"id": "A"}]}, "guitar", lane, ["A"],
                                                                        {"matched": [], "installed": []}, []))
    di_path = tmp_path / "presets" / ".patch-preview-di" / "di-x.mono48.wav"
    got = {}

    def user_di(data, filename, work):
        os.makedirs(work, exist_ok=True)
        di_path.write_bytes(b"RIFF")
        got.update(data=data, filename=filename)
        return {"ok": True, "path": str(di_path), "label": "user:" + "a" * 64, "duration": 12.0, "peak_db": -3.2}
    monkeypatch.setattr(PV, "user_di", user_di)
    monkeypatch.setattr(J, "_blob_bytes", lambda job, tmp: (got.setdefault("sha", job["sha"]), b"AUDIO")[1])

    def generate(pid, seq, on_scene=None, in_key="1", ref=None, casting=None, only=None, max_s=None, di_file=None):
        got.update(ref=ref, di_file=di_file, only=only, there=os.path.isfile(di_file))
        p = json.load(open(os.path.join(C.PRESETS_DIR, pid + ".json")))
        p["preview"] = {"ref": ref, "instrument": "guitar", "fingerprint": "fp", "scenes": {"A": "x/A.opus"}}
        json.dump(p, open(os.path.join(C.PRESETS_DIR, pid + ".json"), "w"))
        on_scene("A", "x/A.opus")
    monkeypatch.setattr(PV, "generate", generate)
    monkeypatch.setattr(PV, "status", lambda: {"phase": "done"})
    monkeypatch.setattr(PV, "push_clip", lambda pid, sc, rel: {"sha256": "c", "duration": 12.0})
    monkeypatch.setattr(PV, "_di_index", lambda: {})
    r = J._patch_preview({"action": "patch-preview", "sha": "PATCH", "role": "guitar", "patch_id": "p1", "scene": "A",
                          "di": {"sha": "DISHA", "filename": "me.wav"}})
    assert got["sha"] == "DISHA" and got["filename"] == "me.wav" and got["there"] is True and got["only"] == "A"
    assert got["ref"] == "user:" + "a" * 64 and got["di_file"] == str(di_path)
    assert r["di"] == "user:" + "a" * 64 and r["di_peak_db"] == -3.2 and r["di_duration"] == 12.0 and r["di_name"] is None
    assert not di_path.exists()                                                      # la DI de l'utilisateur ne reste pas
    monkeypatch.setattr(PV, "user_di", lambda d, f, w: {"ok": False, "error": "a DI lasts between 3 and 30 seconds (this one: 44 s)"})
    with pytest.raises(RuntimeError, match="between 3 and 30 seconds"):
        J._patch_preview({"action": "patch-preview", "sha": "PATCH", "role": "guitar", "patch_id": "p1", "di": {"sha": "D", "filename": "l.wav"}})


def test_le_rack_annonce_ce_qu_il_comprend():
    from bridge import blockstatus as BS
    assert {"patch-preview-di", "patch-preview-scene", "groove-render", "kit-pad-set", "kit-available"} <= set(BS.JOB_CAPS)
