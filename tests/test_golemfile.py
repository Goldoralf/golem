# SPDX-License-Identifier: GPL-3.0-or-later
"""Le fichier .golem (docs/golem-format.md, FIGÉ 2026-10-08) : écrire, relire, vérifier, refuser."""
import json
import os
import zipfile

import pytest

from bridge import golemfile as G

WAV = b"RIFF" + b"\0" * 2000
MAN = {"type": "song", "id": "rs:abc", "title": "Paper Kite", "kind": "cover", "rights": {"work": "third-party"}}


def _song(tmp_path, **extra):
    p = str(tmp_path / "s.golem")
    members = {"audio/original.wav": WAV, "stems/drums.flac": b"fLaC" + b"\1" * 500,
               "sync/bars.json": json.dumps({"bars": []}).encode(), "lyrics/song.lrc": b"[00:01.00]hello"}
    members.update(extra)
    G.write(p, dict(MAN, files={"stems/drums.flac": {"part": "drums", "origin": "separated"},
                                "scores/song.gp": {"sha256": "0" * 64}}), members)
    return p


def test_ecrire_puis_verifier(tmp_path):
    p = _song(tmp_path)
    rep = G.verify(p)
    m = rep["manifest"]
    assert m["format"] == "golem/1"
    assert m["files"]["stems/drums.flac"]["part"] == "drums"            # les métadonnées d'entrée sont gardées
    assert m["files"]["audio/original.wav"]["bytes"] == len(WAV)
    assert rep["missing"] == ["scores/song.gp"]                           # attendu, absent : pas une erreur
    with zipfile.ZipFile(p) as zf:
        assert zf.namelist()[0] == "golem.json"                           # le manifeste en premier
        assert zf.getinfo("audio/original.wav").compress_type == zipfile.ZIP_STORED
        assert zf.getinfo("lyrics/song.lrc").compress_type == zipfile.ZIP_DEFLATED


def test_lire_un_membre_sans_extraire(tmp_path):
    p = _song(tmp_path)
    assert G.read_member(p, "audio/original.wav") == WAV
    with pytest.raises(G.GolemError):
        G.read_member(p, "../etc/passwd")


def test_un_fichier_altere_est_refuse(tmp_path):
    p = _song(tmp_path)
    with zipfile.ZipFile(p) as zf:
        items = {n: zf.read(n) for n in zf.namelist()}
    items["audio/original.wav"] = WAV[:-1] + b"X"
    with zipfile.ZipFile(p, "w") as zf:
        for n, b in items.items():
            zf.writestr(n, b)
    with pytest.raises(G.GolemError, match="fingerprint"):
        G.verify(p)


def test_trois_formats_audio_seulement(tmp_path):
    with pytest.raises(G.GolemError, match="WAV, MP3 or FLAC"):
        _song(tmp_path, **{"audio/original.m4a": b"x"})


def test_version_majeure_superieure_refusee_inconnu_ignore(tmp_path):
    p = str(tmp_path / "f.golem")
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("golem.json", json.dumps(dict(MAN, format="golem/2", files={})))
    with pytest.raises(G.GolemError, match="update the golem"):
        G.verify(p)
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("golem.json", json.dumps(dict(MAN, format="golem/1", files={}, futur={"x": 1})))
        zf.writestr("hologram/scene.bin", b"?")
    rep = G.verify(p)
    assert rep["unknown"] == ["hologram/scene.bin"]
    G.extract(p, str(tmp_path / "cache"))
    assert not os.path.exists(tmp_path / "cache" / "hologram")          # l'inconnu ne sort jamais
    # même DÉCLARÉ au manifeste avec sa bonne empreinte (revue 2026-10-25 : il passait dans `present`, donc extrait)
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("golem.json", json.dumps(dict(MAN, format="golem/1",
                                                  files={"payload/run.sh": {"sha256": G.sha256_bytes(b"#!")}})))
        zf.writestr("payload/run.sh", b"#!")
    rep = G.verify(p)
    assert rep["unknown"] == ["payload/run.sh"] and rep["present"] == []
    G.extract(p, str(tmp_path / "cache2"))
    assert not os.path.exists(tmp_path / "cache2" / "payload")


