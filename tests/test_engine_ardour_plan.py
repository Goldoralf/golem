# SPDX-License-Identifier: GPL-3.0-or-later
"""Le plan MOTEUR du Golem Engine (bridge/engine/ardour_plan.py, lot A2.0) : topologie, paramètres à la règle de
golem_rig, refus dits — et l'adaptateur qui joint ce plan aux rappels et aux scènes, et lit ses bornes au livemap."""
import json

import pytest

from bridge import commands
from bridge import config as C
from bridge.engine import ardour as A
from bridge.engine import ardour_plan as P

CAT = {
    "amp-nam": {"type": "amp-nam", "params": [{"id": "input", "name": "Input", "min": -20, "max": 20},
                                               {"id": "output", "name": "Output", "min": -20, "max": 20}]},
    "cab": {"type": "cab", "params": [{"id": "level", "name": "Wet Signal Level", "min": -12, "max": 12,
                                       "map": {"mode": "raw"}}]},
    "delay-tape": {"type": "delay-tape", "params": [
        {"id": "time", "name": "Time L", "type": "enum", "options": ["16th", "8th", "dotted 8th"], "values": [1, 2, 3],
         "map": {"mode": "raw"}},
        {"id": "medium", "name": "Medium", "type": "enum", "options": ["plain", "tape", "old"], "map": {"mode": "raw"}},
        {"id": "mode", "name": "Mode", "type": "enum", "options": ["a", "b", "c"]},
        {"id": "feedback", "name": "Feedback", "min": 0, "max": 80, "map": {"mode": "raw", "scale": 0.01}},
        {"id": "on", "name": "Sync", "type": "bool"}]},
    "rea": {"type": "rea", "params": [{"id": "wet", "name": "Wet", "map": {"curve": "pct_db"}}]},
    "gate": {"type": "gate", "params": []},
}
TABLE = {"amp-nam": {"lv2": "urn:nam", "files": {"file": "urn:nam#model"}},
         "cab": {"lv2": "urn:ir", "files": {"file": "urn:ir#ir"}},
         "delay-tape": {"lv2": "urn:dly"},
         "rea": {"lv2": "urn:rea"},
         "volume": {"lua": "ACE Amplifier", "params": {"gain": "Gain"}}}


def split_rig():
    pre, merge, la, lb = "G:g", "G:g#merge", "G:g/lane-a", "G:g/lane-b"
    return {"id": "patch:x", "paths": [{"id": "g", "tracks": [
        {"role": "pre", "name": pre, "input": 2, "blocks": [{"id": "g1", "type": "gate"}], "sends_to": [la, lb]},
        {"role": "merge", "name": merge, "merge_gain": -3, "folder": "parent", "out_sel": "3-4",
         "blocks": [{"id": "d", "type": "delay-tape", "foot": 8, "bypass": True,
                     "params": {"feedback": 120, "time": "8th", "medium": "old", "mode": "b", "on": 1}}]},
        {"role": "branch", "name": la, "folder": "child", "folder_of": merge, "mute": True,
         "blocks": [{"id": "a", "type": "amp-nam", "file": "/m.nam", "params": {"output": 3.7, "_loud": -20}},
                    {"id": "c", "type": "cab", "file": "/c.wav", "params": {"level": -30}}]},
        {"role": "branch", "name": lb, "folder": "child", "folder_of": merge,
         "blocks": [{"id": "r", "type": "rea", "params": {"wet": 50}}]}]}]}


def test_topologie_pre_branches_merge():
    plan = P.build(split_rig(), CAT, TABLE)
    t = {x["name"]: x for x in plan["tracks"]}
    assert t["G:g"]["kind"] == "track" and t["G:g"]["input"] == 2 and t["G:g"]["out"] is None
    assert t["G:g/lane-a"]["kind"] == "bus" and t["G:g/lane-a"]["from"] == ["G:g"] and t["G:g/lane-a"]["mute"]
    assert t["G:g#merge"]["from"] == ["G:g/lane-a", "G:g/lane-b"] and t["G:g#merge"]["out"] == [3, 4]
    assert t["G:g#merge"]["gain_db"] == -3.0


