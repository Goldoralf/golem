# SPDX-License-Identifier: GPL-3.0-or-later
"""La veille de branchement voit aussi Windows (2026-10-03) : sans /proc, les ports MIDI de l'OS — c'est elle
qui déclenche la réparation MIDI auto (midi_reinit) quand un appareil que REAPER tient est rebranché."""
from bridge import desktop_midi, hotplug


def test_windows_scan_depuis_les_ports_midi(monkeypatch):
    monkeypatch.setattr(hotplug.sys, "platform", "win32")
    monkeypatch.setattr(desktop_midi, "usb_devices", lambda: [{"name": "Alesis Nitro", "kind": "midi", "usb": "13b2:009c"}])
    seen = hotplug.scan()
    assert seen == [{"index": None, "id": "Alesis Nitro", "usb": "13b2:009c", "name": "Alesis Nitro", "pcm": False}]
    st, arr, dep = hotplug.step(hotplug.new_watch(), seen, 0.0)
    st, arr, dep = hotplug.step(st, seen, 3.0)                 # après le débounce : il arrive
    assert [d["name"] for d in arr] == ["Alesis Nitro"]
    st, arr, dep = hotplug.step(st, [], 6.0)                   # débranché
    assert [d["name"] for d in dep] == ["Alesis Nitro"]
