# SPDX-License-Identifier: GPL-3.0-or-later
"""Le reamp (docs/reamp.md). Ce que ces tests gardent : la règle « libre » refuse Gig, prise, chanson
et un rack qu'on vient de toucher ; un job différé n'est JAMAIS acquitté et revient en file ; la lane
se choisit par `preset_lane`, puis par rôle LU, jamais au hasard, et une lane MIDI ou non montée est
refusée en le disant ; la DI se trouve sans extension ; le rendu est coupé à la longueur de la DI ;
la montée suit la reprise servie par golem.fm ; un reamp déjà scellé ne se refait pas."""
import contextlib
import json
import os
import wave

import pytest

from bridge import activity, reamp, tones_jobs
from bridge.state import state


@pytest.fixture
def free(monkeypatch):
    saved = (state.mode, state.perf, state.perf_countin, state.backing, state.arrangement, state.rig_loading)
    state.mode = {"id": "home"}; state.perf = {"recording": False}; state.perf_countin = None
    state.backing = {"playing": False}; state.arrangement = {}; state.rig_loading = None
    monkeypatch.setattr(activity, "idle_s", lambda: 10_000)
    yield
    state.mode, state.perf, state.perf_countin, state.backing, state.arrangement, state.rig_loading = saved


def _wav(path, frames, sr=48000, ch=1):
    with contextlib.closing(wave.open(str(path), "wb")) as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x01\x00" * frames * ch)
    return str(path)


# ── §2 la règle « libre » ────────────────────────────────────────────────────────────────────
def test_libre_quand_rien_ne_joue_et_personne_na_touche(free):
    assert reamp.busy_reason() is None


@pytest.mark.parametrize("setup,why", [
    (lambda: setattr(state, "mode", {"id": "gig"}), "gig"),
    (lambda: setattr(state, "mode", {"id": "home", "ui": {"locked": True}}), "locked"),
    (lambda: setattr(state, "perf", {"recording": True}), "recording"),
    (lambda: setattr(state, "backing", {"playing": True}), "playing"),
    (lambda: setattr(state, "arrangement", {"running": True}), "playing"),
    (lambda: setattr(state, "rig_loading", {"preset": "x"}), "loading"),
])
def test_occupe_jamais_en_gig_ni_pendant_quon_joue(free, setup, why):
    setup()
    assert why in reamp.busy_reason()


def test_un_rack_touche_recemment_nest_pas_libre(free, monkeypatch):
    monkeypatch.setattr(activity, "idle_s", lambda: 30)
    assert reamp.busy_reason().startswith("in use")


def test_le_signal_dune_entree_compte_comme_une_presence():
    activity.touch("boot")
    activity._last["t"] -= 5000
    activity.note_level(activity.SIGNAL / 4)          # souffle : ne compte pas
    assert activity.idle_s() > 4000
    activity.note_level(activity.SIGNAL + 0.05)       # quelqu'un joue
    assert activity.idle_s() < 5 and activity.last()["src"] == "signal"


# ── §3 la file différée ──────────────────────────────────────────────────────────────────────
def test_un_job_differe_nest_pas_acquitte_et_revient_en_tete(monkeypatch):
    acks = []
    monkeypatch.setattr(tones_jobs, "_req", lambda *a, **k: acks.append((a, k)) or (200, {}))

    def busy(_j):
        raise reamp.Deferred("gig mode")
    monkeypatch.setitem(tones_jobs._HANDLERS, "reamp", busy)
    j = {"id": 991, "action": "reamp", "reamp": 7}
    tones_jobs._inflight.add(991)
    reamp._queue.clear()
    tones_jobs._run_job(j)
    assert acks == []                                   # AUCUN ack : golem.fm le garde pending
    assert reamp._queue[0]["id"] == 991                 # en tête de file
    assert 991 in tones_jobs._inflight                  # pas de doublon au prochain tirage
    reamp._queue.clear(); tones_jobs._inflight.discard(991); reamp.finished()


def test_un_echec_de_reamp_est_acquitte_ok_false(monkeypatch):
    acks = []
    monkeypatch.setattr(tones_jobs, "_req", lambda m, p, body=None, **k: acks.append((p, body)) or (200, {}))
    monkeypatch.setitem(tones_jobs._HANDLERS, "reamp", lambda j: (_ for _ in ()).throw(RuntimeError("di not found")))
    tones_jobs._inflight.add(992)
    tones_jobs._run_job({"id": 992, "action": "reamp", "reamp": 8})
    assert acks == [("/api/ext/tones/jobs/992/ack", {"ok": False, "error": "di not found"})]
    assert 992 not in tones_jobs._inflight


def test_le_veilleur_ne_verse_rien_tant_que_le_rack_est_occupe(free, monkeypatch):
    put = []
    monkeypatch.setattr(tones_jobs, "_lane", lambda a: type("Q", (), {"put": lambda self, j: put.append(j)})())
    reamp._queue.clear(); reamp.finished()
    reamp._queue.append({"id": 5, "action": "reamp"})
    state.mode = {"id": "gig"}
    reamp._pump()
    assert put == [] and reamp.status()["waiting_for"] == "gig mode"
    state.mode = {"id": "home"}
    reamp._pump()
    assert [j["id"] for j in put] == [5] and reamp._queue == []
    reamp._queue.append({"id": 6, "action": "reamp"})
    reamp._pump()                                        # un à la fois : 5 n'a pas fini
    assert [j["id"] for j in put] == [5]
    reamp.finished(); reamp._queue.clear()


