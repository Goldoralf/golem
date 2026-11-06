# SPDX-License-Identifier: GPL-3.0-or-later
"""Recevoir les .golem de golem.fm (plan-song-sharing lot 2, côté rack) : le job song-install et le tirage
par golem_etag. Le serveur est simulé : `_download` écrit le fichier qu'il aurait servi."""
import os
import shutil

import pytest

from bridge import golem_pull as P, golemfile as G, songs as S

SID = "rs:" + "c" * 32


def _make(tmp_path, sid=SID, title="Paper Kite"):
    p = str(tmp_path / ("srv-%s.golem" % sid.replace(":", "-")))
    G.write(p, {"type": "song", "id": sid, "title": title, "kind": "cover",
                "golemfm": {"slug": "glass_lanterns_paper_kite"}},
            {"stems/drums.mp3": b"ID3" + b"\1" * 200, "sync/bars.json": b'{"version":1}'})
    return p


@pytest.fixture
def server(tmp_path, monkeypatch):
    served = {"file": None, "calls": []}

    def fake(url, dest):
        served["calls"].append(url)
        shutil.copyfile(served["file"], dest)
        return '"etag-1"'
    monkeypatch.setattr(P, "_download", fake)
    from bridge import golemfm
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://golem.test", "tok"))
    # pas de plan servi : le rack tire l'archive, comme avant R6
    monkeypatch.setattr(golemfm, "_req", lambda path, **k: (404, "not found"))
    return served


def test_le_job_installe_et_rend_l_ack(tmp_path, server):
    server["file"] = _make(tmp_path)
    ack = P.song_install({"id": SID, "slug": "glass_lanterns_paper_kite",
                          "url": "/api/ext/songs/glass_lanterns_paper_kite/golem", "etag": "e1"})
    assert ack == {"song": {"id": SID}, "missing": []}
    assert S.load(SID)["title"] == "Paper Kite"
    assert P.etags() == {"glass_lanterns_paper_kite": "e1"}
    assert not [f for f in os.listdir(S.C.SONGS_DIR) if f.startswith(".dl-")]       # pas de reste


def test_le_job_refuse_un_fichier_d_une_autre_chanson(tmp_path, server):
    server["file"] = _make(tmp_path, sid="us:" + "d" * 32)
    with pytest.raises(RuntimeError, match="not " + SID):
        P.song_install({"id": SID, "slug": "x", "url": "/api/ext/songs/x/golem", "etag": "e1"})
    assert S.list_all() == [] and P.etags() == {}


def test_le_tirage_ne_vise_que_ce_que_le_rack_porte_et_qui_a_change(tmp_path):
    S.save({"id": SID, "rev": 3, "title": "Paper Kite", "kind": "cover",
            "song_slug": "glass_lanterns_paper_kite", "sheet": {}}, bump=False)
    P._set_etag("autre", "e9")
    cards = [{"slug": "glass_lanterns_paper_kite", "golem_etag": "e2"},      # dans la bibliothèque : oui
             {"slug": "en-cache", "golem_etag": "e3", "cached": True},           # en cache golem.fm : oui
             {"slug": "inconnue", "golem_etag": "e4"},                           # ni l'un ni l'autre : non
             {"slug": "sans-droit", "golem_etag": None, "cached": True},         # pas de droit au fichier : non
             {"slug": "autre", "golem_etag": "e9", "cached": True}]              # déjà installée : non
    assert P.wanted(cards) == [("glass_lanterns_paper_kite", "e2"), ("en-cache", "e3")]


