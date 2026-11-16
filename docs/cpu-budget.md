# CPU budget: will this preset play on this golem?

> **Status: FIXED** (2026-11-16): direction approved 2026-11-15, mockup "CPU budget mockup" (5 screens: Designer,
> fixes sheet, /live, Companion, Library ▸ Amps) validated by the maintainer 2026-11-16. Coding in 4 lots (§9). The
> maintainer asked for it after a rehearsal where scenes A and C of a patch crackled (xruns) and gfx-fuzz cut the
> sound on an overloaded core.
>
> **Lot 1: CODED 2026-11-16** (`bridge/cpu_budget.py`, `bridge/cpu_bench.py`, `bridge/routes_cpu.py`, the `bench` op
> of `golem_preview.lua`, the `cpu` fact of Health). Not yet run on a rack: the first real calibration confirms the
> timings below. What lot 1 decided or changed is in §11.
>
> **Lots 2–4: CODED 2026-11-16** (app only, against the §9 shapes; the routes come with lot 1). Pure logic in
> `app/cpu-budget-model.mjs` (tested), fetches and shared pieces in `app/cpu-budget.js` + `app/cpu-budget.css`.
> Deviations from the mockup, decided while coding:
> - Designer: the topbar has no room left, so the verdict chip sits at the right of the chain's title row, compact
>   ("Tight · Guitar 78 %", the cores in its tooltip and in the sheet). The bar per lane, the scenes and each block's
>   share live in the sheet the chip opens (the Main screen); a tight or red lane also gets a dot on its tab.
> - Fix buttons: `perf-mode` (POST /api/perf-mode), `buffer` (opens Settings ▸ System), and in the Designer only
>   `turn-off` (the block off in that scene) and `lighter-capture` ("Use it" when the action carries `ref`, else "Find"
>   opens the capture picker). `mono` and `split` stay a sentence. A fix with `action.lane` shows on that lane; the
>   others belong to the busiest lane. On /live and the Companion the sheet is read-only.
> - /live: the chips live in the bank bar (the loaded song, the next one in the "next" peek) and on the rows of the
>   songs picker. Lists (Songs ▸ Presets, setlist rows) show a compact "CPU" chip coloured by the verdict; "plays" is
>   silent everywhere outside the Designer.
> - Library: costs are asked mono; a NAM capture's variant is sent as `nam:<arch>` (`standard`, `lite`, `feather`,
>   `nano` from the catalogue's `size`, `a2` when `arch` is 2). A capture's chip is coloured on a block scale (≤ 10 %,
>   ≤ 25 %), not the lane thresholds.
> - A route answering FastAPI's 404 `Not Found` silences every CPU read of the page until it reloads; an empty profile
>   reads "not measured". Never an error banner.

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

## 9. The contract between the bridge and the app (lot 1 serves it, lots 2–4 read it)

All under `/api/cpu/`, read-only except `calibrate`. Percentages are of ONE core's budget for one buffer
(`budget_us = buffer / srate × 1e6`); `null` means "not measured".

- `GET /api/cpu/profile` →
  `{machine: {cpu, cores, governor, srate, bsize, engine}, measured_at, budget_us,
    blocks: {"<type>[:<variant>]|mono|stereo": {avg_us, worst_us, pct, at, hash}},
    calibration: {state: "idle"|"waiting"|"running"|"done"|"failed", done, total, current, waiting_for, error}}`
- `POST /api/cpu/calibrate` `{force?: bool, types?: [..]}` → starts the bench (refused with 409 when the rack is busy:
  `reamp.busy_reason`), measures what is missing or changed (plugin hash, machine, srate, bsize).
- `GET /api/cpu/estimate?preset=<id>|sandbox` →
  `{verdict: "ok"|"tight"|"red"|"unknown", budget_us, cores, total_cores, worst: {lane, scene, pct},
    lanes: [{id, name, pct, worst_scene, by_scene: {A: pct…}, blocks: [{id, type, label, pct, stereo, measured,
    on: {A: bool…}}]}],
    fixes: [{id, title, sub, gain_pct, action: {kind: "perf-mode"|"mono"|"split"|"buffer"|"lighter-capture"|
    "turn-off", …} | null}],
    machine: {cpu, governor, bsize, srate}, measured_at}`
  Thresholds: ok ≤ 60 %, tight ≤ 80 %, red above (one constant, `cpu_budget.THRESHOLDS`). A lane with an unmeasured
  block gets `verdict: "unknown"` unless the measured part is already red.
- `GET /api/cpu/estimate-many?ids=a,b,c` → `{id: {verdict, worst: {lane, scene, pct}}}` (setlist rows, /live,
  Companion).
- `GET /api/cpu/swap?preset=<id>|sandbox&block=<id>&ref=<tone id>[&model=<id>]` → the lane before/after replacing
  that block's capture: `{lane, before_pct, after_pct, verdict_after, lighter: {ref, model, pct}|null}` (Library ▸
  Amps listening bar, Add to…).
- A block's own cost for the Library and the drawer: `GET /api/cpu/block?type=&variant=&stereo=` →
  `{pct, avg_us, worst_us, measured}`; a NAM capture's variant is its architecture (`nam:standard`, `nam:lite`…), read
  from the capture.

## 10. Lots

1. **Bench, profile, estimate** (bridge): `bridge/cpu_budget.py` (pure estimate from a compiled plan + profile),
   `bridge/cpu_bench.py` (the calibration, idle-gated like the demo renderer), `config/cpu-profile.json`, the routes
   above, `golem doctor` facts. The bench never runs while someone plays.
