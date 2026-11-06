# Plugins

> **Status: CODED** — which plugins the blocks use on each OS, how they are installed (packages,
> pinned releases, plugins compiled from source with our patches), and how a block finds its plugin.

Related: [blocks-doctrine.md](blocks-doctrine.md) (catalogue, quarantine) ·
[block-status.md](block-status.md) (plugin absent on this machine) ·
[desktop-windows-macos.md](platforms.md) · [integration-macos.md](platforms.md) ·
[installer.md](installer.md) · [plugin-recipes.md](plugin-recipes.md) · [plugin-window.md](plugin-window.md).

---

## 1. How a block finds its plugin

- A block type declares its plugin in `library/catalog/effects.json` (`plugin`, `engine`).
  `golem_rig.lua` tries, in order, `plugin`, then the names in `ADD_ALIAS` (in `golem_rig.lua`), then
  the type itself; `bridge/blockstatus.candidates` reproduces the same order.
- **Windows and macOS** use override tables, `library/catalog/effects-windows.json` and
  `effects-macos.json` (`effects.<type>` = `{plugin, params, param_mode(s), param_ranges}` or
  `unsupported`). A type listed there resolves **strictly** to that plugin. The `unmapped` section makes
  each table complete (every type is mapped, unsupported, or listed with a `family`: `core`,
  `reaper-plugin`, `reaper-jsfx`, `golem-jsfx`, `installed-plugin`, `no-plugin`, `untested`); the
  rack code does not read `unmapped`.
- On Windows/macOS the amp/cab core (`amp`, `amp-nam`, `cab`) is the official **NeuralAmpModeler VST3**
  (`VST3: NeuralAmpModeler`), which loads both the `.nam` model and the IR.
- What REAPER actually scanned decides availability, not what an installer claims
  ([block-status.md](block-status.md) §3). REAPER scans plugins **only at start-up**: after any plugin
  install, restart REAPER (`POST /api/system/reaper-restart`).
- REAPER loads LV2, VST2, VST3 and CLAP (Linux), not LADSPA.
- The full list of embedded components, with licences and what is really installed on this machine, is
  `provision/components.json`, served by `GET /api/system/libraries` (System ▸ Licences ▸ Libraries).

## 2. Linux install (`provision/install.sh`)

| Script | What it installs | Where |
|---|---|---|
| `packages.txt` (apt) | LSP, Calf, x42-plugins, Dragonfly, Guitarix + GxPlugins, ZamPlugins, mda-lv2… | system |
| `install-plugins.sh` (sudo) | the LV2 set the catalogue needs (Calf, x42, Dragonfly, guitarix, zam, mda, BYOD, avldrums, DrumGizmo…) | system |
| `plugins.sh` | pinned GitHub releases, checked against `downloads.sha256` (`lib-fetch.sh` `fetch_verified`): NAM LV2 v0.2.2 (base only, see §3), AIDA-X, Ratatouille, Aether, Dexed VST3 | `~/.lv2`, `~/.vst3` |
| `plugins-deb.sh` | pinned `.deb`: GuitarML Proteus, ChowDSP BYOD | system |
| `install-zconvo.sh` | **patched** IR convolver (§3) | `~/.lv2/zeroconvo.lv2` |
| `install-nam.sh` | **patched** NAM LV2 (§3) | `~/.lv2/neural_amp_modeler.lv2` |
| `airwindows.py` | Airwindows TapeDelay2 (VST2, MIT): fingerprint of the **extracted file** pinned (the archives change at the same URL); no admin rights | `~/.vst/airwindows` (Linux), `%LOCALAPPDATA%\Programs\Common\VST3\GoleM` (Windows) |
| `install-sfizz.sh` | sfizz (piano block, SFZ kits) from the sfztools OBS repository, falling back to the repository's `.deb` files if its key expired; never leaves a broken `sources.list.d` behind | system |
| `install-prisma.sh` | Prisma (Grit block), compiled from source at a pinned commit, free variant | `~/.vst3/Prisma.vst3` |
| `install-spectral.sh` | Spectral Compressor (nih-plug), PaulXStretch, and our own **GoleM Freeze** (`plugins/golem_freeze`, Rust/nih-plug), compiled from pinned sources, no JACK | `~/.clap`, `~/.vst3` |

