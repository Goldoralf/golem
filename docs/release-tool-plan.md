# The release tool and the snapshot page — plan

> **Status: CODED** (2026-11-27; proposed and validated the same day). Asked by the maintainer after v0.7.2 shipped the Golem Engine 9.9-g3 on Linux
> and REAPER 7.79 while 9.9-g8 and 7.86 were published: "we publish from my local golem, and there are things to do
> or to remind me at each step". Two tools: `tools/release.py`, which walks a release step by step, and
> `tools/snapshot.py`, which writes one HTML page saying where every golem entity stands. The rules they enforce are
> those of [release-checklist.md](release-checklist.md); `tools/release.sh` stays the last step (the signed tag).

## 1. Principles

- **Run on the maintainer's golem, in his terminal** (`! tools/release.py` from a Claude session, or a plain shell).
  The signing key is in his agent; an agent session cannot sign, so the tool never pretends it can.
- **Guided, not silent.** Each step is one of three kinds, shown as such:
  - **check**: the tool measures and says ✅ / ✗ with the evidence (a version, a hash, a CI run);
  - **reminder**: something only a human can do or decide (play the rig, update REAPER, re-pin the site); the tool
    says what and why, and waits for "done", "skip — reason" or "stop";
  - **action**: the tool does it after a yes (commit, push, run the benches, run `release.sh`).
- **Nothing is skipped without a written reason.** A skipped step and its reason go into the release record (§5) and
  into the notes draft when the user should know (a pin left behind on purpose).
- **Resumable.** State in `~/.local/share/golem/release/<version>.json`: a stop, a crash or a long bench never forces
  starting again. `--from <step>` and `--status`.
- **Never touches what plays.** Any step that makes sound, rebuilds a rig or uses the card asks "is anybody playing?"
  first (CLAUDE.md). Benches use their own engine and ports.
- **Reads, never guesses.** Every version comes from its source of truth (a file, a tag, a GitHub release, a vendor
  page), never from a doc.
- **One source for the entities**: the same inventory module feeds the release tool and the snapshot page (§3).

## 2. The steps of `tools/release.py`

### 0. Environment (checks)
1. On `main`, clean tree, `HEAD == origin/main`, nothing unpushed.
2. Release key in the agent (`ssh-add -L`), `gh auth status`, network to GitHub.
3. The local bridge answers; which engine runs; whether a take is recording (refuse to go on during a take).
4. The sibling repositories are present and clean: `~/golem-engine`, `~/code/golem-fx`, `~/golem-binaries`,
   `~/code/maestrium` (golem.fm), `~/code/golem-site`. Each one fetched; "behind origin" is a reminder.

### 1. Version (action)
5. Last tag, commits since; proposes nothing by default — **asks** the number (the maintainer chooses it).
6. Refuses a tag that exists; warns when the number does not follow the last one.

### 2. Snapshot (check)
7. Writes the snapshot page (§3) for this release and opens it. Every red or orange panel becomes an item of steps
   3 to 6 below; nothing is "only visual".

### 3. Third-party components (reminders, with the facts)
8. **REAPER**: pinned (`install-reaper.sh`, both `pins.json`) vs the latest on reaper.fm. Behind → reminder:
   "REAPER X is out. Update the pin? It must be played on the rig first: install it here (Settings ▸ About ▸ REAPER),
   play a patch, change scenes, record a take; then the tool recomputes the three hashes." Skip needs a reason.
9. Plugins golem installs and pins: NAM (golem build), sfizz, Surge XT, Dexed, AVL, PawPaw/Vitalium, x42, zeroconvo
   commit, PaulXStretch commit: pinned vs the latest upstream release. A reminder each, never an automatic bump.
10. Python dependencies: open Dependabot PRs, `requirements.lock` age; a reminder.

### 4. golem's own components (checks, then actions)
11. **Golem Engine**: latest `golem-engine-*` tag in `~/golem-engine` and on golem-binaries vs the pin of each system
    (`golem_engine.py` Linux, `pins.json` Windows/macOS). Behind → the tool offers to move the pin (download, hash
    against `SHA256SUMS`, write). Moved → the engine benches become required (step 19).
