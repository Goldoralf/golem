# SPDX-License-Identifier: GPL-3.0-or-later
"""Séparer un dossier (docs/separation-batch.md) : le dossier se LIT et ne s'écrit jamais, chaque morceau devient un
`.golem` complet dans la bibliothèque (original, stems, tab et paroles du même nom), « reprise » par défaut, le mode
Vocals garde la voix et réunit le reste, un morceau déjà là est sauté, et le lot survit à un arrêt."""
import json
import os
import shutil
import subprocess
import zipfile

import pytest

np = pytest.importorskip("numpy")
if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
    pytest.skip("ffmpeg absent", allow_module_level=True)

from bridge import golemfile as G, separation as S, separation_batch as SB, songs  # noqa: E402

STEMS = {"vocals": 0.5, "drums": 0.3, "bass": 0.2}


def _clip(path, seconds=3, tags=None):
    sr = 44100
    t = np.arange(seconds * sr) / sr
    x = np.stack([0.3 * np.sin(2 * np.pi * 220 * t), 0.3 * np.sin(2 * np.pi * 330 * t)], 1).astype(np.float32)
    raw = str(path) + ".f32"
    x.tofile(raw)
    meta = sum((["-metadata", "%s=%s" % kv] for kv in (tags or {}).items()), [])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", raw] + meta + [str(path)],
                   check=True)
    os.unlink(raw)
    return path


