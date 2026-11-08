# The installer

> **Status: CODED** — the one-line bootstrap and the graphical installer for Linux, Windows and
> macOS, the `golem desktop` / `golem server` launch model, and the library manifest. Linux and
> Windows have been run end to end on clean virtual machines; the **macOS** module has never run on
> a Mac ([`platforms.md`](platforms.md)). The **graphical uninstaller** is a mode of the same server
> (`--uninstall`, Linux, [`uninstall.md`](uninstall.md) §4). A bootable image and `golem update` are **not
> built**.

Related: [`platforms.md`](platforms.md) (per-OS details and manual install),
[`audio-engine-choice.md`](audio-engine-choice.md) (the "Audio engine" screen),
[`rack-hardware.md`](rack-hardware.md) (OS tuning), [`release-signing.md`](release-signing.md).

The truth stays in `provision/`: the installer is a window onto the same scripts, never a second
implementation.

## 1. Bootstrap — one line, no dependency

| OS | Command | Script |
|---|---|---|
| Linux | `curl -fsSL https://get.golem.fm \| sh`, or `./install-linux.sh` in a clone | `provision/bootstrap.sh` (`install-linux.sh` calls it with `GOLEM_SRC`) |
| Windows | `irm https://get.golem.fm/win \| iex`, or double-click `install-windows.cmd` in a clone | `provision/bootstrap.ps1` |
| macOS | double-click `install-macos.command` in a clone | `install-macos.command` |

**Linux** (`bootstrap.sh`, no sudo):

1. Checks the minimum: x86-64 (blocking), Ubuntu 24.04 (warning), `python3`, `curl` (only to download: not
   needed from a clone).
2. Fetches the **latest release** — the GitHub release marked latest, else the highest `vX.Y.Z` tag by version
   number (`sort -V`; never the first tag the API lists: its order is not a version order) — (`GOLEM_REF` forces a tag; `GOLEM_REPO` another repository;
   `GOLEM_SRC` a local tree) into `~/.cache/golem-installer/golem-<tag>`, with `git clone --depth 1`
   if git exists, else the release archive. When `GOLEM_RELEASE_SIGNERS` is set in the served
   script, the tag must carry a valid signature or the bootstrap stops
   ([`release-signing.md`](release-signing.md)).
3. Starts `installer/server.py` and opens the browser. Nothing is installed before the user has seen
   the screens.

**From a clone** (`./install-linux.sh`, 2026-11-03): refuses to run as root (under `sudo`, `$USER` and `$HOME` are
root's: audio group, `~/.vst` and shortcuts would land in root's account), then runs `bootstrap.sh` with
`GOLEM_SRC` = the clone — nothing is downloaded, and the installer installs **in place** (a git tree outside the
cache is its own target, `installer/server.py`). `GOLEM_INSTALLER_DRY=1` shows the screens without installing.

**Windows** (`bootstrap.ps1`, no administrator rights): checks Windows x64 build ≥ 19041, finds a
Python ≥ 3.10 or installs **Python 3.12.10 for the user only** (`%LOCALAPPDATA%\Programs\Python`,
PATH untouched, hash **and** "Python Software Foundation" signature checked), fetches golem into
`%LOCALAPPDATA%\golem-installer`, then launches the installer under `pythonw.exe` and returns.
The Python pin is **copied** into the script (it runs before the repository exists);
`tests/test_installer_windows.py` checks it matches `provision/windows/pins.json`. The file is
**ASCII**: Windows PowerShell 5.1 reads a BOM-less `.ps1` as cp1252, and a UTF-8 "✓" contains byte
0x93, which it takes for a quote. The elevated script carries a BOM.

**macOS**: finds Python 3.12 or 3.13 (onnxruntime 1.23.2, the bridge's macOS pin, has no wheel for 3.14+), sets `SSL_CERT_FILE=/etc/ssl/cert.pem` (python.org's Python has no
certificates before "Install Certificates") and opens the installer. From a clone, it installs **in
place**, as on Windows.

## 2. The graphical installer

`installer/server.py` is an HTTP server in the **standard library** (nothing to install before
installing), bound to `127.0.0.1` on a free port, protected by a **one-time token** passed in the
URL (`?t=`) and then in the `X-Golem-Token` header of every call. Screens are Preact/htm without
build (`installer/ui/`), same tokens and look as the app. `--dry` makes every step run
`installer/dry_step.py` (Python, since Windows has no bash): nothing is touched, which is how the
screens are checked with Playwright.

`--uninstall [--root DIR]` turns the same server into the **uninstaller** (Linux only): it copies
itself to `/tmp/golem-uninstaller-<random>/`, re-executes from there, serves `ui/uninstall.html` +
`ui/uninstaller.js` with the same token, CSS and askpass, and runs `provision/uninstall.py` and the
backup CLI ([`uninstall.md`](uninstall.md) §4). The mode's state and routes live in
`installer/uninstaller.py`; `server.py` keeps `/api/state`, `/api/log`, `/api/sudo`, `/api/quit`.

The server knows no OS: it picks **one** platform module (`installer/platform_linux.py`,
`platform_windows.py`, `platform_macos.py`) with the same interface — `NAME`, `PRIVILEGE`
(`sudo` | `uac`), `STEPS`, `default_dir()`, `ui()` (every OS-dependent sentence on screen),
`checks()`, Reaper detection and install, sizes, `run_step()`. What Windows and macOS share (copy
without overwriting local state, reference DIs, disk and network probes) is in
`installer/desktop_steps.py`.

