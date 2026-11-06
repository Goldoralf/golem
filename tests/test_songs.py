# SPDX-License-Identifier: GPL-3.0-or-later
"""LE RÉPERTOIRE — la chanson comme objet (docs/songs.md).

Ce que ces tests gardent, et qui s'est déjà cassé ailleurs :
  - trois formes d'identité et pas une de plus : `bs:` (née chez golem.fm), `rs:` (née sur un rack) et
    `us:` (perso, née chez golem.fm, 2026-10-08), docs/songs.md §9.3 — un quatrième format serait un
    effet de bord, pas une décision ;
  - la fiche et la ligne restent comparables : même nettoyeur, jamais une copie ;
  - `pulled_at` reste HORS du corps comparé — sinon boucle de `resend` sans fin, le piège que
    golem.fm avait trouvé pour `song_setlists` avant le premier push.
"""
import json
import os

import pytest

from bridge import songs as S


@pytest.fixture(autouse=True)
def _dir(tmp_path, monkeypatch):
    d = str(tmp_path / "songs")
    monkeypatch.setattr(S.C, "SONGS_DIR", d)
    os.makedirs(d, exist_ok=True)
    return d


def _song(sid="bs:42", rev=1, **kw):
    return {"id": sid, "rev": rev, "band": "b_night", "title": "Paper Kite",
            "artist": "Glass Lanterns", "kind": "cover",
            "sheet": {"preset": "paper-kite", "bpm": 118, "tuning": "E♭"}, **kw}


# ── l'identité ───────────────────────────────────────────────────────────────────────────────
def test_trois_formes_d_identite_et_pas_une_de_plus():
    assert S.clean(_song("bs:42")) is not None
    assert S.clean(_song("rs:9f3c0a1b2c3d4e5f60718293a4b5c6d7")) is not None      # née sur un rack (§9.3)
    assert S.clean(_song("us:9f3c0a1b2c3d4e5f60718293a4b5c6d7")) is not None      # perso, née chez golem.fm (2026-10-08)
    for bad in ("r:covers:ab12", "42", "paper-kite", "bs:", "rs:", "xs:1", "", None):
        assert S.clean(_song(bad)) is None, bad


def test_un_id_hors_des_deux_formes_est_refuse():
    """Accepter un id maison créerait un TROISIÈME format sans que personne l'ait décidé."""
    with pytest.raises(ValueError, match="song id"):
        S.save({"id": "mine-1", "title": "X"})


def test_un_id_devient_un_nom_de_fichier_portable():
    """Les deux-points sont légaux sur ext4, pas sur la FAT d'une clé de sauvegarde."""
    S.save(_song("bs:42"), bump=False)
    assert os.path.exists(os.path.join(S.C.SONGS_DIR, "bs-42.golem"))


def test_une_ecriture_invalide_le_cache_meme_si_mtime_reste_identique():
    path = os.path.join(S.C.SONGS_DIR, "bs-42.golem")
    stamp = 1_700_000_000_000_000_000
    S.save(_song(), bump=False)
    os.utime(path, ns=(stamp, stamp))
    assert S.load("bs:42")["title"] == "Paper Kite"
    S.save(_song(rev=2, title="Paper Kite live"), bump=False)
    os.utime(path, ns=(stamp, stamp))
    assert S.load("bs:42")["title"] == "Paper Kite live"


# ── la fiche ─────────────────────────────────────────────────────────────────────────────────
def test_la_fiche_porte_exactement_les_champs_de_portee():
    assert S.SHEET_FIELDS == ("preset", "bpm", "tuning", "capo", "note", "backing", "arrangement", "blocks")


def test_la_fiche_passe_par_le_nettoyeur_des_lignes():
    """Un backing en dict s'aplatit, un bpm hors bornes tombe, un champ inconnu est jeté — les
    mêmes règles que sur une ligne, parce que c'est le MÊME code."""
    d = S.clean(_song(sheet={"preset": "p", "bpm": 900, "backing": {"slug": "x"}, "inconnu": 1}))
    assert d["sheet"]["backing"] == "x"
    assert "bpm" not in d["sheet"] and "inconnu" not in d["sheet"]


def test_kind_est_declare_jamais_devine():
    assert "kind" not in S.clean(_song(kind="peut-être"))
    assert S.clean(_song(kind="original"))["kind"] == "original"



def test_une_demo_de_golem_fm_se_lit_et_ne_s_ecrit_jamais():
    S.save(_song())
    assert "demo" not in S.load("bs:42")                                  # absent = vendu ou inconnu
    from bridge import golemfile as G
    G.rewrite_manifest(S.source_path("bs:42"), lambda m: m.update(release={"kind": "demo"}))
    assert S.load("bs:42")["demo"] is True
    S.save(S.load("bs:42"))                                               # une écriture du rack la garde, sans l'écrire
    m = G.read_manifest(S.source_path("bs:42"))
    assert m["release"] == {"kind": "demo"} and "demo" not in m and S.load("bs:42")["demo"] is True


