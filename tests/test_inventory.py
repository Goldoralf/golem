# SPDX-License-Identifier: GPL-3.0-or-later
"""L'inventaire du golem sur golem.fm et le stockage à la carte (song-sharing.md §2.7). golem.fm est simulé :
`_req` pour l'inventaire et les quotas, `urlopen` pour l'envoi d'un .golem."""
import io
import json
import os
import zipfile

import pytest

from bridge import golemfile as G, golem_pull as P, inventory as I, golemfm as M, songs as S
from bridge import config as C

SID = "rs:" + "d" * 32
GP = b"BCFZ" + b"\0" * 64


def _song(sid=SID, title="Paper Kite", lyrics=True):
    members = {"audio/original.flac": b"fLaC" + b"\1" * 400, "stems/drums.flac": b"fLaC" + b"\2" * 300,
               "scores/song.gp": GP, "sync/bars.json": b'{"version":1}'}
    if lyrics:
        members["lyrics/song.lrc"] = b"[00:01.00]hello"
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    p = os.path.join(C.SONGS_DIR, "src.golem")
    G.write(p, {"type": "song", "id": sid, "title": title, "artist": "Glass Lanterns", "kind": "cover"}, members)
    S.install_golem(p)
    os.unlink(p)
    return sid


# ── la règle de catégorie, partagée avec golem.fm ──

@pytest.mark.parametrize("present,declared,want", [
    ({"scores/song.gp", "audio/original.flac"}, (), "song"),
    ({"chart/song.gsx"}, (), "standard"),
    ({"chart/song.gsx"}, ("audio/original.wav",), None),            # une grille + de l'audio n'est pas un standard
    ({"lyrics/song.lrc"}, ("audio/original.mp3",), "vocals"),       # une ligne Vocals LÉGÈRE reste une ligne Vocals
    ({"lyrics/song.lrc", "audio/original.mp3"}, (), "vocals"),
    ({"audio/original.wav"}, (), "track"),                          # de l'audio seul : une chanson en attente de tab
    ({"stems/vocals.mp3"}, ("audio/original.mp3",), "track"),
    ({"scores/song.gp"}, ("audio/original.flac",), "song"),         # une chanson légère reste une chanson
])
def test_la_categorie_est_lue(present, declared, want):
    assert G.category(present, declared) == want


def test_la_copie_legere_garde_le_manifeste_sans_l_audio(tmp_path):
    _song()
    src = S._path(SID)
    dst = str(tmp_path / "light.golem")
    G.light_copy(src, dst)
    rep = G.verify(dst)
    assert rep["manifest"] == G.read_manifest(src)                  # MÊME manifeste
    assert set(rep["missing"]) == {"audio/original.flac", "stems/drums.flac"}
    assert G.category_of(dst) == "song"
    assert os.path.getsize(dst) < os.path.getsize(src)


# ── l'inventaire ──

@pytest.fixture
def fm(monkeypatch):
    calls = []

    def req(path, body=None, token=None, method=None, **kw):
        calls.append((method or ("POST" if body is not None else "GET"), path, body))
        if path == "/api/ext/inventory":
            ids = {c["id"]: c["etag"] for c in (body or {}).get("cards", []) + (body or {}).get("upsert", [])}
            return 200, {"rev": ids, "kept": len(ids)}
        if path == "/api/ext/quotas":
            return 200, {"songs": {"used": 3, "limit": 10}, "standards": {"used": 6, "limit": 10}}
        return 404, "x"
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(M, "_req", req)
    return calls


def test_la_carte_ne_porte_aucun_contenu(fm):
    _song()
    c = I.card_of(S._path(SID))
    assert c["category"] == "song" and c["title"] == "Paper Kite"
    assert c["carries"] == {"audio": True, "stems": ["drums"], "tab": True, "lyrics": True, "chart": False,
                            "bars": True, "booklet": False, "video": False, "parts": []}
    assert all(isinstance(v, (bool, list)) for v in c["carries"].values())


def test_premier_envoi_instantane_puis_diff(fm):
    _song()
    r = I.publish()
    assert r == {"ok": True, "put": 1} and fm[-1][0] == "PUT"
    assert I.publish() == {"ok": True, "unchanged": True}            # rien n'a bougé : rien n'est envoyé
    S.update(SID, title="Paper Kite (live)")                         # le fichier change -> sa version change
    r = I.publish()
    assert r == {"ok": True, "upsert": 1, "remove": 0} and fm[-1][0] == "PATCH"


