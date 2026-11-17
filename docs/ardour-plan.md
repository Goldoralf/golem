# Ardour engine — action plan

> **Status: FIXED** (plan validated 2026-11-10, decisions in §6) — A0 measured (§7), A1 and A2 coded (§7b, §7c); state on
> 2026-11-17 in §7d: the factory's 52 patches measured on the engine, the A2 leftovers, the keys instruments, the command
> guard and recording coded, the other services to do. The principle and
> the feature map are in [`ardour-engine.md`](ardour-engine.md); how an engine is described and chosen
> is in [`audio-engine-choice.md`](audio-engine-choice.md). This page says **how** we build it, in
> what order, and how each step is proven.

## 0. Where we start (facts read on 2026-11-10)

| | |
|---|---|
| Engine descriptor | `config/engines/ardour.json`: `selectable: false`, says "built from Ardour **9.8**". Upstream's latest tag is **9.9**. |
| Ardour on the dev machine | Not installed. No clone, no build. |
| Bridge ↔ REAPER coupling | ~35 commands through `presets/.command.json` (`rig_recall`, `stomp`, `mixer_apply`, `meters`, `midi_reinit`, `set_buffer`, `dumpfx`, `preview`, `backing`, `drums`, `sample`, `tuner`, `vst_*`…), ~25 telemetry files `presets/.*.json` (`.livemap`, `.rig-check`, `.clock`, `.fxdump`, `.looper`…), OSC for meters and fast parameter writes, `gmem` between Lua and JSFX. 16 bridge modules call `write_command`. |
| REAPER side | 23 Lua scripts (`golem_rig.lua` alone: 4 373 lines), 36 JSFX. |
| Catalog | 74 blocks in `library/catalog/effects.json`. Per-OS overrides already exist (`effects-windows.json`, `effects-macos.json`). |
| Sound homogeneity today | **Already broken across OSes**: on Linux `chorus` is Calf Multi Chorus, on Windows/macOS it is `golem_chorus.jsfx` — the same for 18 blocks (flanger, phaser, tremolo, wah ×3, tape delay, shimmer, rotary, eq ×2, octaver, vibrato, grit…). |
| Factory content | 9 factory presets; lanes: guitar 13, bass 8, keys 8, drums 7, voice 6, keys-pads 1. Blocks used: guitar 26, bass 13, keys 14, voice 9, drums 6. |
| Reference DI | `library/di-refs/`: guitar ×7 (clean, crunch, high-gain, djent, funk, lead, lead-clean), keys ×5 MIDI, drums ×4 MIDI. **No bass DI, no voice DI.** |
| Plugins installed | NAM LV2, x42, Calf, guitarix, Dragonfly, MDA, Zam, LSP, Surge XT, sfizz, DrumGizmo, setBfree; VST3: Prisma, Vital, Dexed, Spectral Compressor, PaulXStretch, golem Freeze. |
| Existing measurement tools to reuse | `tools/check-core-parity.py` (renders the same DI through two hosts and measures the null depth), `check-rig-materialize.py`, `check-block-stall.py`, `check-scene-gap.py`, `check-scene-latency.py`, `check-foot.py`, `check-ui.py`, `tests/fakereaper.lua`. |

## 1. Fork strategy — follow upstream, keep our changes small

**Goal:** take every Ardour release with a few hours of work, never a merge war.

### 1.1 Three layers, from cheapest to most expensive to keep

| Layer | What | Conflicts with upstream |
|---|---|---|
| **Outside the tree** | Bridge adapter (Python), session template, our plugins (Rust), Lua scripts loaded at run time | None |
| **Overlay** — new files only, in a `golem/` directory at the root of the fork | Our control surface `golem/surface/` (C++, built as an Ardour surface module), branding assets, build and bundle scripts, CI | None: upstream never touches `golem/` |
| **Patches** — changes to upstream files | Only what cannot be done otherwise: hook the overlay into `wscript`, branding/program name if the configure option is not enough, headless backend if needed, bug fixes | Yes — this is the layer to keep small |

**Patch budget: ≤ 10 commits, each small.** Every patch carries a tag in its subject:
`[build]`, `[brand]`, `[headless]`, `[fix]`, `[upstreamable]`. An `[upstreamable]` patch is
proposed to Ardour (tracker / pull request) and dropped from our branch the day it lands upstream.

### 1.2 Repository and branches

- A **separate public repository** (name decided with D1), GPL, with upstream Ardour as a remote.
  `golem` never vendors Ardour's sources; it pins a **binary** of a tagged build, as it does with REAPER.
- `upstream/*` mirrors upstream; we build **only from release tags** (`9.9`, `9.10`…), never from master.
- Our work = the branch **`main`** (decided by the maintainer on 2026-11-17; it was `golem/9.9` until then, kept
  as it was that day): Ardour's tag `9.9` + overlay commit + patch commits. The repository is **not a GitHub fork**:
  Ardour is only a remote we follow. A **release of our engine is a tag on `main`** (`golem-engine-<version>`) —
  the exact sources of each shipped binary (GPL obligation), what `golem-binaries` builds and golem pins.
- **Update** to an upstream release: **merge** Ardour's tag (`9.10`…) into `main` — never a rebase, `main` is never
  rewritten — review, rebuild, run the full bench (§4). Rollback = the previous tag's binary.
- **Early warning**: a weekly CI job rebases our branch on upstream master and builds. A red job tells us
  months before a release that a patch will conflict. It never ships anything.

### 1.3 Build and distribution

