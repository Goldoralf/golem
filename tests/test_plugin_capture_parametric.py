# SPDX-License-Identifier: GPL-3.0-or-later
"""Les positions apprises, celles qu'on n'a jamais apprises et les réglages NAM exportés."""
import json
import math
from pathlib import Path
import subprocess

import pytest

from bridge import plugin_capture as P, plugin_capture_parametric as K


PARAMS = [{"i": 3, "name": "Gain", "value": 0.4, "display": "4.0"},
          {"i": 7, "name": "Bass", "value": 0.5, "display": "5.0"},
          {"i": 8, "name": "FX Section Active", "value": 0, "toggle": True},
          {"i": 9, "name": "Delay Mix", "value": 0},
          {"i": 10, "name": "Master", "value": 0.6}]
RECIPE = {"vendor": "Test", "full": {"gear": "amp", "off": {"Master": "max"}}}
SPEC = {"controls": [{"i": 3, "min": 0.1, "max": 0.9}, {"i": 7, "min": 0, "max": 1}],
        "samples": 8, "validation": 2, "seed": 41}


@pytest.fixture(autouse=True)
def isolated_job(monkeypatch):
    monkeypatch.setattr(P, "_job", {"state": "idle"})
    P._cancel.clear()
    yield
    P._cancel.clear()


def test_plan_is_deterministic_joint_and_has_disjoint_unseen_settings():
    a = K.plan(SPEC, PARAMS, RECIPE)
    assert a == K.plan(SPEC, PARAMS, RECIPE)
    train = [p["values"] for p in a["points"] if p["split"] == "train"]
    validation = [p["values"] for p in a["points"] if p["split"] == "validation"]
    assert len(train) == 8 and len(validation) == 2
    assert {"Gain": 0.1, "Bass": 0} in train
    assert {"Gain": 0.9, "Bass": 1} in train
    assert {"Gain": 0.4, "Bass": 0.5} in train
    assert not any(p in train for p in validation)
    for p in train + validation:
        assert 0.1 <= p["Gain"] <= 0.9 and 0 <= p["Bass"] <= 1
    assert len({tuple(p.values()) for p in train + validation}) == 10


@pytest.mark.parametrize("change", [
    {"controls": []}, {"controls": [{"i": 8}]}, {"controls": [{"i": 9}]}, {"controls": [{"i": 10}]},
    {"controls": [{"i": -1}]}, {"controls": [{"i": True}]}, {"controls": [{"i": 3.2}]},
    {"controls": [{"i": 3}, {"i": 3}]}, {"controls": [{"i": 3, "min": 0.9, "max": 0.1}]},
    {"controls": [{"i": 3, "max": float('nan')}]}, {"controls": [{"i": 3, "min": -1}]},
    {"samples": 2}, {"samples": 3.5}, {"samples": 500}, {"validation": 0}, {"seed": -1},
])
def test_bad_plans_never_launch_a_render(change):
    with pytest.raises(ValueError):
        K.plan({**SPEC, **change}, PARAMS, RECIPE)


def test_stepped_or_ambiguous_parameters_cannot_be_trained_as_continuous():
    with pytest.raises(ValueError):
        K.plan(SPEC, [{**p, "step": 0.5} for p in PARAMS], RECIPE)
    with pytest.raises(ValueError, match="uniquely named"):
        K.plan(SPEC, [{**p, "name": "Gain"} if p["i"] == 7 else p for p in PARAMS], RECIPE)


@pytest.fixture
def audio(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "train_home", lambda: tmp_path)
    monkeypatch.setattr(P, "SR", 1000)
    P.write_wav(tmp_path / "v3_0_0.wav", [0.2 * math.sin(i * 0.13) for i in range(90000)], 1000)
    monkeypatch.setattr(P, "V3_MD5", __import__("hashlib").md5((tmp_path / "v3_0_0.wav").read_bytes()).hexdigest())
    calls = []
    def render(plugin, chunk, off, source, work, name, controls=None):
        calls.append((plugin, chunk, dict(off), controls))
        x, sr = P.read_wav(source)
        gain = 0.5 + controls[0]["value"]
        P.write_wav(work / "target.wav", [v * gain for v in x], sr)
        return {"peak": 0.3, "set": [], "controls": {p["i"]: p["value"] for p in controls}}
    monkeypatch.setattr(P, "render", render)
    return tmp_path, calls


