# SPDX-License-Identifier: GPL-3.0-or-later
"""Karaoké au rack (docs/karaoke.md, lot 1) : cache, mix, chargement, enchaînement, fin, sortie, WS.
Reaper et le rappel sont simulés : on vérifie ce que le rack DÉCIDE et ce qu'il RÉPOND à golem.fm."""
import json
import os

import pytest

from bridge import config as C
from bridge import karaoke as K
from bridge import golemfm, store
from bridge.state import state


class FakeCtl:
    def __init__(self):
        self.calls = []

    def load(self, slug):
        self.calls.append(("load", slug))
        state.backing = {**state.backing, "present": True, "slug": slug}
        return {"ok": True}

    def adopt(self, songs):
        self.calls.append(("adopt", [s["slug"] for s in songs]))

    def mix(self, stem, mute, vol):
        self.calls.append(("mix", stem, mute, vol))

    def stop(self):
        self.calls.append(("stop",))

    def unload(self):
        self.calls.append(("unload",))
        state.backing = {**state.backing, "present": False, "slug": None}


@pytest.fixture
def kar(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "BACKING_DIR", str(tmp_path / "backing"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    os.makedirs(C.PRESETS_DIR)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", "tok"))
    served = {"rev": 2, "title": "Song", "duration_ms": 180000,
              "stems": {s: f"/api/ext/files/k/{s}.mp3" for s in golemfm.STEMS}}
    reqs = []

    def fake_req(path, token=None, timeout=None, raw=False, **kw):
        reqs.append(path)
        if path.startswith("/api/ext/karaoke/"):
            if "notready" in path:
                return 404, "not_ready"
            return (200, dict(served)) if "missing" not in path else (404, "not found")
        return 200, b"ID3" + path.encode()

    monkeypatch.setattr(golemfm, "_req", fake_req)
    ctl = FakeCtl()
    monkeypatch.setattr(K, "_ctl", ctl)
    K._deactivate()
    K._cur.update(ends=None, prefetched=None)
    K.drain()
    monkeypatch.setattr(state, "mode", {"id": "home", "name": "Home", "services": {}})
    monkeypatch.setattr(state, "perf", {})
    store._write_json_atomic(os.path.join(C.PRESETS_DIR, "night-shift.json"),
                             {"id": "night-shift", "name": "SC", "lanes_v": 2,
                              "lanes": [{"id": "gtr", "role": "guitar", "input": 1, "chain": []}],
                              "scenes": [{"id": "A"}, {"id": "B"}]})
    monkeypatch.setattr(state, "preset_id", "night-shift")
    monkeypatch.setattr(state, "scene_id", "B")
    monkeypatch.setattr(state, "backing", {"present": False, "slug": None})
    recalls = []

    from bridge import recall as R

    def fake_recall(pid, scene, line=None):
        recalls.append((pid, scene))
        state.preset_id = pid
        state.scene_id = scene
        if pid == store.KARAOKE_ID:                 # backing.on_recall charge songs[0] (+0,7 s, ici tout de suite)
            p = store.load_preset(pid)
            state.backing = {**state.backing, "present": True, "slug": p["backing"]["songs"][0]["slug"]}
        return True

    monkeypatch.setattr(R, "do_recall", fake_recall)
    monkeypatch.setattr(R, "check_preset", lambda preset, scene: None)
    return {"served": served, "reqs": reqs, "ctl": ctl, "recalls": recalls}


def _frames():
    return K.drain()


def test_slug_jamais_en_collision_avec_une_chanson():
    assert K.slug_of("k_8F2c/../x") == "k-k_8f2c-x"
    with pytest.raises(ValueError):
        K.slug_of("///")


def test_le_mix_de_golem_fm_devient_un_mix_de_backing_complet():
    m = K.backing_mix({"vocals": "guide", "muted": ["guitar", "nope"]})
    assert m["vocals"] == {"mute": 0, "vol": pytest.approx(0.1995, abs=1e-4)}      # −14 dB
    assert m["guitar"]["mute"] == 1 and m["drums"] == {"mute": 0, "vol": 1.0}
    assert set(m) == set(golemfm.STEMS)                                          # l'état COMPLET
    assert K.backing_mix({"vocals": "off"})["vocals"]["mute"] == 1
    assert K.backing_mix({"vocals": "guide", "guide_db": -6})["vocals"]["vol"] == pytest.approx(0.5012, abs=1e-3)
    with pytest.raises(ValueError):
        K.backing_mix({"vocals": "loud"})
    assert K.public_mix({"vocals": "guide", "muted": ["other", "bass"]}) == {"vocals": "guide", "muted": ["bass", "other"], "guide_db": -14}


def test_fetch_met_en_cache_avec_la_revision_et_dit_sa_progression(kar):
    meta = K.fetch("k1", 2, {"req": "r1"})
    assert meta["rev"] == 2 and meta["karaoke_id"] == "k1"
    d = golemfm.song_dir("k-k1")
    assert sorted(os.listdir(d)) == sorted([s + ".mp3" for s in golemfm.STEMS] + ["meta.json"])
    assert K.is_cached("k1", 2) and not K.is_cached("k1", 3)
    prog = [f for f in _frames() if f["state"] == "fetching"]
    assert prog and prog[-1]["stems_done"] == 6 and prog[-1]["req"] == "r1"
    n = len(kar["reqs"])
    K.fetch("k1", 2)                                            # en cache : rien n'est retéléchargé
    assert len(kar["reqs"]) == n


def test_le_cache_evince_les_moins_recemment_joues(kar, monkeypatch):
    monkeypatch.setattr(K, "CACHE_MAX", 2)
    K.fetch("a"); K.fetch("b")
    K._write_meta("k-a", dict(golemfm.read_meta("k-a"), played_at=999))   # « a » vient d'être joué
    K._write_meta("k-b", dict(golemfm.read_meta("k-b"), played_at=1))     # « b » est le plus ancien
    K.fetch("c")                                    # au-delà du plafond : on évince au téléchargement
    assert K.is_cached("a") and K.is_cached("c") and not K.is_cached("b")
    # la chanson COURANTE n'est jamais évincée, même la plus ancienne
    K._cur["slug"] = "k-a"
    K._write_meta("k-a", dict(golemfm.read_meta("k-a"), played_at=1))
    K.fetch("d")
    assert K.is_cached("a") and K.is_cached("d")


def test_premier_load_monte_le_preset_volatil_et_repond_ready(kar):
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1", "rev": 2}, "mix": {"vocals": "guide", "muted": ["guitar"]},
             "voice": None, "req": "r1"})
    doc = json.load(open(os.path.join(C.PRESETS_DIR, store.KARAOKE_FILE)))
    # SANS VOIX : par-dessus le preset joué (un rig sans lane n'existe pas) — la guitare continue de sonner
    assert doc["id"] == "karaoke" and [L["id"] for L in doc["lanes"]] == ["gtr"]
    assert doc["backing"]["songs"][0]["slug"] == "k-k1" and "__patch" not in doc
    assert kar["recalls"] == [("karaoke", "B")]                 # la scène que le musicien jouait
    assert K._cur["prev"] == ("night-shift", "B")
    ready = [f for f in _frames() if f["state"] == "ready"]
    assert ready == [{"type": "karaoke", "state": "ready", "id": "k1", "rev": 2, "voice": "none",
                      "mix": {"vocals": "guide", "muted": ["guitar"], "guide_db": -14}, "req": "r1"}]
    meta = golemfm.read_meta("k-k1")
    assert meta["mix"]["guitar"]["mute"] == 1 and meta["played_at"]          # le mix voyage par le meta


