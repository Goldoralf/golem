# Standards

> **Status: CODED** — the Standard block plays a chord chart as a rhythm section (piano, bass, drums, click, and
> the manouche "pompe" rhythm guitar, §10) while the musician plays the tune; charts come from golem.fm or from
> song files. The pompe is CODED (2026-10-17), heard offline through sfizz, not yet heard on the rig.

Related: [standards-format.md](standards-format.md) (the `.gsx` chart format), [arrangement.md](arrangement.md)
(the form), [blocks-doctrine.md](blocks-doctrine.md), [golem-format.md](golem-format.md),
[song-folders.md](song-folders.md).

**The promise.** A standard arrives with its chart, key and conventional tempo. The rack plays the rhythm
section; the musician plays the head and improvises. "One tone lower" works instantly: **a chart transposes,
stems do not** — that is what this feature is for.

## 1. Engine

| Piece | Role |
|---|---|
| `bridge/standards.py` | **all the music**: symbol grammar, chart compilation, transposition, voicings, bass lines, comping, grooves, click and count-in rendering. Testable without REAPER (`tools/check-standards.py`) |
| `bridge/routes_standards.py` | catalogue, chart, preview, play/stop, grooves, sync, overlay |
| `bridge/app.py` `_standard_cmd` | foot/recall path: renders and sends the `standard` command |
| `reaper/Scripts/golem_chordseq.lua` | transport only: reads the rendered sequence, writes it to `gmem`, builds the tracks, sets the arpeggiator; publishes `presets/.standard.json` |
| `reaper/Effects/golem_chordseq.jsfx` | free-running PPQ clock, emits each event at its exact sample offset, note-offs, panic on stop; **armed** (op 2, a standard take, [compo.md §11](compo.md#11-standard-takes)) it waits for the transport and puts its playhead on the timeline, stops with it, and loops back to the end of the count-in. `ext_noinit`: a transport start no longer resets it ([pitfall](pitfalls/jsfx.md#init-runs-again-at-every-transport-start)) |
| block `standard` | `library/catalog/effects.json` |

Why this shape: ReaScript cannot inject MIDI into a specific FX instance (`StuffMIDIMessage` goes to a global
bus), and the command path jitters by one `defer` tick (~30 ms). So Lua fills a bank in `gmem` and a JSFX plays
it sample-accurately — the same pattern as `golem_drumseq`.

**Sequence file** `presets/.standard.seq` (text, written by `standards.write_seq`; a chorus is ~1500 events, too
many for JSON in the command):

```
v 1
len <ticks>      bar <ticks>      cin <count-in ticks>      nev <n>
<ppq> <note> <vel> <lane>          (vel 0 = note-off)
```

`PPQ = 960`. Lanes: `0` keys (`LANE_KEYS`), `1` bass, `2` drums (General MIDI notes), `3` click, `4` the pompe
(`LANE_GUITAR`). The JSFX `lane` slider goes 0–4 and is set with a **raw** value (`TrackFX_SetParam`), never a
normalized one: widening the range would otherwise have moved the click onto another lane. Note-offs are
produced by Python in the same sorted list and pulled back before the loop point; on stop, explicit note-offs
then CC123.

**Tracks** (created by `golem_chordseq.lua`): `Standard Keys` (sfizz + the Salamander piano), `Standard Bass`
(ReaSynth at −10 dB, under the piano), `Standard Drums` (avldrums: `black-pearl`, `red-zeppelin`, `blonde-bop`),
`Standard Guitar` (sfizz + Shinyguitar, two voices, −6 dB — §10). With the pompe and no piano the bass goes up to −4 dB: the pompe's accents masked it (by ear, 2026-10-17).
`Standard Drums` is separate from the drum machine's `Drums` track. All `golem_chordseq` instances read the same
`gmem` bank and latch the same nonce in the same audio cycle: they cannot drift apart.

**One clock.** Drums and click are events of the same sequence, not separate sequencers. Two free-running
sequencers at the same tempo are not in phase (30 ms of command jitter is audible), so:

- drums are rendered on lane 2 inside the chart — the block **conflicts** with the drum machine (`drums`) and
  with `backing-track` (a preset is one song: either a backing or a standard; and two drummers would clash);
- the **click** is rendered on lane 3 (note 76 = bar downbeat, 77 = other beats, 78 = subdivisions); a
  `golem_chordseq` instance sits in front of `golem_click` on the Click track and the click JSFX just sounds the
  notes it receives. The click follows the chart's meter (5/4 on a 5/4 tune) and covers the count-in. **It is
  rendered at compile time**: only if the metronome is on when the tune starts (`_click_div()` reads
  `presets/.click.json` and the click `div`); turning it on mid-tune needs a restart;
- the **count-in** (`count_in` bars) is two short high notes on the keys lane (the pompe if no keys, else the
  bass): note 96 vel 110 on the "1", note 91 vel 78 on the other beats — 83 and 78 on the pompe, inside the
  guitar's range.

## 2. The Standard block

Catalogue entry `standard` (category `utility`, engine `virtual`): `unique`, `scene_invariant` (the key does not
change at the chorus), `foot_scene_claim` (borrows one switch of the scene row), `conflicts: [backing-track,
drums]`. It lives in the **Players** service lane (`config.gen`, `CONFIG_GEN_TYPES`): it claims no input, it
makes one. It is inert at recall; the foot (or the screen) starts it.

Params (catalogue): `standard` (slug), `key` (`Original` or a key), `feel` (`auto` or a feel), `motion`,
`voicing` (`rootless | full`), `arp`, `keys` / `bass` / `drums` / `guitar` (parts, defaults true/true/false/false),
`pompe` (`auto` or a style, §10), `groove`, `kit`, `choruses` (1–16), `count_in` (0–2 bars), `live_view`
(`Chart | Pedalboard`). Playing settings written by the drawer are stored in the block params too and listed once
in `standards.PLAY_KEYS`: `size, style, register, density, anticip, move, passing, approach, bass_oct, ghost,
land, fill, pompe` — the foot reads them from the block, so it plays exactly what the drawer shows.

**No tempo in the block.** `preset.bpm` is the only tempo (pushed by `golem_rig` at recall, used by click,
delays, arpeggiator, grooves). The drawer shows the chart's usual tempo ("Usually played at 62 bpm") and offers a
button to copy it into the preset; that is all. Grooves are picked from the **preset** tempo
(`app._preset_bpm()`), not the chart's.

**The form belongs to the Arrangement**, not to the block: choruses, solos, intro, coda are arrangement
sections. The block carries the chart and the sound; a second sequencer for the form is refused.

**Mode veto**: service `standard` ([modes.md](modes.md)); `_standard_cmd` refuses to play when it is off, and a
mode switch stops a running standard.

## 3. Where charts come from

The rack has **no catalogue of its own**: it holds only what it received. `standards._load_raw()` merges, by slug:

| Source | Path | Notes |
|---|---|---|
| synced JSON (legacy) | `library/standards/synced/<slug>.json` | iReal or `.gsx`; envelope `_golem: {slug, synced_at, seeded}` |
| standards as `.golem` | `library/standards/golem/<slug>.golem` | chart = `chart/song.gsx`; slug = file name; **wins** over a synced JSON of the same slug |
| song folders | read in place | read-only; a slug the golem already has is skipped |
| song charts | `songs/<id>.golem` → `chart/song.gsx` | slug `song-<safe id>` (`standards.song_slug`) |

- A standard **arrives** through golem.fm's "Send to <golem>" (job `song-install`, category `standard`) or by
  adopting it from a song folder.
- `POST /api/standards/sync` (`golemfm.standards_sync`) only **updates** standards the rack already has when
  golem.fm announces another version (`golem_etag`); it never adds and never removes. With `{slug}` it fetches
  that one standard. `GET /api/standards/sync` lists what golem.fm can serve, crossed with the rack.
- Removing is a gesture on the rack (`DELETE /api/standards/synced/{slug}`, 🗑); the inventory then tells
  golem.fm.
- `tools/seed-standards.py` installs a few charts from `library/standards/jazz-standards.json` for development;
  they are marked `seeded` ("seed" badge). That corpus file is **not** a product source.
- `library/standards/` and `library/grooves/` are git-ignored (machine state).

`standards.catalog_ready()` is true when any synced JSON, standard `.golem` or folder standard exists; otherwise
`GET /api/standards` answers `ready: false`.

## 4. Charts: compile, never rewrite

Two input formats, chosen by **shape** (`standards.is_gsx`): `.gsx` (`v` + `sections` as an object —
[standards-format.md](standards-format.md)) or **iReal Pro JSON** (`Sections` as an array: `|` separates bars,
`,` separates subdivisions, an empty subdivision holds the previous chord, `(X)` = substitution shown not
played). Both compile to the same internal grid (`get_grid`): sections of bars of `{beat, len, sym, alt}` in
1-based quarter notes, plus `key`, `meter`, `beats`, `feel`, `groove`, `tempo`, `bars`, `order`, `play`.

iReal specifics:

- `Rhythm` is a **style label**, not a tempo: tempo comes from `TEMPO_BY_RHYTHM`, feel from `FEEL_BY_RHYTHM`,
  default groove from `GROOVE_BY_FEEL`. Conventions, never deductions.
- A chart without a key gets one inferred from the **last chord of the form** (`_infer_key`), flagged
  `key_inferred` so the UI says so — without a key there is no transposition.

**Overlay** (a correction without touching the source): `library/standards/local/<slug>.json`, written by
`PUT /api/standards/{slug}/overlay`. **Flat merge**: a key in the overlay replaces the compiled key (correcting
`sections` means giving them whole); `slug`, `v`, `source` are never overridden; the grid lists `patched` keys.
An empty body deletes the overlay.

**Symbol grammar** (`parse_symbol`) — closed, built from the corpus: root `A–G` with `#`/`b`; cores matched
longest first (`m/maj7` and `mmaj7`, `maj13/9/7`, `m7b5`, `m11/69/9/7/6/b6`, `maug`, `m`, `dim7`/`07`, `dim`/`0`,
`aug`, `add9`, `alt`, `69`, `13/11/9/7/6/5`, major); alterations `b5 #5 b9 #9 #11 b13 #13` applied after the
core (adding the degree if absent); `sus`/`sus2`/`sus4` replaces the third with the fourth; `/bass`;
`N.C.`/`NC` = silence. Pitfalls handled: `m/maj7` is normalised **before** any slash logic (it is not a bass);
`7alt` = b9 #9 b13 without a fifth. An unreadable symbol returns `None` and is reported in the render's `unknown`
list — never approximated.

**Transposition** (`flatten`): the shortest interval between the chart key's tonic and the requested key; endings
are unrolled (ending *k* replaces the section tail on pass *k*).

## 5. Rendering (`standards.render`)

`render(grid, key, feel, motion, parts, choruses, click_div, count_in, rootless, groove, groove_take, bass_mode,
bpm, size, style, register, density, anticip, move, passing, approach, bass_oct, ghost, land, fill)` returns
events `(ppq, note, vel, lane)` plus `bars` (symbols per bar, for the stand and phones), `semis`, `feel`,
`unknown`, `fills`, `count_in_ppq`. **Without settings, the render is the historical one, byte for byte**, and
every setting must change something — both checked by `tools/check-standards.py` on three charts of different
feels (several settings only act on swing/even).

### 5.1 Motion

| `motion` | Sound |
|---|---|
| `block` | plain block chords (to study a chart) |
| `comp` (default) | rhythmic comping patterns per feel (`COMP`) |
| `arp` | the chord **held**; the `midi_arp` JSFX animates it |
| `arp+bass` | the same + bass line |

### 5.2 Piano

Voicings are **tabular, never generative**: rootless (the bass plays the root) with voice leading — common tones
stay, others move by the smallest interval (`voicing_pcs`, `place_voicing`).

| Setting | Values |
|---|---|
| `size` | `as-written` (default) · `triad` · `7th` · `9` · `9-13` · `alt` |
| `style` | `rootless` (default) · `shell` · `drop2` · `full` |
| `register` | `low` · `mid` (default) · `high` |
| `density` | `auto` (from the feel) · `1` · `2` · `4` · `charleston` · `sparse` |
| `anticip`, `move`, `passing` | anticipations, inner-voice motion, passing chords |

Harmony rules (`size_ints`): sizes start from the **written** intervals (so `E7alt` keeps its b9/#9/b13);
`alt` applies only to dominants (elsewhere it renders as `9-13`); the major third wins over the minor one (a #9
is not a minor third); a tension a semitone **above** a chord tone is refused (avoid notes), a semitone below is
fine.

### 5.3 Bass

`bass_mode`: `auto` (from the feel, or the chart's `play.bass.mode`) · `walk` · `roots` · `two` · `root5` ·
`pedal` · `bossa`; `approach`: `chromatic` · `diatonic` · `none`; `bass_oct`; `ghost` (ghost notes, velocity
`GHOST_VEL = 44`); `land` (re-anchor low on the root). The `root5` fifth goes **up**; `pedal` holds the **tonic**,
not the chord root.

### 5.4 Drums

- **Written grooves** (`GROOVES`, swung by `_swing` like the chords) — always available.
- **Played grooves** from imported MIDI packs (`library/grooves/packs.json`, built by
  `tools/import-drum-packs.py`): `groove` names a **family** (`jazz/walk/sticks`), never a file. The take
  closest to the **preset** tempo is used (`pack_pattern`), or a specific take (`groove_take` = its tempo); a
  vanished take falls back to the nearest. Unknown family, no pack, or a meter mismatch (a 4/4 groove under a
  waltz) → the written pattern. Velocities are scaled by one factor so the pack's peak equals `VEL_CEIL = 92`
  (never scaled up). Notes are remapped to General MIDI from the pack's own kit map.
- **Fills** (`fill`: `off` · `8` · `section` · `chorus`) come only from packs (`pack_fill`: the last bar of a
  fill file). When no fill can be placed (no fills in the pack, a one-section chart), the render reports how many
  were placed — the drawer greys the option with the reason.

### 5.5 Arpeggiator

`arp` (`Off`, `Up 1/4`, `Up 1/8`, `Down 1/8`, `Up-Down 1/8`, `Up 1/16`, `Up-Down 1/16`, `Up 2 oct` — gentlest
first) inserts REAPER's `midi_arp` before the instrument. Its `Velocity` slider is set to **0** ("use played
velocity"; its default 127 forces maximum velocity), and held notes are sent at a calibrated velocity. The same
`ARP_CONFIGS` table exists in `golem_chordseq.lua` (standard) and `golem_rig.lua` (`ARP_TYPES` = `vital`,
`piano`, `ep`, `organ` blocks of the rig). In the rig, the arp is placed **after** the note-zone (arpeggiate
what the zone lets through), found by a **parameter** name (`Rate (x BPM)`) because `tag_fx` renames FX to
`golem:<id>`, inserted **last** in materialisation (an insertion shifts FX indices), and never inserted on a
scene switch (`no_insert`: reconfigure only).

## 6. The foot: one switch, three gestures

`standards.StandardControl` (edges from the foot controller):

| Gesture | Effect |
|---|---|
| tap while stopped | PLAY |
| tap while playing | STOP |
| hold ≥ `RESTART_S = 1.2` s while playing | restart from the top |

No variation/fill gestures: the form belongs to the arrangement. Rendering happens in the bridge
(`_standard_cmd`), not in the foot thread. The controller is optimistic (the LED answers at once) and is
reconciled with the Lua witness `presets/.standard.json` (`monitors._poll_standard` → `apply_feedback`).
`standards.switches(preset)` lists foot-assigned blocks; `standards.block_of(preset)` returns the block whether
or not it has a switch.

## 7. Endpoints

| Route | Effect |
|---|---|
| `GET /api/standards?q=&limit=&synced=` | `{ready, standards[meta], total, synced}` (factory-marked) |
| `GET /api/standards/{slug}` | compiled grid (+ overlay) |
| `POST /api/standards/{slug}/preview {key, feel, motion, groove, groove_take, parts, choruses, count_in, voicing, bpm}` | render without playing: transposed bars, event count, `unknown`, fills, a two-bar piano-roll (`roll`) |
| `POST /api/standards/play {standard, key, feel, motion, groove, groove_take, parts, choruses, count_in, voicing, bpm, play, arp, kit, loop}` | compile, render, write, send `{action: "standard", op: "play", file, …}`; returns the **effective** parts (track mutes must follow them) |
| `POST /api/standards/stop` | stop |
| `GET /api/standards/state` | the player's witness |
| `GET /api/standards/grooves?meter=`, `/grooves/tree` | played-groove families; tree pack › style › kit › takes |
| `POST /api/standards/grooves/audition {family, bpm, bars, meter, fill, kit}` | play one take (drums only) **without changing the block** |
| `GET/POST /api/standards/sync`, `DELETE /api/standards/synced/{slug}`, `PUT /api/standards/{slug}/overlay` | §3–4 |

Fixed routes are declared **before** `/{slug}`, which would capture them.

## 8. UI

- **Library ▸ Standards** (`app/page-standards.js`): cards whose thumbnail is the SHAPE of the chart (32 bars, one height per chord), with ⚡ the presets that use it (`/api/presets` exposes `standards`).
- **The drawer** (`app/designer-standard.js`): a strip of standards, then one selector
  `Song · Piano · Bass · Drums · Guitar` (the grid is the right half of the Song tab; a green dot = that part plays,
  a part switched off greys its tab). The drums panel is a pack browser (tree + takes with ▶ audition). A
  two-bar piano-roll preview shows what the settings produce. The grid follows playback (current bar scrolled
  into view, "bar n / N"). The chart render is shared with the Library page.
- **/live**: a playing Standard shows its chart (`ChartLive`) unless the block says `live_view: "Pedalboard"`;
  stopping gives the pedalboard back. Decided on `state.standard_block` (`block_of`), not on foot switches, so a
  standard started from the screen still gets its chart ([modes.md](modes.md) §4.1).

## 9. Out of scope

| | Why |
|---|---|
| "intelligent" accompaniment generation | deterministic, correctable tables over models |
| a tempo in the block | `preset.bpm` is the source |
| the form in the block | it is the arrangement's |
| a **lead** guitar | the guitarist is the player |
| melodies and lyrics | charts only |

## 10. Manouche rhythm guitar ("pompe") — CODED

In gypsy jazz there is no piano or drums: the rhythm guitar *is* the rhythm section. Rule: **rhythm guitar yes,
lead guitar never** — the guitarist is the player.

**Line-up** (drawer, Song tab): `Combo` (piano · bass · drums) · `Manouche` (pompe · bass) · `Custom` (any parts,
Guitar included). A line-up is only a set of parts (`keys`, `bass`, `drums`, `guitar`); picking a standard whose
style is `manouche` (or "gypsy") switches to `Manouche`. The factory chart Crooked Lantern carries
`play.parts = {keys: false, bass: true, drums: false, guitar: true}`. With the pompe and no piano, the bass
defaults to `two` (roots on 1 and 3: pompe and bass lock together) unless the block sets a pattern.

**Rendering** (`standards.pompe_events`, lane 4):

- strum **spread** 12 ms between strings (20 ms in `ballad`), low to high on a down-stroke, high to low on an
  up-stroke — three notes on one tick is an organ;
- note **length** as groove, in milliseconds (a muted stroke lasts as long as the left hand, whatever the tempo):
  45 ms on 1 and 3, 120 ms on 2 and 4 (the "dry" render, chosen by ear on 2026-10-17);
- **accent** on 2 and 4: velocity 58 vs 122, minus 4 per string (the first string hit is the loudest).
- **styles** (`pompe` param): `pompe` (4 strokes), `pompe-fast` (2 and 4 only), `ballad` (half-beat notes,
  softer), `valse` (1 muted, 2 and 3 ringing), `bolero` (1 · 2-and · 3 · 4), `rumba` (3-3-2), `bossa` (a two-bar
  figure). `auto` (`pompe_style`): `valse` in 3/4, `bossa` on a bossa feel, `rumba` on latin, `ballad` on ballad,
  `pompe-fast` from 230 bpm (the **preset** tempo), else `pompe`.
- **shapes** are a table (`pompe_shape`), never generated: 6 (or 6/9 when the 9 is written) instead of maj7, m6
  for minor triads (Dm6 = x5x465), dim7 placed on the b9 for a dominant b9 (A7b9 = Bbdim7, the bass keeps the
  root), no fifth on dominants (A7 = 5x56xx), the root **played** on the low strings (E2–Eb3).

**Sound**: Shinyguitar (Karoryfer Samples, an archtop recorded with a microphone and a pickup, **CC0**, fetched
in its own `guitar` pack, pinned in `downloads.sha256`: `provision/fetch-assets.sh` on Linux,
`installer/desktop_steps.py` on Windows and macOS — same URL, same checksum; it lives in `library/sfz/`, inside the
install folder, so the uninstaller removes it with the folder). `golem_chordseq.lua` writes
`library/sfz/golem-pompe.sfz`, a wrapper that keeps the microphone only (`cc100 = 127`; its `main.sfz` starts
on the pickup and low-passes at 1250 Hz) and the **two-voice** program (`cc107`): two different takes per
note, spread left/right (`cc108 = 70`) — that is the doubled, panned track of the contract, inside one sfizz.
Its velocity layers map to level: measured offline on the engine's own render of Crooked Lantern, **+7.5 dB**
between beats 2-4 and 1-3 (a stock patch measured +0.1 dB on a prototype — the accent disappears). sfizz is
loaded as LV2 on Linux (a `P` line in the track chunk) and as VST3 on Windows and macOS (its `sfzFile` in the VST3
state, `sfizz_load` picks by `fx_type`) — the Windows/macOS path is copied from `golem_drums`, measured there on a
bench REAPER, not yet heard with the pompe. A recorded pompe stem is refused (it cannot transpose).

**Scores.** A take recorded while a Standard plays keeps the played sequence (`standard.seq`), and its parts are
written as exact scores by the transcription job ([`tablature-fingering.md`](tablature-fingering.md) §1).

**Not verified on the rig yet**: the level against the bass (`D_VOL` 0.5, from the offline peaks), and that the
new track wakes up like the others (it is armed, `I_RECMODE = 2`).