def test_le_tirage_refuse_un_fichier_qui_n_est_pas_la_chanson_du_rack(tmp_path, server):
    """Vécu au premier tirage réel : golem.fm a servi la chanson PERSO (us:) au lieu de celle du groupe (rs:)."""
    S.save({"id": SID, "rev": 138, "title": "Paper Kite", "kind": "cover",
            "song_slug": "glass_lanterns_paper_kite", "sheet": {"bpm": 87}}, bump=False)
    server["file"] = _make(tmp_path, sid="us:" + "e" * 32)
    assert P.id_for_slug("glass_lanterns_paper_kite") == SID
    with pytest.raises(RuntimeError, match="not " + SID):
        P.fetch_install("/api/ext/songs/glass_lanterns_paper_kite/golem", want_id=P.id_for_slug("glass_lanterns_paper_kite"))
    assert [d["id"] for d in S.list_all()] == [SID]                    # pas de seconde « Paper Kite »


def test_un_fichier_refuse_n_est_pas_retire_tant_qu_il_ne_change_pas(tmp_path):
    S.save({"id": SID, "rev": 1, "title": "C", "kind": "cover", "song_slug": "s1", "sheet": {}}, bump=False)
    P._set_refused("s1", "e1", "the file is song us:x, not " + SID)
    assert P.wanted([{"slug": "s1", "golem_etag": "e1"}]) == []              # même version : on ne retire pas
    assert P.wanted([{"slug": "s1", "golem_etag": "e2"}]) == [("s1", "e2")]  # nouvelle version : on réessaie
    P._set_etag("s1", "e2")
    assert P.refused() == {} and P.etags() == {"s1": "e2"}


def test_r2_la_copie_d_un_membre_met_a_jour_la_chanson_du_groupe_par_son_id(tmp_path, server):
    """R2 : le golem du groupe reçoit la copie d'un membre — id de la chanson du GROUPE, slug d'une copie que le
    propriétaire ne connaît pas. Trouvée PAR L'ID : mise à jour, jamais refusée, et le slug du rack ne change pas."""
    BS = "bs:2"
    S.save({"id": BS, "rev": 4, "band": "b_night", "title": "Annie-Dog", "kind": "cover", "sheet": {"bpm": 90}}, bump=False)
    server["file"] = _make(tmp_path, sid=BS, title="Annie-Dog")
    ack = P.song_install({"id": BS, "slug": "copie_du_membre", "url": "/api/ext/songs/copie_du_membre/golem?job=77",
                          "etag": "e1", "from": 12})
    assert ack["song"] == {"id": BS}
    d = S.load(BS)
    assert d["rev"] == 4 and d["band"] == "b_night" and d["sheet"] == {"bpm": 90}
    assert "song_slug" not in d                                            # le slug d'une copie étrangère n'est pas adopté
    assert server["calls"] == ["/api/ext/songs/copie_du_membre/golem?job=77"]


# ── R6 : le PLAN d'un .golem, assemblé ici (song-sharing §2.8, golem.fm M6) ─────────────────────────────────────────
@pytest.fixture
def plan_server(tmp_path, monkeypatch):
    """golem.fm simulé : `_req` sert le plan, `_download` sert chaque membre par son url."""
    import base64
    import zipfile
    st = {"plan": None, "blobs": {}, "calls": []}

    def plan_of(golem, etag="pe-1", tamper=None):
        with zipfile.ZipFile(golem) as zf:
            mbytes = zf.read(G.MANIFEST)
            members = []
            for name in sorted(n for n in zf.namelist() if n != G.MANIFEST):
                blob = zf.read(name)
                url = "/api/ext/files/" + name
                st["blobs"][url] = (tamper or {}).get(name, blob)
                members.append({"path": name, "sha256": G.sha256_bytes(blob), "bytes": len(blob), "url": url})
        st["plan"] = {"format": 1, "manifest": base64.b64encode(mbytes).decode(), "members": members, "etag": etag}
        return st["plan"]

    def fake_download(url, dest):
        st["calls"].append(url)
        with open(dest, "wb") as f:
            f.write(st["blobs"][url])
    from bridge import golemfm
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://golem.test", "tok"))
    monkeypatch.setattr(golemfm, "_req", lambda path, **k: (200, st["plan"]) if path.endswith("/plan") or "/plan?" in path
                        else (404, "x"))
    monkeypatch.setattr(P, "_download", fake_download)
    st["plan_of"] = plan_of
    return st


