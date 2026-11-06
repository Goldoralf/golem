# /live — the Rehearsal and Concert pages, and their widgets

> **Status: CODED** — the three /live views (Pedalboard, Rehearsal, Concert), their widgets, and the rehearsal
> gestures of the arrangement engine (start from a section, cue, loop). Not yet proven on a rig with stems: the
> items of §8 still have to be measured there.

Related: [`arrangement.md`](arrangement.md) (the engine and its four rules) · [`modes.md`](modes.md)
(`ui.live`, `ui.locked`) · [`bars-format.md`](bars-format.md) (real bar times) ·
[`standards.md`](standards.md) (the Standard block, source of the `chords` widget).

Code: `app/live-pages.js` (the two pages), `app/live-tools.js` (view menu), `app/live-customize.js`
(widget panel), `app/live-widgets-model.mjs` (pure model, mirror of `bridge/modes.py`),
`bridge/live_widgets.py` (lyrics), `bridge/arrangement.py` (gestures).

## 1. The three views

| View | id (`mode.ui.live`) | Purpose |
|---|---|---|
| **Pedalboard** | `pedalboard` | the mirror of the foot controller |
| **Rehearsal** | `rehearsal` | pick a section, start from it, loop it |
| **Concert** | `timeline` | readable from two metres; the foot plays |

The id `timeline` stays the Concert's id: it is the word already stored in modes and edited by
golem.fm (`mode-set` job). Labels come from `PAGE_LABEL`.

Factory defaults (`config/modes/*.json`): Rehearsal → Rehearsal page; Gig and Accompaniment → Concert;
Studio and Pedalboard → Pedalboard. A mode with no or an unknown view falls back to Pedalboard
(`modes.live_view`). While a song runs, the arrangement's `live_view` can also bring the Concert page
forward ([`arrangement.md`](arrangement.md) §12).

## 2. Choosing a view

- **The mode gives the default** (Settings ▸ Mode ▸ Live screen, three choices; `POST /api/mode/update
  {live_view}`).
- **The view button** at the head of the /live toolbar opens a small menu: Pedalboard · Rehearsal ·
  Concert, then "Customize this page…". The choice applies to **this screen, for the time of the mode**:
  it is kept in `sessionStorage` (`golem.liveView`) keyed by mode id + mode view, so it never rewrites
  the mode (safe in a locked mode) and the next mode change returns to that mode's view. The button shows
  the active page's icon; the mode's view carries a `mode default` badge.

## 3. The Rehearsal page

- **Sections as cards**, fixed height (150 px) whether or not the song has lyrics. A card: number, name,
  bars, scene letter and colour, first lyric line if any.
  - **5 sections or fewer**: no arrows, the cards fill the width.
  - **More than 5**: ‹ › move **by 4** (one card stays visible between pages), greyed at the ends; a swipe
    also pages (beyond 40 px when |dx| > 1.5·|dy|), then the row snaps to a card. The row follows the
    playing card, except for 5 s after a gesture.
  - **A swipe is never a tap**: a tap is cancelled beyond 10 px of movement, and only counts if it began
    on the card.
- **A tap queues a section, never starts it** (in rehearsal people touch the screen while talking). The
  card gets a full band at the top: `START` when stopped (the first section by default), `NEXT` while
  playing, `COUNT-IN` during the count-in. Tapping the card again cancels.
- **Stopped**: the big button says where it starts from, `▶ FROM <SECTION>`, with the bar and the
  count-in length under it.
- **Count-in**: the NOW zone shows `COUNT-IN · then <section>` with large beat dots; tapping a card
  during the count-in changes the start section.
- **Playing**: a queued card starts **at the end of the current section** (quantised on the boundary).
  NOW says `then ▸ <section> (cued) in N bars` in the accent colour; the card pulses on the beat over the
  last two bars; at the jump a 150 ms flash marks the new card and NOW.
- **⟲ LOOP** on the playing card (at least 44×44, bottom right) loops the section: `⟲ LOOP`, then `×2`,
  `×3`… Queuing another card during a loop leaves at the end of the lap, towards it.
- **Transport**: `❚❚ PAUSE` (stop; start again from the section that was playing) and `■ STOP` (stop;
  back to the section the run started from). STOP is greyed when stopped.
- **End of song**: NOW shows `END — <title>` and the button offers to start again.
- **A song without an arrangement**: no cards, a single panel `No arrangement — plays from the top` and
  `▶ PLAY` across the width (or `Nothing to run on this song` without a backing).

## 4. The Concert page

