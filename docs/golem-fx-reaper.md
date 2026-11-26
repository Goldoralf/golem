# golem-fx under REAPER

> **Status: CODED** (2026-11-13; all three OS 2026-11-15). Asked by the maintainer: "play the golem-fx under REAPER, and
> keep the other blocks as under the Golem Engine".
>
> **2026-11-15:** the installers ship golem-fx 0.8.1 since 2026-11-26 (0.8.1: 0.8's code rebuilt, with the levelled Organ presets and the gesture flag; 0.4 on 2026-11-15, 0.6 on 2026-11-17, 0.7 earlier on 2026-11-26;
> 0.8 adds Organ and Octafuzz, three Dist circuits at the end of its list and Pitch's bend, [golem-fx-sheet.md](golem-fx-sheet.md) §4; prebuilt VST3, Linux / Windows / macOS — [installer.md](installer.md)
> §2, Pins), and REAPER on Windows and macOS now plays golem-fx blocks when the plugin is installed, exactly as on
> Linux. The third-party fallbacks (guitarix, Calf, Dragonfly, Zam…) stay installed until a later step.

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
| Quarantine, golem FX list, engine-only knobs | `rig._engine_safe_types()`: under REAPER, the table's types whose bundle is in one of `rig.golem_fx_dirs()` — Linux `~/.vst3` (where the installer and `tools/golem-fx-install.py` put them), `/usr/local/lib/vst3`, `/usr/lib/vst3`; Windows `%LOCALAPPDATA%\Programs\Common\VST3\GoleM` (the installer's), `%LOCALAPPDATA%\Programs\Common\VST3`, `%CommonProgramFiles%\VST3`; macOS `~/Library/Audio/Plug-Ins/VST3` (the installer's), `/Library/Audio/Plug-Ins/VST3`. Pitch and detune leave quarantine there; `/api/effects` `golem_fx` lists them (clay fill, drawer column, golem-fx pedals); the flanger's `fb_polarity` stays |
| Windows and macOS (2026-11-15) | `apply_golem_fx` runs **before** the OS table (`effects-windows.json` / `effects-macos.json`), which then skips every type golem-fx plays: no JSFX or Surge mapping, no `unsupported`, no renamed knob. REAPER names a VST3 the same way on every OS (`VST3: GoleM FX Gate (GoleM)`); the installed name is still read from `EnumInstalledFX`. `bridge/blockstatus.py` judges such a block by its golem-fx plugin name |

Tests: `tests/test_rig_lua.py::test_golem_fx_sous_reaper_installe_ou_non` (installed and not, on Linux, Windows and
macOS), `test_met_emet_shem_se_posent_sous_reaper_avec_golem_fx` (the golem-fx-only blocks, three OS),
`test_sans_le_plugin_dans_reaper_la_table_de_l_os_reprend_la_main` (bundle on disk, not scanned by REAPER: the OS
table applies), `tests/test_golem_fx_install.py` (the installer step, the dirs per OS, the block status, the
uninstaller), `tests/test_compile_rig.py`.
The test suite never sees the machine's own golem-fx (`conftest.py`).

## 3. Open

- The engine-stall bench under REAPER (2026-11-13, 12 switch-ons each, machine quiet): **no freeze** on Autowah,
  Boost, Chorus, Comp, Delay, Flanger, Gate, Limiter, Octaver, Phaser, Wah. The other twelve (De-esser, Detune, Drive,
  EQ, Killswitch, Pitch Classic, Pitch, Reverb, Rotary, Shimmer, Tremolo, Vibrato) must be run again: a
  `tools/check-params.py` run on the rack's REAPER shared the command slot during the bench (the last seven read
  exactly 0 ms, three others ~517 ms), and the rerun stopped when the rack left the patch.
- `fxparams` (golem_apply) now reports the pins REAPER gives a plugin: the golem-fx VST3s listed "(mono)" get 2 in /
  2 out on a stereo track.
- **Windows, checked on a real machine 2026-11-20** (REAPER 7, golem-fx 0.6, i9-13900H): REAPER scans
  `%LOCALAPPDATA%\Programs\Common\VST3\GoleM` and lists the plugins as `VST3: GoleM FX <Name> (GoleM)`, with
  ` (mono)` appended for the mono ones (`golem_rig.lua` takes the installed name that starts with the manifest's). The
  engine-stall bench ran on **all 49 golem-fx plugins the catalogue uses** (8 switch-ons each, on the merge track of a
  live patch): **no freeze**, worst 6 ms (Tremolo) — the measurement's own noise; Pitch Correct, suspected of a 519 ms
  freeze, did not freeze. The twelve left from 2026-11-13 are covered for Windows; Linux still has to rerun them.
  Two bench bugs found on the way, fixed in `tools/check-block-stall.py`: after ~22 plugins the measurement froze and
  every switch-on read exactly 0 ms, reported as "no freeze" (eight exact zeros are now "measurement frozen — not
  measured", rerun in batches); and "track not found" was read from the last 600 characters of `.apply.log`, which still
  held a previous run's message (now only the log written after the command).
- The parameter manifest (`library/catalog/golem-fx-plugins.json`) regenerated from golem-fx 0.6 (e7e9ecc) on
  2026-11-20 is identical to the one from 048142e, and regenerated from 0.7 (ea689aa) on 2026-11-26 it is identical
  again (only `golem_fx_commit` moves: 0.7 adds the editor, not parameters). From 0.8 (ef58874, synced at 189293e) it gains
  the two new plugins, Dist's `circuit` grows to 7 options (`n`) and Dist and Pitch gain parameters at the end; `golem_rig.lua` `gfx_range` now matches parameter names EXACTLY
  (the case-insensitive substring fallback iterated `pairs()`, whose order is undefined) and logs a missing name;
  `tests/test_golem_fx_manifest_names.py` checks every name golem looks up (1,434) against the manifest.
- macOS: coded and tested under the fake REAPER only (2026-11-15); the same checks are still to run there.
- Linux: the release `.so` need glibc ≥ 2.34; on an older system REAPER does not load them and the blocks keep their
  original plugins (the bridge still sees the bundles in `~/.vst3`: the quarantine is lifted for pitch / detune there).
