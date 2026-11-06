# Choosing the audio engine

> **Status: PARTLY CODED** — engine descriptors, the local choice, the `/api/engines` routes, the
> **Settings ▸ Engines ▸ Audio** page and the installer's "Audio engine" screen are coded as a shell
> (REAPER is the only selectable engine). Switching engines, the impact report, moving the REAPER
> licence into that page and capability-based hiding are **PROPOSED**.

The second engine itself (Ardour) is described in [`ardour-engine.md`](ardour-engine.md). This page
covers how an engine is described, chosen and installed.

## 1. Engines are data

Each engine is a descriptor in `config/engines/<id>.json`; the code never hard-codes REAPER. The
same doctrine as pedalboards ([`pedalboards.md`](pedalboards.md)).

| Field | Meaning |
|---|---|
| `id`, `name`, `by` | Identity shown on the card |
| `license` | `commercial` or `gpl-2.0-or-later` (the page shows "commercial" / "free · GPL") |
| `buy_url` / `sources_url` | Where to buy it, or where its sources are |
| `order` | Card order |
| `default` | The engine used when nothing is chosen (REAPER: `true`) |
| `selectable` | Whether golem ships an engine behind this descriptor at all |
| `unavailable_reason` | Shown when not selectable |
| `platforms.<linux\|win32\|darwin>` | `{available, reason?}` per OS |
| `summary` | One line on the card |
| `capabilities` | One entry per feature of `config/engines/features.json`: `yes`, `no` or `planned` |

`config/engines/features.json` lists the features in page order with their UI labels: Lanes &
scenes, NAM & IR, Recording, Backing, Click, MIDI clock, Looper, Drum machine, Samples, Standards,
Riff, Kill switch, Previews, Reamp. REAPER declares all of them `yes`. Ardour's descriptor has
`selectable: false` and its capabilities are the **target** of `ardour-engine.md`, not a measurement.

**Single reader.** `bridge/engines.py` (standard library only) is used by the bridge, the graphical
installer (`installer/server.py`) and `provision/install.sh`:

- `descriptors()` — every engine with its `available` and `reason` for this OS. Available means
  `selectable` **and** `platforms.<os>.available` (`availability`).
- `default_id()` — the engine marked `default`.
- `current()` — the choice in `config/engine.json`; if the file is missing, or names an engine that
  is no longer available, it falls back to the default. A rack installed before this file existed
  therefore runs REAPER with no action.
- `write_choice(id, set_by=…)` — writes `config/engine.json` after checking availability; raises
  `ValueError` otherwise.

`config/engine.json` is **local state** (not versioned).

## 2. Routes and page

| Route | Behaviour |
|---|---|
| `GET /api/engines` | `{current, platform, features[{id,label}], engines[]}` |
| `POST /api/engine {id}` | Writes the choice. An unavailable engine → **409** with its reason and `current`. Accepted → `{ok, current, switch_pending}`. **Nothing is switched**: `switch_pending` (`id != current`) is the hook where the switch will plug in (`engine_select` in `bridge/routes_system.py`). |

**Settings ▸ Engines ▸ Audio** (`#/system/sys/audio-engine`, `app/page-engine.js` `EnginePanel`): one
card per engine, same layout. The active engine shows "● Selected · running|stopped"; an unavailable
one shows its reason and a disabled "Select" button. Each card counts its features ("All 14", or
"N of 14 · M planned") and strikes out the ones marked `no`.

## 3. Installation

- **Graphical installer** (Linux, Windows, macOS — [`installer.md`](installer.md)): an
  **"Audio engine"** screen between "Checks" and "Reaper" (`installer/ui/installer.js`). The default
  engine is pre-selected; unavailable engines are greyed. The server ignores an unavailable engine
  even if forced through its API. Each platform module writes `config/engine.json` during its
  profile step (`ctx.write_engine`, in `installer/platform_*.py`).
- **`provision/install.sh --engine=<id>`** (Linux): validates the engine with `bridge/engines.py`
  before asking for sudo, then writes the choice. Without the option it does not overwrite an
  existing choice. Windows and macOS have no command-line installer; their bootstraps open the
  graphical installer.

## 4. The REAPER licence and versions today

They live in **Settings ▸ About ▸ REAPER** (`app/page-licenses.js`: `ReaperVersioningCard`,
`ReaperLicenseCard`).

