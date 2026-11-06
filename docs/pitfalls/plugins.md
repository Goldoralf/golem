# Third-party plugin pitfalls

Plugins (NAM, x42 zeroconvo, guitarix, Calf, Vital/Vitalium, sfizz…) run inside REAPER's process: a
plugin bug is a REAPER crash, and a plugin that "loads" may still do nothing. Catalog and per-block
data: `library/catalog/effects.json`, `docs/plugins.md`, `docs/blocks-doctrine.md`.

---

## Read REAPER's stderr first when it dies

**Symptom.** REAPER disappears; `journalctl -k` shows one old segfault or nothing.

**Cause.** Aborts (signal 6: glibc heap corruption messages, failed `assert` inside a plugin) leave
nothing in the kernel log; `apport.log` gives only the signal number. The plugin often names itself
(file and line of an assertion) on REAPER's stderr.

**Rule.** Read in this order: REAPER's stderr log, then `/var/log/apport.log` ("called for pid …
signal N"), then `journalctl -k`. Look in third-party code before rewriting your own. If guessing
fails, instrument the plugin (an in-memory event ring: who calls what, on which thread, timestamped)
rather than theorise.

**Detect.** `/tmp/golem-reaper.log` (REAPER's stdout/stderr, written by `provision/start.sh`),
`/var/log/apport.log`, `journalctl -k`, `/proc/<pid>/maps` (which `.so` is actually loaded).

**Code.** `provision/start.sh`, `provision/autostart/install-autostart.sh` (log redirection),
`bridge/diag.py` (collects it).

---

## x42 zeroconvo: double state restore on a fresh instance crashes REAPER

**Symptom.** About one crash in ten when presets are recalled in quick succession (three rebuilds
in under three seconds). Four signatures for one bug: assertion `clv_online->ready()`, null write in
`Convolver::run_buffered_mono`, `free(): corrupted unsorted chunks`, segfault in REAPER's LV2 work
queue.

**Cause.** The plugin's worker frees "whatever is in `clv_offline`". On a fresh instance there is no
old engine; a second load slips in and the NEW engine is destroyed while being put online. Two state
restores ~40 ms apart are enough — and every `SetTrackStateChunk` re-restores every FX on the track.
Distribution packages also ship it compiled with assertions (an `assert` in the audio thread aborts
the host).

**Rule.** Use the rack's build: upstream commit `05405cb` (x42/zconvo.lv2#12, fixed after our report: a
restore that arrives while an engine is pending is queued). Our own patch did the same job until
2026-11-03; the standalone reproducer passes on `05405cb` and fails on v0.7.2. `git pull` does not fix an
installed rack: run the install script, restart REAPER, check `/proc/<pid>/maps`. When a release carries
the fix, pin the release and rerun the reproducer.

**Detect.** `./tools/check-recall-stress.sh [N]` (expected: 0 crashes; it brings REAPER down when
the bug bites — never while someone plays). Settings ▸ Licences ▸ Libraries shows
`zeroconvo.lv2 (fixed build)`.

**Code.** `provision/install-zconvo.sh`, `provision/patches/zconvo-repro/`, called by `provision/install.sh`. Reference:
`docs/audit-2026-10-01-crash-convolveur.md`.

---

## NAM LV2: two producers on the LV2 work queue crash REAPER

**Symptom.** Crash on quick patch changes: general protection fault in a NAM layer `Process`,
`double free or corruption`, or a fault inside REAPER's work-queue loop.

**Cause.** `restore()` (main thread) used the instance's scheduler instead of the restore-safe one
the host passes in its features, and `work_response()` — which REAPER also calls on the main thread
when it retires an instance — scheduled work while audio threads used the same queue.

**Rule.** In LV2 code: `restore()` schedules with the `LV2_WORKER__schedule` passed in its features;
`work_response()` schedules nothing (retired objects go to a lock-free slot emptied by the worker).
Use the rack's patched build; `git pull` alone does not install it.

**Detect.** Rapid `POST /api/recall` series across NAM patches; `./tools/check-recall-stress.sh`;
`/proc/<pid>/maps`.

**Code.** `provision/install-nam.sh`, `provision/patches/nam-thread-safe-worker.patch`;
`provision/plugins.sh` must not reinstall the release over the patched binary. Reference:
`docs/audit-2026-10-14-crash-nam.md`. The Windows/macOS VST3 does not use this worker.

---

## Linux: two plugins embedding the NAM core share one registry

**Symptom.** On Linux only, REAPER dies the moment a rig holds both a NAM block and a capture-module
block (`.gcap`); its stderr ends with `terminate called after throwing an instance of
'std::runtime_error' — what(): Config parser already registered for: SlimmableContainer`. The same
patch plays on Windows. Measured 2026-10-25 with the two Titan `.gcap` next to a Fender Super Reverb NAM.

**Cause.** `golem-capture.clap` and the NAM LV2 both compile the NAM core. On Linux the reader exported
it, and `nam::ConfigParserRegistry::instance()::inst` is a GNU *unique* symbol, bound once for the
whole process whatever the plugins' load flags. The second plugin loaded registers its architectures
into the first one's registry and throws. Windows DLLs do not share symbols, so it never shows there.
macOS (weak symbols coalesced by dyld) is unverified.

