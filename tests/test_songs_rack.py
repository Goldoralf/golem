# SPDX-License-Identifier: GPL-3.0-or-later
"""La chanson NÉE SUR LE RACK (docs/songs.md §9, VALIDÉ 2026-09-22), et la ligne qui la JOUE.

Ce que ces tests gardent :
  - un id `rs:` est frappé UNE fois et ne change jamais (pas de renommage à l'adoption, §9.3) ;
  - la nature est obligatoire à la création, sans défaut — chez golem.fm une chanson sans nature
    deviendrait une reprise publiable (§9.2) ;
  - une ligne `{band_song}` seule joue TOUTE sa chanson : preset au pied, tempo, arrangement (§9.7) —
    avant, `pid_of` lisait `line.preset` et la bank était vide ;
  - une retouche d'une ligne à chanson va à la CHANSON, ou devient une exception DÉCLARÉE ;
  - on ne perd jamais une référence que golem.fm ne sait pas encore résoudre (fusion, §9.7).
"""
import json

import pytest

from bridge import setlists as SL
from bridge import songs as S


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "SONGS_DIR", str(tmp_path / "songs"))
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path / "setlists"))
    monkeypatch.setattr(SL, "ACTIVE_CFG", str(tmp_path / "active.json"))
    monkeypatch.setattr(SL, "PENDING_DIR", str(tmp_path / ".pending"))
    monkeypatch.setattr(SL, "SNAP_DIR", str(tmp_path / "snapshots"))
    (tmp_path / "songs").mkdir()
    (tmp_path / "setlists").mkdir()
    S._CACHE.clear()
    return tmp_path


def _setlist(dirs, lines, sid="covers"):
    json.dump({"id": sid, "name": "Covers", "rev": 1, "lines": lines}, open(dirs / "setlists" / f"{sid}.json", "w"))
    return sid


# ── la création ──────────────────────────────────────────────────────────────────────────────
def test_une_chanson_nee_ici_porte_un_id_rs_et_le_dit_dans_un_champ():
    d = S.create("Killing in the Name", "cover", band="b_night", preset="riot", bpm=88)
    assert d["id"].startswith("rs:") and len(d["id"]) == 3 + 32
    assert d["born"] == "rack" and d["rev"] == 1 and d["band"] == "b_night"
    assert d["sheet"] == {"preset": "riot", "bpm": 88}
    assert S.load(d["id"])["title"] == "Killing in the Name"


def test_la_nature_est_obligatoire_et_sans_defaut():
    for bad in (None, "", "say later", "reprise"):
        with pytest.raises(ValueError, match="cover"):
            S.create("X", bad)
    with pytest.raises(ValueError, match="title"):
        S.create("  ", "original")


def test_l_id_ne_change_jamais_meme_au_transfert():
    d = S.create("Swerve Lane", "cover", band="b_perso")
    S.update(d["id"], bpm=96, title="Swerve Lane (live)")
    t = S.transfer(d["id"], "b_night")
    assert t["id"] == d["id"] and t["band"] == "b_night" and t["rev"] == 3
    assert S.transfer(d["id"], "b_night") is None                       # déjà là : rien à faire


def test_la_nature_declaree_ne_s_efface_pas():
    d = S.create("Compo", "original")
    assert S.update(d["id"], kind=None)["kind"] == "original"
    assert S.update(d["id"], kind="peut-être")["kind"] == "original"
    assert S.update(d["id"], kind="cover")["kind"] == "cover"


# ── §9.7 : la ligne JOUE sa chanson ─────────────────────────────────────────────────────────
def test_une_ligne_band_song_seule_donne_le_preset_de_sa_chanson(dirs):
    d = S.create("KITN", "cover", preset="riot", bpm=88)
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}, {"id": "l2", "rev": 1, "preset": "soad"}])
    sl = SL.load(sid)
    assert [SL.pid_of(ln) for ln in sl["lines"]] == ["riot", "soad"]
    assert sl["presets"] == ["riot", "soad"]                           # le dérivé aussi (pied, pages)


def test_changer_le_preset_de_la_chanson_change_la_bank(dirs):
    d = S.create("KITN", "cover", preset="riot")
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}])
    S.update(d["id"], preset="riot-live")
    assert SL.pid_of(SL.load(sid)["lines"][0]) == "riot-live"


