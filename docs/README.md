# golem documentation

> **Status: REFERENCE** — the index of every published document in `docs/`, with the status each one
> declares in its header.

Every document describes what the code does today. Statuses: **CODED** (built), **PARTLY CODED** (the
header says which part is not), **PROPOSED** (a design, not built), **REFERENCE** / **GUIDE**
(derived from the code, for reading or for working). When a document and the code disagree, the code
is right and the document needs fixing.

## Start here

| Document | What it is |
|---|---|
| [architecture.md](architecture.md) | How the code fits together: bridge, app, REAPER scripts, JSFX, golem.fm |
| [glossary.md](glossary.md) | The vocabulary — preset, lane, scene, patch, block, take… — checked against the code |
| [dev-setup.md](dev-setup.md) | Working on golem without a rack: run it, the checks, the probes, what never to commit |
| [quality-automation.md](quality-automation.md) | PROPOSED, lot 1 PARTLY CODED — seven lots to catch regressions before a human does: nightly three-OS run, red-main alarm, pre-push hook, rendered app, headless REAPER, Lua unit tests, the rack testing itself |
| [health.md](health.md) | PARTLY CODED — Settings ▸ Health: the "Now" facts, the top-bar dot, environment drift, the first-start check, Fix and incidents are built; last self-test, the other checks on demand and the rest of the backlog are proposed |
| [troubleshooting.md](troubleshooting.md) | Symptom → checks → code, for problems that happen on a rack |
| [assistant.md](assistant.md) | PARTLY CODED — the action registry, Health ▸ Fix, incidents and how they ended (sent in the reports), `golem doctor` and « Ask golem » answered by golem.fm (it proposes, the machine validates, shows and verifies) are built; the musician's help pages are proposed |
| [pitfalls/](pitfalls/README.md) | Hard-won rules per subsystem: [REAPER](pitfalls/reaper.md), [JSFX](pitfalls/jsfx.md), [plugins](pitfalls/plugins.md), [MIDI](pitfalls/midi.md), [Windows](pitfalls/windows.md), [data](pitfalls/data.md), [UI](pitfalls/ui.md), [tooling](pitfalls/tooling.md), [install](pitfalls/install.md), [security](pitfalls/security.md) |
| [howto/](howto/README.md) | Recipes: [API route](howto/add-api-route.md), [app page](howto/add-app-page.md), [block type](howto/add-block-type.md), [golem.fm job](howto/add-golemfm-job.md), [JSFX](howto/add-jsfx.md), [REAPER loop](howto/add-reaper-loop.md) |

Also: [`../README.md`](../README.md) (the project), [`../CONTRIBUTING.md`](../CONTRIBUTING.md) (how
to contribute), [`../CLAUDE.md`](../CLAUDE.md) (the briefing for AI coding agents).

## References

| Document | What it is |
|---|---|
| [preset-format.md](preset-format.md) | The preset document (lanes, scenes, blocks, config) — REFERENCE |
| [golemfm-protocol.md](golemfm-protocol.md) | Everything the rack sends to and expects from golem.fm — REFERENCE |
| [telemetry.md](telemetry.md) | What leaves a rack on its own, and how to check it — CODED |
| [../SECURITY.md](../SECURITY.md) | The bridge's trust model and access control; reporting a vulnerability — CODED |
| [licence.md](licence.md) | Which licence covers which part of the repository — CODED |

## Contracts by domain

### Playing: songs, scenes, the live engine

| Document | Status | Scope |
|---|---|---|
| [live-engine.md](live-engine.md) | CODED | Preset change rebuilds the rig; scene change switches state without rebuild |
| [live-pages.md](live-pages.md) | CODED | The /live views (Pedalboard, Rehearsal, Concert) and their widgets |
| [band-scenes.md](band-scenes.md) | CODED | Lane states, scenes that pick one state per lane |
| [arrangement.md](arrangement.md) | CODED (§14 PROPOSED) | The `arrangement` block: the song conductor and its cues |
| [songs.md](songs.md) | CODED | The song as an object: identity, sheet, storage |
| [patches.md](patches.md) | CODED | A patch: one musician's sound, played like a preset |
| [setlists.md](setlists.md) | CODED | Setlists and sound lists, the list on the foot |
| [looper.md](looper.md) | CODED | The `looper` block and the `golem_super8` JSFX |
| [standards.md](standards.md) | CODED | The Standard block: a chord chart played as a rhythm section |
| [standards-format.md](standards-format.md) | CODED | The `.gsx` chord-chart format |
| [samples-backings.md](samples-backings.md) | CODED | Short samples, song samples and backings |
| [bars-format.md](bars-format.md) | CODED | `bars.json`: the bar and beat map of a backing |
| [karaoke.md](karaoke.md) | CODED | Playing a song's stems and processing the singer's microphone |
| [compo.md](compo.md) | PARTLY CODED | The Riff block: capture a riff and send it to the composer |
| [reamp.md](reamp.md) | CODED | Re-playing a recorded DI through a lane, offline |
| [preset-preview.md](preset-preview.md) | PARTLY CODED | A short demo per scene, rendered from a reference DI |
| [tablature-fingering.md](tablature-fingering.md) | PROPOSED | Shape-based string and fret choice for transcriptions |

