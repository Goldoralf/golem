# Arrangement — the song conductor

> **Status: CODED** (except the items listed in §14, which are PROPOSED) — the `arrangement` block, the cue
> engine in `bridge/arrangement.py`, what it starts with the song, its clock, its count-in, its sample lane and
> its screens.

Related references: [`preset-format.md`](preset-format.md) (block and scene shapes) ·
[`songs.md`](songs.md) and [`setlists.md`](setlists.md) (where the parts live) ·
[`bars-format.md`](bars-format.md) (the bar map of a backing) · [`live-pages.md`](live-pages.md)
(the Rehearsal and Concert pages, and the rehearsal gestures of the engine) · [`modes.md`](modes.md)
(service vetoes, click policy) · [`glossary.md`](glossary.md) ("cue", "loop", "advance").

---

## 1. What it is

A song is a sequence of **sections** (also called *parts* on screen) laid end to end. Each section
names a **scene** and may force some blocks on or off. The arrangement plays those sections in time
and applies their cues at each boundary. This is what playback rigs call *song sections + MIDI
cues*, done by the box that already makes the sound.

**The arrangement makes no sound. It sequences scenes.** The state hierarchy stays
Mode → Preset → Scene → Stomp ([`modes.md`](modes.md)). A scene already says what every lane does;
the section detail is a **reader** of the chosen scene with an "edit this scene" shortcut, never a
second place to define the sound. Scenes stay global to the preset: wanting "scene A for everyone,
B for the keys" means the scenes are badly factored, not that the model is wrong.

**A cue references a BLOCK, never a switch.** Section toggles are `blocks: {"<block id>": bool}`.
Reorganising the pedalboard then never changes the meaning of a song, and a block with no switch
can still be automated.

**Order at a boundary: the scene first, then the toggles** ("scene B, but delay off").
`app._arr_cue_core` recalls the scene (`recall.do_recall(None, scene)`), then sends the toggles as
**one** `stomp` command (`on_ids`/`off_ids`, `_route: rig_recall`): the command slot holds one
message, and two would race. The body runs on the recall executor (`recall.submit`), so the order
is kept and the asyncio loop stays free.

**What a section may force** (editor rule): the pedals of each lane, grouped by branch when a
branch carries pedals (`Guitar` vs `Guitar · dirt`). Not the amp or cab (choosing an amp is a
scene decision), not the system volume, not services. The engine itself accepts any block id the
preset has (`arrangement._block_ids`) and ignores unknown ids.

There is **no REAPER track** for the arrangement. It drives paths that already exist: the scene
switch without rebuild ([`live-engine.md`](live-engine.md)) and stomp toggles.

## 2. Where the data lives — rig, song, line

| Level | Holds | Stored in |
|---|---|---|
| **Rig** (preset) | the arrangement block: its `id`, its **switch** (`foot`) and the advance rule `params.advance` — never `sections` | `preset.config.arr.blocks[0]` (`type: "arrangement"`) |
| **Song** | the parts and everything about the song in time: `sections`, `sig`, `count_in`, `bars`, `live_view`, `starts`, `samples`, `samples_off` | the song sheet, `sheet.arrangement` ([`songs.md`](songs.md)) |
| **Setlist line** | only the evening's exceptions (a short festival version): a field listed in `line_overrides` | the line ([`setlists.md`](setlists.md)) |

What is played is recomposed by `recall.effective_preset(p)`:

- When the current song comes from a setlist line, `songs.line_sheet(line)` gives the song sheet
  overridden by the line's `line_overrides`; a line without `band_song` owns its own content.
- When ▶ Play starts a song from the Songs page without a line (`state.song.band_song`), the song
  sheet is read directly.
- `recall.merge_arrangement(preset, sheet.arrangement)` keeps the parts from the sheet and takes
  `id`, `foot` and `params.advance` from the rig block. Without a rig block, the sheet is used as is.
- The sheet's `bpm` replaces the preset tempo (the plan must count at the tempo REAPER plays), and
  its `backing` replaces the preset backing.
- **Outside a song** (a preset recalled on its own), `config.arr` is emptied: no automation. The
  screen says so (§12).

Writes from the rack declare their scope (`setlists.update_line(..., scope=song|line)`): fixing the
arrangement goes to the song, a "tonight only" change stays on the line.

