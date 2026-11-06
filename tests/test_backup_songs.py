# SPDX-License-Identifier: GPL-3.0-or-later
"""Les chansons dans les sauvegardes (plan-song-sharing lot 8, 2026-10-08) : avant, backup.py ne les sauvegardait
PAS — la bibliothèque de .golem n'était protégée par rien. Le .golem revient OCTET POUR OCTET, avec sa synchro."""
import json
import os
import zipfile

import pytest

from bridge import backup as B, config as C, golemfile as G, importer as I, songs as S

SID = "rs:" + "c4" * 16


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(I, "STAGING", str(tmp_path / "backups" / ".staging"))
    src = str(tmp_path / "s.golem")
    G.write(src, {"type": "song", "id": SID, "title": "Paper Kite", "kind": "cover"},
            {"stems/drums.mp3": b"ID3" + b"\1" * 500, "sheet.json": b'{"bpm": 87}'})
    S.install_golem(src)
    S.update(SID, capo=2)                                       # rev 2 : une synchro à préserver
    from bridge.store import _write_json_atomic
    _write_json_atomic(os.path.join(C.SONGS_DIR, ".sync.json"), {SID: {"rev": 2, "status": "applied"}})
    os.makedirs(os.path.join(C.SONGS_DIR, ".mix"), exist_ok=True)
    _write_json_atomic(os.path.join(C.SONGS_DIR, ".mix", "rs-" + "c4" * 16 + ".json"), {"drums": {"mute": 1}})
    os.makedirs(os.path.join(C.SONGS_DIR, ".work", "junk"), exist_ok=True)
    return tmp_path


def _apply(name, strategy="skip"):
    return I.apply(os.path.join(B.BACKUP_DIR, name), strategy)


def test_sauvegarder_perdre_restaurer_a_l_identique(lib):
    golem = S._path(SID)
    before = open(golem, "rb").read()
    r = B.build("songs")
    with zipfile.ZipFile(os.path.join(B.BACKUP_DIR, r["file"])) as zf:
        names = set(zf.namelist())
        assert zf.getinfo("songs/" + os.path.basename(golem)).compress_type == zipfile.ZIP_STORED
    assert {"songs/.sync.json", "songs/.mix/rs-" + "c4" * 16 + ".json"} <= names
    assert not [n for n in names if ".work" in n]                     # le cache se reconstruit, il ne voyage pas
    assert B.counts()["songs"]["n"] == 1
    os.remove(golem)
    os.remove(os.path.join(C.SONGS_DIR, ".sync.json"))
    res = _apply(r["file"])
    assert res["songs"] >= 2
    assert open(golem, "rb").read() == before                          # octet pour octet
    assert S.load(SID)["rev"] == 2 and json.load(open(os.path.join(C.SONGS_DIR, ".sync.json")))[SID]["rev"] == 2


def test_skip_garde_la_notre_overwrite_la_remplace(lib):
    r = B.build("songs")
    S.update(SID, capo=5)                                              # rev 3, après la sauvegarde
    assert _apply(r["file"], "skip")["songs_skipped"] >= 1 and S.load(SID)["sheet"]["capo"] == 5
    _apply(r["file"], "overwrite")
    S._CACHE.clear()
    assert S.load(SID)["sheet"]["capo"] == 2


def test_un_golem_abime_n_est_jamais_pose(lib, monkeypatch):
    r = B.build("songs")
    os.remove(S._path(SID))
    monkeypatch.setattr(I, "_verify", lambda zf, m: None)              # le manifeste de la sauvegarde ne voit rien…
    real = zipfile.ZipFile.read
    monkeypatch.setattr(zipfile.ZipFile, "read", lambda self, n, *a: b"PK broken" if str(n).endswith(".golem") else real(self, n, *a))
    with pytest.raises(I.ImportError_):                                # …le .golem, lui, est vérifié avant d'être posé
        _apply(r["file"])
    assert not os.path.exists(S._path(SID))


def test_les_reprises_restent_locales_les_originaux_partent(lib, tmp_path, monkeypatch):
    """2026-10-08 : reprises (et standards, karaokés) → locales ; originaux → aussi chez golem.fm."""
    from bridge import golemfm as M
    monkeypatch.setattr(M, "_push_worker", lambda name: None)          # pas de réseau : on juge l'autorisation
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))   # appairé : seul le vault juge ici
    orig = "rs:" + "d5" * 16
    src = str(tmp_path / "o.golem")
    G.write(src, {"type": "song", "id": orig, "title": "Our Song", "kind": "original"}, {"stems/guitar-1.flac": b"fLaC"})
    S.install_golem(src)
    assert M.push_backup(B.build("songs")["file"])["ok"] is False     # toute la bibliothèque : locale
    o = B.build("originals")
    with zipfile.ZipFile(os.path.join(B.BACKUP_DIR, o["file"])) as zf:
        golems = [n for n in zf.namelist() if n.endswith(".golem")]
    assert golems == ["songs/rs-" + "d5" * 16 + ".golem"]               # la reprise n'y est pas
    # le vault de golem.fm refusait `originals` (400 depuis le lot 8, sans que l'écran le dise) ; il l'accepte depuis
    # v0.54.1 (2026-10-09). Une sauvegarde `songs`, elle, ne part toujours jamais.
    assert M.push_backup(o["file"])["ok"] is True
    M._PUSH.update(state="idle")
    with zipfile.ZipFile(os.path.join(B.BACKUP_DIR, B.build("all")["file"])) as zf:
        assert [n for n in zf.namelist() if n.endswith(".golem")] == golems
    assert B.counts()["originals"]["n"] == 1 and B.counts()["songs"]["n"] == 2
