# golem-fx under REAPER

> **Status: CODED** (2026-11-13). Asked by the maintainer: "play the golem-fx under REAPER, and keep the other blocks
> as under the Golem Engine". Linux only (golem-fx is built there).

Related: [ardour-plan.md](ardour-plan.md) (D3: golem-fx blocks replace REAPER's stock plugins), [designer-glyphs-pedals.md](designer-glyphs-pedals.md).

## 1. The rule

One table decides, for both engines, which block types golem-fx plays: `golem_fx: true` in
`library/catalog/effects-golem-engine.json`. Under REAPER, a type of that table plays its golem-fx VST3 **when REAPER
has that plugin installed**; otherwise the block keeps its original plugin (Calf, ReaPlugs, guitarix…). Every other
block keeps its original plugin, as under the Golem Engine. The block keeps its id, presets, scenes and foot switch:
only the plugin changes.

## 2. How REAPER is told

| What | Where |
|---|---|
| Each golem-fx plugin, the name REAPER adds it by, and every parameter's plain range (linear) and option count | `library/catalog/golem-fx-plugins.json`, generated from golem-fx by `tools/sync-golem-fx-manifest.py`, keyed by VST3 class id as in the engine table |
| The switch, per type | `golem_rig.lua` `apply_golem_fx`: the plugin found in `EnumInstalledFX` (a name starting with `VST3: GoleM FX …`); each catalogue knob takes the table's label (or its own name) and the plugin's range: floats `pow` with exponent 1 (linear normalization), enums by rank over the plugin's option count, booleans 0 / 1; the table's `init` (plugin units) is written normalized after the add; `absent` knobs are skipped. No fallback to the original aliases with golem-fx knob names |
| The EXP fast path | the live map publishes the plugin's range (`pmin` / `pmax`), so the bridge's `(v − pmin) / (pmax − pmin)` lands right |
| Quarantine, golem FX list, engine-only knobs | `rig._engine_safe_types()`: under REAPER on Linux, the table's types whose bundle is in `~/.vst3` (where `tools/golem-fx-install.py` puts them). Pitch and detune leave quarantine there; `/api/effects` `golem_fx` lists them (clay fill, drawer column, golem-fx pedals); the flanger's `fb_polarity` stays |

Tests: `tests/test_rig_lua.py::test_golem_fx_sous_reaper_installe_ou_non` (installed and not), `tests/test_compile_rig.py`.
The test suite never sees the machine's own golem-fx (`conftest.py`).

## 3. Open

- The engine-stall bench under REAPER (2026-11-13, 12 switch-ons each, machine quiet): **no freeze** on Autowah,
  Boost, Chorus, Comp, Delay, Flanger, Gate, Limiter, Octaver, Phaser, Wah. The other twelve (De-esser, Detune, Drive,
  EQ, Killswitch, Pitch Classic, Pitch, Reverb, Rotary, Shimmer, Tremolo, Vibrato) must be run again: a
  `tools/check-params.py` run on the rack's REAPER shared the command slot during the bench (the last seven read
  exactly 0 ms, three others ~517 ms), and the rerun stopped when the rack left the patch.
- `fxparams` (golem_apply) now reports the pins REAPER gives a plugin: the golem-fx VST3s listed "(mono)" get 2 in /
  2 out on a stereo track.
- Windows and macOS: once golem-fx ships there.
