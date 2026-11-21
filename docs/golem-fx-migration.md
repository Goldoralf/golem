# golem-fx replaces the open-source effects

> **Status: FIXED** (2026-11-15). Asked by the maintainer: "we remove the old open-source pedals and replace them with
> gfx everywhere? Fine, but I want to follow the progress. Will we only have gfx pedals in the end?"

Related: [golem-fx-reaper.md](golem-fx-reaper.md) (the rule per engine), [golem-fx-sheet.md](golem-fx-sheet.md) (the
block sheet, the golem-fx-only blocks), golem-fx's `docs/golem-contract.md`.

## 1. The rule

- **A block keeps its type, presets, scenes and footswitch; only the plugin that plays it changes.** A golem-fx plugin
  "stands for" a catalogue block and keeps its parameter ids (the contract). Saved patches keep working.
- **Where golem-fx plays.** `golem_fx: true` in `library/catalog/effects-golem-engine.json` switches a type to its
  golem-fx plugin on the Golem Engine, and under REAPER (Linux, Windows, macOS) when the plugin is installed. Elsewhere
  (a machine without the plugin) the block keeps its open-source plugin. Nothing is deleted from the catalogue while
  one platform still needs the original.
- **New blocks** that no open-source plugin plays (Met, Glitch, Tape, Poly Synth…) are golem-fx only: offered where
  golem-fx plays, out of the drawer elsewhere.
- **Retiring an original** (a duplicate such as the Calf flanger, catalogue v40) is a separate, explicit decision, with
  the saved patches migrated.

## 1 bis. The legacy blocks are retired (catalogue v48, 2026-11-15)

