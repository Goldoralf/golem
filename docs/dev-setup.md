# Developing golem without a rack

> **Status: GUIDE** — for anyone (human or agent) working on a laptop with no sound card set up for golem, no
> REAPER and no foot controller. It describes what the repository does today; the house rules themselves live in
> [`CLAUDE.md`](../CLAUDE.md) and [`CONTRIBUTING.md`](../CONTRIBUTING.md). If this page and the code disagree,
> the code is right and this page needs fixing.

The repository has four layers, and only one of them needs the rig to run:

| Layer | Where | Runs without a rack? |
|---|---|---|
| Bridge (Python, FastAPI) | `bridge/` | **Yes** — it starts, serves the app and the API, and waits for REAPER |
| App (Preact + htm, **no build**) | `app/` | **Yes** — served by the bridge |
| REAPER scripts (Lua) | `reaper/Scripts/` | Syntax-checked only (`tools/check-syntax.py`, `tools/check-vst-host.lua`) |
| JSFX (EEL2) | `reaper/Effects/` | No — they run in REAPER's audio thread |

## 1. Prerequisites

- **Linux, Ubuntu 24.04** is the reference (that is what CI and the rack run). Windows and macOS have a desktop
  path (`provision/desktop.py`, workflow `desktop-tests.yml`) but this guide assumes Linux.
- **Python 3.12** with `python3-venv` (`ruff.toml` targets py312, CI pins 3.12).
- **Node.js** for the app tests and the JS syntax check — CI uses Node 24 (`node --test`).
- **ffmpeg** and **libasound2-dev** — CI installs both before the Python tests
  (`sudo apt install ffmpeg libasound2-dev`).
- **google-chrome** (or Chromium) to look at the UI — see §6. Playwright is optional.
- **REAPER: optional.** Without it you get the full app and API but no sound and no rig. `./provision/install.sh
  --light` installs everything (system, REAPER, plugins, bridge) *without* the ~1 GB of amp captures and piano
  samples; it uses `sudo` and tunes the system for real-time audio, so it is for a machine you want to turn into a
  golem, not for a quick look at the code.

## 2. Get it running without hardware

```bash
git clone <repo> golem && cd golem
./provision/bridge-setup.sh                 # .venv + bridge/requirements.lock, hashes verified (--require-hashes)
.venv/bin/pip install --require-hashes -r requirements-dev.lock   # + pytest, httpx, ruff, lupa, playwright
```

`requirements-dev.txt` lists the tools; `requirements-dev.lock` is what CI installs, hashes verified, with the
bridge's versions as constraints. After changing either file, regenerate it:
`uv pip compile --universal --generate-hashes --python-version 3.12 requirements-dev.txt -c bridge/requirements.lock -o requirements-dev.lock`.

Run the bridge in the foreground, bound to localhost:

```bash
.venv/bin/uvicorn bridge.app:app --host 127.0.0.1 --port 8770
```

A second bridge on a machine where a rack runs (another port, a worktree) must start with **`GOLEM_NO_HW_MIDI=1`**:
without it, it opens the same MIDI ports as the rack, sends the foot controller its bank and LED state, and the
controller's echo reaches the live bridge as stomp presses (2026-10-31).

The scripted launchers bind to **0.0.0.0** (reachable from the LAN): `./provision/serve-rig.sh` runs uvicorn in the
foreground; `./provision/start.sh` runs it in the background (log in `/tmp/golem-bridge.log`) **and also launches
REAPER** if it finds one at `$REAPER_BIN` (default `~/opt/REAPER/reaper`). The `golem` launcher
(`provision/golem`: `golem desktop`, `golem phone`, `golem ui`…) calls `start.sh` too.

Open **`http://localhost:8770/app/`**. Localhost always passes authentication; any other device has to be paired
first (`/app/unpaired.html`).

**What you will see**

- At startup the bridge **seeds the factory content** (`bridge/factory.py` → `library/patches/`, `presets/`,
  `setlists/`, `library/standards/golem/`…): never overwriting, never bringing back what a user deleted. You can do
  the same without the bridge — CI does it before the tests:
  `.venv/bin/python -c "from bridge import factory; factory.seed()"`.
