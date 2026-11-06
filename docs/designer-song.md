# The song loaded in the Designer

> **Status: CODED** (2026-10-18) — the Designer shows **which song is loaded** and edits **its** values next to the
> preset's. A value set "for this song" is saved **in the song** (its sheet), so every setlist that plays the song
> plays it. Follows [song-backing.md](song-backing.md) (the backing belongs to the song).

Related: [songs.md](songs.md) (the sheet, §9.7 lines and `line_overrides`), [setlists.md](setlists.md) (§9.9 blocks
per song), [arrangement.md](arrangement.md), [song-backing.md](song-backing.md).

## 1. Why

A preset serves several songs and does not know them. What changes from one song to the next — the tempo, the
time signature, whether the click plays at the start, the samples, the stems, the arrangement — belongs to the
**song**. Before, the Designer listed every setlist line that overrode a block ("Per song · set in the setlist"),
twice for the same song when two setlists played it, and sent you to the setlist to change it. The Designer now
works **in the context of the loaded song**, like the backing drawer already did.

## 2. The song bar

On the second row of the Designer (lanes · ⚙ … BPM), right before the BPM field:

- **A song is loaded** (the rig state's `song` names this preset, from a setlist line or from Songs): cover,
  `♪ title · setlist #bank` (the bank only when it comes from a line), and **✕** — unload, the preset stays on its
  own (`POST /api/arrangement {op: "unselect"}`).
- **No song**: `♪ Load a song ▾`. The menu lists the songs that use this preset (computed,
  `POST /api/backing/drawer` → `used_by`), with their cover, artist and setlists, and **Load** — loads the song
  without starting it (`{op: "select", song}`). "A song picks its preset on its page (Songs)" when none does.
- **Exactly one song uses this preset → it loads by itself** (2026-10-24), when the Designer opens the preset — only
  if the rig already plays that preset (`select` never recalls it from here: no rebuild, no trial lost), once per
  preset opened, and never again after the user's **✕** while they stay on that preset. Several songs: the menu
  lets you choose, nothing loads by itself.
- The BPM field is the **preset's** tempo. The song's own tempo is set in the Click drawer, not shown next to the
  field (the pink `♪ 87` was removed, 2026-10-24).

Loading and unloading are remembered across a restart (`.live.json`, song-backing.md §6).

## 3. Values for this song — saved in the song

A value "for this song" is written into the song's **sheet** (`POST /api/song/<id>`), the fields that already
exist (songs.md, setlists.md §9.9):

| What | Sheet field |
|---|---|
| Tempo | `bpm` |
| Click: beats per bar, note value | `blocks[<click id>].params.beats`, `.den` |
| Click: plays at the start | `blocks[<click id>].bypass` |
| Samples | `blocks[<sample id>].params.samples` |
| Stems muted for this song | the song's mix (song-backing.md §4) |
| Arrangement | `arrangement` (already edited in the arrangement drawer) |

`↺ use the preset's` removes the song's value (an empty value removes the field, songs.md). A **setlist line**
that declares an exception for tonight (`line_overrides`) still wins on that line: the drawer says so ("Covers #02
plays 92 tonight") instead of hiding it.

A change plays from the next **Load** or **▶ Play** — the Designer re-arms the loaded song after each edit
(`{op: "select"}`), it never restarts what is playing.

## 4. The drawers

- **Click**: two columns, **This preset · every song** and **♪ title · this song only**. Rows: Tempo, Time signature
  ("same as the preset" + **Set for this song**), On at start. The level stays below, global, never per song (its
  slider reads the level that plays, `GET /api/click`). The preset's time
  signature is the global one (`config/click.json`, every preset).
- **Sample**: a switch **This preset · ♪ This song** above the list. On "This song", the list shown and edited is
  the song's (the preset's until the first change makes one for the song).
- **Backing Track**: unchanged (song-backing.md §6) — its own This preset / This song switch.
- **Arrangement**: the **same song card** as the Backing Track drawer (`SongCard`, designer-song.js): cover, "The song
  loaded now · its arrangement plays", artist, "16 parts · 111 bars", where it comes from, Open the song ›, ✕ Unload;
  without a song, "No song loaded — the arrangement belongs to the song" and ▶ Load. Its parts are read from the
  **song's sheet**. "Change song" (two lists of setlist lines) is gone: two lines of the same song play the same parts,
  and another song is **loaded**. The header counts **songs**, not lines.
- Without a song loaded, each drawer shows the preset only, and one line: "Set per song in: Paper Kite — load
  it to see its values", with **Load**.
- The old list "Per song · set in the setlist" is gone. With a song loaded: "Paper Kite is also in Night Shift
  #03 — the same song, the same values."

## 5. The arrangement band

The ⚙ Arrangement band shows the **loaded song's** arrangement when one is loaded (its line, else the first line
that plays the song); otherwise the first line playing this preset, as before (the band's own pick still works).

## 6. Rig side

- `recall.song_click()` reads the loaded song's Click values for a song loaded **from Songs** too (before: only
  from a setlist line — a song's time signature was ignored when it was loaded without a line).
- No new endpoint: `/api/arrangement {select | unselect}`, `/api/song/<id>`, `/api/backing/drawer`, `/api/click`.