def test_chemins_pieges_refuses(tmp_path):
    for bad in ("../evil.txt", "/abs.txt", "audio/../../x.wav", "a\\b.txt", "C:/x.txt"):
        if os.sep == "\\" and "\\" in bad:
            continue                                  # zipfile de Windows récrit « \ » en « / » à l'écriture : ce piège se joue sur Linux
        p = str(tmp_path / "bad.golem")
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("golem.json", json.dumps(dict(MAN, format="golem/1", files={})))
            zi = zipfile.ZipInfo("placeholder")
            zi.filename = bad                         # brut : ZipInfo(bad) remplacerait « \ » par « / » sous Windows
            zf.writestr(zi, b"x")
        with pytest.raises(G.GolemError):
            G.verify(p)


def test_le_type_est_verifie_par_la_structure(tmp_path):
    p = str(tmp_path / "a.golem")
    G.write(p, dict(MAN, files={}), {"songs/x.golem": b"PK"})            # un « song » qui contient songs/
    with pytest.raises(G.GolemError, match="album"):
        G.verify(p)
    G.write(p, dict(MAN, type="album", files={}), {"songs/x.golem": b"PK"})
    G.verify(p)
    G.write(p, dict(MAN, type="album", files={}), {"songs/x.golem": b"PK", "audio/original.mp3": b"ID3"})
    with pytest.raises(G.GolemError, match="no audio"):
        G.verify(p)


def test_cache_de_travail_puis_reecriture_du_manifeste(tmp_path):
    p = _song(tmp_path)
    cache = str(tmp_path / "cache")
    G.extract(p, cache)
    assert open(os.path.join(cache, "audio", "original.wav"), "rb").read() == WAV
    G.rewrite_manifest(p, lambda m: m.update(title="Paper Kite (live)"))
    rep = G.verify(p)                                                     # médias recopiés intacts
    assert rep["manifest"]["title"] == "Paper Kite (live)"
    with zipfile.ZipFile(p) as zf:
        assert zf.getinfo("audio/original.wav").compress_type == zipfile.ZIP_STORED
    G.extract(p, cache)                                                   # un cache existant est remplacé d'un coup
    assert json.load(open(os.path.join(cache, "golem.json")))["title"] == "Paper Kite (live)"


def test_zip_piege(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "MAX_MEMBERS", 3)
    p = _song(tmp_path)
    with pytest.raises(G.GolemError, match="too many"):
        G.verify(p)


def test_ecriture_en_flux_non_positionnable(tmp_path):
    """golem.fm (lot 2) écrit le .golem dans la réponse HTTP : aucun seek possible."""
    import io

    class Pipe(io.RawIOBase):                      # un flux qui n'avance qu'en écrivant, comme un socket
        def __init__(self): self.buf = bytearray()
        def writable(self): return True
        def seekable(self): return False
        def write(self, b): self.buf += b; return len(b)
        def tell(self): raise OSError("not seekable")
        def seek(self, *a): raise OSError("not seekable")

    disk = tmp_path / "drums.flac"
    disk.write_bytes(b"fLaC" + b"\2" * 70000)
    pipe = Pipe()
    G.write_stream(pipe, dict(MAN, files={"stems/drums.flac": {"part": "drums", "origin": "separated"}}),
                   {"stems/drums.flac": str(disk), "audio/original.mp3": b"ID3" + b"\0" * 5000,
                    "sync/bars.json": b'{"v":1,"bars":[]}'})
    p = tmp_path / "streamed.golem"
    p.write_bytes(bytes(pipe.buf))
    rep = G.verify(str(p))
    assert sorted(rep["present"]) == ["audio/original.mp3", "stems/drums.flac", "sync/bars.json"]
    assert rep["manifest"]["files"]["stems/drums.flac"]["part"] == "drums"
    with zipfile.ZipFile(p) as zf:
        assert zf.namelist()[0] == "golem.json"
        assert zf.getinfo("stems/drums.flac").compress_type == zipfile.ZIP_STORED
    assert G.read_member(str(p), "stems/drums.flac") == disk.read_bytes()


# ── hors manifeste : signatures/ et mine/ (lot 8, golem.fm 2026-10-08) ──