- `/app/` lands on **Live**, which shows the **loading screen** (`app/page-loading.js`) while it waits for REAPER.
  Without REAPER that step goes "late" ("REAPER has not started after N s") and an **"Open the app anyway →"** button
  appears. Other pages are reachable directly by hash: `#/designer`, `#/songs`, `#/library`, `#/system`
  (sub-tabs as `#/system/sound`). `?boot=demo` shows the loading screen with fake data (`&at=40`: the late case,
  with the golem.fm, TONE3000 and REAPER-licence rows in warning style).
- Designer, Songs, Library, Settings, the catalogs, presets and setlists all work: they are files plus the bridge.
- The Companion (musician's phone view) is `/app/m.html`; the shells are `/app/device.html` (tablet frame, exactly
  1024×600) and `/app/device.html?d=phone` (390×844, with a Who selector and the conductor switch).
  `/app/?shell=ro` is the read-only screen used by golem.fm ([`docs/shell.md`](shell.md)).

**What you won't see**

- No sound, no meters, no tuner, no scene switching that does anything audible. `reaper_running` and
  `reaper_connected` stay false (`bridge/monitors.py`), Settings ▸ Engine and System say so.
- Commands still get written: a recall writes `presets/.command.json` for REAPER's `golem_watch` loop, which nobody
  reads. Expect ACK timeouts in the log, not crashes.
- No MIDI devices, no foot controller, no sound card in the Soundcard page — the pages show their empty states.

## 3. The edit loop

| You changed | Do this | Why |
|---|---|---|
| `bridge/*.py` | `./provision/reload.sh` (or Ctrl-C and rerun uvicorn) | uvicorn runs **without** `--reload`: otherwise you are testing the old code. `reload.sh` kills every `uvicorn bridge.app` and re-execs `start.sh` — so it binds 0.0.0.0 and **starts REAPER if one is installed and not running**. On a rig, follow it with `curl -X POST localhost:8770/api/system/osc-refresh` if the REAPER link drops |
| `app/*.js`, `app/*.css`, `app/*.html` | Refresh the browser | No build. `/app` is served `Cache-Control: no-cache`. The **`golem desktop` window never reloads by itself**: it shows a "⟳ New version installed — tap to reload" banner when `GET /api/app-build` changes (polled every 20 s). Until you tap it, you test the old code |
| `reaper/Scripts/golem_apply.lua`, `golem_rig.lua` | Nothing | `golem_watch` re-`dofile`s them on every command |
| A `defer` loop (`golem_click`, `golem_looper`, `golem_midi`, `golem_watch`…) | `python3 reaper/golem-cmd.py '{"action":"reload","script":"golem_midi"}'` | Hot swap. Only scripts in the **whitelist** of the `reload` action in `golem_apply.lua` are accepted (`golem_perfrec`, `golem_click`, `golem_backing`, `golem_looper`, `golem_tuner`, `golem_sample`, `golem_drums`, `golem_clock`, `golem_knobs`, `golem_preview`, `golem_watch`, `golem_midi`, `golem_chordseq`, `golem_drumlearn`). Anything else — `__startup.lua` included — needs a REAPER restart |
| `reaper/Effects/*.jsfx` | Re-instantiate the FX: rebuild the rig (recall the preset) or reload the project (`POST /api/projreload`) | REAPER compiles a JSFX when an instance is created. Read the JSFX traps in `CLAUDE.md` first (code before the first `@` section never runs; EEL2 is case-insensitive) |

Without REAPER, the Lua and JSFX rows reduce to "run `tools/check-syntax.py` and the tests" — say so in your
report: the code has not run.

## 4. Checks before a commit

### What CI runs (`.github/workflows/ci.yml`, every push and pull request, Ubuntu 24.04, Python 3.12, Node 24)

Run them in the same order with the venv:

```bash
.venv/bin/ruff check .                                   # 1. static analysis — narrow on purpose: E9, F63, F7, F82
.venv/bin/python tools/check-syntax.py                   # 2. JS modules (node --check) + Lua scripts (lupa or luac)
node --test app/*.test.mjs                               # 3. app tests
.venv/bin/python -c "from bridge import factory; factory.seed()"   # 4. factory content — some tests assume it
.venv/bin/python -m pytest -q tests                      # 5. Python tests (tests/conftest.py blocks golem.fm,
                                                         #    real USB devices, the real songs/ folder…)
```

