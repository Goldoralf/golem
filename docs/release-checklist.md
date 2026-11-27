# Release checklist

> **Status: FIXED** (2026-11-27, validated by the maintainer). Followed for every golem release, item by item, by
> whoever prepares it. Each item comes from something that was missed: v0.7.2 shipped the Golem Engine 9.9-g3 on Linux
> while 9.9-g8 was published; a first name blocked the public scan; a manifest change broke CI because only the tests
> of the subject had run. The mechanics of the tag itself are in [update.md](update.md) §5.

## A. What the release installs

1. **Every pin against the latest release we published**: run `tools/snapshot.py` (one page, every entity: here,
   published, pinned; it exits 1 while a line is red). A pin that is behind is moved, or its reason is written in
   `provision/pins-held.json` (the page then shows it orange, until a newer version is published):
   - golem-fx: `provision/golem_fx.py` `VERSION` (the only copy of the number: `install-golem-fx.sh` and the
     installer's dry run read it), `provision/downloads.sha256`, `provision/windows/pins.json` and
     `provision/macos/pins.json` (`golem_fx`: version, url, sha256, comment), `provision/components.json` (version,
     url), then `tools/sync-golem-fx-manifest.py` and `tools/sync-golem-fx-presets.py` from the tag
     (`library/catalog/golem-fx-plugins.json` records the commit), and `docs/installer.md`;
   - Golem Engine: `provision/golem_engine.py` `VERSION` (Linux), `downloads.sha256`, the two `pins.json`
     (`golem_engine`), per system;
   - the prebuilt Linux plugins (`linux-plugins-vN`: `provision/fetch-prebuilt.sh`, `downloads.sha256`);
   - the factory demos (`bridge/factory_demos.py` `TAG`);
   - REAPER (`provision/install-reaper.sh`, the two `pins.json`), played on the rig first.

   `tests/test_pins_coherent.py` fails when two of these files disagree. It cannot know that a newer release exists:
   that comparison is this item.
2. **Every hash recomputed on the downloaded asset** and compared with the release's `SHA256SUMS`:
   `tools/bump.py <component> <version>` does both and writes every file of the pin (golem-fx, golem-engine, reaper,
   factory-demos, dexed, surge; `--dry-run` to look first). It refuses REAPER until it was played on the rig, and it
   lists what still quotes the old version. NAM LV2 and the prebuilt Linux plugins are not automated (it says why).
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

The index of the pinned factory release (`golem-factory-demos.json` of `factory-demos-vN`) carries the `rack_commit`,
`catalog_version` and `golem_fx_version` it was rendered with. The check: they equal the catalogue version of the
repository and the pinned golem-fx; otherwise the blocks added since have no demo and a new release is rendered on the
rack (`tools/pack-factory-demos.py`, about an hour, nobody playing), published, and its tag sent to golem.fm, which
serves the same release. Found on 2026-11-27: v4 was rendered with golem-fx 0.6 and catalogue 51 while golem pinned
0.8.1 and 52.
