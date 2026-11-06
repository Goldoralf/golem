# Calibration — learning the gear, on the rack, without code

> **Status: PARTLY CODED** — the Calibration tab (controllers, pedals, pedalboard, drums), learned profiles and descriptors, pad-channel programming, and cross-OS device keys are built; sharing calibrations by device model through golem.fm is not.

The probe ([gear-registry.md](gear-registry.md)) makes a device **work**; calibration makes it
**known**: ranges, assignment tables, capabilities — learned by the user on the rack, never
hard-coded in development.

## 1. The tab

Settings ▸ **Gear** (`app/page-pedalboard.js`, deep link `#/system/gear/<sub>`; the former
`#/system/pedal/<sub>` redirects), where these four sit next to Soundcard:

| Sub-tab | Content | Writes |
|---|---|---|
| **Controllers** | USB keyboards/pad controllers: calibration stepper, profiles, pad channel | `config/controllers/<key>.json`, `config/knobs.json` |
| **Pedals** | controlled MIDI pedals (Whammy DT…): catalogue, mapping verification, new-pedal wizard | `mappings/<id>.json` — [pedal-registry.md](pedal-registry.md) |
| **Pedalboard** | foot controller: device, contract, load, learning, expression roles | `config/pedalboard/…` — [pedalboards.md](pedalboards.md) |
| **Drums** | electronic drum modules (USB-MIDI): pad-by-pad measurement | `config/drumkits.local/<id>.json` — [drums-kit.md](drums-kit.md) |

Out of scope: the **sound card** (its flow is adoption, [gear-registry.md](gear-registry.md)); a drum
module plugged into the sound card's **DIN** (that port is the pedalboard's).

## 2. Listening through REAPER

REAPER holds the MIDI devices it opened; while it does, nothing else can listen (`aseqdump` gets
"Resource temporarily unavailable"). So learning goes **through REAPER**, on on-demand listening
tracks created by `reaper/Scripts/golem_drumlearn.lua` on the command `{action: "drumlearn", on,
dev, tap}`:

| Track | Tap JSFX | Used by | Output |
|---|---|---|---|
| `KeysLearn` | `knob-tap.jsfx` (notes, CC, pitch bend, note channel) | Controllers stepper | `golem-learn.json` (runtime dir) → `GET /api/calibrate/live` |
| `DrumLearn` | `drum-tap.jsfx` | Drums stepper | gmem `golem_drumlearn` → `golem-drumlearn.json` → `GET /api/calibrate/drums/live` |
| `SysexIO` | `sysex-io.jsfx` (device as input **and** hardware output) | pad-channel programming | gmem `golem_sysex` |

