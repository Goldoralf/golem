# Spectral blocks — Spectral Comp, Stretch, Freeze

> **Status: CODED** — three spectral blocks (`spectral-comp`, `stretch`, `freeze`) in the catalog, built from
> pinned sources by `provision/install-spectral.sh`; validated on the bench, not yet judged by ear.

golem does not clone commercial spectral suites (no Linux build to study, licences forbid decompiling, and copying
code or UI would be infringement). The DSP is public (phase vocoder, bin-wise companders): golem reuses two
GPL-3 projects and writes its own blocks on one of them. One block = one stage gesture; a 36-effect sound-design
tool is not the goal.

Block definitions (params, roles, notes, `_validation`) live in `library/catalog/effects.json`, the source of
truth. Block rules in general: [`blocks-doctrine.md`](blocks-doctrine.md).

## 1. Two bases

| | Spectral Compressor (nih-plug author) | PaulXStretch |
|---|---|---|
| Licence · tech | GPL-3.0-or-later · Rust, **nih-plug** framework (ISC), `realfft` | GPL-3 · C++, JUCE 6 fork, FFTW |
| Formats built | CLAP + VST3 | CLAP + VST3 (no standalone) |
| Role | the engine to **write** golem blocks (`StftHelper`: window, overlap-add, per-bin callback) + one block as is | one block as is: a texture instrument, not a base to fork |
| Latency | the window (2048 → ~43 ms at 48 kHz) | hundreds of ms to seconds, by design |

## 2. The blocks

### `spectral-comp` — Spectral Comp (category `dynamics`)

`CLAP: Spectral Compressor (Robbert van der Helm)`. A compressor **per FFT bin**, downwards and upwards, with a
threshold **curve** across the spectrum. Smooths a voice or pad without pumping, holds a synth pad. Params:
`thresh`, `down`, `up`, `center`, `slope`, `attack`, `release`, `window`, `mix`, `out`; others stay at the plugin
default. Roles: voice, keys, pads, guitar, bass.

### `stretch` — Stretch (category `reverb`)

`CLAP: PaulXStretch (Sonosaurus)`. Not a continuous effect: a **capture-and-stretch** instrument. `capture` on
records the input (up to `maxlen` s); off commits it and plays it looped, stretched (`amount` ×0.1 to ×1024)
through the spectral modules (`pitch`, `fshift`, `spread`, `compress`); `freeze` holds the play position.
`thru` (pass input through) is **off by default in the plugin** and **on by default in golem**: an insert that
swallows the direct signal is a silence nobody would find. Other params: `fft`, `vol`, `spread_on`, `comp_on`
(module switches set by the compile). `capture` and `freeze` are foot booleans (a stomp on Capture = a spectral
looper). Roles: voice, keys, pads, guitar, bass (not drums). Direct latency 0. Placement: last in the lane.

### `freeze` — golem Freeze (category `reverb`)

`CLAP: GoleM Freeze (GoleM)`, our own plugin: crate `plugins/golem_freeze` (Rust workspace `plugins/`, bundler
`xtask`), on nih-plug, CLAP + VST3, GPL-3, no GUI (the rack drives parameters).

- **Gesture**: the freeze pedal — a chord, a tap, it **holds** and you play over it; tap again, it fades in
  `decay` seconds. A tap toggles: the foot controller sends toggles, not press/release.
- **Algorithm** (`src/lib.rs`): the direct always passes through the STFT analysis/synthesis unchanged (Hann ×
  Hann, overlap 4, gain compensated), so latency equals the declared window. On engage the magnitudes of the
  first `CAPTURE_FRAMES` (4) frames are averaged (never freeze a transient) and each bin's **instantaneous
  frequency** is measured; each output frame = frozen magnitudes × a phase advancing at that frequency (a classic
  phase vocoder — advancing at the bin centre made the freeze stutter at the frame rate), plus a gentle phase
  jitter (`smear`). `tone` tilts the frozen spectrum ±6 dB/oct around 1 kHz. Release decays exponentially per
  frame.
