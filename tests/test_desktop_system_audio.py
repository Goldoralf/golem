# SPDX-License-Identifier: GPL-3.0-or-later
"""Le dashboard et Soundcard d'origine consomment aussi le pilote ASIO desktop."""
import asyncio

from bridge import cards, desktop_audio, inputmap, monitors, routes_system


def _settings():
    return {"platform": "windows", "drivers": ["UMC ASIO Driver", "ASIO4ALL v2"],
            "driver": "UMC ASIO Driver", "input_first": 0, "input_last": 3,
            "output_first": 0, "output_last": 1,
            "sample_rate": 44100, "sample_rate_use": False,
            "buffer_size": 256, "buffer_size_use": False,
            "actual": {"MODE": "ASIO", "IDENT_IN": "ASIO UMC ASIO Driver",
                       "IDENT_OUT": "ASIO UMC ASIO Driver", "SRATE": "48000", "BSIZE": "128",
                       "INPUT_COUNT": 4, "OUTPUT_COUNT": 2,
                       "INPUT_NAMES": ["Mic 1", "Mic 2", "Line 3", "Line 4"],
                       "OUTPUT_NAMES": ["Main L", "Main R"],
                       "INPUT_LATENCY_SAMPLES": 128, "OUTPUT_LATENCY_SAMPLES": 128}}


def test_windows_soundcard_uses_reaper_and_keeps_input_patch_per_driver(monkeypatch):
    for module in (cards, inputmap, routes_system, monitors):
        monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    monkeypatch.setattr(desktop_audio, "_public_actual", lambda: _settings()["actual"])
    monkeypatch.setattr(desktop_audio, "asio_drivers", lambda: _settings()["drivers"])
    sound = routes_system.soundcard()
    assert sound["card"] == {"alsa": "UMC ASIO Driver", "name": "UMC ASIO Driver",
                             "present": True, "backend": "ASIO", "inputs": 4, "outputs": 2,
                             "input_names": ["Mic 1", "Mic 2", "Line 3", "Line 4"],
                             "output_names": ["Main L", "Main R"]}
    assert sound["capture_open"] and sound["playback_open"]
    assert sound["bsize"] == 128
    assert inputmap._card_device() == "asio:UMC ASIO Driver"
    assert inputmap.device_of("ASIO4ALL v2") == "asio:ASIO4ALL v2"
    assert inputmap._card_channels("asio:UMC ASIO Driver") == (4, 2)
    assert cards.connected() == [{"index": 0, "id": "UMC ASIO Driver", "name": "UMC ASIO Driver"}]
    assert monitors._read_latency_ms() == 5.3
    assert sound["latency_source"] == "reaper"


