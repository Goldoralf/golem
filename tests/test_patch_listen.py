# SPDX-License-Identifier: GPL-3.0-or-later
"""L'écoute d'un PATCH sur la page Patches (2026-11-03) : `patch:<id>` se rend comme un preset (le chemin de tout
rappel), mais sa démo s'écrit À CÔTÉ de ses clips (library/previews/patch-<id>/preview.json) — jamais dans le
fichier du patch ni dans presets/ — et GET /api/patches la relit. Sans REAPER : rendu, attente et encodage sont
des faux."""
import json
import os

import pytest

from bridge import config as C, preview as PV, store


@pytest.fixture
def pv(tmp_path, monkeypatch):
    presets, previews = tmp_path / "presets", tmp_path / "previews"
    presets.mkdir(); previews.mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(presets))
    monkeypatch.setattr(C, "PREVIEWS_DIR", str(previews))
    monkeypatch.setattr(C, "rel", lambda p: os.path.relpath(p, str(tmp_path)))
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    patch = {"id": "patch:jazz", "name": "Jazz", "lanes": [{"id": "g", "role": "guitar", "in_sel": "2"}],
             "scenes": [{"id": "A"}, {"id": "B"}]}
    monkeypatch.setattr(store, "load_preset", lambda pid: dict(patch) if pid == "patch:jazz" else None)
    monkeypatch.setattr(PV, "resolve_di", lambda *a, **k: ("guitar/clean", "/di/clean.wav"))
    monkeypatch.setattr(PV, "input_role", lambda k: "guitar")
    monkeypatch.setattr(PV, "_apply_scene", lambda pid, sc: None)
    monkeypatch.setattr(PV, "_restore_live", lambda: None)
    sent = []
    monkeypatch.setattr(PV, "write_command", lambda cmd: sent.append(cmd))

    def _poll(seq, sc, timeout):
        w = tmp_path / f"{sc}.wav"; w.write_bytes(b"RIFF"); return str(w)
    monkeypatch.setattr(PV, "_poll_scene", _poll)

    def _enc(wav, opus, start=0.0):
        open(opus, "wb").write(b"OggS"); return True
    monkeypatch.setattr(PV, "_encode_opus", _enc)
    from bridge import preset_export
    monkeypatch.setattr(preset_export, "fingerprint", lambda p: "fp1")
    monkeypatch.setattr(PV.time, "sleep", lambda s: None)          # les délais du rig, sans rig
    monkeypatch.setattr(PV, "_peak_db", lambda wav: -12.0)         # un rendu qui sonne
    return tmp_path, sent


def test_la_demo_d_un_patch_s_ecrit_a_cote_de_ses_clips(pv):
    tmp, sent = pv
    PV.generate("patch:jazz", 1, in_key="2")
    assert PV.status()["phase"] == "done", PV.status().get("error")
    # toute la lane est rendue (`tree`), sur l'entrée où le patch se joue
    assert [c["scene"] for c in sent] == ["A", "B"] and all(c["tree"] for c in sent)
    assert all(c["chain"] == "Sandbox #Input 2" for c in sent)
    side = tmp / "previews" / "patch-jazz-in2" / "preview.json"
    e = json.loads(side.read_text())
    assert set(e["scenes"]) == {"A", "B"} and e["ref"] == "guitar/clean" and e["input"] == "2"
    assert not os.listdir(tmp / "presets")                 # rien dans presets/ : un patch n'y a pas de fichier
    assert PV.patch_preview("jazz")["scenes"] == e["scenes"]


def test_la_plus_recente_des_demos_gagne(pv):
    tmp, _ = pv
    for d, when in (("patch-jazz", "2026-11-01T10:00:00Z"), ("patch-jazz-in2", "2026-11-03T10:00:00Z")):
        os.makedirs(tmp / "previews" / d)
        (tmp / "previews" / d / "preview.json").write_text(json.dumps({"generated": when, "scenes": {"A": d}}))
    assert PV.patch_preview("jazz")["scenes"] == {"A": "patch-jazz-in2"}
    assert PV.patch_preview("other") is None


