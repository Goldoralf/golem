# The golem FX block sheet

> **Status: CODED** (2026-11-13), on golem-fx's full descriptors (`visuals/data/descriptors.json`, golem-fx 405c90d:
> 24 pedals, 405 settings, 83 groups). Asked by the maintainer: "a new sheet with each pedal's settings, as golem-fx
> planned them".

Related: [golem-fx-reaper.md](golem-fx-reaper.md), [designer-glyphs-pedals.md](designer-glyphs-pedals.md).

## 1. What the maintainer sees

A block that golem-fx plays **here** (Golem Engine, or REAPER with the plugin installed) opens a sheet built from its
pedal's descriptor, in the drawers' usual cells (dials, selects, switches, EXP chips, scene overrides):

| Tab | Content |
|---|---|
| **Settings** | the **front panel**: exactly the controls the pedal face draws, in its order, under golem-fx's names |
| **Expert** | one sub-tab per expert group; the group's **Custom** switch first, its settings greyed until it is on (`depends`) — only when the descriptor has groups |
| **Presets** | block presets carry the front panel **and** the expert settings |
| **MIDI assign** | unchanged |

Where golem-fx does not play the block, the sheet is the catalogue's, as before. The pedal drawn in the Designer's
pedal view shows the block's real settings (scene first).

## 2. Where the settings come from

The **descriptor** of each golem-fx plugin is in `library/catalog/golem-fx-plugins.json` (written by
`tools/sync-golem-fx-manifest.py`): golem-fx's `visuals/data/descriptors.json` when it exists, otherwise a provisional
one taken from the pedal faces (front panel only: names, ranges, defaults, option labels; no units, no groups).

`bridge/golem_fx.py` merges it with the catalogue, per type:

- a descriptor setting that **is** a catalogue knob (same plugin name, through the engine table) keeps the catalogue's
  id, range and mapping: presets keep their values, and REAPER without golem-fx still plays it; it takes golem-fx's
  name as its label;
- the others become new knobs: golem-fx's id (`gfx_` + id if it collides with a catalogue id of another meaning), the
  plugin's units and range, raw values, `engine_only: "golem"`; the compiler removes them wherever golem-fx does not
  play the block;
- catalogue knobs the plugin does not have stay, hidden;
- a catalogue list that is the **start** of the plugin's (same order) keeps its labels and gains the plugin's extra
  choices: the Delay's Time gains 1/2, 1/4T, 1/16• and Free; Wah Color gains its four extra models;
- a `depends` value is translated into the block's vocabulary (a plugin label becomes the catalogue's label of the same rank);
- golem-fx's reference presets (12 for the Chorus) are factory block presets, only where golem-fx plays the block.

Readers: `/api/effects` (`params` + `gfx_sheet` for those types), the compiler (ranges, removal), the Golem Engine plan,
and `golem_rig.lua` (`apply_golem_fx`, the same key rule, values normalized on the plugin's ranges).

## 3. The descriptor asked of golem-fx

Per crate: `name`, `class_id`, `blocks`, `front` (ordered ids = the face), `groups` (`id`, `name`, `custom` bool id or
null, `params`), `params` (`name`, `kind` float/enum/bool, `min`, `max`, `default`, `unit`, `display` lin/log,
`decimals`, `options`, `exp`, `structural`, `depends` {param, equals}, `help`), `presets`. Every parameter is in
`front` or exactly one group; ids follow golem-fx's contract (added, never renamed or removed).

## 4. Blocks only golem-fx plays

`met` (Met Gate, dynamics), `emet` (Emet Overdrive, drive) and `shem` (Shem Boost, drive) — catalogue v43, golem-fx
be2380b, status `testing` — have no original plugin. Their catalogue entry carries a `quarantine` that starts with
"golem-fx only": `rig.quarantined_types()` lifts it wherever golem-fx plays the type, so they are offered, compiled and
in the AI's vocabulary there and nowhere else (Windows, macOS, REAPER without the plugin). `/api/effects` lifts a
quarantine on every OS (before 2026-11-13 only on Windows/macOS: on Linux the drawer still hid a type golem-fx plays).
Their catalogue params are the front panel under golem-fx's ids; the expert groups come from the descriptor.
golem-fx's visuals list the blocks of their catalogue snapshot: `app/golem-visuals.js` attaches a type the rack's
catalogue gained since to its face (`face.blocks`).

`golem-double` (Golem Double, pitch, **voice lanes only** — catalogue v44, golem-fx 87c55ea) is the same kind: a live
vocal doubler (a double an octave below, formants kept or moved; the dry voice has no latency). The rack calls it `golem-double`,
not `golem`: the product's name is not a block type (`golem:golem` in the FX names, the drawer search, the AI's
vocabulary); golem-fx aligned its face, glyph and snapshot (56616d1). `/api/effects` also gives every golem-fx type its
crate (`gfx_crates`), so the app draws the right pedal even for a type golem-fx's snapshot does not list yet. Put a de-esser and a gate before it.

