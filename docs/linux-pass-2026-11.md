# Linux pass after the Windows port (November 2026)

**Status: PROPOSED** — a checklist for the next session on the Linux rack. Written 2026-11-20 on Windows, at the end of
the Golem Engine's Windows port ([ardour-plan.md](ardour-plan.md) §7e). Nothing below has run on Linux yet.

The Windows port changed code that Linux runs too: the fork's C++ patches, the watcher (`golem_watch.lua`), the
adapter bench, the drum machine. Every change was measured on Windows only. This pass rebuilds Linux, runs the benches
there, and publishes the Linux package with the same fixes.

Rules as always: nobody playing; the benches use their own engine and ports, never the rack's; commit only when Raph
asks. Read [CLAUDE.md](../CLAUDE.md) and this file first.

## 1. Rebuild the fork on Linux

`git pull` both repos (golem, golem-engine), then build the engine the Linux way (`./waf configure … && ./waf build`,
the CI recipe is `.github/workflows/golem-engine.yml` of Goldoralf/golem-binaries). What changed in C++ since the last
Linux build (`golem-engine-9.9-g3`) — each one must still compile and behave on Linux:

| Change (fork) | What to check on Linux |
|---|---|
| `IO` unsubscribes from its ports first in `~IO`, under `PortManager::connect_callback_lock` (`[fix]`, b90d2ddff) | No deadlock at a rig rebuild or when a take removes its tracks: the full bench, several runs (§2). The ALSA backend delivers connection callbacks the same way as Dummy and PortAudio |
| OSC observers are `sigc::trackable` with real invalidators (`[fix]`, 5a4aff4d1) | OSC feedback (meters, faders, strips) still arrives after recalls; no crash at recall |
| `LuaAPI.release_sources`, `LuaAPI.replace_file` (lua_api patch) | Takes leave no doubled files (`release_sources`); status files never missing (`replace_file` is `rename(2)` on Linux) |
| `vst3_plugin.cc`: try/catch around the DPF MIDI CC regex — **MinGW only** (`#if defined(PLATFORM_WINDOWS) && defined(COMPILER_MINGW)`) | Nothing to do: Linux uses `std::regex` |
| `portaudio/wscript`: `pa_asio.h` looked for with PortAudio's include path | Linux does not build PortAudio (`--with-backends=alsa,dummy`): configure must still pass |

## 2. Run the benches on Linux

