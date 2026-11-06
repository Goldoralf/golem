# SPDX-License-Identifier: GPL-3.0-or-later
"""Soundcard et cycle de vie de REAPER sous macOS (docs/platforms.md, M2).

Avant : la carte « connectée » se lisait dans /proc/asound/cards (aucune sur un Mac), changer de carte
passait par le chemin ALSA, et la fermeture de REAPER par un `-closeall:exit` jamais essayé."""
import asyncio
from subprocess import CompletedProcess

from bridge import cards, desktop_audio, routes_system
from provision import desktop_window

ACTUAL = {"MODE": "CoreAudio", "IDENT_IN": "Volt 276", "IDENT_OUT": "Volt 276",
          "INPUT_COUNT": 2, "OUTPUT_COUNT": 4, "SRATE": "48000", "BSIZE": "128"}


def _mac(monkeypatch, configured="Volt 276", actual=ACTUAL):
    for module in (cards, routes_system, desktop_audio):
        monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_audio, "_public_actual", lambda: actual)
    monkeypatch.setattr(desktop_audio, "configured_coreaudio_input", lambda: configured)


def test_the_opened_coreaudio_input_is_the_connected_card(monkeypatch):
    _mac(monkeypatch)
    assert cards.connected() == [{"index": 0, "id": "Volt 276", "name": "Volt 276"}]
    probe = cards.probe("Volt 276")
    assert (probe["inputs"], probe["outputs"], probe["probed"]) == (2, 4, True)


def test_a_configured_device_reaper_did_not_open_is_not_connected(monkeypatch):
    _mac(monkeypatch, actual={**ACTUAL, "IDENT_IN": "MacBook Pro Microphone"})
    assert cards.connected() == []
    _mac(monkeypatch, actual={**ACTUAL, "MODE": "Dummy Audio"})
    assert cards.connected() == []


def test_default_system_devices_name_the_card_by_what_reaper_opened(monkeypatch):
    _mac(monkeypatch, configured=desktop_audio.DEFAULT_DEVICE)
    assert cards.mac_opened_input() == "Volt 276"


def _settings():
    return {"platform": "macos", "inputs": [desktop_audio.DEFAULT_DEVICE, "Volt 276", "USB Mic"],
            "outputs": [desktop_audio.DEFAULT_DEVICE, "Volt 276", "MacBook Pro Speakers"],
            "input_device": "USB Mic", "output_device": "MacBook Pro Speakers",
            "sample_rate": 48000, "sample_rate_use": True, "buffer_size": 128, "buffer_size_use": True}


def test_activating_a_card_sets_its_input_and_output(monkeypatch):
    _mac(monkeypatch)
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    sent = {}
    monkeypatch.setattr(desktop_audio, "start_apply", lambda body, **kw: sent.update(body) or {"phase": "x"})
    out = asyncio.run(routes_system.cards_adopt({"id": "Volt 276"}))
    assert out["ok"] and sent["input_device"] == sent["output_device"] == "Volt 276"
    assert sent["buffer_size"] == 128


def test_an_input_only_device_keeps_the_current_output(monkeypatch):
    _mac(monkeypatch)
    monkeypatch.setattr(desktop_audio, "settings", lambda: {**_settings(), "inputs": [*_settings()["inputs"], "Mic Only"]})
    sent = {}
    monkeypatch.setattr(desktop_audio, "start_apply", lambda body, **kw: sent.update(body) or {})
    asyncio.run(routes_system.cards_adopt({"id": "Mic Only"}))
    assert sent["input_device"] == "Mic Only" and sent["output_device"] == "MacBook Pro Speakers"


def test_an_unknown_device_is_refused_in_english(monkeypatch):
    _mac(monkeypatch)
    monkeypatch.setattr(desktop_audio, "settings", _settings)
    out = asyncio.run(routes_system.cards_adopt({"id": "Nope"}))
    assert out.status_code == 400 and b"CoreAudio" in out.body


