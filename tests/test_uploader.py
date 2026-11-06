# SPDX-License-Identifier: GPL-3.0-or-later
"""Le monteur (bridge/uploader.py) — sans serveur, sans Reaper, sans réseau.

Le serveur est simulé au niveau des deux fonctions du client (`_req`, `put_bytes`), ce qui
laisse tout le reste RÉEL : le transcodage FLAC, les sha, le découpage en tranches, la
reprise à l'offset, l'écriture de `upload` dans le manifeste.
Lancer : .venv/bin/python -m pytest tests/test_uploader.py -q
"""
import json
import os
import struct
import time

import pytest

from bridge import takes, uploader


def _wav(path, seconds=1, rate=8000, ch=1, bits=16):
    byte_rate = rate * ch * bits // 8
    data = b"\x01\x00" * (byte_rate * seconds // 2)
    fmt = struct.pack("<HHIIHH", 1, ch, rate, byte_rate, ch * bits // 8, bits)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(data)) + data
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks)


class FakeServer:
    """Le contrat de `band_recordings.py` : POST idempotent qui rend l'état par piste,
    PUT par tranches avec offset, complete qui exige toutes les pistes."""

    def __init__(self, fail_put_after=None, open_status=200):
        self.recs, self.puts, self.completed = {}, [], []
        self.fail_put_after, self.open_status = fail_put_after, open_status

    def req(self, path, body=None, token=None, **kw):
        if path == "/api/ext/recordings":
            if self.open_status != 200:
                return self.open_status, "refusé"
            rec = self.recs.setdefault(body["uid"], {"id": 42, "uid": body["uid"], "tracks": {}, "take": body.get("take")})
            for d in body["tracks"]:
                rec["tracks"].setdefault(d["idx"], {**d, "received": 0, "done": False})
            return 200, {"id": rec["id"], "uid": rec["uid"],
                         "tracks": list(rec["tracks"].values())}
        if path.endswith("/complete"):
            rec = next(iter(self.recs.values()))
            if any(not t["done"] for t in rec["tracks"].values()):
                return 409, "tracks not fully uploaded"
            self.completed.append(rec["uid"])
            return 200, {"id": rec["id"], "status": "complete"}
        return 404, "?"

    def put(self, path, data, token=None, **kw):
        rec = next(iter(self.recs.values()))
        idx = int(path.split("/tracks/")[1].split("?")[0])
        off = int(path.split("offset=")[1])
        t = rec["tracks"][idx]
        if self.fail_put_after is not None and len(self.puts) >= self.fail_put_after:
            return 500, "boom"
        if off != t["received"]:
            return 409, f"Out-of-order chunk: expected offset {t['received']}"
        t["received"] += len(data)
        t["done"] = t["received"] >= t["size_bytes"]
        self.puts.append((idx, off, len(data)))
        return 200, dict(t)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(takes, "RECORDINGS", str(tmp_path))
    monkeypatch.setattr(uploader, "CACHE", str(tmp_path / ".upload"))
    monkeypatch.setattr(uploader, "CHUNK", 4096)          # plusieurs tranches par piste
    monkeypatch.setattr(uploader, "can_run", lambda: (True, None))
    d = tmp_path / "perf-20260907-120000"
    d.mkdir()
    for n in ("Mix.wav", "Input-1.wav", "DI-Sandbox-Input-1.wav"):
        _wav(d / n, seconds=2)
    (d / "MIDI-Input-3.mid").write_bytes(b"MThd\0\0\0\6")
    json.dump({"kind": "take", "mode": "tracks_di", "started_at": "2026-09-07T12:00:00",
               "band": {"id": "b_haw6vqzh5u", "name": "Night Shift", "source": "cache"},
               "files": ["Mix.wav"]}, open(d / "take.json", "w"))
    return str(d)


def _wire(monkeypatch, srv):
    from bridge import golemfm
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("http://x", "tok"))
    monkeypatch.setattr(golemfm, "_req", srv.req)
    monkeypatch.setattr(golemfm, "put_bytes", srv.put)


def test_par_defaut_les_lanes_traitees_et_le_manifeste(rig, monkeypatch):
    """DI et MIDI ne partent PAS d'office : « le mix suffit à décider si la prise vaut
    quelque chose »."""
    srv = FakeServer()
    _wire(monkeypatch, srv)
    rep = uploader.upload_take("perf-20260907-120000")
    assert rep["ok"] and rep["rec_id"] == 42
    rec = srv.recs["perf-20260907-120000"]
    kinds = sorted(t["kind"] for t in rec["tracks"].values())
    assert kinds == ["meta", "mix", "track"]
    assert all(t["filename"].endswith((".flac", ".json")) for t in rec["tracks"].values())
    assert srv.completed == ["perf-20260907-120000"]


def test_les_kinds_ajoutent_la_di_et_le_midi(rig, monkeypatch):
    srv = FakeServer()
    _wire(monkeypatch, srv)
    uploader.upload_take("perf-20260907-120000", kinds=("mix", "track", "di", "midi"))
    kinds = sorted(t["kind"] for t in srv.recs["perf-20260907-120000"]["tracks"].values())
    assert kinds == ["di", "meta", "midi", "mix", "track"]


