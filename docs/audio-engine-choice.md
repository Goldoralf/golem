# Choosing the audio engine

> **Status: PARTLY CODED** — two engines are selectable: the **Golem Engine** (the default, on Linux and Windows where
> it is installed) and **REAPER**. Coded: engine descriptors, the local choice, the `/api/engines` routes, the
> **Settings ▸ Engines ▸ Audio** page, the installer's "Audio engine" screen, **the switch between engines with its
> automatic return** (§2, `bridge/engine/switch.py`) and the block state "not on this engine". Still **PROPOSED**
> (§5): the impact report before a switch, moving the REAPER licence into the engine page, the installer default read
> from the machine.

The second engine itself (the Golem Engine, built from Ardour) is described in
[`ardour-engine.md`](ardour-engine.md) and [`ardour-plan.md`](ardour-plan.md). This page covers how an engine is
described, chosen, switched and installed.

## 1. Engines are data

Each engine is a descriptor in `config/engines/<id>.json`; the code never hard-codes REAPER. The
same doctrine as pedalboards ([`pedalboards.md`](pedalboards.md)).

| Field | Meaning |
|---|---|
| `id`, `name`, `by` | Identity shown on the card |
| `license` | `commercial` or `gpl-2.0-or-later` (the page shows "commercial" / "free · GPL") |
| `buy_url` / `sources_url` | Where to buy it, or where its sources are |
| `order` | Card order |
| `default` | The engine proposed when nothing is chosen (the Golem Engine: `true`) — used only where it is available, see `default_id()` |
| `selectable` | Whether golem ships an engine behind this descriptor at all |
| `unavailable_reason` | Shown when not selectable |
| `platforms.<linux\|win32\|darwin>` | `{available, reason?, requires?}` per OS. `requires` says what must be on the machine for the engine to be selectable: a file under a folder (`file`, with `env` or `default` folders), a file named by a variable (`env_file`) or a program on the PATH (`which`), and the `reason` shown when it is missing ("Golem Engine is not installed on this machine") |
| `summary` | One line on the card |
| `capabilities` | One entry per feature of `config/engines/features.json`: `yes`, `no` or `planned` |

`config/engines/features.json` lists the features in page order with their UI labels: Lanes &
scenes, NAM & IR, Recording, Backing, Click, MIDI clock, Looper, Drum machine, Samples, Standards,
Riff, Kill switch, Previews, Reamp. Both engines declare all of them `yes`. The Golem Engine's descriptor
(`ardour.json`, `selectable: true`; available on Linux and Windows, not on macOS) says of its own capabilities that they
are the **target**, not a measurement — the measurements are in [`ardour-plan.md`](ardour-plan.md).
The `blocks` key of `features.json` maps a feature to the block types it carries (`looper` → `looper`, `samples` →
`sample`, `pads`…, `engines.feature_of_block()`): a block whose feature the active engine does not declare
`yes` is `unavailable` with reason `engine` ([`block-status.md`](block-status.md)).

**Single reader.** `bridge/engines.py` (standard library only) is used by the bridge, the graphical
installer (`installer/server.py`) and `provision/install.sh`:

- `descriptors()` — every engine with its `available` and `reason` for this OS. Available means all three:
  `selectable`, `platforms.<os>.available`, **and** what `platforms.<os>.requires` asks for is on the machine
  (`availability`). An engine golem ships but that is not installed here is therefore not selectable, and says why.
- `default_id()` — the engine marked `default` **if it is available here**, otherwise the first available one.
- `current()` — the choice in `config/engine.json`; if the file is missing, or names an engine that
  is no longer available, it falls back to `default_id()`. A rack with no choice file and no Golem Engine installed
  therefore runs REAPER with no action; with both engines installed and no choice file, it runs the Golem Engine.
  The installer writes the file, so this fallback concerns racks installed before it existed.
- `write_choice(id, set_by=…)` — writes `config/engine.json` after checking availability; raises
  `ValueError` otherwise. It starts and stops nothing: the switch is `bridge/engine/switch.py`.

`config/engine.json` is **local state** (not versioned).

## 2. Routes and page

| Route | Behaviour |
|---|---|
| `GET /api/engines` | `{current, platform, features[{id,label}], engines[]}` |
| `POST /api/engine {id}` | Writes the choice and, when it differs from the running engine, **starts the switch** (`engine_select` in `bridge/routes_system.py`). Refused with **409** and `current`: an unavailable engine (with its reason), a take being recorded, a switch already running. Accepted → `{ok, current, switch_pending}`, plus `switch` (the status below) when a switch started. |
| `GET /api/engine/switch` | Where the switch is: `{phase, from, to, error?}`, `phase` being `idle`, `stopping`, `starting`, `remounting`, `done`, `reverting` or `failed`. |

