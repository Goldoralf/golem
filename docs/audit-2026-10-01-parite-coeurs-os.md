# Audit 2026-10-01 — does the amp + cab core sound the same on Linux and Windows?

> **Status: CODED** — incident report. Measured differences between the Linux core (NAM LV2 + x42 convolver) and the
> Windows/macOS core (official NeuralAmpModeler VST3); VST3 settings corrected in `golem_rig.lua`
> `load_native_core`, A2 captures declared unplayable off Linux (`bridge/rig.py` `nam_unreadable`). Tool:
> `tools/check-core-parity.py` (+ `tools/core_render_lv2.c`).

The question came from golem.fm's store compatibility plan, which wanted a measured answer rather than one deduced
from plugin names. Compile side: `bridge/compile_rig.py` (`_native_core_for`).

## 1. What was compared

| | Linux (rack) | Windows / macOS |
|---|---|---|
| `.nam` capture | NAM LV2 (Oliphant) v0.2.2 | official NeuralAmpModeler VST3 v0.7.13, "model only" instance |
| `.wav` IR | x42 zeroconvo (CfgMono, the rack's patched build) | the same VST3, second "IR only" instance |

Same files on both sides: a real 20 s DI take, a 20 Hz–20 kHz sweep at −24 and −6 dBFS, one A2 capture, one
WaveNet capture, one IR.

- **Linux**: rendered by a minimal LV2 host loading the very binaries REAPER uses (two renders bit-identical).
- **Windows**: rendered by native REAPER 7.80 in a VM; the "no plugin" case nulls at −282 dB against the input.

After sample alignment the tool reports the level difference, the **null depth** once gain is equalized (−60 dB =
indistinguishable, −20 dB = close, −5 dB = another sound), and the worst third-octave difference.

## 2. Results

| Case | Before (raw VST3 settings) | After (VST3 set like the LV2, §3) |
|---|---|---|
| IR only | **−18.0 dB**, null −30/−33 dB, 0.08 dB | −0.06 dB, null −30/−33 dB, 0.08 dB |
| WaveNet amp | +1.3 dB, **null −5 dB**, 3.0 dB | −0.01 dB, null −28/−25 dB, 0.06 dB |
| WaveNet amp + IR | **−16.4 dB**, null −4 dB, 3.6 dB | −0.07 dB, null −24 dB, 0.09 dB |
| A2 amp | **the DI comes out unchanged** | unchanged: still the DI |

Once set alike, the two engines match in level and timbre within a tenth of a dB. They remain two implementations
(the −24 to −33 dB residual is not zero); nobody has judged by ear.

## 3. The three causes (read in the plugins' code)

### 3.1 The published official NAM does not read the A2 format

An A2 capture (`architecture: "SlimmableContainer"`, file version 0.7.0) loaded into VST3 0.7.13 passes the DI
through — same level within 0.01 dB, same spectrum — **with no error**. The format reached NeuralAmpModelerCore in
March 2026; the last plugin release **with binaries** is 0.7.13 (December 2024); later versions that read A2 publish
no binaries. On the measuring rack most captures (688 of 906) were A2.

So off Linux a preset built on an A2 capture played **without an amp**, while the block status said the file was
present and the VST3 accepted it — "right form, wrong nature" (see [`CLAUDE.md`](../CLAUDE.md)).

**In code now:**

- `rig.nam_architecture(path)` reads `architecture` from the `.nam` (cached by path + mtime);
- `rig.nam_unreadable()` returns `["SlimmableContainer"]` on Windows/macOS, `[]` on Linux — the single place to
  empty the day a desktop NAM reads A2;
- `rig._wrong_kind` refuses such a file with `A2_DESKTOP_WHY` ("A2 capture — this golem's NAM engine cannot play
  it (the guitar would pass through dry)"); the block status reason is `format`;
- the heartbeat publishes `caps.nam_unreadable` (`blockstatus.py`);
- `bridge/resolver.py` plays the **A1 twin** of an A2 capture when it is installed (TONE3000 publishes each A2
  retraining next to the original under the same name: same setting, same take, two formats). Only a twin of the
  same name, never another setting silently.

Building the official NAM ourselves was not pursued; A2 stays unplayable off Linux until a published NAM reads it.

### 3.2 The NAM LV2 calibrates input and normalizes output; the port set the VST3 to raw

The LV2 always (a) shifts the input by `12 − input_level_dbu` (a 12 dBu interface assumed) and (b) brings the output
to −18 dB loudness from the capture's `loudness`. Shifting the Linux render's input by the computed amount moved the
null from −5 to −28 dB, the best point to 0.003 dB. **In code**: `load_native_core` sets `CalibrateInput = 1`,
`InputCalibrationLevel = 12` (`NAM_CALIBRATION_DBU`), `OutputMode = "Normalized"`, gate and tone stack off.

### 3.3 The official NAM applies −18 dB to every IR; x42 applies none

AudioDSPTools (`ImpulseResponse::_SetWeights`): `gain = 10^(−18/20) · 48000 / sample_rate`, fixed. **In code**:
the IR-only instance gets `Output = 18 + 20·log10(sr / 48000)` dB (`nam_ir_comp_db`, `NAM_IR_COMP_DB`), to which
the `cab` block's `level` is added (`apply_core_params`, livemap). Only 48 kHz was measured; other rates follow the
VST3's law.

## 4. Two traps found on the way

- **`TrackFX_SetParam` takes a NORMALIZED 0–1 value on the NAM VST3**, not the native value: writing 12 to
  `InputCalibrationLevel` set 60 dBu, writing 1 to `OutputMode` set "Calibrated". Switches are written 0/1;
  everything else is targeted by its **displayed** value (`set_param_shown`: enum sweep, or dichotomy).
- **REAPER adds automatic fades to a new item.** Without disabling them, the "no plugin" render only nulled at
  −38 dB.

## 5. Not concluded

- **Oliphant's NAM LV2 on Windows** (Windows x64 binaries exist, same v0.2.2, A2 included): REAPER 7.80 added it with
  an empty URI and declared it unavailable on project reopen. Not resolved.
- **Listening.** A −24 to −33 dB null between two implementations is probably inaudible on a saturated sound;
  untested by ear.
- The DI take used was clipped (thousands of samples at full scale): the interface input gain was too hot. Irrelevant
  here (the same DI feeds both sides) but worth knowing for any take.

## 6. What it means for a block's `dsp` compatibility

| Block | Measured verdict off Linux |
|---|---|
| `amp`, `amp-nam`, `pedal-nam`, `preamp-nam`, `comp-nam` with an A2 capture | **does not play** (dry DI) — refused with reason `format` |
| same, WaveNet capture | same sound within a tenth of a dB (different implementation) |
| `cab` | same sound within a tenth of a dB (with the +18 dB compensation) |

Compatibility depends on the **capture format**, not on the block type.
