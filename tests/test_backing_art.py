# SPDX-License-Identifier: GPL-3.0-or-later
"""Les images de la page Tracks ▸ Backings servies PAR LE RACK (2026-10-16) : la pochette du cache, sinon celle du `.golem`
de la chanson (copiée une fois dans le cache, le `.golem` jamais réécrit), la photo d'un autre morceau du même artiste —
hors ligne — et golem.fm seulement en dernier."""
import json
import os
import zipfile

import pytest

from bridge import golemfm as M
from bridge import songs as S

JPG = b"\xff\xd8\xff\xe0fake-jpeg"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    bk, sg = tmp_path / "assets" / "backing", tmp_path / "songs"
    bk.mkdir(parents=True)
    sg.mkdir()
    monkeypatch.setattr(M.C, "ROOT", str(tmp_path))
    monkeypatch.setattr(M.C, "BACKING_DIR", str(bk))
    monkeypatch.setattr(M.C, "SONGS_DIR", str(sg))
    monkeypatch.setattr(M, "_ZIP_ART", {})
    lib = {}

    def golem(sid, title, artist, song_slug=None, cover=True, members=None, files=None):
        p = sg / (S._safe(sid) + ".golem")
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("golem.json", json.dumps({"files": files or {}}))
            if cover:
                zf.writestr("art/cover.jpg", JPG + sid.encode())
            for name, data in (members or {}).items():
                zf.writestr(name, data)
        lib[sid] = {"id": sid, "title": title, "artist": artist, "song_slug": song_slug}
        return p

    def cache(slug, meta=None, stems=True, files=()):
        d = bk / slug
        d.mkdir()
        if meta is not None:
            (d / "meta.json").write_text(json.dumps(meta))
        if stems:
            (d / "guitar.mp3").write_bytes(b"x")
        for f in files:
            (d / f).write_bytes(JPG + f.encode())
        return d

    monkeypatch.setattr(S, "list_all", lambda: list(lib.values()))
    monkeypatch.setattr(S, "load", lambda sid: lib.get(sid))
    monkeypatch.setattr(S, "source_path", lambda sid: str(sg / (S._safe(sid) + ".golem")))
    calls = []

    def req(path, **kw):                             # golem.fm : hors ligne, sauf si un test le remplace
        calls.append(path)
        return 0, None
    monkeypatch.setattr(M, "_req", req)
    monkeypatch.setattr(M, "_cfg", lambda: ("https://golem.fm", "tok"))
    return type("T", (), {"golem": staticmethod(golem), "cache": staticmethod(cache), "bk": bk, "sg": sg,
                          "calls": calls, "lib": lib})


def test_le_fichier_du_cache_passe_en_premier(tree):
    tree.cache("ray_stone_warm_light", {"title": "Warm Light", "artist": "Ray Stone"},
               files=("art-cover.jpg", "art-photo.jpg"))
    assert M.asset("ray_stone_warm_light", "cover").replace("\\", "/").endswith("ray_stone_warm_light/art-cover.jpg")
    assert M.asset("ray_stone_warm_light", "photo").replace("\\", "/").endswith("ray_stone_warm_light/art-photo.jpg")
    assert tree.calls == []                          # rien demandé à golem.fm


def test_la_pochette_du_golem_est_copiee_une_fois_et_le_golem_reste_intact(tree, monkeypatch):
    g = tree.golem("us:abc", "Black", "Pearl Jam", song_slug="pearl_jam_black")
    before = (g.read_bytes(), os.stat(g).st_mtime_ns)
    tree.cache("k-4", {"title": "Black"})            # une entrée k-* : pas d'artiste, titre unique au golem
    p = M.asset("k-4", "cover")
    assert p == str(tree.bk / "k-4" / "art-cover.jpg")
    assert open(p, "rb").read() == JPG + b"us:abc"
    assert (g.read_bytes(), os.stat(g).st_mtime_ns) == before
    # deuxième affichage : le cache suffit, le .golem n'est plus ouvert
    monkeypatch.setattr(M, "_golem_art", lambda d, kind: pytest.fail("relu"))
    assert M.asset("k-4", "cover") == p
    assert tree.calls == []


