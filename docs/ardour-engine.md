# Ardour as a second audio engine

> **Status: CODED — the proposal was adopted.** The engine exists: the **Golem Engine**, built from Ardour 9.9
> (repository `Goldoralf/golem-engine`, GPL), shipped since golem v0.7.0. It is selectable on **Linux and Windows**
> wherever it is installed, and it is the default engine there (`config/engines/ardour.json`); macOS runs REAPER only.
> The bridge talks to an engine contract (`bridge/engine/`), and Settings ▸ Engines ▸ Audio switches between the two
> ([`audio-engine-choice.md`](audio-engine-choice.md)).
>
> **This page is the proposal of 2026-11, kept as the reasoning behind the engine**: the principle (§1), what was
> expected to map or be lost (§2), how the gaps were to be filled (§3), the first plan (§4). It was written before
> anything was built. **What was actually built, in what order, with its measurements, is in
> [`ardour-plan.md`](ardour-plan.md)** (decisions §6, logs §7–§7e). Each section below says where reality differs.

## 1. Principle

The bridge already compiles a preset into an engine-neutral **plan** — tracks, blocks, sends,
scenes (`bridge/compile_rig.py`, `bridge/scene_bake.py`; see [`architecture.md`](architecture.md) and
[`live-engine.md`](live-engine.md)). REAPER materialises that plan through the Lua
scripts in `reaper/Scripts/`, the JSFX in `reaper/Effects/`, `gmem` shared memory and the command
slot. The Golem Engine is a second engine behind an **engine contract** (`bridge/engine/base.py`, `EngineAdapter`;
adapters `reaper.py` and `ardour.py`): commands in the vocabulary `golem_watch.lua` has always read, a fast path
for knobs and transport, and the same telemetry files (`presets/.rig-check.json`, `.livemap.json`…), whoever writes
them. REAPER stays as it is.

- **Free edition**: an engine built by golem from Ardour (GPL, redistributable with the rack). It ships
  under **another name** — the Golem Engine — because Ardour's maintainers ask forks not to call themselves "Ardour".
- **REAPER edition**: per-machine licence paid by the user, every feature.

Each rack declares what its engine can do (`capabilities`, already in the descriptors); the screen
hides what is missing instead of letting it fail.

## 2. What maps, what is lost, what is gained

> **As proposed, before the build.** Today the Golem Engine's descriptor declares all 14 features of
> `config/engines/features.json` as `yes` (lanes and scenes, NAM and IR, recording, backing, click, MIDI clock, looper,
> drum machine, samples, standards, riff, kill switch, previews, reamp) — the descriptor calls this "the target, not a
> measurement"; what was measured, feature by feature, is in [`ardour-plan.md`](ardour-plan.md) §7c–§7e. Its card
> states the known gap: no plugin windows yet. The ➖ and ❓ below are the expectations of the time, not today's state.

Legend: ✅ equivalent · ➖ missing at first (or for good) · ➕ better · ❓ to measure on the rig.

### Sound

| Feature | Under Ardour | |
|---|---|---|
| Lanes, A/B splits, outputs, sends | Tracks, buses and sends (no folders: groups) | ✅ |
| NAM captures (amps, pedals, preamps) | The NAM LV2 plugin golem already uses; session at 48 kHz | ✅ |
| Cabs (IR) | x42 convolver, or the convolver bundled with Ardour | ✅ |
| Calf, guitarix, Dragonfly, Proteus, Prisma, Dexed, setBfree | Standard LV2 / VST3 | ✅ |
| Blocks on REAPER plugins: gate (ReaGate), comp (ReaComp), eq (ReaEQ), delay (ReaDelay), volume (ReaPlugs Volume), pitch (ReaPitch, quarantined) | Free LV2 replacements (§3); the catalog would carry one plugin per engine | ✅ with work |
| Spectral blocks | Ardour has no CLAP host → the VST3 build of the nih-plug plugins | ✅ with work |
| Vital | VST3 on Linux, reliability varies; fallback Vitalium LV2 | ❓ |
| Pads / kits on ReaSamplOmatic5000 | sfizz or DrumGizmo | ➖ at first |
| Scene switch without rebuild | Parameters, bypass, mutes at runtime over OSC / HTTP; plugin activation off the audio thread | ❓ gaps to measure |
| Latency compensation | A bypass that changes latency forces a recompute → use the plugin's own bypass port | ❓ |