def test_la_vue_montre_ce_que_la_ligne_joue_sans_jamais_l_ecrire(dirs):
    d = S.create("KITN", "cover", preset="riot", bpm=88, artist="RIOT")
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"], "bpm": 70}])   # 70 = vieille copie
    v = SL.view(SL.load(sid))["lines"][0]
    assert v["title"] == "KITN" and v["bpm"] == 88 and v["preset"] == "riot"
    assert v["song"]["id"] == d["id"] and v["song"]["born"] == "rack"
    raw = json.load(open(dirs / "setlists" / f"{sid}.json"))["lines"][0]
    assert "title" not in raw and raw["bpm"] == 70                     # le fichier n'a pas bougé


def test_le_rappel_joue_le_tempo_et_l_arrangement_de_la_chanson(dirs, monkeypatch):
    from bridge import recall
    from bridge.state import state
    arr = {"type": "arrangement", "id": "arr-song", "params": {"sections": [{"name": "intro", "bars": 8}]}}
    d = S.create("KITN", "cover", preset="riot", bpm=88)
    S.update(d["id"], arrangement=arr, backing="riot_kitn")
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}])
    monkeypatch.setattr(SL, "active_id", lambda: sid)
    line = SL.load(sid)["lines"][0]
    song = recall.song_of_line(line, "riot")
    assert song["bpm"] == 88 and song["title"] == "KITN" and song["arrangement"] is True
    assert song["backing"] == "riot_kitn" and song["band_song"] == d["id"]
    monkeypatch.setattr(state, "song", {**song, "setlist": sid}, raising=False)
    q = recall.effective_preset({"id": "riot", "config": {}})
    assert q["backing"]["songs"] == [{"slug": "riot_kitn"}]          # la backing de la CHANSON (song-backing.md §2)
    assert q["config"]["arr"]["blocks"][0]["params"]["sections"][0]["name"] == "intro"


# ── la setlist ajoute, elle ne fabrique plus (§9.6) ─────────────────────────────────────────
def test_ajouter_des_chansons_du_repertoire(dirs):
    a = S.create("A", "original"); b = S.create("B", "cover")
    sid = _setlist(dirs, [])
    out = SL.add_songs(sid, [a["id"], b["id"], a["id"], "rs:inconnue"])
    assert len(out["added"]) == 2
    assert [x["why"] for x in out["skipped"]] == ["already in this setlist", "unknown song"]
    lines = SL.load(sid)["lines"]
    assert [set(ln) for ln in lines] == [{"id", "rev", "band_song"}] * 2   # rien d'autre sur la ligne
    assert SL.load(sid)["rev"] == 2


def test_une_ligne_libre_devient_une_chanson(dirs):
    arr = {"type": "arrangement", "id": "arr-1", "params": {"sections": []}}
    sid = _setlist(dirs, [{"id": "l1", "rev": 2, "title": "Short Summer", "preset": "velvetine", "bpm": 96,
                           "arrangement": arr}])
    with pytest.raises(ValueError):
        SL.line_to_song(sid, "l1", None)                                # la nature se demande ici
    setl, song = SL.line_to_song(sid, "l1", "cover", band="b_perso")
    assert song["title"] == "Short Summer" and song["sheet"]["bpm"] == 96 and song["sheet"]["preset"] == "velvetine"
    ln = setl["lines"][0]
    assert ln == {"id": "l1", "rev": 3, "band_song": song["id"]}
    assert SL.pid_of(ln) == "velvetine"                                  # et elle joue toujours pareil


# ── une retouche d'une ligne à chanson ──────────────────────────────────────────────────────
def test_retouche_portee_song_va_a_la_chanson(dirs):
    d = S.create("KITN", "cover", preset="riot", bpm=88)
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}])
    SL.update_line(sid, "l1", scope="song", bpm=90)
    assert S.load(d["id"])["sheet"]["bpm"] == 90
    ln = SL.load(sid)["lines"][0]
    assert "bpm" not in ln and "line_overrides" not in ln


def test_retouche_portee_line_devient_une_exception_declaree(dirs):
    d = S.create("KITN", "cover", preset="riot", bpm=88)
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}])
    SL.update_line(sid, "l1", scope="line", bpm=80)
    ln = SL.load(sid)["lines"][0]
    assert ln["bpm"] == 80 and ln["line_overrides"] == ["bpm"]
    assert S.line_sheet(ln)["bpm"] == 80 and S.load(d["id"])["sheet"]["bpm"] == 88
    SL.update_line(sid, "l1", scope="line", bpm=None)                   # vider l'exception
    ln = SL.load(sid)["lines"][0]
    assert "line_overrides" not in ln and S.line_sheet(ln)["bpm"] == 88


