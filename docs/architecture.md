# golem — architecture map

> **Status: DESCRIPTIVE.** How the code works today; every claim cites a file or function. If the
> code and this page disagree, the code is right: fix the page. Read with [`CLAUDE.md`](../CLAUDE.md)
> (pitfalls), [`glossary.md`](glossary.md), [`preset-format.md`](preset-format.md),
> [`golemfm-protocol.md`](golemfm-protocol.md), and [`live-engine.md`](live-engine.md) (scene design).

---

## 1. Processes and channels

| Process | What it is | Entry point |
|---|---|---|
| **Bridge** | FastAPI app served by uvicorn on `:8770` (`GOLEM_PORT`, `bridge/config.py` `HTTP_PORT`). It owns the state, the API, the WebSocket, the foot controller reader, outgoing hardware MIDI, and every background poller. | `bridge/app.py` (`_startup` starts the tasks) |
| **REAPER** | The audio engine. It runs headless and opens `sets/golem-set.rpp` (`provision/start.sh`). At launch REAPER runs `Scripts/__startup.lua`, which `dofile`s each golem script **into one shared Lua context**. Each script then keeps its own `reaper.defer` loop running. | `reaper/Scripts/__startup.lua` |
| **Browser app** | Preact + htm with **no build step**, served as static files on `/app/` (rack screen and tablet) and `/app/m.html` (phone Companion). | `app/index.html` → `app/main.js` |
| **golem.fm** (optional) | Cloud service. The rack **pulls** jobs from it and pushes status to it. golem.fm never opens a connection into the rack. | `bridge/tones_jobs.py`, `bridge/golemfm.py`, `bridge/rigstatus.py` |

