# REAPER pitfalls

REAPER is driven by Lua scripts (`reaper/Scripts/`) loaded by `__startup.lua` and by JSFX
(`reaper/Effects/`). None of this code can be unit-tested: every rule below was measured on a
running engine. Read the relevant section before touching `golem_rig.lua`, `golem_watch.lua` or any
script that creates a track, a send or a `defer` loop.

See also: [jsfx.md](jsfx.md) (the DSP side), [plugins.md](plugins.md) (third-party plugins),
[midi.md](midi.md) (devices).

---

## An unarmed service track leaves the live graph

**Symptom.** A service track (click, clock, drum machine, sampler, standard player, MIDI clock,
looper) stops reacting: its JSFX witness sliders (`ticks`, `tempo`) freeze, `gmem` heartbeats stop,
a "start" order logged by Lua has no effect. Sometimes it never works at all from the moment the
track is created.

**Cause.** A track with no input, no item and not record-armed is dropped from REAPER's live audio
graph once it goes silent (about two seconds of tail). Its `@block` stops running. Orders that
arrive through `gmem` are invisible to REAPER, so nothing can wake it up again: a permanent lock.
Input monitoring alone is not enough.

**Rule.** Every service track whose JSFX must keep running is armed with `I_RECARM = 1` and
`I_RECMODE = 2` ("record: none") — alive in the graph, unable to write a file. Re-assert it on every
rebuild, not only at creation.

**Detect.** A JSFX witness slider (`ticks`) that does not advance while the transport/heartbeat
says it should; `gmem` heartbeat frozen; `./tools/check-alive.py`.

**Code.** `reaper/Scripts/golem_click.lua` (arming block near `I_RECMODE`),
`golem_clock.lua` (track `MIDI Clock`), `golem_drums.lua`, `golem_sample.lua`,
`golem_rig.lua` (looper and service tracks, `I_RECARM`/`I_RECMODE` check before re-arming; input
tracks are `I_RECMODE 2` too).

---

## REAPER cannot tell that its sound card disappeared

**Symptom.** No sound at all, while everything reports healthy: `Audio_IsRunning()` returns 1,
`GetAudioDeviceInfo` returns the configured device name, zero xruns, `reaper_running: true`.

**Cause.** After a USB re-enumeration (unplug, hub reset) REAPER keeps a dead device handle. Every
status API returns configuration, not reality.

**Rule.** The only honest signal is a counter incremented by the audio thread. Compare it against
a wall clock that does not depend on the audio thread: wall clock advances + audio counter frozen =
card lost. Recover with the `audio_reset` command, not by restarting the whole stack.

**Detect.** `golem_clock` publishes `{ticks, t}` every second; the bridge compares two readings and
raises the "NO AUDIO" chip on `/live`. `./tools/check-silence.py` (run it BEFORE restarting REAPER —
a restart erases the evidence).

**Code.** `bridge/monitors.py` (`_read_clock_witness`, `_audio_alive`, `_audio_recover`,
`_monitor_audio`), `reaper/Scripts/golem_clock.lua`, `audio_reset` in `golem_apply.lua`.

---

## A relative clock persisted in the project freezes REAPER

