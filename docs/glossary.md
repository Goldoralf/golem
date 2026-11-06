# Glossary

> **Status: REFERENCE.** Every entry was checked against the code, not against older docs. When a doc
> and this page disagree, read the "Source of truth" files: they win. Code comments are French; the
> UI is English. Paths are relative to the repository root.

How to read an entry: **Term** (aliases, legacy names in code) — definition — *Source of truth.*

---

## Words with several meanings

These words cause most of the confusion. Find which meaning you are looking at before reading further.

### "lane" (five meanings)

| Meaning | What it is | How to recognise it in code |
|---|---|---|
| **Instrument lane** | One input's signal path in a preset: `{id, role, input, chain, states…}`. This is the main meaning. | `preset["lanes"]` (a list) with `preset["lanes_v"] == 2`; ids look like `guitar-1`, `voice-1`. `preset_view.lanes_of()` |
| **Lane entry of a scene** | What a scene says about one instrument lane: `{state, level, mute}`. | `scene["lanes"][<laneId>]` where the key is a lane id of the preset. |
| **Legacy branch mute** | Old storage of split-branch mutes, before they moved to `scene["branches"]`. Migrated on load. | A `scene["lanes"]` value that has `mute` and nothing else and whose key is not a lane id. `preset_view.migrate_scene_branches()`, `is_legacy_branch_mute()`. Branch ids themselves are often named `lane-a`, `lane-b`. |
| **Config ("service") lane** | Where service blocks live, outside any signal chain: `gen` (Players), `rec` (Recorder & Click), `arr` (Arrangement). | `preset["config"]["gen" / "rec" / "arr"]`; `preset_view.SERVICE_GEN / SERVICE_REC / SERVICE_ARR`. |
| **Job queue lane** | One of two worker queues for golem.fm jobs: `sync` (network only) and `rig` (anything that touches REAPER, one at a time). | `tones_jobs._LANES`, `tones_jobs.lane_of(action)`. Not related to audio. |

### "sandbox" (three meanings)

| Meaning | How to recognise it |
|---|---|
| **Edit buffer** of the Designer: the unsaved preset being auditioned, saved to disk so it survives a reload or reboot. | `presets/.sandbox.json`, `recall.SANDBOX_BUF`, `GET /api/sandbox`, `POST /api/sandbox_apply`, `bridge/sandbox_edit.py`. |
| **REAPER tracks** built by the rig engine, one root track per input. | Track names `Sandbox #Input <n>` (sub-tracks `…/merge`, branches); `golem_rig.lua` `SANDBOX_PREFIX`, `sandbox_name(input)`. |
| **Reserved preset id** for a trial (an unnamed draft played as the current preset). | `store.SANDBOX_TRY_ID = "sandbox-try"`; see **Trial**. Never a file in `presets/`. |

`emit_sandbox*` functions in `bridge/recall.py` mean "materialise a preset on the sandbox tracks";
they are used for every recall, not only for Designer drafts.

### "mode" (at least six meanings)

| Meaning | Values | Where |
|---|---|---|
| **Machine mode** (the main one) | ids `studio`, `pedalboard`, `rehearsal`, `accompaniment`, `gig`; see **Mode** | `config/modes/*.json`, `bridge/modes.py` |
| Fields of a machine mode | `perfrec_mode` (`manual`…), `click_mode` (`preset`…) | same files |
| **Block `foot_mode`** | how a block uses its footswitch: `transport` (looper), `sample`, `drums` | `library/catalog/effects.json` |
| **Arrangement advance mode** | `bars` (sections advance on the clock) or `foot` (each tap = next part; "Foot mode" on screen) | block param `advance`, `arrangement.py` `self._mode` |
| **Looper mode** | an integer packed for the JSFX: `beats*10 + snap + 2*count_in` | `looper.py` `_pending_cfg["mode"]` |
| **Drum "Song mode"** | the drum machine plays a sequence of grooves; `seq_mode` = `loop` or `once` ("1-shot") | `app/designer-sheets.js` `DrumSongEditor` |