Two one-shot startup migrations exist, both idempotent:
`arrangement.migrate_foot_to_rig()` (moves an old per-line pedal to the rig block, keeping the most
frequent one and logging a conflict) and `arrangement.migrate_stacks_to_starts()` (§6).
`setlists._legacy_arrangement` copies an old `preset.config.arr` to lines only if it has parts.

### 2.1 Shape

```json
"arrangement": {
  "type": "arrangement", "id": "arr-1",
  "bypass": false,
  "params": {
    "sig": { "num": 4, "den": 4 },
    "count_in": 1,
    "bars": 0,
    "live_view": null,
    "starts": { "backing": null, "click": true, "rec": false, "sample": null },
    "sections": [
      { "name": "intro",  "bars": 8,  "scene": "A" },
      { "name": "chorus", "bars": 8,  "scene": "B", "blocks": { "boost-1": true, "delay-1": false } },
      { "name": "bridge", "bars": 8,  "scene": "D", "sig": { "num": 7, "den": 8, "groups": [3, 2, 2] },
        "look": { "color": "#7a5cff", "anim": "" } }
    ],
    "samples": [ { "block": "sample-1", "idx": 0, "bar": 21, "beat": 1, "anchor": "land", "stop": "ring", "name": "riser" } ],
    "samples_off": false
  }
}
```

The rig block adds `foot` (switch number) and `params.advance` (`"bars"` | `"foot"`).

| Field | Meaning |
|---|---|
| `bypass` | **Automation off** for this song (the ⏻ on the Songs page and the dot of the Designer tile). `block_of()` ignores a bypassed block, so nothing plays. |
| `sig` | default meter of the song. A section's own `sig` overrides it (`section.sig → arrangement.sig → 4/4`). `groups` = accent grouping, must sum to `num` (checked in the editor). Bounds: `num` 1–32, `den` ∈ {1, 2, 4, 8, 16}. |
| `count_in` | bars counted before section 1 (editor: 0–8). §9. |
| `bars` | declared song length in bars when no backing gives it (0 = what is written). With a backing, the backing duration (or its bar map) wins. |
| `live_view` | what /live shows while the song plays: `null` (default: the Concert/stage board) or `"Pedalboard"` (keep the stomps, a pill is enough). Read by the engine snapshot and `app/page-live.js`. |
| `starts` | what starts with the song (§6). |
| `sections[]` | `{name, bars, scene?, blocks?, sig?, look?, samples?, drums?}`. `name` is free; the library offers intro, pre-chorus, verse, chorus, bridge, solo, outro. A section without `scene` keeps the scene that is playing. `drums` = the drum machine's groove for this part: an index into the `drums` block's `patterns`, or `"stop"`; absent = the groove of the part before (§6). |
| `look` | the part's colour and animation (§12). |
| `samples[]`, `samples_off` | the sample lane (§10). |

## 3. Meter and time

