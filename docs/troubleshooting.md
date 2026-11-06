# Troubleshooting — symptom → checks → code

**Status: REFERENCE.** Decision trees for problems that actually happen on a golem rack. Each tree is
ordered: do step 1 before step 2. The background stories behind each step live in `CLAUDE.md`
("Pièges vécus"); this page only keeps what to look at and what each answer means.

Conventions: `$B` = `http://localhost:8770`. Paths are relative to the repo root. `presets/.*` files are
runtime state written by the bridge or by REAPER's Lua loops (never committed). Logs on Linux:
bridge = `/tmp/golem-bridge.log`, REAPER stdout/stderr = `/tmp/golem-reaper.log` (both from
`provision/start.sh`); on Windows/macOS the bridge log is `<resource dir>/GoleM/logs/bridge.log`
(`provision/desktop.py`). On Linux REAPER runs on a virtual X display (Xvfb, `:99` by default).

**Three rules that apply to every tree**

1. **Capture before you restart.** A REAPER restart erases the evidence. Run the probe of the tree
   first, then repair.
2. **A probe must not launch anything.** Tools marked ⚠ below make sound, crash REAPER on purpose, or
   take the engine for a few seconds: never while someone is playing or recording.
3. **Present is not loaded, configured is not running.** A file that exists, a device listed in
   `reaper.ini`, `reaper_running: true` — none of these prove the thing works. Each tree ends on a
   witness that moves (a counter, a parameter read back in clear, a message received).

---

## 1. No sound at all

Likely causes: sound card lost by REAPER · monitor knob / ALSA volume at 0 · input not armed · NAM or IR
not loaded · REAPER auto-mute · a service track fell out of REAPER's live graph.

1. **Run `./tools/check-silence.py` BEFORE restarting REAPER** (`--no-wait` without a musician). Read-only,
   ~12 s, asks you to play for 4 s, prints a verdict from upstream to downstream (no input → FX chain →
   muted branches → hardware output → outside REAPER) and saves `presets/.silence-<hhmmss>.json`.
2. **Is the audio thread alive?** `GET $B/api/state` → `audio`.
   - `{"ok": true}` → the card is fine, go to 3.
   - `ok: false`, `why: "audio thread stalled — sound card lost?"` → `/live` shows **⚠ NO AUDIO**. Witness:
     `presets/.clock.json` `{ticks, t}` written each second by `golem_clock.lua`. `t` advances and
     `ticks` frozen = the Lua loop lives but the audio thread is dead (REAPER kept a dead device;
     `Audio_IsRunning()` still says 1). The bridge already sent **one** automatic `audio_reset`
     (`bridge/monitors.py` `_audio_recover`), never during a take. Manual retry:
     `python3 reaper/golem-cmd.py '{"action":"audio_reset"}'` (refused while the transport runs —
     `golem_apply.lua` `audio_reset()`). `fix: "recovery had no effect — check the cable"` → cable/hub.
   - `card` set, `why: "<card> is not connected"` → chip **NO CARD**: plug it in or switch card in
     Settings ▸ Gear ▸ Soundcard. The single recovery attempt is kept for when it comes back.
   - `t` frozen too → not a card problem: REAPER or its Lua loops stopped → tree 4.
3. **Volume outside REAPER first.** Headphones OK but speakers silent = the interface's MONITOR knob, or
   the ALSA hardware volume (`alsamixer`), not the rig.
4. **Is the input armed and monitored?** `check-silence.py` section 3 reads the input tracks' chunk
   (REC/monitor, mute, HWOUT). Input tracks are armed with `I_RECMODE = 2` in `reaper/Scripts/golem_rig.lua`.
5. **Did the plugins load their files?** `GET $B/api/state` → `rig_check` (`presets/.rig-check.json`,
   written ~2 s after each recall by the `rig_verify` pass of `golem_watch.lua` → `golem_rig.lua`).
   `ok: false` → chip **⚠ FX FILE**; `issues[]` names track, kind (NAM model / IR) and expected file.
   Abnormal passes are kept in `presets/.rig-check.history.json`. An amp re-instantiated without its
   model sounds like a dry boost; a missing IR is silence on that lane.
