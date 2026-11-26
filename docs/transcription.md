# Transcription — golem.fm listens, the rack records

> **Status: ACCEPTED** (2026-11-26) — the split between the rack and golem.fm for turning a take into notes,
> rhythm and tablature. Decided by the maintainer on 2026-11-25/26: golem.fm owns the whole listening, Q1–Q6 of §7
> answered, the removal of §6 approved; reviewed with the golem.fm session. **CODED on the rack** the same day: the
> `instruments` block of §4 (`bridge/guitars.py`) and the removal of §6. Replaces, for the rack, the transcription half of
> [`tablature-fingering.md`](tablature-fingering.md) and `archive/tablature-study.md` §12 (not published).

Related: [`golemfm-protocol.md`](golemfm-protocol.md) (take upload), [`compo.md`](compo.md) §5 (Riff manifest),
[`tablature-fingering.md`](tablature-fingering.md) (the hand, §6 review).

## 1. Why

- **The rack's ear never shipped.** It needs `.venv-transcribe` (835 MB: Basic Pitch, librosa, pYIN), installed by
  hand on one development PC. On Windows, `/recordings ▸ Transcribe` said "transcription engine not installed", and
  so did every rack but that one.
- **Takes already go to golem.fm** (DI and MIDI included, §3). golem.fm can install and run models; the rack should
  not have to.
- **The guitarist knows the string, not the sound.** Measured on 2026-11-25 (§8), the string a note was played on
  cannot be told from its timbre on a guitar the system has not calibrated. Knowing the hand position (a 4-fret
  window) leaves 0 % of notes ambiguous. That information comes from the person, on golem.fm, after the take (§5).

## 2. Who does what

| | Rack | golem.fm |
|---|---|---|
| Record the DI and the MIDI of a take | ✔ | |
| Write the grid in `take.json` (`bpm`, `downbeat_s`, `sig`, `count_in`, `bars`) | ✔ | |
| Write the instrument of each lane (§4) | ✔ (2026-11-26) | |
| Upload the DI and the MIDI | ✔ (exists) | |
| Notes from the audio (the ear) | ✘ (removed, §6) | ✔ |
| Rhythm on the grid, rhythm-only score | | ✔ |
| String and fret (the hand), with the position given by the person | | ✔ |
| Exact scores from MIDI (keys, pads, drums) | ✘ (Q4) | ✔ |
| Review and correct a score | | ✔ ([`tablature-fingering.md`](tablature-fingering.md) §6) |
| Show the scores | ✘, a link to the recording on golem.fm (Q5) | ✔ |

## 3. What golem.fm receives (exists)

The take upload of [`golemfm-protocol.md`](golemfm-protocol.md) (`uploader.upload_take`), unchanged:

- the DI as `DI-*.wav` (sent as FLAC, `kind: di`) when the job's `kinds` asks for `di`; the MIDI capture
  (`kind: midi`) when it asks for `midi`;
- the frozen copy of `take.json` (without `upload`): the grid fields of a take on a grid (an armed Riff:
  `bpm`, `sig`, `bars`, `passes`, `count_in`, `downbeat_s`, `tempo_source`), `roles` (input channel → role or
  label), `marks[]` (preset, scene, section, click + bpm), `song`, `backing`.

Existing fields `guitar` (the active profile id) and, for a Riff, `tuning` (a MIDI list, §4) stay. Fields are added,
never removed.

**Takes without `instruments`** (every take recorded before this lands) carry no reliable instrument. golem.fm
**asks the person**: strings, tuning, capo. It never guesses them, not even from `guitar`.

## 4. New: the instrument of each lane in `take.json`

```json
"instruments": {
  "1": {"role": "guitar", "strings": 8, "tuning": [30, 35, 40, 45, 50, 55, 59, 64], "tuning_id": "8-std",
        "capo": null, "frets": 24, "guitar": {"id": "eight", "name": "Ibanez 8"}, "source": "tuner"},
  "2": {"role": "bass", "strings": 4, "tuning": [28, 33, 38, 43], "tuning_id": null,
        "capo": null, "frets": 20, "guitar": null, "source": "default"}
}
```

- **Keyed by input channel**, like `roles`. It is a dict next to `roles`, not inside it, because older takes carry
  string labels in `roles`. Only lanes whose role is `guitar` or `bass` get an entry; others are absent.
- `tuning`: MIDI note numbers, **lowest string first**, one per string; `strings` = its length. **This MIDI list is
  the truth.**
