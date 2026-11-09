# The `.gsx` chart format

> **Status: CODED** — golem's own hand-writable chord-chart format, read by `bridge/standards.py`
> (`is_gsx`, `_gsx_grid`, `_gsx_bar`, `parse_symbol`); `pickup`, `bass.riff` and `drums.pattern` are reserved
> and not read.

Related: [standards.md](standards.md) (the engine that plays it), [golem-format.md](golem-format.md) (a chart
travels as `chart/song.gsx` inside a `.golem`). Examples: [`docs/examples/*.gsx`](examples/) — the three
factory standards, original compositions given to the public domain (Crooked Lantern, Rented Room Blues, Rooftop Prowl).

**Criterion number one: it is written by hand.** A chart must be typeable in a text editor, readable at a glance
and fixable in ten seconds. One chart fits on one screen.

## 1. Why a format of our own

The iReal Pro JSON is still read (user playlists), but as a *working* format it lacks: any tempo, a key on ~17 %
of charts, readable subdivisions (`Am7,,D7`), a drum groove, playing hints, an explicit form, and provenance.
`.gsx` keeps what iReal does well — a section of 8 bars on one line, named sections with 1st/2nd endings,
substitutions in parentheses — and adds the rest.

## 2. A complete file

JSON, one chart per file, extension `.gsx`:

```json
{
  "v": 1,
  "slug": "autumn-leaves",
  "title": "Autumn Leaves",
  "composer": "Joseph Kosma",
  "year": 1945,
  "style": "jazz",

  "key": "Gm",
  "meter": "4/4",
  "tempo": 132,
  "feel": "swing",
  "groove": "swing-medium",

  "play": { "motion": "comp", "voicing": "rootless",
            "parts": { "keys": true, "bass": true, "drums": true } },

  "form": ["A", "A", "B", "C"],
  "sections": {
    "A": "Cm7 | F7 | Bbmaj7 | Ebmaj7 | Am7b5 | D7b9 | Gm6 | %",
    "B": "Am7b5 | D7b9 | Gm6 | % | Cm7 | F7 | Bbmaj7 | Ebmaj7",
    "C": {
      "bars": "Am7b5 | D7b9 | Gm7 Gb7 | Fm7 E7 | Am7b5 | D7b9",
      "endings": ["Gm6 | %", "Gm6 | D7b9"]
    }
  },

  "source": { "by": "<author>", "licence": "CC0-1.0", "method": "by ear", "date": "2026-08-03" }
}
```

**Detection** (`standards.is_gsx`): a truthy `v` **and** `sections` as an object. A document with `Sections` as an
array is iReal. Anything else is not read as a chart.

## 3. Bar syntax

```
|   separates BARS
    inside a bar, chords separated by SPACES share the bar EQUALLY (one share per token)
.   extends the previous chord by one share
%   repeats the previous bar ENTIRELY (the bar alone, nothing else)
```

| Written | Played (4/4) |
|---|---|
| `Cm7` | Cm7 for 4 beats |
| `Am7b5 D7b9` | 2 beats each |
| `Am7 . . D7` | Am7 3 beats, D7 1 |
| `Am7 . D7 Db7` | Am7 2, D7 1, Db7 1 |
| `%` | the previous bar, identical |
| `N.C.` | silence — the rack stops playing |

- `.` is the readable version of iReal's empty subdivisions: same rule (one share per token), made visible.
- **Substitution**: a token entirely in parentheses after a chord, `Cmaj7 (Am7)` — attached to the preceding
  chord as `alt`, **shown, never played**, and it takes **no** share of the bar.
- Shares are `beats / number of tokens`, so a bar can only be split evenly into the number of tokens written.

### Chord symbols

The grammar of [standards.md](standards.md) §4 (`parse_symbol`): `<root><quality>[<alterations>][/<bass>]`,
root `A–G` with `#`/`b`.