On Windows and macOS the installer opens as an **application window**: Chrome/Edge in `--app` mode,
1120×780, with its own profile (Windows: `%LOCALAPPDATA%\GoleM\installer-browser` — the `GoleM` folder name is an identifier, kept as is). That makes the
browser process ours: the server stops when the window closes — after a running step finishes, never
in the middle of an elevated step. External links open in the user's browser.

On **Linux** (CODED 2026-11-03) the same application window: a Chromium in `--app` mode (`chromium`,
`chromium-browser`, `google-chrome`, `brave-browser` — the list of `provision/golem`), else **Firefox as a new
instance** on a dedicated, bare profile (a `user.js` that silences the first run, a `userChrome.css` that hides tabs,
address bar and bookmarks), else a tab (`xdg-open`). Before, `xdg-open` alone put the installer in a background tab
of an already open Firefox — GNOME on Wayland does not raise a window another program wakes — while the terminal
said "open this link". A browser installed as a **snap** cannot write under a hidden folder of the home: its profile
lives in `~/snap/<name>/common/golem-installer`. The **uninstaller** stays in a tab: the dedicated profiles are among
what it removes.

`golem desktop` needs that Chromium too (window size, scale, remembered geometry), so `install.sh` installs one when
none is there (2026-11-03): first a **real apt package** `chromium` (Debian, Linux Mint — Mint blocks snapd), recorded
in the receipt like every package golem asked for; on Ubuntu, where `chromium` and `chromium-browser` only redirect to
the snap (they depend on `snapd`, `lib-packages.sh golem_chromium_deb`), the **snap**. Neither possible: a named
warning, and golem opens in a browser tab.

### Screens (`installer/ui/installer.js` `SCREENS`)