**The BPM always means the quarter note** (REAPER's convention):

```
pulse = (4 / den) × 60 / bpm        bar = num × pulse
```

7/8 at 120 → 0.25 s pulse, 1.75 s bar · 9/4 at 120 → 0.5 s pulse, 4.5 s bar.

**The click plays the section's meter.** `arrangement.click_meter(sec, base)` gives `{beats, den, groups}`
from the section `sig`, else the song `params.sig`, else nothing (the click keeps the line override, then
`config/click.json`); groups are kept only if they add up to `num`. The engine sends the next section's
meter **half a pulse before the boundary** (`ArrangementCtl._premeter`) — the JSFX recomputes its bar on
every block, so a meter that arrives during the outgoing section's last pulse makes the new downbeat land
exactly; arriving after the boundary would shift the whole section by one pulse difference. The count-in
uses the start section's meter; stop and the natural end give the normal config back
(`app._arr_click_meter`, laid over `_click_cfg`). The meter is pushed in song-click mode too (bar map): the
beats come from the notes, the accent groups from the section (§4, [`bars-format.md`](bars-format.md) §5).

Three quantities are never confused: **tempo** (the preset/sheet BPM), **meter** (`num/den`), and
the **pulse unit** heard (the eighth in 7/8, the quarter in 9/4).

**The same formula lives in three places** that cannot share code: `bridge/arrangement.py`
(`section_seconds`), `app/designer-arrangement.js` (widths and durations shown), and
`reaper/Effects/golem_click.jsfx`. They share a table, `tools/meter-cases.json`, and
`tools/check-meter.py` checks Python and the JS module actually served (in Chrome); `--rig` also
measures the JSFX by counting its pulses. Run it whenever one of the three changes.

Consequences:

- With mixed meters, "bar 33" is ambiguous. A position is `(section, bar in section, beat)`.
- The timeline is **proportional to time**, not to bars: eight bars of 7/8 are shorter than eight
  bars of 4/4. A section whose meter differs from the previous one carries a `7/8` badge.

## 4. One clock

The arrangement never counts for itself against what the musicians hear. `ArrangementCtl._song_time()`
returns the seconds since the first beat of section 1 from the **clock master**, published as
`arrangement.clock`:

| Situation | Master |
|---|---|
| The song started its backing and follows it | **`transport`**: `pos` published by `golem_backing.lua` in `.backing.json`, dated by the file's write time, extrapolated to now. A paused backing holds the arrangement; a jump back (double-tap restart, seek) by more than `REWIND_S` (0.5 s) re-aligns on the section the transport is in; a jump forward past the section end by `FORWARD_S` (0.6 s) too. |
| No backing, a stale state, or a backing that ended or was stopped elsewhere | **`server`**: wall clock, continued from the last estimate (no jump). |
| A perf-rec take is running | the backing starts but is **not followed** (`"free"`): `restart` does not rewind it during a take, so its position is not song time. |

The loop polls the transport every `CLOCK_TICK_S` (50 ms) and republishes the HUD bounds only when
the estimated origin moves by more than `HUD_SHIFT_S` (0.5 s).

**The bar map.** When the backing starts with the song (`starts.backing` is not `false`) and has a
valid `bars.json`, `plan()` and `sample_marks()` place each part and marker at the **real** time of
its bar (`bars.time_of`) instead of `bars × tempo`. A band recorded without a click has no single
tempo. See [`bars-format.md`](bars-format.md).

**The click stays aligned by construction.** At the first beat (`go`), `app._arr_click_song` turns
the click on, and the JSFX restarts on pulse 1 on its 0→1 edge. A click that was already running is
turned off at `start` so it gets that edge. With a bar map and beats really laid on the Click track
(`.backing.json` `songclick` > 0), the click plays the song's real beats (`song` mode,
[`bars-format.md`](bars-format.md) §5).

**Bar phase after a transport start or jump** (no bar map; 2026-10-15). The stems sit at position 0, so the
REAPER transport position (`play_position`, seconds) **is** the song time. With each meter, the engine sends an
**anchor**: where bar 1 of the current section starts on the transport — more exactly the start of the run of
consecutive sections in the same `num/den` (`arrangement.click_anchor`; whole bars of one meter give the same
phase, so the anchor changes only with the meter and costs no extra command). `app._click_cmd` carries
`anchor` on every click command (`-1` = none), `golem_click.lua` writes it raw to slider 14 as `anchor + 1`
(`0` = none). When the transport starts or jumps, the JSFX computes

```
steps = (play_position − anchor) × tempo × den × div / 240        index = steps mod (num × div)
```

i.e. pulses of `4/den` quarter notes since the section's bar 1. Without an anchor, or with the transport
**before** it (a perf-rec take started from 0 while the song starts from a later section), it keeps the old
quarter-note count from the project start. An anchor that **changes** during playback re-aligns too, only
(1) within 1 s of a detected start/jump (a seek the bridge sees afterwards: its corrected anchor arrives
100–400 ms later), or (2) when it arrives less than half a pulse after its own boundary (a late meter). A meter
pre-sent half a pulse before a boundary, or before a rehearsal jump, does nothing until the boundary or the
jump itself. Model and cases: `tests/test_click_phase.py`.

A **silent clock** exists (`POST /api/metronome {clock: true}` → `app._click_clock`): the click
counter runs with no sound, and with no mode veto, since "no sound" is not "no clock". The engine does
not need it today.

## 5. Advance rule and the foot

`params.advance` belongs to the **rig** (one rule for every song of the preset; the Songs page labels
it "shared"):