def test_rapprochement_par_song_slug_puis_titre_et_artiste(tree):
    tree.golem("us:1", "Paper Kite", "Glass Lanterns", song_slug="glass_lanterns_paper_kite")
    tree.golem("us:2", "Emergence", "Hollow Choir")
    tree.golem("us:3", "Black", "Pearl Jam")
    tree.golem("us:4", "Black", "Sevendust")
    assert M.lib_match("glass_lanterns_paper_kite", {})["id"] == "us:1"     # même sans meta : le song_slug
    assert M.lib_match("x", {"title": "EMERGENCE!", "artist": "hollow choir"})["id"] == "us:2"
    assert M.lib_match("x", {"title": "Emergence", "artist": "Someone Else"}) is None
    assert M.lib_match("x", {"title": "Black", "artist": "Pearl Jam"})["id"] == "us:3"
    assert M.lib_match("x", {"title": "Black"}) is None                         # deux « Black » : on ne choisit pas
    assert M.lib_match("x", {}) is None


def test_la_photo_vient_d_un_morceau_du_meme_artiste(tree):
    tree.golem("bs:2", "Annie-Dog", "Glass Lanterns", song_slug="glass_lanterns_annie_dog")
    tree.golem("us:9", "Paper Kite", "Glass Lanterns", song_slug="glass_lanterns_paper_kite")
    tree.cache("k-2", {"title": "Annie Dog"})
    tree.cache("glass_lanterns_paper_kite", {"title": "Paper Kite"}, files=("art-photo.jpg",))
    p = M.asset("k-2", "photo")
    assert p == str(tree.bk / "glass_lanterns_paper_kite" / "art-photo.jpg")
    assert not (tree.bk / "k-2" / "art-photo.jpg").exists()                    # servie sur place, pas recopiée
    assert tree.calls == []


def test_catalogue_hors_ligne_dit_vrai_et_complete_l_artiste(tree):
    tree.golem("us:abc", "Black", "Pearl Jam")
    tree.golem("us:nocov", "Emergence", "Hollow Choir", cover=False)
    tree.cache("k-4", {"title": "Black"})
    tree.cache("k-5", {"title": "Emergence"})
    tree.cache("k-1", {"title": "Pour que tu m'aimes encore"})
    tree.cache("half", {"title": "Half"}, stems=False, files=("art-cover.jpg",))   # téléchargement interrompu
    cat = M.catalog()
    assert cat["online"] is False
    by = {s["slug"]: s for s in cat["songs"]}
    assert set(by) == {"k-1", "k-4", "k-5"}
    assert by["k-4"]["has_cover"] is True and by["k-4"]["artist"] == "Pearl Jam"
    assert by["k-5"]["has_cover"] is False and by["k-5"]["artist"] == "Hollow Choir"
    assert by["k-1"]["has_cover"] is False and by["k-1"]["has_photo"] is False and by["k-1"]["artist"] is None
    # ce que le catalogue annonce, la route le sert
    assert M.asset("k-4", "cover") and M.asset("k-5", "cover") is None and M.asset("k-1", "cover") is None


def test_catalogue_en_ligne_ajoute_la_pochette_locale(tree, monkeypatch):
    tree.golem("us:abc", "Black", "Pearl Jam", song_slug="pearl_jam_black")

    def req(path, **kw):
        if path.startswith("/api/ext/songs?"):
            return 200, [{"slug": "pearl_jam_black", "title": "Black", "artist": {"name": "Pearl Jam"}, "album": {}},
                         {"slug": "other", "title": "Other", "artist": {"name": "X", "photo_path": "p.jpg"},
                          "album": {"cover_path": "c.jpg"}}]
        return 404, None
    monkeypatch.setattr(M, "_req", req)
    monkeypatch.setattr("bridge.bars.refresh_async", lambda songs: None)
    monkeypatch.setattr("bridge.golem_pull.refresh_all", lambda: None)
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert by["pearl_jam_black"]["has_cover"] is True and by["pearl_jam_black"]["has_photo"] is False
    assert by["other"]["has_cover"] is True and by["other"]["has_photo"] is True


