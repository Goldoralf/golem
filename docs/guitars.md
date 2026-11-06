# Guitars — profiles, neck maps and the "map my guitar" screen

> **Status: PROPOSED** (2026-11-02) — a screen **System ▸ Gear ▸ Guitars** to declare one's guitars, choose the one
> being played, and give each one a **neck map** (`bridge/neckmap.py`, CODED 2026-11-01, see
> [`tablature-fingering.md`](tablature-fingering.md) §1): factory maps offered as a starting point, or the
> musician's own, recorded in about three minutes. Nothing in this document is built; the engine it drives is.

Related: [`tablature-fingering.md`](tablature-fingering.md) (the transcription and the fingering that read the map),
[`compo.md`](compo.md) §5 (armed riffs, the takes that get transcribed), [`calibration.md`](calibration.md) (the
other "make golem know my gear" screens), [`licence.md`](licence.md) (what we may ship).

## 1. Why — what was measured

A neck map is the fingerprint of every fret of **one** guitar (the amplitudes of its first 12 partials). It tells
the fingering *where* a note was played when the pitch alone cannot (an A3 exists on five strings of a 6-string).
Measured 2026-11-01/02 (benches in `~/golem-doc-work/neck` and `~/golem-doc-work/tx`, machine-local):

| Notes to place | Its own map | Another guitar's map | Chance |
|---|---|---|---|
| the maintainer's 8-string, another session (190 notes) | 91 % | — | 27 % |
| Guitar-TECHS player 1, scales (3,526 notes, bridge pickup) | 83 % | 51 % (P2) · 65 % (the maintainer's 8-string) | 29 % |
| Guitar-TECHS player 2, scales (3,295 notes, neck pickup) | 73 % | 23 % (P1) · 28 % (the maintainer's 8-string) | 29 % |

What follows from it, and shapes this screen:

1. **A guitar's own map is what works.** Another guitar's map sometimes helps (the maintainer's bridge-pickup 8-string helps
   P1's bridge-pickup guitar) and sometimes does **worse than chance** (P2, neck pickup). A factory map can
   therefore never be applied silently: it must be **checked on the musician's guitar** first (§3.3).
2. **Ten frets per string are enough**, interpolated along the string: P1 84 % (full map 83 %), P2 72 % (73 %),
   the maintainer's 8-string 170/190 (173/190). Five frets lose up to 12 points (P2 61 %). Ten whole notes per string at
   100 BPM is about 25 s per string: **~3 minutes for a 6-string, ~4 for an 8-string**.
3. **No map, nothing changes.** Without a map the transcription keeps its pitch, rhythm, tapping rule and default
   fingering; the map only adds evidence. Every guitar starts there.

Not measured yet, and the screen must not pretend otherwise: **the pickup selector** (a guitar played on another
pickup may need its own map — each Guitar-TECHS player used one pickup), tapping versus picking (maps are recorded
picked; 8/9 tapped notes of one riff were placed right), 7- and 8-string factory maps (only the maintainer's exists), chords
(the map judges single notes only).

## 2. The data — what exists, what is added

| What | Where | Today | Added |
|---|---|---|---|
| Guitar profiles (name, tuning, frets, inharmonicity `b_open`, hand, `neckmap`) | `config/string-calib.json` | CODED, edited by hand | written by the screen |
| The **active** guitar (recorded into every take, `take.json.guitar`) | `active` in the same file | CODED, edited by hand | chosen on the screen |
| A guitar's own map | `config/neckmap/<guitar>.json` | CODED (`python -m bridge.neckmap`) | built by the wizard |
| **Factory maps** | `library/neckmaps/<id>.json` | — | shipped, with `source`, `licence`, `attribution`, `pickup`, `tuning` |
| The audio of the mapping takes | `recordings/` (`take.json.kind = "guitar-map"`) | — | kept locally to rebuild a map when the fingerprint changes; **never uploaded** |

A profile gains `pickup` (`bridge` / `middle` / `neck` / `other`) and `neckmap_source`
(`own` / `factory:<id>` / none). Everything under `config/` stays local (rule 2 of `CLAUDE.md`); only factory maps
are committed.

**Factory maps offered at first** (measurements only — no sound is shipped):

- `guitar-techs-p1` — Ibanez PF300, bridge pickup, standard tuning, 22 frets; `guitar-techs-p2` — EVH Wolfgang,
  neck pickup. From **Guitar-TECHS** (Pedroza, Abreu, Corey, Roman, ICASSP 2025), **CC BY 4.0**: the attribution
  is carried by the file and listed in Settings ▸ About ▸ Licenses. Their audio stays out of the repository.
- `eight-double-drop` — an 8-string in double drop (E A E A D G B E), bridge pickup, 24 frets, recorded and offered
  by a golem musician. **Its licence is to be decided before it ships** (open question 1).

## 3. The screen — System ▸ Gear ▸ Guitars

1024×600, no scroll (the rack's rule). A list on the left, the selected guitar's sheet on the right — the layout of
System ▸ Mode.

### 3.1 The list

One row per profile: name, `8 · E A E A D G B E · 24`, a **map chip** — `Own map` / `Factory map · checked` /
`No map` — and a ● on the guitar being played. **+ Add a guitar** at the bottom. Tapping the ● makes a guitar the
active one: the next take records it.

### 3.2 The sheet

- Name, strings (6 / 7 / 8), tuning (presets per string count, or note by note), frets, pickup.
- **Neck map**: what it is now, and three actions — **Map my guitar** (§3.4), **Try a factory map** (§3.3, only maps
  with the same number of strings), **Remove the map** (back to no map).
- What the map gave on its last check (`7/8 notes placed right`), so the musician sees it is earning its place.
- Delete the guitar (the takes keep the name they recorded; a take whose guitar no longer exists is read without a
  map).

### 3.3 Try a factory map — the check

Because a foreign map can do worse than chance, a factory map is **never** attached without a check:

1. The screen shows eight known positions on the musician's tuning, chosen where strings compete (the same pitch on
   several strings: e.g. G3 = string 6 fret 15, string 5 fret 10, string 4 fret 5, string 3 open), one whole note
   each, on the click.
2. One armed take (~25 s). The rack places those eight notes with **each** factory map of the right string count,
   and with none.
3. It shows the scores and **attaches the best map only if it beats no map**; otherwise it says so and offers
   **Map my guitar**. The check is kept on the sheet.

### 3.4 Map my guitar — the wizard

- **Before**: "Bridge pickup? Same knobs and pick as when you play? Tune up." — and the level check of the input
  (peaks near −6 dBFS, the measured sweet spot; a clipped input gave inconsistent readings).
- **Per string**, one armed take at 100 BPM, one bar of count-in, then one whole note per bar on frets
  **0, 3, 5, 7, 10, 12, 15, 17, 19 and the last fret**. The screen shows the string and the fret to play now,
  large, and the bar count — readable from a step away.
- **After each string**, the rack checks the take (every pitch where expected, nothing clipped, the level) and says
  **Next string** or **Play this string again** with the reason (`fret 7 not heard`, `clipped`). Nothing is built
  from a bad take.
- **At the end**, the rack builds the map (interpolated along each string) **and** the open-string inharmonicity
  `b_open` from the fret-0 notes — the hand-made calibration of today disappears. The sheet shows `Own map`.
- **Leaving**: ✕ at every step. A string already validated is kept; leaving discards nothing that was finished, and
  never leaves a half-built map attached (the rule "never ship a mode without its tested exit").
- **A probe never starts a take** — here the takes are the point, so each one is started by the musician (foot or
  button), never by the screen on its own.

## 4. What the rest of golem does with it

- **Transcription**: unchanged in principle — the take's guitar, its profile, its map
  (`transcribe_cli._neck`); a map of another tuning or string count is ignored.
- **golem.fm**: nothing at first. A profile and its map could follow the musician to another rack through their
  account later (a separate proposal).
- **Backups**: profiles and own maps are local state worth keeping — they join the local back-up
  (`bridge/backup.py`); the mapping takes follow the recordings' rules.

## 5. Work items

1. **API** — `GET /api/guitars` (profiles, active, factory maps), `PUT /api/guitars/<id>`, `POST /api/guitars/active`,
   `DELETE /api/guitars/<id>`; behind the authenticated prefix (`docs/howto/add-api-route.md`). Factory maps:
   `library/neckmaps/` with their metadata; the About ▸ Licenses entry.
2. **Mapping takes** — an armed take of kind `guitar-map` (the riff engine's click and count-in, not sent to
   golem.fm), the per-string check, `neckmap.build` from sparse frets, `b_open` from the open strings.
3. **The check of a factory map** (§3.3).
4. **The screen** (§3), verified at render at 1024×600 (`tools/check-ui.py`).
5. **Bench in CI** — the map's scoring on a small, licence-clean fixture, so a change of the fingerprint cannot lower
   it silently.

## 6. Open questions

1. **The licence of the offered 8-string map** (CC0, CC BY, the repository's GPL?) and how it is credited on screen
   (no first names in displayed text, by default).
2. **The pickup**: one map per guitar, or per guitar *and* pickup? To be measured on one guitar, two pickups,
   before §3.2 offers a pickup field.
3. **More factory maps**: Guitar-TECHS P3 (Sire T7, bridge+neck), and whether a sample library adds anything the
   check (§3.3) could not already reject.
