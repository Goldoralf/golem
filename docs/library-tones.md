# Library ▸ Tones: the captures, drawn

> **Status: CODED** (2026-11-14). The maintainer approved the four concepts of the mockup (Amps, Pedals, Cabs,
> Outboard, and their detail views) and asked that touching a capture plays it. golem-fx draws the rack units
> (`namRack`, golem-fx dbcf040).

Related: [designer-glyphs-pedals.md](designer-glyphs-pedals.md) (golem-fx's visuals in the app),
[library-loans.md](library-loans.md), [tone-import.md](tone-import.md).

The four tabs of Library ▸ Tones show every capture **drawn** by golem-fx's renderers (`app/vendor/golem-visuals/`,
`tools/sync-golem-visuals.py`), on pages that turn instead of scrolling (the 1024×600 rule). Each tab opens a detail
view in place, where touching a capture **plays it**. Shared code: `app/tones-ui.js`.

## 1. Amps: the backline

- One tile per capture pack, drawn as what it captured: a **head** (`gear: amp`, `namHead`) or a **stack** (`amp-cab`,
  `namStack`). The look follows the gain family (`clean`, `crunch`, `high-gain`, `bass`). A named amp's family wins
  (effects.json `amps[]`); otherwise keywords, then the style.
- The brands are a rail on the left (10, then "+ N more"). The gain family is a **proportional bar** above the shelf:
  its widths are the counts, and tapping a segment filters. 8 amps per page.
- Detail: the amp on a stage; its captures as rows, with what their **names** say as tags (mic, gain, channel).
  "Pairs with" opens a cab of the same style in the Cabs tab. The family switch (Guitar/Bass), the source link
  and the delete flow (trash, per-preset dependencies) are kept from the old card.

## 2. Pedals: the pedalboard

- Two worlds: **captured pedals** (NAM) and **built-in effects** (golem-fx in metal, the others in enamel).
- Captured: one pedal per named pedal (effects.json `pedals[]`), its captures gathered under it, then the captures no
  named pedal claims. A named pedal with no capture stays on the board **greyed**, with "Find on TONE3000".
  Family chips filter; 14 pedals per page.
- Detail: when a capture's name writes its settings ("Drive 7 Tone 6 Level 9", "L8 B7 T5 G10"), **the knobs are drawn
  at that position** (`knobsOf`: two settings at least, values 0–10). The detail opens on the first capture that has
  them.
- A built-in effect has no capture: its detail lists its factory presets (`/api/block-presets/{type}`).

## 3. Cabs: the wall

- The size is read from the name, then from the IR file names ("412 Mesa" counts as 4x12; `cabSize`), and drawn
  with that many speakers. Chips filter by size; 10 cabs per page. A pack with a late echo keeps its "echo" mark.
- Detail, **where the mic was**: each IR whose name places the mic is a dot on the speaker cone (center/cap,
  cap edge, mid cone, edge, or "0.50in" from the center; a 45° slash when off-axis; `micPos`). IRs taken at the
  same spot gather into one dot (×3). When the name says which speaker (UL/UR/LL/LR), only that speaker's IRs are
  shown, and the speaker is circled on the cab. Blends with no position stay in the list.

## 4. Outboard: the 19" rack

- One rack unit per capture pack, drawn by golem-fx (`GolemPedals.namRack`: archetypes in its `outboard.json`,
  a generic preamp/comp/EQ otherwise; height in U). Empty slots invite "+ Add outboard".
- Detail: the captures of a pack read as **one unit**. golem-fx's `outboardSetting(label)` reads each name
  ("1073MP - 60 dB Hard - B" → gain 60, hard, channel B). The settings that vary become a **grid**: columns are
  gain, ratio or time; rows are normal/hard; channel or limit become selectors. Touching a cell turns the unit's
  controls to that setting and plays it. A pack whose names say nothing is a plain list.

## 5. Touch = listen

`POST /api/library/audition {ref, model}` (`bridge/audition.py`, route in `bridge/routes_content.py`) plays a capture
**in the patch that is loaded**:

- A **copy** of the current preset is emitted under the id `audition`. Nothing is written: not the preset, not the
  Designer draft, not the state (`preset_id` and `scene_id` stay).