def test_le_plan_s_assemble_ici_et_s_installe(tmp_path, plan_server):
    src = _make(tmp_path)
    plan_server["plan_of"](src)
    r = P.fetch_install("/api/ext/songs/glass_lanterns_paper_kite/golem", want_id=SID, slug="glass_lanterns_paper_kite")
    assert r["id"] == SID and r["etag"] == "pe-1"
    assert S.load(SID)["title"] == "Paper Kite"
    assert sorted(plan_server["calls"]) == ["/api/ext/files/stems/drums.mp3", "/api/ext/files/sync/bars.json"]
    assert not [f for f in os.listdir(S.C.SONGS_DIR) if f.startswith(".plan-")]     # pas de reste


def test_le_manifeste_est_pose_tel_quel_a_l_octet(tmp_path, plan_server):
    """Une signature couvre les octets de golem.json : ils ne sont jamais recalculés (write_raw)."""
    import zipfile
    src = _make(tmp_path)
    plan_server["plan_of"](src)
    out, _ = P.fetch_plan("/api/ext/songs/x/golem", SID, str(tmp_path / "w"))
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        assert a.read(G.MANIFEST) == b.read(G.MANIFEST)
    assert open(src, "rb").read() == open(out, "rb").read()            # même chanson, même fichier
    assert sorted(G.verify(out)["present"]) == ["stems/drums.mp3", "sync/bars.json"]


def test_un_membre_qui_ne_correspond_pas_au_plan_est_refuse(tmp_path, plan_server):
    src = _make(tmp_path)
    plan_server["plan_of"](src, tamper={"stems/drums.mp3": b"ID3" + b"\2" * 200})
    with pytest.raises(RuntimeError, match="does not match the plan"):
        P.fetch_install("/api/ext/songs/x/golem", want_id=SID, slug="x")
    assert S.list_all() == []


def test_un_plan_coherent_mais_contraire_au_manifeste_est_refuse(tmp_path, plan_server):
    """Le plan et le membre s'accordent, le MANIFESTE (signé) dit autre chose : la double vérification le voit."""
    src = _make(tmp_path)
    plan = plan_server["plan_of"](src)
    other = b"ID3" + b"\3" * 200
    m = next(x for x in plan["members"] if x["path"] == "stems/drums.mp3")
    m.update(sha256=G.sha256_bytes(other), bytes=len(other))
    plan_server["blobs"][m["url"]] = other
    with pytest.raises(RuntimeError, match="does not match the manifest"):
        P.fetch_install("/api/ext/songs/x/golem", want_id=SID, slug="x")
    assert S.list_all() == []


def test_le_rafraichissement_ne_retire_que_ce_qui_a_change(tmp_path, plan_server):
    v1 = _make(tmp_path)
    plan_server["plan_of"](v1)
    P.fetch_install("/api/ext/songs/s/golem", want_id=SID, slug="s")
    plan_server["calls"].clear()
    v2 = str(tmp_path / "v2.golem")
    G.write(v2, {"type": "song", "id": SID, "title": "Paper Kite", "kind": "cover"},
            {"stems/drums.mp3": b"ID3" + b"\1" * 200, "sync/bars.json": b'{"version":2}'})
    plan_server["plan_of"](v2, etag="pe-2")
    r = P.fetch_install("/api/ext/songs/s/golem", want_id=SID, slug="s")
    assert r["etag"] == "pe-2"
    assert plan_server["calls"] == ["/api/ext/files/sync/bars.json"]   # le stem inchangé vient de la copie locale


def test_un_plan_qui_sort_du_serveur_appaire_est_refuse(tmp_path, plan_server):
    src = _make(tmp_path)
    plan = plan_server["plan_of"](src)
    plan["members"][0]["url"] = "https://ailleurs.example/x"
    with pytest.raises(RuntimeError, match="outside the paired server"):
        P.fetch_install("/api/ext/songs/x/golem", want_id=SID, slug="x")