def test_une_cle_de_chanson_a_sa_pochette_a_part(tree):
    tree.golem("us:abc", "Black", "Pearl Jam")
    p = M.asset("us:abc", "cover")
    assert p == str(tree.sg / ".work" / ".art" / "us-abc-cover.jpg") and open(p, "rb").read() == JPG + b"us:abc"
    assert M.asset("us:abc", "photo") is None and tree.calls == []


def test_rien_sur_le_rack_on_demande_a_golem_fm(tree, monkeypatch):
    tree.cache("ray_stone_slow_surrender", {"title": "Slow Surrender", "artist": "Ray Stone"})

    def req(path, **kw):
        if path == "/api/ext/songs/ray_stone_slow_surrender":
            return 200, {"album": {"cover_path": "covers/ts.jpg"}}
        if path == "/api/ext/files/covers/ts.jpg":
            return 200, JPG
        return 404, None
    monkeypatch.setattr(M, "_req", req)
    p = M.asset("ray_stone_slow_surrender", "cover")
    assert p == str(tree.bk / "ray_stone_slow_surrender" / "art-cover.jpg") and open(p, "rb").read() == JPG


def test_un_slug_qui_sort_du_cache_est_refuse(tree):
    assert M.asset("..", "cover") is None and M.asset("a/b", "cover") is None


PNG = b"\x89PNG\r\n\x1a\nfake-png"


def test_la_photo_d_artiste_du_golem_role_band_a_son_type_reel(tree):
    g = tree.golem("bs:2", "Annie-Dog", "Glass Lanterns", song_slug="glass_lanterns_annie_dog",
                   members={"art/band.png": PNG}, files={"art/band.png": {"role": "band"},
                                                         "art/cover.jpg": {"role": "cover"}})
    before = g.read_bytes()
    tree.cache("k-2", {"title": "Annie-Dog"})
    assert M.local_art("k-2")["photo"] is True
    p = M.asset("k-2", "photo")
    assert p == str(tree.bk / "k-2" / "art-photo.png") and open(p, "rb").read() == PNG
    assert g.read_bytes() == before and tree.calls == []
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert by["k-2"]["has_photo"] is True and by["k-2"]["has_cover"] is True


def test_le_role_declare_l_emporte_sur_le_nom(tree):
    # le manifeste dit QUI est la pochette et la photo, quel que soit le nom du membre
    tree.golem("us:r", "Red Miso", "Leaders As Animals", cover=False,
               members={"art/front.webp": b"RIFFwebp-cover", "art/group.jpg": JPG + b"group",
                        "art/band.jpg": JPG + b"ignored"},
               files={"art/front.webp": {"role": "cover"}, "art/group.jpg": {"role": "band"}})
    tree.cache("rm", {"title": "Red Miso", "artist": "Leaders As Animals"})
    c, p = M.asset("rm", "cover"), M.asset("rm", "photo")
    assert c.endswith("art-cover.webp") and open(c, "rb").read() == b"RIFFwebp-cover"
    assert open(p, "rb").read() == JPG + b"group"


def test_sans_role_declare_le_nom_art_band_suffit(tree):
    tree.golem("us:n", "Sisters", "Ray Stone", members={"art/band.webp": b"RIFFwebp"})
    tree.cache("sv", {"title": "Sisters", "artist": "Ray Stone"})
    assert M.asset("sv", "photo").replace("\\", "/").endswith("sv/art-photo.webp")


def test_la_photo_d_un_autre_golem_du_meme_artiste(tree):
    tree.golem("us:a", "Sisters", "Ray Stone")
    tree.golem("us:b", "Long Prayer", "Ray Stone", members={"art/band.jpg": JPG + b"stone"})
    tree.cache("sv", {"title": "Sisters", "artist": "Ray Stone"})
    assert open(M.asset("sv", "photo"), "rb").read() == JPG + b"stone"


def test_un_golem_sans_photo_n_annonce_pas_de_photo(tree):
    tree.golem("us:abc", "Black", "Pearl Jam")
    tree.cache("k-4", {"title": "Black"})
    art = M.local_art("k-4")
    assert (art["cover"], art["photo"], art["artist"]) == (True, False, "Pearl Jam")
    assert M.asset("k-4", "photo") is None