```
 Browser (app/, m.html)                                 golem.fm (optional)
   │  HTTP /api/*  ▲ WS /ws (full state snapshot, push-only)   ▲ pull jobs / ack / PUT status
   ▼               │                                           │
 ┌──────────────────────────── BRIDGE (uvicorn :8770) ─────────┴──────────────┐
 │ routes → recall engine → compile → commands.write_command()                │
 │ foot.py (pedalboard MIDI in) · midi_out.py (MIDI out to pedals) · monitors │
 └──┬──────────────────────┬─────────────────────────────────────▲────────────┘
    │ presets/.command.json│ OSC UDP :8000 →  ← :9000           │ presets/.*.json telemetry
    │ (single slot + ack)  │ (FX params, transport actions, vu) │ (polled by monitors.py)
 ┌──▼──────────────────────▼─────────────────────────────────────┴────────────┐
 │ REAPER: golem_watch (defer) ─dofile→ golem_rig / golem_apply               │
 │         ─ProjExtState relays→ golem_backing/click/drums/sample/… loops     │
 │         Lua loops ⇄ JSFX through gmem namespaces                           │
 └────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 Command slot: `presets/.command.json`

- **Writer and ack.** Only `bridge/commands.py` `write_command(cmd)` writes the slot: it adds a
  monotonic `seq` and renames a temp file into place (`_write`). `golem_watch.lua` `ack()` writes
  `{seq,t}` to `.command-ack.json` (Windows: `.command-ack.json.<seq>`) on each consumption.
- **Bridge-side queue.** The slot is never overwritten while it holds an unread command. If the
  slot is busy, the command joins `_queue`, and a daemon thread (`_drain`) writes it after the next
  ack. `_superseded()` drops queued commands that a newer one makes useless: a `rig_recall`
  replaces queued recalls **and** scenes, a `scene_apply` replaces scenes queued after the last
  queued rebuild, `mixer_apply` and `tuner` keep only the latest. A `stomp` is never dropped.
- **Stuck or missing reader.** An unread command older than 3 s is overwritten when REAPER is
  down (`_STALE_S`); after 30 s with REAPER up, the queue moves on and logs it (`_HUNG_S`). At its
  own startup `golem_watch` **consumes the leftover command without running it** (`last =
  read(CMD)`); after a REAPER restart, `monitors._remount_after_restart` replays the preset.

### 1.2 Routing inside REAPER: `golem_watch.lua` `tick()`

`tick()` reads the action and does one of three things:

1. **Relays it with no FX surgery.** It writes the raw JSON into a **ProjExtState** key that a
   dedicated loop reads (deduplicated by `seq`): `backing`, `perf_rec`, `sample`, `drums`,
   `standard`, `preview`, `click` and `drumlearn` go to `golem/<name>_cmd` (`perf_rec` →
   `perf_cmd`); `tuner` sets `golem/tuner_on`; `midi_reinit` calls `reaper.midi_reinit()`.
2. **Runs `golem_rig.lua`.** It `dofile`s `golem_rig.lua` when the raw text contains `"rig_recall"`
   or `"stomp"`, or the action is `vst_*`, `mixer_apply` or `mixer_dump`. **The match is on the raw
   JSON text, not the action field.** That is why every rig command the bridge sends carries
   `"_route":"rig_recall"`: `scene_apply`, `stomp` and `plugin_window` all include it.
3. **Runs `golem_apply.lua` for everything else.** This file holds dev probes and utility actions
   such as `dumpfx`, `fxparams`/`fxset`, `chunkdump`, `audio_reset`, `extstate` and `reload`. It
   contains no recall code.

Note that `golem_rig.lua` is **not** a resident loop: it is re-executed from disk for every command
and every deferred verification pass.

### 1.3 Other channels

- **ExtState (process-wide, non-persistent).** Handshakes between Lua scripts: `golem/watch_gen`
  and `click_gen` (a loop that is no longer the latest instance stops), `golem/rig_rebuilt`
  (golem_rig → golem_watch), `golem/rig_verify` and `rig_verify_heal` (golem_watch → golem_rig).
- **ProjExtState** (in the project) holds the relay keys above. **Track `P_EXT`** (saved in the
  `.rpp`) holds golem_rig's per-track memory: FX signature (`get_fxsig`) and file lines (`files_mem`).
- **OSC** (`bridge/reaper_osc.py` `ReaperLink`). Device file: `reaper/OSC/golem.ReaperOSC`. The
  bridge sends on UDP 8000 and listens on 9000 (`GOLEM_OSC_SEND` / `GOLEM_OSC_RECV`).
  - **Bridge → REAPER** carries only low-latency, stateless writes: `set_fx_param`
    (`/track/N/fx/M/fxparam/P/value`: expression pedal in `app._apply_exp`, looper commands and
    levels in `bridge/looper.py`), `trigger_action` (`/action`: backing transport in
    `bridge/backing.py`) and `set_track_volume`.
  - **REAPER → bridge**: `/track/1..3/vu` becomes `state.levels.in1..in3` (broadcasts are throttled
    to about 20 Hz), `/tempo/raw` becomes `state.tempo`, and any received message sets
    `reaper_connected` (`app.on_osc`).
  - **What OSC never carries:** recalls, scenes, stomps, mixer trims, and anything that adds or
    removes FX. All of those go through the command slot.
- **gmem (JSFX ↔ Lua).** Namespaces: `golem_tuner`, `golem_looper`, `golem_drums`, `golem_knobs`,
  `golem_chordseq`, `golem_drumlearn`, `golem_sysex`, `golem_gapmeter`, and `golem_drumtrans`
  (written by golem_rig: the drum-kit translation table). `__startup.lua` shares **one** Lua
  context, so the last `gmem_attach` wins: each gmem loop re-attaches on every tick.
- **Telemetry files** under `presets/`, read by the bridge (mostly `monitors.py` pollers):

  | File | Written by | Read by |
  |---|---|---|
  | `.livemap.json` | golem_rig | `rig_is_live`, `_apply_exp` |
  | `.rig-check.json` | golem_rig `verify_files` | `_monitor_audio` → `state.rig_check` (FX FILE chip) |
  | `.clock.json` | golem_clock | `_audio_alive` (audio-thread witness) |
  | `.tuner.json`, `.looper.json`, `.backing.json`, `.perf.json`, `.click.json`, `.drums.json`, `.sample.json`, `.standard.json`, `.midi.json` | one per loop | the matching `_poll_*` task (`.midi.json`: `_read_midi_health`) |
  | `.watch.log`, `.golem-rig.log`, `.lua-errors.log` | Lua scripts | logs; `.lua-errors.log` receives any error from a guarded `defer` callback |

- **Hardware MIDI from the bridge.** Pedalboard input is read by `bridge/foot.py`: `aseqdump` on
  Linux, `python-rtmidi` on Windows and macOS. Outgoing MIDI to the Whammy DT and generic MIDI
  pedals goes through `bridge/midi_out.py` and never passes through REAPER. On the REAPER side,
  `golem_midi.lua` keeps REAPER's MIDI inputs to the keyboard controllers and leaves the sound
  card's MIDI port to the bridge.

---

## 2. The journey of a gesture

### 2.1 Loading a preset from the screen

1. **The app sends the request.** Live (`app/page-live.js` `recall`) and setlists post
   `/api/recall {preset, scene}` or `{slot}`. A scene tile posts `{scene}` with **no preset**, so
   the current setlist line is kept.
2. **The route hands off.** `app.py` `recall()` calls `recall.recall_async(pid, scene)` for a
   preset, or `recall.slot_async(slot, "screen")` for a slot. Either way the work goes to `_EXEC`, a
   **single-worker** `ThreadPoolExecutor`, which keeps the asyncio loop free and gestures in FIFO
   order. `_RECALL_LOCK` (an `RLock`) also serializes the entry points that are not on the loop:
   the foot, golem.fm jobs and preview.
3. **`recall.do_recall(pid, scene, line)` updates the state.** It sets `state.preset_id`,
   `scene_id` and `song`, loads the arrangement, seeds `state.stomps` (`stomp_states()`), writes
   `.perfsrc.json`, arms backing and foot services, and calls `emit_sandbox()`. The click (when the
   mode's click policy is `preset`) and the stop of orphaned drums are scheduled at +0.8 s
   (`_later`), *after* the recall, so they do not compete with it for the command slot.
4. **`emit_sandbox_preset(preset, scene)` compiles and decides.** It bakes the scene
   (`scene_bake.to_paths_preset(work, scene, union=True, veto=input_veto(work))`), then compiles it:
   `compile_rig.compile_preset(baked)` builds the plan with `rig.build_plan` and writes
   `reaper/FXChains/<id>.rig.json` (`:` becomes `~`, `file_stem`), plus per-track `.RfxChain`
   cores on Linux or a `native_core` spec on Windows/macOS. The requested `rig_recall` is
   downgraded to **`scene_apply`** only when the preset id, `scene_shape()` and `state.reaper_gen`
   are unchanged since the last emission, REAPER is running, and `rig_is_live(pid)` holds:
   `.livemap.json` names this preset **and** is newer than the REAPER process (the `_LAST_EMIT`
   test). It then calls `write_command({action, preset, scene, "_route":"rig_recall", bpm?})`,
   pushes hardware-pedal state (`_whammy_dt_glue`, injected as `app._hw_pedals_glue`) and sets the
   EXP targets (`_set_exp_blk_from`, `_set_exp_vol_from`).
5. **`golem_watch.lua` `tick()` runs it.** If a rebuild's SETTLE window is still open, `tick()`
   returns and retries on a later tick (§5). Otherwise it acks, then `dofile`s `golem_rig.lua`.
6. **`golem_rig.lua` `main()` applies it.** It reads the `.rig.json` and sets the project tempo from
   `cmd.bpm` (falling back to the preset file). For `scene_apply`, `reapply_scene()` re-applies
   bypass, params, levels and mutes on the existing tracks; it returns `false` when the rig holds
   0 FX, which falls through to a rebuild. Otherwise it sets ExtState `rig_rebuilt`, and
   `materialize()` builds tracks, sends and FX, then `write_livemap()` and `write_knobmap()`. If
   materialization fails, the livemap is overwritten with `preset:""` so the next emission rebuilds.
7. **Verification.** About 2 s later golem_watch triggers `rig_verify` (§5).
8. **Back to the screen.** `do_recall` writes `presets/.live.json`, which lets `boot_recall` adopt
   the running rig on the next bridge start. Then `_notify()` (`broadcast_threadsafe`) sends
   `state.snapshot()` to every `/ws` client, and the HTTP response also carries the snapshot.

**The Designer path.** `POST /api/sandbox_apply` (`app.py` `sandbox_apply`) emits the draft through
`recall.emit_preset_async`, then saves it to `presets/.sandbox.json`. Same-shape edits (a knob, a
bypass) become `scene_apply`.

### 2.2 A foot switch press

1. **Which pedalboard.** `pedalboard.wire_contract()` combines the intent in
   `config/pedalboard/contract.json` with the active device descriptor
   (`config/pedalboard/devices/*.json`). `foot.set_device()` loads the result. Default intent
   (`foot.DEFAULT_INTENT`): **PC n** → slot n; **CC 20–24** → scenes A–E; **CC 30–34** → stomp
   switches 6–10; **CC 7 / CC 11** → expression pedals 1 / 2; **Note** → switch identity and
   press/release edges.
2. **PC.** One press sends Note + PC + CC; `FootReader._handle` filters by wire channel and
   dispatches. `_on_pc` → `recall.schedule_slot(slot, "pc")` → `do_recall_slot` on the engine
   worker, a no-op when the slot's preset and line are already loaded (so the PC that accompanies
   every scene press is harmless).
3. **Scene CC.** `app._on_foot_scene(sc, val)` runs off the reader thread through `_off_thread`.
   If a block claims that scene switch (`state.scene_claims`: tuner, rec, click, a chain block…),
   the press goes to `_do_stomp`. Otherwise it calls `recall.schedule(None, sc)`. **The preset id
   is `None` on purpose**: the preset and setlist line stay as they are, and the scene is normally
   emitted as `scene_apply`.
4. **Note edges** go straight to `app._on_stomp_edge`, on the reader thread, because timing
   matters here. They are dispatched in this order: arrangement → backing → sample → drums →
   standard → looper.

### 2.3 A stomp toggle (foot CC 30–34, Live tile `POST /api/stomp`, phone `POST /api/lane/stomp`)

1. **Find the target.** `app._do_stomp(sw, want, source)` first skips switches that are driven by
   edges (sample, drums, standard, arrangement). When the press comes from the screen it
   synthesizes a press and release instead. It then resolves the switch through
   `store._foot_summary`, and service blocks (tuner, rec, click, compo, Whammy, midi-pedal) are
   handled in the bridge.
2. **Toggle chain blocks.** For chain blocks it sends
   `write_command({"action":"stomp","ids":[…],"on":bool,"_route":"rig_recall"})`.
3. **REAPER side.** `golem_rig.lua` `handle_stomp` finds each FX tagged `golem:<id>` and calls
   `fx_set_on` (for an IR convolver this drives the plugin's Enable parameter instead of bypassing
   it; see CLAUDE.md). Nothing is rebuilt. The bridge updates `state.stomps[sw]`, and calls
   `foot_leds.request_align()` when the press did not come from the foot.

### 2.4 An expression pedal

1. **Read.** `foot.py` `_on_cc` turns CC 7 and CC 11 into `on_volume` and `on_treadle`, which call
   `app._on_pedal("exp1"|"exp2", v)` on the reader thread.
2. **Pick the role.** `state.pedals` (from `config/pedals.json`) maps the physical pedal to a role.
   The volume role uses `_EXP_VOL["assign"]`; the block role uses `_EXP_BLK["assign"]`. With no
   block assignment, a looper preset sets all loop levels instead, and otherwise the treadle is
   relayed to the Whammy DT or a midi-pedal (`midi_out`).
3. **Send.** `_apply_exp(assign, v)` looks up the block in `.livemap.json` (cached by mtime) to get
   the track, FX, parameter and native range, normalizes the value, and calls
   `reaper.set_fx_param(...)`. That is **one OSC datagram**, with no command slot and no Lua.
4. **Carry over** (2026-11-06, the maintainer's decision). A pedalboard sends a pedal's position only
   when it moves; nothing can query it. So every emission (`recall.emit_sandbox_preset`, rebuild **and**
   scene switch — `reapply_scene` sets each block's whole state) passes its working copy through
   `app._exp_bake` before compiling: the known position is written on each role's target, base params
   and scene overrides alike. The volume role always has a value — the last one received (pedal or
   screen, `POST /api/exp`), else **100 %** after a bridge start (0 dB, never a silent start). The block
   role is written only once its pedal has moved (`state.exp_known`); until then the preset's own setting
   stays. Nothing is saved to disk: after a restart the pedal may have moved.

---

## 3. Where state lives

**In memory.** `bridge/state.py` holds the singleton `RigState` (`state`). Fields are mutated in
place and `state.touch()` stamps the change. `snapshot()` is the **whole** document sent to the
WebSocket by `app._broadcast()`, or by `broadcast_threadsafe()` from other threads. The socket is
push-only: incoming text is ignored. Other in-memory state that a bridge restart loses:
`recall._LAST_EMIT` (the last emitted shape, so the first emission after a restart rebuilds), the
`app._EXP_*` pedal targets and the `commands._queue`.

**On disk** (all paths relative to the repo root, `bridge/config.py`):

| Path | Content | Versioned? |
|---|---|---|
| `presets/<id>.json` | user presets | **no** (`.gitignore`) |
| `presets/.sandbox.json` | Designer edit buffer (`GET /api/sandbox`). Edit it through the app, never by hand. | no |
| `presets/.*` | command slot, ack, livemap, telemetry, logs, `.live.json` | no |
| `library/factory/` | factory presets, patches, setlists, grooves, standards (`bridge/factory.py`) | yes |
| `library/catalog/effects.json` | block catalogue, including `catalog_version` and per-type `quarantine` | yes |
| `library/…` (other) | patches, kits, pedals, block presets, tones… (partly ignored: downloads, sfz, drumkits) | mixed |
| `config/` | recipes and descriptors (`pedalboard/`, `engines/`, `controller-models/`, `modes/`…) and local state (`io.json`, `cards/`, `inputmaps/`, `mixer.json`, `devices.json`, `.band.json`…) | mixed |
| `setlists/*.json`, `songs/`, `recordings/`, `sets/*.rpp`, `mappings/*.json` | user content and REAPER project | no |
| `reaper/FXChains/*.rig.json`, `*.RfxChain` | compiled plans (build output) | no |

`bridge/local_state.py` lists the paths that are local state but used to be tracked (`PATHS`).
`preserve()` keeps them across an update (`tools/local-state.py`). The rule: **the repository
versions recipes and seeds, not what happens on the machine.**

**In REAPER.** Each input gets a root track named `Sandbox #Input N` (`SANDBOX_PREFIX`), with
sub-tracks for lanes and branches, plus service tracks (Click, Drums, Looper, MIDI Clock…). Each
block's FX is tagged `golem:<id>` through its `renamed_name`. Per-track `P_EXT` holds the signature
and file memory (§1.3); ProjExtState holds the relays. gmem is process memory only and is lost on
restart, which is why drum-kit tables are rewritten on every materialization.

---

## 4. Module map

### 4.1 Bridge (`bridge/`)

| Domain | Modules |
|---|---|
| App and wiring | `bridge/templates/` (core FX-chain templates: NAM head/cab, x42 cab, Vital) · `app.py` (FastAPI app, auth middleware, `/ws`, foot and stomp dispatch, EXP glue, includes every router) · `config.py` (paths, ports) · `state.py` · `golog.py` (logging) · `winfs.py` (atomic replace on Windows) |
| Recall engine | `recall.py` (`do_recall`, `emit_sandbox_preset`, `scene_shape`, `boot_recall`) · `scene_bake.py` (Designer document → baked paths) · `rig.py` (paths/splits model, validation, quarantine, `_wrong_kind`) · `compile_rig.py` (plan + cores → `.rig.json`) · `resolver.py` (ref → NAM/IR file) · `commands.py` (slot + queue) · `store.py` (preset I/O, migrations, foot summaries) · `vital.py` · `sandbox_edit.py` (draft conflicts between screens) |
| REAPER link and monitors | `reaper_osc.py` · `monitors.py` (REAPER process, audio witness, rig check, every `_poll_*`) · `reaper_update.py` · `desktop_*.py` (Windows/macOS engine, audio, MIDI, power, network) |
| Foot and MIDI | `foot.py` · `pedalboard.py` (which board, contract) · `foot_leds.py` · `midi_out.py` · `midi_api.py` · `controllers.py`, `controller_program.py` · `devices.py`, `hotplug.py` · `drumlearn.py` |
| Live services | `looper.py` · `backing.py` · `drums.py` · `sample.py` · `standards.py` · `arrangement.py` (cues) · `bars.py` · `riffclick.py` · `compo.py` · `mixer.py` · `modes.py` · `karaoke.py` · `live_widgets.py` · `lane_stomps.py`, `lane_apply.py` |
| Content | `patches.py` · `setlists.py` · `songs.py`, `golemfile.py` (`.golem` format), `song_folders.py`, `inbox.py` · `kits.py`, `kit_import.py`, `drumkits.py`, `grooves.py` · `irlib.py`, `ir_quality.py` · `factory.py` · `genres.py`, `tunings.py` · `anim_packs.py` · `preset_view.py` (pure preset sheet, shared with golem.fm) · `preset_export.py` · `blockstatus.py`, `inventory.py`, `libraries.py` |
| Recording and audio jobs | `recording.py`, `takes.py`, `takecut.py`, `take_rpp.py`, `song_rec.py`, `uploader.py` · `reamp.py`, `preview.py` · `plugin_capture.py`, `plugin_recipes.py`, `plugin_view.py` · `separation*.py` · `transcribe*.py` · `disk.py`, `storage.py`, `activity.py` |
| Cards and inputs | `cards.py`, `card_setups.py` · `inputmap.py` · `inputclip.py` · `engines.py` |
| golem.fm | `golemfm.py` (pairing, catalogue, stems, pushes) · `tones_jobs.py` (**job queue**: `_HANDLERS`, `process`, `start_poller`) · `tones_sync.py` (library push) · `golem_pull.py` (`.golem` install) · `rigstatus.py` (status push) · `roster.py` · `loans.py` · `follow_uplink.py` · `fingerprint.py`, `signatures.py`, `ed25519.py`, `release_sig.py` |
| Auth and network | `auth.py` (loopback trusted; remote devices use a token; `ADMIN_*` lists) · `connect.py`, `reach.py`, `serial.py` |
| Diagnostics | `diag.py` (events, reports) · `mcp.py` (read-only MCP server) |
| Startup and backup | `boot_progress.py`, `startup_home.py`, `arrivals.py`, `backup.py`, `importer.py`, `local_state.py` |
| Health | `health.py` (dated facts, verdict, environment drift — Settings ▸ Health and the top-bar dot) · `first_check.py` (the first-start check: three gestures, dated and verified) · `silence.py` ("why no sound?": where the signal stops) · `routes_health.py` |
| Routers | `routes_content` (catalogue, presets CRUD, setlists, integrations, VST host) · `routes_system` (dashboard, buffer, restart) · `routes_dev` (REAPER probes — admin only; calibration, meters and controller set-up — any paired device, a musician's gesture) · `routes_patches` · `routes_modes` · `routes_inputmap` · `routes_card_setups` · `routes_desktop_audio` · `routes_backing` · `routes_blocks` · `routes_kit_import` · `routes_standards` · `routes_separation` · `routes_diag` · `routes_connect` · `routes_network` · `routes_startup` · `routes_t3k` (TONE3000) · `routes_machine` (this computer: window, start with it, lock down — logic in `machine.py`) |

### 4.2 REAPER scripts (`reaper/Scripts/`)

| Script | Role |
|---|---|
| `__startup.lua` | Wraps `reaper.defer` in `xpcall` (errors go to `.lua-errors.log`) and `dofile`s the scripts below |
| `golem_watch.lua` | Command-slot loop: ack, SETTLE, routing, deferred `rig_verify` |
| `golem_rig.lua` | The engine: `materialize`, `reapply_scene`, `handle_stomp`, mixer, VST host, `verify_files`, livemap and knobmap |
| `golem_apply.lua` | Dev probes and utility actions (not the recall) |
| `golem_backing` · `golem_click` · `golem_drums` · `golem_sample` · `golem_chordseq` · `golem_looper` · `golem_perfrec` · `golem_preview` · `golem_drumlearn` · `golem_tuner` · `golem_clock` (MIDI clock + audio witness) · `golem_knobs` · `golem_midi` (MIDI device guard) | Service loops (`.lua`), each reading its relay or gmem; most publish a `presets/.<name>.json` |
| `golem_fxinventory.lua` (runs once from golem_watch) · `golem_paths.lua` · `golem_desktop_audio.lua` · `golem_capture.lua` · `golem_audio_snapshot.lua` | Helpers |

Key JSFX (`reaper/Effects/`): `golem_super8` (looper), `golem_drumseq`, `golem_drumtrans`,
`golem_chordseq`, `golem_click`, `golem_tuner`, `golem_safety` (output limiter), `golem_killswitch`,
`golem_deesser`, `golem_gapmeter` (test instrument), `midi-clock`, `knob-tap`, `note-zone`,
`sysex-io`. `golem_click` declares `gmem=golem_chordseq`: it reads the sequencer's "a grid is
playing" flag, and while a grid plays its ticks arrive as notes from a `golem_chordseq` instance
placed before it on the Click track (`golem_click.lua`).

### 4.3 App (`app/`)

- **Shell.** `main.js` is the topbar plus a hash router. `NAV` lists Live, Designer, Songs, Library
  and Settings; the Settings route is `#/system`. `PAGES` maps routes to `page-live.js`,
  `page-designer.js`, `page-songs.js`, `page-library.js` and `page-systeme.js`. The current mode
  can hide pages (`mode.ui.pages`).
- **`lib.js`.** `api`, `post`, `useAsync`; `useRigState` (the WebSocket, reconnecting every
  1.5 s); `useRoute`, `go`; the topbar slots `setTopAction`, `setTopSlot`, `setTopIO`; `HubPage`;
  `savePresetEverywhere`.
- **Hubs** assemble `page-*.js` tabs. Library: amps, fxblocks, ir, kits, samples, grooves, synth,
  backing, loops, outboard, keys-instruments, standards. Songs: setlists, patches, setlist-groups,
  repertoire. Settings: system, soundcard, network, pedalboard, api, licenses.
- **Pages.** `designer-*.js` (lanes, drawer, browser, sheets, scenes, arrangement, pedalboard, VST
  host; `designer-model.js` holds `MODEL_GEARS`), `live-*.js` (bank bar, stageboard, pages, mixer,
  tuner, chart, widgets, tools), and `m.html` + `mobile.js` for the phone Companion.
- **Pure models.** `*-model.mjs` files hold logic without UI, each with a `*.test.mjs` beside it.
  The only dependency is `vendor/htm-preact-standalone.module.js`.

---

## 5. Rebuild vs scene switch

**Union materialization.** `to_paths_preset(..., union=True)` mounts **every** lane and branch
that any scene uses. A lane that is off in a scene is kept and turned down to `LANE_MUTE_DB`
(−150 dB, `scene_bake.py`). The track topology is therefore the same for all scenes of a preset,
and a scene change only flips state (`reapply_scene`): no `TrackFX_Add`/`Delete`, so reverb and
delay tails keep ringing. The design rationale is in [`live-engine.md`](live-engine.md).

**What makes a change a rebuild.** A change is a rebuild when anything in `recall.scene_shape()`
changes. The shape covers paths (id, input, out, MIDI); block id, type, ref, cab and model,
**and the resolved capture file**; split structure; Vital sound, piano `sfz` and EP bank; the set of
drum kits, and the pads kit with its contents; whether the looper is on, and its loop table; and
controller channels.

Bypass, knobs, levels and lane mutes are **not** part of the shape. A new preset, a REAPER restart
(`reaper_gen` increments in `monitors._monitor_reaper`; `recall.invalidate_shape()`), or a stale
livemap also forces a rebuild.

**A rebuild still reuses tracks.** Inside `materialize`, each track is cleared and rebuilt
(`clear_track_fx` → `build_track_fx`) only if its `fx_signature` differs from the one stored in
`P_EXT`, or if the track is new, its core failed, or it unexpectedly holds 0 FX. The signature
covers role, a hash of the `.RfxChain` contents, core types, and per block the type, id and files.
Otherwise the track **REUSEs** its FX and only gets `apply_track_params`. Two presets with
identical chains switch without reloading their IRs.

**SETTLE** (`golem_watch.lua`, `SETTLE = 0.5`). After a rebuild, NAM and IR files load on LV2
worker threads. Touching the FX graph during that window led to use-after-free crashes. So for
0.5 s after a rebuild (signalled by ExtState `rig_rebuilt`), golem_watch **does not consume**
rig commands (rebuild, scene, stomp). They stay in the slot; the bridge queues anything newer and
coalesces it. Relayed services and read-only diagnostics (`dumpfx`, `peaks`, `meters`, `midilist`,
`recdiag`, `chunkdump`) always pass. The bridge's slot timeout (`_SLOT_TIMEOUT = 0.9` s) is
deliberately longer than SETTLE.

**`rig_verify`.** About 2 s (`VERIFY_DELAY`) after a `rig_recall` or `scene_apply`, golem_watch
sets ExtState `rig_verify`, then `dofile`s golem_rig. golem_rig reads back, in plain text, the model
or IR that each plugin actually loaded (`verify_files`), writes `.rig-check.json`, and may request
one retry. It **repairs** (re-instantiates through the chunk) only after a rebuild
(`rig_verify_heal`). After a scene switch it only reports, because a repair would cut the sound
mid-song.

---

## 6. Where to change what

| I want to… | Start in… |
|---|---|
| Add a block type | `library/catalog/effects.json`: the `type`, `plugin`, `params` (with `map`) and `category` (plus `effects-windows.json` / `effects-macos.json` for desktop plugin names). Usually no engine code: `golem_rig.lua` `add_block_fx` and `apply_block_params` are driven by the catalogue. Special loaders (files, chunks, instruments) live in `golem_rig.lua` (`build_*_block`, `load_block_file`). If the block changes what must be rebuilt, add it to `recall.scene_shape`. Validate it with `tools/check-block-stall.py` before offering it. |
| Add an API route | A `routes_*.py` `APIRouter`, included in `app.py`. Check `auth.py` (`SENSITIVE_GET`, `ADMIN_*`) for anything sensitive. After editing, run `./provision/reload.sh`. |
| Add a page or tab | A new `app/page-*.js`, registered in its hub's `HubPage` tabs (`page-library.js`, `page-songs.js`, `page-systeme.js`), or in `main.js` `PAGES`/`NAV` for a new hub. UI text in English. Check the rendered page at 1024×600. |
| Add a golem.fm job | `bridge/tones_jobs.py` `_HANDLERS` (plus `_SYNC_PREFIXES` if it belongs on the sync lane). The protocol is in [`golemfm-protocol.md`](golemfm-protocol.md). |
| Change scene behaviour | Bridge: `scene_bake.py` (what a scene bakes), `recall.scene_shape` (what forces a rebuild), `recall.do_recall`. REAPER: `golem_rig.lua` `reapply_scene`. |
| Change foot behaviour | Data first: `config/pedalboard/contract.json`, `devices/*.json`. Then `foot.py` (parsing) and `app.py` `_on_foot_scene`, `_do_stomp`, `_on_stomp_edge`. Test without the pedalboard with `tools/check-foot.py` (`/api/foot/inject`). |
| Add a REAPER loop | A new `reaper/Scripts/golem_<x>.lua` `dofile`d from `__startup.lua`. Use a generation ExtState so a relaunch replaces the loop; re-attach gmem on every tick; publish `presets/.<x>.json`. Add a relay branch in `golem_watch.lua` (exempt from SETTLE only if it never touches preset FX) and a `_poll_<x>` in `monitors.py`. Arm any service track (`I_RECMODE=2`). |
| Add a JSFX | `reaper/Effects/<name>.jsfx`. Put every constant in `@init`, prefix local copies (EEL2 is case-insensitive), declare `options:gmem=` if it talks to Lua, and keep `@block` light. Write slider values raw when the minimum is negative. |