Every optional step is non-fatal: on failure `install.sh` prints which block will stay struck and where
to see it (System ▸ Licences ▸ Libraries). Scripts run with `sudo` install system headers but build and
place user plugins as the calling user (`$SUDO_USER`), otherwise REAPER would never see them.

## 3. Plugins we compile and patch

Two plugins in the default chain crashed REAPER on rapid preset/patch changes. The rack compiles them
from pinned sources with a patch from `provision/patches/` and installs them in `~/.lv2`, where they
take precedence over the packaged/released build.

| Script | Plugin (blocks) | Source | Patch | Defect fixed |
|---|---|---|---|---|
| `install-zconvo.sh` | x42 zeroconvo.lv2 (`cab`, IR in `amp`) | `x42/zconvo.lv2` commit `05405cb` (v0.7.2 + the upstream fix) | none since 2026-11-03 (was `zconvo-retired-engines.patch`) | the worker destroyed the engine it had just loaded when two state restores followed each other on a fresh instance (every chunk rewrite re-restores all FX of the track) → assertion/abort. Reported upstream (x42/zconvo.lv2#12) and fixed there on 2026-10-02; no release carries it yet, hence the pinned commit. The Ubuntu package is also built with assertions and lacks two upstream fixes. |
| `install-nam.sh` | neural-amp-modeler-lv2 (`amp`, `amp-nam`, `pedal-nam`, `preamp-nam`, `comp-nam`) | `mikeoliphant/neural-amp-modeler-lv2` tag v0.2.2 | `nam-thread-safe-worker.patch` | `restore()` and `work_response()` (which REAPER also calls on the main thread when removing an instance) scheduled work on the LV2 queue while audio threads used it. `restore()` now uses the scheduler the host passes; `work_response()` no longer schedules (retired models go to a bin the worker empties). |

- Each script verifies the result: NAM by a marker string only the patched binary contains (`retired model(s)
  freed by the worker`), zeroconvo by the commit written in its bundle (`golem-build.txt`, the upstream fix leaves
  no string); `plugins.sh` does not overwrite a patched NAM.
- **A `git pull` is not enough** on an installed rack: run the script, restart REAPER, and check
  `/proc/<reaper pid>/maps` points to `~/.lv2/…`. Licences ▸ Libraries shows "zeroconvo.lv2 (fixed build)" and
  "neural-amp-modeler-lv2 (patched)" as installed or missing.
- `tools/check-recall-stress.sh [N]` replays rapid recalls and counts crashes (expected 0). It can crash
  REAPER when the defect is present: never while someone plays.
- Investigations: [audit-2026-10-01-crash-convolveur.md](audit-2026-10-01-crash-convolveur.md),
  [audit-2026-10-14-crash-nam.md](audit-2026-10-14-crash-nam.md).

## 4. Windows and macOS

The desktop installers (`provision/windows/install-system.ps1`, `provision/macos/install-system.sh`)
download pinned versions with SHA-256 from `provision/windows/pins.json` / `provision/macos/pins.json`
(REAPER, NeuralAmpModeler VST3, AVL Drumkits, sfizz, PawPaw/Vitalium, and Python/VC++ on Windows).
Everything else a block needs on those systems is either shipped with REAPER (ReaPlugs, JSFX), a GoleM
JSFX from the repository, or listed as "install it yourself" (macOS `manual` pins, shown on the
installer's last page). Per-type status: the `unmapped` section of the desktop tables (§1). Known gaps:
DrumGizmo (Aasimonster kit) is unavailable; the E-Piano (Dexed) and organ (setBfree) blocks are not
mapped on desktop yet, the piano (sfizz) plays on Windows since 2026-10-22 and is untested on macOS; NAM A2 captures do not play with the official VST3 0.7.13 (`format`
reason and playable twin, [block-status.md](block-status.md) §2) — they do with the NAM 0.7.15 golem builds
and installs over it since 2026-10-22 ([platforms.md](platforms.md) §5.2).

## 5. Catalogue of plugin families (Linux)

| Family | Plugins | Blocks |
|---|---|---|
| Neural capture | **NAM LV2** (A1 and A2; `quality_scale` port = A2 quality scaling), AIDA-X, Ratatouille (unused by the pipeline: no A2), GuitarML Proteus (knob-driven models), ChowDSP BYOD | amp/pedal/outboard capture blocks |
| Convolution | **zeroconvo.lv2** (fixed build), ir.lv2 | `cab` |
| Reverb | Dragonfly (Hall/Room/Plate/Early), Aether, Calf Reverb, a-Reverb | reverbs |
| Delay | ReaDelay (REAPER), Calf Vintage Delay, Airwindows TapeDelay2, LSP, a-Delay | delays |
| Dynamics / EQ | LSP (EQ, comp, gate, limiter, de-esser), Calf, ZamPlugins, x42 (dpl limiter, fil4 EQ), ReaGate/ReaEQ/ReaComp/ReaXcomp | dynamics, eq, voice chain |
| Drive / amp sims | Guitarix + GxPlugins, BYOD | drives, wah, octave… |
| Pitch | x42 fat1 (pitch correction), REAPER JSFX | `pitch-correct`, pitch blocks |
| Spectral / lofi | Spectral Compressor, PaulXStretch, GoleM Freeze, Prisma | `spectral-comp`, `stretch`, `freeze`, `grit` |
| Instruments | Vital / Vitalium, Dexed, setBfree, sfizz, RS5k, avldrums, DrumGizmo | keys and drum blocks |
| GoleM JSFX | `reaper/Effects/` (`golem_killswitch`, `golem_deesser`, `golem_click`, `golem_drumseq`, `golem_sample_trig`, `golem_super8` looper, `golem_tuner`…) | service and utility blocks |

Not used: Airwin2rack (only a VCV Rack build is released), individual ChowDSP plugins (covered by
BYOD), TAP/rev-plugins (LADSPA only), commercial "AI" plugins.

**Quarantine is data, not a missing plugin.** Some installed plugins are removed from every compile
because they freeze or crash REAPER (GxEchoCat, ReaPitch, GxDetune): `effects.json` `quarantine`,
see [blocks-doctrine.md](blocks-doctrine.md) §6. Before offering a new plugin as a block, validate it
there (alone in a lane, two rebuilds, `fxparams`, `tools/check-block-stall.py`).

## 6. Vital / Vitalium (`vital` block, keys lane)

The block tries, in order (`ADD_ALIAS`): `VST3i:Vital` (official, user-installed), `VST3i:Vitalium`,
`Vitalium` (LV2; installed by the desktop installers from PawPaw). A `.vital` preset (JSON, ~200 KB) is
loaded:

- **VST3**: spliced into a template `vst_chunk` (`bridge/vital.py` `splice_chunk`, templates
  `bridge/templates/vital-vst3.chunk.b64`, `vitalium-vst3.chunk.b64`), applied live. The template works
  on Linux and Windows.
- **LV2**: through the **track chunk** — the `P` port lines **and** the `<X urn:juce:stateBinary>` block
  (the JSON + a NUL), FXID removed to re-instantiate (`vital.lv2_state` → `golem_rig.lua`
  `chunk_set_vitalium`).

Rules learned the hard way:

- **An LV2 port belongs to the host** and overwrites the value the binary state just restored: a preset
  is complete only with its ports, computed from the file.
- A preset loaded with `TrackFX_SetPreset` applies only its ports; its `state:state` is ignored, even for
  presets shipped with the plugin. REAPER does not expose `vst_chunk` for an LV2.
- An LV2 preset added while REAPER runs is seen only after a restart, hence the chunk path.
- Verify in the plugin's **internal state** (`chunkdump`, then read the `stateBinary`), not in the
  params REAPER displays (those are the ports, i.e. what the host believes).

`bridge/templates/vitalium-lv2-ports.json` (772 ports → Vital id, min, max): names come from the plugin
source, bounds are **read on the plugin**. To regenerate it for a new Vitalium: a probe track `GoleM:_…`
holding Vitalium, `fxsetall` to 0 then to 1 (dev command of `golem_apply.lua`, track at zero volume),
`chunkdump` after each pass, read `settings` in the `stateBinary`: min = pass 0, max = pass 1. The
normalised value is linear. `fxpreset` and `trackdel` are the companion dev commands.
