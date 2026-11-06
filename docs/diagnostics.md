# Diagnostic reports — what the rack tells golem.fm about itself

> **Status: CODED** — a paired rack builds whitelisted, scrubbed usage and bug reports at startup, at
> shutdown and on incidents, and sends them to golem.fm when the reports box is ticked (`bridge/diag.py`,
> `bridge/routes_diag.py`). Short user-facing summary: [`telemetry.md`](telemetry.md).
>
> **Incidents and how they ended** (2026-10-20, [`assistant.md`](assistant.md) §3.1): the events `incident`, `fix`,
> `resolution` and the session section `incidents` — CODED (`bridge/incidents.py`, `bridge/fixes.py`).
>
> **Next** (2026-10-27, §7): an install report sent on one click, app errors in the timeline (`ui_error`) and error
> signatures (`sig`, `sig_src`) — CODED on the rack (lots D1, D2, D4, D5). golem.fm's side (D3: the install-report
> route; D6: the signature index) is theirs. No third-party error service (sentry.io…): decided 2026-10-27.

Related: [`identity.md`](identity.md) (the rack does not know people), [`golemfm-protocol.md`](golemfm-protocol.md)
(the upload call and the `diagnostic-report` job), [`rack-mcp.md`](rack-mcp.md) (`diag_report`).

## 1. Principles

1. **Automatic.** One box in Settings ▸ Connect, **ticked by default**: "Allow this golem to send usage and
   bug reports to golem.fm". Ticked → the rack sends. Unticked → no package is ever built and nothing
   leaves (the local timeline is still written, §4.3). There is no other control: no send button, no
   preview, no history screen.
2. **Inverted whitelist.** Nothing leaves unless explicitly listed. Every section is **picked** field by
   field from a declared table (`diag.WHITELIST`, `_pick`), never copied from an existing dict. A field
   added tomorrow to `/api/state` is not in the report. `diag.violations()` walks the result, and **a
   violation makes the build fail**: no report is better than a leak.
3. **Never a `tar` of `config/`.** A built package.
4. **The rack does not know people.** No first name, roster, space, `person`, preset/lane/capture name:
   **types** and **short hashes** only (`HASH_LEN = 12`; a hex string of 32+ characters is treated as a
   token by the scrubber, so full hashes never appear).
5. **Scrubbing** (§3) of every string and every log line, as a second layer behind the whitelist.
6. **Readable by the user and by a model.** The package describes itself (versioned schema, `_doc` per
   section, closed event vocabulary), because its final reader does not know the code.
7. **Survives power loss.** The rack is unplugged like an appliance: the session lives on disk, and a
   session that did not close is reported at the next boot.

golem.fm keeps reports 90 days; the box's text says so.

## 2. The package

### 2.1 Three kinds (`diag.KINDS`)

| `kind` | When | Contains |
|---|---|---|
| `boot` | at bridge start, once REAPER is connected (90 s max, `BOOT_WAIT_REAPER_S`) | the machine sections, and `previous_session` if the last session did not close |
| `session` | at bridge shutdown — or at the next boot if the shutdown could not | usage, the session timeline, samples, logs (last 2 h) |
| `event` | on an incident (§4.2), or on request | the state now, `event`, timeline and logs of the last 30 min |

A zip `diag/golem-<kind>-<YYYYMMDD-HHMMSS>-<report_id[:8]>.zip`:

```
golem-report.json   manifest: {golem_report: 2, kind, session_id, report_id, created_at,
                    files{name: sha256}, truncated, missing[]}
report.json         state + usage, whitelisted (§2.2)
timeline.ndjson     one event per line (§2.3)
samples.ndjson      measurements (§4.1); absent from boot unless previous_session
logs/bridge.log     journald (user units golem-bridge, -reaper, -midi, -kiosk, -server)
logs/kernel.log     kernel journal, lines matching xrun|snd_|usb |audio|ALSA
logs/reaper.log     tail of $GOLEM_REAPER_LOG (default /tmp/golem-reaper.log)
logs/apport.log     lines mentioning reaper in /var/log/apport.log (plugin aborts, signal 6)
logs/rig-check.json presets/.rig-check.json + the archived abnormal passes
```