6. **REAPER auto-mute.** A track whose output exceeds +6 dB is muted mid-song unless
   `automute=0` in `~/.config/REAPER/reaper.ini` `[reaper]` (documented in `provision/system-tuning.md`;
   not enforced by `provision/reaper-ini-setup.py` — check it by hand).
7. **Service tracks alive?** `./tools/check-alive.py` (read-only, ~20 s) reads the liveness witnesses
   twice (`.clock.json`, `.click.json`, …). A service track (click, drums, sample, standard, MIDI Clock,
   looper) that is not armed leaves REAPER's live graph once silent and its `@block` stops forever.
   Fix in code: arm it with `I_RECMODE = 2` (pattern in `golem_rig.lua`, looper track).

Code: `bridge/monitors.py` (`_audio_alive`, `_audio_recover`, `_read_rig_check`) ·
`reaper/Scripts/golem_clock.lua` · `golem_apply.lua` `audio_reset` · `app/page-live.js` (chips).

---

## 2. A scene does not switch / a block stays on

Likely causes: the scene was applied but its table says otherwise (bake priority) · rebuild expected but
`scene_apply` sent (stale livemap) · a muted branch still processing · lane state and flat table disagree.

1. **Did the command go out, and which one?** `tail /tmp/golem-bridge.log` and `presets/.watch.log`.
   The bridge chooses (`bridge/recall.py` `emit_sandbox_preset`): same plan *shape* (`scene_shape`: tracks,
   split, routing, NAM/IR files, Vital sound) + rig live → `scene_apply` (state toggle, no FX added or
   removed); anything else → `rig_recall` (rebuild).
2. **What did REAPER do?** `presets/.golem-rig.log` (rewritten each run, last lines = last action).
   `scene_apply : rig non matérialisé (0 FX) -> rebuild` = the rig was empty, it fell back to a rebuild.
   `scene_apply : ⚠ fichier non chargé` = a NAM/IR file is missing on a track (tree 1 step 5).
3. **Is the livemap stale?** `presets/.livemap.json` is rewritten on each REBUILD. `rig_is_live()` rejects
   it when its `preset` differs or it is older than the REAPER process. After a REAPER restart
   `invalidate_shape()` forces the next emission to rebuild. If a scene was applied on a freshly reloaded,
   empty project, force a rebuild by reloading the preset.
4. **What does the scene really say for that block?** Read the edit buffer, `GET $B/api/sandbox` (not
   `presets/<id>.json`: the Designer edits the sandbox). Bake rule, `bridge/scene_bake.py` `_bake_block`:
   1. `scene.blocks[<block id>]` → `true` forces ON, `false` forces OFF;
   2. else `scene.blocks[<block type>]` (stomp semantics: all blocks of that type);
   3. else the block's base `bypass`.
   A block "stuck on" usually has no key in this scene and `bypass: false` in its base.
5. **Lane states vs the flat table.** In a v2 preset each `(lane, scene)` points to a named state
   (`scene.lanes[<lane>].state`); the flat `scene.blocks` is its mirror, and it is what the bake reads.
   `bridge/preset_view.py` `ensure_lane_states` reconciles: if the scenes sharing a state contradict
   each other, **the state wins**. Editing one scene's flat table by hand can be silently undone.
6. **Branch muted, plugins still running.** In the live engine (`union=True`) a muted branch is a track
   mute (`D_MUTE`), not a removal: its plugins keep processing (CPU, and any engine freeze they cause).
   A lane muted in a scene sits at `LANE_MUTE_DB` (−150 dB), still present.
7. **Knob values.** `scene.params[<id>]` override the base; a knob set in another scene and absent here
   is written back to base or catalogue default (`touched_params`) — a scene is a state, not a diff.

Code: `bridge/recall.py` · `bridge/scene_bake.py` · `bridge/preset_view.py` · `reaper/Scripts/golem_rig.lua`
(`scene_apply` path). Contract: `docs/live-engine.md`, `docs/band-scenes.md`.

---

## 3. The foot controller sends nothing / triggers the wrong action

Likely causes: pedal unplugged or wrong port · port taken by REAPER or held for flashing · wrong MIDI
channel · chip out of date with the setlist · wrong transport declared (DIN vs USB).