def test_acquire_preserves_levels_and_resumes_only_complete_verified_renders(audio):
    base, calls = audio
    work = base / "work"
    pl = K.plan(SPEC, PARAMS, RECIPE)
    data = K.acquire(work, "Test VST", {"chunk": "fixed native state"}, RECIPE, pl)
    assert len(calls) == 10
    assert all(c[1] == "fixed native state" and c[2] == {"Master": "max"} for c in calls)
    assert len(data["train"]) == 8 and len(data["validation"]) == 2
    assert data["train"][0]["x_path"] != data["validation"][0]["x_path"]
    peaks = [json.loads((work / p["id"] / "render.json").read_text())["peak"] for p in pl["points"]]
    assert len(peaks) == 10
    targets = [max(abs(v) for v in P.read_wav(Path(p["y_path"]))[0]) for p in data["train"]]
    assert max(targets) > 2 * min(targets)  # un nivellement indépendant détruirait le gain appris
    assert K.acquire(work, "Test VST", {"chunk": "fixed native state"}, RECIPE, pl) == data
    assert len(calls) == 10
    Path(data["train"][0]["y_path"]).write_bytes(b"interrupted write")
    K.acquire(work, "Test VST", {"chunk": "fixed native state"}, RECIPE, pl)
    assert len(calls) == 11


def test_acquire_refuses_unverified_values_and_cancellation(audio, monkeypatch):
    base, _ = audio
    monkeypatch.setattr(P, "render", lambda *a, **k: {"controls": {3: 0.99, 7: 0.5}})
    with pytest.raises(RuntimeError, match="did not keep"):
        K.acquire(base / "unsettled", "VST", {"chunk": "C"}, RECIPE, K.plan(SPEC, PARAMS, RECIPE))
    P._cancel.set()
    with pytest.raises(RuntimeError):
        K.acquire(base / "cancelled", "VST", {"chunk": "C"}, RECIPE, K.plan(SPEC, PARAMS, RECIPE))


def test_control_render_is_checked_again_after_the_plugin_restores_state(tmp_path):
    from lupa import LuaRuntime
    lua = LuaRuntime()
    trace = tmp_path / "trace.txt"
    lua.execute('''
      current, clock = 0.2, 0
      reaper = {
        CountTracks=function() return 0 end, InsertTrackAtIndex=function() end, GetTrack=function() return {} end,
        SetOnlyTrackSelected=function() end, SetEditCurPos=function() end, InsertMedia=function() return 1 end,
        GetTrackMediaItem=function() return {} end, GetMediaItemInfo_Value=function() return 2 end,
        TrackFX_AddByName=function() return 0 end, TrackFX_SetNamedConfigParm=function() return true end,
        TrackFX_GetNumParams=function() return 1 end, TrackFX_GetParamName=function() return true, 'Gain' end,
        TrackFX_SetParamNormalized=function(tr,fx,p,v) current=v end,
        TrackFX_GetParamNormalized=function() return current end,
        GetSetProjectInfo=function() end, GetSetProjectInfo_String=function() end, GetSet_LoopTimeRange=function() end,
        Main_OnCommand=function() rendered=true end,
        time_precise=function() clock=clock+4 return clock end,
        defer=function(f) f() end,
      }
    ''')
    script = P._render_script("VST", "C", {}, tmp_path / "in.wav", tmp_path / "x.rpp", trace,
                              "test", controls=[{"i": 0, "name": "Gain", "value": 0.72}])
    lua.execute(script)
    assert lua.globals().rendered is True
    assert "param 0 0.720000000" in trace.read_text()
    lua.execute("reaper.TrackFX_GetParamNormalized=function() return 0.2 end; rendered=false")
    with pytest.raises(Exception, match="did not settle"):
        lua.execute(script)
    assert lua.globals().rendered is False


