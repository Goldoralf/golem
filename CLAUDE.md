# Working on golem with an AI agent

This file is loaded at the start of every agent session in this repository. It does not tell the
project's story — [`README.md`](README.md) does. It gives the **map**, the **rules that prevent
damage**, and where the details live. Read the map before you change anything.

## Start here

| Read | When |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Always, once: processes, channels, the journey of a gesture, where state lives, module map, "where to change what" |
| [`docs/glossary.md`](docs/glossary.md) | When a word is ambiguous — *lane* has five meanings, *mode* six, *sandbox* three |
| [`docs/preset-format.md`](docs/preset-format.md) | Before touching presets, scenes, lanes or blocks |
| [`docs/pitfalls/README.md`](docs/pitfalls/README.md) | Before touching REAPER, JSFX, plugins, MIDI, Windows, the UI or auth — one line per known trap |
| [`docs/howto/README.md`](docs/howto/README.md) | Recipes: add a block type, an API route, a page, a golem.fm job, a REAPER loop, a JSFX |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Symptom → checks → code (no sound, scene stuck, foot silent, REAPER deaf, crash) |
| [`docs/dev-setup.md`](docs/dev-setup.md) | Running without a rack; the checks CI runs; which `tools/check-*` probes are dangerous |
| [`docs/golemfm-protocol.md`](docs/golemfm-protocol.md) | Anything that talks to golem.fm (jobs, heartbeat, `/api/ext/…`) |

## The five rules that prevent damage

1. **Edited `bridge/*.py` → `./provision/reload.sh`, then `POST /api/system/osc-refresh`.** uvicorn runs
   **without** `--reload`: otherwise you test the old code and debug a ghost. JS/CSS: a refresh is enough —
   but the rack window never reloads by itself (it shows a "New version installed" banner). Lua: hot reload
   through the `reload` command whitelist, or restart REAPER.
2. **Never commit local state.** `sets/*.rpp`, `presets/`, `setlists/*.json`, `config/click|compo|recorder|io.json`,
   `config/cards/`, `config/inputmaps/`, `mappings/*.json` are written by the running rack
   (`bridge/local_state.py`, `.gitignore`). The repo holds recipes and seeds, not what happens on a machine.
3. **Verify at render, not at build.** The app is Preact + htm with no build: nothing compiles, nothing
   warns you. Use Chrome headless (`google-chrome --headless --screenshot`, or Playwright with
   `executable_path="/usr/bin/google-chrome"`) at **1024×600, no scroll** (phone: 390×844). Look at the
   pixels, read the console, and intercept every POST/PUT/DELETE to `/api/` when exploring.
4. **Languages.** The UI is in **English**; a French label on screen is a bug. Docs are in English. Code
   identifiers stay as they are; **code comments are in French**. The brand is written **`golem`** or
   **`/golem_`** in anything displayed — never "GoleM". Existing identifiers (folders `…/GoleM/…`, firewall
   rule, mDNS service) keep their name: renaming them breaks installs.
5. **A decision that matters goes into a doc**, with its status at the top (PROPOSED / FIXED / CODED), not into
   a commit message nobody will read. Descriptive references (architecture, glossary, formats) describe what
   the code does today: if they disagree with the code, the code is right — fix the doc.

## The map in fifteen lines

- **Bridge** (`bridge/`, FastAPI on `:8770`) owns the state (`state.py`), the API (`app.py`, `routes_*.py`), the
  WebSocket, the foot controller (`foot.py`), outgoing MIDI (`midi_out.py`) and the pollers (`monitors.py`).
- **A recall**: `recall.py` → `scene_bake.py` (preset + scene → plan) → `compile_rig.py` / `rig.py` → it decides
  **rebuild** (`rig_recall`) or **state switch** (`scene_apply`) in `emit_sandbox_preset` → `commands.write_command`.
- **REAPER side**: `golem_watch.lua` reads `presets/.command.json`, acks it, and runs `golem_rig.lua` (the engine:
  materialize, scenes, stomps, mixer) or relays to a dedicated loop (backing, click, drums, looper…).
  `golem_apply.lua` holds dev probes and utilities only.
- **Back to the bridge**: telemetry files `presets/.*.json` (`.livemap.json`, `.rig-check.json`, `.clock.json`…),
  OSC for meters and fast parameter writes. JSFX ↔ Lua talk through `gmem`.
- **Blocks** are typed by `library/catalog/effects.json` (+ `effects-windows.json`, `effects-macos.json`).
- **The Designer edits the sandbox** (`presets/.sandbox.json`, `GET /api/sandbox`, `POST /api/sandbox_apply`),
  never `presets/<id>.json` directly — hand edits diverge and get overwritten.
- **golem.fm** is optional and always pulled by the rack: jobs in `tones_jobs.py`, client in `golemfm.py`.
- **Auth** (`auth.py`) protects by **URL prefix**; the local screen is admin. A new route outside a protected
  prefix is public — see [`docs/howto/add-api-route.md`](docs/howto/add-api-route.md).

## How we work here

- **Read the contract before coding.** `docs/*.md` carry a status. If the code contradicts a contract, one of
  them is wrong: say so, don't settle it silently.
- **Refuse a wrong instruction.** Instructions sometimes rest on a false premise. Check, then say it **before**
  executing.
