# SPDX-License-Identifier: GPL-3.0-or-later
"""Le cache des backings golem.fm lit les stems que golem.fm NOMME (`stems[].path`), jamais `<stems_dir>/<stem>.mp3`
(2026-10-09 : rangement par compte, `blobs/<u|b><id>/<sha[:2]>/<sha>.<ext>` ; et un original a `guitar-1`, `.flac`)."""
import json
import os

import pytest

from bridge import config as C, golemfm as M


@pytest.fixture
def fm(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "BACKING_DIR", str(tmp_path / "assets" / "backing"))
    asked = []
    song = {"title": "Paper Kite", "artist": {"name": "Glass Lanterns"}, "stems_dir": "songs/cr/stems",
            "stems": [{"id": "drums", "path": "blobs/u1/e1/e1b7.mp3"}, {"id": "guitar-1", "path": "blobs/u1/aa/aa01.flac"},
                      {"id": "vocals", "path": "blobs/u1/94/94d6.mp3"}, {"id": "../evil", "path": "../../etc/passwd"},
                      {"id": "files", "path": "blobs/u1/00/0000.mp3"}]}

    def req(path, token=None, raw=False, **kw):
        asked.append(path)
        if path == "/api/ext/songs/cr":
            return 200, song
        if path.startswith("/api/ext/files/blobs/"):
            return 200, b"audio:" + path.encode()
        return 404, "x"
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(M, "_req", req)
    monkeypatch.setattr("bridge.bars.fetch", lambda slug: None)
    return asked


def test_les_stems_sont_ceux_que_golem_fm_nomme(fm):
    M._dl_worker("cr")
    assert M.dl_status()["state"] == "done", M.dl_status()
    assert [p for p in fm if p.startswith("/api/ext/files/")] == [
        "/api/ext/files/blobs/u1/e1/e1b7.mp3", "/api/ext/files/blobs/u1/aa/aa01.flac", "/api/ext/files/blobs/u1/94/94d6.mp3"]
    assert not any("stems_dir" in p or p.endswith("/drums.mp3") for p in fm)          # plus jamais déduit
    files = M.local_files("cr")
    assert set(files) == {"drums", "guitar-1", "vocals"} and files["guitar-1"].endswith("guitar-1.flac")
    assert M.is_cached("cr") and M.stems_of("cr") == ["vocals", "drums", "guitar-1"]
    meta = json.load(open(os.path.join(C.BACKING_DIR, "cr", "meta.json")))
    assert meta["mix"]["guitar"]["mute"] == 1                                         # le mix golem.fm par défaut reste


def test_un_ancien_cache_joue_encore(fm):
    d = os.path.join(C.BACKING_DIR, "old")
    os.makedirs(d)
    open(os.path.join(d, "drums.mp3"), "wb").write(b"x")
    json.dump({"title": "Old", "mix": dict(M.DEFAULT_MIX)}, open(os.path.join(d, "meta.json"), "w"))
    assert M.is_cached("old") and M.local_files("old") is None and M.stems_of("old") == list(M.STEMS)
