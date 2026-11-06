# Pedalboards — intention, descriptor, transport

> **Status: CODED** — how the rack talks to a foot controller: one intention for every pedalboard, one descriptor per device and firmware, the transport it arrives by, detection, loading, LEDs and learned devices.

The pedalboard is an **accessory, not a prerequisite**. The touch screen already carries scenes,
stomps, knobs, presets and arrangement; the Live page mirrors the pedalboard entirely, and a
written song can run from the arrangement timeline ([arrangement.md](arrangement.md)) without any
gesture. The foot keeps what nothing replaces: both hands on the instrument, a switch found without
looking, a sound change on the beat.

**Invariant (check it at every review):** nothing is controllable by foot that is not also
controllable on screen. Every assignable switch has its tile. `tools/check-foot.py` tests the rack
side without a pedalboard (it replays messages through `/api/foot/inject`).

This document extends [pedal-registry.md](pedal-registry.md), which defines the descriptor schema
for controlled pedals. The chip-level format of the UnO2 is in [fcb/uno2/README.md](fcb/uno2/README.md).

## 1. Three objects

| Object | What it says | File | Versioned |
|---|---|---|---|
| **Intention** | what golem wants from *any* pedalboard: slots, scenes, stomps, expression pedals, numeric select | `config/pedalboard/contract.json` | yes |
| **Device descriptor** | what *this* chip does with the intention: identity, channel, quirks, capabilities, transport, load recipe, install steps, provenance | `config/pedalboard/devices/<id>.json` (one per device **and** firmware) | yes |
| **State** | the declared device and the last probe result | `config/.pedalboard.json` | no (local) |
| **Gestures table** | per block and per state, the foot gestures and their glyphs/texts | `config/pedalboard/gestures.json` | yes |

The intention contains no chip name, no channel, no byte. The device facts (channel, quirks) never
live in code or in hand-written screen sentences: the screen renders them from the descriptor.

`config/pedals.json` (one character away) is a different file: it holds the **roles** of the
expression pedals (volume / block), switchable without reflashing.

Module: `bridge/pedalboard.py` (`contract()`, `devices()`, `active()`, `select()`, `probe()`,
`goto_bank()`, `save_learned()`, `wire_contract()`, `edge_switches()`, `summary()`). The reader is
`bridge/foot.py`.

## 2. The intention — `config/pedalboard/contract.json`

| Key | Content |
|---|---|
| `slots` | 19 — the setlist slots. Each bank of the pedalboard is one slot and announces it as a Program Change (`PC = slot`, 0–18, on the wire). |
| `scenes[]` | `{switch, name, cc}` — switches 1–5 = scenes A–E, CC 20–24. A scene switch sends PC (current slot), its scene CC and its identity Note, so any press first selects the right preset, then the scene. |
| `stomps[]` | `{switch, cc, gestures}` — switches 6–10, CC 30–34. `gestures: true` is a **requirement** ("this switch must deliver press and release edges"), satisfied by each device its own way or declared unmet. What a stomp triggers is per preset (`block.foot`), not here. |
| `looper_bank.gestures` | switches a looper bank must compile as `trigger`. Currently empty: loops live on SW 1–4 (scene row, see [looper.md](looper.md)), which already release. |
| `expression[]` | `{pedal, role, cc, min, max}` — pedal 1 = CC 7, pedal 2 = CC 11. Roles are switched in `config/pedals.json`. |
| `select` | `{switch: 1, long_press_s: 1.5, timeout_s: 8.0}` — long press on SW1 opens numeric select (two digits, then recall of that slot). |

**Compilation.** `foot.apply_intent(con)` compiles the contract into the reader tables
(`SCENE_CC`, `STOMP_CC`, `VOLUME_CC`, `TREADLE_CC`, `DIGIT_OF_SWITCH`, `SELECT_SWITCH`,
`LONGPRESS_S`, `SELECT_TIMEOUT_S`). The intention travels inside the wire contract
(`pedalboard.wire_contract()["intent"]`) and is applied by `foot.set_device()`, so boot order is:
declared device first, the probe corrects afterwards (`app.py::_apply_pedalboard`).