- A **setlist strip** at the top: previous song, current song with elapsed / total, next song.
- **The current section very large** (84 px) in its colour, the bar within the section and its beats;
  `next ▸ <section> in N bars` at 28 px, in the accent colour at 4 bars or fewer.
- A thin **song map** (sections to scale, a play head), read-only: not a target.
- **Transport** in a 64 px bottom strip: `▶ PLAY`, `▶▶ NEXT` (only with `advance: foot`) and `■ STOP`.
  **No pause in concert**, and **STOP needs a 0.6 s hold** (a ring fills, `Hold to stop`): an accidental
  tap never stops the song.
- **End of song**: `END — <title>`, then `Next song ▸ <title>` (or "last song of the set").

## 5. Widgets

Fixed **slots**, never free stacking, never scrolling, no drag and drop on stage. The NOW zone
(section + bar) is fixed and cannot be removed. At most four widgets per page.

| Page | Slots |
|---|---|
| Rehearsal | `right` (M, right of NOW) · `bottom` (L, under NOW) |
| Concert | `top1`, `top2` (S, top left of the big NOW) · `bottom` (L) |

| id | Widget | Sizes | Source |
|---|---|---|---|
| `lyrics` | current line and next (30 px in Concert) | L | `lyrics/song.lrc` of the song's `.golem`, timed on song time (`GET /api/live/lyrics`, `live_widgets.lyrics`) |
| `song_time` | elapsed / total | M | the arrangement (`song_t0`, `song_len`) |
| `set_clock` | `SET +2:10 LATE` (amber) / `SET −0:45 EARLY` (green) | S | planned durations of the setlist lines (`setLate`, `lineSeconds`) |
| `chords` | chords, current bar lit — **only while the grid plays** | M, L | the grid of a **Standard** block |
| `notes` | the song's stage note ("capo 2") | S, M | `note` of the setlist line |
| `instruments` | who plays in this scene | S, M | the preset |

- S widgets are at least 22 px bold (readable at 2 m).
- **A widget without data disappears** and gives its space back to the page (NOW widens). Nothing
  replaces it, not even "No data".
- Choices are kept **per mode**: `mode.ui.widgets = {rehearsal: {right, bottom}, timeline: {top1, top2,
  bottom}}`, written by `POST /api/mode/update {widgets}`. A widget that does not fit a slot's size is
  refused there and falls back to the default (`modes.WIDGET_SLOTS`, `WIDGET_SIZES`, `WIDGET_DEFAULTS`,
  mirrored in `live-widgets-model.mjs`). `null` = empty slot. Factory defaults: Rehearsal = `chords`
  right, `lyrics` bottom; Concert = `notes`, `set_clock`, `lyrics`.
- **Customize this page…** opens a panel shaped like the Mixer, editing **only the open page**:
  "saved for the <mode> mode", a miniature with its slots (at least 44 px high), the first selected;
  tap a slot, then a widget (those that do not fit are hidden), `Empty` frees the slot, `Done`. Disabled
  on Pedalboard and when the mode locks the screen (`ui.locked`).
- **Chords** are shown only from a Standard block's grid. A recorded song's chart (`chart/song.gsx` of a
  `.golem`) is not displayed on the rack.

## 6. The engine — rehearsal gestures (`bridge/arrangement.py`)

Three gestures extend `start / stop / next / load` of `POST /api/arrangement`
([`arrangement.md`](arrangement.md) §7). The audio jump is done **in REAPER** by `golem_backing.lua`; the
engine only knows song time and drives it through `backing_ctl(op, …)` (`app._arr_backing_ctl` →
`backing.py` `seek`, `pause`, `jump`, `loop`, `loop_off`).

### 6.1 Start from a section — `{op: "start", from: k}`

- Song time starts at `at[k]`; earlier sections are skipped. **A sample whose marker falls before
  `at[k]` does not fire** (started midway it would be a cut attack and a click); later ones fire on time.
