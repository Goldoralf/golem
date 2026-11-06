# SPDX-License-Identifier: GPL-3.0-or-later
"""Module unique, scène, contrat MIDI et garde du téléphone — sans trainer ni VST."""
import base64
import copy
import json
from pathlib import Path

import pytest

from bridge import capture_module as M, config as C, resolver, scene_bake, compile_rig, preset_view, store
from bridge import app as A


def bundle():
    model = {"architecture": "HyperWaveNet", "sample_rate": 48000, "weights": [.1], "version": "1.0.0",
             "config": {"params": [{"name": "Drive", "min": .2, "max": .8, "default": .5}]}}
    return M.build("Test capture", [{"id": "od", "name": "Overdrive", "switch": "Overdrive", "model": model}])


@pytest.fixture
def module_rig(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    monkeypatch.setattr(C, "ASSET_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(C, "CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(resolver, "_TONES", {"mtime": None, "idx": None})
    monkeypatch.setattr(compile_rig, "OUT_DIR", str(tmp_path / "plans"))
    monkeypatch.setattr(compile_rig, "ASSET_CACHE", str(tmp_path / "assets/.cache"))
    monkeypatch.setattr(compile_rig, "_FX_DEFS", None)
    monkeypatch.setattr(store, "_imap", lambda: {})
    entry = M.install(bundle())
    block = {"type": "amp", "id": "capture", "ref": entry["id"], "model": entry["models"][0]["id"],
             "capture_foot": {"od_on": 6}, "capture_controls": entry["capture_module"]["controls"]}
    preset = {"id": "module-song", "name": "Capture", "lanes_v": 2,
              "lanes": [{"id": "gtr", "role": "guitar", "in_sel": "1", "out_sel": "1-2", "chain": {"pre": [block]}}],
              "scenes": [{"id": "A", "params": {"capture": {"od_on": 0, "od_drive": .3}}},
                         {"id": "B", "params": {"capture": {"od_on": 1, "od_drive": .7}}}]}
    Path(C.PRESETS_DIR).mkdir()
    Path(C.PRESETS_DIR, "module-song.json").write_text(json.dumps(preset), encoding="utf-8")
    return preset, entry


def test_one_block_survives_compile_with_all_stages_and_no_vst(module_rig):
    preset, entry = module_rig
    original = copy.deepcopy(preset)
    blocks = []
    for scene, expected in [("A", [0, 1 / 6]), ("B", [1, 5 / 6]), ("A", [0, 1 / 6])]:
        baked = scene_bake.to_paths_preset(preset, scene, union=True)
        path = compile_rig.compile_preset(baked)
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
        blocks = [b for p in plan["paths"] for t in p["tracks"] for b in t["blocks"]]
        captured = next(b for b in blocks if b["id"] == "capture")
        assert captured["type"] == "capture-module"
        assert captured["params"]["_capture_values"] == pytest.approx(expected)
        state = json.loads(base64.b64decode(Path(captured["capture_chunk"]).read_bytes()))
        assert state["bundle"]["format"] == M.FORMAT
        assert len(state["bundle"]["stages"]) == 1
    assert preset == original
    assert len([b for b in blocks if b["type"] == "capture-module"]) == 1
    assert not any(b.get("type") == "vst-host" for b in blocks)


@pytest.mark.parametrize("mutation", [
    lambda b: b["controls"][1].update(min=-1),
    lambda b: b["controls"][1].update(default=float("nan")),
    lambda b: b["controls"][0].update(default=.5),
    lambda b: b["stages"][0].update(enable="absent"),
    lambda b: b["stages"][0].update(controls=[]),
    lambda b: b["stages"][0]["model"].update(architecture="OriginalVST"),
])
def test_refuses_invalid_models_ranges_and_switches(mutation):
    data = bundle(); mutation(data)
    with pytest.raises(ValueError):
        M.validate(data)


def test_internal_switch_is_in_the_midi_contract_but_not_the_chain(module_rig):
    preset, _ = module_rig
    physical = [b for b, _ in store.all_blocks(preset) if b.get("id") == "capture"]
    assert len(physical) == 1
    summary = preset_view._foot_summary(preset, {})
    sw = next(s for s in summary["switches"] if s["sw"] == 6)
    assert [b["id"] for b in sw["blocks"]] == ["capture@capture0"]
    assert 6 not in summary["scenes"][0]["on"] and 6 in summary["scenes"][1]["on"]


def test_phone_owns_only_its_lane_and_sees_live_midi_state(module_rig):
    preset, _ = module_rig
    assert not M.owned(preset, "A", "Bass")
    row = M.owned(preset, "A", "Guitar", stomps={6: True})[0]
    assert row["values"] == {"od_on": 1, "od_drive": .3}
    assert len(M.owned(preset, "A", "Guitar")) == 1


def test_phone_writes_the_scene_and_invalidates_stale_designer(module_rig):
    preset, _ = module_rig
    sandbox = Path(C.PRESETS_DIR, ".sandbox.json")
    sandbox.write_text(json.dumps({"preset": preset, "edit_rev": 7, "editor": "rack"}), encoding="utf-8")
    row = M.owned(preset, "A", "Guitar")[0]
    normalized = M.write_values(preset, "A", row, {"od_drive": .6})
    assert normalized == {"1": pytest.approx(2 / 3)}
    saved = json.loads(Path(C.PRESETS_DIR, "module-song.json").read_text(encoding="utf-8"))
    assert saved["scenes"][0]["params"]["capture"]["od_drive"] == .6
    assert saved["scenes"][1]["params"]["capture"]["od_drive"] == .7
    draft = json.loads(sandbox.read_text(encoding="utf-8"))
    assert draft["edit_rev"] == 8 and draft["editor"] == "capture-controls"
    assert draft["preset"]["scenes"][0]["params"]["capture"]["od_drive"] == .6


def test_phone_rejects_extrapolation_before_saving(module_rig):
    preset, _ = module_rig
    path = Path(C.PRESETS_DIR, "module-song.json"); before = path.read_bytes()
    with pytest.raises(ValueError):
        M.write_values(preset, "A", M.owned(preset, "A", "Guitar")[0], {"od_drive": .99})
    assert path.read_bytes() == before


def test_one_scene_phone_edit_sets_the_base_like_the_designer(module_rig):
    preset, _ = module_rig
    preset["scenes"] = preset["scenes"][:1]
    path = Path(C.PRESETS_DIR, "module-song.json")
    path.write_text(json.dumps(preset), encoding="utf-8")
    row = M.owned(preset, "A", "Guitar")[0]
    M.write_values(preset, "A", row, {"od_drive": .6})
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["lanes"][0]["chain"]["pre"][0]["params"]["od_drive"] == .6
    assert "od_drive" not in doc["scenes"][0]["params"]["capture"]


def test_midi_cc_controls_the_internal_switch_via_the_real_dispatcher(module_rig, monkeypatch):
    from bridge import foot, inputmap, diag
    preset, _ = module_rig
    commands = []
    monkeypatch.setattr(A, "load_preset", lambda _: preset)
    monkeypatch.setattr(A, "write_command", commands.append)
    monkeypatch.setattr(diag, "event", lambda *a, **k: None)
    for name, value in {"preset_id": preset["id"], "scene_id": "A", "stomps": {6: False},
                        "sample_switches": {}, "drum_switches": {}, "standard_switches": {}, "arr_switch": None,
                        "looper": {}, "scene_claims": {}, "lane_toggles": {}}.items():
        monkeypatch.setattr(A.state, name, value)
    monkeypatch.setattr(foot, "_DEVICE", {"device_id": "test", "wire_channel": 1, "note_edges": "clean", "note_base": 0, "edge_switches": None})
    monkeypatch.setattr(foot, "_BOUND", {})
    monkeypatch.setattr(foot, "_LEARN", {"on": False})
    monkeypatch.setattr(inputmap, "din_role", lambda _: "fcb")
    reader = foot.FootReader(lambda *_: None, A._do_stomp)
    reader.feed("20:0 Control change 1, controller 30, value 127")
    reader.feed("20:0 Control change 1, controller 30, value 0")
    assert [(c["ids"], c["on"]) for c in commands] == [(["capture@capture0"], True), (["capture@capture0"], False)]
    assert A.state.stomps[6] is False


def test_phone_api_requires_ownership_and_the_current_scene(module_rig, monkeypatch):
    from fastapi.testclient import TestClient
    from bridge import auth, inputmap
    preset, _ = module_rig
    commands = []
    monkeypatch.setattr(A, "load_preset", lambda _: store.load_preset(preset["id"]))
    monkeypatch.setattr(A, "write_command", commands.append)
    monkeypatch.setattr(A.state, "preset_id", preset["id"])
    monkeypatch.setattr(A.state, "scene_id", "A")
    monkeypatch.setattr(A.state, "stomps", {6: False})
    monkeypatch.setattr(A.state, "lane_toggles", {})
    monkeypatch.setattr(inputmap, "current", lambda: {})
    monkeypatch.setattr(auth, "allowed_http", lambda request: True)
    monkeypatch.setattr(auth, "device_of", lambda request: {"role": "Guitar"})
    client = TestClient(A.app)
    assert len(client.get("/api/lane/capture").json()["modules"]) == 1
    body = {"preset": preset["id"], "scene": "A", "block": "capture", "values": {"od_drive": .6}}
    assert client.post("/api/lane/capture", json={**body, "scene": "B"}).status_code == 409
    monkeypatch.setattr(auth, "device_of", lambda request: {"role": "Bass"})
    assert client.get("/api/lane/capture").json()["modules"] == []
    assert client.post("/api/lane/capture", json=body).status_code == 403
    assert not commands
    monkeypatch.setattr(auth, "device_of", lambda request: {"role": "Guitar"})
    result = client.post("/api/lane/capture", json=body)
    assert result.status_code == 200, result.text
    assert commands[-1]["action"] == "capture_params"
    assert commands[-1]["values"] == {"1": pytest.approx(2 / 3)}
    # Un switch partagé avec une AUTRE lane ne donne pas au téléphone le droit de la basculer.
    path = Path(C.PRESETS_DIR, preset["id"] + ".json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["lanes"].append({"id": "vox", "role": "voice", "in_sel": "2", "out_sel": "1-2",
                         "chain": {"pre": [{"id": "voice-chorus", "type": "chorus", "foot": 6}]}})
    path.write_text(json.dumps(doc), encoding="utf-8")
    commands.clear()
    response = client.post("/api/lane/capture", json={**body, "values": {"od_on": 1}})
    assert response.status_code == 200, response.text
    assert [c["action"] for c in commands] == ["capture_params"]
    assert client.get("/api/lane/capture").json()["modules"][0]["values"]["od_on"] == 1


def test_capture_data_is_private_on_the_lan(monkeypatch):
    from types import SimpleNamespace as NS
    from bridge import auth
    monkeypatch.setattr(auth, "_device_by_token", lambda token: None)
    for path in ("/api/lane/capture", "/api/vst-host/capture/module/download"):
        request = NS(method="GET", url=NS(path=path, hostname="192.168.0.22"), client=NS(host="192.168.0.50"),
                     headers={}, cookies={}, query_params={})
        assert not auth.allowed_http(request)