- `foot.DEFAULT_INTENT` is the **fallback**, same schema and values as the file, compiled by the
  same function, used only when the file is missing or unreadable. Any missing section falls back
  section by section; a malformed contract falls back entirely and is logged.
  `tests/test_foot_intent.py` proves the file and the fallback compile to the same tables.
- The numeric keypad is **derived**: switch N types digit N, switch 10 types 0.
- `tools/check-foot.py` deliberately keeps **its own copy** of the tables: an independent checker
  must not read the source it checks.

**Numeric select is visible.** While it is open, `state.foot_select` is published and the app shows
a global banner (digits typed, countdown, **Cancel** → `POST /api/foot/select/cancel`). A mode that
changes the meaning of switches must show itself and be leavable. The long press is 1.5 s so that a
firm press on scene A does not silently enter select mode.

## 3. The device descriptor — `config/pedalboard/devices/<id>.json`

Fields read by the code:

| Field | Meaning |
|---|---|
| `id`, `name`, `kind: "pedalboard"`, `schema` | identity of the file |
| `identity` | brand/model/firmware; `identity.probe` (optional) = SysEx identity request and how to parse the reply (`request`, `reply_prefix`, `reply_len`, `device_byte`, `device_id`, `version_byte`, `serial_bytes`). Only devices with `probe` are probed. |
| `channel` | contract channel, **1–16**. On the wire it is 0–15 (`wire_contract()` converts). Mixing the two makes the rack deaf without error. |
| `quirks.note_edges` | `clean` (press = Note on, release = Note off) or `paired` (both edges arrive as Note off; the reader rebuilds press/release by pairing). Declared, never guessed: applying pairing to a clean device inverts gestures. |
| `quirks.note_base` | offset between the chip's Note numbering and the intention's switch numbers |
| `quirks.thru_echo` | the chip echoes its MIDI IN to its OUT (UnO2, not disableable) |
| `quirks.display_base` | how the chip's display numbers banks (0 or 1). Sent to the app as `state.bank_base`; `bankNo()` in `app/lib.js` formats every slot number on screen with it. Formatting only: the wire and the API stay in slots 0–18. |
| `capabilities.identifies` | answers the identity probe |
| `capabilities.gestures` | can deliver per-switch press/release edges |
| `capabilities.goto_bank` | `{supported, channel, controller, index_base}` — the rack can move the chip to a bank |
| `capabilities.remote_press` | `{supported, channel, pc_base}` — the rack can press a switch remotely (LED alignment, §7) |
| `capabilities.load` | `wire`, `wire+foot`, `none` (descriptive) |
| `transport` | where the device arrives (§5) |
| `load` | `{recipe, label, hint}` — the load recipe **name** and its button text (§6) |
| `install.phases`, `verify` | the step-by-step procedure shown in the generic stepper, and the checks |
| `bindings` | learned devices only (§8) |
| `provenance` | `{source, confidence, note}` |

`tools/check-descriptors.py` validates descriptors (ids, bounds, known gestures, `transport.kind`,
`port_match` required for `usb`, French text in UI fields). It does not say whether a table is
true: `provenance.confidence` carries that, and only a foot test answers it.

**Provenance vs measured.** Two different questions: *measured / declared* says whether this chip is
the one plugged in; `provenance.confidence` says whether the file's content is trustworthy. A
descriptor written from a manufacturer's manual must not look like one proven by foot.

### Shipped devices

