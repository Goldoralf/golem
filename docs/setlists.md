# Setlists and the foot list

> **Status: CODED** — ordered lists of songs (setlists) or sounds (sound lists), the list on the foot, lines,
> per-song overrides, snapshots and the two-way merge with golem.fm (`bridge/setlists.py`,
> `bridge/routes_content.py`, `bridge/golemfm.py`).

Related: [songs.md](songs.md) (the song object a line points to), [arrangement.md](arrangement.md) (the
arrangement block), [patches.md](patches.md) §5–6 (patches on the foot, sound lists),
[pedalboards.md](pedalboards.md) (the foot controller), [golemfm-protocol.md](golemfm-protocol.md).

## 1. Vocabulary

- **A list** = lines in order. It has a `kind`, fixed at creation (`setlists.KINDS`):
  - **setlist** (`kind: "songs"`, ▤) — each line plays a song or a preset;
  - **sound list** (`kind: "sounds"`, ⛓) — each line plays a patch (`{id, rev, patch, title}`).
  A list never mixes the two; adding the wrong kind raises a `ValueError` ("this is a sound list — songs go
  into a setlist of songs", and the reverse).
- **The foot list** = the one list the foot controller plays. **Bank #n = line n of the foot list**, nothing
  else. The foot knows only this list.
- **A bank** = a *position* on the foot controller. It is not a list of sounds. (Instrument "banks" — DX7
  bank, pad banks — are another domain.)
- **Who plays: the last gesture.** A patch opened from the screen holds until the foot changes bank: the PC
  the foot controller sends with each scene is the bank it was already on (`recall.do_recall_slot`). Changing
  bank on the foot is a real song choice.

## 2. Storage

| File | Content |
|---|---|
| `setlists/<id>.json` | one list (machine state, never committed) |
| `config/setlist.json` | `{"active": "<id>"}` — **the foot list** |
| `setlists/snapshots/<stamp>-<id>.json` | read-only snapshots (§7) |
| `setlists/.pending/<id>.json` | golem.fm pushes deferred while a mode is locked (§8.3) |

Factory lists (for example `factory`, the default `foot_list` of the factory modes) are seeded by
`bridge/factory.py` ([factory.md](factory.md)).

**The active list is not a field of the lists** (two files could contradict each other): it lives once in
`config/setlist.json`, and a plain recall never rewrites it. Only three things change it:
`POST /api/setlists/{sid}/activate`, entering a mode that declares a `foot_list`
([modes.md](modes.md) §4), and the "On the foot" gestures of the app.

`setlists.active_id()` resolves the foot list: the configured id if its file exists, else the historical id
**`fcb-banks`** (`DEFAULT_ID`) if `setlists/fcb-banks.json` exists, else the first list file alphabetically,
else `fcb-banks`. The foot must always have a source. `fcb-banks` is otherwise an ordinary setlist (displayed
"Repertoire" — `load()` renames the legacy names "FCB Banks"/"fcb-banks" once, idempotently); its id is kept
because backups, imports and `preset_export` know it. `list_all()` still flags it `default: true`; the UI shows
no "default" badge.

### 2.1 List fields

| Field | Meaning |
|---|---|
| `id` | file slug (`_slug(name)`, unique) |
| `name` | displayed name |
| `kind` | `songs` (default, also for every legacy list) \| `sounds` |
| `rev` | list revision: bumped by any change of **name or order** (§8) |
| `lines` | **the truth**: ordered lines (§3) |
| `presets` | **derived** from `lines` on every save (`pid_of` per line, `""` = free bank) — for older readers |
| `origin` | `local` \| `golem.fm` |
| `fcb` / `fcb_wanted` | a *wish* to be the foot list; never switches it by itself (§8.3) |
| `scopes` | pending write scopes for the next mirror push (§5) |
| `created_at`, `updated_at` | timestamps (information only — merging uses `rev`) |

A legacy list `{presets: [ids]}` is still read: `normalize()` turns each entry into a line
`{id: "r:<sid>:<n>", rev: 1, preset: <id>}`.

### 2.2 Capacity: 19 banks

`setlists.MAX_SLOTS = 19` (and `app.FCB_PHYS_BANKS` derives from it): a setlist is one gig and must fit on the
foot controller's directly reachable banks (00–18). The bridge **refuses** (409, `over_cap()`) instead of
truncating — truncation would lose a preset silently. A **hole** is a real bank: an empty bank is a silent
no-op on the foot and never changes the current preset.

## 3. Lines

There is no song catalogue inside a list: **a line is one performance slot**. It points either to a song of
the repertoire (`band_song`), or carries its own fields (a "free" line), or plays a patch (sound list). Several
lines may play the same preset; a preset never knows which songs it serves.

`setlists.LINE_FIELDS`:

| Field | Written by | Value |
|---|---|---|
| `id` | the origin | `w:<setlist>:<n>` from golem.fm, `r:<setlist>:<uuid8>` on the rack. Opaque, **stable across reordering** — it is what makes merging possible |
| `rev` | whoever writes the line | integer ≥ 1, +1 on every write |
| `preset` | | the rack preset id. `null` = a line **without a rig** (kept: a cappella, guest, song not built yet) |
| `title` | | text ≤ 120 shown on stage; absent = the song title, else the preset name |
| `song_slug` | golem.fm | catalogue slug (same namespace as `take.song.slug`). **Not a song identity** |
| `bpm` | | integer 20–400; omitted when none (never 0, never the preset's copied) |
| `backing` | | slug of a backing-catalogue song; replaces the preset's backing when the line is played |
| `arrangement` | | an arrangement block `{type: "arrangement", id, params}` ([arrangement.md](arrangement.md)) |
| `blocks` | | per-song block overrides (§4.2) |
| `tuning`, `capo`, `note` | | opaque prep info read by the phones' "Between songs" page: text ≤ 24, integer 1–12, text ≤ 140 |
| `band_song` | | id of the song played (`bs:`/`rs:`/`us:`/`ct:` — [songs.md](songs.md) §3). Opaque |
| `line_overrides` | | the sheet keys **this line** overrides; the rest comes from the song |
| `song_setlists` | golem.fm | how many setlists play this song (information, §8.2) |
| `patch` | | sound lists only: the patch id |

`_clean_line()` validates every line (unknown keys dropped, bounds applied). It is also the validator of song
sheets (`songs.clean_sheet`), so a line and a sheet stay byte-comparable.

**One function returns the preset of a line: `setlists.pid_of(line)`**, used by every consumer (foot, Live,
bank picker, snapshots, take cutting, Designer). A patch line returns `"patch:<id>"`; a line with `band_song`
returns the preset of the song's resolved sheet; otherwise `line.preset`.

`setlists.view_line()` / `view()` are what screens read: a song line shows what it **plays** (resolved sheet,
song title if the line has none, `song: {id, title, artist, kind, born, band}`). Views are never written back.

## 4. What a line overrides when it is played

### 4.1 The played preset: `recall.effective_preset(p)`

When a preset is recalled **through a line** (foot bank, line tapped on the tablet, ▶ Play of a song), the
preset is recomposed — nothing is written into the preset file:

- the played sheet is `songs.line_sheet(line)`: the song's sheet, overridden **only** by the keys listed in
  `line_overrides`; a free line uses its own fields; a song missing from the rack lets the line play what it
  carries;
- `arrangement` of the sheet → `config.arr` (merged with the preset's own Arrangement block, which carries the
  pedal and the advance rule — `recall.merge_arrangement`). **Outside a line, no automation**;
- `bpm` of the sheet → the preset tempo (and the command's `bpm`, preferred by `golem_rig`);
- `backing` → `{songs: [{slug}]}`;
- `blocks` → per-block overrides (§4.2).

Recalling a preset directly (Designer, presets page) plays the preset's own tempo and backing. Screens show the
**effective** tempo and its source. A line edit takes effect at the next recall of the line.

### 4.2 Per-song blocks

The preset carries the **capability** (the rig has a sampler on switch 8, a click on 6…); the line carries the
**use** for this song. Composition is **line > preset > global**.

`blocks: {"<block id of the preset>": {"bypass"?: bool, "params"?: {…}}}` overrides the preset's `config.gen`
and `config.rec` blocks **by id** (params merged, bypass replaced). What a song may set:

- `sample` → `params.samples`;
- `click` → `bypass` and `params.beats` / `params.den` (time signature, also used by `recall.song_click()`);
- `backing-track` → through the line's `backing` field.

`rec`, `looper`, `drums`, `standard`: nothing per song. A block id the rig no longer has is ignored and
reported; a block absent from the rig is never invented from the line. The line detail shows a read-only
"Song blocks" strip: lit + dot = set for this song, lit = in the preset, dashed = not in this preset. The list
is derived from `CONFIG_GEN_TYPES` + `click`.

## 5. Write scope: song or line

When a line that plays a song is edited on the rack, the write goes either to the **song** (every setlist
follows) or to **this line only** ("tonight only"). `POST /api/setlists/{sid}/line {id, …, scope}`:

- `scope` applies to the whole body of that write; it is **never stored on the line**.
- Default when absent: `setlists.default_scope()` → **`line` when the mode's `take_kind` is `gig`**, `song`
  everywhere else. It reads a field, never a mode id. `GET /api/setlists/scope` returns
  `{scope, mode, mode_name, locked}` so the drawer can display "saves into the song" / "tonight only" without
  asking the player; a tap switches it. **No rack screen does this today**: a song line is read in the setlist
  and edited in its song ([songs.md](songs.md) §7), so rack edits go to the song; line exceptions come from golem.fm.
- Only sheet fields are scoped (`SCOPED_FIELDS` = `preset, bpm, tuning, capo, note, backing, arrangement,
  blocks`). `title` stays a line exception and never renames the song; `song_slug` is changed on the song.
- In `update_line()`: scope `song` writes the fields into the song (`songs.update`) and removes them from the
  line's `line_overrides`; scope `line` stores them on the line and adds them to `line_overrides` (an empty
  value gives the field back to the song).
- For the mirror (§8.1), pending instructions are stored **per field** on the list:
  `scopes: {line_id: {field: "song" | "line"}}`. They are cleared field by field once golem.fm accepts the
  push (a write that happened during the push keeps its own); a failed push keeps them. `scopes` is always
  sent, even empty — its presence says this rack can declare a scope. Incoming `scopes` are discarded.

## 6. Gestures and endpoints

| Route | Effect |
|---|---|
| `GET /api/setlists` | `{active, setlists (views, factory-marked, with count/missing/active), snapshots}` |
| `POST /api/setlists {name, kind?, presets?, from_banks?}` | create, **named at creation**; `from_banks` copies the foot list; 409 over 19 |
| `POST /api/setlists/{sid}/activate` | make it the foot list (the only list gesture with an effect on the foot) |
| `POST /api/setlists/{sid}/duplicate {name?}`, `/rename {name}`, `DELETE /api/setlists/{sid}` | the active list cannot be deleted; deleting a list never deletes presets |
| `POST /api/setlists/{sid}/presets {presets: [ids]}` | reorder by preset ids (`set_presets`): lines follow their preset, `""` keeps a rig-less line, a new id creates a line |
| `POST /api/setlists/{sid}/line {id?, title?, bpm?, preset?, song_slug?, backing?, arrangement?, blocks?, tuning?, capo?, note?, scope?}` | edit a line (rev +1); without `id`, append a line |
| `DELETE /api/setlists/{sid}/line/{line_id}[?keep_slot=1]` | "Remove from setlist" (never the preset); `keep_slot` empties the bank without shifting the next ones |
| `POST /api/setlists/{sid}/songs {ids}` | "Add a song" from the repertoire: lines `{id, rev, band_song}`; unknown or duplicate songs are returned in `skipped` |
| `POST /api/setlists/{sid}/line/{line_id}/to-song {kind, band?}` | "◆ Make it a song": a free line becomes a song; the line keeps only `band_song` |
| `POST /api/setlists/{sid}/place-song {song, slot}` | put a **song** in a bank in one write (its old row and preset-only rows of the same preset become empty; the target bank is replaced) |
| `POST /api/setlists/{sid}/swap {from, to}` | swap two banks (drag and drop) |
| `POST /api/setlists/{sid}/patches {ids}` | append patches to a sound list |
| `POST /api/setlists/{sid}/snapshot {name?}`, `POST /api/snapshots/{snid}/restore {name?, overwrite?}` | §7 |
| `POST /api/setlists/{sid}/mirror` | push the list to golem.fm now (§8.1) |
| `POST /api/setlists/{sid}/push` | push the **bundle** (list + its presets) through the backups channel, reporting what is missing (`backup.build_setlist`) |
| `GET/POST /api/foot-list` (alias `/api/fcb-banks`) | the foot list: `{id, name, kind, capacity, presets, banks[{slot, preset, name, missing, free, scenes}], lines, rev}`; POST `{presets}` reorders it |
| `POST /api/setlist` | legacy raw write of a list file |

Songs and lists: adding a song read from a song folder copies it onto the golem first
([song-folders.md](song-folders.md)).

Invariants:

- A line may point to a preset **absent from disk** (list received before its presets): it is shown as a
  **free** slot, never by its id, and `list_all()` reports it in `missing`.
- **Deleting a preset** (explicit gesture) frees its lines in every list (`forget_preset`: `preset = null`),
  never removes them — removing would shift the following banks under the feet. Deleting a patch does the same
  in sound lists (`forget_patch`).
- Every rack write to a list triggers the mirror push (§8.1).

**UI.** Songs ▸ **Banks & Setlists** (cards, then an open list: songs on the left in bank order, line detail
on the right — title, tempo, "Song blocks", arrangement, "Get ready" for tuning/capo/note). Songs ▸ Presets
offers only setlists, Songs ▸ Patches only sound lists; their `#NN` badges and bank picker write into the
**viewed** list. **Viewing is not playing**: the viewed list is remembered per device (`localStorage`); the
foot list is marked ● and changed with "On the foot" (two taps) or from `/live` (a **tap** on the list name in the
top bar opens "What the pedalboard plays"; a list is confirmed in two taps, then its first playable line is loaded). A **tap on the line's title** (the song bar under the top bar,
`app/live-bankbar.js` `LivePicker`) lists the lines of that foot list — its songs, or its sounds for a bank — in bank
order; a tap loads **the line** (`POST /api/recall {slot}`: song, tempo, stems, arrangement), like ◀ ▶ and the foot.
Before 2026-10-22 it listed every preset of the golem and loaded a bare preset. `/live` shows `SETLIST #NN` or `BANK #NN`.

**What plays is not in the foot list (CODED 2026-10-24).** A preset or patch opened from the Designer or Songs plays
even when the foot list does not hold it. `/live` then shows `PRESET`, `PATCH` or `DRAFT` with no number and no ◀ ▶
(2026-10-17: the arrows would jump to sounds of a list that does not contain it). A Windows tester read the missing
arrows as a bug. The bar now **says why and gives the gesture**, in the place of the next sound (empty in that
state): `not in « <foot list> » — tap to change`. A tap opens "What the pedalboard plays", like the list name in the
top bar.

## 7. Snapshots

A list is **references**: restoring a list restores the order, not the sounds. A **snapshot** is the separate,
explicit gesture that freezes sounds: `snapshot()` writes the list kind, its full `lines` (title, bpm,
arrangement, backing…) and the **content** of each referenced sound — a preset as a preset, a `patch:<id>` line as
its patch document (`_frozen_item`) — read-only, and lists what could not be frozen (`missing`).

`restore(snid, as_name, overwrite=False)` puts the sounds back (patches as patches, never as a `patch…` preset) and
creates a new list `<name> (restored)` with the saved kind and lines (new line ids). A sound with the same id whose
content **changed since the snapshot** is a conflict: without `overwrite` nothing is written and the call returns
`{ok: false, conflicts: [ids], error}` (HTTP 400); the Songs ▸ Setlists screen shows "overwrite N changed?" and a
second tap re-posts with `overwrite: true`. Unchanged sounds are not conflicts. Old snapshots that froze a patch as a
composed preset report it in `skipped`.

## 8. Exchange with golem.fm

### 8.1 Two directions

- **golem.fm → rack**: job `setlist-push` with `{setlist: {…}}` (`tones_jobs._setlist_push` →
  `setlists.receive_push`).
- **rack → golem.fm**: `golemfm.push_setlist(sid)` sends `POST /api/ext/golem/setlists {setlist}` after every
  rack write, debounced (5 s), never on a schedule; always `complete: true` (the rack file **is** the list);
  `presets` (derived) is not sent. Before the list, the songs it cites are pushed (`push_songs_now`), and a song
  line without a title gets its song's title **on the wire only** (`songs.wire_titles`). Never called by the
  receiver (no echo).

### 8.2 Merge rules — `setlists.merge_push(doc)`

A push **without `lines`** but with `presets[]`, on a list that already exists (a bank picker that knows neither line
ids nor revs), is applied as the rack's own reorder: `set_presets` — each line follows its preset, new ids create
lines, the list rev is bumped. A list that does not exist yet is created as below.

Otherwise, by line `id` and `rev`, never by clock (a stage rack may live for days without NTP):

- incoming `rev` higher → incoming wins (keeping a local `band_song` of a rack-born song the other side cannot
  resolve yet — `_keep_ref`);
- equal `rev` and same body → kept; **equal `rev` and different body, or lower `rev` → the rack wins** (its
  state is what actually played) and the line is listed in `resend` so the other side converges;
- the compared body (`_line_body`) excludes `id`, `rev`, `song_setlists`; for a song line it compares only what
  the line **declares** (`band_song`, `line_overrides` and their values), not the resolved copies golem.fm adds;
  a returned "tombstone" of a rack-born song is not a divergence (`_tomb_of_ours`);
- `song_setlists` is information: the received value replaces the local one whatever the `rev`;
- `complete: true` = this is the whole list, lines absent are **deleted**; otherwise lines are only added or
  updated. A flag, never an inference;
- **name and order**: the list `rev` arbitrates. Incoming higher → its order (local-only lines after); else the
  rack keeps its order, new incoming lines go at the end, and `*order*` is queued for resend;
- a new list is created with the incoming `kind`; `fcb: true` only sets `fcb_wanted`.

Because golem.fm pushes resolved lines and the rack compares bodies, golem.fm's resolution must be
deterministic (same keys, same nulls) or the two sides loop on `resend`.

### 8.3 The foot first — what a push never does

- A push **never switches the foot list** by itself (`fcb` is a wish; outside a locked mode the list arrives
  inactive and the screen offers to put it on the foot).
- In a **locked** mode (Gig), a push that touches the **active** list or asks for the foot is written to
  `setlists/.pending/` and applied at the next mode change (`apply_pending()`, called by `POST /api/mode`).
- A line deleted by `complete` frees its position exactly like a deleted preset.

### 8.4 "Played in N setlists"

The rack holds only the lists pushed to it. `song_setlists` from golem.fm is authoritative; without it (rack-born
line), the rack counts what it holds and says "in N setlists **on this rack**" (`songs.setlists_of`).

### 8.5 Stage-ready

golem.fm reads three facts: arrangement armed, samples set, rig present on the rack. The third is published
through the preset export envelope (`deps[]`, `unresolved[]` with a reason per block —
`bridge/preset_export.py`): a preset with `unresolved` entries is not playable here, and says why.

## 9. Startup migration

`migrate_legacy_arrangements()` (once at boot, idempotent) copies an arrangement block **with sections** that a
preset still carries in `config.arr` onto each line without an arrangement that plays that preset (rev +1). The
preset is not rewritten; its old block is dead data the Designer no longer shows.
