# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop audio preferences stay isolated from the Linux rack and other REAPER settings."""
import pytest

from bridge import desktop_audio as audio

_REAL_SAVE = audio.save_project_in_place


@pytest.fixture(autouse=True)
def _no_real_save(monkeypatch):
    # sans ça, un test qui ne mocke pas _actual lit le VRAI projet et envoie « Save project » par OSC au
    # REAPER qui tourne sur la machine du développeur
    monkeypatch.setattr(audio, "save_project_in_place", lambda wait=1.0: None)
    # ni le VRAI pilote ASIO de la machine (il peut être tenu par le REAPER qui joue), ni son cache
    monkeypatch.setattr(audio, "probe_asio_if_missing", lambda driver=None: None)


def test_le_projet_nomme_est_enregistre_par_osc_et_jamais_un_projet_sans_chemin(tmp_path, monkeypatch):
    """2026-10-03 : WM_CLOSE sur un projet modifié ouvrait « Save project…? » derrière la coquille."""
    import pythonosc.udp_client as U
    sent = []
    monkeypatch.setattr(U.SimpleUDPClient, "send_message", lambda self, addr, val: sent.append((addr, val)))
    monkeypatch.setattr(audio.time, "sleep", lambda s: None)
    rpp = tmp_path / "golem-set.rpp"
    rpp.write_text("<REAPER_PROJECT>")
    monkeypatch.setattr(audio, "_actual", lambda since=0: {"PROJECT": str(rpp)})
    assert _REAL_SAVE() == str(rpp) and sent == [("/action", 40026)]
    sent.clear()
    from provision import desktop
    monkeypatch.setattr(audio, "_actual", lambda since=0: {"PROJECT": ""})
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "none.rpp")
    # sans chemin : jamais 40026 (« Enregistrer sous » serait une boîte de plus) — l'instantané Lua l'enregistre
    # dans sets/ et le rouvre (2026-11-04 : sinon CHAQUE arrêt laissait « Save project? » ouverte)
    target = tmp_path / "sets" / "golem-set.rpp"
    remembered = []
    monkeypatch.setattr(audio, "_auto_save_target", lambda: target)
    monkeypatch.setattr(desktop, "remember_project", remembered.append)

    def snapshot(save_target=None):
        save_target.parent.mkdir(parents=True, exist_ok=True)
        save_target.write_text("<REAPER_PROJECT>")
        return {"PROJECT": str(save_target), "AUTO_SAVED": True}
    monkeypatch.setattr(audio, "_snapshot_reaper", snapshot)
    assert _REAL_SAVE() == str(target) and sent == [] and remembered == [target]
    monkeypatch.setattr(audio, "_snapshot_reaper", lambda save_target=None: {"PROJECT": "", "AUTO_SAVED": False})
    target.unlink()
    assert _REAL_SAVE() is None and sent == []


def test_le_changement_audio_enregistre_avant_de_fermer(tmp_path, monkeypatch):
    from provision import desktop, desktop_window
    order = []
    monkeypatch.setattr(audio, "save_project_in_place", lambda wait=1.0: order.append("save"))
    monkeypatch.setattr(desktop_window, "request_reaper_close", lambda *_: order.append("close") or 1)
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "missing.rpp")
    monkeypatch.setattr(desktop, "reaper_binary", lambda: tmp_path / "reaper")
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(desktop, "launch_reaper", lambda args: None)
    monkeypatch.setattr(audio, "apply_ini", lambda *a: None)
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    monkeypatch.setattr(audio, "_actual", lambda since=0: None)
    monkeypatch.setattr(audio.time, "sleep", lambda s: None)
    audio._lock.acquire()
    audio._apply_worker("audioconfig", {}, True, {"PROJECT": "", "TRACKS": 0})
    assert order[:2] == ["save", "close"]