### Services

| Service | Under Ardour | |
|---|---|---|
| Multitrack recording (DI, BWF timestamps) | Ardour's core job | ✅ ➕ |
| Backing tracks (stems) | Regions on the timeline + transport | ✅ ➕ |
| Arrangement following bars | Driven by the bridge, transport position read over OSC | ✅ |
| Click | Ardour's metronome; grouped accents (3+2+2…) to rebuild | ✅ / ➖ |
| MIDI clock | Sent only while the transport runs → keep the transport running | ✅ |
| Whammy DT, foot controller | Already in the bridge, engine-independent | ✅ |
| Preset previews, reamp | Render a track through its chain; blocks live play during the render, as with REAPER | ✅ |
| Foot looper (`golem_super8`) | Rewrite (§3) | ➖ at first |
| Drum machine, samples, standards (JSFX + `gmem`) | Rewrite (MIDI regions + DrumGizmo/AVL, sfizz) | ➖ at first |
| Knob tap, kill switch, de-esser (JSFX) | LV2 equivalent (de-esser) or rewrite | ➖ at first |
| Tuner | x42-tuner LV2; reading the note from the bridge to verify | ❓ |
| Measurement tools (gap meter, block stall, clock witness) | JSFX detectors to rewrite | ➖ at first |

### The rack

| | Under Ardour | |
|---|---|---|
| Cost, redistribution | Free, GPL, shipped with the rack | ➕ |
| Control from the bridge | Ardour's HTTP control API (recent, experimental) and OSC, instead of a Lua watcher and a command file | ➕ ❓ |
| Sound card unplugged | Ardour stops and reports an I/O error (REAPER reports nothing — see [`CLAUDE.md`](../CLAUDE.md)) | ➕ |
| Headless | `luasession` runs libardour with Lua and no GUI; `hardour` takes `-B <backend>` (JACK/PipeWire is only its default) — measured 2026-11-10, [`ardour-plan.md`](ardour-plan.md) §7 | ✅ |
| Shared memory bridge ↔ DSP (`gmem`) | Does not exist → exchanges over OSC / API | ➖ |
| ARM64 | Official arm64 builds; low-latency effects on small boards unproven ([`rack-classes.md`](rack-classes.md)) | ❓ |
| 24/7 endurance on stage | No public data | ❓ |

## 3. Replacing what is missing

> **What happened instead of the table below:** the blocks were not handed to third-party LV2 plugins engine by
> engine. golem wrote its own effects, **golem-fx**, which play the catalogue's blocks on both engines and on all three
> systems, and retired the old third-party pedals ([`golem-fx-migration.md`](golem-fx-migration.md),
> [`golem-fx-reaper.md`](golem-fx-reaper.md); decision D3 of [`ardour-plan.md`](ardour-plan.md) §6). The rule that
> follows — our own plugin, running in both editions — is the one that was kept.

**Rule:** what Ardour lacks is not rewritten as Ardour Lua DSP (slow, no file access). It comes from
a mature free plugin, or is written **in Rust with nih-plug** — the toolchain of the spectral blocks
(`plugins/`), which builds VST3 (for Ardour) and CLAP (for REAPER). A golem plugin therefore runs in
**both** editions.