1. **Does the rack hear anything?** `GET $B/api/state` → `foot_heard` = epoch of the last message
   *retained* from the pedalboard (`bridge/foot.py` `last_heard`). Press a switch, read again: unchanged
   → the message never reached the bridge (steps 2–5); changed → the message arrives, the mapping is
   wrong (steps 6–7).
2. **Bridge log.** `grep 'golem.foot' /tmp/golem-bridge.log`: `connecté au FCB (aseqdump -p <port>)` =
   listening; `port FCB introuvable — réessai auto…` = no port matched; `port du pédalier rendu` = released.
3. **Which port should it be?** `aseqdump -l`. The descriptor's `transport.kind` decides
   (`foot.resolve_port`): `din-soundcard` (default) = the DIN input of the **active sound card** (line
   matching its name, e.g. "Volt 276"); `usb` = the pedalboard's own port, matched on `transport.port_match`.
   A USB pedalboard declared as DIN (or the reverse) is never heard.
4. **Is the port free?** `GET $B/api/pedalboard` → `ports_held: true` = the port was handed to a flashing
   tool (auto-released after 15 min, `foot.HOLD_MAX_S`). On Linux the sound card's DIN belongs to the
   bridge; REAPER must never open it (rawmidi is exclusive). Check `cat /proc/asound/card<N>/midi0`
   (Owner PID per direction) and `presets/.midi.json` → `soundcard.in_owner/out_owner` (written by
   `golem_midi.lua`). If REAPER's PID owns it, the masks in `reaper.ini` are wrong → tree 7 step 3.
5. **Card re-enumerated?** After a USB replug `aseqdump` prints "Port unsubscribed"; the bridge restarts
   it (`_supervise`). If not, `./provision/reload.sh` (kills orphan `aseqdump`, relaunches the bridge).
6. **Channel and descriptor.** `GET $B/api/pedalboard` → `active`, `device.channel`, `wire`. The contract's
   channel is 1–16, the wire is 0–15. Intent (what golem wants) is `config/pedalboard/contract.json`;
   device facts (chip, channel, quirks, transport) are `config/pedalboard/devices/<id>.json`, never code.
   Validate with `./tools/check-descriptors.py`.
7. **Chip up to date?** `./tools/fcb/check-uno2.py` (no chip needed) checks the compiler and says whether
   the flashed image (`presets/.uno2-flashed.json`) matches the current setlist. Reflash when a preset of
   the setlist takes or gives SW2–5 to an on/off block: `tools/fcb/flash_uno2.py --identify | --write`.
8. **Rack side without the pedal.** ⚠ `./tools/check-foot.py [--preset X]` replays the chip's messages via
   `/api/foot/inject` and restores the state after; it rebuilds presets, so not while playing.

Code: `bridge/foot.py` · `bridge/routes_system.py` (`/api/pedalboard*`) · `tools/fcb/` · contract
`docs/pedalboards.md`.

---

## 4. REAPER stopped listening / commands are ignored

Likely causes: a Lua `defer` loop crashed · REAPER's main thread blocked (modal dialog, busy loop) ·
REAPER hung.

1. **Is the command consumed?** Compare `presets/.command.json` (`seq` written by the bridge) with
   `presets/.command-ack.json` (`seq` written by `golem_watch.lua` on each read; one file per seq on
   Windows). Ack `seq` ≥ command `seq` = consumed. The bridge queues commands while the slot is full
   (`bridge/commands.py`; `queued()` lists them but no endpoint exposes it — read the bridge log:
   `slot occupé : <action> attend son tour`). After 30 s unread (`_HUNG_S`) it logs
   `commande <seq> jamais lue en N s (REAPER figé ?)` and moves on.
2. **Is the watcher alive?** `tail presets/.watch.log` (started / replaced / commands). `presets/.clock.json`
   `t` frozen = the Lua loops are not running.
3. **Did a Lua callback crash?** `presets/.lua-errors.log` (written by the guard in
   `reaper/Scripts/__startup.lua`, with traceback). All golem loops share one Lua context; the guard
   keeps one error from killing the others. A single loop can be hot-reloaded:
   `python3 reaper/golem-cmd.py '{"action":"reload","script":"golem_midi"}'`.