def test_coreaudio_inventory_is_cached(monkeypatch):
    monkeypatch.setattr(desktop_audio.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_audio, "_CA_CACHE", {"at": 0.0, "val": None})
    calls = []
    monkeypatch.setattr(desktop_audio.subprocess, "run", lambda *a, **k: calls.append(1) or
                        CompletedProcess(a[0], 0, '{"SPAudioDataType": []}', ""))
    a = desktop_audio.coreaudio_devices()
    a["inputs"].append("mutated")                     # une copie : le cache ne se corrompt pas
    b = desktop_audio.coreaudio_devices()
    assert len(calls) == 1 and "mutated" not in b["inputs"]


def test_reaper_quits_politely_by_apple_event(monkeypatch):
    monkeypatch.setattr(desktop_window.sys, "platform", "darwin")
    seen = []
    monkeypatch.setattr(desktop_window.subprocess, "run", lambda args, **k: seen.append(args) or
                        CompletedProcess(args, 0, "", ""))
    assert desktop_window.request_reaper_close(set()) == 1        # aucun PID enregistré sur Mac
    assert seen[-1][:2] == ["osascript", "-e"] and 'id "com.cockos.reaper" to quit' in seen[-1][2]
    assert desktop_window.set_reaper_windows_visible(set(), True) == 1
    assert "set visible" in seen[-1][2] and "to true" in seen[-1][2]


def test_a_refused_apple_event_is_reported(monkeypatch):
    monkeypatch.setattr(desktop_window.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_window.subprocess, "run", lambda args, **k: CompletedProcess(args, 1, "", "denied"))
    assert desktop_window.request_reaper_close({1}) == 0


def test_mac_snapshot_goes_through_the_running_engine(tmp_path, monkeypatch):
    """Plus de second binaire REAPER lancé : la demande passe par le fichier que lit le moteur."""
    monkeypatch.setattr(desktop_audio.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_audio.C, "runtime_file", lambda name: str(tmp_path / name))
    spawned = []
    monkeypatch.setattr(desktop_audio.subprocess, "Popen", lambda *a, **k: spawned.append(a))
    (tmp_path / "desktop-audio-snapshot.json").write_text("{}")
    real_unlink = type(tmp_path).unlink

    def keep_output(self, missing_ok=False):              # la réponse « du moteur » est déjà là
        if self.name != "desktop-audio-snapshot.json":
            real_unlink(self, missing_ok=missing_ok)
    monkeypatch.setattr(type(tmp_path), "unlink", keep_output)
    assert desktop_audio._snapshot_reaper() == {}
    assert not spawned


def test_an_empty_coreaudio_mode_is_read_from_the_device_name(monkeypatch):
    # REAPER 7.82 macOS-arm64 répond MODE="" sous Core Audio (2026-11-04) : la carte passait pour absente
    monkeypatch.setattr(desktop_audio.sys, "platform", "darwin")
    seen = {"MODE": "", "IDENT_IN": "CoreAudio Microphone MacBook Air",
            "IDENT_OUT": "CoreAudio Haut-parleurs MacBook Air"}
    assert desktop_audio._with_mode(dict(seen))["MODE"] == "CoreAudio"
    # aucun périphérique derrière le préfixe : rien n'est ouvert, MODE reste vide
    assert desktop_audio._with_mode({"MODE": "", "IDENT_IN": "CoreAudio ", "IDENT_OUT": "CoreAudio "})["MODE"] == ""
    assert desktop_audio._with_mode({**seen, "MODE": "Dummy Audio"})["MODE"] == "Dummy Audio"
    monkeypatch.setattr(desktop_audio.sys, "platform", "win32")
    assert desktop_audio._with_mode(dict(seen))["MODE"] == ""


def test_the_opened_card_is_named_without_reaper_s_coreaudio_prefix(monkeypatch):
    # REAPER rapporte « CoreAudio <nom> » : la même carte avait deux clés d'inputmap (2026-11-04)
    _mac(monkeypatch, configured=desktop_audio.DEFAULT_DEVICE,
         actual={**ACTUAL, "IDENT_IN": "CoreAudio Microphone MacBook Air"})
    assert cards.mac_opened_input() == "Microphone MacBook Air"
    _mac(monkeypatch, configured="Microphone MacBook Air",
         actual={**ACTUAL, "IDENT_IN": "CoreAudio Microphone MacBook Air"})
    assert cards.mac_opened_input() == "Microphone MacBook Air"
    # débranchée : REAPER retombe sur un autre périphérique — la carte configurée n'est pas ouverte
    _mac(monkeypatch, configured="Volt 276", actual={**ACTUAL, "IDENT_IN": "CoreAudio Microphone MacBook Air"})
    assert cards.mac_opened_input() is None


