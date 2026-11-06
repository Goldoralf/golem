# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrat MIDI partagé entre aseqdump et RtMidi natif."""
from types import SimpleNamespace
import sys
import threading

from bridge import foot, midi_api


def test_native_api_keeps_linux_and_selects_desktop_backends(monkeypatch):
    api = SimpleNamespace(API_LINUX_ALSA=1, API_WINDOWS_MM=2, API_MACOSX_CORE=3)
    for platform, expected in (("linux", 1), ("win32", 2), ("darwin", 3)):
        monkeypatch.setattr(midi_api.sys, "platform", platform)
        assert midi_api.native_api(api) == expected


def test_native_messages_preserve_aseq_dump_contract():
    assert foot.midi_line([0xC1, 17]) == "Program change 1, program 17"
    assert foot.midi_line([0xB0, 20, 127]) == "Control change 0, controller 20, value 127"
    assert foot.midi_line([0x90, 60, 110]) == "Note on 0, note 60, velocity 110"
    assert foot.midi_line([0x90, 60, 0]) == "Note off 0, note 60, velocity 0"
    assert foot.midi_line([0xF8]) is None


def test_native_port_uses_transport_and_override(monkeypatch):
    reader = foot.FootReader(lambda *_: None, lambda *_: None)
    names = ["Volt 276 MIDI", "Morningstar MC6"]
    monkeypatch.setitem(foot._DEVICE, "transport", {"kind": "usb", "port_match": "MC6"})
    assert reader._native_port(names) == (1, "Morningstar MC6")
    monkeypatch.setenv("GOLEM_FCB_PORT", "Volt")
    assert reader._native_port(names) == (0, "Volt 276 MIDI")


def test_native_reader_rebind_and_shared_sysex(monkeypatch):
    opened = []

    class MidiIn:
        def __init__(self, *_args, **_kwargs):
            self.callback = None
            self.closed = threading.Event()
            opened.append(self)

        def get_ports(self):
            return ["Volt 276 MIDI"]

        def ignore_types(self, **_kwargs):
            pass

        def open_port(self, *_args, **_kwargs):
            pass

        def set_callback(self, callback):
            self.callback = callback

        def cancel_callback(self):
            self.callback = None

        def close_port(self):
            self.closed.set()

    monkeypatch.setitem(sys.modules, "rtmidi", SimpleNamespace(MidiIn=MidiIn, API_WINDOWS_MM=2))
    monkeypatch.setattr(foot.sys, "platform", "win32")
    monkeypatch.setitem(foot._DEVICE, "transport", {"kind": "din-soundcard"})
    monkeypatch.setenv("GOLEM_FCB_PORT", "Volt")
    reader = foot.FootReader(lambda *_: None, lambda *_: None)
    reader._retry = 0.01
    seen = []
    handled = threading.Event()

    def handle(line):
        seen.append(line)
        handled.set()

    reader._handle = handle
    assert reader.start()
    try:
        assert reader._native_connected.wait(1)
        opened[0].callback(([0xB0, 20, 127], 0), None)
        assert handled.wait(1)
        stream = foot.native_sysex_stream(timeout=1)
        assert stream is not None
        opened[0].callback(([0xF0, 0x7E, 0xF7], 0), None)
        assert stream.get_message() == ([0xF0, 0x7E, 0xF7], 0)
        stream.close_port()
        reader.rebind()
        assert opened[0].closed.wait(1)
        assert seen == ["Control change 0, controller 20, value 127"]
    finally:
        reader.stop()
        reader._thread.join(timeout=1)
    assert not reader._thread.is_alive()
