# Blocks: doctrine and catalogue declarations

> **Status: CODED** — how a block type is declared in `library/catalog/effects.json`, what each
> declaration does in the rack, and the rules every block follows (service lanes, scenes, foot,
> quarantine, captures).

Related: [preset-format.md](preset-format.md) §4 (block fields in a preset) · [looper.md](looper.md) ·
[arrangement.md](arrangement.md) · [drums-kit.md](drums-kit.md) · [standards.md](standards.md) ·
[samples-backings.md](samples-backings.md) · [block-status.md](block-status.md) ·
[plugins.md](plugins.md) · [spectral.md](spectral.md) · [pedalboards.md](pedalboards.md).

---

## 1. Principle

**Inserting a block is the universal gesture**: Designer drawer → the block lands in a lane → saved in
the preset like everything else. This holds for effects, instruments (Vital, piano, pads, drum kit) and
services (looper, backing, rec…). Three kinds of blocks:

| Kind | What it does | Where it lives | Examples |
|---|---|---|---|
| **Chain block** | transforms the signal; position matters; on/off and params per scene | a lane's chain (`pre`, split branches, `post`) | drive, amp, delay, Vital |
| **Service block** | runs outside any chain on dedicated REAPER tracks or system JSFX; the block is a **marker** (`engine: virtual` or `mode`) carrying UI and foot assignment | `preset.config` lanes (§3), or a signal lane for the tuner | looper, backing-track, sample, drums, standard, rec, click, compo, tuner |
| **Conductor** | no audio at all; commands scenes, stomps and samples at written times; never invents a sound; the foot can always override it (last writer wins) | `config.arr` | arrangement ([arrangement.md](arrangement.md)) |

**Content lives in the library, not in the block.** Like an amp block references a capture (`ref`), an
instrument block references a library object through its `content_param` (Vital preset, pad kit, sfz,
DX7 bank, drum kit). The same mechanism gives "a different sound per scene" for free.

## 2. Catalogue declarations (`effects.json` → `effects[]`)

`catalog_version` (integer) is bumped whenever the vocabulary changes; it is published in the heartbeat
and golem.fm re-fetches the catalogue (`rigstatus.catalog()`, job `push-catalog`) when it changes. The
catalogue row is the authority for golem.fm's drawer and AI vocabulary: `rigstatus.catalog()` sends
`type, name, category, params, quarantine` plus, when present, `roles, foot_mode, input_claim, icon,
glyph, short, color, unique, engine, scene_invariant, content_param, foot_scene_claim, note`. Keys
starting with `_` are comments and are never sent.

### 2.1 Block-level keys

| Key | Values | Effect (read by) |
|---|---|---|
| `type` | id | block type, the `type` of a block in a preset |
| `name`, `short`, `glyph`, `icon` | strings | labels; `short`/`glyph` on tiles and `/live` |
| `color` | hex | the block's colour (drawer and chain read the block colour first, then the category) |
| `category` | `dynamics, preamp, drive, lofi, filter, amp, cab, eq, modulation, delay, reverb, pitch, utility, drums, keys, pads, hardware` | drawer section; `blockstatus.alternatives` (Replace offers the same category) |
| `engine` | `plugin` (default), `midi`, `rs5k`, `drumkit`, `b3`, `sfizz`, `dexed`, `virtual`, `mode` | how `golem_rig` materialises it. `virtual` = pure marker, never materialised; `mode` = marker that switches a runtime mode (looper, click). `blockstatus.is_plugin_block` judges only `plugin` |
| `plugin` | REAPER FX name | first name `golem_rig` tries (`TrackFX_AddByName`), then `ADD_ALIAS` in `golem_rig.lua`, then the type (`blockstatus.candidates`). Desktop overrides: `effects-windows.json`, `effects-macos.json` |
| `params[]` | §2.2 | knobs |
| `unique` | bool | at most one per preset: the drawer greys the entry ("already in this preset (unique block)"), `addBlock` refuses (`app/designer-drawer.js`, `page-designer.js`) |
| `scene_invariant` | bool | never bypassed or changed by a scene change (a recorded loop survives the chorus); the Designer does not offer per-scene on/off for it (`page-designer.js`) |
| `foot_scene_claim` | bool | may be assigned to a **scene-row** switch (1–5), replacing that scene slot for this preset: the `/live` tile becomes the service tile and the FCB press is routed to the service (`store._scene_claims`, `app.py`). The pedalboard MIDI contract (scene CCs) is unchanged; the bridge does the routing. The Designer only offers 1–5 to these blocks (`designer-pedalboard.js`) |
| `foot_mode` | `transport` (looper), `sample`, `drums` | the block is driven by press/release **gestures**, not a CC toggle. `transport` = the block owns its switch table and is never placed on a single switch (`designer-pedalboard.js`, [looper.md](looper.md)) |
| `foot_suggest` | switch number | proposed switch for the block (tuner: 5). **Declared but not read by the current code**: no pre-filled Assign on insertion |
| `input_claim` | `keys`, `pads`, `drums` | the input slice an instrument takes on a MIDI lane (keys of the controller, its pads, a drum module). Published to golem.fm; on the rack, uniqueness is enforced by `unique` and the MIDI-lane instrument list (`KEYS_TYPES` in `page-designer.js`), not by reading this key |
| `roles` | list of lane roles | the block is offered only to these roles (`blockstatus.alternatives`, drawer). Absent = every role allowed by `role_categories`/`role_blocks` |
| `content_param` | param id | the param that references a library object (`preset`, `kit`, `sfz`, `bank`) — `designer-model.js` handles it generically |
| `conflicts` | list of types | cannot coexist in a preset (Standard vs backing-track and drums); checked both ways in the drawer |
| `loads` | `nam_model`, `ir_cab` | the block loads a capture file (shown in Library ▸ blocks: "Loads a capture") |
| `defaults` | `compile` | catalogue defaults are written at compile time (`compile_rig._fill_compile_defaults`) |
| `knobs` | list | instrument knob mapping read by `compile_rig` (Vital, E-Piano) |
| `midi` | object | MIDI vocabulary of an external pedal (whammy-dt) |
| `unsupported` | bool | the plugin cannot be used: `blockstatus` reports it unavailable, `golem_rig` skips it |
| `quarantine` | string (the measured reason) | **§6** |
| `bench` | `pending` | informational: not yet benched. Not read by the rack |
| `note`, `_validation` | text | documentation (validation record); `_` keys are never published |