- Write **`mMaj7`**, never `m/maj7` (the slash reads as a bass; the reader normalises it anyway).
- `dim7`/`dim` and iReal's `07`/`0` are all read; `6/9` is read as `69`.
- Also read since 2026-11-09 (21 synced charts had silent chords): `mMaj9`, `dimMaj7` (`dimmaj7`), an added note on
  any quality (`madd9`, `7add11`, `m7add13`), and `sus4add3` — the suspended fourth **with** the third kept.
- Spell what the chart reads (`Bb`, not `A#`); transposition is the engine's job.
- An unreadable symbol is reported in the render's `unknown` list and does not sound.

## 4. Fields

### Identity

| Field | | |
|---|---|---|
| `v` | **required** | format version (currently `1`); without it the file is not read as `.gsx` |
| `slug` | required | stable id, independent of the title. On the rack the slug actually used is the **file name** (`<slug>.golem`) or the song slug |
| `title`, `composer` | required | |
| `year` | optional | not used by the engine |
| `style` | optional | exposed as the grid's `rhythm` |

### Harmony

| Field | | |
|---|---|---|
| `key` | **required** | `Gm`, `Bb`… without it there is no transposition |
| `meter` | required | `4/4`, `3/4`, `5/4`…; `beats` = the numerator (default 4) |
| `sections` | required | `{id: "bars"}` or `{id: {bars, endings: ["bars", …]}}` |
| `form` | required | the running order, e.g. `["A","A","B","C"]`; a section is written once and played as often as listed. Absent: the sections in object order. An id missing from `sections` is skipped |

Each form entry becomes an internal section `<id><position>` (`A1`, `A2`, `B3`…). Endings are unrolled at play
time: ending *k* replaces the tail on pass *k*. The announced bar count is body + **first** ending (one pass).

### How it plays by default

| Field | | Default |
|---|---|---|
| `tempo` | **required** | `120` if absent. A **proposal**: `preset.bpm` stays the only tempo on the rack; the drawer offers to copy it |
| `feel` | required | `swing`. One of `swing · bossa · latin · samba · funk · ballad · even · waltz` — drives comping and the swing of eighths |
| `groove` | optional | `auto` (follows the feel) or a groove/family name |
| `play.motion` | optional | `comp` · `block` · `arp` · `arp+bass` |
| `play.voicing` | optional | `rootless` · `full` |
| `play.parts` | optional | `{keys, bass, drums}`, default all three on |
| `play.bass.mode` | optional | `auto` (from the feel) · `walk` · `roots` · `two` (and the other modes of [standards.md](standards.md) §5.3) |

The block's settings override these defaults (`standards.build`: "the chart says how it is usually played, the
block decides"). Example: Take Five's feel (`even`) would give a walking bass; `"bass": {"mode": "roots"}` gives
the 3+2 vamp roots instead.

### Provenance

`source`: `{by, licence, method, date}` — who wrote **this chart**, under which licence (SPDX id), how (`by ear`,
`from an owned lead sheet`, `imported by the user`, `converted`), when. It describes the chart file, not the
musical work. The engine passes it through (`grid.source`) and an overlay can never change it.

### Reserved, not implemented

- `pickup` (an anacrusis, in beats);
- `bass.riff` and `drums.pattern` (a bass line or drum pattern written note by note, for the few tunes whose
  riff *is* the tune).

No reader handles them; a v1 file carrying them stays valid (unknown fields are ignored). The default stays
generated: writing every bass and drum note by hand would kill the hand-writable criterion.

### Not in the file, on purpose

| | Why |
|---|---|
| number of choruses, solos, intro, coda | the form of a *performance*: the Arrangement block |
| melody, lyrics | the format carries chords only |
| tablature, fingerings | other members of a `.golem` |
| a second BPM | `preset.bpm` is the tempo |

## 5. Compatibility

- The iReal reader stays (user playlists); both formats compile to the same internal grid, so `render()` ignores
  where a chart came from.
- An iReal → `.gsx` conversion is mechanical; converted files carry `source.method: "converted"`.
- Local corrections never edit the file: they go to an overlay (`library/standards/local/<slug>.json`,
  [standards.md](standards.md) §4).