12. **golem-fx**: latest tag in `~/code/golem-fx` and on golem-binaries vs `golem_fx.py`, `downloads.sha256`, both
    `pins.json`. A newer tag is shown with its changelog line: a DSP change asks for the bump; an editor-only release
    (0.8.2) is recorded as "behind on purpose".
13. **golem-fx parameter manifest**: `library/catalog/golem-fx-plugins.json` generated from the pinned golem-fx
    commit, and the catalogue version golem-fx was built against (`golem-blocks.json`).
14. **Prebuilt Linux plugins** (`linux-plugins-vN`) and **factory demos** (`factory_demos.TAG`): latest on
    golem-binaries vs pinned.
15. **Every moved pin**: hash recomputed on the downloaded asset; **caught up after an update?** (golem-fx and the
    engine are; anything else is a reminder for the notes: "run the install line").

### 5. golem.fm (reminders, with the facts)
16. **Factory content**: the factory release golem.fm serves (`maestrium/backend/app/data/golem-factory-renders.json`
    `release`) equals the rack's `factory_demos.TAG`; the factory patches changed since that release (stale renders).
17. **The empty shell and the docs** (§3 bis): extract the shell of this release, or record "UI unchanged, the shell
    stays at vX"; then golem.fm and golem-site must both run that shell, and their docs must be based on it
    (`doc-impact.py` lists the pages to fix). The site's `/fx` page golem-fx version; the roadmap page (`data.ts`)
    entries this release closes.
18. **golem.fm's own release** (`maestrium`, its `backend/tools/release.py`): its version, and whether it needs
    anything from this golem release (a job, a heartbeat field). A reminder to tell the golem-fm session the tag.

### 6. Checks of this repository (actions)
19. The whole suite: `pytest tests`, `node --test`, `ruff`, `check-syntax`; `check-ui.py --test-content` and the UI
    inventory (new controls listed; machine-specific ones never written, e.g. Wi-Fi networks); the factory seed check.
    If the engine moved: `check-engine-ardour.py --engine-dir <pinned package>` × 5 (asks first).
20. Docs: every doc that quotes an old pinned version; every `PROPOSED` doc this release codes.
21. Public scan at 0.

### 7. The rig (reminders — the maintainer's golem)
22. Reload; play a patch, change scenes, a stomp, record and play back a take; `golem doctor` clean.
23. Settings ▸ About shows the versions the snapshot expects (golem, golem-fx, Golem Engine, REAPER).

