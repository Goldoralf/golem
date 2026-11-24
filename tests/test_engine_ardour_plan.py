# SPDX-License-Identifier: GPL-3.0-or-later
"""Le plan MOTEUR du Golem Engine (bridge/engine/ardour_plan.py, lot A2.0) : topologie, paramètres à la règle de
golem_rig, refus dits — et l'adaptateur qui joint ce plan aux rappels et aux scènes, et lit ses bornes au livemap."""
import json
import sys

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
    assert t["G:g#merge"]["trim_db"] == -3.0 and t["G:g#merge"]["gain_db"] == 0.0   # merge_gain AVANT les plugins


def test_le_niveau_de_scene_va_au_fader_du_merge_et_son_gain_au_trim():
    # golem_rig.lua : `level` = D_VOL de la piste qui sort ; `merge_gain` = un Volume Adjustment en tête du merge
    rig = split_rig()
    for tr in rig["paths"][0]["tracks"]:
        if tr["role"] == "merge":
            tr["level"] = 3
        elif tr["role"] == "pre":
            tr["level"] = 5                     # une piste qui ne sort pas : REAPER n'y pose aucun niveau
    t = {x["name"]: x for x in P.build(rig, CAT, TABLE)["tracks"]}
    assert t["G:g#merge"]["gain_db"] == 3.0 and t["G:g#merge"]["trim_db"] == -3.0
    assert t["G:g"]["gain_db"] == 0.0 and t["G:g"]["trim_db"] == 0.0


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


def test_sous_windows_le_clavier_est_le_nom_de_son_port(monkeypatch):
    # midi_in y est déjà le port présent (vital._hw_of) : None muait toutes les lanes Keys / Drums du moteur
    monkeypatch.setattr(P.sys, "platform", "win32")
    assert P.midi_device("MPK Mini Mk II") == "MPK Mini Mk II"
    assert P.midi_device("usb1") is None and P.midi_device("") is None and P.midi_device(None) is None
    assert P.midi_device("hw:II", CARDS) == "MPK Mini Mk II"           # la forme Linux reste comprise


def test_le_nom_du_clavier_vient_de_la_carte_alsa(monkeypatch):
    monkeypatch.setattr(P.sys, "platform", "linux")
    assert P.midi_device("MPK Mini Mk II", CARDS) is None               # sous Linux, seul « hw:… » nomme une carte
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


def test_l_ir_fx_joue_le_convolveur_stereo_avec_son_ir():
    # docs/library-tones.md §8 : la variante stéréo du convolveur du baffle, son IR en propriété de fichier
    blk, sk = P.plan_block({"id": "re301", "type": "ir-fx", "file": "/x/echo.wav", "params": {"wet": -6, "dry": 0}},
                           P.load_catalog(), P.load_table())
    assert blk["plugin"] == {"lv2": "http://gareus.org/oss/lv2/zeroconvolv#CfgStereo"}, sk
    assert blk["files"] == {"http://gareus.org/oss/lv2/zeroconvolv#ir": "/x/echo.wav"}
    assert {"pid": "wet", "label": "Wet Signal Level", "value": -6} in blk["params"]


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
        st = blockstatus.block_state({"type": "surge-freqshift"})
    finally:
        engine.use(prev)
    assert "amp-nam" not in gate and "cab" not in gate                  # dans la table : ils jouent
    assert gate["surge-freqshift"] == ("planned", "Golem Engine")           # Surge XT : pas sur ce moteur
    assert "looper" not in gate and "compo" not in gate                  # leurs fonctions sont déclarées : ils jouent
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
    monkeypatch.setattr(A.sys, "platform", "linux")
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "alsa_card", lambda: "V276")
    assert A.card_device() is None                                       # pas de registre : pas de carte
    (tmp_path / "config" / "cards").mkdir(parents=True)
    (tmp_path / "config" / "cards" / "V276.json").write_text(json.dumps({"id": "V276", "name": "Universal Audio Volt 276"}))
    assert A.card_device() == "Universal Audio Volt 276"


def test_sans_fiche_la_carte_branchee_est_sondee(monkeypatch, tmp_path):
    # rack réel 2026-11-24 : iTwo choisie par config/io.json, aucun config/cards/ — le moteur partait sur Dummy
    from bridge import cards
    monkeypatch.setattr(A.sys, "platform", "linux")
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "alsa_card", lambda: "iTwo")
    monkeypatch.setattr(cards, "probe", lambda cid: {"id": cid, "name": "PreSonus AudioBox iTwo"} if cid == "iTwo" else None)
    assert A.card_device() == "PreSonus AudioBox iTwo"
    monkeypatch.setattr(cards, "probe", lambda cid: None)               # débranchée : rien n'est deviné
    assert A.card_device() is None
    monkeypatch.setattr(C, "alsa_card", lambda: "")
    assert A.card_device() is None