def _wave():
    return {"version": "0.7.0", "architecture": "WaveNet", "weights": [0.1],
            "config": {"head_scale": 0.02, "head": None, "layers": [{"input_size": 1, "condition_size": 1,
                "channels": 1, "kernel_sizes": [3], "dilations": [1], "activation": ["Tanh"],
                "gating_mode": ["none"], "head": {"out_channels": 1, "bias": True}}]}}


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    controls = K.plan(SPEC, PARAMS, RECIPE)["controls"]
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P.C, "ROOT", str(tmp_path))
    monkeypatch.setattr(P.C, "ASSET_ROOTS", [str(tmp_path / "assets")])
    monkeypatch.setattr(P.C, "CATALOG", str(tmp_path / "catalog.json"))
    monkeypatch.setattr(K, "environment", lambda: {"ready": True})
    folder = tmp_path / "assets" / "models" / "captures" / "test"
    folder.mkdir(parents=True)
    (folder / "parametric.nam").write_text('{"architecture":"HyperWaveNet"}')
    entry = {"id": "cap-test", "models": [{"id": "default", "file": "assets/models/captures/test/default.nam",
                 "controls": {"Gain": 0.4, "Bass": 0.5}}],
             "parametric": {"controls": controls, "file": "assets/models/captures/test/parametric.nam", "validation": {},
                            "reference_loudness": -18.5}}
    Path(P.C.CATALOG).write_text(json.dumps({"tones": [entry]}))
    return folder


