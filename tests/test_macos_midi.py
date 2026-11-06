# SPDX-License-Identifier: GPL-3.0-or-later
"""MIDI sous macOS (docs/platforms.md, M5) : VID:PID, hotplug, réparation au rebranchement."""
from subprocess import CompletedProcess

from bridge import desktop_midi, hotplug

# forme « SPUSBDataType » (macOS ≤ 14)
LEGACY = {"SPUSBDataType": [{"_name": "USB31Bus", "_items": [
    {"_name": "MPK mini 3", "vendor_id": "0x09e8  (AKAI professional M.I. Corp.)", "product_id": "0x0049"},
    {"_name": "USB Hub", "_items": [{"_name": "Nitro Max", "vendor_id": "0x13b2", "product_id": "0x0071"}]},
    {"_name": "Mystery", "vendor_id": "apple_vendor_id"}]}]}
# forme « SPUSBHostDataType » (macOS 15+) : d'autres noms de clés
HOST = {"SPUSBHostDataType": [{"_name": "USB 3.1 Bus", "_items": [
    {"_name": "Volt 276", "USBDeviceKeyVendorID": "0x2b5a", "USBDeviceKeyProductID": "0x0012"}]}]}


def test_vid_pid_from_both_system_profiler_shapes():
    assert desktop_midi.parse_system_profiler_usb(LEGACY) == {"mpk mini 3": "09e8:0049", "nitro max": "13b2:0071"}
    assert desktop_midi.parse_system_profiler_usb(HOST) == {"volt 276": "2b5a:0012"}


def test_usb_ids_on_macos_are_cached(monkeypatch):
    import json
    monkeypatch.setattr(desktop_midi.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_midi, "_USB_IDS", {"key": None, "val": {}})
    calls = []
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda args, **k: calls.append(args) or
                        CompletedProcess(args, 0, json.dumps(LEGACY), ""))
    usb_ids = desktop_midi._REAL_USB_IDS                 # conftest neutralise usb_ids (pas de vrai matériel)
    assert usb_ids(["MPK mini 3"]) == {"mpk mini 3": "09e8:0049", "nitro max": "13b2:0071"}
    usb_ids(["MPK mini 3"])
    assert len(calls) == 1 and calls[0][:2] == ["system_profiler", "-json"]


def test_hotplug_reads_coremidi_ports_instead_of_proc(monkeypatch):
    monkeypatch.setattr(hotplug.sys, "platform", "darwin")
    monkeypatch.setattr(desktop_midi, "usb_devices", lambda: [{"name": "MPK mini 3", "kind": "midi", "usb": "09e8:0049"}])
    assert hotplug.scan() == [{"index": None, "id": "MPK mini 3", "usb": "09e8:0049", "name": "MPK mini 3", "pcm": False}]


def test_midi_repair_on_replug_covers_macos():
    """REAPER n'ouvre ses appareils qu'au démarrage, sur Mac aussi : le remède Windows vaut là."""
    import inspect
    from bridge import monitors
    src = inspect.getsource(monitors._poll_hotplug)
    assert 'sys.platform in ("win32", "darwin") and arrivals' in src


def test_le_cache_midi_de_reaper_mac_se_lit_en_utf8(tmp_path):
    """REAPER macOS écrit reaper-midihw.ini en UTF-8 (premier Mac réel, 2026-11-04) : un nom accentué se relit tel
    quel — lu en latin-1, « Clé » devenait « ClÃ© » ; un fichier ANSI d'un vieux REAPER Windows se lit encore."""
    from bridge import desktop_midi
    (tmp_path / "reaper-midihw.ini").write_bytes("[mididevcache]\nin0=Clé USB\non1=Pédalier\n".encode("utf-8"))
    assert desktop_midi._device_cache(str(tmp_path)) == {"in": {0: "Clé USB"}, "out": {1: "Pédalier"}}
    (tmp_path / "reaper-midihw.ini").write_bytes("[mididevcache]\nin0=Clé USB\n".encode("latin-1"))
    assert desktop_midi._device_cache(str(tmp_path))["in"] == {0: "Clé USB"}