# ── rev ──────────────────────────────────────────────────────────────────────────────────────
def test_une_ecriture_locale_bumpe_le_rev():
    S.save(_song(rev=3), bump=False)
    assert S.update("bs:42", bpm=120)["rev"] == 4
    assert S.load("bs:42")["sheet"]["bpm"] == 120


def test_une_reception_ne_bumpe_pas():
    """Incrémenter à la réception ferait croire à une modification locale, et la chanson
    repartirait en boucle."""
    assert S.save(_song(rev=7), bump=False)["rev"] == 7


def test_une_valeur_vide_retire_le_champ():
    """« pas de capo » n'est pas « capo 0 »."""
    S.save(_song(sheet={"preset": "p", "capo": 3}), bump=False)
    assert "capo" not in S.update("bs:42", capo=None)["sheet"]


# ── la fusion ────────────────────────────────────────────────────────────────────────────────
def test_une_chanson_inconnue_est_ajoutee():
    out = S.merge_push([_song()])
    assert out["added"] == ["bs:42"] and S.load("bs:42")


def test_un_rev_superieur_gagne():
    S.save(_song(rev=2), bump=False)
    S.merge_push([_song(rev=5, title="Autre titre")])
    assert S.load("bs:42")["title"] == "Autre titre"


def test_a_rev_EGAL_et_corps_different_LE_RACK_GAGNE():
    """Son état a réellement joué : il repart au prochain push, il n'est pas écrasé."""
    S.save(_song(rev=4, title="Le mien"), bump=False)
    out = S.merge_push([_song(rev=4, title="Le leur")])
    assert out["resend"] == ["bs:42"]
    assert S.load("bs:42")["title"] == "Le mien"


def test_pulled_at_est_hors_du_corps_compare():
    """Il change sans que la chanson change : le comparer produirait un `resend` sans fin — le
    piège trouvé pour `song_setlists` avant le premier push."""
    S.save({**_song(rev=4), "pulled_at": "2026-01-01T00:00:00"}, bump=False)
    out = S.merge_push([_song(rev=4)])
    assert out["kept"] == ["bs:42"] and out["resend"] == []


def test_complete_retire_les_absentes_sinon_jamais():
    S.save(_song("bs:1"), bump=False); S.save(_song("bs:2"), bump=False)
    assert S.merge_push([_song("bs:1")])["removed"] == []       # lot partiel : rien ne disparaît
    assert S.load("bs:2")
    assert S.merge_push([_song("bs:1")], complete=True)["removed"] == ["bs:2"]


def test_complete_ne_touche_pas_un_autre_espace():
    """Un rack sert plusieurs groupes : le lot de l'un ne vide pas le répertoire de l'autre."""
    S.save({**_song("bs:1"), "band": "b_a"}, bump=False)
    S.save({**_song("bs:2"), "band": "b_b"}, bump=False)
    S.merge_push([_song("bs:1")], band="b_a", complete=True)
    assert S.load("bs:2")


# ── la ligne ─────────────────────────────────────────────────────────────────────────────────
def test_la_fiche_d_une_ligne_vient_de_sa_chanson():
    S.save(_song(), bump=False)
    assert S.line_sheet({"band_song": "bs:42"})["bpm"] == 118


def test_une_COPIE_sur_la_ligne_ne_surcharge_pas_la_chanson():
    """§9.7 (2026-09-22) : golem.fm pousse des lignes RÉSOLUES, qui portent une copie de la fiche. Avec
    l'ancienne règle « la ligne gagne champ par champ », une retouche de la chanson au rack ne jouait
    jamais : la vieille copie gagnait. Seule une exception DÉCLARÉE surcharge."""
    S.save(_song(), bump=False)
    out = S.line_sheet({"band_song": "bs:42", "bpm": 108})
    assert out["bpm"] == 118 and out["preset"] == "paper-kite"


def test_une_exception_DECLAREE_surcharge_la_chanson():
    S.save(_song(), bump=False)
    out = S.line_sheet({"band_song": "bs:42", "bpm": 108, "line_overrides": ["bpm"]})
    assert out["bpm"] == 108 and out["preset"] == "paper-kite"


def test_une_ligne_SANS_chanson_est_maitresse_de_son_contenu():
    """A cappella, invité : rien à hériter, et surtout rien à chercher."""
    assert S.line_sheet({"bpm": 100}) == {"bpm": 100}


def test_une_chanson_absente_ne_vide_pas_la_ligne():
    """Setlist reçue avant son répertoire : la ligne joue ce qu'elle porte."""
    assert S.line_sheet({"band_song": "bs:999", "bpm": 100})["bpm"] == 100