def test_any_in_range_setting_bakes_to_a_portable_model_and_is_cached(catalog, monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append(args)
        folder = Path(args[-1])
        (folder / "model.nam").write_text(json.dumps(_wave()))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(K.subprocess, "run", run)
    values = {"Gain": 0.23456, "Bass": 0.76543}
    result = K.bake("cap-test", values)
    assert result["values"] == values
    assert K.bake("cap-test", values) == result and len(calls) == 1
    cat = json.loads(Path(P.C.CATALOG).read_text())
    model = cat["tones"][0]["models"][-1]
    assert model["id"] == result["model"] and model["controls"] == values
    saved = json.loads((P.ROOT / model["file"]).read_text())
    assert saved["version"] == "0.5.4" and saved["metadata"]["loudness"] == -18.5
    assert K.model_status("cap-test", result["model"])["values"] == values
    assert K.model_file("cap-test") == catalog / "parametric.nam"


@pytest.mark.parametrize("values", [{"Gain": 1, "Bass": 0.5}, {"Gain": 0.5},
    {"Gain": float('inf'), "Bass": 0.5}, {"Gain": 0.5, "Bass": 0.5, "unknown": 0}, None])
def test_bake_refuses_extrapolation_or_missing_controls(catalog, values, monkeypatch):
    monkeypatch.setattr(K.subprocess, "run", lambda *a, **k: pytest.fail("should not execute"))
    with pytest.raises(ValueError):
        K.bake("cap-test", values)


def test_download_rejects_a_catalog_path_outside_assets(catalog):
    cat = json.loads(Path(P.C.CATALOG).read_text())
    cat["tones"][0]["parametric"]["file"] = "../../private.nam"
    Path(P.C.CATALOG).write_text(json.dumps(cat))
    with pytest.raises(ValueError, match="missing"):
        K.model_file("cap-test")


def test_cancelled_worker_never_installs_a_partial_capture(monkeypatch, tmp_path):
    def acquire(*a):
        P._cancel.set()
        P._check_cancel()
    monkeypatch.setattr(K, "acquire", acquire)
    monkeypatch.setattr(K, "install", lambda *a: pytest.fail("partial capture installed"))
    K._worker("b", "VST", "Name", tmp_path, {}, {}, {}, 1)
    assert P.status()["state"] == "cancelled" and P.status()["error"] is None


def test_backup_keeps_the_parametric_source_with_the_playable_snapshots(catalog, tmp_path):
    import zipfile
    from bridge import backup
    entries = []
    archive = tmp_path / "capture.zip"
    cat = json.loads(Path(P.C.CATALOG).read_text())
    cat["tones"][0]["gear"] = "amp"
    Path(P.C.CATALOG).write_text(json.dumps(cat))
    with zipfile.ZipFile(archive, "w") as z:
        backup._add_gear(z, ["amp"], "amps", set(), entries)
    with zipfile.ZipFile(archive) as z:
        assert "assets/models/captures/test/parametric.nam" in z.namelist()


def test_control_capture_routes_require_pairing_and_setup_requires_admin(monkeypatch):
    from bridge import auth
    class Req:
        method = "GET"
        headers = {"host": "192.168.0.22:8770"}
        cookies, query_params = {}, {}
        client = type("C", (), {"host": "192.168.0.25"})()
        url = type("U", (), {"path": "/api/vst-host/capture/parametric/download", "hostname": "192.168.0.22"})()
    req = Req()
    monkeypatch.setattr(auth, "_device_by_token", lambda t: None)
    assert not auth.allowed_http(req)
    monkeypatch.setattr(auth, "_device_by_token", lambda t: {"id": "m"})
    assert auth.allowed_http(req)
    req.method = "POST"
    req.url.path = "/api/vst-host/capture/parametric/setup"
    assert not auth.allowed_http(req)
    monkeypatch.setattr(auth, "_device_by_token", lambda t: {"id": "a", "admin": True})
    assert auth.allowed_http(req)


@pytest.mark.parametrize("gear,block_type", [("amp", "amp-nam"), ("amp-cab", "amp"), ("pedal", "pedal-nam")])
def test_finished_worker_installs_the_source_and_selects_a_compatible_default(catalog, monkeypatch, tmp_path, gear, block_type):
    work = tmp_path / "work"
    controls_plan = K.plan(SPEC, PARAMS, RECIPE)
    metrics = {"worst_esr": 0.03, "mean_esr": 0.02, "unseen_settings": []}
    def acquire(*args):
        work.mkdir()
    def run(*args, **kw):
        out = work / "output"
        out.mkdir()
        (out / "model.nam").write_text(json.dumps(_wave()))
        (out / "model_parametric.nam").write_text(json.dumps({"architecture": "HyperWaveNet", "sample_rate": 48000,
            "weights": [0], "version": "1.0.0", "config": {"params": controls_plan["controls"]}}))
        (work / "metrics.json").write_text(json.dumps(metrics))
        return subprocess.CompletedProcess([], 0, "trained", "")
    checks = []
    monkeypatch.setattr(K, "acquire", acquire)
    monkeypatch.setattr(P, "_run", run)
    monkeypatch.setattr(P, "playback_check", lambda *a, **kw: checks.append(kw) or {"ok": True})
    P._set(block="b", mode="parametric", patch="Original patch")
    recipe = {**RECIPE, "full": {**RECIPE["full"], "gear": gear}}
    K._worker("b", "Test VST", "Knob capture", work, controls_plan, recipe, {"chunk": "C"}, 1)
    job = P.status()
    assert job["state"] == "done", job.get("error")
    core = job["result"]["core"][0]
    assert core["type"] == block_type and core["origin"]["mode"] == "parametric"
    assert checks[0]["python_exe"] == K.python()  # pas de dépendance au venv des captures fixes
    entry = K._entry(core["ref"])
    assert entry["capture"]["private"] is True
    assert entry["parametric"]["capture_settings"] == recipe["full"]["off"]
    module = json.loads((P.ROOT / entry["models"][0]["file"]).read_text())
    assert module["format"] == "golem-capture-1" and not module["requires_original_plugin"]
    assert len(entry["capture_module"]["controls"]) == 2
    assert json.loads((P.ROOT / entry["models"][1]["file"]).read_text())["version"] == "0.5.4"
    assert K.model_file(core["ref"]).is_file()
    assert K.model_status(core["ref"], core["model"])["values"] == {"Gain": 0.4, "Bass": 0.5}


def test_retrying_a_bake_recreates_a_missing_cached_file(catalog, monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append(args)
        (Path(args[-1]) / "model.nam").write_text(json.dumps(_wave()))
        return subprocess.CompletedProcess(args, 0, "", "")
    monkeypatch.setattr(K.subprocess, "run", run)
    values = {"Gain": 0.3, "Bass": 0.6}
    first = K.bake("cap-test", values)
    model = next(m for m in K._entry("cap-test")["models"] if m["id"] == first["model"])
    (P.ROOT / model["file"]).unlink()
    assert K.bake("cap-test", values) == first and len(calls) == 2
    assert len(K._entry("cap-test")["models"]) == 2