def test_sous_windows_la_carte_est_le_pilote_asio_de_settings_audio(monkeypatch, tmp_path):
    """Windows (2026-11-20) : pas de config/cards — la carte est le pilote ASIO réglé dans Settings ▸ Audio (le
    reaper.ini de golem) ; un autre mode audio ne devine rien : le moteur reste sur le pilote factice."""
    monkeypatch.setattr(A.sys, "platform", "win32")
    monkeypatch.setattr(C, "reaper_resource_dir", lambda: str(tmp_path))
    ini = tmp_path / "reaper.ini"
    assert A.card_device() is None                                       # pas de reaper.ini
    ini.write_text('[audioconfig]\nmode=3\nasio_driver_name="Universal Audio Volt"\n', encoding="utf-8")
    assert A.card_device() == "Universal Audio Volt"
    ini.write_text('[audioconfig]\nmode=5\nasio_driver_name="Universal Audio Volt"\n', encoding="utf-8")
    assert A.card_device() is None                                       # WASAPI : rien n'est deviné


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
    assert blk["init"][0]["label"] == "Level Comp" and blk["init"][0]["value"] == 0     # gfx-chorus : niveau de Calf


def test_un_parametre_sans_controle_est_refuse_avec_sa_raison():
    table = {"autowah": {"lv2": "urn:gxautowah", "absent": {"wah": "GxAutoWah has no such control"}}}
    blk, sk = P.plan_block({"id": "aw", "type": "autowah", "params": {"wah": 0.5}}, P.load_catalog(), table)
    assert blk["params"] == [] and sk[0]["param"] == "wah" and "GxAutoWah" in sk[0]["why"]


def test_un_vst3_part_avec_son_identifiant():
    blk, _ = P.plan_block({"id": "b", "type": "grit", "params": {}}, P.load_catalog(), P.load_table())
    assert set(blk["plugin"]) == {"vst3"} and len(blk["plugin"]["vst3"]) == 32



def test_un_parametre_renomme_par_la_table_perd_l_echelle_du_catalogue():
    # le limiteur : le catalogue envoie la release en SECONDES à l'x42 (scale 0.001) ; gfx-limiter la prend en ms
    cat = P.load_catalog()
    table = {"limiter": {"lv2": "urn:x42"}}
    blk, _ = P.plan_block({"id": "l", "type": "limiter", "params": {"release": 80}}, cat, table)
    assert blk["params"][0]["value"] == pytest.approx(0.08)
    table = {"limiter": {"vst3": "X", "params": {"release": "Release"}}}
    blk, _ = P.plan_block({"id": "l", "type": "limiter", "params": {"release": 80}}, cat, table)
    assert blk["params"][0] == {"pid": "release", "label": "Release", "value": 80.0}


def test_chaque_effet_golem_fx_porte_son_statut():
    # pendant les essais au rig : `testing`, puis `validated` sur le oui du mainteneur (seuls ceux-là partent en release)
    for t, spec in P.load_table().items():
        if spec.get("golem_fx"):
            assert spec.get("status") in ("testing", "validated"), t


def test_un_parametre_renomme_part_dans_l_unite_du_catalogue_sans_courbe_ni_values():
    # gfx-delay : le temps par son RANG (pas la noire de ReaDelay), feedback et mix en % bruts (pas le pct_db de ReaDelay)
    cat = P.load_catalog()
    table = {"delay": {"vst3": "X", "params": {"time": "Time", "feedback": "Feedback", "mix": "Mix"}}}
    blk, sk = P.plan_block({"id": "d", "type": "delay", "params": {"time": "1/8", "feedback": 35, "mix": 25}}, cat, table)
    assert sk == [] and {p["pid"]: p["value"] for p in blk["params"]} == {"time": 3, "feedback": 35.0, "mix": 25.0}
    # sans renommage, la courbe de REAPER reste refusée (rien ne la sait jouer ici)
    blk, sk = P.plan_block({"id": "d", "type": "delay", "params": {"feedback": 35}}, cat, {"delay": {"vst3": "X"}})
    assert blk["params"] == [] and "pct_db" in sk[0]["why"]


def test_le_plan_emporte_le_tempo_du_morceau(tmp_path, monkeypatch):
    from bridge.engine import ardour as AR
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path))
    assert AR._bpm({"preset": "x", "bpm": 92}) == 92.0                       # la ligne de setlist d'abord
    (tmp_path / "x.json").write_text(json.dumps({"bpm": 140}))
    assert AR._bpm({"preset": "x"}) == 140.0                                 # sinon le preset, comme golem_rig
    assert AR._bpm({"preset": "y"}) is None


