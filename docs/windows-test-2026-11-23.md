# Windows live test — handoff note (2026-11-23)

> **Status: TO DO** — written on the Linux dev box for the agent session that opens on the Windows dev box. It says
> what was found, what is already fixed and pushed, and what has to be checked on real hardware. Delete this file once
> the test is done and its results are in the docs it points to.

## Where this comes from

On 2026-11-23 the README's install lines were run in two bare VMs (Ubuntu 24.04, Windows 11), on release v0.7.1, with
the Golem Engine as the default engine. Linux had no blocking bug. Windows had several; they are fixed in
`e7367017` (golem, `main`) and `1a1827be12` (golem-engine, `main`). **None of this is in a release yet**: v0.7.1 is
still what the install line puts on a machine. The VMs had no sound card: nothing below was heard.

## First, on the Windows box

```
cd <golem>          && git pull
cd %USERPROFILE%\golem-engine && git pull
```

The dev tree `~/golem-engine` wins over the installed package `~/opt/golem-engine` (`provision/golem_engine.py`,
`engine_dir`). Check which one runs before concluding anything: `python provision\golem_engine.py --check`. If golem
runs the **package** (9.9-g4), fix 3 below is not there — the watcher fix lives in the fork, not in the published
package.

## What to check, in this order

| # | What was wrong in the VM | Fix | How to check on the Windows box |
|---|---|---|---|
| 1 | The Golem Engine opened a black console window (`ardour9-lua.exe`) over golem, and `%TEMP%\golem-engine.log` stayed empty | `bridge/engine/ardour.py`: `run.py` gets a hidden console, under `python.exe` | Start golem from the desktop shortcut: no console window; the log grows. Then Settings ▸ Engines, switch away and back: still no window |
| 2 | "Open golem" left the installer window open and frozen behind golem | `installer/platform_windows.py`: `close_app` also closes every browser carrying the installer's profile | Only visible in a full install. Dry run: `set GOLEM_INSTALLER_DRY=1` then `python installer\server.py --open`, go to Done, "Open golem": the window must close |
| 3 | **Engine crash** when a preset with the piano was followed by another within seconds, disk cache cold (`0xC0000005` in `sfizz.dll`, or `0xC0000374`) — 3 cold runs out of 3 | golem-engine `golem/engine/golem_watch.lua`: a removed sampler is kept 60 s (`GRAVE`) before it is destroyed | **The one that matters most.** Reboot Windows, start golem, recall "Jazz Club", then another preset within 4 s. Repeat with "Pop Rock". The engine must not restart: no `restart (crash)` line in `%TEMP%\golem-engine.log`, no "Application Error" for `ardour9-lua.exe` in the Windows Event Viewer |
| 4 | Switching from the Golem Engine to REAPER failed on a PC with no ASIO driver ("Choose an installed ASIO driver") | `bridge/engine/reaper.py`: REAPER starts without a card, as `golem desktop` starts it | On the dev box (it has an ASIO driver) the usual path runs, not the new one: check that the switch to REAPER and back still works and remounts the preset |
| 5 | The Windows install line checked no signature | `provision/bootstrap.ps1`, `Verify-Release` | Already checked in the VM against the published script (v0.7.1 verified, 2323 files; v0.6.4, signed by the old key, refused). Nothing to do unless the install line is rerun |
| 6 | Health proposed "Resync REAPER" for a Golem Engine | `bridge/fixes.py`: the texts name the active engine | Settings ▸ System ▸ Health, or `python tools\doctor.py --list`, with the Golem Engine chosen: no "REAPER" in the labels |

Also worth a look while there, never tested in a VM: **the sound** (the dummy card played nothing), the ASIO card
picked by the Golem Engine at start, a take, the looper.

## If check 3 fails

Read the last 40 lines of `%TEMP%\golem-engine.log` before the `exited with code` line, and the faulting module in the
Event Viewer. What was tried and ruled out: keeping one idle sfizz instance alive so that `sfizz.dll` never unloads —
the crash then moved inside `sfizz.dll` itself. The measured facts are in `docs/ardour-plan.md` §7e ("Fresh Windows 11
VM, 2026-11-23"). The delay is `GRAVE.secs` (60 s); the piano's cold load took up to 13 s in the VM.

## What is left after the test

1. **A new Windows engine package** (9.9-g5) carrying the watcher fix: built on this box like 9.9-g4 (`golem/tools/
   win-build.sh`, `bundle.py`, `docs/ardour-plan.md` §7e), published on Goldoralf/golem-binaries, then pinned in
   `provision/windows/pins.json` (`golem_engine`: version, url, sha256). Until then a machine installed by the install
   line still crashes on check 3. Linux keeps 9.9-g3, whose watcher is older: the same fix reaches it with its next
   package.
2. **A golem release (v0.7.2)** so that the install line and the Update button deliver fixes 1, 2, 4 and 6
   (`tools/release.sh`, from the Linux box where the release key is).
3. **Not done, by choice**: REAPER is still always installed on Windows, even when the Golem Engine is chosen
   (`docs/install-v2.md`, lot 3 — an installer lot, not a bug). A Windows without `ssh-keygen.exe` installs without the
   signature check, and says so (`docs/release-signing.md`): stopping there instead is a one-line decision.

## Reminders that cost time in the VM

- `set PYTHONUTF8=1 & python …` in `cmd` sets the value to `1 ` (with the space) and Python refuses to start: write
  `set "PYTHONUTF8=1"& python …`.
- A file of the engine package has CRLF line endings; the fork has LF. Compare with that in mind.
- `golem_watch.lua` is at Lua's limit of 200 local variables in its main chunk: a new file-level `local` breaks the
  engine at start (`too many local variables`). Use a global table, as `GRAVE` and the MIDI clock do.
