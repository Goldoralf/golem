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