def test_la_quarantaine_vise_un_plugin_que_le_golem_engine_ne_pose_pas(monkeypatch):
    # pitch : ReaPitch figeait REAPER (quarantaine du catalogue) ; sous le Golem Engine, gfx-pitch le joue — pas de
    # quarantaine là ; sous REAPER, elle reste
    from bridge import engine, rig
    monkeypatch.setattr(rig, "_QUARANTINE", {"pitch": "ReaPitch freezes REAPER", "delay-echo": "GxEchoCat"})
    monkeypatch.setattr(P, "load_table", lambda path=None: {"pitch": {"vst3": "X", "golem_fx": True},
                                                            "delay-echo": {"lv2": "urn:gx"}})
    prev = engine.use(A.ArdourEngine(link=object()))
    try:
        assert set(rig.quarantined_types()) == {"delay-echo"}          # un plugin hors golem-fx reste en quarantaine
    finally:
        engine.use(prev)
    assert set(rig.quarantined_types()) == {"pitch", "delay-echo"}     # REAPER : rien ne change


def test_l_harmonie_de_gfx_pitch_part_par_le_rang_et_song_key_reste_au_compilateur():
    blk, sk = P.plan_block({"id": "h", "type": "pitch", "params": {
        "harmony": "Scale", "key": "Bb", "scale": "Minor Pentatonic", "shift2": 7, "voice2": -4, "song_key": True}},
        P.load_catalog(), P.load_table())
    got = {p["label"]: p for p in blk["params"]}
    assert set(got) >= {"Harmony", "Key", "Scale", "Shift 2", "Voice 2 Level"}
    assert [s["param"] for s in sk] == ["song_key"]


def test_un_gate_a_cle_recoit_l_entree_de_sa_lane():
    # docs/golem-fx-sheet.md §4 : le sidechain de Met est relié à l'entrée de la carte de son path
    from bridge.engine import ardour_plan as P
    rig = {"id": "k", "paths": [{"id": "p", "tracks": [
        {"role": "pre", "name": "G", "input": 3, "blocks": [], "sends_to": ["G#merge"]},
        {"role": "merge", "name": "G#merge", "blocks": [{"id": "met", "type": "met"}, {"id": "dly", "type": "delay"}],
         "out_sel": "1-2"}]}]}
    plan = P.build(rig)
    blocks = {b["id"]: b for t in plan["tracks"] for b in t["blocks"]}
    assert blocks["met"]["key_input"] == 3 and "key_input" not in blocks["dly"]


def test_une_tete_sans_baffle_emporte_son_baffle_par_defaut():
    # REAPER fond ce baffle dans le cœur de la piste ; ici un plugin par bloc : le compileur dit le fichier, le plan
    # pose un cab juste derrière la tête, dans le même état qu'elle, hors du livemap (`shadow`)
    rig = {"id": "p", "paths": [{"id": "g", "input": 1, "tracks": [{"role": "main", "name": "G:g", "input": 1, "out_sel": "1-2",
           "blocks": [{"id": "head", "type": "amp-nam", "file": "/m.nam", "bypass": True, "default_ir": "/cab.wav"},
                      {"id": "g1", "type": "gate"}]}]}]}
    blocks = P.build(rig, CAT, TABLE)["tracks"][0]["blocks"]
    assert [b["id"] for b in blocks] == ["head", "head~ir"]
    ir = blocks[1]
    assert ir["type"] == "cab" and ir["files"] == {"urn:ir#ir": "/cab.wav"} and ir["shadow"] is True
    assert ir["enabled"] is False                              # il suit la tête, éteinte dans cette scène


def test_une_route_qui_sort_dit_sa_tranche_du_mixer():
    tr = {t["name"]: t for t in P.build({"id": "p", "paths": [dict(split_rig()["paths"][0], input=2)]}, CAT, TABLE)["tracks"]}
    assert tr["G:g#merge"]["mixer"] == "in2"                   # la route qui va à la carte porte le trim du rig
    assert "mixer" not in tr["G:g"] and "mixer" not in tr["G:g/lane-a"]


# ── lot 2 : les instruments de clavier (docs/ardour-plan.md §7d) ─────────────────────────────────────────────────────
KCAT = {"organ": {"type": "organ", "params": [{"id": "db16", "name": "1: Drawbar 16", "min": 0, "max": 8},
                                              {"id": "zone_lo", "name": "Zone Low"}, {"id": "arp", "type": "enum"}]},
        "vital": {"type": "vital", "params": [{"id": "preset", "type": "enum", "dynamic": "vital-presets"},
                                              {"id": "vol", "name": "Volume", "min": 0, "max": 1, "map": {"mode": "raw"}},
                                              {"id": "transpose", "name": "Transpose"}, {"id": "arp", "type": "enum"}]},
        "ep": {"type": "ep", "params": [{"id": "bank", "type": "enum", "dynamic": "dx7-banks"}, {"id": "patch", "name": "Patch"}]},
        "pads": {"type": "pads", "params": [{"id": "kit", "type": "kitref"}]},
        "comp": {"type": "comp", "params": []}}