**4 MB cap** (`MAX_ZIP_BYTES`), of which 3 MB for logs (`LOG_BUDGET_BYTES`). Logs are cut from the
start (recent lines win), never the timeline nor `report.json`; the manifest says `truncated`. A missing
source (no apport, bridge not started by systemd) is listed in `missing[]` rather than guessed.

All times are UTC ISO-8601, plus `up` (seconds since bridge start) to order without a clock; units are in
field names (`_ms`, `_mb`, `_pct`, `_c`).

### 2.2 `report.json` — the whitelist (`diag.WHITELIST`)

Starts with `report.schema = "golem-report/2"`; each section carries a one-sentence `_doc`. A probe that
fails leaves its section out and lists it in `_missing`.

| Section | Fields |
|---|---|
| `report` | `schema`, `kind`, `session_id`, `report_id`, `created_at`, `up`, `truncated` |
| `platform` | `os`, `kernel`, `rt` (PREEMPT_RT), `arch`, `cpu_model`, `cpu_count`, `ram_total_mb` |
| `golem` | `version`, `branch`, `dirty`, `profile`, `installed_at`, `installer`, `catalog_version` |
| `reaper` | `installed`, `pinned`, `running`, `uptime_s`, `rss_mb`, `restarts` |
| `audio` | `card` = `{usb: "VID:PID", inputs, outputs, midi{in, out}}` (**no name**), `bsize`, `rate`, `latency_ms`, `governor`, `boost`, `alive`, `xruns_total`, `xruns_window` |
| `midi` | `devices[]` = `{usb, kernel}` (no name), `ok`, `issues` |
| `pedalboard` | `id`, `source`, `stale` |
| `mode` | `id`, `kind` (show / gig / rehearsal), `locked`, `services{}` |
| `preset` | `hash` (short file hash), `scene`, `blocks[]` = `{type, category, quarantine?, bypass?, wrong_kind?}`, `lanes` = `{count, roles}` — **never id or name** |
| `libraries` | `components[]` = `{id, installed, version?}`, `missing` — only components of the public manifest `provision/components.json` |
| `catalog` | `quarantined` (types), `captures` = `{nam, ir}` (**counts**: a capture name can be a person's name) |
| `rig_check` | `ok`, `checked`, `issues[]` = `{kind, expected (scrubbed basename), repaired}` — no track |
| `health` | `cpu_pct`, `temp_c`, `ram_used_pct`, `disk{free_gb, used_pct}` |
| `first_check` | the first-start check ([health.md](health.md) §2): `done_at`, `skipped`, `took_s`, `verdict` (ok / partial), `steps{input{ok, took_s, peak_db, input, role, gain}, output{ok, took_s, click_ticks, heard}, foot{ok, took_s, answered}}` — verdicts and durations, never a name (`role` is the instrument confirmed on the input — guitar, voice… — `gain` is low / good / hot); absent until it has run |
| `usage` (session) | `started_at`, `ended_at`, `ended` (`clean` / `unclean` / `unknown`), `duration_s`, `modes[]{kind, duration_s}`, `recalls{count, ms_median, ms_max, failed}`, `scene_switches`, `presets_distinct`, `block_types_used`, `takes{count, duration_s, kinds}`, `standards_played`, `looper_used`, `keys_used`, `pedalboard_used`, `foot_messages`, `jobs{done, error}`, `events` (counts per type) |
| `anomalies[]` (session) | `{chip, first_at, total_s, count}` — /live chips that lit up, with durations |
| `incidents` (session) | `opened` (count), `resolved{action, restart, outside}` (counts — the **last** resolution of each incident wins, so a hint given after the close counts), `hints{cable, gain, power, other}` (counts), `open[]` = `{kind, code, age_s}` still failing at the end — types and codes, **never** the incident's title or detail ([assistant.md](assistant.md) §3.1) |
| `previous_session` (boot) | `session_id`, `started_at`, `ended_at`, `ended`, `usage`, `anomalies` |
| `event` (event) | `type`, `at`, `chips` (active now), `detail` (scrubbed, ≤ 500 chars) |

Free-key maps (counts keyed by a type or service id, never a name): `mode.services`, `usage.takes.kinds`,
`usage.events`, `incidents.resolved`, `incidents.hints` (`FREE_MAPS`).

**Never included**: `config/.band.json`, `config/auth-devices.json`, `config/integrations.json`, `.env`,
`config/network.json`, REAPER's license, any `person`/`people`/`band`/`space` field, preset ids or names,
lane, track, capture, setlist or song names, the golem.fm `base_url`, plugin names outside the public
manifest, and audio.

Plugins found on disk outside a public manifest are never named: a name read on the user's disk does not
leave the rack.

### 2.3 `timeline.ndjson` — the event vocabulary (`diag.EVENTS`)

One line per event, `{"t", "up", "type", …}`. The vocabulary is **closed**: an unknown type is refused, an
unknown field is dropped. Every event goes through `diag.event(type, **fields)` (validates, scrubs, caps
strings to 200 chars and lists to 20, appends one line with `O_APPEND`), or `diag.trigger()` for types
that can trigger a package.

| `type` | Fields | Emitted by |
|---|---|---|
| `boot`, `shutdown` | `reason` | `open_session`, `close_session` |
| `reaper` | `state` (`up` / `down` / `restart`), `pid_uptime_s`, `why` | `monitors` |
| `mode` | `from`, `to`, `locked` | `routes_modes.set_mode` |
| `recall` | `preset_hash`, `scene`, `ms`, `ok`, `rebuild`, `blocks` (block TYPES) | `recall` |
| `scene` | `to`, `ms` | `recall` |
| `stomp` | `block_type`, `on` | `app._do_stomp` |
| `foot` | `msg` (`pc` / `cc` / `note`), `n` | `foot` |
| `xrun` | `delta`, `window_s` | `monitors` (per 3 s tick with new xruns) |
| `chip` | `chip`, `on` | `monitors`, `app` (`NO AUDIO`, `NO MIDI`, `FX FILE`, `PEDAL?`, `IN n CLIP`) |
| `audio` | `state` (`lost` / `recovered` / `reset`), `why` | `monitors` |
| `midi` | `state` (`unplugged` / `plugged` / `reinit`) | `monitors` |
| `rig_check` | `ok`, `issues` (count), `kinds` | `monitors` |
| `take` | `state` (`start` / `stop`), `kind`, `duration_s`, `tracks` | `monitors` |
| `job` | `action`, `ok`, `ms` | `tones_jobs` |
| `error` | `logger`, `msg` | `golog` handler (every ERROR of the bridge) |
| `requested` | — | a report requested by golem.fm or `POST /api/diag/build` |
| `incident` | `id` (short, local), `state` (`open` / `closed`), `kind` (`fact` / `silence` / `first_check`), `code` (the fact id, the "Why no sound?" verdict code, or the gesture), `stage` | `incidents` (Health pass, a probe) |
| `fix` | `id` (the incident, if any), `action` (a registry name), `params` (bounded values: a buffer size), `by` (`button` / `doctor` / `assistant` / `undo`), `verify` (`ok` / `ko`), `ms` | `fixes` |
| `resolution` | `id`, `resolved_by` (`action` / `restart` / `outside`), `after_s`, `hint` (`cable` / `gain` / `power` / `other`, sent again when the musician gives it) | `incidents` |
| `assist` | `ok`, `error` (golem.fm's refusal code: `ai_quota`, `rate_limited`, `repair`…), `cites` (help ids `<section>/<page>`), `proposed` (a registry action name), `dropped` (the rack refused golem.fm's proposal), `ms` — **never the question or the answer** | `assistant` ([assistant.md](assistant.md) §5) |

**Reaper intent.** A `reaper down` without `why` reads as a crash. The code that decides to stop REAPER
(restart from the Dashboard, buffer or card change, engine update) calls `diag.intent("reaper", why)`
**before** killing it; the monitor attaches it (`why` = `requested` / `settings` / `update`, valid
120 s). An announced stop does not trigger an `event` package.

`sample` rows (`res`, `xruns`, `latency_ms`, `cpu_pct`, `temp_c`, `audio_ok`, `midi_ok`, `mode`, `scene`,
`preset_hash`) only go to `samples.ndjson`, never to the timeline.

## 3. The scrubber (`diag.Scrubber`)

Applied to every string of the report (keys included), of the timeline and of every log line. Rebuilt at
most every 60 s, since the name lists change.

| Replaces | With |
|---|---|
| `C.ROOT`, `$HOME`, `/home/<user>` | `~` |
| song ids (`bs:2`, `rs:<id>`, `rs-<id>.golem`) | `<song-id>` |
| `gmt_…`, `t3k_…`, `Bearer …`, hex ≥ 32 chars | `<token>` |
| private IPv4 (10/8, 172.16/12, 192.168/16, 127/8) | `<ip>` |
| MAC addresses | `<mac>` |
| hostname, POSIX user name (≥ 3 chars) | `<host>`, `<user>` |
| roster names and ids, band names, input-map `person` names | `<name>` |
| preset, artist, lane and patch names | `<preset>` |
| song titles and golem.fm song slugs, setlist names and line titles | `<song>` |

Known labels (≥ 3 characters) are replaced **whole**, with word boundaries ("Lea" must not eat the middle
of "unclean"), **longest first** ("Set Léa" becomes `<preset>` before "Léa" becomes `<name>`). Band
slugs are not scrubbed ("test", "dev" are log words). A two-letter first name is an accepted risk.

The scrubber is not a guard: the whitelist forbids first, the scrubber catches what a log line may have
written. Both layers, not one.

## 4. On the rack's disk

### 4.1 Samples (`diag.sample`)

Called on each 3 s tick of `monitors._monitor_audio`: a ring of the last 10 minutes (`RING_POINTS = 200`,
`res: "3s"`) plus one average per minute for the whole session (`res: "1m"`; `xruns` = within that minute).
CPU is computed from `/proc/stat` deltas without sleeping. Flushed to disk every 15 s
(`FLUSH_EVERY_S`). `xruns_window` is a difference between two ring points, not a new counter.

### 4.2 Triggers (`diag.EVENT_TRIGGERS`)

| Event | Builds an `event` package when |
|---|---|
| `reaper` | `down` or `restart` without an intent |
| `audio` | `lost` |
| `rig_check` | `ok: false` (a NAM model or IR not loaded) |
| `xrun` | `delta ≥ 10` in one tick |
| `error` | always (an ERROR logged by the bridge) |

At most **one `event` package per type every 10 minutes** (`EVENT_RATE_S`); between two, events stay in the
timeline and leave with the `session` package. Packages are built and sent in a thread, never on the event
loop.

### 4.3 Session lifecycle

- **Start** (`app.py` → `diag.boot()`): `open_session` writes `diag/session.json`
  `{session_id, started_at, mode_kind, ended_at, ended}`. If the previous session has no `ended_at`, it is
  closed as `unclean`, its usage and anomalies are rebuilt from its timeline (`summarize`), the timeline is
  moved to `diag/prev-timeline.ndjson`, and the summary leaves in the `boot` package as `previous_session`.
  Then `boot_task` waits for REAPER and `boot_report` sends pending packages first, then the `boot`.
- **Shutdown** (`app.py` shutdown hook → `diag.shutdown_report`): **write first** (close the session, zip on
  disk), **send second** with a short timeout (`SHUTDOWN_SEND_TIMEOUT_S = 5`). A send that drags must never
  prevent the write; a failed send leaves at the next boot.
- **Files** in `diag/` (local state, not in the repository): `session.json`, `timeline.ndjson`, samples,
  packages and `index.json` (`{report_id, kind, created_at, file, size, sha256, sent_at, error}`). The last
  **20** packages are kept (`KEEP_REPORTS`); an unsent package is never removed by rotation.
- **Box unticked**: session and timeline are still written (local troubleshooting); no zip is built (except on explicit local request, §5), nothing leaves.

### 4.4 Sending

`diag.send(report_id)` → `POST /api/ext/diagnostics?filename=&kind=&sha256=` with the zip as raw body and
the pairing token (the same upload contract as the backup vault). Deduplicated by sha256 on both sides: a
package never leaves twice. On failure the package stays pending (`sent_at: null`, `error`).
`diag.flush_pending()` resends in order on every heartbeat tick (`rigstatus.start_pusher`) and at boot,
and stops at the first failure.

**Job `diagnostic-report`** (from golem.fm, `tones_jobs._diagnostic_report`): builds an `event` package
(`type: "requested"`), sends it, then acks `{report_id, sha256, size}`. Governed by the same box: unticked,
the job fails with `reports disabled on this rack`, which golem.fm displays as is.

## 5. Local routes and tools

| Route / tool | |
|---|---|
| `GET /api/diag` | box state, current session, package index, timeline line count (`/api/diag*` GETs are sensitive, `auth.SENSITIVE_GET_PREFIX`) |
| `POST /api/diag/build {kind, detail?}` | builds a package **without sending it** (works with the box unticked) |
| `GET /api/diag/{id}/download` | the zip, for local troubleshooting |
| `POST /api/diag/settings {auto}` | the box; stored in `config/diag.json` `{"auto": bool}` (absent = ticked) |
| MCP `diag_report` | last `report.json` + timeline tail, admin only ([`rack-mcp.md`](rack-mcp.md)) |
| `tools/check-report.py [--kind …] [--keep]` | builds a package on the running rack and checks manifest, hashes, size, vocabulary and whitelist, then greps the personal data the rack knows about itself (roster names, preset names, `$USER`, hostname, token, LAN addresses). Removes the package from the index unless `--keep` |

## 6. Tests

`tests/test_diag_whitelist.py`, `test_diag_pii.py`, `test_diag_session.py`, `test_diag_send.py`,
`test_diag_timeline.py`:

- **Whitelist**: a fake rack whose state carries an unknown field → absent from the report; every key is in
  the table; every timeline type is in the vocabulary.
- **Personal data**: a roster with a first name, a golem.fm token, a preset and a lane named after a person,
  a home path and a LAN IP in a log → none of those strings anywhere in the zip.
- **Session**: open, append, no close → next boot reports `ended: "unclean"`, rebuilt usage, a late
  `session` package and a `boot` with `previous_session`.
- **Box off**: no zip, no send, the timeline still written; the job fails with the documented message.
- **Pending**: golem.fm unreachable at shutdown → sent once at the next boot, never twice.
- **Events**: one `audio lost` → one package; two within 10 minutes → one.

## 7. Next: install failures, app errors, grouping

> **Status:** §7.1 **CODED on the rack** (2026-10-27: `bridge/scrub.py`, `installer/report.py`, the failure card of the
> Install screen, `POST /api/report` on the installer's server; tests `test_scrub.py`, `test_install_report.py`) — not
> yet sent to production golem.fm (their route, D3, is built and checked end to end against a local golem.fm, not
> deployed). The **uninstaller** sends its report automatically on failure (decision of 2026-10-27).
> §7.2–§7.3 **CODED on the rack** (2026-10-27: `app/ui-errors.mjs`, `POST /api/diag/ui-error`, `diag.SIGNED`,
> `golog._exc_sig_src`; tests `app/ui-errors.test.mjs`, `test_diag_signatures.py`); the index (D6) is golem.fm's. **Decision (2026-10-27):** no third-party error service
> (sentry.io or similar) in the rack. golem keeps its own reports, with the whitelist and the scrubber above, and adds
> the three missing parts below with its own tools.

Three gaps in what reaches golem.fm today:

1. **A failed install is invisible.** The installer keeps its trace on disk, but the bridge is not running yet and
   the rack is not paired, so nothing reaches golem.fm.
2. **An error in the app** (rack screen, Companion) never reaches the timeline: no global handler feeds the reports.
3. **Reports are not grouped.** Each package is read on its own. Nobody can see that one error hits forty racks,
   that it appeared in v3.0.5, or that it is gone since v3.0.7.

Unchanged: **an unpaired rack still sends nothing.** Consent goes through the pairing box (§1); §7.1 is the one
exception, and it is explicit, one click per report.

### 7.1 The install report (`kind: "install"`)

- **When**: the installer's failure screen — a step that failed, or a stall the user stopped — shows **"Send this
  report to golem"**. The installer never sends by itself: nobody has ticked a box yet. Next to the button:
  "What is in it" lists the files and sections below.
- **Uninstall: sent automatically** (`kind: "uninstall"`). Decision of 2026-10-27: someone who is uninstalling will not
  tap a button, so a failed uninstall (an item not removed, or a run that stopped) sends its report **by itself**
  (`installer/uninstaller.send_report`, from the uninstaller's copy, which carries `installer/report.py` and
  `bridge/scrub.py`). The Uninstall screen says that it was sent, gives its code, and has the same "What is in it".
  Same package, same scrubbing; `install.failed_items` lists the plan ids that stayed (`golem:command`…); the version
  is read before anything is removed. `--dry`: built, never sent. A successful uninstall sends nothing. A Retry starts
  a new report.
- **Package** `golem-install-<YYYYMMDD-HHMMSS>-<report_id[:8]>.zip`, the same layout as §2.1:

  ```
  golem-report.json   manifest {golem_report: 2, kind: "install", report_id, created_at, files{name: sha256}, truncated, missing[]}
  report.json         report, platform (§2.2 fields), golem {version (the installer's), target_version (what it was
                               installing, when known), installer: platform module, dry: false},
                      install {failed_step, rc, sig, sig_src (§7.3: the failure line), stalled, quiet_s, elapsed_s,
                               steps[{id, state, secs}],
                               phases[{id, state, secs, warns}], packs, engine, instrument, privilege},
                      checks[{id, ok, blocking}]
  logs/install.log    the installer trace (installer/server.py open_log_file), scrubbed, last 1 MB
  ```

- **Never included**: the sudo password (it is never in the trace; a test proves it), the REAPER licence, the
  golem.fm and TONE3000 keys typed on the Connect screen, the target folder as typed (it becomes `~/…` or
  `<dir>`), the hostname, `$USER`.
- **Scrubbing without the bridge**: the scrubber (§3) moves to a stdlib-only module, `bridge/scrub.py`. The bridge
  keeps using it through `diag`, and the installer loads it by path, as it already loads `bridge/reaper_license.py`
  and `bridge/engines.py`. The installer's lists of things to erase: `$USER`, the home folder, the hostname, the
  target folder, LAN addresses, and every key typed during this install.
- **Where it is kept**: `<tmp>/golem-reports/golem-install-….zip`, next to the installer trace. Built on the click only,
  in a thread; the screen polls `S.report` = `{state: sending | sent | fail | dry, code, path, error}`, reset by Retry.
  The signature line is the last `✗` / error line **of the failed step**, never the installer's own summary
  ("✗ step « … » failed", the same for every failure).
- **Sending**: `POST /api/ext/install-reports?kind=&sha256=` with the zip as raw body and **no token**, to
  production golem.fm (`installer/report.PROD_URL`, the same as `routes_content.DEFAULT_SERVER`; `GOLEM_SERVER_URL`,
  or `GOLEM_REPORTS_URL` for reports only, points it at a dev golem.fm). golem.fm
  answers `{code}`, a short reference such as `R7K2Q`, which the screen shows ("Quote R7K2Q if you write to us").
  If sending fails, there is no queue: the screen says so, and gives the zip's path so it can be shared by hand.
  In `--dry`, the package is built and never sent, and the screen says so.
- **golem.fm side** (agreed by golem.fm on 2026-10-27; theirs to build, lot D3):
  - **Size**: `Content-Length` is required and must be ≤ 2 MB; the body is read up to 2 MB + 1, and 413 beyond.
  - **Hash**: `sha256` must be the body's hash, otherwise 422. It is also the dedup key: the same zip gets the
    **same** code back, with 200.
  - **Zip guards**: those of `golemfile` (≤ 50 members, ≤ 20 MB unpacked, a ratio guard, no path traversal). Only
    `golem-report.json`, `report.json` and `logs/install.log` are kept.
  - **Manifest**: checked (`golem_report` = 2, `kind` = the query's `kind` ∈ {install, uninstall}, each member's
    sha256 matches `files{}`).
  - **Rate limit** per client address: 5 an hour, 20 a day. Behind golem.fm's proxy, only the trusted forwarded
    address counts. Only a salted hash of the address is stored.
  - Kept 90 days; no CORS.
  - **Answers**: 201 `{code}` for a new report, 200 `{code}` for a duplicate, 413 / 422 / 429 `{error, message}`.
    The code is 5 characters of Crockford base32 (no I, L, O, U), unique.

### 7.2 App errors (timeline event `ui_error`)

- The app (`app/*.js`, rack screen and Companion) catches `error` and `unhandledrejection` once, globally, and posts
  `POST /api/diag/ui-error {page, msg, src, line, col, frames}`: `src` and `frames` are **file basenames and
  line numbers only** (at most 5), `page` is the route without its parameters, and `msg` is capped at 200
  characters.
- Throttled in the page: the same error once per page load, at most 20 per load. The bridge caps again (60 per
  session), scrubs, and writes one timeline event:
  `ui_error` — `page`, `msg`, `where` (`file:line`), `sig` and `sig_src` (§7.3), `client` (`rack` / `companion` /
  `phone`).
- **Not a trigger** (§4.2): `ui_error` leaves with the `session` package. One broken page would otherwise send a
  package every 10 minutes.
- As coded: `watchErrors('rack')` in `app/main.js`, `watchErrors('companion')` in `mountCompanion`; `page` is the
  first segment of the route (`#/songs/rs-…?x` → `/songs`); the post bypasses `api()` (a failed send never raises a
  new error). Cap per session: `routes_diag.UI_ERRORS_MAX` = 60, then `{ok: false, dropped: true}`. The `sig_src` of a
  `ui_error` is `msg @ file:line frames…`, normalized — line numbers become `#`, so the signature survives a version.
- The route accepts any paired device of this rack, never an anonymous caller. Like the other `/api/diag*` routes,
  it is not public (`auth.py`).

### 7.3 Signatures and versions (grouping)

- **On the rack**, every `error`, `ui_error` and install failure carries a `sig`: the first 12 hex characters of
  the sha256 of a normalized form.
  - For a Python error: the logger, the exception type, and the innermost `bridge/` frame as `module:function`.
  - For a log line or a message: numbers become `#`, hex strings and ids become `*`, paths become their basename,
    and the text inside quotes is dropped.
  - **As coded**: the rule is `bridge/scrub.normalize` + `scrub.sig` (one rule for the rack and the installer).
    `diag.event` computes `sig` itself for `diag.SIGNED` = `error`, `ui_error`, from the **scrubbed** `sig_src`, then
    normalized; a `sig` given by the caller is ignored. An exception's `sig_src` is
    `logger|ExceptionType|module:function` of its innermost `bridge/` frame (`golog._exc_sig_src`): no message, no
    line number. Another `error` signs `logger: message`.
  - Two racks hitting the same bug produce the same `sig`, and a `sig` reveals nothing the message did not.
  - **`sig_src`** travels next to every `sig`: the normalized string itself, free of personal data by construction
    and scrubbed anyway. golem.fm recomputes `sha256(sig_src)[:12]` and refuses a mismatch: it reads, it does not
    trust a declared value.
- **The version** is already in every package (`golem.version`, §2.2). An install report carries the installer's
  version, and `target_version` (what it was installing, when known): "new in v3.0.x" is about that one.
- **On golem.fm** (its side, to agree): an index of signatures — `first_seen`, `last_seen`, `count`, distinct
  racks (hashed), versions seen, `new in` / `last seen in` a version, and a free link to the fix (a rack commit).
  Install reports are grouped by `failed_step` + `install.sig`. A notice goes to the maintainers when a signature is
  new and seen on two racks, and when an install-failure signature is new.
- **Notices** (golem.fm, agreed 2026-10-27): there is no outgoing email (SMTP deferred). They show on golem.fm's admin
  side: in admin ▸ Health, a "new signatures" check that turns amber, plus a badge on the admin menu like the reports
  badge. An install report's code is searchable in admin. Another channel is the maintainer's choice, later.

### 7.4 Lots

| Lot | Content | Side |
|---|---|---|
| D1 | `bridge/scrub.py` extracted from `diag` (no behaviour change; the PII tests still pass) | rack |
| D2 | the install report: failure-screen button, "What is in it", package, scrub, send, code shown; `--dry` | rack |
| D3 | `POST /api/ext/install-reports`, storage, limits, the reference code | golem.fm |
| D4 | `ui_error`: global handler in the app, `/api/diag/ui-error`, vocabulary, throttles | rack |
| D5 | `sig` + `sig_src` on `error`, `ui_error` and install failures | rack |
| D6 | the signature index and the notices | golem.fm |

Tests to write with them:
- **Install report personal data**: a trace holding `$USER`, the home path, a typed golem.fm key and a LAN
  address → none of them in the zip. The sudo password never appears in the trace.
- **No click, no send**: a failed install sends nothing.
- **`ui_error`**: an unknown field dropped; the throttles hold; it is not a trigger; an anonymous caller is
  refused.
- **`sig`**: the same error with different numbers, ids and paths gives one `sig`; two different errors give two.