def test_signatures_et_mine_sont_ecrits_sans_etre_inscrits(tmp_path):
    import io
    p = str(tmp_path / "s.golem")
    m = G.write(p, {"type": "song", "id": "rs:" + "a" * 32, "title": "T"},
                {"lyrics/song.lrc": b"[00:01.00]x", "mine/take.wav": b"RIFF", "signatures/manifest.json": b"{}"})
    assert set(m["files"]) == {"lyrics/song.lrc"}
    rep = G.verify(p)
    assert set(rep["undeclared"]) == {"mine/take.wav", "signatures/manifest.json"}
    buf = io.BytesIO()
    m2 = G.write_stream(buf, {"type": "song", "id": "rs:" + "a" * 32}, {"signatures/manifest.json": b"{}"})
    assert m2["files"] == {}


def test_ajouter_une_prise_ne_change_pas_le_manifeste_signe(tmp_path):
    p = str(tmp_path / "s.golem")
    G.write(p, {"type": "song", "id": "rs:" + "a" * 32, "title": "T"}, {"lyrics/song.lrc": b"[00:01.00]x"})
    signed = G.read_member(p, G.MANIFEST)                     # les octets EXACTS que golem.fm signe
    G.replace(p, None, {"signatures/manifest.json": b'{"v":1}', "mine/take.wav": b"RIFF"})
    G.replace(p, None, {"mine/take.wav": None})
    assert G.read_member(p, G.MANIFEST) == signed
    assert "signatures/manifest.json" in G.verify(p)["undeclared"]


def test_cache_tenu_ouvert_mis_a_jour_membre_par_membre(tmp_path, monkeypatch):
    """Windows : REAPER tient un stem du cache, le dossier ne se renomme pas. La fiche change, le stem non :
    le cache se met à jour sans toucher au stem ouvert, et un membre retiré en sort."""
    p = _song(tmp_path)
    cache = str(tmp_path / "cache")
    G.extract(p, cache)
    stem = os.path.join(cache, "stems", "drums.flac")
    before = os.stat(stem).st_mtime_ns
    G.replace(p, lambda m: m.update(title="Paper Kite (live)"), {"lyrics/song.lrc": None})
    real = os.replace

    def refuse_dir(a, b):
        if os.path.abspath(a) == os.path.abspath(cache):
            raise PermissionError(5, "Accès refusé")
        return real(a, b)
    monkeypatch.setattr(G.os, "replace", refuse_dir)
    G.extract(p, cache)
    assert json.load(open(os.path.join(cache, "golem.json"), encoding="utf-8"))["title"] == "Paper Kite (live)"
    assert os.stat(stem).st_mtime_ns == before                            # identique : pas réécrit
    assert not os.path.exists(os.path.join(cache, "lyrics", "song.lrc"))  # retiré de la chanson
    assert not [n for n in os.listdir(tmp_path) if n.startswith(".golem-x-")]


# ── un .golem ne mène à personne (song-sharing.md §2.8, FIGÉ le 2026-10-11) ──

SHEET = {"bpm": 87, "backing": "glass_lanterns_paper_kite", "preset_doc": {"preset": {"id": "paper-kite",
          "backing": {"songs": [{"slug": "glass_lanterns_paper_kite", "title": "Paper Kite"}]},
          "config": {"rec": {"persons": {"alex": {"off": ["voice-1"]}},
                                                                                     "foot_person": "alex"}},
          "lanes": [{"id": "guitar-1", "person": "alex", "patch_from": {"id": "paper-kite-2", "rev": 1},
                     "chain": {"pre": [{"type": "amp", "ref": "t3k:246", "label": "Twin"},
                                       {"type": "pedal", "ref": "local:cap-ds1-alex", "model": "x", "label": "DS-1"}]}}]},
          "deps": [{"uid": "t3k:246", "sha256": "a" * 64}, {"uid": "local:cap-ds1-alex", "sha256": "b" * 64}]}}