- Dev: `./waf configure` with the distribution's dependencies (Ubuntu 24.04).
- Shipped: a **self-contained bundle** (Ardour's own packaging approach, dependencies bundled), installed
  under `~/opt/<engine>/` like `~/opt/REAPER`, so Mint/Debian work without distro packages.
- Binaries in `golem-binaries` (where third-party binaries already live), sources = the tag of the fork.
- Engine updates use the REAPER update pattern (`bridge/reaper_update.py`): pinned version, verified
  start, automatic rollback. Never during a take, a song or Show mode.
- **Linux only** in this plan (Windows/macOS: D7).

## 2. Engine contract — the prerequisite (step A1)

The bridge must stop knowing REAPER. Everything below goes through an `EngineAdapter`
(`bridge/engine/` — `base.py`, `reaper.py`, `ardour.py`):

| Group | Calls | REAPER today | Ardour |
|---|---|---|---|
| Lifecycle | `start`, `stop`, `restart`, `status`, `version` | `desktop_reaper.py`, Xvfb | process supervision, same launcher |
| Audio device | `set_device`, `set_buffer`, `set_rate`, `dsp_load`, `xruns` | `set_buffer`, `audio_reset` | Ardour ALSA backend reconfigure |
| Rig | `apply_plan` (rebuild), `scene_apply` (state switch), `stomp`, `set_param` (fast path), `mixer_apply` | `rig_recall`, `stomp`, `mixer_apply`, OSC | surface socket |
| Witnesses | `rig_check` (each plugin loaded, each file loaded), `live_map`, `fx_params`, `meters` | `.rig-check.json`, `.livemap.json`, `dumpfx`, OSC meters | pushed by the surface, written to the **same** files/schemas |
| MIDI | `midi_inputs`, `midi_reinit`, routing of a device to a lane | `midi_reinit`, `I_MIDIFLAGS` | ALSA MIDI ports, port connections |
| Services | `preview`, `reamp`, `record`, `backing`, `click`, `clock`, `tuner`, `looper`, `drums`, `sample` | dedicated Lua loops | per phase (§5) |

Rules:
- **REAPER moves behind the adapter first, with no behaviour change** (gate: test suite green, rig
  identical at the foot). This step is useful even if Ardour stops here.
- The adapter declares its capabilities; the app reads them (`audio-engine-choice.md` E1) and hides
  what is missing instead of failing.
- **Control channel (D4, recommended):** our C++ **surface** in the overlay, listening on a local socket
  (JSON lines), running Ardour API calls on the right thread, **pushing** telemetry (no polling, no
  command file). It replaces `golem_watch.lua` + `.command.json` for Ardour. A one-day spike with
  Ardour's built-in OSC + Lua comes first, to measure whether we can avoid C++ at all.
- Tests: a fake surface (`tests/fakeardour.py`) as `tests/fakereaper.lua` does for REAPER, so the adapter
  is tested in CI without Ardour.

## 3. Block strategy — one block, one sound, every engine

### 3.1 The rule

A block offered in the Designer is **one binary**, loaded by every engine on every OS where it exists.
A block is admitted only if its plugin:

1. is free software whose licence allows redistribution with golem;
2. exists in a format **both** hosts load (LV2 or VST3 for Ardour; LV2, VST3 or CLAP for REAPER on Linux);
3. passes `check-block-stall` and two rebuilds **in both engines**;
4. exposes its parameters by **stable identifier** (LV2 symbol / VST3 id), not by index.

If a mature free plugin satisfies the four → **integrate it**. Otherwise → **recode it** in Rust/nih-plug
in the existing `plugins/` workspace (CLAP + VST3), in a suite named **golem-fx**. No Ardour Lua DSP, no
per-engine substitute that sounds different.

### 3.2 The 74 blocks sorted

| Tier | Blocks | Under Ardour | Work |
|---|---|---|---|
| **T1 — same binary already** (≈45) | amp, amp-nam, pedal-nam, preamp-nam, comp-nam (NAM LV2) · cab (x42) · boost (Proteus) · grit (Prisma) · chorus, flanger, phaser, tremolo, rotary, delay-tape (Calf) · wah, wah-color, autowah, reverb-shimmer, vibrato, octaver, eq-graphic (guitarix) · reverb, reverb-plate, reverb-room (Dragonfly) · eq-para, limiter, pitch-correct (x42) · granular (Zam) · ringmod, bitcrusher, rezfilter (MDA) · surge-spring, surge-freqshift, surge-treemonster · spectral-comp, stretch, freeze, pitch-spectral (VST3 builds of our Rust/nih-plug ones) · delay-tape-aw (airwindows) · vital (VST3) | Load as is; port the parameter mapping (by symbol) | Mapping + bench |
| **T2 — REAPER-only, recode in golem-fx** (≈13) | gate (ReaGate) · comp (ReaComp) · eq (ReaEQ) · delay (ReaDelay, BPM sync) · volume, clean-boost (ReaPlugs / JS Volume) · chorus-js, flanger-js, phaser-js, guitar-drive, pitch-shift-js (stock JSFX) · killswitch, deesser (our JSFX) | Missing | Rust plugin per block, **voiced to match the REAPER original** at the parameter values the presets use |
| **T3 — instruments and services** | drumkit, pads (RS5K) · organ (setBfree + `b3-ctl.jsfx`) · piano, ep (sfizz) · whammy-dt, midi-pedal (MIDI out) · looper, tuner, rec, click, compo, sample, drums, standard, arrangement, backing-track | Per feature | Phase A4, feature by feature (D6) |
| **Quarantined** | pitch (ReaPitch), detune, delay-echo | Stay unavailable unless a candidate passes the stall test | — |

**Why recode T2 instead of picking LSP/Zam equivalents:** factory and user presets were tuned by ear
on ReaComp, ReaEQ, ReaGate, ReaDelay at given values. Another compressor at the same values sounds
different, so a straight substitute breaks every preset in the free edition. A golem-fx plugin voiced
against the REAPER render (same curves, same parameter units as the catalog) keeps the presets'
sound — and is measurable (§4). The JSFX we wrote ourselves (killswitch, deesser) are ported, not
reinvented. These are simple DSP; the parameter units already exist in the catalog.

**DECIDED 2026-11-12 (maintainer) — supersedes the voicing rule above:** no backward compatibility on sound. The T2 list
is built as **new golem effects** in the separate repository `golem-fx` (`~/code/golem-fx`, VST3, Rust/nih-plug, its
own agent), voiced as golem wants, to become golem's default blocks later; presets will sound different then. They
**keep the catalog's parameter ids and units**, so a preset keeps its settings when its block switches. The parity
bench then proves the same binary sounds the same in both engines (null ≤ −50 dB), not a match with ReaGate/ReaComp.
The ReaGate/ReaComp clones written that day (§7c) were removed from golem the same day: golem-fx starts from scratch
and keeps only the measurements and test ideas. Brief sent to golem-fx the same day (priority: gate, comp, eq, delay,
clean-boost/volume, killswitch, deesser, guitar-drive, flanger, phaser, chorus, pitch-shift; pitch and detune as a bonus;
a gap-meter probe).

**Consequence for REAPER (D3, recommended):** once a golem-fx block passes the bench against its
REAPER original, the catalog switches **both** engines to it. Then a block sounds the same in REAPER
and in our engine, and the catalog keeps one plugin per block (no `plugin_by_engine` except as a
temporary escape). Later, outside this plan, the same suite can replace the 18 Windows/macOS JSFX
substitutes and close the OS gap too.

## 4. How sound is proven — without asking anyone to listen first

**DECIDED 2026-11-13 (maintainer) — supersedes the parity thresholds below: we do not aim at the same sound
everywhere.** golem-fx effects are new sounds (2026-11-12), and two engines need not null against each other. The
benches below stay, **to catch engine bugs**: a setting that never reaches the plugin, a scene not applied, a block
missing, a level jump when the rack switches engines. A deep null is a hint, a poor one is not a failure; nobody
chases a third-octave. An instrument is closed (A3) when:

1. every block its role is offered **plays on the Golem Engine**: it is placed, follows its settings, its scenes and
   the foot (`check-engine-blocks.py`, `check-engine-ardour.py`, `check-rig-materialize.py --engine golem-engine`);
2. **no level jump**: each factory scene of that role within ±1 dB of the same scene under REAPER
   (`check-rig-materialize.py --render --against`, level only);
3. the maintainer has **listened** to the golem-fx effects of that role and says yes or no: their sound is a choice,
   not a measurement.

A new bench, `tools/check-engine-parity.py`, generalising `check-core-parity.py`:

1. **Render** a DI (or a MIDI ref) through a block, a preset or a scene in REAPER (its own REAPER with
   dummy audio on a `git worktree`, as `check-rig-materialize.py` does — the rack next to it sees nothing)
   and in our engine (offline export through the surface).
2. **Compare**: level difference, latency offset, **null depth** after alignment and gain match,
   third-octave spectral difference, envelope (attack/release behaviour).
3. **Thresholds**:
   - T1 (same binary): null ≤ −50 dB. A worse result means a mapping bug, not a sound difference.
   - T2 (recoded): level ≤ 0.5 dB, each third-octave band ≤ 1 dB, envelope within 10 %; plus an A/B
     pair of WAV files for **your** ear, only for T2 blocks and only after the numbers pass.
   - Preset level: every factory preset × every scene × its DI — level ≤ 1 dB, no new clipping.
4. **Stall**: every plugin through the Ardour port of `check-block-stall.py`, two rebuilds.
5. Reports land in the scratchpad, never in `presets/`; a run restores every file it touched.

Safety (CLAUDE.md): no bench while someone plays; nothing that records or makes sound on the rack's
outputs; the dummy-audio worktree is the default.

**Bass and voice (D9):** there is no bass DI and no voice DI; their lanes are benched with a guitar DI
(`guitar/clean` for voice, `guitar/djent` for bass). That proves the path and the blocks, not the
instrument's tone, which is checked later on the rig.

## 5. Phases

Each phase ends with a gate; the next starts only if the gate is green. Sizes are relative
(S < M < L < XL).

### A0 — Fork, build, spikes (M)

- Fork repository, `golem/9.9` branch, overlay skeleton, reproducible build, bundle under `~/opt`.
- Spikes, each answered by a measurement:
  1. ALSA backend driven without the GUI: `hardour`/headless with ALSA, or the GUI on Xvfb as REAPER today.
  2. Control: OSC + Lua coverage (create track, insert LV2/VST3, set parameter by symbol, bypass, mute,
     sends) vs. what needs the C++ surface.
  3. Round-trip latency, scene switch (bypass/mute without rebuild) gap, plugin activation stall — on
     a one-lane NAM + IR session.
- **Gate**: build reproducible from the tag; spikes give numbers ≤ REAPER or an accepted gap; D1, D2,
  D4, D5 decided.

### A1 — Engine contract (L)

- `EngineAdapter`, REAPER moved behind it without behaviour change; capabilities read by the app;
  `engine` block-state reason; `caps.engine` in the heartbeat; fake surface for tests.
- **Gate**: `pytest tests`, `node --test`, `check-rig-materialize.py`, `check-scene-latency` identical
  to before; you play a set at the foot and notice nothing.

### A2 — /system on the new engine (L)

The /system pages are the first user of the engine; they need a minimal core underneath
(materialize a built-ins-only fixture patch: one lane, NAM + IR, two scenes, one stomp).

| Page | Work | Proof |
|---|---|---|
| **Launch** | `golem desktop` / `golem server` start the chosen engine; supervision, restart, logs (`/tmp/golem-<engine>.log`) | cold start → sound; kill → incident + restart |
| **Dashboard** (System ▸ Dashboard) | engine status, DSP load, xruns, buffer and sample rate (`/api/audio-buffer` → backend), restart button (route renamed engine-neutral, old one kept), meters | every tile shows real values; buffer change applied and read back |
| **Health** | facts made engine-neutral: audio thread advancing, plugins loaded, files loaded, card present; `check-silence` and `doctor` for Ardour | an unplugged card raises an incident (Ardour reports it, REAPER does not) |
| **Soundcard** (Gear ▸ Soundcard) | ALSA device chosen from `config/io.json` / card setups; input map → Ardour ports; outputs; card change; MIDI port | each input meters on the right lane; card swap without reboot |
| **Pedalboard** (Gear ▸ Pedalboard/Controllers/Pedals) | `foot.py` unchanged; adapter carries scenes, stomps, EXP → parameter (fast path); ports of `check-scene-latency`, `check-scene-gap` (the gap meter JSFX becomes a golem-fx probe plugin) | scene ≤ 40 ms at the real foot; EXP drives a wah; `check-foot` green |
| **USB devices** (Akai MPK, Nitro, keyboards; Gear ▸ Drums, Calibration) | MIDI devices → lanes (channel filtering, splits: `note-zone`/`sysex-io` equivalents), hotplug (`midi_reinit`), calibration flows, Whammy DT out (bridge, unchanged) | MPK keys + pads and Nitro pads reach their lanes; unplug/replug; calibration saves a profile |

- **Gate**: `check-ui.py` green with engine = Ardour (no French, no scroll, same buttons); every /system
  page shows real values; the fixture patch plays at the foot with scenes and stomps.

### A3 — /designer, instrument by instrument (XL)

Order: **guitar → bass → voice → keys → drums → keys-pads**. For each instrument:

1. Every block its role is offered (`role_blocks` / `role_categories`): insert in the Designer,
   materialize, read and write each parameter (`fxparams` / `fxset` equivalents), toggle in a scene,
   stall test, parity bench (§4).
2. T2 blocks of that instrument are recoded in golem-fx **before** the instrument is closed
   (guitar: gate, comp, eq, delay, volume, clean-boost, chorus-js, phaser-js, killswitch;
   voice: deesser; the rest follow).
3. Every factory preset with that role: all scenes rendered with the matching DI, compared to REAPER.
4. Designer UI: the drawer hides what the engine lacks (capabilities), nothing else changes.

- **Gate per instrument** (2026-11-13, §4): every offered block plays on the engine or is hidden with a reason; no
  factory scene of that role jumps by more than 1 dB between engines; the maintainer has listened to its golem-fx
  effects. Sameness of sound is not a criterion.

### A4 — Services (L, feature by feature)

Recording, backing, click, MIDI clock, arrangement, previews, reamp (near-free under Ardour), then the
rewrites — looper, drum machine, samples, standards, tuner, knob tap — **only those D6 keeps for the free
edition**. Each one as its own small plan.

### A5 — Product (M)

`ardour.json` → `selectable: true` on Linux with measured capabilities; installer engine screen;
verified engine switch with rollback (`audio-engine-choice.md` E2–E4); Ardour pitfalls in
`docs/pitfalls/`; GPL sources linked from Settings ▸ About; user docs.

## 6. Decisions (taken 2026-11-10)

| # | Question | Decision |
|---|---|---|
| D1 | Engine name (Ardour's maintainers ask forks not to use "Ardour") | **Golem Engine** |
| D2 | Licence of our overlay (it links Ardour) | Overlay under **GPL-2.0-or-later**; golem-fx plugins under GPL-3.0-or-later (separate binaries) |
| D3 | Do golem-fx blocks also replace REAPER's stock plugins in the catalog? | **Yes**, each once it passes the bench against its original |
| D4 | Control channel | **OSC + Lua if that is enough** (spike A0.2 decides); the C++ surface only for what they cannot do |
| D5 | Headless: `hardour` vs. GUI on Xvfb | Whatever spike A0.1 measures as more reliable |
| D6 | T3 features required in the free edition | Looper and click first; drum machine, samples, standards later or REAPER-only |
| D7 | Scope | Linux only; Windows/macOS later |
| D8 | Upstream pin | 9.9, then each release after the bench |
| D9 | Bass and voice DI | The bench uses a **guitar DI** for bass and voice lanes: it proves the audio path and the blocks are correct, not the instrument's tone. Real bass and voice are checked later on the rig |

## 7. A0 log (measured)

**2026-11-10 — build and first render, dev machine (Ubuntu 24.04), local clone of tag 9.9.**

- Build from the tag: `--program-name="Golem Engine" --with-backends=alsa,dummy --optimize`, 8 min, 286 MB.
  The program name needs **no patch**. It is lowercased into binary names (`golem engine9-export`, with a
  space): a name without a space for binaries is still to choose.
- **Headless works without the GUI**: `luasession` (Lua interpreter on libardour, no X) picks the backend
  from Lua (`AudioEngine:set_backend`); the dummy backend is hidden from the list in optimized builds but
  selectable by name. `hardour` also takes `-B <backend>` (the "JACK/PipeWire only" in
  `ardour-engine.md` is only its default).
- **Lua covers the core of a lane** with no C++: create a session and a mono track, insert LV2 by URI,
  load a NAM model and an IR through LV2 file properties (`set_plugin_insert_property`; the IR convolver
  of the catalog is `zeroconvolv#CfgMono`), set parameters, bypass (`enable`), activate, mute, read
  latency, DSP load, xruns. Insert ≈ 2–4 ms; bypass, mute and parameter writes return in < 0.05 ms
  (call side only — the audible gap is still to measure, A0.3).
- Lua has **no file import** without the GUI → the overlay tool `golem-place` (C++, `golem/tools/`)
  places a DI on a track; Ardour's own `…-export` renders the session. That is the bench renderer.
- **Parity (T1)**, same DI and same binaries, Golem Engine vs the minimal LV2 host of
  `check-core-parity.py`: offset 0 samples, level 0.00 dB, worst third-octave band 0.00 dB; null
  −86/−91 dB with the IR alone; with NAM −40/−48 dB over the whole file, **−141 dB after the first second**
  (NAM warm-up starts at a different moment in each host). Two renders in a row are identical (−300 dB).
  → the bench measures T1 nulls after a 1 s warm-up.
- Pitfalls met: `luasession` swallows Lua errors and crashes at exit ("exception not rethrown") — scripts
  wrap their body in `xpcall`; `ImportStatus.replace_existing_source = true` reaches an unimplemented
  path that blocks forever.

**2026-11-10 — real sound card (Universal Audio Volt 276, ALSA backend, REAPER stopped).** No engine output
was connected to the card during the tests (master and every track disconnected, nothing reached the
outputs).

- The ALSA backend opens the Volt at 48 kHz from Lua (device "Volt 276", buffer, periods). Physical
  ports: `system:capture_1/2` (Main In 1/2), `system:playback_1/2` (Out Left/Right), and the Volt's DIN
  MIDI in and out through the ALSA sequencer. The MPK and the Nitro were not plugged in: not tested.
- Ardour's D-Bus device reservation fails ("Audio1" held by PipeWire/wireplumber) and is only a warning:
  the device opens anyway. REAPER does not use the reservation.
- Software monitoring must be set (`monitoring-model = SoftwareMonitoring`, track monitoring forced to
  input) for a live rig: Ardour's default is external monitoring.
- **Scene switches, measured** on a recorded sine → NAM → IR, three cycles at 128 × 2: plugin bypass
  (`enable`) on NAM or IR = **no gap**; IR deactivate / activate = 1–2 ms gap, one click out of three on
  deactivate, **no engine freeze** (the same convolver freezes REAPER ~540 ms on re-activation); lane mute /
  unmute clean. → scenes use `enable`, as planned.
- **Xruns occur only while building** (session creation, plugin instantiation: 3 to 7). While running,
  two NAM + IR lanes for 30 s: **0 xrun** at 64 × 3, 128 × 2, 128 × 3 and 256 × 2. DSP load: 63 % (peak
  72 %) at 128 × 2, 61 % at 128 × 3, 37 % at 256 × 2, peak 95 % at 64 × 3. REAPER on this rack runs 192 × 3.
  → a rebuild must stay out of a song, as with REAPER.
- Pitfall: Ardour remembers a master → hardware connection in the session file (`ExtConnection`) even
  after `disconnect_all`; a reloaded session can reconnect it. The engine must assert its routing after
  every load, not trust the file.
- Not measured yet: round-trip latency (needs a cable loop), card unplug, 24 h endurance.

**2026-11-10 — fork published.** `github.com/Goldoralf/golem-engine` (public), default branch `golem/9.9` (`main` since 2026-11-17)
= tag 9.9 + 3 commits: `[build]` overlay hook, `[brand] [upstreamable]` `PROGRAM_SLUG` (binaries
`golem-engine9-*`, config `~/.config/golem-engine9`; renders bit-identical to before the patch), the overlay.
Remotes: `origin` = our fork, `upstream` = Ardour.

## 7b. A1 log

**2026-11-10 — lot A1.1: the adapter, REAPER behind it (CODED).**

- `bridge/engine/` — `base.py` (`EngineAdapter`: commands, fast path, feedback, lifecycle, capabilities read
  from `config/engines/<id>.json`), `reaper.py` (`ReaperEngine`), `fake.py` (`FakeEngine`, for tests),
  `__init__.py` (`get()` = the adapter of `engines.current()`, one per process; `use()` swaps it).
- **The command dict is the contract.** `commands.write_command` is now the door: it calls
  `engine.get().send(cmd)`. REAPER's transport is the unchanged queue + slot, renamed `commands.enqueue`.
  None of the ~80 call sites changed. An adapter declares the actions it accepts; an unknown action returns
  `None` and is logged once (REAPER accepts all).
- **Fast path** through the adapter: `set_fx_param`, `set_track_volume`, `set_track_mute`, `transport(op)`
  (`play`/`pause`/`stop`/`start`), `refresh()`. The backing no longer holds REAPER action numbers; they live
  in `engine/reaper.py` with the same values (1007, 1008, 1016, 40042, 41743). `app.reaper` is the adapter
  (the name stays: modules and tests read it).
- `caps.engine` / `caps.engine_version` in the heartbeat come from the adapter, no longer a literal.
- Checks: `tests/test_engine_adapter.py` (9 tests: default engine, fallback, door, unknown action, same
  numbers and OSC addresses); `pytest tests` 3031 passed, `ruff`, `check-syntax`, `node --test` green.
  Live rack after `reload.sh`: a command sent through the door is acknowledged by `golem_watch`; the OSC
  feedback reaches `on_osc` through the adapter (probe message).
  `check-rig-materialize.py --working-tree --fixture`: 37 patches materialized, 0 failed, 2 skipped (patches
  with an empty capture slot), scene A→B on each.
- Seen on the rack, not caused by this lot (same `ReaperLink`, same action 41743): after the reload,
  REAPER sent no OSC feedback in the 7 s after `osc-refresh` — the 2026-10-13 symptom ("REAPER stops
  applying OSC, a restart fixes it"). Later the same day, after another bridge reload and with no REAPER restart,
  the feedback was back (`reaper_connected` true): a passing REAPER silence, not the adapter.

**2026-11-10 — lot A1.2: lifecycle behind the adapter (CODED).** `EngineAdapter.pid()` / `running()` /
`ready_since(t0)` / `restart(why)`. The process monitor (`monitors._monitor_reaper`) and the remount after
a restart read the **active** engine's PID and readiness (`_engine_pid`, `_engine_ready_since`); REAPER
answers with the same functions as before (`_reaper_pid`, golem_watch's "démarré" line in `.watch.log`).
`POST /api/system/reaper-restart` calls `engine.get().restart()` (REAPER: the unchanged Linux SIGTERM +
`start.sh`, or the desktop audio re-apply on Windows/macOS); an engine that cannot restart → 409. Settings
that rewrite `reaper.ini` then restart (buffer, card) stay REAPER code: they belong to the audio-device group,
moved in A2.

**2026-11-10 — lot A1.3: blocks the engine cannot play (CODED).** `config/engines/features.json` gains a
`blocks` key (feature → block types: `looper` → `looper`, `samples` → `sample`, `pads`, `riff` → `compo`…).
`blockstatus.engine_gate()` lists the types whose feature the active engine does not declare `yes`;
`block_state` returns `unavailable`, reason **`engine`**, `why` "not available on <engine> yet" (`planned`) or
"<engine> can't play this block" (`no`). REAPER declares everything: nothing changes. The app needs no
change (the block sheet shows `why`, alternatives and Remove for any reason). Docs: `block-status.md`,
`audio-engine-choice.md`.

**2026-11-10 — spike for A1.4: the control channel without C++ (measured, dummy backend).** In one
`luasession` process: Ardour's **OSC surface** activated from Lua (`ControlProtocolManager.manager():activate(info, "")`,
port 3819) applies `/strip/mute 1 1` and `/strip/plugin/parameter 1 1 1 v` while a **Lua loop** polls a
command file every 0.5 s, applies `mute` / parameter commands and writes an ack — 0 xrun. → The Ardour
adapter takes REAPER's shape: a Lua watcher (`golem/engine/golem_watch.lua` in the overlay) reading the same
command slot and ack, OSC for the fast path, telemetry files with the same schemas. D4 holds: no C++ surface.

**2026-11-10 — lot A1.4: the Golem Engine behind the adapter (CODED).**

- Fork overlay: `golem/engine/golem_watch.lua` (session load/create, OSC surface on, a command already in the slot
  at start is acked but never run, then a 30 ms loop: decode, ack `{seq, t}`, run; writes the "démarré. surveille"
  line golem's monitor waits for; minimal JSON in Lua) and `golem/engine/run.sh` (environment, PID in
  `presets/.engine.pid`, `exec luasession`). Vocabulary so far: `ping`, `status` (→ `presets/.engine-status.json`:
  backend, rate, buffer, DSP, xruns, tracks, rolling). Not committed in the fork yet.
- `bridge/engine/ardour.py` (`ArdourEngine`): commands through the **same slot** (`commands.enqueue`), accepts only
  `ping`/`status` (anything else → `None`, logged once); fast path on Ardour's OSC addresses (`/strip/mute`,
  `/strip/fader`, `/strip/plugin/parameter` strip, plugin and parameter 1-based, `/transport_play|stop`,
  `/goto_start`, `/refresh`). Ardour writes **raw** plugin values: the bridge's normalized value is converted
  with ranges the engine will publish (`load_ranges`, linear or log); no known range → refused. The surface is
  told to send its feedback to the bridge's port (`/set_surface/port|strip_types|feedback`), and its feedback is
  **translated** to the bridge's vocabulary (`/strip/meter` dB → `/track/N/vu` with 1.0 = 0 dBFS, `/strip/mute` →
  `/track/N/mute`): `app.on_osc` is unchanged. PID from `.engine.pid` checked against `/proc` (process name,
  zombie); `restart` = stop (SIGTERM, wait) + `run.sh`; version = `git describe` of the engine tree.
- Selection: still `engines.current()` (the descriptor stays `selectable: false` until E3). Dev only:
  `GOLEM_ENGINE=ardour` forces the adapter in a bench bridge. `commands._reaper_up` asks the active engine.
  The descriptor is renamed "Golem Engine", built from 9.9, sources = our fork.
- Checks: `tests/fakeardour.py` (fake OSC surface + fake watcher) and `tests/test_engine_ardour.py` (9 tests);
  `tools/check-engine-ardour.py` drives the **real** engine through the adapter on a throw-away root and free
  port: restart, PID, watcher ready, version `9.9-3-g6659440631`, ping acked, `rig_recall` refused, transport
  started and stopped over OSC, 0 xrun, clean stop — all OK.
- Risk noted: Ardour's OSC surface listens on `0.0.0.0:3819` without authentication (REAPER's port 8000 does the
  same today). To close before a rack runs it: bind to loopback (a small `[headless]` patch or the surface's
  config), or firewall it.
- **A1 gate, scene latency at the real foot (2026-11-10, REAPER behind the adapter)** — `check-scene-latency.py 120`,
  one patch, SW1–SW5 only: 37 presses in 66 s, **37 `scene_apply`, 0 rebuild**. Press → command +66 ms median
  (p95 91), taken by REAPER +76 (p95 109), applied +113 (p95 146, max 196). Reference 2026-09-21 (17 presses, another
  patch, two months of code earlier): +54 / +68 / +99. The adapter's door costs 0.07 µs per command (measured), so it
  does not explain the gap; the press → command part (recall and compile in the bridge) carries it. No regression
  attributable to A1; the ≤ 40 ms budget of the 09-21 audit remains its own project.
  A first capture taken right after a bridge reload showed one rebuild on the first scene press: the boot adoption
  (`recall._boot_recall`) does not seed `_LAST_EMIT`, so the first scene after any bridge restart rebuilds —
  pre-existing, not changed here.
