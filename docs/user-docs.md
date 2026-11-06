# The musicians' documentation — golem pages shown with the real screen

> **Status: CODED** for the factory snapshot (`tools/shell_snapshot.py --factory`), the examples of §3 and the
> anchors of §4; every golem page of the plan is written (§5, 2026-10-22) — golem.fm writes `separation` and the web
> halves; **FIXED** (2026-10-21) for the page plan
> (§5) and golem.fm's choice for its own pages (§6). The examples marked *to make* are not built. golem.fm owns the documentation site (`/docs`, `docsTree.ts`) and the web pages; the
> rack owns the golem pages and the rack half of the pages that concern both.

Related: [`shell.md`](shell.md) (the read-only shell, the snapshot, its redaction) ·
[`factory.md`](factory.md) (the factory content every golem has) · [`ui-architecture.md`](ui-architecture.md)
(hubs and routes).

## 1. The principle

The documentation is also a **tutorial on concrete examples**. A golem page does not carry a screenshot: it
carries a **panel of the real rack interface** (golem.fm's `<GolemScreen>`, the shell of [`shell.md`](shell.md)),
loaded with the **factory content** every golem ships with, and text around it that explains what the reader
sees. The reader can open Golem Rising on their own rack and find the same screen.

- One source: the app at a pinned commit, and a snapshot made at **the same commit** (golem.fm refuses a
  snapshot from another commit). A release re-pins both; the panels follow the product without anyone
  re-taking a picture.
- No picture goes stale, no screen lies: the panel is the code that runs on the rack, in read-only mode
  (`?shell=ro`).
- golem.fm pages (web features) follow golem.fm's own choice — see §6.

## 2. The factory snapshot — CODED

```
.venv/bin/python tools/shell_snapshot.py --factory [--rev COMMIT] --out DIR
```

1. A **disposable bridge** on a `git worktree` of the commit, the one `tools/check-ui.py` uses: factory content
   only, no person, no device, temporary runtime and REAPER folders, free ports — **and its own REAPER** (
   2026-10-22; `--no-engine` to go without): the isolated REAPER of `tools/check-rig-materialize.py`, on ALSA's
   `null` PCM under Linux (a real device that plays nothing; « Dummy Audio » is a Windows key, and without a running
   audio thread Health concluded "sound card lost?"). The rack next to it is never touched: this REAPER is stopped
   by its PID. Once it answers, the musician's gesture « Skip for now » closes the first-install check, which would
   otherwise replace `/live` on a golem that has just booted. Health, the looper's loops and the arrangement then
   show a golem that plays.
2. **Crawl**: headless Chrome opens every page of `check-ui.py`'s list, plus each factory song, each setlist,
   two lines of each setlist, and the phone Companion; every `GET /api/…` the app **actually** makes is recorded
   (writes are intercepted). An observed list beats a grep: it never mistakes a write for a read and it sees the
   addresses the code builds.
3. **Snapshot**: the observed reads plus the default enumeration go through the usual redaction and check
   ([`shell.md`](shell.md) §3). For this snapshot only, `/api/separation` and `/api/separation/batch` are allowed
   (a fresh bridge has no excerpt).
   `browse`, key options and `/api/separation/programs` (what the developer's machine has installed) stay out.
4. **Examples** (§3) are replayed, and `SNAPSHOT.json` is written.

Output:

| Path | Content |
|---|---|
| `api/<encoded path>.json` | one read, redacted ([`shell.md`](shell.md) §3) |
| `assets/api/…` | the images the app loads with `<img src>` (a song's cover and photo): images only |
| `examples/<name>.json` | `{name, title, route, preset, scene, state, reads}` (§3) |
| `SNAPSHOT.json` | `{kind: "factory", commit, catalog_version, made, reads, examples, assets, machine, pages, skipped, failed, refused}` |

**Reads made with POST.** Two routes read with a body because they take the preset as the Designer holds it,
draft included: `POST /api/blocks/status` (what each block needs on this rack: a capture to download…) and
`POST /api/backing/drawer`. golem.fm's shell drops every write and answers `{ok: true}`: without their answer the
Designer lost, silently, the block states and the Backing drawer. The crawl lets them through on the disposable
bridge (`POST_READS`) and keeps their answer in each example's `reads`, under the key `POST /api/…`. Since then a
factory example shows the truth of a new golem: the factory captures are **not downloaded**, the tiles say ⬇ and
the Designer offers "Download all".

**Writes at load.** A page must write nothing when it opens. `SNAPSHOT.json` `load_writes` lists, per page, the
non-GET requests made with no gesture, outside `POST_READS`. Today: `POST /api/services/check` on Settings ▸
Connect ▸ golem.fm and ▸ TONE3000 (a fresh verdict of the two services; it changes nothing on the rack).

`catalog_version` is read **at the commit**. `pages` maps each route to the reads it made: golem.fm knows which
reads a doc panel needs. `machine` lists the reads that describe **the machine that made the snapshot** (sound
card, USB controllers, CPU, disk, REAPER: `/api/cards`, `/api/soundcard`, `/api/controllers`, `/api/state`…):
they are written (a screen needs an answer) and they describe the **reference rack** (§2 bis).

## 2 bis. The reference rack

The Gear pages need real hardware. Fixed on 2026-10-21: **Volt 276** (sound card, two inputs) +
**FCB1010 with the UnO2 chip** (pedalboard, on the card's MIDI port), and **two variants**, because the machine has
not enough USB ports for both: **`drums`** adds the **Alesis Nitro** (electronic drums), **`keys`** adds the
**MPK Mini Mk II** (keys and pads). One snapshot per variant, made **at the same commit**: `factory` (drums) and
`factory-keys` (keys); the keys and Controllers pages read the second. An example marked `rack: "keys"` is only
made on that variant (`golem-rising-keys`, `reference-controllers`). Each `SNAPSHOT.json` carries its **`name`** (`SNAPSHOT_NAMES`:
drums → `factory`, keys → `factory-keys`): golem.fm reads it, never the folder name, and the doc pages cite it
(`snapshot="factory-keys"`; default `factory`).

- The snapshot is made **on** that rack. `REFERENCE_RACK` (`tools/shell_snapshot.py`) declares it; the tool
  **checks** what the disposable bridge sees (`/api/cards`, `/api/controllers`, `/api/soundcard`) and writes
  `SNAPSHOT.json` `rack: {reference, variant, seen, missing, complete}`. golem.fm serves the `machine` reads only when
  `rack.complete` is true.
- The pedalboard has no USB name: it is recognised by the UnO2 chip's **identity probe** — the "Detect" gesture
  of Settings ▸ Gear ▸ Pedalboard, replayed on the **reference rack's own bridge** (`--reference`, default
  `http://localhost:8770`): a disposable bridge does not touch the machine's MIDI (`GOLEM_NO_HW_MIDI`), so its probe
  never answers. A SysEx request, no note: it plays nothing.
- The sound card is shown **as it is the day it is plugged**: detected and offered for adoption. Adopting it
  (`POST /api/cards/adopt`) rewrites `reaper.ini` and restarts the engine, and the restart looks for REAPER by
  process name: on a disposable bridge it would reach the REAPER of the rack running next to it. Never replayed.

**Taking the pair.** Plug the variant's device, then **restart golem on the rack** before the snapshot: REAPER opens
its MIDI devices only at startup, and the rack's masks still name the other device — the disposable bridge's Health
then reads "Keys controller input opened by NOBODY" (a fact of the machine, not of a golem). Swap the device, restart,
take the second snapshot at the same commit.

## 3. Examples — a musician's gesture, replayed

An example is a gesture **replayed** on the disposable bridge, never typed by hand: a line of the factory setlist
is recalled (`POST /api/recall {slot}`), a scene is chosen, the Designer's draft is set to the same preset and
scene (`POST /api/sandbox_apply`) so that the Designer and the WebSocket agree, and the page is visited. The
example keeps:

- `state`: `GET /api/state` (the shape the WebSocket pushes), redacted;
- `reads`: only the reads that **differ** from the base snapshot (the Designer's draft, mostly).

**Two retouches, and only these**: `devices_online` is emptied (the screens paired to the disposable bridge are
the crawl's own Chrome), and `state.boot` is removed with `reaper_connected` set to `true` (kept for `--no-engine`:
without a REAPER, `/live` would show the `/loading` screen — `showBoot`, `app/boot-model.mjs`).

**Routes.** Three forms, the ones golem.fm's shell opens: `#/live` (the rack app), `?boot=firstcheck&at=input[#/…]`
(a demo of the app opened by its query) and `/app/m.html?tab=now` (the phone Companion, measured at 390×844).
`shell=ro` is added to the query. Any other form is refused by golem.fm's test.

`click` (optional) names anchors (§4) tapped after the page loads, in sequence (`a > b`), by `element.click()` —
the way golem.fm does it in the iframe, and it works on a button hidden by `?shell=ro` (the /live toolbar):
the drawer's own reads (`/api/block-presets/<type>`) are then recorded with the example. `gestures` (optional)
are other musician gestures replayed first (`POST` path and body: setting a mode's Live view, switching mode);
`undo` puts the disposable bridge back so the next example starts from the same state. The Rehearsal and
Concert examples are made this way: the view of /live is the mode's (Settings ▸ Mode ▸ Live screen).

The list lives in `EXAMPLES` (`tools/shell_snapshot.py`). Coded:

| Example | What it shows | Route |
|---|---|---|
| `golem-rising-live` | Factory Golem #09 Golem Rising (Ambient Metal), scene B "Glass Verse" | `#/live` |
| `golem-rising-designer` | the same rig in the Designer: split A/B, two amps, Ambient Djent patch | `#/designer` |
| `golem-rising-amp-sheet` | a tap on the Peavey amp: its capture is not downloaded, the block-status sheet opens | `#/designer` |
| `golem-rising-delay-sheet`, `-delay-presets`, `-delay-assign` | the Tempo Delay's drawer (a block that is ready) on Settings, Presets, MIDI assign | `#/designer` |
| `factory-patches`, `library-amps`, `settings-mode` | Songs ▸ Patches, Library ▸ Tones ▸ Amps, Settings ▸ Mode | their route |
| `reference-soundcard`, `reference-pedalboard`, `reference-drums` | Settings ▸ Gear ▸ Soundcard, Pedalboard, Drums (`drums` rack) on the reference rack | their route |
| `metal-for-all-designer` | Metal for all: six lanes (two guitars, bass, voice, drums, keys), scene B "Verse" | `#/designer` |
| `blues-night-live` | Factory Golem #02 Rented Room Blues (Blues Night), scene C "Organ Solo" | `#/live` |
| `factory-setlist` | the Factory Golem setlist, nine songs, #01 Rooftop Prowl loaded | `#/songs/setlists/factory` |
| `factory-setlist-line` | the Golem Rising line opened: preset, tempo, tuning, its players, its arrangement | `#/songs/setlists/factory/r:factory:8` |
| `golem-rising-song` | the Golem Rising song page: arrangement, "When the song starts" | `#/songs/songs/rs:…` |
| `golem-rising-config` | Golem Rising's ⚙ lane: players, Global (Click, Rec, Riff), the Arrangement block | `#/designer/config` |
| `metal-for-all-drums` | Metal for all, the drum lane (USB kit, Kit block) | `#/designer/drums-1` |
| `loop-station-live` | Loop Station on Live: the looper on the foot | `#/live` |
| `golem-rising-rehearsal` | Golem Rising on the Rehearsal page: sections, "from Intro" | `#/live` (Rehearsal mode) |
| `golem-rising-concert` | Golem Rising on the Concert page | `#/live` (Gig mode) |
| `golem-rising-mixer` | the Live mixer (`click: live.tool.mixer`) | `#/live` |
| `golem-rising-assign` | ✎ Assign, the pedalboard editor (`click: live.tool.assign`) | `#/live` |
| `golem-rising-scenes-sheet` | Scenes & sounds (`click: designer.menu > designer.menu.scenes`) | `#/designer` |
| `golem-rising-scene-sheet` | scene B's sheet (`click: designer.scene-name`) | `#/designer` |
| `golem-rising-keys` | the Piano lane of Ambient Metal, played from the MPK Mini (`keys` rack) | `#/designer/keys-1` |
| `reference-controllers` | Settings ▸ Gear ▸ Controllers, MPK Mini connected (`keys` rack) | `#/system/gear/controllers` |
| `settings-mode-gig` | Settings ▸ Mode, the Gig mode's sheet (`click: mode.item:gig`) | `#/system/mode` |
| `factory-setlists` | Songs ▸ Banks & Setlists: the six factory lists | `#/songs/setlists` |
| `factory-setlist-banks` | the Factory Golem grid, ⇅ Banks (`click: setlists.banks`) | `#/songs/setlists/factory` |
| `golem-rising-setlist-picker` | Live: "What the pedalboard plays" (`click: live.setlist`) | `#/live` |
| `golem-rising-songs-picker` | Live: the songs of the setlist on the foot (`click: live.song`) | `#/live` |
| `golem-rising-part-sheet` | the Golem Rising song page, its first Chorus opened (`click: arr.part.4`) | `#/songs/songs/rs:…` |
| `golem-rising-rehearsal-chorus` | the Rehearsal page, ready to start from the Chorus (`click: live.section.4`) | `#/live` (Rehearsal mode) |
| `library-amp-detail` | Library ▸ Tones ▸ Amps, the Peavey 6505 opened (`click: tones.amp:peavey-6505`) | `#/library/tones/amps` |
| `factory-health` | Settings ▸ System ▸ Health on a new golem that plays | `#/system/sys/health` |
| `factory-storage`, `factory-backups` | Settings ▸ Content ▸ Storage; the Backups modal (`click: storage.backup`) | `#/system/content/storage` |
| `factory-standards`, `standard-rooftop-prowl` | Library ▸ Tracks ▸ Standards; Rooftop Prowl's chart (`click: standards.card:rooftop-prowl`) | `#/library/tracks/standards` |
| `library-keys`, `library-grooves`, `library-kits`, `library-samples` | Library ▸ Keys ▸ Instruments, Drums ▸ Grooves, Drums ▸ Kits, Samples ▸ Short | their route |
| `library-backings`, `library-vocals`, `library-recordings` | Library ▸ Tracks ▸ Backings, Vocals, Recordings | their route |
| `connect-tone3000`, `connect-golemfm`, `connect-devices` | Settings ▸ Connect ▸ TONE3000, golem.fm, Devices | their route |
| `engines-separation` | Settings ▸ Engines ▸ Separation | `#/system/engines/separation` |
| `golem-rising-riff` | Golem Rising's ⚙ lane, the Riff drawer (`click: designer.block:compo-global`) | `#/designer/config` |
| `first-check`, `first-check-input`, `first-check-done` | the first-install check (its built-in demo): Listen, Plug and play, the verdict | `?boot=firstcheck[&at=input\|done]` |
| `companion-now`, `companion-song`, `companion-rec` | the phone Companion during Golem Rising | `/app/m.html?tab=…` |
| `reference-drums-bound` | Settings ▸ Gear ▸ Drums, the Nitro bound as drums (`drums` rack; made last: its gesture is not undone) | `#/system/gear/drums` |

## 4. Anchors — `data-doc` (PROPOSED)

golem.fm draws a halo around an element of the panel and clicks it to open a drawer: it finds the element by
`[data-doc="…"]` in the same-origin iframe. The anchor is a **contract**: golem.fm's test fails when a doc page
cites an anchor that the pinned app does not carry.

- Name: `zone.object[.detail]`, stable, English: `designer.chain`, `designer.block:amp-1`, `live.scene.B`,
  `settings.tab.mode`. A repeated element carries its id (`designer.block:<block id>`) or the first one is meant.
- An anchor is added **where a doc page needs it**, not everywhere; the list below grows with the pages.
- Opening a drawer must be **local UI state** (no bridge round trip): a dropped write would leave the screen
  closed. Checked for the pilot pages: a block tile (`setSel`, or the capture picker / block-status sheet), a
  scene tab, a lane tab, ⓘ and the footswitch map are local. The `?open=` vocabulary is therefore empty.
- **Measured, not grepped**: `SNAPSHOT.json` `anchors` lists the anchors present on each crawled page and in
  each example, read from the rendered DOM — for an example, those present on load **and** after each of its
  clicks (an anchor that only exists once a panel is open is listed). Examples are measured **in `?shell=ro`**,
  as golem.fm shows them; `anchors_hidden` lists the anchors present but without size there (the /live toolbar,
  the Designer's `⋯`): they can be clicked, never haloed. A dynamic anchor (`designer.block:<id>`) cannot be found by
  searching the code; golem.fm checks a doc page's anchors against this list.

Anchors carried today:

| Anchor | Element | File |
|---|---|---|
| `topbar.brand`, `topbar.mode`, `nav.<live\|designer\|songs\|library\|settings>` | the top bar: logo, mode badge, the five hubs | `main.js` |
| `live.bank`, `live.prev`, `live.next`, `live.song` | the song bar: whole bar, ◀, ▶, the setlist number and title | `live-bankbar.js` |
| `live.setlist` | the setlist button in the top bar | `live-bankbar.js` |
| `live.stomps`, `live.stomp.<6–10>` | the stomp row, one stomp tile (by switch number) | `page-live.js` |
| `live.scenes`, `live.scene.<A–E>` | the scene row, one scene tile (by scene id) | `page-live.js` |
| `live.exp` | the two expression bars | `page-live.js` |
| `live.tool.view`, `live.view.<pedalboard\|rehearsal\|timeline>`, `live.tool.mixer`, `live.tool.assign` | the /live toolbar: the view button and its menu, Mixer, ✎ Assign (hidden in `?shell=ro`: click them, never halo them) | `live-tools.js` |
| `live.mixer`, `live.assign` | the open Mixer and Assign panels | `live-tools.js` |
| `live.rehearsal`, `live.rehearsal.song`, `live.sections`, `live.section.<n>`, `live.now` | the Rehearsal page: whole page, song line, the section cards, one card (1-based), the NOW zone | `live-pages.js` |
| `live.concert`, `live.concert.setlist`, `live.concert.section` | the Concert page: whole page, the setlist strip, the big current section | `live-pages.js` |
| `live.map`, `live.transport` | the song map and the transport bar (Rehearsal and Concert) | `live-pages.js` |
| `designer.preset`, `designer.scenes`, `designer.scene.<id>`, `designer.info` | the preset picker, scene tabs, one scene, ⓘ | `page-designer.js` |
| `designer.rig`, `designer.lanes`, `designer.lane:<lane id>`, `designer.lane:config` | the rig, the lane tabs, one lane, ⚙ | `page-designer.js`, `designer-lanes.js` |
| `designer.chain`, `designer.block:<block id>`, `designer.in`, `designer.out` | the current lane's chain, one block tile, IN, OUT | `page-designer.js` |
| `designer.patch`, `designer.foot` | the lane's patch chip, the footswitch map | `page-designer.js` |
| `designer.bank`, `designer.scene-name`, `designer.song`, `designer.bpm` | the bank pill, the open scene's name, the song chip, the tempo | `page-designer.js`, `designer-song.js` |
| `designer.saved`, `designer.menu`, `designer.menu.scenes` | the save indicator, `⋯`, its "Scenes & sounds" entry (hidden in `?shell=ro`: click, never halo) | `page-designer.js` |
| `designer.scenes-sheet`, `designer.scene-sheet` | the open Scenes & sounds sheet, the open sheet of one scene | `page-designer.js`, `designer-sheets.js` |
| `designer.sheet.settings`, `designer.sheet.presets`, `designer.sheet.assign` | the tabs of an open block drawer | `designer-sheets.js` |
| `designer.split`, `designer.merge` | the ⇉ / Σ choice of a split, the Σ level | `page-designer.js` |
| `designer.block-status`, `designer.missing` | the sheet of a block that is missing on this rack, the "N blocks missing" banner | `designer-blockstatus.js` |
| `tab.<id>` | a tab of a hub (`tab.tones`, `tab.gear`…) | `lib.js` (`HubPage`) |
| `songs.patch:<patch id>` | a patch card of Songs ▸ Patches | `page-patches.js` |
| `designer.sheet` | an open block drawer | `designer-sheets.js` |
| `mode.list`, `mode.item:<id>`, `mode.compare`, `mode.detail`, `mode.state` | Settings ▸ Mode: the list, one mode, ▦ All modes side by side, the open sheet, ⏻ Active / ⏻ Switch to (the latter hidden in `?shell=ro`) | `page-system.js` |
| `mode.group.<who\|stage\|time>`, `mode.row.<space\|card\|inputs\|tools\|live-screen\|foot-list\|click\|rec\|arrangement>`, `mode.table` | the three parts of a mode's sheet, one row, the comparison table | `page-system.js` |
| `setlists.card:<list id>`, `setlists.kind`, `setlists.lines`, `setlists.line.<n>`, `setlists.banks`, `setlists.detail`, `setlists.grid` | Songs ▸ Banks & Setlists: a list's card, the open list's kind, its lines, one line (1-based), ⇅ Banks, the right side, the bank grid | `page-setlist-groups.js` |
| `setlists.facts`, `setlists.players`, `setlists.edit-song` | an open line: Preset · Tempo · Tuning · Capo, the players of its preset, ✎ Edit the song | `page-setlist-groups.js` |
| `live.setlists` | the open "What the pedalboard plays" picker | `live-bankbar.js` |
| `live.songs` | the open list of the foot list's lines (a tap on `live.song`) | `live-bankbar.js` |
| `songs.song:<song id>`, `songs.sources`, `songs.facets` | Songs ▸ Songs: a song card, Golem · Folders · All, the filters | `page-repertoire.js` |
| `song.head`, `song.kind`, `song.setlists`, `song.sheet`, `song.file`, `song.arrangement`, `song.footer` | the song page: header, Cover/Original, "in N setlists", the sheet row, File, the arrangement, the setlists at the bottom | `page-repertoire.js` |
| `arr.power`, `arr.total`, `arr.play`, `arr.start`, `arr.count-in`, `arr.switch`, `arr.advance`, `arr.live-view` | the arrangement editor: Automation on, the length, ▶ Play (hidden in `?shell=ro`), "When the song starts", count-in, the switch, next part, on /live | `designer-arrangement.js` |
| `arr.track`, `arr.part.<n>`, `arr.part-sheet`, `arr.library`, `arr.read` | the track, one part (1-based), the open part's sheet, the part palette, the read-only arrangement of a setlist line | `designer-arrangement.js`, `arr-read.js` |
| `tones.amps`, `tones.amp:<model id>`, `tones.type`, `tones.amp-detail` | Library ▸ Tones ▸ Amps: the brands, one amp model, Heads/+Cab, the open model | `page-amps.js` |
| `factory.show`, `factory.kind:<kind>`, `factory.restore`, `factory.edited`, `factory.sounds` | Settings ▸ Content ▸ Factory: Show factory content, one kind, Restore, Changed on this golem, Factory sounds | `page-factory.js` |
| `health.verdict`, `health.ask`, `health.now`, `health.fact:<id>`, `health.guard`, `health.checks`, `health.incidents` | Settings ▸ System ▸ Health: the banner, ✦ Ask golem, Now, one fact, "Rack free for a check", Check now, Incidents | `page-health.js` |
| `storage.disk`, `storage.music`, `storage.backup`, `storage.folders` | Settings ▸ Content ▸ Storage: the disk, your music, ⇅ Back up… (hidden in `?shell=ro`), song folders and caches | `page-storage.js` |
| `backups`, `backups.<export\|import\|vault>` | the Backups modal and its tabs | `io-modal.js` |
| `standards.card:<slug>`, `standards.chart` | Library ▸ Tracks ▸ Standards: one standard, its open chart | `page-standards.js` |
| `connect.tone3000`, `connect.golemfm` | Settings ▸ Connect ▸ TONE3000, ▸ golem.fm | `page-api.js` |

Renaming or removing an anchor is a contract change: say it in the commit message.

## 5. The golem pages — plan

`product`: `golem` = the rack only; `both` = the page has a rack half (ours) and a web half (golem.fm's), in
separate sections. Each page names its panels: an example of §3, or one to make (*to make*).

### Getting started

| id | product | Sections (h2) | Panels |
|---|---|---|---|
| `what-is-golem` | both | The rack and the site · What happens where · Plans | `golem-rising-live` |
| `unbox` | golem | In the box · Power, network, sound card · First boot | — (photos of the hardware) |
| `first-check` **new** | golem | The first-install check · Guitar in, sound out · When something is missing | `?boot=firstcheck` (*to make*: the three steps, `/app/?boot=firstcheck&at=…`) |
| `tour` **new** | golem | The five hubs: Live, Designer, Songs, Library, Settings · The top bar · Tap, long press, drawers | `golem-rising-live`, `golem-rising-designer` |
| `connect` | both | golem.fm/connect and the QR code · Approving the golem · Your golem number | Settings ▸ Connect ▸ golem.fm (*to make*) |
| `phone` | both | Joining the rack without typing an IP · Your lane on the phone | Companion `m.html?tab=now` (*to make*, 390×844) |

### The golem

| id | product | Sections (h2) | Panels |
|---|---|---|---|
| `hardware` | golem | Front and back panels · Supported sound cards · Updates (Settings ▸ About) | About ▸ golem (*to make*) |
| `modes` | golem | **Pedalboard, Home, Jam, Rehearsal, Gig** (the factory modes — the title "Home, Rehearsal, Gig, Studio" is out of date) · What each mode changes · Comparing modes · Locking the screen and the 2 s exit | `settings-mode`, `settings-mode-gig`, `settings-mode-compare`, `golem-rising-concert` — **written** |
| `soundcard` | golem | Inputs and roles · Stereo pairs · USB and MIDI · Card setups | reference rack (*to make*) |
| `controllers` **new** | golem | Keyboards and pads · Calibration · Expression pedals | reference rack (*to make*) |
| `pedalboard` | golem | Scenes and stomps · Assigning a switch (✎ Assign) · Tap and long press · Flashing the FCB1010 UnO2 | `golem-rising-live`; ✎ Assign (*to make*) |
| `lanes` | golem | What a lane is · Guitar, bass, voice, keys, drums · One input per musician | `metal-for-all-designer` |
| `live-screen` | golem | **Pedalboard · Rehearsal · Concert** (the three views; "Timeline view" is out of date) · The toolbar: Mixer, Tuner, Click, Lock, Rec · Next and previous song | `golem-rising-live`, `blues-night-live`; Rehearsal and Concert (*to make*) |
| `mixer` **new** | golem | Output trims · Headphones and the PA | Live ▸ Mixer (*to make*) |
| `health` | golem | What Health checks · Fixing from Health · Ask golem · Incidents and reports | `#/system/sys/health` |
| `separation` | golem | Listed engines · Other engines (written by golem.fm) | — |
| `separate-folder` **new** | both | Separate one song · Separate a whole folder · Where the stems go (golem.fm "track") | Engines ▸ Separation (*to make*) |
| `factory` **new** | golem | What every golem ships with · Hiding and restoring · Downloading the captures | `factory-content` — **written** |
| `storage-backups` **new** | golem | Storage · Back-ups, local and vault · Before a reinstall | `#/system/content/storage` |

### Sound

| id | product | Sections (h2) | Panels |
|---|---|---|---|
| `presets` | both | A preset is your rig · Scenes (Ambient Metal's five) · Scenes & sounds · Saving | `golem-rising-designer`; scene C (*to make*) |
| `patches` | both | A patch is one chain · Dropping a patch into a lane · "edited": when a lane is no longer its patch · Trying a patch on the rack | `golem-rising-designer` (patch chip), Songs ▸ Patches |
| `blocks` **new** | golem | The block catalogue · A block's drawer: knobs, assign, presets · Split, merge, A/B branches | `golem-rising-designer` with a block drawer open (*to make*) |
| `captures` | both | Amps, pedals, cabinets · Your Tones library · Missing captures | `golem-rising-amp-sheet`, `library-amps`, `library-amp-detail`, `golem-rising-designer` — **written** (rack half) |
| `tone3000` | both | Why each account connects its own · On golem.fm · On the golem | Settings ▸ Connect ▸ TONE3000 |
| `keys-drums` | both | Instruments of the rack (DX7 bank, Vital, pianos) · Drum kits and grooves (26 factory grooves) · Samples | Library ▸ Keys, Library ▸ Drums ▸ Grooves |
| `drums-lane` **new** | golem | A drum lane: an electronic kit or the Drum Machine · Kits by song section · Calibrating a kit | `metal-for-all-designer`, Drums tab (*to make*) |
| `looper` **new** | golem | The Loop Station preset · Recording, overdub, undo on the foot | Loop Station (*to make*) |

### Band

| id | product | Sections (h2) | Panels |
|---|---|---|---|
| `songs` | both | The song page (Golem Rising) · Instruments, rig, arrangement · Originals and covers | `factory-songs`, `golem-rising-song` — **written** (rack half) |
| `setlists` | both | Building a setlist · Banks on the foot · Tonight-only changes · Playing it on the golem | `factory-setlists`, `factory-setlist`, `factory-setlist-banks`, `golem-rising-setlist-picker`, `factory-setlist-line` — **written** (rack half) |
| `arrangement` **new** | golem | Sections and bars · When the song starts: count-in, click · Rehearsing a section, cue, loop | `golem-rising-song`, `golem-rising-part-sheet`, `golem-rising-rehearsal-chorus` — **written** |
| `click-tempo` **new** | golem | The Click · Tempo per song · Tap | Designer ▸ ⚙ Global (*to make*) |
| `standards` **new** | golem | Playing along a grid: Rooftop Prowl, Rented Room Blues, Crooked Lantern · Grooves and the band | Library ▸ Tracks ▸ Standards |
| `backings` **new** | both | Backing tracks · Vocals (karaoke) · Bars and tempo | Library ▸ Tracks ▸ Backings |
| `recordings` | both | What the golem records · Sessions and takes · DI and processed sound · Splitting a take | Library ▸ Tracks ▸ Recordings |
| `reamp` | both | Asking for a reamp · When the golem does it · Choosing the sound | — |

### Troubleshooting

| id | product | Sections (h2) | Panels |
|---|---|---|---|
| `no-sound` | golem | Inputs and levels · The lane and the preset · Health ▸ silence | an incident example (*to make*: replayed, or stated as made) |
| `golem-missing` | both | Network · Pairing again | — |
| `tone3000-issues` | both | Reconnecting · One connection per machine | — |
| `faq` | both | — | — |

**Status (2026-10-22).** Every page above is written — in `~/golem-doc-work/docs-pages/<section>/<id>.en.md`, the
panels each page cites are its `::golem` directives — except `separation` (golem.fm's). The pages the plan imagined
around a boxed product (`unbox` "In the box", `hardware` "Front and back panels") describe what exists: golem is
installed on a computer, and the reference rack is a build (`docs/rack-hardware.md`).

## 6. golem.fm pages — golem.fm's proposal (to validate)

- No hand-made screenshots: stale at the first release and frozen in one language.
- By default, **generated** screenshots: a Playwright script on a demo account filled with the same factory
  content (Golem Rising, the factory setlists, the Standards), regenerated at each release and per language;
  halos and captions drawn with the same `data-doc` anchor system.
- A **live React component** only for small, self-contained widgets (plans grid, chord box, preset card,
  genre picker). Whole pages under test (Composer, DAW, Publish) cost too much (stores, API, auth).
- An "Open in golem.fm" link to the real screen for a signed-in reader.
- One frame, one halo, one caption style for both products: the reader must not feel two docs.

## 7. Not built

- The anchors of the other pages (§4), added with each page.
- The examples marked *to make* in §5, and a **reference rack** for the Gear pages (a card, a pedalboard, a
  keyboard, declared as such rather than borrowed from the developer's machine).
- An incident example for `no-sound`.

## 8. When the golem's UI changes — the re-pin

> **Status: FIXED** (2026-10-22). golem.fm embeds the **whole app of the golem** at a pinned commit
> (`public/golem-app/<commit>`, copied by golem.fm's `tools/sync_golem_app.py`) — not only for these doc pages: the
> showcase (`pages/public/homeShared.tsx`) and the Library (`PresetBuilder`, `PatchBuilder`, `PatchDetail`,
> `GolemPresetDetail`) render it too. A UI change on the rack reaches golem.fm only through a re-pin.

**On the rack** (whoever changes the UI):

1. Code the change, check it at render (1024×600), keep `tests/ui/inventory-linux.json` in step
   (`tools/check-ui.py --test-content --update-inventory`), commit and push.
2. **Anchors are a contract** (§4): a renamed or removed `data-doc` anchor is said to golem.fm *before* the push. A
   new screen the doc should show gets its anchor and an example (§3).
3. Take the snapshot at that commit (`tools/shell_snapshot.py --factory --rev <commit>`), the golem relaunched first
   (§2 bis). **Only the variants the change touches**: a change outside the Gear keys/drums pages does not need the
   Nitro/MPK swap — the other variant keeps its snapshot (decided by 2026-10-22). golem.fm's rule "both snapshots
   at the same commit" must then accept a variant from an older commit when the rack says the change does not concern
   it (asked of golem.fm the same day).
4. **Measure the impact**: `tools/doc-impact.py <pinned snapshot> <new snapshot>` lists, per example, what changed
   (anchors gone or new, now hidden, reads, the rendering — pixel diff when both `-shots` folders exist), the app
   files changed between the two commits, and **the doc pages that cite a touched example** or halo a vanished anchor.
   Keep each pin's `-shots` folder next to it (`~/golem-doc-work/pin-<commit>/`) so the next comparison has pixels.
5. Fix the rack-written pages it lists (`~/golem-doc-work/docs-pages`), run `check_pages.py` against the new pair.
6. Send golem.fm: the commit, the snapshot paths, the `doc-impact` output, the pages changed — **only what changed**.

**On golem.fm**: re-pin the app at the commit (`sync_golem_app.py`), import the snapshots, copy the pages listed, and
look again at the non-doc pages that embed the app (the showcase, the Library) — they show the new UI from the re-pin
on, with no snapshot of their own.
