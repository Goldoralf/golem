# Quality automation: seven lots to catch regressions before a human does

> **Status: PROPOSED — lot 1 PARTLY CODED (2026-10-19).** The plan to move golem's quality assurance from
> "a musician tries everything after each update" to "machines catch regressions, humans judge the sound".
> Constraints that shape it: the repository is **private on a free GitHub plan** — no branch protection, no
> required checks, and a monthly budget of Actions minutes where Windows counts double and macOS ten times.
> Each lot says what exists, what gets built, and how we know it is done. Statuses are updated here, per lot.

Related: [`dev-setup.md`](dev-setup.md) (the checks and the probes), [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
(what a contributor runs), [`pitfalls/README.md`](pitfalls/README.md) (what the Lua tests of lot 4 must cover),
[`capture-module.md`](capture-module.md) §"Checks" (the first REAPER-in-isolation checks, a model for lot 3).

---

## 0. Where we start (2026-10-19)

| Layer | Size | Automated coverage today |
|---|---|---|
| Bridge (Python) | 3.3 MB | good, unit level: 261 test files, ~2 300 tests; few end-to-end API tests |
| App (JS, Preact + htm, no build) | 1.9 MB | syntax (`node --check`) + 15 logic test files; **no rendering test** in CI |
| REAPER side (Lua) | 690 KB | syntax only (lupa/luac); two test files load Lua through lupa |
| Audio and timing | — | 32 probes in `tools/`, run by hand on a rack when nobody plays |
| Windows / macOS | — | `desktop-tests.yml`: three OS + a real REAPER rendering NAM — **manual only, never run** |

What GitHub Actions does: `ci.yml` on every push and pull request (Ubuntu, 4–7 min): ruff, JS/Lua syntax, node
tests, factory seed, pytest. The last twelve runs on `main` are green. What it cannot do on this plan: refuse a
merge. A red pull request can be merged; a red push to `main` is only a red badge.

Three regressions of 2026-10-19 show the gaps: a registry walk on the hot path made two pages take minutes
(no time budget is measured anywhere); the capture player was installed in a CLAP folder REAPER does not scan
(no test asserts the scan path per OS); REAPER died of a Windows paging error on a plugin file (not a code bug —
but nothing relaunches REAPER on Windows, and the bridge logged nothing).

## 1. A green base everywhere, every night — PARTLY CODED

**Goal.** Red means a regression, nowhere else. The three-OS run happens without anyone asking.

**Built (2026-10-19).**
- `desktop-tests.yml` runs **every night** (02:17 UTC) and on demand. A preflight job skips the night when
  `main` has not moved in 25 hours (no minutes burnt for nothing). The nightly matrix is **Linux + Windows**;
  macOS joins only on a manual run (ten-times minutes). REAPER and NAM downloads are cached between runs.
- `main-red-alert.yml`: when `CI` or `Desktop tests` fails on `main`, an issue labelled `ci-red` is opened
  (or commented if one is open); the next green run on the same workflow closes it. On a plan without
  branch protection, this is the alarm that replaces the lock.
- `.githooks/pre-push`: the fast CI steps (ruff, JS/Lua syntax, node tests, ~30 s) before every push; opt-in
  with `git config core.hooksPath .githooks`. `GOLEM_PUSH_FULL=1` adds pytest; `GOLEM_SKIP_HOOKS=1` bypasses
  once. It is the local substitute for a required check.

**Built (2026-10-19, evening).** The Windows pytest baseline on the dev box went from 66 failures + 44 errors
to zero, sorted into three piles. *Code wrong on Windows* (fixed): `os.path.relpath` against the repository
raised on another drive (songs or caches on `D:` vs `C:`) — now `config.rel()`; `machine.can_show` served a
stale cache because `time.monotonic()` ticks every ~15 ms; `reaper_license.resource_dir` joined Linux/macOS
paths with `\`; the shell snapshot treated the word "host" of a `host.docker.internal` FQDN as a hostname and
rendered repository-relative paths with `\`. *Test wrong on Windows* (made portable): separator assertions,
pytest param ids over 32 KB (Windows refuses the env var), zipfile normalising `\` on write, the real shell
folders leaking into the fake Windows profile, `expanduser` reading `USERPROFILE`. *POSIX-only features*
(skipped with a reason): sudo, apt, bash libraries, symlinks without privilege, mode bits. One real incident:
the Linux receipt tests, run on Windows, resolved `%LOCALAPPDATA%\GoleM` and wrote **40 test entries into the
machine's real install receipt** — set aside as `install-receipt.json.test-pollution-20261019`, and the fixture
now skips on Windows. Still to do: the first nightly run on a **clean** `windows-2025` runner (workspace on
`D:`, temp on `C:` — the same cross-drive layout) gives the list that matters there. Done when the Windows
job is green three nights in a row.
- Fold the "cold" battery (`tools/check-cold.sh`: descriptors, UnO2 witness, transcription rules, standards,
  meter formula) into `ci.yml`, so that CI and the pre-commit ritual check the same things.
- Split `ci.yml` into parallel jobs (static, node, pytest) so the first verdict arrives in a minute.

**Budget.** Free plan: 2 000 minutes/month, Linux ×1, Windows ×2, macOS ×10. Today's CI: ~6 pushes/day × 5 min
≈ 900/month. Nightly Windows (pytest ~8 min + NAM render ~8 min, ×2) ≈ 1 000/month. That fits, barely, and it
is the reason macOS is manual and the night is skipped when nothing changed. The way out of the budget is
**lot 5**: a self-hosted runner costs no minutes at all, and can carry the Windows night.

## 2. The app rendered, in CI — PARTLY CODED

**Goal.** No page ships that scrolls, throws in the console, shows French, or lost a control.

**Built (2026-10-19).** `tools/check-ui.py`: a disposable bridge (temporary runtime, REAPER dir and OSC ports,
free HTTP port), the system Chrome through Playwright (nothing downloaded), **32 rack pages at 1024×600** (every
hub, tab and sub-tab of `ui-architecture.md` §1) and **3 Companion tabs at 390×844**. Per page: no page error,
no console error (the WebSocket of a bridge without REAPER is noise), no document scroll on the rack and no
horizontal scroll on the phone, no French line (three French function words, or one word of UI vocabulary — a
song title like *Pour que tu m'aimes encore* passes), brand spelt `golem` outside identifiers (folders,
REAPER plugin names), something interactive rendered (the `/loading` screen excepted). Every POST/PUT/DELETE
to `/api/` is intercepted and answered `{ok: true}`: the sweep changes nothing, even against a live bridge
(`--base`). Screenshots per page; JSON report. 75 s on the dev box. `ci.yml` job **Rendered app**, parallel
to the tests, screenshots uploaded as an artifact. First run found three real findings: brand spelt "GoleM"
in the Licenses ▸ Libraries prose (fixed in `provision/components.json`), the loading screen on `/live`
without an engine (expected), and a song title flagged as French (detector refined).

**To build.** Key flows with writes intercepted: open a block sheet in the Designer, switch a scene, select a
preset row, pair a phone. Panels that scroll *inside* the page (the Library grids): detect inner scroll regions
and report them, then decide per page what is paging and what is a bug. Reference screenshots with a
tolerance, compared in CI, once the pages are stable enough not to cry wolf. The phone sweep only sees the
tabs a local, unpaired browser gets (Now, Song, Rec): Mine and Lyrics need a paired device with lanes.

## 3. REAPER headless for the engine — PARTLY CODED (3a built)

**Goal.** A patch that no longer materializes, or no longer sounds the same, fails a job.

**Built (2026-10-19) — 3a, materialization.** `tools/check-rig-materialize.py`. Everything disposable: a
`git worktree` of HEAD as the repository (own `presets/`, own command file — a rack running next to it sees
nothing; local models, IRs and user patches are *copied* in), a REAPER with its own resource dir provisioned by
the launcher's own code (`copy_resources`, `configure_ini` with dummy audio, OSC ports of this run), a bridge on
free ports with mDNS off. Then, patch by patch: block status first (a block that is `download` or
`unavailable` on this machine makes the patch **skipped, with the reason** — the probe judges the engine, not
the inventory), recall, wait for a `.rig-check.json` strictly newer than the previous one and a `.livemap.json`
in the patch's name, then assert: no `rig_error`, rig-check ok with no issue, every block of the patch present
on the live map, every block type's plugin found (`.rig-plugins.json`), and a scene change lands. `--fixture`
adds a bench patch built only from REAPER built-ins and JSFX (gate, boost, EQ, phaser, comp, chorus, delay,
killswitch; two branches, three scenes), so a runner without a single model still exercises the engine. On the
dev box: REAPER answers in ~40 s thanks to a warm start (the machine's plugin inventory and licence are copied;
`--cold` for a clean runner), then ~5 s per patch; 7 materialized, 0 failed, 32 skipped (TONE3000 downloads,
Linux-only plugins, A2 captures the Windows NAM cannot play). Wired into the nightly Windows job of
`desktop-tests.yml` after the NAM render, logs and report as an artifact; `workflow_dispatch` gained a
**macos** checkbox so a manual run no longer pays macOS by default.

**Built (2026-10-19, evening) — 3b, golden renders.** `--render` on the same probe. A **synthetic DI** (a
plucked 110 Hz note with harmonics, a 80 Hz → 5 kHz glide, a short noise burst, silence for the tails; 4 s,
48 kHz, generated deterministically — nothing to ship, no rights) is replayed **offline** through the lane
the engine just materialized, by `golem_preview.lua`'s render op — the reamp path: a disposable clone of the
whole lane tree, no hardware output, nothing audible. Each render is reduced to a **fingerprint**: RMS
envelope per 100 ms, spectral balance in eight bands, peak and RMS level, length. References live in
`tests/golden/renders.json`, keyed by patch and scene and stamped with a signature of the patch's lanes,
scenes and config: a changed patch makes its reference *stale* (reported, not failed — regenerate with
`--update-golden`); an unchanged patch whose sound moved beyond the tolerances (2 dB envelope, 3 dB per band)
**fails**. Proved both ways on the dev box: two consecutive runs match; a reference shifted by 6 dB turns the
patch red with the figure. The nightly Windows job renders the fixture patch's scenes A and B against the
committed references, so the first cross-machine comparison (REAPER 7.80 portable vs 7.2.7 here) happens
tonight.

**Linux pass (pending — everything above was built and verified on Windows).** On the rack, after a pull:
`check-ui.py --base http://localhost:8770`; `check-rig-materialize.py --fixture --only ci-engine --render`
(never run on Linux: the REAPER binary fallback, `[audioconfig] mode=4` as dummy audio, stock JSFX copied from
`~/.config/REAPER/Effects`, a display or `xvfb-run -a`, `GOLEM_RUNTIME_DIR` honoured instead of `/dev/shm`);
then `--all --render` — the factory patches have their models there, so that is where their references get
generated (`--update-golden`). The fixture's references must **match** across OS, or the tolerances are wrong.

**To build.** The per-push Linux variant: REAPER Linux under Xvfb on the Ubuntu runner, the same probe, factory
patches reachable once a NAM LV2 build is cached — until then the fixture patch. References for the factory
patches, generated on a machine that has their models (the rack), once the first nightly says the fixture's
references hold across machines. (c) *Stall census*: `check-block-stall.py` over the free plugins of the
catalogue, result written **as data** into `effects.json` quarantine. `--fetch` exists (the bridge downloads
what a patch needs) but TONE3000 needs the rack's key: not for CI. Licensed commercial plugins never run in
CI. Done when a factory patch with a deliberately broken IR path turns the job red.

## 4. Lua tested for real — PARTLY CODED

**Goal.** `golem_rig.lua` (240 KB, the engine) has unit tests that run in a second, without REAPER.

**Built (2026-10-19, night).** `tests/fakereaper.lua`: a fake `reaper` API (61 functions the engine calls)
that keeps the bookkeeping REAPER exposes — tracks in project order and their values, FX chains (name, enabled,
parameters, named config, GUID), sends with their flags, `P_EXT` memory, chunks, gmem, ExtState, defers — and
reproduces the documented traps: `SetTrackStateChunk` **erases** `P_EXT`, a new send lets MIDI through
(`I_MIDIFLAGS` 0), a plugin missing from the inventory returns −1, `CreateTrackSend` returns the index. The
inventory is the catalogue's built-ins and JSFX (REAPER's and golem's, resolved by path like the real thing),
never a third-party VST or LV2. `tests/test_rig_lua.py` runs the **real, unmodified** engine script under lupa
against it, on a plan compiled by the **real** bridge compiler (`scene_bake` + `compile_rig`) from the bench
patch of lot 3, on both simulated systems (Linux, Windows via `effects-windows.json`). Ten tests, 19 cases,
2 s: every block posed and on the live map, the lane root armed in monitoring, every internal send with
`I_MIDIFLAGS` 31, `P_EXT` memory on every track with FX, scene switch and stomp **without** any
`TrackFX_AddByName`/`Delete`/`DeleteTrack`, branch mutes following the scene, a scene on an empty project
falling back to a rebuild, an identical recall reusing every track (FX signature), a missing plugin reported
in `.rig-plugins.json` while the rest of the chain is built. The first run found nothing wrong with the engine
and three gaps in the fake (track numbers, JSFX paths, parameter names).

**To build.** The heal-after-rebuild path and the chunk surgery (NAM/IR file loading, `P_EXT` rewritten
*after* the chunk — the fake erases it, the test needs a plan with a model and an IR); the SETTLE window and
the command slot (that is `golem_watch.lua`, not yet loaded under the fake); service tracks armed with
`I_RECMODE` 2 (click, drums, looper live in their own loops); bipolar JSFX sliders written raw (the fake needs
the real slider ranges, parsed from the `.jsfx` files); the mono fallback; a Keys lane (knob-tap, note-zone).
Done when every REAPER pitfall listed has a failing-then-passing test.

## 5. The rack tests itself — PARTLY CODED

**Goal.** What only a real rack can measure is measured every night, by the rack, when nobody plays.

**Built (2026-10-19, night).** A **self-hosted GitHub runner** on the Windows dev box (`studiopc`, labels
`self-hosted, Windows, rack`), installed in the user's profile (`%USERPROFILE%\actions-runner`, runner 2.338.0,
archive hash checked against the release), started by a Startup entry in the **interactive session** — REAPER
needs a desktop, a Windows service in session 0 has none — so it runs as the user, not as a service. Free
minutes: this is also the way out of lot 1's budget. `rack-selftest.yml` runs every night at 03:45 UTC and on
demand, on that runner only (`runs-on: [self-hosted, rack]`, one at a time). **First step, the guard**:
`tools/rack-free.py` reads the live bridge and applies the reamp's "free" rule (`reamp.md` §2) — no Gig mode or
lock, no take or count-in, no song or arrangement playing, no rig loading, and nobody has touched the rack
(screen, foot, signal) for ten minutes; otherwise the night ends there with a notice, not a failure. Then,
only probes that leave the live rack alone: the full Python suite on the real Windows box, every page rendered
against the live bridge with writes intercepted, every patch of the machine materialized and rendered in an
isolated REAPER — the runner works in its own clone, so `GOLEM_RACK_ROOT` (set by the runner's Startup entry) names
the machine's golem, whose models, IRs, captures and patches the probe copies (`--content-from`). Reports as
artifacts. First night, by hand: 14 min 34 s, all green.

**To build.** The probes that make sound, once a loopback cable joins an output to an input: `check-silence`,
`check-scene-gap` (sample-accurate), `check-meter --rig`, level per patch — each restoring preset, scene and
files on exit, each still behind the guard. A virtual MIDI port standing in for the pedalboard (`check-foot`
replays the chip). The same runner on the Linux rack when there is one (same workflow, label `rack`). Results
into the diagnostics packets. Done when a night's report lands with no human action and a deliberate 60 ms
scene gap turns it red.

## 6. Contracts between layers — PARTLY CODED

**Goal.** The seams (bridge ↔ Lua, bridge ↔ app, data ↔ code) are tested as contracts, not by luck.

**Built (2026-10-19, night).** `tests/test_contracts.py`, 70 cases in 8 s:
- **Command vocabulary.** Every `action` the bridge writes into `.command.json` is a word some REAPER script
  knows; every action `golem_rig.lua` handles is routed to it by `golem_watch.lua`, by name or through the
  `_route` the bridge attaches. A new action on one side without the other fails here.
- **Catalogue against its doctrine** (`blocks-doctrine.md` §2): closed vocabularies for `category`, `engine`,
  `map`, param `type`, `foot_mode`; unique types and param ids; defaults inside their range; enums with options;
  `conflicts`, `role_categories`, `role_blocks` pointing at things that exist; the Windows and macOS overlays
  only naming existing block types and params.
- **Factory content compiles.** Each of the 40 factory patches and presets, for each of its scenes, through the
  real path (`ensure_volume` → `scene_bake` → `compile_rig`); the plan's invariants: unique track names, sends
  and folder parents that exist, no block the preset does not declare, no block posed twice, every lane either
  posed or listed as unmounted with its reason.
- **The live map the engine writes is the one the bridge reads.** `.livemap.json` and `.rig-plugins.json`
  produced by the real engine under the fake REAPER (lot 4), schema-checked, then fed to `recall.rig_is_live`.
- **Random presets.** 24 seeded presets (one or two lanes, pre/split/post, merge or fan-out, one to three scenes
  with random block cuts and branch mutes) compile with the invariants above, plus: a block the scene cuts is
  `bypass` in that scene's plan, a fan-out lane has no post block, an unmounted lane leaves nothing behind. The
  first run documented two rules rather than bugs: one lane per input (`_one_lane_per_input`, said in
  `unmounted`) and "no post after a fan-out".

**To build.** Schemas for the remaining telemetry files (`.rig-check.json`, `.clock.json`, `.click.json`,
`.midi.json`…) produced by the service loops, once those loops run under the fake (lot 4); the ack protocol of
the command slot (`golem_watch.lua`); the app ↔ bridge seam (the JSON the pages consume, against the routes'
responses — the disposable bridge of lot 2 is the place); `preset-format.md` as a schema. Done when a field
renamed on one side only fails a test on the other.

## 7. What stays human — REFERENCE

Tone, the feel of latency while playing, touch ergonomics on stage, new hardware. With lots 1–6 running, the
human test becomes an **exploratory session on a release candidate**, guided by a short list of what the
machines do not cover — not a replay of every function after every update.

## 8. Test content and the buttons — PARTLY CODED

**Goal.** Every control of every page is tested against a **known terrain**: content made for the tests, that
exercises everything the factory content leaves out, installed for a run and gone afterwards, never mixed with
the musician's own.

**What the factory content covers, and does not (inventory of 2026-10-20).** 32 patches (guitar 10, bass 6,
keys 6, voice 5, drums 4, keys-pads 1; four or five scenes each; 15 merge splits, **no fan-out**; drums and
standard service blocks; 11 MIDI lanes), 8 presets (five lanes each; rec, click, compo, arrangement; colours and
animations), 6 setlists (five of sounds, one of songs whose lines carry a preset, a title and a BPM — **no song**),
3 standards (`.golem` with a chart), 13 grooves, one DX7 bank, 7 kits (4 drum kits, 3 pad kits whose 48 samples
are all present), a catalogue of 74 block types. **24 types appear in no factory document**: among them every
service block that is not drums or standard (`backing-track`, `looper`, `tuner`, `sample`), `capture-module`,
and the third-party or quarantined effects. Most factory patches need TONE3000 models (a runner has none) and
Linux plugins (Windows has not all of them): on a clean machine they skip.

**Built (2026-10-20).** `library/test-content/`, generated by `tools/make-test-content.py` (edit the generator,
not the files): five patches (`test-guitar-bench` merge split, three scenes, foot 6–9, colours and animations;
`test-bass-fanout` **fan-out**, drive and flanger JSFX, branch mutes; `test-voice-plain` de-esser and pitch
JSFX; `test-keys-pads` the **pads block on the factory kit** `pads-house` = the 16 factory samples;
`test-drums-kit` the factory drum kit and two factory grooves), two presets (`test-band-session`: guitar +
voice, **backing-track, drums, looper, tuner, rec, click, compo, arrangement with four sections**;
`test-standard-trio`: the **standard** block on the test standard — standard conflicts with backing-track and
drums, hence two presets), two setlists (sounds, with a patch shared by two lines; songs, whose first line
carries the test song), a song (built at install: lyrics, chart, a synthetic original and **two stems**, 4 s)
and a standard (a 12-bar chart). Every block is a REAPER built-in or a JSFX: it materializes on any machine.
`bridge/test_content.py` installs and removes it by a **ledger** (`presets/.test-content.json`): a file that
already existed is kept and said, removal deletes only what the ledger lists. `tests/test_test_content.py`
(19 cases) holds the pack to that: round trip without a trace, every document compiled for every scene by the
real compiler, every referenced kit, sample, groove and standard present.

`tools/check-ui.py` now boots its disposable bridge on a **fresh worktree of HEAD** with the factory content
and, with `--test-content`, the pack — the same surface on the dev box and on the runner — and keeps an
**inventory of the controls** of each rack page (tag, role, accessible name, digits normalized), one file per
OS in `tests/ui/`: a control that disappears fails the probe, a new one is reported and enters the contract with
`--update-inventory`. 719 controls on Windows. CI runs it with the pack on every push; the Linux inventory is
written by the first run and committed from its artifact.

**Built (2026-10-20, later) — the expectations per control.** `check-ui.py --press` presses the controls of
each rack page one by one (a fresh document after any press that had an effect, Escape otherwise) and records
the effect in four families: where the app **lands** (hash), whether something **opens** (dialog, drawer, sheet,
menu), which **API calls** it makes (method and path, intercepted and answered `ok`, never executed), **page
errors**. Two files in `tests/ui/`: `effects-<platform>.json`, the observed effect of every control, written by
`--press all --update-effects` (about 20 minutes: the nightly rack run does it, and a changed effect fails it);
`expectations.json`, written by hand for the controls that matter — `navigates_to`, `navigates`, `opens`,
`api` (exact list), `writes_nothing` — checked by `--press declared` on every push in under two minutes. The
first declared pass held 50 expectations (hub links on three pages, every tab of Songs, Library and Settings,
scene A and Add on Presets) and found one fact rather than a bug: opening the API tab posts a services check.
The sweep also showed what the inventory already hinted: the patch and preset tiles were buttons **without an
accessible name** (their key was a soup of glyphs). They have one now (`aria-label`: « bloc · type » on a
Designer tile, « Play « patch » » and « Edit « patch » in the Designer » on the patch list, « Scene A — name »
and « Switch 6 — blocks » on a preset card): the inventory names 804 controls on Windows and the expectations
reach the tiles (playing a test patch posts `patches/test-guitar-bench/play`).

**Dangerous controls.** The sweep records two more families: a native `confirm()`/`alert()` (dismissed by the
probe, `confirms`) and the **two-step buttons** whose press makes a question appear somewhere on the page
(`asks`: « Stop golem — sure? », « sure? » on a setlist's bin, « change the foot? »). Expectations: `asks: true`
plus `writes_nothing`. The first pass found that **« ↻ restart » (REAPER) restarted on a single press**, no
question, where « ⏻ Stop golem » asks — fixed: restart of REAPER and of the bridge are now two-step like Stop.
It also found a probe bug worth recording: the mark left on a pressed element made the next press on the same
page hit the wrong button, so the first two sweeps had recorded false "no effect" entries; the mark is cleared
before each press, and the effects were regenerated. Things that depend on the engine's presence (scene recall,
the restart label, « Show on this computer ») are not in `expectations.json`: the nightly effects file against
the live rack holds them.

**To build, in this order.** The inventory only sees formal controls (`button`, `a`, `input`, roles): the
remaining tiles and rows that Preact makes clickable without a role need a data attribute or a pointer-cursor
heuristic; the setlist bin and duplicate buttons want names too (« 🗑 », « ⧉ »). Then the **flows** on the test
content: load the test setlist, its second line,
scene B, open a block sheet in the Designer, assign a switch, see the tile on Live; `check-rig-materialize --all`
already materializes and renders the pack. Then the **phone** with a fake paired device on the disposable bridge
(Mine, Lyrics). Then the nightly variant against the live rack behind the guard. Gestures (long press to assign,
drag to reorder) one by one. Done when a changed button fails at push with the page, the name and the screenshot.

## 9. golem in use, like a tester — CODED (2026-10-27)

`tools/check-use.py` drives the **real app** the way a person would, writes included, on a disposable bench — never
the rack of the machine. Where lot 8 presses every button with writes intercepted, this one *uses* golem: it recalls,
records, duplicates and deletes, changes mode and comes back, and listens to what comes out.

**The bench** (`Bench` in the tool): the one of `check-rig-materialize.py` — a `git worktree` (factory content only:
the machine's presets and patches are not copied, so a pass replays the same way elsewhere; the local models and IRs
are), a REAPER with its own resources and dummy audio, a bridge on free ports. Two switches keep it off the machine's
hardware, set by both benches:

| Variable | What the bridge does |
|---|---|
| `GOLEM_NO_HW_MIDI=1` | no MIDI sent, no MIDI port opened, no pedalboard listened to or probed (`midi_out.hw_midi_off`). Before it, a bench without a pedalboard fell back on the `volt` amidi port: recalling a patch with a Whammy block changed the program of the **real** Whammy of the rack next to it |
| `GOLEM_BENCH_CARD=golem-bench` | the bench sees only its virtual card, plugged in (`cards.connected`): no "No sound card" banner, and never the machine's Volt offered as a card to switch REAPER to |

**Three passes**, all in `tools/use/`:

1. **Journeys** (`journeys.py`) on the factory content: boot (loading screen, first check), Live (scenes, stomps,
   presets, mixer, tuner, metronome, record the set, setlist picker, live lock), Songs (Golem Rising: parts, tempo,
   sections; patches played; banks and setlists duplicated, deleted, put on the foot, set as startup), Designer,
   Library (every tab, search with junk, a sample, a standard), Settings (modes, **Gig and its exit by holding the
   logo**, Health ▸ Run, every tab), the Companion at 390×844. A missing element is a *skip*, not a failure.
2. **The monkey** (`monkey.py`, `--monkey N`, `--seed S`): N gestures drawn from what is clickable on screen —
   including double taps, junk in fields (`<script>`, 300 characters, right-to-left marks), random menu choices,
   Escape, browser back, jumping to another page. The seed fixes the sequence; `steps.jsonl` replays it. Denied:
   what would kill the bench (stop, restart, lock down, update) or touch the machine's hardware (card switch, flash,
   Wi-Fi, pairing, downloads); on Settings ▸ System, Gear ▸ Soundcard and Engines it only leaves.