Also: `split.mode` (`merge`…) in a lane chain, and **arrangement** "Song" pages are not modes at all.

### "loop", "take", "recording"

- **Recording = take = "prise"**: one performance captured by the Rec block. Shown as **Recordings**
  (Library ▸ Tracks, tab id `recordings`, alias `loops`). API: `GET /api/loops`, `GET /api/loop/<file>`,
  `POST /api/take/*`. Source: `app/page-loops.js`, `bridge/takes.py`, `bridge/routes_content.py`.
- **Looper loop**: an audio loop in the Looper block (REAPER JSFX `golem_super8`). `bridge/looper.py`.
- **Arrangement loop**: a rehearsal gesture that repeats a section. `arrangement.py` `self._sloop`.

So `/api/loops` returns takes, not looper loops.

### "patch"

- **Patch** = a musician's reusable sound (see **Patch**). `bridge/patches.py`, ids `patch:<id>` when played.
- **"Patch d'entrées"** in old comments = the **Input map** (card wiring). Unrelated.
- "patch" in `provision/patches/` = source patches applied to third-party plugins.

### "bank"

- **Bank** = a position on the pedalboard: bank #n = line n of the foot list (see **Bank**).
- "DX7 bank", "Grooves bank", pad banks = instrument content. Unrelated.
- `fcb-banks` = the historical id of one setlist file, and an old API name (see **Foot list**).

### "cue"

- **Arrangement cue**: block states (`blocks: {<id>: bool}`) applied at a section boundary. `bridge/arrangement.py`.
- **Rehearsal cue**: a section queued to start at the next boundary (`self._cue`, `"cue"` in the arrangement state).
- A standalone `cues.json` format once existed on paper; nothing in the rack reads it.

### "shell"

- **App shell**: the topbar + router of the app (`app/main.js`).
- **`?shell=<kind>`**: set by the `golem desktop` / `golem phone` launcher windows (`provision/golem`);
  enables window-geometry memory (`app/shell-geom.js`).
- **`?shell=ro`**: the read-only shell used by golem.fm; sets `data-shell="ro"` (`app/index.html`) and
  `SHELL_RO` (`app/lib.js`) so screens do not render editing controls. See docs/shell.md.

### "SETTLE"

- In `reaper/Scripts/golem_watch.lua`: `SETTLE = 0.5` s during which rig operations are frozen after a rebuild.
- In `bridge/hotplug.py`: how long a USB device must stay visible before it counts. Unrelated.

---

## Glossary

**Admin / conductor / guest** (device tiers) — Paired devices carry flags. `admin` allows system mutations
(`ADMIN_PATHS`); the rack's own screen (localhost) is always allowed. `conductor` lets a phone start the band
(songs, backing); owners and admins of the band space get it automatically on a new phone. A guest is a
device whose `person` starts with `guest:` and expires (`guest_ttl`); a guest cannot DELETE unless also admin.
*Source of truth:* `bridge/auth.py` (`ADMIN_PATHS`, `_grant_conductor`, `create_invite`, the permission check near l.700).

**Arrangement** (bloc `arrangement`, "the conductor") — A service block in the `arr` config lane that plays a
song's structure: `params.sections[]` (name, bars, scene, time signature), advance mode `bars` or `foot`,
cues, count-in. It produces no audio; it triggers scene changes and stomps at section boundaries.
*Source of truth:* `bridge/arrangement.py` (`plan()`, `load()`, the engine class), `preset_view.SERVICE_ARR`.

**Backing track / stems** — Separated audio stems of a song, downloaded from golem.fm into
`assets/backing/<slug>/` and played by REAPER items; driven by the `backing-track` block. Transport goes
over OSC actions, load/seek/mix through the command file.
*Source of truth:* `bridge/backing.py`, `bridge/golemfm.py`, `reaper/Scripts/golem_backing.lua`, `app/page-backing.js`.