**Rule.** A plugin golem builds that embeds a third-party library exports only its entry point:
hidden visibility plus a version script (`{ global: clap_entry; local: *; }`).

**Detect.** `nm -D --defined-only golem-capture.clap` lists `clap_entry` alone;
`tests/test_capture_player.py::test_linux_reader_exports_only_its_clap_entry`.

**Code.** `native/capture/CMakeLists.txt` (`UNIX AND NOT APPLE` block), `native/capture/bin/`.

---

## LV2 ports belong to the host: they override restored state

**Symptom.** A plugin's internal state (e.g. a Vital patch) seems never to reload from the chunk;
or a preset loaded with `TrackFX_SetPreset` applies only some settings.

**Cause.** After restoring `state:state`, the host writes its port values: ports reset to defaults
erase the state just restored. Removing port lines (`P`) from the chunk therefore breaks state
restore. `TrackFX_SetPreset` on an LV2 preset applies ports only and ignores `state:state`, even on
presets shipped with the plugin.

**Rule.** Write the chunk with the state AND the ports computed from that state. Verify in the
plugin's INTERNAL state (dump the chunk and re-read the state blob), not in the parameters REAPER
displays — those are the ports, i.e. what the host believes.

**Detect.** Command `chunkdump`; re-read the `stateBinary`.

**Code.** `reaper/Scripts/golem_rig.lua` `chunk_set_vitalium`, `bridge/vital.py`;
`docs/plugins.md` § Vital.

---

## `TrackFX_SetParam` is normalized (0–1) on the NAM VST3

**Symptom.** Writing `12` to an input calibration level sets 60 dBu; writing `1` to an output-mode
enum selects the wrong entry.

**Cause.** On the official NeuralAmpModeler VST3, `TrackFX_SetParam` takes normalized values, not
native ones. Writing 0/1 to switches and to the first enum entry happens to work, which hides it.

**Rule.** For any non-binary setting on a VST3, target the displayed value (dichotomy), or read the
parameter's min/max and taper first with `fxparams`. Do not trust comments that claim "native
values".

**Detect.** `fxparams` / `fxset`; `./tools/check-core-parity.py`, `./tools/check-native-nam.py`.

**Code.** `reaper/Scripts/golem_rig.lua` `load_native_core`, `set_norm_to_target`.

---

## Same plugin family, different sound per OS

**Symptom.** The same preset is quieter or saturates differently on Windows/macOS than on Linux; an
A2-format NAM capture plays the dry DI on Windows/macOS with no error.

**Cause.** The NAM LV2 (Linux) calibrates input (`12 − input_level_dbu`) and normalises output; the
official VST3 does it only if configured to. The VST3 applies a fixed −18 dB to any IR, x42 none.
The last published VST3 binary cannot read the A2 (`SlimmableContainer`) architecture and passes the
signal through silently.

**Rule.** Configure the VST3 like the LV2 (calibrate input at 12 dBu, normalized output, +18 dB on the
IR-only instance). Read the capture's `architecture` from the file — not from its name — and refuse
A2 where the core cannot read it; publish the limitation (`caps.nam_unreadable`). Re-measure parity
before lifting the restriction.

**Detect.** `./tools/check-core-parity.py` (null depth and per-third-octave difference).

**Code.** `reaper/Scripts/golem_rig.lua` `load_native_core`; `bridge/rig.py` `_wrong_kind_for_os`;
`bridge/compile_rig.py` `_native_core_for`. Reference: `docs/audit-2026-10-01-parite-coeurs-os.md`.

---

## Installed is not validated: quarantine is data

**Symptom.** A plugin that is "already installed" crashes REAPER on patch load or block removal, or
freezes the engine when switched on.

**Cause.** Plugins reach patches (including AI-generated ones) without ever being tested on the rig.

**Rule.** Before offering a block: put it alone in an empty lane, rebuild twice, and run the stall
test. A faulty plugin is quarantined in the catalog data — removed from the drawer, from the
external AI vocabulary and from compilation, with one warning per dropped block. When the quarantine
list changes, notify downstream consumers that keep their own copy of the catalog.

**Detect.** `./tools/check-block-stall.py --catalog` / `--rig`; `./tools/check-recall-stress.sh`.

**Code.** `library/catalog/effects.json` (`quarantine`), `bridge/rig.py` `_drop_quarantined`,
`bridge/blockstatus.py`, `bridge/tones_jobs.py`, `app/page-designer.js` (drawer).

---

## IR files can contain an echo

**Symptom.** "A delay with one repeat" on a preset where every time-based effect is off.

**Cause.** Some cabinet IR `.wav` files contain a second impulse hundreds of ms after the first.

**Rule.** Read every IR at compile time and cut the cached copy before a late impulse; name the
faulty packs.

**Detect.** `./tools/check-irs.py`.

**Code.** `bridge/compile_rig.py` `ir_late_impulse` (compile guard), `bridge/ir_quality.py` (`scan`,
`echo_of`: per-pack verdict for the library and drawer badges), `bridge/rigstatus.py`.