- **`bars`**: the cues fire on their own at section boundaries. Needs a clock (§4).
- **`foot`**: each tap goes to the next section. No counting, so no drift. `POST /api/arrangement
  {op: next}` is refused in `bars` mode (two masters for one thing).

In both cases the foot stays live: cues and the pedalboard write the same state, last one wins.

**One switch** (`foot` on the rig block), handled by `ArrangementCtl.on_edge` on Note edges:

| Gesture | Effect |
|---|---|
| tap, stopped | starts the song (count-in included) |
| tap, running, `bars` | stops everything the song started |
| tap, running, `foot` | next section; after the last section, stops |

The CC path (`_do_stomp`) yields this switch to the edges, as for sample and drum-machine switches,
so a tap never fires twice. The block is counted by the foot inventories (`store._foot_blocks`,
`preset_view._arr_blocks`, `designer-model.footBlocksOf`) and `arrangement` is in
`app.SERVICE_TYPES` (never an FX to toggle). Blocks placed on the same switch do **not** fire from the
pedalboard: what starts with the song is ticked on the song (§6), and the MIDI assign drawer says so.

## 6. What starts with the song — `params.starts`

The arrangement drives a **closed list** of blocks. A block outside this list never becomes "driven",
whatever is placed on its switch.

| Key | Block | The arrangement decides | The block keeps |
|---|---|---|---|
| `backing` | `backing-track` | starts from 0 (or from the start section) at the first beat, stops at ■ Stop; its transport is the clock | stem mix, its own switch for manual use |
| `click` | `click` | sounds from the first beat to the end of the song | level, output, meter |
| `rec` | `rec` | the take starts with the song and stops with it | destination, format, its switch for a free take |
| `sample` | `sample` | its markers fire (§10) | the sound list, its switch |
| `drums` | `drums` (the drum machine) | starts at the first beat on the groove of the start section; each section's `drums` picks the next groove, sent during the **last pulse** of the section before (`_predrums`, the same rule as the click's meter) so the JSFX — which switches at the next bar — lands on the boundary; `"stop"` stops it at the boundary; it stops with the song (■ Stop or the end) | its kit, its switch for manual use (a tap during the song stops it; the next boundary starts it again) |

Effects (scenes handle them), `looper` and `standard` are not on the list. **The drum machine joined it on
2026-10-20**: before, it ran free beside the song — two clocks, two gestures, the form written in two places
(its own "song mode" sequence). Now the song's form lives in one place, the arrangement; `drums.blocks(preset)`
finds the block (on a switch or not), `app._arr_drums` drives it through `DrumControl.song_play` / `song_pattern`,
and the mode veto `drummachine` holds. A section without `drums` keeps the groove playing (`drums_at`); with none
set anywhere, the first pattern plays. Factory example: « Golem Rising » ([factory.md](factory.md) §5.2).

`arrangement.starts_of(preset)` returns each key as `True`, `False` or `None` (never touched). `None`
keeps the default, the same in the bridge and in `app/designer-model.js` `resolveStarts`:
backing **yes**, click **if its block is active**, sample **yes** (if the preset has a sample block),
drums **yes** (if the preset has a drum machine), rec **no**. In the Designer, a part's groove is the 🥁 chip of its
sheet (a button per pattern of the block, « stop », « ↺ inherit »). A ticked block that is absent is said, not hidden ("no stems linked — Link",
"not in this preset — Add", the latter states its scope: "used by N songs").

Behaviour, in `bridge/app.py`:

- **Backing** (`_arr_backing`): only if a backing is loaded, it is the one the song declares
  (`_arr_backing_slugs`), and the mode allows `backing`. ■ Stop stops only a backing the song started.
  ▶ Play right after loading a preset waits up to 8 s for the deferred stem load, then refuses.
- **Click** (`_arr_click_song`): the tick decides; without a tick, the Click block decides
  (`_arr_click_want`). The mode veto applies (`_click_set`). Only what was taken is given back: a
  click that was playing before ▶ keeps playing after ■.
- **Record** (`_on_song` → `song_rec.decide`): the take starts at the **first beat** (`delay` = the
  count-in), with `countin=False` (one count-in: the arrangement's; the Rec block's count-in is for
  free takes). It **announces the backing** (`with_backing`), because a take starts the transport and
  `golem_perfrec` would otherwise mute an unannounced backing; the take's transport then plays it from
  0. Stopping during the count-in cancels the deferred take. A refused take (disk, mode) does not
  deprive the song of its backing. With `rec_scope: set` (Gig), the take covers the whole set and
  starts with the first line.