**Bank** — A pedalboard position. Bank #n is line n of the foot list; Program Change n recalls slot n
(idempotent). A list holds at most 19 slots (`setlists.MAX_SLOTS`), the direct-access banks of the board.
*Source of truth:* `bridge/setlists.py` (`MAX_SLOTS`, `line_at`), `bridge/recall.py` (`do_recall_slot`), `bridge/foot.py`.

**Block** — One unit in a chain: `{id, type, …params, foot?, bypass?}`. Types (73) are defined in
`library/catalog/effects.json` → `effects[]` (`type`, `name`, `category`, `plugin`, `params`, `foot_mode`).
Signal blocks live in a lane's `chain` (`pre`, `split.branches[].blocks`, `post`); service blocks live in
`preset.config`. `block.foot` = the stomp switch it answers to.
*Source of truth:* `library/catalog/effects.json`, `bridge/preset_view.py` (`rich_chain`), `bridge/rig.py`.

**Branch / split** — A lane chain can fork: `{pre, split: {mode, branches: [{id, blocks}], gain}, post}`.
A scene mutes branches in `scene.branches[<id>].mute`. Default merge gain is −3 dB.
*Source of truth:* `bridge/preset_view.py` (`rich_chain`, `migrate_scene_branches`), `bridge/rig.py` (`MERGE_GAIN_DEFAULT`).

**Capture** — A file that makes the sound of a block: a NAM model (`.nam`) or an impulse response
(`.wav`/`.flac`). Capture blocks: `amp`, `amp-nam`, `cab`, `pedal-nam`, `preamp-nam`, `comp-nam`. The compile
checks the file's *nature* (extension), not only its existence.
*Source of truth:* `bridge/rig.py` (`CAPTURE_TYPES`, `CAPTURE_EXT`, `_wrong_kind`), `bridge/resolver.py`.

**Command file** (`.command.json`) — The single slot through which the bridge sends orders to REAPER
(`{action, …, seq}`): `rig_recall`, `scene_apply`, `backing`, `drums`, `tuner`, dev probes… `golem_watch.lua`
polls it and dispatches. Writes wait for the previous command's ack.
*Source of truth:* `bridge/commands.py`, `reaper/Scripts/golem_watch.lua`.

**Companion** — The phone app, `app/m.html` ("Golem Companion"). A paired device of kind `Phone` opening
`/app/` is redirected there.
*Source of truth:* `app/m.html`, `app/mobile.js` (`mountCompanion`), `app/lib.js` (redirect).

**Compo / Riff** (bloc `compo`, shown as **Riff**) — Service block that captures a riff on the Rec path and
sends it to golem.fm's composer; the take is tagged `kind: "riff"`.
*Source of truth:* `bridge/compo.py`, `config/compo.json`, `effects.json` (`type: compo`, `name: Riff`).

**Core** (cœur) — The file-loading blocks baked into REAPER FX-chain templates instead of being added by
name: `amp` (Head+Cab: NAM + x42 convolver), `amp-nam` (head only), `cab` (x42 IR only).
*Source of truth:* `bridge/compile_rig.py` (`CORE_TYPES`, `TEMPLATE_NAM/HEAD/CAB`), `bridge/templates/*.RfxChain`.

**Descriptor** — A data file that tells the rack how to talk to a device, never hard-coded. Families:
pedals (`library/pedals/*.json`, installed copies in `mappings/`), pedalboards
(`config/pedalboard/devices/*.json`; `contract.json` is the device-free *intention*), drum modules
(`config/drumkits/*.json`), MIDI controller models (`config/controller-models/*.json`, `kind: controller-model`).
*Source of truth:* `tools/check-descriptors.py` (`FAMILIES`; controller models are not in it),
`bridge/pedalboard.py`, `bridge/drumkits.py`.

