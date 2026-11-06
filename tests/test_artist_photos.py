# SPDX-License-Identifier: GPL-3.0-or-later
"""La photo de l'artiste rangée dans les `.golem` du répertoire (artist_photos.py, 2026-10-16) : demandée à golem.fm
avec le titre, rangée sous `art/band.<ext>` rôle `band`, le reste du fichier intact ; jamais sur un original signé ;
un 404 retenu 24 h ; un serveur injoignable ne retient rien."""
import json
import zipfile

import pytest

from bridge import artist_photos as A
from bridge import golemfile as G
from bridge import golemfm as M
from bridge import songs as S

JPG = b"\xff\xd8\xff\xe0" + b"j" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 64
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"w" * 64


@pytest.fixture
def lib(tmp_path, monkeypatch):
    sg = tmp_path / "songs"
    sg.mkdir()
    monkeypatch.setattr(A.C, "SONGS_DIR", str(sg))
    songs = {}

    def song(sid, title, artist, members=None, signed=False, cover=True):
        p = sg / (S._safe(sid) + ".golem")
        m = {"format": G.FORMAT, "type": "song", "id": sid, "title": title, "artist": artist}
        G.write(str(p), m, {"sheet.json": b"{}", **({"art/cover.jpg": JPG} if cover else {}), **(members or {})})
        if signed:
            with zipfile.ZipFile(p, "a") as zf:
                zf.writestr(G.SIG_MEMBER, "{}")
        songs[sid] = {"id": sid, "title": title, "artist": artist}
        return p

    monkeypatch.setattr(S, "list_all", lambda: list(songs.values()))
    monkeypatch.setattr(S, "load", lambda sid: songs.get(sid))
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    calls, answers = [], {}

    def req(path, **kw):
        calls.append(path)
        return answers.get("next", (0, "offline"))
    monkeypatch.setattr(M, "_req", req)
    return type("L", (), {"song": staticmethod(song), "calls": calls, "answers": answers})


def _art(p):
    with zipfile.ZipFile(p) as zf:
        m = json.loads(zf.read("golem.json"))
        cover = zf.read("art/cover.jpg") if "art/cover.jpg" in zf.namelist() else None
    return {k: v.get("role") for k, v in m["files"].items() if k.startswith("art/")}, cover


def test_la_photo_est_rangee_role_band_et_le_reste_intact(lib):
    p = lib.song("us:1", "Black", "Pearl Jam")
    lib.answers["next"] = (200, PNG)
    assert A.step() == "added"
    roles, cover = _art(p)
    assert roles.get("art/band.png") == "band" and "art/cover.jpg" in roles
    assert cover == JPG
    G.verify(str(p))                                   # empreintes recalculées : le fichier reste valide
    assert "name=Pearl+Jam" in lib.calls[0] and "title=Black" in lib.calls[0]
    assert A.candidates() == []                        # rangée : on ne redemande plus


def test_la_pochette_manquante_est_demandee_avec_l_album(lib):
    p = lib.song("rs:1", "Pour que tu m'aimes encore", "Céline Dion", cover=False, members={"art/band.jpg": JPG})
    assert [c[:2] for c in A.candidates()] == [("rs:1", "cover")]
    lib.answers["next"] = (200, WEBP)
    assert A.step() == "added"
    assert _art(p)[0].get("art/cover.webp") == "cover"
    assert lib.calls[0].startswith("/api/ext/albums/cover?") and "artist=C%C3%A9line+Dion" in lib.calls[0]
    assert A.candidates() == []
    G.verify(str(p))


def test_un_404_de_pochette_ne_bloque_pas_la_photo(lib):
    lib.song("rs:1", "Red Miso", "Leaders As Animals", cover=False)
    lib.answers["next"] = (404, "no_cover")
    assert A.step() == "none"
    assert [c[1] for c in A.candidates()] == ["band"]


def test_le_type_vient_des_octets(lib):
    assert A.image_ext(JPG) == ".jpg" and A.image_ext(PNG) == ".png" and A.image_ext(WEBP) == ".webp"
    assert A.image_ext(b"<html>") is None
    p = lib.song("us:1", "Black", "Pearl Jam")
    lib.answers["next"] = (200, b"<html>not an image</html>")
    assert A.step() == "error"
    assert "art/band" not in str(_art(p)[0])


def test_jamais_sur_un_original_signe(lib):
    lib.song("us:1", "Mine", "Night Shift", signed=True)
    lib.answers["next"] = (200, JPG)
    assert A.candidates() == [] and A.step() is None and lib.calls == []


def test_une_chanson_qui_a_deja_sa_photo_est_laissee(lib):
    lib.song("us:1", "Annie-Dog", "Glass Lanterns", members={"art/band.jpg": JPG})
    assert A.candidates() == []


def test_un_404_est_retenu_24_h(lib):
    lib.song("us:1", "Red Miso", "Leaders As Animals")
    lib.answers["next"] = (404, "no_photo")
    assert A.step() == "none"
    assert A.candidates() == []
    assert [c[0] for c in A.candidates(now=__import__("time").time() + A.RETRY_S + 1)] == ["us:1"]


def test_injoignable_ne_retient_rien(lib):
    lib.song("us:1", "Black", "Pearl Jam")
    assert A.step() == "error"
    assert [c[0] for c in A.candidates()] == ["us:1"]


def test_sans_artiste_rien_n_est_demande(lib):
    lib.song("us:1", "Untitled", "")
    assert A.candidates() == [] and lib.calls == []
