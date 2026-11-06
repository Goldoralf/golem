# Health — the rack tells the musician how it is

> **Status: PARTLY CODED (2026-10-20).** The design of a **Health** tab under Settings, a **first-start check**, and
> the backlog of ideas to make a golem less of a black box — all drawn from the quality automation of
> [`quality-automation.md`](quality-automation.md), turned towards the musician instead of the developer.
> **CODED:** §1.1 "Now" (`bridge/health.py`, `GET /api/health/facts`, `app/page-health.js`), §2 the first-start
> check (`bridge/first_check.py`, `app/page-first-check.js`), §3 the top-bar dot, §4.1 "Why no sound?" (`bridge/silence.py`, on Health),
> §4.2 environment drift, §1.4 Fix and incidents (`bridge/fixes.py`, `bridge/incidents.py`, `golem doctor` —
> contract in [`assistant.md`](assistant.md) §3).
> **PROPOSED:** §1.2, §1.3 (except the first-start check replayed from Health) and the rest of §4. Mockups: `mockups/health.html`,
> `mockups/first-check.html`, `mockups/health-fix.html` (validated 2026-10-20).

Related: [`troubleshooting.md`](troubleshooting.md) (symptom → checks → code: Health links to it),
[`diagnostics.md`](diagnostics.md) (the packets: Health results go in), [`ui-architecture.md`](ui-architecture.md)
(where the tab lives), [`dev-setup.md`](dev-setup.md) §5 (the probes and their danger).