Then `git status`: the suite must not leave tracked files modified. `tools/check-vst-host.lua` runs inside step 5
(`tests/test_vst_host.py`), and so does the **engine itself**: `tests/test_rig_lua.py` runs the real
`golem_rig.lua` under lupa against `tests/fakereaper.lua`, a fake REAPER API that keeps tracks, FX, sends, `P_EXT`
and chunks and reproduces the documented traps — materialization, scene switch, stomp and plugin resolution
are checked in two seconds on a plan compiled by the real compiler ([`quality-automation.md`](quality-automation.md)
§4). When you change the engine, run it first; when the fake lacks a function the engine now calls, the test
says which. `tests/test_contracts.py` holds the seams: the command vocabulary bridge ↔ REAPER, the catalogue
against `blocks-doctrine.md`, every factory patch compiled for every scene, random presets against the compiler's
invariants — rename a field on one side and it fails there first.

`desktop-tests.yml` runs **every night** (02:17 UTC, skipped when `main` has not moved in 25 hours) and on demand
(Actions ▸ Run workflow): pytest on Linux/Windows, the desktop provisioning, `tools/check-desktop-bridge.py`,
and a real NAM render in a portable REAPER (`tools/check-native-nam.py`) on Windows. **macOS joins only on a manual
run** — its minutes cost ten times Linux's on this private repository. Run it by hand before a release.

`rack-selftest.yml` runs every night at 03:45 UTC on a **self-hosted runner on the Windows dev box** (label `rack`,
free minutes): first `tools/rack-free.py` — the reamp's "free" rule, ten minutes without a gesture, nothing playing
or recording — then the Python suite on the real machine, `check-ui.py` against the live bridge and
`check-rig-materialize.py --all --render` in an isolated REAPER. Nothing in it makes sound or touches the live rig.

The repository is private on a free GitHub plan: there is **no branch protection**, nothing refuses a red push.
Two substitutes ([`quality-automation.md`](quality-automation.md), lot 1): `main-red-alert.yml` opens an issue
labelled `ci-red` when `CI` or `Desktop tests` fails on `main` and closes it on the next green run; and the
local hook `.githooks/pre-push` runs the three fast CI steps (ruff, syntax, node tests, ~30 s) before every
push — install it once with `git config core.hooksPath .githooks` (`GOLEM_PUSH_FULL=1` adds pytest,
`GOLEM_SKIP_HOOKS=1` bypasses once).

### `tools/check-cold.sh` — the "cold" battery, and how it differs

`./tools/check-cold.sh` runs, without stopping at the first failure: `pytest tests/`, `check-descriptors.py`,
`fcb/check-uno2.py`, `check-transcribe.py`, `check-standards.py`, `check-meter.py --skip-js`. It diverges from CI:

- It does **not** run ruff, `check-syntax.py`, the node tests, or the factory seed. Passing `check-cold.sh` does not
  mean CI will pass.
- It runs **checks CI does not** (descriptors, UnO2 compiler witness, transcription rules, standards engine, meter
  formula). Passing CI does not mean `check-cold.sh` passes.
- It calls `python3` and the tools' `#!/usr/bin/env python3` shebangs, i.e. **whatever `python3` is on your PATH**.
  Activate the venv first (`. .venv/bin/activate`) or the bridge imports fail.
- `check-standards.py` returns 1 when no standard is installed: run the factory seed (step 4) first.

So before a commit: **the five CI steps, then `check-cold.sh`** with the venv active. `CONTRIBUTING.md` requires
`check-cold.sh` to stay green and every commit to be signed off (`git commit -s`).

## 5. Probes in `tools/`

Classified from each tool's header and code. "Dangerous" means: makes sound, rebuilds the rig, can freeze or crash
REAPER, or writes real files/remote data. **On a rig, never run a dangerous tool while someone is playing**, and
never one you have not read. A probe must not start a take; the ones below that touch the rig restore its state
when they exit normally.

