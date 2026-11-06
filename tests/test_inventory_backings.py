# SPDX-License-Identifier: GPL-3.0-or-later
"""Le cache de backings dans l'inventaire (accord golem.fm, 2026-10-16) : une carte « coquille » par piste du cache qui
n'est pas déjà une chanson `.golem` — sinon golem.fm ne montrait que Paper Kite."""
import json
import os

from bridge import golemfm, inventory


def _cache(tmp_path, monkeypatch, entries):
    monkeypatch.setattr(golemfm.C, "BACKING_DIR", str(tmp_path))
    for slug, meta, audio in entries:
        d = tmp_path / slug
        d.mkdir()
        (d / "meta.json").write_text(json.dumps(meta))
        if audio:
            (d / "guitar.ogg").write_bytes(b"x" * 10)
    monkeypatch.setattr(golemfm, "is_cached", lambda s: os.path.isfile(os.path.join(str(tmp_path), s, "guitar.ogg")))
    monkeypatch.setattr(golemfm, "stems_of", lambda s: ["drums", "guitar"])


def test_une_carte_par_piste_du_cache_hors_golem_et_hors_vocals(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch, [
        ("black", {"title": "Black", "artist": "Pearl Jam", "duration_sec": 343}, True),
        ("annie-dog", {"title": "Annie-Dog"}, False),
        ("k-4", {"title": "Black (golem.fm k- slug)"}, True),
        ("paper-kite", {"title": "Paper Kite"}, True),
    ])
    import bridge.songs as S
    monkeypatch.setattr(S, "load", lambda gid: {"song_slug": "paper-kite"} if gid == "g1" else None)
    cards, ok = inventory.backing_cards({"g1": {"where": "golem", "category": "song"}})
    assert ok
    byt = {c["title"]: c for c in cards.values()}
    # Paper Kite a son .golem ; Annie-Dog n'a pas ses stems (téléchargement interrompu) : Tracks ne la montre pas
    assert set(byt) == {"Black", "Black (golem.fm k- slug)"}
    assert byt["Black (golem.fm k- slug)"]["category"] == "vocals"
    b = byt["Black"]
    assert b["id"] == inventory.backing_id("black") and b["id"].startswith("bk:") and len(b["id"]) == 35
    assert b["where"] == "backing" and b["category"] == "song" and "kind" not in b
    assert b["duration_ms"] == 343000 and b["carries"] == {"audio": True, "stems": ["drums", "guitar"]}



def test_l_id_est_stable_et_l_etag_suit_le_dossier(tmp_path, monkeypatch):
    _cache(tmp_path, monkeypatch, [("black", {"title": "Black"}, True)])
    a, _ = inventory.backing_cards({})
    b, _ = inventory.backing_cards({})
    assert a == b
    os.utime(tmp_path / "black", (1, 1))
    c, _ = inventory.backing_cards({})
    assert c[inventory.backing_id("black")]["etag"] != a[inventory.backing_id("black")]["etag"]


def test_un_cache_illisible_interdit_les_retraits(monkeypatch):
    def boom():
        raise OSError("disque")
    monkeypatch.setattr(golemfm, "list_cache", boom)
    cards, ok = inventory.backing_cards({})
    assert cards == {} and ok is False


def test_un_golem_fm_qui_refuse_les_cartes_de_backing_n_empeche_pas_l_inventaire(tmp_path, monkeypatch):
    """La prod de golem.fm, avant son déploiement, refuse EN ENTIER un envoi qui porte une carte `bk:` (422) : le rack
    le renvoie sans elles, l'inventaire des .golem passe quand même."""
    _cache(tmp_path, monkeypatch, [("black", {"title": "Black"}, True)])
    monkeypatch.setattr(inventory, "_mem", lambda: {})
    monkeypatch.setattr(inventory, "_set_mem", lambda d: None)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://x", "tok"))
    sent = []

    def req(path, body=None, token=None, method=None, **kw):
        ids = [c["id"] for c in body["cards"]]
        sent.append(ids)
        if any(i.startswith("bk:") for i in ids):
            return 422, {"detail": {"error": "bad_card"}}
        return 200, {"rev": {}}
    monkeypatch.setattr(golemfm, "_req", req)
    monkeypatch.setattr(inventory, "collect", lambda: ({"g1": {"id": "g1", "etag": "e", "category": "song"},
                                                        **inventory.backing_cards({})[0]}, True))
    res = inventory.publish()
    assert res["ok"] and len(sent) == 2 and not any(i.startswith("bk:") for i in sent[1])