def test_la_bande_des_instruments_suit_la_tablature(tree, monkeypatch):
    # golem.fm (2026-10-16) : les instruments sont ceux que joue la TAB du .golem — pas les stems, qu'une séparation
    # sort toujours au complet. Un cache sans .golem rapproché (ou un .golem sans tab) n'a pas de bande.
    d = tree.cache("k-9", {"title": "Nine"}, stems=False)
    for f in ("drums.mp3", "vocals.mp3", "guitar.mp3"):
        (d / f).write_bytes(b"x")
    assert M.local_art("k-9")["parts"] == []
    monkeypatch.setattr(M, "_golem_stems", lambda sid: pytest.fail("extraction"))
    tree.golem("us:p", "Tin Robot", "Statica", song_slug="statica_tin_robot",
               members={"stems/vocals.mp3": b"x", "stems/guitar.mp3": b"x", "scores/song.gp": b"gp"},
               files={"scores/song.gp": {"tracks": [{"track": 0, "part": "voice-1"}, {"track": 1, "part": "keys-2"},
                                                     {"track": 2, "part": "guitar-1"}, {"track": 3, "part": "kazoo-1"},
                                                     {"track": 4, "part": "guitar-2"}]}})
    assert M.local_art("statica_tin_robot", {})["parts"] == ["guitar", "piano", "voice"]
    assert M.local_art("us:p")["parts"] == ["guitar", "piano", "voice"]
    tree.golem("us:w", "The Woven Web", "Animals As Leaders", members={"stems/vocals.mp3": b"x"})
    assert M.local_art("us:w")["parts"] == []                    # des stems, pas de tab : pas de bande


def test_les_lignes_vocals_sont_marquees_pour_leur_onglet(tree):
    # `k-*` = une ligne Vocals de golem.fm ; un .golem audio + paroles sans tab = catégorie « vocals » (golemfile.category)
    tree.cache("k-1", {"title": "Pour que tu m'aimes encore"})
    tree.cache("ray_stone_warm_light", {"title": "Warm Light", "artist": "Ray Stone"})
    tree.golem("us:v", "Annie-Dog", "Glass Lanterns", members={"audio/original.mp3": b"x", "lyrics/song.lrc": b"[00:01]la"},
               files={"audio/original.mp3": {}, "lyrics/song.lrc": {}})
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert by["k-1"]["vocals"] is True and by["ray_stone_warm_light"]["vocals"] is False
    assert by["us:v"]["vocals"] is True and by["us:v"]["library"] is True


def test_une_ligne_vocals_ne_cache_pas_la_chanson_du_meme_titre(tree):
    # k-2 = la ligne Vocals d'Annie-Dog ; le .golem d'Annie-Dog (avec tab) reste dans Backings
    tree.cache("k-2", {"title": "Annie-Dog"})
    tree.golem("bs:2", "Annie-Dog", "Glass Lanterns", members={"stems/guitar.mp3": b"x", "scores/song.gp": b"gp"},
               files={"stems/guitar.mp3": {}, "scores/song.gp": {"tracks": [{"track": 0, "part": "guitar-1"}]}})
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert by["k-2"]["vocals"] is True
    assert by["bs:2"]["vocals"] is False and by["bs:2"]["parts"] == ["guitar"]


def test_une_chanson_sans_stems_se_joue_par_sa_ligne_vocals(tree):
    # Black : un .golem allégé (tab + paroles, ni audio ni stems) — ses stems sont ceux de la ligne Vocals k-4,
    # dont la carte paraît aussi dans Backings ; une ligne dont la chanson a ses stems, non
    tree.cache("k-4", {"title": "Black"})
    tree.golem("us:b", "Black", "Pearl Jam", members={"scores/song.gp": b"gp", "lyrics/song.lrc": b"[00:01]x"},
               files={"scores/song.gp": {"tracks": [{"track": 0, "part": "voice-1"}]}, "lyrics/song.lrc": {}})
    tree.cache("k-2", {"title": "Annie-Dog"})
    tree.golem("bs:2", "Annie-Dog", "Glass Lanterns", members={"stems/guitar.mp3": b"x", "scores/song.gp": b"gp"},
               files={"stems/guitar.mp3": {}, "scores/song.gp": {"tracks": [{"track": 0, "part": "guitar-1"}]}})
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert by["k-4"]["vocals"] is True and by["k-4"]["also_song"] is True
    assert by["k-2"]["also_song"] is False