**Factory content** (usine) — Presets, patches, setlists and chord grids shipped in `library/factory/<kind>/`
(versioned) and seeded at start into the local folders. Never overwrites, never resurrects what the user
deleted (`presets/.factory.json` remembers). Factory ids start with `factory`.
Machine modes have the same split: `config/modes/` (factory) vs `config/modes.local/` (user overrides).
*Source of truth:* `bridge/factory.py`, `bridge/modes.py` (`MODES_DIR`, `LOCAL_DIR`).

**Foot list** (liste au pied; legacy: banks, fcb-banks, setlist-source, `fcb_setlist`) — The one setlist the
pedalboard plays. Its id is `config/setlist.json` → `active`; a machine mode can set it on entry
(`foot_list`). If missing, the rack falls back to `fcb-banks`, then the first setlist file.
*Source of truth:* `bridge/setlists.py` (`active_id`, `set_active`, `DEFAULT_ID`), `bridge/recall.py` (`fcb_setlist`),
`bridge/modes.py` (`apply_foot_list`), `GET/POST /api/foot-list` (alias `/api/fcb-banks`) in `bridge/app.py`.

**.golem file** — A song (or album) as a zip: `golem.json` manifest (only required member) plus `audio/`,
`stems/`, `scores/`, `sheet.json`, `signatures/`… Media stored uncompressed. Band songs are stored as
`songs/<id>.golem`. The module is standalone (stdlib only) and shared with golem.fm.
*Source of truth:* `bridge/golemfile.py`, `bridge/songs.py`.

**golem.fm** (formerly **Maestrium**) — The optional cloud service: pairing, tone library, stems, song
sharing, jobs. The rack-side client is `bridge/golemfm.py`; config key `golemfm` in
`config/integrations.json`. Documents may still carry `"source": "maestrium"`, which is read as `golemfm`.
Older docs still say "Maestrium"; the rack side of the exchange is `docs/golemfm-protocol.md`.
*Source of truth:* `bridge/golemfm.py` (`_cfg`), `bridge/preset_export.py` (`STORE_SOURCES`).

**Heartbeat** — The rack's periodic status push to golem.fm: `PUT /api/ext/rig/status` every 300 s with the
`light()` payload (pending takes, modes, rig state). `full()` adds CPU/temperature/RAM for the on-demand
`rig-status` job. Not the same as the audio-thread counter (`golem_clock`, `{ticks, t}`) that detects a lost
sound card.
*Source of truth:* `bridge/rigstatus.py` (`light`, `full`, `push`, `_PUSH_EVERY`).

**Hub / page** — The topbar has five entries (`NAV`): Live, Designer, Songs, Library, Settings. A *hub* is an
entry with tabs (Songs, Library, Settings); a *page* is one screen component (`app/page-*.js`), usually a hub
tab. Sub-pages light up their hub (`NAV_ACTIVE`).
*Source of truth:* `app/main.js` (`NAV`, `NAV_ACTIVE`, `PAGES`), `app/page-library.js`, `app/page-songs.js`, `app/page-systeme.js`.

**Input map** (legacy: "patch d'entrées", "patch") — Per-sound-card wiring: physical input → instrument role
and rank (`{ch, role, nth}`). One file per card. Lanes find their input through it.
*Source of truth:* `bridge/inputmap.py`, `config/inputmaps/<card>.json`, `GET/POST /api/inputmap`.

**Job** — An action golem.fm queues for the rack (`install`, `remove`, `recall`, `fetch-backup`, `t3k-install`,
`push-library`, `take-*`, `setlist-*`, `patch-try`…). The rack pulls (never pushed to), runs it on the
`sync` or `rig` queue and always acknowledges it once. Local queues with the same word: re-amp jobs
(`GET /api/reamp`) and transcription jobs.
*Source of truth:* `bridge/tones_jobs.py` (`lane_of`, `_LANES`, `_POLL_EVERY`).

**Knobmap** — `presets/.knobmap.json`, written by `golem_rig` at build: which controller CC drives which
FX parameter (`[{cc, track, stamp, pname}]`). Read by the knob loop for the keyboard controller.
*Source of truth:* `reaper/Scripts/golem_knobs.lua`, `reaper/Scripts/golem_rig.lua`.