def test_scripts_that_never_started_are_a_doctor_failure(monkeypatch):
    from bridge import health
    from bridge.state import state
    monkeypatch.setattr(state, "cards", {"scripts_stalled": True, "scripts_never_started": True})
    fact = health._f_scripts()
    assert fact["level"] == "bad" and "never started" in fact["text"] and "REAPER window" in fact["text"]


def test_a_patch_without_its_role_input_says_where_to_assign_it():
    # setlist guitare sur une carte réglée basse : le rappel disait seulement « this sound has no lane » (2026-11-04)
    from bridge import patches, preset_view, scene_bake
    imap = {"card": "coreaudio:Microphone MacBook Air", "inputs": [{"ch": "1", "role": "bass"}],
            "outputs": [{"ch": "1-2", "role": "monitors"}]}
    doc = {"id": "t-guitar", "name": "Test Guitar", "role": "guitar", "chain": {}}
    p = patches.as_preset(doc, imap=imap)
    preset_view.migrate(p, imap)
    why = scene_bake.to_paths_preset(p, "A", union=True).get("why_empty")
    assert "no guitar input" in why and "Modes ▸ Inputs" in why


def test_a_plugged_usb_interface_is_a_candidate_but_not_the_builtin_or_virtual_devices(monkeypatch):
    # une Volt branchée n'était jamais proposée : seul le périphérique ouvert par REAPER existait (2026-11-04)
    report = {"SPAudioDataType": [{"_name": "coreaudio_device", "_items": [
        {"_name": "Microphone MacBook Air", "coreaudio_device_input": 1, "coreaudio_device_transport": "coreaudio_device_type_builtin"},
        {"_name": "Haut-parleurs MacBook Air", "coreaudio_device_output": 2, "coreaudio_device_transport": "coreaudio_device_type_builtin"},
        {"_name": "Microphone de « iPhone »", "coreaudio_device_input": 1, "coreaudio_device_transport": "coreaudio_device_type_unknown"},
        {"_name": "Microsoft Teams Audio", "coreaudio_device_input": 1, "coreaudio_device_output": 1,
         "coreaudio_device_transport": "coreaudio_device_type_virtual"},
        {"_name": "Volt 276", "coreaudio_device_input": 2, "coreaudio_device_output": 4,
         "coreaudio_device_transport": "coreaudio_device_type_usb"}]}]}
    import json
    monkeypatch.setattr(desktop_audio.subprocess, "run",
                        lambda *a, **k: CompletedProcess(a, 0, stdout=json.dumps(report), stderr=""))
    scan = desktop_audio._coreaudio_scan()
    assert scan["details"]["Volt 276"] == {"transport": "usb", "inputs": 2, "outputs": 4}
    assert "coreaudio_device" not in scan["details"]                 # le groupe parent n'est pas un périphérique
    _mac(monkeypatch, configured="Microphone MacBook Air",
         actual={**ACTUAL, "IDENT_IN": "CoreAudio Microphone MacBook Air", "INPUT_COUNT": 1, "OUTPUT_COUNT": 2})
    monkeypatch.setattr(desktop_audio, "coreaudio_devices", lambda: scan)
    assert cards.mac_interfaces() == ["Volt 276"]
    assert [c["id"] for c in cards.connected()] == ["Microphone MacBook Air", "Volt 276"]
    probe = cards.probe("Volt 276")                                  # pas ouverte : ce que Core Audio en dit
    assert (probe["inputs"], probe["outputs"]) == (2, 4)
    assert (cards.probe("Microphone MacBook Air")["inputs"], cards.probe("Microphone MacBook Air")["outputs"]) == (1, 2)