- `tuning_id`: the id from `library/catalog/tunings.json` (the copy of golem.fm's `TUNING_PRESETS`) when the rack
  knows it, else `null`. It is only for the displayed name.
  - ⚠ **Two `tuning` fields, do not confuse them.** In this block, `tuning` is the MIDI list and `tuning_id` the
    string id.
  - The Riff's existing top-level `take.json` `tuning` is **also a MIDI list** on the rack. `compo.py` refuses
    anything else ("bad take: tuning is 4 to 9 MIDI notes") and writes it sorted.
  - The song sheet's `tuning` is free text (≤ 24 characters, "Drop C"). The engine never reads it; it is never
    used here.
- `capo`: an int when something on the rack states it, `null` when nothing does.
  - The source is the sheet of the song being played (`sheet.capo`, through the setlist line or the song page).
  - A Riff target carries no capo today. **To come** (agreed with golem.fm on 2026-11-26, lot not decided):
    golem.fm sends `capo` in the `compo-target`, next to `tuning` (its `BandRiff` has the field). The order will
    then be the Riff's capo, then `sheet.capo`, then `null`.
  - `null` is **not** `0`: the sheet rule is that "no capo" is not "capo 0" (`songs.update`). golem.fm asks the
    person when it is `null` and the fingering depends on it.
- `frets`, `guitar {id, name}`: from the guitar profile in `config/string-calib.json` (the profile whose tuning
  matches, `guitars.guitar_for`, else the active one), or `null`.
- `source`: where `tuning` comes from, in this order:

  | `source` | Where the tuning comes from |
  |---|---|
  | `riff` | the armed Riff's tuning, sent by golem.fm |
  | `tuner` | the lane's Tuner block in the playing preset: `params.tuning`, an id of `tunings.json`, resolved to its MIDI |
  | `profile` | the guitar profile, when it **declares** a tuning |
  | `default` | nothing stated it. A guitar is 6-string E standard (what `guitars.guitar` assumes for a profile without a tuning); a bass is 4-string E standard. **golem.fm asks the person to confirm** |
- A lane the rack knows nothing about (no role) gets **no entry**.
- **Not sent:** calibration (`b_open`), the neck map and the hand weights. Per §8 they do not transfer between
  guitars; golem.fm does not need them.
- Written by `monitors._take_manifest` at stop (`guitars.instruments_of`), frozen like `roles`, and completed by
  `compo.stamp_manifest` for a Riff (`guitars.apply_riff_tuning`, `source: riff`).

## 5. The golem.fm half (for reference: golem.fm decides)

- **Ear**: candidate = the Riley et al. 2024 CRNN (weights `xavriley/midi-transcription-models`, MIT; PyTorch on
  CPU). Measured better than the rack's pipeline on real electric DI (§8).
- **Rhythm**: onsets quantized on the take's grid (`bpm`, `downbeat_s`, `sig`). The rack's attack and mute rules
  (`bridge/transcribe_di.py`, the TX v1 strategy agreed on 2026-10-29) may be reused. **Rhythm-only score**: the
  attacks on the grid without pitches, for when the notes are unsure.
- **Hand**: Viterbi over playability costs (`bridge/fingering.py`) on the `instruments` tuning, plus the **position
  given by the person on the `/composer` fretboard after the upload**: a fret window, a starting note, the strings
  used, or a scale. The rack does not carry it.
- **Review**: [`tablature-fingering.md`](tablature-fingering.md) §6.

## 6. What left the rack (approved and done 2026-11-26)

Removed from the rack on 2026-11-26, with no score left there (Q4, Q5):

| What | Where it was |
|---|---|
| The "Transcribe" buttons of `/recordings` | `app/page-loops.js`, the `.rec-tr` CSS |
| The transcription queue, its subprocess and its routes | `bridge/transcribe_jobs.py`, `bridge/transcribe_cli.py`, `POST /api/take/transcribe` and `GET /api/take/score/…` (`routes_content.py`), `state.transcribe`, the `score` / `can_transcribe` fields of `GET /api/loops` |
| The ear, its rules and the hand | `bridge/transcribe.py`, `bridge/transcribe_di.py`, `bridge/fingering.py` (golem.fm keeps a copy if it wants one) |
| String evidence | `bridge/inharm.py` (B, candidate string), `bridge/neckmap.py`. The guitar profile moved to `bridge/guitars.py`; the old `b_open`, `hand`, `neckmap` keys of `config/string-calib.json` and a `config/neckmap/` folder may stay on a rack, unread |
| Auto-transcription at stop | `monitors.py` (`transcribe == "auto"`), the Designer's "Transcribe takes" (Rec drawer), the "auto-transcribe" mention in Settings ▸ Mode |
| The Riff's transcription before upload | `compo._transcribe`, the upload state `transcribing`, the Riff drawer's "Transcribe on the rack", the manifest field `transcribe` |
| The settings | `transcribe` in `config/recorder.json` and `config/compo.json` (ignored when still there; the `recorder-set` job still **accepts and ignores** the key, for an older golem.fm) |
| The benches and checks | `tools/check-transcribe.py`, `tools/check-tab-vs-gp.py`, `tools/check-fingering.py` (CI and `check-cold.sh` no longer run the first) |
| The components | Basic Pitch, partitura, tuttut, music21, librosa, pretty-midi, mido in `provision/components.json` (onnxruntime and NumPy stay: stem separation) |

Kept: the `/live` Riff chip "→ golem.fm…" (it now says *sending to golem.fm*). `.venv-transcribe` was never installed
by the repository's scripts: a copy on a development machine can be deleted by hand (it stays in `.gitignore`).
Older takes keep their `scores/` folder on disk; the uploader still sends a `files.score` an older Riff declares.

**The Riff (Q1):** the DI goes up as soon as the drop window closes. The `transcribing` state is gone, and so is
the 15-minute wait in `compo._transcribe`; a take still marked `transcribing` uploads at once. The `held` state is **kept**: it is not transcription. It is the 20 s window
in which the author can drop the take (`drop_window_s`, [`compo.md`](compo.md) §5). Removing it would remove the
undo. `lanes[].files.score` is no longer written by the rack.

`bridge/fingering.py` went too: its only reason to stay was an exact score written on the rack, and Q4 says no.

## 7. Questions

- **Q1 — the Riff's score**: golem.fm makes it; the DI goes up at once. *Answered yes, 2026-11-26.*
- **Q2 — the instrument in `take.json`**: strings, tuning (MIDI, low to high), guitar profile. *Answered yes,
  2026-11-26* → §4.
- **Q3 — the hand position**: entered on golem.fm after the upload, on the `/composer` fretboard; not carried by the
  rack. *Answered yes, 2026-11-26.*
- **Q4 — exact scores from MIDI**: golem.fm writes them from the uploaded `.mid`, like the audio ones. The rack
  keeps no score at all, and has no local MIDI → MusicXML. *Answered, 2026-11-26.* (Until then the rack wrote them
  through the same `.venv-transcribe` subprocess, so no rack without the venv had them either.)
- **Q5 — scores back on the rack**: never. Scores live on golem.fm; the rack links to the recording there.
  *Answered, 2026-11-26.*
- **Q6 — Standards**: golem.fm takes the chart as the exact harmony. *Answered, 2026-11-26.* A Standard take already knows its chart: `take.json` `standard` =
  `std_played` + `played: true`, set in `app.py` when the take arms. It holds:
  - `slug`: the chart;
  - `etag`: the chart as golem.fm sent it, `golemfm._std_etags()`, which golem.fm compares as `same_chart`;
  - `key`;
  - `semis`: the transposition;
  - `bpm`;
  - `beats`: per bar;
  - `feel`;
  - `choruses`: passes, 0 = loop;
  - `parts_heard`: the rhythm-section parts that played;
  - `bars`: the chord symbols of each bar played, transposed, the first `bars` bars of the rendered form.

  golem.fm takes `bars` as the exact harmony and listens only to the soloist's DI.

## 8. Measurements behind the decision (2026-11-21 → 26)

The benches are outside the repository (`~/golem-doc-work/libmaps/e6–e12`, `~/golem-doc-work/tx/e13_*`). The
purchased guitar libraries are used for **measurements only**, per the lawyer's opinion of 2026-11-02: no audio
is committed or shipped. Guitar-TECHS is CC BY 4.0.

**String from timbre, on a guitar never seen** (chance 26–29 %):

| Method | Correct string |
|---|---|
| Stiffness from another guitar | 46–60 % |
| Pitch × fret matrix pooled on 4 other guitars | 19–42 % |
| Classifier | 35–54 % |
| Classifier with measured inharmonicity B | 29–53 % |
| Self-calibration on the take | 17–100 % (unstable) |
| Noise2Fret (diffusion, Zenodo 23361924), known pitch | 27–41 %; exact tab 0 % |

Only the calibrated guitar works: 88–100 % on isolated notes, one calibration note per string. On real riffs the
maintainer's neck map gained 6–10 notes out of 66.

**Hand position known**: 4-fret window → 0 % ambiguous notes (6 and 8 strings); 5 frets → 3 %.

**The ear** — real electric DI scales of Guitar-TECHS, 7 005 notes, truth = per-string MIDI realigned, ±60 ms:

| Player | Notes | Rack pipeline: found | Rack pipeline: invented | Riley: found | Riley: invented |
|---|---|---|---|---|---|
| P1 | 3 627 | 84 % | 220 | 89 % | 11 |
| P2 | 3 378 | 88 % | 265 | 91 % | 160 |

Synthetic riffs (library notes, 128 per riff):
- eighths: Riley found 117–128 notes, the rack 84–113;
- sixteenths: Riley 115–118, the rack 47–67;
- invented notes: Riley 0–3, the rack 1–32.

Fingering, tabgen's DP vs `fingering.py`, frets right: 44 vs 51, 70 vs 74, 63 vs 55.

Not covered by any bench: palm mute, chords, tapping, the low strings of an 8-string.
