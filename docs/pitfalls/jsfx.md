# JSFX / EEL2 pitfalls

The rack's own DSP lives in `reaper/Effects/*.jsfx`. EEL2 compiles silently: a wrong program runs,
it just does the wrong thing. Check witnesses (output sliders) on a live engine.

---

## EEL2 is case-insensitive

**Symptom.** A sequence loops back every bar; a value read from `gmem` is garbage; an index constant
"changes" at runtime.

**Cause.** `seq_len` and `SEQ_LEN` are the same variable. `seq_len = gmem[SEQ_LEN]` overwrites the
index constant with the value it just read, and the next block reads from a wrong address.

**Rule.** Never give a local copy the same name (in any case) as a constant. Prefix local copies
(`cur_len`, `cur_slot`).

**Detect.** Witness sliders; diff the expected `gmem` index against the one actually read.

**Code.** `reaper/Effects/golem_drumseq.jsfx` (`cur_len`, `cur_slot`, `cur_barppq` convention).

---

## Code before the first `@` section never runs

**Symptom.** Constants declared at the top of the file (after the `slider:` lines) are all zero. A
JSFX reads `gmem[0]` for every index, ratios collapse to 1, behaviour looks almost plausible.

**Cause.** Only code inside sections (`@init`, `@slider`, `@block`, `@sample`…) is executed.

**Rule.** Every constant and initialisation goes in `@init`.

**Detect.** A witness slider that publishes a constant; `grep -n '^@' file.jsfx` and check nothing
but `desc:`/`slider:`/`in_pin:`/options precede the first section.

**Code.** `reaper/Effects/golem_click.jsfx` (all constants in `@init`).

---

## A slider with a negative minimum is bipolar for REAPER

**Symptom.** Writing a normalized value lands on the wrong raw value; e.g. a trigger note is read as
−1 and every trigger is handled as "stop": the block is completely silent.

**Cause.** For a slider like `<-1,127,1>`, REAPER maps normalized 0.5 to ZERO: `[0, 0.5]` covers
min→0 and `[0.5, 1]` covers 0→max. The linear formula `(v-min)/(max-min)` writes nonsense. Sliders
with a minimum of 0 are linear, which hides the bug elsewhere.

**Rule.** Write the RAW value with `TrackFX_SetParam(tr, fx, p, value)` for rack JSFX — it does not
depend on any taper. Never normalise linearly a slider whose minimum is negative. For third-party
plugins whose taper is unknown, search by displayed value (dichotomy).

**Detect.** Commands `fxparams` (read real parameters of an FX) and `fxset` (write then read back).

**Code.** `reaper/Scripts/golem_sample.lua` (raw `TrackFX_SetParam`), slider definitions in
`reaper/Effects/golem_sample_trig.jsfx`; dichotomy on display in `golem_rig.lua` `set_norm_to_target`.

---

## The audio thread has a budget

**Symptom.** Choppy, crackling sound when a JSFX does heavy work; kernel xrun counters may not show
it.

**Cause.** A heavy computation done in one `@block` exceeds the audio-thread budget for that block.

**Rule.** Decimate and spread heavy work across blocks; keep `@sample` minimal. Measure health on
the engine, not on kernel xrun counters.

**Detect.** REAPER's performance meter for the track; audible artefacts while the JSFX is enabled
vs bypassed.

**Code.** `reaper/Effects/golem_tuner` (`DECIM` decimation before the pitch search).

---

## A JSFX meter cannot see an engine stall

A JSFX that counts the samples it processes cannot detect a moment when REAPER processes nothing.
Compare against an independent clock. See
[reaper.md](reaper.md#a-plugin-can-freeze-the-whole-audio-engine-when-it-turns-on)
and `reaper/Effects/golem_gapmeter.jsfx`.

---

## NaN propagates through the output

A NaN or inf coming from upstream passes through a limiter that only compares magnitudes. The output
safety stage replaces NaN/inf with silence. Code: `reaper/Effects/golem_safety.jsfx`.

## EEL2 has no exponent notation — and REAPER loads a JSFX that does not compile

`1e-6` or `1e-15` is not a number for EEL2. The JSFX fails to compile, but `TrackFX_AddByName` still inserts it
(the error shows in the FX window only), **every slider reads 0 and the audio passes through dry** — nothing in the
engine says so. Measured in a bench REAPER on 2026-10-22: a four-slider test JSFX whose `@init` used `1e3` read 0 on
every slider; the three wah clones rendered white noise unchanged after a denormal guard was written `+ 1e-18`; and
**`golem_shimmer` and `golem_tapedelay`, shipped the day before with `abs(x) < 1e-15 ? x = 0`, had been passing
audio dry all along** (DRYWET = 1 gave the dry burst back, no tail) — a stall bench and a recall through a fake
REAPER had "validated" them, neither compiles EEL2. Write numbers in decimal (`0.000000000000001`);
`tests/test_portable_jsfx_blocks.py` refuses exponent literals in golem JSFX. The honest check is a render through
the JSFX compared with what the file promises (noise in, FFT or tail out), not "the FX was added".

---

## `@init` runs again at every transport start

**Symptom.** A JSFX that holds state between commands (a sequencer playing, armed, waiting) forgets it when the
transport starts: it replays its last command, rewinds, and its all-notes-off lands in the very block where it plays.
Measured on 2026-10-26: the tick 0 of a standard take was cut dead, while the Riff's click file at the same position
sounded.

**Cause.** REAPER runs `@init` on load, on a sample-rate change **and on playback start**, unless the JSFX sets
`ext_noinit = 1` in `@init`.

**Rule.** A JSFX whose state lives only through commands (`gmem` nonce) sets `ext_noinit = 1`.

**Detect.** Record the JSFX's output through a take starting at 0 and look for the event at sample 0, next to a
reference that does not go through the JSFX (an audio item at 0).

**Code.** `reaper/Effects/golem_chordseq.jsfx`; measured by `tools/check-rig-materialize.py --standard-take`.
