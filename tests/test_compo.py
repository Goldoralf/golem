# SPDX-License-Identifier: GPL-3.0-or-later
"""Bloc COMPO, lot 1 (docs/compo.md FIGÉ 2026-09-17) : config globale singleton, bloc permanent,
cibles « Follow Golem » en mémoire par personne, auteur et lanes, tap attribué et vérifié."""
import json
from pathlib import Path

import pytest

from bridge import compo, store
from bridge.state import state

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def cfgdir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "COMPO_CFG", str(tmp_path / "compo.json"))
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "recorder.json"))
    monkeypatch.setattr(store, "CLICK_CFG", str(tmp_path / "click.json"))
    state.compo = {"targets": {}, "last": None}
    state.mode = {"id": "rehearsal", "name": "Rehearsal", "services": {"compo": True}}
    state.perf_countin = None
    compo.RIFF.update(active=None, last=None, refused=None)
    monkeypatch.setattr(compo, "_HOOKS", {})                         # les branchements d'app.py ne fuient pas
    monkeypatch.setattr(compo, "_perf_status", lambda: {})         # jamais le vrai .perf.json du rack
    store.save_recorder_cfg({"mode": "tracks_di", "in1": True, "in2": False, "usb": False})
    yield tmp_path
    compo.RIFF.update(active=None, last=None)                      # une capture laissée ouverte fuirait dans
                                                                   # le manifeste d'une prise d'un autre test


IMAP = {"card": "hw:V276",
        "inputs": [{"ch": "1", "role": "guitar", "nth": 1, "person": "alex"},
                   {"ch": "2", "role": "voice", "nth": 1, "person": "alex"},
                   {"ch": "3", "role": "bass", "nth": 1, "person": "ju"}],
        "usb": [{"port": 1, "role": "keys", "nth": 1, "person": "sala", "bound": True}]}

PRESET = {"id": "p", "lanes_v": 2, "lanes": [
    {"id": "guitar-1", "role": "guitar", "in_role": "guitar", "in_nth": 1, "in_sel": "1", "name": "Guitar 1", "chain": {"pre": [], "split": None, "post": []}},
    {"id": "voice-1", "role": "voice", "in_role": "voice", "in_nth": 1, "in_sel": "2", "name": "Voice 1", "chain": {"pre": [], "split": None, "post": []}},
    {"id": "bass-1", "role": "bass", "in_role": "bass", "in_nth": 1, "in_sel": "3", "name": "Bass 1", "chain": {"pre": [], "split": None, "post": []}},
    {"id": "keys-1", "role": "keys", "midi": True, "in_sel": "usb", "name": "Keys", "chain": {"pre": [], "split": None, "post": []}},
]}


def test_config_globale_defauts_validation_et_relecture(cfgdir):
    assert store.load_compo_cfg() == store.COMPO_DEFAULTS
    out = store.save_compo_cfg({"keep_s": 60, "transcribe": False, "foot_person": "alex",
                                "persons": {"alex": {"off": ["voice-1"]}, "x": {"off": []}, "": {"off": ["a"]}}})
    assert out["keep_s"] == 60 and out["transcribe"] is False and out["foot_person"] == "alex"
    assert out["persons"] == {"alex": {"off": ["voice-1"]}}          # les entrées vides disparaissent
    assert store.save_compo_cfg({"keep_s": 45})["keep_s"] == 60          # 45 n'est pas une valeur : gardé 60
    assert json.load(open(cfgdir / "compo.json"))["keep_s"] == 60


