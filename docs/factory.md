# Factory content

> **Status: PARTLY CODED** — the factory content (patches, presets, setlists, Standard grids, grooves, DX7
> bank) ships in `library/factory/` and is seeded at bridge start-up, untouched old versions are updated, changed
> ones are kept and can be reset; hiding, restoring and downloading its captures are coded. The read-only lock ("Save as mine") is **PROPOSED, not built**.

Related: [patches.md](patches.md) (patches, sound banks) · [setlists.md](setlists.md) ·
[standards.md](standards.md) (Standard engine) · [arrangement.md](arrangement.md) ·
[block-status.md](block-status.md) (missing captures).

Code: `bridge/factory.py`, routes in `bridge/routes_t3k.py` (`/api/factory/*`), seeding call in
`bridge/app.py` (start-up, before the boot recall), UI filter `app/factory-show.js`. Tests:
`tests/test_factory.py`.

---

## 1. Rules

- **Nothing that belongs to someone else.** Songs are fictitious: titles, chord grids and forms are
  original (a 12-bar blues or a ii-V-I belongs to nobody; a melody, title, lyrics or arrangement does).
  Scene names are playing names, never an artist or a song title. Captures are shown by amp name.
- **A chain without a split lives entirely in `pre`.** The Designer draws `post` only behind a split; the
  engine plays `pre` then `post` either way. The 2026-11-16 factory shipped `{pre, split: null, post}` and
  14 patches and 9 presets opened cut after `pre` (amp invisible, though it played). `make-factory.py` `patch()` now folds
  `post` into `pre`, and `richChain` (app) does the same for any document it reads.
- **Every state says everything it toggles.** A block a scene does not name stays ON at the rig
  (`scene_bake`). The 2026-11-16 factory wrote "Crushed: crush on" without turning it off elsewhere: the
  effect played in every scene and 27 patches (keys, drums, bass, voice) had scenes that changed nothing.
  `make-factory.py` `_explicit()` now writes every toggled block into every state (off if it has a
  footswitch, on otherwise) and refuses two scenes with the same content.
- **Captures are TONE3000 links, not files.** Amp, cab and outboard captures (`amp`, `amp-nam`, `cab`,
  `pedal-nam`, `preamp-nam`, `comp-nam` blocks) are referenced by TONE3000 id (`ref`) and model (`model`);
  the rack ships none. Everything else (drives, modulation, delays, reverbs, pitch, filters, dynamics,
  keys, drums, Standard, arrangement) ships and plays as is.
- **A capture is used for what it IS.** Its nature is read in the `.nam` file (`metadata.gear_type`), not in a
  catalogue label: a `full-rig` capture (pedal + amp + cab + mic) is an `amp` block with nothing after it, never a
  `pedal-nam` in front of another amp and cab. Fixed 2026-10-20 on Metal Bass, Rock Grind and Synth Bass, whose
  Darkglass captures (27697, 27698) are full rigs: each now has its own branch, opened by the states instead of a
  switch (bypassing an amp block would let the dry bass through).
- **What is missing is said.** A patch whose capture is not downloaded still opens; the block shows its
  download state ([block-status.md](block-status.md)).
- **One sound exists once.** Every lane of a factory preset was built by depositing a factory patch
  (`patches.apply_to`); presets reuse only factory patches (checked by `tests/test_factory.py`).
- **Every factory object compiles**, all its references resolve, no block is quarantined.
- **Nothing machine-specific ships.** No per-person settings (`persons`), no input numbers computed for a
  card (`input`, `on_card`, numbered `in_sel`): lanes bind by role on the user's card
  ([patches.md](patches.md) §5.2). A lane whose role has no input on the card waits ("IN —") rather than
  taking another input.
- Each shipped object carries `factory: true`; list routes also mark factory ids with `factory.mark()`.

## 2. Delivery (`bridge/factory.py`)

The folders where these objects live (`library/patches/`, `presets/`, `setlists/`,
`library/standards/golem/`, `library/grooves/`, `library/dx7/`, `songs/`) are local state, not versioned. The
factory has its own versioned source:

| Kind (`factory.KINDS`) | Source | Destination | Count |
|---|---|---|---|
| `patches` | `library/factory/patches/*.json` | `library/patches/` | 52 |
| `presets` | `library/factory/presets/*.json` | `presets/` | 13 |
| `setlists` | `library/factory/setlists/*.json` | `setlists/` | 6 |
| `standards` | `library/factory/standards/*.golem` | `library/standards/golem/` | 3 |
| `grooves` | `library/factory/grooves/*.mid` (+ `meta.json`) | `library/grooves/` | 26 |
| `dx7` | `library/factory/dx7/*.syx` (SynprezFM, see `CREDITS.md`) | `library/dx7/` | 1 |
| `songs` | `library/factory/songs/*.golem` | `songs/` | 1 |

Factory Vital presets are versioned separately in `library/synth/vital/factory/`; factory drum kits come
from `library/kits-factory/`.

`factory.seed(force_ids=None)` runs at every bridge start:

- a missing file is copied;
- an existing file that is an **old factory version, untouched**, is replaced by the current one (`updated` in the
  result, logged). "Old factory version" means its SHA-256, line endings normalised, is listed for that file in
  `library/factory/history.json` — every version any commit ever shipped, written by
  `tools/gen-factory-history.py` from Git, because a release has no Git to ask;