KTABLE = {"organ": {"lv2": "urn:b3", "midi": "organ", "zone": True, "arp": True},
          "vital": {"vst3": "ABABABABABABABABABABABABABABABAB", "zone": True, "arp": True, "preset": {"from": "vital_chunk", "vendor": "V", "name": "Vital"}},
          "ep": {"vst3": "DX", "midi": "dx7", "zone": True},
          "pads": {"lv2": "urn:sfizz", "pads": "urn:sfizz:sfzfile"}, "comp": {"lua": "comp"}}


def keys_lane(*blocks, midi_ch=None, role="keys"):
    return {"id": "p", "paths": [{"id": "k", "input": 3, "tracks": [
        {"role": "main", "name": "G:k", "input": 3, "midi": True, "midi_in": None, "midi_role": role,
         "midi_ch": midi_ch or {"keys": 1}, "level": -2, "out_sel": "1-2", "blocks": list(blocks)}]}]}


def test_un_instrument_emporte_sa_zone_et_son_arpegiateur():
    b = {"id": "o", "type": "organ", "params": {"db16": 5, "zone_lo": 48, "zone_hi": 72, "transpose": -12, "arp": "Up-Down 1/16"}}
    plan = P.build(keys_lane(b), KCAT, KTABLE)
    blocks = plan["tracks"][0]["blocks"]
    assert [x["id"] for x in blocks] == ["o~zone", "o~arp", "o"]          # la zone, puis l'arp, puis l'instrument
    zone = {p["label"]: p["value"] for p in blocks[0]["params"]}
    assert zone == {"Zone Low": 48, "Zone High": 72, "Transpose": -12} and blocks[0]["shadow"] is True
    arp = {p["label"]: p["value"] for p in blocks[1]["params"]}
    assert arp == {"On": 1, "Rate": 4, "Mode": 3, "Octaves": 0, "Length": 0.7} and blocks[1]["bpm"] == "BPM"
    # la registration part en MIDI, rien de tout cela n'est un port du plugin ni un refus
    assert blocks[2]["params"] == [] and blocks[2]["midi"][0] == [0xB0, 70, 127 - 79]
    assert [s for s in plan["skipped"] if s.get("id")] == []     # (le seul refus : aucun clavier branché, dit par la lane)
    off = P.build(keys_lane({"id": "o", "type": "organ", "params": {"arp": "Off"}}), KCAT, KTABLE)["tracks"][0]["blocks"][1]
    assert off["params"][0] == {"pid": "arp", "label": "On", "value": 0}


def test_la_registration_de_l_orgue_suit_la_table_de_b3_ctl():
    from bridge.engine import keys_midi as K
    cc = {c: v for _, c, v in K.organ_cc({"db16": 8, "db8": 0, "leslie": "fast", "vibrato": "C3", "perc": True,
                                          "perc_harm": "2nd", "drive": True, "character": 100})}
    assert cc[70] == 0 and cc[72] == 127                       # tirettes inversées : tirée = 0, rentrée = 127
    assert cc[1] == 110 and cc[95] == 80 and cc[92] == 5 * 23 + 11 and cc[80] == 127 and cc[83] == 0
    assert cc[65] == 127 and cc[93] == 127
    assert 92 not in {c for _, c, _ in K.organ_cc({"vibrato": "off"})}     # coupé : seul le routage part (CC95 = 0)


def test_la_voix_du_dx7_est_depliee_de_la_cartouche(tmp_path):
    from bridge.engine import keys_midi as K
    voice = bytearray(128)
    voice[11] = 0b1110                                         # opérateur 6 : courbe gauche 2, droite 3
    voice[12] = (9 << 3) | 5                                   # detune 9, rate scaling 5
    voice[15] = (17 << 1) | 1                                  # coarse 17, mode fixe
    voice[110], voice[111], voice[116] = 21, 0b1011, (5 << 4) | (3 << 1) | 1
    voice[118:128] = b"GOLEM TEST"
    bank = bytes([0xF0, 0x43, 0x00, 0x09, 0x20, 0x00]) + bytes(128) + bytes(voice) + bytes(128 * 30) + bytes([0, 0xF7])
    syx = K.dx7_voice_sysex(bank, 1)
    assert len(syx) == 163 and syx[:6] == [0xF0, 0x43, 0, 0, 1, 0x1B] and syx[-1] == 0xF7
    d = syx[6:-2]
    assert d[11:13] == [2, 3] and d[13] == 5 and d[20] == 9 and d[17:19] == [1, 17]
    assert d[134:137] == [21, 3, 1] and d[141:144] == [1, 3, 5] and bytes(d[145:155]) == b"GOLEM TEST"
    assert (sum(d) + syx[-2]) & 0x7F == 0                       # somme de contrôle du DX7
    f = tmp_path / "c.syx"
    f.write_bytes(bank)
    blk = P.build(keys_lane({"id": "e", "type": "ep", "dx7_bank": str(f), "dx7_patch": 1, "params": {"bank": "c", "patch": 1}}),
                  KCAT, KTABLE)["tracks"][0]["blocks"][-1]
    assert blk["midi"] == [syx] and blk["params"] == []
    with pytest.raises(ValueError):
        K.dx7_voice_sysex(b"\x00" * 4104, 0)


