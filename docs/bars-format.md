# `bars.json` — the bar map of a backing

> **Status: CODED** — the format golem.fm delivers for a backing (the real time of every bar and beat on the
> stems timeline), and what the rack does with it: `bridge/bars.py`, the arrangement plan, the song click.

Related: [`arrangement.md`](arrangement.md) §4 (the clock) · [`golemfm-protocol.md`](golemfm-protocol.md)
(the route and when it is pulled) · [`golem-format.md`](golem-format.md) (`sync/bars.json` inside a `.golem`).

A band that records without a click has no single tempo. At a fixed BPM, the click drifts off the stems
and section changes land early or late. The bar map gives the **real** instant of each bar, so the rack
can:

1. start each **section** of the arrangement on its real bar: a section that begins at bar 9 starts when
   the backing transport reaches `bars[8].ms`, not after "8 bars × 60/bpm × 4";
2. play the **click** on the real beats, as a generated MIDI item that plays with the stems (it follows
   pause and rewind at the sample);
3. give the song **length** in bars (the timeline header "108/108 bars").

Doctrine: golem.fm produces, the rack validates, stores and executes. An invalid map is rejected
**whole**: never half a map. The rack then falls back to the sheet tempo.

## 1. Transport and storage

- **The rack pulls**: `GET /api/ext/songs/{slug}/bars` with the device token (`bars.fetch`). 404 = no map
  (normal); a local map that no longer exists upstream is removed. An invalid answer never overwrites a
  valid local map.
- **When**: at the end of the stem download, then whenever the catalogue (`GET /api/ext/songs`)
  announces a `bars_rev` different from the local file's `rev` (`bars.refresh_async`, called from
  `golemfm.py`). A catalogue without `bars_rev` changes nothing.
- **Where**: `assets/backing/<slug>/bars.json` (old cache), or `sync/bars.json` inside the song folder
  of a `.golem` (key = song id, `bars.path`). Everything is local: golem.fm can be off on the night.
- Subscribers (`bars.listeners`) are told when a map arrives, changes or disappears: the **loaded**
  backing is reloaded (outside playback) so the click beats are laid again.

## 2. Schema (version 1)

```json
{
  "version": 1,
  "slug": "artist_song",
  "rev": "a3f9…",
  "source": "aligned",
  "end_ms": 297893,
  "bars": [
    { "bar": 1, "ms": 290,  "num": 4, "den": 4, "confirmed": true,  "beats": [290, 980, 1665, 2350], "beats_source": "detected" },
    { "bar": 2, "ms": 3017, "num": 2, "den": 4, "confirmed": true,  "beats": [3017, 3733] },
    { "bar": 3, "ms": 4449, "num": 4, "den": 4, "confirmed": false }
  ],
  "sections": [ { "bar": 1, "label": "Intro" }, { "bar": 9, "label": "Intro (dist)" } ]
}
```

| Field | Type | Rule (checked by `bars.validate`) |
|---|---|---|
| `version` | int | must be `1`. An unknown version is refused (no silent best effort). |
| `slug` | string | must equal the backing's golem.fm slug. Inside a `.golem` it may be absent (the export filter removes it); if present it must match. |
| `rev` | string | changes at every re-alignment; this is what the catalogue's `bars_rev` announces. A map is never rewritten silently. |
| `source` | string | `aligned` · `manual` · `songsterr` · `algo`. Informative: shown, never used to sort. |
| `end_ms` | number | end of the song (end of the last bar), after the last `ms`. Without it, the last bar's length is guessed. |
| `bars` | array | **one entry per bar played**, in play order, repeats **unrolled**. Not empty. |
| `bars[].bar` | int | **1-based and contiguous**. Bar 1 = the first downbeat of the score, and also bar 1 of the arrangement. A pickup is a bar of its own (its own short meter, e.g. 1/4). There is no bar 0. |
| `bars[].ms` | number | the instant of the bar's first beat, in ms on the **stems timeline** (0 = first sample of the stems). The **attack**, with no display anticipation. Strictly increasing. |
| `bars[].num` / `den` | int > 0 | the meter of **this** bar. Always present (nothing is assumed 4/4). |
| `bars[].confirmed` | bool | placed or checked by a human ear. The rack shows the share of confirmed bars. |
| `bars[].beats` | number[] | optional: the instant of each beat; exactly `num` entries, the first equal to `ms`, strictly increasing, and before the next bar's `ms` (or `end_ms`). |
| `bars[].beats_source` | string | `detected` (found on the stems) · `interpolated` (spread evenly in the bar). Counted by `bars.stats` and said on screen. |
| `sections` | array | optional, informative `{bar, label}`. Not used to play (the parts stay those of the arrangement). |