def test_la_chanson_de_la_bibliotheque_remplace_son_entree_du_cache(tree, monkeypatch):
    # Paper Kite : en cache ET en .golem complet — la carte montre le .golem, qui garde le slug du cache (presets liés)
    tree.cache("glass_lanterns_paper_kite", {"title": "Paper Kite", "artist": "Glass Lanterns"})
    tree.golem("rs:c", "Paper Kite", "Glass Lanterns", members={"stems/guitar.mp3": b"x"}, files={"stems/guitar.mp3": {}})
    # Black : son .golem n'a pas de stems — l'entrée du cache reste
    tree.cache("pearl_jam_black", {"title": "Black", "artist": "Pearl Jam"})
    tree.golem("us:b", "Black", "Pearl Jam", members={"scores/song.gp": b"gp"}, files={})
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert "glass_lanterns_paper_kite" not in by
    assert by["rs:c"]["library"] and by["rs:c"]["aliases"] == ["glass_lanterns_paper_kite"]
    assert "pearl_jam_black" in by
    from bridge import storage, store
    monkeypatch.setattr(store, "load_presets", lambda: [{"backing": ["pearl_jam_black"]}])
    assert storage.unused_backings() == ["glass_lanterns_paper_kite"]
    monkeypatch.setattr(store, "load_presets", lambda: [{"backing": ["glass_lanterns_paper_kite"]}])
    assert storage.unused_backings() == []          # un preset le joue encore sous ce slug, sans redirection : gardé


def test_une_chanson_avec_paroles_se_chante(tree):
    # Paper Kite : tab + paroles = une CHANSON (la tab décide), marquée `lyrics` pour l'onglet Vocals
    tree.golem("rs:c", "Paper Kite", "Glass Lanterns", members={"stems/guitar.mp3": b"x", "scores/song.gp": b"gp",
               "lyrics/song.lrc": b"[00:01]x"}, files={"stems/guitar.mp3": {}, "scores/song.gp": {}, "lyrics/song.lrc": {}})
    tree.golem("us:s", "Sisters", "Ray Stone", members={"stems/guitar.mp3": b"x"}, files={"stems/guitar.mp3": {}})
    by = {s["slug"]: s for s in M.catalog()["songs"]}
    assert by["rs:c"]["vocals"] is False and by["rs:c"]["lyrics"] is True
    assert by["us:s"]["lyrics"] is False


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg absent")
def test_sans_original_le_rack_ecoute_la_somme_des_stems(tree, tmp_path):
    # une ligne Vocals de golem.fm n'a que ses stems : le ▶ joue leur somme, rendue une fois et gardée
    import subprocess
    d = tree.cache("k-1", {"title": "Pour que tu m'aimes encore"}, stems=False)
    for st, hz in (("vocals", 440), ("drums", 110)):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={hz}:duration=1",
                        "-c:a", "libmp3lame", str(d / f"{st}.mp3")], check=True)
    p = M.listen_path("k-1")
    assert p and p.endswith("original-mix.mp3") and os.path.getsize(p) > 0
    t = os.path.getmtime(p)
    assert M.listen_path("k-1") == p and os.path.getmtime(p) == t          # gardée : pas rendue deux fois
    assert M.listen_path("../x") is None


def test_l_ecoute_d_un_golem_n_extrait_que_l_original(tree):
    # le ▶ d'une chanson de la bibliothèque : SEUL audio/original.* est copié, pas les stems (le dossier de travail)
    tree.golem("us:o", "Sisters", "Ray Stone", members={"audio/original.mp3": b"ID3-orig", "stems/guitar.mp3": b"ID3-g"},
               files={"audio/original.mp3": {}, "stems/guitar.mp3": {}})
    p = M._golem_original("us:o")
    assert p and p.endswith("-original.mp3") and open(p, "rb").read() == b"ID3-orig"
    assert not os.path.isdir(os.path.join(str(tree.sg), ".work", "us-o"))         # rien d'autre n'est extrait
    assert M._golem_original("us:o") == p