Rules (REAPER pitfalls listed in the repository's CLAUDE.md): listening tracks are **armed with
`I_RECMODE = 2`** (an unarmed service track leaves REAPER's live graph and its `@block` stops); each
loop **re-attaches** its gmem space every tick; the drum tap uses its own gmem space so it never
writes over the Keys lane's `golem_knobs`. Track names match no purge pattern of `golem_rig`.
REAPER does not pass MIDI clock (0xF8) to track FX, so clock cannot be measured this way.

Routes (`bridge/routes_dev.py`): `POST /api/calibrate/keys/start {device}` / `…/keys/stop`;
`POST /api/calibrate/drums/start {port | device}` / `…/drums/stop`. A device not plugged → 409.

## 3. Controllers

### Stepper

The Controllers listening track does not depend on the loaded preset having a Keys lane. Steps, each
skippable:

1. **Identity** (automatic): VID:PID, name, ports.
2. **Keyboard**: lowest key → highest → middle C (range + reference). The note **channel** is
   recorded.
3. **Pads**: on-screen grid, "hit pad N" → note↔pad table; the pads' channel is recorded.
4. **Knobs**: "turn K1"… → CC↔position table.
5. **Extras**: sustain (CC 64), pitch wheel, mod wheel; the **arpeggiator is verified, not
   detected** ("turn the arp on, hold a note": golem checks notes arrive in time with its clock).
6. **Save** → `POST /api/controllers/profile` → profile + immediate application (`golem_knobs` is
   reloaded).

### Profile — `config/controllers/<key>.json` (local state, git-ignored)

`{usb, name, keys{lo, hi, middle}, pads[…], knobs[…], caps{arp, sustain, pitch, mod},
channels{keys, pads}, calibrated}` — `bridge/controllers.py`.

- `save()` also writes the active consumer `config/knobs.json` (bankA, `kb_range`, `kb_name`;
  git-ignored, seed `config/knobs.default.json` used when absent). Pads and caps wait for consumers.
- A calibration that did not measure channels (Pads skipped) **keeps** the previous `channels`:
  otherwise Keys-lane channel sorting would stop silently.
- A partial update (channels only, `stamp=False`) does not pretend to be a calibration and does not
  touch `knobs.json`.
- A calibrated controller becomes a known device in `config/devices.json`.
- `GET /api/controllers` lists plugged USB MIDI controllers with their profile (null = never
  calibrated).

### Pads on their own channel

Factory-set, some controllers send pads and keys on the same channel with overlapping notes, so no
software can tell a pad from a key. The only real separation is **inside the controller**.

1. **Measure** — the stepper records the channel of notes during Keys and Pads.
2. **Correct** — same channel: the stepper says so. If the **model** has a descriptor
   (`config/controller-models/<id>.json`, versioned, `program.kind: "sysex-dump"`: read request,
   length, header, byte offsets of pad channel / key channel / pad notes, `stored` program and
   `working` memory), **"Give the pads their own channel"** → `POST /api/controllers/pads-channel`
   → `bridge/controller_program.py`: read → keep the original (`presets/.controller-backup.json`,
   never overwritten) → write pads on channel 10 with GM notes in MPC placement
   (`kits.DEFAULT_NOTES`: A low 36 38 42 46, A high 39 37 45 49, B low 35 44 41 48, B high 51 57 53
   56) → **read back** → write the same into the working memory (writing the program stores it, but
   the controller keeps playing the old setting) → channels into the profile; then the stepper asks
   to hit pad 1 again. Without a descriptor (409): set it in the maker's editor, then recalibrate.
   **A new model = a descriptor, not code**; `tests/test_controller_program.py` checks every shipped
   descriptor. Shipped: AKAI MPK Mini Mk II (verified).
3. **Sort** — only when the profile knows two **different** channels (`controllers.channels_for`,
   set by `compile_rig` as `midi_ch` on the lane; `recall.scene_shape`). Otherwise all channels (a
   blind filter would mute another controller's pads):
   - instrument + pads: the lane unfolds into a folder, keys channel → instrument, pads channel →
     pads; audio FX of the lane go on the sum (`merge`);
   - instrument only: the track input listens to the keys channel; pads only: the pads channel.

Pad kits, grooves and golem.fm all speak General MIDI.

## 4. Pedals

- **Catalogue first**, the wizard last ([pedal-registry.md](pedal-registry.md)).
- **Mapping verification**: golem sends the mapping's PCs one by one (`POST /api/calibrate/midi`:
  `{pc}`, `{cc, val}`, `{sweep_cc}`, `channel`), the user confirms what the pedal shows (✓/✗); the
  verdict goes to `provenance.verified_here` (`POST /api/pedals/{id}/verify`).
- **New-pedal wizard**: "I send PC n, what does the pedal do?" → the user names the mode or skips →
  `mappings/<id>.json` (+ treadle CC tested by sweep). Feasible without ever having seen the pedal:
  golem emits, the human observes.

## 5. Drums — the module is a rack fact, and it is measured

A drum module is chosen **once, in Calibration**, not in the Soundcard page and not in a patch: a
song does not know which kit is plugged, the rack does. Only measurement produces true data —
declared descriptors were found wrong on hi-hat CC, positions, choke and notes.

### Tab

Lists USB-MIDI devices bound as `drums` (Soundcard), plus unbound ones with "this is a drum module".
Per module: USB name, descriptor identified by name (`drumkits.identify`), a provenance badge
(✓ verified · ~ reported · ? unconfirmed, same as Pedalboard), and **Measure**.

### Stepper

One question per element: kick, snare, snare rim, toms 1–4 and rims, hi-hat closed / open / half /
pedal / splash, crash 1 + choke, crash 2, ride, bell. "Hit the kick" → the cell lights with note and
velocity; **skip** (element absent); **redo**; two strong notes in one gesture → said; a very weak
hit → said (real zone or crosstalk?).

The tap keeps a **timestamped ring buffer** (32 events: note on, CC, poly aftertouch) because one
gesture produces several events (closing the hi-hat = aftertouch burst + pedal "chick" note, and the
hit later). Rule: **the hit is the loudest note of the gesture**; a **splash** takes the first note.

Review screen = comparison with the descriptor (✓/✗/⚠ per element, hi-hat, choke, channel) →
**Save as measured** (`POST /api/drumkits/measure {measure, kit?, dry?}`; `dry: true` = review only).
Shared analysis in `bridge/drumlearn.py`; since the stepper knows which step each event belongs to,
it decides:

- `hihat.positions` = 3 if half-open gave a note distinct from open, else 2;
- `hihat.cc` = the CC seen during hi-hat steps, else `null` (switch pedal);
- `choke` = `poly-aftertouch` only if aftertouch arrived **during the choke step** (aftertouch from
  the hi-hat pedal elsewhere is not a choke), else `none`;
- `map` = measured elements only; declared rows never received go to `provenance.reported_map`, the
  old note to `provenance.reported_note`; `source: measured`, `confidence: verified`, `measured_at`,
  `measured_on`.

Guards: a **derived** element (rim, bell, half-open, splash) on the note of a base element = same
pad, dropped; two **base** elements on one note = contradiction, **nothing is written** (409). An
unknown module gets a new descriptor from the measurement.

Storage: seeds by model in `config/drumkits/` (versioned); a measured kit is written to
`config/drumkits.local/<id>.json` (local) and wins over the seed of the same id
(`drumkits.LOCAL_DIR`).

Consequences elsewhere: **"Add a drum kit"** reads the calibrated module (USB port bound as drums →
its descriptor) and only asks what is wired and where each element lands; without a calibrated
module it says so and links to Calibration ▸ Drums. `drumset_module` stays in the patch as a
**memory** ("made on <module>"); the rack's calibrated module always wins, and a mismatch is shown.
Soundcard ▸ Kit is read-only with **Calibrate**.

`tools/check-drums.py` (headless, SSH) shares `bridge/drumlearn.py` and picks its transport itself:
`aseqdump` if the port is free, the REAPER listening track otherwise.

## 6. Portability between machines and operating systems

| Calibration | File | Scope |
|---|---|---|
| Controller | `config/controllers/<key>.json`, `config/knobs.json` | local |
| Controlled pedal | `mappings/<id>.json` | local |
| Pedalboard (learned) | `config/pedalboard/devices/<id>.json`, `config/.pedalboard.json` | descriptor / local state |
| Drum module (measured) | `config/drumkits.local/<id>.json` | local |
| Expression pedal roles | `config/pedals.json` | local (no travel calibration) |
| Controller models, drum kit seeds, shipped pedals | `config/controller-models/`, `config/drumkits/`, `library/pedals/` | versioned |

**What travels as is — it is MIDI**: notes, CC, channels, PC numbers, ranges, learned bindings, drum
maps. The pedalboard works on Windows unchanged; only the port changes.

**What must be re-resolved on each machine — the port identity**:

| | Linux | Windows |
|---|---|---|
| USB identity | VID:PID from `/proc/asound/cardN/usbid` | VID:PID from the device manager (`desktop_midi.usb_ids`) |
| device name | ALSA name | WinMM name (prefixes like "2- " stripped) |
| pedalboard DIN in/out | `aseqdump`, card name | `config/midi-ports.json` (chosen on screen) |
| card, channels, buffer | `hw:<id>`, ALSA | `asio:<driver>` numbering |
| UnO2 flash state | `presets/.uno2-flashed.json` (per machine) | same |

**One device, one profile**: `controllers.load(usb, name)` reads every profile matching the device
(`devices._match`: equal VID:PID when both have one, else one name contained in the other) and
returns the most recent; `save()` drops twins; `consolidate()` re-files the newest under the VID:PID.

**Not built — a calibration store by device model.** The intended shape: key `{vid_pid?, per-OS name
aliases[]}` (like `identity.usb_names` of drum kits), resolved by each rack to its own port; three
owners — per **model** (shareable, opt-in: controller profile, pedal mapping, kit, pedalboard), per
**musician/band** (private: which models they own, their roles, "verified here" verdicts), per
**rack** (never synced: ports, chosen DIN, card, buffer, flash state). Packages built from a
whitelist, never a tar of `config/`; nothing leaves with a name without an explicit gesture
([identity.md](identity.md)). Today no calibration is pushed to golem.fm; see
[golemfm-protocol.md](golemfm-protocol.md) for what is exchanged.

**Admin only**: the pedalboard routes that change the chip or the device (`/api/pedalboard/load`,
`hold`, `flashed`, `select`, `learn/save`) require an admin device or the rack's own screen
(`bridge/auth.py`).