- The block that changes is on the guitar lane (the bass lane for a bass capture), in the chain the current scene
  plays (pre, the branch it does not mute, post):
  - a head swaps the first amp block (`amp-nam`); with no cab after it, the screen says you hear the head alone;
  - a head + cab swaps it as `amp`, and the chain's cabs are switched off (one cab, not two);
  - a cab replaces the first cab, or lands after the amp (the screen says so when that amp already has its cab);
  - a pedal replaces the first `pedal-nam`, or goes in front of the amp;
  - outboard is `comp-nam` (compressors, by name) or `preamp-nam`: the first of that type, or at the head of the
    chain (comp) / in front of the amp (preamp).
- The touched block is forced **on** in the current scene (and its lane state): a pedal off in scene A is heard.
- `POST /api/library/audition/stop` recalls the current preset. The other id forces a rebuild, never a scene switch
  on the audition's rig. Leaving the detail view stops it. Any other recall (foot, screen) replaces the audition
  too, and `GET /api/library/audition` then reports it off.
- Refused, with a sentence for the musician: no patch loaded, no guitar lane, a locked mode, a take recording.

Each touch compiles and rebuilds the rig: about a second, like an audition from the Designer.

## 6. Outboard in the Designer's pedal view

The rack stays in the Library. On the pedalboard floor (Designer, pedal mode), a `preamp-nam` or `comp-nam` block is
drawn as an **API 500-series-style vertical module** at a pedal's footprint (`GolemPedals.namModule`, golem-fx
63bf60c, the maintainer's choice on 2026-11-14). Its narrow column shows the capture's setting first (gain, hard,
channel, ratio), read from the block's label like the rack unit. `app/golem-visuals.js` passes the block's label,
which golem-fx's `fromGolem` does not carry.

## 7. What golem can play

> **Status: CODED** (lot A, 2026-11-14). The trigger: "+ Add outboard" installed the Roland RE-301. TONE3000 files
> its 13 echo and reverb impulse responses under "outboard", like the NAM preamps. The modal did not show the
> format, and the install checked nothing.

One rule, `bridge/playable.py`, crosses a capture's **nature** (TONE3000 `gear`) with its **format** (`nam`, a neural
model; `ir`, an impulse response) and names the block that plays it:

| | nam | ir |
|---|---|---|
| amp | `amp-nam` | `cab` |
| amp-cab | `amp` | `cab` |
| cab | — | `cab` |
| pedal | `pedal-nam` | `cab` (lot B: by the IR's length) |
| outboard | `preamp-nam` / `comp-nam` | none yet (lot B: `ir-fx`) |

It is applied everywhere a capture comes in or shows:
- **Search** (`/api/t3k/search`): each result carries its `format`, its count (captures or files) and its verdict
  (`playable`, `why`). A search filtered on natures only asks TONE3000 for the formats golem can install there
  (`format=nam` for Outboard).
- **The modal** shows "NAM · 12 captures" or "IR · 13 files". A pack golem cannot play stays visible, greyed, with
  its sentence, and "Add to golem" is disabled.
- **The install** refuses it, with the same sentence, before any download.
- **The catalogue** (`/api/catalog`) marks an installed pack golem cannot play (`playable: false`, `why`): packs that
  came another way (golem.fm, a backup, an install from before the rule). Such a pack leaves Cabs and shows in its tab
  as "not playable yet", with Delete.

Not every IR filed as "pedal" is a cab simulator: TONE3000 also has reverb pedals (Boss RV-6) as IRs. Lot B decides
by the IR's measured length.

## 8. The IR effect block (lot B)

> **Status: CODED** (2026-11-14), catalogue v46. The maintainer chose to make outboard IRs playable (springs,
> echoes). Measured on the isolated REAPER bench (`tools/check-rig-materialize.py --render`, the same amp with and
> without the RE-301's "delay 1", wet −3 dB): the render is 4.6 dB louder and its tail 3.4 times longer, so the
> convolver loads and plays the whole IR. Not yet heard by the maintainer; golem-fx's IR drawings are pending.

A block `ir-fx` plays an impulse response **whole**: no echo cut, stereo. It covers the outboard IR packs (on
TONE3000: mostly spring reverbs, a few echoes such as the RE-301) and the long IRs filed as "pedal" (reverb pedals).

- **Plugin.** The same convolver as the Cab block, golem's zeroconvolv build, in its stereo variant
  (`x42 - IR Convolver Stereo`, `zeroconvolv#CfgStereo`). It runs under REAPER (Linux) and in the Golem Engine. Its
  controls: Dry and Wet levels (dB); Dry stays at unity (an insert), Wet defaults to −6 dB. Like the Cab block it
  keeps the convolver's default `buffered` mode. Windows and macOS mark the block unsupported until a stereo convolver
  is mapped there, and `playable` then refuses its packs on those machines.
- **Files.** `rig.CAPTURE_TYPES` and `CAPTURE_EXT` gain `ir-fx` (.wav), as do the other lists of capture blocks
  (patches, export, factory, golem.fm jobs). The compile's IR guard (`compile_rig._ir_guard`, which cuts a cab IR
  before a late impulse) does **not** run on it: `rig._prep_block` asks the resolver for the whole file
  (`whole=True`), cached under its own name.
- **REAPER.** A cab is baked into the track's core chain (`templates/cab-x42.RfxChain`). `ir-fx` sits anywhere in a
  chain, so it is added by name. Its IR is then written into the LV2 state (`P …zeroconvolv#ir <path> 3`, the format
  the cab template proves). `golem_rig.lua` inserts that line today for a NAM model only, so the IR case is added.
  The no-bypass rule of convolvers applies (it switches through its `Enable` port). No guessed "file" key is tried
  first: one that answered true without loading would leave the convolver empty.
  Checked with `tests/test_rig_lua.py`, then `tools/check-rig-materialize.py` (its own REAPER, nothing on the rack).
- **Golem Engine.** One table entry (`CfgStereo`, file property `#ir`), as for the cab.
- **What plays it.** `playable` gains `(outboard, ir) → ir-fx`. For `(pedal, ir)`, the IR's **measured length**
  decides at install (`ir_kind_of`: energy above −60 dB under the peak past 250 ms): a short IR is a cab simulator
  (Cab block), a long one is an effect (`ir-fx`). The catalogue entry records it (`ir_kind`). `/api/catalog` gives each
  pack the blocks that play it (`plays`), and the Designer's capture picker filters on it: a NAM preamp is never
  offered to `ir-fx`, nor an echo IR to a preamp. The audition routes by the same rule (a short pedal IR goes to the
  Cab block).
- **Library.** An IR unit takes its place in the rack. Its files become **programs**, grouped by name without their
  number (`irPrograms`: Delay 1–10, Reverb 1–3), in a grid. Touching one plays it: the audition puts `ir-fx` at the
  end of the lane's chain (or replaces the one already there). The drawing asks golem-fx for its IR variant
  (`format: 'ir'`, `program`); until golem-fx draws it, the generic unit shows.
- **Designer.** The model picker of `ir-fx` lists the IR packs whose block is `ir-fx`.
- **Limits, said in the block's note.** A static IR gives an echo's repeats as recorded: no feedback control, no tape
  wow. A spring reverb, on the other hand, is what an IR renders well.
- **Its levels are written at every build** (`defaults: compile`). The convolver's own defaults are dry −60 dB and
  wet 0 dB: an audition, which places the block without settings, cut the guitar behind the IR (2026-11-14).

## 9. Hearing without playing: the demo phrase

> **Status: CODED** (2026-11-14). The maintainer, on the RE-301: "I don't have to sing or play guitar to hear the
> sound, right?" Touching a capture put it in the patch, but with nothing on the input nothing could be heard, and
> the screen did not say so.

- **The note says it.** While an audition plays: "Play your guitar to hear it with yours: it is in your patch now.
  Nothing is saved." Before a touch: "Tap a capture to hear it: a guitar phrase plays through your patch with it."
- **A reference phrase plays through it.** After the audition's rebuild (3 s to settle), the reference guitar DI
  (`library/di-refs`, chosen by the patch's tags like its demo) is rendered **offline** through the audition's lane,
  by the same clone as the patch demos (`preview.audition_demo`, `golem_preview` `op: render`, `tree`): no hardware
  output, nothing sounds in REAPER, the live rig is not touched. The page plays the clip (`Audio`), with Replay and
  Stop. Measured on the rig: about 11 s from the touch to the clip (RE-301 Delay 1, Modern Metal).
- **Cached.** One clip per (sound of the audition, input, DI): `library/previews/audition/<key>.opus`, the 24 most
  recent kept. Touching the same capture in the same patch again plays at once.
- **Status.** `GET /api/library/audition` carries `demo: {phase: idle|render|ready|error, clip, ref, error}`. A demo
  that cannot render says why (no input of this card for the lane, no reference DI, another demo rendering, a silent
  render) and the audition still plays for the guitar. The factory demo batch running: no demo phrase.
- **Not done.** Bass and voice reference DIs are not recorded: a bass capture on a bass lane has no phrase.
  A render during someone's playing has not been tried for xruns (same open point as the demos, §7 of
  [preset-preview.md](preset-preview.md)).