def test_meme_voix_enchaine_sans_rappel_et_garde_le_micro(kar, monkeypatch):
    monkeypatch.setattr(K, "_voice_lane_preset", lambda v: ({"lanes_v": 2, "lanes": [{"id": "x"}], "scenes": [{"id": "A"}]}, "mounted", None))
    voice = {"patch_id": "kite-voice", "sha": "abc"}
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1"}, "voice": voice})
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k2"}, "voice": voice, "req": "r2"})
    assert kar["recalls"] == [("karaoke", "A")]                  # UN seul rappel pour deux chansons
    assert ("load", "k-k2") in kar["ctl"].calls
    last = [f for f in _frames() if f["state"] == "ready"][-1]
    assert last["voice"] == "kept" and last["id"] == "k2"
    doc = json.load(open(os.path.join(C.PRESETS_DIR, store.KARAOKE_FILE)))
    assert doc["backing"]["songs"][0]["slug"] == "k-k2"         # un rappel de scène ne ramène pas k1
    # la voix CHANGE : la lane est rebâtie, et la réponse le dit
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k3"}, "voice": {"patch_id": "other", "sha": "def"}})
    assert len(kar["recalls"]) == 2 and K._cur["prev"] == ("night-shift", "B")   # prev = avant le PREMIER load
    assert [f for f in _frames() if f["state"] == "ready"][-1]["voice"] == "rebuilt"


