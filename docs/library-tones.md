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