- an existing file that differs from an old factory version **only by what this machine writes into it** is
  updated too, and keeps those writes (`factory.carry_local`). Machine writes are: `deps`, `deps_sig`, `unresolved`
  (resolved from this machine's library by `patches.refresh_deps`), the lane input binding (`in_sel`, `in_name`,
  `in_role`, `in_nth`, `bind_error`), `config.rec` (the recorder's settings), and `stereo` / `disabled` written as
  `false`; in a **setlist**, `created_at`, `updated_at`, `origin` and `factory` (the rack stamps them when it reads
  the list). The comparison uses `factory.canon_sha`; `history.json` holds those canonical hashes under `canon:<kind>/<file>`
  (JSON kinds only). Anything else (chain, settings, scenes; a scene block `null` → `false` is a real change) is an edit;
- a patch, preset or setlist the factory **no longer ships** is removed when its copy is untouched (`_retire`, same
  test as above) — **unless something here still points at it**: a line of any setlist left in `setlists/`, or the
  start-up home (`_still_used`). It then stays and becomes the user's. An update never leaves a dead bank behind;
- an existing file that is **not** a known factory version, even ignoring machine writes, was changed on this machine
  by the person: it is **never overwritten**;
- every file placed once is recorded in `presets/.factory.json` (the ledger); a factory object the user
  deleted is **not** put back on the next start;
- placed grooves get their metadata merged into the groove library sidecar (`_groove_meta`), without
  touching other grooves.

Consequence: changing `library/factory/` reaches every rack whose copy is untouched, at its next start. **After
any change under `library/factory/`, run `python tools/gen-factory-history.py`** and commit `history.json` with the
change: `tests/test_factory.py` fails while the current version of a shipped file is missing from it. The history only
grows; a version that once shipped stays recognised.

Changed copies are listed by `factory.edited()` and offered in Settings ▸ Content ▸ Factory under **Changed on this
golem ▸ Review**: **Reset** (two taps) replaces one, or all, with the factory version — the local change is lost.
(Fixed 2026-10-22: a rack set up on 2026-10-19 played 37 stale factory objects, and its factory setlist did not know
the ninth preset, Ambient Metal. Fixed 2026-10-24: a Windows rack kept stale factory patches nobody had opened, because
`refresh_deps` and the Designer had written machine data into them. Fixed 2026-11-16: after the factory was rebuilt,
the six factory setlists stayed the old ones — the rack's own stamps made them look edited — while the patches they
named were retired: no bank loaded and start-up stopped on "the first preset could not be loaded". The start-up recall
now also tries the next bank that loads, and opens the app when none can.)

## 3. Hide and restore (Settings ▸ Content ▸ Factory)

The factory is **hidden, never deleted** by a switch per kind.

> **FIXED 2026-11-15 (maintainer's decision): factory content cannot be deleted at all.** A deleted factory item came
> back with the next update, and a factory patch that used it broke in between. `factory.protected(kind, id)` (an id
> in `catalog()`) makes every delete route answer `403 {error, factory: true}` — patches, presets, setlists, grooves,
> songs, block presets with `factory: true`; kits and the Vital factory pack already refused — and the golem.fm jobs
> `patch-delete` / `preset-delete` fail with the reason. The UI offers no Delete on a factory item: its menu points to
> this tab instead. **What the user added** (downloaded NAM captures, imported Vital presets and kits, their own
> patches) is **deleted**, to the trash where one exists — never "hidden": it is theirs and takes disk space. If golem
> ever ships factory captures, they follow the factory rule. `removed()` / `restore()` stay for items deleted before
> this rule.

> **FIXED 2026-11-15 (maintainer's decision): ONE setting for golem.fm and the golem.** golem.fm writes it from
> /profile/settings ▸ Factory content as the person pref `factory_hidden` ("patches,kits": hidden kinds in
> `VIS_KINDS` order; "" = show all), served with the roster. `factory.fm_hidden()` reads it from the **owner**'s card:
> when present it decides `visibility()`, and the tab shows its switches inert with "Set on golem.fm" (`managed`).
> When golem.fm says nothing (no band, no owner, no key), the golem's own switches apply (`presets/.factory-show.json`).

| Endpoint | Function | Effect |
|---|---|---|
| `GET /api/factory/visibility` | `visibility()` | `{show: {patches, presets, setlists, kits, grooves, standards}, kinds}`; default all `true`, stored in `presets/.factory-show.json` |
| `POST /api/factory/visibility` `{show: {kind: bool}}` | `set_visibility()` | |
| `GET /api/factory/status` | `catalog()`, `removed()` | counts per kind, factory files the user deleted, visibility |
| `POST /api/factory/restore` `{files?}` | `restore()` → `seed(force_ids)` | puts back deleted factory files (all, or the named ones) — "Restore factory content" |
| `POST /api/factory/reset` `{files?}` | `reset()` | replaces factory files **changed on this machine** (all, or the named ones) with the factory version — "Reset to factory"; `GET /api/factory/status` lists them under `edited` |

Hidden objects are **filtered out before rendering** in browsing pages (`app/factory-show.js`
`keepFactory`), never hidden with the `hidden` attribute. The routes still list everything: whatever
resolves an object by id (the preset playing, a kit used by a visible preset, a mode's `foot_list`) keeps
working. Hiding the factory setlist does not remove it from a mode that names it ([patches.md](patches.md) §6).

## 3 bis. One factory set for the rack and golem.fm

> **Status: PARTLY CODED 2026-11-21** — the maintainer's decision the same day: factory content is **one** set,
> shipped with golem and held by golem.fm, the same for every account, with nothing to render or upload again.
> CODED on the rack: the extended bundle index (below), `factory_edited` in the heartbeat, the `factory-reset` job.
> Also CODED, and inert until golem.fm announces its store: the rack stops pushing `factory-*` documents and refuses
> a preview job for one ("The switch", below). The extended bundle is **not published** (current release:
> `factory-demos-v3`).

**The rule for a factory object changed on a golem** (maintainer, 2026-11-21, relayed by the golem.fm session and
confirmed by him there):

- It **stays changed and keeps its name** — and so its `factory-*` id. No automatic copy, no rename.
- To really rename it, the musician **copies** it; the copy is theirs.
- golem.fm holds the **untouched original** of every factory object and nothing factory can be changed on the site;
  no golem's sync overwrites that original. From the site the musician can **push the original again**.

What the rack does for it:

- **It says which factory objects are changed here**: the heartbeat carries `factory_edited: [{kind, id}]`
  (`factory.edited_ids`, the list of `factory.edited()` kept 60 s). An object counts when it is neither the current
  nor an older shipped version **after** removing what the machine writes alone (`deps` of its library, the input
  bindings of its card: the canonical fingerprint of §2) — so the list means a person's edit. golem.fm shows
  "modified on your golem", and says that the shared listen is no longer what this golem plays.
- **`factory-reset`** (job, [golemfm-protocol.md](golemfm-protocol.md) §3): `{ids: [{kind, id}]}` or `{files: [...]}`
  puts the shipped version back, as "Reset to factory" does on the screen (`factory.reset`). The edit is lost: the
  site says so before sending. An object that is not edited is left alone and returned in `unchanged`. Refused
  without a target, in a locked mode, during a take, or when the preset named is the one playing. A rack that
  understands it lists `factory-reset` in `caps.jobs`.

- **Nothing from golem.fm merges into a factory object.** The job `setlist-push` is refused for a factory setlist,
  always (not only once golem.fm serves setlists); a factory patch or preset is never installed from the site either
  (`preset-install` would create `<id>-2` next to the edited one): restoring is `factory-reset` only, from the rack's
  own shipped file — a golem on an older version gets its version's original.

**The bundle** — the existing factory demos release ([preset-preview.md](preset-preview.md) §10), extended rather
than doubled by a second archive. `tools/pack-factory-demos.py` now also packs, and its index describes:

| Index key | What |
|---|---|
| `tag`, `rack_commit`, `rack_dirty`, `catalog_version`, `golem_fx_version` | what the pack was rendered with. A listen's `fingerprint` follows the **document**, not the engine: a golem-fx or catalogue change alters the sound and leaves it unchanged, so staleness is judged on (document sha, tag), not on the fingerprint alone |
| `items` | unchanged: what a golem places in `library/previews/` (`bridge/factory_demos.py` reads only this) |
| `documents[]` | every shipped factory document `{kind, id, file, sha256, fingerprint}` (`factory/<kind>/…` in the archive; `fingerprint` for JSON documents only), and `history` |
| `di` | the reference DIs and MIDI phrases `{refs: {ref: {file, sha256, kind}}, missing: [...]}` (`di-refs/…` in the archive) |
| `renders[]` | every render of a factory patch or preset lane `{kind, id, input \| lane, scene, file, sha256, duration, di_ref, di_sha256, fingerprint, generated}` |
| `patches[]` | **every** factory patch `{id, renders, reason?, stale?}`: a patch without a render says why (`reference DI missing: voice/male (record it first)`), so the site says "coming" instead of showing a hole; `stale` = the document changed since the render |

A render's `fingerprint` is the one of the patch **bound to the rendering rack's card** (`preview.plan`), not the
one of the shipped file in `documents[]`: the two are not expected to be equal.

Dry run on the maintainer's rack, 2026-11-21 (nothing published; golem was stopped): 103 documents, 20 reference DIs (3 named by the index have no file:
`voice/male`, `voice/female`, `keys/arp`), 337 renders, 100.7 MB. Of 53 factory patches: 8 up to date, **31 stale**
(the patch as this rack loads it no longer has the fingerprint of its render of 2026-11-16; the cause is not
established — the factory was rebuilt since, and golem had not started, so not re-seeded, after that day's update), 11 voice patches without a reference DI, 2 pad
patches that are never rendered (triggered samples), 1 not rendered yet. **A new bundle is therefore not worth
publishing before the batch has run again on the maintainer's rack.**

**Still to do**, in this order:

1. Run the factory batch on the maintainer's rack (engine taken for about half an hour), then
   `./tools/pack-factory-demos.py --publish factory-demos-v4` and bump `factory_demos.TAG`.
2. golem.fm imports the bundle into its user-less factory store and serves it to every account.
3. golem.fm announces its store in the answer to the heartbeat; the rack then follows by itself (below).

**The switch, per kind** (CODED 2026-11-21, waiting for golem.fm to send the field): the answer to
`PUT /api/ext/rig/status` may carry `factory_store: {kinds: ["patches", …], rack_commit}` — the kinds golem.fm serves
from its own store (`factory.set_fm_store`, kept in memory; kinds known here: `patches`, `presets`, `setlists`). For
a kind it names, and for factory objects only (`factory.fm_serves`):

- `push_patches` leaves the factory patches out of the catalogue it sends; `publish_preset` / `needs_publish` skip a
  factory preset; `push_setlist` skips a factory setlist. An edit made here is never sent in the original's place.
- the jobs `patch-preview` and `generate-preview` are refused for one ("… is factory content: its listen ships with
  golem, it is not rendered again").

**Absent field = everything is pushed, as before.** It has to be so: `push_patches` sends the whole catalogue with
`complete: true` — what is absent is deleted on the site — so the rack must not drop the factory patches before
golem.fm serves them. At start, before the first answer, everything is pushed too.

The heartbeat also carries `factory_held: {patches: [ids], presets: [ids], setlists: [ids]}` — the factory ids
**placed on this rack** (ids only). "On rack" stays a measurement on golem.fm's side: a golem left on an older
version says by itself that it lacks a newer factory patch.

## 4. Factory captures download

| Endpoint | Function |
|---|---|
| `GET /api/factory/captures` | `captures()`: `{total, present, missing: [{tone, models, title}]}`, read on disk through the resolver, plus `connected` (a TONE3000 token exists) and the download state |
| `POST /api/factory/captures/download` | `start_download()`: one thread, one tone at a time, through the TONE3000 install pipeline (`routes_t3k._install_worker`) with the user's account; requests the **union** of the models already installed and the models the factory needs. `409` if a TONE3000 install is already running |

## 5. Content

### 5.1 Sound banks (5 setlists of `kind: "sounds"`)

> **Rebuilt 2026-11-16** (the maintainer: "we start again from new", on golem's own golem-fx blocks) by
> `tools/make-factory.py`, which writes every patch, preset, bank, the factory setlist and Golem Rising. The previous
> content left `library/factory/`; on a rack, `factory.seed` **retires** an old factory object that is no longer
> shipped when it is untouched (its version, or its version up to machine writes, is in `history.json`) — a copy the
> person changed stays and becomes theirs. The styles are inspirations only (never named in what ships, §1); the
> preset names and fictitious songs come from golem.fm's plan (conception/plan-factory-golem-fx.json, not shipped).

Every patch: one lane, 4–5 scenes with playing names, a theme colour, something to play along with on SW10 and REC or Riff on SW9 (one of the two, both kinds in every bank). Guitar and bass: a gate first, one
saturation source per state, at most one amp branch open per state, solos +2/+3 dB. Keys and voice: linear chains;
voice saturation is Morph only. Captures are TONE3000 refs present in the tone catalogue; full rigs take no cab.

**SW10: a Standard for jazz and blues, the drum machine elsewhere** (2026-11-16; `PATCH_STD` in `make-factory.py`).
The jazz and blues patches of every bank carry a Standard block instead of the drum machine — the block excludes
it (two drummers) — and the Standard never plays the part of the patch's own instrument:

| Grid | Patches | Parts that play |
|---|---|---|
| Rooftop Prowl (160) | Jazz Box · Upright Jazz · Jazz Piano · Crooner · Jazz Brushes | piano · bass · drums, minus the patch's own |
| Rented Room Blues (96, 66 on Wailing Blues) | Texas Shuffle · Wailing Blues · Blues Round · Blues Organ · Blues Shout · Vintage Rock | piano · bass · drums, minus the patch's own |
| Crooked Lantern (200) | Gypsy Acoustic | rhythm guitar ("pompe") · bass |

**Sounds validated by ear** (2026-11-16). A factory patch is tuned in the Designer at the rig, then validated:
`tools/make-factory.py --validate [id…]` copies its chain, lane states, scenes, tempo, SW10 block, colours and
animations from the local copy (`library/patches/<id>.json`) into `tools/factory-validated/<id>.json`. That file
then **replaces** what the patch's function in `make-factory.py` describes; the generator still owns identity,
dependencies and the presets, which take the validated lane by **state name** — renaming a state, or removing a
block a preset puts on a switch, fails the generation. The generator refuses to run while a factory patch is
edited on this rack and not validated (`--overwrite-edits` drops the edits). Validated so far: 13 of the 15 guitar
patches — all but Fuzz Grunge and Wailing Blues, which were not edited after generation.

**Metal Grind (bass) was rebuilt on a split** (2026-11-16): a clean SVT rig for the low end beside a Darkglass
Alpha Omega Ultra into a 4x10 for the grind — Grind plays both, Tight the grind alone, Clean Low the SVT alone,
Solo Growl both behind the boost. The other bass patches got the same treatment as the keys below.

- **One split per instrument, two branches at most** (rule fixed by the maintainer, restated 2026-11-16). The
  Designer draws two branches; a third one plays without being seen or set. Bass Lab had three (clean, Darkglass,
  synth): its synth is now a block in series after the sum (SW7), on in *Synth Layer* and *Full Stack*. Pop Chorus
  had three too (its nylon voice): the nylon is now a block before the split, on in *Nylon Solo* only, into the clean
  amp. The generator refuses a third branch, a sound validated by ear included, and `tests/test_factory.py` checks
  every shipped patch and preset.

**Keys and bass scenes must be heard** (2026-11-16). A scene that only moved an EQ shelf by 3 dB or a reverb mix by a few
points was judged identical at the rig. Every keys scene now changes something obvious: an effect on or off (a
hall, a tape, a chorus, a delay), a filter swept wide, an octave down, a dry or drowned space.

**Fuzz Grunge and Groove Metal were rebuilt on 2026-11-16** (judged weak by ear at the rig). Fuzz Grunge: a
split with two amps — the op-amp Big Muff into a miked modified JCM800 for the wall, a bright Twin and a 2x12
Creamback for the clean scene. Groove Metal: a miked solid-state full rig instead of a head behind an IR, a
lighter mid scoop (−3 dB at 800 Hz, was −6), and a miked JC-120B for the clean. Scene names and stomp ids are
unchanged. Not heard at the rig yet.

**Gypsy Acoustic** is a patch to play alone, in no preset and no song: the Acoustic Sim block (no amp or cab behind
it) and the pompe of Crooked Lantern. The pompe needs the `guitar` sound pack (Shinyguitar,
[`standards.md`](standards.md) §10). The other patches keep the drum machine with a groove of their style.

| Bank | Patches (scenes) |
|---|---|
| Guitar (15) | Jazz Box (Comping · Chord Melody · Solo · Ballad · Bright Swing) · Texas Shuffle (Clean Shuffle · Texas Rhythm · Lead · Vibratone · Slow Burn) · Wailing Blues (Clean Ballad · Crunch · Singing Lead · Endless Bend · Rhythm) · Ambient Djent (Halo Clean · Glass Arp · Low Riff · Wall · Lead) · Hero Lead (Clean Arp · Rhythm Drive · Hero Lead · Harmony Lead · Vocal Wah) · Groove Metal (Southern Riff · Chug Breakdown · Scooped Wall · Clean Chorus · Lead) · Squeal Lead (Lead · Wah Lead · Octave Squeal · Flanged Riff · Dive) · Glass Ambient (Glass Clean · Crunch Burst · Frozen Pad · Ring Glitch · Tape Echo) · Loop Indie (Jangle · Dotted Echo · Klon Push · Swell Pad · Lead Out) · Fuzz Grunge (Verse Crunch · Fuzz Wall · Fuzz Lead · Phased Bridge · Jet Clean) · Funk Clean (Chop · Neck Chords · Envelope · Bright Slap · Swirl) · Funk Drive (Crunch Rhythm · Dirty Chords · Wah Lead · Fuzz Solo · Flanged Crunch) · Eight-String Nu (Dream Clean · Whisper Clean · Heavy Low · Shoegaze Wall · Octave Dive) · Pop Chorus (Verse Clean · Chorus Crunch · Nylon Solo · Ballad Arp · Bridge Drive) · Gypsy Acoustic (Theme · Chorus · Ballad · Nylon · Rhythm) |
| Bass (10) | Upright Jazz (Walking · Ballad · Solo · Bright Pluck) · Blues Round (Round · Push · Warm Ballad · Growl Fill) · Prog Bi-Amp (Sub Clean · Grit Blend · Tight Grit · Growl) · Metal Grind (Grind · Tight · Clean Low · Solo Growl) · Synth Ambient (Round · Sub Octave · Synth Bass · Tape Fuzz) · Fuzz Bass (Pick Drive · Fuzz Bass · Clean Verse · Wall) · Funk Slap (Slap · Fingers Pocket · Envelope · Octave Funk · Solo Pop) · Nu Low (Clean Low · Heavy Blend · Grind Only · Chorus Low) · Pop Pick (Pick Verse · Chorus Drive · Ballad · Chorus Bass · Melodic) · Bass Lab (Sub Only · Grit Blend · Synth Layer · Full Stack · Solo Chorus) |
| Keys (12) | Jazz Piano (Trio · Ballad · Solo · Soft) · Blues Organ (Gospel Bed · Fast Leslie · Screaming · Soft Pad) · Cathedral Piano (Hall Piano · Halo · Under · Bloom) · Hero Pad (Sky Pad · Bright · Under · Shimmer Rise) · Dark Pad (Dark Pad · Low Drone · Swell · Crushed) · Glass Rhodes (Glass Rhodes · Tape Rhodes · Dry Keys · Underwater) · Electro Pads (Beat · Crushed Beat · Tape Beat · Dub Beat) · Loop Synth & Beat (Bass & Beat · Bass Only · Filtered · Big Drop) · Strings Wash (Strings Wash · Chorus Strings · Thin · Big Swell) · Funk Clav (Clav · Envelope Clav · Phased · Stab) · Nu Haze (Haze · Glitch Haze · Low Haze · Open Haze) · Pop Piano (Ballad Piano · Bright Pop · Echo Piano · Soft Bed) |
| Voice (10) | Crooner (Close · Ballad · Slap · Big Room) · Blues Shout (Shout · Grit · Slap Echo · Ballad) · Halo Vocal (Falsetto Halo · Close Verse · Grit Belt · Anthem) · Metal Scream (Scream · Growl · Clean Shout · Megaphone) · Ethereal Falsetto (Ethereal · Close · Robot Falsetto · Cloud) · Indie Double (Double · Single · Slap · Shout) · Raw Grunge (Raw · Gravel · Quiet Verse · Scream) · Funk Rap (Rap · Phone Verse · Chorus Double · Slap Hook) · Whisper & Scream (Whisper · Dream · Scream · Low Growl) · Pop Tuned (Pop Verse · Chorus Double · Ballad · Hard Tune) |
| Drums (5) | Jazz Brushes (Brushes · Ride Swing · Soft · Solo) · Vintage Rock (Shuffle · Big Room · Tight · Ballad) · Studio Rock (Tight · Punch · Roomy · Soft) · Metal Kit (Blast · Breakdown · Tight · Clean Intro) · Lo-Fi Kit (Tape Kit · Crushed · Dry · Dusty) |

The drums patches play a factory kit from an electronic kit over USB MIDI (Lo-Fi Kit: tape and bitcrusher for the
electronic styles, with the Electro Pads lane); the drum machine is never a patch, it is a preset service block.

### 5.2 The `factory` setlist ("Factory Golem", 13 songs)

Every preset is a full band built from bank patches (each lane deposited by `patches.apply_to`), at least one keys
lane, with its special blocks. Songs are fictitious.

**Every preset has a guitar lane and a bass lane, and a voice lane except where the song is instrumental** (FIXED
2026-11-20). Whoever is plugged into the rack must be able to play on any song of the setlist: the engine never moves an
instrument onto another instrument's lane ([input-map.md](input-map.md) §3), so a missing lane is silence. Low End
Workshop was Bass + Pad only — with a guitar on a card without a bass input, only the pad played, and it looked like a
freeze. It now has a guitar (Funk Clean, under the bass) and a voice (Funk Rap); Room With Echoes got a bass (Pop Pick).

| # | Song (fictitious) | Key · BPM | Preset (lanes) | Special blocks |
|---|---|---|---|---|
| 1 | Rooftop Prowl | F · 160 | Blue Lantern Trio (Guitar, Bass, Piano, Drums, Voice) | Standard |
| 2 | Rail Yard Shuffle | E · 112 | Rail Yard (Guitar, Bass, Organ, Voice) | Standard (Rented Room Blues in E) |
| 3 | Harbour Rain | Cm · 68 | Harbour Rain (Guitar, Bass, Organ, Voice) | Standard (Rented Room Blues in C) |
| 4 | Velvet Ossuary | F#m · 94 | Velvet Ossuary (Guitar, Bass, Piano, Voice) | drum machine |
| 5 | Glass Summit | E · 120 | Glass Summit (Lead Guitar, Bass, Pad, Drums) | drum machine |
| 6 | Iron Thicket | Eb · 132 | Iron Thicket (Guitar 1, Guitar 2, Bass, Pad, Voice, Drums) | drum machine |
| 7 | Paper Satellites | D · 86 | Paper Satellites (Guitar, Bass, Rhodes, Pads, Voice, Drums) | drum machine |
| 8 | Room With Echoes | A · 104 | Room With Echoes (Synth & Beat, Guitar, Bass, Voice) | looper |
| 9 | Velvet Wasp | Eb · 118 | Velvet Wasp (Guitar, Bass, Strings, Voice, Drums) | drum machine |
| 10 | Sunset Ladder | Em · 98 | Sunset Ladder (Clean Guitar, Drive Guitar, Bass, Clav, Voice) | drum machine |
| 11 | Paper Promises | Cm · 76 | Paper Promises (Guitar, Bass, Piano, Voice, Drums) | drum machine |
| 12 | Low End Workshop | D · 100 | Bass Workshop (Guitar, Bass, Pad, Voice) | drum machine |
| 13 | Golem Rising | F#m · 120 | Low Tide (Guitar, Bass, Synth, Voice) | drum machine + arrangement on SW9 |

**Golem Rising** keeps its form (13 parts, 57 bars, 120 BPM, a one-bar count-in) and is redone on **Low Tide**, the
eight-string nu metal preset: the arrangement changes the scene, the drum machine's metal groove and pedals on each
lane at every part (clean dream intro, whisper verse, heavy low verse, shoegaze wall choruses, an octave-dive solo).
Its `.golem` keeps the cover and band art made for it (`tools/gen-factory-song-art.py`).

### 5.3 The three Standard grids

Original grids, released CC0, in `library/factory/standards/`:

- `rooftop-prowl.golem` — medium-up swing, AABA 32 bars in F, groove `jazz/bop/brushes`. No
  arrangement: the musician changes scenes at the foot.
- `rented-room-blues.golem` — 12-bar shuffle in A with quick change and turnaround, groove
  `blues/texas-blues`. No arrangement (removed 2026-10-20): a standard's form — how many solo choruses — is
  decided while playing, so the scenes change at the foot. The arrangement example is « Golem Rising » (§5.2).
- `crooked-lantern.golem` (2026-10-17) — gypsy swing (`manouche`), AABA 32 bars in D minor at 200: m6 chords,
  minor II-V, Bb7 → A7, a bridge on secondary dominants (D7 · Gm6 · E7 · A7). No drums, as in a gypsy band: the
  chart's parts are the rhythm guitar ("pompe", [`standards.md`](standards.md) §10) and the bass, the `Manouche`
  line-up.

## 6. Proposed, not built

- **Factory lock**: the bridge refuses to rewrite an object with `factory: true`; the Designer offers
  "Save as mine" (a copy); lists show a "factory" badge. Today a factory object is an ordinary local file
  and can be edited in place.
- **Removing a factory bank from the pedalboard** frees its slot while keeping it in the library;
  factory lists placed at the end of the pedalboard so user lists take the first slots.
- **Updating an already placed factory object** on a rack that has it.
- **Instrument assets on a fresh install**: the Salamander piano and the DrumGizmo metal kit come from
  the optional pack of `provision/fetch-assets.sh`; the delivery of the avldrums kits used by the drum
  patches has to be checked.

Setlist snapshots (📷 "Snapshots — frozen sounds", `setlists.snapshot` / `restore`) are a dated backup
of preset contents, not a factory lock.