**Symptom.** Every Lua loop goes silent at once (no commands read, no telemetry, false "no sound
card" alarm), no Lua error, no dialog, one REAPER thread at 100 % CPU, typically right after a
rebuild following a restart.

**Cause.** `reaper.time_precise()` restarts at every launch (of REAPER or of the OS). A value of it
stored in a `P_EXT` is saved in the project; the next session reads a timestamp "in the future", and
a busy-wait "until N seconds after the last write" waits for hours on the main thread.

**Rule.** Never persist a relative clock. If a stored relative timestamp is read back, treat any
value greater than "now" as stale, and bound every wait by an absolute cap computed from "now".

**Detect.** Last line of `presets/.golem-rig.log`; per-thread CPU time of the REAPER process;
`presets/.lua-errors.log` (empty in this case — the absence of errors plus silent loops points to a
main-thread wait).

**Code.** `reaper/Scripts/golem_rig.lua` `wait_loads_done` (`if t0 > t_in then return end`, deadline
capped at `t_in + FILES_FRESH`), key `P_EXT:golem_files_t`.

---

## All Lua loops share one context: one failing callback kills the others

**Symptom.** One script errors and unrelated loops (commands, telemetry, tuner) also stop.

**Cause.** `__startup.lua` runs every script in a single Lua context. An uncaught error in a
`defer` callback ends that callback's chain; a crash in the command watcher stops every command
while the other loops keep saying "alive".

**Rule.** Every `defer` callback runs under `xpcall`/`pcall` and logs with a traceback. A loop must
survive an error in its own tick.

**Detect.** `presets/.lua-errors.log` (written by the startup guard, traceback included); the
"REAPER stopped listening" chip when telemetry stops (as opposed to "no sound card").

**Code.** `reaper/Scripts/__startup.lua` (guard and error log), `golem_watch.lua` `loop()`
(`pcall(tick)`), `bridge/monitors.py` (reads `.lua-errors.log`), `bridge/rigstatus.py`.

---

## `gmem` must be re-attached on every tick

**Symptom.** A `defer` loop reads or writes another script's shared memory, or writes into
nothing.

**Cause.** All scripts share one Lua context, hence one `gmem` binding: the last `gmem_attach`
wins for everyone.

**Rule.** Every `defer` loop calls `reaper.gmem_attach(<its name>)` at the top of each tick, and
restores the previous name if it borrows another space temporarily.

**Detect.** Values that look like another script's data; a JSFX witness that never sees the
expected index.

**Code.** `golem_looper.lua`, `golem_tuner.lua`, `golem_knobs.lua`, `golem_chordseq.lua`,
`golem_drumlearn.lua` (re-attach at tick start); `golem_apply.lua` (gapmeter borrow and restore).

---

## A modal dialog stops the whole rack

**Symptom.** REAPER reads no command for minutes, all `defer` loops are silent. The REAPER window is
hidden, so nobody sees why.

**Cause.** Any modal dialog blocks REAPER's main thread. Known trigger: rendering to a file that
already exists opens "File already exists". Corollary: after the dialog is dismissed without
rendering, a "does the output file exist?" check sees the old file and reports success.

**Rule.** Delete the output file before every render. Never use "file exists" as proof that a step
produced it — present does not mean produced; compare a timestamp or a nonce. Avoid any API path
that can open a dialog on a headless rack.

**Detect.** Linux: `xwininfo -root -tree` then `xwd -id <window>` with the `DISPLAY`/`XAUTHORITY`
read from `/proc/<reaper pid>/environ`. Windows: see [windows.md](windows.md) (hung-window probe).

**Code.** `reaper/Scripts/golem_preview.lua` (`os.remove(out)` before rendering, then
`file_exists` check), used by previews, reamp trials and reamp jobs.

---

## `SetTrackStateChunk` also erases `P_EXT`

**Symptom.** Per-track memory stored in `P_EXT:*` disappears after a chunk rewrite.

**Cause.** `SetTrackStateChunk` replaces the whole track state, extended data included. Also, a
`P_EXT` value holds a single line: a value containing `\n` is stored empty.

**Rule.** Write `P_EXT` AFTER the `Set`, never before. Encode multi-line values (hex or similar).

**Detect.** Read back the `P_EXT` right after the chunk write.

**Code.** `reaper/Scripts/golem_rig.lua` (`FILES_KEY = "P_EXT:golem_files"`, written after the
chunk; hex encoding).

---

## The track chunk lies while a plugin is loading

**Symptom.** After a rebuild an amp or cab is silent, often on several scenes, and stays silent on
reuse (an identical signature reuses the empty instance).

**Cause.** Plugins that load files in an asynchronous LV2 worker (NAM, x42 convolver) serialise an
EMPTY `<STATE` while loading. A Get→modify→Set surgery a few ms after inserting such a plugin
re-instantiates it with no model. Every `SetTrackStateChunk` also makes REAPER restore the state of
EVERY FX on the track, which re-triggers loads.

**Rule.**
1. Remember each file line written on the track (by FXID) and heal any re-read chunk before writing
   it back.
2. Verify with a deferred pass that reads the plugin's own parameter ("Neural Model", "Impulse
   Response") in clear — the only honest fact.
3. Only repair (rewrite = re-instantiate the lane) right after a rebuild, never after a scene change
   mid-song and never while recording; there, only report.
4. An empty read on the first pass can be a slow load; conclude on a second pass.
5. After a rebuild, freeze rig operations (scene, stomp) for a settle period: touching FX that are
   still loading is a crash class.

**Detect.** `presets/.rig-check.json` → "FX FILE" chip on `/live`; command `chunkdump`.

**Code.** `reaper/Scripts/golem_rig.lua`: `heal_files`, `verify_files` (`rig_verify_heal`,
`rig_verify_retry`), `rig_rebuilt` ExtState; `golem_watch.lua` (`SETTLE`, `settle_until`,
`verify_heal`); `bridge/monitors.py`.

---

## A send's index is the value returned by `CreateTrackSend`

**Symptom.** Send parameters (volume, MIDI flags, channels) land on the wrong send, or nowhere.

**Cause.** Computing the index from a category formula is a silent no-op.

**Rule.** Use the index returned by `reaper.CreateTrackSend(src, dst)`; nothing else.

**Detect.** `./tools/check-routing.py`; read back with `GetTrackSendInfo_Value`.

**Code.** All `CreateTrackSend` call sites: `golem_rig.lua`, `golem_preview.lua`,
`golem_backing.lua`, `golem_perfrec.lua`, `golem_click.lua`, `golem_sample.lua`, `golem_drums.lua`,
`golem_chordseq.lua`.

---

## A send carries MIDI by default

**Symptom.** A destination that listens to notes (the looper is note-driven: notes 20-46) reacts to
a keyboard or pad controller on another lane: loops toggle play/stop by themselves.

**Cause.** A REAPER send transports audio AND MIDI, all channels, unless told otherwise.

**Rule.** Set `I_MIDIFLAGS = 31` ("no MIDI") on every send that must carry audio only. Such bugs can
sleep until a controller is enabled: fixing one fault often wakes another.

**Detect.** `./tools/check-routing.py`; `GetTrackSendInfo_Value(…, "I_MIDIFLAGS")`.

**Code.** `reaper/Scripts/golem_rig.lua` (`I_MIDIFLAGS` 31 set then read back), `golem_preview.lua`,
`golem_backing.lua`, `golem_perfrec.lua`.

---

## A plugin can freeze the whole audio engine when it turns on

**Symptom.** A short blank (about half a second) on scene change, on ALL tracks, intermittently.
A detector that counts processed samples reports zero gap.

**Cause.** Some plugins stall every track of REAPER while they activate. Measured offenders: a
guitarix echo (`GxEchoCat`), REAPER's own `ReaPitch` (both quarantined), and the x42 IR convolver
when re-enabled with its IR loaded via FX bypass. A JSFX meter only counts samples it processes:
when the engine is frozen, that time does not exist for it.

**Rule.** Measure engine stalls against a clock independent of the engine. Never bypass the IR
convolver: toggle its "Enable" parameter instead. Test every new block for stalls before offering
it. Make sure the toggle actually reached the target (cores are not always stamped `golem:<id>`).

**Detect.** `./tools/check-block-stall.py [plugins…]`, `--catalog` (every catalog plugin),
`--rig` (blocks of the loaded preset with their real files); `./tools/check-scene-gap.py`.

**Code.** `reaper/Scripts/golem_rig.lua` `fx_set_on` (parameter-based enable for the convolver);
quarantine in `library/catalog/effects.json` (see [plugins.md](plugins.md)).

---

## The live path has a latency budget, and undo points break it

**Symptom.** Scene changes or stomps feel late or random (around 100 ms), with no single culprit.

**Cause.** With no time budget, every added step on the live path looks harmless and nobody says
no. Full undo points (`Undo_BeginBlock`/`EndBlock` with "all" flags) serialise the state of every FX
on the main thread on each stomp or scene.

**Rule.** Budget: foot press → scene applied ≤ 40 ms (`docs/audit-2026-09-21-latence-scenes.md`).
Weigh every change on the live path in milliseconds. No undo block on stomp, scene or mixer moves;
undo only around full rebuilds.

**Detect.** `./tools/check-scene-latency.py` (passive observer at the real foot, safe during a
take); `./tools/check-jitter.py --silent` (the jitter is the `defer` tick, ~30 ms).

**Code.** `reaper/Scripts/golem_rig.lua` (`stomp` and `scene_apply` without undo, `mixer_apply`
without undo; `Undo_BeginBlock` only around the rebuild). `golem_apply.lua` still opens an undo block
in `main()` — it only serves dev/legacy commands; keep live actions out of it.

---

## Route commands on exact tokens, never on substrings

**Symptom.** A preset named "tuner" toggles the tuner; `reload` or `extstate` is routed to the wrong
script.

**Cause.** Dispatching a JSON command by searching a bare word anywhere in the raw text.

**Rule.** Decode the action, or match the quoted token (`'"rig_recall"'`), never a bare substring.
Same for process names (see [tooling.md](tooling.md)).

**Code.** `reaper/Scripts/golem_watch.lua` (quoted patterns, `action == …`).

---

## A single command slot loses commands

**Symptom.** A command sent while REAPER's main thread is busy (waiting on loads, copying a take)
is never executed and leaves no trace.

**Cause.** One file slot (`presets/.command.json`) overwritten by the next command.

**Rule.** Queue on the bridge side: write when the slot is free, advance on each acknowledgement.
Coalesce only what is safe (a recall replaces pending recalls/scenes; never drop a stomp). Flush on
exit.

**Code.** `bridge/commands.py` (`write_command` and queue), `tests/test_command_queue.py`.

---

## Auto-mute cuts a track mid-song

**Symptom.** A lane goes silent in the middle of a riff; REAPER re-mutes it; nothing in the logs.

**Cause.** REAPER's "auto-mute tracks exceeding +6 dB" protection.

**Rule.** `automute=0` in `reaper.ini` `[reaper]`; protect with a limiter on the master instead.
Edit `reaper.ini` only after REAPER has exited (it rewrites the file on quit).

**Code.** `ENGINE_FORCED` in `provision/reaper-ini-setup.py` (Linux) and `configure_ini` in `provision/desktop.py`
(Windows/macOS) force `automute=0`; `tests/test_reaper_ini_automute_license.py`. Output safety: `reaper/Effects/golem_safety.jsfx`.

---

## REAPER adds auto-fades to a new item

**Symptom.** A "no plugin" render does not null against its input (residue around −38 dB); timing
or level measurements are slightly off.

**Cause.** REAPER applies automatic fade-in/out to newly created media items.

**Rule.** In any measurement or render tool, zero `D_FADEINLEN`, `D_FADEOUTLEN`,
`D_FADEINLEN_AUTO`, `D_FADEOUTLEN_AUTO` on the items you create.

**Code.** `tools/check-core-parity.py` (item setup).

---

## Service loops run in every project REAPER opens

**Symptom.** A project that has nothing to do with the rack — a blank project opened to render a bass
line — gets a `MIDI Clock` (or `Click`) track out of nowhere. An instrument put on it stays silent and
cannot be recorded: the track has no master send (`B_MAINSEND = 0`) and is armed with "record: none"
(`I_RECMODE = 2`). Seen 2026-11-08 with EZbass.

**Cause.** `__startup.lua` starts the service loops for the whole REAPER session, not for one project.
`reaper.GetTrack(0, …)` and `InsertTrackAtIndex` act on the **current** project, whatever it is. The clock
re-created its track on every tick; the click created its track in the project open at startup.

**Rule.** A loop creates or repairs a service track only in **golem's project**
(`reaper/Scripts/golem_project.lua`, `is_golem`): a project saved under `<root>/sets/` (the launchers
open nothing else), or an **untitled** project that carries the project ExtState `golem/owner = 1`, which
`golem_rig.lua` sets on `rig_recall` — that covers the first boot, when REAPER starts with `-new` and the
project has no path yet. A project saved anywhere else is never golem's, marked or not: a recall that
lands on the musician's own tab builds the rig there (as before) but does not make it golem's for good.
Elsewhere the loop does nothing. No cached verdict: REAPER may keep the same `ReaProject*` when File ▸ New
replaces a project in the same tab, and a cache keyed on it would call the new blank project golem's.

A loop that publishes an audio-thread witness (`golem_clock` → `presets/.clock.json`) **stops publishing**
in a foreign project — a fresh timestamp with a frozen counter would read as a lost sound card and trigger
`audio_reset` (`bridge/monitors.py` `_audio_alive`) — and waits 1.5 s after coming back, since a background
tab is not processed. The click adopts its track **once per project**: it forces the click off and takes the
saved `click_cmd` seq of *that* project without replaying it; a track lost inside the adopted project is
repaired without switching anything off.

**Detect.** Open a blank project next to the rack: no `MIDI Clock`, no `Click`;
`presets/.clock.log` says "projet étranger au golem".

**Code.** `reaper/Scripts/golem_project.lua`; `golem_clock.lua` (`tick`), `golem_click.lua` (`adopt`, `tick`);
`golem_rig.lua` (`project.mark()` on `rig_recall`); tests `tests/test_service_tracks_lua.py`.
Command-driven loops (backing, drums, sample, perfrec, chordseq, drumlearn, preview) create tracks only on
an order from the bridge, so they are not guarded.

---

## The OSC meter is linear in dB, not an amplitude

`TRACK_VU n/track/@/vu` (`reaper/OSC/golem.ReaperOSC`) sends a normalized 0..1 value that is **linear in
dB over −72…+6 dB**: `dB = −72 + 78 · v`. Not documented by REAPER; measured on the rig 2026-10-20 — a
peak of −18.0 dBFS (`Track_GetPeakInfo`, `tools/check-silence.py`) read 0.685 on the meter (formula: 0.692),
and an empty input at −78 dBFS reads 0. Reading it as an amplitude (`20·log10(v)`) turns −18 dBFS into
−3 dB. A clip threshold of `v ≥ 0.995` means +5.6 dBFS, which an input track does not reach (0 dBFS = 0.923).
Code: `bridge/first_check.py` `vu_db`, `app/first-check-model.mjs` `vuDb` / `dbVu`.

## Devices are opened only at startup

MIDI and audio devices plugged after REAPER started are not opened. See
[midi.md](midi.md#reaper-opens-midi-devices-only-at-startup).

---

## Probing parameters

The track chunk shows a line of numbers without names. When a parameter write does not seem to land,
use the dev commands `fxparams` (list index, name, value, normalized, min/max) and `fxset` (write in
`norm` or `value`, then read back — separates "the API refuses" from "the caller never calls").
Code: `reaper/Scripts/golem_apply.lua` `fxparams`, `fxset`.