# ── on ne perd jamais une référence que l'autre côté ne sait pas résoudre ───────────────────
def test_la_fusion_garde_un_band_song_ne_ici(dirs):
    d = S.create("KITN", "cover", preset="riot")
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}])
    # golem.fm ne connaît pas encore rs:… : sa ligne revient en « pierre tombale », sans band_song
    _, rep = SL.merge_push({"id": sid, "name": "Covers", "rev": 1,
                            "lines": [{"id": "l1", "rev": 2, "title": "KITN"}]})
    ln = SL.load(sid)["lines"][0]
    assert ln["band_song"] == d["id"] and rep["kept_ref"] == ["l1"]


def test_la_fusion_ne_ressuscite_pas_une_reference_venue_du_web(dirs):
    """La garde ne vaut que pour une chanson NÉE ICI : si golem.fm retire le lien d'une des siennes,
    c'est son droit — et c'est `born`, un champ, qui le dit, pas le préfixe."""
    S.save({"id": "bs:42", "rev": 1, "title": "Paper Kite", "kind": "cover", "sheet": {"preset": "cr"}}, bump=False)
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": "bs:42"}])
    SL.merge_push({"id": sid, "name": "Covers", "rev": 1, "lines": [{"id": "l1", "rev": 2, "title": "Other"}]})
    assert "band_song" not in SL.load(sid)["lines"][0]


# ── la synchro d'ici le lot 4 (remarques de golem.fm, 2026-09-22) ───────────────────────────
def test_le_titre_part_sur_le_fil_sans_etre_stocke(dirs):
    d = S.create("KITN", "cover", preset="riot")
    lines = [{"id": "l1", "rev": 1, "band_song": d["id"]}, {"id": "l2", "rev": 1, "band_song": d["id"], "title": "KITN (live)"},
             {"id": "l3", "rev": 1, "title": "Invité"}]
    out = S.wire_titles(lines)
    assert [x.get("title") for x in out] == ["KITN", "KITN (live)", "Invité"]
    assert "title" not in lines[0]                                     # l'original n'est pas touché


def test_a_rev_egal_une_copie_resolue_n_est_pas_une_divergence(dirs):
    """golem.fm pousse des lignes RÉSOLUES (titre, preset, tempo, slug) ; le rack stocke la ligne nue.
    Comparer les copies faisait un `resend` à chaque push venu du web."""
    S.save({"id": "bs:42", "rev": 1, "title": "Paper Kite", "kind": "cover", "sheet": {"preset": "cr", "bpm": 118}}, bump=False)
    sid = _setlist(dirs, [{"id": "l1", "rev": 3, "band_song": "bs:42"}])
    _, rep = SL.merge_push({"id": sid, "name": "Covers", "rev": 1, "lines": [
        {"id": "l1", "rev": 3, "band_song": "bs:42", "title": "Paper Kite", "preset": "cr", "bpm": 118,
         "song_slug": "glass_lanterns_paper_kite"}]})
    assert rep["kept"] == ["l1"] and "l1" not in rep["resend"]


def test_a_rev_egal_une_EXCEPTION_differente_reste_une_divergence(dirs):
    S.save({"id": "bs:42", "rev": 1, "title": "Paper Kite", "kind": "cover", "sheet": {"bpm": 118}}, bump=False)
    sid = _setlist(dirs, [{"id": "l1", "rev": 3, "band_song": "bs:42", "bpm": 108, "line_overrides": ["bpm"]}])
    _, rep = SL.merge_push({"id": sid, "name": "Covers", "rev": 1, "lines": [
        {"id": "l1", "rev": 3, "band_song": "bs:42", "bpm": 104, "line_overrides": ["bpm"]}]})
    assert "l1" in rep["resend"] and SL.load(sid)["lines"][0]["bpm"] == 108


