# Tablature — shape-based fingering, and how golem.fm drives transcription

> **Status: PROPOSED** — a design for choosing string and fret like a guitarist (shapes and hand continuity over a
> whole song) and for letting golem.fm request and review transcriptions. §1 describes what is CODED on the rack:
> the "ear", a naive fingering, and one staff per instrument (tabs for guitar and bass, two staves for keys, a
> percussion staff for drums — 2026-10-17). The hand of §5 points 1–3 (candidates, costs, Viterbi, shapes) is
> CODED in `bridge/fingering.py` and replaces `naive_fingering` in the tabs, with a per-guitar neck map as evidence
> (§1, CODED 2026-11-01); doubt (§5.4), constraints (§5.5), the
> tuning from the setlist line and §6 are not built.

Related: [`compo.md`](compo.md) §5 (a riff is transcribed on the rack — unchanged by this document),
[`gear-classifier.md`](gear-classifier.md) (the "one source, two executions" precedent),
[`arrangement.md`](arrangement.md) (one clock), [`golemfm-protocol.md`](golemfm-protocol.md).

## 1. What exists on the rack

- **The ear** — `bridge/transcribe.py`: Basic Pitch on the DI (`notes_from_audio`), then five pure rules
  (`rule1_range` … `rule5_figures`, `apply_rules`), MusicXML output (`to_musicxml`). Run by
  `bridge/transcribe_jobs.py`: one job at a time, in a separate process at `nice -19`, never while playing,
  venv `.venv-transcribe`; results in `<take>/scores/` (`index.json` + one MusicXML per source). A take is
  eligible if it holds a DI (`DI-*.wav`) or a MIDI capture. Trigger: the Rec block setting
  `transcribe: manual | auto`. Only the inputs ticked in the Rec block are recorded, DI included.