### Blocks, plugins and sound

| Document | Status | Scope |
|---|---|---|
| [blocks-doctrine.md](blocks-doctrine.md) | CODED | How a block type is declared in `library/catalog/effects.json` |
| [block-status.md](block-status.md) | PARTLY CODED | The state of each block of a preset (ready, download, unavailable…) |
| [plugins.md](plugins.md) | CODED | Which plugins the blocks use on each OS, and how they are installed |
| [plugin-window.md](plugin-window.md) | CODED | Opening a plugin's own window (Vital) and saving on close |
| [plugin-capture.md](plugin-capture.md) | PARTLY CODED | Capturing a plugin block into NAM captures and IRs |
| [capture-module.md](capture-module.md) | CODED, experimental captures | One autonomous captured block with live controls, internal MIDI switches and phone control |
| [tone-import.md](tone-import.md) | CODED | Library ▸ Tones ▸ + Add ▸ Import files: `.nam` (A1/A2), `.gcap`, IR `.wav`, `.zip` packs, with what is left out and why |
| [plugin-recipes.md](plugin-recipes.md) | CODED (rack side) | Capture recipes for unknown plugins: proposed, measured, validated |
| [spectral.md](spectral.md) | CODED | Spectral Comp, Stretch and Freeze blocks |
| [gear-classifier.md](gear-classifier.md) | CODED | `tools/classify.py`: brand, device and pack classification of captures |
| [separation.md](separation.md) | CODED (local engines only; paid services removed 2026-10-31) | Source separation on the rack, engine-agnostic |
| [separation-batch.md](separation-batch.md) | phase 1 CODED, phase 2 PROPOSED | Separate a folder: one `.golem` per song of the user's folder |

### Hardware: cards, inputs, controllers

| Document | Status | Scope |
|---|---|---|
| [gear-registry.md](gear-registry.md) | CODED | Sound-card registry and adoption, known USB devices |
| [input-map.md](input-map.md) | PARTLY CODED | Physical connectors → named instruments, per card |
| [mixer.md](mixer.md) | PARTLY CODED | Output trims and mutes per source |
| [returns.md](returns.md) | PARTLY CODED | Card maps seen from golem.fm, monitor returns |
| [calibration.md](calibration.md) | PARTLY CODED | Learning controllers, pedals, pedalboard and drums without code |
| [guitars.md](guitars.md) | PROPOSED | Guitar profiles, neck maps and the "map my guitar" screen (System ▸ Gear ▸ Guitars) |
| [pedalboards.md](pedalboards.md) | CODED | Foot controllers: intention, descriptor, transport, LEDs |
| [fcb/uno2/README.md](fcb/uno2/README.md) | CODED | The FCB1010 UnO2 chip: flash and check tools, bank species |
| [pedal-registry.md](pedal-registry.md) | PARTLY CODED | Descriptors for MIDI-controlled pedals, one-tap install |
| [drums-kit.md](drums-kit.md) | PARTLY CODED | Electronic drum kits, rack kits and the drums lane |
| [rack-hardware.md](rack-hardware.md) | PARTLY CODED | The reference x86 rack and real-time OS tuning |
| [rack-classes.md](rack-classes.md) | PARTLY CODED | What a machine declares about what it can play |

### Platform, install and engine