def test_piste_unique_et_sorties():
    rig = {"id": "v", "paths": [{"id": "v", "tracks": [{"role": "main", "name": "G:v", "input": 1, "out_sel": "2",
                                                        "level": -4, "blocks": []}]}]}
    tr = P.build(rig, CAT, TABLE)["tracks"][0]
    assert tr["kind"] == "track" and tr["out"] == [2] and tr["gain_db"] == -4.0
    assert P.out_ports(None) == [1, 2] and P.out_ports("1-2") == [1, 2]


def test_parametres_a_la_regle_de_golem_rig():
    plan = P.build(split_rig(), CAT, TABLE)
    blk = {b["id"]: b for t in plan["tracks"] for b in t["blocks"]}
    a, c, d = blk["a"], blk["c"], blk["d"]
    assert a["plugin"] == {"lv2": "urn:nam"} and a["files"] == {"urn:nam#model": "/m.nam"} and a["enabled"]
    assert a["params"] == [{"pid": "output", "label": "Output", "value": 3.7}]           # _loud n'est pas un paramètre
    assert c["params"] == [{"pid": "level", "label": "Wet Signal Level", "value": -12.0}]   # borné au catalogue
    dp = {p["pid"]: p for p in d["params"]}
    assert dp["feedback"]["value"] == pytest.approx(0.8)                 # 120 -> 80 (borne) × 0,01
    assert dp["time"]["value"] == 2                                      # l'option vise sa valeur
    assert dp["medium"]["value"] == 2                                    # sans valeurs, en raw : son rang
    assert dp["mode"]["norm"] == 0.5                                     # sans valeurs, en norm : rang normalisé
    assert dp["on"]["norm"] == 1
    assert d["enabled"] is False and d["foot"] == 8
    assert {k["pid"] for k in a["known"]} == {"input", "output"}         # tous les potards, pour le livemap


def test_ce_qui_ne_joue_pas_ici_est_dit():
    plan = P.build(split_rig(), CAT, TABLE)
    why = {(s.get("id"), s.get("param")): s["why"] for s in plan["skipped"]}
    assert why[("g1", None)] == P.NOT_HERE                               # type absent de la table
    assert "pct_db" in why[("r", "wet")]                                 # courbe REAPER refusée
    blk = {b["id"] for t in plan["tracks"] for b in t["blocks"]}
    assert "g1" not in blk and "r" in blk                                # le bloc reste, sans ce potard


CARDS = """ 1 [V276           ]: USB-Audio - Volt 276
                      Universal Audio Volt 276 at usb-0000:0e:00.0-2, high speed
 4 [II             ]: USB-Audio - MPK Mini Mk II
                      AKAI MPK Mini Mk II at usb-0000:0e:00.0-1, full speed
"""


def test_une_lane_midi_est_une_piste_midi_sur_son_clavier_seul():
    rig = {"id": "k", "paths": [{"id": "keys", "tracks": [{
        "role": "main", "name": "G:k", "midi": True, "midi_role": "keys", "midi_in": "hw:II",
        "midi_ch": {"keys": 1, "pads": 10}, "out_sel": "1-2", "blocks": []}]}]}
    plan = P.build(rig, CAT, TABLE, cards_text=CARDS)
    (t,) = plan["tracks"]
    assert t["kind"] == "midi" and t["input"] is None and t["out"] == [1, 2]
    assert t["midi"] == {"device": "MPK Mini Mk II", "hw": "hw:II", "channel": 1}   # le canal des touches, pas des pads
    assert plan["skipped"] == []


def test_un_clavier_debranche_est_dit_et_la_piste_reste():
    rig = {"id": "k", "paths": [{"id": "keys", "tracks": [{"role": "main", "name": "G:k", "midi": True,
                                                            "midi_in": "hw:Gone", "blocks": []}]}]}
    plan = P.build(rig, CAT, TABLE, cards_text=CARDS)
    assert plan["tracks"][0]["midi"]["device"] is None
    assert "no MIDI device" in plan["skipped"][0]["why"]


def test_le_nom_du_clavier_vient_de_la_carte_alsa():
    assert P.midi_device("hw:II", CARDS) == "MPK Mini Mk II"
    assert P.midi_device("hw:4", CARDS) == "MPK Mini Mk II"            # par numéro aussi
    assert P.midi_device("usb1", CARDS) is None and P.midi_device(None, CARDS) is None