def test_l_entree_du_patch_vient_de_sa_liaison(monkeypatch):
    monkeypatch.setattr(store, "load_preset", lambda pid: {"lanes": [{"in_sel": "2"}]})
    assert PV.patch_input("x") == "2"
    monkeypatch.setattr(store, "load_preset", lambda pid: {"lanes": [{"bind_error": "no bass input"}]})
    assert PV.patch_input("x") is None
    monkeypatch.setattr(store, "load_preset", lambda pid: {"lanes": [{"midi": True}]})
    assert PV.patch_input("x") == "k"


def test_la_di_se_choisit_par_les_tags_avant_le_style():
    # Jazz Clean partait en high-gain sur un style « metal » resté dans un brouillon : les tags décident
    assert PV.resolve_di({"tags": ["jazz", "clean"], "style": "metal"}, None)[0] == "guitar/clean"
    assert PV._bucket_from_tags("guitar", ["metal", "progressive", "ambient", "djent"]) == "guitar/djent"
    assert PV._bucket_from_tags("guitar", ["indie", "pop", "clean", "crunch"]) == "guitar/clean"
    assert PV._bucket_from_tags("guitar", ["blues", "crunch"]) == "guitar/crunch"
    assert PV._bucket_from_tags("bass", ["pop", "soul", "rock"]) == "bass/finger"
    assert PV._bucket_from_tags("guitar", ["ambient"]) is None        # rien de parlant : le style décide


def test_claviers_et_batterie_choisissent_leur_reference_midi():
    import glob
    import json as _j
    want = {"factory-keys-80s-epiano": "keys/epiano", "factory-keys-cathedral-piano": "keys/piano",
            "factory-keys-electric-piano": "keys/epiano", "factory-keys-jazz-piano": "keys/piano",
            "factory-keys-rock-organ": "keys/organ", "factory-keys-synth-lead": "keys/lead",
            "factory-keys-warm-pad": "keys/pad", "factory-drums-classic-rock": "drums/rock",
            "factory-drums-jazz-brushes": "drums/jazz", "factory-drums-metal": "drums/metal",
            "factory-drums-studio-rock": "drums/rock"}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in glob.glob(os.path.join(root, "library", "factory", "patches", "factory-*.json")):
        d = _j.load(open(path))
        if d["id"] in want:
            role = "drums" if d["role"] == "drums" else "keys"
            assert PV._bucket_from_tags(role, d.get("tags")) == want.pop(d["id"]), d["id"]
    assert not want                                  # chaque patch attendu existe encore


