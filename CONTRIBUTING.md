# Contributing to golem

Thank you for helping. This page says how code is accepted. The licence rules are in
[`docs/licence.md`](docs/licence.md); the map of the documentation is [`docs/README.md`](docs/README.md).

## 1. Sign off your commits (DCO, no CLA)

golem has **no CLA**: nobody is asked to assign their rights. Instead, every commit carries

```
Signed-off-by: Your Name <you@example.org>
```

which `git commit -s` adds for you. It certifies the [Developer Certificate of Origin 1.1](DCO): you
have the right to give what you give. Because nobody assigns their rights, the project cannot be
relicensed without every contributor's agreement.

A contribution lands under the licence of the file it touches: GPL-3.0-or-later by default, MIT for
the in-house JSFX (`reaper/Effects/`) and the interchange-format specifications and examples
(preset format, `.gsx` chord grids, the `.golem` format and its parser `bridge/golemfile.py`, `docs/examples/`), LGPL for `reaper/Effects/golem_super8`
([`docs/licence.md`](docs/licence.md) §1).

## 2. Development setup

Most of golem runs without a rack: the bridge starts, serves the app and the API, and waits for
REAPER. [`docs/dev-setup.md`](docs/dev-setup.md) explains how to run it on a laptop with no sound
card, no REAPER and no foot controller, how to look at the UI in its real format, and what each
probe in `tools/` touches.

After editing any `bridge/*.py`, run `./provision/reload.sh`: the bridge runs uvicorn **without**
`--reload`, so otherwise you are testing the old code. JS, CSS and Lua changes only need a refresh.

## 3. The checks

### What CI runs

[`.github/workflows/ci.yml`](.github/workflows/ci.yml), on every push and pull request (Ubuntu 24.04,
Python 3.12, Node 24). Run the same steps locally, in this order, with the venv:

```sh
ruff check .                                          # static analysis
python tools/check-syntax.py                          # JS modules and REAPER Lua scripts (nothing else compiles them)
node --test app/*.test.mjs                            # app tests
python -c "from bridge import factory; factory.seed()"  # factory content — some tests assume it
python -m pytest -q tests                             # Python tests
```

Then `git status`: the suite must not leave tracked files modified.

Changes land on `main` by pull request: a pull request is merged only when CI is green and every commit
is signed off (DCO).
Install the local guard once: `git config core.hooksPath .githooks`. Before every push it runs the three
fast steps above (ruff, syntax, node tests, about 30 s); `GOLEM_PUSH_FULL=1 git push` adds pytest. A red
`main` opens an issue labelled `ci-red` ([`docs/quality-automation.md`](docs/quality-automation.md)).

### `tools/check-cold.sh`

`./tools/check-cold.sh` is the "cold" battery: everything that can be checked without a bridge,
REAPER or hardware. It runs pytest plus checks CI does not (pedal and pedalboard descriptors, the
UnO2 compiler, transcription rules, the Standards engine, the bar-length formula), and it does
**not** run ruff, the syntax check, the node tests or the factory seed. Passing one does not mean
the other passes: before a pull request, run the CI steps **and** `check-cold.sh`, with the venv
active (it calls `python3` from your `PATH`). Details:
[`docs/dev-setup.md`](docs/dev-setup.md) §4.

### Probes that touch a rig

Many `tools/check-*` scripts drive a live rig: they make sound, rebuild the rig, write real files, or
can freeze or crash REAPER. Read a tool before running it, never run a dangerous one while someone
is playing, and restore what a test wrote. The classified list is in
[`docs/dev-setup.md`](docs/dev-setup.md) §5. A probe must leave the rig as it found it and must never
start a recording.

## 4. Code conventions

- **UI text is in English.** Code comments are mostly in **French**: that is normal here, and a
  new comment may be in French or English. A French label visible on screen is a bug.
- **The brand is written `golem`** (or `/golem_`) in anything displayed. Identifiers that already
  exist (folder names, firewall rules, the mDNS service) stay as they are: renaming them breaks
  installed racks.
- **SPDX header on every new file**: `# SPDX-License-Identifier: GPL-3.0-or-later` (or `--`, `//`
  depending on the language); `// SPDX-License-Identifier: MIT` on line 2 of a new JSFX that should
  be MIT.
- **No build step.** The app is Preact + htm loaded as ES modules. Nothing compiles, so nothing
  warns: check your change **rendered**, at 1024×600 for the app and at phone size for the
  Companion, with the browser console open ([`docs/dev-setup.md`](docs/dev-setup.md) §6).
- **Comments explain why**, especially in front of a workaround.
- **Never commit local state.** The repository versions recipes and seeds, not what happens on a
  machine: `presets/`, `sets/*.rpp`, `mappings/`, `setlists/`, the user library, recordings, `.env`,
  and the config files the bridge rewrites (the list is `PATHS` in
  [`bridge/local_state.py`](bridge/local_state.py), mirrored in `.gitignore`). The full table is in
  [`docs/dev-setup.md`](docs/dev-setup.md) §7.
- **A bug that bit becomes a check** (`tests/` or `tools/check-*`), not a memory.

Recipes for the most common changes — an API route, an app page, a block type, a golem.fm job, a
JSFX, a REAPER loop — are in [`docs/howto/`](docs/howto/README.md).

## 5. Documentation conventions

- Every doc in `docs/` starts with a status line: `> **Status: CODED | PARTLY CODED | PROPOSED** — scope`.
  A PROPOSED part says what is not built.
- A doc is a **reference**: it describes what the code does, with paths and function names, and the
  rules in force. History belongs in git, not in the doc. When a doc and the code disagree, the code
  is right — fix the doc, or say which one is wrong in your pull request.
- A decision that matters goes into the relevant `docs/*.md`, not only into a commit message.
- A pitfall you hit (a silent failure, a trap in REAPER, a plugin, the OS) goes into
  [`docs/pitfalls/`](docs/pitfalls/README.md): symptom → rule → where the guard is.
- Docs are in English. Link only to published files.

## 6. Proposing a change

1. For anything larger than a fix, **open an issue first**. Read the contract of the area
   ([`docs/README.md`](docs/README.md)): your idea may already be designed, or excluded for a reason.
2. Keep a pull request to one subject. Say what you changed, how you checked it (CI steps,
   `check-cold.sh`, the rendered page, a measurement on a rig), and what you could not check.
3. **Changes that touch hardware are measured**, not assumed: say on which OS, sound card and
   controller you tested, or that you could not.
4. Sign off every commit (`git commit -s`).

Security issues are not reported in public issues: see [`SECURITY.md`](SECURITY.md).
