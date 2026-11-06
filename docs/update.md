# Updating a golem, and cutting a release

> **Status: CODED (2026-11-06)** — the "Update to …" button of Settings ▸ About, checked end to end on throw-away
> installs (a git clone and an extracted archive, v0.6.0 → a test v0.6.1) and on the maintainer's rack.

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
left out. The release name comes from the bootstrap's cache folder (`golem-<tag>`). Never fatal: if it fails, the
install goes on and the screen says updates will need a git clone.

## 3. Which REAPER is the rack's

`provision/lib-reaper.sh` (`rack_reaper_pids`) and `routes_system._rack_reaper_pids`: a process named `reaper` that is
**not a zombie** and **not a bench** — `tools/check-rig-materialize.py` and `tools/shell_snapshot.py` start theirs with
`-cfgfile`. A bare `pgrep -x reaper` saw a bench's zombie: `start.sh` believed REAPER was open and the restart stopped
it without relaunching it; `pkill -x reaper` also killed the bench's REAPER. The output of the relaunch goes to
`/tmp/golem-reaper-restart.log`.

## 4. Cutting a release

1. Everything on `main`, CI green on that commit, `tools/public_export.py --summary` at 0 forbidden occurrences.
2. An **annotated** tag, version bumped (`v0.6.0` → `v0.6.1` for fixes): never move a published tag. Its message is the
   release notes, **in English** — the update screen shows it.
3. A GitHub release on that tag, marked **Latest** (not pre-release: the bootstrap and the update read "latest"), with
   the same notes. GitHub attaches the source archives itself; nothing else to upload.
4. The website's Download button points at `releases/latest`: nothing to change there.

## 5. Not covered yet

- Python dependencies are not reinstalled by the button: a release that changes `requirements*.txt` needs a step
  that runs pip (none did up to v0.6.1).
- Signed tags: inactive until a release key is declared ([`release-signing.md`](release-signing.md)).