# ── le lot à pousser ─────────────────────────────────────────────────────────────────────────
def test_le_lot_pousse_est_complet_et_sans_trace_locale():
    S.save(_song(), bump=False)
    body = S.push_body(band="b_night")
    assert body["complete"] is True and len(body["songs"]) == 1
    assert "pulled_at" not in body["songs"][0]


def test_un_fichier_casse_n_emporte_pas_le_repertoire():
    S.save(_song("bs:1"), bump=False)
    with open(os.path.join(S.C.SONGS_DIR, "bs-2.golem"), "wb") as fh:
        fh.write(b"PK broken")
    assert [d["id"] for d in S.list_all()] == ["bs:1"]


# ── le récepteur du canal de jobs (docs/songs.md §7) ────────────────────────────────────────
def test_le_job_song_push_fusionne_le_lot():
    """Le récepteur existe AVANT son émetteur : golem.fm n'a pas encore de route qui liste un
    répertoire, et leur moitié a besoin d'une cible."""
    from bridge import tones_jobs as TJ
    out = TJ._song_push({"songs": [_song("bs:9", title="Neuve")], "band": "b_night"})
    assert out["added"] == ["bs:9"]
    assert S.load("bs:9")["band"] == "b_night"


def test_le_job_refuse_un_lot_mal_forme():
    from bridge import tones_jobs as TJ
    with pytest.raises(RuntimeError, match="song-push"):
        TJ._song_push({"band": "b_night"})


# ── la chanson EST un `.golem` (plan-song-sharing.md lot 1, 2026-10-08) ─────────────────────
def test_la_chanson_est_un_fichier_golem_verifiable():
    """Identité au premier niveau du manifeste, synchro sous `repertoire` (jamais `rev` au premier
    niveau : le format le réserve à la révision signée), fiche dans `sheet.json`."""
    from bridge import golemfile as G
    S.save(_song(), bump=False)
    p = os.path.join(S.C.SONGS_DIR, "bs-42.golem")
    rep = G.verify(p)
    m = rep["manifest"]
    assert (m["format"], m["type"], m["id"], m["title"], m["kind"]) == ("golem/1", "song", "bs:42", "Paper Kite", "cover")
    assert "rev" not in m and m["repertoire"]["rev"] == 1 and m["repertoire"]["band"] == "b_night"
    assert json.loads(G.read_member(p, "sheet.json")) == {"preset": "paper-kite", "bpm": 118, "tuning": "E♭"}


def test_les_autres_membres_survivent_a_une_retouche_de_fiche():
    """Une retouche réécrit `sheet.json` ; un stem déjà rangé est RECOPIÉ, pas perdu ni réencodé."""
    from bridge import golemfile as G
    S.save(_song(), bump=False)
    p = os.path.join(S.C.SONGS_DIR, "bs-42.golem")
    G.replace(p, None, {"stems/drums.flac": b"fLaC" + b"\1" * 300})
    S.update("bs:42", capo=2)
    assert G.read_member(p, "stems/drums.flac") == b"fLaC" + b"\1" * 300
    assert S.load("bs:42")["sheet"]["capo"] == 2 and S.load("bs:42")["rev"] == 2
    G.verify(p)


def test_migration_des_anciens_json(tmp_path, monkeypatch):
    """Un ancien `songs/<id>.json` devient `.golem` au premier accès, relu identique ; le JSON est RANGÉ
    dans `.json-migrated/`, jamais effacé. Un JSON cassé reste en place."""
    d = str(tmp_path / "old")
    os.makedirs(d)
    monkeypatch.setattr(S.C, "SONGS_DIR", d)
    with open(os.path.join(d, "rs-abc.json"), "w") as fh:
        json.dump(_song("rs:abc", rev=7, pulled_at="2026-09-22T10:00:00"), fh)
    with open(os.path.join(d, "bs-9.json"), "w") as fh:
        fh.write("{cassé")
    with open(os.path.join(d, ".sync.json"), "w") as fh:
        fh.write("{}")
    got = S.load("rs:abc")
    assert got["rev"] == 7 and got["pulled_at"] == "2026-09-22T10:00:00" and got["sheet"]["bpm"] == 118
    assert os.path.exists(os.path.join(d, "rs-abc.golem"))
    assert os.path.exists(os.path.join(d, ".json-migrated", "rs-abc.json"))
    assert not os.path.exists(os.path.join(d, "rs-abc.json"))
    assert os.path.exists(os.path.join(d, "bs-9.json")) and os.path.exists(os.path.join(d, ".sync.json"))
    assert [x["id"] for x in S.list_all()] == ["rs:abc"]


def test_le_cache_de_travail_suit_le_fichier():
    S.save(_song(), bump=False)
    w = S.workdir("bs:42")
    assert json.load(open(os.path.join(w, "sheet.json")))["bpm"] == 118
    S.update("bs:42", bpm=120)
    assert json.load(open(os.path.join(S.workdir("bs:42"), "sheet.json")))["bpm"] == 120
