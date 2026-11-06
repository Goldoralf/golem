# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 5 : ce que porte une chanson (lu dans l'archive), déposer un .golem — et SEULEMENT un .golem (le mainteneur,
2026-10-08) —, « Replace with a file… » (même enregistrement : les médias remplacés, la fiche gardée)."""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bridge import golemfile as G, inbox as I, routes_content as R, songs as S

D = json.load(open(os.path.join(os.path.dirname(__file__), "data", "fingerprints.json")))
MINE = "rs:" + "e5" * 16


def _file(path, sid, fp=None, stems=("drums",), extra=None, title="Paper Kite"):
    man = {"type": "song", "id": sid, "title": title, "kind": "cover",
           "files": {"lyrics/song.lrc": {"sha256": "0" * 64}}}
    if fp:
        man["recording"] = {"duration_ms": 297893, "fingerprint": {"algo": "chromaprint", "value": fp}}
    members = {f"stems/{s}.mp3": b"ID3" + bytes([i]) * 50 for i, s in enumerate(stems)}
    members.update(extra or {})
    G.write(str(path), man, members)
    return str(path)


def test_ce_que_porte_la_chanson_se_lit_dans_l_archive(tmp_path):
    S.install_golem(_file(tmp_path / "a.golem", MINE, D["kite"], extra={"sync/bars.json": b'{"bars":[{},{}]}'}))
    f = S.files_summary(MINE)
    by = {i["key"]: i for i in f["items"]}
    assert f["state"] == "partial" and f["missing"] == ["Lyrics"]                    # déclarées, absentes
    assert by["stems"]["state"] == "ok" and by["bars"]["info"].startswith("2 bars")
    assert by["video"]["state"] == "none" and by["identity"]["state"] == "ok"
    S.save({"id": "rs:" + "f6" * 16, "rev": 1, "title": "Card", "kind": "cover", "sheet": {}}, bump=False)
    assert S.files_summary("rs:" + "f6" * 16, detail=False)["state"] == "card"


def test_remplacer_par_le_meme_enregistrement_garde_la_fiche(tmp_path):
    S.install_golem(_file(tmp_path / "a.golem", MINE, D["kite"]))
    S.update(MINE, bpm=87)
    friend = _file(tmp_path / "b.golem", "us:" + "a7" * 16, D["reencode96k"], stems=("drums", "bass"))
    with pytest.raises(S.InstallError, match="already complete"):
        S.install_golem(friend)                                                    # sans « remplacer » : refusé
    r = S.install_golem(friend, replace_into=MINE)
    assert r["id"] == MINE and S.load(MINE)["sheet"]["bpm"] == 87
    assert "stems/bass.mp3" in G.verify(S._path(MINE))["present"]
    other = _file(tmp_path / "c.golem", "us:" + "b8" * 16, D["other_song"], title="Warm Light")
    with pytest.raises(S.InstallError, match="not the same recording"):
        S.install_golem(other, replace_into=MINE)


def test_la_route_de_depot_n_accepte_que_des_golem(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_recent", [])
    app = FastAPI()
    app.include_router(R.router)
    c = TestClient(app)
    r = c.post("/api/golem/drop?name=song.mp3", content=b"ID3")
    assert r.status_code == 400 and r.json()["golemfm"] == "https://golem.fm/songs?add=1"
    body = open(_file(tmp_path / "a.golem", MINE, D["kite"]), "rb").read()
    r = c.post("/api/golem/drop?name=kite.golem", content=body)
    assert r.status_code == 200 and r.json()["id"] == MINE
    assert [e["ok"] for e in I._recent] == [True, False]                            # le plus récent d'abord
    assert not [f for f in os.listdir(S.C.SONGS_DIR) if f.startswith(".drop-")]
    assert c.get(f"/api/songs/{MINE}/files").json()["state"] in ("complete", "partial")