**FIXED** — the maintainer: "the golem will run only with our blocks". The list is golem-fx's `docs/legacy-blocks.md`.
These types leave the catalogue, the Windows / macOS tables and the engine table. A document that still carries one
(a patch, a preset, a scene override, a block preset, the Designer sandbox) is rewritten **on load** by
`bridge/option_renames.py` (`RETIRED`), values translated by intent; a scene override keeps only what it changes (the
new pedal's model or voice belongs to the block). The factory and test content, and the block presets, are rewritten
in the repository.

| Old block | Plugin | Now |
|---|---|---|
| `chorus-js` | JS chorus_stereo | `chorus` (gfx-chorus): wet dB → mix, length → base delay and depth, voices |
| `phaser` | Calf Phaser | `phaser-js` (gfx-phaser): depth in cents → sweep from 440 Hz, feedback → dB, stages |
| `delay-tape` | Calf Vintage Delay | `delay` (gfx-delay, model Tape): a division the Delay has stays synced, others go free at the block's tempo; a different right time → Ping-Pong |
| `delay-tape-aw` | Airwindows TapeDelay2 | `delay`, model Tape, free time; regen → feedback, flutter → mod, tone → high cut |
| `delay-echo` | GxEchoCat | `delay`, model Tape, free time (its bpm = a quarter); heads → tap pattern; input → drive |
| `eq-para` | x42 parametric | `eq` (gfx-eq): middle bell → mid, the stronger of the two others → second mid, shelves, low cut |
| `surge-spring` | Surge XT spring | `reverb` (gfx-reverb, Spring voice) |
| `boost` | Proteus | `emet` (overdrive); a drive ≤ 15 % was a boost → `shem` |
| `pitch-spectral` | Spectral Shift | `pitch` (gfx-pitch, engine Poly), fully wet |
| `rezfilter` | MDA RezFilter | `autowah` (gfx-autowah, low-pass, envelope / LFO) |
| `freeze` | GoleM Freeze | dropped (the maintainer found it poor); a document that had it gets `granular`'s hold, the closest |

Kept: `whammy-dt` and `midi-pedal` (MIDI hardware, drawn as hardware units), and `spectral-comp` until golem-fx ships
its own pedal.

### The installers follow (2026-11-15)

**CODED** — the third-party plugins that no block uses any more left the installation on all three OS (and
`provision/components.json`, so System ▸ Licences ▸ Libraries no longer lists them):

- **AIDA-X, Ratatouille, Aether** (Linux, `provision/plugins.sh`): the `amp` block plays NAM; no block named them.
- **Proteus** (Linux `.deb`, Windows `-Proteus`, macOS `--proteus`): `boost` is retired. **BYOD** (Linux): no block.
- **LSP** (Linux, `packages.txt`): no block. `app/vst-host-model.mjs` still recognises it among the user's plugins.
- **Airwindows TapeDelay2** (Linux, Windows; macOS manual pin): `delay-tape-aw` is retired. `provision/airwindows.py`
  and `provision/plugins-deb.sh` are deleted.
- **GoleM Freeze** (Linux, `install-spectral.sh`): `freeze` is retired; its Rust source `plugins/` is deleted.
  Spectral Compressor and PaulXStretch stay in the same script.
- **macOS manual pins**: Spectral Shift (`pitch-spectral` retired); the x42 pin no longer mentions the EQ (`eq-para`
  retired) — the limiter and pitch-correct still need x42.

The uninstallers (`provision/uninstall.py`, `provision/uninstall_win.py`) keep their explicit entries for all of
them: an older install placed them and must still be cleaned up. **What stays until golem-fx ships in the
installers** (it does since 2026-11-15, below — they stay until a later step): guitarix, Calf, x42 / fat1, Dragonfly, ZamAudio, mda, Surge XT, Prisma, PaulXStretch, Spectral
Compressor (nih-plug), zeroconvo, NAM, sfizz, setBfree, Dexed, Vital, AVL Drumkits, DrumGizmo — they still play blocks:
the effects wherever golem-fx is not installed, the rest as instruments, captures and cabs. `reaper/Scripts/golem_rig.lua` keeps its dead Ratatouille path for now.

### Catalogue v49: Spectral Comp and Morph (2026-11-15)

- `spectral-comp` is played by **gfx-spectralcomp** (golem-fx bda4675): the last block a third-party plugin played
  where golem-fx is installed. The ten catalogue ids are kept and mapped to the plugin's names in the engine table,
  `key: true` (Source Key = the lane's DI); the window defaults to 1024. The legacy Spectral Compressor stays the
  fallback where golem-fx is not installed. 18 golem-fx presets, the 7 rack ones converted by golem-fx.
- `morph` is a new golem-fx-only block (gfx-morph, golem-fx 210d4ce), category Lo-Fi, voice lanes: the live vocal
  mangler. 17 presets.
- Not done yet: the meter display (`gr`, `lift_gr`, the eight `dyn_*`), `key_from` (another lane's voice), the
  latency re-sync when a preset switches Live ↔ Studio, gfx-morph's `depends` that golem's descriptor format cannot
  hold (gfx-morph README §3.2), and both on the quiet-machine stall bench.

### The stall bench passes (2026-11-16)

`tools/check-block-stall.py` on the rack, performance governor, 6 switch-ons per wait (1.5 s and 4 s off), control
3 ms: Emet, Met, Shem, Golem (golem-double), Glitch, Flanger (flanger-js), the x42 IR convolver (ir-fx), Spectral
Comp, Morph, Formant, Correct (pitch-correct), and the reworked Fuzz and Dist (golem-fx 5d33aaa) all switch on with
no freeze (max 4 ms). gfx-correct's single 519 ms freeze did not come back. The `bench: pending` key is dropped
from the seven blocks that carried it: no catalogue block is pending any more, so golem.fm's AI may propose them.

### Catalogue v50: Formant (2026-11-15)

- `formant` is a new golem-fx-only block (gfx-formant, golem-fx 048142e), category Pitch, voice and guitar lanes, 17
  presets. Engine Live (no latency, or its Lookahead) or Grain (≈ 9–21 ms by Register).
- **Setup settings** (new rule): a golem-fx setting that changes the latency the plugin reports is listed in the
  engine table (`setup`, here `engine`, `register`, `lookahead`). It lives in the block's base only: the Designer
  writes it there and drops every scene override of it, `scene_bake` ignores an old one, and it never takes the EXP
  pedal. The descriptors' `structural` flag is NOT used for this: it also marks settings played per scene or by foot
  (rotary speed, reverb freeze, delay time).

### golem-fx in the installers (2026-11-15)

**CODED** — the installers ship golem-fx **0.6** (pinned 2026-11-17 — same pedal code as 0.5, rebuilt; 0.5 on 2026-11-15, 0.4 before that) (prebuilt release `golem-fx-0.6` in Goldoralf/golem-binaries, golem-fx
ca0d494, 56 VST3, incl. Formant, Morph and Spectral Comp) on all three OS, pinned and placed without admin rights ([installer.md](installer.md) §2, Pins), and
Windows and macOS now play golem-fx blocks when the plugin is installed, as Linux does
([golem-fx-reaper.md](golem-fx-reaper.md)). The golem-fx-only blocks (Met, Emet, Shem, Tape, Glitch…) are therefore
offered on Windows and macOS too. The third-party fallbacks — guitarix, Calf, Dragonfly, ZamAudio and the rest of the
list above — **stay installed** until a later step retires them: they still play a block wherever golem-fx is missing
or fails to install.

## 2. Will golem have only golem-fx pedals?

For the **effects**, yes: decided on 2026-11-15 ("the golem will run only with our blocks", §1 bis). What remains of
the open-source effects is the step list of §4 and `spectral-comp`. Out of scope, and staying as they are:

- **Captures** (NAM amps, pedals, preamps, compressors): the sound is the capture file; golem-fx draws them but
  does not replace them.
- **Instruments** (Vital, piano, organ, EP, pads, the drum kit).
- **golem features** (Rec, Tuner, Click, Backing Track, Looper, Riff, Drum Machine, Standard, Arrangement, Sample): they
  draw as golem's own devices (golem-fx's "Console" look, da73548), not as pedals.
- **Hardware** driven over MIDI (Whammy DT, MIDI pedals).

## 3. Progress

Generated from the catalogue by `tools/golem-fx-progress.py` (the test suite checks it is current: run the tool after a
catalogue change).

<!-- golem-fx-progress:begin -->
**55 of 60 effect blocks** are played by golem-fx; 5 are ready in golem-fx and not wired yet; 0 have no golem-fx counterpart yet.

| Status | Blocks |
|---|---|
| Played by golem-fx, replacing an open-source plugin (33) | `gate`, `comp`, `eq`, `chorus`, `flanger-js`, `phaser-js`, `tremolo`, `killswitch`, `wah`, `wah-color`, `autowah`, `delay`, `reverb`, `pitch-shift-js`, `pitch`, `volume`, `clean-boost`, `reverb-plate`, `reverb-room`, `reverb-shimmer`, `rotary`, `eq-graphic`, `limiter`, `deesser`, `granular`, `octaver`, `vibrato`, `pitch-correct`, `detune`, `ringmod`, `surge-treemonster`, `spectral-comp`, `guitar-drive` |
| Played by golem-fx, new blocks with no open-source original (22) | `grit`, `golem-double`, `glitch`, `met`, `emet`, `shem`, `swell`, `transient`, `mb-comp`, `ducker`, `widener`, `bass-di`, `tape`, `dist`, `fuzz`, `radio`, `morph`, `formant`, `vocoder`, `acoustic-sim`, `sustainer`, `polysynth` |
| … of which the engine-stall bench is still pending (1) | `grit` |
| Ready in golem-fx, not wired yet (5) | `cab` (gfx-cab, today x42 - IR Convolver Mono), `bitcrusher` (gfx-crusher, today MDA Degrade), `surge-freqshift` (gfx-freqshift, today Surge XT Effects), `ir-fx` (gfx-irfx, today x42 - IR Convolver Stereo), `stretch` (gfx-stretch, today PaulXStretch (Sonosaurus)) |
| No golem-fx counterpart yet (0) |  |
| Out of scope — Captures (the sound is the file) (5) | `pedal-nam`, `preamp-nam`, `comp-nam`, `amp`, `amp-nam` |
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

**`grit` is wired (catalogue v51, 2026-11-21):**

- `grit` → **gfx-grit** (golem-fx 688d9e8, class id `GoleMFxGrit00001`), asked by the maintainer because the block had
  no plugin on the Golem Engine outside Linux (Prisma has no Windows build, and a JSFX does not run in Ardour). The
  block keeps its type, its place in the drawer and its 4 presets, and gains golem-fx's 11 others, Tube and Fuzz,
  Drive, Focus, Level, a mix, a Peak gain, solo and bypass per band, and the 48 dB/oct slope.
- **It is a golem-fx-only block now**, like Tape or Morph: its catalogue entry is the pedal's front panel plus the
  settings below, the rest comes from golem-fx's descriptor. Prisma (Linux) and `golem_grit.jsfx` (Windows, macOS) no
  longer play it: where golem-fx is not installed the block is out of the drawer and of the compile. The JSFX is
  deleted; Prisma stays installed until the installers drop it (no block names it).
- **A setting that changes its unit changes its id** (new rule, catalogue key `was`). gfx-grit's module amounts follow
  laws linear in a real unit (dB, bits) instead of Prisma's, and its band gains are in dB instead of %. So
  `<band>_v1` / `_v2` became `<band>_amt1` / `_amt2` and `<band>_gain` became `<band>_lvl` (bands `lo`, `lm`, `hm`,
  `hi`); every other id is unchanged. `bridge/option_renames.py` converts a document that still carries an old id
  when it is loaded (preset, patch, block preset, scene and lane-state overrides, the Designer sandbox) and removes
  the old id: an old id is never a new one, so the rewrite is pure and idempotent, with no version stamp to trust. The
  formulas are golem-fx's (gfx-grit README, "converting golem's grit values"): a module amount is converted by the
  type of its slot, a scene that changes a slot's type without restating its amount gets the block's amount converted
  for the new type. Tested against golem-fx's converted presets (`tests/test_grit_block.py`).
- One case is not converted: an old document that names a module type and no amount for it played Prisma's amount 0,
  which for Bit crush was already 7.6 bits; it now plays gfx-grit's 0 (16 bits, clean). No factory content does this.
- **Not done yet**: the stall bench (`bench: pending`, so golem.fm's AI does not propose the block until
  `tools/check-block-stall.py` has run on the rack), a listening pass of the converted presets on the rack, and
  the same rule for `bitcrusher`, `surge-freqshift` and `stretch`.

1. `pitch-correct` (catalogue fixes: Live by default, Hard tune's filter, key and scale as real settings), `ringmod` and
   `surge-treemonster`, `granular`, `eq-graphic`.
2. The unit conversions, with saved patches and presets converted once: `bitcrusher`, `surge-freqshift`, `grit`
   (**wired**, catalogue v51, below), `stretch`.
3. `tuner` (a new runtime: one gfx-tuner per lane), then `cab` and `ir-fx` (the IR slot registry; the level of
   converted cabs, +14 dB or 0 dB, is the maintainer's call).