### 8. Publish (actions)
24. Commit what the steps changed (one commit per subject, messages in English), push, **wait for CI green on that
    commit** (polls; a failure shows the failing step's log).
25. **Notes draft** in English from `git log vPREVIOUS..HEAD`, grouped (phone, sound, effects, installers, fixes),
    with the versions table (golem-fx, Golem Engine, REAPER) and the update path from each older version, plus every
    "behind on purpose" the user should know. Opened in `$EDITOR`; the maintainer edits and saves.
26. `tools/release.sh vX.Y.Z notes.md` — in the maintainer's terminal.

### 9. After (checks, then reminders)
27. `git verify-tag`, `releases/latest`, `SHA256SUMS.sig`, the update button of the local rack sees the tag.
28. Reminders: update the other golems (the Windows PC, golem_2/3), tell the golem-fm session, Discussions post if
    the release matters to users, the snapshot page saved with the release record.

## 3. `tools/snapshot.py` — where everything stands

One command, one self-contained HTML page (no network once written), `assets/.cache/snapshot/<date>.html` and
`latest.html`; also embedded by `release.py` step 7. Read-only: it fetches and reads, never changes a pin.

**One panel per entity**, each with the same rows: *here* (the local checkout or install), *published* (the latest
tag or release), *pinned by golem* (what the current golem installs), *target* (what the next golem release should
pin), and a status: ✅ aligned · 🟠 behind on purpose (with the reason) · 🔴 behind · ⚪ not applicable.

| Panel | Here | Published | Pinned by golem |
|---|---|---|---|
| **golem** (rack) | local tag / commit, dirty files, CI of HEAD | latest release | — |
| **Golem Engine** | dev tree tag + build date, or installed package | latest `golem-engine-*` per system | Linux / Windows / macOS pins |
| **golem-fx** | `~/code/golem-fx` tag | golem-binaries release | `golem_fx.py`, both `pins.json` |
| **golem-binaries** | repo commit | each release family (linux-plugins, factory-demos, nam, sfizz…) | each pin |
| **Factory content** | catalogue version, factory patches, renders stale | `factory-demos-vN` | `factory_demos.TAG`; golem.fm's release |
| **golem.fm** (service) | maestrium tag + commits ahead | its last release | the empty shell it embeds; its docs' shell version |
| **golem-site** (golem.fm's public site) | commit, = origin, last deploy | the deployed commit | the empty shell it embeds; its docs' shell version; `/fx` golem-fx version |
| **Empty shell** (the demo) | the last extraction (golem version, commit, date, catalogue) | the shell release (§3 bis) | which shell each consumer runs |
| **REAPER** | installed on this rack | reaper.fm latest | three pins |
| **Third-party plugins** | installed | upstream latest | each pin |

A header line says "next release: vX.Y.Z — N red, M orange", and each red line names the step of §2 that fixes it.

**Refreshed from the page** (2026-11-28): `tools/snapshot.py --serve` serves the page on `127.0.0.1:8779` (`--port`,
`--no-open`) with a **↻ Refresh** button (and an *offline* box) that runs the inventory again (~7 s) and reloads. It is
not a route of the bridge: the page only means something on the maintainer's machine (sibling repositories, `gh`
signed in) and works with golem stopped. One gesture, read-only; guards: it listens on 127.0.0.1 only, demands a local
`Host` (DNS rebinding) and a custom header on the POST (another site cannot send it). Opened as `file://`, the page shows
the command instead of the button.

**The empty shell kept on purpose**: `provision/pins-held.json` key `shell`, `{pinned: <commit of the shell golem.fm
serves>, latest: <the release>}`. The panel is orange with the reason for that release only; the next one turns it red.

## 3 bis. The empty shell — what the audit found, and the plan

**The chain** (audit of 2026-11-27, all five repositories read): golem (git objects at a commit) + a snapshot folder →
**maestrium** (`backend/tools/sync_golem_app.py`) → **golem-site** (`tools/import_shell.py`, everything under its
`golem-app/` is copied out of maestrium) → the public repository → GitHub Pages. golem-site's `tools/update_site.py`
drives the whole chain. **golem-site is temporary** (the maintainer, 2026-11-27): it disappears when maestrium serves
golem.fm, so nothing is built for it; the target is maestrium.

**Why each re-pin costs hours**, though the extraction itself runs in about 7 minutes:

- **Hardware.** The reference rack (Volt, FCB1010 UnO2, Nitro or MPK, not both) with a device swap and a golem
  relaunch per variant. The recent pins took one variant and **grafted** the other by hand, with scripts that live
  outside the repository (`~/golem-doc-work`: `merge_gear.py`, `graft_take.py`), untested, one of them no longer the
  version that ran.
- **The tool drifts unseen.** Since the last shell (4cdf4951, 2026-11-22): `check-ui.Bridge` now points
  `GOLEM_ENGINE_DIR` at a folder that does not exist, so the default bench engine very probably no longer starts (read
  in the code, not run); the Companion examples use `?tab=now` / `?tab=song` / `?tab=rec`, legacy addresses since
  2026-11-26; 21 commits touched `app/`. Each re-pin starts by repairing the tool.
- **All or nothing.** One failing example of about sixty aborts the run.
- **Sorting by eye.** `doc-impact.py`'s pixel diff sees the clock, the animation phase and the disk figures; the real
  changes are found by looking at the PNGs.
- **By hand between sessions.** The pages listed are copied into maestrium by hand; the rack copy
  (`~/golem-doc-work/docs-pages`, 2026-10-22) has drifted, and maestrium's `content/docs` is the de facto source. No
  page records the shell it was written against.

**The plan** (order agreed 2026-11-27: 1 and 4 first, then 2, then 3):

1. **Stop the drift.** The graft and check scripts enter the repository with tests, and CI extracts a mini-shell
   (two pages, two examples) at each push: the tool breaks at the commit that breaks it.
   **Done 2026-11-27** for the tool itself: the bench engine starts again (`check-ui.Bridge` takes the caller's
   environment last), the Companion examples use the current routes (a test ties them to `PHONE_PAGES`), and CI runs
   `shell_snapshot.py --factory --smoke` (19 s). A full extraction at e8cfe1fb made 58 examples of 58, none failed.
   The graft scripts are not moved: step 2 replaces them.
2. **Canned hardware.** The reads of each device (Volt, FCB, Nitro, MPK) are recorded once into a versioned reference
   set the bench replays: no swap, no hand graft. Re-recorded only when the Gear pages change. **Done 2026-11-27**
   (`tools/shell_overlay.py`): the rack is declared in `tools/shell/reference-rack.json` and the demo take lives in the
   kit (`~/golem-doc-work/reference/demo-take`, audio, outside the repository); both are replayed while the pages
   render (GET reads and the WebSocket state), then written into the snapshot. The hand grafts (`merge_gear.py`,
   `graft_take.py`) are no longer needed. The rack file was assembled from the entries of earlier snapshots: to
   re-record with the hardware plugged at the next occasion.
3. **By section of the menu.** **Done 2026-11-27, and not as first planned.** The first idea was to work out the
   touched sections from the files changed between two versions and to re-extract only those. It does not hold:
   nearly every UI change touches `app/style.css`, shared by every page, so the answer would be "everything" nine
   times in ten; and the shell is one whole (the app at one commit, with its reads). So:
   - **the extraction stays complete**, at one commit (ten minutes, unattended);
   - **the review is by section**: every page and every example belongs to a section (`section_of`: live, designer,
     songs, library/<tab>, settings/<tab>, companion, first-check; `SNAPSHOT.json` `sections`), and
     `tools/doc-impact.py` says, per section, *to review* / *noise only* / *unchanged*. Measured between the shell
     online (4cdf4951) and d0b0cb24: 9 sections to review, 2 noise only, 5 unchanged;
   - **`--section a,b`** re-extracts chosen sections alone (1 min 35 for the Companion) and **`--merge-into DIR`** puts
     their examples into a full snapshot **of the same commit** (a fixed example leaves `examples_failed`); two
     different commits are refused.
4. **Independent examples.** A failing example stops nothing; only the failed ones are rerun. **Done 2026-11-27**: a
   failed example is recorded in `SNAPSHOT.json` (`examples_failed`, with its reason), its undo always runs, and
   `--examples a,b` reruns a chosen few (the result then says `partial`).
5. **Noise sorted by the tool.** **Done 2026-11-27, by measuring instead of freezing.** Two extractions of the same
   app code were compared: **no pixel differed** (the bench already renders still), so there is no clock or animation
   to freeze. The noise was in the reads: the bench's boot time, the time of the read, a heartbeat counter, "3 s ago",
   Unix dates in the state, the free disk. `doc-impact.py` compares reads without them (`stable`, `VOLATILE_KEYS`) and
   does not ask for a review when only volatile reads differ (`NOISE`: disk, CPU, backups). After that, the same two
   extractions differ by one example, and it is a true difference.
6. **One command on the rack.** **Done 2026-11-27**: `tools/shell_release.py v0.7.3` checks what it needs (the
   reference kit, a bench engine), extracts the full shell at the tag's commit, controls it (no failed example, no
   refused read, the kit at the right shape; each problem says the exact command to redo it), measures the doc impact
   against the shell golem.fm serves, per section, and writes `HANDOVER.md` (what golem.fm re-pins, the sections and
   doc pages to review, the anchors gone, the commands). Everything lands in `~/golem-doc-work/pin-<commit>/`; no
   other repository is touched. Run on v0.7.3: 7 minutes, 62 examples, ready to hand over; 10 sections to review,
   6 unchanged, 22 doc pages to look at. The shell carries its version (`SNAPSHOT.json` `shell.version`).
