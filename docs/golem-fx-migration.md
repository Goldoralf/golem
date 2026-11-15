# golem-fx replaces the open-source effects

> **Status: FIXED** (2026-11-15). Asked by the maintainer: "we remove the old open-source pedals and replace them with
> gfx everywhere? Fine, but I want to follow the progress. Will we only have gfx pedals in the end?"

Related: [golem-fx-reaper.md](golem-fx-reaper.md) (the rule per engine), [golem-fx-sheet.md](golem-fx-sheet.md) (the
block sheet, the golem-fx-only blocks), golem-fx's `docs/golem-contract.md`.

## 1. The rule

- **A block keeps its type, presets, scenes and footswitch; only the plugin that plays it changes.** A golem-fx plugin
  "stands for" a catalogue block and keeps its parameter ids (the contract). Saved patches keep working.
- **Where golem-fx plays.** `golem_fx: true` in `library/catalog/effects-golem-engine.json` switches a type to its
  golem-fx plugin on the Golem Engine, and under REAPER on Linux when the plugin is installed. Elsewhere (Windows and
  macOS until golem-fx builds there, a Linux rack without the plugin) the block keeps its open-source plugin. Nothing is
  deleted from the catalogue while one platform still needs the original.
- **New blocks** that no open-source plugin plays (Met, Glitch, Tape, Poly Synth…) are golem-fx only: offered where
  golem-fx plays, out of the drawer elsewhere.
- **Retiring an original** (a duplicate such as the Calf flanger, catalogue v40) is a separate, explicit decision, with
  the saved patches migrated.

## 2. Will golem have only golem-fx pedals?

For the **effects**, that is the direction: golem-fx's contract says its plugins "become golem's default blocks later".
Not everything, though. Out of scope, and staying as they are:

- **Captures** (NAM amps, pedals, preamps, compressors, Proteus): the sound is the capture file; golem-fx draws them but
  does not replace them.
- **Instruments** (Vital, piano, organ, EP, pads, the drum kit).
- **golem features** (Rec, Tuner, Click, Backing Track, Looper, Riff, Drum Machine, Standard, Arrangement, Sample): they
  draw as golem's own devices (golem-fx's "Console" look, da73548), not as pedals.
- **Hardware** driven over MIDI (Whammy DT, MIDI pedals).

## 3. Progress

Generated from the catalogue by `tools/golem-fx-progress.py` (the test suite checks it is current: run the tool after a
catalogue change).

<!-- golem-fx-progress:begin -->
**51 of 68 effect blocks** are played by golem-fx; 6 are ready in golem-fx and not wired yet; 11 have no golem-fx counterpart yet.

| Status | Blocks |
|---|---|
| Played by golem-fx, replacing an open-source plugin (32) | `gate`, `comp`, `eq`, `chorus`, `flanger-js`, `phaser-js`, `tremolo`, `killswitch`, `wah`, `wah-color`, `autowah`, `delay`, `reverb`, `pitch-shift-js`, `pitch`, `volume`, `clean-boost`, `reverb-plate`, `reverb-room`, `reverb-shimmer`, `rotary`, `eq-graphic`, `limiter`, `deesser`, `granular`, `octaver`, `vibrato`, `pitch-correct`, `detune`, `ringmod`, `surge-treemonster`, `guitar-drive` |
| Played by golem-fx, new blocks with no open-source original (19) | `golem-double`, `glitch`, `met`, `emet`, `shem`, `swell`, `transient`, `mb-comp`, `ducker`, `widener`, `bass-di`, `tape`, `dist`, `fuzz`, `radio`, `vocoder`, `acoustic-sim`, `sustainer`, `polysynth` |
| … of which the engine-stall bench is still pending (6) | `flanger-js`, `golem-double`, `glitch`, `met`, `emet`, `shem` |
| Ready in golem-fx, not wired yet (6) | `grit` (gfx-grit, today Prisma), `cab` (gfx-cab, today x42 - IR Convolver Mono), `bitcrusher` (gfx-crusher, today MDA Degrade), `surge-freqshift` (gfx-freqshift, today Surge XT Effects), `ir-fx` (gfx-irfx, today x42 - IR Convolver Stereo), `stretch` (gfx-stretch, today PaulXStretch (Sonosaurus)) |
| No golem-fx counterpart yet (11) | `chorus-js` (sstillwell/chorus_stereo), `phaser` (Calf Phaser), `pitch-spectral` (Spectral Shift), `delay-tape` (Calf Vintage Delay), `delay-tape-aw` (TapeDelay2 (airwindows)), `delay-echo` (GxEchoCat), `eq-para` (x42-eq - Parametric Equalize), `rezfilter` (MDA RezFilter), `surge-spring` (Surge XT Effects), `spectral-comp` (Spectral Compressor (Robbert), `freeze` (GoleM Freeze (GoleM)) |
| Out of scope — Captures (the sound is the file) (6) | `boost`, `pedal-nam`, `preamp-nam`, `comp-nam`, `amp`, `amp-nam` |
| Out of scope — Instruments (6) | `vital`, `pads`, `drumkit`, `organ`, `piano`, `ep` |
| Out of scope — golem features (10) | `backing-track`, `looper`, `tuner`, `rec`, `click`, `compo`, `sample`, `drums`, `standard`, `arrangement` |
| Out of scope — Hardware (MIDI) (2) | `whammy-dt`, `midi-pedal` |
<!-- golem-fx-progress:end -->

## 4. The order for what is ready (2026-11-15)

**Step 1 is wired (2026-11-15):**

- `pitch-correct` → gfx-correct. Live (`fastmode`) is on by default; the knob that read Speed is Smoothing (lower
  = tighter); Key and Scale are real settings of the plugin (eleven scales; the x42 mask learned them too) and
  follow the song's key (`song_key`, virtual, on by default, never over Chromatic). Hard tune and Transparent are
  re-voiced by hand, Tight pop by golem-fx. Stall bench: one 519 ms freeze in 32 switch-ons (none in a rerun of 20);
  519 ms is the signature of a known bench artefact (golem-fx-reaper.md §3), to confirm on a quiet machine.
- `ringmod` and `surge-treemonster` → gfx-ringmod (Carrier Free / Track written at insert). Bench clean.
- `granular` → gfx-grains: Grain Position works; Freeze is a switch and the block's footswitch holds it
  (`golem_rig.lua` `switch_param_of`); the lane turns stereo. Bench clean.
- `eq-graphic` → gfx-geq: one block (the maintainer did not ask for three), ±15 dB; Layout (expert) gives the guitar
  or bass seven-band set. Bench clean.


1. `pitch-correct` (catalogue fixes: Live by default, Hard tune's filter, key and scale as real settings), `ringmod` and
   `surge-treemonster`, `granular`, `eq-graphic`.
2. The unit conversions, with saved patches and presets converted once: `bitcrusher`, `surge-freqshift`, `grit`,
   `stretch`.
3. `tuner` (a new runtime: one gfx-tuner per lane), then `cab` and `ir-fx` (the IR slot registry; the level of
   converted cabs, +14 dB or 0 dB, is the maintainer's call).