**The switch** (`bridge/engine/switch.py`), in the background, one at a time:

1. `stopping` — the previous engine's process stops and frees its OSC port;
2. `starting` — the new one becomes the bridge's active engine (`engine.use`), its OSC return opens, it starts;
3. `remounting` — once it answers, the monitor sees a new process and rebuilds the current patch, as after a crash;
   the switch waits for the live map to say so;
4. `done` — or, if the new engine does not answer in time (45 s to start, 45 s to rebuild): `reverting` (the previous
   engine, its choice and its process are put back), then `failed` with the error.

**Settings ▸ Engines ▸ Audio** (`#/system/sys/audio-engine`, `app/page-engine.js` `EnginePanel`): one
card per engine, the Golem Engine first. The active engine shows "● Selected · running|stopped"; an unavailable
one shows its reason and a disabled "Select" button. A card names only the features its engine **lacks** ("Not on
this engine: …") — no summary, no feature count (the maintainer, 2026-11-17). "Select" takes two taps: the first arms
it for 4 seconds ("Tap again — sound stops for a few seconds"), the second starts the switch. A strip follows the
phases, then says "Engine switched." or, on failure, the error and that golem went back to the previous engine.

## 3. Installation

- **Graphical installer** (Linux, Windows, macOS — [`installer.md`](installer.md)): an
  **"Audio engine"** screen between "Accounts" and "Reaper" (`installer/ui/installer.js`). Since
  [`install-v2.md`](install-v2.md) (2026-11-18) the Golem Engine is **always installed** and REAPER is a checkbox:
  checked, REAPER is installed too and becomes the default engine; unchecked, the "Reaper" screen is skipped. Where the
  Golem Engine is not ported the box is checked and locked — golem never installs without an engine — and the Golem
  Engine's card says why.
- **`provision/install.sh --engine=<id>`** (Linux): `--engine=reaper` installs REAPER next to the Golem Engine and
  makes it the default; `--engine=ardour` installs the Golem Engine alone; without the option a new install takes the
  Golem Engine if it could be placed, otherwise REAPER, and a machine that already chose (`config/engine.json`) keeps
  its choice and its REAPER. The choice is written after the engines are placed, since `bridge/engines.py` only
  accepts an engine that is there.
- **Windows**: the setup places the pinned Golem Engine package next to REAPER (`provision/desktop.py`,
  `provision/golem_engine.py`); without a pin it says so and golem plays on REAPER. **macOS**: REAPER only.
  Neither has a command-line installer; their bootstraps open the graphical installer.

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

**Switching engines.** Points 4 and 5 are **coded** (§2), and of point 3 the refusal during a take; points 1 and
the rest of 3 are not. Point 2 is coded (block state `unavailable`, reason `engine` — `bridge/blockstatus.py`).

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
blocks that change. *Today:* the block-status capabilities report the active engine's id and version
(`blockstatus.caps()`: `engine`, `engine_version`), and the catalogue has a per-engine layer
(`library/catalog/effects-golem-engine.json`); the per-feature capabilities are not sent.

**Installer default read from the machine**: REAPER found → REAPER; nothing found → the free engine.
Only one engine installed at first; the licence card appears only if REAPER is chosen and unlicensed.
*Superseded by [`install-v2.md`](install-v2.md):* the Golem Engine is always installed and REAPER is a checkbox (§3).

| Step | Content | State (2026-11-22) |
|---|---|---|
| E0 | Licence and versions on the engine page, read-only Licenses ▸ Engines, **fix of the licence path**, shape check, file drop, restart refused during a take | Not coded: the licence is still in Settings ▸ About ▸ REAPER (§4) |
| E1 | Capabilities read by the app, `engine` reason on block state, `caps.engine` in the heartbeat | Partly: the engine page lists what an engine lacks, the `engine` reason exists, the engine's id and version are reported; per-feature capabilities are not sent |
| E2 | Impact report by dry compile | Not coded |
| E3 | Verified switch with automatic rollback | **CODED** (§2) |
| E4 | Installer default read from the machine | Superseded by [`install-v2.md`](install-v2.md) |
| E5 | "Confirmed" licence state on Linux | Not coded (Windows reads it, §4) |