7. **The docs.** **ACCEPTED by the maintainer 2026-11-27** (with golem.fm's amendment below); golem.fm applies its side. What happened at the
   v0.7.3 re-pin shows the flow that works: the rack hands over facts, golem.fm writes.
   - **One source**: maestrium's `frontend/src/content/docs`. The rack copy (`~/golem-doc-work/docs-pages`, drifted
     since 2026-10-22) and `check_pages.py` are retired; golem.fm's own test already measures every anchor.
   - **The rack's part is the handover**: per section, each changed example with what changed (route, screen
     redrawn, data only), the anchors gone, the API addresses the app now names, the commits that touched `app/`, and
     `--notes`: what changed on screen, in words. golem.fm asked for those last three after the v0.7.3 re-pin; they
     are in `HANDOVER.md` now.
   - **Each page records what it was reread against, per example** (golem.fm's amendment, accepted by the
     maintainer 2026-11-27): `SNAPSHOT.json` `screens` gives every example a **screen signature** (`screen_signature`:
     its route, its click, the anchors measured, those hidden in `?shell=ro`, the visible controls with their digits
     neutralised — what makes the screen, not its data; the same on two extractions of the same code). golem.fm keeps
     `content/docs/reviewed.json` = {page: {shell, examples: {name: signature}}}, stamped when a page is reread; a page
     is behind when an example it cites has another signature in the pinned shell, or no stamp. No chain of impact
     files, and noise never flags a page.
   - This replaces [user-docs.md](user-docs.md) §8's "the rack writes the golem pages and golem.fm copies them".

