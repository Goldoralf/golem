# Uninstalling golem

> **Status: FIXED (design validated 2026-10-15). Linux: CODED and TESTED in a clean VM** — install receipt (§2,
> `provision/receipt.py`), engine (§3, §5: `provision/uninstall.py`, `golem uninstall [--dry-run]`), full backup (§6:
> `bridge/backup_cli.py`), graphical uninstaller (§4: `installer/server.py --uninstall`), VM test and judge (§7). Four
> cycles on Ubuntu 24.04 (2026-10-15/16); the last one, everything ticked: **0 real leftovers** — only base packages
> the install upgraded and the system base golem never offers remain. **Windows: CODED (§9, 2026-10-16) —
> receipt, engine, screens, backup, VM tools — tested on Linux only, not yet run on the Windows VM.** macOS later. **Not coded**: the app's System button.

Related: [`installer.md`](installer.md) (what the install does), [`backups.md`](backups.md) (what a backup
carries), [`platforms.md`](platforms.md), [`network.md`](network.md).

## 1. The problem this solves

A Linux install touches about sixty places in seven families: the install folder, REAPER, a dozen plugins in
`~/.lv2`, `~/.vst3` and `~/.clap`, about forty apt packages, root-level settings (the `audio` group, real-time
limits, two sudoers rules, two scripts in `/usr/local/sbin`, the `golem-net` service, and on a dedicated machine
ufw, ssh, udev, sysctl and automatic updates), desktop integration, and the user's own data.

Many of these are **shared** with the rest of the machine — ffmpeg or pipewire may predate golem, a personal
REAPER may use SWS or the same LV2 plugins, the user may already have been in `audio` — and the install does not
record what was there before it. Some of its own backups overwrite themselves (`reaper.ini.bak` is rewritten on
every run that changes something; `harden.sh` replaces the automatic-updates file without a copy; the previous ufw
state and CPU governor are never saved). An uninstaller built on that can only guess: it leaves traces or breaks
something else. Hence the receipt (§2) comes first.

## 2. The install receipt

`~/.local/share/golem/install-receipt.json` — **outside** the install folder, so deleting the folder never loses
it. One receipt per user; it describes the install at `root`.

```json
{
  "format": 1,
  "root": "/home/u/golem",
  "created": "2026-10-16T10:00:00", "updated": "…",
  "release": "v2.9.0",
  "items": [
    {"id": "file:/etc/sudoers.d/golem-net", "kind": "file", "path": "/etc/sudoers.d/golem-net",
     "owner": "root", "by": "provision/setup-net-sudo.sh", "group": "system", "prior": null},
    {"id": "link:~/.config/REAPER/Scripts/__startup.lua", "kind": "link", "path": "…",
     "owner": "user", "by": "provision/link-reaper.sh", "group": "reaper",
     "prior": {"moved_to": "~/.config/REAPER/Scripts/__startup.lua.golem-orig"}}
  ],
  "apt": {"added": ["guitarix-lv2", "x42-plugins", "libgxw0", "…"], "debs": ["surge-xt", "proteus", "byod"],
          "requested": ["guitarix-lv2", "x42-plugins", "ffmpeg", "…"]},
  "prior": {
    "audio_group": false,
    "reaper": {"installed_by_golem": true, "path": "~/opt/REAPER", "version": "7.x"},
    "reaper_ini": {"csurf_added": true, "keys": {"automute": "1", "midiins": "0", "…": null}},
    "ufw": {"active": false, "rules": []},
    "auto_upgrades": "APT::Periodic::Update-Package-Lists \"1\";\n…",
    "linger": false,
    "governor": "powersave"
  }
}
```

Rules:

- **Written by one helper**, `provision/receipt.py` (standard library only, callable from every install script:
  `receipt.py add PATH --kind file --by <script> --group <g>`, `receipt.py prior KEY VALUE`,
  `receipt.py apt-snapshot before|after`). It always writes **as the installing user** — under `sudo` it uses
  `SUDO_USER`'s home and gives the file back to that user — and atomically.
- **The prior state is recorded once.** A second install over the first merges items but never replaces a
  `prior` value: the first one is the machine before golem. This replaces every `.bak` that overwrites itself.
- **Moved originals get a golem-specific name** (`*.golem-orig`), never `.bak`, so a user's own `.bak` is never
  taken for ours.
- **apt**: `apt-snapshot before` stores the list of installed packages (`dpkg-query -W`) before `install.sh`
  runs `apt-get install`; `after` stores the difference as `apt.added`. A package that was already there is not
  ours. `.deb` files installed with `dpkg -i` go in `apt.debs` with their package name. `apt.added` is the whole
  dpkg difference — the packages golem asked for **and every dependency apt pulled in with them** (609 packages on
  a clean Ubuntu 24.04, 2026-10-15).
- **apt.requested** (2026-10-15): the package names each install script passes to `apt-get install` or `dpkg -i`
  (`receipt.py apt-requested PKG…`, called next to each `apt-snapshot before`: `install.sh` with `packages.txt`,
  `install-plugins.sh`, `install-zconvo.sh`, `install-nam.sh`, `install-prisma.sh`, `install-spectral.sh`,
  `install-sfizz.sh`, `plugins-deb.sh`, `setup-net-sudo.sh`, `harden.sh` — the scripts keep one array for both
  calls, so the two lists cannot drift; `tests/test_receipt.py` fails if a script calls apt without it). It
  records the **request**, not the effect: a requested package that was already installed is not in `apt.added`,
  and the uninstaller only keeps `apt.requested ∩ apt.added`. `pkg:arch` is stored as `pkg`; a `.deb` path is
  ignored (its package name, read with `dpkg-deb -f`, is recorded instead).
- **What the bridge writes at run time** to shared places (`reaper.ini` audio buffer, REAPER version slots,
  `reaper-license.rk`) records its prior state through the same helper. The installer's screen 3 writes the
  licence with the same code (`bridge/reaper_license.py`); the receipt does not exist yet at that point, so the
  prior is held and recorded right after the *source* step creates the receipt.
- **No receipt** (a machine installed before this exists, or a hand install): the uninstaller still works, in a
  stated *no-receipt* mode (§3).
- **A receipt can be partial**: one install script run alone on an older install creates it, and the bridge and
  `reaper-ini-setup.py` only write to an existing one. So the uninstaller scans for golem-named leftovers in
  receipt mode too, and merges them with the receipt's items (deduplicated by path).
- `GOLEM_RECEIPT` points both the helper and the uninstaller at another receipt file (tests, VM).

Additions to the format (2026-10-15, with the helper):

| Key | Meaning | What the uninstaller does |
|---|---|---|
| item `prior: {"existed": true}` | the path was already there before golem placed it | listed, origin `receipt`, **unchecked**, reason "already here before golem" |
| item `prior: {"moved_to": …}` | where the original was moved (`*.golem-orig`, timestamped when that name is taken) | puts back exactly that path |
| `reaper.license_present` | a `reaper-license.rk` existed before golem wrote one | shown in the reason of the `~/.config/REAPER` box |
| `reaper_ini.existed: false` | golem created `reaper.ini` | its keys are removed (not set to a value); the file stays |
| `apt_timers` | `systemctl is-enabled` of `apt-daily.timer`, `apt-daily-upgrade.timer` before `harden.sh` | `dedicated`: services unmasked, each timer back to `enabled` / `masked`, left off otherwise |
| `avahi_enabled` | `systemctl is-enabled avahi-daemon` before `harden.sh` (`absent` when not installed) | `dedicated`: disabled when it was not enabled before; left as is when enabled or absent from the receipt |
| `governor` | recorded by `setup-perf-sudo.sh` and `harden.sh` (with `golem-perf.service`; until 2026-10-16 by `install-autostart.sh`) | `dedicated`: set back |
| `toolchain.rust_installed_by_golem` | Rust installed by `install-spectral.sh` | `toolchain` offered, checked (2026-10-24) |
| `ufw.rules` | the lines of `ufw status` before | a golem rule (`8770/tcp`, `80/tcp`, `5353/udp`, `OpenSSH`) is deleted only if its first word was not there |

`net.sh` and `perf-mode.sh` are not instrumented: they are root-owned NOPASSWD copies. Their traces are found by
name (`golem-ap` through `nmcli`, `/etc/NetworkManager/dnsmasq-shared.d/golem-name.conf`).

## 3. The uninstall engine — `provision/uninstall.py`