| Document | Status | Scope |
|---|---|---|
| [platforms.md](platforms.md) | PARTLY CODED | Linux, Windows, macOS: what works where |
| [installer.md](installer.md) | CODED | One-line bootstrap, graphical installer, `golem desktop` / `golem server` |
| [uninstall.md](uninstall.md) | FIXED, CODED on Linux (VM test pending) | Install receipt, uninstall engine with dry run, graphical uninstaller, full backup outside the install folder, VM test |
| [audio-engine-choice.md](audio-engine-choice.md) | PARTLY CODED | Engine descriptors and the local engine choice |
| [ardour-engine.md](ardour-engine.md) | PROPOSED | A free engine built from Ardour, next to REAPER |
| [ardour-plan.md](ardour-plan.md) | FIXED | Action plan for the Golem Engine: fork strategy, engine contract, block homogeneity, phases A0–A5 |
| [release-signing.md](release-signing.md) | CODED, inactive until a key is declared | Verifying signed release tags |
| [update.md](update.md) | CODED | The "Update to …" button of Settings ▸ About, installs from an archive, and how to cut a release |
| [network.md](network.md) | CODED (macOS reads only) | How a tablet or phone reaches the rack: station, access point |
| [connect.md](connect.md) | CODED (rack side) | Joining the rack without typing an address |
| [backups.md](backups.md) | CODED | What a backup carries, where it goes, how it is restored |

### The app, modes and people

| Document | Status | Scope |
|---|---|---|
| [ui-architecture.md](ui-architecture.md) | CODED | The five hubs, the top bar, the desktop window |
| [modes.md](modes.md) | PARTLY CODED | Machine modes: services and inputs vetoed, UI shaped |
| [devices-people.md](devices-people.md) | CODED | Paired devices carry a person; the Companion on phones |
| [identity.md](identity.md) | PARTLY CODED | Devices and people: the roster, attribution per input |
| [shell.md](shell.md) | CODED (rack side) | The read-only shell shown by golem.fm |
| [user-docs.md](user-docs.md) | PARTLY CODED | The musicians' documentation: the factory snapshot and the page anchors golem.fm shows in its docs |
| [anim-packs.md](anim-packs.md) | CODED (rack side) | Tile animation packs |

### Content and exchange

| Document | Status | Scope |
|---|---|---|
| [factory.md](factory.md) | PARTLY CODED | Factory content seeded on first launch |
| [genres.md](genres.md) | CODED (rack side) | The two-level genre taxonomy |
| [golem-format.md](golem-format.md) | PARTLY CODED | The `.golem` file: a song or an album in one file |
| [song-folders.md](song-folders.md) | CODED | Reading libraries of `.golem` files in place |
| [song-backing.md](song-backing.md) | CODED | The backing belongs to the song; a preset plays it and mutes the stems it plays |
| [designer-song.md](designer-song.md) | CODED | The song loaded in the Designer: its values next to the preset's, saved in the song |
| [designer-glyphs-pedals.md](designer-glyphs-pedals.md) | CODED | golem-fx's glyphs everywhere, the clay fill of golem FX blocks, the Add-block rows and pedal shelf, the Designer pedal view, pedals on the /live stomps |
| [golem-fx-reaper.md](golem-fx-reaper.md) | CODED | golem-fx blocks under REAPER: the engine table, the plugin ranges, installed-or-original |
| [library-loans.md](library-loans.md) | CODED | Sounds lent to a band by a band mate |
| [card-setups-exchange.md](card-setups-exchange.md) | CODED (rack side) | A card's setup shared across the user's racks |
| [diagnostics.md](diagnostics.md) | CODED | Whitelisted, scrubbed usage and bug reports |
| [rack-mcp.md](rack-mcp.md) | CODED | A read-only MCP server on `POST /mcp` |

## Incident reports

Measured investigations: cause, evidence, and the fix now in code. Read them before touching the
same subsystem.

| Report | Subject |
|---|---|
| [audit-2026-09-21-latence-scenes.md](audit-2026-09-21-latence-scenes.md) | Scene and stomp latency; plugins that stall the engine (PARTLY CODED) |
| [audit-2026-10-01-crash-convolveur.md](audit-2026-10-01-crash-convolveur.md) | REAPER crashes on rapid preset changes: the IR convolver (CODED) |
| [audit-2026-10-01-parite-coeurs-os.md](audit-2026-10-01-parite-coeurs-os.md) | Does the amp + cab core sound the same on Linux and Windows? (CODED) |
| [audit-2026-10-10-entrees.md](audit-2026-10-10-entrees.md) | Input assignment, from the sound card to patches and presets (CODED) |
| [audit-2026-10-14-crash-nam.md](audit-2026-10-14-crash-nam.md) | REAPER crashes on rapid patch changes: the NAM amp (CODED) |
| [audit-2026-10-15.md](audit-2026-10-15.md) | Pre-publication audit: security, REAPER side, technical debt, platform status (CODED) |

## Not published

`docs/archive/` (superseded documents) and `docs/private/` (personal material) exist only in the
working repository and are not part of the published tree.