def test_le_manifeste_porte_letat_puis_done(rig, monkeypatch):
    srv = FakeServer()
    _wire(monkeypatch, srv)
    uploader.upload_take("perf-20260907-120000")
    up = json.load(open(os.path.join(rig, "take.json")))["upload"]
    assert up["state"] == "done" and up["rec_id"] == 42 and up["pct"] == 100


def test_une_prise_montee_sort_de_lindex(rig, monkeypatch):
    srv = FakeServer()
    _wire(monkeypatch, srv)
    assert takes.pending()["pending_total"] == 1
    uploader.upload_take("perf-20260907-120000")
    assert takes.pending()["pending_total"] == 0          # « la liste est ce qui reste »


def test_la_reprise_repart_de_loffset_du_serveur(rig, monkeypatch):
    """Coupure au milieu : le serveur garde ce qu'il a reçu, et le rack n'a RIEN à mémoriser."""
    srv = FakeServer(fail_put_after=2)
    _wire(monkeypatch, srv)
    rep = uploader.upload_take("perf-20260907-120000")
    assert not rep["ok"] and rep["reason"] == "put_failed"
    partiel = sum(t["received"] for t in srv.recs["perf-20260907-120000"]["tracks"].values())
    assert partiel > 0

    srv.fail_put_after = None
    n_avant = len(srv.puts)
    rep = uploader.upload_take("perf-20260907-120000")
    assert rep["ok"]
    renvoye = sum(sz for _, _, sz in srv.puts[n_avant:])
    assert renvoye < sum(t["size_bytes"] for t in srv.recs["perf-20260907-120000"]["tracks"].values())


def test_le_quota_est_un_refus_lisible_pas_une_boucle(rig, monkeypatch):
    srv = FakeServer(open_status=413)
    _wire(monkeypatch, srv)
    rep = uploader.upload_take("perf-20260907-120000")
    assert not rep["ok"] and rep["reason"] == "quota"
    up = json.load(open(os.path.join(rig, "take.json")))["upload"]
    assert up["state"] == "refused" and up["code"] == "quota"
    assert uploader.due() == []                           # on ne retente pas un refus


def test_une_prise_sans_tag_ne_monte_pas(rig, monkeypatch):
    srv = FakeServer()
    _wire(monkeypatch, srv)
    man = json.load(open(os.path.join(rig, "take.json")))
    man["band"] = None
    json.dump(man, open(os.path.join(rig, "take.json"), "w"))
    assert uploader.upload_take("perf-20260907-120000")["reason"] == "untagged"
    assert uploader.due() == []


def test_le_monteur_se_tait_pendant_quon_joue(rig, monkeypatch):
    srv = FakeServer()
    _wire(monkeypatch, srv)
    monkeypatch.setattr(uploader, "can_run", lambda: (False, "rec"))
    assert uploader.tick()["reason"] == "rec"
    assert srv.recs == {}


def test_les_noms_reaper_sont_nettoyes():
    """`#` est interdit par FILENAME_RE : sans nettoyage, le serveur refuse la DÉCLARATION,
    donc la prise entière, pour un caractère."""
    import re
    FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$")
    for bad in ("02-Sandbox #Input 2-260726_1807.wav", "#weird.wav", "  spaced #1.wav"):
        assert FILENAME_RE.match(uploader.clean_name(bad)), bad


# ── publication des presets au fil de l'eau (message-maestrium-ranger-prises.md §6) ────────
def test_lempreinte_ignore_lhabillage_pas_le_son(tmp_path, monkeypatch):
    """Renommer une couleur de tuile ne doit RIEN republier ; changer un ampli, si. Sans ça,
    le Designer — qui sauvegarde à chaque geste — pousserait à chaque clic de couleur."""
    from bridge import store, tones_sync
    preset = {"id": "p1", "bpm": 120, "lanes": [{"blocks": [{"type": "amp", "id": "a"}]}]}
    pub = tmp_path / ".published.json"
    monkeypatch.setattr(tones_sync, "_PUBLISHED", str(pub))
    monkeypatch.setattr(store, "load_preset", lambda pid: preset)

    assert tones_sync.needs_publish("p1", preset) is True          # jamais publié
    from bridge import preset_export
    tones_sync._mark_published("p1", preset_export.fingerprint(preset))
    assert tones_sync.needs_publish("p1", preset) is False

    habillage = {**preset, "colors": {"tile": "red"}, "anims": ["pulse"], "preview": {"x": 1}}
    assert tones_sync.needs_publish("p1", habillage) is False      # cosmétique : rien
    son = {**preset, "bpm": 132}
    assert tones_sync.needs_publish("p1", son) is True             # le son a bougé


