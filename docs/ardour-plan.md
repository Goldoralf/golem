# Ardour engine — action plan

> **Status: FIXED** (plan validated 2026-11-10, decisions in §6) — A0 measured (§7), A1 in progress (§7b). The principle and
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
- Our work = `golem/9.9`: tag `9.9` + overlay commit + patch commits. A release of our engine is a tag
  `golem-9.9-g1`, `-g2`… — the exact sources of each shipped binary (GPL obligation).
- **Update** to an upstream release: `git rebase --onto 9.10 9.9 golem/9.9` → `golem/9.10`, review with
  `git range-diff`, rebuild, run the full bench (§4). The previous branch stays: rollback = previous binary.
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

- **Gate per instrument**: every offered block green on the bench or hidden with a reason; every factory
  lane of that role within thresholds; for T2 blocks, your A/B listening says yes.

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

**2026-11-10 — fork published.** `github.com/Goldoralf/golem-engine` (public), default branch `golem/9.9`
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
  except the Calf phaser on Fuzz Wall (~4 dB at 80 Hz). **Open**: scenes with delay-tape on Singing Clean and Texas
  Blues null at only ~−25 dB.
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
processing; Ardour has to finish each 4 ms cycle. Open: run the CPU boost while the Golem Engine plays; replace the
Lua limiter with a compiled one; stop computing a muted branch (needs the scene-gap bench before it ships).

**2026-11-13 — REAPER stall bench on the blocks golem.fm's AI may not propose yet (catalog v41).** The rack was
switched to REAPER for the run, then back. A first run was void: a golem-fx Rust build in parallel (load 10, 152
xruns) made plain JSFX "freeze" up to 500 ms. On a quiet machine, two passes (8 + 18 switch-ons per block):
chorus-js, pitch-shift-js, guitar-drive and capture-module freeze nothing (≤ 4 ms) and lose `bench: pending`.
flanger-js (REAPER's JS flanger) froze once in 26 (521 ms) and stays pending — the maintainer's call: no rerun under
REAPER; the flag is settled when the Golem Engine becomes the default, where gfx-flanger plays it (stall-free); pitch-spectral is not installed on this
machine, not measured. `check-block-stall.py` now warns when the load average is high.

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