def test_l_etat_de_vital_devient_un_preset_vst3(tmp_path, monkeypatch):
    import base64
    comp = b"VstW" + bytes(range(64))
    (tmp_path / "x.vital.b64").write_text(base64.b64encode(b"\x00" * 8 + comp + b"\x00" * 8).decode())
    plan = P.build(keys_lane({"id": "v 1", "type": "vital", "vital_chunk": "x.vital.b64", "params": {"preset": "P", "vol": 0.5}}),
                   KCAT, KTABLE)
    blk = plan["tracks"][0]["blocks"][-1]
    assert blk["preset"] == {"chunk": "x.vital.b64", "vendor": "V", "name": "Vital", "uid": "ABABABABABABABABABABABABABABABAB"}
    assert [p["pid"] for p in blk["params"]] == ["vol"]         # `preset` n'est pas un port : il ne part ni ne se refuse
    monkeypatch.setattr(A, "preset_dir", lambda vendor, name: str(tmp_path / vendor / name))
    A.write_presets(plan, chunk_dir=str(tmp_path))
    out = blk["preset"]
    assert out["uri"].startswith("VST3-S:ABABABABABABABABABABABABABABABAB:golem-v") and len(out["sig"]) == 16
    data = (tmp_path / "V" / "Vital" / (out["uri"].rsplit(":", 1)[1] + ".vstpreset")).read_bytes()
    assert data[:4] == b"VST3" and data[8:40] == b"ABABABABABABABABABABABABABABABAB" and data[48:48 + len(comp)] == comp and b"List" in data[-28:]
    # un état illisible est dit et retiré : le synthé garde son son par défaut
    bad = P.build(keys_lane({"id": "v", "type": "vital", "vital_chunk": "absent.b64", "params": {}}), KCAT, KTABLE)
    A.write_presets(bad, chunk_dir=str(tmp_path))
    assert "preset" not in bad["tracks"][0]["blocks"][-1]


def test_les_pads_sont_un_kit_sfz(tmp_path):
    pads = {"id": "pd", "type": "pads", "params": {"kit": "k"}, "kit_pads": [
        {"note": 36, "file": "/s/kick.wav", "mode": "oneshot", "level": 0}, {"note": 38, "file": "/s/sn.wav", "mode": "gate", "level": -3},
        {"note": 40, "file": "/s/lp.wav", "mode": "toggle", "level": 0}]}
    plan = P.build(keys_lane(pads, midi_ch={"keys": 1, "pads": 10}, role="keys-pads"), KCAT, KTABLE)
    tr = plan["tracks"][0]
    assert tr["midi"]["channel"] == 10                          # un kit de pads seul n'écoute que le canal des pads
    text = tr["blocks"][0]["write"]["text"]
    assert "<region> sample=/s/kick.wav key=36 volume=0 loop_mode=one_shot" in text
    assert "<region> sample=/s/sn.wav key=38 volume=-3\n" in text
    assert [s["why"] for s in plan["skipped"] if s.get("id")] == ["pad 40: toggle plays as a one-shot on this engine"]
    A.write_content(plan, "patch:x", out_dir=str(tmp_path))
    path = tr["blocks"][0]["files"]["urn:sfizz:sfzfile"]
    assert open(path).read() == text and "write" not in tr["blocks"][0]