def test_la_fin_vient_du_compteur_jamais_d_une_pause(kar):
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1"}})
    _frames()
    K.on_backing({"slug": "k-k1", "ends": 4, "playing": True})     # baseline
    K.on_backing({"slug": "k-k1", "ends": 4, "playing": False, "paused": True})
    assert _frames() == []                                        # une pause n'est pas une fin
    K.on_backing({"slug": "k-k1", "ends": 5, "playing": False, "len": 180.0})
    assert _frames() == [{"type": "karaoke", "state": "ended", "id": "k1", "posMs": 180000}]
    K.on_backing({"slug": "k-k1", "ends": 0})                       # Reaper relancé : compteur à zéro, rien
    assert _frames() == []


def test_un_preset_rappele_au_rack_quitte_le_karaoke(kar):
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1"}})
    _frames()
    K.on_recall("karaoke")
    K.on_recall(None)                                               # changement de scène
    assert K.active() and _frames() == []
    K.on_recall("velvetine")
    assert not K.active() and _frames() == [{"type": "karaoke", "state": "left", "id": "k1"}]


def test_stop_rappelle_le_preset_d_avant(kar):
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1"}})
    K._stop({"cmd": "karaoke-stop", "req": "s"})
    assert kar["recalls"][-1] == ("night-shift", "B") and not K.active()
    assert ("unload",) in kar["ctl"].calls
    assert _frames()[-1] == {"type": "karaoke", "state": "stopped", "id": "k1", "req": "s"}


def test_refus_total_dit_pourquoi_et_golem_fm_joue_dans_le_navigateur(kar, monkeypatch):
    monkeypatch.setattr(state, "perf", {"recording": True})
    K._safe(K._load, {"cmd": "karaoke-load", "karaoke": {"id": "k1"}, "req": "r"})
    assert _frames() == [{"type": "karaoke", "state": "refused", "id": "k1", "why": "a take is recording", "req": "r"}]
    monkeypatch.setattr(state, "perf", {})
    K._safe(K._load, {"cmd": "karaoke-load", "karaoke": {"id": "missing"}})
    last = [f for f in _frames() if f["state"] == "refused"][-1]
    assert last["id"] == "missing" and last["why"].startswith("song missing not found on golem.fm")


def test_prefetch_ne_touche_pas_a_reaper(kar):
    K._prefetch({"cmd": "karaoke-prefetch", "karaoke": {"id": "k9", "rev": 2}, "req": "p"})
    assert kar["recalls"] == [] and kar["ctl"].calls == []
    assert _frames()[-1] == {"type": "karaoke", "state": "cached", "id": "k9", "rev": 2, "req": "p"}


def test_voix_absente_du_rack_les_stems_jouent_quand_meme(kar, monkeypatch):
    from bridge import patches as P
    monkeypatch.setattr(P, "get_patch", lambda pid: None)
    preset, status, why = K._voice_lane_preset({"patch_id": "ghost"})
    assert preset is None and status == "refused" and why == "patch ghost is not on this rack"
    monkeypatch.setattr(state, "mode", {"name": "Gig", "services": {"voice": False}})
    assert K._voice_lane_preset({"patch_id": "x", "sha": "y"})[1:] == ("none", "the Gig mode keeps the voice off")


def test_le_ws_route_les_commandes_et_marque_la_trame(kar, monkeypatch):
    from bridge import follow_uplink as F
    got = []
    monkeypatch.setattr(K, "handle", lambda msg: got.append(msg["cmd"]) or True)
    F._apply_cmd({"type": "cmd", "cmd": "karaoke-mix", "mix": {}})
    assert got == ["karaoke-mix"]
    K._cur.update(active=True, id="k1", slug="k-k1", mix={"vocals": "off", "muted": []})
    monkeypatch.setattr(state, "backing", {"slug": "k-k1", "playing": True, "pos": 12.5, "t": None})
    f1, f2 = F._frame(1), F._frame(2)
    assert f1["src"] == "karaoke" and f1["id"] == "k1" and f1["mix"] == {"vocals": "off", "muted": []}
    assert "mix" not in f2                                          # le mix ne se répète pas