- **Params**: `freeze` (bool, foot), `mix` (0–100 %, EXP-safe), `decay` (0.05–10 s), `smear` (0–100 %), `tone`
  (0–100, centre 50), `window` (enum 1024/2048/4096 = the latency).
- **The foot drives the `Freeze` PARAMETER, never the bypass** (`golem_rig.lua` `switch_param_of` → `fx_set_on`,
  like the x42 convolver's "Enable"): latency never moves, the release tail sounds, and the plugin sees a rising
  edge = capture.
- Roles: guitar, bass, voice, keys, pads. Placement: after amp/cab, before delay/reverb.

### Latency rule

`spectral-comp` and `freeze` add their window (2048 → 42.7 ms), compensated by REAPER's PDC **on the lane**.
They never belong in the base path of a guitar lane (the block `note` says so): use them on a split branch or on
voice/keys/pads lanes.

## 3. Writing parameters: `map.mode: "pow"`

On nih-plug (CLAP and VST3) as on JUCE, a parameter written with `TrackFX_SetParamNormalized` is applied on the
**audio thread**: reading it back in the same call returns the **previous** value, and a bypassed FX never
applies it. The display dichotomy of `golem_rig.set_norm_to_target` therefore lands on wrong values for these
plugins. They use `map.mode: "pow"` (`golem_rig.lua`, block param writer), written without reading back:

- `norm = ((v − min) / (max − min)) ^ exp`, with the **plugin's** bounds (`map.min`/`map.max`) and exponent
  (nih-plug `Skewed{factor}` = `2^n`, JUCE `NormalisableRange` skew = `exp`);
- `sym` + `center`: two halves around the centre (nih-plug `SymmetricalSkewed`);
- `db`: the value is in dB, the port is a linear gain.

Enums are written raw on the integer port (`window`: order − 6). Because a knob absent from the preset is never
written, the three blocks carry **`defaults: "compile"`**: the catalog defaults are written at compile time (the
plugins' own defaults would leave Spectral Comp at 1:1 and Stretch with the direct cut).

## 4. Installation

`provision/install-spectral.sh` (sudo, like `install-prisma.sh`):

1. headers: `libfftw3-dev` (PaulXStretch) and the X11/xcb/xkbcommon dev packages nih-plug's editor needs.
   **No JACK**: Spectral Compressor's `standalone` feature is removed at build time and PaulXStretch is built with
   `JUCE_JACK=0` (a plugin never opens a device);
2. Rust: user-side `rustup` (`~/.cargo`, minimal profile, shell untouched) if missing;
3. nih-plug at a pinned commit → `Spectral Compressor.clap` + `.vst3` in `~/.clap` / `~/.vst3`;
4. PaulXStretch at a pinned commit → `PaulXStretch.clap` + `.vst3`;
5. `plugins/golem_freeze` → `GoleM Freeze.clap` + `.vst3`;
6. restart REAPER (it only rescans at startup).

Licences: `provision/components.json` lists `fftw3`, `nih-plug`, `spectral-compressor`, `paulxstretch` and the
freeze block (System ▸ Licences ▸ Libraries).

## 5. Validation

Each block's `_validation` field in `effects.json` records what was measured. All three passed: `fxadd` under
the block's plugin name, `tools/check-block-stall.py` (no stall; the −41…−47 ms seen on Spectral Comp are the
PDC coming in), every knob read back at the expected displayed value, two rebuilds, catalog defaults written at
compile. For Freeze: scene A/B and stomp drive the parameter (FX always active), and the hold was measured (a
−20 dB tone, frozen then cut: ≈ −21 dB still held at +4 s; released: −81 dB at +3 s). None has been judged by
ear yet; Stretch's foot Capture gesture is not validated.

## 6. Out of scope

Dozens of effects, modulators routable to any parameter, visualizations, a large studio UI. A missing stage
spectral effect (spectral gate, smear, bin shift) is a new ~100-line block on the Freeze engine, one gesture each.
