# Install and provisioning pitfalls

Provisioning scripts live in `provision/` (`install.sh` and the scripts it calls). An install must
work on a bare machine, non-interactively, and be replayable. Most of these bugs never show on a
development machine and always show on a fresh rack.

---

## A test install must not inherit the developer's state

**Symptom.** A clean-VM install "works" because it received the developer's configuration — and
received secrets (API keys, device tokens) with it.

**Cause.** Pushing the working directory with `rsync` without honouring `.gitignore`.

**Rule.** Push exactly what a `git clone` would give: `--filter=':- .gitignore'`. In an rsync filter
file, `!` CLEARS the list — it is not a negation: re-include tracked files explicitly with
`--include=` BEFORE the filter. `--delete` protects excluded files, so replaying a push does not clean
a polluted VM: restart from a clean snapshot.

**Code.** `provision/vm/vm.sh` (`--include='.env.example'` then `--filter=':- .gitignore'`),
`.gitignore` (`!.env.example`).

---

## A package that "is just there" on the dev machine

**Rule.** Every runtime dependency is listed explicitly (`provision/packages.txt`); test on a bare OS
snapshot to find those present only by accident.

---

## A package that a new Ubuntu release removed

**Symptom.** The install dies in its first phase, on a newer Ubuntu, with
`E: Package 'invada-studio-plugins-lv2' has no installation candidate` — before anything is installed.

**Cause.** The whole of `packages.txt` went to a single, fatal `apt-get install`: one package dropped by
the distribution (Invada, gone in Ubuntu 26.04) failed every package, and the install with them.

**Rule.** Resolve the list against the index after `apt-get update`. A package that a block or a tool can
live without is marked optional (`name?` in `packages.txt`): if it has no candidate it is skipped and
announced (a warning on the installer screen); an essential package with no candidate still stops the
install, naming it. The install receipt gets the filtered list. "No candidate" is both
`Candidate: (none)` and an empty `apt-cache policy` (unknown name); read it under `LC_ALL=C`.

**Code.** `provision/lib-packages.sh` (`golem_packages_resolve`), `provision/install.sh` (phase 1),
`tests/test_packages_list.py`.

---

## `sudo -v` needs a terminal, even with NOPASSWD

**Rule.** Try `sudo -n true` first; prompt only if needed. Keep the ticket alive in a background loop
that dies with the installer.

**Code.** `provision/install.sh` (`sudo -n true` keepalive).

---

## sudo-rs ignores `SUDO_ASKPASS` without `-A`

**Symptom.** On Ubuntu 25.10 and later, the graphical installer says "Nothing new for 3 min" on System packages (or
"sudo requis"), and a password prompt waits in the terminal that started `./install-linux.sh` — started from an
icon, with no terminal, the install hangs for good.

**Cause.** Ubuntu ships **sudo-rs** as `/usr/bin/sudo`. Classic sudo uses the `SUDO_ASKPASS` helper on its own when
it has no terminal; sudo-rs uses it **only with `-A`**. The scripts call plain `sudo`.

**Rule.** Under the installer, a `sudo` shim sits first in the job's `PATH`, next to the askpass helper (same 0700
folder, same lifetime): `exec <real sudo> -A "$@"`. The real sudo is resolved once, by absolute path, before the
shim exists — never a bare `sudo`, which would call the shim again. `-A` is understood by both implementations. A
sudo failure is said on the screen ("golem could not get administrator rights"), never left to the stall notice.

**Code.** `installer/platform_linux.py` (`_askpass`, `_real_sudo`, `job_env`), `provision/install.sh` (sudo check),
`tests/test_installer_window_linux.py`.

---

## golem's processes survive a log-out — "log out and back in" is not enough

**Symptom.** After the first install and a log-out/log-in, the audio still crackles: REAPER runs without real-time
priority although the user is now in the `audio` group.

**Cause.** The installer starts the bridge and REAPER (Connect screen, first start) with `setsid nohup`: they belong
to no session and survive the log-out. `golem desktop` then finds them ("déjà actif") and reuses a REAPER started
before the user had the rights.

**Rule.** Say "Restart your computer to finish" — only when the install just gave the rights: the user is in `audio`
in `/etc/group` but the installer's own process (the old session) is not. The Done screen offers **Restart now**
(`golem stop`, then `systemctl reboot`, no sudo from a graphical session) and "Open golem anyway"; closing the
installer in that case also runs `golem stop`. Already in `audio` before the install: nothing to restart.

**Code.** `installer/platform_linux.py` (`restart_needed`, `stop_golem`, `restart`), `installer/server.py`
(`/api/restart`, `/api/quit`), `installer/ui/installer.js` (Done), `provision/install.sh` (summary).

---

## The dpkg lock fails the first install on a fresh machine

**Symptom.** The install fails the first time and succeeds the second — looks like bad luck.

**Cause.** `unattended-upgrades` holds `/var/lib/dpkg/lock-frontend` for minutes after boot.

**Rule.** `apt-get -o DPkg::Lock::Timeout=300` on every apt call.

**Code.** `provision/*.sh` (`DPkg::Lock::Timeout=300`).