3. **Sound** (`Tester.listen`): at checkpoints, the bench DI rendered offline through the lane in place
   (`golem_preview.lua`, as `check-rig-materialize --render`), after the rig is mounted: silence, digital clipping,
   non-finite samples, and the reference of `tests/golden/renders.json` when one exists. A preset whose lanes are all
   MIDI (keys, pads, drums) is not judged on silence.

**The oracles, after every gesture** (`runner.Tester._oracles`): a JavaScript or console error; a 5xx from the API;
an ERROR or a traceback in the bridge log; a Lua error; REAPER or the bridge dead; a rack page that scrolls, a phone
page that scrolls sideways; French on screen; « GoleM »; a gesture slower than 6 s; and **a control a finger cannot
reach** — the click is intercepted by another element (a sheet's scrim is not counted: the tester closes the sheet
and tries again). **UX notes**, per screen: targets under 32 px, truncated text, overlapping controls, controls off
screen without a scroller.

**The report** in `--out` (default `assets/.cache/use-check`): `report.html` (failures first with their
screenshot, the sound table, the UX table, then every gesture with its screenshot), `report.json`, `steps.jsonl`,
`shots/`, `audio/` (the renders). Exit 1 if an oracle saw a failure. `--serve` mounts the bench and keeps it open to
explore by hand; `--only live,songs`, `--no-audio`, `--working-tree`, `--keep`.

What it does not judge: whether the sound is *good* (only that it exists, is finite and does not clip — a musician
listens), gestures Playwright cannot make (drag to reorder, multi-touch), golem.fm and TONE3000 (not connected on the
bench), real hardware (by design).

## Order

1 and 2 now; 3 and 4 next; 5 and 6 in the background; 8 as soon as 2 is stable. Lot 5's self-hosted runner is
also the answer to lot 1's minute budget, so it may move up.