Unknown fields are tolerated and ignored (forward compatibility). Only `version` breaks.

golem.fm guarantees that the timeline is that of the stems it delivered: if the stems change, the map
gets a new `rev` at the same time.

## 3. What the rack does — absent, partial, invalid

| Case | The rack |
|---|---|
| No `bars.json` (404, not downloaded yet) | sheet BPM; the arrangement follows the backing transport. The Songs page says "stems ✓ · no bar map" and, under Click, "constant N BPM". |
| Invalid | rejected whole, logged once per file version (`bars.load`), then as "absent". |
| Bars without `beats` | section changes are fine (only `ms` counts). The click gets beats spread evenly in the bar (`bars.ticks`), and the screen says "N bars approximated". |
| The arrangement counts more bars than the map | beyond the last bar, the last bar's length is extended (`bars.time_of`). |
| The meter differs between the map and the arrangement on a bar | the map wins for **time**. |

The map is used only when the backing **starts with the song** (`starts.backing` is not `false`): it
describes the backing's timeline, nothing else ([`arrangement.md`](arrangement.md) §4).

## 4. Code

- `bridge/bars.py`: `validate`, `load` (cached on mtime), `slug_of(preset)` / `for_preset`, `time_of(doc,
  bar, beat)` (a beat without `beats` is placed evenly), `ticks(doc)` → `[(ms, accent)]` (accent on the
  first beat of the bar), `stats(doc)`, `write_ticks(slug)`, `fetch`, `refresh_async`.
- **Sections and markers**: `arrangement.plan(preset, bars)` and `arrangement.sample_marks(preset, bars)`.
- **Screen**: `GET /api/backing/bars/{slug}` (`routes_backing.py`) returns the stats. The "When the song
  starts" row shows "stems ✓ · bar map N bars" under Backing and "on the song's beats · N bars
  approximated" under Click; the song length in bars comes from the map.

## 5. The song click

- `backing.load` writes `.ticks.txt` next to the stems (one line per beat: `ms accent`, `bars.write_ticks`).
- `golem_backing.lua` lays a MIDI item on the **Click** track at position 0, tagged `P_EXT:golem =
  golem_songclick` (removed at the next load). Notes 76/77 on **channel 16**. The item source is frozen at
  its creation tempo (the rig changes the project tempo at recall and at each scene), `B_LOOPSRC` = 0, and
  `I_RECMONITEMS` = 1 on the Click track so the item plays during a take. If the Click track does not exist
  yet, the beats are kept and laid as soon as it does; the number of beats really laid is published as
  `songclick` in `.backing.json`.
- **Accent groups** (3+2+2, 2026-10-15). The bar map has no groups: they belong to the arrangement section. The
  note **velocity** carries the beat's index in its bar + 1 (1–99; `golem_backing.songclick_parse` counts from
  each accent-1 line); velocity 100 = unknown index (items laid before this change, or beats before the first
  downbeat of the file), and the JSFX then counts from the last note 76. The bridge pushes each section's meter
  in song mode too (`app._arr_click_meter`), so the JSFX has the group mask (`gmask`): a note 77 whose index
  starts a group sounds as a group start (800 Hz, full level), like the free-running click. The `.ticks.txt`
  format is unchanged.
- `golem_click.jsfx` slider `song` ("Song click (beats of the backing)"): when on and the transport plays,
  the JSFX plays those notes instead of its own counter, and never both sources at once. It is silent while
  paused.
- The bridge sets `song` mode only if the song's backing is the one loaded, the arrangement holds a bar map,
  and `songclick` > 0 (`app._song_click_ready`); otherwise the click keeps a fixed tempo (wrong, but it
  sounds). The mode is set from the count-in on, so the first notes are never missed. **Every** `click`
  command carries `song` (`app._click_cmd`): `golem_click.lua` keeps the last value of an absent field, and a
  stale `song: true` would leave the click waiting for notes that do not exist.