def test_la_pierre_tombale_de_notre_chanson_ne_relance_pas_de_renvoi(dirs):
    d = S.create("KITN", "cover", preset="riot")
    sid = _setlist(dirs, [{"id": "l1", "rev": 2, "band_song": d["id"]}])
    _, rep = SL.merge_push({"id": sid, "name": "Covers", "rev": 1,
                            "lines": [{"id": "l1", "rev": 2, "preset": None, "title": "KITN"}]})
    assert rep["kept"] == ["l1"] and "l1" not in rep["resend"]
    assert SL.load(sid)["lines"][0] == {"id": "l1", "rev": 2, "band_song": d["id"]}


# ── lot 4 : la MONTÉE vers golem.fm (contrat de leur POST /api/ext/golem/songs, 2026-09-22) ──
def test_la_forme_envoyee_suit_leur_contrat():
    d = S.create("KITN", "cover", band="b_perso", preset="riot", bpm=88, song_slug="riot_kitn")
    w = S.wire_song(d)
    assert w["bpm"] == 88 and "bpm" not in w["sheet"] and w["sheet"]["preset"] == "riot"
    assert w["born"] == "rack" and w["band"] == "b_perso" and w["kind"] == "cover" and w["song_slug"] == "riot_kitn"
    assert S.wire_song({**S.load(d["id"]), "born": None})["born"] == "web"


def test_une_chanson_monte_puis_repart_si_elle_change():
    d = S.create("KITN", "cover", band="b_perso")
    assert [x["id"] for x in S.pending()[0]] == [d["id"]]
    S.apply_ack({"applied": [{"id": d["id"], "status": "created", "band_song": d["id"], "rev": 1}]}, {d["id"]: 1})
    assert S.pending()[0] == [] and S.sync_of(S.load(d["id"]))["state"] == "synced"
    S.update(d["id"], bpm=90)
    assert [x["id"] for x in S.pending()[0]] == [d["id"]]


def test_un_refus_est_dit_et_ne_repart_que_si_la_chanson_change():
    d = S.create("KITN", "cover", band="b_night")
    S.apply_ack({"rejected": [{"id": d["id"], "why": "not a member of Night Shift"}]}, {d["id"]: 1})
    s = S.sync_of(S.load(d["id"]))
    assert s == {"state": "rejected", "why": "not a member of Night Shift"}
    assert S.pending()[0] == []
    S.transfer(d["id"], "b_perso")
    assert [x["id"] for x in S.pending()[0]] == [d["id"]]


def test_sans_nature_ou_sans_espace_elle_reste_au_rack_et_le_dit():
    S.save({"id": "rs:" + "a" * 32, "rev": 1, "title": "Vieille", "born": "rack", "band": "b_perso", "sheet": {}}, bump=False)
    S.save({"id": "rs:" + "b" * 32, "rev": 1, "title": "Sans espace", "born": "rack", "kind": "original", "sheet": {}}, bump=False)
    todo, blocked = S.pending()
    assert todo == [] and sorted(b["why"] for b in blocked) == ["band required", "kind is required: original or cover"]


def test_une_chanson_recue_est_a_jour_jusqu_a_ce_qu_on_la_retouche():
    S.merge_push([{"id": "bs:42", "rev": 5, "title": "Paper Kite", "kind": "cover", "band": "b_night", "sheet": {"bpm": 118}}])
    assert S.sync_of(S.load("bs:42"))["state"] == "synced" and S.pending()[0] == []
    S.update("bs:42", bpm=120)
    assert [x["id"] for x in S.pending()[0]] == ["bs:42"]


def test_la_chanson_part_AVANT_la_setlist_qui_la_cite(dirs, monkeypatch):
    from bridge import golemfm as M
    calls = []

    def fake_req(path, body=None, token=None, **kw):
        calls.append(path)
        if path == "/api/ext/golem/songs":
            return 200, {"ok": True, "applied": [{"id": x["id"], "status": "created"} for x in body["songs"]], "rejected": []}
        return 200, {"ok": True}
    monkeypatch.setattr(M, "_cfg", lambda: ("http://golem.test", "tok"))
    monkeypatch.setattr(M, "_req", fake_req)
    d = S.create("KITN", "cover", band="b_perso", preset="riot")
    sid = _setlist(dirs, [{"id": "l1", "rev": 1, "band_song": d["id"]}])
    M.push_setlist(sid, delay=0)
    M._setlist_timers[sid].join(5)
    assert calls == ["/api/ext/golem/songs", "/api/ext/golem/setlists"]
    assert S.sync_of(S.load(d["id"]))["state"] == "synced"