def test_une_lecture_ratee_n_envoie_ni_instantane_ni_retrait(fm):
    _song()
    I.publish()
    with open(os.path.join(C.SONGS_DIR, "casse.golem"), "wb") as f:   # un fichier illisible
        f.write(b"not a zip")
    os.unlink(S._path(SID))                                           # et la chanson a disparu
    r = I.publish()
    assert r.get("unchanged") or r.get("remove") == 0                 # incomplète : AUCUN retrait
    I.forget()
    r = I.publish()
    assert fm[-1][0] == "PATCH" and fm[-1][2]["remove"] == []         # pas d'instantané : des ajouts, aucun retrait


# ── stocker ──

class _Resp(io.BytesIO):
    status = 201
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_stocker_note_la_version_et_relie_la_chanson(fm, monkeypatch):
    _song()
    seen = {}

    def urlopen(req, timeout=None):
        body = req.data.read()
        seen.update(url=req.full_url, size=len(body))
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            seen["names"] = set(z.namelist())
            seen["manifest"] = json.loads(z.read("golem.json"))
        return _Resp(json.dumps({"kind": "song", "slug": "paper-kite", "id": SID, "mode": "light",
                                 "golem_etag": "up-0123456789abcdef0123"}).encode())
    monkeypatch.setattr(I.urllib.request, "urlopen", urlopen)
    res = I.upload(SID, "light")
    assert seen["url"] == "https://golem.fm/api/ext/golem?mode=light"
    assert not any(n.startswith(("audio/", "stems/")) for n in seen["names"])     # le texte seul
    assert "scores/song.gp" in seen["names"] and "golem.json" in seen["names"]
    # un .golem ne mène à personne (song-sharing.md §2.8) : la copie de SORTIE, sans la synchro du rack (le groupe,
    # le slug), mais sous NOTRE id — golem.fm le relie dans notre compte
    assert "repertoire" not in seen["manifest"] and "golemfm" not in seen["manifest"] and seen["manifest"]["id"] == SID
    assert P.etags()["paper-kite"] == "up-0123456789abcdef0123"                  # noté comme un tirage
    assert S.load(SID)["song_slug"] == "paper-kite"                               # relié : pas de doublon
    assert P.wanted([{"slug": "paper-kite", "golem_etag": "up-0123456789abcdef0123"}]) == []
    assert res["kind"] == "song"


def test_un_refus_se_dit(fm, monkeypatch):
    _song()

    def urlopen(req, timeout=None):
        raise I.urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(
            json.dumps({"detail": {"error": "quota_exceeded", "section": "songs", "used": 10, "limit": 10}}).encode()))
    monkeypatch.setattr(I.urllib.request, "urlopen", urlopen)
    with pytest.raises(I.UploadError) as e:
        I.upload(SID, "full")
    assert "no room left in your songs" in str(e.value)
    assert S.load(SID).get("song_slug") is None                                    # rien de relié



def test_une_declaration_manquante_se_dit_sans_passer_pour_une_panne(fm, monkeypatch):
    """golem.fm, 2026-10-12 : le dépôt exige la déclaration sur l'honneur du COMPTE (faite là-bas, rien à cocher ici)."""
    _song()

    def urlopen(req, timeout=None):
        raise I.urllib.error.HTTPError(req.full_url, 403, "x", {}, io.BytesIO(
            json.dumps({"detail": {"error": "rights_not_declared"}}).encode()))
    monkeypatch.setattr(I.urllib.request, "urlopen", urlopen)
    with pytest.raises(I.UploadError) as e:
        I.upload(SID, "full")
    assert "open golem.fm and confirm your rights declaration" in str(e.value) and "unreachable" not in str(e.value)

def test_le_job_golem_upload(fm, monkeypatch):
    _song()
    monkeypatch.setattr(I.urllib.request, "urlopen", lambda req, timeout=None: _Resp(json.dumps(
        {"kind": "song", "slug": "paper-kite", "id": SID, "golem_etag": "up-1"}).encode()))
    ack = I.golem_upload_job({"id": SID, "category": "song", "mode": "full",
                              "url": "/api/ext/golem?mode=full&job=42"})
    assert ack == {"ok": True, "kind": "song", "slug": "paper-kite", "golem_etag": "up-1"}