- **Click in `click_mode: preset`** (`_click_follow_preset`): when the loaded song has parts and does
  not untick Click, the click is silenced at recall and waits for the song's start. Nothing is touched
  while a song is running.
- **`click_mode: off`**: the Click tick stays (it is the song's intent), the state says "off in <mode>",
  the click does not sound. The count-in still does (§9).

**Migration** (`migrate_stacks_to_starts`, at startup): a Rec, Click or Backing block placed on the
arrangement's switch leaves the switch; each song of the preset (and each free line with its own
arrangement) gets the matching tick if it was never set (a manual tick wins). The Designer sandbox gets
the same edit. The report is `presets/.arr-stacks-migrated.json`, served by
`GET /api/arrangement/stacks-moved`; the Designer says it once per preset.

## 7. The engine — `ArrangementCtl`

One arrangement runs at a time. The class knows neither REAPER nor the routes: `bridge/app.py`
injects `apply_cue`, `apply_sample`, `on_change`, `click_hold`, `allowed`, `on_song`, `backing`,
`transport`, `click_song` and `backing_ctl`.

- **Planned, not polled.** `plan(preset, bars)` gives `[{i, name, at, dur, bars, scene, broken,
  blocks, samples, num, den}]`. `_run` merges sections, sample markers and an `end` event into one
  dated queue and sleeps until the next deadline (at most 0.1 s, so a cue posted meanwhile is seen).
- **Pre-armed samples.** The command path has ~30 ms of jitter (the REAPER `defer` tick;
  `tools/check-jitter.py --silent` measures it). Sample markers are emitted `PREARM_S` (0.35 s) early
  with `in_ms`, and `golem_sample.lua` fires them at the sample. The jitter becomes a margin.
- **`foot` mode**: the task applies the first section and ends; the rest comes from taps (`_live`
  stays true, so a tap advances instead of restarting).
- **Song end** is the end of the **last** section: `done`, `on_song("end")`, the song's click stops,
  a take "with the song" stops. The last scene holds and the backing tail is not cut. The song is then
  stopped (the next tap restarts it).

**API — `POST /api/arrangement {op, …}`** (`app.arrangement_action`; a *conductor* path,
`auth.CONDUCTOR_PATHS`):

| `op` | Body | Effect |
|---|---|---|
| `start` | `song?`, `from?` | Starts the current preset's song. With `song: <id>`: loads that song's preset if needed (`state.song = recall.song_of_song`, set before the recall so REAPER gets the sheet tempo), 409 while the rig is loading. `from: k` starts from section `k` ([`live-pages.md`](live-pages.md) §6.1). |
| `stop` | | stops the song and what it started |
| `next` | | `foot` mode only |
| `load` | | prepares the plan without playing (the stage board shows the structure) |
| `cue` | `index` (or `null`) | queues a section for the end of the current one |
| `loop` | `on` | loops the current section |