def test_windows_soundcard_does_not_claim_a_closed_driver_is_connected(monkeypatch):
    monkeypatch.setattr(cards.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", lambda: {**_settings(), "actual": None})
    assert cards.connected() == []


def test_reaper_underrun_timestamp_counts_new_events_only(monkeypatch):
    monkeypatch.setattr(monitors.sys, "platform", "win32")
    monkeypatch.setattr(monitors, "_DESKTOP_XRUN", {"stamp": None, "clock": 0, "count": 0})
    events = iter([(0, 100), (0, 102), (101, 104), (101, 106), (105, 108)])
    monkeypatch.setattr(desktop_audio, "_public_actual", lambda:
                        dict(zip(("AUDIO_XRUN_TIME", "XRUN_CLOCK"), next(events))))
    assert [monitors._read_xruns() for _ in range(5)] == [0, 0, 1, 1, 2]


def test_dashboard_buffer_uses_desktop_apply_instead_of_linux_ini(monkeypatch):
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    requests = []
    monkeypatch.setattr(desktop_audio, "start_apply", lambda request:
                        requests.append(request) or {"phase": "starting"})
    result = asyncio.run(routes_system.audio_buffer({"size": 2048}))
    assert result["ok"] and result["apply"]["phase"] == "starting"
    assert requests == [{"sample_rate": 44100, "sample_rate_use": False,
                         "buffer_size": 2048, "buffer_size_use": True,
                         "driver": "UMC ASIO Driver", "input_first": 0, "input_last": 3,
                         "output_first": 0, "output_last": 1}]


def test_desktop_restart_explicitly_starts_an_offline_backend(monkeypatch):
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    requests = []
    def apply(request, *, ensure_running=False):
        requests.append(ensure_running)
        return {"phase": "starting"}
    monkeypatch.setattr(desktop_audio, "start_apply", apply)
    assert asyncio.run(routes_system.reaper_restart())["restarting"]
    assert requests == [True]


def test_mac_din_role_never_enumerates_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(inputmap.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_audio.C, "reaper_resource_dir", lambda: str(tmp_path))
    (tmp_path / "reaper.ini").write_text("[REAPER]\ncoreaudioindevnew=Interface\n", encoding="utf-8")
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    (tmp_path / "coreaudio-Interface.json").write_text('{"midi_in":"fcb"}', encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("Device enumeration in MIDI handler")
    monkeypatch.setattr(desktop_audio, "coreaudio_devices", forbidden)
    monkeypatch.setattr(desktop_audio, "settings", forbidden)
    assert [inputmap.din_role("midi_in") for _ in range(5)] == ["fcb"] * 5


def test_mac_map_tracks_actual_channel_growth_without_erasing_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(inputmap.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_audio, "configured_coreaudio_input", lambda: "Interface")
    counts = {"MODE": "CoreAudio", "INPUT_COUNT": 4, "OUTPUT_COUNT": 8}
    monkeypatch.setattr(desktop_audio, "_public_actual", lambda: counts)
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    seeded = inputmap._load()
    assert len(seeded["inputs"]) == 4
    assert len(seeded["outputs"]) == 4
    seeded["inputs"][0]["role"] = "voice"
    inputmap._save(seeded)
    counts.update(INPUT_COUNT=6, OUTPUT_COUNT=10)
    refreshed = inputmap._load()
    assert len(refreshed["inputs"]) == 6
    assert len(refreshed["outputs"]) == 5
    assert refreshed["inputs"][0]["role"] == "voice"


def test_desktop_growth_preserves_stereo_inputs_and_split_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(inputmap.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    inputmap._save({"card": "asio:UMC ASIO Driver",
                   "inputs": [{"ch": "1-2", "role": "keys"}, {"ch": "3", "role": "voice"}],
                   "outputs": [{"ch": "1", "role": "monitors"}, {"ch": "2", "role": "other"}]})
    for _ in range(2):
        current = inputmap._load()
        assert [item["ch"] for item in current["inputs"]] == ["1-2", "3", "4"]
        assert [item["ch"] for item in current["outputs"]] == ["1", "2"]


def test_desktop_dashboard_exposes_all_buffer_sizes_and_nominal_latency(monkeypatch):
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    monkeypatch.setattr(desktop_audio, "_public_actual", lambda: _settings()["actual"])
    monkeypatch.setattr(routes_system, "_git", lambda *args: "")
    monkeypatch.setattr(routes_system, "load_presets", lambda: [])
    monkeypatch.setattr(routes_system, "_read_json", lambda *args: {})
    monkeypatch.setattr(routes_system._serial, "plate", lambda: {})
    dashboard = routes_system.system()
    assert dashboard["audio_bsize"] == 128
    assert dashboard["audio_bsizes"] == list(desktop_audio.BUFFER_SIZES)
    assert dashboard["audio_latency_ms"] == 5.3
    assert dashboard["audio_latency_source"] == "reaper"
    assert dashboard["audio_srate"] == 48000
    assert desktop_audio.nominal_latency_ms({"SRATE": "0", "BSIZE": "128"}) is None
    assert desktop_audio.latency_ms({"SRATE": "48000", "BSIZE": "128",
                                     "INPUT_LATENCY_SAMPLES": 0,
                                     "OUTPUT_LATENCY_SAMPLES": 0}) == (5.3, "nominal")


def test_linux_cpu_boost_is_not_offered_on_macos(monkeypatch):
    monkeypatch.setattr(routes_system.sys, "platform", "darwin")
    assert routes_system.apply_perf(True)[0] is False
    response = asyncio.run(routes_system.perf_mode({"on": True}))
    assert response.status_code == 501


def test_windows_cpu_boost_is_the_performance_power_plan(monkeypatch):
    """Windows (2026-10-03) : le boost bascule le plan d'alimentation — sans sudo, sans toucher au vrai
    plan du poste pendant les tests (desktop_power.set_boost est remplacé)."""
    from bridge import desktop_power
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(desktop_power, "set_boost", lambda on: (calls.append(on), (True, "power plan: Performance"))[1])
    assert routes_system.apply_perf(True) == (True, "power plan: Performance") and calls == [True]
    rows = [{"guid": "a", "name": "Silent", "active": True}, {"guid": "b", "name": "Performance", "active": False},
            {"guid": desktop_power.HIGH_PERF, "name": "High performance", "active": False}]
    assert desktop_power.performance_scheme(rows)["guid"] == "b"                    # le plan du fabricant d'abord
    assert desktop_power.performance_scheme(rows[:1] + rows[2:])["guid"] == desktop_power.HIGH_PERF


def test_windows_health_reads_reaper_tasklist_without_linux_proc(monkeypatch):
    from subprocess import CompletedProcess
    from bridge import rigstatus
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(rigstatus, "cpu_pct", lambda: 12.5)
    monkeypatch.setattr(rigstatus, "temp_c", lambda: None)
    monkeypatch.setattr(rigstatus, "ram", lambda: {"total_mb": 32768, "used_pct": 40})
    monkeypatch.setattr(routes_system.subprocess, "run", lambda *args, **kwargs:
                        CompletedProcess(args[0], 0, b'"reaper.exe","1234","Console","1","123,456 K"\r\n'))
    health = routes_system.system_health()
    assert health["cpu_pct"] == 12.5
    assert health["reaper"] == {"running": True, "pid": 1234, "rss_mb": 121, "uptime_s": None}


def test_desktop_dashboard_actions_leave_event_loop_responsive(monkeypatch):
    import threading
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    entered, release = threading.Event(), threading.Event()
    def blocking_apply(*args, **kwargs):
        entered.set()
        assert release.wait(2), "Dashboard action blocked the event loop"
        return {"phase": "starting"}
    monkeypatch.setattr(desktop_audio, "start_apply", blocking_apply)
    async def check(action):
        entered.clear()
        release.clear()
        task = asyncio.create_task(action())
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            release.set()
            assert (await task)["ok"]
        finally:
            release.set()
            await task
    asyncio.run(check(lambda: routes_system.audio_buffer({"size": 128})))
    asyncio.run(check(routes_system.reaper_restart))