| Block | Today | Under Ardour | Write our own? |
|---|---|---|---|
| gate (thresh, attack, hold, release, hpf, lpf, hyst) | ReaGate | LSP Gate | No |
| comp (thresh, ratio, makeup, attack, release) | ReaComp | LSP Compressor, Calf, x42-dyn | No |
| eq (midgain, midfreq, lowcut, highs) | ReaEQ | x42-fil4, LSP Para EQ | No |
| delay (BPM-synced time, feedback, mix) | ReaDelay | Calf Vintage Delay, x42-delayline | No |
| volume (gain) | ReaPlugs Volume | Ardour's bundled amp | No |
| pitch (shift, mix) | ReaPitch (quarantined: it freezes the engine) | Rubber Band LV2, if it passes `tools/check-block-stall.py` | No (hard) |
| killswitch | `golem_killswitch.jsfx` | Nothing equivalent | **Yes**, Rust |
| deesser | `golem_deesser.jsfx` | Calf Deesser | Optional |
| looper | `golem_super8` (LGPL fork, 4 stereo loops, one master length, MIDI-note commands; the foot logic is in `bridge/looper.py`, the state comes back through `gmem`) | ysfx (JSFX host in VST3) keeps the notes working but loses the state; or a Rust rewrite | **Yes**, Rust (recommended) |

A Rust looper must keep the same model (4 loops, one length, rec / overdub / play / stop / clear /
kill all / play all), preallocate its buffers, avoid clicks at loop and punch points (short fades),
record what the musician **heard** (compensate input latency), allocate nothing on the audio thread,
and publish its state.

The real cost is not the code:

1. **Parameter mapping** — the catalog describes each knob for one plugin (range, curve, index); it
   needs one entry per engine (`plugin.reaper` / `plugin.ardour`).
2. **Tone** — presets were tuned by ear on ReaComp, ReaEQ…; another compressor at the same values
   sounds different.
3. **Rig validation** — every plugin passes `tools/check-block-stall.py` and two rebuilds before it
   is offered (see the plugin pitfalls in [`CLAUDE.md`](../CLAUDE.md)).

## 4. Plan

> **Superseded.** The plan that was followed is [`ardour-plan.md`](ardour-plan.md) §5 (phases A0–A5), with a log per
> phase. Step 5 below ("Product") is done on Linux: the installer always installs the Golem Engine and offers REAPER
> as a checkbox ([`install-v2.md`](install-v2.md)).

Each step has a gate: the next one starts only if the measurement says yes.

| Step | Content | Gate |
|---|---|---|
| 0 — Engine contract | Write what the bridge asks of an engine (the plan, the command set), what it expects back (witnesses, meters, clock, state files) and the capabilities. An `EngineAdapter` interface in the bridge; REAPER moves behind it **without behaviour change**. Useful even if Ardour stops there. | Test suite green, rig identical at the foot |
| 1 — Ardour test bench | Our Ardour build on PipeWire-JACK; one lane (gate LV2, NAM, IR), two scenes, one stomp, driven through HTTP/OSC by a prototype adapter. Measure round-trip latency, scene-switch gap, block-activation stall over the catalog, sound-card unplug, 24 h endurance with ported tools. | Each measure ≤ REAPER, or an accepted gap |
| 2 — Core engine | Full plan (paths, splits, sends, outputs), scenes without rebuild, stomps, parameters, captures and IRs with a file check equivalent to `rig-check`, meters, health. One plugin per engine for the REAPER-only blocks; spectral blocks in VST3. | Real presets play at the foot; `check-scene-gap` and `check-block-stall` green |
| 3 — Near-free services | Takes, backing tracks, click, MIDI clock, arrangement following, previews, reamp | A rehearsal recorded end to end |
| 4 — Rewrites | Looper, drum machine, samples, standards, knobs, kill switch, tuner: for each, port it or keep it REAPER-only | Per feature |
| 5 — Product | Engine choice at install, capabilities in the heartbeat, features hidden with "available with REAPER", Ardour pitfalls in `CLAUDE.md`, GPL sources published with the build | — |

## 5. Decisions — taken

The four questions this page left open were settled on 2026-11-10 ([`ardour-plan.md`](ardour-plan.md) §6):

1. **Which ➖ features must exist in the free edition** — looper and click first (D6); the descriptor now declares
   every feature, the drum machine, samples and standards included.
2. **The name** — **Golem Engine** (D1).
3. **Distribution package or our own build** — our own build, in `Goldoralf/golem-engine`, pinned by release in the
   installers (Ardour 9.9, D8).
4. **Windows** — reached on 2026-11-20 (D7; PortAudio/ASIO, [`ardour-plan.md`](ardour-plan.md) §7e). macOS: not
   ported.
