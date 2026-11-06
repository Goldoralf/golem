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
| `patches` | `library/factory/patches/*.json` | `library/patches/` | 38 |
| `presets` | `library/factory/presets/*.json` | `presets/` | 9 |
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
  `false`. The comparison uses `factory.canon_sha`; `history.json` holds those canonical hashes under `canon:<kind>/<file>`
  (JSON kinds only). Anything else (chain, settings, scenes; a scene block `null` → `false` is a real change) is an edit;
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
`refresh_deps` and the Designer had written machine data into them.)

## 3. Hide and restore (Settings ▸ Content ▸ Factory)

The factory is **hidden, never deleted** by a switch per kind:

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

## 4. Factory captures download

| Endpoint | Function |
|---|---|
| `GET /api/factory/captures` | `captures()`: `{total, present, missing: [{tone, models, title}]}`, read on disk through the resolver, plus `connected` (a TONE3000 token exists) and the download state |
| `POST /api/factory/captures/download` | `start_download()`: one thread, one tone at a time, through the TONE3000 install pipeline (`routes_t3k._install_worker`) with the user's account; requests the **union** of the models already installed and the models the factory needs. `409` if a TONE3000 install is already running |

## 5. Content

### 5.1 Sound banks (5 setlists of `kind: "sounds"`)

`factory-guitar`, `factory-bass`, `factory-keys`, `factory-voice`, `factory-drums`. Each patch has 4–5
contrasting scenes (base, more gain or solo, the opposite extreme, effects). Guitar and bass patches use
two complementary amps on two branches, a gate first, one saturation source, solos +2/+3 dB.

| Bank | Patches (scenes) |
|---|---|
| Guitar (13) | Jazz Clean (Thumb · Lush · Comping · Solo · Ballad) · Singing Clean (Clean · Singing · Lead · Ballad · Chords) · Funk Clean (Chop · Envelope · Wah · Phase Solo · Clean Pad) · Texas Blues (Texas Rhythm · Lead · Vibratone · Clean · Big Ending) · Indie Chime (Arpeggio · Dotted Echo · Crunch Chorus · Big Chorus · Swell) · British Crunch (Power Chords · Treble Lead · Wall of Chords · Clean-ish) · Fuzz Wall (Intro · Big Muff Wall · Solo · Verse Crunch · Wide Wall) · Brown Lead (Rhythm · Brown Lead · Wah Lead · Flanged Riff · Clean-ish) · Modern Metal (Clean Intro · Chug · Lead · Breakdown · Stutter) · Gypsy Lead (Theme · Solo · Ballad · Rhythm · Finale — an acoustic capture, the Crooked Lantern standard on SW10, played by the pompe and the bass) · Hero Lead (Clean Arp · Rhythm Drive · Hero Lead · Big Lead — an edge-of-breakup lead: a TS9 at low drive and unity level pushing a Fender Deluxe at the edge of breakup, a slow-attack compressor, two delays low in the mix (dotted eighth centred, tape ping-pong), a plate; a bright Twin Reverb branch for the clean. One branch open per state, never two amps summed; made by `tools/make-factory-song.py` from captures already shipped) · Ambient Djent (Halo Clean · Glass Arp · Low Riff · Wall · Lead — a JC-120 full rig for the cleans, a TS9 into a Peavey 6505+ head and a Mesa 4x12 V30 for the tight low riff) · Soaring Lead (Shimmer Pad · Clean Echo · Riff Double · Soaring Lead · Halo Lead — a Twin Reverb full rig for the cleans, a TS9 into an EVH 5150 for the lead, two delays and a shimmer) |
| Bass (7) | Jazz Warm · Vintage Round · Funk Slap · Rock Grind · Metal Bass · Synth Bass · Bi-Amp Grit (Sub Clean · Grit Blend · Tight Grit · Growl — a clean SVT and a Darkglass B7K full rig in parallel, no cab after either) |
| Keys (8) | Jazz Piano (Salamander sfz) · Cathedral Piano (Hall Piano · Halo · Under · Bloom — the Salamander that blooms into a pad through a shimmer) · Electric Piano (DX7) · Rock Organ (tonewheel + Leslie) · 80s E-Piano (DX7) · Warm Pad (Vital) · Synth Lead (Vital) · Loop Bass & Beat (Vital + pads kit, role `keys-pads`) |
| Voice (6) | Clean Vocal · Crooner · Pop Tuned · Rock Vocal · Metal Vocal · Halo Vocal (Falsetto Halo · Close Verse · Grit Belt · Anthem) |
| Drums (4) | Jazz Brushes · Classic Rock · Studio Rock · Metal (electronic kit over USB MIDI) |