def test_une_entree_du_cache_au_meme_titre_qu_un_golem_ne_fait_pas_doublon(tmp_path, monkeypatch):
    """Les .golem complets réinstallés (Black, Annie-Dog…) : leurs vieilles entrées du cache (k-4, k-2…) feraient des
    doubles. Même titre, casse et ponctuation ignorées = pas de carte ; le cache, lui, n'est pas touché."""
    _cache(tmp_path, monkeypatch, [("gnr_knockin", {"title": "Knockin' On Heaven's Door"}, True),
                                   ("ray_stone_warm_light", {"title": "Warm Light"}, True)])
    import bridge.songs as S
    monkeypatch.setattr(S, "load", lambda gid: None)
    cards, _ = inventory.backing_cards({"us:x": {"where": "golem", "category": "song", "title": "KNOCKIN ON HEAVENS DOOR"}})
    assert [c["title"] for c in cards.values()] == ["Warm Light"]
    assert (tmp_path / "gnr_knockin").is_dir()


def test_une_entree_k_est_une_ligne_vocals(tmp_path, monkeypatch):
    """`k-<n>` = la ligne Vocals n°<n> de golem.fm (2026-10-16) : catégorie « vocals », même id bk: ; écartée, comme une
    chanson, quand un .golem du golem (chanson ou ligne Vocals) porte le même titre."""
    _cache(tmp_path, monkeypatch, [("k-1", {"title": "Pour que tu m'aimes encore"}, True),
                                   ("ray_stone_warm_light", {"title": "Warm Light"}, True)])
    import bridge.songs as S
    monkeypatch.setattr(S, "load", lambda gid: None)
    cards, _ = inventory.backing_cards({})
    by = {c["title"]: c for c in cards.values()}
    assert by["Pour que tu m'aimes encore"]["category"] == "vocals"
    assert by["Pour que tu m'aimes encore"]["id"] == inventory.backing_id("k-1")
    assert by["Warm Light"]["category"] == "song"
    cards, _ = inventory.backing_cards({"rs:c": {"where": "golem", "category": "vocals", "title": "POUR QUE TU M'AIMES ENCORE"}})
    assert [c["title"] for c in cards.values()] == ["Warm Light"]


def test_la_carte_d_un_golem_porte_album_et_genres_sans_image():
    import glob
    from bridge import config as C
    from bridge import golemfile as G
    path = sorted(glob.glob(os.path.join(os.path.dirname(C.ROOT if hasattr(C, "ROOT") else "."), "**", "*.golem"), recursive=True))
    # un .golem de test fabriqué sur place : manifeste minimal avec album et 5 genres (4 au plus partent)
    import tempfile
    import zipfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.golem")
    man = {"golem": 1, "type": "song", "id": "us:abc", "title": "T", "album": "Ten",
           "genres": [{"family": f, "subgenre": None} for f in ("rock", "pop", "jazz", "metal", "funk")], "files": {}}
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(G.MANIFEST, json.dumps(man))
    rep = {"manifest": man, "present": [], "undeclared": []}
    c = inventory.card_of(p, rep)
    assert c["album"] == "Ten" and len(c["genres"]) == 4 and c["genres"][0] == {"family": "rock", "subgenre": None}
    assert not any(k for k in c if "image" in k or "cover" in k)


def test_la_duree_se_lit_en_ms_ou_en_secondes(tmp_path, monkeypatch):
    """Les chansons k-* de golem.fm portent `duration_ms` dans leur meta.json, pas `duration_sec` (golem.fm, 2026-10-16)."""
    _cache(tmp_path, monkeypatch, [("k-4", {"title": "Black", "duration_ms": 424283}, True),
                                   ("w", {"title": "Warm Light", "duration_sec": 300}, True)])
    cards, _ = inventory.backing_cards({})
    by = {c["title"]: c["duration_ms"] for c in cards.values()}
    assert by == {"Black": 424283, "Warm Light": 300000}


def test_un_golem_fm_qui_refuse_la_categorie_track_n_empeche_pas_l_inventaire(monkeypatch):
    """La catégorie « track » (separation-batch.md §7) : un golem.fm qui ne la connaît pas encore refuse l'envoi EN ENTIER
    (422 bad_card) ; le rack le renvoie sans ces cartes — elles repartiront quand golem.fm les acceptera."""
    monkeypatch.setattr(inventory, "_mem", lambda: {})
    monkeypatch.setattr(inventory, "_set_mem", lambda d: None)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://x", "tok"))
    sent = []

    def req(path, body=None, token=None, method=None, **kw):
        cats = [c["category"] for c in body["cards"]]
        sent.append(cats)
        return (422, {"detail": {"error": "bad_card"}}) if "track" in cats else (200, {"rev": {}})
    monkeypatch.setattr(golemfm, "_req", req)
    monkeypatch.setattr(inventory, "collect", lambda: ({"g1": {"id": "g1", "etag": "e", "category": "song"},
                                                        "ct:t": {"id": "ct:t", "etag": "f", "category": "track"}}, True))
    res = inventory.publish()
    assert res["ok"] and sent == [["song", "track"], ["song"]]
