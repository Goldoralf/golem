# MIDI pitfalls

Controllers (keyboards, pads), drum modules and the foot controller reach the rack two ways: through
REAPER's MIDI device masks (lanes Keys, pads, drums) and through the bridge's own reader (foot
controller, `bridge/foot.py`). Most failures here are silent: no error, just no notes.

---

## An unplugged controller is no longer nameable — keep its mask bit from memory

**Symptom.** "MIDI is broken after every reboot": the rig is started, the keyboard is plugged in
afterwards, and it never plays. No error.

**Cause.** REAPER keeps the slot of an absent device (`[mididevcache]`, e.g. `in2=hw:II`) but no longer
gives it its rich name (the OS card list does not describe it while unplugged). Provisioning that
resolves devices BY NAME fails and writes `midiins=0` / `midiouts=0`. Replugging does not help: the
mask is already zero.

**Rule.** Remember each resolved device (name ↔ slot) and let an absent controller keep its bit.
Set the matching `nowarn` bits so REAPER shows no modal at boot when it is absent. Both the Python
provisioning and the Lua sentinel read the same memory.

**Detect.** Compare `reaper.ini` with its backup (`midiins` dropped to 0); controller present but
mask zero = stale mask.

**Code.** `provision/reaper-ini-setup.py` (`keys_memory`, `remember_keys_device`,
`write_keys_sidecar`, `resolve_keys_index`), sidecar `presets/.keys-midi.json` (`devices`),
`reaper/Scripts/golem_midi.lua` (reads the sidecar, sets `midiins_nowarn`).

---

## REAPER opens MIDI devices only at startup

**Symptom.** A device plugged (or re-enumerated by the OS, or a hub reset) while REAPER runs stays a
dead port.

**Cause.** REAPER enumerates and opens its MIDI devices at launch only.

**Rule.** On a hot-plug of a device REAPER should hold, call `midi_reinit()` alone — do not touch the
masks (they only change at startup). Never restart the engine for a cable; the UI never proposes
"restart REAPER" for an unplugged controller. Rate-limit (one reinit per ~10 s; not during boot).

**Detect.** REAPER log line "midi_reinit"; on Windows/macOS the OS MIDI port list shows the device
re-appearing.

**Code.** Linux: `reaper/Scripts/golem_midi.lua` (watches the card list, bounded `midi_reinit`).
Windows/macOS: `bridge/monitors.py` `_poll_hotplug` writes `{"action": "midi_reinit"}`;
`reaper/Scripts/golem_watch.lua` executes it.

---

## Windows: a drum module opened as an OUTPUT stops sending

**Symptom.** An electronic drum kit sounds in its own headphones, but no message reaches the OS once
REAPER has started; replugging restores it until the next REAPER start.

**Cause.** REAPER opened the module both as input AND output, like a keyboard. Some modules stop
transmitting over USB when their output port is held.

**Rule.** Open the OUTPUT only for devices that need it (keyboards/pads receiving MIDI clock). Close
it if it was open.

**Detect.** Read the port live with rtmidi while REAPER runs.

**Code.** `bridge/desktop_midi.py` `wanted_masks` (`out_names`).

---

## Windows: "Python can open the port" proves nothing

**Cause.** The Windows 11 MIDI service is multi-client: several processes can open the same port.

**Rule.** Do not use "the port opens" as evidence that REAPER does not hold it; observe actual
message flow instead.

---

## Foot controller: DIN versus USB, and a reader subscribed to nothing

**Symptom.** A USB foot controller is never heard; or, after the sound card re-enumerates, the
screen says "MIDI ok" but no switch arrives.

**Cause.** A reader hard-wired to the sound card's DIN port ignores USB controllers. And after a card
re-enumeration `aseqdump` prints "Port unsubscribed" and stays alive, subscribed to nothing; the MIDI
output on the same card talks to a dead client without error.

**Rule.** The transport is DATA in the pedalboard descriptor (`transport.kind`: `din-soundcard`
default, or `usb` with `port_match`). A transport change re-resolves the listening port. The reader
restarts on "Port unsubscribed" and the output forgets its ports. An absent port means retry, never
crash.

**Detect.** `aseqdump -l`, `aconnect -l`; `./tools/check-descriptors.py` (validates `transport`);
`./tools/check-foot.py --live`.

**Code.** `bridge/foot.py` (`resolve_port`, `_supervise`, transport change in `set_device`),
`config/pedalboard/`, `tests/test_foot_port_lost.py`. Contract: `docs/pedalboards.md`.

---

## The foot controller chip must be reflashed when switch ownership changes

**Symptom.** A switch LED or on/off behaviour does not match the preset.

**Cause.** The rack reads what was flashed (`presets/.uno2-flashed.json`), not the preset.

**Rule.** Reflash when a preset in the setlist takes or releases a switch for an on/off block.
Channel and quirks come from the descriptor, never from code.

**Detect.** `./tools/fcb/check-uno2.py` (also says whether the chip matches the setlist).

**Code.** `tools/fcb/flash_uno2.py`, `config/pedalboard/`.

---

## Sends leak MIDI into note-driven destinations

See [reaper.md](reaper.md#a-send-carries-midi-by-default) (`I_MIDIFLAGS = 31`).

## MIDI clock never reaches devices

The `MIDI Clock` service track must be armed. See
[reaper.md](reaper.md#an-unarmed-service-track-leaves-the-live-graph).

## Windows: the sound card's MIDI ports are not instruments

FIXED 2026-11-03 (AudioBox iTwo, PreSonus Universal Control driver).

**Symptom.** "AudioBox iTwo MIDI In / MIDI Out" listed in Controllers and Drums, and two "unknown MIDI
device — calibrate it" banners that never go away, with nothing plugged into the DIN jacks.

**Cause.** Linux drops the active sound card from the instrument list by its ALSA id (`devices._usb_list`).
WinMM gives a flat list of port names: the card's DIN ports look like any USB keyboard. A DIN jack cannot
tell whether something is plugged into it, so it must never be offered for calibration.

**Rule.** On Windows a MIDI port is the active card's when its PnP parent also carries audio endpoints and
its driver provider is the vendor that signs the active ASIO driver's DLL (CLSID → InprocServer32). A USB
drum module (audio + MIDI too) has another driver vendor and stays. On any doubt nothing is excluded. The
card's ports remain choosable in Soundcard ▸ MIDI IN / OUT (`ports()`). `Get-PnpDeviceProperty` with a list
of ids returns incomplete results at random — query by CIM, one entity at a time (~3 s, cached, never on
the asyncio loop).

**Code.** `bridge/desktop_midi.py` `card_ports` / `card_ports_from` / `usb_devices`,
`tests/test_desktop_midi_card_ports.py`.