def test_windows_input_map_grows_when_reaper_opens_more_channels(tmp_path, monkeypatch):
    import json
    from bridge import inputmap
    monkeypatch.setattr(inputmap.sys, "platform", "win32")
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path))
    monkeypatch.setattr(inputmap, "_card_device", lambda: "asio:UMC ASIO Driver")
    monkeypatch.setattr(inputmap, "_card_channels", lambda device: (4, 4))
    path = tmp_path / "asio-UMC-ASIO-Driver.json"
    path.write_text(json.dumps({"card": "asio:UMC ASIO Driver",
                                "inputs": [{"ch": "1", "role": "guitar"},
                                           {"ch": "2", "role": "voice"}],
                                "outputs": [{"ch": "1-2", "role": "monitors"}]}))
    loaded = inputmap._load()
    assert [item["ch"] for item in loaded["inputs"]] == ["1", "2", "3", "4"]
    assert [item["ch"] for item in loaded["outputs"]] == ["1-2", "3-4"]
    assert loaded["inputs"][1]["role"] == "voice"
    assert inputmap._load() == loaded


def test_live_audio_snapshot_retries_a_partial_lua_write(tmp_path, monkeypatch):
    path = tmp_path / "desktop-audio.json"
    path.write_text('{"MODE":"ASIO"}', encoding="utf-8")
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    read = audio.Path.read_text
    calls = []
    def interrupted(self, *args, **kwargs):
        if self == path and not calls:
            calls.append(True)
            return '{"MODE":'
        return read(self, *args, **kwargs)
    monkeypatch.setattr(audio.Path, "read_text", interrupted)
    monkeypatch.setattr(audio.time, "sleep", lambda *_: None)
    assert audio._actual() == {"MODE": "ASIO"}


def test_windows_snapshot_asks_the_running_script_without_spawning_reaper(tmp_path, monkeypatch):
    from provision import desktop
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    monkeypatch.setattr(desktop, "launch_reaper", lambda *args, **kwargs:
                        (_ for _ in ()).throw(AssertionError("second REAPER instance")))
    original = audio.Path.write_text
    def respond(self, content, *args, **kwargs):
        result = original(self, content, *args, **kwargs)
        if self.name == "desktop-audio-snapshot-request.txt":
            original(tmp_path / "desktop-audio-snapshot.json",
                     '{"PROJECT":"C:/sets/golem-set.rpp","TRACKS":4}', encoding="utf-8")
        return result
    monkeypatch.setattr(audio.Path, "write_text", respond)
    assert audio._snapshot_reaper() == {"PROJECT": "C:/sets/golem-set.rpp", "TRACKS": 4}


def test_asio_apply_reports_when_driver_ignores_requested_buffer(tmp_path, monkeypatch):
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))   # la taille refusée s'y note
    updates = {"asio_driver_name": '"UMC ASIO Driver"', "asio_srate": "48000",
               "asio_srate_use": "1", "asio_bsize": "256", "asio_bsize_use": "1",
               "asio_input0": "0", "asio_input1": "1", "asio_output0": "0", "asio_output1": "1"}
    actual = {"MODE": "ASIO", "IDENT_IN": "ASIO UMC ASIO Driver", "SRATE": "48000", "BSIZE": "128"}
    msg = audio._verify_actual("audioconfig", updates, actual)
    assert msg.startswith("UMC ASIO Driver kept its own buffer (128 samples instead of 256)")
    assert "ASIO Configuration" in msg                                   # dit OÙ se règle le vrai buffer
    assert audio._verify_actual("audioconfig", updates, {**actual, "BSIZE": "256"}) is None


def test_asio_apply_reports_clamped_channel_range():
    updates = {"asio_driver_name": '"UMC ASIO Driver"', "asio_srate": "48000",
               "asio_srate_use": "0", "asio_bsize": "128", "asio_bsize_use": "0",
               "asio_input0": "0", "asio_input1": "3", "asio_output0": "0", "asio_output1": "3"}
    actual = {"MODE": "ASIO", "IDENT_IN": "ASIO UMC ASIO Driver",
              "INPUT_COUNT": 2, "OUTPUT_COUNT": 4}
    assert audio._verify_actual("audioconfig", updates, actual) == \
        "REAPER opened 2 input channels instead of 4"