**Lane state** (état de lane) — A named state of one instrument lane (`lane.states[]`: `{id, name, blocks,
params, branches, implicit?}`, ids like `st-guitar-1-B`). A scene picks one per lane with
`scene.lanes[<laneId>].state`.
*Source of truth:* `bridge/patches.py` (`_inject_states`), `bridge/scene_bake.py`, docs/band-scenes.md.

**Line** (setlist line) — One row of a setlist: `{id, title, bpm, …}` plus what it plays: `preset`, or
`band_song` (plays that song's sheet preset), or `patch` (in a sound list). Always resolve with `pid_of()`;
screens read `view_line()`.
*Source of truth:* `bridge/setlists.py` (`pid_of`, `view_line`, `update_line`).

**Livemap** — `presets/.livemap.json`, written by `golem_rig` after each rebuild: for every placed block, its
track, FX index and parameter indexes. The bridge uses it to aim expression pedals and parameter changes
over OSC, and to know which preset REAPER actually has built.
*Source of truth:* `reaper/Scripts/golem_rig.lua` (livemap writer), `bridge/recall.py` (`_LIVEMAP_STATE_PATH`, `rig_is_live`).

**Local state** (état local) — Files the running rack rewrites (presets, setlists, mappings, `sets/*.rpp`,
`config/setlist.json`…). Ignored by git; `local_state.preserve` sets them aside around an update.
*Source of truth:* `bridge/local_state.py`, `.gitignore`.

**Mode** (machine mode) — How the whole rack behaves: allowed services, visible pages, locked UI, Live view,
foot list, take kind, record scope. Ids differ from display names: `studio` = **Home**,
`accompaniment` = **Jam**, `pedalboard` = Pedalboard, `rehearsal` = Rehearsal, `gig` = Gig. Default id `studio`.
*Source of truth:* `config/modes/*.json`, `config/modes.local/*.json`, `bridge/modes.py` (`list_modes`, `current`,
`allows`, `live_view`), `GET /api/modes`, `POST /api/mode`.

**Pack** — A TONE3000 / golem.fm bundle of capture files. Its uid is `t3k:<id>`; the local catalog indexes the
same tone by its numeric catalog id. The resolver accepts both; the canonical `ref` is the catalog id.
*Source of truth:* `bridge/resolver.py` (`_resolve`), `bridge/tones_jobs.py` (`install <uid>`).

**Patch** — A musician's sound for one role, reused across songs: `library/patches/<id>.json`. Assigning it to
a preset **copies** its chain (and its scene slice) into the lane; nothing propagates afterwards. A patch can be
played on its own as a preset under the id `patch:<id>`.
*Source of truth:* `bridge/patches.py`, `bridge/store.py` (`_load_patch_preset`, `load_preset`), `GET /api/patches`.

**Preset** — A song's full rig: `presets/<id>.json` with `lanes` (`lanes_v: 2`), `scenes`, `config`
(service lanes), `bpm`… Loaded through one entry point that also serves the virtual ids `sandbox-try`,
`karaoke` and `patch:<id>`. Shown in the Songs hub ▸ Presets.
*Source of truth:* `bridge/store.py` (`load_preset`, `migrate_config`), `bridge/preset_view.py` (`lanes_of`, `is_v2`).

**Quarantine** — A block type or plugin withdrawn because it crashes or freezes REAPER: field `quarantine`
(the reason) on its entry in `effects.json`. Removed from the drawer and from compilation, with a warning.
*Source of truth:* `library/catalog/effects.json`, `bridge/rig.py` (`quarantined_types`, `quarantined_plugin`, `_drop_quarantined`).

**Rebuild** (`rig_recall`) **vs scene_apply** — A rebuild recreates tracks and FX from `<id>.rig.json`; a
`scene_apply` only switches states (bypass, parameters, mutes) on the tracks already built. The bridge picks:
same preset, same *shape* and REAPER alive → `scene_apply`; otherwise rebuild.
*Source of truth:* `bridge/recall.py` (`emit_sandbox_preset`, `scene_shape`, `_LAST_EMIT`), `reaper/Scripts/golem_rig.lua` (`reapply_scene`).

**Recall** (rappel) — Loading a preset at a scene: `do_recall(pid, scene, line)` → compile → command to
REAPER. Triggered by `POST /api/recall`, the pedalboard (PC → `do_recall_slot`), golem.fm jobs, boot.
*Source of truth:* `bridge/recall.py` (`do_recall`, `do_recall_slot`, `emit_sandbox`, `boot_recall`).

**rig_verify** — About 2 s after a recall or scene, `golem_rig` reads back what each NAM/IR plugin actually
loaded and writes `presets/.rig-check.json` (the "FX FILE" chip on /live). It repairs a lost file only after a
rebuild; after a scene change it only reports.
*Source of truth:* `reaper/Scripts/golem_watch.lua` (`VERIFY_DELAY`, `verify_heal`), `reaper/Scripts/golem_rig.lua`.

**Scene** — One of a preset's sound states, switched without rebuild: `{id, name, blocks: {<id>: bool},
params: {<block>: {<param>: v}}, branches, lanes: {<laneId>: {state, level, mute}}}`. Ids are position
letters (`A`, `B`…); footswitch CC 20–24 = scenes A–E.
*Source of truth:* `bridge/preset_view.py`, `bridge/scene_bake.py`, `bridge/foot.py`.

**Serial** (`golem_N`) — The rack's lifetime number, assigned by golem.fm per machine and written once to
`config/serial.json` (read-only); a different number later goes to `config/serial.conflict.json`.
*Source of truth:* `bridge/serial.py`.

**SETTLE** — After a rebuild, `golem_watch` freezes every rig operation (rebuild, scene, stomp) for 0.5 s while
plugins finish loading. Bridge timers are set above it (`backing.RECALL_SETTLE_S = 0.7`,
`commands._SLOT_TIMEOUT = 0.9`).
*Source of truth:* `reaper/Scripts/golem_watch.lua` (`SETTLE`, `settle_until`).

**Setlist / sound list** — An ordered list of lines in `setlists/<id>.json`. `kind: "songs"` lines play presets
or band songs; `kind: "sounds"` lines play patches. Never mixed. Shown as "Banks & Setlists".
*Source of truth:* `bridge/setlists.py` (`KINDS`, `create`, `load`, `save`).

**Song** (band song) — A song of the band's repertoire, stored as `songs/<id>.golem`; its `sheet.json` names the
preset it plays. Setlist lines point to it with `band_song`.
*Source of truth:* `bridge/songs.py`, `bridge/setlists.py` (`pid_of`).

**Space** (band space, `band`; legacy "groupe") — A band or personal project on golem.fm
(`bands[]` of `GET /api/ext/band`: `{id, name, kind: personal|band, people[]}`). Only the opaque `id` is a
key: it is frozen into each take's `band` tag at the start of the REC; `name` and `slug` are display only.
The *current* space is chosen on the rack (a mode's `band`, `POST /api/band/current`) among the cached
ones; a sync replaces the list but keeps the current space by id, and falls back to `default`, then the
`personal` space, only if it vanished. The rack never creates a space.
*Source of truth:* `bridge/roster.py` (`sync`), `bridge/takes.py` (`resolve_band`), `bridge/routes_patches.py`, docs/identity.md §3.

**Standard** — A chord grid (iReal Pro format, from golem.fm) that the rack plays as piano + bass through the
`standard` block, transposable. Grids live in `library/standards/` (`golem/`, `local/`, `synced/`).
*Source of truth:* `bridge/standards.py`, `docs/standards-format.md`.

**Stomp** — A footswitch position 6–10 that toggles every block whose `foot` equals it (several blocks per
switch allowed). Switches used by sample, drums, standard or arrangement blocks follow their own gesture.
*Source of truth:* `bridge/app.py` (`_do_stomp`), `bridge/preset_view.py` (`stomp_states`, `FCB_SWITCHES`).

**Take kind** — What a take says about itself to golem.fm: `rehearsal`, `gig` (or legacy `show`, read only),
plus `riff` for the Riff block. Comes from the machine mode's `take_kind`.
*Source of truth:* `bridge/modes.py` (`TAKE_KINDS`, `take_kind`), `bridge/takes.py`.

**Tone** — An entry of the local capture catalog `library/catalog/tones-index.json`: `{id, title, gear,
format, models[], pack…}`. A block's `ref` names a tone; `model_id` picks one model file inside it.
`gear` (`amp-cab`, `amp`, `pedal`…) is declared upstream, while the file extension is read.
(`library/tones/*.json` are two old recipe files, not this.)
*Source of truth:* `bridge/resolver.py` (`_tones_index`, `_resolve`), `bridge/config.py` (`CATALOG`).

**Trial** (essai) — A Designer draft that is not a named preset (an opened patch, or a new bench) becomes
the current preset so /live and the pedalboard play what you hear: id `sandbox-try` for an unnamed
draft, `patch:<id>` for a named patch. No file is ever written under these ids.
*Source of truth:* `bridge/recall.py` (`is_trial_doc`, `trial_id`, `is_trial_id`), `bridge/store.py` (`SANDBOX_TRY_ID`, `_load_sandbox_try`).

**Union materialization** — On rebuild, the rig engine builds every lane and block used by *any* scene of
the preset; a scene then only mutes tracks (`D_MUTE`) and bypasses blocks. Keeps topology stable so scene
changes need no FX add/remove.
*Source of truth:* `bridge/scene_bake.py` (`to_paths_preset(..., union=True)`), `bridge/recall.py`, `bridge/rig.py` (mute → `D_MUTE`).

---

## Naming in code vs on screen

The UI is English; code identifiers and data keys are often French or legacy. Do not rename identifiers
to match the screen: files, saved data and tools depend on them.

| On screen | In code / data |
|---|---|
| Home, Jam, Pedalboard, Rehearsal, Gig | mode ids `studio`, `accompaniment`, `pedalboard`, `rehearsal`, `gig` |
| Settings | route `system` (legacy alias `systeme`), file `app/page-systeme.js`; tabs Mode · System · Gear · Engines · Content · Connect · About (`#/system/<tab>/<sub>`); the old addresses (`#/system/pedal`, `#/system/api/mst`…) redirect (`legacyRoute`) |
| Recordings | tab id `recordings`, alias `loops`; API `/api/loops`, `/api/take/*`; French "prises" |
| Presets (Songs hub) | component `SetlistsPage` in `app/page-setlists.js` |
| Banks & Setlists | tab id `setlists`, `app/page-setlist-groups.js` |
| Riff | block type `compo` |
| Head+Cab (NAM), Head (NAM), Cab (IR) | block types `amp`, `amp-nam`, `cab` |
| guitar 1, voice 1 (numbered lanes) | lane ids `guitar-1`, `voice-1`; legacy top-level keys `guitar` / `voice` / `keys` with `in` / `out` / `names` are regenerated as mirrors for old readers (`preset_view._mirror_legacy`, `LEGACY_KEY`) |
| New preset | draft id `nouveau-preset` |
| recall / load | `do_recall`, `rappel`; REAPER action `rig_recall` = rebuild |
| foot list | `fcb_setlist()`, `/api/fcb-banks`, fallback setlist id `fcb-banks` |
| golem / /golem_ (never "GoleM") | identifiers keep `GoleM`: folders, firewall rule, mDNS service, `GoleM:*` legacy track sweep |
| golem.fm | `golemfm` (current), `maestrium` (old docs, accepted `source` value) |
| input map | French comments "patch d'entrées" |
| Players / Recorder & Click / Arrangement | config lanes `gen` / `rec` / `arr` |