def test_les_references_midi_sont_valides_et_reproductibles():
    # le générateur est la partition : même sortie à chaque fois, chaque note fermée, la fin pile sur la barre
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("mkrefs", os.path.join(root, "tools", "make-midi-refs.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    for key, (fn, _name, _shows) in m.REFS.items():
        a, b = fn(), fn()
        assert a == b and a[:4] == b"MThd" and a.endswith(b"\xff\x2f\x00"), key
        ons = sum(1 for i in range(len(a) - 2) if a[i] & 0xF0 == 0x90 and a[i + 2] > 0 and a[i + 1] < 128)
        assert ons > 10, key


def test_un_clip_muet_reapplique_la_scene_et_se_rend_une_seconde_fois(pv, monkeypatch):
    # vu au rig : juste après un redémarrage du bridge, la lane n'était pas construite (racine muette, 0 FX)
    tmp, sent = pv
    applied = []
    monkeypatch.setattr(PV, "_apply_scene", lambda pid, sc: applied.append(sc))
    peaks = iter([-240.0, -10.0, -10.0])
    monkeypatch.setattr(PV, "_peak_db", lambda wav: next(peaks))
    PV.generate("patch:jazz", 1, in_key="2")
    assert PV.status()["phase"] == "done", PV.status().get("error")
    assert applied == ["A", "A", "B"]                          # A réappliquée avant son second rendu
    assert [c["scene"] for c in sent] == ["A", "A", "B"]
    assert sent[1]["settle"] == 2 * sent[0]["settle"]          # le second rendu attend deux fois plus


def test_une_reference_midi_se_joue_par_l_instrument_de_la_lane(pv, monkeypatch, tmp_path):
    tmp, sent = pv
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import importlib.util
    spec = importlib.util.spec_from_file_location("mkrefs", os.path.join(root, "tools", "make-midi-refs.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    mid = tmp_path / "epiano.mid"
    mid.write_bytes(m.e_piano())
    keys = {"id": "patch:ep", "lanes": [{"id": "k", "role": "keys", "midi": True, "input": 3}], "scenes": [{"id": "A"}],
            "tags": ["rhodes"]}
    monkeypatch.setattr(store, "load_preset", lambda pid: dict(keys) if pid == "patch:ep" else None)
    monkeypatch.setattr(PV, "resolve_di", lambda *a, **k: ("keys/epiano", str(mid)))
    monkeypatch.setattr(PV, "_di_index", lambda: {"keys/epiano": {"file": "keys/epiano.mid", "kind": "midi"}})
    from bridge import store as S
    monkeypatch.setattr(S, "lanes_of", lambda p, imap=None: p["lanes"])
    seen = {}

    def _send(cmd):
        sent.append(cmd)
        seen["events"] = open(cmd["midi"]).read()               # lu AVANT que le rendu l'efface
    monkeypatch.setattr(PV, "write_command", _send)
    starts = []
    monkeypatch.setattr(PV, "_encode_opus", lambda wav, opus, start=0.0: (starts.append(start), open(opus, "wb").write(b"x"))[1] > 0)
    PV.generate("patch:ep", 1, in_key="k")
    assert PV.status()["phase"] == "done", PV.status().get("error")
    c = sent[-1]
    assert c["chain"] == "Sandbox #Input 3" and c["settle"] == PV.MIDI_CLONE_SETTLE_S
    first = next(ln for ln in seen["events"].splitlines() if ln.startswith("n "))
    assert seen["events"].startswith("len ") and float(first.split()[1]) == PV.MIDI_LEAD_IN
    assert starts == [PV.MIDI_LEAD_IN - PV.MIDI_KEEP_S]        # l'encodage retire l'avance
    assert not os.path.exists(c["midi"])                       # le fichier d'événements ne traîne pas


def test_les_evenements_midi_sont_dates_en_secondes(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    import importlib.util
    spec = importlib.util.spec_from_file_location("mkrefs", os.path.join(root, "tools", "make-midi-refs.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    p = tmp_path / "lead.mid"
    p.write_bytes(m.lead())
    dur, lines = PV.midi_events(str(p), offset=1.0)
    assert abs(dur - (1.0 + 24 * 0.6)) < 1e-6                  # six mesures à 100 bpm, plus l'avance
    notes = [ln.split() for ln in lines if ln[0] == "n"]
    assert len(notes) == 16 and float(notes[0][1]) == 1.0 and notes[0][4:] == ["76", "96"]
    assert any(ln.startswith("c ") and ln.split()[2] == "224" for ln in lines)   # le bend (0xE0)


def test_une_scene_joue_la_phrase_de_son_son(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "DI_REFS_DIR", str(tmp_path))
    idx = {}
    for r in ("clean", "crunch", "djent", "lead", "lead-clean"):
        (tmp_path / f"{r}.wav").write_bytes(b"x")
        idx["guitar/" + r] = {"file": f"{r}.wav"}
    monkeypatch.setattr(PV, "_di_index", lambda: idx)
    monkeypatch.setattr(PV, "_casting", lambda pid: {})
    p = {"tags": ["jazz"], "scenes": [{"id": "A", "name": "Thumb"}, {"id": "D", "name": "Solo"}]}
    assert PV._scene_refs(p, ["A", "D"], "guitar/clean", "guitar", False) == {"A": "guitar/clean", "D": "guitar/lead-clean"}
    assert PV._scene_refs(p, ["A", "D"], "guitar/crunch", "guitar", False)["D"] == "guitar/lead"
    # un TAG « lead » ne met plus tout le patch en solo (Singing Clean jouait le solo partout, 2026-11-03)
    singing = {"tags": ["blues", "clean", "lead"], "scenes": [{"id": "A", "name": "Clean"}, {"id": "C", "name": "Lead"}]}
    assert PV._scene_refs(singing, ["A", "C"], "guitar/clean", "guitar", False) == {"A": "guitar/clean", "C": "guitar/lead-clean"}
    # une scène claire d'un patch metal joue la DI clean
    djent = {"scenes": [{"id": "A", "name": "Halo Clean"}, {"id": "C", "name": "Low Riff"}]}
    assert PV._scene_refs(djent, ["A", "C"], "guitar/djent", "guitar", False) == {"A": "guitar/clean", "C": "guitar/djent"}
    assert PV._scene_refs(p, ["A", "D"], "guitar/clean", "guitar", True)["D"] == "guitar/clean"    # DI choisie : respectée
    assert PV._scene_refs(p, ["A", "D"], "bass/finger", "bass", False)["D"] == "bass/finger"


def test_la_distribution_d_usine_passe_avant_la_regle(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "DI_REFS_DIR", str(tmp_path))
    (tmp_path / "clean.wav").write_bytes(b"x"); (tmp_path / "hg.wav").write_bytes(b"x")
    monkeypatch.setattr(PV, "_di_index", lambda: {"guitar/clean": {"file": "clean.wav"}, "guitar/high-gain": {"file": "hg.wav"},
                                                   "guitar/funk": {"file": "funk.wav"}})
    monkeypatch.setattr(PV, "_casting", lambda pid: {"A": "guitar/clean", "C": "guitar/high-gain", "B": "guitar/funk"})
    p = {"scenes": [{"id": "A", "name": "Shimmer Pad"}, {"id": "B", "name": "Chop"}, {"id": "C", "name": "Riff Double"}]}
    got = PV._scene_refs(p, ["A", "B", "C"], "guitar/high-gain", "guitar", False, "soaring")
    assert got == {"A": "guitar/clean", "B": "guitar/high-gain", "C": "guitar/high-gain"}   # funk pas enregistrée : la règle


def test_la_distribution_d_usine_nomme_des_patchs_et_des_di_qui_existent():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cast = json.load(open(os.path.join(root, "library", "factory", "demo-casting.json")))["patches"]
    known = {"guitar/" + b for b in ("clean", "crunch", "high-gain", "djent", "lead", "lead-clean", "funk")}
    for pid, scenes in cast.items():
        doc = json.load(open(os.path.join(root, "library", "factory", "patches", pid + ".json")))
        assert set(scenes) <= {s["id"] for s in doc["scenes"]}, pid
        assert set(scenes.values()) <= known, pid


def test_le_lot_saute_ce_qui_est_a_jour_et_dit_pourquoi_il_saute(pv, monkeypatch):
    tmp, sent = pv
    from bridge.state import state
    monkeypatch.setattr(state, "perf", {"recording": False}, raising=False)
    monkeypatch.setattr(PV, "patch_input", lambda pid: {"jazz": "2", "nobass": None, "novox": "2"}[pid])
    real_plan = PV.plan
    monkeypatch.setattr(PV, "plan", lambda pid, in_key="1", ref=None, casting=None:
                        "reference DI missing: voice/male (record it first)" if pid == "patch:novox" else real_plan(pid, in_key, ref, casting))
    PV.batch(["jazz", "nobass", "novox"])
    st = PV.batch_status()
    assert not st["running"] and st["done"] == 3
    got = {i["id"]: (i["status"], i.get("reason")) for i in st["items"]}
    assert got["jazz"] == ("rendered", None)
    assert got["nobass"] == ("skipped", "no input of this card plays it")
    assert got["novox"][0] == "skipped" and "voice/male" in got["novox"][1]
    n = len(sent)
    PV.batch(["jazz"])                                       # relancé : rien n'a bougé, rien n'est refait
    assert PV.batch_status()["items"][0] == {"id": "jazz", "status": "skipped", "reason": "up to date"}
    assert len(sent) == n
    PV.batch(["jazz"], force=True)
    assert PV.batch_status()["items"][0]["status"] == "rendered" and len(sent) > n


def test_le_lot_s_arrete_quand_une_prise_commence(pv, monkeypatch):
    from bridge.state import state
    monkeypatch.setattr(state, "perf", {"recording": True}, raising=False)
    PV.batch(["jazz"])
    st = PV.batch_status()
    assert st["done"] == 0 and "take" in st["stopped"] and st["items"][0]["status"] == "waiting"


def test_le_role_rendu_est_celui_de_la_lane_pas_de_l_entree(monkeypatch):
    # le lot du 2026-11-03 rendait les patchs voix avec la DI guitare : l'IN 1 de la carte « est » une guitare
    monkeypatch.setattr(PV, "_main_role", lambda p: "guitar")
    monkeypatch.setattr(PV, "input_role", lambda k: "guitar")
    from bridge import store as S
    monkeypatch.setattr(S, "lanes_of", lambda p, imap=None: p["lanes"])
    voice = {"lanes": [{"role": "voice", "input": 1}]}
    assert PV._role_of(voice, "1") == "voice"
    assert PV.resolve_di(voice, None, in_key="1")[0] == "voice/male"
    assert PV._role_of({"lanes": []}, "1") == "guitar"           # rien ne le dit : la carte


def test_une_basse_sans_entree_basse_n_a_pas_d_entree(monkeypatch):
    monkeypatch.setattr(store, "load_preset", lambda pid: {"lanes": [{"in_sel": "NONE"}]})
    assert PV.patch_input("x") is None


# ── la démo d'un preset, lane par lane : copiée de son patch quand la lane sonne pareil, rendue sinon ──
_PATCH_LANE = {"id": "guitar-1", "role": "guitar", "chain": {"pre": [{"id": "comp", "type": "comp", "params": {"ratio": 3}},
                                                                    {"id": "dly", "type": "delay", "bypass": True}],
                                                            "split": None, "post": []},
               "states": [{"id": "s-A", "name": "Thumb", "blocks": {}, "params": {"comp": {"ratio": 1}}},
                          {"id": "s-B", "name": "Lush", "blocks": {"dly": True}, "params": {}}]}


def _song(lane_chain=None, state_a=None):
    lane = {"id": "guitar-2", "role": "guitar", "patch_from": {"id": "jazz"},
            "chain": lane_chain or {"pre": [{"id": "comp-2", "type": "comp", "params": {"ratio": 3}},
                                            {"id": "dly-2", "type": "delay", "bypass": True}],
                                    "split": None, "post": [{"id": "volume-sys", "type": "volume"}]},
            "states": [state_a or {"id": "t-A", "name": "Thumb", "blocks": {"comp-2": True}, "params": {"comp-2": {"ratio": 1.0}}},
                       {"id": "t-B", "name": "Lush", "blocks": {"dly-2": True}}]}
    return {"id": "song", "lanes": [lane],
            "scenes": [{"id": "A", "name": "Verse", "lanes": {"guitar-2": {"state": "t-B"}}},
                       {"id": "B", "name": "Intro", "lanes": {"guitar-2": {"state": "t-A"}}},
                       {"id": "C", "name": "Break", "lanes": {"guitar-2": {"state": "t-A", "mute": True}}}]}


@pytest.fixture
def song(pv, monkeypatch):
    tmp, _ = pv
    from bridge import store as S
    monkeypatch.setattr(S, "lanes_of", lambda p, imap=None: p["lanes"])
    patch = {"id": "patch:jazz", "lanes": [_PATCH_LANE],
             "scenes": [{"id": "A", "lanes": {"guitar-1": {"state": "s-A"}}}, {"id": "B", "lanes": {"guitar-1": {"state": "s-B"}}}]}
    docs = {"song": _song(), "patch:jazz": patch}
    monkeypatch.setattr(store, "load_preset", lambda pid: docs.get(pid))
    d = tmp / "previews" / "patch-jazz"
    d.mkdir(parents=True)
    for s in "AB":
        (d / f"{s}.opus").write_bytes(b"clip-" + s.encode())
    monkeypatch.setattr(PV, "patch_preview", lambda pid: {"ref": "guitar/clean", "generated": "g1",
                                                          "scenes": {"A": "previews/patch-jazz/A.opus", "B": "previews/patch-jazz/B.opus"}})
    return tmp, docs


def test_une_lane_qui_sonne_comme_son_patch_recoit_ses_clips(song):
    tmp, docs = song
    pl = PV.lane_plan("song", "guitar-2")
    # Verse pose « Lush » -> scène B du patch ; Intro pose « Thumb » (écrit autrement : comp explicite, 1.0) -> A ;
    # Break coupe la lane : rien
    assert pl["copy"] == {"A": "B", "B": "A"}
    PV.copy_lane("song", "guitar-2", pl)
    e = PV.lane_previews("song")["guitar-2"]
    assert e["made"] == "copied" and e["from"] == "jazz" and set(e["scenes"]) == {"A", "B"}
    assert (tmp / e["scenes"]["A"]).read_bytes() == b"clip-B"                 # une COPIE, plus un lien
    assert PV.lane_up_to_date(PV.lane_plan("song", "guitar-2"), "song", "guitar-2")


def test_une_lane_retouchee_se_rend(song):
    _tmp, docs = song
    docs["song"] = _song(state_a={"id": "t-A", "name": "Thumb", "params": {"comp-2": {"ratio": 6}}})
    assert "state its patch does not have" in PV.lane_plan("song", "guitar-2")["render"]
    docs["song"] = _song(lane_chain={"pre": [{"id": "comp-2", "type": "comp", "params": {"ratio": 3}}], "split": None, "post": []})
    assert PV.lane_plan("song", "guitar-2")["render"] == "the lane was changed since its patch"


def test_la_demo_du_patch_refaite_fait_recopier(song, monkeypatch):
    pl = PV.lane_plan("song", "guitar-2")
    PV.copy_lane("song", "guitar-2", pl)
    monkeypatch.setattr(PV, "patch_preview", lambda pid: dict(pl["patch_demo"], generated="g2"))
    assert not PV.lane_up_to_date(PV.lane_plan("song", "guitar-2"), "song", "guitar-2")


def test_une_entree_est_empruntee_sans_toucher_la_carte(monkeypatch):
    # le rack du mainteneur n'a pas d'entrée basse : la démo d'une basse se rend sur une entrée empruntée
    from bridge import inputmap
    card = {"card": "hw:X", "inputs": [{"ch": "1", "role": "voice"}, {"ch": "2", "role": "guitar"}]}
    monkeypatch.setattr(inputmap, "current", lambda: card)
    imap, ch = PV._borrowed_imap("bass")
    assert ch == "1" and imap["inputs"][0]["role"] == "bass"
    assert card["inputs"][0]["role"] == "voice"                  # la vraie carte n'est pas touchée
    monkeypatch.setattr(inputmap, "current", lambda: {"inputs": []})
    assert PV._borrowed_imap("bass") == (None, None)
