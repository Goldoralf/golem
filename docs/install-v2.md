# Installation v2 — the Golem Engine by default, accounts first

> **Status: FIXED** (decisions of the maintainer, 2026-11-17) — **lot 1 CODED**, lots 2–5 not started.
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
| 1 | **The engine as a package.** `golem-engine/golem/tools/bundle.py` builds a self-contained archive (the engine, its libraries, the watcher); `provision/golem_engine.py` + `install-golem-engine.sh` place it in `~/opt/golem-engine` (atomic, previous engine kept as `.prev`, receipt); golem finds the engine by one rule everywhere | **CODED** — no release published yet |
| 2 | **Publishing.** A workflow in `golem-binaries` builds the fork from a tag on the oldest supported distribution, runs `bundle.py`, publishes `golem-engine-<version>`; the pin goes in `provision/downloads.sha256` | not started |
| 3 | **Installer: engine choice.** REAPER as a checkbox (decision 2), the engine step always, the default engine written at the end of the install (`config/engine.json`) | not started |
| 4 | **Installer: accounts first.** golem.fm and TONE3000 on the first pages; the capture download starts as soon as TONE3000 is signed in and runs beside the install phases — the installer must download captures **without golem running** (today the download goes through the bridge) | not started |
| 5 | **Faster sign-in** (§ below) | to be agreed with golem.fm |

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
- **Not proved**: a package built on the oldest distribution we want to support (this one was built on Ubuntu 24.04,
  glibc 2.39 — it will not start on anything older); the engine's own update and rollback from the app.
- While no release is pinned the install step prints one line and is not a warning.

## Faster sign-in (decision pending with golem.fm)

- **TONE3000.** A golem **paired with golem.fm** already signs in to TONE3000 in one click: it borrows golem.fm's
  TONE3000 application (`/api/ext/t3k/relay`, 2026-10-22), with no key to paste and no address to declare. Without
  golem.fm the user still needs their own publishable key and a declared redirect address. To make TONE3000 one
  click **without** golem.fm, golem would need its own registered TONE3000 application with a `localhost` redirect —
  an account-side step for the maintainer, then no key for anyone.
- **golem.fm.** The device flow exists (a code, "Open golem.fm ↗", polled every 2 s). "Accelerated" means the page
  golem.fm opens lets a visitor **sign in or create an account there and approve in the same page**, naming the
  golem; the installer side barely changes. That page is golem.fm's.
- So the order that costs the user the least is: **golem.fm first (one page), then TONE3000 in one click**.