4. **Modal dialog hidden behind the rack window** (e.g. "File already exists" on a render): it stops the
   main thread, so no command is read. Find it on REAPER's display:
   ```
   PID=$(pgrep -x reaper)
   export $(tr '\0' '\n' < /proc/$PID/environ | grep -E '^(DISPLAY|XAUTHORITY)=')
   xwininfo -root -tree | grep -i -E 'warning|reaper'
   xwd -id <window id> -out /tmp/dlg.xwd     # then view it
   ```
   Known cause fixed in `golem_preview.lua` (output deleted before rendering). New dialogs: same recipe.
5. **Main thread busy, no dialog.** One REAPER thread at 100 % CPU (`top -H -p $(pgrep -x reaper)`).
   Last line of `presets/.golem-rig.log` tells which rebuild step it is stuck in. A relative clock
   (`time_precise()`) persisted in the project (`P_EXT`) is a known cause of endless waits.
6. **Chip "⚠ REAPER stopped listening"** (Windows/macOS: `GET $B/api/state` → `cards.scripts_stalled`,
   with `cards.lua_error` = last line of `.lua-errors.log`; set when the audio telemetry from
   `golem_desktop_audio.lua` is silent ~9 s). Linux has no such chip: use steps 1–3.
7. **Repair.** `POST $B/api/system/reaper-restart`. On Windows a REAPER that answers no message for 15 s
   is terminated (`provision/desktop_window.py` `reaper_hung`, WM_NULL probe); one showing a "Save?"
   dialog still answers and is left alone. Then `POST $B/api/system/osc-refresh` if `reaper_connected`
   stays false.

Code: `bridge/commands.py` · `reaper/Scripts/golem_watch.lua` · `__startup.lua` · `bridge/monitors.py`
`_poll_cards` · `app/main.js` `CardMissing`.

---

## 5. REAPER crashes on preset changes

Likely causes: a plugin corrupting the heap on state restore — the IR convolver from the distro package,
the NAM amp before its patch, or an unvalidated plugin (some guitarix ones).

1. **Read REAPER's stderr FIRST:** `/tmp/golem-reaper.log`. Plugin assertions name their source
   (e.g. `src/lv2.cc:… Assertion 'self->clv_online->ready ()' failed` = convolver).
2. **Signal 6 (abort) leaves nothing in the kernel log.** `journalctl -k` shows only segfaults; aborts
   are in `/var/log/apport.log` ("called for … signal 6"). Look at both.
3. **Which plugin binaries are loaded?** The patched builds live in `~/.lv2` and must shadow the
   packaged ones:
   ```
   grep -o '/[^ ]*zeroconvolv.so' /proc/$(pgrep -x reaper)/maps | sort -u
   grep -o '/[^ ]*neural_amp_modeler.so' /proc/$(pgrep -x reaper)/maps | sort -u
   grep -c 'retired engine' ~/.lv2/zeroconvo.lv2/zeroconvolv.so
   grep -c 'retired model(s) freed by the worker' ~/.lv2/neural_amp_modeler.lv2/neural_amp_modeler.so
   ```
   A path under `/usr/lib/lv2`, or a 0 count → run `provision/install-zconvo.sh` / `provision/install-nam.sh`,
   then restart REAPER and re-check. A `git pull` alone does not rebuild them.
4. **Isolate.** Reduce the lane to one block and rebuild twice. A guilty plugin goes to quarantine by
   data: `"quarantine": "<reason>"` on its entry in `library/catalog/effects.json` (dropped from the
   drawer and the compile — `bridge/rig.py` `_drop_quarantined`).
5. **Measure.** ⚠ `./tools/check-recall-stress.sh [N]` — rapid preset changes, counts crashes, restarts
   REAPER after each. Expected 0 with patched plugins. **Crashes REAPER by design: never while playing.**

Background: `docs/audit-2026-10-01-crash-convolveur.md`, `docs/audit-2026-10-14-crash-nam.md`,
`provision/patches/`.

---

## 6. A blank / gap between scenes

Likely causes: a plugin that freezes the **whole** audio engine when enabled · the IR convolver bypassed
then re-enabled.