def test_une_lane_a_deux_instruments_est_depliee():
    organ = {"id": "o", "type": "organ", "params": {}}
    pads = {"id": "pd", "type": "pads", "params": {}, "kit_pads": []}
    plan = P.build(keys_lane(organ, pads, {"id": "c", "type": "comp"}, midi_ch={"keys": 1, "pads": 10}, role="keys-pads"),
                   KCAT, KTABLE)
    tr = {t["name"]: t for t in plan["tracks"]}
    assert list(tr) == ["G:k#merge", "G:k/o", "G:k/pd"]
    merge = tr["G:k#merge"]
    assert merge["kind"] == "bus" and merge["from"] == ["G:k/o", "G:k/pd"] and merge["out"] == [1, 2]
    assert merge["gain_db"] == -2 and merge["mixer"] == "in3" and [b["id"] for b in merge["blocks"]] == ["c"]
    assert tr["G:k/o"]["kind"] == "midi" and tr["G:k/o"]["midi"]["channel"] == 1 and tr["G:k/o"]["out"] is None
    assert [b["id"] for b in tr["G:k/o"]["blocks"]] == ["o~zone", "o~arp", "o"]
    assert tr["G:k/pd"]["midi"]["channel"] == 10
    # un seul instrument : la lane reste une piste, sur le canal des touches
    one = P.build(keys_lane(organ, {"id": "c", "type": "comp"}, midi_ch={"keys": 1, "pads": 10}, role="keys-pads"), KCAT, KTABLE)
    assert [t["name"] for t in one["tracks"]] == ["G:k"] and one["tracks"][0]["midi"]["channel"] == 1


def test_un_bloc_de_service_joue_quand_sa_fonction_est_declaree_et_un_bloc_midi_toujours(monkeypatch):
    eng = A.ArdourEngine(link=object())
    caps = {"recording": "yes", "looper": "no", "standards": "planned"}
    monkeypatch.setattr(eng, "descriptor", lambda: {"name": "Golem Engine", "capabilities": caps})
    assert eng.plays("rec") is True                      # pas de plugin dans la table : sa fonction le porte
    assert eng.plays("looper") is False and eng.plays("standard") is False
    assert eng.plays("whammy-dt") is True                # joué par le bridge (MIDI matériel) : sur tous les moteurs
    assert eng.plays("amp-nam") is True and eng.plays("stretch") is False
    blk, skipped = P.plan_block({"id": "w", "type": "whammy-dt"}, {"whammy-dt": {"type": "whammy-dt", "engine": "midi"}}, TABLE)
    assert blk is None and skipped == []                 # rien à poser dans le moteur, et rien à signaler


def test_la_table_de_boucles_dit_quelle_entree_nourrit_quelle_paire():
    rig = {"id": "p", "paths": [{"id": "guitar-1", "input": 2, "tracks": [{"role": "main", "name": "GoleM:p", "input": 2, "blocks": [], "out": 1}]}]}
    assert "looper" not in P.build(rig, catalog={}, table={})                       # pas de looper dans le preset
    rig["looper"] = {"enabled": True, "loops": [{"sw": 1, "src": "guitar-1"}, {"sw": 2, "src": "guitar-1"},
                                                {"sw": 3, "src": "k"}, {"sw": 4, "src": "keys-9"}, {"sw": 5, "src": "1"}]}
    # l'ordre des lignes fait la paire ; plusieurs lignes peuvent écouter la même lane ; une lane absente : None ; 4 au plus
    assert P.build(rig, catalog={}, table={})["looper"] == {"loops": [{"input": 2}, {"input": 2}, {"input": 3}, {"input": None}]}
    rig["looper"] = {"enabled": True}                                               # sans table : le défaut 1 / 2 / k
    assert P.build(rig, catalog={}, table={})["looper"] == {"loops": [{"input": 1}, {"input": 2}, {"input": 3}]}
    rig["looper"] = None
    assert "looper" not in P.build(rig, catalog={}, table={})


def test_un_bloc_vst_host_est_planifie_par_le_nom_de_son_plugin():
    b = {"id": "h1", "type": "vst-host", "plugin": "VST3: Fancy Verb (Acme)", "foot": 7, "bypass": True,
         "knobs": [{"i": 3, "name": "Decay"}, {"i": 8, "name": "Mix"}, {"i": "x"}, {"i": True}],
         "params": {"p3": 0.4, "p8": 7, "p9": 0.2, "_vst_chunk": "AAAA"}}
    blk, skipped = P.plan_block(b, {}, {})
    assert blk["plugin"] == {"host": "VST3: Fancy Verb (Acme)"} and blk["enabled"] is False and blk["foot"] == 7
    # les potards CHOISIS seulement, par rang et par nom, en normalisé borné ; les autres clés ne sont pas des potards
    assert blk["params"] == [{"pid": "p3", "index": 3, "name": "Decay", "norm": 0.4}, {"pid": "p8", "index": 8, "name": "Mix", "norm": 1.0}]
    assert blk["known"] == [{"pid": "p3", "index": 3, "name": "Decay"}, {"pid": "p8", "index": 8, "name": "Mix"}]
    assert skipped == [] and blk["host_state"] == {"chunk": "AAAA", "plugin": "VST3: Fancy Verb (Acme)"}   # son état part avec lui
    blk, skipped = P.plan_block({"id": "h2", "type": "vst-host", "plugin": "CLAP: Thing (Acme)"}, {}, {})
    assert blk is None and skipped[0]["why"] == "only VST3 plugins are hosted on the Golem Engine"
    assert P.plan_block({"id": "h3", "type": "vst-host"}, {}, {})[1][0]["why"] == "no plugin chosen"


