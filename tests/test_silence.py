# SPDX-License-Identifier: GPL-3.0-or-later
"""« Why no sound? » (docs/health.md §4.1) : le verdict du plus amont au plus aval, les sondes rejouées à blanc, la
garde du départ, et la route. `.venv/bin/python -m pytest tests/test_silence.py -q`"""
import json

import pytest

from bridge import silence as S



ROOT, MERGE = "Sandbox #Input 1", "Sandbox #merge"


def test_le_verdict_du_plus_amont_au_plus_aval():
    st = {"audio": {"ok": True}}
    peaks = {ROOT: {"inst": -80, "mute": 0, "hw_sends": 0, "sends": 1}, MERGE: {"inst": -80, "mute": 0, "hw_sends": 1, "sends": 0}}
    chunk = {ROOT: {"rec": "REC 1 0 1 0 0 0 0", "mute": None, "hwout": [], "mainsend": None}}
    assert S.verdict({"audio": {"ok": False, "why": "frozen"}}, peaks, chunk, {})["code"] == "card"
    assert S.verdict(st, {}, {}, {})["code"] == "probe"
    v = S.verdict(st, peaks, chunk, {})
    assert v["code"] == "input" and "REC 1 0 1" in v["text"] and v["level"] == "bad"
    assert S.verdict(st, peaks, chunk, {}, waited=False)["text"].endswith("normal when idle.")
    peaks[ROOT]["inst"] = -12
    peaks[MERGE]["hw_sends"] = 0
    assert S.verdict(st, peaks, chunk, {})["code"] == "routing"
    peaks[MERGE]["hw_sends"] = 1
    peaks[MERGE]["inst"] = -14
    v = S.verdict(st, peaks, chunk, {})
    assert v["code"] == "downstream" and v["level"] == "ok", "le signal sort de REAPER : le rig n'y est pour rien"
    peaks[MERGE]["inst"] = -90
    fx = {ROOT + "/A": [{"i": 2, "plugin": "NAM", "files": {"Neural Model": ""}}]}
    v = S.verdict(st, peaks, chunk, fx)
    assert v["code"] == "chain" and "Neural Model is empty" in v["text"] and v["missing"][0]["fx"] == 2
    assert S.verdict(st, peaks, chunk, {})["code"] == "chain"
    peaks[ROOT + "/A"] = {"inst": -20, "mute": 0, "hw_sends": 0, "sends": 1}
    assert S.verdict(st, peaks, chunk, {})["code"] == "merge"


@pytest.fixture
def rack(tmp_path, monkeypatch):
    from bridge import config as C
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    from bridge.state import state
    monkeypatch.setattr(state, "reaper_running", True)
    monkeypatch.setattr(state, "audio", {"ok": True})
    monkeypatch.setattr(S, "_S", {"phase": "idle", "started": None, "seconds": 4.0, "play_until": None, "report": None, "error": None, "at": None})
    return tmp_path


def test_la_chasse_rejoue_les_sondes_et_ecrit_son_rapport(rack, monkeypatch):
    rows = [{"track": "03 Sandbox #Input 1", "instL": -9.0, "instR": -150, "vol_db": 0, "mute": 0, "hw_sends": 0, "sends": 1},
            {"track": "04 Sandbox #Input 1/A", "instL": -70, "instR": -70, "vol_db": 0, "mute": 0, "hw_sends": 0, "sends": 1},
            {"track": "05 Sandbox #merge", "instL": -90, "instR": -90, "vol_db": 0, "mute": 0, "hw_sends": 1, "sends": 0},
            {"track": "MASTER", "instL": -150, "instR": -150, "vol_db": 0, "mute": 0, "hw_sends": 0, "sends": 0}]
    fxd = [{"track": "Sandbox #Input 1/A", "fx": [{"fx": 1, "plugin": "NAM", "params": [{"name": "Neural Model", "disp": ""}]}]}]
    asked = []

    def fake_probe(cmd, out, timeout=6.0):
        asked.append(cmd["action"])
        return {"peaks": json.dumps(rows), "chunkdump": "REC 1 0 1\nMAINSEND 0\n", "dumpfx": json.dumps(fxd)}[cmd["action"]]
    monkeypatch.setattr(S, "_probe", fake_probe)
    rep = S.hunt(seconds=0.2)
    assert rep["verdict"]["code"] == "chain" and "Neural Model is empty" in rep["verdict"]["text"]
    assert [t["name"] for t in rep["tracks"]] == ["Sandbox #Input 1", "Sandbox #Input 1/A", "Sandbox #merge"]
    assert rep["chunk"]["Sandbox #Input 1"]["rec"] == "REC 1 0 1"
    assert asked.count("chunkdump") == 1 and asked.count("dumpfx") == 1 and 1 <= asked.count("peaks") <= S.SAMPLES
    saved = json.load(open(rack / rep["file"], encoding="utf-8"))
    assert saved["verdict"]["code"] == "chain" and "peaks" in saved


def test_le_depart_est_garde(rack, monkeypatch):
    import bridge.reamp as RE
    monkeypatch.setattr(RE, "busy_reason", lambda idle=True: "a take is recording")
    r = S.start()
    assert r["ok"] is False and "a take is recording" in r["why"]
    from bridge.state import state
    monkeypatch.setattr(state, "reaper_running", False)
    monkeypatch.setattr(RE, "busy_reason", lambda idle=True: None)
    assert "REAPER is not running" in S.start()["why"]
    assert S.status()["phase"] == "idle"
    S._set(phase="listening")
    assert S.start()["why"] == "a hunt is already running"
    S.clear()
    assert S.status()["phase"] == "idle"


def test_la_route_lance_puis_rend_le_statut(rack, monkeypatch):
    from bridge import routes_health as R
    monkeypatch.setattr(S, "start", lambda seconds=4.0, waited=True: {"ok": True, "seconds": seconds})
    assert R.silence_act({"seconds": 3}) == {"ok": True, "seconds": 3}
    monkeypatch.setattr(S, "start", lambda seconds=4.0, waited=True: {"ok": False, "why": "not now: a song is playing"})
    assert R.silence_act({}).status_code == 409
    assert R.silence_act({"action": "clear"}) == {"ok": True}
    assert R.silence_status()["phase"] == "idle"