Errors are returned in English ("no arrangement in this preset", "the arrangement is off in this
mode", "not in foot mode"…). `cue`, `loop` and `start` with `from > 0` are rehearsal gestures, with
their own refusals ([`live-pages.md`](live-pages.md) §6.3 bis).

**Published state** (`state.arrangement` = `snapshot()`): `present`, `allowed`, `running`, `counting`,
`done`, `mode`, `live_view`, `index`, `count`, `marks`, `name`, `next`, `scene`, `broken`, `sig`,
`started_at`, `count_from`/`count_to` (count-in bounds), `sec_from`/`sec_to` (current section bounds,
server clock), `bars`, `parts[]`, `by` (who started it), `backing`, `clock`, `starts`, `bar_map`,
`cue`, `loop`, `loops`, `from`, `song_len`, `song_t0`.

## 8. The four behaviour rules

1. **An arrangement never crosses a preset change.** `recall.do_recall` stops it when the preset
   changes. Loading the next song arms it at bar 1, stopped.
2. **It repairs itself.** The scene is reapplied at **every** boundary: a scene forced at the foot wins
   now, the arrangement takes over again at the next section. (Rehearsal loop laps and jumps recall the
   scene only if it changes.)
3. **The last section holds.** No wrap to the intro under the last ringing chord, no silence.
4. **A section pointing to a missing scene does nothing.** `plan()` neutralises it (`scene: None`,
   `broken: True`) and the state carries `broken`. Unknown block ids in `blocks` are dropped the same
   way. Nothing is done rather than anything, and it is never silent.

## 9. Count-in

`params.count_in` = bars, 0 = none. `arrangement.count_in_seconds()`:

1. Its **duration** is counted in the meter of the **first section** (from a rehearsal start: the
   start section, at least 1 bar, 2 bars if a bar lasts under 2 s).
2. It is **always audible**, even in `click_mode: off`: `app._arr_click_hold` bypasses the mode veto on
   purpose. That is its only reason to exist.
3. With a backing, it **delays the transport** by its length. A backing that carries its own count-in
   is set to `count_in: 0`, which is why the setting is per song.
4. It exists in `foot` mode too: it is for starting together; after it, section 1 is active.

The Songs page HUD shows the count-in large, using `count_from`/`count_to`.

## 10. The sample lane

Markers live at an **absolute bar** of the song (`params.samples[]`), not inside a section: a riser
crosses a boundary.

| Field | Meaning |
|---|---|
| `block`, `idx` | which sample block and which entry of its full list (`sample.files_of`) |
| `bar`, `beat` | where (1-based); beyond the written sections, the base meter extends |
| `anchor` | `"land"` = the sample must **arrive** there: the engine subtracts its real duration. Otherwise it starts there. |
| `stop` | `"section"` cuts the previous sound of the block; anything else lets it **ring** |
| `name` | label |

- Durations are read by the rack (`arrangement.sample_seconds`: WAV header, cached on mtime). An
  unreadable duration falls back to "starts at".
- **Polyphony**: `golem_sample.lua` builds one RS5k per sample of a block. The foot is monophonic (one
  switch, each press cuts the previous); the lane sends `ring: true` so a riser keeps sounding under the
  impact. A sample cannot overlap **itself** (same note).
- A marker whose block or index vanished is ignored. `params.samples_off` mutes the whole lane;
  `starts.sample: false` mutes it for the song.
- **Song-only entries.** A sample block entry is a path (on the foot) or `{"file": "…", "foot": false}`
  (song only: the lane may fire it, the pedal skips it). `sample.switches()` returns the full list
  (which builds the RS5k, so indices stay stable) and `foot_idx` (what the pedal cycles through). Code
  that shows or compares entries must use the **path**, never `String(entry)`.
- The lane's "＋ from library" adds the sample to the block as `foot: false` and says so; an existing
  file is not duplicated.
- **Mode veto**: `app._arr_sample` does nothing when the mode cuts `sample`. The foot launchers are
  cut too (`state.sample_switches` is empty), at recall and at mode change (`routes_modes._re_veto`).

## 11. Mode veto

`arrangement` is a mode service (`bridge/modes.py` `SERVICES`). The mode says whether automation runs
in this situation, the song whether it has one. Factory defaults (`config/modes/*.json`): on in
Studio, Gig and Accompaniment; off in Rehearsal and Pedalboard. Editing stays possible in every mode.
`start` returns "the arrangement is off in this mode", and the Songs page header shows "⏻ Off in <mode>"
instead of the Automation button. The Arrangement row is visible in the mode editor (Settings ▸ Mode).

## 12. Screens

- **Songs page** (`app/page-repertoire.js` → `ArrangementPage` in `app/designer-arrangement.js`): the
  only place that edits parts. Header: ▶ Play · ■ Stop (`POST /api/arrangement {op: start, song}`),
  ⏻ Automation on/off, the HUD (count-in, NOW/NEXT, scene, progress in the section,
  elapsed/total, play head). The **"When the song starts"** row: count-in, one tick per driven block with
  a status line under it ("stems ✓ · bar map N bars", "on the song's beats · N bars approximated",
  "constant N BPM", "no stems linked"), then `switch N ▾` (grid 1–10, labelled "shared"), next part
  `bars | foot` ("shared"), song bars (without a backing), "on /live" `Stage board | Stomps`, and
  `Fit | Bars`.
- **Timeline**: sections end to end, widths proportional to time. **Fit** shows the whole song (no
  minimum width; a 2 px floor keeps a section visible, labels drop under 34 px). **Bars** uses a fixed
  width per bar with ticks, scrolls, and follows the playing section. The rest of the song (from the
  backing or `params.bars`) is drawn empty and clickable: a tap starts a section there. The header says
  "16 / 123 bars", or "⚠ 8 bars over" in red.
- **Section drawer** (fits 1024×600): name, bars, duration, the scene as one button per scene of the
  preset ("same" = nothing set, the previous scene keeps playing), signature and accent groups (one-tap
  `3+2+2`, `2+2+3`, `3+2`, `2+3`, `flat`; "⚠ 5 ≠ 7" when the sum is wrong), and the look inline.
- **Song grid**: one column per section, one row per block of the chosen musician (input), plus a
  "Song" row for the scene. A cell shows the block's **real** state at that section (explicit toggle >
  `scene.blocks[id]` > `scene.blocks[type]` > base `bypass`): **colour** = what the block does (green on,
  red off), **fill** = who decides (solid + capitals = the section forces it; dotted + lower case = the
  scene or the base). An inherited scene is drawn as a bar through the cell, never as a repeated letter.
