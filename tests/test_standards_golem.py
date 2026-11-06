# SPDX-License-Identifier: GPL-3.0-or-later
"""Les standards en .golem (lot 10, 2026-10-08 : « on passe au .golem », dans leur propre rayon). Même slug que
l'ancien JSON (les blocs Standard le désignent), miroir inchangé, et rien n'est retéléchargé à version égale."""
import io
import json
import os

import pytest

from bridge import golemfile as G, golemfm as M, standards as S

GSX = {"v": 1, "title": "Summertime", "composer": "George Gershwin", "key": "Am", "meter": "4/4", "tempo": 80,
       "feel": "swing", "form": ["A"], "sections": {"A": {"bars": "Am7 | Bm7b5 E7 | Am7 | Am7"}}}


@pytest.fixture
def fm(tmp_path, monkeypatch):
    std = tmp_path / "standards"
    monkeypatch.setattr(S, "STD_DIR", str(std))
    monkeypatch.setattr(S, "SYNCED_DIR", str(std / "synced"))
    monkeypatch.setattr(S, "GOLEM_DIR", str(std / "golem"))
    S._cache.update(sig=None)
    os.makedirs(std / "synced")
    json.dump(dict(GSX, _golem={"slug": "summertime"}), open(std / "synced" / "summertime.json", "w"))   # l'ancien JSON
    src = str(tmp_path / "srv.golem")
    G.write(src, {"type": "song", "id": "us:" + "9c" * 16, "title": "Summertime", "artist": "George Gershwin",
                  "kind": "cover", "rights": {"work": "third-party"}, "golemfm": {"standard": "summertime"}},
            {"chart/song.gsx": json.dumps(GSX).encode()})
    served = {"cards": [{"slug": "summertime", "title": "Summertime", "golem_etag": "E1"}], "downloads": 0}
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(M, "_req", lambda path, **kw: (200, list(served["cards"])) if path == "/api/ext/standards" else (404, "x"))

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(req, timeout=None):
        served["downloads"] += 1
        return Resp(open(src, "rb").read())
    monkeypatch.setattr(M.urllib.request, "urlopen", urlopen)
    yield served
    S._cache.update(sig=None)


def test_le_standard_arrive_en_golem_sous_le_meme_slug(fm):
    r = M.standards_sync()
    assert r["ok"] and r["imported"] == 1 and fm["downloads"] == 1
    assert os.path.isfile(os.path.join(S.GOLEM_DIR, "summertime.golem"))
    assert not os.path.exists(os.path.join(S.SYNCED_DIR, "summertime.json"))     # le .golem fait foi
    S.invalidate()
    g = S.get_grid("summertime")                                                  # le bloc Standard le trouve
    assert g and g["title"] == "Summertime" and S.render(g, key="Am")["events"]
    assert [m["slug"] for m in S.list_standards()] == ["summertime"]             # pas de doublon JSON + .golem
    assert S.catalog_ready()                    # synced/ est vide : la route /api/standards ne doit pas dire « aucune grille »
    import asyncio
    from bridge import routes_standards as RS
    r = asyncio.run(RS.api_list(synced=1))
    assert r["ready"] and [m["slug"] for m in r["standards"]] == ["summertime"]
    M.standards_sync()
    assert fm["downloads"] == 1                                                   # même version : rien de retiré


def test_la_synchro_ne_retire_rien_et_n_ajoute_rien(fm):
    """L'étoile est partie (2026-10-08) : la synchro MET À JOUR ce que le golem a. Un standard qui n'est plus
    servi RESTE ; un standard servi que le golem n'a pas n'arrive PAS (il arrive par song-install)."""
    M.standards_sync()
    fm["cards"] = [{"slug": "autre", "title": "Autre", "golem_etag": "E9"}]
    r = M.standards_sync()
    assert r["removed"] == 0 and r["updated"] == 0
    assert os.path.exists(os.path.join(S.GOLEM_DIR, "summertime.golem"))
    assert not os.path.exists(os.path.join(S.GOLEM_DIR, "autre.golem"))


def test_une_nouvelle_version_est_retelechargee(fm):
    M.standards_sync()
    fm["cards"] = [{"slug": "summertime", "title": "Summertime", "golem_etag": "E2"}]
    r = M.standards_sync()
    assert r["updated"] == 1 and fm["downloads"] == 2