def test_aucune_date_de_fabrication_dans_l_archive_et_le_meme_fichier_a_l_octet(tmp_path):
    disk = tmp_path / "take.wav"
    disk.write_bytes(WAV)
    os.utime(disk, (1_700_000_000, 1_700_000_000))         # un fichier disque daté : sa date ne doit pas entrer
    a, b = str(tmp_path / "a.golem"), str(tmp_path / "b.golem")
    G.write(a, dict(MAN), {"stems/guitar-1.wav": str(disk), "lyrics/song.lrc": b"x"})
    G.write(b, dict(MAN), {"lyrics/song.lrc": b"x", "stems/guitar-1.wav": WAV})
    assert open(a, "rb").read() == open(b, "rb").read()   # même chanson, même fichier (bytes ou disque, ordre égal)
    for p in (a, b):
        with zipfile.ZipFile(p) as zf:
            assert {i.date_time for i in zf.infolist()} == {G.ZIP_DATE}
    G.replace(a, lambda m: m.update(title="Paper Kite"), {"sheet.json": b"{}"})
    lc = str(tmp_path / "light.golem")
    G.light_copy(a, lc)
    for p in (a, lc):
        with zipfile.ZipFile(p) as zf:
            names = [i.filename for i in zf.infolist()]
            assert {i.date_time for i in zf.infolist()} == {G.ZIP_DATE}
            assert names[0] == G.MANIFEST and names[1:] == sorted(names[1:])


def test_la_copie_de_sortie_ne_mene_a_personne(tmp_path):
    src, out = str(tmp_path / "in.golem"), str(tmp_path / "out.golem")
    m = dict(MAN, golemfm={"slug": "glass_lanterns_paper_kite"},
             repertoire={"rev": 140, "band": "b_djsqupcj2e", "song_slug": "x", "born": "rack"},
             production={"recorded": {"by": "golem", "serial": "golem_1"}},
             versions=[{"id": "demo", "production": {"recorded": {"by": "golem", "serial": "golem_1"}}}],
             credits={"recording": {"performers": [{"name": "Billy", "part": "guitar-1", "person": "u_42"}]}})
    G.write(src, m, {"sheet.json": json.dumps(SHEET).encode(), "mine/mine.json": json.dumps({"takes": [{"part": "guitar-1", "person": "alex"}]}).encode(),
                     "lyrics/song.lrc": b"x", "sync/bars.json": json.dumps({"version": 1, "slug": "glass_lanterns_paper_kite", "bars": []}).encode()})
    rep = G.outbound(src, out)
    assert json.loads(G.read_member(out, "sync/bars.json")) == {"version": 1, "bars": []}   # la carte, sans le slug
    o = G.verify(out)["manifest"]                           # toujours un .golem valide (sha256 de sheet.json suivi)
    assert o["id"] == "rs:abc" and rep["signed"] is False   # sans `id=`, l'id ne change pas (dépôt chez son compte)
    for k in ("golemfm", "repertoire"):
        assert k not in o
    assert o["production"]["recorded"] == {"by": "golem"} and "serial" not in o["versions"][0]["production"]["recorded"]
    assert o["credits"]["recording"]["performers"] == [{"name": "Billy", "part": "guitar-1"}]
    sheet = json.loads(G.read_member(out, "sheet.json"))
    flat = json.dumps(sheet)
    for leak in ("alex", "persons", "foot_person", "patch_from", "local:cap", "b" * 64, "glass_lanterns"):
        assert leak not in flat, leak
    pre = sheet["preset_doc"]["preset"]["lanes"][0]["chain"]["pre"]
    assert pre[0]["ref"] == "t3k:246" and pre[1] == {"type": "pedal", "label": "DS-1"}   # le bloc reste, sans réf privée
    assert sheet["preset_doc"]["deps"] == [{"uid": "t3k:246", "sha256": "a" * 64}]
    assert sheet["backing"] == "rs:abc" and sheet["preset_doc"]["preset"]["backing"]["songs"][0]["slug"] == "rs:abc"   # elle-même
    assert "alex" not in G.read_member(out, "mine/mine.json").decode()
    assert rep["private_refs"] == 2 and rep["owner_keys"] >= 4
    G.outbound(src, str(tmp_path / "out2.golem"))
    assert open(out, "rb").read() == open(tmp_path / "out2.golem", "rb").read()   # pas de tatouage : deux sorties identiques
    assert json.loads(G.read_member(src, "sheet.json")) == SHEET                     # la copie interne n'est pas touchée


