# CPU budget: will this preset play on this golem?

> **Status: PROPOSED** (2026-11-15). The maintainer asked for it after a rehearsal where scenes A and C of a patch
> crackled (xruns) and gfx-fuzz cut the sound on an overloaded core. Direction approved in conversation: measure,
> do not guess; calibrate automatically; golem says what to do; show it in the Designer, the Library, /live and the
> Companion. Nothing is coded.

## 1. What counts: the busiest lane, not the number of cores

REAPER spreads **tracks** over the cores, but a chain of effects on one track runs **in series on one core**: each
block waits for the one before it. At 48 kHz with a 192-sample buffer, a lane has about **4 ms per buffer on one
core** to run its whole chain. If one lane goes past that, the sound crackles or stops, however many cores are idle.

So the verdict on a preset is its **busiest lane in its heaviest scene**. The total in cores is shown too, as
information (several lanes, the drums, the backing), never as the verdict.

- A bypassed effect costs (almost) nothing in REAPER: what counts in a scene is the blocks that are **on** in it.
- A split's branches are separate tracks: they can run on separate cores. A merge waits for all its branches.

## 2. Where the numbers come from: a calibration per machine

A theoretical sum does not hold: the cost changes with the processor, its governor (powersave vs performance, seen on
2026-11-15), mono vs stereo, the sample rate, the buffer, and some settings (oversampling, gfx-formant's Grain engine,
the NAM capture's architecture, the cab IR's length). So golem **measures** on the machine it runs on.

- **The bench**: each block type is rendered offline through the engine, mono and stereo, at this machine's sample
  rate and buffer, with its catalogue defaults. The bench reports the time per buffer, both the average and the worst
  of N buffers. The worst case matters: a circuit simulation spikes.
  - NAM: one measure per **architecture** (standard, lite, feather, nano, A2), since the captures of one
    architecture cost the same.
  - Cab IR: a measure per IR length bucket.
  - golem-fx pedals: the same bench in golem. golem-fx's own `gfx-bench` numbers are a cross-check.
  - Third-party plugins the user adds in VST Host: measured the first time they are added; until then "not measured".
- **When** (the maintainer's choice: automatic):
  - after the install;
  - after a golem update or a golem-fx release that changes a plugin (its binary hash);
  - when a new plugin is added;
  - when the machine changes: a different CPU, core count, sample rate or buffer.

  It only runs when the rack is idle, like the demo renderer (`reamp.busy_reason`: no take, no song playing, no
  gesture for 10 min), and resumes where it stopped.
- **How long**: about 60 block types × 2 (mono and stereo) × a few seconds each, so **roughly 5 to 10 minutes** the
  first time on a desktop CPU. After that, only what changed: a new pedal takes a few seconds. This estimate is to be
  confirmed by the first run.
- **The profile**: `config/cpu-profile.json` (local state, never committed). It holds:
  - the machine: CPU model, cores, governor at measure time, sample rate, buffer;
  - one entry per block: type, variant, mono/stereo, µs per buffer (average and worst), the plugin's hash and the
    date.

## 3. What golem shows

| Where | What |
|---|---|
| Block sheet (Designer), Library ▸ Pedals | "≈ 9 % of a core" (this lane's mono/stereo) |
| Lane (Designer chain) | a bar against the one-core budget: green ≤ 60 %, orange ≤ 80 %, red above; per scene, the heaviest scene marked |
| Preset / patch (Songs, Designer header) | the verdict (plays / tight / will crackle), from its busiest lane in its heaviest scene; plus "1.2 of 8 cores" |
| Add block drawer | before adding: "this lane would go to 85 %" |
| /live, Companion | the verdict of the loaded song and of the next one in the setlist; a warning chip only when tight or red, never a number on stage |

Every figure says **what machine and when** it was measured, and "not measured" where it was not.

## 4. What golem proposes (the maintainer's choice)

When a lane is orange or red, golem proposes concrete fixes, cheapest first. Each fix is a button where golem can do
it, and a sentence where it can't.
1. **CPU in performance mode** if the governor is powersave (`POST /api/perf-mode`, already there).
2. **Turn off a block nobody hears in that scene** (on but at mix 0, or doubled).
3. **A lighter variant**: a NAM capture with a lighter architecture, Live instead of Grain, oversampling off.
4. **Split the lane**: move the heavy part of the chain to a branch, which goes on another track and another core.
5. **A bigger buffer** (256, 384): more room, more latency. golem says how many ms that adds.
6. Otherwise: "this preset is too heavy for this golem", with the lane and the block that weighs most.

## 5. Checking the prediction while playing

golem already counts xruns. Still to verify before coding: whether REAPER exposes the real CPU per track or per FX to
scripts. If it does, golem compares prediction and reality and corrects the profile, so a lane that crackles below
its predicted budget teaches the bench something. If it does not, xruns per scene are the check.

## 6. golem.fm

The profile's summary (CPU model, cores, sample rate, buffer, cost per block) can go up with the heartbeat, so that
golem.fm says whether a shared preset will play on **your** golem before you load it. This is optional and follows
docs/golemfm-protocol.md.

## 7. Limits we accept

- It is an **estimate with a margin**, not a guarantee. Spikes, heat and other programs can still make a lane
  crackle. On 2026-11-15 GNOME's file indexer used more than a full core during rehearsal.
- Mono vs stereo, sample rate and buffer are measured; per-setting variations (oversampling, Grain) are measured only
  for the settings the catalogue marks as heavy.

## 8. Open questions

- The thresholds 60 % / 80 % are to tune after the first measures on the rehearsal rack.
- Should the bench also run the Golem Engine (Ardour) when it is the active engine, or only the engine in use?
- On the Companion, is the chip enough, or does a musician want the "what to do" too?