- **The DI of a take with a grid** (an armed riff: `bpm`, `downbeat_s`, `count_in` in `take.json`), guitar or bass
  only — `bridge/transcribe_di.py`, golem.fm's TX v1 strategy (its bench `maestrium/backend/tools/tx_bench`,
  agreed 2026-10-29), instead of the five rules:
  - a note exists only if the DI shows an **attack** (spectral flux; two peaks < 150 ms apart are one — the pick,
    then the string — **unless a new pitch starts at the first peak and changes again at the second** (≥ 0.7
    semitone each time: before the first peak, between the peaks, after the second, each read with at least three
    sure pYIN frames, the last on the note's body up to the next peak). Picked, the first peak falls while the
    previous note still rings, so between the peaks one hears the OLD note: comparing only between/after doubled
    the invented notes on Guitar-TECHS' picked scales (2026-11-02). Two tapping fingers are two notes, 2026-11-01, the maintainer's
    all-tapped riff at 120 bpm lost 6 of 15 notes to the merge; a model note that starts after the next attack
    belongs to it, not to this one; `merge_onsets`. Bench: golem.fm's 9 takes unchanged (40/41, nothing
    invented), the 8-string's whole notes unchanged, riffs 305/307/308/392 75 → 86 notes found, 59 → 65 string
    and fret. Still lost: the same pitch tapped again on another string, under 150 ms; a real attack
    rises ≥ 3 dB and peaks ≤ 24 dB under the loudest; a slur is kept if the pitch moves ≥ 0.7 semitone and the
    level still holds 200 ms later);
  - pitch: pYIN for a single note, the model otherwise, with the **whole harmonic series** filtered (partials
    2–10, confidence < 0.6 × the fundamental's). `rule2_harmonics` of the five rules uses the series too. When
    pYIN holds one clear pitch (median probability ≥ 0.8 over 200 ms), a brief model note (< 200 ms) at a pitch
    played in the 4 s before is the previous string the attack woke up, not a finger (take 260, open strings left
    ringing: the B was read [E, A, B]); and a model pitch less than 0.6 × as sure as pYIN's is a shared partial, not
    a second note (take 266: a B whole note read [D, B]). **A pitch without its fundamental is not played**
    (2026-10-30): a model pitch whose fundamental is 20 dB under the loudest other one of the attack is another
    string's partial (take 286: a high E read [G, B, E]; take 288: the open A that a high E makes ring). Under E2
    the pickup cuts the fundamental, so the 3rd partial is read instead, with a 12 dB gap (take 292: the low A woken
    by the open A, its octave, is 18 dB down; played, the low strings are 2–3 dB from their octave). And under E2 an
    exact octave is the string's strongest partial unless the model hears it ≥ 0.85 × as surely;
  - the click's grid, read from the take, and the whole phrase snapped at once (`quantize_phrase`, a Viterbi:
    position cost, the player's lead, a smooth change of that lead);
  - the written length runs to the next attack unless the sound dies first (30 dB under the peak, snapped to the
    eighth): the rest is a rest. Dotted values and rests are written exactly (`_typed`, `_split_ql`), for every
    instrument;
  - **the hand that listens** — on a guitar whose strings are calibrated, the inharmonicity B of each single note
    (`bridge/inharm.py`; partial k at k·f0·√(1+Bk²)) is checked against each shape's prediction
    B = B_open(string)·2^(fret/6): an evidence cost in the fingering Viterbi (`fingering.evidence_cost`, tolerance
    0.2 octave — 0.35 let an open G lose to D string fret 5, whose B is 0.18 octave away — capped),
    applied only when **every** candidate string of the note is calibrated; beyond the cap the nearer shape still
    wins by a small tail (0.15 per unit). **When the ear cannot tell, the open string** (2026-10-30, agreed by
    ): if the open shape and a fretted one predict B within 0.08 octave (8-string: open G and D string fret 5,
    2 % apart), or the reading says nothing (B = 0) on a calibrated guitar, the open shape gets a bonus of 1. On the
    6-string the open G and the D string fret 5 are 0.15 octave apart: the ear alone decides. `estimate_b` prefers
    readings of ≥ 10 partials: a low wound string has two coherent readings, one on a few partials partly from a
    string still ringing. **The hand stays where the ear saw it** (2026-10-30, the maintainer's riffs in high position):
    a note whose best shape fits the reading (cost ≤ 1) with the next one ≥ 2 behind is an anchor; the unread notes
    up to 16 notes around it pay 1 per twelve frets away from it — fast notes often have several equally playable
    fingerings (the same pattern at fret 3 or fret 10). No ear, no anchor: the corpus is unchanged. A profile may
    carry its own **hand** (`"hand": {"reach": 4, "height": 0, "string": 1.0, "shift": 0.5}`, keys of
    `fingering.WEIGHTS`): the 8-string played in 3–4-notes-per-string patterns is not the 6-string corpus' hand
    (these weights would cost the corpus ~0.6 point). Riffs 305/307/308 against the player's own tab: 26/66 → 47/66 string and
    fret; whole-note takes 47/48 unchanged. Short fast notes stay the hard part: under ~0.2 s nothing is read, and
    on this guitar strings 8/7 and 4/3 predict the same B five frets apart. Calibration:
    `config/string-calib.json`, local to the machine — **one profile per guitar** (`bridge/inharm.py`, 2026-10-29):
    `{"active": "default", "default": {"name", "tuning": [40, 45, 50, 55, 59, 64], "frets": 22, "b_open": {"6": …}},
    "eight": {"tuning": [28, 33, 40, …, 64], "frets": 24, "b_open": {…}}}` (tuning in MIDI notes, low to high; strings
    numbered as in MusicXML, 1 = highest). Each take freezes its guitar (`take.json.guitar`): for an armed riff,
    the profile whose tuning is the riff's (`take.tuning` from golem.fm, `inharm.guitar_for`), else the active one;
    `guitar: null` with a `tuning` = no profile has it (the tab follows the tuning, no calibration). The
    transcription reads that guitar's tuning, frets and calibration — range from its lowest open string to its last
    fret, a tab with as many lines as strings (`to_musicxml(tuning=, frets=)`, `<tuning-alter>` for an F#), the
    fingering on its strings. A profile without `tuning` is a standard 6-string. Choosing the guitar has no screen
    yet (the file's `active`). Measured on
    take TX00 string by string (open whole note + 12th-fret whole note; the 12th fret is a check only — the open
    string still ringing under it blurs the reading). As of 2026-10-29: string 6 from whole notes, strings 5–1
    provisional from open strings played as quarter notes (take 258, matching golem.fm's take 250 within 6 %).
    the maintainer's 8-string in double drop (E A E A D G B E, 24 frets) is calibrated on all 8 strings (2026-10-30, medians
    of three open-string takes; keep the DI peaks near −6 dBFS: a clipped input gave inconsistent readings). A take
    without a `guitar` field predates the profiles and is read as the 6-string `default`.
  Bench (golem.fm's 9 takes TX00–TX02 + take 260, six open strings): every pitch found, no invented note; TX02 13/13
  pitches, 12/13 lengths, 13/13 string and fret with the calibration (5/13 without); take 260 6/6 string and fret.
  The five rules on TX02: 10/13 pitches, 11 invented. 2026-10-30: the 13 bench takes unchanged by the rules above;
  the 8-string's open-string takes 8/8 pitch, string and fret (takes 286–294).
- **The neck map** (CODED 2026-11-01, `bridge/neckmap.py`) — the fingerprint of every fret of ONE guitar, a second
  piece of evidence next to B. Two positions of a note do not sound alike (a thicker string shortened has other
  partials than a thinner one left long): the guitar is recorded fret by fret, one whole note per bar and per string,
  frets 0–24, and each cell keeps the amplitudes of its first 12 partials (dB under the loudest, **slope removed** —
  playing harder brightens every fret, not one), read on nine windows from 0.06 to 0.4 s since a 16th note is not a
  whole note. A single note with several positions is compared to each of them at the window closest to its own
  length; the distance to the nearest becomes a fingering cost, `W_NECK` = 0.5 capped at `NECK_CAP` = 2
  (`fingering.fingering(neck=)`), and it also feeds the anchors — so it judges notes too short for their B. The map is
  a local file, `config/neckmap/<guitar>.json` (never committed), named by the profile (`"neckmap": "eight"` in
  `config/string-calib.json`); built with `python -m bridge.neckmap <guitar> <take string 1> … <take string N>` in
  `.venv-transcribe`. No map, or a map of another tuning: nothing changes (the corpus, the 6-strings, golem.fm).
  Measured on the maintainer's 8-string (bench `~/golem-doc-work/neck`, machine-local): learnt on one session (30/10), the map
  puts 170/190 notes of another session (31/10–01/11, soft and loud attacks) on the right string (chance: 51) — its
  errors are always the next string, soft notes are the weak spot (~83 %). In the fingering, judged on the riffs and
  the whole notes **together**: riffs 305/307/308 47/66 → 53/66 string and fret, whole notes 47/48 unchanged.
  Uncapped, 0.5 gave 57/66 but sent two open low E to string 7 fret 7 (45/48) — the cap was chosen for no loss.
  Not measured yet: riffs other than these three (the weight was chosen on them), chords and dyads (the map only
  judges single notes), a second guitar.
- **The instrument** of a source comes from `take.json.roles` (input number → label, frozen at the take): the
  source name carries the input (`DI-Sandbox-Input-2` → 2), the label gives guitar, bass, voice, keys or drums
  (`transcribe_cli._instrument_of`). Each one gets its own staff (`to_musicxml(instrument=…)`): a 6-string tab for
  the guitar, a **4-string tab** for the bass (E1 A1 D2 G2, frets to 24), a note staff (treble or bass clef) for
  the voice. A MIDI capture is read with `mido` (`transcribe_cli._midi_read`) at the file's own tempo, onsets
  **and** durations, with the sustain pedal (CC64).
- **Keys** (MIDI capture, quality `exact`) — `to_musicxml_piano`: one part, **two staves** (treble and bass clef,
  split at middle C), voice 1 on both. Not rule 5: `piano_hands` snaps each note's start **and** end to the grid
  (rule 3), hand by hand, one voice per staff (a figure is cut at the next onset of the same hand); the pedal is
  written below the bass staff.
- **Drums** (MIDI capture of an electronic kit only) — the module's notes are read through the **descriptor**
  frozen in `take.json.drums` (`config/drumkits/`, General MIDI as fallback): note → element → the element's
  General MIDI note (`DRUM_GM`), unknown notes counted in the report. `to_musicxml_drums` writes a percussion staff:
  `<unpitched>` at the conventional line (kick F4, snare C5, toms, hi-hat G5, ride F5, crashes A5/B5), cross heads
  for cymbals, one `<score-instrument>` per element on channel 10. An acoustic drum recording is skipped (it needs
  a drum-transcription model).
- **The Standard block's parts** (quality `exact`, nothing heard) — a take played over a Standard keeps the
  sequence the engine played (`<take>/standard.seq`, copied at the end of the take by `monitors._take_manifest`;
  `take.json.standard.seq`). `standard_scores` writes one score per part that played: piano (two staves), bass
  (4-string tab), drums (percussion staff, General MIDI notes of the engine), the pompe (6-string tab, naive
  fingering until the shape-based hand exists). Swing is written as straight eighths, as it is read; bars start
  at the chart's first beat (count-in removed) and stop at the form's length. Aligning them to the take's time is
  the grid's job.
- **alphaTab** (golem.fm's reader, 1.8.2, checked at render on 2026-10-17): a percussion note **must** carry a
  `<notehead>` (without one, kick and snare get a stem and no head); the second staff of a piano part must use
  voice 1, not 5 (voice 5 is drawn greyed as a secondary voice).
- **The hand** — `naive_fingering(pitches, max_fret=17, tuning=TUNING)`: for each pitch, high to low, the
  **lowest fret** on an unused string, with the instrument's tuning (`TUNINGS`, standard E). Mathematically minimal, musically wrong: an octave played
  `0 7 x 9 x x` (low E open, A 7, G 9) comes out as `0 x 2 x x 0` — the same three notes on other strings.
- **The bench** — `tools/check-tab-vs-gp.py` compares a transcription to a Guitar Pro reference (onset ±50 ms,
  exact pitch, then octave-tolerant; precision/recall/F1). It does **not** count string/fret.

Measured baselines that motivate the design:

- the ear is decent: on a test song, ~96 % of the reference pitches per bar are heard; a low-pass before the model
  changes nothing (a DI has almost nothing above 5 kHz);
- on a corpus of Guitar Pro files (42 six-string standard-tuning songs, ~117 000 notes), `naive_fingering` finds the
  reference string and fret for **54.8 %** of notes and **47 %** of whole chords; 13 % on the worst song; it puts
  23.5 % of notes on open strings where the files have 14 %;
- in that corpus 99.6 % of chords span ≤ 3 frets, none more than 4; the hand does not move in 45 % of transitions
  and moves ≤ 2 frets in 84 %.

## 2. Where a transcription belongs

- **The object is the take**: the DI, the playing. A transcription is redone, compared, thrown away; it belongs to
  a recording, **one per DI lane**. A long rehearsal is cut into one take per song when it is uploaded
  (`bridge/takecut.py`), so "a song played" is simply a cut take.
- **The context is the song**: its reference score, its sync map (hence the bar grid), each musician's part, and
  the fingering memory ("I play this one at the 7th fret").

| Situation | Takes | Started from | Read from |
|---|---|---|---|
| Take started with the backing (from 0) | one; song = `backing.slug` | the take | the take and the song |
| Long rehearsal | several, cut on upload | each take | each song played |
| Riff (Compo block) | one, no song | automatic ([`compo.md`](compo.md) §5) | the riff box, then the composer |
| Free take | one, no song | the take | the take only |

`take.json` already carries what the join needs: `backing.slug` + `played`, `people` (input → person), `roles`
(input → role), `bpm`, `marks`. One fact is missing: the backing position at the take's time 0
(`backing.offset_sec`). It is 0 by construction since takes start the backing at 0, but a residual of about
−0.15 s between DI and sync map was measured once; it must be explained (uncompensated input latency?) before it is
declared.

## 3. Who computes what

| Step | Where | Why |
|---|---|---|
| **Ear**: Basic Pitch → raw notes | rack | the DI lives there and leaves only on request; offline, low priority, no network |
| **Rules, hand, writing** (pure functions) | both, same module (§4) | the rack writes its own score (a riff must open the composer filled, even offline); golem.fm re-writes with what only it has |
| **Grid** (where bars fall) | wherever the played clock is | backing → the song's sync map (held by golem.fm); click → the rack's counter and the arrangement's meter; nothing → a tempo, and the score says so |
| **Review** (the guitarist's opinion) | golem.fm | a real screen, the person's account, per-song memory; the 1024×600 rack is not a score editor |

"golem.fm drives" means it decides (a button on the take, or an automatic rule), renders and runs the review. The
rack runs the ear on request through the existing job queue: a proposed action **`take-transcribe`**
`{uid, lanes}` → the rack transcribes (the `transcribe_jobs` queue) and uploads `notes.json`. The Rec block setting
stays the **local** trigger. Running the model on golem.fm instead was rejected: a rehearsal DI is heavy and not
uploaded by default, the "everything local" promise would break, an offline rack would get no score, and two ears
would have to be kept on the same model.

## 4. The hand module — one source, two executions

Same shape as `tools/classify.py` ([`gear-classifier.md`](gear-classifier.md)):

- **standalone**: standard library only, nothing from the bridge, no side effect on import. The pure part of
  `bridge/transcribe.py` (rules, fingering, MusicXML) moves into it; the model call stays on the rack;
- **`FINGERING_VERSION`** (integer), bumped whenever a **result** changes; written in every `notes.json` and sent in
  the heartbeat, so golem.fm can tell it is behind;
- copied to golem.fm by script, per release, never by hand;
- **the tuning comes from the setlist line** (`tuning`/`capo`), never from the `TUNING` constant.

### `notes.json` (proposed)

The raw truth: dated notes are the fact; bars and strings are a view, redrawn without listening again. Today
`scores/` only keeps MusicXML and the uploader does not send it.

```json
{
  "schema": 1,
  "engine": "golem-transcribe/1",
  "fingering_version": 1,
  "take": "perf-…",
  "lane": "Input-1", "person": "…", "role": "Guitar", "instrument": "guitar",
  "tuning": [40, 45, 50, 55, 59, 64], "capo": 0,
  "clock": {"kind": "backing", "slug": "…", "offset_sec": 0.0},
  "raw":   [{"t": 4.412, "d": 0.172, "p": 40, "c": 0.58}],
  "rules": {"in": 2005, "out_of_range": 12, "harmonics": 292, "kept": 1701}
}
```

- `raw` = model output before the rules: the expensive part (DI, model) is paid once; rules and hand replay anywhere.
- `clock.kind` = `backing` (+ `slug`, `offset_sec`) · `click` (+ `bpm`, the arrangement's meter per section) ·
  `none` (+ declared `bpm`). The grid is the clock the musician played against.
- It would be uploaded as a take track `kind: "notes"` (a new kind for golem.fm to accept).

## 5. The hand — how a guitarist chooses

A guitarist does not choose note by note: they pick a **shape**, and the hand **stays where it is**.

1. **Candidates.** For each group of simultaneous onsets, every playable placement: one note per string, fret 0–24,
   **span of fretted notes ≤ 4**. A note no placement accepts leaves the group, and that is reported (often a ghost).
2. **Cost** of a placement (weights are what gets calibrated, §7):
   - **hand movement** from the previous group, dearer when there is less time;
   - **stretch** between fingers;
   - **open strings**, penalized only when the hand is high (the open low E of `0 7 x 9` is right);
   - a **known-shape bonus**: skipped-string octave, power chord, barre, triads;
   - **string continuity** in a melodic line.
3. **The whole song at once**: dynamic programming (Viterbi) over the groups — the best **sequence** of positions,
   not the best isolated chord. ~800 groups × ~30² candidates: trivial even in pure Python.
4. **Doubt.** For each passage (between two hand moves), compare the best path with the best path playing that
   passage **elsewhere**. A small gap = a doubtful passage, which carries its alternatives.
5. **Constraints.** `(t0, t1, position | shape)` filters candidates in the window, then re-runs: one answer moves a
   whole passage.

Bass uses the same algorithm (4 or 5 strings, its own weights).

## 6. Review (on golem.fm)

On the take, **before** the score is sent to the composer (after that it is a band document and is no longer
rewritten from `notes.json`).

- Ask only about doubt, a few questions per take, heaviest first (notes involved × weakness of the gap).
- Show the alternatives as diagrams side by side with the DI at that spot (`[▶ Listen] [①] [②] [Other…]`).
- **An answer is a constraint**, not a note edit. Answers are data: stored on the take lane, reused as a prior for
  the next take of the same song by the same person, aggregated into a per-person hand profile, and each one labels
  the take (a dataset for the ear, built without manual annotation).
- Chord names above the staff (E5, A, G), computed from pitches: they help reading and absorb different voicings.

## 7. Calibration — two corpora, three scores

- **Corpus A — the hand, no audio.** Guitar Pro files give string and fret for every note: feed the algorithm the
  pitches only and compare its choice. Split **by song** (tune on some, check on others). Measure exact match **and**
  "same position ±2 frets", and look at the **worst** song, not just the mean.
- **Corpus B — the whole chain.** DI takes of songs that have a reference score (octaves and chords, clean
  arpeggio, single-note solo, palm-muted riff). The hand gets real pitches, mistakes included: one wrong note must
  not make the hand jump five frets.
- **Three scores, never merged**: notes heard · fingering · bars.

Acceptance for the hand: **beat `naive_fingering`** on the test corpus **and** write `0 7 x 9` on the octave case.
Learned models (pitch → tab) are measured on corpus A the same way; the explicit algorithm comes first because it
can say where it doubts and accept a constraint.

### 7.1 Measured — 2026-10-17 (`tools/check-fingering.py`, FINGERING_VERSION 1)

Corpus A: 69 distinct songs (the Guitar Pro 7/8 files of golem.fm, deduplicated **by title** — the same song
exists as several files), 205 guitar tracks, 193 000 notes, each track in its own tuning and capo; `.gp5` files
need a library this machine does not have and are skipped. Split by song: 40 to tune, 29 to check.

| Test set (29 songs, 79 000 notes) | notes exact | chords exact | position ±2 | open strings (truth 13.7 %) |
|---|---|---|---|---|
| `naive_fingering` | 52.9 % | 45.5 % | 49.4 % | 22.0 % |
| shapes, weights as shipped | **64.2 %** | **64.3 %** | **60.7 %** | 12.4 % |
| shapes, weights from `--tune` | 61.4 % | 58.1 % | 60.0 % | 19.5 % |

- `--tune` (coordinate search on the training set) reached 72.3 % there and **lost** on the test set: it
  over-fitted, mostly by shrinking `reach` to 0.75 fret (no more hand position) and `max_fret` to 16 (high solos
  unplayable). The shipped weights are the hand-set ones; a tuning is only kept if it wins on the **test** set.
- What the model learned from mistakes: a hand covers `reach` = 3 frets without moving (without it a scale jumped
  to the 12th fret); an open string **under** the fretted notes is a pedal, not a pull (the low E of `0 7 x 9`).
- In sequence, the gypsy shapes of Crooked Lantern come out exactly: Dm6 `x5x465`, Gm6 `3x233x`, A7 `5x56xx`.
- **Not met**: the octave case. Alone or in the Paper Kite riff (E → G → A → B over the open low E) the hand
  plays the octaves on D/B (`0 x 2 x 5`), the reference on A/G (`0 7 x 9`). Both are octave shapes; the corpus
  does not support a general preference for the lower pair (tuning even raised the D/B bonus). This is the case
  constraints are for (§5.5, "I play this one at the 7th fret"), not a global weight.
- Worst song: ~17 % (a Frusciante solo played high where the hand prefers low).

## 8. Work items

| Item | Content | Side |
|---|---|---|
| Measure | `check-tab-vs-gp` also counts string/fret; a `check-fingering` tool measures the hand on corpus A | rack |
| Hand | standalone module + `FINGERING_VERSION`, candidates, costs, Viterbi, shapes, doubt; replaces `naive_fingering`; tuning from the line | rack |
| Data | `notes.json` written and uploaded with the take (`kind: "notes"`, plus `score` for MusicXML); `take-transcribe` action | rack + golem.fm |
| Render, review | re-writing from `notes.json` with the sync-map grid; doubt questions, constraints, memory | golem.fm |
| Rack grid | click + arrangement meter for takes without backing | rack |

Open questions: should golem.fm ever run the ear itself when it has the DI (recommended: no, one ear); an automatic
trigger "when the take plays a song that has a reference score"; declaring "which part of the score is mine" per
song and person (useless to fingering, needed for comparison).