def test_le_preset_volatil_est_servi_sous_son_id_reserve(kar):
    store._write_json_atomic(os.path.join(C.PRESETS_DIR, store.KARAOKE_FILE),
                             {"lanes_v": 2, "lanes": [], "scenes": [{"id": "A"}], "name": "Karaoke"})
    p = store.load_preset("karaoke")
    assert p["id"] == "karaoke" and p["name"] == "Karaoke"
    assert "karaoke" not in [x.get("id") for x in store.load_presets()]   # jamais au catalogue


def test_un_job_recu_ne_porte_jamais_de_document_interne(monkeypatch):
    from bridge import tones_jobs as T
    seen = {}
    monkeypatch.setitem(T._HANDLERS, "patch-try", lambda j: seen.update(j) or {})
    monkeypatch.setattr(T, "_ack", lambda *a, **k: None, raising=False)
    try:
        T._run_job({"action": "patch-try", "id": "j1", "_doc": {"evil": 1}})
    except Exception:
        pass
    assert "_doc" not in seen
    assert T._job_doc({"_doc": {"a": 1}}, "x.tmp") == {"a": 1}


def test_une_voix_qui_ne_compile_pas_retombe_sur_le_preset_joue(kar, monkeypatch):
    from bridge import recall as R
    monkeypatch.setattr(K, "_voice_lane_preset", lambda v: ({"lanes_v": 2, "lanes": [{"id": "v"}], "scenes": [{"id": "A"}]}, "mounted", None))
    monkeypatch.setattr(R, "check_preset", lambda p, sc: "voice#1 is off in this mode" if [L["id"] for L in p["lanes"]] == ["v"] else None)
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1"}, "voice": {"patch_id": "x", "sha": "y"}})
    ready = [f for f in _frames() if f["state"] == "ready"][-1]
    assert ready["voice"] == "refused" and ready["voice_why"] == "voice#1 is off in this mode"
    doc = json.load(open(os.path.join(C.PRESETS_DIR, store.KARAOKE_FILE)))
    assert [L["id"] for L in doc["lanes"]] == ["gtr"]


def test_sans_preset_au_rack_et_sans_voix_le_refus_est_dit(kar, monkeypatch):
    monkeypatch.setattr(state, "preset_id", None)
    K._safe(K._load, {"cmd": "karaoke-load", "karaoke": {"id": "k1"}})
    assert _frames()[-1]["why"] == "no preset is loaded on the rack to play the song over"


def test_une_chanson_pas_prete_le_dit(kar):
    K._safe(K._prefetch, {"cmd": "karaoke-prefetch", "karaoke": {"id": "notready"}})
    assert "not ready yet" in _frames()[-1]["why"]


def test_l_id_entier_de_golem_fm_revient_entier(kar):
    """golem.fm envoie un id ENTIER et un rev texte : les réponses rendent l'id tel qu'il est venu,
    sinon le navigateur ne retrouve pas sa chanson (42 != "42")."""
    kar["served"]["rev"] = "a1b2c3d4e5f6"
    K._load({"cmd": "karaoke-load", "karaoke": {"id": 42, "rev": "a1b2c3d4e5f6"}})
    ready = [f for f in _frames() if f["state"] == "ready"][-1]
    assert ready["id"] == 42 and ready["rev"] == "a1b2c3d4e5f6" and K.is_cached(42, "a1b2c3d4e5f6")
    K.on_backing({"slug": "k-42", "ends": 1}); K.on_backing({"slug": "k-42", "ends": 2, "len": 1})
    assert _frames()[-1]["id"] == 42


