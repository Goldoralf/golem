# SPDX-License-Identifier: GPL-3.0-or-later
"""La page Storage (mockups/storage.html, 2026-10-09) : la nature d'un dossier LUE dans le système (ce disque, externe,
réseau), plusieurs dossiers ajoutés d'un coup, et les caches qui se vident sans toucher à ce qui sert."""
import os

import pytest

from bridge import backup as B, config as C, song_folders as SF, storage as ST


MOUNTS = [("/", "ext4", "/dev/nvme0n1p6"), ("/media/alex/HD Save", "ntfs3", "/dev/sda1"),
          ("/run/user/1000/gvfs", "fuse.gvfsd-fuse", "gvfsd-fuse"), ("/mnt/nas", "cifs", "//nas/music"),
          ("/data", "ext4", "/dev/nvme1n1p1")]


@pytest.fixture
def linux(monkeypatch, tmp_path):
    if SF.sys.platform == "win32":
        # os.stat remplacé ci-dessous pour TOUT le processus : sous Windows pytest lui-même l'appelle pendant
        # le test et plante (erreur interne, pas un échec). Ces natures de dossier sont celles de Linux.
        pytest.skip("Linux mount kinds; patching os.stat breaks pytest itself on Windows")
    monkeypatch.setattr(SF.sys, "platform", "linux")
    monkeypatch.setattr(SF, "_linux_mounts", lambda: MOUNTS)
    monkeypatch.setattr(SF.os.path, "realpath", lambda p: p)
    monkeypatch.setattr(SF.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(SF, "_usb", lambda dev: dev == "/dev/sda1")

    class St:
        def __init__(self, dev): self.st_dev = dev
    monkeypatch.setattr(SF.os, "stat", lambda p: St(1 if (p == C.ROOT or not p.startswith(("/media", "/run", "/mnt", "/data"))) else 2))


@pytest.mark.parametrize("path,kind", [
    ("/home/alex/Music", "this-disk"),
    ("/media/alex/HD Save/golem", "external"),                                         # USB
    ("/run/user/1000/gvfs/smb-share:server=starnas.local,share=music/jazz", "network"),  # gvfs SMB
    ("/run/user/1000/gvfs/mtp:host=Phone/Music", "external"),                           # un téléphone, pas le réseau
    ("/mnt/nas/golem", "network"),                                                       # cifs
    ("/data/golem", "other-disk"),                                                       # un second disque interne
])
def test_la_nature_d_un_dossier_est_lue_dans_le_systeme(linux, path, kind):
    assert SF.location(path)["kind"] == kind


@pytest.mark.skipif(os.name != "posix", reason="gvfs shares and ~/Music are the Linux desktop")
def test_un_partage_gvfs_a_un_nom_lisible():
    assert SF.display_name("/run/user/1000/gvfs/smb-share:server=starnas.local,share=music/jazz") == "music on starnas.local / jazz"
    assert SF.display_name(os.path.expanduser("~") + "/Music") == "~/Music"


def test_plusieurs_dossiers_d_un_coup_chacun_sa_reponse(tmp_path):
    from fastapi.routing import APIRoute
    from bridge import routes_content as R
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    out = R.api_song_folders_add({"paths": [str(a), str(b), str(tmp_path / "nope")], "show_on_golemfm": False})
    assert out["ok"] and set(out["added"]) == {str(a), str(b)} and out["refused"][0]["why"] == "not found"
    assert {f["path"] for f in SF.folders()} == {str(a), str(b)}


def test_vider_les_apercus_orphelins_seulement(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "RECORDINGS_DIR", str(tmp_path / "rec"))
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    (tmp_path / "rec/peaks").mkdir(parents=True)
    (tmp_path / "rec/perf-1").mkdir()
    (tmp_path / "rec/perf-1/take.wav").write_bytes(b"RIFF")
    (tmp_path / "rec/peaks/take.wav.reapeaks").write_bytes(b"x" * 10)          # son audio existe : gardé
    (tmp_path / "rec/peaks/gone.wav.reapeaks").write_bytes(b"x" * 100)         # orphelin : vidé
    r = ST.clear("peaks")
    assert r == {"freed": 100, "n": 1}
    assert os.listdir(tmp_path / "rec/peaks") == ["take.wav.reapeaks"]


def test_vider_les_chansons_decompressees_garde_celle_qui_est_chargee(monkeypatch):
    from bridge.state import state
    work = os.path.join(C.SONGS_DIR, ".work")
    for n in ("rs-aaa", "rs-bbb"):
        os.makedirs(os.path.join(work, n), exist_ok=True)
        open(os.path.join(work, n, "stem.flac"), "wb").write(b"f" * 50)
    monkeypatch.setattr(state, "backing", {"slug": "rs:aaa", "playing": False})
    monkeypatch.setattr(state, "song", None)
    r = ST.clear("work")
    assert r["n"] == 1 and r["kept"] == ["rs-aaa"] and os.listdir(work) == ["rs-aaa"]
    monkeypatch.setattr(state, "backing", {"slug": "rs:aaa", "playing": True})
    with pytest.raises(ST.StorageError, match="playing"):
        ST.clear("work")


def test_l_inventaire_repond(tmp_path):
    o = ST.overview()
    assert o["disk"]["total"] > 0 and {c["id"] for c in o["caches"]} == {"peaks", "work", "backing"}
    assert set(o["music"]) >= {"amps", "patches", "synths", "recordings", "songs"}


def test_your_music_separe_chansons_et_vocals(tmp_path, monkeypatch):
    # Songs et Vocals vivent dans le même dossier songs/ : seule la catégorie que porte le .golem les sépare
    from bridge import config as C
    from bridge import golemfile as G
    from bridge import storage as ST
    monkeypatch.setattr(C, "SONGS_DIR", str(tmp_path))
    G.write(str(tmp_path / "a.golem"), {"type": "song", "id": "rs:" + "a" * 32, "title": "A"},
            {"audio/original.flac": b"fLaC" + b"\1" * 100, "scores/song.gp": b"BCFZ" + b"\0" * 8})
    G.write(str(tmp_path / "b.golem"), {"type": "song", "id": "rs:" + "b" * 32, "title": "B"},
            {"audio/original.flac": b"fLaC" + b"\1" * 100, "lyrics/song.lrc": b"[00:01.00]la"})
    ST._CAT_CACHE.clear()
    got = ST._songs_by_category()
    assert got["songs"]["n"] == 1 and got["vocals"]["n"] == 1
    assert got["vocals"]["bytes"] == os.path.getsize(tmp_path / "b.golem")