Role filters (top-level keys of `effects.json`, data shared with golem.fm):

- `role_categories` — the categories offered to each lane role; a role absent from the table (guitar,
  line) sees every category. Voice: vocal FX, captured outboard and `lofi` — never amp, cab or drive.
  Keys/pads: instruments and keyboard-coherent FX (no wah, pitch or amp). Drums: kit instrument,
  dynamics, preamp, lofi, eq, modulation, delay, reverb, utility.
- `role_blocks` — the exact blocks of a role within its categories (finer sieve); a role absent sees
  every block of its categories.

### 2.2 Param-level keys

| Key | Meaning |
|---|---|
| `id`, `name`, `label`, `unit`, `fmt`, `note`, `group`, `sub` | identity and display |
| `default`, `min`, `max` | range (in the plugin's displayed unit) |
| `map` | how the value is written to the plugin: `raw` (value as is, `TrackFX_SetParam`), `norm` (normalised 0..1 — required for JUCE VST3 enums), `pow` (skewed curve, matched on the displayed value). Never compute a linear normalisation for a slider with a negative minimum (REAPER treats it as bipolar) |
| `type` | `enum`, `bool`, `kitref`, `midilist`, `samplelist`, `standardref` (number if absent) |
| `options`, `values` | enum choices |
| `dynamic` | enum filled at runtime from a library list (`vital-presets`, `pad-kits`, `sfz-instruments`, `dx7-banks`, `dx7-patches`, `tunings`, `whammy-modes`, `drop-modes`, `pedal-settings`) |
| `widget`, `size` | `chips`, `fader` |
| `hidden` | not shown as a knob |
| `depends` | `{param: value}` — greyed unless the other param has that value (`designer-sheets.js`) |
| `exp` | `true` marks the knobs an expression pedal may drive. A block with at least one marked knob offers the EXP chip **only** on those, and the Assign modal targets the first one; a block with no mark keeps EXP on every knob |

## 3. Service lanes (`preset.config`)

Service blocks never sit in a signal chain. The Designer shows them in the ⚙ tab as three lanes:
**Players**, **Global** and **Arrangement**.

```json
"config": {
  "gen": {"blocks": [/* looper, backing-track, sample, drums, standard */], "out": "1-2"},
  "rec": {"blocks": [/* rec, compo, click */], "tap": "post"},
  "arr": {"blocks": [/* arrangement */]}
}
```

| Lane | Blocks (`preset_view.SERVICE_*`) | Notes |
|---|---|---|
| `gen` — Players | `looper, backing-track, sample, drums`, `standard` | unordered; `out` = where players sum (default `1-2`) |
| `rec` — Global | `rec, compo` (+ the click) | singletons whose settings are global (`config/recorder.json`, `compo.json`); only the foot switch is per preset |
| `arr` — Arrangement | `arrangement` | no REAPER track, engine in the bridge |

`store.migrate_config(p)` (idempotent) moves service blocks found in signal lanes into `config`; it
runs on load and on save, and the app mirrors it (`designer-model.js` `migrateConfig`). The tuner,
`whammy-dt`, `midi-pedal` and `clean-boost` stay in signal lanes (the tuner designates the source it
listens to; the others are links or external pedals). The drawer is per lane kind: the ⚙ lanes show
only services; signal lanes show everything except services.

Service block colours follow what the service **does** (catalogue `_color_note`): green = it plays into
the mix (Backing Track `#1ab7b0`, Looper `#2ecc71`, Sample `#5fce8f`, Drum Machine `#7fd4a8`, Standard
`#9ad9be`); red = it captures to disk (Rec `#ff4136`, Riff `#ff7a45`); amber = it keeps time (Click
`#e0b23a`, Arrangement `#c98a2e`).

`store._foot_blocks` enumerates config blocks with the lane blocks, so every foot map derives from it
(`_scene_claims`, `rec_sources`, `sample.switches`, `drums.switches`, `backing_switch`).
**Saving the current preset rebinds the foot registers** (`_bind_foot_services`): service controllers
copy block params at recall, and an edit that does not act at the foot is worse than no setting.

## 4. Scenes

| Block kind | Scene behaviour |
|---|---|
| Effect | on/off + params per scene (`scene.blocks`, `scene.params`) |
| Instrument (Vital, pads, piano…) | the referenced content (`content_param`) may change per scene; the block stays on |
| `scene_invariant` service | never touched by a scene change |

The live engine excludes scene-invariant blocks from the state switch ([live-engine.md](live-engine.md)).

## 5. Foot

- **Free assignment**: a block's `foot` is the switch number (scene row 1–5 only for
  `foot_scene_claim` blocks; stomps 6–10 for others). Several blocks on one switch toggle together.