def test_bloc_permanent_hydrate_depuis_le_singleton(cfgdir):
    store.save_compo_cfg({"keep_s": 15})
    p = store.migrate_config({"id": "p", "config": {"gen": {"blocks": []}, "rec": {"blocks": []}}})
    kb = [b for b in p["config"]["rec"]["blocks"] if b["type"] == "compo"]
    assert len(kb) == 1 and kb[0]["id"] == "compo-global" and kb[0]["params"]["keep_s"] == 15
    # l'édition dans un preset devient la config globale (extraction au save, comme le Rec)
    kb[0]["params"] = {**kb[0]["params"], "keep_s": 60, "persons": {"ju": {"off": ["bass-1"]}}}
    store.save_recorder_cfg_from(p)
    assert store.load_compo_cfg()["keep_s"] == 60 and store.load_compo_cfg()["persons"] == {"ju": {"off": ["bass-1"]}}
    # un 2e passage ne duplique pas le bloc
    p = store.migrate_config(p)
    assert len([b for b in p["config"]["rec"]["blocks"] if b["type"] == "compo"]) == 1


def test_cibles_follow_golem_par_personne_en_memoire(cfgdir):
    calls = []
    compo.init(on_change=lambda: calls.append(1))
    assert compo.apply_cmd({"type": "cmd", "cmd": "seek"}) is False
    ok = compo.apply_cmd({"type": "cmd", "cmd": "compo-target", "person": "alex",
                          "target": {"id": "bs:42", "mode": "append", "title": "Orbit Decay", "band": "b_1"}})
    assert ok is True and compo.target_of("alex")["id"] == "bs:42" and compo.target_of("alex")["mode"] == "append"
    compo.apply_cmd({"type": "cmd", "cmd": "compo-target", "person": "sala",
                     "target": {"id": "bs:7", "mode": "replace", "title": "Nocturne"}})
    assert set(state.compo["targets"]) == {"alex", "sala"}          # deux personnes armées en même temps
    assert compo.set_target("alex", {"id": "bs:9", "mode": "sideways"}) == (False, "unknown mode: sideways")
    compo.apply_cmd({"type": "cmd", "cmd": "compo-target", "person": "alex", "clear": True})
    assert "alex" not in state.compo["targets"] and compo.target_of("sala")["title"] == "Nocturne"
    assert calls                                                     # chaque changement a été diffusé


def test_auteur_du_pedalier_et_lanes_par_personne(cfgdir):
    cfg = store.load_compo_cfg()
    assert compo.foot_person(cfg, IMAP) == "alex"                    # 1re entrée qui porte une personne
    assert compo.foot_person({**cfg, "foot_person": "ju"}, IMAP) == "ju"
    assert [l["id"] for l in compo.lanes_of_person(PRESET, "alex", cfg, IMAP)] == ["guitar-1", "voice-1"]
    assert [l["id"] for l in compo.lanes_of_person(PRESET, "ju", cfg, IMAP)] == ["bass-1"]
    assert [l["id"] for l in compo.lanes_of_person(PRESET, "sala", cfg, IMAP)] == ["keys-1"]   # lane MIDI -> port USB
    assert compo.lanes_of_person(PRESET, "nobody", cfg, IMAP) == []
    cfg = store.save_compo_cfg({"persons": {"alex": {"off": ["voice-1"]}}})
    assert [(l["id"], l["on"]) for l in compo.lanes_of_person(PRESET, "alex", cfg, IMAP)] == [("guitar-1", True), ("voice-1", False)]