- **Part colour is identity.** `designer-model.sectionLook(sec)` = `sec.look` > the default colour of the
  part name. The scene never colours a part, on the Songs page or on /live.
- **Designer ⚙** (`app/designer-arrlane.js`, its own lane, neither Global nor Players): a ▤ Arrangement
  tile (switch badge, no audio pins, long press = MIDI assign, tap = drawer `app/designer-arrsheet.js`),
  next to it the linked song (setlist · number · title · parts · duration · advance) and its strip. The
  tile's dot is the song's ⏻ Automation (it rewrites the song sheet, never the resolved line copy).
  Blocks the song starts get an outline and a ▤ badge ("started by the Arrangement with «…» — set in
  Songs"); the lane says "▤ drives the outlined blocks". The drawer edits only rig fields (switch, next
  part) and lists the songs that play the preset, each with "Open in Songs"; parts are read-only there
  (`app/arr-read.js`). Rig writes from any page go through `savePresetEverywhere` (`app/lib.js`).
- **Without its song**: the lane says "⚠ loaded without its song — sounds only"; /live shows
  "no song · sounds only — load it" next to the bank, and a tap loads the line with its song
  (`app/live-bankbar.js`), only when the line has something to lose.
- **/live** follows the player: while a song runs (count-in included), the Concert page takes the screen
  unless the song says `live_view: "Pedalboard"` ([`live-pages.md`](live-pages.md)).

## 13. Who writes it

Both the rack (by hand, offline, no account) and golem.fm (sections detected in the audio, placed
already) write the **same object**. There is no parallel runtime: at play time the only source is the
resolved sheet. A golem.fm cue import becomes sections in the sheet. The exchange is in
[`golemfm-protocol.md`](golemfm-protocol.md).

## 14. Not built (PROPOSED)

- **Click phase, remaining limits** (both former gaps are CODED, not yet heard on the rig: §4 "Bar phase…",
  [`bars-format.md`](bars-format.md) §5). Left: after an unplanned seek, the click plays up to ~0.4 s in the
  previous section's grid until the corrected anchor arrives; a perf-rec take started from a later section keeps
  the quarter-note count (its transport is not song time); the anchor assumes the project tempo is constant
  since the anchor (no tempo map).
- A **vamp / loop option** for the last section (rule 3 makes "hold" the only behaviour today).
- Free cues at a bar **inside** a section, repeat markers (×2, ×4) on a section, a meter change in the
  middle of a section (cut the section today).
- A badge when a drum-machine groove's meter differs from its section's (polymeter is allowed, never
  blocked).

## 15. Tests and tools

`tests/test_arrangement_foot.py`, `test_arrangement_practice.py`, `test_arrangement_rig.py`,
`test_arrangement_click_meter.py`, `test_click_phase.py` (click phase and song-click groups, EEL2 mirrored),
`test_arrangement_song_play.py`, `test_arr_stacks_migration.py` · `tools/check-meter.py [--rig]` ·
`tools/check-jitter.py --silent`.