def test_le_piano_joue_sfizz_avec_son_fichier():
    table = P.load_table()
    blk, sk = P.plan_block({"id": "piano", "type": "piano", "params": {"volume": -3},
                            "sfz_file": "/x/piano.sfz"}, P.load_catalog(), table)
    assert blk["plugin"] == {"lv2": "http://sfztools.github.io/sfizz"}
    assert blk["files"] == {"http://sfztools.github.io/sfizz:sfzfile": "/x/piano.sfz"}
    assert {"pid": "volume", "label": "Volume", "value": -3.0} in blk["params"]
    assert blk["loaded_output"] == "Number of regions"            # sfizz ne renvoie pas son fichier : ce témoin le dit


def test_la_vraie_table_et_le_vrai_catalogue_se_lisent():
    table, cat = P.load_table(), P.load_catalog()
    assert {"amp-nam", "cab", "volume"} <= set(table)
    assert set(table) <= set(cat)                                        # chaque entrée vise un type du catalogue


@pytest.fixture
def slot(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "COMMAND_FILE", str(tmp_path / ".command.json"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    monkeypatch.setattr(commands, "ACK_FILE", str(tmp_path / ".command-ack.json"))
    monkeypatch.setattr(commands.sys, "platform", "linux")
    monkeypatch.setattr(commands, "_reaper_up", lambda: True)
    monkeypatch.setattr(commands, "_queue", [])
    monkeypatch.setattr(commands, "_drainer", None)
    return tmp_path


def test_le_rappel_emporte_son_plan(slot, monkeypatch):
    rig = slot / "x.rig.json"
    rig.write_text(json.dumps(split_rig()))
    monkeypatch.setattr(P, "rig_path", lambda pid: str(rig))
    monkeypatch.setattr(P, "load_catalog", lambda path=None: CAT)
    monkeypatch.setattr(P, "load_table", lambda path=None: TABLE)
    seq = A.ArdourEngine(link=object()).send({"action": "rig_recall", "preset": "patch:x", "scene": "A"})
    cmd = json.loads((slot / ".command.json").read_text())
    assert cmd["seq"] == seq and cmd["plan"]["preset"] == "patch:x" and len(cmd["plan"]["tracks"]) == 4


def test_sans_plan_compile_rien_ne_part(slot, monkeypatch):
    monkeypatch.setattr(P, "rig_path", lambda pid: str(slot / "absent.rig.json"))
    assert A.ArdourEngine(link=object()).send({"action": "scene_apply", "preset": "p", "scene": "B"}) is None
    assert not (slot / ".command.json").exists()


def test_les_bornes_des_potards_viennent_du_livemap(slot):
    (slot / ".livemap.json").write_text(json.dumps({"preset": "p", "blocks": {
        "a": {"track": 4, "fx": 0, "type": "amp", "params": {"input": {"p": 0, "pmin": -20, "pmax": 20}}}}}))
    e = A.ArdourEngine(link=object())
    assert e.raw_value(4, 0, 0, 0.75) == pytest.approx(10.0)
    assert e.raw_value(4, 0, 1, 0.5) is None


def test_dans_le_designer_un_type_sans_plugin_ici_est_pas_encore():
    from bridge import blockstatus, engine
    prev = engine.use(A.ArdourEngine(link=object()))
    try:
        gate = blockstatus.engine_gate()
        st = blockstatus.block_state({"type": "eq"})
    finally:
        engine.use(prev)
    assert "amp-nam" not in gate and "cab" not in gate                  # dans la table : ils jouent
    assert gate["eq"] == ("planned", "Golem Engine")                    # ReaEQ : pas encore (golem-fx)
    assert gate["looper"][1] == "Golem Engine"                          # fonction du moteur non déclarée
    assert st["reason"] == "engine" and st["why"] == "not available on Golem Engine yet"


# ── A2.2 : le Dashboard lit le moteur actif ─────────────────────────────────────────────────────────────────
def _alive_engine(monkeypatch, tmp_path, status):
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    (tmp_path / "presets").mkdir(exist_ok=True)
    (tmp_path / "presets" / ".engine-status.json").write_text(json.dumps(status))
    e = A.ArdourEngine(link=object())
    monkeypatch.setattr(e, "pid", lambda: 4242)
    return e


def test_le_moteur_dit_son_buffer_sa_frequence_sa_charge(monkeypatch, tmp_path):
    e = _alive_engine(monkeypatch, tmp_path, {"buffer": 256, "sample_rate": 48000, "dsp_load": 37.04, "xruns": 3,
                                              "backend": "ALSA"})
    assert e.audio() == {"buffer": 256, "rate": 48000, "backend": "ALSA", "dsp_load": 37.0}
    assert e.xruns() == 3


def test_le_buffer_change_a_chaud_et_se_garde(monkeypatch, tmp_path):
    e = _alive_engine(monkeypatch, tmp_path, {"buffer": 1024})
    sent = []
    monkeypatch.setattr(e, "send", lambda c: sent.append(c) or 7)
    r = e.set_buffer(256)
    assert r["restarting"] is False and r["applied_live"] and sent == [{"action": "audio_set", "buffer": 256}]
    assert json.loads((tmp_path / "config" / "golem-engine.json").read_text()) == {"buffer": 256}
    with pytest.raises(ValueError):
        e.set_buffer(100)


def test_les_routes_du_dashboard_suivent_le_moteur_actif(monkeypatch, tmp_path):
    import asyncio
    from bridge import engine, routes_system
    e = _alive_engine(monkeypatch, tmp_path, {"buffer": 128, "sample_rate": 48000, "dsp_load": 12.0})
    monkeypatch.setattr(e, "send", lambda c: 1)
    monkeypatch.setattr(e, "descriptor", lambda: {"name": "Golem Engine"})      # C.ROOT pointe sur tmp_path
    prev = engine.use(e)
    try:
        s = routes_system.system()
        r = asyncio.run(routes_system.audio_buffer({"size": 512}))
        bad = asyncio.run(routes_system.audio_buffer({"size": 100}))
    finally:
        engine.use(prev)
    assert s["engine"]["name"] == "Golem Engine" and s["audio_bsize"] == 128 and s["audio_srate"] == 48000
    assert s["audio_dsp_load"] == 12.0 and 1024 in s["audio_bsizes"] and s["audio_live_buffer"] is True
    assert r["ok"] and r["size"] == 512 and r["restarting"] is False
    assert bad.status_code == 400


def test_sous_reaper_le_dashboard_ne_change_pas():
    from bridge import engine, routes_system
    from bridge.engine.reaper import ReaperEngine
    prev = engine.use(ReaperEngine(link=object()))
    try:
        s = routes_system.system()
    finally:
        engine.use(prev)
    assert s["engine"]["id"] == "reaper" and "audio_live_buffer" not in s and "audio_dsp_load" not in s
    assert s["audio_bsize"] == routes_system._read_bsize()


def test_les_xruns_du_moteur_se_cumulent_a_travers_ses_relances(monkeypatch):
    from bridge import engine, monitors
    counts = iter([5, 7, 2, 4])                         # 5 (base), +2, relance (repart à 2 : +2), +2
    fake = type("E", (), {"xruns": lambda self: next(counts)})()
    monkeypatch.setattr(engine, "get", lambda: fake)
    monkeypatch.setattr(monitors, "_ENGINE_XRUN", {"last": None, "acc": 0})
    assert [monitors._engine_xruns() for _ in range(4)] == [0, 2, 4, 6]


# ── A2.3 : la carte son ─────────────────────────────────────────────────────────────────────────────────────
def test_le_buffer_lu_partout_est_celui_du_moteur_actif(monkeypatch, tmp_path):
    """Soundcard, le battement golem.fm, Health et le diagnostic lisent routes_system._read_bsize : sous le Golem Engine
    c'est le buffer du moteur, jamais celui de reaper.ini (mesuré au banc : « 192 smp » affiché pour un moteur en 1024)."""
    from bridge import engine, routes_system
    e = _alive_engine(monkeypatch, tmp_path, {"buffer": 1024})
    prev = engine.use(e)
    try:
        assert routes_system._read_bsize() == 1024
    finally:
        engine.use(prev)


def test_la_carte_par_defaut_est_celle_de_golem(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "alsa_card", lambda: "V276")
    assert A.card_device() is None                                       # pas de registre : pas de carte
    (tmp_path / "config" / "cards").mkdir(parents=True)
    (tmp_path / "config" / "cards" / "V276.json").write_text(json.dumps({"id": "V276", "name": "Universal Audio Volt 276"}))
    assert A.card_device() == "Universal Audio Volt 276"


# ── A2.4 : Health et l'inventaire du moteur ─────────────────────────────────────────────────────────────────
def test_health_lit_l_inventaire_et_le_veilleur_du_golem_engine(monkeypatch, tmp_path):
    import time as _t
    from bridge import engine, health, incidents
    e = _alive_engine(monkeypatch, tmp_path, {"buffer": 256})
    monkeypatch.setattr(e, "descriptor", lambda: {"name": "Golem Engine"})
    pr = tmp_path / "presets"
    prev = engine.use(e)
    try:
        assert health._f_plugins()["level"] == "wait"                          # le moteur n'a pas encore répondu
        (pr / ".engine-plugins.json").write_text(json.dumps({"found": {"amp-nam": True, "delay-tape": False},
                                                              "n": 1, "total": 2}))
        f = health._f_plugins()
        assert f["level"] == "warn" and "1 of 2 block plugins found by Golem Engine" in f["text"] and "delay-tape" in f["text"]
        assert e.missing_plugin("delay-tape") and not e.missing_plugin("amp-nam")
        from bridge import blockstatus
        assert blockstatus.block_state({"type": "delay-tape"})["reason"] == "plugin"
        assert health._f_scripts()["level"] == "ok"
        now = _t.strftime("%Y-%m-%d %H:%M:%S")
        (pr / ".watch.log").write_text(f"{now} [golem-engine] ÉCHEC rig_recall : plugin absent\n")
        s = health._f_scripts()
        assert s["level"] == "warn" and "plugin absent" in s["text"]
        assert incidents._title("engine") == "Golem Engine not answering"
    finally:
        engine.use(prev)
    assert incidents._title("engine") == "REAPER not answering"                 # sous REAPER : le texte de toujours


def test_un_drum_kit_est_le_traducteur_puis_le_kit_avldrums():
    table = P.load_table()
    blk = {"id": "kit", "type": "drumkit", "kit_engine": "avldrums", "kit_bank": "red-zeppelin", "bypass": True,
           "drum_map": [-1] * 36 + [36] + [-1] * 91, "drum_hh": {"cc": 4}, "drum_chan": 10, "foot": 3}
    rig = {"id": "d", "paths": [{"id": "drums", "tracks": [{"role": "main", "name": "G:d", "midi": True,
                                                             "midi_in": "hw:II", "blocks": [blk]}]}]}
    (t,) = P.build(rig, P.load_catalog(), table, cards_text=CARDS)["tracks"]
    trans, kit = t["blocks"]
    assert trans["plugin"] == {"lua": "golem Drumtrans"} and trans["enabled"] is True     # le traducteur ne se coupe pas
    assert trans["drumtrans"]["map"][36] == 36 and len(trans["drumtrans"]["map"]) == 128
    assert kit["plugin"] == {"lv2": "http://gareus.org/oss/lv2/avldrums#RedZeppelin"}
    assert kit["enabled"] is False and kit["foot"] == 3 and kit["id"] == "kit"           # le kit suit le bypass, garde son id


def test_un_kit_drumgizmo_ne_joue_pas_encore_ici():
    blocks, sk = P.plan_drumkit({"id": "kit", "kit_engine": "drumgizmo", "kit_id": "drums-aasimonster"},
                                P.load_table()["drumkit"])
    assert blocks == [] and "drumgizmo" in sk[0]["why"]


def test_les_reglages_d_ajout_partent_avec_le_bloc():
    table = P.load_table()
    table = dict(table, fake={"lv2": "urn:x", "init": {"FX Type": 27}})
    blk, _ = P.plan_block({"id": "sp", "type": "fake", "params": {}}, P.load_catalog(), table)
    assert blk["init"] == [{"pid": "init:FX Type", "label": "FX Type", "value": 27}]
    blk, _ = P.plan_block({"id": "ch", "type": "chorus", "params": {}}, P.load_catalog(), table)
    assert blk["init"][0]["label"] == "Dry Amount" and blk["init"][0]["value"] == 1.0


def test_un_parametre_sans_controle_est_refuse_avec_sa_raison():
    blk, sk = P.plan_block({"id": "aw", "type": "autowah", "params": {"wah": 0.5}}, P.load_catalog(), P.load_table())
    assert blk["params"] == [] and sk[0]["param"] == "wah" and "GxAutoWah" in sk[0]["why"]


def test_un_vst3_part_avec_son_identifiant():
    blk, _ = P.plan_block({"id": "b", "type": "boost", "params": {"drive": 40}}, P.load_catalog(), P.load_table())
    assert set(blk["plugin"]) == {"vst3"} and len(blk["plugin"]["vst3"]) == 32