---

## SIGPIPE under `pipefail`

**Symptom.** The whole install exits 141.

**Cause.** `tr -dc … < /dev/urandom | head -c 16`: `head` closes the pipe, `tr` gets SIGPIPE, and
`pipefail` turns it into a failure. It sleeps until the script is first called.

**Rule.** Bound the producer so it ends normally (`head -c 1024 /dev/urandom`), truncate downstream
(`cut`).

**Code.** `provision/setup-net-sudo.sh` (PSK generation).

---

## The install must be replayable

**Symptom.** The second run fails (`gpg: cannot open '/dev/tty'`).

**Cause.** `gpg --dearmor -o <existing file>` asks for confirmation before overwriting; with no TTY it
dies.

**Rule.** Every step is idempotent and non-interactive (`gpg --batch --yes`). Test the install twice
in a row.

**Code.** `provision/install-sfizz.sh`.

---

## Patched plugin builds are not installed by `git pull`

**Rule.** Fixes that live in a compiled plugin (x42 zeroconvo, NAM LV2) require running their script
on each installed rack, restarting REAPER and checking `/proc/<pid>/maps`. The scripts verify a
string only the patched binary contains. See [plugins.md](plugins.md).

**Code.** `provision/install-zconvo.sh`, `provision/install-nam.sh`, called from
`provision/install.sh`.

---

## Every download is pinned

**Rule.** Binaries are fetched through a verifier that refuses unpinned URLs and wrong hashes; no
"latest" or nightly builds; Python dependencies are installed from a hash-locked file with
`--require-hashes`; a REAPER update without a known hash is not installed silently.

**Code.** `provision/lib-fetch.sh` `fetch_verified`, `provision/downloads.sha256`,
`bridge/requirements.lock` (`provision/bridge-setup.sh`, `provision/desktop.py`),
`bridge/reaper_update.py`, `tests/test_downloads_pinned.py`.

---

## Scripts run with sudo write into root's home

**Symptom.** A plugin installed by a script run with sudo is never seen by REAPER.

**Cause.** `$HOME` is root's home under sudo.

**Rule.** Resolve the invoking user's home (`$USER_HOME` / `SUDO_USER`) for user-scoped installs.

**Code.** `provision/install-plugins.sh`.

---

## Editing `reaper.ini` while REAPER runs is lost

REAPER rewrites `reaper.ini` when it quits. Edit it only after the process has exited.

---

## A fresh install must not assume the author's sound card or set

**Symptom.** First start on a new machine: the loading screen waits on the sound card forever; on the hidden
display (`:99`) REAPER shows "There was an error opening the audio hardware: JACK…" and "There was an error
opening the project …/sets/golem-set.rpp". Both are modal: REAPER runs nothing, `.command.json` is never acked.

**Cause.** `reaper.ini` got `alsa_indev/outdev=hw:V276` (the author's Volt 276) and no `linux_audio_mode`, so
REAPER tried JACK; `bridge/config.alsa_card()` also fell back to the literal `V276`. `sets/golem-set.rpp` is local
state that a fresh machine does not have, yet `start.sh` passed it to REAPER.

**Rule.** No card is a default. REAPER runs raw ALSA (`linux_audio_mode=1`) on the active card resolved like the
bridge (io.json > registry > first plugged USB card), or the silent ALSA `null` device when there is none. A
configured card that is absent is replaced by the active one only if that one is plugged; a working user choice is
never touched. No set → REAPER starts with `-new`, as `golem desktop` does.

**Code.** `provision/reaper-ini-setup.py` (`audio_keys`), `bridge/config.py` (`alsa_card`), `provision/start.sh`,
`tests/test_reaper_ini_audio.py`, `tests/test_inputmap_seed.py`.

---

## Prebuilt plugins need x86-64-v3

**Symptom.** REAPER dies on the first recall with nothing in `/tmp/golem-reaper.log`; the kernel log says
`traps: reaper[…] trap invalid opcode … in neural_amp_modeler.so`. Seen on an Ivy Bridge laptop (i5-3337U: AVX, no AVX2/FMA).

**Cause.** The golem-binaries NAM is built with `-march=x86-64-v3`, and so is a source build with
`-DUSE_NATIVE_ARCH=ON`: despite its name, NAM's CMake maps that option to `-march=x86-64-v3`.

**Rule.** `cpu_x86_64_v3` (`provision/lib-prebuilt.sh`) decides. Without it, `install-nam.sh` skips the prebuilt,
compiles with `USE_NATIVE_ARCH=OFF` and `-march=native`, and marks the bundle `.golem-built-here`; a NAM without that
mark on such a CPU is rebuilt. If that build fails (or is interrupted), the script REMOVES the NAM bundle rather than
leave one that kills REAPER: NAM blocks go missing, the rest of the rig plays; `install.sh` says so. `plugins.sh` never
lays the x64v3 release on such a CPU. Check other plugins with `objdump -d … | grep -c vfmadd` before blaming the engine.

**Code.** `provision/lib-prebuilt.sh`, `provision/install-nam.sh`, `provision/plugins.sh`, `provision/install.sh`.