def test_l_id_de_sortie_est_donne_et_un_original_signe_garde_le_sien(tmp_path):
    src = str(tmp_path / "in.golem")
    G.write(src, dict(MAN), {"lyrics/song.lrc": b"x"})
    assert G.outbound(src, str(tmp_path / "o.golem"), id="ct:abc")["id"] == "ct:abc"
    signed = str(tmp_path / "signed.golem")
    G.write(signed, dict(MAN, id="bs:7", golemfm={"slug": "s"},
                         credits={"recording": {"performers": [{"name": "Alex", "person": "u_1"}]}}),
            {"lyrics/song.lrc": b"x", "signatures/manifest.json": b'{"v": 1}'})
    raw = G.read_member(signed, G.MANIFEST)
    with pytest.raises(G.GolemError):
        G.outbound(signed, str(tmp_path / "o2.golem"), id="ct:abc")
    r = G.outbound(signed, str(tmp_path / "o3.golem"))
    o = G.read_manifest(str(tmp_path / "o3.golem"))
    assert r["signed"] and o["id"] == "bs:7" and "golemfm" not in o
    assert o["credits"]["recording"]["performers"][0]["person"] == "u_1"          # l'artiste a choisi de se nommer
    assert G.read_member(str(tmp_path / "o3.golem"), G.SIGNED_MANIFEST) == raw    # la signature reste vérifiable


def test_les_octets_du_manifeste_et_sa_part_de_sortie_sont_publics(tmp_path):
    """golem.fm signe et sert en flux : il appelle CES fonctions, pas une copie (vécu le 2026-10-11 : le tri de `files`
    avait cassé ses signatures, faites par un json.dumps à part)."""
    p = str(tmp_path / "s.golem")
    m = G.write(p, dict(MAN), {"lyrics/song.lrc": b"x", "audio/original.wav": WAV})
    assert G.read_member(p, G.MANIFEST) == G.manifest_bytes(m)
    o = G.outbound_manifest({"id": "rs:1", "golemfm": {}, "repertoire": {}, "production": {"mixed": {"serial": "golem_1"}},
                             "credits": {"recording": {"performers": [{"name": "A", "person": "u"}]}}}, signed=False, id="ct:x")
    assert o == {"id": "ct:x", "production": {"mixed": {}}, "credits": {"recording": {"performers": [{"name": "A"}]}}}
    with pytest.raises(G.GolemError):
        G.outbound_manifest({"id": "bs:1"}, signed=True, id="ct:x")


def test_l_id_ct_designe_la_chanson_et_tombe_pareil_des_deux_cotes():
    """song-sharing.md §2.8, spécification de golem.fm (2026-10-11) : ISRC, sinon MBID, sinon artiste+titre+kind."""
    import hashlib
    from bridge import songs
    a = G.content_id("Beyoncé", "Halo!", "cover")
    assert a == "ct:" + hashlib.sha256(b"golem-ct/1|tk:beyonce|halo|cover").hexdigest()[:32]   # la valeur, pas qu'une forme
    assert len(a) == 35 and songs.BS.match(a)
    assert a == G.content_id("BEYONCE", "  halo ", "cover") == G.content_id("Beyonce", "Halo", "remix")   # kind inconnu → cover
    assert a != G.content_id("Beyoncé", "Halo", "original")                                    # original ≠ cover
    isrc = G.content_id("A", "B", "cover", isrc="us-wb1-93-00123")
    assert isrc == G.content_id("Other", "Title", "original", isrc="USWB19300123")
    assert isrc == "ct:" + hashlib.sha256(b"golem-ct/1|isrc:USWB19300123").hexdigest()[:32]
    mb = "A1B2C3D4-0000-1111-2222-333344445555"
    assert G.content_id("A", "B", "cover", isrc="bad", mbid=mb) == G.content_id("Z", "Y", "cover", mbid=" " + mb.lower())
    assert G.content_id("A", "B", "cover", mbid=mb) == "ct:" + hashlib.sha256(("golem-ct/1|mbid:" + mb.lower()).encode()).hexdigest()[:32]