**A shell has a version: the golem release it comes from** (`shell v0.7.3` = the app at tag v0.7.3, its factory
snapshot, its examples), in its manifest with the commit, the catalogue version and the date. The maintainer lifted
the shell freeze on 2026-11-27: the next shell is v0.7.3 or later, after step 1.

## 4. Build order

0. Coherence of this repository (done 2026-11-27): one copy of each pinned version, `tests/test_pins_coherent.py`,
   the checklist's full file list.
1. `tools/golem_inventory.py`: the readers, one per entity, pure where possible, tested with fixtures (no network in
   tests). **Done 2026-11-27.**
2. `tools/snapshot.py` on top of it — useful on its own from day one. **Done 2026-11-27**; a delay kept on purpose is
   written in `provision/pins-held.json`.
3. `tools/bump.py <component> <version>`: writes every pin file of a component and recomputes the hashes. **Done 2026-11-27**
   (golem-fx, golem-engine, reaper, factory-demos, dexed, surge).
4. The empty shell (§3 bis).
5. `tools/release.py`: state file, the step runner (check / reminder / action), then the steps in order. **Done 2026-11-27**:
   24 steps in nine phases; in a terminal it asks, without one (`!` from a Claude session) it stops at the first step
   that needs an answer and prints the command that gives it (`--done`, `--yes`, `--skip ID "reason"`). A dry run on
   v0.7.4 found, the first time: REAPER 7.79 while 7.86 is out, Dexed and NAM LV2 behind, the factory demos rendered
   with golem-fx 0.6, this rack's engine built before its sources. `tools/snapshot.py` also shows golem.fm's doc pages
   behind (from its `content/docs/reviewed.json`).
6. `release.sh` refuses unless the release record says every step is done or skipped with a reason. **Done 2026-11-27**
   (`tools/release.py --check-record`; `GOLEM_RELEASE_NO_RECORD=1` overrides it).

## 5. The release record

`~/.local/share/golem/release/<version>.json`: each step, its result, the evidence, the skips and their reasons, the
snapshot. Copied into the notes' working folder; never committed (it holds local paths).

## 6. Open questions

- REAPER: is a rig test by the maintainer enough to move the pin, or do the materialize probe and the block-stall bench
  run too?
