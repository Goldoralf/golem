# SPDX-License-Identifier: GPL-3.0-or-later
"""Samples à deux types (short | song, CHOISI à l'import) et backings LOCAUX (1 à 6 stems = des
samples song) — décisions 2026-09-15, docs/samples-backings.md. La COMPOSITION d'un backing local est retirée
le 2026-10-08 ; ceux qui existent se jouent encore."""

import json
import os
import struct
import math

import pytest

from bridge import config as C, kits, golemfm


def _wav(path, seconds=0.5, amp=0.1, sr=8000):
    n = int(seconds * sr)
    frames = b"".join(struct.pack("<h", int(amp * 32767 * math.sin(i * 0.3))) for i in range(n))
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
                + b"data" + struct.pack("<I", len(frames)) + frames)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path
    (root / "assets" / "samples").mkdir(parents=True)
    (root / "assets" / "backing").mkdir(parents=True)
    (root / "library" / "kits").mkdir(parents=True)
    monkeypatch.setattr(C, "ROOT", str(root))
    monkeypatch.setattr(C, "BACKING_DIR", str(root / "assets" / "backing"))
    monkeypatch.setattr(kits, "SAMPLES_DIR", str(root / "assets" / "samples"))
    monkeypatch.setattr(kits, "KINDS_FILE", str(root / "assets" / "samples" / ".kinds.json"))
    monkeypatch.setattr(kits, "KITS_DIR", str(root / "library" / "kits"))
    return root


def test_le_type_est_choisi_a_l_import_et_se_corrige(lib):
    r = kits.save_sample("kick.wav", open(_mk(lib, "k.wav", 0.2), "rb").read())
    assert r["kind"] == "short" and r["loudness_db"] is None
    r2 = kits.save_sample("chorus-bounce.wav", open(_mk(lib, "c.wav", 1.0, amp=0.5), "rb").read(), kind="song")
    assert r2["kind"] == "song" and -12 < r2["loudness_db"] < -6           # ~0.5 × sin : RMS ≈ -9 dBFS
    by = {s["file"]: s for s in kits.list_samples()}
    assert by[r["file"]]["kind"] == "short" and by[r2["file"]]["kind"] == "song"
    assert [s["file"] for s in kits.list_samples(kind="song")] == [r2["file"]]
    assert kits.set_sample_kind(r["file"], "song")["ok"] and kits.sample_kind(r["file"]) == "song"
    assert kits.set_sample_kind(r["file"], "bogus")["ok"] is False
    # un vieux fichier posé à la main, sans sidecar = short
    _wav(os.path.join(kits.SAMPLES_DIR, "old.wav"))
    assert kits.sample_kind(os.path.join("assets", "samples", "old.wav")) == "short"


def test_un_backing_local_existant_se_joue_encore(lib):
    """On ne COMPOSE plus de backing local (2026-10-08 : un backing arrive de golem.fm ou d'un .golem). Ceux qui
    existent sur un rack se jouent comme avant : listés, lus, leurs samples protégés, supprimables."""
    song = kits.save_sample("bounce.wav", open(_mk(lib, "b.wav", 1.0, amp=0.5), "rb").read(), kind="song")["file"]
    slug = "local-paper-kite-no-vox"
    os.makedirs(os.path.join(C.BACKING_DIR, slug))
    json.dump({"title": "Paper Kite (no vox)", "bpm": 124.0, "local": True, "stems": {"other": song, "drums": song},
               "mix": {"other": {"mute": 0, "vol": 0.5}, "drums": {"mute": 0, "vol": 0.5}}},
              open(os.path.join(C.BACKING_DIR, slug, "meta.json"), "w"))
    c = {s["slug"]: s for s in golemfm.list_cache()}
    assert c[slug]["local"] is True and c[slug]["cached"] is True and c[slug]["stems_n"] == 2
    assert golemfm.is_cached(slug)
    files = golemfm.local_files(slug)
    assert set(files) == {"other", "drums"} and all(os.path.isabs(p) for p in files.values())
    assert golemfm.local_files("not-local") is None
    # un stem en service ne se supprime pas, ni ne redevient short
    assert kits.delete_sample(song)["ok"] is False and "backing" in kits.delete_sample(song)["error"]
    assert kits.set_sample_kind(song, "short")["ok"] is False
    assert kits.backing_usage() == {song: [slug]}
    assert golemfm.remove_cached(slug) and kits.delete_sample(song)["ok"]
    assert not hasattr(golemfm, "save_local_backing")               # la création est retirée, pas cachée


def test_stem_gain_ramene_a_la_cible(lib):
    loud = kits.save_sample("loud.wav", open(_mk(lib, "l.wav", 1.0, amp=0.9), "rb").read(), kind="song")
    quiet = kits.save_sample("quiet.wav", open(_mk(lib, "q.wav", 1.0, amp=0.01), "rb").read(), kind="song")
    assert kits.stem_gain(loud["file"]) < 1.0 < kits.stem_gain(quiet["file"]) <= 4.0
    assert kits.stem_gain("assets/samples/unknown.mp3") == 1.0


def _mk(root, name, seconds=0.3, amp=0.1):
    p = str(root / name); _wav(p, seconds, amp); return p