- **Gestures are data**: `config/pedalboard/gestures.json` (served by `GET /api/gestures`, read by
  `app/gestures.js`) describes each gesture block per state; `/live` draws the glyphs (`•` tap, `••`
  double-tap, `▬` hold, `▬▬` long hold) and the Designer's MIDI assign tab writes them as sentences. The
  bridge acts (`backing.py`, `looper.py`, `sample.py`, `drums.py`, `standards.py`, `arrangement.py`);
  `tests/test_gestures_table.py` ties each duration in the table to the code constant.
- **Switch species** (`store.claim_species`): a scene-row switch claimed by a gesture block
  (`GESTURE_CLAIMS`: backing-track, sample, drums, standard, arrangement, compo, looper) needs both
  press and release edges; a pure on/off claim (rec, click, tuner, Rec + Backing) can carry a status LED.
  The pedalboard chip compiler imports this rule (`tools/fcb/gen_uno2_syx.py`); the select switch is
  never a toggle.
- **Two blocks on one switch share one gesture vocabulary.** Rec + Backing = one **take** gesture: tap
  = count-in (Rec ▸ Count-in: Off · 1 bar · 2 bars, `config/recorder.json` `count_in`), then the take and
  the backing start from 0; tap = stop both. A second press during the count-in cancels. A backing alone
  keeps its three gestures (tap play/pause, double-tap restart, hold stop and rewind). A gesture block
  (sample, drums, standard) keeps its switch for itself: other blocks on it do not fire from the foot,
  and the Designer says so.
- Gesture blocks:

| Block | Gestures (controller) |
|---|---|
| `sample` | stopped: tap = play the next of `params.samples` (cycles, the first at start); playing: tap = stop; hold ≥ 0.6 s = stop (`sample.SampleControl`, `POST /api/sample {sw, op: tap|stop}`) |
| `drums` | stopped: tap = play; playing: tap (< 0.6 s) = stop, release 0.6–1.5 s = next variation on the bar, hold ≥ 1.5 s = stop (`drums.DrumControl`, `VAR_S`, `STOP_S`; `POST /api/drums`) |
| `looper` | owns its switch table ([looper.md](looper.md), `looper.SWITCHES`) |
| `backing-track`, `standard`, `arrangement`, `compo` | see gestures.json and their own docs |

Edge precedence in `app._on_stomp_edge`: arrangement > backing > sample > drums > standard > looper (the
looper fallback only on its own switches); the CC path (`_do_stomp`) yields to them to avoid double
triggers.

## 6. Quarantine

