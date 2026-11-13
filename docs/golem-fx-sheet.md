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

Their pedals have their own **Blackwork** finish (black lacquer, an engraved skull whose eyes light in the pedal's
colour; names in Pirata One, vendored with the other OFL fonts) — golem-fx d70807d, the maintainer's decision.

Shem is filed under **drive** (golem-fx proposed utility): a boost is looked for next to the drives.
**Met's key input is not routed yet** (nor gfx-gate's): it reads the main input until a key arrives, so it gates on what
reaches it in the chain. Routing the lane's DI to the key bus is the next step, on both engines.
REAPER sees a newly installed VST3 only after a restart (its startup scan).

**Measured under REAPER on 2026-11-13** (the rack, golem-fx be2380b installed): the three blocks auditioned in one
lane are placed by their REAPER name; rig-check is clean, and `fxparams` reads the written values back normalized on
the plugin's ranges (Met Threshold −60 dB = 0.333, Emet Gain 20 % = 0.2, Shem Grind +6 dB = 0.5). Met shows 4 input
pins on a 2-channel track: its key pins read the silent channels 3/4, so it stays on the main input.

## 5. Open

- Only the Chorus has Custom switches and reference presets so far (golem-fx side).
- The pedals in the Add-block shelf and on `/live` still draw golem-fx's defaults, not the block's values.

Tests: `tests/test_golem_fx_sheet.py`, `tests/test_rig_lua.py::test_un_reglage_de_la_pedale_golem_fx_s_ecrit_sous_reaper`.