| | `fcb1010-uno104` (UnO 1.0.4) | `fcb1010-uno2` (UnO2) |
|---|---|---|
| Contract channel | 1 | 2 (channel 1 is the Whammy's; the THRU echo forced the split) |
| Note edges | `paired` | `clean` |
| Identifies | no | yes (type 8, firmware, serial) |
| Load | frozen `.syx` dump + settings by foot (`uno104`) | compiled, everything over the wire (`uno2`) |
| Switch species | no | `preset` / `effect` / `trigger`, exclusive |
| Goto bank | no | yes (CC 0, channel 16, `index_base: 1`) |
| Remote press | no | yes (PC `switch-1`, channel 16) |
| Display | 00–18 | 01–19 (`display_base: 1`) |

`goto_bank.index_base: 1`: the chip numbers banks from 1 like its display, the rack counts slots
from 0; sending 3 lands on display `03`, i.e. slot 2.

## 4. Detection — probe first, declared fallback

The UnO2 answers the universal identity request `F0 7E 7E 30 F7`; the 1.0.4 answers nothing.
**Silence identifies nobody: it only rules out the UnO2.** Hence (`pedalboard.active()`):

1. **Measured** — a probe got a reply: that device, with firmware and serial.
2. **Declared** — otherwise the device chosen in `config/.pedalboard.json` (`declared`), default
   `DEFAULT_DEVICE = "fcb1010-uno2"`.
3. **Fallback** — no descriptor readable: `FALLBACK` (channel 2, clean edges).

`active()["source"]` is `measured | declared | fallback`; the screen always shows which.

- `probe()` runs at bridge start and when a USB device is plugged (`detect_async()`, called by
  `monitors._poll_hotplug`; non-reentrant). It sends through `midi_out` and listens on a separate
  rtmidi port under Linux; on Windows/macOS it reads SysEx through the reader already connected to
  the native port (`foot.native_sysex_stream()`). Timeout `PROBE_TIMEOUT = 2.0` s per candidate.
- **No reply keeps the last measurement**, marked `stale` with `last_fail`. A stale measurement may
  get the name wrong; falling back to the declared device would get the **channel** wrong, which
  makes the pedalboard dead and lets the Whammy's THRU echo on channel 1 act as foot presses.
- `select(id)` (`POST /api/pedalboard/select`) declares a device and **clears** the probe: an
  explicit declaration always wins.
- `POST /api/pedalboard/detect` re-runs the probe.
- Every change calls the `on_change` callbacks; `foot.py` reconfigures its reader (`set_device()`).

The probe is the only round trip in the system. `_link_proven()` = source `measured` and not
`stale`. Anything that sends orders **to** the chip (goto bank, remote press) requires it, because on
a rig with one DIN output the cable may lead to the Whammy instead.

## 5. Transport — where the pedalboard arrives

Optional descriptor field, resolved by `foot.resolve_port(listing, transport, card_name)` (pure,
tested):

| Declaration | Behaviour |
|---|---|
| absent or `{"kind": "din-soundcard"}` | the DIN input of the active sound card (default) |
| `{"kind": "usb", "port_match": "<ALSA name fragment>"}` | the device is its own port, found by `port_match` in `aseqdump -l` |

A missing port returns `None` and the `_supervise` loop retries (unplugged device, empty pattern):
never a crash. A transport change (probe or `select()`) makes `set_device()` kill the current
`aseqdump`, and the loop reconnects to the right port. The channel filter applies whatever the
transport. The `usb` transport has not been exercised with real USB hardware: to validate, read the
device name in `aseqdump -l`, declare `transport`, check `/api/state` sees presses, then
unplug/replug.

**Channel filter.** The reader listens only to the contract channel. The UnO2 echoes everything
received on MIDI IN to MIDI OUT; with the sound card OUT wired to the pedalboard IN, the Whammy's
orders come back. The Whammy keeps channel 1, the pedalboard uses channel 2.

## 6. Loading the chip — recipes

`POST /api/pedalboard/load` loads the intention into the active device by **its** recipe: the
descriptor declares `load.recipe`, `_LOAD_RECIPES` in `bridge/routes_system.py` resolves it.

| Recipe | Device | What it does |
|---|---|---|
| `uno2` | UnO2 | `tools/fcb/flash_uno2.py` (Linux); `_flash_uno2_native()` on Windows/macOS — compiles the contract into the chip's memory image and sends it |
| `uno104` | UnO 1.0.4 | sends the frozen dump (`tools/fcb/gen_golem_syx.py`, 2352 bytes); the pedal must be in Global Configuration with SysEx receive armed |

A new device = a descriptor + one entry in the table. An unknown or absent recipe (learned device,
`load: none`) is refused with 400. **A recipe is trusted code**: the descriptor only chooses a
**name**; letting an imported file carry a command would let it run anything on the rack.

`GET /api/pedalboard` returns `summary()` plus `load_mode` (`editor` on macOS, `wire` elsewhere),
`ports_held` and `os`. On Windows/macOS the official editor (FCB UnO Control Center) is the fallback:

- `GET /api/pedalboard/setup-text` — the setup as text to paste in the editor, decompiled from the
  same setup as the binary and refused (500) if reading it back does not give the binary bit for bit
  (`tools/fcb/uno2_text.py`).
- `POST /api/pedalboard/hold {on}` — release/take back the pedalboard MIDI ports so the editor can
  open them; auto-released after `foot.HOLD_MAX_S` (15 min).
- `POST /api/pedalboard/flashed` — "I flashed it": records `presets/.uno2-flashed.json` like a wire
  flash (marked `source: "editor"`, a user declaration, not a chip acknowledgement) and takes the
  ports back.

## 7. Switch species, claims and LEDs (UnO2)

**Edge switches.** `pedalboard.edge_switches()` = the switches that really deliver press **and**
release: the scene row always (compiled as `preset`, whose off face is a real Note off) plus, if the
device has `gestures`, the stomps the intention marks `gestures`. Others (stomps compiled as
`effect`) keep a status LED at the cost of their release: their "off" face is a second press. The
reader never runs a long-press timer on a non-edge switch.

**Claimed scene-row switches get an on/off LED.** When a preset reserves SW2–5 for an on/off block,
that switch becomes a toggle with an LED, like a stomp.

- The rule lives once in the rack: `bridge/store.py` `claim_species()` / `toggle_claim_switches()`.
  On/off: Rec, Click, Tuner, Whammy, a chain block, and Rec + Backing (the take). With gestures:
  backing alone, sample, drums, standard, arrangement, compo — they keep species `preset` and both
  edges. The select switch is never claimed (its long press needs the release).
- The chip: `gen_uno2_syx.build(claim_slots=…)`. In the affected banks only, those switches go from
  `preset` to `effect`; both faces send **PC + the scene CC, 127 then 0**, no Note. Without claims
  the binary is bit-identical; `tools/fcb/check-uno2.py` checks this and the looper + claim case.
- **The rack reads a state only for what is really flashed**: `flash_uno2.py` writes
  `presets/.uno2-flashed.json` after a successful flash, and `_on_foot_scene` treats 127 = on /
  0 = off only for switches listed there. Never deduced from the preset: a claim changed without
  reflashing would otherwise make "127 = on" forever and a take could never be stopped. No file →
  toggle. An absolute order also realigns LED and rack after a refused take (disk full).
- **Reflash** when a preset of the pedalboard setlist takes or releases SW2–5 for an on/off block;
  `check-uno2.py` says whether the chip is up to date. **Way out:** `flash_uno2.py --write
  --no-claims` gives five scenes back to every bank.
- Cost: no release on that switch, so no long press or double tap.

**Stomp LEDs follow the scene** (`bridge/foot_leds.py`). An `effect` LED is a toggle local to the
chip; the rack aligns it by **remote press** (`capabilities.remote_press`: `ProgramChange(switch-1)`
on the remote channel, firmware ≥ 1.3), which the chip answers with the same `CC + Note` a foot
press would send.

- After each change of `state.stomps` (scene, preset, stomp from the screen), `request_align()`
  (debounced 80 ms) compares the believed LED with the wanted state (`app.py::_led_desired`) and
  presses the switches that differ. An unknown LED (rack restarted) is pressed anyway: the sound
  never moves, at worst it blinks once.
- The **echo is swallowed** (otherwise a switch carrying two blocks would switch both on) and
  **tells the truth**: its value corrects a wrong belief, and the rack re-presses once — only when
  the full echo (CC + Note) came back within `ECHO_WINDOW_S` (0.6 s).
- Not aligned: stomps with `gestures` (and the looper bank's), switches driven by edges (sample,
  drums, standard, arrangement, backing, looper), services (tuner, Rec, Click, compo), claimed
  scene-row switches, and everything when the link is not proven by the probe.

**Goto bank.** `pedalboard.goto_bank(slot)` aligns the chip on a slot (e.g. after a numeric select
or a screen recall), so the next scene press does not send the old PC back. The caller decides when;
the rack never realigns against a PC the foot just sent. `_BELIEVED["slot"]` is written only from
facts: an incoming PC from the pedalboard (`note_foot_bank`), or an order sent while the link is
proven. `POST /api/pedalboard/goto` is the bench entry point.

## 8. Learning an unknown pedalboard

Many controllers cannot be programmed to the golem contract — some only send Program Changes
(e.g. ENGL Z9, Diezel Columbus: no CC, no release, so no long press or expression), others are fully
programmable (Morningstar MC8, Nektar Pacer, Singular Sound MIDI Maestro). Learn mode does not
configure the device: it **records what it sends and assigns a role**. With ten PCs, the user chooses
between scenes + stomps and setlist slots; not both.

| Endpoint | Effect |
|---|---|
| `POST /api/pedalboard/learn/start` | opens listening on **all channels**; the pedalboard **stops driving the rig** meanwhile |
| `GET /api/pedalboard/learn/live` | last event + summary per message (a switch sends two values, an expression pedal sweeps many: the role can be guessed) |
| `POST /api/pedalboard/learn/stop` | closes listening |
| `POST /api/pedalboard/learn/save` | `{name, channel, bindings:[{event:{type,channel,number}, intent:{kind…}}], edges?, note?}` → `save_learned()` writes `devices/<slug>.json` (never overwrites), provenance `measured`, `load: none`, and selects it |

Binding intents handled by the reader: `scene`, `stomp`, `slot`, `expression` (`foot.py`,
`_BOUND` index built by `set_device()`). The two FCB descriptors have no `bindings` and use the
compiled intention.

## 9. The screen

Settings ▸ Gear ▸ **Pedalboard** (`app/page-pedalboard.js`, deep link `#/system/gear/board`)
is a reader of `GET /api/pedalboard`; it knows no model:

- header: the active device, *measured* (firmware, serial, stale) or *declared*, a device menu,
  re-detect, "Teach a new pedalboard…";
- the contract rendered from data (channel, scenes, stomps, expression), the capabilities as they
  are (what a device cannot do is shown, not hidden), `unmet_gestures`, the provenance;
- the install procedure (`install.phases`) in the generic stepper and the load button, both labelled
  by the descriptor;
- the expression pedal roles (golem routing, no reflash).

## 10. Gestures table — `config/pedalboard/gestures.json`

For each block type with foot behaviour (`backing-track`, `take`, `sample`, `drums`, `standard`,
looper, arrangement…), per state: a list of `{g, icon, text, s}` where `g` ∈ `signs` (`tap`,
`double`, `hold`, `longhold`), `icon` is the glyph drawn on `/live`, `text` the English sentence of
the Designer's MIDI assign tab, `s` the duration in seconds when the gesture has one.

This file **describes**; the bridge **acts** (`backing.py`, `looper.py`, `sample.py`, `drums.py`,
`standards.py`, `arrangement.py`, `foot.py`). `tests/test_gestures_table.py` ties each duration to
the code constant, so a threshold changed on one side breaks the test instead of lying on screen.
Served by `GET /api/gestures` (plus `select_switch`), read by `app/gestures.js`.