def test_le_patch_installe_au_rack_fait_autorite_sur_le_sha(kar, monkeypatch):
    """Essai réel (2026-10-06) : golem.fm envoyait le sha d'une copie vieille de deux semaines."""
    from bridge import patches as P, tones_jobs as T
    local = {"id": "1983-2", "role": "voice", "chain": {"pre": [], "split": None, "post": []}}
    monkeypatch.setattr(P, "get_patch", lambda pid: local if pid == "1983-2" else None)
    seen = {}

    def fake_trial(job, tmp):
        seen.update(job)
        lane = {"id": "voice-try", "role": "voice", "in_sel": "2"}
        return {"lanes": [lane], "scenes": [{"id": "A"}]}, "voice", lane, [{"id": "A"}], {}, []
    monkeypatch.setattr(T, "_trial_preset", fake_trial)
    preset, status, _ = K._voice_lane_preset({"patch_id": "1983-2", "sha": "old"})
    assert status == "mounted" and seen.get("_doc") is local and "sha" not in seen
    assert K._cur["voice_src"] == "rack" and K._cur["voice_in"] == "2"
    seen.clear()
    K._voice_lane_preset({"patch_id": "not-here", "sha": "abc"})            # absent du rack : le sha
    assert seen.get("sha") == "abc" and K._cur["voice_src"] == "golem.fm"


def test_ready_dit_l_entree_que_la_voix_ecoute(kar, monkeypatch):
    def fake_voice(v):
        K._cur.update(voice_in="2", voice_src="rack")
        return {"lanes_v": 2, "lanes": [{"id": "v"}], "scenes": [{"id": "A"}]}, "mounted", None
    monkeypatch.setattr(K, "_voice_lane_preset", fake_voice)
    K._load({"cmd": "karaoke-load", "karaoke": {"id": "k1"}, "voice": {"patch_id": "1983-2"}})
    ready = [f for f in _frames() if f["state"] == "ready"][-1]
    assert ready["voice_input"] == "IN 2" and ready["voice_src"] == "rack"


def test_play_sans_rien_de_charge_est_ignore(kar, monkeypatch):
    from bridge import follow_uplink as F
    calls = []
    monkeypatch.setattr(F, "_backing_ctl", type("C", (), {"play": lambda self: calls.append("play")})())
    monkeypatch.setattr(state, "backing", {"present": False})
    F._apply_cmd({"type": "cmd", "cmd": "play"})
    assert calls == []
    monkeypatch.setattr(state, "backing", {"present": True, "slug": "k-1"})
    F._apply_cmd({"type": "cmd", "cmd": "play"})
    assert calls == ["play"]


def test_un_original_enregistre_garde_tous_ses_stems_et_coupe_sa_voix(kar):
    """Lot 9 (golem.fm, 2026-10-08) : un original enregistré a un stem PAR PARTIE (un .flac possible) et
    `voice_stems` dit lesquels font la voix. Avant : les stems hors des six étaient JETÉS, et seule `vocals`
    se coupait — la voix d'un original jouait en entier."""
    def served_req(path, token=None, timeout=None, raw=False, **kw):
        if path.startswith("/api/ext/karaoke/"):
            return 200, {"rev": 1, "title": "Original", "duration_ms": 200000,
                         "stems": {"guitar-1": "/api/ext/files/o/guitar-1.flac", "guitar-2": "/api/ext/files/o/guitar-2.mp3",
                                   "voice-1": "/api/ext/files/o/voice-1.flac", "voice-2": "/api/ext/files/o/voice-2.flac",
                                   "drums-1": "/api/ext/files/o/drums-1.mp3"},
                         "voice_stems": ["voice-1", "voice-2"]}
        return 200, b"fLaC" + path.encode()
    import bridge.golemfm as M
    old = M._req
    M._req = served_req
    try:
        meta = K.fetch("orig1", 1)
    finally:
        M._req = old
    d = golemfm.song_dir("k-orig1")
    assert sorted(f for f in os.listdir(d) if f != "meta.json") == ["drums-1.mp3", "guitar-1.flac", "guitar-2.mp3",
                                                                    "voice-1.flac", "voice-2.flac"]
    assert meta["voice_stems"] == ["voice-1", "voice-2"]
    assert set(golemfm.local_files("k-orig1")) == {"guitar-1", "guitar-2", "voice-1", "voice-2", "drums-1"}
    assert golemfm.stems_of("k-orig1") == ["guitar-1", "guitar-2", "voice-1", "voice-2", "drums-1"]
    off = K.backing_mix({"vocals": "off", "muted": ["guitar-2", "vocals"]}, meta)
    assert off["voice-1"]["mute"] == 1 and off["voice-2"]["mute"] == 1 and off["guitar-2"]["mute"] == 1
    assert off["guitar-1"]["mute"] == 0 and "vocals" not in off                  # « vocals » n'existe pas ici
    guide = K.backing_mix({"vocals": "guide", "guide_db": -6}, meta)
    assert guide["voice-1"]["vol"] == pytest.approx(0.5012, abs=1e-3) and guide["drums-1"]["vol"] == 1.0
    assert K.public_mix({"vocals": "off", "muted": ["guitar-2", "nope"]}, meta)["muted"] == ["guitar-2"]