Standard library only, so it runs without the golem venv. The graphical uninstaller is a window onto it, never a
second implementation (the installer's rule).

| Command | Does |
|---|---|
| `uninstall.py plan [--root DIR] [--json]` | lists every item it would touch, with group, path, privilege, origin (`receipt` · `golem-named` · `unknown`), default choice and the reason — **touches nothing** |
| `uninstall.py run --items <ids…>` / `--select FILE` | removes exactly the chosen items, in the order of §5, logging each action |
| `golem uninstall` | opens the graphical uninstaller; `golem uninstall --dry-run` prints the plan |

**Groups and defaults**

| Group | Items | Default |
|---|---|---|
| `golem` | the install folder, `~/.local/bin/golem`, desktop file and icon, user unit and linger (back to its prior value), the launcher's browser profile, `~/.cache/golem-installer`, `~/.cache/golem-build`, `/tmp` and `/dev/shm` leftovers, the song inbox (`~/golem-inbox`, or the folder `config/inbox.json` names) | removed; the inbox only when it holds no file |
| `reaper-links` | `Scripts/golem`, `Effects/golem`, the OSC files, the `FXChains` link, `__startup.lua`; originals moved aside are put back | removed (with restore) |
| `reaper-ini` | the keys golem wrote, set back to their prior values; the OSC surface removed only if golem added it | reverted |
| `system` | sudoers rules, `/usr/local/sbin/golem-*`, `golem-net.service`, `golem-perf.service`, the `golem-ap` connection and its DNS file, `95-golem-audio.conf`, the `audio` group (only if the user was not in it before) | removed |
| `dedicated` | ssh hardening, ufw rules (golem's rules deleted; ufw disabled only if it was inactive before), the port-80 sysctl, the USB autosuspend rule, automatic updates restored to their prior file | reverted |
| `plugins` | plugins golem placed or built (patched NAM, patched zconvo, Freeze, Prisma, Spectral Compressor, PaulXStretch, Dexed, AIDA-X, Ratatouille, Aether, TapeDelay2) | checked if the receipt says golem placed them; else listed unchecked |
| `reaper` | REAPER itself (`~/opt/REAPER`, `~/opt/reaper-versions`) and the desktop integration its installer wrote (menu entries, icons, file types) | offered **only** if `installed_by_golem`; unchecked. `~/.config/REAPER` is a separate box, unchecked; the licence is always backed up first |
| `apt` | the packages golem asked for **explicitly**: `apt.requested ∩ apt.added`, plus `apt.debs`; for a receipt written before `apt.requested`, `apt.added ∩` the packages apt marks manual. A package of `apt.added` that apt marks manual but no script requested is listed too, unchecked ("installed on purpose, but no golem script asked for it"). The rest of `apt.added` — the dependencies — are **not items**: the plan counts them (`apt_deps`) and the run removes them with what pulled them in | audio plugin packages checked; **build files checked** (`BUILD_APT`: `*-dev`, cmake, pkg-config — asked only to compile golem's plugins, absent before golem; 2026-10-24: a VM uninstall left ~20 of them with ~500 dependencies); general tools (ffmpeg, jq, xvfb) unchecked; **never offered**: the system base (pipewire, wireplumber, alsa, pulseaudio-utils, git, curl, wget, unzip, python3-*, network-manager, avahi-daemon, ufw, build-essential) — nor removed as a dependency |
| `toolchain` | Rust (`~/.cargo`, `~/.rustup`) if the receipt says golem installed it | checked when `rust_installed_by_golem` is true, else unchecked |

**Engine notes (as coded).**

- Item ids: `golem:install-folder`, `golem:command`, `golem:desktop:<file>`, `golem:icon:<file>`,
  `golem:user-unit:<unit>`, `golem:linger`, `golem:share-dir`, `golem:cache:<name>`, `golem:tmp`, `golem:inbox`,
  `reaper-links:<path under ~/.config/REAPER>`, `reaper-ini:revert`, `system:<absolute path>`,
  `system:nm:golem-ap`, `system:audio-group`, `dedicated:<absolute path>`, `dedicated:ufw`,
  `dedicated:auto-upgrades`, `dedicated:apt-timers`, `dedicated:avahi`, `dedicated:governor`,
  `plugins:<slug>`, `reaper:app`, `reaper:config`, `apt:<package>`, `toolchain:rust`.
- The plan lists only what **exists** on the machine. Receipt entries already gone go to `absent` (their receipt
  ids) and count as done: they leave the rewritten receipt. A receipt path outside what golem may remove is
  refused and stated in `warnings`.
- **What the user cannot see is never "absent"** (third VM cycle, 2026-10-16). The plan runs as the user;
  `/etc/sudoers.d` is `0750 root`, so `golem-net` and `golem-perf` looked absent and stayed — a security leftover.
  Every item carries `presence`: `present`, or `unknown` when `stat` fails with a permission error (never
  "absent"). In a folder the user cannot list, the engine looks for the receipt's paths and golem's **fixed
  names** (`GOLEM_FIXED_ROOT`: both sudoers rules, the `/usr/local/sbin` helpers, the units, `95-golem-audio.conf`,
  the dnsmasq, lightdm, ssh, sysctl and udev files). An `unknown` item is listed, checked, privilege `root`, with
  the reason "can't be checked without root (its folder is closed to you): removed if present"; the root pass
  removes it with `rm -f` and reports `removed` or `was not there` — both a success. Other root-only places the
  engine reads are already safe: the `golem-ap` connection is asked to `nmcli`, linger and `ufw.conf` are
  world-readable.
- **The song inbox** (`golem:inbox`): `bridge/inbox.py`'s folder — `~/golem-inbox`, or the `dir` of
  `<install folder>/config/inbox.json`. Checked when it holds no file (its empty `.imported`/`.refused` included);
  unchecked when it holds files, with their count — they are the user's, so it stays (the golem screen is
  read-only). Never offered when it is a protected folder (`~`, `~/Music`…) or inside the install folder (it goes
  with it). A moved inbox is outside the expected set: the run removes it only while it is empty
  (`_remove_empty_tree`), even when chosen by hand. The bridge creates no other folder outside the install
  folder (song folders are chosen by the user, never created).
- **REAPER's desktop integration** goes with `reaper:app`: its paths list, before the program itself,
  `~/.local/share/applications/cockos-reaper*.desktop`, `~/.gnome/apps/cockos-reaper*.desktop`,
  `~/.local/share/icons/hicolor/*/apps/cockos-reaper*.png` / `cockos-reamote*.png` and
  `~/.local/share/mime/packages/application-x-reaper.xml` (what `install-reaper.sh --integrate-user-desktop` writes
  through `xdg-desktop-menu`, `xdg-icon-resource` and `xdg-mime`). The run first calls REAPER's own uninstaller,
  `~/opt/REAPER/uninstall-reaper.sh --remove-user-desktop --quiet` (non-interactive; it needs the xdg tools, which
  the apt step may have purged), then removes each file itself whatever that returned. The receipt's
  `~/opt/REAPER` entry is carried by `reaper:app` (it used to appear twice).
- **Desktop databases** (after any chosen item removed a menu entry, an icon or a file type — golem's or
  REAPER's): `update-desktop-database`, `update-mime-database` and `gtk-update-icon-cache` run (through the
  runner) where entries remain; a cache that no longer describes anything is removed — `mimeinfo.cache` when no
  `.desktop` is left, the whole `~/.local/share/mime` when `packages/` is empty (everything else there is generated
  from it), `icon-theme.cache` and the empty theme folders when no icon is left, xdg's
  `xdg-desktop-menu-dummy.menu` when it is alone and no entry is left. `defaults.list` is removed only when every
  association in it points to a `cockos-reaper*`/`golem*` entry that no longer exists; a user's own association
  keeps the file untouched. Empty `~/.gnome/apps`, `~/.gnome`, `~/.config/menus/applications-merged` and
  `~/.config/menus` join the empty container folders removed at the end.
- `run --json` prints one line per action: `{"step", "item", "ok", "msg"}`; `step` is `stop`, `root`, `apt`,
  `reaper`, `user`, `folder`, `receipt`, then a final `done` line (`item` null, `ok` = everything succeeded).
  Two optional keys: `"kept": true` on a package kept on purpose (neither done nor failed: no Retry, the receipt
  keeps it) and `"deps": N` on the apt summary line. `--select FILE` takes a JSON list of ids, or objects
  `{id, selected}` (a plan JSON uses each item's `default`).
- Root items (except apt) go through **one** generated shell script, run with `sudo -A` when `SUDO_ASKPASS` is
  set, else `sudo` (which needs a terminal), each item reporting its own result.
- **apt has its own step**, after the root pass. "Manual" is read from `/var/lib/apt/extended_states` (what
  `apt-mark showmanual` reads; readable without root, and testable on the fake tree). Every command goes through
  the engine's runner (tests replace it); real purges run as
  `sudo [-A] env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 purge -y …`.
  1. **Simulate first**: `apt-get -s purge <chosen packages>` (no root, touches nothing). If the simulation would
     also remove a package that is **not** in `apt.added`/`apt.debs` — something the user had before golem — each
     package is simulated alone and the culprits leave the batch: reported `kept`, with the reason
     "needed by <pkg> (installed before golem)". When only the batch as a whole does it, nothing is purged.
  2. **One purge** of the remaining batch, then `dpkg-query` checks each package is gone.
  3. **Dependencies**: `apt-get -s autoremove --purge` lists what apt would remove; only those **in `apt.added`**
     (golem added them), not in the system base and not held by an explicit package the user kept, are
     candidates. They go through the same simulation screen, then one purge. Repeated until nothing new
     (at most 3 rounds). **Never a plain `autoremove`**: it would also remove automatic packages that predate
     golem. A dependency kept by the screen is reported on its own line.
  4. A summary line `N dependencies removed` (with `"deps": N`); the Done screen repeats it.
  Without a selected apt package, the step does nothing (no dependency is touched).
- The install folder is refused while the current directory or the uninstaller itself lives inside it: the
  graphical uninstaller copies itself to `/tmp` first.
- The receipt is deleted only when every chosen item succeeded (a package `kept` by the apt screen is not a
  failure) **and** the install folder is gone; otherwise it is rewritten with what remains (items not done, priors
  not consumed, `apt.added`/`debs`/`requested` without the packages purged — dependencies included) plus
  `uninstall.failed`. Without a
  receipt nothing is written: a second run finds the leftovers by name.
- Never deleted: `/`, `$HOME` and its ancestors, the system and shared folders themselves (`/etc`, `/usr`,
  `~/.config`, `~/.lv2`…); a path is deleted only if it matches the expected set; a symbolic link is removed,
  never its target, and a path reached through a symlinked parent is refused. `--root-fs PREFIX` (or
  `GOLEM_UNINSTALL_FSROOT`) runs everything on a fake tree, system commands simulated — for tests only.
- `reaper.ini` is edited in its `[reaper]` section only, written atomically, and the previous file is kept as
  `reaper.ini.golem-uninstall`. Our OSC surface is the `OSC` line whose name contains `golem` or that reads the
  `golem` pattern; the surfaces after it are renumbered and `csurf_cnt` fixed (removed when it reaches 0).

**No-receipt mode.** Items that are golem's by name (`golem-*` files, units and rules, the install folder, the
golem links in REAPER) are removed as usual. Everything shared is listed with origin `unknown` and unchecked;
`apt` packages are **not offered at all** — guessing there is how a user loses their pipewire.

## 4. The graphical uninstaller

Same server, token and look as the installer (`installer/server.py`, `installer/ui/`), with its own screens. At
launch it **copies itself** to `/tmp/golem-uninstaller-<random>/` and runs from there: it deletes the folder it
came from.

| # | Screen | What it does | Blocks if |
|---|---|---|---|
| 1 | **Back up** | Checked by default. Destination outside the install folder (default `~/golem-backup-<date>`, or a chosen folder or USB drive), with the size against its free space. Content: §6. Box **"Include my keys"** unchecked, with its warning. Optional push to the golem.fm vault | backup checked and it failed its verification |
| 2 | **golem** | What goes: the `golem`, `reaper-links`, `reaper-ini`, `system` and `dedicated` groups, item by item, read-only (this is what "uninstall golem" means) | — |
| 3 | **Third-party software** | The `plugins`, `reaper`, `apt` and `toolchain` groups as a checklist, with each default and its reason ("already here before golem", "system base — never removed") | — |
| 4 | **Review** | The exact plan (`plan --json` of the selection), the password (as in the installer: askpass, never on disk) | — |
| 5 | **Uninstall** | The steps with a live log; a failed item is stated and the others continue; Retry | — |
| 6 | **Done** | Where the backup is and how to restore it; what remains and why (unchecked items, unknown origin); "log out and back in" if the `audio` group changed | — |

Entry points: `golem uninstall`, an "Uninstall golem" desktop entry installed next to the launcher, and later a
button in the app (System) that starts the uninstaller and then closes the app.

**As coded (2026-10-15).**

| | |
|---|---|
| Launch | `golem uninstall` → `exec python3 installer/server.py --uninstall --root <install folder> --open` (system Python, no venv). `golem uninstall --dry` opens the same screens in simulation; `golem uninstall --dry-run` still prints the text plan. Desktop entry: `~/.local/share/applications/golem-uninstall.desktop` ("Uninstall golem", `Exec=~/.local/bin/golem uninstall`), written by `provision/install-desktop.sh` and recorded in the receipt; the engine also finds it by name (`golem*.desktop`, item `golem:desktop:golem-uninstall.desktop`) |
| Self-copy | first pass: `installer/uninstaller.py self_copy` copies `installer/{server,platform_linux,dry_step,uninstaller}.py`, `installer/ui/*`, `provision/uninstall.py`, `bridge/engines.py`, the Preact/htm bundle and the favicon to `$TMPDIR/golem-uninstaller-<random>/` (mode 700, with a marker file), `chdir`s there and `execv`s itself with `--owned-tmp`. That folder is deleted at every exit (Close, Cancel, Ctrl-C, SIGTERM/SIGHUP, an exception, the idle watchdog) by `server.cleanup()`, and only if it carries the marker. The engine already ignores `/tmp/golem-uninstall*` when it lists leftovers. The sudo askpass folder is created **inside** that copy, so it is never one of the leftovers being removed |
| Window | Linux opens a tab in the default browser (`xdg-open`), like the installer — not an app window: golem's own browser profile (`~/.local/share/golem/browser`) is one of the things being removed. With no window to watch, the server leaves after 15 minutes without a call from its screen while nothing runs (the screen calls every 10 s). Every screen before the uninstall has **Cancel**; Done has **Close the uninstaller** |
| Back up | runs on screen 1 ("Back up now"), with the venv: `<root>/.venv/bin/python -m bridge.backup_cli full --dest DIR [--secrets] --json`, `cwd = <root>`. Success = exit 0, `ok: true` **and** a `verified` map. Size: `python -m bridge.backup_cli estimate --dest DIR [--secrets]` (JSON, writes nothing) against the destination's free space. The destination is refused inside the install folder or the temporary copy. Changing the destination or the keys box after a backup makes it stale (to redo). **No venv**: the backup cannot run; the screen says so, points at the install folder for a manual copy, and goes on only after the box "Continue without a backup" is ticked |
| golem screen | read-only. Items of the `golem`, `reaper-links`, `reaper-ini`, `system`, `dedicated` groups are removed as the engine proposes them (`default`); one the engine leaves unchecked (for instance the `audio` group with origin `unknown`) is shown as **stays**, with its reason |
| Third-party screen | checkboxes, the engine's `default` pre-ticked; origin `unknown` shown as a chip, the engine's reason under each item, the never-offered system base listed. Each group has a **Select all / Select none** toggle and a "k of n selected" count. The `apt` group says how many dependencies go with the packages (`apt_deps`). Without a receipt it says why packages are not offered |
| Review | the exact selection (`GET /api/review`) and what stays. The password is asked only when a selected item needs root (checked with `sudo -k -S -v`, kept in memory, askpass as in the installer) |
| Uninstall | the server writes the ids to `select-N.json` in the copy and runs `python3 <copy>/provision/uninstall.py run --root <root> --select FILE --yes --json --log FILE`, `cwd = <copy>`, `SUDO_ASKPASS` + `GOLEM_SUDO_PW` in its environment. Each JSON line updates the item and its step; the log is shown live. **Retry** reruns only the failed ids that the engine still lists (it refuses absent ids). The log file is written next to the backup (`uninstall-<ts>.log`), or inside the temporary copy when there is no backup |
| Done | backup folder + README hint; "N dependencies of golem's packages removed with them"; what remains (unchecked, kept — including packages kept because software from before golem needs them —, failed with its message) and why; "log out and back in" when `system:audio-group` was removed |
| `--dry` | the plan is read for real (`plan --json` touches nothing); the backup and the run are played by `installer/dry_step.py backup …` / `uninstall-run …`, which print exactly what the real commands print. `GOLEM_DRY_FAIL=backup`, `GOLEM_DRY_FAIL_ITEM=<id>` (first attempt only) and `GOLEM_DRY_NO_VENV=1` show the failure screens. Tests: `tests/test_uninstaller_gui.py` |

**Deviations from the table above.**

- **No golem.fm vault push** on the Back up screen: there is no command-line path to the vault that works with the
  bridge stopped. Left out rather than faked.
- **`~/.config/REAPER` needs a verified backup.** §3 promises the REAPER licence is backed up first, but the engine
  does not copy it: the uninstaller therefore refuses `reaper:config` unless the backup (which carries
  `identity/reaper-license.rk`) is verified.
- Back up blocks on more than a failed verification: a ticked backup that has **not run yet** also blocks (the
  screen's button is "Back up now"; unticking it is the explicit choice).

## 5. Order of operations

1. **Back up**, then verify (every zip re-read, every manifest hash checked). Nothing below runs if it fails.
2. **Stop the engine**: `golem autostart off`, `provision/stop.sh` (REAPER then the bridge). The app never removes
   itself while it runs.
3. **Root items** in one elevated pass (`system`, `dedicated`), then the **apt** step: chosen packages purged
   after a simulation, then the dependencies golem added that nothing needs any more (§3).
4. **REAPER**: links and `reaper.ini` reverted, then REAPER itself if chosen.
5. **Plugins, toolchain**, user-level integration.
6. **The install folder**, last.
7. **The receipt**: deleted if everything succeeded; otherwise rewritten with what remains, so a second run
   finishes the job.

## 6. The full backup

Written to the chosen folder, outside the install folder:

| File | Content |
|---|---|
| `golem-all-<ts>.zip` | backup category `all` ([`backups.md`](backups.md)) — restorable from ⇅ I/O |
| `golem-songs-<ts>.zip` | category `songs`: every `.golem` of the song library — restorable from ⇅ I/O |
| `identity/serial.json` | the rack's lifetime number (kept by decision, 2026-10-15) |
| `identity/reaper-license.rk` | the REAPER licence, if present |
| `secrets/` | only with "Include my keys": `integrations.json`, `auth-devices.json`, `network.json`, `.env` |
| `README.txt` | what each file is and how to put it back (identity and secrets by copy: the importer refuses them by design) |

Produced by a command-line entry of the backup module run with the golem venv (`python -m bridge.backup_cli full
--dest DIR [--secrets]`), so it works with the bridge stopped. Not included, as today: DrumGizmo kits, SFZ
pianos, the backing cache — the installer gets them back.

## 7. The test that proves it — a clean virtual machine

Never on a working machine: a second install there shares `~/.config/REAPER`, `~/.lv2`, port 8770 and
`/usr/local/sbin/golem-net` (which carries the install folder's path), and an uninstall would destroy it.

`tools/check-uninstall-vm.sh before|installed|after` (on the VM of `provision/vm`; the footprint itself is
`tools/footprint.sh`, read-only, sent to the VM through ssh's stdin). Install and uninstall are done **by hand**,
through the graphical installer and uninstaller as a user would, between the snapshots:

1. snapshot of the footprint: installed package **names** (`## packages`; a removed-but-not-purged package shows
   as `name (config-files)`), their versions apart (`## versions`, so an upgrade is not a leftover), a file listing
   of `$HOME`, `/etc`, `/usr/local`, enabled system and user units, groups, ufw status, sysctl values, linger;
2. install (graphical or `bootstrap.sh`), footprint again; `installed` also saves the uninstall **plan**
   (`provision/uninstall.py plan --json` run in the VM through stdin — read-only) to know later what was offered;
3. uninstall through the graphical uninstaller;
4. footprint again, plus what only the VM knows, read-only: `dpkg -S` of every new path, of its parent folders
   under `/etc` and of each new unit's file (`*/systemd/<scope>/<unit>`, `/etc/init.d/<name>`), and the target
   (`readlink -f`) of each new symbolic link under `/etc` (`new-paths`, `new-links` → `owners.txt`, `links.txt`);
   `tools/uninstall-judge.py` compares it with step 1 and sorts every difference into
   **(a) upgraded** base packages (same name, other version — informational), **(b) kept** by design or by choice
   (packages matching `NEVER_APT` imported from the engine, files `dpkg -S` says belong to such a package or to a
   package from before golem, anything inside an item the uninstaller offered and the user kept, a dependency a
   kept package still holds, the backup folder — informational), and **(c) leftovers**: everything else, including
   an item of the read-only golem screen that is still there, a golem dependency `apt-get -s autoremove` would still
   remove, and anything from before golem that disappeared → exit 1. Each class is written to its own file in
   `~/.cache/golem-vm/footprint/` (`upgraded.txt`, `kept.txt`, `leftovers.txt`, a reason per line), with a short
   summary per class on screen. Footprints taken before `## versions` existed are refused (exit 2): retake
   `before`.

   **Judge rules (2026-10-16)**, in order, for a new file or link:
   1. the backup folder → kept;
   2. inside an offered item → the **most specific** item decides (a link under a kept `~/.config/REAPER` that
      `reaper-links` had to remove is a leftover); on a tie, kept wins. An item whose action is `revert` or
      `restore` (`reaper.ini`, ufw, an original put back) leaves its path in place: kept, "set back in place";
   3. `dpkg -S` owns it → judged like that package; a package **no longer installed** (`## packages`) makes it a
      leftover, named;
   4. it carries golem's name (outside the home folder's own path: the VM user may be called golem) → leftover —
      no rule below can keep it;
   5. a symbolic link under `/etc` whose target belongs to a package (a `*.wants` link, `/etc/rc?.d`,
      `conf-enabled`) → judged like that package;
   6. a file a package's postinst writes in a shared folder (`GENERATED_BY`: `/etc/security/limits.d/audio.conf`
      and `.disabled` → jackd2) → judged like that package;
   7. a file under `/etc` in a folder that a package owns (nearest owned parent; never `/etc` itself, a shared
      `*.d` folder or `/etc/systemd`) → judged like that package (`/etc/ppp/peers/provider` → ppp);
   8. a desktop cache (`mimeinfo.cache`, `defaults.list`, xdg's dummy menu; `icon-theme.cache`; everything in
      `~/.local/share/mime` but `packages/`) → kept while one of its sources (a `.desktop`, an icon, a MIME
      package) stays, a leftover otherwise.
   A new folder is judged the same way, then: kept when everything it holds is kept ("holds only what stays" —
   `~/opt` holding a kept REAPER, `~/.config`, `*.wants` folders), kept when it is an **empty** standard XDG
   folder (`~/.local/bin`, `~/.local/share/applications`…), a leftover otherwise. A new **unit** (enabled or
   masked) is judged like the package that ships its unit file or SysV script; one with golem's name, or that no
   package ships, is a leftover.

   Third cycle replayed through these rules (2026-10-16, the run's own footprints; link targets and unit owners
   reconstructed from the same Ubuntu 24.04 release, since that `after` predates their collection): of the 103
   leftovers, 100 are kept by the rules above once the plan carries REAPER's desktop integration, and 3 stay real
   leftovers that the new engine removes — the two sudoers rules and the empty `~/golem-inbox`. Judged against that
   run's own plan, 46 stay: those 3, plus REAPER's desktop integration (files, MIME database, icon cache and their
   folders) that that plan did not offer.

Run it twice: on a machine without REAPER (golem installs it) and on one where REAPER, guitarix and the user's
`audio` membership were there before (they must survive).

## 8. Fixed along the way

- `reaper.ini.bak` rewritten on every run → the prior keys live in the receipt.
- `harden.sh` overwriting `20auto-upgrades`, ufw and governor states never saved → recorded in `prior`.
- `golem autostart off` leaving linger on → linger goes back to its prior value.
- the installer's askpass folder in `/tmp` never removed → removed when the installer closes.
- local backups live inside the install folder → the uninstaller's backup never goes there.

## 9. Windows

> **Status: FIXED (design, 2026-10-16). CODED 2026-10-16** — receipt (§9.2), engine (§9.3), graphical uninstaller
> (§9.4), backup (§9.5), VM tools and judge (§9.6). **Tested on Linux only**: a fake Windows profile given by the
> environment, every command and the elevation replaced (`tests/test_uninstall_win.py`, `tests/test_uninstaller_gui.py`,
> `tests/test_uninstall_judge.py`). **First real cycle on a clean Windows 11 VM: 2026-10-16**, everything ticked —
> seven defects found, fixed and coded the same day (§9.8); the fixes are tested on Linux only and wait for the next
> VM cycle. Same contract as Linux — receipt first, an engine with a dry plan, the same screens, the same VM test
> — with the differences below. macOS follows later on the same model.

### 9.1 What a Windows install leaves

| Family | Items | Privilege |
|---|---|---|
| golem | install folder (`%USERPROFILE%\golem`, venv, `golem.cmd`), `%USERPROFILE%\golem-inbox`, `%LOCALAPPDATA%\GoleM` (browser profiles, runtime, NAM training env), `%LOCALAPPDATA%\golem-installer` (bootstrap cache), `%TEMP%\golem-install-*.log` | user |
| Python | Python 3.12 per-user from the bootstrap (`%LOCALAPPDATA%\Programs\Python\Python312`, HKCU Uninstall key) — only when no Python was found | user |
| REAPER | `C:\Program Files\REAPER (x64)` (NSIS, only if absent) and `… (x64).golem-prev` after an engine update | admin |
| REAPER resource folder | `%APPDATA%\REAPER`: `Scripts\golem`, `Effects\golem`, `OSC\golem.ReaperOSC`, the `__startup.lua` wrapper (user's original kept as `__startup.golem-user.lua`), `golem-root.txt`, `golem-runtime.txt`, `GoleM\` (logs, lock), `reaper.ini` keys (OSC surface, `verchk`, `norunmute`, `automute`, MIDI masks, `[audioconfig]`), `reaper-license.rk` | user |
| Plugins and runtimes | NAM VST3 (Inno), AVL Drumkits (NSIS), sfizz (Inno), PawPaw/Vitalium (Inno), Proteus (Inno), VC++ runtime (Burn), Airwindows TapeDelay2 and the Dragonfly Hall/Plate/Room VST3 bundles (`%LOCALAPPDATA%\Programs\Common\VST3\GoleM`), installer cache `%ProgramData%\GoleM` | admin, except TapeDelay2 and Dragonfly |
| System | firewall rules `GoleM - Reaper, no inbound network`, `GoleM - bridge` (+ legacy names), `GoleM - golem.local (mDNS)` | admin |
| Integration | shortcuts (Desktop and Start menu: golem, golem server, Stop golem), autostart (`Startup\golem server.lnk`), active power plan (prior in `config\.power.json`) | user |

### 9.2 The receipt on Windows

> **Status: CODED (2026-10-16), tested on Linux only** (`tests/test_receipt_windows.py`: path per OS, `msvcrt` lock
> through a fake, fragments, the PowerShell scripts read as text, `desktop.setup` on a fake resource folder). Not yet
> run on a Windows VM.

- **Path**: `%LOCALAPPDATA%\GoleM\install-receipt.json` (macOS: `~/Library/Application Support/golem/install-receipt.json`;
  Linux unchanged). `provision/receipt.py` resolves it per OS (`default_path()`) and locks `<receipt>.lock` with
  `msvcrt.locking` on Windows (non-blocking, retried for 30 s). No `SUDO_USER` logic on Windows. `GOLEM_RECEIPT`
  still overrides it on every OS. `bridge/install_receipt.py` writes on Linux and Windows (into an existing receipt only).
- **Stored paths.** An item's path inside the user's profile is written relative to `%LOCALAPPDATA%`, `%APPDATA%` or
  `%USERPROFILE%` (the longest match wins, case-insensitive): `%APPDATA%\REAPER\Scripts\golem`. A system path
  (`C:\Program Files\…`, `C:\ProgramData\GoleM`) stays absolute. `prior` values that are paths may be absolute
  (`prior.python.path`, `prior.programs.*.path`). **Every reader passes a path through `receipt.expand()`**, which
  turns `%VAR%` (Windows) and `~` (Linux, macOS) back into the real path and leaves an absolute one as is. Owner:
  `user` for a `%…%` path, `root` (= needs administrator) otherwise.
- **Fragments.** What cannot call `receipt.py` drops a small JSON next to the receipt,
  `<receipt>.pending-<name>.json`: `{"format": 1, "by": …, "items": [{path, kind, group, owner, existed, moved_to}],
  "prior": {"dotted.key": value}, "append": {"dotted.key": [values]}}`. The next locked write of `receipt.py` merges
  it — `prior` keys first-wins, `append` lists completed and deduplicated (objects by `name`) — then deletes it; an
  unreadable fragment is set aside as `.bad`. `load()` merges pending fragments in memory without writing.
  `receipt.py merge-pending` (and `merge_pending()`) merges them into an existing receipt.
- **The bootstrap** (`bootstrap.ps1`, before the repository exists) writes the fragment `pending-bootstrap.json`:
  `prior.python = {installed_by_golem, version, path}`, true only when it downloaded and installed Python itself —
  then also `prior.python.uninstall`, the bundle's HKCU `QuietUninstallString` (`"…\Package Cache\{guid}\
  python-3.12.10-amd64.exe" /uninstall /quiet`). And `prior.pip_cache_existed`: whether `%LOCALAPPDATA%\pip` existed,
  read at its very start, before Python and any pip. `provision/desktop.py setup` records the same key right before
  its first `pip install` (first wins: it only counts when the bootstrap did not run). It
  never replaces a fragment already there. The installer's *source* step creates the receipt (`set_root`, as on
  Linux), which merges it.
- **`install-system.ps1`** (elevated) receives the receipt path as **`-Receipt`** from its non-elevated caller
  (`installer/platform_windows.py run_elevated`, `bridge/desktop_reaper.py`, `bridge/desktop_network.py open_firewall`)
  — never resolved as administrator, whose `%LOCALAPPDATA%` may be another account's. It writes the fragment
  `pending-system-<pid>.json`, rewritten after each component (a failure halfway keeps what was installed); the
  caller merges it as soon as the elevated process exits. It records:
  - `prior.programs.<id>` for `reaper`, `nam_vst3`, `avldrums`, `sfizz`, `pawpaw`, `vcredist`:
    `installed_by_golem` (it ran the vendor installer; `vcredist` exit 1638 = a newer one was there: false), `path`,
    `version`, and when installed `uninstall`, `display_name`, `uninstall_key`. The uninstall command is read right
    after the install from the `Uninstall` key that **appeared** during it (HKLM 64/32-bit, HKCU) and whose
    `DisplayName` matches; `QuietUninstallString`, else `UninstallString` + the family's silent switch (NSIS `/S`,
    Inno `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`, Burn `/uninstall /quiet /norestart`). Not found: `uninstall:
    null`, said in the log — the uninstaller never guesses.
  - `prior.reaper.{installed_by_golem, path, version, uninstall}` — the Linux shape.
  - `firewall.added` (top level, like `apt.added`): the display names of the `GoleM - …` rules it created.
  - `prior.firewall_deleted`: each Windows-made rule for the bridge's Python, **exported before it is deleted**
    (`name, displayname, program, direction, action, profile, protocol, ports, enabled`).
  - `prior.common_dirs = {VST3, LV2, CLAP}`: whether each `%CommonProgramFiles%\<dir>` existed **before** any vendor
    installer ran (recorded at the start of every run; first wins, so a later firewall or engine-update run, which
    sees them already there, changes nothing).
  - items (group `system`, owner `root`): `%ProgramData%\GoleM` (`existed` when it was there), `REAPER (x64).golem-prev`
    after an engine update.
- **`provision/desktop.py setup`** (into an existing receipt only — a hand-run setup on an older install would record
  golem's own values as the machine before it) records, group `reaper-links`: `Scripts\__startup.lua` (with
  `moved_to: …\__startup.golem-user.lua` whenever that file exists), `Scripts\golem`, `Effects\golem`,
  `OSC\golem.ReaperOSC`, `golem-root.txt`, `golem-runtime.txt`, `GoleM\`; group `golem`: `%LOCALAPPDATA%\GoleM` and the
  browser profile. `reaper.ini`: `prior.reaper_ini.keys` for every `[reaper]` key it writes (`verchk` when added,
  `norunmute`, `automute` — first value wins), `existed: false` when it created the file, `csurf_added: true`, and
  for the `[audioconfig]` it seeds before REAPER's first start, `prior.reaper_ini.audioconfig = {section_added,
  keys: {mode, asio_driver, …: value before or null}}`.
- **Shortcuts**: each `.lnk` that `install_shortcuts` writes, by the path PowerShell returns (`GetFolderPath`, so a
  OneDrive-redirected Desktop is right), group `golem` — including **"Uninstall golem"** (Start menu): the **base**
  Python's `pythonw.exe` (`home` of `.venv\pyvenv.cfg`, else `sys._base_executable`; never the venv's) running
  `<root>\installer\server.py --uninstall --root <root> --open`, working folder the user's home. The autostart link
  `Startup\golem server.lnk` when turned on. TapeDelay2 (`provision/airwindows.py`, group `plugins`), the Dragonfly bundles (`provision/dragonfly.py`, group `plugins`).
- **Power plan**: `bridge/desktop_power.py` records `prior.power_scheme = {guid, name}` the first time the boost
  changes the plan; `config\.power.json` keeps working for boost OFF.
- **Licence**: `installer/platform_windows.py` sets `RECEIPT = True`, so screen 3's `prior.reaper.license_present`
  is recorded on Windows too.

### 9.3 The engine on Windows

`provision/uninstall.py` keeps one plan model and one CLI (`plan` / `run`). The OS-specific parts sit behind a
platform layer (`provision/uninstall_win.py`): paths (`%APPDATA%`, `%LOCALAPPDATA%`, `%ProgramData%`, Program Files
from the environment, never hard-coded), the forbidden-paths list, the running-check (`desktop.reaper_running`), the
stop (`python -m provision.desktop stop`, then the windows closed), and elevation.

| Group | Windows items | Default |
|---|---|---|
| `golem` | as §9.1, plus autostart off and the power plan put back | removed |
| `reaper-links` | the golem files in `%APPDATA%\REAPER`, `__startup.lua` restored from `__startup.golem-user.lua` | removed / restored |
| `reaper-ini` | same revert as Linux | reverted |
| `system` | golem's firewall rules removed; deleted rules recreated from `prior.firewall_deleted`; `%ProgramData%\GoleM`; `REAPER (x64).golem-prev` | removed / restored |
| `programs` (Windows' `apt`) | REAPER, NAM VST3, AVL Drumkits, sfizz, PawPaw — each by its **vendor uninstaller**, silent, only if the receipt says golem installed it | checked if golem installed it, except REAPER (unchecked, as on Linux). PawPaw says it removes **all** PawPaw plugins |
| `plugins` | TapeDelay2 | checked |
| `toolchain` | Python per-user, if golem installed it | unchecked (other scripts may use it) |
| never offered | the VC++ runtime (system base, like Linux's NEVER_APT) | — |

**Elevation: one UAC prompt.** The admin items run in one generated PowerShell script through the installer's
existing elevated path (`Start-Process -Verb RunAs`, log file read live), never one prompt per item. Refusing UAC is a
stated failure with Retry.

**No-receipt mode** works as on Linux: golem-named items by name (folders, `GoleM - *` firewall rules, shortcuts,
the startup link); vendor programs are listed as `unknown`, unchecked; nothing is uninstalled on a guess.

**As coded (2026-10-16).**

- **Dispatch.** `uninstall.py main()` hands over to `provision/uninstall_win.py` when `sys.platform == "win32"`
  (loaded next to itself, so the uninstaller's copy in `%TEMP%` works). Same commands, same plan JSON, same `run
  --json` lines; the plan adds `"platform": "windows"` and `check_yourself` (§9.7); `never_apt` lists the VC++ runtime.
  The Linux engine is unchanged except two shared helpers: `ini_revert` keeps CRLF line ends, `revert_ini_file(path…)`.
- **Context.** `WinCtx` reads `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `ProgramData`, `ProgramFiles`,
  `CommonProgramFiles` (and `ProgramFiles(x86)`, `SystemRoot`) from the environment; Desktop, Start menu and Startup
  from the shell (`SHGetFolderPathW`: a OneDrive-redirected Desktop is right), with a fallback under the profile. No
  `C:\` anywhere. Receipt paths (`%APPDATA%\…`, `~\…`, absolute) are expanded by `WinCtx.expand` — the same rule as
  `receipt.expand()`, which only expands `%VAR%` when it runs on Windows (the tests run elsewhere).
- **Receipt.** Loaded with `receipt.load()` (sibling `provision/receipt.py`, copied with the uninstaller), so pending
  fragments (`<receipt>.pending-*.json`) are merged in memory. No receipt file = no-receipt mode. When the receipt is
  rewritten, the fragments are deleted (they are in it; keeping them would bring consumed priors back, first-wins).
  When it is deleted, its `.lock` and fragments go too, then `%LOCALAPPDATA%\GoleM` if empty. That folder is item
  `golem:local-data`, emptied in the user step **except** `install-receipt.json*`; the receipt step comes last (§5).
- **Item ids.** `golem:install-folder`, `golem:local-data`, `golem:installer-cache`, `golem:tmp` (`%TEMP%\golem-*`,
  never `golem-uninstall*`), `golem:inbox`, `golem:shortcut:Desktop|Programs/<name>.lnk` (any `.lnk` whose name holds
  "golem", "Uninstall golem" included), `golem:autostart` (`Startup\golem*.lnk`), `golem:power-plan`
  (`powercfg /setactive` to `prior.power_scheme.guid`, else `config\.power.json` `before`; not listed when that plan
  is already active), `reaper-links:Scripts/golem|Effects/golem|OSC/golem.ReaperOSC|golem-root.txt|golem-runtime.txt|GoleM`,
  `reaper-links:Scripts/__startup.lua` (only when it starts with golem's hook line; `restore` puts
  `moved_to` / `__startup.golem-user.lua` back), `reaper-ini:revert`, `system:firewall:<display name>`,
  `system:firewall-restore`, `system:programdata`, `system:reaper-prev`, `system:common-dirs`,
  `programs:<reaper|nam_vst3|avldrums|sfizz|pawpaw>`, `plugins:tapedelay2`, `reaper:config`, `toolchain:python`,
  `toolchain:pip-cache`; at run time only, `toolchain:python:firewall` (added to the elevated pass when Python is
  chosen). Privilege `admin` (not `root`) for `system` and `programs`.
- **`reaper.ini`.** `[reaper]` as on Linux, plus `[audioconfig]` from `prior.reaper_ini.audioconfig`:
  `section_added` removes the whole section golem added; otherwise each key goes back to its value (null = removed).
  With the section gone, REAPER asks again for an audio device at its next start — that is the machine before
  golem. Refused while any REAPER runs.
- **Programs.** Offered only when `prior.programs.<id>.installed_by_golem` is true **and** its files are there (else
  `absent`, consumed from the receipt); `installed_by_golem: false` ("existed") is never listed. **`uninstall: null` →
  not offered**, said in `warnings` ("remove it from Windows Settings ▸ Apps"). The command is split
  (`"…exe" args`, an unquoted `C:\Program Files\…\x.exe /S`, `MsiExec.exe /X{…}`) and the family's silent switch is
  added if missing. Without a receipt, present programs are listed `unknown`, unchecked, with the command Windows
  registered (read-only `winreg`), or `manual` (the run refuses it) when there is none. `vcredist` is never offered.
- **Firewall.** Rules named `golem*` (case-insensitive) are read at plan time (`Get-NetFirewallRule`, no admin): one
  item per rule present. **Checked only when golem made it**: its display name is in the receipt's `firewall.added`
  or among the fixed names (`FIREWALL_FIXED`, with the legacy ones); without a receipt, the fixed names only. Any
  other `golem*` rule is listed **unchecked**, origin `unknown`, "named like golem's rules, but golem did not create
  it" (the golem screen is read-only: it is never removed). `firewall.added` names already gone are consumed.
  Unreadable firewall: the fixed names are listed `presence: unknown`, "removed if present".
  `prior.firewall_deleted` → `system:firewall-restore`, each rule recreated with `New-NetFirewallRule` (DisplayName,
  Direction, Action, Profile, Program, Protocol, LocalPort, Enabled) only if no rule of that name exists.
- **Python's firewall rules.** When `toolchain:python` is chosen, the elevated pass gains an item
  `toolchain:python:firewall`: every **inbound** rule whose application filter `Program` is that Python's
  `python.exe` or `pythonw.exe` (folder of `prior.python.path`, compared case-insensitively) is removed — the
  "TCP/UDP Query User{…}python.exe" rules Windows made when the bridge first listened. And the
  `prior.firewall_deleted` rules whose program is that Python are **not** recreated (they would point to a removed
  program); if none is left to put back, `system:firewall-restore` says so and succeeds. Python kept: both behave as
  before.
- **Common Files containers** (`system:common-dirs`, receipt only). Each of `%CommonProgramFiles%\VST3|LV2|CLAP` that
  `prior.common_dirs` says did **not** exist before golem, and is there: one item, checked, action
  `remove-empty-dirs`, run **last** in the elevated pass (after the vendor uninstallers). A folder is removed only if
  it has no child item; one that still holds a plugin stays, and that is not a failure. Without a receipt they are
  never touched. Paths outside these three are refused before the script is written.
- **One elevated pass.** One generated PowerShell script (UTF-8 with BOM), system items first then programs, each in
  `Item n { … }` writing `@@ITEM n code message` to its log; run through `installer/elevate_win.py` — the **same**
  `Start-Process -Verb RunAs` + live log tail that `platform_windows.run_elevated` now uses (factored out of it; it
  also quotes any argument holding a space for `Start-Process`, which fixes `-BridgePython C:\Users\Jean Paul\…`).
  Every path in the script is single-quoted (`'` doubled). A vendor uninstaller is judged **on evidence**: after
  `Start-Process -Wait` (an NSIS uninstaller relaunches itself from `%TEMP%` and returns at once) the script waits at
  most **90 s** for its files — and its `Uninstall` key when the receipt gives `uninstall_key` — to be gone; still
  there = failed, with its exit code. Exit 1223 (UAC refused) = every admin item failed, "Windows permission was not
  granted — Retry and approve the Windows prompt"; the user items go on.
- **Stop (§5 step 2).** `<root>\.venv\Scripts\python.exe` (else the base Python) `-m provision.desktop stop`, cwd the
  install folder; then golem's browser windows are closed: `chrome.exe` / `msedge.exe` whose command line holds
  `--user-data-dir=%LOCALAPPDATA%\GoleM\…` (`taskkill /T /F`) — never your own browser, never the uninstaller's window
  (its profile is in its copy). Then **golem's REAPER** (a `reaper.exe` whose command line opens `<root>\sets\…`, read
  with `Get-CimInstance`) still running = **refusal**: nothing is touched, every chosen item fails with the reason,
  Retry. Deviation: the running-check is this process query, not `desktop.reaper_running()` (the copy has no
  `bridge`, and only golem's REAPER must block; any REAPER still blocks the `reaper.ini` revert).
- **Python** (`toolchain:python`): uninstalled **after the uninstaller closes** — it runs on that Python. The command
  is `prior.python.uninstall`, else the one Windows registered for the **bundle** — "Python 3.12.10 (64-bit)", HKCU,
  its `QuietUninstallString` — never one of its MSI components ("… Core Interpreter (64-bit)", `SystemComponent=1`);
  then `/norestart` is added. The run hands it to the **after-exit waiter** (`installer/after_exit_win.py`): a hidden
  PowerShell created **through WMI** (`Invoke-CimMethod Win32_Process Create`) — parented to `WmiPrvSE.exe`, outside
  the uninstaller's process tree and any job object, so neither `taskkill /T` nor a closing session, terminal or
  scheduled task kills it (a `Popen(DETACHED_PROCESS)` child did die in the VM: Python stayed, and Windows' Application
  log showed no uninstall attempt). A scheduled task would also escape the tree, but leaves a trace when its
  self-unregistration fails and can be blocked by policy. The waiter waits for the uninstaller's process
  (`GOLEM_UNINSTALL_WAIT_PID`, set by the graphical uninstaller; else the parent) plus 3 s, runs the command, waits up
  to 60 s for the Python folder to go, then removes the uninstaller's copy (`GOLEM_UNINSTALLER_COPY`, only if its
  name is `golem-uninstaller-*` and it carries the marker), and deletes its own script. It logs every step to
  `%TEMP%\golem-after-uninstall-<stamp>.log` (what it waited for, the command, its exit code, Python folder gone or
  not, copy removed or not). Reported "scheduled … (log: …)"; the Done screen shows the log path. A waiter that cannot
  start is a failure with its reason.
- **pip's cache** (`toolchain:pip-cache`, receipt only): `%LOCALAPPDATA%\pip`, offered when `prior.pip_cache_existed`
  is `false` and the folder is there; unchecked (like Python), "pip's download cache, created by golem's install".
  Never offered without a receipt or when it existed before golem.
- **Install folder.** Removed last; read-only files (`.git\objects`) are made writable first. A file still open is
  said ("close golem's windows and Retry"). Then `%LOCALAPPDATA%\Programs\Common\VST3` and `…\Common` if empty.

### 9.4 The graphical uninstaller on Windows

The same server and screens. Launch: a **"Uninstall golem"** Start-menu shortcut, and `golem.cmd uninstall`. At launch
it copies itself to `%TEMP%\golem-uninstaller-<random>` and restarts there **detached, with the base Python** (never
the venv's: the venv is deleted), since Windows has no `exec`. The window is an app window, as for the installer. The
venv's Python is `.venv\Scripts\python.exe` (the backup step used the Linux path).

**As coded (2026-10-16).** `platform_windows.UNINSTALL = True`. `server.py --uninstall`: `uninstaller.self_copy` (now
also `installer/platform_windows.py`, `desktop_steps.py`, `elevate_win.py`, `provision/desktop.py` — the app window —
`provision/uninstall_win.py`, `provision/receipt.py`), then `uninstaller.relaunch_detached`: `subprocess.Popen` with
`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, cwd the copy, std streams closed, the **base** `python.exe`
(`sys._base_executable`; `pythonw.exe` swapped for its `python.exe`), then the first process exits. The app window's
browser profile is `<copy>\browser` (`platform_windows.APP_PROFILE`): the installer's lives in `%LOCALAPPDATA%\GoleM`,
which is removed. Closing the window waits for a running backup or uninstall. `remove_tmp` retries for 5 s on Windows
(the browser releases its files late). **At exit** (`server.cleanup`, every exit path), on Windows: the app window is
closed first, the process leaves the copy (`chdir` to `%TEMP%`: a process cannot delete its current folder), then
`remove_tmp`; if the copy still resists, it is handed to the after-exit waiter (§9.3), which waits for this process
and removes it (marker checked). The engine's run gets `GOLEM_UNINSTALLER_COPY`, so when Python is removed the same
waiter does both jobs. Every command the uninstaller starts has `CREATE_NO_WINDOW`. **No password
on Windows**: Review says "Windows asks your permission once" when an `admin` item is chosen (`needs_uac`); the
Uninstall screen shows the Windows steps (stop, system settings, programs, REAPER, user files, folder, receipt).
`golem.cmd uninstall [--dry]` (written by `platform_windows.launcher_script`) runs `cd /d %TEMP%` first — the console
must not hold the folder being removed — then the base Python on `installer\server.py --uninstall --root <root>
--open`; `golem.cmd uninstall --dry-run` prints the plan.

### 9.5 Backup on Windows

`bridge/backup_cli.py` works as is. Two additions, on both OS: `%LOCALAPPDATA%\GoleM\captures` (user captures) go
into the backup, and the README says that the `secrets/` folder is **not** protected on NTFS by file modes — keep it
private.

**As coded (2026-10-16).** `backup_cli.captures_dir()` = the sibling of the NAM training folder
(`bridge/plugin_capture.py`, `train_home().parent / "captures"`): `%LOCALAPPDATA%\GoleM\captures` on Windows,
`~/.cache/golem-build/captures` on Linux (removed with `golem:cache:golem-build`), `~/Library/Application
Support/GoleM/captures` on macOS. Every file is copied to `captures/` in the backup, counted in the estimate and
checked by sha256 like the identity files; the README says where to copy it back. The NTFS note is written when
`secrets/` is.

### 9.6 The VM test on Windows

`tools/footprint.ps1`, read-only, sent through `win.sh ps`. It lists:

- the Uninstall keys (HKLM and HKCU);
- Program Files and Common Files (`VST3`, `LV2`);
- `%APPDATA%`, `%LOCALAPPDATA%` and `%ProgramData%`, filtered as on Linux;
- the firewall rules;
- the shortcuts and the Startup folder;
- the active power plan.

`tools/check-uninstall-vm.sh` gains a `--win` mode. The judge classifies the same way:
upgrades, kept by design or by choice, real leftovers. Start from `bare-windows`, install, uninstall with everything
ticked, verdict 0 real leftovers.

**As coded (2026-10-16).** `tools/check-uninstall-vm.sh --win before|installed|after`. `footprint.ps1` (ASCII,
read-only) travels on the standard input of `win.sh ps` (a one-line `-EncodedCommand` reads and runs it: the script
itself would exceed cmd.exe's 8191-character line). Sections: `uninstall-keys` (`HKLM|HKLM32|HKCU <DisplayName>`),
`versions`, `install-locations` (`name | InstallLocation | uninstaller folder`), `program-files` (Program Files one
level, Common Files `VST3`/`LV2`/`CLAP` two, `%LOCALAPPDATA%\Programs` four), `files` (`%APPDATA%` and
`%LOCALAPPDATA%` five levels, `%ProgramData%` four, the profile one, `%TEMP%\golem*`), `firewall` (`DisplayName |
Enabled | Direction | Action`), `shortcuts` (Desktop, public Desktop, Start menu, common Start menu, Startup), `power`
(active GUID). A coarse noise filter keeps it small; a path holding "golem" is never filtered. `installed` saves the
plan from the **installed** engine (the Python of `golem.cmd`, `uninstall.py plan --json`, read-only). `after` also
reads, read-only, **what was really chosen** (`chosen.txt`: the uninstall log next to the backup,
`golem-backup-*\uninstall-*.log`, every attempt; else the `select-*.json` of a copy left in `%TEMP%`) and passes it
as `--chosen`; without it the judge says it assumes the plan's defaults. It prints the after-exit waiter's log
(`after-uninstall.log`).

`uninstall-judge.py judge --win` (`judge_win`), rules in order:

1. a program (`Uninstall` key): the VC++ runtime → kept (system base); one the plan offered (`programs`,
   `toolchain:python`) and still there → kept if you unticked it, a leftover if you chose it ("still installed");
   a Microsoft component Windows installs or updates by itself (`WIN_CHURN_PROGRAMS`: OneDrive, Edge, WebView2…) →
   kept, its Start-menu shortcut too; else a leftover. No "upgraded" class on Windows.
2. a file or folder: the backup → kept; inside an offered item → the most specific item decides (an item **chosen**
   = must be gone — with `--chosen` the real choice, else the golem screen's ticks; a program item not kept = left
   behind by its uninstaller); inside the `InstallLocation` or uninstaller folder of a kept program → kept; a plugin
   bundle under `Common Files\VST3|LV2|CLAP` → the program whose bundle it is (kept → kept, removed → leftover), an
   unknown bundle → kept only if a **program** (`programs:*`) is kept — never attributed to `toolchain:python`, and the
   container folder itself is judged as a folder (holds only what stays → kept; empty → leftover); the after-exit
   waiter's log (`golem-after-uninstall-*.log`) → kept on purpose; the `Package Cache` of the VC++ runtime
   (ProgramData) or of a kept Python → kept; **Windows noise** → kept; golem's name → leftover; anything else →
   leftover. A folder holding only what stays is kept. A path from **before** golem that disappeared is a leftover,
   unless it is Windows noise (OneDrive's versioned folder replaced by its auto-update, a `Temp\tmpXXXX.tmp`).
3. a firewall rule that appeared: golem's (an offered rule that was chosen, a fixed name, golem's name) → leftover;
   an offered rule left unchecked (a `golem*` name that is not golem's) → kept; Windows' own rule for a kept program
   (`reaper.exe`, `python.exe`) → kept, for a removed one → leftover; **any other → kept, Windows churn** (Store apps
   updating: Teams, Xbox TCUI, Calculator, Feedback Hub, Widgets…). A rule from **before** golem that is gone or
   changed → leftover (it had to be recreated — how the `GoleM sshd` deletion was caught).
4. a shortcut: in an offered, kept item, or named after a kept program → kept; else leftover.
5. the power plan changed → leftover. Any line from before golem that disappeared → leftover.

**Windows noise** (`WIN_NOISE`, explicit, each with its reason; complete it only from a VM run, never to hide a
trace): `%LOCALAPPDATA%\Temp`, `%LOCALAPPDATA%\Microsoft` (Windows, Edge, OneDrive caches), `%APPDATA%\Microsoft`
(recent files, PowerShell history, credentials), `Packages` (Store apps), `LocalLow`, `ConnectedDevicesPlatform`,
`D3DSCache`, `CrashDumps`, `Comms`, `PlaceholderTileLogoFolder`, `Publishers`, `PeerDistRepub`, `IconCache.db`, your own
Chrome/Firefox profile, OneDrive, `%ProgramData%\Microsoft` (Defender, Search, WER),
`%ProgramData%\Packages|USOShared|USOPrivate|regid.*|ssh`, `Prefetch`, the `NTUSER.DAT` hive.

**What only the Windows VM can prove** (first cycle run 2026-10-16, §9.8; to replay after its fixes): the UAC prompt and the 1223 path; the real vendor uninstallers
in silent mode (REAPER NSIS, NAM / sfizz / PawPaw Inno, AVL NSIS) and the 90 s wait; `Get-NetFirewallRule` reads and
the recreated `python.exe` rules; `powercfg`; the detached relaunch and the app window (profile in `%TEMP%`, copy
removed at exit with the browser just closed); `golem.cmd uninstall` from a console; the Python uninstall after the
window closes; the install folder with `.git` read-only files and a just-stopped bridge; `footprint.ps1` through
`win.sh ps` standard input (console code page) and its size; the judge's noise list against real Windows churn; the
Windows-only screens (Review's UAC card, the Windows steps, "Check yourself") at render.

### 9.7 What stays, said on the Done screen

Wi-Fi profiles and the mobile-hotspot name or passphrase that golem may have set are not recorded, so the uninstaller
cannot tell them from yours. It lists them as "check yourself" and never deletes them.

**As coded (2026-10-16).** The Windows plan carries `check_yourself` (where each is, in Windows Settings); the Done
screen shows it under "What remains, and why", and `uninstall.py plan` prints it.

### 9.8 First VM cycle (2026-10-16) — what it found, as coded

> **Status: CODED 2026-10-16**, tested on Linux only (`tests/test_uninstall_win.py`, `tests/test_uninstaller_gui.py`,
> `tests/test_uninstall_judge.py`, `tests/test_receipt_windows.py`). To be replayed on the Windows VM.

Clean Windows 11 VM, install, then uninstall with everything ticked. Evidence: `~/.cache/golem-vm/footprint-win/`.

| # | Found | Fix |
|---|---|---|
| 1 | **The firewall over-reached**: every rule named `golem*` was removed — including the VM's own `GoleM sshd` (SSH lost). On a user's machine, any rule of theirs named so would go. | Checked = live rules in `firewall.added` ∪ `FIREWALL_FIXED`; other `golem*` rules listed unchecked, origin unknown (§9.3 Firewall). |
| 2 | Windows' "Query User" `python.exe` allow rules stayed after Python was chosen for removal. | `toolchain:python:firewall` in the elevated pass; rules for that Python not recreated (§9.3). |
| 3 | **The deferred Python uninstall never ran** (no attempt in Windows' Application log): the detached `Popen` waiter died with its tree or job. | The after-exit waiter is created through WMI, logs to `%TEMP%\golem-after-uninstall-<stamp>.log`; the bundle's quiet command, never an MSI component (§9.3 Python). |
| 4 | `%TEMP%\golem-uninstaller-<x>\` (with the window's `browser\` profile and `select-1.json`) stayed. | Window closed first, `chdir` out, then removal; a copy that resists goes to the same waiter (§9.4). |
| 5 | `%LOCALAPPDATA%\pip` (pip's cache, from the venv's pip) was not offered. | `prior.pip_cache_existed` at bootstrap / before setup's pip; `toolchain:pip-cache` (§9.2, §9.3). |
| 6 | `Common Files\VST3` and `LV2` stayed as empty folders after the vendor uninstallers. | `prior.common_dirs` in `install-system.ps1`; `system:common-dirs`, last, only if empty (§9.2, §9.3). |
| 7 | Judge noise: Store-app firewall rules, OneDrive's versioned folder and its HKCU key, `Temp\tmp*.tmp`, `PeerDistRepub`; `Common Files\LV2`/`VST3` attributed to `toolchain:python`; the plan's defaults taken for the user's choice. | Firewall churn class, noise on vanished lines, `WIN_CHURN_PROGRAMS`, bundle attribution by program, `--chosen` fed by `check-uninstall-vm.sh --win after` (§9.6). |

The one leftover the judge rightly kept as (c): `GoleM sshd`, a rule from before golem that disappeared — that is how
defect 1 was caught.