2. **Designer and fixes sheet** (app): the header verdict chip, a bar per lane against one core with the
   heaviest scene, each block's share, the fixes sheet; the Add block drawer shows "this lane would go to N %".
3. **Library**: Amps (per-capture cost and architecture, the listening bar before → after, Add to… greys a lane
   pushed into red), Pedals (cost per pedal).
4. **/live and Companion**: a chip only when tight or red, for the loaded song and the next ones; tap = the fixes
   sheet, read-only on stage.

## 11. What lot 1 coded, and where it departs from the text above

- **How the bench measures.** Through the demo engine, never on the live track: a bench patch of one lane holding only
  the measured block (catalogue defaults) is posed by the recall path, with its lane **cut in its scene** (level at
  the floor: nothing reaches the speakers, even if a guitar is plugged in). `golem_preview` clones the lane (no
  hardware output, unarmed), lays the reference DI (`guitar/clean`), and its `render` op with `bench: 3` renders
  offline at full speed three times, timed with `time_precise` around the render action, then removes the clone's FX
  and renders three times more (the baseline: reading, resampling, writing). Cost per buffer = (median with − median
  without) / buffers rendered, minus the cost of an **empty lane** measured once (the FX golem puts on every lane).
  "worst" = the slowest render with the block against the fastest without.
- **Precision and limits.** A total render time cannot see the spike of one buffer: `worst_us` is the spread between
  runs, not the worst buffer. The live engine runs during the render; its noise enters both sides and cancels on
  average. A render that ran in real time (not full-speed offline) is refused, not recorded.
- **Mono and stereo.** The bench measures the **stereo** instance only: a REAPER track has two channels and a plugin
  processes both, whether the lane is mono (a mono input lands on both) or stereo. Keys are `…|stereo`; a lookup of
  `…|mono` falls back to the stereo measure. This halves the bench time (about 75 targets, not 150).
- **The lane model.** A lane's figure is its critical path: pre + the heaviest branch + the merge (post). Branches run
  in parallel, the merge waits for them (§1). A branch muted by the scene still counts, by prudence: golem does not
  assume REAPER skips the FX of a muted track (that is a preference, not verified on the rack).
- **Fixes served:** `perf-mode` (governor not `performance`; `gain_pct: null`, the bench cannot measure the other
  governor), `turn-off` (on at mix 0, or the same sound twice on a track), `lighter-capture` (another installed model
  of the same tone, same name without its size suffix, with a cheaper **measured** architecture), `buffer` (the next
  size of `AUDIO_BSIZES`, with `latency_ms`; its gain is the per-run spread spread over more samples), and a final
  `too-heavy` sentence (`action: null`). **Not served:** `mono` (golem cannot make a plugin process one channel: it
  picks no per-lane plugin variant and sets no pin mapping) and `split` (under the critical-path model, moving the
  tail of a chain to a branch does not shorten it: the branch still waits for the pre — no gain to announce).
- **Variants.** NAM: `nam:standard|lite|feather|nano` (the trainer's WaveNet sizes, read from the layers), `nam:a2`
  (SlimmableContainer), `nam:lstm-<layers>x<size>`, `nam:wavenet-<hash>` for a custom size; one installed capture
  per variant is measured. Every NAM block type (amp, amp-nam, pedal-nam, preamp-nam, comp-nam) uses the `nam:` keys.
  A head with no cab downstream also costs the default cab the compile fuses to it. IR: `cab:<bucket>` and
  `ir-fx:<bucket>`, buckets 50, 100, 200, 500, 1000, 2000, 5000 ms and `long`, measured with the longest installed IR
  of each bucket.
- **Not measured in lot 1:** instruments (Vital, piano, E-Piano, organ, pads, drum kit: their cost depends on what is
  played), the capture module, blocks with `bench: pending` (they may freeze REAPER), quarantined blocks, plugins not
  in REAPER's inventory. A lane holding one of them, on, is `unknown` unless already red.
- **Re-measure and validity.** A measure is redone when its plugin fingerprint changes (golem-fx binary hash, the
  identifier REAPER scanned, the NAM build) or the machine changes (CPU, cores, sample rate, buffer, engine). Until
  then a new buffer or sample rate is corrected pro rata of the samples; another CPU or engine voids the profile.
- **API as served (§9):** shapes unchanged. Additions: each lane also carries its own `verdict`; `GET /api/cpu/block`
  accepts `type=amp&variant=nam:standard` as well as `type=nam&variant=standard`. `/api/cpu/` reads need a paired
  device (`SENSITIVE_GET_PREFIX`: an estimate tells what a preset holds); `POST /api/cpu/calibrate` is admin
  (`ADMIN_WRITES`) and, pressed by hand, skips the "10 min without a gesture" rule (someone is at the screen) but
  keeps the rest of `reamp.busy_reason`.
- **When.** The idle watcher (`cpu_bench.start_idle`, every 60 s; `GOLEM_CPU_BENCH=0` turns it off) starts the bench
  whenever something is pending and the rack is free; each measure is written as it lands (resumable); the sandbox is
  posed back at the end, only if the rig is still the bench patch. Under the Golem Engine the bench waits (§8).
- **First calibration time, estimated:** about 75 targets × ~10 s (rebuild, 3 s settle, 2 s clone settle, six renders
  of an 11 s DI) ≈ **12–15 min**. To be confirmed by the first run.