def test_une_chanson_sur_le_rack_a_la_meme_version_joue_son_golem(kar, monkeypatch, tmp_path):
    """Lot 9 (contrat golem.fm 2026-10-08) : karaoke-load porte `song_id` + `golem_etag`. Le rack a la chanson, avec
    ses stems, à la MÊME version : son .golem joue, rien n'est téléchargé. Version différente : téléchargement."""
    from bridge import golemfile as G, golem_pull as GP, songs as S
    sid = "rs:" + "9a" * 16
    src = str(tmp_path / "s.golem")
    G.write(src, {"type": "song", "id": sid, "title": "Paper Kite", "kind": "cover"},
            {"stems/drums.mp3": b"ID3d", "stems/vocals.mp3": b"ID3v"})
    S.install_golem(src, slug="kite")
    GP._set_etag("kite", "E1")
    assert K._local_golem({"song_id": sid, "golem_etag": "E1"}) == sid
    assert K._local_golem({"song_id": sid, "golem_etag": "E2"}) is None          # autre version : on télécharge
    assert K._local_golem({"song_id": None, "golem_etag": "E1"}) is None         # karaoké déposé, sans chanson
    meta = K._kmeta(sid)
    assert set(meta["stems"]) == {"drums", "vocals"} and meta["voice_stems"] == ["vocals"]
    assert K.backing_mix({"vocals": "off"}, meta)["vocals"]["mute"] == 1


def test_le_relais_des_paroles_d_une_chanson_jouee_depuis_son_golem(kar, tmp_path):
    """Lot 9 (contrat golem.fm 2026-10-08) : le rack envoie le TEXTE BRUT du .lrc, avec karaoke_id ET song_id, et le
    renvoie sur lyrics-get — pour la chanson EN COURS seulement. Jamais pour un karaoké du cache k-<id>."""
    from bridge import golemfile as G, songs as S
    sid = "rs:" + "7b" * 16
    src = str(tmp_path / "s.golem")
    G.write(src, {"type": "song", "id": sid, "title": "Paper Kite", "kind": "cover"},
            {"stems/vocals.mp3": b"ID3v", "lyrics/song.lrc": "[00:12.00]Freedom ».".encode()})
    S.install_golem(src)
    K.drain()
    K._cur.update(active=True, id="k77", slug=sid, local=False)
    assert K.send_lyrics()
    f = [x for x in K.drain() if x.get("type") == "lyrics"][0]
    assert f["karaoke_id"] == "k77" and f["song_id"] == sid and f["format"] == "lrc"
    assert f["text"] == "[00:12.00]Freedom »." and len(f["rev"]) == 64
    assert K.lyrics_get({"type": "lyrics-get", "song_id": sid}) and K.drain()
    assert not K.lyrics_get({"type": "lyrics-get", "karaoke_id": "autre"})        # pas la chanson en cours
    K._cur.update(slug="k-k77")
    assert not K.send_lyrics()                                                     # cache golem.fm : il les sert lui-même
    K._deactivate()


def test_un_morceau_prete_dit_quoi_faire_au_lieu_d_echouer(kar):
    """Q2 : une ligne prêtée répond avec `stems_denied` — le rack ne tente aucun téléchargement et dit quoi faire."""
    import bridge.golemfm as M
    old = M._req
    calls = []
    def denied(path, token=None, timeout=None, raw=False, **kw):
        calls.append(path)
        if path.startswith("/api/ext/karaoke/"):
            return 200, {"rev": 1, "title": "Annie-Dog", "song_id": "bs:2", "golem_etag": "x", "stems_denied": True,
                         "stems": {"vocals": "/api/ext/files/a/vocals.mp3"}}
        return 403, "denied"
    M._req = denied
    try:
        with pytest.raises(RuntimeError, match="lent song: drop your own .golem on this golem"):
            K.fetch("lent1", 1)
    finally:
        M._req = old
    assert not [c for c in calls if c.startswith("/api/ext/files/")]                # aucun stem demandé