A block type that freezes or crashes REAPER is quarantined **by data**: `effects.json`
`quarantine: "<measured reason>"`. Today: `pitch` (ReaPitch freezes the whole audio engine on
activation), `delay-echo` (GxEchoCat, same), `detune` (GxDetune corrupts REAPER's heap).

- Removed from the compile with a log line per block (`rig._drop_quarantined`); `vst-host` blocks are
  checked by plugin name too (`rig.quarantined_plugin`), so a quarantined plugin cannot come back
  through the VST Host block.
- Removed from the drawer; shown as `unavailable` with `reason: quarantine` (generic English `why`,
  the catalogue reason in `detail`) ([block-status.md](block-status.md)).
- Published in `caps.quarantine` and in the catalogue (the reason is sent as is), so golem.fm removes it
  from its vocabulary.
- **A plugin "already installed" is not a validated plugin.** Before offering a block: put it alone in
  an empty lane, rebuild twice (two real rebuilds, not a reuse), read its params with `fxparams`, check
  REAPER survived (same pid), and run `tools/check-block-stall.py` (no engine freeze on enable/disable).

## 7. Capture blocks

`CAPTURE_TYPES = ("amp", "amp-nam", "cab", "pedal-nam", "preamp-nam", "comp-nam")` (`rig.py`, mirrored in
`tones_jobs.py`; a test compares the copies). Without a capture they are silent, so they are removed
from the rig and shown `empty`.

- **Nature is read, not declared**: `rig._wrong_kind` checks the file against the block (a `.nam` for NAM
  blocks, an IR for `cab`; `patches.BLOCK_GEARS` maps block → accepted capture `gear`). Used by the
  compile, the acks (`unresolved[].why`) and the MCP `resolve`.
- `amp` = Head+Cab (capture `gear: amp-cab`); `amp-nam` = a head (`gear: amp`). A head always has a
  visible cab: the Designer inserts an empty `cab` after any head without one (`designer-model.js`
  `ensureHeadCabs`); an empty cab plays the compile's default IR. A Head+Cab must not be followed by a
  cab (`rig.stacked_cab` warns).
- `preamp-nam` (category `preamp`) and `comp-nam` (category `dynamics`) take TONE3000 `gear: outboard`
  captures. With `amp` and `amp-nam`, their output is normalised to `compile_rig.LOUD_TARGET` (−18,
  `NORMALIZED_TYPES`); the `output` knob is an offset on top. `pedal-nam` is not normalised.
  Voice order: `gate → preamp-nam → deesser → pitch-correct → comp | comp-nam → eq → delay/reverb`; one
  preamp per lane, never in a split branch. Outboard packs in IR format are refused by the nature guard.
- **Model order and default in a pack** (Capture dial, default model on insertion): the capture-gain
  reading in `app/capture-gain.js`, played against the shared case table
  `tests/capture-gain-cases.json` (`tests/test_capture_gain.py`). The input family is chosen before the
  gain (a voice keeps `mic` models, other roles `di`/`line`), then the cleanest readable model of
  channel 1.
- **IR guard**: the compile reads every IR (`compile_rig.ir_late_impulse`); past 100 ms, a 20 ms window
  rising above −40 dB under the peak is a late impulse (an echo baked into the file) → the cached copy is
  cut just before it (5 ms fade). The library file is never modified. Per-pack verdicts:
  `bridge/ir_quality.py` → `library/catalog/.ir-quality.json`, exposed as `echo` in `/api/catalog`, the
  "⚠ echo" badge, and `captures[].echo` in the heartbeat. `tools/check-irs.py` names faulty packs.

## 8. Other rules

- `whammy-dt` is always first in the pre-chain (a physical pedal before the interface):
  `designer-model.js` `pinWhammyFirst` puts it back at index 0 on every edit and load, and drag-and-drop
  refuses to move it.
- `grit` (Prisma, category `lofi`) is the only saturation offered to a voice. Its JUCE VST3 enums are
  normalised (`map: norm`). Factory block presets in `library/block-presets/grit/`. Installed by
  `provision/install-prisma.sh` ([plugins.md](plugins.md)).
- `killswitch` (JSFX `reaper/Effects/golem_killswitch.jsfx`, roles guitar/bass/voice): Depth, Length,
  Rate are EXP-marked; Trigger Engage/Pick/Beat. Its stomp is a toggle (the chip's `effect` switches send
  no release, so a momentary kill is not possible).
- **Pad kits** (`pads` block): `library/kits/<id>.json`, up to 16 pads `{note, sample, mode, level}`;
  `mode` = `gate` (note-off cuts), `oneshot` (plays to the end, re-tap restarts), `toggle` (re-tap cuts —
  not native in RS5k: `golem_rig` falls back to `oneshot` and logs it). Kit engines: `rs5k`, `sfz`,
  `avldrums`, `drumgizmo` (`bridge/kits.py`). Samples live in `assets/samples/` (upload:
  `POST /api/sample/upload`).