Keys patches use a linear chain (no gate, no split); their scenes change the instrument itself
(drawbars, filter cut-off, brightness), not only effects. On voice, the only saturation is the Grit
block. The drum machine is never a patch: it is a preset service block.

### 5.2 The `factory` setlist ("Factory Golem", 9 songs)

Every preset is a full band (one lane per instrument, each from a bank patch, at least one keys lane).
Scenes are named for the song and point each lane at a lane state. Every factory preset and patch has a theme:
one colour on every occupied cell (scenes and used switches) and an animation per cell (2026-10-20: Diesel Heart
was the one without; that was a mistake).

| # | Song (fictitious) | Key · BPM | Preset | Extra |
|---|---|---|---|---|
| 1 | Rooftop Prowl | F · 180 | Chill Jazz (guitar, rhythm guitar, bass, keys, drums) | Standard block on SW9, stopped by default; REC on SW10 |
| 2 | Rented Room Blues | A · 96 | Blues Night (guitar, rhythm guitar, bass, keys, drums) | Standard block on a switch — no arrangement (a standard's form is played at the foot) |
| 3 | Velvet Pocket | E · 104 | Funk Session | Drum machine on SW10, REC on SW9 |
| 4 | Diesel Heart | A · 128 | Rock Classics | REC on SW9 |
| 5 | Paper Satellites | G · 118 | Indie Pop (Pop Tuned set to G major) | — |
| 6 | Static Bloom | E · 120 | Alt Rock | — |
| 7 | Iron Tide | D · 140 | Metal for all (two guitars) | REC on SW10 |
| 8 | One-Man Orchestra | A · 100 | Loop Station (keys-pads, guitar, voice) | REC on SW9; looper: keys lays bass and drums, then guitar, then voice (the line says 100, the preset 127: the line wins) |
| 9 | Golem Rising | E · 120 | Ambient Metal (two guitars, bass, piano, voice + drum machine) | **The arrangement example**: the line plays the factory **song** (`band_song`), 13 parts that change the scene, the drum machine's groove and pedals on every instrument (below) |

**Golem Rising** (2026-10-20) is the case the factory did not show: a written song, end to end, with no stems —
the arrangement drives the scenes, the drum machine (docs/arrangement.md §6) and pedals on each lane (§1). It is a
**factory song**: `library/factory/songs/rs-f3f0….golem` (kind `original`, rights `own`, artist « golem »), with
its sheet, a cover and a band photo made for golem with Nano Banana (`tools/gen-factory-song-art.py`: five stone
golems, no human face, no text in the image). It shows in Songs with a « ◆ Factory » chip and **never goes up to
golem.fm** (`songs.is_factory`, `sync_of` → `factory`): it belongs to golem, not to a band. The factory line plays it
through `band_song` and keeps a copy of the sheet, so deleting the song leaves a line that still plays.

Built by `tools/make-factory-song.py [--art <dir>]` (the song, the line, and the Hero Lead patch of the guitar bank)
on the **Ambient Metal** preset (§5.2 bis, built first by `tools/make-factory-ambient-metal.py`) and its seven
`golem-metal-*` grooves. The first version ran on a rock preset (Rock Anthem) with rock grooves; the owner found it
limp (2026-10-20): the song kept its structure, took the metal sounds and rhythms, and Rock Anthem left the factory.
Every toggle is checked against the preset's blocks at build time. 120 BPM, 4/4, a one-bar count-in, 57 bars
(1 min 54):

| Part | Bars | Scene | Groove | Pedals forced on |
|---|---|---|---|---|
| Intro | 4 | Halo Clean | intro | piano echo |
| Verse 1 | 7 | Glass Verse | verse | piano shimmer |
| Fill | 1 | — | fill | guitar 1 Tube Screamer, voice grit |
| Chorus | 8 | Wall Chorus | chorus | guitar 2 chorus |
| Verse 2 | 7 | Low Riff | breakdown | piano echo |
| Fill | 1 | — | fill | guitar 2 shimmer, voice grit |
| Chorus | 7 | Wall Chorus | chorus | guitar 2 quarter-note echo |
| Fill | 1 | — | fill | guitar 2 dotted-eighth delay, voice grit |
| Solo | 4 | Soaring Solo | solo | guitar 1 chorus |
| Solo · climb | 4 | — | solo | guitar 2 shimmer |
| Chorus | 8 | Wall Chorus | chorus | guitar 2 shimmer, voice doubler, piano echo |
| Outro | 4 | Low Riff | breakdown | piano shimmer, voice grit |
| End | 1 | — | the final hit | guitar 1 delay, guitar 2 and piano shimmer |

The bass has no pedal to toggle: its states open or close the Darkglass branch, so it follows the scenes. A part
that recalls a scene starts again from what the scene says: a toggle lasts for its part only. Levels are reasoned,
not measured: re-amp each scene before trusting them.

The song starts from the screen (▶ on /live or Songs) or **at the foot: SW9 is the Arrangement block** (a tap starts
the song, count-in included; a tap while it runs stops everything it started). SW6–SW8 are the stomps (Shimmer, Echo,
Grit), SW10 the drum machine.

The five factory modes ship with `"foot_list": "factory"`.

### 5.2 bis The `Ambient Metal` preset (2026-10-20)

Modern progressive metal, the preset of « Golem Rising » (§5.2): ambient cleans, a tight low riff, a soaring lead, a piano that blooms
into a pad, a falsetto voice. Built by `tools/make-factory-ambient-metal.py` (five new patches, each lane deposited
from its patch). The **gear** was proposed by golem.fm's patch AI (a 6505+ head into a V30 4x12; an SVT and a
Darkglass in bi-amp), each capture's **nature read in its .nam file** (a full rig takes no cab after it), the
settings and gain staging set by hand. No artist name anywhere (§1).