# ── `golem: {id}` : jouer la COPIE DU RACK d'une ligne Vocals que golem.fm n'a plus (contrat 2026-10-17) ──────────
def _song(tmp_path, sid, title, members):
    from bridge import golemfile as G, songs as S
    src = str(tmp_path / (title + ".golem"))
    G.write(src, {"type": "song", "id": sid, "title": title, "kind": "cover"}, members)
    S.install_golem(src)


def test_la_copie_du_rack_joue_sans_route_ni_telechargement(kar, tmp_path):
    sid = "rs:" + "c1" * 16
    _song(tmp_path, sid, "Pour que tu m'aimes encore",
          {"stems/vocals.mp3": b"ID3v", "stems/drums.mp3": b"ID3d", "lyrics/song.lrc": "[00:01.00]Oh".encode()})
    K._load({"cmd": "karaoke-load", "karaoke": {"id": 1}, "golem": {"id": sid}, "req": "r1"})
    assert not any(p.startswith("/api/ext/karaoke/") for p in kar["reqs"])      # golem.fm n'a plus rien : rien demandé
    fr = _frames()
    ready = [f for f in fr if f.get("state") == "ready"][0]
    assert ready["id"] == 1 and ready["from_golem"] == sid
    lyr = [f for f in fr if f.get("type") == "lyrics"][0]
    assert lyr["karaoke_id"] == 1 and lyr["song_id"] == sid and lyr["text"] == "[00:01.00]Oh"
    K._deactivate()


def test_un_golem_sans_stems_joue_les_stems_de_sa_ligne_en_cache(kar, tmp_path):
    # Black : le .golem n'a que tab et paroles ; les stems sont dans le cache k-4 — ils jouent, les paroles du .golem suivent
    sid = "us:" + "b1" * 16
    _song(tmp_path, sid, "Black", {"scores/song.gp": b"gp", "lyrics/song.lrc": "[00:02.00]Sheets".encode()})
    K.fetch(4, 2)
    n = len(kar["reqs"])
    K._load({"cmd": "karaoke-load", "karaoke": {"id": 4}, "golem": {"id": sid}})
    assert len(kar["reqs"]) == n                                               # rien de plus à golem.fm
    fr = _frames()
    assert [f for f in fr if f.get("state") == "ready"][0]["from_golem"] == "k-4"
    assert [f for f in fr if f.get("type") == "lyrics"][0]["song_id"] == sid
    K._deactivate()


def test_la_copie_absente_ou_sans_stems_est_refusee_avec_sa_raison(kar, tmp_path):
    K._safe(K._load, {"cmd": "karaoke-load", "karaoke": {"id": 9}, "golem": {"id": "us:" + "00" * 16}})
    assert _frames()[-1] == {"type": "karaoke", "state": "refused", "id": 9, "why": K.NOT_HERE}
    sid = "us:" + "d2" * 16
    _song(tmp_path, sid, "Tab only", {"scores/song.gp": b"gp"})
    K._safe(K._load, {"cmd": "karaoke-load", "karaoke": {"id": 9}, "golem": {"id": sid}})
    assert _frames()[-1]["why"] == K.NO_STEMS
    K._safe(K._load, {"cmd": "karaoke-load", "karaoke": {"id": 9}, "golem": {"id": "../etc"}})
    assert _frames()[-1]["why"] == K.NOT_HERE


def test_une_carte_bk_joue_son_entree_du_cache(kar):
    from bridge.inventory import backing_id
    K.fetch(6, 2)
    K._load({"cmd": "karaoke-load", "karaoke": {"id": 6}, "golem": {"id": backing_id("k-6")}})
    assert [f for f in _frames() if f.get("state") == "ready"][0]["from_golem"] == "k-6"
    K._deactivate()


def test_la_trame_pos_d_une_copie_du_rack_porte_le_slug_de_la_ligne(kar, tmp_path):
    # rs:… né sur le rack n'a pas de slug golem.fm : la trame pos disait slug=None et la page coupait la lecture
    sid = "rs:" + "e5" * 16
    _song(tmp_path, sid, "Pour que tu m'aimes encore", {"stems/vocals.mp3": b"ID3v"})
    K._cur.update(active=True, id=1, slug=sid, local=False)
    f = K.pos_fields(sid)
    assert f["src"] == "karaoke" and f["id"] == 1 and f["slug"] == "k-1"
    K._cur.update(slug="k-1")
    assert "slug" not in K.pos_fields("k-1")                      # le cache : le slug est déjà le bon
    K._deactivate()