# ── §4 la lane ───────────────────────────────────────────────────────────────────────────────
LANES = [
    {"id": "guitar-1", "role": "guitar", "in_role": "guitar", "in_nth": 1, "input": 1, "on_card": True},
    {"id": "voice-1", "role": "voice", "in_role": "voice", "in_nth": 1, "input": 2, "on_card": True},
    {"id": "bass-1", "role": "bass", "in_role": "bass", "in_nth": 1, "input": 3, "on_card": False},
    {"id": "keys", "role": "keys", "midi": True, "input": 3, "on_card": True},
]


def test_preset_lane_explicite_gagne():
    assert reamp.pick_lane(LANES, "voice-1", role="guitar")[0]["id"] == "voice-1"
    assert reamp.pick_lane(LANES, "nope")[1] == "lane nope is not in this preset"


def test_regle_lue_meme_role_sinon_premiere_instrumentale():
    assert reamp.pick_lane(LANES, None, role="voice")[0]["id"] == "voice-1"
    assert reamp.pick_lane(LANES, None, role="line")[0]["id"] == "guitar-1"
    assert reamp.pick_lane([], None, role="guitar")[1] == "no instrument lane in this preset"


def test_lane_midi_ou_non_montee_refusee_en_le_disant():
    assert reamp.check_lane(LANES[2]) == "lane bass-1 is not mounted on this card"
    assert "MIDI lane" in reamp.check_lane(LANES[3])
    assert reamp.check_lane(LANES[0]) is None


# ── §4 la DI ─────────────────────────────────────────────────────────────────────────────────
def test_di_trouvee_sans_extension_et_role_lu_sur_la_prise(tmp_path, monkeypatch):
    monkeypatch.setattr(reamp.C, "ROOT", str(tmp_path))
    d = tmp_path / "recordings" / "perf-20260926-211403"
    d.mkdir(parents=True)
    _wav(d / "DI-Sandbox-Input-1.wav", 10)
    json.dump({"roles": {"1": "Guitar", "2": "Voice"}}, open(d / "take.json", "w"))
    assert reamp.local_di("perf-20260926-211403", "DI-Sandbox-Input-1.flac").endswith(".wav")
    assert reamp.local_di("../etc", "passwd") is None
    assert reamp.take_role("perf-20260926-211403", "DI-Sandbox-Input-1.flac") == ("guitar", None)
    assert reamp.take_role("import-xyz", "DI.wav") == (None, None)


# ── §5 la longueur ───────────────────────────────────────────────────────────────────────────
def test_le_rendu_est_coupe_ou_complete_a_la_longueur_exacte_de_la_di(tmp_path):
    long = _wav(tmp_path / "a.wav", 1200, ch=2)
    reamp.fit_length(long, 1000)
    assert reamp.wav_info(long) == (48000, 1000, 2)
    short = _wav(tmp_path / "b.wav", 900, ch=2)
    reamp.fit_length(short, 1000)
    assert reamp.wav_info(short) == (48000, 1000, 2)


# ── §6 la montée ─────────────────────────────────────────────────────────────────────────────
def test_la_montee_reprend_a_loffset_servi_et_scelle(tmp_path, monkeypatch, free):
    from bridge import golemfm
    f = _wav(tmp_path / "DI.reamp37.wav", 50)
    size = os.path.getsize(f)
    calls = []
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", "gmt_x"))

    def req(path, body=None, token=None, **k):
        calls.append(("POST", path, body))
        if path.endswith("/result"):
            return 200, {"reamp": 37, "recording": 1204, "upload": "/api/ext/recordings/1204/tracks/5",
                         "track": {"idx": 5, "received": 10, "done": False}}
        return 200, {"status": "done"}
    monkeypatch.setattr(golemfm, "_req", req)
    monkeypatch.setattr(golemfm, "put_bytes", lambda p, buf, token=None: calls.append(("PUT", p, len(buf))) or (200, {}))
    out = reamp.upload({"reamp": 37, "result": {}}, f)
    assert calls[0][1] == "/api/ext/recordings/reamps/37/result" and calls[0][2]["size_bytes"] == size
    assert calls[1] == ("PUT", "/api/ext/recordings/1204/tracks/5?offset=10", size - 10)
    assert calls[2][1] == "/api/ext/recordings/reamps/37/complete"
    assert out["track"] == 5 and out["recording"] == 1204


def test_quota_plein_est_un_echec_dit(tmp_path, monkeypatch):
    from bridge import golemfm
    f = _wav(tmp_path / "x.wav", 5)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", "gmt_x"))
    monkeypatch.setattr(golemfm, "_req", lambda *a, **k: (413, {"detail": "quota"}))
    with pytest.raises(RuntimeError, match="quota"):
        reamp.upload({"reamp": 1}, f)


def test_un_reamp_deja_scelle_ne_se_refait_pas(monkeypatch):
    monkeypatch.setattr(reamp, "remote_status", lambda rid: "done")
    monkeypatch.setattr(reamp, "render", lambda *a, **k: pytest.fail("ne doit pas rendre"))
    assert reamp.run({"reamp": 37, "preset": "x"})["status"] == "done"


def test_preset_absent_du_rack_est_un_echec_dit(monkeypatch, free):
    monkeypatch.setattr(reamp, "remote_status", lambda rid: "queued")
    from bridge import store
    monkeypatch.setattr(store, "load_preset", lambda pid: None)
    with pytest.raises(RuntimeError, match="preset plexi-lead is not on this rack"):
        reamp.run({"reamp": 3, "preset": "plexi-lead"})