def test_tap_attribue_verifie_et_dit(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    store.save_compo_cfg({"persons": {"alex": {"off": ["voice-1"]}}})
    compo.set_target("alex", {"id": "bs:42", "mode": "append", "title": "Orbit Decay"})
    rep = compo.tap(source="companion", person="nobody", preset=PRESET)
    assert rep["refused"].startswith("nobody has no lane")
    rep = compo.tap(source="foot", preset=PRESET)
    assert rep["person"] == "alex" and rep["lanes"] == ["guitar-1"] and rep["target"]["id"] == "bs:42"
    assert rep["capture"] == "start" and state.compo["last"] is rep
    compo.RIFF.update(active=None)
    state.mode = {"id": "gig", "name": "Gig", "services": {"compo": False}}
    assert compo.tap(source="foot", preset=PRESET)["refused"] == "off in Gig"


# ── LOT A : la capture (docs/compo.md §11) ─────────────────────────────────────────────────────
def test_un_tap_demarre_un_tap_arrete_par_le_chemin_du_rec(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    calls = []
    toggle = calls.append
    assert compo.tap(preset=PRESET, toggle=toggle)["capture"] == "start" and calls == [True]
    assert state.compo["riff"] == {"state": "counting", "person": "alex"}
    compo.on_perf_start()                                          # le perf-rec a vraiment démarré
    assert state.compo["riff"]["state"] == "rec"
    assert compo.tap(source="companion", person="ju", preset=PRESET, toggle=toggle)["refused"].startswith("alex is recording")
    assert compo.tap(preset=PRESET, toggle=toggle)["capture"] == "stop" and calls == [True, False]
    riff = compo.claim_riff()
    assert riff["person"] == "alex" and [l["input"] for l in riff["lanes"]] == ["1", "2"]
    assert compo.claim_riff() is None                             # pris une fois


def test_arreter_pendant_le_decompte_annule(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    calls = []
    compo.tap(preset=PRESET, toggle=calls.append)
    assert compo.tap(preset=PRESET, toggle=calls.append)["capture"] == "cancelled"
    assert calls == [True, False] and compo.RIFF["active"] is None and compo.claim_riff() is None


def test_les_refus_de_lenregistreur_se_disent(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    store.save_recorder_cfg({"mode": "mix"})
    assert "Mix" in compo.tap(preset=PRESET)["refused"]
    # cases IN éteintes : le riff part quand même, sa prise enregistre les entrées de SES lanes (2026-11-02)
    store.save_recorder_cfg({"mode": "tracks", "in1": False, "in2": False})
    assert not compo.tap(preset=PRESET).get("refused")
    assert set(compo.riff_inputs()) <= {"1", "2"} and compo.riff_inputs()
    compo.RIFF.update(active=None)
    store.save_recorder_cfg({"mode": "tracks", "in1": True})
    monkeypatch.setattr(compo, "_perf_status", lambda: {"recording": True})
    assert "already recording" in compo.tap(preset=PRESET)["refused"]
    assert compo.RIFF["active"] is None


def test_le_manifeste_declare_le_riff_et_ses_lanes(cfgdir, monkeypatch):
    from bridge import takes
    monkeypatch.setattr(takes, "resolve_band", lambda b: {"id": b, "name": "Night Shift"} if b == "b_known" else None)
    riff = {"person": "alex", "target": {"id": "rf:17", "mode": "replace", "title": "Orbit", "band": "b_known"},
            "lanes": [{"id": "guitar-1", "name": "Guitar 1", "role": "guitar", "input": "1"},
                      {"id": "voice-1", "name": "Voice 1", "role": "voice", "input": "2"}]}
    man = {"kind": "rehearsal", "band": {"id": "b_other"},
           "files": ["DI-Sandbox-Input-1.wav", "Input-1merge.wav", "Input-3merge.wav", "Mix.wav"]}
    compo.stamp_manifest(man, riff)
    assert man["kind"] == "riff" and man["by"] == "alex" and man["drop_window_s"] == 20
    assert man["target"] == {"id": "rf:17", "mode": "replace", "title": "Orbit", "band": "b_known"}
    assert man["band"]["id"] == "b_known"                           # le groupe de la cible, connu ici
    assert man["lanes"] == [{"id": "guitar-1", "name": "Guitar 1", "role": "guitar", "input": "1",
                             "files": {"di": "DI-Sandbox-Input-1.wav", "wet": "Input-1merge.wav"}}]   # la voix n'a rien enregistré
    assert man["upload"]["state"] == "held"
    man2 = {"files": []}
    compo.stamp_manifest(man2, dict(riff, target={"id": "rf:1", "mode": "append", "band": "b_elsewhere"}))
    assert "target" not in man2 and man2["target_dropped"] == "unknown band"


def test_une_lane_midi_declare_son_midi_et_le_son_de_son_instrument(cfgdir):
    """Riff d'orgue (rf:41, 2026-11-02) : la prise n'avait que le MIDI. Le son du patch (post-plugin et FX) est
    sur la piste de la lane, « Input-3.wav » : c'est son `wet` ; pas de `di` pour du MIDI."""
    riff = {"person": "alex", "lanes": [{"id": "keys-1", "name": "Rock Organ", "role": "keys", "input": "usb", "track": "3"},
                                        {"id": "drums-1", "name": "Drums", "role": "drums", "input": "usb", "track": "4"}]}
    man = {"files": ["DI-Sandbox-Input-1.wav", "Input-1.wav", "Input-3.wav", "MIDI-Input-3.mid", "MIDI-Input-4.mid", "Mix.wav"]}
    compo.stamp_manifest(man, riff)
    assert [l["files"] for l in man["lanes"]] == [{"midi": "MIDI-Input-3.mid", "wet": "Input-3.wav"},
                                                  {"midi": "MIDI-Input-4.mid"}]


def test_un_riff_ne_monte_que_ses_fichiers_et_attend_sa_fenetre(tmp_path, monkeypatch):
    import time
    from bridge import takes, uploader
    rec = tmp_path / "recordings"; d = rec / "perf-20260930-120000"; d.mkdir(parents=True)
    for f in ("DI-Sandbox-Input-1.wav", "Input-1merge.wav", "Input-3merge.wav", "Mix.wav"):
        (d / f).write_bytes(b"RIFF")
    man = {"kind": "riff", "band": {"id": "b1"}, "upload": {"state": "held", "until": time.time() + 20},
           "lanes": [{"id": "guitar-1", "files": {"di": "DI-Sandbox-Input-1.wav", "wet": "Input-1merge.wav", "score": "scores/x.musicxml"}}]}
    json.dump(man, open(d / "take.json", "w"))
    monkeypatch.setattr(takes, "RECORDINGS", str(rec))
    monkeypatch.setattr(uploader, "CACHE", str(rec / ".upload"))
    import os

    def fake_flac(src, dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "wb").write(b"fLaC")
        return True
    monkeypatch.setattr(uploader, "to_flac", fake_flac)
    (d / "scores").mkdir()
    (d / "scores" / "x.musicxml").write_text("<score/>")
    tracks = uploader.prepare(d.name)
    names = sorted(t["orig"] if "orig" in t else t["filename"] for t in tracks if t["kind"] != "meta")
    assert names == ["DI-Sandbox-Input-1.wav", "Input-1merge.wav", "scores/x.musicxml"]   # ni le Mix, ni l'entrée 3
    assert {t["filename"]: t["kind"] for t in tracks}["x.musicxml"] == "score"
    # golem.fm apparie AU NOM EXACT : la copie qui monte nomme chaque fichier comme sa piste
    photo = json.load(open(next(t["path"] for t in tracks if t["kind"] == "meta")))
    assert photo["lanes"][0]["files"] == {"di": "DI-Sandbox-Input-1.flac", "wet": "Input-1merge.flac", "score": "x.musicxml"}
    assert set(photo["lanes"][0]["files"].values()) <= {t["filename"] for t in tracks}
    uid = takes.uid_of(d.name)
    assert uid not in uploader.due()                                         # dans sa fenêtre de drop
    man["upload"] = {"state": "held", "until": time.time() - 1}
    json.dump(man, open(d / "take.json", "w"))
    assert uid in uploader.due()
    man["upload"] = {"state": "dropped"}
    json.dump(man, open(d / "take.json", "w"))
    assert uid not in uploader.due()                                         # jeté = jamais monté


def test_drop_pendant_la_fenetre_seulement(tmp_path, monkeypatch, cfgdir):
    import time
    from bridge import takes
    rec = tmp_path / "recordings"; d = rec / "perf-20260930-130000"; d.mkdir(parents=True)
    json.dump({"kind": "riff", "upload": {"state": "held"}}, open(d / "take.json", "w"))
    monkeypatch.setattr(takes, "RECORDINGS", str(rec))
    compo.RIFF["last"] = {"state": "held", "person": "alex", "uid": takes.uid_of(d.name), "name": d.name, "until": time.time() + 20}
    assert compo.drop() == (True, None)
    assert json.load(open(d / "take.json"))["upload"]["state"] == "dropped"
    compo.RIFF["last"] = {"state": "held", "person": "alex", "uid": "x", "name": d.name, "until": time.time() - 1}
    assert compo.drop()[1].startswith("too late")


def test_le_pied_ne_plante_plus(monkeypatch):
    """`_compo_tap` passait `preset=cur`, une variable qui n'existait pas : NameError à chaque appui."""
    import ast
    src = (ROOT / "bridge/app.py").read_text(encoding="utf8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_compo_tap")
    assigned = {t.id for n in ast.walk(fn) for t in getattr(n, "targets", []) if isinstance(t, ast.Name)}
    assert "cur" in assigned


# ── LOT B : la prise armée (docs/compo.md §12) ─────────────────────────────────────────────────
TAKE = {"bpm": 120, "sig": {"num": 4, "den": 4}, "count_in": 2, "bars": 4, "passes": 2}


def test_larmement_porte_la_prise_et_se_valide(cfgdir):
    ok, _ = compo.set_target("alex", {"id": "rf:17", "mode": "append", **TAKE})
    t = compo.target_of("alex")["take"]
    assert ok and t == {**TAKE, "click": "always"}
    assert compo.set_target("alex", {"id": "rf:17", "bpm": 900, "bars": 4}) == (False, "bad take: bpm out of 20-400")
    assert compo.set_target("alex", {"id": "rf:17", "bpm": 120, "bars": 4, "sig": {"num": 4, "den": 3}})[1] == "bad take: sig"
    assert "take" not in (compo.set_target("alex", {"id": "rf:17"}) and compo.target_of("alex"))   # sans bpm+bars : capture libre


def test_le_click_de_la_prise_est_un_fichier_au_temps_exact(tmp_path):
    from bridge import riffclick
    beat, bar, down, total = riffclick.timing(TAKE)
    assert (beat, bar, down, total) == (0.5, 2.0, 4.0, 4.0 + 4 * 2 * 2.0)
    six8 = {**TAKE, "sig": {"num": 6, "den": 8}, "count_in": 1}
    assert riffclick.timing(six8)[2] == 1.5                     # une mesure de 6/8 à 120 à la noire
    dur = riffclick.render(dict(TAKE, bars=1, passes=1), str(tmp_path / "c.wav"))
    import wave
    w = wave.open(str(tmp_path / "c.wav"))
    assert w.getframerate() == 48000 and abs(w.getnframes() / 48000 - dur) < 1e-6 and dur == 4.0 + 2.0 + 2.0


def test_un_tap_arme_part_par_le_backing_et_sarrete_seul(cfgdir, monkeypatch):
    import time
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    started, restored, toggles = [], [], []
    compo.bind(armed_start=lambda path, alive: (started.append((path, alive())), (True, None))[1],
               restore=lambda: restored.append(1))
    compo.set_target("alex", {"id": "rf:17", "mode": "append", **dict(TAKE, count_in=0, bars=1, passes=1, bpm=400)})
    rep = compo.tap(preset=PRESET, toggle=toggles.append)
    assert rep["capture"] == "start-armed" and toggles == []            # pas le chemin du Rec : le backing
    for _ in range(50):
        if started and not compo.RIFF["active"].get("loading"):
            break
        time.sleep(0.02)
    assert started and started[0][0].endswith(".riff-click.wav") and started[0][1] is True
    compo.on_perf_start()
    time.sleep(0.9)                                                      # 1 mesure à 400 = 0,6 s + un temps
    assert toggles == [False]                                            # arrêtée seule, à la longueur
    riff = compo.claim_riff()
    assert riff["armed"] and restored == [1]                             # le backing du preset reprend sa place
    man = {"files": ["DI-Sandbox-Input-1.wav"]}
    compo.stamp_manifest(man, riff)
    assert man["downbeat_s"] == 0.0 and man["bars"] == 1 and man["sig"] == {"num": 4, "den": 4} and man["bpm"] == 400


def test_la_prise_armee_refuse_un_transport_qui_roule(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    monkeypatch.setattr(state, "backing", {"playing": True}, raising=False)
    compo.set_target("alex", {"id": "rf:17", **TAKE})
    assert compo.tap(preset=PRESET)["refused"] == "the backing is playing — stop it first"


def test_le_compte_des_frames_pos_suit_le_fichier(cfgdir, monkeypatch):
    compo.RIFF["active"] = {"person": "alex", "rolling": True, "take": dict(TAKE), "t_rolling": 0}
    monkeypatch.setattr(state, "backing", {"pos": 1.2}, raising=False)
    assert compo.riff_frame() == {"person": "alex", "state": "count", "beat": 3, "beats": 8, "count_in": 6}
    monkeypatch.setattr(state, "backing", {"pos": 4.0 + 2.0 * 5 + 0.1}, raising=False)   # 6e mesure = passe 2
    assert compo.riff_frame() == {"person": "alex", "state": "rec", "bar": 6, "bars": 8, "beat": 1, "beats": 4,
                                  "pass": 2, "passes": 2}
    monkeypatch.setattr(state, "backing", {"pos": 4.0 + 2.0 * 5 + 1.6}, raising=False)   # 4e temps de la mesure
    assert compo.riff_frame()["beat"] == 4



# ── LOT D : le départ depuis golem.fm (docs/compo.md §13) ──────────────────────────────────────
def test_le_depart_a_distance_suit_les_garde_fous(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    taps = []

    def tap(source, person):
        taps.append((source, person))
        return compo.tap(source=source, person=person, preset=PRESET, toggle=lambda want: None)
    compo.bind(tap=tap)
    assert compo.apply_cmd({"type": "cmd", "cmd": "compo-start", "person": "alex"}) is True
    assert compo.riff_frame() == {"person": "alex", "state": "refused", "why": "arm the rack on a riff first"}
    compo.set_target("alex", {"id": "rf:12", "mode": "append"})
    state.mode = {"id": "gig", "name": "Gig", "ui": {"locked": True}, "services": {"compo": True}}
    assert compo.remote("compo-start", "alex")[1].startswith("the rack is in Gig mode")
    state.mode = {"id": "rehearsal", "name": "Rehearsal", "services": {"compo": True}}
    assert compo.remote("compo-start", "alex") == (True, None) and taps == [("golem.fm", "alex")]
    assert compo.remote("compo-start", "alex")[1] == "a take is already recording"   # jamais un 2e départ
    assert compo.remote("compo-stop", "ju")[1].startswith("alex is recording")
    assert compo.remote("compo-stop", "alex") == (True, None)                          # arrêté pendant le décompte
    assert compo.RIFF["active"] is None and compo.remote("compo-stop", "alex")[1] == "nothing is recording"


def test_test_reel_du_30_09_le_backing_se_lit_et_lechec_se_dit(cfgdir, monkeypatch):
    """Test réel (20:34:37) : preset SANS backing -> le moniteur ne lisait pas .backing.json, le click
    chargé dans Reaper n'était jamais vu, et l'échec (8 s) n'arrivait pas à la page."""
    import time
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    compo.set_target("alex", {"id": "rf:12", **TAKE})
    compo.bind(armed_start=lambda path, alive: (False, "the backing track did not load the click in time"))
    compo.tap(preset=PRESET)
    assert compo.backing_needed() or compo.RIFF["active"] is None           # lu PENDANT la prise armée
    for _ in range(50):
        if compo.RIFF["active"] is None:
            break
        time.sleep(0.02)
    assert compo.riff_frame() == {"person": "alex", "state": "refused", "target_id": "rf:12",
                                  "why": "the backing track did not load the click in time"}
    assert not compo.backing_needed()


def test_un_mode_sans_backing_refuse_au_depart(cfgdir, monkeypatch):
    monkeypatch.setattr(compo, "_imap", lambda: IMAP)
    state.mode = {"id": "pedalboard", "name": "Pedalboard", "services": {"compo": True, "backing": False}}
    compo.set_target("alex", {"id": "rf:12", **TAKE})
    rep = compo.tap(preset=PRESET)
    assert rep["refused"].startswith("the backing track is off in Pedalboard")
    assert compo.riff_frame()["state"] == "refused"                            # au pied aussi, la page le voit


def test_le_moniteur_lit_le_backing_pendant_une_prise_armee():
    src = (ROOT / "bridge/monitors.py").read_text(encoding="utf8")
    body = src[src.index("async def _poll_backing"):src.index("data = await loop.run_in_executor(None, _read_backing_file)")]
    assert "backing_needed()" in body and 'not state.backing.get("enabled") and not riff_needs' in body


# ── EN BOUCLE (docs/compo.md §12 bis) ──────────────────────────────────────────────────────────
def test_en_boucle_jusquau_stop(cfgdir, monkeypatch, tmp_path):
    from bridge import riffclick
    loop = dict(TAKE, passes=0)
    ok, _ = compo.set_target("alex", {"id": "rf:12", **loop})
    assert ok and compo.target_of("alex")["take"]["passes"] == 0
    assert compo.set_target("alex", {"id": "rf:12", **dict(TAKE, passes=17)})[1].startswith("bad take")
    beat, bar, down, total = riffclick.timing(loop)
    assert total == riffclick.LOOP_MAX_S                                      # plafond : s'arrête seule à 10 min
    dur = riffclick.render(loop, str(tmp_path / "loop.wav"))
    assert abs(dur - (riffclick.LOOP_MAX_S + bar)) < 1e-3                      # rendu d'un coup, sans dérive
    compo.RIFF["active"] = {"person": "alex", "rolling": True, "take": loop, "t_rolling": 0}
    monkeypatch.setattr(state, "backing", {"pos": down + 2.0 * 9 + 0.6}, raising=False)   # 10e mesure = boucle 3, mesure 2
    assert compo.riff_frame() == {"person": "alex", "state": "rec", "bar": 2, "bars": 4, "beat": 2, "beats": 4,
                                  "pass": 3, "passes": 0}
    riff = {"person": "alex", "armed": True, "take": loop, "lanes": [], "t_rolling": 100.0, "t_stop": 100.0 + down + 2.0 * 9 + 0.6}
    man = {"files": []}
    compo.stamp_manifest(man, riff)
    assert man["passes"] == 0 and man["loops"] == 3 and man["downbeat_s"] == 4.0


def test_le_riff_dit_avec_quoi_il_a_ete_joue_et_ne_prend_pas_le_nom_du_preset(cfgdir):
    riff = {"person": "alex", "lanes": []}
    man = {"files": [], "preset": "night-shift", "preset_name": "Night Shift", "bpm": 120, "started_at": "2026-09-30T19:08:14"}
    compo.stamp_manifest(man, riff)
    assert man["rig"] == {"kind": "preset", "id": "night-shift", "name": "Night Shift"}
    assert man["title"] == "Riff 2026-09-30 19:08" and man["tempo_source"] == "preset"
    man = {"files": [], "preset": "patch:1983", "preset_name": "⛓ 1983"}
    compo.stamp_manifest(man, dict(riff, target={"id": "rf:12", "mode": "append"}))
    assert man["rig"] == {"kind": "patch", "id": "1983", "name": "1983"} and "title" not in man   # il entre dans rf:12
    man = {"files": [], "preset": "night-shift"}
    compo.stamp_manifest(man, dict(riff, armed=True, take=dict(TAKE)))
    assert man["tempo_source"] == "riff" and man["bpm"] == 120


def test_le_click_des_riffs_suit_le_level_du_bloc_click(tmp_path):
    """« On ne l'entend pas assez » (2026-09-30) : le click d'un riff avait ses amplitudes figées.
    Il suit désormais le Level du bloc Click, avec la loi de golem_click.jsfx (accent ×1, autres −3 dB)."""
    import struct, wave
    from bridge import riffclick
    g = riffclick.gains(-12)
    assert abs(g[(False, True)] - 10 ** (-12 / 20)) < 1e-9 and abs(g[(False, False)] / g[(False, True)] - 0.708) < 1e-9
    assert g[(True, True)] > g[(False, True)]                          # le décompte au-dessus
    assert riffclick.gains(6)[(True, True)] == 0.95                    # plafonné, jamais saturé

    def peak(level):
        p = str(tmp_path / f"c{level}.wav")
        riffclick.render({"bpm": 120, "sig": {"num": 4, "den": 4}, "count_in": 0, "bars": 1, "passes": 1}, p, level_db=level)
        w = wave.open(p); raw = w.readframes(w.getnframes())
        return max(abs(v) for (v,) in struct.iter_unpack("<h", raw))
    assert peak(0) > 3.5 * peak(-12)                                   # +12 dB ≈ ×4


def test_le_volume_du_click_se_regle_seul_et_borne(cfgdir):
    """« Je n'ai aucun réglage de level dans le bloc Click » (2026-09-30) : le niveau existait sans écran."""
    json.dump({"level": -12.0, "beats": 7, "den": 8}, open(store.CLICK_CFG, "w"))
    assert store.save_click_level(-4)["level"] == -4.0
    assert store.load_click_cfg()["beats"] == 7                     # la mesure n'est pas touchée
    assert store.save_click_level(20)["level"] == 6.0                # bornes du JSFX
    assert store.save_click_level(-99)["level"] == -60.0


def test_un_espace_plein_a_l_armement_bloque_le_riff(cfgdir):
    """golem.fm (2026-10-14) joint à l'armement la place de l'espace (`space`, octets) et `blocked: "quota"` sous 64 Mio :
    le rack garde la cible ET la raison (/live dit « storage full ») — et le tap au pied est refusé, rien ne partirait."""
    compo.init(on_change=lambda: None)
    compo.apply_cmd({"type": "cmd", "cmd": "compo-target", "person": "alex",
                     "target": {"id": "bs:42", "mode": "append", "title": "Orbit Decay",
                                "space": {"free_bytes": 1024, "quota_bytes": 1 << 30}, "blocked": "quota"}})
    t = compo.target_of("alex")
    assert t["blocked"] == "quota" and t["space"] == {"free_bytes": 1024, "quota_bytes": 1 << 30}
    compo.apply_cmd({"type": "cmd", "cmd": "compo-target", "person": "alex",
                     "target": {"id": "bs:42", "mode": "append", "space": {"free_bytes": 10 << 30, "quota_bytes": 100 << 30}}})
    assert "blocked" not in compo.target_of("alex")                  # ré-armé avec de la place : plus bloqué


def test_les_frames_compo_portent_l_id_de_la_cible_armee(cfgdir, monkeypatch):
    # deux pages peuvent armer la même personne (une section depuis le player) : l'id dit laquelle tourne
    ID = "rf:318|ly:4|b:5-8"
    compo.set_target("alex", {"id": ID, **TAKE})
    compo.RIFF["active"] = {"person": "alex", "loading": True, "take": dict(TAKE), "target": compo.target_of("alex")}
    assert compo.riff_frame() == {"person": "alex", "state": "loading", "target_id": ID}
    compo.RIFF["active"] = {"person": "alex", "rolling": True, "take": dict(TAKE), "t_rolling": 0,
                            "target": compo.target_of("alex")}
    monkeypatch.setattr(state, "backing", {"pos": 1.2}, raising=False)
    assert compo.riff_frame()["target_id"] == ID
    compo.RIFF["active"] = None
    compo.RIFF["last"] = {"state": "sending", "person": "alex", "target_id": ID}
    assert compo.riff_frame() == {"state": "arriving", "person": "alex", "target_id": ID}
    compo.RIFF["last"] = None
    compo._refuse("alex", "nope")
    assert compo.riff_frame() == {"person": "alex", "state": "refused", "why": "nope", "target_id": ID}
    compo.RIFF["refused"] = None
    compo.set_target("alex", clear=True)
    compo.RIFF["active"] = {"person": "alex", "loading": True}                 # capture libre : pas de clé
    assert compo.riff_frame() == {"person": "alex", "state": "loading"}