`glitch` (Glitch, modulation — catalogue v45, golem-fx aa7851f, the maintainer's go on 2026-11-14) is the same kind: a
spectral glitch (the sound cut into spectral bins, then held, scattered or reshaped: 30 effects; Sustain makes a pad of
what you play). Its front panel is Effect, Amount, Sustain, Mix. It is **stereo by nature** (2/2 first, it also plays
1/1): put it on a stereo lane. The dry is never delayed; the wet trails by the analysis window (size + size/4: 2,560
samples, 53 ms at 48 kHz, at the default size). The plugin reports no latency unless its expert `align` is on, which
delays the dry to match: a **setup** setting, never a scene value. There is **no footswitch action** (no `foot_mode`,
no trigger: you set it before playing), and 17 factory presets (golem-fx e2fbdd9, default "Ringing partials"; none turns `align` on), values tuned after the maintainer listens.

Their pedals have their own **Blackwork** finish (black lacquer, an engraved skull whose eyes light in the pedal's
colour; names in Pirata One, vendored with the other OFL fonts) — golem-fx d70807d, the maintainer's decision.

Shem is filed under **drive** (golem-fx proposed utility): a boost is looked for next to the drives.
**The key of a keyed gate is the lane's DI** (Met, and the golem-fx gate; `key: true` in the engine table), on both
engines, wherever the block sits in the lane:

- **REAPER** (`golem_rig.lua`): a track carrying one has 4 channels, 3/4 being the key (the plugin's aux pins). On the
  lane's input track, `golem_keytap.jsfx` at the head of the chain copies the input onto 3/4 (mono lane: channel 1 on
  both); on another track of the path (a branch, the merge), a **pre-FX** send from the input track lands on 3/4. The
  key never reaches the sound: the other sends stay on 1/2, and a folder child sends only 1/2 to its parent
  (`C_MAINSEND_NCH`). The key is part of the FX signature (the keytap appears on a rebuild).
- **Golem Engine** (`golem_watch.lua`, fork): the plan gives the block `key_input` (the card input of its path); the
  watcher adds the insert's sidechain (`Route:add_sidechain`) and connects it to that input; `dump` reports it.

Without a key (Windows, macOS, a plugin missing), Met reads its main input: nothing breaks.
Tests: `tests/test_rig_lua.py::test_la_cle_du_gate_entend_le_di_de_la_lane`, `tests/test_engine_ardour_plan.py`;
on a real engine, `tools/check-engine-ardour.py` (Met after the branches and the gate in a branch both key on the
card's input 1, measured 2026-11-13).
REAPER sees a newly installed VST3 only after a restart (its startup scan).

**Measured under REAPER on 2026-11-13** (the rack, golem-fx be2380b installed): the three blocks auditioned in one
lane are placed by their REAPER name; rig-check is clean, and `fxparams` reads the written values back normalized on
the plugin's ranges (Met Threshold −60 dB = 0.333, Emet Gain 20 % = 0.2, Shem Grind +6 dB = 0.5). Met shows 4 input
pins on a 2-channel track; before the key was routed, its key pins read silent channels and it stayed on the main input.

## 5. golem-fx's factory presets (golem-fx 0.2)

golem-fx researched and annotated about 400 factory presets for its pedals (golem-fx/presets/, exported COMPLETE in
`visuals/data/descriptors.json`). `tools/sync-golem-fx-presets.py` seeds them into
`library/block-presets/<type>/<id>.json`, one file per preset: golem.fm's sync reads those files, and its AI refers to a
preset as `<type>/<id>`. The id is stable forever. Rules decided with the maintainer on 2026-11-13:

- **A preset is the whole sound.** Loading one on a block golem-fx plays sets every setting: each starts from its
  default, then the preset on top. Nothing from the previous state survives (`page-designer.js` `onLoadPreset`).
- **A preset wins over a value golem pins at insert, except the type's identity.** `identity` in the engine table:
  reverb-plate is algo Plate, reverb-room is algo Room, wah (Cry Baby) is model GCB-95. Those settings are hidden from
  the sheet and never written; a preset that contradicts them is refused by the seed. The generic Reverb may play
  Spring, Chamber, Cloud… .
- **The rack's own factory presets stay.** golem-fx's new presets (`golem_fx: true`) are offered only where golem-fx
  plays the block, and their `default` wins over the rack's there; elsewhere, the rack's presets alone. An id the rack
  already had (eq `standard`…) takes golem-fx's version and stays offered everywhere (`golem_fx: false`).
- Params are written in the block's vocabulary (`golem_fx.preset_params`): the sheet's id, a list by its rank.
- No `vendor` / `twin_of`: golem.fm's prompts advise golem-fx blocks from the list of types itself.

`--check` says whether the files are current. The plugin table no longer carries the presets.

## 6. Open

- Only the Chorus has Custom switches and reference presets so far (golem-fx side).
- The pedals in the Add-block shelf and on `/live` still draw golem-fx's defaults, not the block's values.

Tests: `tests/test_golem_fx_sheet.py`, `tests/test_rig_lua.py::test_un_reglage_de_la_pedale_golem_fx_s_ecrit_sous_reaper`.