- `GET /api/system/reaper-license` → `{present}`; on Windows also `state` ("registered" or
  "evaluation"), read from the title of REAPER's window (`bridge/desktop_reaper.license_state`),
  because a file being present does not mean REAPER accepted it.
- `POST /api/system/reaper-license {license}` writes `reaper-license.rk` (mode `0600`); REAPER
  imports it at its next start. The content is a secret: never returned nor logged. Admin only
  ([`SECURITY.md`](../SECURITY.md)).
- The writing lives in **one** module, `bridge/reaper_license.py` (standard library only): REAPER's
  resource folder for this OS (`resource_dir()`, re-exported as `config.reaper_resource_dir`: Linux
  `~/.config/REAPER`, Windows `%APPDATA%\REAPER`, macOS `~/Library/Application Support/REAPER`), the
  minimal check (text, not empty, at most 64 KB — no format check: REAPER judges the key at start) and
  the atomic `0600` write, which first records the install receipt prior `reaper.license_present`
  (first value wins). The installer's screen 3 loads the same module by path
  ([`installer.md`](installer.md) §2), since the bridge is not running during the install.
- The **loading screen** shows a `REAPER` row in warning style ("evaluation — add your licence to
  remove the reminder", **Set up** → `#/system/lic/reaper`) when no licence works on this machine
  (`state.boot.services.reaper`, filled by `boot_progress.refresh_reaper_license` from
  `reaper_license_status`; on Windows a file REAPER shows as "evaluation" counts as no licence). The row
  neither keeps the screen up nor brings "Open the app anyway"; with a licence there is no row.

## 5. Proposed

**Licence and versions move to the engine page.** One licence entry, on the engine card; Licenses
keeps a read-only "Engines" view (each engine, its licence, state on this rack, and a "Manage in
Audio Engine →" link). That view also carries Ardour's GPL and the obligation to publish the sources
of our build. Robust entry:

1. Drop or pick the `.rk` file first; pasting text second.
2. A shape check before writing (non-empty text, several lines, not JSON, not a URL). Only REAPER
   can validate the key.
3. Two states, never merged: "License file installed" (file present) and "Confirmed" (REAPER did not
   show its evaluation window at its last start). Windows already reads this; Linux would need to
   look for the window (`xwininfo`).
4. Restart is an explicit choice ("Later — at the next start" / "Save & restart now · audio stops
   ~10 s"), refused during a take or in Show mode, with the reason on the button.

**Switching engines.**

1. An impact report **computed** by compiling every preset dry against the target engine's
   capabilities (the dry compile already validates golem.fm patches), e.g. "N of M presets lose a
   block".
2. Nothing is deleted: an unplayable block stays in the preset with the state "not on this engine"
   (the block-state reason `engine`, next to `os` and `format`).
3. Refused during a take, in Show mode or during a song; the button says which.
4. Same pattern as the REAPER update (`bridge/reaper_update.py`): stop, start the other engine,
   rebuild, **verify with honest facts** (the audio-thread counter advances, each capture's file is
   really loaded — not "the command was sent" nor `Audio_IsRunning`), roll back automatically on
   failure.
5. Never two engines at once (the sound card is exclusive under ALSA and ASIO). No Cancel during the
   switch; the previous engine stays installed.

**Capabilities everywhere.** The app hides or strikes features the engine lacks, the heartbeat
carries the active engine and its capabilities (`caps.engine`,
[`golemfm-protocol.md`](golemfm-protocol.md)), and the catalog can carry one plugin per engine for
blocks that change.

**Installer default read from the machine**: REAPER found → REAPER; nothing found → the free engine.
Only one engine installed at first; the licence card appears only if REAPER is chosen and unlicensed.

| Step | Content | Needs a second engine? |
|---|---|---|
| E0 | Licence and versions on the engine page, read-only Licenses ▸ Engines, **fix of the licence path**, shape check, file drop, restart refused during a take | No |
| E1 | Capabilities read by the app, `engine` reason on block state, `caps.engine` in the heartbeat | No |
| E2 | Impact report by dry compile | No (testable with a fake descriptor) |
| E3 | Verified switch with automatic rollback | Yes |
| E4 | Installer default read from the machine | Yes |
| E5 | "Confirmed" licence state on Linux | No |
