# Installation v2 — the Golem Engine by default, accounts first

> **Status: FIXED** (decisions of the maintainer, 2026-11-17) — **lots 1–5 DONE on Linux**, proved on a fresh VM on
> 2026-11-18 (§ "The proof on a fresh machine"). Windows and macOS: the engine is not ported yet.
> Descriptive reference of today's installer: [`installer.md`](installer.md). This page is the plan that replaces
> parts of it; each lot moves its text there when it ships.

## Decisions

1. **The Golem Engine is installed by default, always** — whether REAPER is chosen or not. It is golem's own audio
   engine (built from Ardour, GPL): with it golem installs with nothing to buy.
2. **REAPER becomes a checkbox.** Unchecked (the default): golem runs on the Golem Engine. **Checked: REAPER is
   installed and becomes the default engine.** Either way the other engine stays selectable later in
   System ▸ Engines ▸ Audio.
3. **Windows and macOS.** The Golem Engine will be ported there right after this work. The installer is written for
   it now: same step, same pin format (`pins.json`, key `golem_engine`), same checkbox. Until the port ships a system
   without a pinned engine installs REAPER (the step says so and is not a failure).
4. **Accounts come first.** The golem.fm and TONE3000 screens move to the first pages, before the long install, so
   that the **captures download while golem and its effects install**.
5. **Neither account is mandatory.**
   - **TONE3000: pushed hard, with a way out.** No capture ships with golem; without TONE3000 the amps of the factory
     sounds are missing. The screen says so plainly and offers a discreet "Continue without". A hard block would
     forbid an offline install, a test machine, or an install while TONE3000 is down.
   - **golem.fm: optional**, presented as what it adds (backup, sharing, assistant). golem runs without it.
6. **golem-fx**: the prebuilt release stays the default; building from source is the fallback where no binary exists
   for the machine.

## Lots

| Lot | What | Status |
|---|---|---|
| 1 | **The engine as a package.** `golem-engine/golem/tools/bundle.py` builds a self-contained archive (the engine, its libraries, the watcher); `provision/golem_engine.py` + `install-golem-engine.sh` place it in `~/opt/golem-engine` (atomic, previous engine kept as `.prev`, receipt); golem finds the engine by one rule everywhere | **DONE** |
| 2 | **Publishing.** `golem-binaries` workflow `golem-engine.yml` builds the engine from a tag in an `ubuntu:22.04` container, starts the package once, publishes `golem-engine-<version>`; pinned in `provision/downloads.sha256` | **DONE** — release `golem-engine-9.9-g1` (2026-11-18) |
| 3 | **Installer: engine choice.** REAPER as a checkbox (decision 2), the engine step always and first, the default engine written after the engines are placed | **DONE on Linux** (container run, then the VM of 2026-11-18). Windows and macOS keep REAPER until the engine is ported |
| 4 | **Installer: accounts first.** An "Accounts" screen right after the checks; the TONE3000 sign-in is written to the installed folder as soon as golem is copied, and the factory captures download **in the background while the sounds download** (`bridge/factory_fetch.py`) | **DONE on Linux** (VM, 2026-11-18) |
| 5 | **Sign-in round trip** with golem.fm (§ below), then TONE3000 in one click through golem.fm's relay — `installer/early.py`, standard library only | **DONE on Linux**, against the development golem.fm (VM, 2026-11-18); golem.fm's side is not deployed in production yet |

## The proof on a fresh machine (2026-11-18)

A new Ubuntu 24.04 VM (cloud image, 6 cores, 8 GB, no sound card), golem's `main` pushed into it, **the graphical
installer driven through its real screens** from the host over an SSH tunnel.

- **Without REAPER** (lot 3): 7 min 40. Golem Engine 9.9-g1 in `~/opt/golem-engine`, no `~/opt/REAPER`,
  `config/engine.json` = the Golem Engine. golem **starts on it by itself** (dummy backend, the VM has no card), the
  bridge talks to it, no watcher error; a factory patch recalled builds its rig; System ▸ Engines says "REAPER is
  not installed on this machine".
- **golem.fm round trip** (lot 5), against the maintainer's development golem.fm: "Continue with golem.fm" → the
  golem.fm page → "Connect this rack" → back in the installer, "✓ paired — golem-vm". After the install the golem
  itself answers `paired: true, authed: true`.