1. ⚠ **Measure the gap:** `./tools/check-scene-gap.py` (continuous test tone + sample-accurate detector,
   `reaper/Effects/golem_gapmeter.jsfx`, on the merge and each branch; screen path then foot path). Lower
   the MONITOR: the tone reaches the outputs. `--listen 180`: passive, you play and switch with the real
   pedal. `--off` removes probes left by an interrupted run.
2. **Gap everywhere, detector says 0?** The detector counts samples it *processes*; a frozen engine is time
   that does not exist for it. Compare with a clock that does not depend on what you measure:
   ⚠ `./tools/check-block-stall.py [plugins…]` (`--catalog`, then `--rig` to include the real NAM/IR
   files). Takes the engine for a few seconds; a test tone sounds.
3. **Known freezers:** GxEchoCat and ReaPitch (quarantined in `library/catalog/effects.json`), and the x42
   IR convolver when **bypassed and re-enabled** with its IR. Rule: never bypass the convolver — toggle its
   internal "Enable" parameter (`golem_rig.lua` `fx_set_on`).
4. **Check the gesture reached its target.** `stomp` targets the `golem:<id>` stamp; a measure of 0 ms on
   an FX that was never toggled proves nothing.
5. **Latency rather than a gap?** `./tools/check-scene-latency.py` (passive, real foot) — budget in
   `docs/audit-2026-09-21-latence-scenes.md`.

---

## 7. Keys / MIDI controller silent after a reboot

Likely causes: controller unplugged when REAPER started · `midiins`/`midiouts` masks wrong in `reaper.ini`
· REAPER opens MIDI devices only at startup.

1. **What does the sentinel say?** `GET $B/api/state` → `midi` (`ok`, `issues[]`, `fix`), from
   `presets/.midi.json` written by `reaper/Scripts/golem_midi.lua` (details in `presets/.midi.log`):
   the Keys device's name, `in_owner`/`out_owner` (should be REAPER's PID), `unplugged`.
2. **Controller plugged after REAPER started** → the sentinel sends `midi_reinit` alone (no mask touched,
   3 bounded tries). Log `✓ midi_reinit EFFICACE` = fixed; `⚠ midi_reinit SANS EFFET` = needs a REAPER
   restart. Do not restart the engine for a cable before that.
3. **Masks.** `grep -E '^midi(ins|outs)(_nowarn)?=' ~/.config/REAPER/reaper.ini`. Bits index REAPER's device
   cache (`~/.config/REAPER/reaper-midihw-alsa.ini` `[mididevcache]`, first-seen order, never pruned),
   not `amidi -l`. A mask at 0 with the controller present = stale mask. The sound card's DIN must **not**
   be in the masks (tree 3 step 4).
4. **Device memory.** `presets/.keys-midi.json` → `patterns` (from config) and `devices` (the slot last
   resolved). An unplugged controller is no longer nameable (`hw:II` only); this memory lets
   `provision/reaper-ini-setup.py` keep its bit. Missing `devices` → plug the controller once and restart.
5. **Repair for good.** `POST $B/api/system/reaper-restart`: stops REAPER, `provision/start.sh` reruns
   `reaper-ini-setup.py` (masks rewritten while REAPER is closed), relaunches.

---

## 8. golem.fm link

1. `GET $B/api/golemfm/status` → `{configured, paired, reachable, authed}` (`bridge/golemfm.py` `status`):
   - `configured: false` → no server URL in `config/integrations.json` (`golemfm.base_url`). Set it in
     Settings ▸ Connect. Rule (`routes_content.server_url_ok`): **https only**, plain http accepted only for
     loopback or private-network addresses (a dev server).
   - `reachable: false` → `<base>/api/health` did not answer 200: network, DNS, server down.
   - `paired: false` → no device token: pair from Settings ▸ Connect (`POST /api/golemfm/pair`, QR to approve,
     polled by `/api/golemfm/pair/status`).
   - `paired: true`, `authed: false` → token rejected (revoked, or token of another server): pair again.
2. **Jobs from golem.fm** (installs, recalls…) come by pull, never by push. `GET $B/api/tones-jobs` →
   `{last, processed, errors, log, inflight}`. `last` should be recent (long poll ~50 s, back-off up to
   5 min, paused when not paired — `bridge/tones_jobs.py`). Errors are in `log`.
   `POST /api/tones-jobs/run` pulls immediately.