# ── le banc du premier usage sur le Golem Engine (trial_engine) : le JUGE, sur un faux moteur ────────────────────────
def _fake_engine(tmp_path, body):
    """Un faux run.sh : il dit « démarré », attend la commande, puis joue `body` (bash ; $OUT = le fichier de résultat)."""
    sh = tmp_path / "run.sh"
    sh.write_text("#!/bin/bash\nROOT=$1\necho 'x démarré. surveille' > $ROOT/presets/.watch.log\n"
                  "while [ ! -f $ROOT/presets/.command.json ]; do sleep 0.05; done\nOUT=$ROOT/presets/.trial.json\n" + body + "\n")
    return str(sh)


# le faux moteur est un script bash : sous Windows `bash` est l'amorce de WSL, rien ne démarre (2026-11-22). Le juge
# lui-même est le même code sur les trois systèmes ; le lanceur Windows (run.py) n'est pas éprouvé par ces deux tests.
bash_engine = pytest.mark.skipif(sys.platform == "win32", reason="the fake engine is a bash script")


@bash_engine
@pytest.mark.parametrize("body, want", [
    ("echo '{\"done\":true,\"stall_ms\":12,\"noise_ms\":3}' > $OUT; sleep 5", (True, None, {"stall_ms": 9, "engine": "golem-engine"})),
    ("echo '{\"done\":true,\"stall_ms\":420,\"noise_ms\":5}' > $OUT; sleep 5",
     (False, "stopped the audio engine for 415 ms when switched on or off", {"stall_ms": 415, "engine": "golem-engine"})),
    ("echo '{\"step\":\"on 2\"}' > $OUT; exit 3", (False, "crashed the audio engine", {"at": "on 2", "engine": "golem-engine"})),
    ("echo '{\"step\":\"off 1\"}' > $OUT; sleep 30", (False, "froze the audio engine", {"at": "off 1", "engine": "golem-engine"})),
])
def test_le_banc_du_golem_engine_juge_gel_plantage_et_trou(tmp_path, monkeypatch, body, want):
    from bridge import plugin_trial as T
    monkeypatch.setattr(T, "FROZEN_S", 0.6)
    assert T.trial_engine("VST3: X (Y)", script=_fake_engine(tmp_path, body)) == want


@bash_engine
def test_le_banc_du_golem_engine_ne_juge_pas_un_plugin_introuvable(tmp_path):
    from bridge import plugin_trial as T
    with pytest.raises(RuntimeError, match="plugin not found"):
        T.trial_engine("VST3: X (Y)", script=_fake_engine(tmp_path, "echo '{\"error\":\"plugin not found\"}' > $OUT; sleep 5"))


def test_un_verdict_par_moteur(tmp_path, monkeypatch):
    from bridge import engine, plugin_trial as T
    monkeypatch.setattr(T, "TRIALS", str(tmp_path / "vst-trials.json"))
    monkeypatch.setattr(T.sys, "platform", "linux")
    monkeypatch.delenv("GOLEM_VST_TRIAL", raising=False)
    T._record("VST3: X (Y)", True)                                       # essayé sous le moteur du moment (pas Ardour)
    assert T.verdict("VST3: X (Y)")["ok"] is True and not T.pending("VST3: X (Y)")
    prev = engine.use(A.ArdourEngine(link=object()))
    try:
        assert T.pending("VST3: X (Y)") is True                          # le verdict de REAPER ne vaut pas ici
        T._record("VST3: X (Y)", False, "froze the audio engine")
        assert T.failed("VST3: X (Y)") == "froze the audio engine"
    finally:
        engine.use(prev)
    assert T.failed("VST3: X (Y)") is None                               # et celui d'ici ne refuse rien sous REAPER
    assert sorted(json.loads((tmp_path / "vst-trials.json").read_text())) == ["VST3: X (Y)", "golem-engine|VST3: X (Y)"]