| Tool | Needs | Dangerous? |
|---|---|---|
| `check-syntax.py` | nothing (node, lupa) | no |
| `check-descriptors.py` | nothing (repo files) | no |
| `fcb/check-uno2.py` | nothing; reads `presets/.uno2-flashed.json` to tell if the chip matches the setlist | no — but `--update` rewrites the versioned witness: only after an intended compiler change |
| `check-transcribe.py` | nothing (`--audio W` needs the transcription venv) | no |
| `check-meter.py --skip-js` | nothing | no |
| `check-vst-host.lua` | nothing (`lua`, or via pytest) | no |
| `check-tab-vs-gp.py --self-test` | nothing | no |
| `check-desktop-bridge.py` | nothing — starts **its own** bridge on a free port with a temporary runtime dir | no — but that bridge boots on the repo tree like any bridge (factory seed). Linux: run it with `.venv/bin/python` |
| `check-ui.py` | the system Chrome (Playwright); starts **its own** bridge like the one above, or `--base` a live one | no — every write to `/api/` is intercepted. The disposable bridge reads the repo's `config/` (a paired rack sends its heartbeat for a minute): on a paired dev box prefer `--base`. Its bridge runs with `GOLEM_NO_HW_MIDI=1` (since 2026-10-31: before, it opened the rack's pedalboard and its LED sync toggled the live rack's stomps) |
| `check-use.py` | the system Chrome and a REAPER binary; starts **its own** bench like `check-rig-materialize.py` (worktree with factory content only, REAPER on dummy audio, bridge on free ports, `GOLEM_NO_HW_MIDI` and `GOLEM_BENCH_CARD` set) | no — writes are **real** but go to the bench, which is removed at the end; the machine's MIDI devices and sound cards are never touched. Journeys on the factory content, then `--monkey N` random gestures (`--seed`), then sound checkpoints; report in `assets/.cache/use-check/report.html` ([`quality-automation.md`](quality-automation.md) §9). ~1 min to boot, ~15–25 min for a full pass |
| `check-rig-materialize.py` | a REAPER binary (the launcher's, or `--reaper`); starts **its own** REAPER (own resource dir, dummy audio, own OSC ports) and **its own** bridge on a `git worktree` of HEAD | no — the live rack next to it sees nothing (separate `presets/`, command file, ports); local models are *copied* into the worktree. Recalls every factory patch (`--all`: yours too, `--fixture`: a built-ins-only bench patch) and checks rig-check, live map, plugins, a scene change; a bench card gives it one input of each audio role (guitar, bass, voice), so every bass and voice patch is materialized; `--chain N` then fires N series of recalls and scene changes without waiting (a scene in the middle of a rebuild) and checks that REAPER lives and that the last patch asked is the one in place, complete; `--working-tree` builds the worktree from uncommitted changes; `--render` replays a synthetic DI offline through each materialized lane and compares the fingerprint to `tests/golden/renders.json` (`--update-golden` to regenerate after an intended change); `--standard-take N` instead records N standard takes through the real path (arming, tap, take, `take.json`) and measures, on each take's `Mix.wav`, where the armed grid landed against where it should (budget 1 ms; it seeds one chart from the local corpus into the worktree). ~40 s to boot, ~5 s per patch, ~8 s per rendered scene |
| `check-alive.py --dry-run`, `check-routing.py --dry-run`, `check-params.py --dry-run` | local files only (parser self-tests) | no |
| `check-standards.py` | files: needs installed standards (factory seed) | no — `--rig` plays on the rack |
| `check-irs.py` | files: `assets/irs/**` | no |
| `check-tab-vs-gp.py <take>` | files: a take in `recordings/` + a Guitar Pro reference | no |
| `check-fingering.py` | files: the Guitar Pro corpus under `~/code/maestrium` (`GOLEMFM_CODE`), cached in `$TMPDIR` | no — `--tune` takes ~20 min of CPU |
| `check-core-parity.py` | `fixtures`/`compare`: files; `render-lv2`: a C compiler + the installed LV2 plugins; `render-native`: REAPER + NAM VST3 | no |
| `check-native-nam.py` | REAPER + NeuralAmpModeler VST3 installed, network (downloads a model) | launches **its own** REAPER instance (`-newinst`, own config in `--work-dir`) |
| `shell_snapshot.py` | bridge (GET only) | no — writes the snapshot to `--out` |
| `check-meter.py` (default) | bridge (the JS stage imports the served module in headless Chrome) | no |
| `check-report.py` | bridge | writes a diagnostics package, removed at the end unless `--keep`; never sent |
| `check-recall.py` | bridge (REAPER optional) | **yes — recalls real presets**: on a live rig the sound changes for ~10 s; restores preset and scene |
| `check-restore.py` | bridge + golem.fm vault (`--local` without) | **yes — writes real files and remote data**: creates/deletes a witness preset, builds backups, pushes and deletes in the vault; cleans both sides |
| `check-alive.py` | bridge + REAPER | no — reads liveness files and track chunks |
| `check-routing.py` | bridge + REAPER | no — reads chunks |
| `check-silence.py` | bridge + REAPER, you playing (`--no-wait` without) | no — read-only; writes `presets/.silence-*.json` (local state) |
| `check-params.py` | bridge + REAPER | **yes — audible**: sweeps every mapped knob min/mid/max; restores; refuses during a take |
| `check-jitter.py` | bridge + REAPER | **yes — makes noise** on the monitors unless `--silent` |
| `check-meter.py --rig` | bridge + REAPER | **yes — plays the click** |
| `check-foot.py` | bridge + REAPER (`--live`: the real foot controller) | **yes — rebuilds the rig**: injects foot messages, changes preset/scene/stomps (three rebuilds in < 3 s); restores. Skips Rec/backing switches |
| `check-recall-stress.sh` | bridge + REAPER | **yes — designed to crash REAPER** (N × `check-foot.py`), then restarts it |
| `check-block-stall.py` | bridge + REAPER | **yes — test tone, adds FX to a live track, can freeze the whole engine** (~0.5 s per stall); `--rig` toggles the loaded preset's blocks |
| `check-scene-gap.py` | bridge + REAPER (`--listen`: you + the foot controller, passive) | **yes — continuous test tone**, adds probe FX (`--off` removes them after an interrupted run) |
| `check-scene-click.py` | bridge + REAPER | **yes — test tone and a recorded take** (deleted unless `--keep`) |
| `check-reamp-align.py` | bridge + REAPER | **yes — takes the live engine** for a few seconds |
| `bench-lanes.py` | bridge + REAPER | **yes — rebuilds the rig** with N NAM lanes to load the CPU |
| `bench-liveconfigs.py` | bridge + REAPER + SWS | **yes — continuous sound, REAPER restarts at the end** |
| `check-scene-latency.py` | the real foot controller (`aseqdump`) while you play | no — passive observer, sends nothing |
| `check-drums.py` | a drum module and you hitting it (bridge + REAPER if REAPER holds the port) | read-only, except **`--write` rewrites the device descriptor** (keeps a `.bak`) |
| `fcb/flash_uno2.py` | the FCB1010 with its UnO2 chip | **yes — `--write` replaces the whole chip content**; `--identify` and `--dry-run` are safe |

Other tools worth knowing: `reaper/golem-cmd.py` (send a raw command to REAPER's watcher, §3),
`tools/seed-standards.py` (install a few standards from the upstream dataset; network),
`tools/local-state.py pull` (a `git pull` that keeps the rack's local state), `tools/shoot.sh` (screenshot a
mockup), `tools/follow-push.py` (simulate the rack's follow frames to golem.fm, no REAPER).

## 6. Looking at the UI like a user

The app is designed for a **1024×600 touch panel with no scrolling**. A maximised browser on a large screen shows
neither overflow nor what a musician sees on a phone. Nothing compiles, so nothing warns you: look at the pixels and
read the console.

**The machine does the first pass**: `python tools/check-ui.py` boots a disposable bridge on a fresh worktree of
HEAD (factory content; `--test-content` adds the pack of `library/test-content/`, made for the tests — see
[`quality-automation.md`](quality-automation.md) §8), opens every page of the rack at 1024×600 and the Companion at
390×844 in the system Chrome (Playwright, nothing downloaded), and fails on a console error, a scrolling page, a
French label, the brand spelt "GoleM", or a control that disappeared from `tests/ui/inventory-<platform>.json`
(a new one is reported; `--update-inventory` adopts it). The inventory is taken with `--test-content`, as CI runs
it: without the pack the probe says so and does not compare it. `--press declared` presses the controls whose effect
`tests/ui/expectations.json` states (landing hash, opening, API calls) — the per-push check; `--press all` presses
every control and compares its effect with `tests/ui/effects-<platform>.json` (the nightly rack run, ~20 min;
`--update-effects` after an intended change). Every write to `/api/` is intercepted, so it changes
nothing — `--base http://localhost:8770` runs it against a live bridge (with `--test-content` the pack is installed
there by ledger and removed afterwards), `--only designer` narrows it, screenshots land in `assets/.cache/ui-check/`.
CI runs it on every push (job **Rendered app**, screenshots and inventory as an artifact). It does not see what
scrolls *inside* a panel, nor what a page looks like: for that, keep reading.

Quick screenshot at panel size (dedicated profile, so `--window-size` is honoured even if Chrome is already open):

```bash
google-chrome --headless=new --disable-gpu --hide-scrollbars --user-data-dir=/tmp/golem-shot \
  --window-size=1024,600 --screenshot=/tmp/designer.png 'http://localhost:8770/app/#/designer'
```

For anything interactive, use Playwright with the system Chrome (no browser download), and **intercept every
write**: the app autosaves (setlist rows, the Designer sandbox, window geometry…), so exploring by clicking can
overwrite real presets.

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    page = b.new_page(viewport={"width": 1024, "height": 600})
    writes = []
    def guard(route):
        if route.request.method in ("POST", "PUT", "DELETE", "PATCH"):
            writes.append(route.request.method + " " + route.request.url)
            return route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
        return route.continue_()
    page.route("**/api/**", guard)
    page.on("console", lambda m: print("console:", m.type, m.text))
    page.on("pageerror", lambda e: print("pageerror:", e))
    page.goto("http://localhost:8770/app/#/designer")
    page.wait_for_timeout(1500)
    page.screenshot(path="/tmp/designer.png")
    print("scrolls:", page.evaluate("document.documentElement.scrollHeight > innerHeight"))
    print("blocked writes:", writes)
    b.close()
```

Checks while you are there: no horizontal or vertical scroll; every visible label is **English**; the brand reads
`golem` or `/golem_`, never "GoleM"; a control that must not be used is **not rendered** rather than hidden with
`hidden` (a stylesheet rule can show it again). For the phone view, use `viewport={"width": 390, "height": 844}`
on `/app/m.html`, or `/app/device.html?d=phone`. If you did let writes through, restore what you changed and say so.

## 7. What never to commit

The repository versions **recipes and seeds**, not what happens on a machine. The bridge, REAPER and the user
rewrite these files while golem runs; they are ignored for that reason (`.gitignore`, sections "ÉTAT LOCAL DU RACK"
and "LA BIBLIOTHÈQUE N'EST PAS DANS LE DÉPÔT"):

| Path | Written by |
|---|---|
| `presets/*.json`, `presets/.*` | the user playing; the bridge (`.sandbox.json`, `.command.json`, logs, probes) |
| `sets/*.rpp` | REAPER, which rewrites the project while it runs |
| `mappings/*` | the user's controller calibrations and checks |
| `config/click.json`, `compo.json`, `recorder.json`, `io.json`, `config/cards/`, `config/inputmaps/` | the bridge (defaults live in the code); listed in `bridge/local_state.py` |
| `setlists/*.json` | the user (factory setlists live in `library/factory/setlists/`) |
| `library/patches/`, `library/tones/*.json`, `library/kits/`, `library/standards/`… | the user's library, and the factory seed's copies |
| `recordings/`, `songs/`, `backups/`, `.env` | takes, songs, backups, machine secrets |

Factory content is versioned **in `library/factory/`** and seeded from there; `library/block-presets/` and
`library/pedals/` are versioned seeds too — a user preset saved there shows up untracked: leave it. Two `.gitignore`
traps: a pattern cannot carry an end-of-line comment, and a directory that is excluded cannot be re-included (exclude
its *contents*, then re-open the subfolder). If a decision changes what counts as local state, it goes in a
`docs/*.md` contract, not only in `.gitignore`.