def test_windows_asio_settings_keep_unrelated_ini_bytes(tmp_path, monkeypatch):
    ini = tmp_path / "reaper.ini"
    ini.write_bytes(b"[reaper]\r\nnorunmute=0\r\n\r\n[audioconfig]\r\nmode=4\r\nasio_bsize=512\r\n\r\n[other]\r\nx=\xff\r\n")
    monkeypatch.setattr(audio.C, "reaper_resource_dir", lambda: str(tmp_path))
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(audio, "asio_drivers", lambda: ["ASIO4ALL v2", "UMC ASIO Driver"])
    body = {"driver": "UMC ASIO Driver", "input_first": 0, "input_last": 3,
            "output_first": 0, "output_last": 1, "sample_rate": 48000,
            "sample_rate_use": True, "buffer_size": 128, "buffer_size_use": True}
    section, updates = audio.validate(body, audio.settings())
    audio.apply_ini(section, updates)
    content = ini.read_bytes()
    assert b"[reaper]\r\nnorunmute=0" in content
    assert b"[other]\r\nx=\xff" in content
    assert b"mode=3\r\n" in content
    assert b'asio_driver_name="UMC ASIO Driver"\r\n' in content
    assert b"asio_input1=3\r\n" in content
    assert b"asio_bsize=128\r\n" in content
    assert b"asio_bsize_use=1\r\n" in content
    assert ini.with_suffix(".ini.golem-audio.bak").exists()


def test_macos_coreaudio_devices_and_unicode_settings(tmp_path, monkeypatch):
    ini = tmp_path / "reaper.ini"
    ini.write_text("[REAPER]\ncoreaudioindevnew=<default system devices>\n", encoding="utf-8")
    monkeypatch.setattr(audio.C, "reaper_resource_dir", lambda: str(tmp_path))
    monkeypatch.setattr(audio.sys, "platform", "darwin")
    monkeypatch.setattr(audio, "coreaudio_devices", lambda: {
        "inputs": [audio.DEFAULT_DEVICE, "Entrée USB"],
        "outputs": [audio.DEFAULT_DEVICE, "Sortie USB"]})
    current = audio.settings()
    assert current["input_device"] == audio.DEFAULT_DEVICE
    body = {"input_device": "Entrée USB", "output_device": "Sortie USB",
            "sample_rate": 48000, "sample_rate_use": True,
            "buffer_size": 128, "buffer_size_use": True}
    section, updates = audio.validate(body, current)
    audio.apply_ini(section, updates)
    result = ini.read_text(encoding="utf-8")
    assert "coreaudioindevnew=Entrée USB" in result
    assert "coreaudiooutdevnew=Sortie USB" in result
    assert "coreaudiosrateuse=1" in result
    assert "coreaudiobsuse=1" in result


def test_macos_profiler_flat_output_falls_back_to_visible_names(monkeypatch):
    import json
    from subprocess import CompletedProcess
    monkeypatch.setattr(audio.sys, "platform", "darwin")
    output = {"SPAudioDataType": [{"_name": "USB Audio"}, {"_name": "Built-in Output"}]}
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k:
                        CompletedProcess(a[0], 0, json.dumps(output), ""))
    monkeypatch.setattr(audio, "_CA_CACHE", {"at": 0.0, "val": None})
    devices = audio.coreaudio_devices()
    assert "USB Audio" in devices["inputs"]
    assert "Built-in Output" in devices["outputs"]
    assert devices["enumeration_warning"]


def test_macos_missing_section_uses_reaper_canonical_case(tmp_path, monkeypatch):
    ini = tmp_path / "reaper.ini"
    ini.write_text("[other]\nx=1\n", encoding="utf-8")
    monkeypatch.setattr(audio.C, "reaper_resource_dir", lambda: str(tmp_path))
    audio.apply_ini("REAPER", {"coreaudiobs": "128"})
    assert "[REAPER]\ncoreaudiobs=128" in ini.read_text(encoding="utf-8")