---

## 9. Windows-specific

1. **One input silent with a generic ASIO driver.** ASIO4ALL (or any generic wrapper) can lose one input of
   a stereo endpoint without a word. Measure on the meter of an **armed** input track (it shows its input
   even muted; `GetInputActivityLevel` reads −150 when REAPER's window is hidden). Fix: choose the
   card's **native** ASIO driver. The card is recognised by USB identity (`provision/desktop.py`
   `KNOWN_USB_ASIO`); the Audio page warns "REAPER uses <generic>, a generic wrapper…"
   (`app/page-desktop-audio.js`); input roles follow the driver change (`bridge/inputmap.py` `inherit`).
2. **Drum module goes silent after REAPER starts.** A drum module opened as a MIDI *output* by REAPER
   stops sending. Only keyboards/pads get an output (MIDI clock): `bridge/desktop_midi.py` `wanted_masks`.
3. **Device replugged = dead port.** REAPER opens MIDI devices only at startup. `bridge/monitors.py`
   `_poll_hotplug` sees a REAPER-held device reappear (OS MIDI ports) and sends `midi_reinit`
   (log: `réparation MIDI auto : … rebranché`). Windows 11's MIDI service is multi-client: Python opening a
   port does not prove REAPER does not hold it.
4. **Hung REAPER** → tree 4 step 7.

---

## 10. The app shows old behaviour

**The window is frozen (the loading screen stuck mid-boot, or any page that stopped updating) and
nothing responds.** Check `GET /api/health`: `"screens": 0` while a golem window is open means the
bridge dropped that screen's WebSocket. Fixed on 2026-10-20 (the bridge now closes a screen it drops,
so the page reconnects — [pitfalls/ui.md](pitfalls/ui.md#a-screen-dropped-on-a-send-error-must-have-its-socket-closed));
on an older bridge, close the window and `POST /api/ui/show` (or relaunch golem) to get a live one.

1. **JS/CSS changed, screen unchanged.** The rack window (`golem desktop`) never reloads by itself. It polls
   `GET $B/api/app-build` every 20 s (newest mtime of `.js/.css/.html` at the **top level** of `app/` —
   files in `app/vendor/` are not counted) and shows **"⟳ New version installed — tap to reload"**. Until
   it is tapped, the old code runs.
2. **Python changed, behaviour unchanged.** uvicorn runs without `--reload`: run `./provision/reload.sh`
   (bridge only, REAPER untouched). Then `POST $B/api/system/osc-refresh` if `reaper_connected` stays false.
3. **Lua changed.** `golem_watch` re-reads `golem_rig`/`golem_apply` on each command; permanent `defer`
   loops need `{"action":"reload","script":"<name>"}` via `reaper/golem-cmd.py`, or a REAPER restart.
4. **Patched plugin rebuilt, REAPER still crashes** → it still has the old `.so` mapped: tree 5 step 3.
5. **Which version is installed?** `GET $B/api/system/update` → `current`, `branch`, `clean`, `status`.

---

## Quick index

| Witness | Where | Written by |
|---|---|---|
| Audio thread counter | `presets/.clock.json`, `state.audio` | `golem_clock.lua`, `monitors._audio_alive` |
| NAM/IR really loaded | `presets/.rig-check.json`, `state.rig_check` | `golem_rig.lua` (`rig_verify`) |
| MIDI devices / owners | `presets/.midi.json`, `.midi.log`, `state.midi` | `golem_midi.lua` |
| Last foot message | `state.foot_heard` | `bridge/foot.py` |
| Command consumed | `.command.json` vs `.command-ack.json` | bridge / `golem_watch.lua` |
| Lua callback errors | `presets/.lua-errors.log` | `__startup.lua` guard |
| Last rebuild | `presets/.golem-rig.log`, `.livemap.json` | `golem_rig.lua` |
| REAPER stderr | `/tmp/golem-reaper.log` | `provision/start.sh` |
| Silence snapshot | `presets/.silence-<hhmmss>.json` | `tools/check-silence.py` |
