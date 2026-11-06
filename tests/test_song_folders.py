# SPDX-License-Identifier: GPL-3.0-or-later
"""Les dossiers de chansons (docs/song-folders.md) : lus sur place, jamais écrits ; un index qui est un cache ; un
dossier absent n'efface rien ; une écriture adopte d'abord."""
import json
import os

import pytest

from bridge import config as C
from bridge import golemfile as G
from bridge import inventory as I
from bridge import golemfm as M
from bridge import setlists as SL
from bridge import song_folders as SF
from bridge import songs as S

SID = "rs:" + "f" * 32
SID2 = "rs:" + "e" * 32


def _golem(path, sid=SID, title="Paper Kite", chart=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if chart:
        members = {"chart/song.gsx": json.dumps({"v": 1, "title": title, "key": "C", "sections": {}}).encode()}
        man = {"type": "song", "id": sid, "title": title}
    else:
        members = {"audio/original.flac": b"fLaC" + b"\1" * 400, "scores/song.gp": b"BCFZ" + b"\0" * 64,
                   "lyrics/song.lrc": b"[00:01.00]hello"}
        man = {"type": "song", "id": sid, "title": title, "artist": "Glass Lanterns", "kind": "cover"}
    G.write(path, man, members)
    return path


@pytest.fixture
def lib(tmp_path):
    d = tmp_path / "music"
    d.mkdir()
    return str(d)


def _snapshot(d):
    """Tout ce que porte le dossier : noms, tailles, dates — pour prouver qu'on n'y a RIEN écrit."""
    out = {}
    for r, ds, fs in os.walk(d):
        for f in fs + ds:
            p = os.path.join(r, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


# ── la liste ──

def test_un_dossier_trop_large_ou_celui_du_golem_est_refuse(lib):
    with pytest.raises(SF.FolderError, match="golem's own"):
        SF.add(C.SONGS_DIR)
    with pytest.raises(SF.FolderError, match="not found"):
        SF.add(lib + "/nope")
    with pytest.raises(SF.FolderError, match="too wide"):
        SF.add("/")
    SF.add(lib)
    with pytest.raises(SF.FolderError, match="already"):
        SF.add(lib)
    os.makedirs(os.path.join(lib, "sub"))
    with pytest.raises(SF.FolderError, match="overlaps"):
        SF.add(os.path.join(lib, "sub"))


# ── l'index ──

def test_l_index_lit_le_manifeste_et_rien_n_est_ecrit_dans_le_dossier(lib):
    _golem(os.path.join(lib, "a", "kite.golem"))
    with open(os.path.join(lib, "notes.mp3"), "wb") as f:
        f.write(b"x")
    SF.add(lib)
    before = _snapshot(lib)
    fs = SF.scan_folder(lib)
    assert fs["state"] == "online" and fs["counts"] == {"song": 1} and fs["other_files"] == 1
    got = SF.entries()
    assert got["total"] == 1 and got["items"][0]["title"] == "Paper Kite" and not got["items"][0]["adopted"]
    assert _snapshot(lib) == before                                   # §2.2 : un dossier de chansons ne s'écrit pas


def test_un_passage_ne_relit_que_ce_qui_a_change(lib, monkeypatch):
    p = _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    reads = []
    real = SF._entry_of
    monkeypatch.setattr(SF, "_entry_of", lambda *a: reads.append(a[0]) or real(*a))
    SF.scan_folder(lib)
    assert reads == []                                                # inchangé : des stat, rien d'autre
    _golem(p, title="Paper Kite (live)")
    SF.scan_folder(lib)
    assert reads == [p]


def test_un_fichier_illisible_reste_dans_l_index_avec_sa_raison(lib):
    with open(os.path.join(lib, "casse.golem"), "wb") as f:
        f.write(b"not a zip")
    SF.add(lib)
    fs = SF.scan_folder(lib)
    assert fs["bad"] == 1
    assert SF.overview()["folders"][0]["bad_files"][0]["file"] == "casse.golem"
    assert SF.entries()["total"] == 0


def test_un_dossier_absent_n_efface_rien(lib, tmp_path):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    moved = str(tmp_path / "unplugged")
    os.rename(lib, moved)                                             # le disque est débranché
    fs = SF.scan_folder(lib)
    assert fs["state"] == "offline"
    e = SF.entries()["items"]
    assert len(e) == 1 and e[0]["state"] == "unavailable"             # gardée, marquée
    assert SF.path_of(SID) is None                                    # mais pas lisible
    os.rename(moved, lib)                                             # rebranché
    SF.scan_folder(lib)
    assert SF.entries()["items"][0]["state"] == "ok" and SF.path_of(SID)


def test_un_fichier_vraiment_parti_quitte_l_index(lib):
    p = _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    os.unlink(p)
    SF.scan_folder(lib)                                               # lu EN ENTIER, et absent : parti
    assert SF.entries()["total"] == 0


def test_deux_copies_du_meme_id_font_une_entree(lib):
    _golem(os.path.join(lib, "a", "kite.golem"))
    _golem(os.path.join(lib, "b", "kite copy.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    got = SF.entries()
    assert got["total"] == 1 and len(got["items"][0]["copies"]) == 2


def test_l_index_efface_se_refait(lib):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    os.unlink(SF._index_path())
    SF.reset()
    assert SF.entries()["total"] == 0
    SF.scan_folder(lib)
    assert SF.entries()["total"] == 1


# ── lire sur place ──

def test_une_chanson_de_dossier_se_lit_et_se_joue_sur_place(lib):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    assert not os.path.exists(S._path(SID))
    d = S.load(SID)
    assert d and d["title"] == "Paper Kite"
    w = S.workdir(SID)                                                # le cache de travail, chez le golem
    assert w and w.startswith(C.SONGS_DIR) and os.path.isfile(os.path.join(w, "scores", "song.gp"))
    assert open(os.path.join(w, ".from")).read().startswith("folder:")
    fs = S.files_summary(SID)
    assert fs["folder"]["folder"] == lib and fs["category"] == "song"
    assert S.list_all() == []                                         # le répertoire du golem n'en a pas


# ── adopter ──

def test_modifier_la_fiche_adopte_d_abord_et_le_dossier_ne_bouge_pas(lib):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    before = _snapshot(lib)
    d = S.update(SID, bpm=120)
    assert d["sheet"]["bpm"] == 120
    assert os.path.isfile(S._path(SID))                               # copiée dans le golem…
    assert "audio/original.flac" in G.verify(S._path(SID), hashes=False)["present"]   # …avec ses médias
    assert _snapshot(lib) == before                                   # et le dossier n'a pas bougé
    assert SF.entries()["total"] == 0                                 # adoptée : la liste du golem la montre
    assert SF.entries(include_adopted=True)["items"][0]["adopted"]


def test_entrer_dans_une_setlist_adopte(lib):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    sl = SL.save({"id": "test-folders", "name": "t", "lines": []})
    out = SL.add_songs(sl["id"], [SID])
    try:
        assert out["added"] and out["adopted"] == [SID]
        assert os.path.isfile(S._path(SID))
    finally:
        os.unlink(SL._path(sl["id"]))


def test_un_standard_de_dossier_est_au_catalogue_puis_s_adopte(lib):
    from bridge import standards as STD
    p = _golem(os.path.join(lib, "autumn-leaves.golem"), sid=SID2, title="Autumn Leaves", chart=True)   # le slug = le nom
    SF.add(lib)
    SF.scan_folder(lib)
    STD.invalidate()
    got = [s for s in STD.list_standards() if s["slug"] == "autumn-leaves"]
    assert got and got[0]["folder"] == p and got[0]["synced"] is False
    r = SF.adopt(p)
    assert r["category"] == "standard"
    assert os.path.isfile(os.path.join(STD.GOLEM_DIR, "autumn-leaves.golem"))
    STD.invalidate()
    assert "folder" not in [s for s in STD.list_standards() if s["slug"] == "autumn-leaves"][0]


# ── l'inventaire golem.fm ──

@pytest.fixture
def fm(monkeypatch):
    calls = []

    def req(path, body=None, token=None, method=None, **kw):
        calls.append((method, path, body))
        ids = {c["id"]: c["etag"] for c in (body or {}).get("cards", []) + (body or {}).get("upsert", [])}
        return 200, {"rev": ids}
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    monkeypatch.setattr(M, "_req", req)
    return calls


def test_les_chansons_des_dossiers_montent_marquees_folder(lib, fm):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    cards, complete = I.collect()
    assert complete and cards[SID]["where"] == "folder"
    SF.set_show(lib, False)                                           # exclu : ses titres ne quittent pas la machine
    cards, _ = I.collect()
    assert SID not in cards


def test_un_dossier_debranche_n_envoie_aucun_retrait(lib, fm, tmp_path):
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    assert I.publish()["ok"] and fm[-1][0] == "PUT"
    os.rename(lib, str(tmp_path / "away"))
    SF.scan_folder(lib)
    r = I.publish()
    assert r.get("unchanged") or r.get("remove") == 0                 # incomplète : la carte reste chez golem.fm


def test_un_dossier_retire_quitte_la_liste_sans_toucher_aux_fichiers(lib):
    p = _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    SF.scan_folder(lib)
    assert SF.remove(lib)
    assert os.path.isfile(p) and SF.entries()["total"] == 0 and SF.folders() == []


def test_un_dossier_retire_pendant_son_passage_ne_revient_pas(lib, monkeypatch):
    """Vu le 2026-10-09 : un NAS en cours d'indexation, retiré de la liste — le passage finissait et le réécrivait."""
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib)
    real = SF._entry_of

    def retire_en_route(*a):
        SF.remove(lib)                                # l'utilisateur retire le dossier pendant le passage
        return real(*a)
    monkeypatch.setattr(SF, "_entry_of", retire_en_route)
    assert SF.scan_folder(lib) == {"state": "removed"}
    assert SF.entries()["total"] == 0 and SF._index()["folders"] == {} and SF._index()["entries"] == {}


def test_une_racine_de_disque_ou_un_parent_du_dossier_perso_est_trop_large(lib):
    for p in (os.path.abspath(os.sep), os.path.dirname(os.path.expanduser("~")), os.path.expanduser("~").upper()
              if os.name == "nt" else os.path.expanduser("~")):
        with pytest.raises(SF.FolderError, match="too wide"):
            SF.check_folder(p)


# ── ce qu'un dossier apporte (§2.9, 2026-10-17) ──

def test_un_dossier_type_filtre_et_compte_ce_qu_il_ignore(lib):
    _golem(os.path.join(lib, "kite.golem"))                                           # une chanson
    _golem(os.path.join(lib, "autumn-leaves.golem"), sid=SID2, title="Autumn Leaves", chart=True)   # un standard
    SF.add(lib)
    SF.scan_folder(lib)
    cats = lambda: sorted(e["category"] for e in SF.entries()["items"])             # noqa: E731
    assert cats() == ["song", "standard"]                                           # Auto : tout, rangé d'après le contenu
    row = SF.overview()["folders"][0]
    assert row["kind"] == "auto" and row["ignored"] == 0 and row["suggest"] is None   # deux natures : rien à suggérer
    assert SF.set_kind(lib, "song")
    assert cats() == ["song"] and SF.standards_entries() == [] and not SF.has_standards()
    assert SF.overview()["folders"][0]["ignored"] == 1                               # le standard : ignoré, et DIT
    assert SF.set_kind(lib, "standard")
    assert cats() == ["standard"] and [s for s, _, _ in SF.standards_entries()] == ["autumn-leaves"]
    assert not SF.set_kind(lib, "karaoke") and not SF.set_kind("/nulle/part", "song")


def test_un_dossier_d_une_seule_nature_le_suggere(lib):
    _golem(os.path.join(lib, "autumn-leaves.golem"), sid=SID2, title="Autumn Leaves", chart=True)
    SF.add(lib)
    SF.scan_folder(lib)
    assert SF.overview()["folders"][0]["suggest"] == "standard"
    SF.set_kind(lib, "standard")
    assert SF.overview()["folders"][0]["suggest"] is None                         # réglé : plus rien à suggérer


def test_un_fichier_garde_sa_nature_quel_que_soit_le_dossier(lib):
    # un dossier « Vocals » qui porte une CHANSON ne la fait pas karaoké : elle est ignorée, pas reclassée
    _golem(os.path.join(lib, "kite.golem"))
    SF.add(lib, kind="vocals")
    SF.scan_folder(lib)
    assert SF.entries()["items"] == [] and SF.overview()["folders"][0]["ignored"] == 1
    assert SF.entries(include_adopted=True)["total"] == 0