def test_rejects_unknown_devices_and_invalid_channel_ranges(monkeypatch):
    monkeypatch.setattr(audio.sys, "platform", "win32")
    current = {"drivers": ["UMC ASIO Driver"]}
    body = {"driver": "unknown", "input_first": 0, "input_last": 1,
            "output_first": 0, "output_last": 1, "sample_rate": 48000,
            "sample_rate_use": True, "buffer_size": 128, "buffer_size_use": True}
    import pytest
    with pytest.raises(ValueError, match="ASIO"):
        audio.validate(body, current)
    body["driver"] = "UMC ASIO Driver"
    body["input_first"] = 2
    with pytest.raises(ValueError, match="channel range"):
        audio.validate(body, current)


def test_reopen_explicitly_restores_active_project(tmp_path, monkeypatch):
    from provision import desktop
    project = tmp_path / "active.rpp"
    project.write_text("<REAPER_PROJECT", encoding="ascii")
    binary = tmp_path / "reaper"
    assert audio._reopen_args(binary, {"PROJECT": str(project)}) == [
        str(binary), "-nosplash", str(project)]
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "missing.rpp")
    assert audio._reopen_args(binary, None) == [str(binary), "-nosplash", "-new"]
    assert audio._reopen_args(binary, {"PROJECT": "", "TRACKS": 0}) == [str(binary), "-nosplash", "-new"]


def test_apply_saves_untitled_project_before_audio_restart(tmp_path, monkeypatch):
    from provision import desktop
    monkeypatch.setattr(audio, "_status", {"phase": "idle", "error": None})
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(audio, "settings", lambda: {"drivers": ["UMC ASIO Driver"]})
    monkeypatch.setattr(desktop, "reaper_running", lambda: True)
    target = tmp_path / "sets" / "golem-set.rpp"
    target.parent.mkdir()
    monkeypatch.setattr(audio, "_auto_save_target", lambda: target)
    snapshots = []
    def snapshot(save_target=None):
        snapshots.append(save_target)
        if save_target is None:
            return {"PROJECT": "", "TRACKS": 3, "AUTO_SAVED": False}
        target.write_text("<REAPER_PROJECT", encoding="ascii")
        return {"PROJECT": str(target), "TRACKS": 3, "AUTO_SAVED": True}
    monkeypatch.setattr(audio, "_snapshot_reaper", snapshot)
    remembered = []
    monkeypatch.setattr(desktop, "remember_project", lambda path: remembered.append(path))
    class DormantThread:
        def __init__(self, **kwargs):
            pass
        def start(self):
            pass
    monkeypatch.setattr(audio.threading, "Thread", DormantThread)
    body = {"driver": "UMC ASIO Driver", "input_first": 0, "input_last": 1,
            "output_first": 0, "output_last": 1, "sample_rate": 48000,
            "sample_rate_use": True, "buffer_size": 128, "buffer_size_use": True}
    try:
        result = audio.start_apply(body)
        assert result["saved_project"] == "golem-set.rpp"
        assert snapshots == [None, target]
        assert remembered == [target]
    finally:
        audio._lock.release()


def test_failed_auto_save_does_not_start_audio_restart(tmp_path, monkeypatch):
    import pytest
    from provision import desktop
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(audio, "settings", lambda: {"drivers": ["UMC ASIO Driver"]})
    monkeypatch.setattr(desktop, "reaper_running", lambda: True)
    target = tmp_path / "sets" / "golem-set.rpp"
    monkeypatch.setattr(audio, "_auto_save_target", lambda: target)
    monkeypatch.setattr(audio, "_snapshot_reaper", lambda save_target=None:
                        {"PROJECT": "", "TRACKS": 3, "AUTO_SAVED": False})
    body = {"driver": "UMC ASIO Driver", "input_first": 0, "input_last": 1,
            "output_first": 0, "output_last": 1, "sample_rate": 48000,
            "sample_rate_use": True, "buffer_size": 128, "buffer_size_use": True}
    with pytest.raises(RuntimeError, match="auto-save"):
        audio.start_apply(body)
    assert not audio._lock.locked()