| Scene | Kind | Guitar 1 · Guitar 2 · Bass · Piano · Voice |
|---|---|---|
| A Halo Clean | clean | Halo Clean · Shimmer Pad · Sub Clean · Halo · Falsetto Halo |
| B Glass Verse | clean | Glass Arp · Clean Echo · Sub Clean · Hall Piano · Close Verse |
| C Low Riff | saturated | Low Riff · Riff Double · Tight Grit · Under · Grit Belt |
| D Wall Chorus | saturated | Wall · Riff Double · Grit Blend · Bloom · Anthem |
| E Soaring Solo | saturated (solo) | Wall −4 · Soaring Lead +3 · Grit Blend · Bloom −6 · Close Verse −6 |

Foot: SW6 Shimmer (guitar 2 + piano), SW7 Echo (guitar 1 + voice), SW8 Grit (voice), SW9 the Arrangement, SW10 the
drum machine with the seven `golem-metal-*` grooves (intro, verse, chorus, breakdown, solo, fill, end — in that
order: the arrangement names a groove by its rank) on the Black Pearl kit, which plays on every install. A medium
hold on SW10 moves to the next groove at the bar; a scene does not change the groove (only an arrangement part
does). The parametric EQ, the tape delay, the shimmer and the vocal grit
play on Windows and macOS through golem JSFX that keep the Linux plugins' parameters
([platforms.md](platforms.md) §5): close in sound, not identical; the amps, dynamics, delays and reverbs play on
every system. Levels are
reasoned, not measured: re-amp each scene before trusting them.

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
