# SPDX-License-Identifier: GPL-3.0-or-later
"""« Get this recording » (song-sharing.md §2.6, lot 7) : les liens de golem.fm, https seulement, la dernière réponse
hors ligne, et MusicBrainz d'après le manifeste quand il n'y a rien d'autre."""
import os

import pytest

from bridge import config as C, golemfile as G, golemfm as M, recording as R, songs as S

SID = "rs:" + "c" * 32
ANSWER = {"isrc": "USVI20400123", "mbid": "1b9f5c2e-0000-4000-8000-000000000001",
          "lookup": {"status": "found", "via": "acoustid", "score": 0.97},
          "links": [{"store": "bandcamp", "label": "Bandcamp", "url": "https://band.bandcamp.com/track/x"},
                    {"store": "qobuz", "label": "Qobuz", "url": "https://www.qobuz.com/x"},
                    {"store": "evil", "label": "Get it", "url": "magnet:?xt=urn:btih:abc"},          # jamais
                    {"store": "plain", "label": "Plain", "url": "http://example.com/x"},           # jamais
                    {"store": "qobuz", "label": "Qobuz", "url": "https://www.qobuz.com/x"}]}       # doublon


def _song(slug="paper-kite", recording=None):
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    p = os.path.join(C.SONGS_DIR, "src.golem")
    m = {"type": "song", "id": SID, "title": "Paper Kite", "kind": "cover"}
    if recording:
        m["recording"] = recording
    G.write(p, m, {"lyrics/song.lrc": b"[00:01.00]x"})
    S.install_golem(p, slug=slug)                    # le slug vient du transport (song-sharing.md §2.8)
    os.unlink(p)


@pytest.fixture
def fm(monkeypatch):
    st = {"code": 200, "data": ANSWER, "calls": 0}

    def req(path, token=None, **kw):
        st["calls"] += 1
        assert path == "/api/ext/songs/paper-kite/recording"
        return st["code"], st["data"]
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(M, "_req", req)
    return st


def test_les_liens_de_golem_fm_https_seulement(fm):
    _song()
    r = R.of_song(SID)
    assert r["identified"] and r["isrc"] == "USVI20400123" and r["source"] == "golem.fm"
    assert [l["url"] for l in r["links"]] == ["https://band.bandcamp.com/track/x", "https://www.qobuz.com/x"]
    assert r["lookup"]["status"] == "found"


def test_pas_encore_identifiee_se_dit(fm):
    _song()
    fm["data"] = {"isrc": None, "mbid": None, "lookup": None, "links": [], "acoustid": True}   # mesuré sur le dev
    r = R.of_song(SID)
    assert r["identified"] is False and r["links"] == []


def test_hors_ligne_la_derniere_reponse(fm):
    _song()
    R.of_song(SID)
    fm["code"], fm["data"] = 0, "golem.fm unreachable"
    r = R.of_song(SID)
    assert r["source"] == "cache" and len(r["links"]) == 2 and r["at"]


def test_sans_reseau_musicbrainz_d_apres_le_manifeste(monkeypatch):
    monkeypatch.setattr(M, "_cfg", lambda: (None, None))
    _song(recording={"mbid": "1b9f5c2e-0000-4000-8000-000000000001"})
    r = R.of_song(SID)
    assert r["source"] == "file" and r["identified"]
    assert r["links"] == [{"store": "musicbrainz", "label": "MusicBrainz",
                           "url": "https://musicbrainz.org/recording/1b9f5c2e-0000-4000-8000-000000000001"}]


def test_chanson_inconnue():
    assert R.of_song("rs:" + "0" * 32) is None