- Set played at the foot after the measure: nothing noticed (maintainer, 2026-11-10). **A1 gate passed.**

## 7c. A2 log

**2026-11-10 — lot A2.0: the minimal core on the Golem Engine (CODED, dummy backend).**

- **The bridge resolves, the engine executes.** `bridge/engine/ardour_plan.py` turns the compiled plan
  (`<id>.rig.json`, the one REAPER reads) + the catalog + `library/catalog/effects-golem-engine.json` (new: the
  plugin of each block type on this engine, LV2 URI or Ardour Lua DSP name, and the LV2 properties that carry
  files) into an **engine plan**: routes, links, blocks with plugin, files, and each parameter reduced to
  "label = value". Pure, tested in CI. `ArdourEngine` joins that plan **to the `rig_recall` / `scene_apply` command
  itself** (a queued scene can never overwrite the plan of a recall not yet read).
- **Topology:** `main` / `pre` = audio track on the card input; `branch` = bus fed by its `pre`; `merge` = bus fed
  by its branches, gain `merge_gain`, out to `out_sel`. **Mono to the card**: 1 in / 1 out per route, the output
  port linked to each requested card output — no panner, so no pan law, unity gain like REAPER. Stereo in A3.
- **Parameters, golem_rig's rule:** value in catalog units, bounded, × `map.scale`; `raw` = port value, `norm` =
  displayed target = raw value for LV2 and Lua DSP; enum → its `values[i]`, else its rank (raw) or normalized rank;
  `pct_db` and `pow` (REAPER / golem-fx curves) refused with the reason. Resolution by label, exact then substring.
- **Watcher (fork overlay):** `rig_recall` (clear, create routes, insert plugins, set files, link ports, apply
  state, write `.livemap.json` with each parameter's control index and plugin range), `scene_apply` (enable, mute,
  parameters, gains — nothing added or removed), `stomp`, `rig_verify` (`.rig-check.json`, REAPER's format, second
  read after 2 s), `dump` (`.engine-dump.json`, real state for benches).