@pytest.fixture
def batch(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(S, "_busy", lambda idle: None)
    monkeypatch.setattr(S, "_note_rtf", lambda eid, rtf: None)
    monkeypatch.setattr(S, "caps", lambda: {"stems": list(STEMS), "rtf": 0.5})
    eng = {"id": "e1", "kind": "program", "test": {"ok": True, "stems": list(STEMS)}}
    monkeypatch.setattr(S, "active_engine", lambda: (eng, None))

    def fake_separate(e, mix, n, workdir, outdir, stop=None, progress=None):
        """Trois stems qui se somment au mix, comme un vrai moteur honnête."""
        os.makedirs(outdir, exist_ok=True)
        if stop and stop():
            raise S.Stopped(stop())
        m = np.fromfile(mix, dtype=np.float32)
        out = {}
        for s, g in STEMS.items():
            p = os.path.join(outdir, s + ".f32")
            (m * g).astype(np.float32).tofile(p)
            out[s] = p
        return out, 0.1, 0.0
    monkeypatch.setattr(S, "separate", fake_separate)
    monkeypatch.setattr(SB, "ensure_worker", lambda: None)          # le worker tourne dans le test, pas en fond
    SB._SCAN.update(dir=None, at=0.0, res=None)
    music = tmp_path / "Covers"
    (music / "Album").mkdir(parents=True)
    _clip(music / "Hollow Pines - Paper Engines.wav")
    (music / "Hollow Pines - Paper Engines.gp").write_bytes(b"GP-TAB")
    (music / "Hollow Pines - Paper Engines.lrc").write_text("[00:01.00]la la\n")
    _clip(music / "Album" / "03 - whatever.flac", tags={"title": "Glass Harbour", "artist": "The Lanterns", "album": "Tides"})
    _clip(music / "Album" / "Velvet Static.ogg", tags={"title": "Velvet Static", "artist": "The Lanterns"})
    (music / "broken.mp3").write_bytes(b"not audio at all")
    (music / ".hidden.wav").write_bytes(b"x")
    return {"tmp": tmp_path, "music": music, "engine": eng}


def _tree(root):
    return sorted((os.path.relpath(os.path.join(d, f), root), os.path.getsize(os.path.join(d, f)))
                  for d, _, fs in os.walk(root) for f in fs)


def _run(b, mode="full", keys=None, **edit):
    sc = SB.scan(str(b["music"]))
    items = [{"key": it["key"], "title": it["title"], "artist": it.get("artist"), **edit.get(it["key"], {})}
             for it in sc["items"] if it["state"] == "new" and (keys is None or it["key"] in keys)]
    SB.start(str(b["music"]), items, mode)
    SB._work()
    return SB.state()


def test_le_dossier_se_lit_tags_puis_nom_tab_et_paroles_du_meme_nom(batch):
    before = _tree(batch["music"])
    sc = SB.scan(str(batch["music"]))
    by = {it["path"]: it for it in sc["items"]}
    assert set(by) == {"Hollow Pines - Paper Engines.wav", "Album/03 - whatever.flac", "Album/Velvet Static.ogg",
                       "broken.mp3"}                                            # le fichier caché n'est pas lu
    p = by["Hollow Pines - Paper Engines.wav"]
    assert (p["title"], p["artist"], p["from"]) == ("Paper Engines", "Hollow Pines", "name")
    assert p["gp"] == "Hollow Pines - Paper Engines.gp" and p["lrc"] == "Hollow Pines - Paper Engines.lrc"
    g = by["Album/03 - whatever.flac"]
    assert (g["title"], g["artist"], g["album"], g["from"]) == ("Glass Harbour", "The Lanterns", "Tides", "tags")
    assert by["broken.mp3"]["state"] == "unreadable"
    assert sc["total_s"] == 9
    assert _tree(batch["music"]) == before                                   # rien n'est écrit dans le dossier


def test_chaque_morceau_devient_un_golem_complet_dans_la_bibliotheque(batch):
    before = _tree(batch["music"])
    st = _run(batch)
    assert st["counts"]["done"] == 3 and st["finished"]
    lib = {d["title"]: d for d in songs.list_all()}
    assert set(lib) == {"Paper Engines", "Glass Harbour", "Velvet Static"}
    path = songs._path(lib["Paper Engines"]["id"])
    rep = G.verify(path)
    m = rep["manifest"]
    assert m["id"] == G.content_id("Hollow Pines", "Paper Engines", "cover") and m["kind"] == "cover"
    assert m["rights"] == {"work": "third-party"} and 2900 < m["recording"]["duration_ms"] < 3100
    assert {"audio/original.wav", "stems/vocals.mp3", "stems/drums.mp3", "stems/bass.mp3",
            "scores/song.gp", "lyrics/song.lrc"} <= set(rep["present"])
    assert m["files"]["stems/drums.mp3"]["origin"] == "separated" and m["files"]["stems/drums.mp3"]["part"] == "drums"
    with zipfile.ZipFile(path) as z:
        assert z.read("scores/song.gp") == b"GP-TAB"
        assert z.read("audio/original.wav") == (batch["music"] / "Hollow Pines - Paper Engines.wav").read_bytes()
    v = G.verify(songs._path(lib["Velvet Static"]["id"]))
    assert "audio/original.flac" in v["present"]                             # un .ogg devient FLAC, seul format permis
    assert G.verify(songs._path(lib["Glass Harbour"]["id"]))["manifest"]["album"] == "Tides"
    assert _tree(batch["music"]) == before
    assert not os.path.isdir(SB._dir(st["id"], st["items"][0]["key"]))     # le travail est nettoyé


def test_le_mode_vocals_garde_la_voix_et_reunit_le_reste(batch):
    key = next(it["key"] for it in SB.scan(str(batch["music"]))["items"] if it["path"].endswith(".wav"))
    _run(batch, mode="vocals", keys={key})
    d = songs.list_all()[0]
    present = G.verify(songs._path(d["id"]))["present"]
    assert sorted(p for p in present if p.startswith("stems/")) == ["stems/other.mp3", "stems/vocals.mp3"]


def test_un_titre_corrige_a_l_ecran_fait_l_identite(batch):
    sc = SB.scan(str(batch["music"]))
    key = next(it["key"] for it in sc["items"] if it["path"].endswith(".wav"))
    _run(batch, keys={key}, **{key: {"title": "Paper Engines (live)"}})
    assert songs.list_all()[0]["title"] == "Paper Engines (live)"


def test_un_morceau_deja_sur_le_golem_est_saute(batch):
    _run(batch)
    SB._SCAN.update(dir=None)
    states = {it["path"]: it["state"] for it in SB.scan(str(batch["music"]))["items"]}
    assert states["Hollow Pines - Paper Engines.wav"] == "duplicate"


def test_ce_qui_est_refuse(batch, monkeypatch):
    sc = SB.scan(str(batch["music"]))
    one = [{"key": next(it["key"] for it in sc["items"] if it["state"] == "new")}]
    with pytest.raises(S.SeparationError, match="no song"):
        SB.start(str(batch["music"]), [{"key": "nope"}], "full")
    batch["engine"]["test"]["stems"] = ["low", "high"]
    with pytest.raises(S.SeparationError, match="no vocals stem"):
        SB.start(str(batch["music"]), one, "vocals")
    batch["engine"]["test"]["stems"] = list(STEMS)
    SB.start(str(batch["music"]), one, "full")
    with pytest.raises(S.SeparationError, match="already running"):
        SB.start(str(batch["music"]), one, "full")
    monkeypatch.setattr(S, "active_engine", lambda: (None, None))
    SB.cancel()
    with pytest.raises(S.SeparationError, match="no tested engine"):
        SB.start(str(batch["music"]), one, "full")


def test_annuler_et_reprendre(batch):
    sc = SB.scan(str(batch["music"]))
    items = [{"key": it["key"]} for it in sc["items"] if it["state"] == "new"]
    SB.start(str(batch["music"]), items, "full")
    b = SB.load()
    b["items"][0]["state"] = "running"                                       # le bridge s'est arrêté en plein morceau
    SB._save(b)
    SB.resume()
    assert [it["state"] for it in SB.load()["items"]] == ["waiting"] * 3
    st = SB.cancel()
    assert st["counts"]["cancelled"] == 3 and st["finished"]
    st = SB.retry(items[0]["key"])
    assert st["counts"]["waiting"] == 1
    SB._work()
    assert SB.state()["counts"]["done"] == 1 and len(songs.list_all()) == 1
    SB.dismiss()
    assert SB.state() is None


def test_l_etat_ne_montre_que_le_lot(batch):
    _run(batch)
    st = SB.state()
    assert st["name"] == "Covers" and st["mode"] == "full" and st["left_s"] == 0
    assert json.dumps(st)                                                    # sérialisable tel quel pour l'écran


def test_stocker_sur_golem_fm_demande_la_declaration_et_envoie_chaque_morceau_fini(batch, monkeypatch):
    from bridge import golemfm, inventory
    sc = SB.scan(str(batch["music"]))
    items = [{"key": it["key"]} for it in sc["items"] if it["state"] == "new"]
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://x", None))
    with pytest.raises(S.SeparationError, match="not paired"):
        SB.start(str(batch["music"]), items, "full", store=True, declared=True)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://x", "tok"))
    with pytest.raises(S.SeparationError, match="declaration"):              # la déclaration de CE lot (CGU §3.3)
        SB.start(str(batch["music"]), items, "full", store=True)
    sent = []

    def upload(gid, mode="full", url=None, declared=False):
        sent.append((gid, mode, declared))
        if len(sent) == 2:                                                    # golem.fm refuse le 2e (catégorie inconnue)
            raise inventory.UploadError("golem.fm found nothing it can keep in this file")
        return {"slug": "s-%d" % len(sent)}
    monkeypatch.setattr(inventory, "upload", upload)
    SB.start(str(batch["music"]), items, "full", store=True, declared=True)
    SB._work()
    st = SB.state()
    assert st["counts"]["done"] == 3 and st["stored"] == 2 and st["finished"]
    assert all(m == "full" and d is True for _, m, d in sent)
    failed = [it for it in st["items"] if it.get("store") == "failed"]
    assert len(failed) == 1 and "nothing it can keep" in failed[0]["store_error"]
    with pytest.raises(S.SeparationError, match="declaration"):
        SB.store()
    st = SB.store(declared=True)                                              # après coup : seulement ce qui n'est pas parti
    SB._work()
    assert SB.state()["stored"] == 3 and len(sent) == 4
    with pytest.raises(S.SeparationError, match="nothing to store"):
        SB.store(declared=True)


def test_un_morceau_audio_seul_est_une_chanson_en_attente_de_tab(batch):
    """Sans tab ni paroles, le .golem du lot est de la catégorie « track » (la règle partagée avec golem.fm)."""
    _run(batch)
    cats = {d["title"]: G.category_of(songs._path(d["id"])) for d in songs.list_all()}
    assert cats == {"Paper Engines": "song", "Glass Harbour": "track", "Velvet Static": "track"}


def test_les_deux_refus_de_declaration_se_disent_differemment():
    from bridge import inventory
    assert "tick the declaration" in inventory._why(422, "rights_not_declared", None)
    assert "open golem.fm" in inventory._why(403, "rights_not_declared", None)