1. `tools/check-engine-ardour.py --engine-dir ~/golem-engine` — the full adapter bench, **at least 5 runs**. Expected:
   no failure except plugins not installed on the rack. It now stops at once when the engine crashes ("le moteur est
   resté vivant") and keeps its work folder (`--keep`): read `engine.log` there.
   New or changed checks since g3: the fill that leads to a variation (`drums`), the sample level on the typical peak
   (`sample`), the level across a recall on the typical peak (`rec`), the capture reader must be placed for "the model
   sounds" (`capture`), `--only keys` runs alone.
2. `tools/check-engine-ardour.py --device "<the rack's card>" --only start` — the engine on the **real ALSA card**
   (new option): start, transport, 0 xrun.
3. The rest of the Golem Engine probes, never run since the port: `tools/check-rig-materialize.py --engine
   golem-engine` (and `--kill-restart`), `tools/check-engine-blocks.py`; System ▸ CPU cores (a Windows path was added
   to `bridge/cpu_cores.py`).
4. `pytest tests` — these fail on Windows because they are Linux-only; they must pass on Linux:
   `test_a2_desktop.py` (4), `test_desktop_midi.py::test_prises_usb_hors_din_et_ports_logiciels`,
   `test_engine_ardour.py::test_le_pid_est_celui_du_process_moteur`, `test_engine_ardour_plan.py` (the 5 "banc du
   golem engine" cases), `test_engine_drum_bank.py` (2), `test_engines.py::test_sans_golem_engine_construit_reaper_seul_selectionnable[linux]`,
   `test_golem_engine_install.py` (3). A failure there that is not Linux-specific is a regression of the port.

## 3. Things changed on Windows that Linux runs as is

- **Drum machine** (`bridge/drums.py`, `reaper/Scripts/golem_drums.lua`, `reaper/Effects/golem_drumseq.jsfx`, the
  engine's `scripts/golem_drumseq.lua`): holding the switch 0.6–1.5 s plays the block's fill, then the next variation
  (`then_idx`, gmem cell 6). **Never run in a real REAPER**: on the rack, start a groove with fills, hold the switch
  mid-bar — `presets/.drums.json` must show `mode: fill` at the next bar, then `groove` with the next `idx`.
- **Empty MIDI files** swept at engine start (`golem/engine/run.py` `sweep_empty_midi`): after a few takes and an
  engine restart, `sets/golem-engine/interchange/*/midifiles` holds no 26-byte files.
- **sfizz guard**: without Shinyguitar the gypsy guitar is not placed (no `[sfizz] Loading failed` in the log).
- **Card banner** (`bridge/monitors.py`): the Linux branch is unchanged, but check System ▸ Gear ▸ Soundcard still
  shows the card with the Golem Engine.

## 4. Publish the Linux package with these fixes

Windows is on `golem-engine-9.9-g4` (release of Goldoralf/golem-binaries, Windows asset only, pinned in
`provision/windows/pins.json`). Linux is still on `golem-engine-9.9-g3` (`VERSION` in `provision/golem_engine.py`,
`provision/downloads.sha256`).

- The CI workflow `golem-engine.yml` **creates** the release (`gh release create`): it fails on `golem-engine-9.9-g4`,
  which exists. Either change its publish step to upload into an existing release (`gh release upload`, keep the
  Windows asset), or tag a new `golem-engine-9.9-g5` and publish both systems there (rebuild the Windows package from
  the same tag with `golem/tools/bundle.py` on Windows). Ask Raph which.
- Release tags of the engine must be **lightweight** (the workflow says why: `git describe`).
- Then pin Linux: `VERSION` in `provision/golem_engine.py` and the line in `provision/downloads.sha256` (sha256
  recomputed on the downloaded asset and compared with the release's `SHA256SUMS`).

## 5. Not for this pass

- `grit` (Prisma) has no Windows build: Raph asks golem-fx for a VST3; nothing to do in golem or the fork.
- The DSP load at buffer 128 on Windows (crackles; 256 is fine): a Windows question, measured with the engine's
  `dspstats`.
- macOS.

## 6. Review of both engines (2026-11-20) — what Linux must also look at

Written after a read of the code, docs and tests (two independent reviews, spot-checked). Statuses as of that day.

### REAPER after the golem-fx change

- 54 of 60 effect block types play golem-fx on all three OS once installed (33 replace an open-source plugin, 21 are
  golem-fx-only); 11 types retired in catalogue v48; 6 not wired yet (grit, cab, ir-fx, bitcrusher, surge-freqshift,
  stretch). All 54 are `status: testing`, none `validated`.
- The resolution logic (plugin choice, fallback when golem-fx is missing, value normalisation, retired-type rewrite) is
  tested — against the fake REAPER only (`tests/test_rig_lua.py`). **No automated test loads a real golem-fx VST3 in a
  real REAPER**, on any OS. The only real-REAPER guard, `tools/check-block-stall.py`, is run by hand on Linux; 12 types
  are still to rerun there (De-esser, Detune, Drive, EQ, Killswitch, Pitch Classic, Pitch, Reverb, Rotary, Shimmer,
  Tremolo, Vibrato) — it proves "no freeze", not "right sound".
- Risks: factory presets and demos may sound different from the replaced plugins (nothing measures it); the parameter
  manifest `library/catalog/golem-fx-plugins.json` was generated from golem-fx 048142e while the installers ship 0.6
  (e7e9ecc); `gfx_range` falls back to a case-insensitive substring match in `pairs()` order (undefined); on Linux with
  glibc < 2.34 REAPER keeps the old plugins while the bridge believes golem-fx is installed; the CPU budget
  (`docs/cpu-budget.md`) was never calibrated on a rack.
- The only golden render (`tests/golden/renders.json`, `patch:ci-engine`, 2026-10-19, Windows) predates golem-fx, and the
  fixture of `check-rig-materialize.py` still uses the retired `chorus-js`.

### Golem Engine

- Good unit coverage on golem's side (adapter, plan, switch, Lua DSP — about 130 tests) and three benches (adapter: 162
  checks; blocks; parity with REAPER). **All engine benches are manual**: no CI runs them; `test_engine_lua_dsp.py`
  skips in CI (no fork checkout).
- **The watcher `golem_watch.lua` (3,700 lines) has no unit test** — REAPER's `golem_rig.lua` has a fake REAPER under
  lupa; the engine has no fake Ardour for its Lua. Every crash found that week was found by the bench, never by a fast
  test.
- Not covered: real cards (ASIO/ALSA, by hand only), endurance (the planned 24 h soak has no tool), latency
  measurement, regression tests of the fork's C++ patches, switch failure paths (old engine that does not come back,
  remount timeout), Lua DSP `golem_safety` (the safety limiter on every output route), `golem_clock`,
  `golem_drumtrans`, `golem_stall`.
- Security: the engine's OSC surface listens on every interface (port 3819), without authentication.

### Tests to add, most important first

1. A real golem-fx in a real REAPER in CI (Windows first, then Linux): install golem-fx 0.6, mount a patch with several,
   check the scanned names, every parameter resolving, no freeze.
2. The parameter manifest against the shipped plugins, exact name match for every parameter of the 54 types.
3. Golden renders with golem-fx: a fixture without retired types, one reference per family (drive, modulation, delay,
   reverb).
4. Unit tests of `golem_watch.lua` with a fake Ardour under lupa (rig mounting, scenes, takes, source release).
5. The engine's adapter bench in CI, on the dummy card, against the published package (Linux at least).
6. Level of the old plugin vs golem-fx for the 33 replaced blocks on the factory presets (> 1 dB flagged).
7. Scene changes without gap or click on golem-fx blocks under REAPER.
8. Failure paths of the engine switch.
9. Lua DSP: `golem_safety` first, then `golem_clock`, `golem_drumtrans`, `golem_stall`.
10. Endurance: 24 h of simulated playing.
11. glibc < 2.34: the bridge and REAPER agree on what is installed.

### Improvements, most important first (§7 below says what was done on Windows the same day)

1. The engine's OSC surface listens on 127.0.0.1 only.
2. Regenerate the golem-fx manifest from 0.6; exact parameter names only, a visible error otherwise.
3. Validate the 54 golem-fx types family by family (stall bench on Windows and macOS, listening, level vs the old plugin).
4. The Linux pass of the Golem Engine (this file, §1–4).
5. Calibrate the CPU budget on a rack, for both engines (the engine's fixed share, about 26 points, is not counted).
6. Repair the golden renders (fixture without retired types, new reference).
7. Golem Engine: create the 17 take tracks only while recording (back to buffer 128 on Windows?).
8. Refresh stale docs (`golem-fx-reaper.md` and `golem_rig.lua` comments say golem-fx 0.4; `test_engines.py` says "Linux
   only").
9. Remove dead code (the Ratatouille path in `golem_rig.lua`).
10. golem-fx finishes from the docs: momentary footswitch for Ducker/Swell, values written from context, reference presets
    beyond the Chorus.

## 7. What was done on Windows the same day (2026-11-20)

The improvements of §6 that Windows could take, in the same order. Each with what Linux still owes.

1. **OSC on the loopback only — DONE.** liblo cannot bind a unicast server to 127.0.0.1 (`lo_server_config.ip` left
   it on 0.0.0.0, measured), so the fork registers a first handler that drops every message whose sender is not
   local (`libs/surfaces/osc/osc.cc` `golem_local_only`, on when `ARDOUR_OSC_LOCAL` is set — `run.py` sets it).
   Measured: `/transport_play` from the LAN address ignored, from 127.0.0.1 obeyed; the adapter bench's rig and
   looper sections pass. The port still *answers* the LAN at the socket level (nothing is executed). **Linux:** rebuild
   the fork, rerun the adapter bench, send one message from another machine.
2. **golem-fx manifest — DONE.** Regenerated from golem-fx 0.6 (e7e9ecc): identical content to 048142e, only the
   commit changed. `gfx_range` in `golem_rig.lua` matches names exactly and logs a missing one;
   `tests/test_golem_fx_manifest_names.py` checks the 1,434 names golem looks up. **Linux:** nothing (pure data).
3. **Stall bench on all golem-fx under REAPER for Windows — DONE.** The 49 plugins the catalogue uses, 8 switch-ons
   each on a live patch: no freeze, worst 6 ms (`docs/golem-fx-reaper.md` §3). The first run hid a frozen measurement
   (every plugin after the 22nd read exactly 0 ms, reported "no freeze"); `check-block-stall.py` now says "measurement
   frozen — not measured" on eight exact zeros, and the 27 were rerun in two batches. **Linux:** rerun the twelve of
   §6 (or all 49, in batches of ~14). Listening and the level against the old plugins are still to do, on any OS.
4. **The Linux pass** — this file, §1–4: Linux only.
5. **CPU budget calibrated — DONE by itself.** The rack ran the bench while idle, for both engines (`docs/cpu-budget.md`
   header: REAPER 73 entries at 128, the Golem Engine 71 + `engine_idle` 12.7 % at 256, about 35 min each, no failure).
   On the Golem Engine the profile's sample rate was `None` (read from REAPER's telemetry): `cpu_bench._srate()` now
   asks the active engine first, with a test — that profile re-measures once. **Linux:** let it run once on the rack
   and compare the estimate with the engine's figure per scene.
6. **Golden renders — DONE.** The fixture's chorus is the `chorus` type (the retired `chorus-js` is gone), and the
   references are per condition: `patch:ci-engine@golem-fx` when golem-fx is installed (made on Windows, rerendered:
   A and B match), the plain one removed (it described the old fixture). **Linux:** `--fixture --render` there —
   compare to the Windows reference first (same plugins, a different OS); if it differs beyond tolerance, the
   references need an OS key too. A machine without golem-fx says "no golden" until someone makes that variant.
7. **Take tracks only while recording — MEASURED, NOT CHANGED.** The engine on the dummy card at 128, at rest, two
   times two rounds: with the 17 pool tracks (35 routes) 33, 56, 41, 53 % against 29, 30, 40, 45 % without (18
   routes). The pool may cost a few points, but the run-to-run noise (±15 points) is larger than the gap, and the
   pool exists because creating tracks at take start cost 5 dropouts on the real card (2026-11-17). Nothing changed.
   **Linux:** measure on the real card with ALSA (the dummy's DSP figure is not the card's), with `perf` if needed,
   before trading the pool away.
8. **Stale docs — DONE.** golem-fx 0.4 → 0.6 in `golem-fx-reaper.md`, `platforms.md`, `golem_rig.lua`, `rig.py`,
   `provision/desktop.py`; the `test_engines.py` docstring (the engine is choosable on Windows too).
9. **Dead code — DONE.** The Ratatouille path of `golem_rig.lua` (`rata_block`, `chunk_replace_ratatouille`, its branches
   in `load_block_file` and `try_named_file`). `test_rig_lua.py`: the same 6 failures as before the change (they
   predate it).
10. **golem-fx finishes — NOT DONE.** A momentary footswitch for Ducker and Swell is a foot-controller and UI decision;
    `bass-di` `low_note` and `fuzz` `pickup` following the lane need a place for the lane's tuning and instrument that
    does not exist yet; reference presets beyond the Chorus are golem-fx's work. To decide with the maintainer.