- **Verify before asserting.** On hardware, an unverified sentence costs an evening: read the code, measure in
  the browser, query the API. "I think that" has no place in a report.
- **A probe never starts a take.** A check tool that triggers a service puts it back the way it found it, and
  never touches what records or makes sound. Several `tools/check-*` probes play audio, rebuild the rig or can
  crash REAPER: their danger is listed in [`docs/dev-setup.md`](docs/dev-setup.md) — never run them while
  someone plays, and never without being asked.
- **Clean up after your tests.** Test scripts write real files (presets, setlists, mappings): restore them, and
  say so.
- **Never ship a mode without its tested exit.** A kiosk with no way out locks the user in.
- **Commit, push or tag only when asked.** Keep the user's uncommitted local files out of commits.

## Pitfalls that bite most often

The full list, with causes, detection and the code that guards each one:
[`docs/pitfalls/README.md`](docs/pitfalls/README.md). The ones to know before your first change:

- An unarmed REAPER service track leaves the live graph and its `@block` stops → arm with `I_RECMODE = 2`.
- `SetTrackStateChunk` erases the track's `P_EXT`, and a chunk lies while a plugin loads → write memory after
  the chunk; heal and verify after a rebuild; never touch FX during the SETTLE window.
- EEL2 is case-insensitive, and code before the first `@` section never runs → constants in `@init`, prefix locals.
- A JSFX slider with a negative minimum is bipolar → write the **raw** value (`TrackFX_SetParam`), not a
  linearly normalized one.
- Every `defer` loop re-attaches its `gmem` on each tick; all loops share one Lua context.
- A modal dialog in REAPER freezes the whole rack; a plugin can freeze the whole engine when it turns on
  (`tools/check-block-stall.py`) → quarantine it **as data** in `effects.json`.
- REAPER opens MIDI devices only at startup → `midi_reinit`; a send carries MIDI by default → `I_MIDIFLAGS = 31`.
- Generic CSS class names collide (`.live` …) → prefix state classes; the `hidden` attribute can be defeated
  by author CSS → don't render the node.
- A reference that **resolves** is not a reference of the right **nature** → check what it contains, and read
  the nature rather than trust a declared one (`rig._wrong_kind`).
- After a REAPER crash, read its stderr first (`/tmp/golem-reaper.log`) — the kernel log shows only segfaults.
- When the sound disappears, run `tools/check-silence.py` **before** restarting REAPER: restarting erases the
  evidence.

## Handy references

| | |
|---|---|
| Bridge | `http://localhost:8770` — app on `/app/`, phone Companion on `/app/m.html`, API reference on `/docs` |
| Full rig state | `GET /api/state` |
| App format | **1024×600, no scroll** (a tablet). `golem desktop` reproduces it exactly (REAPER hidden; `--dev` to see it) |
| Two uses, one install | `golem desktop` (window) and `golem server` (headless, a tablet is the screen); dedicated box: `golem autostart on` |
| The musician's screen | `golem phone` (dev only) — the Companion at 390×844 with a **Who** selector and the **conductor** switch |
| Checks CI runs | `ruff check .` · `python tools/check-syntax.py` · `node --test app/*.test.mjs` · factory seed · `pytest tests` ([`docs/dev-setup.md`](docs/dev-setup.md)) |
| Health from the terminal | `golem doctor` (`tools/doctor.py`) — the facts, open incidents and the registry's fixes (`--list`, `--fix ACTION`); works with the bridge down |
| Photograph a silence | `./tools/check-silence.py` — before restarting REAPER |
| Does a block freeze the engine? | `./tools/check-block-stall.py [plugins…]` — before offering a block |
| Does every page still render? | `.venv/bin/python tools/check-ui.py --test-content` (as CI; without the test pack the button inventory is not compared) — every page at 1024×600 and the Companion at 390×844 in headless Chrome: console, scroll, French, brand (writes intercepted; `--base` for a live bridge) |
| Does every patch still materialize? | `python tools/check-rig-materialize.py` — its own REAPER (dummy audio) and bridge on a `git worktree`: recalls each factory patch, checks rig-check, live map, plugins, a scene change; the rack next to it sees nothing (`--all` yours too, `--fixture` a built-ins-only bench patch) |
| Changed `golem_rig.lua`? | `pytest tests/test_rig_lua.py` first — the real engine under lupa on a fake REAPER (`tests/fakereaper.lua`): materialization, scenes, stomps, plugin resolution, in two seconds, no REAPER needed |
| Scene latency / blanks | `./tools/check-scene-latency.py` (passive, real foot) · `./tools/check-scene-gap.py` (sample-accurate) — budget ≤ 40 ms |
| Foot controller | `./tools/check-foot.py` replays the chip's messages (**rebuilds the rig**) · `./tools/fcb/check-uno2.py` (no chip needed; says whether the chip matches the setlist) |
| Validate descriptors | `./tools/check-descriptors.py` — pedals and pedalboards; catches French text in the UI |
| Probe an FX parameter | commands `fxparams` and `fxset` (read real parameters; write then read back, `norm` or `value`) |
| Back-ups | `./tools/check-restore.py` — local **and** vault cycle; run before any reinstall |
| Release update / signing | Settings ▸ About (tags only) · [`docs/release-signing.md`](docs/release-signing.md) |