def test_une_capture_pilotable_est_planifiee_pour_le_lecteur_lv2(tmp_path):
    import base64
    table = P.load_table()
    chunk = tmp_path / "abc.b64"
    chunk.write_bytes(base64.b64encode(json.dumps({"bundle": {"format": "golem-capture-1"}}).encode()))
    b = {"id": "cap", "type": "capture-module", "capture_chunk": str(chunk), "capture_values": [0.25, 1.0, 7], "foot": 6}
    blk, skipped = P.plan_block(b, {}, table)
    assert skipped == [] and blk["plugin"] == {"lv2": "https://golem.fm/lv2/capture"} and blk["foot"] == 6
    # les valeurs normalisées, dans l'ordre des contrôles de la capture, bornées, sur « Control NN »
    assert blk["params"] == [{"pid": "c0", "label": "Control 01", "value": 0.25}, {"pid": "c1", "label": "Control 02", "value": 1.0},
                             {"pid": "c2", "label": "Control 03", "value": 1.0}]
    plan = {"tracks": [{"blocks": [blk]}]}
    A.write_captures(plan)                                              # l'adaptateur : le JSON que lit le LV2
    out = str(tmp_path / "abc.json")
    assert blk["files"] == {"https://golem.fm/lv2/capture#bundle": out} and "capture" not in blk
    assert json.loads(open(out).read()) == {"bundle": {"format": "golem-capture-1"}}
    assert P.plan_block({"id": "x", "type": "capture-module"}, {}, table)[1][0]["why"] == "capture file missing"


def test_l_etat_natif_d_un_plugin_va_et_vient_au_format_du_patch(tmp_path, monkeypatch):
    import base64
    comp, ctrl = b"C" * 300, b"K" * 20
    raw = A.reaper_vst3_chunk(comp, ctrl)
    assert A.reaper_vst3_parts(raw) == (comp, ctrl) and A.reaper_vst3_parts(raw + b"x") is None and A.reaper_vst3_parts(b"abc") is None
    uid = "ABCDEF0123456789ABCDEF0123456789"
    assert A.read_vstpreset(A.vstpreset(uid, comp, ctrl)) == (uid, comp, ctrl)
    assert A.read_vstpreset(A.vstpreset(uid, comp)) == (uid, comp, b"")
    assert A._legal('Acme: FX/2 .') == "Acme_ FX_2"
    # le plan : l'état écrit comme preset du plugin, là où le moteur le lira ; le bloc reçoit son uri
    monkeypatch.setattr(A, "preset_dir", lambda vendor, name: str(tmp_path / vendor / name))
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / ".vst-host-list.json").write_text(json.dumps({"plugins": [
        {"name": "VST3: Fancy Verb (Acme)", "ident": uid, "vendor": "Acme", "pname": "Fancy Verb"}]}))
    blk = {"id": "h1", "host_state": {"chunk": base64.b64encode(raw).decode(), "plugin": "VST3: Fancy Verb (Acme)"}}
    A.write_host_states({"tracks": [{"blocks": [blk]}]}, presets_dir=str(tmp_path / "p"))
    f = tmp_path / "Acme" / "Fancy Verb" / "golem-h1.vstpreset"
    assert blk["preset"]["uri"] == f"VST3-S:{uid}:golem-h1" and "host_state" not in blk and A.read_vstpreset(f.read_bytes())[1:] == (comp, ctrl)
    # la capture : le preset que le moteur vient d'écrire -> l'état du patch, et le fichier est retiré
    (tmp_path / "Acme" / "Fancy Verb" / "golem-state-7.vstpreset").write_bytes(A.vstpreset(uid, b"NEW", b""))
    chunk = A.host_state_chunk({"preset_label": "golem-state-7", "vendor": "Acme", "pname": "Fancy Verb"})
    assert A.reaper_vst3_parts(base64.b64decode(chunk)) == (b"NEW", b"") and not (tmp_path / "Acme" / "Fancy Verb" / "golem-state-7.vstpreset").exists()
    # un état qui n'est pas celui d'un VST3, un plugin inconnu de l'inventaire : pas de preset, le plugin garde son défaut
    blk = {"id": "h2", "host_state": {"chunk": base64.b64encode(b"junk").decode(), "plugin": "VST3: Fancy Verb (Acme)"}}
    A.write_host_states({"tracks": [{"blocks": [blk]}]}, presets_dir=str(tmp_path / "p"))
    assert "preset" not in blk


@pytest.mark.parametrize("platform, tail", [
    ("linux", (".vst3", "presets", "Vendor", "Synth")),
    ("darwin", ("Library", "Audio", "Presets", "Vendor", "Synth")),
    ("win32", ("Docs", "VST3 Presets", "Vendor", "Synth")),
])
def test_le_dossier_des_presets_vst3_est_celui_qu_ardour_lit_sur_chaque_systeme(monkeypatch, platform, tail):
    # VST3PluginInfo::preset_search_path : sous Windows, Documents\VST3 Presets (le dossier Documents que Windows dit)
    import os
    monkeypatch.setattr(A.sys, "platform", platform)
    monkeypatch.setattr(A, "_win_documents", lambda: "Docs")
    parts = os.path.normpath(A.preset_dir("Vendor", "Synth")).split(os.sep)
    assert tuple(parts[-len(tail):]) == tail
