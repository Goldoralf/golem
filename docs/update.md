# Updating a golem, and cutting a release

> **Status: CODED (2026-11-06)** — the "Update to …" button of Settings ▸ About. The git way is checked end to end on
> throw-away installs (a git clone and an extracted archive, v0.6.0 → a test v0.6.1) and on the maintainer's rack; the
> archive way (§3) on a Windows/macOS-style copy against the real GitHub (v0.6.0 → v0.6.1), **not yet on a real
> Windows or Mac**.

## 1. What the button does

`GET /api/system/update?fetch=1` (`bridge/routes_system.py`) runs `git fetch --tags origin` and compares `HEAD` with the
highest **tag** (`git tag --sort=-v:refname`): `up-to-date`, `update-available`, `ahead` (a dev rack in front of the
release) or `no-release`. Only tags count — `main` is never offered. `notes` is the **message of the annotated tag**,
signature stripped: the screen shows it as "What's new in …". Commit subjects are written in French (CLAUDE.md, rule 4)
and are never shown.

`POST /api/system/update {tag}` refuses local code changes (machine state under `config/`, `presets/`, `sets/`,
`mappings/`, `setlists/` does not count), checks the tag signature when a release key is declared
([`release-signing.md`](release-signing.md)), sets aside tracked local state (`bridge/local_state.py`), runs
`git checkout <tag>`, then restarts:

- **Linux**: `provision/reload.sh` — the bridge, and **REAPER too when its scripts changed**: `start.sh` records the git
  tree of `reaper/` in `presets/.reaper-tree` when it launches REAPER; `reload.sh` relaunches REAPER when the current
  commit's `reaper/` differs, or when nothing was recorded (a REAPER launched by an older version — the case of an
  update started by v0.6.0, which does not know this). `reload.sh --with-reaper` forces it. An uncommitted Lua edit
  does not count (same commit): reload it by hand (CLAUDE.md, rule 1). The rig comes back on its own: the bridge's
  startup policy recalls what was playing.
- **Windows, macOS**: `provision.desktop restart` — window, REAPER and bridge.

## 2. An install that came from an archive

On a machine without git (a fresh Ubuntu), `provision/bootstrap.sh` downloads the release **archive** instead of
cloning — and a folder without `.git` could never update. git arrives with the system packages
(`provision/packages.txt`), so right after them the installer links the folder to the repository
(`installer/platform_linux.ensure_git_repo`): `git init`, `origin` = the public repository, fetch of the installed tag
only (depth 1), `git reset` (the index follows the release, the files are not touched), then any file the archive
left out. The release name comes from the folder name: the bootstrap's cache (`golem-<tag>`), or the "Source code" zip
of a GitHub release, which unpacks into `golem-0.6.1` — without the `v` of the tag, put back. Never fatal: if it fails,
the install goes on and the button falls back to the archive way (§3). It is git the tool that is needed, never a
GitHub account: the repository is public.

## 3. Updating without git — Windows, macOS (by archive)

Windows and macOS installs are copies without `.git` (the PowerShell bootstrap always downloads the archive, and
neither installer installs git — Git for Windows is a heavy, elevated dependency, and the first `git` on a Mac opens
the Command Line Tools dialog). There the button redoes what the installer does (`bridge/release_update.py`), chosen
by `routes_system` whenever the install is not a git repository:

1. **Check** (`GET /api/system/update?fetch=1`, only on "Check for releases"): GitHub's `releases/latest` — the
   bootstrap's own request — gives the tag and its notes; the answer is kept in `presets/.release-check.json` for
   About's dot. The installed version is `.golem-release`, written by the installer (`installer/desktop_steps`, from the
   folder name) and by every update; an install without it is "unknown" and is offered the latest release. Response
   `mode: "archive"`.
2. **Update** (`POST`): the tag's zip (`/archive/refs/tags/<tag>.zip`, as `bootstrap.ps1`), extracted into a temporary
   folder (no member may leave it), copied over the install by the installer's own `desktop_steps.step_source` —
   `presets`, `sets`, `mappings`, `config`, `setlists`, `recordings`, `assets` are never overwritten —, then the files
   the previous version had and this one has not are removed (manifest `.golem-files`; never local state), and the
   version is written.
3. **Python packages**: if `bridge/requirements.lock` changed, pip runs — on Windows and macOS **after** the bridge has
   stopped (a loaded module cannot be replaced on Windows): flag `.golem-pip-pending`, read by
   `provision/desktop.py restart`; on Linux at once.
4. **Restart**: the same as the git way — everything on Windows/macOS, `reload.sh --with-reaper` on Linux (without git,
   the scripts' fingerprint cannot be compared).

When a release key is declared (from v0.6.2), the release's signed file list is checked before anything is copied
([`release-signing.md`](release-signing.md) §5).

## 4. Which REAPER is the rack's

`provision/lib-reaper.sh` (`rack_reaper_pids`) and `routes_system._rack_reaper_pids`: a process named `reaper` that is
**not a zombie** and **not a bench** — `tools/check-rig-materialize.py` and `tools/shell_snapshot.py` start theirs with
`-cfgfile`. A bare `pgrep -x reaper` saw a bench's zombie: `start.sh` believed REAPER was open and the restart stopped
it without relaunching it; `pkill -x reaper` also killed the bench's REAPER. The output of the relaunch goes to
`/tmp/golem-reaper-restart.log`.

## 5. Cutting a release

1. Everything on `main`, CI green on that commit, `tools/public_export.py --summary` at 0 forbidden occurrences.
2. `tools/release.sh vX.Y.Z notes.md`: an **annotated, signed** tag, version bumped (`v0.6.1` → `v0.6.2` for fixes) —
   never move a published tag. Its message is the release notes, **in English** — the update screen shows it. The
   script refuses an unclean tree, a HEAD that is not `origin/main`, a red CI or a non-zero public scan.
3. The script then publishes the GitHub release, marked **Latest** (not pre-release: the bootstrap and the update read
   "latest"), with the same notes and the signed file list (`SHA256SUMS`, `SHA256SUMS.sig`); GitHub attaches the
   source archives itself.
4. The website's Download button points at `releases/latest`: nothing to change there.

## 6. Not covered yet

- On a git install (Linux), Python dependencies are not reinstalled by the button: a release that changes
  `bridge/requirements.lock` needs that step there too (the archive way already has it). None did up to v0.6.1.