- **TONE3000 through the relay** (lot 5): signed in by the maintainer in 42 s from the address the installer gave.
- **Captures during the install** (lot 4): the TONE3000 tokens were in the installed folder's `.env` from the first
  second; the background download started when the Python environment was ready (232 s) and ended with the install
  (380 s): 34 of 35 captures, then 35 of 35 after the fix below. The patch that built with 11 blocks without
  captures builds with its 14.

Three defects this run found, fixed:
- **The golem.fm pairing was not written** on Linux: the installer called `provision.desktop connect`, which refuses
  to run there. It now calls the bridge's own function in golem's Python. (The screen said so honestly: "the pairing
  could not be written — pair again in golem".)
- **One factory capture could not be downloaded on a new machine**: TONE3000 now files the Gallien-Krueger 4x10
  impulse response of *Bass Funk Slap* under "experimental", a label golem had no block for. An impulse response
  labelled so is played by the Cab block (`bridge/playable.py`).
- The installer's server stops by itself when no page talks to it for a while: a script must use it at once.

Seen, not explained: after the install **no preset is loaded** at the first start ("nothing loaded yet") when no
golem window is open. Not tried: a machine with a sound card, the REAPER checkbox ticked, Mint and Debian.

## Lot 1 — what exists

- **The package** keeps the shape of the development tree (`build/libs/…`, `build/luasession/luasession`,
  `golem/engine/run.sh`, `share/`), so the launcher and the bridge see no difference. It adds `deps/`: the system
  libraries the engine needs (closure of `ldd`), **except** the base every distribution carries (glibc, ALSA, udev,
  the C++ runtime — a user's plugin may need a newer one than ours). Ardour's GUI is left out, except what the OSC
  surface links (its settings panel): about thirty libraries a fork patch could drop later. 52 MB compressed.
- **Proved**: the whole engine bench (161 checks) run from the unpacked package, with no library loaded from the
  development tree (`/proc/<pid>/maps`: 130 from the package, the rest glibc, ALSA, udev, libstdc++ and the plugins);
  the engine starts in a bare `ubuntu:24.04` container that has none of its dependencies; `golem_engine.py --place`
  into a throwaway home, engine run from there.
- **Where golem looks for the engine**: `GOLEM_ENGINE_DIR`, else a development tree (`~/golem-engine`), else the
  installed package (`~/opt/golem-engine`). Written three times (bridge, provision, launcher) and held together by
  `tests/test_golem_engine_install.py`.
- **The published package** is built on Ubuntu 22.04 (glibc 2.35): it starts in bare `ubuntu:22.04`, `debian:12` and
  `ubuntu:24.04` containers, and the engine bench passes from it on Ubuntu 24.04 (160 of 161: the samples level
  check fails about one run in two on this package and has failed once from the development tree — open, see
  `ardour-plan.md`).
- **`deps/` only fills what the machine lacks.** Putting all of `deps/` in front of the system forced the build
  distribution's versions on everything the engine runs or launches: a system `ffmpeg` died on "undefined symbol"
  under our older glib, and 25 checks went red. `env.sh` now links, in a cache folder, only the bundled libraries the
  machine does not have (7 of 105 on Ubuntu 24.04); a system library of the same name is at least as recent and wins.
- A release tag of the engine must be **lightweight**: Ardour's build reads its version with `git describe`, and an
  annotated tag is what it would return.
- **Not proved**: the engine's own update and rollback from the app.

## Lot 3 — what exists

- **`provision/install.sh`**: the Golem Engine is placed first, always. REAPER (`install-reaper.sh`, `setup-reaper.sh`)
  only with `--engine=reaper`, or when the machine had already chosen REAPER, or as a **fallback** when the Golem
  Engine could not be placed — golem is never left without an engine. The default engine (`config/engine.json`) is
  written **after** the engines are placed: `bridge/engines.py` only accepts an engine that is there.
- **Descriptors**: the Golem Engine is the default (`config/engines/ardour.json`), REAPER second. On a machine where
  the Golem Engine is not installed the default stays REAPER, as before.
- **Installer** (`installer/server.py` `installer_engines`): for the installer "available" means "the installation
  can place it" — a release pinned for this system. The screen shows the Golem Engine as *always installed* and
  **"Also install REAPER"** as a checkbox; the REAPER screen is skipped when it is not ticked; the phases show
  "Golem Engine" always and "REAPER" only when ticked. Where the engine is not ported yet the checkbox is ticked and
  locked, with the reason on the Golem Engine's card.
- The plugin step no longer installs the SWS extension (and its `~/.config/REAPER` folder) when REAPER is not there.
- **REAPER not installed is said** (Linux): its descriptor asks for the binary (`REAPER_BIN`, `reaper` in the PATH,
  `~/opt/REAPER`, `/opt/REAPER`); without it System ▸ Engines shows "REAPER is not installed on this machine" instead
  of offering a switch that fails. Windows and macOS: not done (REAPER is always installed there today).

## Lots 4 and 5 — what exists

- **`installer/early.py`** (standard library — golem is not on the machine yet): `pair/start`, the window leaves for
  golem.fm with `return_to=http://127.0.0.1:<port>/back`, and the installer's server polls `pair/poll`. TONE3000 goes
  through golem.fm's relay with the device token; the PKCE exchange is done here with the source folder's
  `tools/t3k.py`, its `.env` redirected to a private temporary file. **Tokens stay in memory** and never reach the
  screen (`/api/early` returns states only).
- **Where they go**: the TONE3000 tokens into `<target>/.env` right after the "source" step (`Ctx.early_env`); the
  golem.fm device token at the "profile" step, through the very function of Settings ▸ Connect
  (`provision.desktop connect`, secret on stdin).
- **Captures during the install**: after the Python environment is ready, `provision/install.sh` starts
  `python -m bridge.factory_fetch` in the background when a TONE3000 token is in `.env`; it runs while the sounds
  download, and the script waits for it at the end (phase "Amp captures", progress shown; a failure is a warning with
  Retry, never fatal). It is the same work as Settings ▸ Content ▸ Factory, in its own process.
- **The screen** exists where the platform module says so (`early_accounts`, Linux today): golem.fm first ("Continue
  with golem.fm"), TONE3000 enabled once paired, a plain sentence about silent amps, and Next always enabled.
- **Not proved**: a real round trip (golem.fm's side is not deployed), a real relay sign-in from the installer, a real
  capture download outside golem (it would have used the maintainer's TONE3000 session), Windows and macOS (their
  profile steps do not write the early tokens yet).
- Not done: starting the Python environment earlier so the captures also overlap the plugin phases.

## Sign-in from the installer — the round trip (agreed with golem.fm on 2026-11-18)

> **Status: FIXED** — golem.fm's side is coded (not deployed); the installer's side is **not coded**.

golem.fm has **no passwords**: an account is created by the first sign-in (Google, GitHub, or a 6-digit e-mail code,
off in production today). A form inside the installer is therefore not possible; the installer uses a round trip:

1. "Continue with golem.fm": `POST /api/ext/pair/start` as today, then the **installer's server** polls
   `/api/ext/pair/poll` every 2 s (the page itself is about to leave), and the window navigates to
   `approve_url` + `&return_to=http://127.0.0.1:<port>/back`.
2. On golem.fm: sign in or sign up, name the golem, "Connect this rack". golem.fm accepts `return_to` only for
   `http://127.0.0.1`, `localhost` or `[::1]` (any port) and sends the window back with `?paired=1`, or
   `?paired=0&reason=expired|denied`.
3. `/back` carries **no installer token**: the page keeps its one-time token in `sessionStorage` before leaving and
   `/back` reads it there. `paired=1` is a hint for the screen; the truth is the poll, whose answer now also carries
   `name` (the name chosen on golem.fm). A code lives twenty minutes.
4. A golem paired this way is personal; adopting it for a band keeps its own screen on golem.fm.

**TONE3000 right after**: a paired golem signs in through golem.fm's TONE3000 application (`/api/ext/t3k/relay`),
which needs nothing per account — it works for an account created a minute earlier.

## Without golem.fm

A golem that is not paired still needs, for TONE3000, the user's own publishable key and a declared redirect
address. To make TONE3000 one click **without** golem.fm, golem would need its own registered TONE3000 application
with a `localhost` redirect — an account-side step for the maintainer (**not decided**, and not checked against
TONE3000's documentation), then no key for anyone. Until then the order that costs the user the least is
**golem.fm first (one page), then TONE3000 in one click**.
