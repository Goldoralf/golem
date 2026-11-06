# Cards seen from golem.fm, and monitor returns

> **Status: PARTLY CODED** — the rack publishes every relevant card's input/output map in its heartbeat, accepts remote edits through the `inputmap-set` job, and lets an output carry a person and a return type; the rack actually mixing per-person returns (per source × destination levels) is not built.

The wire format of the heartbeat and of jobs is in [golemfm-protocol.md](golemfm-protocol.md); this
page says what the rack puts in them and which rules apply. The input map itself is in
[input-map.md](input-map.md).

## 1. Outputs carry a person and a type

Output roles include `iem` (In-ear) and `wedge` besides `monitors`, `pa`, `amp`, `click`, `other`.
An output may carry `person` (a roster handle) and `type` (`iem` | `wedge`):
`inputmap.set_out_person()`, `POST /api/inputmap {kind:"output", ch, person?, type?}`.

It is a **declaration** — for a technical rider, and the future target of a per-person mix. It lives
in the card's input map, so it follows the card, and the mode that declares that card.

## 2. Heartbeat content (`bridge/rigstatus.py`)

`rigstatus.light()` is pushed as the heartbeat. Fields relevant here:

### `cards[]` and `patch_version` — `cards_doc()`, `patch_version()`

Which cards: those a **mode declares** (`modes.card_of`), the **active** card, and those **plugged**
(max 8). The heartbeat, not a job, because the rider must be right while the rack is off.

```json
{"card": "hw:XR18", "name": "Behringer X Air XR18", "connected": false, "active": false,
 "operational": null, "operational_why": null,
 "modes": ["rehearsal", "gig"],
 "inputs":  [{"slot": "IN 1", "kind": "audio", "role": "guitar", "nth": 1, "name": "Guitar 1", "pair": null, "person": "<handle>"},
             {"slot": "USB 1", "kind": "midi", "role": "drums", "device": "<USB device>", "person": null, "guest": true}],
 "outputs": [{"slot": "OUT 1-2", "role": "pa", "type": null, "pair": "1-2", "person": null},
             {"slot": "OUT 3-4", "role": "iem", "type": "iem", "pair": "3-4", "person": "<handle>"}],
 "usb_ports": 4, "midi_in": "fcb", "midi_out": "whammy-dt",
 "midi_in_device": "Volt 276", "midi_out_device": "Volt 276"}
```

- `patch_version` = short hash of `cards`, so the other side does not re-diff.
- **Guests leave without their name**: `{"person": null, "guest": true}` (`_who`), same whitelist as
  `inputs`.
- **`connected`** uses each system's key: `hw:<id>` on Linux, `asio:<driver>` on Windows,
  `coreaudio:<name>` on macOS. A registry card `hw:<id>` is also connected when its USB device
  (`config/cards/<id>.json` → `usb`) is present. A card's identity is still **per system** (two map
  files for the Volt under Linux and Windows); `cards.same_card()` links two names by USB identity
  (`hw:<id>` via the registry, `asio:<native driver>` via `provision/desktop.KNOWN_USB_ASIO`, macOS
  via `system_profiler` — the macOS path is untested on hardware). Merging the two maps is not built.
- **`operational`** — only for the engine's card: `true` = plugged, opened, the audio thread advances
  (`state.audio`, the `golem_clock` counter) and REAPER's scripts answer; `false` +
  `operational_why` ∈ `not plugged in` · `audio engine not running` · `REAPER stopped listening` ·
  `no audio (the engine stopped processing)`; `null` for a card the engine does not use. An input
  with role `none` is not a fault. There is no per-input signal measurement.
- `midi_in_device` / `midi_out_device`: the OS MIDI port behind the DIN jacks (engine card,
  Windows/macOS).

### `engine` — `engine_doc()`

What the engine **really** opened, distinct from `cards[].active` (declared): `{mode, device,
samplerate, bsize, inputs, outputs, input_names, output_names, latency_ms, latency_source}`.

### `health` — `health_doc()`

`{cpu_pct, ram_used_pct, ram_total_mb, temp_c, xruns_total}`; `temp_c` is null outside Linux; the
CPU is sampled for 0.25 s every 5 min. The rack does not read headphone, Hi-Z, line/mic or 48 V
state.

### `controllers` — `controllers_doc()`

`[{id, name, kind, usb, calibrated, connected, active, where, role}]` (max 24). Read from: known USB
MIDI devices (`devices`), calibrated profiles (`controllers`), **measured** drum-kit descriptors
(`drumkits`, confidence `verified`), the pedalboard (`pedalboard.active()`), controlled pedals
(`mappings/*.json`). `kind` ∈ `keys`, `pads`, `keys-pads`, `drums`, `pedalboard`, `pedal`,
`controller`. `connected` is null when nothing can tell (DIN output). Unmeasured factory descriptors
are not listed: they are not this rack's controllers.

## 3. Remote edit — job `inputmap-set` (`tones_jobs._inputmap_set`)

```json
{"action": "inputmap-set", "card": "XR18",
 "entries": [{"slot": "IN 3", "role": "voice", "nth": 1, "person": "<handle>"}, {"slot": "USB 1", "role": "drums"}],
 "outputs": [{"slot": "OUT 3-4", "role": "iem", "person": "<handle>", "type": "iem"}],
 "pairs":   [{"kind": "input", "a": "5", "b": "6", "linked": true}]}
```

It goes through **the same functions as the screen** (`inputmap.set_role / set_nth / set_person /
set_out_person / set_pair`), so the same refusals apply: unknown instrument or destination, MIDI
role marked "soon", number already taken (unique per role across audio + USB), unbound USB port, a
USB port only carries keys / pads / keys-pads / drums. Three more guards exist because the caller is
remote:

1. **All or nothing.** One refusal = nothing written: the touched files (the card's input map,
   `config/devices.json`) are restored, and the ack says `refused, nothing written: <slot>: <why>; …`.
2. **`person` must be a roster handle** (`config/.band.json`), never a `guest:` created from the web.
3. **The active card is not rewired** during a take (`state.perf.recording`), a song
   (`backing.playing`, `arrangement.running`) or a locked mode. A non-active card (the gig card,
   prepared days before) is written unconditionally.

An unknown card is refused: declare it on the rack first (`POST /api/cards/declare`,
[gear-registry.md](gear-registry.md)). Ack: `{card, applied[], cards[], patch_version}`; the next
heartbeat is sent right away (`push_soon`). Tests: `tests/test_returns_r1.py`.

## 4. Returns: declaration vs mixing

- **Declaration (rider)** — kept by golem.fm per band and venue: who has a wedge or an in-ear and
  what they want in it. With a house console, **the venue does the monitors**: the rack only declares
  what it outputs (`outputs[]` of the gig card). Outputs carrying `person` + `type` pre-fill it.
- **Mixing by the rack — not built.** Only possible when the rack holds the outputs (a multi-output
  card or a console's aux buses). It requires the mixer to move from one level per source to one level
  per (source, destination) — N hardware sends per track instead of one ([mixer.md](mixer.md) §6) —
  with the engine rule: **click and backing go only to `iem` / `wedge` / `click` destinations, never
  to `pa` or `monitors`** in a gig. To be designed with the multi-output hardware plugged and measured.