- **Two traps found and fixed:** (1) Ardour's `set_processor_param(proc, n)` and the OSC surface take the **rank of
  the control parameter**, not the port number (NAM's controls are ports 4–6): indexing by port wrote the wrong
  parameter. (2) **A disabled LV2 plugin does not run, so its deferred file load never completes**: a NAM bypassed
  in the first scene never read its model, and the first scene to enable it would have loaded it while playing.
  The watcher now loads every file with plugins enabled, waits until each is read (266 ms for 2 NAM + 1 IR), and
  only then applies the scene — the equivalent of REAPER's union materialization.
- **Designer:** `EngineAdapter.plays(type)`; under the Golem Engine a type absent from its table is `unavailable`,
  reason `engine`, "not available on Golem Engine yet".
- **Volume block:** interim Ardour "ACE Amplifier" (−20…+20 dB): a volume pedal's heel is not silence until the
  golem-fx volume (T2).
- **Proof:** `tools/check-engine-ardour.py` on the real engine (dummy backend), a bench patch (card input 1 → pre →
  lane A NAM + IR / lane B NAM + gate → merge −3 dB with Tape Delay at the foot + volume → out 1-2): rebuild 405 ms,
  REAPER-only gate left out with its reason, 3 files read, links and outputs as planned, scene A then scene B
  **without rebuild** (mutes, enable, NAM input +4 dB), stomp, a knob over OSC through the livemap (0.75 → +10 dB):
  18 checks OK. CI: `tests/test_engine_ardour_plan.py`.

**2026-11-10 — lot A2.1: launch and supervision (CODED, dummy backend).**

- **Launcher:** `provision/lib-engine.sh` — `golem_engine` (the choice through `bridge/engines.py`, or `GOLEM_ENGINE`,
  dev only), `golem_engine_pid` (`presets/.engine.pid`, checked against `/proc`: `luasession`, not a zombie),
  `start_golem_engine` (session, backend and device from `GOLEM_ENGINE_SESSION` / `_BACKEND` / `_DEVICE`, log
  `/tmp/golem-engine.log` or `GOLEM_ENGINE_LOG`), `stop_golem_engine`. `start.sh` starts the chosen engine (REAPER path
  unchanged); `golem stop` stops a running Golem Engine whatever the choice; `golem status` names the engine.
- **"The engine talks to the bridge"** was "an OSC message arrived": REAPER sends all the time, Ardour's surface only on
  a change — the engine fact would have said "not answering" and opened an incident after 45 s on a healthy engine.
  `EngineAdapter.talking()`: `None` for REAPER (OSC traffic, unchanged); the Golem Engine's watcher writes a beat
  (`.engine-status.json` every 2 s) and the monitor sets `reaper_connected` from it. The Health fact names the active
  engine and its version.
- `EngineAdapter.engine_started()`, called once a new engine process's watcher is ready: the Golem Engine re-subscribes
  the bridge to its OSC surface (the surface forgets its clients). REAPER: nothing (no wait).
- **Bug found and fixed:** `recall.rig_is_live` compared the livemap to the start time of the **REAPER** process
  (`monitors.reaper_pid_recent`). Under the Golem Engine, the REAPER next to it (the rack's) made a killed engine's
  livemap look alive: the rig was never remounted, and a scene could have been sent to a dead rig.
  `reaper_pid_recent` now reads the active engine's PID (REAPER: the same `_reaper_pid`, same 1.5 s memo).
- **Bench:** `check-rig-materialize.py --engine golem-engine` — the same worktree, bridge and checks, the Golem Engine
  (dummy backend, throw-away session) instead of REAPER; `--fixture` writes `ci-golem-engine` (NAM head + IR cab of the
  factory content, Tape Delay at the foot, two scenes); service blocks of the config lanes (Rec, Click, Riff,
  Arrangement) not yet on the engine are listed, not a reason to skip; `--kill-restart` kills the engine (SIGKILL),
  restarts it through `POST /api/system/reaper-restart` and checks the bridge saw it, Health said it, and the last
  patch came back. Results: `ci-golem-engine` materialized, scene A→B; killed → seen in 0.8 s → talking again 1.8 s
  after the restart → **remounted in its scene B after 4.1 s** → Health ok. The 38 factory patches: all skipped, each
  with the list of its blocks not yet on the engine — the A3 to-do list. The bridge's own first recall (Chill Jazz)
  mounted 12 routes and 12 blocks in 0.5 s with the rest left out.
- Not proven yet: the incident opening (the bench bridge is younger than the 45 s grace, the fact said `wait`), a cold
  start with sound (needs the real card: Soundcard lot).
- **Same false alarm on REAPER, fixed:** at rest (no signal on the inputs) REAPER sends no OSC, so every bridge reload
  opened "REAPER not answering" although `golem_watch` acknowledged every command (two incidents measured on
  2026-11-10). `ReaperEngine.talking()` says yes when `golem_clock.lua`'s beat (`presets/.clock.json`) is fresh — all
  REAPER loops share one Lua context — and says nothing otherwise (OSC traffic decides, as before): it can only remove
  that false alarm. On the rack after a reload: fact `ok`, the open incident closed by itself.
- The engine session lives in golem: `sets/golem-engine/` (local state, git-ignored), not `~/.local/share` — the
  uninstall receipt test caught a write outside the install.

**2026-11-10 — lot A2.2: Dashboard (CODED, dummy backend).**

- `EngineAdapter.audio()` ({buffer, rate, backend, dsp_load}), `xruns()` (counted by the engine, DSP overloads
  included), `set_buffer(size)`. REAPER keeps every source it had (`reaper.ini`, the real card on Windows/macOS,
  the kernel journal for xruns, a restart to change the buffer): `/api/system` only adds `engine {id, name, version}`.
- Golem Engine: `/api/system` gives `audio_bsize`, `audio_srate`, `audio_dsp_load`, `audio_backend`, its buffer list
  (32…1024) and `audio_live_buffer`; `POST /api/audio-buffer` → `set_buffer`: the choice goes to
  `config/golem-engine.json` (local state, git-ignored) and the watcher applies it **live** — engine stopped and
  restarted, the session stays: **0.4 s from the button to the new buffer, 23–189 ms inside the engine**, no restart
  (REAPER: ~10 s). The watcher re-reads the file at every start (checked: 256 kept across a kill and restart).
- The watcher writes `presets/.clock.json` ({ticks = processed samples, t, on}) every second: the "audio thread
  advancing" witness of `monitors._audio_alive` works unchanged. Engine xruns are added to the kernel's, summed across
  engine restarts (its counter starts again at zero).
- The process tile reads the active engine's PID (`/api/system/health`); the app titles it with the engine's name
  ("Reaper" stays "Reaper") and shows the DSP load when the engine gives it; a live buffer change does not wait for a
  restart that will not come.
- **Proof:** `check-rig-materialize.py --engine golem-engine --fixture --dashboard --kill-restart`: engine named,
  buffer 1024 → 256 in 0.4 s without restart, 48 kHz, DSP 30.6 %, process tile on the engine's PID, xruns 0, audio
  witness ok; then killed and remounted (4.3 s). The Dashboard rendered by a bench bridge on the Golem Engine at
  1024×600 (headless Chrome, every write intercepted): no scroll, no console error, "Golem Engine · … · DSP 11 %",
  256 selected among 32…1024. The rack's Dashboard on REAPER: unchanged (Reaper tile, 192, 8 ms measured).
- "measured live: —" on the dummy backend: no ALSA hardware to read; the real latency comes with the card.

**2026-11-10 — lot A2.3: Soundcard, on the real Volt 276 (CODED; REAPER stopped for the test, no engine output linked
to the card).**

- **The card:** by default the Golem Engine opens golem's ACTIVE card in ALSA — the one REAPER opens
  (`config/cards/<card>.json`, `ardour.card_device()`, also used by `lib-engine.sh`); no known card → the dummy backend.
  The watcher finds it among the ALSA backend's devices by a name contained in the other ("Universal Audio Volt 276" →
  "Volt 276"), then sets device, 48 kHz and the saved buffer before opening the session. (Fixed on the way: the device
  was passed as `set_backend`'s second argument, which is the client name — harmless on the dummy backend, fatal on
  ALSA; `os.exit` does not exist in `luasession`, `quit()` does.)
- **Inputs:** three permanent tracks `golem:in1..3`, each on one physical input, meter at the input, no output — strips
  1–3 of the OSC surface, like REAPER's "Sandbox #Input 1/2/3": their `/strip/meter` becomes `/track/1..3/vu`, so
  golem's input meters (Soundcard, /live, clip chip) work unchanged; lanes start at strip 4. They survive rebuilds.
- `GOLEM_ENGINE_NO_OUTPUT=1`: the watcher links no output to the card (each skipped link is logged) — the bench mode.
- The beat publishes what the engine sees of the card: device, inputs/outputs, MIDI ports.
- **One reader of the buffer:** `routes_system._read_bsize()` asks the active engine when it is not REAPER — the
  Soundcard header, the golem.fm heartbeat (`engine_doc`), Health and diag all read there (the bench showed "192 smp"
  — reaper.ini — for an engine running at 1024).
- **Bench:** `check-rig-materialize.py --engine golem-engine --real-card` (refuses while REAPER or the rack's bridge
  runs; copies the rack's card config into the worktree; engine on the card, no output linked).
- **Measured on the Volt:** ALSA · Volt 276 · 2 in / 2 out · 48 kHz; latency measured by the bridge from ALSA
  `hw_params` **42.7 ms at 1024** (= 2 × 1024 / 48000); the guitar lane listens to `system:capture_2`, the input the
  rack's input map gives the guitar (input 1 = voice); input meters live per physical input (in1 ≈ −95 dB noise floor,
  in2 ≈ −40 dB); MIDI "Volt 276 MIDI 1" in and out; buffer 1024 → 256 live on the card in 0.7 s; killed and restarted
  by the bridge on the card, patch back in its scene after 4.3 s, outputs still unlinked; DSP 34–37 % at 1024
  (two plugin hosts at rest). Gear ▸ Soundcard rendered by the bench bridge at 1024×600: Volt 276, "1024 smp · 42.7 ms",
  Voice on input 1, Guitar on input 2, no scroll, no console error.
- Seen, not engine-related: the bench showed "Generic USB Audio detected (new)" — the worktree has no copy of the rack's
  device registry, where that second USB card is known. And `state.levels.guitar` is a fixed alias of input 1 (old
  compatibility key, REAPER too) while this rack's guitar is on input 2: to look at in the Live/Health pass.
- Not measured yet: sound out (no output was linked), a card swap without reboot, unplugging the card.
- Rack given back: golem desktop restarted, Fuzz Wall scene B recalled (rig-check ok), xruns 0, latency 8 ms.
- Next: Pedalboard (scenes, stomps and EXP through the adapter at the real foot — needs sound out, so with the maintainer), USB
  devices (MPK, Nitro), Health facts engine-neutral, then the A2 gate (`check-ui` with engine = Golem Engine).

**2026-11-10 — lot A2.4: Health, plugin inventory (CODED).** The watcher answers `plugins` (which plugins of the
bridge's table are installed here, `presets/.engine-plugins.json`, asked at every engine start): 8/8 on this machine.
A block whose plugin is missing is `unavailable`, reason `plugin`, as under REAPER. Health: the Plugins fact reads the
engine's inventory ("N of M block plugins found by Golem Engine"), the Scripts fact reads the watcher's failures in
`.watch.log`, "Since last boot" follows the engine's name and version, incident titles say the active engine
("Golem Engine not answering"). Under REAPER every text is unchanged.

**2026-11-10 — safety limiter: `golem Safety`** (`golem/engine/scripts/golem_safety.lua` in the fork overlay, an Ardour
Lua DSP found through `ARDOUR_DATA_PATH`): `golem_safety.jsfx` ported as is — ceiling −1 dBFS, no lookahead (x42-dpl was
not taken: lookahead is the latency golem dropped with ReaLimit on 2026-10-14), linked channels, NaN/inf → silence, no
allocation in the audio thread. Rendered offline: below the ceiling the output equals the input (1.5e-8) with **0
latency**; a +6 dBFS sine comes out at exactly −1 dBFS; no NaN. The watcher puts it last on every route that goes to the
card (main, merge) — after the blocks, so no livemap index moves.

**2026-11-10 — lot E3: switching engines (CODED, proven on the rack).** `bridge/engine/switch.py`: `POST /api/engine`
writes the choice then runs the switch in the background — stopping (old engine stopped, its OSC port freed, its
witnesses `.clock.json` / `.engine-status.json` removed), starting (the new adapter becomes the active one, its feedback
opens, it starts, it adopts the old engine's buffer when it has none of its own), remounting (the monitor sees a new
process and remounts the current patch; the switch waits for the livemap to say it) — or reverting (new one stopped,
old choice written back, old engine restarted) then failed. Refused during a take or while another switch runs;
followed by `GET /api/engine/switch`. `app.reaper` is now a relay to the active engine (`engine.active()`): the looper
and the backing follow a switch. `ReaperLink.stop()` now frees its port. The Golem Engine descriptor is `selectable`,
Linux only, **where it is built** (`platforms.linux.requires`: `golem/engine/run.sh` under `GOLEM_ENGINE_DIR` or
`~/golem-engine`; otherwise "Golem Engine is not built on this machine", in the app and the installer). Engine page: the
first tap arms ("Tap again — sound stops for a few seconds"), then the phases are shown, and a failure says golem went
back. **On the rack** (silent test: `config/golem-engine.json` `"no_output": true`, removed afterwards): REAPER →
Golem Engine in **4.9 s**, Fuzz Wall scene B remounted (4 routes, 6 blocks in 365 ms, gate and phaser left out), 4 files
read, 42.7 ms, 0 xrun, outputs not linked; Golem Engine → REAPER in **6.0 s**, Fuzz Wall B back, rig-check ok, 8 ms.

**2026-11-10 — first test at the rack by the maintainer: sound on the Golem Engine, then silence after a scene change.**
The engine crashed (`luasession` segfault at 14:11:12, faulting address `0x656e656373` = the bytes of "scene") while
applying the first scene; the foot gestures after it queued against a dead engine. Evidence kept. Not reproduced on the
bench (12 scene changes on the real Fuzz Wall plan, with pink noise in, a 192 buffer, OSC feedback, MIDI events).
Rack given back on REAPER through the switch (Ambient Djent A, 8 ms). Three suspects, all addressed:
1. **Hardware MIDI in the engine**: the ALSA backend opened the sequencer ports (the pedalboard port vanished on the
   bridge side for a moment) and the FCB's MIDI reached Ardour's own ports ("Scene in", MMC…). The watcher now sets the
   backend's MIDI to "None" — a third fork patch, `[headless] [upstreamable]`: bind `AudioBackend::
   enumerate_midi_options` / `midi_option` / `set_midi_option` in `luabindings.cc` (the bridge owns every controller).
2. **Lua kept removed routes and plugins alive** (shared_ptr) until a random garbage collection — possibly while the OSC
   surface or the audio thread still saw them. `clear_routes` now drops every reference and collects at once, as Ardour's
   own scripts do.
3. Core dumps are on for the engine (`run.sh`: `ulimit -c unlimited`, apport keeps them) — the next crash has a stack.
And a safety net: a Golem Engine that falls **without an announced stop** is restarted by the monitor one second later,
at most 3 times in 10 minutes, then the patch is remounted (sound back in ~5 s). REAPER: unchanged.

**2026-11-12 — the real cause, read from the core dump.** The engine crashed again at 09:00:51 after a scene change on
Modern Metal (address `0x6e6f6974` = "tion"); the safety net restarted it, then every `scene_apply` failed with
"shared_ptr is nil". The core's stack: `r:mute_control ()` in `apply_state`, called on a route that was already freed.
**`Session:new_audio_track (…):front ()` returns a reference into a temporary list** (LuaBridge binds `T& front ()`):
once the garbage collector freed the list, `RIG.routes` pointed into reused memory — text bytes (crash) or zeros ("nil").
Yesterday's suspect 2 made the collection sooner, not safer. Fix: `first (list)` takes a **copy** through `:iter ()`
(watcher and bench script). Reproduced on the dummy backend (`front` → "shared_ptr is nil" after a collection; copy →
300 calls clean). Rule for the fork's Lua: **never keep the result of `:front ()`**. The MIDI change (suspect 1) stays:
it was right on its own.

**2026-11-12 — A2 closed except the USB drum module; first MIDI lane (A3).** Pedalboard at the foot with sound: OK
(maintainer). `check-ui --base` against the rack on the Golem Engine: 47 pages, 46 OK — the one failure is the local Wi-Fi
hotspot name (`config/network.json`, "GoleM", local state), not the engine. OSC exposure: see §8.
**MIDI lanes** (keys; pads and drums follow the same path):
- Plan (`ardour_plan.py`): a lane with `midi` becomes a track of kind `midi`; its keyboard = the ALSA card short name of
  the compiler's `midi_in` (`hw:II` → "MPK Mini Mk II", `/proc/asound/cards`); its channel = `midi_ch[midi_role]`
  (keys on 1, the MPK's pads on 10 stay out). A keyboard not plugged is said in `skipped`; the track is built, silent.
- Engine: the backend's MIDI is the **ALSA sequencer** (shared — the bridge keeps its ports), with **every device closed
  at start**: by default Ardour opened them all, the card's DIN (the pedalboard, the bridge's) and the bridge's own
  virtual ports included. A lane's keyboard is opened when a rig needs it, hot (`set_midi_device_enabled`, bound in
  the third fork patch), and only it. Measured on the rack: the engine reads the MPK only; the Volt's DIN is not
  connected to it.
- Track: MIDI in, two audio outs (the instrument is stereo: left → output 1, right → output 2; one output gets both),
  input monitoring, capture channel filter; safety limiter last as on every route to the card.
- Block `piano` → sfizz LV2, file property `sfizz:sfzfile`. sfizz never echoes its file back: the table's
  `loaded_output` names the output control that proves the load ("Number of regions" > 0; Salamander: 641 regions in
  0.5 s). Its instrument enum (the `.sfz`) is content resolved by the compiler, no port: refused in the plan.
- **Locale**: lilv translates plugin labels (sfizz under `fr_FR`: "Polyphonie", "Nombre de régions") and golem finds a
  knob by its catalog name → `run.sh` sets `LC_ALL=C.UTF-8`.
- **Drums lanes** (same day, the Alesis Nitro): a `drumkit` block = two engine blocks, the translator **golem
  Drumtrans** (Lua DSP in the fork's `golem/engine/scripts/`, a line-for-line port of `golem_drumtrans.jsfx`: module
  note → kit note, three-position hi-hat from the pedal CC, note-off follows the note sent, output on channel 10; its
  table is in the instance's `shmem`, written by the watcher, nonce last) then the avldrums kit of the block's
  `kit_bank` (Black Pearl, Red Zeppelin, Blonde Bop). The translator never bypasses; the kit follows the scene.
  Tested under lupa (8 cases, identical to the JSFX) and on the dummy engine (avldrums sounds through the translator).
  drumgizmo kits (Aasimonster, the hybrid megakit) are not here yet: Metal mounts with no block.
- **Hot-plugged MIDI devices**: Ardour's ALSA backend opened every sequencer client that appeared after it started —
  golem's pedalboard reader (`aseqdump -p 20:0`) included. A bridge restart made the engine subscribe to it; an engine
  restart dropped the subscription and the bridge saw "the pedalboard port disappeared": **the pedalboard cut on every
  engine start**, seen since 2026-11-10. Closing those devices from the watcher made it worse (a reconnect loop every
  2 s). Fix: **5th fork patch** `[headless] [upstreamable]`, `ARDOUR_ALSA_MIDI_NO_HOTPLUG_OPEN` (set by `run.sh`):
  hot-plugged devices stay closed. Measured: an engine restart, 0 pedalboard cut. A lane keyboard plugged after the
  rebuild opens at the next rebuild (as REAPER's `midi_reinit`).
- Not yet: comp / eq / reverb of the keys and drums lanes (not in the table), a per-scene `.sfz` or kit (files
  and kits are set at the rebuild only), the E-Piano (Dexed), organ (b3), Vital, pads, drumgizmo kits.

**2026-11-12 — A3 guitar, step 1 (T1 blocks mapped and probed).** `tools/check-engine-blocks.py`: every block of the
engine table instantiated on a dummy engine, each catalog parameter resolved by name and written/read back, two
toggles, xruns counted → **32/32 green**. Added: boost (Proteus), grit (Prisma), chorus, flanger, phaser, tremolo,
rotary (Calf), wah, wah-color, autowah, reverb-shimmer, octaver, vibrato, eq-graphic (guitarix), reverb, -plate, -room
(Dragonfly), eq-para, limiter (x42), granular (Zam), ringmod, bitcrusher, rezfilter (MDA).
- **VST3**: Proteus, Prisma, ZamGrains (and Vital, Surge) are VST3 under REAPER; their LV2 builds expose no or other
  controls (JUCE's LV2 wrapper: "Free Wheeling, Enabled" only). Headless Ardour reads only its VST3 cache → `run.sh`
  runs Ardour's `ardour-vst3-scanner` over `~/.vst3`, `/usr/lib/vst3`, `/usr/local/lib/vst3` before each start (33
  bundles: 4 s the first time, 0.7 s cached). The table names a VST3 by its class id (`vst3`).
- `init` (golem_rig's `FX_INIT`) is data: values set once at add (Calf chorus dry at unity).
- `absent`: catalog parameters with no control, refused with the reason — autowah's "Wah" (GxAutoWah has none: the knob
  does nothing under REAPER either, a **catalog bug** to fix on both engines), granular's "Grain Position" (ZamGrains 4),
  the piano's zone / transpose / arp (golem_rig helpers, not here yet).
- Out: Surge XT Effects (spring, freqshift, treemonster) — its VST3 renames controls after the FX type, the catalog's
  "FX Parameter N" names do not resolve. Vital waits for its state loading.
- **Not proven yet**: the sound. Step 1 proves load + mapping; parity (§4: the same DI through REAPER and the engine,
  null ≤ −50 dB for T1) needs `check-engine-parity.py` — next. Until then a T1 block plays on the engine with the same
  binary and the same values, but `norm`-mode parameters are an assumption (displayed = raw for LV2) to be measured.

**2026-11-12 — the parity bench (§4) exists: `tools/check-engine-parity.py`.** First run on 25 T1 blocks
(DI crunch, values at 30 % of each range): **14 ok, 1 inconclusive, 10 to fix**.
- Calibration: without a block the two hosts are bit-identical (null −276 dB) once two host differences are matched —
  Ardour's region fades (64 samples, now off in `golem-place`; that tool also crashed at exit, fixed) and Ardour's
  **2 s export pre-roll** (REAPER given the same pre-roll, so LFOs start in phase).
- Identical to the sample (null < −88 dB): eq-graphic, eq-para, grit (VST3), octaver, wah, wah-color, autowah,
  reverb-plate. Free-phase blocks within level/third-octave limits: granular, reverb-room, reverb-shimmer, ringmod.
  Inconclusive: boost (Proteus leaves the DI untouched without a model — on both).
- **Stereo topology** (delay-tape, rotary; probably chorus, flanger, phaser): every parameter is identical on both sides
  (all ports compared), but REAPER feeds a stereo plugin with the mono DI on **both** inputs and keeps both outputs,
  the engine's mono route feeds the left input only and keeps the left output. A ping-pong delay builds its echoes
  from both inputs (−17 dB on the engine). → the stereo step announced in §7c: lanes processed on two channels as
  REAPER's tracks are, before these blocks can pass.
- **Catalog bug, both engines** — limiter (x42 dpl): the catalog gives Threshold −30…0 dB and Release 1…1000 ms in raw
  mode; the plugin's ports are −10…0 dB and 0.001…1 **s**. REAPER passes the out-of-range values as they are (the 50 ms
  default is sent as 50 s); Ardour clamps them. To fix in the catalog — it changes the sound of the patches that use it.
- Free-phase blocks still above the limits (tremolo 1.1 dB, vibrato, bitcrusher, reverb hall, rezfilter): to look at
  after the stereo step (phase windows of 6 s; rezfilter's values give near-silence).

**2026-11-12 (later) — stereo lanes and the catalog's limiter.**
- **REAPER's behaviour, measured** (parity renders, L and R): a golem track has 2 channels and the mono input is on
  both; a **mono** plugin's output goes to **both** channels (eq-para: L = R, processed); a **stereo** plugin gets the
  DI on both inputs and returns two different channels (chorus).
- **The engine now does the same without doubling the work** — `golem/engine/golem_chain.lua`, shared by the watcher
  and the parity bench (the bench tests the rack's code): a route stays mono while its plugins are (one port to both
  card outputs = REAPER's "mono to both"); at the first stereo plugin (`natural_input_streams` ≥ 2, read from the
  plugin, no table to keep) `Route::customize_plugin_insert` gives it two outputs and its input map takes channel 1
  on both pins (Ardour: "copy the first buffer to the others"); the route gets a second output port, L → out 1,
  R → out 2. A bus takes the channels of its widest source; routes are built **after their sources** (the plan lists
  the merge before its branches; strips follow creation order, carried to the bridge by the livemap); links go
  channel by channel (mono source → both inputs of a stereo bus). A mono plugin after a stereo one is doubled by
  Ardour (dual mono) — REAPER's behaviour for that case is not measured yet. On the rack: Modern Metal's merge is
  stereo, rig-check ok, the pedalboard did not cut.
- **Limiter fixed in the catalog (v34, maintainer's decision)**: Threshold −10…0 dB, Release kept in ms with `scale` 0.001
  for the x42's seconds; the Windows table names both parameters, which drops the scale there (its JSFX takes ms).
  Test: `test_sous_linux_le_limiteur_x42_recoit_des_secondes` (0.08 s for 80 ms). Autowah's "Wah" stays: it drives
  golem_autowah.jsfx on Windows/macOS; it does nothing on Linux only (the engine table says so in `absent`).
- **Free-phase blocks are compared on a stationary signal**: the LFO's phase differs at every engine render (measured:
  the same tremolo shifted by 5 888 then 2 688 samples within its period), and a guitar DI is not stationary (where the
  sweep is when a note hits) → those blocks get a fixed-seed pink noise (−18 dBFS), long-term third-octaves.
- **Parity now: 20 ok, 1 inconclusive (boost: Proteus without a model leaves the DI untouched), 4 open**: vibrato
  (−5 dB at 200 Hz), ringmod, bitcrusher (all parameters identical on both sides — suspected: modulation updated once
  per audio block, and REAPER's render and Ardour's export do not use the same block size; live, both use the card's
  buffer), rezfilter (silent on the engine with these values — to look at).
- Found on the way: `tests/test_portable_jsfx_blocks.py::test_un_rappel_windows…` fails alone and passes in the full
  suite (the bridge's quarantine of delay-echo follows the platform the compile sees) — order-dependent, pre-existing.

**2026-11-12 (evening) — ReaGate and ReaComp measured; clones written, then dropped.** (Superseded the same day by
the maintainer's decision in §3.2: golem-fx effects are new sounds, not clones. The crates `plugins/golem_gate` / `golem_comp`,
their engine-table entries, the bench's T2 criteria and `provision/install-golem-fx.sh` were removed before any
commit; the measured models below stay as reference.)
- **Method — measure the original, then write it**: a lab renders REAPER's plugin in the bench's isolated REAPER on
  signals that expose its mechanism (sine and DC steps, slow level ramps, per-frequency ramps), with every port read
  back; a Python model is fitted sample by sample, then ported to Rust (`plugins/golem_gate`, `plugins/golem_comp`,
  nih-plug, VST3 + CLAP, mono first so a guitar lane stays mono, stereo with linked detection). Each crate has an
  offline renderer (`cargo run --example gate_render|comp_render`) for that comparison.
- **ReaGate as golem leaves it** (RMS size 0, Dry/Noise −150 dB): peak detection sample by sample; opens when |x| >
  threshold, stays open while |x| > threshold + hysteresis; closes Attack + Hold after the last sample above; gain ramps
  **linearly** 0→1 over Attack and 1→0 over Release; sidechain Hipass then Lowpass = RBJ biquads, Q = 1. The model
  matches REAPER at −128 dB on every probe, **bit-exact on a guitar DI** with REAPER's effective values.
- **ReaComp as golem leaves it** (knee 0, no lookahead, Auto Make Up off): RMS over a **rectangular** 5 ms window; a
  level smoothed in amplitude — rising, it starts from the **threshold** and joins the input with time constant Attack;
  falling, it joins the input (even below the threshold) with time constant Release; gain = (level / threshold) ^
  −(1 − 1/ratio), then Wet (the catalog's makeup). Matches REAPER at −99 to −112 dB on twelve probes (ratios 2/4/8,
  two thresholds, two attack/release pairs, peak and RMS). The give-away was the attack: an exponential in neither dB
  nor gain, but exact in gain^−4/3 at ratio 4, i.e. in the detected level.
- **Bench, end to end in Ardour** (`check-engine-parity.py gate comp`, T2 criteria — table key `voiced_on`): gate
  null −55 dB, level 0.00 dB, envelope 1.0 %; comp null −62 dB, level +0.08 dB, envelope 0.9 %. Comp on 3 DIs × 3
  preset settings: level ≤ 0.09 dB, third-octaves ≤ 0.11 dB, envelope ≤ 1.3 %.
- **Found on REAPER's side — golem_rig lands a `norm` knob one display step off.** Its bisection on the *displayed*
  value stops where the display flips, and ReaGate/ReaComp display whole ms: Attack 3 ms → 2.49 ms, Release 150 → 149.5,
  Threshold −62 → −62.4, Makeup 0 → −0.05 dB. That is why T2 is judged on level/bands/envelope, not on the null (the
  Golem Engine gets the exact value). Harmless by ear; it disappears for these blocks when REAPER plays golem-fx too
  (D3 — not done: it is the maintainer's call, it moves REAPER's sound by those fractions).
- **Ardour + nih-plug**: an *active* VST3 gets a value through the next audio cycle's parameter queue; nih-plug ignores
  the controller's `setParamNormalized` while processing. Live (the watcher) that is immediate; the bench's session
  builder now lets the engine run 0.3 s before saving (it saved the defaults: Attack 3 instead of 15).

**2026-11-12 (night) — A3 step 3 for the guitar: every factory guitar patch rendered on both engines.**
- **The bench**: `tools/check-rig-materialize.py --render --di auto [--engine golem-engine --against <REAPER run>]`
  renders every scene of every patch with the DI its genre picks (the per-scene demos' rule, `bridge/preview.py`). On
  the Golem Engine the watcher's new `snapshot` command saves the session as the scene mounted it; the bench copies it,
  `golem-place --disk --to-master` plays the DI from disk into the lane input and routes the lane's outputs to the
  master, Ardour's export renders it. REAPER renders at 48 kHz when a real DI is used. The comparison skips the first
  4 s (the engine pre-rolls 2 s, REAPER's preview starts cold: a NAM warms up, a delay repeats the difference) and
  ignores third-octaves more than 50 dB below the total (24-bit quantisation behind a cab).
  `--engine-blocks-only` reduces the patches on both engines to the blocks the engine plays, until golem-fx delivers.
- **Golem Engine fixed**: scene levels were never applied (only the merge gain). Now, as golem_rig does, the scene
  `level` goes to the fader of the track that reaches the card, the merge gain to the route's trim (before its
  plugins — REAPER puts a Volume Adjustment at the head of the merge).
- **Result** (12 guitar patches, 60 scenes, Gypsy Lead skipped: a cab without capture in the factory content, both
  engines): every scene without a free-phase block nulls at −68 to −107 dB (NAM, cabs, eq-para, octaver, wahs, plate,
  delay-tape at 120 BPM). Free-phase blocks (hall, room, shimmer, rotary, phaser) stay within ~0.3 dB per third-octave
  except the Calf phaser on Fuzz Wall (~4 dB at 80 Hz). Scenes with delay-tape on Singing Clean and Texas Blues
  null at only ~−25 dB — **closed 2026-11-13, not a defect**: the delay-tape alone nulls at −276 dB
  (`check-engine-parity.py delay-tape`), the levels of every scene are within ±0.06 dB except a free-running Leslie
  scene (+1.2 dB), and sameness of sound is no longer a goal (§4).
- **Two REAPER bugs found by the comparison, fixed (maintainer's go)**: (1) autowah's Wah does not exist on GxAutoWah;
  golem_rig fell back to the parameter's numeric rank, landed on the plugin's BYPASS port and switched the effect off
  in every patch that sets Wah (Funk Clean scene B never had its autowah on Linux) — catalog v36
  `index_fallback: false`; (2) a scene without a level kept the previous scene's level (Brown Lead D after C: +3 dB) —
  now 0 dB, plus the merge gain when it had to fall back to the same D_VOL.
- **golem-fx on the engine** (table key `golem_fx`; the parity bench reports their distance to REAPER's original for
  information): gfx-boost (volume, clean-boost: null −149 dB vs the JSFX), gfx-gate (−44 dB vs ReaGate, lane stays
  mono with its Key bus), gfx-comp (level −0.5 dB vs ReaComp after golem-fx recalibrated its detectors from −2.6 dB),
  gfx-limiter (−34 dB vs x42-dpl, release in ms: a parameter renamed by the engine table drops the catalog's scale,
  golem_rig's rule), gfx-eq (−10 dB vs ReaEQ, a steeper low cut: ReaEQ's high pass is 2-pole with a 2-octave
  bandwidth, its high shelf at 5 kHz / 0.8 oct, read and passed to golem-fx). The golem-fx nih-plug fork fixes two things measured here: a value written before the first audio
  cycle was lost (REAPER and Ardour), and read-only meters (gate state, gain reduction) now exist — readable from
  Ardour's Lua and from ReaScript.

**2026-11-12 (late night) — golem-fx: 11 blocks on the engine; a third REAPER bug.**
- Engine table (`golem_fx: true`): volume, clean-boost (gfx-boost), gate, comp, limiter, eq, deesser, wah and wah-color
  (gfx-wah), autowah, chorus — each through `check-engine-blocks` and `check-engine-parity`. wah-color and autowah were
  taken by ear (the maintainer's A/B against GxWahwah / GxAutoWah, level-matched), their numbers having converged to
  −9 / −12 dB on envelope-driven filters where a few ms of follower move a +20 dB peak across third-octaves. Explicit
  label maps where the catalog's REAPER names differ (wah-color's "MODE" matched gfx-wah's "Model" by substring).
  gfx-chorus is 2/2 first (stereo-by-nature effects are, by the golem-fx contract), so the lane turns stereo at it as
  with Calf; `init` pins Level Comp = 0 for Calf's loudness.
- **ReaEQ's high pass was never enabled** (BANDENABLED4 = 0 in a fresh instance): the catalog's eq lowcut cut nothing
  under REAPER (0.0 dB from 20 to 300 Hz, white noise). golem_rig enables it at add (f0da53fe).
- Bench: the parity bench links golem's JSFX into its REAPER (Effects/golem), honours `index_fallback`, and the block
  probe writes 1 to booleans.
- REAPER normalisation of nih-plug VST3 parameters, measured for golem-fx: enums at index/(n−1), snapping to the
  nearest; booleans as toggles (≤ 0.5 off); linear plain ranges exact, negative minimums included.

**2026-11-13 — gfx-pitch harmony follows the song's key (catalog v39).**
- golem-fx phase 2 of gfx-pitch (8a52f9e): `harmony` (Off · Scale), `key` (C…B, flats as gfx-pitch names them), `scale`
  (10, order only grows at the end), appended after the existing parameters, defaults unchanged. With Scale, `shift` /
  `shift2` are nominal intervals landed on the scale above the detected note. The catalog exposes them on the `pitch`
  block with the second voice (`shift2`, `voice2`); the engine table maps them, enums by rank.
- `song_key` (virtual, default on): `compile_rig._expand_pitch_harmony` replaces Key with the song's tonic and Scale
  with Major / Minor — unless the scale picked by hand already belongs to the song's family (Dorian stays Dorian in a
  minor song). The song's key is the preset's `key`, else its Standard block's (its grid's when "Original");
  `scene_bake.to_paths_preset` carries it to the compiler as `key` ("Em"). Off, or no key: Key and Scale stay as set.
- Block presets "Twin lead" (Scale, +4, mix 50) and "Twin lead + fifth" (+ `shift2` +7 at −4 dB).
- The rebuilt plugin, switched on and off by scene on the Golem Engine (`check-scene-gap`, a pitch block in one branch of
  a merge): 0/24 gaps. `check-block-stall` needs REAPER and was not run.
- Open: a setlist line cannot carry a key yet (it carries `bpm`); a scene that overrides `key` writes the key as set,
  not the song's.
- **Watcher bug found on the way: every other rebuild failed** when the new rig reused a route name (editing a patch
  in the Designer does): "Port already exists", the rig left empty. Ardour's OSC surface holds its strips (shared_ptr)
  until its next bank recalculation, so a removed route and its ports outlive `remove_routes`. `clear_routes` now
  renames each route (`golem-gone-N`) before removing it: the port names are free at once. 12/12 rebuilds after the
  fix, against an exact FAIL/ok alternation before (with or without a golem-fx plugin).

**2026-11-13 — one flanger (catalog v40).** golem had two flanger blocks, `flanger` (Calf: rate, depth, linear
feedback) and `flanger-js` (REAPER's JSFX: length, feedback dB, wet, dry, rate); golem-fx played both with one engine
through two VST3s. The maintainer's call: one block. `flanger` is retired from the catalog, the OS overrides
(`golem_flanger.jsfx`, Windows/macOS) and the engine table; `flanger-js` is now named "Flanger" and its feedback goes
up to −1 dB (the engine's ceiling; REAPER's JSFX accepts +6). A document that still carries `flanger` is rewritten
on load (`option_renames.RETIRED`) with gfx-flanger-calf's own translation: length = 0.5 + depth ms, feedback =
|f| in dB, its sign in `fb_polarity` (Normal/Inverted, gfx-flanger's own control), wet −6 dB, dry 0. `fb_polarity`
is `engine_only: "golem"`: the compiler drops it under REAPER, whose JSFX has none (the sign is lost there only). The
four block presets moved to `flanger-js`.
No factory patch used the Calf block. golem-fx retires GoleM FX Flanger Calf.

**2026-11-13 — Dropouts on the Golem Engine: the CPU clock, then two costs.** Modern Metal on the rack: 6 xruns a
minute on the Golem Engine, 0 under REAPER with the same chain and buffer (192). The engine's DSP load read 92–100 %.
Measured, buffer sizes: 192 → 100 % and xruns, 256 → 84 %, 384 → 77 %, no xruns. New watcher command `dspstats`
(Ardour's per-plugin `get_stats`, written to `presets/.engine-dspstats.json`), average per 4 ms cycle: each NAM
620–660 µs (peaks to ~2 ms), the **muted branch's NAM still computed**, `golem Safety` (the Lua DSP output limiter)
**323 µs**, golem-fx reverb 204, delay 131, IR cabs ~90 each, the small golem-fx blocks 20–80. RT scheduling is fine
(FIFO 78–80). The cause that dominates: **the CPU governor was `powersave`, the core at 0.67 GHz** — with
`performance` (the Dashboard's ⚡ CPU boost) the load drops from 80 % to 31 %. REAPER hides it with anticipative FX
processing; Ardour has to finish each 4 ms cycle.
**CODED, OFF by default 2026-11-13 — a muted branch sleeps.** A route mute leaves Ardour computing the branch's
plugins (the muted branch's NAM cost as much as the playing one). With `config/golem-engine.json`
`"sleep_muted_branches": true` (read at every scene), the watcher deactivates a muted branch's plugins AFTER the mute
and the blocks' enable, and reactivates them BEFORE the unmute (`apply_state`, `RIG.asleep`; `dump` reports `asleep`
per route and `active` per block). The engine bench turns it on and checks both directions (scene A: branch B asleep,
even its gate that the scene keeps on; scene B: B awake, A asleep).
**Measured 2026-11-13 — it stays OFF.** `check-scene-gap.py --seq A,B -n 5 --lane 2` on the rack (Golem Engine,
Modern Metal, whose A and B swap the muted branch, screen and foot paths, 20 switches each run): switch **off**, 0 gaps
and 1 dip (−8 dB) in 20; switch **on**, 0 gaps but a dip on almost every wake (9 of 10 switches toward the woken
branch, −7 to −15 dB under the quieter scene). A reactivated NAM restarts cold: the level sags for a moment, which a
player hears. The muted branch keeps being computed; the CPU boost covers its cost. Ways to revisit: wake the branch
one cycle before the unmute, or keep the amp awake and put only the rest to sleep — each to be measured the same way.
The same run showed the CPU boost switching itself on with the Golem Engine and off again back on REAPER.
**CODED 2026-11-13 — the safety limiter is compiled.** The watcher puts golem-fx's `gfx-limiter` last on every route
that goes to the card, set like `golem_safety.jsfx`: no lookahead (latency 0), threshold −1 dBFS, release 15 ms, style
clean, fixed release. The Lua `golem Safety` stays as the fallback when the plugin is missing (logged). Measured on the
engine bench: 0.2–0.45 µs per sample, against 1.7 for the Lua DSP (323 µs per 192-sample cycle on the rack); the bench
checks it (< 1 µs) and that the limiter is the compiled one (`dump` reports `safety: "gfx-limiter" | "lua"`). The
bench's "merge at −3 dB" check reads the route's trim (`dump` `trim_db`), where the merge gain has lived since
2026-11-12.
**CODED 2026-11-13 — the CPU boost follows the engine** (the maintainer's decision): while the Golem Engine runs, the
governor is `performance` whatever the mode; under REAPER, the mode's rule alone (Gig and Show,
docs/modes.md). `routes_system.wants_boost` decides; it is applied at the bridge's start, at every mode switch, and at
every engine switch — before the Golem Engine starts, and again on a switch back (`engine/switch._boost`). Tests never
touch the machine's governor (`conftest._pas_de_boost_cpu_de_la_machine`).

**2026-11-13 — REAPER stall bench on the blocks golem.fm's AI may not propose yet (catalog v41).** The rack was
switched to REAPER for the run, then back. A first run was void: a golem-fx Rust build in parallel (load 10, 152
xruns) made plain JSFX "freeze" up to 500 ms. On a quiet machine, two passes (8 + 18 switch-ons per block):
chorus-js, pitch-shift-js, guitar-drive and capture-module freeze nothing (≤ 4 ms) and lose `bench: pending`.
flanger-js (REAPER's JS flanger) froze once in 26 (521 ms) and stays pending — the maintainer's call: no rerun under
REAPER; the flag is settled when the Golem Engine becomes the default, where gfx-flanger plays it (stall-free); pitch-spectral is not installed on this
machine, not measured. `check-block-stall.py` now warns when the load average is high.

## 7d. Inventory 2026-11-16 — what REAPER gained while the Golem Engine stood still

**Status: MEASURED (inventory), order PROPOSED.** The fork's last commit is 2026-11-13 and the rack has run REAPER
since that evening. Three days of work went into the bridge and the REAPER side. This section lists the gap, read on
the three contact surfaces and measured on the bench; nothing was coded for it.

**Measured** — `check-rig-materialize.py --engine golem-engine --working-tree` (its own engine, dummy backend, the
rack untouched), the 52 factory patches of the working tree:

| | |
|---|---|
| materialized, scene A→B applied | **42**, 0 failed, 191 s |
| skipped: an instrument the engine lacks | 9 keys patches — `vital` (4), `ep` (3), `organ` (1), `pads` (2) |
| skipped: content not on this machine | 1 (Aasimonster kit samples; not an engine gap) |
| settings refused by the engine plan in the 42 | **none** (only `sfz`, resolved by the compiler, and "no MIDI device", the bench has none) |
| services missing in **every** materialized patch | `rec`, `click`, `compo`, `arrangement` (42/42), `drums` (28), `standard` (11) |

So the core kept up: the catalog moved from v44 to v50 and every block of the audio lanes still lands with its
settings, per-scene settings included (`apply_state`). What the engine lacks is what it never had.

**Surface 1 — commands.** The Golem Engine adapter accepts 12 actions (`ArdourEngine.actions`); any other is dropped
with one log line. The bridge sends about 45 kinds. By family:

| Family | Actions REAPER answers | Golem Engine | Phase |
|---|---|---|---|
| Rig | `rig_recall`, `scene_apply`, `stomp`, verify, dump | yes | done |
| Bench and health | `gapmeter`, `dspstats`, `plugins`, `audio_set` | yes | done |
| Output mixer | `mixer_apply` (`bridge/mixer.py`: output trims, XR18) | **no** | A2 leftover |
| Health probes | `peaks` (`check-silence`), `meters`, `midi_reinit`, `audio_reset`, `fxinventory` | **no** | A2 leftover |
| Recording | `perf_rec` (takes, DI tracks, `.perfsrc.json`) | no | A4 |
| Click, MIDI clock | `click` | no | A4 |
| Backing, arrangement | `backing` | no | A4 |
| Drum machine | `drums`, `drumlearn` | no | A4 |
| Standards, Riff | `standard`, chord sequencer | no | A4 |
| Samples, pads | `sample`, `sample_preview` | no | A4 |
| Looper | its own command file and gmem ring | no | A4 |
| Tuner | `tuner` | no | A4 |
| Listening without playing | `preview` — patch, preset lane, keys sound, kit, capture audition, reamp, **CPU calibration bench** | no | A4 |
| VST Host | `vst_list`, `vst_open`, `vst_params`, `vst_state`, `plugin_window` | no | A4 |
| Capture wizard | `capture_params` | no | A4 |

**Surface 2 — the compiled plan** (`<id>.rig.json`, the same file for both engines). Fields `golem_rig.lua` reads and
neither `ardour_plan.py` nor the watcher mentions:

- lanes: `mono_fallback`, `in_sel`, `midi_avoid`, `midi_strict`, `midi_ch.pads`;
- instruments: `vital_chunk`, `vitalium_state`, `dx7_bank`, `dx7_patch`, `kit_pads`, `engines`, `kits` and the
  per-kit fields beyond the AVL translator (`kit_mix`, `kit_bleed`, `drum_lost`, `drum_slot`);
- services carried by the plan: `looper`, `knobs` (EXP and knob tap);
- REAPER-only plumbing, nothing to port: `rfxchain`, `core_types`, `core_ids` (one NAM per amp, 2026-11-15 — the
  Golem Engine already inserts one plugin per block).

Not ported from that commit: **a head without a cab gets its default IR** (`default_ir`). To check on the engine.

**Surface 3 — telemetry.** The watcher writes `.livemap.json`, `.rig-check.json`, `.clock.json`, the ack and its own
`.engine-*.json`. The bridge also reads, from REAPER only: `.rig-plugins.json`, `.knobmap.json`, `.keys-midi.json`,
`.midi.json`, `.peaks.json`, `.fx-inventory.json`, and one state file per service (`.perf.json`, `.perfsrc.json`,
`.backing.json`, `.click.json`, `.drums.json`, `.standard.json`, `.sample.json`, `.looper.json`, `.tuner.json`,
`.preview.json`).

**What the three days added, and where it lands:**

| Added under REAPER (2026-11-13 → 16) | On the Golem Engine |
|---|---|
| Catalog v45–v50: ~20 golem-fx blocks, legacy blocks retired, IR Effect, Formant, Morph | follows — one shared table, bench green |
| One NAM per amp on a lane | not needed; default IR of a cab-less head to check |
| Per-scene settings used by the whole factory | applied |
| Factory: drum machine or Standard on SW10, Rec or Riff on SW9, in every patch | **absent** — every factory patch arrives without them |
| Demos: patch, lane, keys sound, kit, capture audition | absent (`preview`) |
| Drum kits: import, General MIDI safety net | AVL kits only; imported SFZ kits and DrumGizmo to do |
| CPU budget: calibration bench and estimate | calibrated under REAPER only; the engine needs its own profile |
| Bass DIs, factory casting, two branches at most | engine-neutral |

**Proposed order** (everything is to be coded; this is the sequence, each lot with its own short plan and bench):

1. **A2 leftovers**: output mixer, health probes (`peaks`, `meters`, MIDI and audio reset), default IR check.
2. **A3 keys**: `vital`, `ep`, `organ`, `pads` and the keyboard zones — 9 factory patches wait on them. Bass and voice
   lanes already materialize; their gate (levels against REAPER, listening) can run in parallel.
3. **A4 in the order the factory needs it** — this revises D6 ("looper and click first"): recording and click, then
   drum machine and Standard (SW10 of every patch), Riff, backing and arrangement, then `preview` (demos, audition,
   CPU calibration), samples, looper, tuner, VST Host, capture wizard.
4. **A guard so the gap cannot reopen silently**: a test that lists every action the bridge sends and fails on one no
   engine has classified (plays it, or declares it missing with its feature).

**2026-11-16 — lot 1, the A2 leftovers (CODED, proven on the real engine, dummy backend).**
`tools/check-engine-ardour.py` now opens the dummy card that plays a sine on its inputs and passes 47 checks.

- **Output mixer** (`docs/mixer.md`). A route of Ardour has no level per output, so the two stages add up on the fader:
  scene level + mixer trim (attenuation only, −60 dB = silence), and the two mutes combine. The engine plan names the
  mixer source of each route that goes to the card (`mixer: "in<input>"`); the trims of the rig travel with every
  recall and scene (`plan.mixer`, read from `config/mixer.json`) and hot with `mixer_apply`. The dump reports
  `mixer` and `level_db` next to the real fader. The recording mix that follows the main mix comes with recording (A4).
- **Default cab of a head without a cab.** REAPER fuses it into the track's core; the engine inserts one plugin per
  block and never read that core, so such a head played bare. The compiler now says the file in the plan
  (`default_ir` on the amp block, ignored by `golem_rig.lua`), the engine plan inserts a cab right behind the head,
  in the head's state, outside the live map (`shadow`), and a stomp on the head toggles it too.
- **Why no sound** (`bridge/silence.py`). The watcher answers `peaks` in REAPER's row shape with two marks the
  bridge reads instead of track names: `root` (a card input a lane listens to — the `golem:inN` meter tracks) and
  `rig`. The verdict names the engine that plays, drops the "track armed" clue where the engine has no such probe,
  and takes missing files from the rig check instead of `dumpfx`.
- **Reopen the sound card / MIDI devices** (`audio_reset`, `midi_reinit`): the backend stopped and started with the
  session and its links kept; each MIDI lane closes and reopens its keyboard. The pedalboard is read by the bridge
  and is not concerned.

Not done in this lot: the per-block meter probe (`meters`, a dev route) and the wording of Health ▸ Fix, which still
says "REAPER" in its plans.

**2026-11-16 — lot 2, the keys instruments (CODED, each one heard on the real engine, dummy backend).** The bench
(`tools/check-engine-ardour.py`, 73 checks) mounts each instrument on a MIDI lane, writes a note into the track and
reads the peak on its route.

| Block | On the Golem Engine | How its content gets in |
|---|---|---|
| `vital` | Vital VST3 | its state is a **VST3 preset file**: the compiler already splices the `.vital` into a REAPER `vst_chunk`; the adapter keeps the component state and writes `~/.vst3/presets/Vital Audio/Vital/golem-<block>.vstpreset` (`ardour.write_presets`), the watcher loads it (`preset_by_uri` + `load_preset`) — again when a scene changes the sound, no rebuild |
| `organ` | setBfree LV2 (`b_synth`) | it has no control port: the registration is **Control Changes** computed by the table of `b3-ctl.jsfx` (`bridge/engine/keys_midi.py`), written into the plugin (`write_immediate_event`) |
| `ep` | Dexed VST3 | the watcher can write 1024 bytes at most, a 32-voice cartridge is 4104: the **chosen voice** is unpacked from the cartridge and sent as a one-voice SysEx (163 bytes); a scene with another patch sends another voice |
| `pads` | sfizz | the kit becomes a **SFZ file** the adapter writes (`ardour.write_content`): one region per pad, `oneshot` and `gate`; `toggle` does not exist in SFZ, it plays as a one-shot and the plan says so |
| keyboard zone | `golem Zone` (Lua DSP, port of `note-zone.jsfx`) | in front of each instrument: low note, high note, transpose |
| arpeggiator | `golem Arp` (Lua DSP, written for golem) | between the zone and the instrument, **always there**: "Off" passes everything, a scene turns it on without a rebuild (REAPER must insert the stock `midi_arp`, hence rebuild). Same named settings as `ARP_CONFIGS`; its tempo is the song's, set by the watcher |

- **One lane, several instruments** (`ardour_plan.expand_keys`, the rule of `golem_rig.lua`): two instruments, or an
  instrument and pads when the controller separates them by channel, get one MIDI track each — opened on the same
  keyboard, listening to its own channel — and a bus that sums them, carries the lane's audio effects, the scene level
  and the mixer source. REAPER uses a root track that forwards MIDI; here each track opens the keyboard itself.
- A lane with one kind of sound listens to its channel only (keys or pads), as under REAPER.
- Plugins the engine adds for a block (`<id>~zone`, `<id>~arp`, `<id>~ir`) are `shadow`: they stay out of the live map.
  Consequence: zone and arpeggiator settings follow scenes and edits, but have no fast OSC path.
- `pads` no longer depends on the `samples` feature (`config/engines/features.json`): the engine plays it.
- New watcher commands: `midi_send` (messages into a block's plugin or a track's input), `peaks` with `clear` and a
  resettable maximum. The dump reports `preset`, `midi`, `plugin` per block and `midi_mask` per MIDI track.

**Factory bench after this lot** (`check-rig-materialize.py --engine golem-engine --working-tree`): **51 of 52
patches materialize, 0 failed** — the nine keys patches included, no setting refused; the one skipped lacks its
samples on this machine. Every patch still arrives without its services (`rec`, `click`, `compo`, `arrangement`: 51;
`drums`: 34; `standard`: 12) — lot 3.

**OPEN — one freeze in three full runs.** The second full run stopped answering while it materialized Hero Lead (the
24th recall of the run): one real-time thread of the engine at 100 % CPU, the watcher waiting, for ten minutes until
killed. Hero Lead alone three times, the fifteen guitar patches in a row, and a third full run all passed. Not
reproduced, cause unknown (a plugin spinning in its process call is the likely shape); the first run of the day, before
this lot, had passed too. To hunt with a core of the stuck process (`gcore`, ptrace is restricted for `gdb -p`).

The Vital preset file is written in the user's VST3 preset folder, the only place Ardour reads: the factory bench
therefore writes `golem-<block>.vstpreset` there too (removed by hand after these runs) — to isolate.

Not proven by the bench: the channel filter by ear (a note written into a track enters after its filter; the mask is
read instead), and a real keyboard on these lanes. Not ported: the AKAI knob map (`knobs`, `.knobmap.json`), the
DrumGizmo kit, imported SFZ drum kits.

**2026-11-16 — lot 4, the guard (CODED).** `bridge/engine/actions.py` classifies every command the bridge sends, for
the Golem Engine: handled by its watcher, waiting for a feature of `config/engines/features.json`, or not applicable
with its reason. `tests/test_engine_actions.py` scans the bridge for `{"action": "<name>"}` and fails on a command
that is not classified, on a classification that no longer matches `ArdourEngine.actions`, and on a feature declared
"yes" whose command is not handled. Adding a command on the REAPER side now forces the question.

**2026-11-17 — lot 3, first service: recording (CODED, proven on the real engine with the dummy card that plays a
sine).** `perf_rec` is handled by the watcher; the descriptor declares `recording: yes`, so the Rec block is offered.

- **How.** An Ardour track records its input. Each take track is connected to the **output ports** of the routes
  that go to the card — after the plugins, the scene level and the mixer trim: `Mix` (all of them, stereo),
  `Input-N` (the lane of input N, modes `tracks` and `tracks_di`), `DI-Sandbox-Input-N` (the raw card input, mono,
  `tracks_di`). Names are the ones REAPER writes; what is taken comes from `presets/.perfsrc.json`, frozen at the
  start. `in_ms` delays the start (count-in), a stop during it cancels.
- **Files.** Ardour writes one mono file per channel. At the stop the watcher lists what it wrote
  (`presets/.engine-take.json`) and launches `bridge/engine/take_finalize.py` **outside itself** (assembling an
  hour of rehearsal must not freeze scenes): left + right joined into one stereo WAV with ffmpeg, files moved to
  `recordings/perf-<date>/` (or the flat `perf-<date>.wav` in mix mode), then `presets/.perf.json` says the take is
  finished — until then it is reported as recording. An error is written there, never swallowed.
- **A recall during a take.** Ardour does not let routes be rebuilt while it records: a keyed gate's sidechain is
  refused, and the bench crashed once (core: `IO::connection_change` called from the audio thread on a route being
  destroyed). So the take **pauses** — record off, transport still rolling — the rig is rebuilt, the take resumes; its
  tracks then hold several segments, which the assembler puts back at their positions (the hole is the moment the rig
  was not sounding anyway). Each segment is trimmed to its region: the engine's file holds more (one second of DI was
  doubled at the resume before that).
- **Routes are disconnected before they are removed**, and the engine is given 120 ms to drain its connection queue
  (`clear_routes`) — the fix for the crash above, for every rebuild, take or not.
- Take tracks precede the routes of a rig rebuilt during the take on the OSC surface: strip numbers account for
  them (`ssid_of`), and the live map is rewritten when they leave.
- Bench (`check-engine-ardour.py`, `rec_bench`): a multitrack take with a recall in the middle, a mix-only take, an
  unchecked input, a muted mixer strip (the mix follows the mixer, the DI stays raw at −18.0 dBFS), OSC knobs after
  the take.

Not in this lot: the **MIDI capture** of keys and drums lanes (`MIDI-….mid`), the service tracks in a take (backing,
drum machine, standard: they do not exist on this engine yet), `with_backing`, the BWF timestamp, the recording mix
following the mixer per source in `tracks` mode.

**Limit found on the way — the peak probe.** `peaks` reads Ardour's route meters. Their resettable maximum can keep
a transient from before the reset. The bench therefore judges takes against recorded files, never against the meter.
The silence hunt uses the same probe, with a −60 dBFS threshold: its "signal leaves the engine" verdict needs a check
at the rack before it is trusted on this engine. 
**CLOSED 2026-11-17 — "the same rig does not come out at the same level from one recall to the next".** Recorded files
showed 5 to 30 dB between two takes in a row. Hunted on recorded files, stage by stage; two causes, neither in the
engine's gain:

1. **The bench's test tone was random.** The bench asked for the dummy device "Sine Wave 1K"; the watcher's device
   matching took the first partial match, "Sine Wave", whose frequency is drawn at random at every backend start
   (20 Hz to 9.6 kHz). An amp and a cab do not weigh every frequency the same: the level changed with each engine run
   and each "reopen the sound card". The bench now names "Sine Wave 1K, 1/3 Oct" exactly (397 Hz on input 1).
2. **A ghost echo at every recall — a real defect, fixed.** While a rig was being built, its card input was already
   connected: for a moment the signal crossed the rig with every branch open and every block on, before the scene
   state was applied, and a delay kept it. Measured: −46 dBFS of echo on a bus whose two branches are muted, with a
   bypassed delay (its trails). The watcher now connects the card input (and the keyboard of a MIDI lane) **last, once
   the scene is applied** (`materialize`, `inputs`). After the fix: −91 dBFS on that bus, and the bench rig at
   −28.6 dBFS over 19 recalls in a row — stopped, with the transport rolling, during mix and multitrack takes.

What looked like a muted branch leaking, or a bus reading a stale buffer, was that echo. `rec_bench` now holds a firm
check: two takes in a row within 1 dB.

**2026-11-17 — lot 3, second service: the click (CODED, proven on the real engine).** `click` is handled; the
descriptor declares `click: yes`.

- A **permanent route** `golem:click`, created when the engine starts and never removed by a recall, with one
  processor: `golem Click` (Lua DSP, `golem/engine/scripts/golem_click.lua`), a port of the counter and the sound of
  `golem_click.jsfx` — a fractional sample accumulator that runs with the transport stopped, the bar as
  numerator / denominator / subdivisions, accents by beat groups (bit mask), the silent clock, the four levels.
- Its output goes to the pair or channel the command names (`"1-2"`, `"3-4"`, `"3"`), relinked only when it changes.
  A field missing from a command keeps its value. The tempo is the song's: the watcher pushes it when it sets the
  session tempo. State in `presets/.click.json`, with the audio thread's witnesses (steps emitted, tempo seen), read
  from the processor's shared memory.
- The click route takes the strip after the input meters on the OSC surface (`SERVICE_ROUTES`); it is not a source of
  a take, so the metronome never ends up in a recording.
- Bench (`click_bench`): route present at start, 7/8 in 3+2+2 taken, steps counted at the engine's tempo with the
  transport stopped, sound on its route, silent clock, off.

Not in this lot: the click **played** by a standard's grid or by a song's beat map (`song`, notes 76–78), the section
anchor and the transport resync (`sync`, `anchor`: stored, not used) — they come with standards and backing — and the
MIDI clock out.

**2026-11-17 — the fader was in front of the plugins (a defect of the engine since A2, FIXED).** The watcher added
plugins with `add_processor_by_index (proc, -1)`, which Ardour understands as "at the end" — **after the fader**. The
scene level and the mixer trim, both set on the fader, therefore acted before the amp: they changed its drive, not the
volume, and the fader of an instrument track acted on nothing. Measured on a pushed NAM (input +12 dB): a scene level of
+6 dB came out at −1.0 dB, −12 dB at −1.1 dB. Plugins are now inserted **before the fader** (`golem_chain.lua`,
`fader_index` / `pre`: the visible index of the fader, as `Route::before_processor_for_index` counts); only the safety
limiter stays behind it. After the fix: +6.0 and −12.0 dB. A firm check sits in `rec_bench`. Consequence to hear at
the rack: on the Golem Engine, scenes with a level and mixer trims now sound like REAPER's; they did not before.

**2026-11-17 — lot 3, third service: the drum machine (CODED, proven on the real engine).** `drums` is handled; the
descriptor declares `drum_machine: yes`, so the Drums block is offered.

- A **permanent MIDI track** `golem:drums` (created at start after the click; strips: input meters, click, drums, then
  the rig): `golem Drumseq` (Lua DSP, a port of `golem_drumseq.jsfx`: a tick playhead that runs with the transport
  stopped, variation at the next bar, a fill once then back, the song sequence in loop or once) then the kit's plugin.
- Under REAPER `golem_drums.lua` parses the grooves' `.mid` and the kit descriptor itself; here the watcher reads
  nothing: the adapter completes each `play` (`ardour.drums_play`, `bridge/engine/drum_bank.py`) with the bank
  **already unfolded** into events (same rules: 960 ticks, note-ons only, bar from the first time signature, length
  rounded up to the bar, a silent slot for an unreadable file, the GM note map for a non-GM kit) and the kit's plugin.
  The watcher writes the bank into the sequencer's shared memory, then the command, the nonce last.
- **Kits**: AVL kits by their LV2; SFZ kits and sample kits (`rs5k`, a bare list of samples) through sfizz — for
  sample kits golem writes the SFZ. **DrumGizmo kits (Aasimonster) do not play yet**: the plan says so and the
  sequencer still runs.
- The kit plugin is rebuilt only when the kit changes. State in `presets/.drums.json` (`playing`, `idx`, `mode`,
  `step`), twice a second.
- **Mixer and takes.** The `drums` and `click` strips of the mixer act on the faders of their routes (`SERVICE_MIX`).
  A take hears the drum machine in its mix and gives it its own track (`Drums.wav`); the click never enters a take.
- Bench (`drums_bench`): a factory groove in an AVL kit with the transport stopped, the variation at the bar, the fill
  and its return, stop, a sample kit playing a one-step song once, a DrumGizmo kit reported, the drum track in a take
  with the click sounding beside it, the mixer strip lowering it by 12 dB.

Not in this lot: the per-microphone mix of a multi-mic kit (`mix`, `master`), the learning of an e-drum module
(`drumlearn`), the arrangement driving the grooves section by section (it reuses `play` and `variation`, not tried).

**2026-11-17 — lot 3, fourth service: standards (CODED, proven on the real engine).** `standard` is handled; the
descriptor declares `standards: yes`, so the Standard block is offered.

- The bridge still renders the chart (`bridge/standards.py` → `presets/.standard.seq`); the engine only plays it.
- **One clock.** Under REAPER one sequencer instance per part reads the same shared bank. Here a single
  `golem Chordseq` (Lua DSP, port of `golem_chordseq.jsfx`) sits on `golem:std` and emits **every part on its own
  channel**; its MIDI output feeds one permanent track per part, each listening to its channel: `golem:std:keys`
  (1, sfizz and the Salamander piano), `:bass` (2, ACE Reasonable Synth — REAPER uses ReaSynth), `:drums` (10, the AVL
  kit of the command), `:guitar` (4, sfizz and the pompe). The parts cannot drift.
- Instruments are inserted at the first chart that asks for them (the piano loads a gigabyte) and stay. A part the
  chart does not ask for is muted **and its instrument sleeps**. End of chart or stop: every sounding note is
  released at its place in the cycle.
- **The click is played by the chart** (lane 3 → channel 16 → `golem Click` in `Grid` mode, its own counter silent),
  as under REAPER: two free clocks at the same tempo are never in phase. Chart stopped or finished, the click takes
  its counter back.
- The files of the piano and the pompe are named by the bridge in the command (`ardour.standard_instruments`).
  Mixer strips `std-keys`, `std-bass`, `std-drums`, `std-guitar`; in a take, each playing part has its track
  (`Standard-Keys.wav`…) and enters the mix. State in `presets/.standard.json`.
- Strips on the OSC surface: input meters, click, drums, the five standard routes, then the rig.
- Bench (`standard_bench`): a two-bar chart with the four parts and a click lane — each part heard on its track, the
  click played by the chart, a part not asked for silent, stop without a hanging note, the click back on its counter,
  the end of a chart without loop.

Not in this lot: the **armed start** with a take's transport (`arm`: the chart starts at once, and says so), the tempo
held for a standard take, the keys' arpeggiator (`arp`), the balance of the synth bass against the piano (−10 dB on
its fader, −4 dB with the pompe alone: REAPER's ReaSynth values, **to be set by ear** on this synth).

**2026-11-17 — service blocks and hardware MIDI blocks are playable on the engine (CODED).** A service block (Rec,
Click, Drum machine, Standard) has no plugin in `effects-golem-engine.json`; `ArdourEngine.plays` answered "not here"
for it even with its feature declared, so the Designer and the factory bench still listed it as missing. It now
answers by the **feature** (`config/engines/features.json` + the descriptor's capability). A block the **bridge**
plays itself — the Whammy DT, a MIDI pedal (`engine: midi` in the catalog) — plays on every engine and is no longer
reported by the engine plan.

**2026-11-17 — lot 3, fifth service: the tuner (CODED, proven on the real engine).** `tuner` and `extstate`
(`tuner_in`) are handled.

- `golem Tuner` (Lua DSP, `golem/engine/scripts/golem_tuner.lua`) is a port of golem's detector — same thresholds,
  same state machine: 15 Hz high-pass and 1600 Hz low-pass, YIN on the signal decimated to ~8 kHz and spread over
  several cycles under an iteration budget, the descent to the dip, parabolic interpolation, full-rate refinement for
  high strings, no note under −62 dBFS. The audio passes untouched.
- One instance sits **asleep** on each input meter track (`golem:in1…3`), inserted once at start: arming the tuner
  wakes the one of the input the bridge names and never rebuilds the graph while someone plays.
- Reading in `presets/.tuner.json` (`note`, `octave`, `cents`, `freq`, `conf`), ten times a second at most, the
  note ↔ silence flip at once.
- Outside the engine (lupa): B0 of a five-string bass to E5 within 0.05 Hz, silence reported. On the engine
  (`tuner_bench`): the dummy card's 396.85 Hz read as G4 +21 cents, the input changed on the fly, off.

Limit: three input meter tracks exist, so the tuner listens to inputs 1 to 3.

**2026-11-17 — lot 3, sixth service: backing tracks (CODED, proven on the real engine) — with a sixth fork patch.**
`backing` is handled; the descriptor declares `backing: yes`. The Arrangement block, which the bridge leads with the
click, the drum machine and the backing, is offered too (`plays`: a `virtual` block with no feature of its own).

- **Fork patch 6 `[headless] [upstreamable]`** (the maintainer allowed source changes on 2026-11-17). Ardour's Lua has
  no way to put a file on a track: the GUI does it through `Editor::do_embed`. Added `ARDOUR.LuaAPI.place_audio_file
  (Session, track, path, position)` — an external source (the file stays where it is), one region of the whole file,
  no fades, wrapped in the auditioner's on-the-fly resampler when its rate differs — and the binding of
  `Session:set_auto_loop_location` (a fresh session has no loop range). The fork is rebuilt (`python3 ./waf build`,
  73 s); binaries of before are kept in the scratchpad of this session only.
- A permanent bus `golem:backing` to outputs 1/2 and one track per stem (the six of golem.fm at start, any other on
  demand — an original has one stem per instrument). Strips on the OSC surface are no longer assumed: the watcher
  **counts** what precedes the rig at each rebuild (`RIG.base`).
- **Stems are decoded once by the bridge** (`ardour.backing_load`): Ardour reads a placed mp3 but *seeking* in it costs
  a decode from the start — the transport started at the third try, a seek or a loop dragged. Each stem becomes a WAV at
  the engine's rate in `assets/.cache/backing-wav/<key>/` (decodes in parallel: 2.4 s for six stems of 4 minutes the
  first time, nothing after), and the cache keeps the last four songs (~280 MB a song).
- Ops as under REAPER: `load` (default mix, then the command's), `unload`, `seek`, `loop` A/B (Ardour's loop range,
  loop-is-mode so that arming it stopped does not roll), `jump` (the rehearsal's section jump: backwards, a loop lifted
  at the first wrap; forwards, a seek on reaching the boundary), `mix` per stem, `mute` of the bus. End of song: stop,
  back to zero, counted (`ends`). State in `presets/.backing.json`.
- **Transport.** "stop" then "start" from the bridge: Ardour refuses a locate while it is stopping, so the rewind is
  sent 0.4 s after a stop; "start" is `/locate 0`, not `/goto_start` (the session's range start, which a take made in
  the middle of a song had moved to 101 s).
- **Takes.** A take and the backing share the transport. A take started while the backing plays grafts onto it
  without rewinding; a loaded backing the take did not ask for, and that was not playing, is muted for the take and
  restored after; the backing has its track in a multitrack take (`Backing-Track.wav`) and enters the mix. Mixer strip
  `backing`.
- Bench (`backing_bench`, 13 checks): a six-stem song loaded, played, seek, loop A/B held and lifted, a backward and a
  forward jump, per-stem mix, a take over a playing backing, stop and rewind, end of song, unload.

Not in this lot: the **song's click** (the beat map `ticks` of a backing played by the click: the click runs free),
and the arrangement tried end to end on this engine — its pieces are there, the whole was not played.

**2026-11-17 — lot 3, seventh service: listening without playing (CODED, proven on the real engine).** `preview` is
handled; the descriptor declares `previews: yes`.

- REAPER clones the lane and renders it **offline**. An offline render in Ardour freewheels the engine: the whole
  rack would go silent. Here the render is done **in real time, in the lane itself**, for the length of the phrase:
  a DI is played by a track (`golem:preview:di`, placed with `place_audio_file`) **in place of the card input** — the
  lane and the keys of its gates listen to it; a MIDI phrase is played by `golem Midiplay` (a new Lua DSP, sample
  accurate, one shot) inserted at the head of each MIDI track of the lane, on that track's channel. The lane's output
  is **disconnected from the card** — the room hears nothing — and recorded; the mixer trim is lifted for the render.
- The machinery is the take's (transport, stop, assembler): the assembler writes the WAV where the bridge asked and
  says so in `presets/.preview.json`. Then everything is put back: card input, outputs, gate keys, mixer trim, and the
  render's tracks and players are removed.
- A kind of render that is not there yet answers at once with an error (`bench`, block renders with a drum machine or
  a standard playing, per-track renders), so the bridge does not wait for a timeout.
- Cost: real time. A scene takes its phrase plus its tail (about 15 s), where REAPER's offline render is faster than
  the music. The musician's lane is busy meanwhile — the bridge already takes the rig for a batch.
- Bench (`preview_bench`): a 220 Hz DI rendered through the bench lane (not the card's 397 Hz), the lane back on the
  card afterwards, an unsupported render reported at once, a MIDI phrase played by the organ, the player gone.

Not in this lot: the CPU calibration bench (`bench: N` — the estimate stays calibrated under REAPER), the demo of a
block (drum machine, standard), the kit demos, the audition of a capture and the reamp of a take, which use other
forms of the command.

**2026-11-17 — lot 3, eighth service: samples (CODED, proven on the real engine).** `sample` and `sample_preview` are
handled; the descriptor declares `samples: yes`.

- A permanent MIDI track `golem:sample` with sfizz, on outputs 1/2. REAPER builds one sampler per sound; here the
  watcher writes **one SFZ file** — one region per sound, each on its own note, a block after the other — rewritten
  only when a block's list changes. Launching = a note-on written into sfizz; `stop`, or another sound of the same
  block, releases it. The adapter gives the files as absolute paths and their **durations** (`audio_seconds`): they
  tell the watcher when a sound has ended (`presets/.sample.json`, same shape as under REAPER). `in_ms` delays a start
  (a song aligns a cue on its beat).
- `sample_preview` (the Library's audition) is a block of its own that never shows in the state.
- A launched sample has its track in a take (`Sample`), its strip in the mixer (`sample`) and its row in the silence
  hunt.
- **Level.** sfizz plays a file 4.1 dB under its level (measured in a take, mono and stereo alike: 3 dB of centre pan
  law plus 1.1 dB); the kit compensates, so a sample comes out at the level of its file (bench: within 1 dB — the bench retriggers the sound during the take, and the overlap of the two moves the peak by up to 0.9 dB).
  The pads and drum kits that also go through sfizz are **not** compensated: their level is set by their blocks.
- **Fork patch 7 — live notes survive the transport.** Starting a take cut a sample that was ringing: Ardour sends
  all-notes-off on every MIDI track and resolves plugin MIDI on a transport stop or locate — right for a timeline, wrong
  for instruments played live. `ARDOUR_MIDI_KEEP_NOTES_ON_TRANSPORT` (set by `run.sh`) skips both
  (`midi_track.cc`, `plugin.cc`). It also protects a held organ chord when a take or a backing track starts or stops.
- Bench (`sample_bench`): play, stop before the end, a short sound ending by itself, a delayed start, the level in a
  take, a sound that survives the start of a take, the Library audition.

**2026-11-17 — lot 3, ninth service: the looper (CODED, proven on the real engine).** The descriptor declares
`looper: yes`; the bridge side (`bridge/looper.py`, the foot, /live) is unchanged.

- **`golem Looper`** (`golem/engine/scripts/golem_looper.lua` in the fork) is a new Lua DSP, 8 inputs (4 stereo pairs),
  stereo output. It takes the **contract** of `golem_super8`, not its code: the same command notes written into a
  parameter `GoleM Cmd` (`seq×128 + note`), the same parameter order (`GoleM Tempo`, `GoleM Mode`, `GoleM Loop 1-4 dB`,
  `GoleM Loops level`), so `LooperControl` drives it as it drives the JSFX — count-in bar, first loop snapped to the
  bar, Rec → Dub, per-loop level. Its state is in the plugin's shared memory.
- The audio lives in the same shared memory (8 channels × 120 s, 184 MB at 48 kHz, never cleared in one go): each pair
  knows the **region** it has written and plays only that; the rest of a partial loop is zeroed in small pieces. The
  recording fades in over one block and out over 30 ms — the tail of a first loop falls onto its head (a crossfade at
  the seam). A first loop closes by itself at the end of the memory.
- **`golem:looper`** is a permanent bus created at engine start: loops survive recalls. The engine plan carries the
  loop table (`ardour_plan.looper_loops`: one row = one pair = the lane **input** it listens to, resolved as REAPER
  does); the watcher connects the lane's **output** (post-fader) to the pair's inputs after each rebuild, mutes the bus
  when the preset has no looper, and says "boucle MUETTE" when a row's lane is not in the preset.
- **Commands.** The watcher publishes the address in `presets/.looper.json` (strip, plugin 0, parameter 0) after every
  recall, with the state (`len`, `pos`, `firstrec`, `countin`, `slots`), four times a second while a loop runs. The
  adapter knows the looper's parameter ranges at that address (`ArdourEngine.LOOPER_RANGES`), so the bridge's OSC
  writes reach it; the file fallback `presets/.looper-cmd.json` (`seq`, `notes`, `cfg`) is honoured too.
- The looper has its strip in the mixer (`looper`), its track in a take (`Looper`) and its row in the silence hunt,
  only while the preset has one.
- Differences from REAPER, assumed: the loop records the lane **after the mixer trim** (here the trim is on the lane's
  fader); a command lands at the start of an audio block (≤ 5 ms at 256 samples), the count-in and the snapping are
  exact to the sample in length; no undo, as under REAPER.
- Bench (`looper_bench`): address published, rec → play over OSC, a second loop of the same lane, per-loop level,
  survival across a recall, the file fallback, play all, clear all, count-in then a loop of exactly 2.000 s at
  120 BPM. Tests: `tests/test_engine_lua_dsp.py` runs the DSP on a fake host.

**2026-11-17 — lot 3, tenth service: the VST Host (CODED, proven on the real engine).** `vst_list`, `vst_params` and
`vst_state` are handled; `vst_open` is not (a headless engine has no plugin window).

- **Inventory.** `vst_list` lists the VST3 plugins Ardour knows, named **as REAPER names them** (`VST3: Name (Vendor)`,
  `VST3i:` for an instrument): the Designer's page and the catalogue matching work unchanged, and a patch made under
  REAPER finds its plugin here by name. The engine hosts VST3 only: a CLAP block is skipped with its reason.
- **The block.** `ardour_plan.plan_host` plans a `vst-host` block outside the engine table: the plugin by its name
  (the watcher resolves the class id), the **knobs** the musician chose (`{i, name}`, value normalized under `p<i>`),
  found by their name first, by their rank otherwise. The livemap carries them, so the screen and the EXP pedal drive
  them like a catalogue knob. `vst_params` reads the real parameters of the instance (normalized, with toggle/step).
- **Not there, and said:** the plugin's **native state** — `vst_state` answers that it cannot be captured, and a state
  captured under REAPER (`_vst_chunk`) is not loaded: the plan lists it as skipped and the plugin starts from its
  default state. Parameter ranks may differ between the two engines for a plugin that hides parameters: the name is
  tried first for that reason.
- **First-use bench (CODED 2026-11-17, proven).** `bridge/plugin_trial.py` tried an unknown plugin in a separate
  REAPER; its verdict says nothing about Ardour. On the Golem Engine the same bench runs on a **second Golem Engine**
  (`trial_engine`): a throwaway root, the dummy backend, no OSC surface (`GOLEM_ENGINE_NO_OSC`), no output — the
  engine that plays is not touched. Its watcher (`plugin_trial` action) puts the plugin on a track, switches it off and
  on four times, and measures at each gesture the time the audio clock **lost** (wall time minus processed samples).
  Verdicts: more than 50 ms lost → "stopped the audio engine for N ms"; the process dead → "crashed the audio engine";
  the trace stuck → "froze the audio engine"; plugin not found → no verdict. About 9 s per plugin. **One verdict per
  engine** in `config/vst-trials.json` (key `golem-engine|<plugin>`): a plugin cleared under REAPER is tried again here.
  Proof: `golem Stall`, a test Lua DSP of the fork that blocks the audio thread on purpose, is refused (299 ms
  measured); golem FX Delay and Vital pass (≤ 10 ms).
- Bench (`host_bench`): the inventory, a golem-fx plugin hosted by name, its knob in the livemap, its value read back,
  driven over OSC, the state and a missing block answered honestly; `trial_bench`: the stalling plugin refused, a
  healthy one cleared, a missing one not judged.

**2026-11-17 — lot 3, eleventh service: the Riff block, audio lanes (CODED, proven on the real engine).** The descriptor
declares `riff: yes`. The Riff has no command of its own: it is a take (`perf_rec`) armed by the bridge, with its click
— a file — and its optional bed loaded in the backing (`backing load` with `files`), started together from zero.

- Nothing had to be added to the watcher: the take already names its files as REAPER does (`Input-N.wav`,
  `DI-Sandbox-Input-N.wav`, `Backing-Track.wav`), honours `backing: true` and starts the transport at 0.
- Bench (`riff_bench`): an armed take has the files the Riff uploads, and the "1" of the click falls in the recording
  where it is in its file (1.000 s, within 5 ms) — the property golem.fm relies on to lay the take on the riff.
- **MIDI in a take (CODED 2026-11-17, proven).** A MIDI lane's keyboard is recorded by a MIDI take track opened on
  the same device (one per lane input, all channels, before the zone, the arpeggiator and the instrument); the
  assembler turns the engine's file (musical time at the session tempo) into `MIDI-Input-N.mid`, one format-0 file
  aligned on the take, tempo first — as `golem_perfrec` does. A keyboard that played no note leaves no file.
  Bench (`miditake_bench`): the dummy card's MIDI generator feeds an organ lane (`midi_in: "port:<engine port>"`, a
  bench form); the take holds the notes and the lane's sound, and each rise of the sound follows its note by less
  than 80 ms (measured: about 30 ms — the instrument's attack and one audio period; not corrected).
  **Not verified:** with a real keyboard on ALSA, and a riff uploaded and transcribed from that file.

**2026-11-17 — capture modules (CODED, proven on the real engine with a capture of this rack).** `capture_params` is
handled. The reader of a controllable capture is a CLAP plugin; Ardour does not host CLAP. `native/capture-lv2` builds
the **same reader** (same `engine.cpp`, same pinned NAM core) as an LV2 — `https://golem.fm/lv2/capture`, mono, 32
normalized controls, the capture given as a file property. The engine table maps `capture-module` to it;
`ardour_plan.plan_capture` gives the controls their values in the capture's order, `write_captures` decodes the
compiler's state file into the JSON the LV2 reads, and the watcher writes `capture_params` on `Control NN`.
Bench (`capture_bench`, skipped with a line when the machine has no `.gcap`): the reader placed with the capture's
values, the model loaded (325 ms) and **sounding**, a knob moved while playing. Not compared sample for sample with
the CLAP reader under REAPER.

**2026-11-17 — end to end through a real bridge (`tools/check-rig-materialize.py --engine golem-engine`).** Until now
each service was proven against the engine alone. Three rounds now go through a throwaway bridge, by the real path:

- **A whole song** (`--arrangement`, new): ▶ Play on the factory song *Golem Rising* — the bridge recalls its preset,
  counts one bar in, and its conductor (`bridge/arrangement.py`) lays the scene, the forced blocks and the groove of
  each part at its boundary; then Stop. Measured: part 2 arrives **+6 to +12 ms** from its boundary on the Golem Engine
  (+17 ms under REAPER, same round), the rig is on the part's scene, the drum machine plays the part's groove and
  stops with the song.
  - It found a **bridge bug on both engines**: ▶ Play on a song whose preset was not the loaded one answered
    "no arrangement in this preset" — the recall of the preset erased the song the route had just set
    (`recall.do_recall`). Fixed: a Songs-page song set for the preset being recalled stays.
- **A riff with its bed** (`--compo-bed`, now allowed on this engine): armed takes with the click file and the bed in
  the backing — the bed's first sample and the take's downbeat are **0 samples** apart in `Mix.wav`, at −6, −60 and
  0 dB; a bed with a wrong hash refuses the take; a take without a bed is silent after the count-in.
- **A standard take** (`--standard-take`, now allowed): the **armed start of a standard** is coded. `standard play`
  with `arm: true` sets the take's tempo and arms `golem Chordseq`; the grid leaves **with the transport**. What the
  engine reads from the timeline (the riff's click file) comes out ahead by the output latency so that it lands
  right; notes generated live would come out late by as much (measured: 280 samples). The armed grid therefore runs
  ahead by `Session:worst_output_latency()` and starts **inside the transport's latency preroll** — fork patch 8 binds
  `Session:remaining_latency_preroll`. Measured against the riff's click: **0.5 ms** (24 samples; budget 1 ms), tick 0
  sounds, and a looped grid resumes after its count-in. The preset's tempo comes back at `standard stop`.

- **Demos** (`--demos`, new): `POST /api/preview/batch` on a guitar patch (reference DI), a keys patch and a drums
  patch (MIDI phrases) — the bridge lays each scene, the engine renders it in real time (about 28 s per scene), the
  files arrive: 5, 4 and 4 demos, none silent (peaks −11 to −1 dB). Not compared by ear with REAPER's demos.

The factory pass on the current tree: 51 patches materialized, 0 failed, 1 skipped (the Aasimonster samples).

**2026-11-17 (afternoon) — the remaining list, closed.**

- **Capture reader, bundled.** `native/capture-lv2/bin` holds the compiled LV2 with its hashes; golem's setup installs
  it with the CLAP reader, only where the Golem Engine is present (`provision/capture_player.py`).
- **The other forms of `preview`.**
  - *Block and kit demos* (`chains`, `midis`): phrases played in the **live service tracks** (`Drums`,
    `Standard Keys`…) by `golem Midiplay`, their outputs taken off the card and recorded; `drums op load` puts a kit
    without playing. Engine bench: a drum phrase rendered through its kit. Through the bridge
    (`check-rig-materialize --listen-forms`): the block demos of a factory preset rendered by `POST /api/preview/blocks`.
  - *CPU calibration bench* (`bench: N`): REAPER renders offline and times it; this engine plays the DI in real time
    and **reads what each plugin of the lane cost per buffer** (Ardour's own counters): `avg_us`, `worst_us`, `nfx`,
    buffer and rate come back in `.preview.json`, and `bridge/cpu_bench.py` takes them as they are. The bench is no
    longer REAPER-only: its targets are the types of the engine table whose plugin is installed, and a target's
    fingerprint carries the engine's version. Through the bridge: `POST /api/cpu/calibrate` measured the empty lane
    (77 µs per 1024-sample buffer on this laptop, on the dummy backend).
  - *Audition of a capture* and *reamp of a take* use the DI form already proven; the descriptor declares
    `reamp: yes`. **Not run end to end** (a reamp needs a golem.fm job).
- **A whole song, complete** (`--arrangement`, second round): a backing (stems of a song of this golem), a sample cue
  at bar 2 and "Record with the song". The backing plays with the song, the cue fires, the take runs and holds
  `Backing-Track.wav` and `Sample.wav`. The samples track is now always recorded and kept only if a sample rang
  during the take (a cue can fire the first sound of a block in the middle of a take).
- **VST Host: the plugin's native state.** `vst_state` makes the engine save the state as a VST3 preset; the bridge
  reads it and stores it **in REAPER's `vst_chunk` layout** (component size, 1, state; controller size, 0, state —
  checked on the 118 Vital states the compiler grafts), so a patch carries its plugin state from one engine to the
  other. At recall `write_host_states` writes it back as a preset of the plugin (`golem-<block>`), found through the
  inventory the watcher now publishes at start (`ident`, `vendor`, `pname`). Bench: Vital hosted with a factory
  sound — what is read back from the engine is that sound, not the default. A state that is not a VST3 state is
  refused, never guessed.
- **Plugin windows: not possible, and said.** The engine has no display; the button answers "The Golem Engine has no
  plugin windows — set the plugin with its knobs, or open it under REAPER".

**2026-11-17 — on the real card (Universal Audio Volt 276, ALSA, MPK Mini plugged; the Nitro was not).**
`check-rig-materialize --engine golem-engine --real-card` — the rack stopped, **no engine output linked** (no sound):

- The engine opens the card: 2 in / 2 out, 48 kHz, the rack's buffer (192 samples, 8.0 ms), its threads in real-time
  priority. The lane of the instrument mapped on the card (bass, input 2) listens to `capture_2`; the round now follows
  the card's input map instead of assuming a guitar. The factory pass on the real card: 36 patches, the guitar ones
  skipped (no guitar in this card's map today).
- **The keyboard**: the MPK Mini is opened by the engine for a keys lane (the bench needs the rack's
  `config/devices.json`, which says which keyboard plays the Keys lanes).
- **A take of the real inputs**: the files arrive at 48 kHz; the DI carries the preamp's noise floor (−69 dB), not
  digital zero.
- **Dropouts (xruns) at 192 samples.** At rest: **0** in a minute, with or without a rig. Around a take: **5** —
  creating then removing the take's tracks rebuilt the engine's graph while the rig played. **Fixed**: the take tracks
  are now **permanent** (17, created once at engine start: mix, three lanes and their DIs, the services, a MIDI
  track, the demo track); a take only connects and arms them, then empties their playlists. Measured again, twice:
  **0** around a take, 0 at rest. A track the pool does not have is still created on demand. (A pooled track must
  never be renamed: renamed at take start, it gave no region once a recall passed during the take.)
- The idle looper cost 42 µs per cycle for nothing; at rest it now only writes silence.
- The buffer changes hot (1024 → 256, 0.6 s); the engine killed and restarted remounts its patch in 4.3–4.8 s. One
  run showed Health in "warn" right after the remount (the OSC link not yet heard), the next "ok".
- **At the switch from REAPER** (done from the app on the rack, 15:11): the engine failed twice with "Failed to open
  audio device" — REAPER had not released the card yet — and started at the third launch; Health kept a watcher-error
  warning. The watcher now retries opening the card for 12 s (**not verified on a real switch**).

- **A bench next to a rack that runs the Golem Engine.** The OSC surface took the next free port (3820) silently
  while the bench's adapter kept sending to 3819 — **the rack's engine**: a bench run started and stopped the rack's
  transport and wrote a plugin parameter to a strip the rack did not have (no backing was loaded, nothing was
  recording). Fixed: fork patch 9, `ARDOUR_OSC_PORT` (no fallback when set), passed by `run.sh` from
  `GOLEM_ENGINE_OSC`; both benches now take a free port of their own. Checked next to the live rack: the bench passes,
  the rack's transport and dropout counter do not move.

- **The rack itself on the Golem Engine** (switched from the app, real card, outputs linked), after the musician played:
  - *The switch.* REAPER → Golem Engine → REAPER → Golem Engine through `POST /api/engine`: each switch ends "done" and
    the patch is remounted. The engine opened the card at the first try on the second switch (the retry for a card
    still held was not exercised). Health says "started but not answering" for a few seconds after a start, then ok.
  - *Dropouts counted for what they are.* The engine makes about 37 xruns while it starts and a few each time a rig is
    laid — the sound is cut then anyway — and Health showed "Audio dropouts: 37" in red after every start. The watcher
    now publishes only the dropouts of **playing**: those of the start and of a rebuild (and 0.7 s after) are left out
    (`xruns` in the status; `xruns_all` keeps the engine's raw count). Measured on the rack: 0 published after a
    restart, 0 in a minute at rest with the outputs linked.
  - *A reamp* (`tools/check-reamp-align.py`, the real path of the job without golem.fm): the render had the DI's rate
    and length, and its three impulses fall **22 samples (0.46 ms)** from the DI's, constant — budget 1 ms. It first
    failed: the bridge reads a render with Python's `wave`, which does not read the float WAV the engine writes; a
    render is now written as 24-bit PCM (a take keeps the engine's format).
  - *CPU calibration, whole* (`POST /api/cpu/calibrate` on the rack, 25 minutes): **72 of 73 targets measured** at
    192 samples — the empty lane 21 µs per buffer, the costliest a NAM WaveNet capture at 792 µs, fuzz 602 µs, of a
    4000 µs budget. It first measured nothing: the bench lane was a guitar lane and the card carries voice and bass
    today; it now takes the input of whichever instrument the card has. Not measured: `volume` — at its default the
    block puts no plugin in the lane on this engine, so there is nothing to time.
  - *A restart that left the engine without its service tracks* (16:00 and 20:33). No input meters, click, drum
    machine, looper nor take tracks: eight errors in a row at start. **Cause found at the second occurrence**: stopped
    cleanly, the engine saves its session — its service and take tracks with it; at the next start their ports
    already exist ("Port already exists") and none can be created. The watcher now **removes every route a reloaded
    session holds** before creating its own (`purge_routes`): three restarts of the rack's engine in a row, 38 stale
    routes removed each time, every service created. (A first guess — the audio backend not running yet — was wrong;
    the wait for `AudioEngine:running()` stays as a guard.)
  - *The engine fell at a rig recall* (four times on the rack this day: 19:06, 20:10 twice, 20:31; the bridge
    relaunched it each time). The log names it: a golem-fx plugin (Rust, nih-plug) panics "already mutably
    borrowed" in `VST3PI::activate` — on a latency change Ardour re-activates the component from the butler thread
    while the audio thread is inside `process()`. Fork patch 10: that re-activation takes the plugin's process lock
    (`connect_and_run` try-locks and skips the cycle). Since the rebuild: 13 recalls of the heavy patch, no fall.
    A race: **not proven gone**.
  - *MIDI clock out* (asked by the maintainer the same evening; it was the last feature marked "planned"). A
    permanent MIDI track `golem:clock` with the script `golem Clock`: 0xF8 at 24 per quarter note at the preset's
    tempo, **transport stopped**, as `golem_clock.lua` does under REAPER. It is linked to the **output of each
    keyboard a MIDI lane opened** (REAPER looks for "MPK"/"akai" by name; here any keyboard), re-linked when the
    list changes (checked every 2 s). No Start/Stop: a free-running clock. Bench: counted at the engine's tempo with
    the transport stopped. On the rack: linked to the MPK Mini's output at the recall of a keys patch, 242 ticks in
    6 s at 100 BPM, and the kernel counted 201 bytes sent to the keyboard in 5 s (`/proc/asound/card4/midi0`).
    **Not checked by ear**: nobody played an arpeggio against it. First version forgot that a recall removes every
    route it does not know — the track vanished at the first recall; it is now in the list `clear_routes` keeps.
  - *The processor's power mode* decides whether a heavy patch drops out: see [`cpu-budget.md`](cpu-budget.md) §4 bis
    (performance mode now follows golem, under both engines).
  - *The estimate against the engine.* The bench first published a block's single worst cycle as its "worst" cost (a
    gate: 19 µs on average, 152 at worst) and the estimate adds the worsts: Eight-String Nu read 132 % while the
    engine held. The bench now cuts the render in **three passes** and gives their median and the slowest, as
    REAPER's three renders do. Recalibrated in performance mode (72 of 73): the estimate reads **15 % (scene A) and
    16 % (D)**; the lane's plugins really cost **14 % and 23 %** (their own counters, live). The engine's own load
    figure is higher — 40 % and 51 % — because it counts the whole cycle (graph, threads, 35 routes), about 26
    points more than the plugins. **Open**: the estimate does not count that fixed share, nor the amp of a muted
    branch, which this engine keeps running.
  - *CPU profile.* One profile **per engine** now (`config/cpu-profile-ardour.json`; REAPER keeps
    `config/cpu-profile.json`): a single file made every switch re-measure everything.

Not judged here: the sound itself compared with REAPER, the foot controller, a keyboard actually played into a take.

**What is left.**

| What | Why |
|---|---|
| Real hardware, by ear and by hand | The card, the keyboard's opening, a take and the dropouts are measured (above). Not judged: the sound compared with REAPER, the foot controller, a played keyboard in a take, the Nitro. |
| A capture audition, and a reamp **job** from golem.fm | The reamp render is proven on the rack (aligned, 0.46 ms); the audition uses the same form; neither the job's download/upload nor an audition was played. |
| The LV2 reader for another architecture | Bundled for Linux x64 only. |
| DrumGizmo kits, the song click (beat map), `drumlearn` | Unchanged since their lots. |
| One full bench run in four failed from a keys recall on | Cause not captured; not reproduced since. |

## 8. Risks

- **Scene latency.** REAPER's scene switch is tuned (union materialization, ≤ 40 ms). Ardour's bypass may
  change latency compensation and cause a gap → use the plugin's own bypass port, measured in A0.
- **Plugin stalls on activation** differ per host; the quarantine list may change — it is data, per engine.
- **Telemetry parity.** The app reads REAPER-shaped files; the surface writes the same schemas, so the app
  does not change. A schema drift would show in `check-ui`.
- **T2 voicing effort.** Matching ReaComp/ReaEQ curves is real DSP work; the bench tells when to stop.
- **Upstream churn.** Mitigated by the patch budget and the weekly rebase job.
- **Endurance.** No public data on 24 h runs; a 24 h soak at the end of A2 and of A3.
- **OSC exposure.** Ardour's surface binds `0.0.0.0:3819`, unauthenticated (§7b), like REAPER's port 8000.
  2026-11-12: binding to loopback is **not possible** with the system liblo (0.31 has no unicast bind address —
  tested: `lo_server_new_from_url("osc.udp://127.0.0.1:…")` fails, the iface variant still binds 0.0.0.0); it would
  mean rewriting the surface's socket. What was done: the surface no longer **advertises** the port over avahi
  (4th fork patch, `[headless] [upstreamable]`, `ARDOUR_OSC_NO_ZEROCONF` set by `run.sh`); the port itself is closed
  by golem's firewall on a rack (`provision/harden.sh`: deny incoming, only SSH / 8770 / 80 / mDNS open). A desktop
  install without `harden.sh` stays exposed on the LAN, as with REAPER. Revisit if a newer liblo can bind a single unicast address.