# ── lot 5 Vocals (plan-vocals-library.md §6 ter) : golem seul, voix exigée, même chanson sans effet, file de soirée ──
def test_une_chanson_du_golem_seul_joue_sans_ligne_golem_fm(kar, tmp_path):
    sid = "us:" + "a7" * 16
    _song(tmp_path, sid, "Karaoke Only", {"stems/vocals.mp3": b"ID3v", "stems/other.mp3": b"ID3o",
                                          "lyrics/song.lrc": "[00:01.00]la".encode()})
    K._load({"cmd": "karaoke-load", "golem": {"id": sid}, "req": "r1"})
    fr = _frames()
    ready = [f for f in fr if f.get("state") == "ready"][0]
    assert ready["id"] == sid and ready["from_golem"] == sid
    assert [f for f in fr if f.get("type") == "lyrics"][0]["song_id"] == sid
    assert not any(p.startswith("/api/ext/karaoke/") for p in kar["reqs"])
    K._deactivate()


def test_sans_voix_separee_pas_de_karaoke(kar, tmp_path):
    sid = "us:" + "b8" * 16
    _song(tmp_path, sid, "Instrumental", {"stems/drums.mp3": b"ID3d", "stems/bass.mp3": b"ID3b"})
    K._safe(K._load, {"cmd": "karaoke-load", "golem": {"id": sid}})
    assert _frames()[-1]["why"] == "no vocal stem"


def test_la_chanson_qui_joue_deja_ne_redemarre_pas(kar, tmp_path):
    sid = "us:" + "c9" * 16
    _song(tmp_path, sid, "Twice", {"stems/vocals.mp3": b"ID3v", "stems/other.mp3": b"ID3o"})
    K._load({"cmd": "karaoke-load", "golem": {"id": sid}})
    n_recalls, n_calls = len(kar["recalls"]), len(kar["ctl"].calls)
    _frames()
    K._load({"cmd": "karaoke-load", "golem": {"id": sid}, "mix": {"vocals": "off"}, "req": "again"})
    assert len(kar["recalls"]) == n_recalls                                   # aucun rappel, aucun load
    assert not any(c[0] == "load" for c in kar["ctl"].calls[n_calls:])
    assert [f for f in _frames() if f.get("req") == "again"][0]["state"] == "ready"
    K._deactivate()


def test_la_file_de_soiree_survit_a_une_coupure(kar, tmp_path, monkeypatch):
    from bridge import follow_uplink as FU
    a, b = "us:" + "d1" * 16, "us:" + "d2" * 16
    _song(tmp_path, a, "First", {"stems/vocals.mp3": b"ID3v"})
    _song(tmp_path, b, "Second", {"stems/vocals.mp3": b"ID3v"})
    K.handle({"cmd": "karaoke-queue", "items": [{"golem": {"id": a}}, {"golem": {"id": b}}, {"bad": 1}], "pos": 0,
              "mix": {"vocals": "guide"}, "req": "q"})
    q = [f for f in _frames() if f.get("req") == "q"][0]
    assert q["state"] == "queue" and q["pos"] == 0 and q["n"] == 2
    K._load({"cmd": "karaoke-load", "golem": {"id": a}})
    _frames()
    monkeypatch.setitem(FU.LINKED, "ok", False)                                # golem.fm absent
    assert K._advance_offline() is True and K._queue["pos"] == 1
    msg = K._cmds.get_nowait()
    assert msg["golem"]["id"] == b and msg["mix"] == {"vocals": "guide"}
    monkeypatch.setitem(FU.LINKED, "ok", True)                                 # connecté : golem.fm enchaîne lui-même
    assert K._advance_offline() is False
    K.on_reconnect()
    assert _frames()[-1] == {"type": "karaoke", "state": "queue", "pos": 1, "n": 2}
    K.handle({"cmd": "karaoke-queue", "items": []})
    assert K._queue["items"] == [] and K._queue["pos"] == -1
    K._deactivate()