**Doctrine.** Health states **dated facts it measured**, never guesses (CLAUDE.md: verify before asserting). Every
line names its source (`.rig-check.json`, `.clock.json`, the plugin inventory, a probe's report) and, when red, the
gesture that fixes it. Nothing in Health makes sound or touches the live rig without saying so first and without
the "rack free" guard (`tools/rack-free.py`, `reamp.md` §2).

---

## 1. The Health tab (Settings ▸ System ▸ Health)

Three layers, because they differ in cost and in moment.

### 1.1 Now — facts read continuously, costing nothing — CODED

`bridge/health.py` reads the eleven facts below every 5 s (a daemon thread, `health.start()`), caches them, and
serves them on `GET /api/health/facts` (a sensitive GET: it names the preset played and the setlist). Each fact is
`{id, name, level: ok|wait|warn|bad, text, source, fix?: {label, go}, repair?, incident?}` — `fix` is a **navigation**;
`repair` is the registry action that answers this fact, when there is one (§1.4).
`wait` means "not measured, or not applicable": it never alarms. The verdict is the worst level, with a one-line
title; `state.snapshot()["health"]` carries its brief for the top-bar dot. The only costly fact (the blocks of the
active setlist) is cached 60 s. Page: `app/page-health.js`; pure part: `app/health-model.mjs`.

| Fact (`id`) | Source | Orange / red means → the fix |
|---|---|---|
| Engine (`engine`) | `state.reaper_running`, `reaper_connected`, `rigstatus.reaper_version` | running but not answering → Dashboard (resync); not running after 60 s → red, Dashboard |
| Sound card (`audio`) | `state.audio` (the `.clock.json` witness), `rigstatus.engine_doc` | `audio.ok` false → red, Soundcard page |
| Dropouts (`dropouts`) | `state.xruns`, `xruns_recent` (10 min), `xruns_last` | 1–9 recent → orange, ≥ 10 → red; Dashboard (buffer) |
| Pedalboard & MIDI (`pedalboard`) | `pedalboard.active()`, `state.midi` (`.midi.json`) | stale probe or a MIDI issue → orange, Calibration; only declared → wait |
| Playing (`playing`) | `state.preset_name`, `rig_check` (`.rig-check.json`), `rig_error` | files not loaded → red (Designer); repaired after the build → orange; refused recall → red |
| Setlist on the foot (`setlist`) | `setlists.active_id/load`, `blockstatus.preset_status` per preset (cached 60 s) | blocks that will not play here, counted by reason (plugin missing on this OS, capture format this engine cannot play, capture to download) → orange, Patches (each patch opens in the Designer, which downloads or swaps in a playable twin — Health itself never downloads: a download re-poses the preset) |
| Plugins (`plugins`) | `blockstatus.inventory/caps` (`.fx-inventory.json`) | counts only; not scanned yet → wait |
| Disk (`disk`) | `rigstatus.disk()` | < 20 GB → orange, < 5 GB → red; Storage |
| golem.fm (`golemfm`) | `boot.services.fm`, `follow_uplink.LINKED` | paired but unreachable (after 15 s) → orange, API; not paired → wait, API |
| Scripts (`scripts`) | `presets/.lua-errors.log` (mtime since the bridge started) | an error since start → orange, with its last line |
| Since last boot (`environment`) | `config/.env-snapshot.json` (§4.2) | something changed since the bridge started → orange, listed |

Most of this exists as scattered tiles (System ▸ Dashboard) and as the facts of the loading screen
(`boot_progress`). Health is the one list, green / amber / red, with the fix on the same line.

### 1.4 Fix and incidents — CODED (2026-10-20)

The contract is [`assistant.md`](assistant.md) §3 and §3.1; the screen is `mockups/health-fix.html`. On the page:

- **"Fix…" on the line.** `health.compute()` asks `fixes.repair_for(fact)`: when the action registry
  (`bridge/fixes.py`) has an answer to a red or orange fact, the fact carries `repair = {action, params, label,
  title, blocked}`. Today: dropouts → raise the buffer one step; engine running but silent → resync; engine down or
  a Lua error → restart REAPER; the audio thread stopped with the card plugged → reopen the card; a MIDI problem →
  reopen MIDI devices; files not loaded → pose the preset again. A fact without an answer keeps its navigation.
- **The sheet.** `POST /api/health/fix {action, params}` (without `confirm`) returns the plan: before → after, what it
  costs, how golem will verify, how to undo. Nothing runs before the tap. With `confirm`, the bridge re-checks the
  schema and the guard (`reamp.busy_reason(idle=False)`: a take, a song, a load, gig or locked mode — and one fix at
  a time), runs the action through the code path that already existed, then a thread **verifies** (the probe back
  to green, or a timeout: the buffer is judged on two minutes of play with at most two dropouts). Admin write.
- **Incidents** (`bridge/incidents.py`, `config/.incidents.json`, local, 30 days) replace the "Last self-test" card.
  A watched fact red twice in a row (golem.fm: for a minute — a network service down ten seconds is not a failure of
  the rack) and not in the first 45 s after the bridge started opens one; green twice
  closes it as `restart` (REAPER or the bridge restarted since) or `outside` (nothing from golem). A fix verified
  green closes it as `action`; a failed fix reopens it and keeps the attempt. "Why no sound?" (when the musician
  played) and the first-start check open and close their own. An incident that came back by itself in the last
  hour asks "What fixed it?" (cable · gain · power · other), optional — only where a hand can fix it (the card, the
  pedalboard or MIDI, REAPER, "Why no sound?", the first-start check; never golem.fm, the disk or a file). The last fix that changed a setting (the
  buffer) offers "undo", through the same sheet.
- **From /live.** A warning chip (⚠ NO AUDIO / NO CARD, NO MIDI, FX FILE, RIG, PEDAL?, the dropouts count) is a
  tap to `#/system/sys/health/<fact>`: Health opens with that line lit for a few seconds — never a fix by itself.
  In a locked mode (Gig, Show) the chips stay information only: a finger brushing the bar must not leave /live on
  stage. "IN n CLIP" has no Health line and stays information.
- **To golem.fm:** the events `incident`, `fix`, `resolution` and the session section `incidents` —
  [`diagnostics.md`](diagnostics.md). Titles and details stay on the machine.
- **« Ask golem »** — a field in the verdict banner, present when the rack is paired and the mode allows the service
  `assistant`; a drawer on the right asks consent once, sends the question to golem.fm, shows the answer, the help
  pages cited (named, not linked yet) and at most one proposed fix, which opens the same sheet (`by: assistant`).
  Contract: [`assistant.md`](assistant.md) §5–§8.
- **`golem doctor`** (`tools/doctor.py`, standard library only): the same facts, open incidents, the proposed fixes
  (`--fix ACTION --param k=v`, confirm, then the verification followed to its verdict), `--list` for the registry;
  the bridge down → what it sees from outside (port, REAPER process) and how to restart.

### 1.2 Last self-test — what the night found

*(Not built. Its card on the page gave its place to "Incidents" (§1.4): a failing self-test will land there as an
incident.)*

The nightly runs (`desktop-tests.yml` on GitHub, `rack-selftest.yml` on the machine's runner) produce reports
(`ui-check/report.json`, `rig-check/report.json`, pytest's verdict). The runner is on the machine: it drops a copy
in a folder the bridge reads (`presets/.health/<date>/…`, or a small `POST /api/health/report` admin-only). Health
shows: when, verdict per probe, what changed since the previous night (a patch that stopped materializing, a
render that drifted, a control whose effect changed). The UI tests never run on a rack (no Chrome): Health
imports their result, it does not launch them.

### 1.3 Check now — on demand, each announced with its cost

| Check | Proves | Cost | Needs a human |
|---|---|---|---|
| materialize and render every patch (`check-rig-materialize --all --render`) | the engine builds every patch; sounds match their references | ~2 min, isolated REAPER, **no sound** | no |
| scene gap (`check-scene-gap`) | ≤ 40 ms budget | 10 s, a test tone | no (loopback cable, or ears) |
| silence hunt (`check-silence`) — **CODED** | where the signal stops | read-only, 4 s | play something |
| input check | signal on IN 1 / IN 2 / MIDI | read-only | plug and play |
| output check | the click is heard on 1-2 | plays the click | listen and confirm |
| pedalboard check | the chip answers, the switch matches the setlist | read-only | press a switch |
| backup round trip (`check-restore --local`) | a backup restores | writes a witness preset, cleans up | no |

All behind the guard: never while a take runs, a song plays, or someone touched the rack in the last ten minutes
(the on-demand ones started from the screen skip the idle clause, like the reamp bench does). Results are kept
with history (like `.rig-check.history.json`) and joined to the diagnostics packets.

## 2. The first-start check (first install) — CODED

After the first boot, once — and replayable from Health. It continues the loading screen (`app/page-first-check.js`
replaces /live when `state.first_check.pending`, the boot is done and no mode is locked): the automatic lines
first (engine, sound card, factory content, the first preset posed and its files checked — the facts of §1.1, said
for this screen), then three gestures asked of the musician, each with a live measure and a one-line verdict:

1. **Plug and play** — every audio input of the card, with what the input map says is plugged in and its OSC
   meter (`state.levels.in<N>`, ~20 Hz on the WebSocket; the bridge receives the meters of input tracks 1–3 only).
   The musician plugs into **any** input and plays: the loudest recent peak above −45 dBFS is the input retained
   ("We hear IN 2. What is plugged in?"). The declared instrument is pre-selected; the musician confirms it or taps
   another (guitar · bass · voice · keys · line), and a changed one is written to the input map at the end of the
   gesture (`POST /api/inputmap`, as in Soundcard — not during it: the rig re-emit would cut the meters). The gain
   is judged live on the peak of the last 3 s while the knob turns: **low** below −24 dBFS ("turn up the gain of
   IN 2 on the card"), **good**, **hot** above −3 dBFS or when the bridge saw the input clip. The gesture passes
   on any signal; a gain that is not good shows on its line and in the bilan ("Ready, one adjustment: the input
   gain"). Verdict: "Guitar on IN 2 — peak −11 dBFS, good level". "Nothing to plug in — skip" always exits.
   The OSC meter is linear in dB (0 = −72, 1 = +6 dB — [pitfalls/reaper.md](pitfalls/reaper.md#the-osc-meter-is-linear-in-db-not-an-amplitude)),
   converted before any threshold. *(Changed 2026-10-20: the first version watched IN 1 only — a guitar on IN 2
   was never seen — and read the meter as an amplitude.)*
2. **Listen** — the bridge starts the click (`POST /api/metronome {on: true}`), the page shows it really runs
   (`.click.json` ticks) and asks "do you hear it?" yes / no; the click stops after the answer. A mode whose click
   is off says so and the step is skipped.
3. **Press a switch** — the bridge dates the start of the gesture; a switch counts only if `foot.last_heard()` is
   **after** that moment. Thirty seconds, then "nothing received — check the USB or MIDI cable". The chip-vs-setlist
   check (`fcb/check-uno2`) is not run here (it needs a chip in hand; Calibration does it).

Flow and storage: `bridge/first_check.py` — `begin(step)` dates, `record(step, ok, measured)` verifies what the
machine can (foot heard after the start, click ticks) and keeps the screen's measure (peak in dB), `finish()`
writes `done_at`, `took_s` and the verdict (`ok` when the three gestures are green, else `partial`), `skip()` and
`reset()` (the previous pass is kept under `previous`). Routes: `GET/POST /api/health/first-check`
(`{action: begin|step|finish|skip|reset}`). File: `config/.first-check.json` (local, gitignored). The result goes
in the next boot packet as the `first_check` section of `diagnostics.md` §2.2 — verdicts and durations, never a
name: when someone later says "it never worked here", we know what the machine saw on day one. The bilan screen
offers "Try the pedalboard again" (replays gesture 3 only) and "Open golem →"; "Skip for now" always exits.
A rack installed before this version sees the check once, at its next start. Dev: `?boot=firstcheck[&at=input|done]`
shows the screens; the UI probe renders both.

## 3. No health dot in the top bar — DECIDED 2026-10-20

The mockup drew a permanent dot in the top bar. It was built, then **removed** the same day ("a badge visible all
the time — remove it everywhere"): the top bar carries what is true everywhere, and health is read in
Settings ▸ System ▸ Health. What remains: **only red** (something broken) puts a badge on the Settings icon, the
System tab and the Health sub-tab (`healthDot` in `app/health-model.mjs`, from `state.health`). Amber never shows
outside the Health page. On Settings pages, where the
Health tab sits two taps away, the dot stays wordless (six tabs plus a sentence truncated "Licenses"). The Settings
icon, the System tab and the Health sub-tab carry the same dot (`svc-dot warn|bad`). Health is a **sub-tab of
System**, between Mode and Audio Engine (`#/system/sys/health`; the mockup drew it as a hub tab — decision of
2026-10-20); `#/system/health` redirects there.

## 4. Backlog — ideas to keep, by value

1. **"Why no sound?" button — CODED (on Health).** `bridge/silence.py` is the logic of `check-silence.py`, served
   from Settings ▸ Health ▸ Check now: the musician plays four seconds, the bridge samples the peaks of every track
   (the `peaks` probe, four times — each probe takes the single command slot), reads the input tracks' chunk and
   the files each NAM / IR loaded, and names the first silent stage, upstream to downstream: sound card lost →
   no input → no hardware output → the signal leaves REAPER (the silence is after it: monitor knob, volume,
   cables — the rig is fine) → stops inside the chain (an empty model or IR, a muted branch) → in the branches but
   not on the output track (merge). Read-only; refused with its reason during a take, a song, a load or in gig
   mode (`reamp.busy_reason(idle=False)`). Routes `GET/POST /api/health/silence`; the report is kept in
   `presets/.silence-<hhmmss>.json` as before, and `tools/check-silence.py` now drives this route. Still to do:
   the one-tap entry on /live when the input moves and the output does not.
2. **Environment drift — CODED.** `health.env_update()` compares, at every pass, what should not change by itself —
   golem and REAPER versions, OS, card, sample rate, buffer, plugin count, CPU governor, kernel — with the last
   snapshot (`config/.env-snapshot.json`, local), dates each change (30 kept) and says it on the "Since last boot"
   line. A probe that answers `None` (engine not up yet) never counts as a change. A change of golem's own version
   is said in green ("golem updated: …") — it happens at every wanted update, and on a dev box at every commit;
   the amber is kept for what moves by itself. Half of the "it worked yesterday" live there.
3. **The black box.** `monitors` already detects REAPER restarts, xrun bursts, a lost pedalboard, a failed recall
   (`diag` timeline). A "what happened" page: the last fifty events, timestamped, readable after the fact.
4. **End-of-session report.** The session packet goes to golem.fm; show it to the musician too: xruns, measured
   scene latency, incidents, missing files.
5. **Gig readiness badge.** On the active setlist: every block ready, models present, plugins stall-tested, scene
   gap within budget. Green, you can leave.
6. **A watchdog.** The REAPER crash of 2026-10-19 left the Windows rack silent because nothing relaunches REAPER
   there (Linux has the launcher's supervision). Automatic relaunch with a crash-loop guard, and Health tells the
   story.
7. **Sound fingerprints of the musician's own patches.** What lot 3b does for the bench patch, done when a patch is
   saved: a render, a fingerprint (`check-rig-materialize --render` machinery). Later Health can say "your patch
   X no longer sounds like the day you saved it" — typically after a plugin update.
8. **Rehearsed updates.** Everything exists: worktree, disposable bridge and REAPER, materialization. Before
   switching to a release (Settings ▸ About), play it blind on the new code and apply only if green.
9. **Self-test without GitHub.** The same scripts on a timer of the rack itself (systemd user timer on Linux, the
   Startup entry on Windows), result into Health. The runner stays for history and the alarm; the rack no longer
   depends on it.
10. **Verified backups.** `check-restore.py` exists; Health shows the date of the last backup that *restored*
    successfully, not only the last one written.
11. **Human checklist.** Lot 7 of `quality-automation.md`: the exploratory session on a release candidate, guided
    by what the machines do not cover — kept as a checklist in Health, ticked and dated by the musician.
12. **Health ▸ Fix, `golem doctor`, and an assistant.** The typed action registry, the incidents and `golem doctor`
    are CODED (§1.4); the conversation answered by golem.fm in front of them is PROPOSED in
    [assistant.md](assistant.md) §5.

**Where to start**, if three: the "Now" layer with the first-start check (§1.1, §2), the "why no sound?" button
(§4.1), environment drift (§4.2). Little new code, many existing pieces, and what a musician actually looks at.