def test_publie_vers_la_dev_nest_pas_publie_en_prod(tmp_path, monkeypatch):
    """Le bug de `1983` (2026-09-29) : le map « déjà publié » était à plat. Publié vers la base de DEV,
    un preset passait pour publié en PROD après le changement d'adresse — et n'y arrivait jamais."""
    import json
    from bridge import preset_export, tones_sync
    preset = {"id": "1983", "bpm": 90, "lanes": [{"blocks": [{"type": "amp", "id": "a"}]}]}
    pub = tmp_path / ".published.json"
    monkeypatch.setattr(tones_sync, "_PUBLISHED", str(pub))
    base = {"url": "http://localhost:5173"}
    monkeypatch.setattr(tones_sync, "_cfg", lambda: (base["url"], "gmt_x"))
    tones_sync._mark_published("1983", preset_export.fingerprint(preset))
    assert tones_sync.needs_publish("1983", preset) is False          # déjà publié… vers la dev
    base["url"] = "https://golem.fm/"
    assert tones_sync.needs_publish("1983", preset) is True           # la prod ne l'a jamais reçu
    # l'ancienne forme (à plat) ne s'attribue à aucun serveur : jetée, tout repart une fois
    json.dump({"1983": preset_export.fingerprint(preset)}, open(pub, "w"))
    assert tones_sync.needs_publish("1983", preset) is True


def test_lexport_resout_un_ref_en_forme_uid_comme_le_moteur():
    """Le 2026-09-29, AUCUN preset n'est arrivé en prod : l'export cherchait `caps["t3k:1148"]` alors que
    son index est tenu par l'id de catalogue (« 1148 ») — les 13 captures des 6 presets sortaient
    « missing », publication refusée. Le moteur accepte les deux formes depuis le 11/09 ; l'export aussi."""
    from bridge import preset_export
    pack = {"uid": "t3k:1148", "kind": "outboard", "title": "UA 1176",
            "assets": [{"sha256": "L", "extra": {"model_id": "420079"}}, {"sha256": "R", "extra": {"model_id": "420078"}}]}
    caps = {"1148": pack}
    for ref in ("t3k:1148", "1148", "comps/1148"):
        got = preset_export._resolve({"type": "comp-nam", "ref": ref, "model": "420078"}, caps, {}, {})
        assert got and got[1][0]["sha256"] == "R", ref
    assert preset_export._resolve({"type": "comp-nam", "ref": "t3k:9999"}, caps, {}, {}) is None


def test_un_riff_declare_une_seule_verite(rig, monkeypatch):
    """Prise 175 (2026-09-30) : golem.fm stocke le `take` de l'OUVERTURE et apparie les fichiers de lane
    aux pistes AU NOM EXACT. On envoyait le manifeste local (.wav, « scores/… ») : lane sans fichier, riff
    muet. La déclaration porte la même copie que la piste meta — chaque fichier de lane EST une piste."""
    os.makedirs(os.path.join(rig, "scores"))
    open(os.path.join(rig, "scores", "Input-1.musicxml"), "w").write("<score/>")
    man = json.load(open(os.path.join(rig, "take.json")))
    man.update(kind="riff", by="alex", lanes=[{"id": "guitar-1", "input": "1", "files": {
        "di": "DI-Sandbox-Input-1.wav", "wet": "Input-1.wav", "score": "scores/Input-1.musicxml"}}])
    json.dump(man, open(os.path.join(rig, "take.json"), "w"))
    srv = FakeServer()
    _wire(monkeypatch, srv)
    assert uploader.upload_take("perf-20260907-120000")["ok"]
    rec = srv.recs["perf-20260907-120000"]
    names = {t["filename"]: t["kind"] for t in rec["tracks"].values()}
    files = rec["take"]["lanes"][0]["files"]
    assert files == {"di": "DI-Sandbox-Input-1.flac", "wet": "Input-1.flac", "score": "Input-1.musicxml"}
    assert all(f in names for f in files.values()) and names["Input-1.musicxml"] == "score"
    assert "Mix.flac" not in names and "upload" not in rec["take"]


def _state(rig, up):
    man = json.load(open(os.path.join(rig, "take.json")))
    man["upload"] = up
    json.dump(man, open(os.path.join(rig, "take.json"), "w"))


def test_un_riff_en_transcription_n_est_pas_du(rig):
    """Rec 242 (2026-10-29) : la fenêtre de drop passée, une passe du monteur montait le riff SANS sa partition,
    puis la fin de la transcription le remontait avec une piste de plus — golem.fm refusait (409)."""
    _state(rig, {"state": "transcribing", "since": time.time()})
    assert uploader.due() == []
    _state(rig, {"state": "transcribing", "since": time.time() - uploader.TRANSCRIBE_STALE_S - 1})
    assert uploader.due() == ["perf-20260907-120000"]                   # abandonnée : monte sans partition


def test_des_uids_demandes_dont_aucun_n_est_du_ne_montent_rien(rig, monkeypatch):
    got = []
    monkeypatch.setattr(uploader, "tick", lambda uids=None, kinds=None: got.append(uids))
    monkeypatch.setattr(uploader.threading, "Thread", lambda target, daemon: type("T", (), {"start": lambda s: target()})())
    uploader.queue(["perf-inconnue"])
    uploader.queue()
    assert got == [set(), None]                                          # jamais « tout ce qui est dû » sur demande
