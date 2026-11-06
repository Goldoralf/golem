# How to add an in-house JSFX

**When:** a DSP or MIDI job REAPER must run on the audio thread — an effect block
(`golem_killswitch`), a service engine on its own track (`golem_click`, `golem_drumseq`), a probe
(`golem_gapmeter`). Model: `reaper/Effects/golem_killswitch.jsfx` — its header lists the traps
it respects, and `tests/test_killswitch_block.py` enforces them.

## Files, in order

1. **`reaper/Effects/golem_<name>.jsfx`** — header convention (copy the first lines of an existing
   file verbatim, including its copyright line):
   ```
   desc:GoleM Safety limiter (safety) -- zero latency, ceiling -1 dBFS
   // SPDX-License-Identifier: MIT
   // Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors
   // Ce JSFX est sous MIT, PAS sous la GPL du depot : un effet doit pouvoir voyager seul.
   ```
   In-house JSFX are **MIT** (`reaper/Effects/LICENSE`), unlike the rest of the repository;
   `golem_super8` is a Cockos fork and stays LGPL. Comments in French, `desc:` in English.
2. **Sliders** — `sliderN:var=default<min,max,step{opt1,opt2}>Name`:
   ```
   slider1:ks_depth=100<0,100,1>Depth (%)
   slider2:ks_sync=4<0,6,1{Free,1/4,1/8,1/8T,1/16,1/16T,1/32}>Sync
   slider8:ks_wsteps=0<0,1000000000,1>Steps (witness)
   ```
   - `Name` is what `golem_rig` matches (catalog param `name`); an enum's index is its raw value.
   - **Minimum ≥ 0.** A negative minimum makes the slider *bipolar* for REAPER (normalized 0.5 = 0):
     any normalized write — the EXP pedal over OSC, a linear formula — lands on a wrong value.
     If you need −1 as "off", write raw values only (`TrackFX_SetParam`) and say so.
   - **Append, never insert:** probes read by index (`fxparams`) and saved projects keep the order.
   - A witness slider (a counter incremented in `@block`/`@sample`) lets `fxparams` prove the audio
     thread runs. Prefix a slider name with `-` to hide it (`golem_super8`).
3. **Sections.**
   - Code **before the first `@` section never runs**: constants declared there are all 0. Put
     every constant and gmem index in `@init` (`golem_click.jsfx` documents the bug this caused).
   - **EEL2 is case-insensitive**: `seq_len = gmem[SEQ_LEN]` overwrites the index constant.
     Prefix every variable of the file (`ks_`, `cur_`).
   - `@init` re-runs on transport start unless `ext_noinit = 1;` and on sample-rate change; with
     `ext_noinit`, recompute srate-dependent values in `@block` when `srate` changes (killswitch).
   - A bypassed JSFX gets no `@block` and no notice when re-enabled: detect it from a gap in
     `time_precise()` between blocks (killswitch, > 150 ms).
   - **Audio-thread budget:** per-sample code is a few operations; anything depending on sliders,
     tempo or srate is computed once per `@block`; heavy analysis is decimated or spread over
     blocks. A heavy `@block` chops the sound with no error anywhere.
4. **gmem** (sharing with Lua): `options:gmem=golem_<name>` after the sliders; the Lua loop does
   `reaper.gmem_attach("golem_<name>")` on every tick (see [add-reaper-loop.md](add-reaper-loop.md)).
   Write the slot map (index → meaning) in the header of both files. A JSFX may read another's
   namespace: `golem_click.jsfx` declares `options:gmem=golem_chordseq` to read two of its slots.
5. **Wire it.** As an effect block: catalog entry + `ADD_ALIAS` with `"JS:golem/golem_<name>"`
   first — that path loads the file even before REAPER's JSFX cache has seen it (see
   [add-block-type.md](add-block-type.md)). As a service engine: a Lua loop inserts it on its own
   track (`FX_NAMES` in `golem_click.lua`) and **arms** that track (`I_RECMODE = 2`).
6. **Licence list:** add the file to the table of `docs/licence.md` §3.

## Deployment

- Linux: `provision/link-reaper.sh` symlinks `reaper/Effects` to `~/.config/REAPER/Effects/golem`
  — an edit is live at the next instantiation (re-add the FX, or rebuild the preset).
- Windows/macOS: `provision/desktop.py: copy_resources` **copies** `reaper/Effects` into REAPER's
  resource folder at setup. A changed JSFX does nothing there until the setup runs again.

## Checks

- A test modelled on `tests/test_killswitch_block.py`: parse the `slider` lines, compare with the
  catalog (names, bounds, defaults, enums), assert no negative minimum, assert only declarations
  before `@init`, assert the `ADD_ALIAS` line.
- On the rig: `fxparams` to read the real parameters, `fxset` to write a raw value and read it
  back; `./tools/check-params.py --block <id>`; `./tools/check-block-stall.py "JS:golem/golem_<name>"`
  for an effect block.

## Traps

- A write that "looks set" may not have landed (bipolar slider, wrong FX index): read it back.
- A JSFX on an unarmed service track (no input, no item) stops when REAPER ejects the track from the
  live graph; gmem commands can never wake it again.
