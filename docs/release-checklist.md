# Release checklist

> **Status: FIXED** (2026-11-27, validated by the maintainer). Followed for every golem release, item by item, by
> whoever prepares it. Each item comes from something that was missed: v0.7.2 shipped the Golem Engine 9.9-g3 on Linux
> while 9.9-g8 was published; a first name blocked the public scan; a manifest change broke CI because only the tests
> of the subject had run. The mechanics of the tag itself are in [update.md](update.md) §5.

## A. What the release installs

1. **Every pin against the latest release we published** (`gh release list -R Goldoralf/golem-binaries`). A pin that
   is behind is moved, or the reason is written in the doc that owns it:
   - golem-fx: `provision/golem_fx.py` `VERSION`, `provision/downloads.sha256`, `provision/windows/pins.json` and
     `provision/macos/pins.json` (`golem_fx`);
   - Golem Engine: `provision/golem_engine.py` `VERSION` (Linux), `downloads.sha256`, the two `pins.json`
     (`golem_engine`), per system;
   - the prebuilt Linux plugins (`linux-plugins-vN` in `downloads.sha256`);
   - REAPER (`provision/install-reaper.sh`, the two `pins.json`).
2. **Every hash recomputed on the downloaded asset** and compared with the release's `SHA256SUMS`.
3. **What an update brings, not only a fresh install.** For every pin that moved: is it caught up at the restart that
   follows an update ([update.md](update.md) §3 bis)? If not, fix it, or the notes say what to run.
4. **Factory content**: the factory bundle in the repository is the one golem.fm expects (see
   [factory content](#factory-content) below).
5. **The docs that quote a version or a status** ("pinned to…", "stays until…") say the new one.

## B. Checks, always after the last change

6. **The whole suite**: `pytest tests`, `node --test app/*.test.mjs`, `ruff check .`, `python tools/check-syntax.py`.
   Never only the tests of the subject.
7. **`tools/check-ui.py --test-content`** (as CI), rack 1024×600 and phone 390×844: every failure explained or fixed.
8. **Public scan at 0** (`tools/public_export.py --summary`, see the memory of the public switch): before every push,
   not only at the release.
9. **If the engine moved**: the benches of [linux-pass-2026-11.md](linux-pass-2026-11.md) §2 on the pinned package
   (`tools/check-engine-ardour.py --engine-dir <package>`, 5 runs), nobody playing.
10. **About shows the true versions** (Settings ▸ About: golem, golem-fx, Golem Engine).

## C. Publish

11. Commit, push, and wait for **CI green on that exact commit**.
12. **Notes in English**, written from `git log vPREVIOUS..HEAD`: every visible change, the versions of golem-fx and
    the Golem Engine, the update path from each older version, the known limits. The maintainer reads them.
13. The maintainer runs `tools/release.sh vX.Y.Z notes.md` (the key must be in the agent; an agent session cannot sign).

## D. After

14. `git verify-tag`, `releases/latest` = the new tag, `SHA256SUMS.sig` verified against `provision/release-signers`,
    and Settings ▸ About on the rack says up to date.
15. The release is noted (memory of the session, and the doc of anything left for later).

## Factory content

To be specified with the maintainer: how to check that the factory bundle shipped by the repository is the one
golem.fm publishes.