| # | Screen | What it does | Blocks if |
|---|---|---|---|
| 0 | **Before you start** | How long it takes (the sum of the measured phases below, for the chosen packs — Linux; "half an hour" where nothing is measured yet), **click each button once**, keep the window open, stay connected and plugged in, what will be asked (the password or the system prompt, once), not before a gig. "I am ready →" | — |
| 0b | **Instrument** — *What do you play?* (2026-10-27) | Guitar (default), Bass, Keys, Drums or Voice (`POST /api/config {instrument}`). `step_profile` of each OS writes `config/first-run.json` `{instrument}` in the installed folder (`Ctx.write_first_run`, also in `--dry`, into the dry folder). At its first start, after the factory seed and before the startup recall, the bridge applies it **once** and removes the file (`bridge/first_run.py`): `config/instrument.json` keeps the instrument, and input 1 of a sound card seen for the first time takes its role (`inputmap._seed`: guitar, bass or voice; Keys and Drums come in by USB-MIDI, so input 1 stays guitar; a voice on input 1 leaves input 2 of the Volt unassigned). The instrument's factory bank (`factory-<instrument>`) goes on the foot **if no setlist was chosen yet** (`config/setlist.json` absent). Guitar only: that bank opens at startup on its **first entry** (Jazz Clean), **if no startup home is set** (`config/.startup.json` absent). An install over an existing one changes nothing the user had set. Both files are local state (`.gitignore`) | — |
| 1 | **Checks** | OS, architecture, memory (8 GB recommended), free space, Internet, rights, Python — green / orange / red, each with its explanation | a red |
| 2 | **Audio engine** | Choose the engine; the default (REAPER) is pre-selected, unavailable engines greyed | — |
| 3 | **Reaper** | Detected: version and path — on Windows **wherever it is** (`reaper_license.windows_exe`: `REAPER_BIN`, the path golem remembered in `%LOCALAPPDATA%\GoleM\reaper-path.txt`, the registry key REAPER's installer writes and its *Apps* entry, then Program Files; a portable REAPER — `reaper.ini` next to `reaper.exe` — keeps golem's files in its own folder). Missing, Windows adds two gestures: **"I already have it"** (a folder holding `reaper.exe`, checked, then remembered — `POST /api/reaper/locate`) and **"Install it in"** (a folder, Program Files by default, passed as `-ReaperDir` → NSIS `/D=`, remembered after the install). Launch, engine update, firewall rule and uninstaller follow the same path. Missing: **"Install Reaper <pinned version> for me"** (pinned and hash-checked; Linux `~/opt/REAPER` without sudo, Windows/macOS through the elevated step) or the reaper.fm link; re-checks every second. Below, whether REAPER was found or just installed, the card **"Your REAPER licence — optional"**: paste the text or pick the `.rk` file (read in the page, sent as text, `POST /api/reaper/license`). The server writes `reaper-license.rk` into REAPER's resource folder of this OS (created if missing) with the **same code as Settings ▸ About** (`bridge/reaper_license.py`, loaded by path); text, not empty, ≤ 64 KB. A licence already there shows "✓ a REAPER licence is already on this computer" with a "Replace" link (`GET /api/reaper` → `license_present`, never the content). The content is never returned, logged (live log included) nor put in `/api/state`. Receipt prior `reaper.license_present` (Linux, Windows): written at once if the receipt exists, else held and written after the *source* step creates it. `--dry`: nothing written, the card says "saved" | REAPER missing |
| 4 | **Folder** | Install folder (`~/golem`). Starting with the machine is no longer asked here: it is a switch in the app (§4) | — |
| 5 | **Size** | Size per component and the optional sound packs against free space. No capture ships with golem: they come from golem.fm or TONE3000 after pairing | total > free |
| 6 | **Install** | Linux: the password (checked, kept in memory only). Then the **phases** with their times and a countdown (below); the raw output is folded under "Show details". **Install now** greys out on the first click. Retry restarts from the failed step | until done |
| 7 | **Connect** | Two cards of the installer's own, **golem.fm** and **TONE3000** (§6). Linux: golem runs (step *start*), so the cards drive it through the installer's relay — golem.fm pairing by device code ("Pair this golem", the code, "Open golem.fm ↗", polled until paired) or a pasted device token; TONE3000: once golem.fm is paired, the sign-in goes **through golem.fm, with no key** (step 1 "Through golem.fm"); a golem without golem.fm opens "No golem.fm? Use your own TONE3000 key"; then sign-in (OAuth) and factory captures. `.env.example` carries no TONE3000 key, and its old placeholder (`t3k_pub_colle_ta_cle_ici`, copied by every install) is read as no key (`tools/t3k.py own_key`) — it made a new golem say "key saved". Windows/macOS: golem is not running yet — the same two cards hold two fields (golem.fm token, TONE3000 key) written without starting golem (`provision.desktop connect`, secrets on stdin), and "Factory sounds" starts golem as a server. Both optional, Finish always possible | — |
| 8 | **Done** | Two ways out, on every OS: **"Open golem"** (the window — Linux: the app at `http://localhost:8770/app/`; Windows/macOS: `/api/finish` starts golem with its window and closes the installer) and **"📱 Continue on a tablet"** (`POST /api/tablet`: golem **server** is started if it does not answer — Linux `provision/golem server`, Windows/macOS `provision.desktop server`, detached — then the screen polls `GET /api/tablet` and shows the address that works, its QR (`/api/tablet/qr`, relayed from the bridge's `/api/network/open-qr`) and, when no admin device exists, a pairing code created **once**, with `…/app/pair.html`). The page never calls `:8770`: three bridge routes are added to the relay (`GET /api/network/open-url`, `GET /api/auth/devices`, `POST /api/auth/pair-code`). `--dry`: `dry_bridge` answers (a `.local` address, no admin device, a code; a placeholder QR), nothing is started. Then next steps, the REAPER licence reminder; Windows/macOS: a Vital card (re-checks the disk every 3 s) and, on macOS, "To install yourself" (`manual` in `provision/macos/pins.json`) | — |

### The Install screen in phases (CODED 2026-10-23)

Before, the screen showed the shell output: compiler warnings read as errors, and with nothing changing for minutes
people clicked "Install now" again and again (VM test 2026-10-23). Now it shows **phases** — what the user reads —
apart from **steps** — what the server runs (`installer/phases.py`):

- The platform module declares them: `phases(S)` → `[{id, step, label, est}]` (Linux: 10 phases; a platform without
  `phases` gets one phase per step and no countdown — Windows and macOS today). A step opens its first phase when it
  starts; `provision/install.sh` switches phase with marker lines printed only under the installer
  (`GOLEM_INSTALLER=1`, function `mark`): `@@phase <id>`, `@@sub <text>` (the running phase's sub-line, e.g. "Prisma
  (Grit block) — 3 of 4"), `@@warn <retry-id>|<text>`, `@@progress <done> <total>`
  (measured progress, MB). The server takes markers out of the log shown under Show details.
- **Trace on disk and silence (CODED 2026-10-24).** A Windows tester sat 16 min on "golem itself" with no new line;
  after a relaunch nothing said where it had stopped, the trace lived in memory only. Every line now also goes to
  `golem-install-<date>.log` (or `golem-uninstall-…`) in the temp folder, named under Show details. `/api/state` gives
  `quiet` (seconds since the running step's last line or marker) and `stall_secs` (180): past it, the screen says
  "Nothing new for N min" and offers **■ Stop this step** (`POST /api/stop-step`: the step's command and its children
  are killed, the step fails, Retry restarts from it). An elevated step (UAC, `-Verb RunAs`) cannot be stopped from the
  unelevated installer: the screen says to look for a Windows prompt. Python steps run unbuffered
  (`PYTHONUNBUFFERED`), the Windows setup step with `python.exe` rather than the installer's `pythonw.exe`, and
  `provision.desktop setup` announces each of its stages (REAPER scripts, capture reader, ASIO driver, Python
  environment, pip, MIDI check, desktop plugins).
- **Estimate.** Each phase carries its measured time (full install in a VM, Ubuntu 24.04, 6 cores, packs
  di + piano + guitar: 28 min). The build phase is scaled by the number of cores, the sounds by the MB of the chosen
  packs (3 MB/s — two VM installs measured 1.85 and 5.1 MB/s). While running, the time left is corrected by the
  speed seen on finished phases (real / planned, bounded 0.5–3, only after 90 s of planned time), and a running phase
  always has a few seconds left — never "0". Network-bound phases (`learn: False`: system packages, sounds) neither
  teach that speed nor follow it: a slow apt mirror (220 s instead of 130, VM run 3) inflated the build estimate by 30 %.
- **Sounds: measured, not guessed.** The network varies threefold from day to day, and the speed of the build phases
  says nothing about it (VM 2026-10-23: 31 min announced, 11 real). `fetch-assets.sh` (`fetch_watched`) says every
  5 s how many MB of the packs are downloaded; after 15 s and 3 % done, the phase's time left comes from that
  measured rate, and its sub-line shows "Drums (Aasimonster) — 3 of 3 · 1.1 GB of 3.3 GB".
- **Missing but not fatal.** A third-party plugin that fails to install does not stop the install (§ Rules); it now
  says so on its phase, in English, with what it changes (`soft_fail <id> <terminal text> <screen text>` in
  `install.sh`). The install ends in **⚠** ("golem is installed — 2 things will not play yet") and each line that has
  a script offers **↻ Try again** (`POST /api/retry-item`, `platform_linux.RETRY`: that script alone, after the
  install). Vital, which no package installs, is said too, without a retry. The Done screen says them again.
- **Windows (2026-10-24).** `platform_windows.phases` gives the same screen: one phase per step, short labels, the
  times measured on a bare Windows 11 VM (4 min 34 in all; the system step includes the UAC click and is
  network-bound, like the sounds). The installer window is fitted to the screen's work area and centred
  (`window_geometry`: on a 1280×800 screen the taskbar hid Back and Next). **Open golem** keeps the installer open
  with "Starting golem…" until golem answers (`FINISH_WAIT_S`, 150 s): the first start takes ~50 s before golem's
  window shows, and the installer used to close at once on an empty screen. The firewall rule names the **python.exe**
  that serves the bridge (`bridge_python`), not the installer's pythonw.exe — Windows asked "Allow Python?" at the
  first start.
- **Reference DIs.** Not recorded yet ([`preset-preview.md`](preset-preview.md)): no release `di-refs-v1`, its URL is
  not pinned, so `fetch-assets.sh` says "not published yet" without trying (it used to print a refusal that read as a
  failure), and it now targets `library/di-refs/`, where the bridge reads them (it was `library/di/`). Windows and
  macOS (`desktop_steps._sound_di`) do the same, and check the archive's pinned hash, which they did not.
- **Prebuilt plugins (2026-10-23).** The plugins golem used to compile at every install — the IR convolver and NAM
  with our crash fixes, Prisma, Spectral Compressor, PaulXStretch, GoleM Freeze — are built once by a GitHub Action in
  the **public** repository [`Goldoralf/golem-binaries`](https://github.com/Goldoralf/golem-binaries) (same pinned
  commits and patches, `-march=x86-64-v3` at most, no AVX-512) and published as release `linux-plugins-v2` (v1 until 2026-11-03). Each
  `install-*.sh` first runs `provision/fetch-prebuilt.sh` (archive pinned in `downloads.sha256`; the patch marker is
  checked as for a local build; the libraries the binaries load are installed by name, `lib-prebuilt.sh
  runtime_libs`), and compiles only if that fails or `GOLEM_BUILD_FROM_SOURCE=1`. The phase "Plugins built for
  golem" then takes ~30 s instead of ~12 min; a script that must compile says so (`@@est-add`, its measured time)
  and the countdown grows accordingly. GoleM Freeze is golem's own code: its prebuilt binary is used only while
  `plugins/` hashes to `FREEZE_SRC_SHA` (`install-spectral.sh`), else it is compiled — a change to the block needs a
  new `linux-plugins-vN` release. The same repository hosts `nam-0.7.15-golem` (Windows, macOS) and
  `sfizz-1.2.3-golem`: a release of the private golem repository answers 404 to an installer not signed in to GitHub.
- The NAM fix fetches Eigen from gitlab.com, which refuses "due to load" at times (2 VM installs out of 3):
  `install-nam.sh` retries the submodules 4 times (0, 20, 60, 120 s). Git checks the pinned commits, so a retry
  cannot bring anything else. A prebuilt binary in a release would remove both the wait and the dependency.
- The sudo keep-alive loop of `install.sh` writes to `/dev/null`: its orphaned `sleep 60` held the output pipe and the
  installer waited up to a minute after "Provisioning terminé" (53 s measured).

**Packs.** `di` (reference DIs for preset previews, required, from release `di-refs-v1`,
[`preset-preview.md`](preset-preview.md)); optional `piano` (Salamander grand piano) and `drums`
(a multi-mic kit) from their original sources. A missing DI release is **not fatal**.

### Steps

| Linux | Windows | macOS |
|---|---|---|
| **source** — clone (or `git pull --ff-only` over an existing install) from the installer's copy, `origin` reset to the public repository; an extracted archive is copied with `rsync`, then linked to the repository once git is installed ([`update.md`](update.md) §2) | **source** — copy into the chosen folder (`~\golem`); over an existing install the code is updated and **local state is never overwritten** (`presets`, `sets`, `mappings`, `config`, `setlists`, `recordings`, `assets`) | **source** — same as Windows |
| **system** — `provision/install.sh` (`--light` when no pack is chosen, `GOLEM_PACKS=<list>`) | **system** — **one UAC prompt** for `provision/windows/install-system.ps1`: Visual C++ runtime (without it `python-rtmidi` does not load: no foot controller, no MIDI), REAPER if missing, NAM VST3, AVL Drumkits, sfizz, Vitalium (PawPaw), Proteus (the Boost block), firewall rules; the bridge setup then adds, without admin rights, Airwindows TapeDelay2 and the Dragonfly Hall, Plate and Room reverbs (`provision/airwindows.py`, `provision/dragonfly.py`) | **system** — **one administrator prompt** (`osascript … with administrator privileges`) for `provision/macos/install-system.sh`: REAPER (`.dmg`), NAM VST3, AVL Drumkits, sfizz, Vitalium (PawPaw, Rosetta first), the Dragonfly Hall, Plate and Room reverbs, Proteus (the Boost block) |
| — | **bridge** — `python -m provision.desktop setup` | **bridge** — same |
| — | **sounds** — reference DIs, and the `guitar` pack (Shinyguitar, the Standard block's pompe) when chosen, checked against `provision/downloads.sha256` (both non-fatal) | **sounds** — same |
| **profile** — `config/engine.json`, `provision/install-desktop.sh` (icons, `golem` command: desktop and server, always both — no autostart, no hardening) | **profile** — `golem.cmd` (console launcher for troubleshooting) and shortcuts "golem", "golem server" (Desktop, Start menu) and "Stop golem" (Start menu) | **profile** — golem.app, golem server.app, Stop golem.app in `~/Applications` |
| **start** — `provision/start.sh`, then waits up to 90 s for the bridge on `:8770` | (golem starts from the Done button, so it never opens on top of the installer) | (same) |

**Pins.** Windows and macOS components are pinned in `provision/windows/pins.json` and
`provision/macos/pins.json` (version, URL, sha256 — read with `plutil` on macOS). The Microsoft
runtime has no fixed URL: its **signature** is checked instead. A component already present is left
as is (never downgrade someone's REAPER) and is judged after installation. Unsigned third-party
installers (AVL, sfizz, PawPaw, Proteus) and the Dragonfly archive are trusted only through their pinned hash.

### Privileges

- **Linux (`sudo`).** The password serves the installation only. No `sudo` sees a terminal: it is
  passed through an **askpass helper that reads it from the job's environment**
  (`SUDO_ASKPASS` + `GOLEM_SUDO_PW`, `platform_linux._askpass`). The helper never contains the
  password, it is **never written to disk**, and it is forgotten when the installer closes; the helper's
  folder (`/tmp/golem-installer-*`) is removed then too, whatever the way out — button, Ctrl-C, closed
  terminal or signal (`platform_linux.cleanup`, called by `server.py`). A thread
  refreshes the sudo ticket every 50 s (`keepalive`) so a long sound download does not hit an
  expired cache.
- **What the install grants for later.** Two root actions are needed at runtime: the CPU governor
  (the Dashboard ⚡) and Wi-Fi switching ([`network.md`](network.md)). They work through **two narrow
  NOPASSWD rules** (`provision/setup-perf-sudo.sh`, `provision/setup-net-sudo.sh`) on **root-owned
  copies** in `/usr/local/sbin`, limited to a few verbs; the bridge calls `sudo -n`, so it can never
  raise a prompt. The password itself is not kept.
- **Windows / macOS (`uac`).** No password field: one system prompt, for the one script that writes
  system locations. Its log is written to a file (Windows: a stream shared for read and write) that
  the installer reads live. Refusing the prompt is a stated failure with Retry.

### Rules learned the hard way (keep them)

- A third-party package source that breaks must never kill the install: the sfizz step is
  **non-fatal**, falls back to the repository's `.deb` files, and `install.sh` removes our APT source
  at start (a broken `sources.list.d` entry poisons every later `apt`, including the user's).
  `apt-get update` is non-fatal; `apt-get install` is.
- Package names are **read** from the repository listing, never guessed.
- A presence test is done on the path (`[ -d … ]`), never on a pipeline under `pipefail`.
- **Everything the install creates is written down** in the install receipt
  (`~/.local/share/golem/install-receipt.json`; Windows `%LOCALAPPDATA%\GoleM\install-receipt.json`,
  [`uninstall.md`](uninstall.md) §2, §9.2), with the state of
  the machine **before** it — through one helper, `provision/receipt.py` (bash scripts source
  `provision/lib-receipt.sh`). A failing helper never breaks the install. `apt-snapshot before` /
  `after` frame **each** `apt-get install` / `dpkg -i`, so a package that was already there is never
  counted as golem's. `tests/test_receipt.py` fails if a provision script writes to `/etc`,
  `/usr/local`, `~/.lv2`, `~/.vst3`, `~/.clap`, `~/.local` or `~/.config/REAPER` without it.
- A user's file in the way of a golem link (`__startup.lua`, `FXChains`, …) is moved aside as
  **`<name>.golem-orig`**, never `.bak` (a user's own `.bak` must not pass for ours); the receipt says
  where, so uninstalling puts it back. An old `.bak` left by an earlier golem install is left alone.
- On Windows, `setup` writes `verchk=0` to `reaper.ini` (REAPER's "New Version Notification" modal
  blocked `__startup.lua`), and the system step adds an **inbound block** rule for `reaper.exe` so
  Windows does not ask about REAPER's OSC port.

## 3. Updating REAPER after installation

Changing REAPER's version is a gesture of **Settings ▸ About ▸ REAPER**, with the rack's rule
(`bridge/reaper_update.py`): the main button targets the pin, the latest Cockos release installs in
two taps without guarantee (sha256 logged), and a failed start rolls back. On Windows the mechanics
are `bridge/desktop_reaper.py`: the official installer is downloaded and checked by the bridge,
REAPER is closed politely (project saved), then `install-system.ps1 -ReaperUpdate` runs **elevated
— a UAC prompt on the PC screen** (nobody can approve it from a phone; the screen says so). It keeps
the active install as `REAPER (x64).golem-prev`, installs silently, checks the exe version, restarts
REAPER and waits 60 s for it to run with its OSC link, otherwise swaps back (`-ReaperSwap`). On
macOS updating from golem is not available.

## 4. One installation, two uses: `golem desktop` and `golem server`

There is **one installation**, the same on every OS. At each launch you choose whether golem opens a
window on this computer. The engine is the same in both cases (bridge + hidden REAPER), and you
switch between them **without stopping the sound or restarting REAPER**.

| Command (Linux `provision/golem`) | Does | For |
|---|---|---|
| `golem desktop` (and `golem` alone) | Starts golem if needed, then opens **the window** (the app in a 1024×600 tablet shell). If golem runs already, only opens the window. `--fullscreen`, `--dev` (show REAPER), `--reset` (window size) | Laptops and PCs |
| `golem server` (aliases `rack`, `headless`) | Starts golem **without a window** and prints the address, plus a pairing code when no admin device exists | A tablet or phone is the screen |
| `golem window` | Only the window of `golem desktop`, on a golem that runs already (what "Show on this computer" runs) | |
| `golem stop` | Stops REAPER, the bridge and the windows | |
| `golem status` / `golem restart` | One-line state / stop then start | |
| `golem pair` | A six-digit pairing code for the first tablet ([`SECURITY.md`](../SECURITY.md)) | |
| `golem autostart on\|off\|status` | Start golem server with the machine — the same as the switch in Settings ▸ System ▸ Dashboard (below) | |
| `golem start` / `golem ui` | The stack with REAPER visible / a plain 1024×600 window (debugging) | Development |
| `golem phone` | The phone Companion in a phone shell | **Development only**: no icon offers it |

On Windows and macOS the same model is `python -m provision.desktop start|server|stop|restart|autostart`
and the shortcuts/apps of the profile step.

The bridge serves the app on the network in **both** uses, so a tablet can join a desktop golem at
any time. `GOLEM_BIND=127.0.0.1` closes it.

> **Switching and the dedicated machine: FIXED 2026-10-16 — CODED 2026-10-16** (tested with a stubbed API and the
> installer in `--dry`; not yet run on a real machine or VM — see "As coded" at the end of this section). The installer
> no longer asks: both launchers (golem, golem server) are always installed, and everything below is done from the app.

**Switching, from the app, both ways**

| Where | Control | Does | Who |
|---|---|---|---|
| The window's bar | 📱 "Continue on a tablet" | the address and its QR, pairing if no tablet is paired, then **closes the window; golem keeps running** | anyone at the computer |
| **Settings ▸ System ▸ Dashboard**, next to ⏻ Stop golem | **"Continue on a tablet"** | the same sheet and the same action, where it can be found | admin device or the computer |
| **Settings ▸ System ▸ Dashboard** on a tablet or phone (golem has no window) | **"Show on this computer"** | golem opens its window on the computer's screen again (remembered size, `provision.desktop` `open_window`) — the sound does not stop | **admin device only** (like Stop golem) |

- "Show on this computer" needs a **desktop session** on that computer. Windows and macOS: golem server runs in the
  user's session, the window can open. Linux: a golem that started at boot **without a session** (linger) has no
  screen to open on — the button is **greyed, with that reason**, never a promise that fails. The bridge publishes
  `ui.can_show = {ok, why}` in its state.
- The bridge knows which use it is in **now**, not only at launch: `profile` (`desktop|server`) follows the window —
  set to `server` when the last golem window closes, `desktop` when one opens.
- **golem desktop: the window's close button (or Ctrl+W) stops golem**, like any program — REAPER closed (its
  project saved first on Windows/macOS; not on Linux, where the rig is rebuilt at each start), then the bridge (decision 2026-11-08, [`ui-architecture.md`](ui-architecture.md) §5; verified on Windows
  and Linux, macOS still to verify). Only "Continue on a tablet" closes the window and keeps golem running. Escape
  closes nothing. `golem server` (and the autostart of a dedicated box, which runs it) never stops this way.
- **Stopping without a window**: only an **admin** device (or the computer itself) can stop golem, from
  **Settings ▸ System ▸ Dashboard**, or `golem stop` / "Stop golem". Route `POST /api/ui/quit {stop: true}` (admin path).

**The dedicated machine is a setting, not an install choice**

**Settings ▸ System ▸ Dashboard ▸ "Start golem with this computer"** (an on/off switch, admin): golem server starts on its own,
without a window; a tablet or a phone is the screen. Same mechanism as before, now switched from the app (route
`POST /api/system/autostart {on}`, which runs `golem autostart on|off` / `provision.desktop autostart on|off`):

- **Linux:** a systemd **user** service (`golem-server.service`) with **linger**: it starts at boot **without any
  session**, REAPER on its virtual display.
- **Windows and macOS:** golem server starts **at login** (Windows Startup folder; macOS LaunchAgent
  `fm.golem.server`). A box that must start on its own needs the system's **automatic login**, which the user
  enables; the switch says so (setting it would need their password).

**Hardening (Linux) is a separate, explicit action**, no longer bundled with start-up: **Settings ▸ System ▸ Dashboard ▸
"Lock down this machine"** applies `harden.sh` (firewall, mDNS, frozen automatic updates, USB autosuspend off) and the
permanent CPU governor (`golem-perf.service`). It touches the whole machine and needs the **user's password**,
asked at that moment and never kept (same askpass rule as the installer). Each change is recorded in the install
receipt, so the uninstaller reverts it ([`uninstall.md`](uninstall.md)). Shown only on Linux.

**The installer** loses its "dedicated machine" box (screen 4 becomes "Folder"); its Done screen offers **"Open
golem"** (the window) and **"Continue on a tablet"** (golem server, then the address and pairing on that screen).

**What the bridge knows.** The launcher sets `GOLEM_LAUNCH=desktop|server` at start; the bridge then follows the
window (above). It publishes a pairing code for a server with no admin device, and reports `profile` in
`rack_identity()` for golem.fm.

**As coded (2026-10-16).**

- `bridge/machine.py` holds the logic, `bridge/routes_machine.py` the routes: `POST /api/ui/show`,
  `GET|POST /api/system/autostart {on}`, `GET|POST /api/system/harden {password}`. All in `ADMIN_PATHS`; the two `GET`s
  are also in `SENSITIVE_GET`, otherwise a plain `GET` would never be guarded (`bridge/auth.py`). Tests:
  `tests/test_machine_switch.py`.
- **How the bridge sees a window.** The app's WebSocket carries `?shell=device` when the page runs inside the shell
  `device.html` (or `?shell=ui` for `golem ui`) — `app/lib.js` `golemShell()`. The bridge counts it only when the peer
  is the computer itself (`machine.is_window_ws`): a tablet cannot pretend to be the window. `profile` goes to `server`
  **3 s** after the last window closes (a ↻ of the shell reloads the page; it must not flip), and a broadcast follows.
  Before the first window, `GOLEM_LAUNCH` decides. The state carries `profile` and `ui: {windows, can_show}`.
- **`ui.can_show` on Linux**: a local display whose socket exists (`WAYLAND_DISPLAY` under `XDG_RUNTIME_DIR`, or `DISPLAY`
  `:N` with `/tmp/.X11-unix/XN`), taken from the bridge's environment, else from `systemctl --user show-environment`
  (where a desktop session publishes it — this is how a golem started at boot finds a session opened later). REAPER's
  Xvfb display and remote displays (`localhost:10`) do not count, and `loginctl show-user` saying "no graphical
  session" wins over an inherited variable. Cached 5 s. Windows: false only for a service session (`SESSIONNAME=Services`
  or `SYSTEM`); macOS: true.
- **Show on this computer.** Linux runs `provision/golem window` — a new command, the window part of `golem desktop`
  without restarting the stack — detached, in the session's display environment. Windows/macOS call
  `provision.desktop.open_window` in the bridge (remembered size, an open window is focused).
- **Autostart.** Linux: `provision/autostart/install-autostart.sh [--off]`, which **no longer installs the CPU governor**
  (moved to `harden.sh`): starting with the computer never touches the rest of the machine. Run by the app there is no
  terminal, so linger is set with `loginctl enable-linger` first (polkit allows it to the user of an active session),
  then `sudo -n`; if both are refused, nothing is installed and the script says so (exit 3, the line is shown under the
  switch). Windows/macOS: `provision.desktop.autostart()` in the bridge; the answer carries the automatic sign-in hint.
  The receipt records what it did before (`linger` prior, the unit; the Startup link on Windows).
- **Lock down this machine** (Linux): the password is checked with `sudo -k -S -v` (stdin), then `harden.sh` runs in
  the background with `SUDO_ASKPASS` pointing to a helper that prints `$GOLEM_SUDO_PW` — the installer's pattern. The
  helper is in a `0700` `/tmp/golem-askpass-*` folder removed when the job ends; the password is never written,
  logged, returned, nor kept by the page. `harden.sh` now ends with `golem-perf.service` (governor prior recorded
  first). `GET` says `applied` from the files it places (`90-golem-usb-power.rules`, `90-golem-port80.conf`) or the
  receipt's `dedicated` items.
- **App.** Settings ▸ System ▸ Dashboard, next to ⏻ Stop golem: inside the window, "Continue on a tablet" opens the shell's own
  panel (`app/tablet-sheet.js`, shared with the 📱 of `device.html`, which exposes `window.golemTabletSheet`); elsewhere,
  "Show on this computer", greyed when `can_show` is false — a tap says why, in clear. A bottom row "Start golem with
  this computer" (switch + its sentence) and, on Linux, "Lock down this machine" (a dialog with the password). Admin
  only (local screen or promoted device). The phone Companion has no System page: not there.
- `GOLEM_MACHINE_DRY=1` makes the three gestures simulated in the bridge (tests, screenshots).
- **To verify on a machine** (not done yet): `golem window` from a linger-started bridge after a desktop login;
  the switch on a fresh Ubuntu (linger without sudo through polkit); `harden.sh` through the askpass from the bridge;
  Windows/macOS: the Startup link / LaunchAgent from the app and "Show on this computer" from a tablet.

## 5. The library manifest

`provision/components.json` lists **everything golem ships or installs**: name, author, role,
licence, source, and how to check it is present (`dpkg` package, file, venv module, or "vendored in
the repository"). `GET /api/system/libraries` (`bridge/libraries.py`) checks it against the machine,
per OS, and **Settings ▸ About ▸ Libraries** shows it, filterable by licence, with installed /
missing / to install yourself. It is a GPL obligation (say what we ship and where it comes from) and
a diagnostic: "x42-plugins missing" explains a silent block. The installer reads pack sizes from it
too.

## 6. The Connect screen: golem.fm, TONE3000, factory captures

> **Status: CODED** (2026-10-15). Until then the Linux screen showed the app's whole **Settings ▸ API** (now Settings ▸ Connect)
> page in a frame; it is now the installer's own interface, the app's functions behind it.

**The relay.** The page never calls golem (`:8770`): it calls the installer's server, which relays to
the bridge through `_bridge` in `installer/server.py`, restricted to `BRIDGE_ALLOW` — the only routes
it may reach:

| Bridge route | Used for |
|---|---|
| `GET /api/integrations` | masked state: TONE3000 key set?, golem.fm server list (active, Production) |
| `POST /api/integrations` | the TONE3000 publishable key; the golem.fm device token; the golem.fm server (Production) before a first pairing. The body is rebuilt from `golemfm.base_url`, `golemfm.token`, `tone3000.publishable_key` only |
| `GET /api/golemfm/status` | configured / reachable / paired / token accepted |
| `POST /api/golemfm/pair`, `GET /api/golemfm/pair/status` | the device flow ([`golemfm-protocol.md`](golemfm-protocol.md) §1) |
| `GET /api/band` | the band name shown once paired (only when golem.fm already pushed a roster) |
| `POST /api/t3k/auth/start`, `GET /api/t3k/auth/status` | TONE3000 sign-in (OAuth, PKCE; the callback lands on the bridge) |
| `GET /api/factory/captures`, `POST /api/factory/captures/download` | factory captures: present / missing, download and its progress |

The page's own routes compose these: `GET /api/link` (both cards' state), `POST /api/link/pair` +
`GET /api/link/pair`, `POST /api/link/token`, `POST /api/link/t3k-key`, `POST /api/link/t3k-signin` +
`GET /api/link/t3k`, `GET /api/link/factory`, `POST /api/factory/download`; no route forwards a body
or a path as received. Local calls are admin on the bridge (`auth.py`), so no token is needed.

**golem.fm card.** "Pair this golem": a fresh golem has no server, so the Production server is set
first (as `provision.desktop connect` does for a pasted token), then the code is shown large with
"Open golem.fm ↗" (the `approve_url` golem.fm returns, code included) and polled every 2 s until
approved (→ "✓ Paired — <band>"), expired or already claimed. The server it pairs to is shown in small
print. "I have a device token" pastes a token instead. There is **no Unpair**: the bridge has no route
to clear a token (`POST /api/integrations` keeps a blank secret).

**TONE3000 card.** Three steps: the publishable key, "Sign in to TONE3000" (opens the authorisation
page in the user's browser, polls the status every 2.5 s, and shows the redirect URI to register the
first time), then "Download the factory captures" with its progress and failures.

**Windows and macOS.** golem is not running at this point, so the same two cards hold two fields
(golem.fm token, TONE3000 key) written without starting golem (`provision.desktop connect`, secrets
on stdin). Once the key is saved, "Sign in to TONE3000 & download them" (`/api/factory`,
`/api/factory/start`, `/api/factory/download`) starts golem **as a server, without a window**
(`provision.desktop server`) if it is not running, opens the sign-in in the browser, and the download
starts when it succeeds. Pairing by code stays in golem, Settings ▸ Connect.

**`--dry`.** The relay makes **no HTTP request at all**: `installer/dry_bridge.py` answers in the
bridge's shapes (pairing approved at the third poll, a key of 8+ characters accepted, sign-in at the
third poll, a download that advances and fails its last capture), and no link is opened in a browser.
On a development machine `:8770` is the live rack; a demo must never pair it, sign it in, or write its
config. `GOLEM_INSTALLER_DRY_BRIDGE=down` simulates a golem that does not answer.
`tests/test_installer_link.py` checks the allow-list, the body filter and that a dry run reaches
nothing.

**In golem** (all OSes) the same lives in **Settings ▸ Content ▸ Factory** — its "Factory sounds" card
(`GET /api/factory/captures`, `POST /api/factory/captures/download`: one capture at a time, through the
"+ New" pipeline; a tone already in the catalog keeps its models, the union is requested).

## 7. Not built

- **Bootable image** (Ubuntu autoinstall calling the bootstrap); it will also have to create the
  user, since autostart uses `$USER`.
- **`golem update`** from the installer (same screens, steps "source" and "system --light").
- Uninstall on Windows and macOS (the Linux one is coded: [`uninstall.md`](uninstall.md) §4).
- Windows: ffmpeg (preview encoding) is not installed; block plugins other than the core, AVL, sfizz,
  Vitalium, Proteus, Dragonfly and TapeDelay2 are not installed (blocks say "plugin not installed on this
  machine"); a block whose plugin has no Windows build says "only available on a Linux golem" unless a golem
  JSFX plays it ([platforms.md](platforms.md) §5).
- macOS: signing / notarisation.
- `get.golem.fm` and `get.golem.fm/win` must redirect to the bootstrap of the current tag.