- **Count-in** = max(the song's `count_in`, 1 bar, **2 bars if a bar lasts under 2 s**), with the real
  bar length of section `k` (`countInBars` on screen). The click sounds during the count-in; after it, the
  song's Click tick decides.
- **With a backing**: a playing backing is paused, then **positioned at `at[k]` before the count-in**
  (seek while stopped, with its unmute sent alongside), and started at the first beat
  (`play_from_cursor`) — never "start from 0 then jump", which would let the intro be heard. No fade:
  the start falls on a downbeat. Times come from the bar map when there is one.

### 6.2 Cue — `{op: "cue", index: k | null}`

- Quantised on the **end of the current section**. **Locked one beat before the boundary**: a cue or a
  cancel arriving later is refused ("too late — the jump is already armed", `locked: true`).
- **At the boundary the engine applies section `k` itself** (scene, cues) and moves its origin. For
  `JUMP_QUIET_S` (0.35 s) it **ignores** the published transport, which is only written every quarter
  second: following it would play the next section's scene 0.3–0.5 s before the jump. After that, if
  the transport contradicts the engine (a missed jump, beyond `FORWARD_S`), the engine follows the
  transport. If REAPER publishes the jump before the engine reaches its own boundary, the engine
  recognises it as its jump (one jump, never two).
- **Without a backing**: nothing moves in the sound; song time is renamed.
- **With a backing** (`op: jump {at, to}` in `golem_backing.lua`):
  - **backwards or in place**: a native loop `[at[k], end of section]`, armed as soon as the cue is set,
    jumps **at the sample**; the Lua lifts the loop at the first wrap it sees;
  - **forwards**: the Lua seeks when the transport reaches the boundary (decided on
    `GetPlayPosition2` with a 35 ms margin; armed too late = immediate seek). A clean cut of the stems
    with `defer` jitter (~30 ms): acceptable in rehearsal only.
  - A seek inside the section lifts an armed jump in the Lua; the engine re-arms it.
- Samples at the start of the target section are **pre-armed** (no flam after the jump).
- `golem_click` re-aligns on **every transport discontinuity** (more than 20 ms off the expected
  position), not only at start. The drum machine (`golem_drumseq`) keeps its own pulse: it holds on a bar
  boundary, but its pattern does not restart. After a jump the target section's groove is sent at the boundary
  (`_drums_at`), so it changes one bar late; a regular boundary is sent ahead and lands on time (arrangement.md §6).
- In `foot` mode a cue is taken at the next tap; it is refused when the song advances at the foot and
  has a backing ("its backing track cannot jump").

### 6.3 Loop — `{op: "loop", on: bool}`

- Loops the current section: with a backing, a native loop `[start, end]` at the sample; without, song
  time returns to the section start at each lap. Refused in `foot` mode and one beat before the boundary.
- **Each lap reapplies the scene only if it changed** (`_lap` in `app._arr_cue_core`): recalling the
  same scene toggles blocks for nothing. Reverb and delay tails ring on.
- The section's samples restart each lap **without `ring`** (restarted over themselves they would comb,
  +6 dB); `ring` comes back at the next normal boundary.
- Looping cancels a cue, and a cue during a loop leaves at the end of the lap: the last gesture wins.

### 6.3 bis Refusals and resets

- **Refused while recording with a backing**: `from > 0`, `cue`, `loop` (a seek would move the record
  head, a native loop would make REAPER record in a loop). `from > 0` is also refused when the song
  records ("starting from a section does not record — untick “Record with the song”").
- **Refused when the mode locks the screen** (`ui.locked`, e.g. Gig): 403 "rehearsal gestures are off
  in this mode".
- **Reset** at every stop, load, preset change and mode change (`clear_practice`), and on any unplanned
  transport discontinuity (seek, double-tap restart): a forgotten loop would spin the backing, a
  forgotten cue would carry into the next song. Every stop sends `loop_off`. Any take that starts lifts
  loop and cue.

### 6.4 Published state

`snapshot()` adds `cue` (index or null), `loop` (bool), `loops` (laps done), `from` (start section),
`song_len` (seconds) and `song_t0` (origin of song time on the server clock: position = now − `song_t0`).

## 7. Not built

- **Tempo −5 %** (practice slowly): backing, click, drum machine and arrangement clock would have to slow
  together (REAPER playrate, pitch preserved; `_song_time`, sample `in_ms`, click and drum BPM). Rehearsal
  only, set while stopped.
- Stage notes **per section** (per song only today).
- The count-in follows the configured click meter, not the start section's meter (see
  [`arrangement.md`](arrangement.md) §14).
- Scene colours come from the preset: factory presets give all their scenes the same colour, and the page
  shows it as is.

## 8. To measure on a rig with stems

1. Start from a section with stems: the intro is not heard; count-in end → first backing beat within
   15 ms.
2. Section loop with stems: wrap without a click, the scene does not flash, ×N correct; loop of the last
   section.
3. Backward and forward jumps at the boundary: no foreign section heard (> 35 ms); the internal click
   stays on the beat.
4. REAPER's playback pre-roll is off.
5. Stop during a loop: nothing left armed in REAPER (`loop.on` false in `.backing.json`).