def test_failed_ini_write_still_restarts_reaper(tmp_path, monkeypatch):
    from provision import desktop
    from provision import desktop_window
    monkeypatch.setattr(desktop_window, "request_reaper_close", lambda *_: 1)
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "missing.rpp")
    monkeypatch.setattr(desktop, "reaper_binary", lambda: tmp_path / "reaper")
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(audio.subprocess, "run", lambda *a, **k: None)
    launched = []
    monkeypatch.setattr(desktop, "launch_reaper", lambda args: launched.append(args))
    def fail(*_):
        raise OSError("disk full")
    monkeypatch.setattr(audio, "apply_ini", fail)
    audio._lock.acquire()
    audio._apply_worker("audioconfig", {}, True, {"PROJECT": "", "TRACKS": 0})
    assert launched == [[str(tmp_path / "reaper"), "-nosplash", "-new"]]
    assert audio.status()["phase"] == "error"
    assert "disk full" in audio.status()["error"]
    assert not audio._lock.locked()


def test_windows_apply_reports_driver_fallback(tmp_path, monkeypatch):
    from provision import desktop
    from provision import desktop_window
    monkeypatch.setattr(desktop_window, "request_reaper_close", lambda *_: 1)
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "missing.rpp")
    monkeypatch.setattr(desktop, "reaper_binary", lambda: tmp_path / "reaper")
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    monkeypatch.setattr(audio, "apply_ini", lambda *args: None)
    monkeypatch.setattr(audio, "_actual", lambda since=0: {
        "MODE": "ASIO", "IDENT_IN": "ASIO ASIO4ALL v2", "IDENT_OUT": "ASIO ASIO4ALL v2"})
    monkeypatch.setattr(audio.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(desktop, "launch_reaper", lambda args: None)
    audio._lock.acquire()
    audio._apply_worker("audioconfig", {"asio_driver_name": '"UMC ASIO Driver"'},
                        True, {"PROJECT": "", "TRACKS": 0})
    assert audio.status()["phase"] == "error"
    assert "ASIO4ALL v2" in audio.status()["error"]
    assert "UMC ASIO Driver" in audio.status()["error"]
    assert not audio._lock.locked()


def test_restart_launches_a_stopped_reaper_and_verifies_its_device(tmp_path, monkeypatch):
    from provision import desktop
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    monkeypatch.setattr(desktop, "desktop_project", lambda: tmp_path / "missing.rpp")
    monkeypatch.setattr(desktop, "reaper_binary", lambda: tmp_path / "reaper")
    monkeypatch.setattr(desktop, "reaper_running", lambda: False)
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    monkeypatch.setattr(audio, "apply_ini", lambda *args: None)
    monkeypatch.setattr(audio, "_actual", lambda since=0: {"MODE": "CoreAudio", "IDENT_IN": "Interface", "IDENT_OUT": "Interface"})
    launched = []
    monkeypatch.setattr(desktop, "launch_reaper", lambda args: launched.append(args))
    audio._lock.acquire()
    audio._apply_worker("REAPER", {}, False, None, ensure_running=True)
    assert launched == [[str(tmp_path / "reaper"), "-nosplash", "-new"]]
    assert audio.status()["phase"] == "done"
    assert not audio._lock.locked()


def test_stopped_restart_restores_remembered_session(tmp_path, monkeypatch):
    from provision import desktop
    project = tmp_path / "remembered.rpp"
    project.write_text("<REAPER_PROJECT", encoding="ascii")
    monkeypatch.setattr(desktop, "desktop_project", lambda: project)
    assert audio._reopen_args(tmp_path / "reaper", None)[-1] == str(project)


def test_coreaudio_verify_detects_fallback_and_accepts_open_system_devices():
    updates = {"coreaudioindevnew": "USB In", "coreaudiooutdevnew": "USB Out",
               "coreaudiosrate": "48000", "coreaudiosrateuse": "1",
               "coreaudiobs": "128", "coreaudiobsuse": "1"}
    actual = {"MODE": "CoreAudio", "IDENT_IN": "USB In", "IDENT_OUT": "USB Out",
              "SRATE": "48000", "BSIZE": "128"}
    assert audio._verify_actual("REAPER", updates, actual) is None
    for field, value in (("MODE", "WASAPI"), ("IDENT_IN", "Built-in Mic"),
                         ("IDENT_OUT", "Built-in Speakers"), ("SRATE", "44100"), ("BSIZE", "512")):
        assert audio._verify_actual("REAPER", updates, {**actual, field: value})
    updates.update(coreaudioindevnew=audio.DEFAULT_DEVICE, coreaudiooutdevnew=audio.DEFAULT_DEVICE)
    assert audio._verify_actual("REAPER", updates, actual) is None
    assert audio._verify_actual("REAPER", updates, {**actual, "IDENT_OUT": ""})
    updates.update(coreaudiosrateuse="0", coreaudiobsuse="0")
    assert audio._verify_actual("REAPER", updates, {**actual, "SRATE": "44100", "BSIZE": "512"}) is None


def test_le_pilote_asio_dit_ses_tailles_et_le_reste_se_grise(tmp_path, monkeypatch):
    """2026-10-24, UA Volt : golem proposait 192, le pilote n'ouvre que des puissances de 2. getBufferSize (granularité -1)
    est retenu par pilote ; 192 est refusé AVANT de fermer REAPER, avec ce que le pilote offre ; 32 apparaît."""
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    assert audio.buffer_choices("Volt") == (list(audio.BUFFER_SIZES), None)          # rien de sondé : tout reste ouvert
    audio._asio_save({"Volt": {"min": 32, "max": 1024, "preferred": 128, "granularity": -1}})
    shown, ok = audio.buffer_choices("Volt")
    assert ok == [32, 64, 128, 256, 512, 1024] and 32 in shown and 192 in shown
    current = {"drivers": ["Volt"]}
    body = {"driver": "Volt", "sample_rate": 48000, "sample_rate_use": False, "buffer_size": 192, "buffer_size_use": True,
            "input_first": 0, "input_last": 1, "output_first": 0, "output_last": 1}
    with pytest.raises(ValueError, match="Volt does not offer 192 samples — it offers 32, 64, 128, 256, 512, 1024"):
        audio.validate(body, current)
    assert audio.validate({**body, "buffer_size": 32}, current)[1]["asio_bsize"] == "32"


def test_une_taille_remplacee_par_le_pilote_est_retenue(tmp_path, monkeypatch):
    """Sans sonde (pilote jamais vu REAPER fermé) : la taille que le pilote a remplacée à l'ouverture se grise."""
    monkeypatch.setattr(audio.sys, "platform", "win32")
    monkeypatch.setattr(audio.C, "runtime_file", lambda name: str(tmp_path / name))
    updates = {"asio_driver_name": '"Volt"', "asio_srate": "48000", "asio_srate_use": "0", "asio_bsize": "192",
               "asio_bsize_use": "1", "asio_input0": "0", "asio_input1": "1", "asio_output0": "0", "asio_output1": "1"}
    assert "kept its own buffer" in audio._verify_actual("audioconfig", updates, {"MODE": "ASIO", "IDENT_IN": "ASIO Volt", "BSIZE": "128"})
    assert 192 not in audio.buffer_choices("Volt")[1]


def test_la_granularite_asio():
    from bridge.asio_probe import sizes
    c = (32, 48, 64, 96, 128, 192, 256, 528)
    assert sizes({"min": 48, "max": 192, "preferred": 96, "granularity": 48}, c) == [48, 96, 192]
    assert sizes({"min": 528, "max": 528, "preferred": 528, "granularity": 0}, c) == [528]
    assert sizes({}, c) is None
