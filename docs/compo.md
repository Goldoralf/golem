# The Riff block (`compo`)

> **Status: PARTLY CODED** — the Riff block captures a short take of one person's lanes and sends it, with a transcription, to the golem.fm composer; free and armed captures, standard takes (§11), the bed of an armed take (§12), drop window, transcription and remote start/stop are coded; retro-capture and the long-press / double-tap gestures are PROPOSED (§9).

Related: [blocks-doctrine.md](blocks-doctrine.md) (service blocks, the global Rec),
[modes.md](modes.md) (services and vetoes), [devices-people.md](devices-people.md) (who plays which
input), [identity.md](identity.md) (persons and devices), [golemfm-protocol.md](golemfm-protocol.md)
(uploads, the follow uplink).

## 1. What it is

A riff is a different **kind** of take from a rehearsal session: short, one person, one idea, and its
destination is the golem.fm **composer**, not the archive. The block is distinct; the recording pipe
underneath is the Rec take.

- Block type **`compo`**, displayed **"Riff"** (flame icon). `comp` would read as "compressor" next
  to the Compressor blocks; the id `compo` never shows and stays in the protocol (`compo-target`),
  the mode service and `config/compo.json`.
- Catalog: `unique`, `scene_invariant`, `foot_scene_claim`, no audio in/out. It lives permanently
  in the Recorder config lane (`preset.config.rec`), next to the Rec block on the same row of the
  Designer's Global lane; it cannot be removed.
- **Global config** `config/compo.json` (machine state, not versioned), like Rec and Click; only the
  footswitch is per preset (`block.foot`). Hydrated / extracted by `store.migrate_config` /
  `save_recorder_cfg_from`; `store.load_compo_cfg`.

```json
{ "keep_s": 30, "transcribe": true, "foot_person": null,
  "persons": { "<person>": { "off": ["voice-1"] } } }
```

| key | meaning |
|---|---|
| `keep_s` | 15 \| 30 \| 60 — retro-capture length (reserved: not used until retro-capture exists, and hidden on screen) |
| `transcribe` | transcribe on the rack before sending |
| `foot_person` | who owns the rack's footswitch; `null` = the first input of the card (by channel) that carries a person, else the first bound USB port with a person (`compo.foot_person`) |
| `persons[p].off` | lane ids this person has unticked ("what Riff records"); default = all their lanes |

## 2. Author and lanes

- **The author** is the person of the **device** that triggers: the rack footswitch → `foot_person`;
  a Companion → its device's person; never a choice in a list while playing.
- **Their lanes** (`compo.lanes_of_person`) = lanes whose input carries that person in the current
  card's input map — numbered input `(role, nth)` first, else the physical input; a MIDI lane through
  its USB port — minus `persons[p].off`. Mirror in the app: `designer-model.lanesByPerson`.
- A guest has lanes like anyone else.

## 3. The gesture (coded)

**Tap = start a capture, tap = stop.** The start goes through the **Rec take path**
(`app._compo_tap` → `compo.tap(toggle=app._foot_perf_toggle)`): disk guard, mode veto, the Rec
block's count-in, delayed start on the REAPER side. A second tap during the count-in cancels
(nothing is written). Only the person recording (or the rack footswitch) can stop.

Triggers, all through the same function:
- the footswitch — a claimed switch (1–5) or a stomp (6–10) carrying the block;
- `POST /api/compo/tap {person?, source?}` (screen, Companion);
- golem.fm `compo-start` / `compo-stop` (§7).

**Refusals** (said, never a half take; stored in `state.compo.last.refused`):
Riff off in this mode · nobody owns the switch · the person has no lane in this preset · a take is
already recording ("stop it first") · recorder off in this mode · recorder on **Mix** (a riff needs
one track per input: `tracks` or `tracks_di`) · none of the person's inputs is recorded (Rec ▸
sources) · the armed target's space is full (`target.blocked == "quota"`) · for an armed take: the
backing service is off in this mode, or the backing is already playing.

## 4. Modes

Service `compo` in the mode service table (`modes.SERVICES`, `config/modes/*.json`): **on** in
Rehearsal, Home (`studio`), Jam (`accompaniment`); **off** in Gig and Pedalboard. The veto removes the block from
compile and foot and says so on the tile ("off in Gig"); the chip is in Settings ▸ Mode ▸ Tools.

## 5. The manifest

`take.json` is written by `monitors._take_manifest` and completed by `compo.stamp_manifest`:

| field | value |
|---|---|
| `kind` | `"riff"` — stamped at capture, never deduced from mode or duration |
| `by` | the author (person handle) |
| `drop_window_s` | 20 |
| `target` | `{id, mode, title?, band?}` copied from the armed target at **start**; a `target.band` this rack does not know (`takes.resolve_band`, `config/.band.json` → `bands[]`) → no target, `target_dropped: "unknown band"`, the take goes to the current space |
| `band` | the target's band if known, else the band frozen at start (take rule) |
| `lanes[]` | `{id, name, role, input, files: {di?, wet?, midi?, score?}}` — **declared**, never inferred from file names. `wet` (not `track`, which is a track *kind*) |
| `transcribe` | `done` \| `failed` \| `off` \| `unavailable` |
| `rig` | `{kind: preset\|patch\|trial, id, name}` — what it was played with, for information |
| `tempo_source` | `riff` (armed take) \| `preset` (free capture: the preset tempo, nothing says it was played to) |
| `title` | `Riff YYYY-MM-DD HH:MM` on a **free** capture only; an armed capture has no title (it enters that riff). The rack never invents a riff number |
| `bpm, sig, bars, passes, count_in, downbeat_s` | armed takes only (§6) |
| `loops` | loop mode only: loops **started**, indicative |
| `upload` | `{state: held, until}` → `transcribing` (`since`; due again after 20 min if abandoned) → `pending` → uploaded, or `dropped` |

**Drop window**: the rack holds the take **20 s before sending** (`compo.DROP_S`). `POST
/api/compo/drop {uid?}` (button on /live) sets `upload.state = "dropped"`: never uploaded, **kept on
disk**. There is no remote delete afterwards (someone may already have attached it to a song). After
20 s (`compo._settle`): transcription if `transcribe` is on and the engine is available
(`transcribe_jobs`, Basic Pitch — an armed riff's guitar or bass DI through the TX strategy, the click's grid read
from the take, [tablature-fingering.md](tablature-fingering.md) §1; `files.score` per transcribed lane), then immediate upload (not into
the pending-takes queue). A bridge restart during the window: the uploader's safety net sends it
later, without transcription.

**What is uploaded**: only the files declared in `lanes[]` + the manifest — no mix, no other
people's tracks (`uploader.prepare`). The score goes up as a track of kind `score`, one per lane. The
uploaded copy of the manifest names each lane file **exactly like its uploaded track** (golem.fm
pairs lanes to tracks by exact file name; no `/` allowed); the rack's local `take.json` keeps its
local paths. MusicXML is 4.0 partwise (`transcribe.to_musicxml`): tempo in a `<direction>` with
`<metronome>` + `<sound tempo>`, strings numbered from high E; sounding notes, no capo
transposition. Known gap: `staff-tuning` and fretting use a constant standard tuning (`TUNING`), not
the line's tuning.

An upload failure for a riff is published as `state.compo.riff_fail {why, uid, at}`
(`compo.note_upload`). Without golem.fm linked the riff stays on the rack and /live says so
("Riff kept on golem · link golem.fm ›").

## 6. Following golem.fm — armed targets

On a riff page of golem.fm, "Follow Golem" **arms** the rack for one person: that person's next
Riff tap writes into that riff instead of the unsorted strip. Arming is per person, lives **in memory
only** (`state.compo.targets`), and golem.fm resends active armings on every uplink reconnection — a
restart neither loses nor resurrects one. The checks on tuning and tempo at merge time are on the
golem.fm side.

**Command** on the follow uplink (`bridge/follow_uplink.py` → `compo.apply_cmd` → `set_target`):

```json
{"type": "cmd", "cmd": "compo-target", "person": "<handle>",
 "target": {"id": "rf:17", "mode": "append", "title": "…", "band": "…", "lane": "…",
            "bpm": 96, "sig": {"num": 4, "den": 4}, "count_in": 1, "bars": 8, "passes": 1, "click": "always",
            "space": {"free_bytes": 0, "quota_bytes": 0}, "blocked": "quota"}}
{"type": "cmd", "cmd": "compo-target", "person": "<handle>", "clear": true}
```

- `target.id` is **opaque** (≤ 120 chars), copied, never interpreted. `mode` = `append` (default) \|
  `replace`.
- **Armed take** (`compo.take_params`): with `bpm` **and** `bars`, a tap records over the riff:
  `bpm` 20–400, `sig` (default 4/4; num 1–32, den power of 2), `count_in` 0–4 bars, `bars` 1–512,
  `passes` 0–16 (default 1; **0 = loop until Stop**), `click` `always` (default) \| `count-in`, `tuning?` — the
  riff's tuning as 4 to 9 MIDI notes, read by golem.fm on the stored riff (agreed 2026-10-29): the rack picks the
  guitar whose profile has that tuning (`inharm.guitar_for`, the active one if several), never a profile name
  declared by the page; `take.json` gets `tuning` and `guitar` (`null` = no guitar of this rack has it: the tab
  uses the tuning, without calibration — [tablature-fingering.md](tablature-fingering.md) §1).
  An out-of-range value refuses the arming with the reason. Without `bpm` and `bars`: a free capture.
- /live and the person's Companion show the target ("armed from golem.fm (Follow Golem)").
- Probe without golem.fm: `POST /api/compo/target {person, target | clear}`.

**The click of an armed take is a file** (`bridge/riffclick.py`): the rack Click is a free-running
JSFX and a take starts on a command (~30 ms jitter), so nothing would tie the heard "1" to the first
recorded sample. The click is rendered to WAV (louder count-in, then the take — softer, or silent with
`click: "count-in"` — with the 1 accented; gains follow the Click block's level, `riffclick.gains`),
loaded into the **Backing** track, and the take starts **at 0 with the backing**: the first beat
falls at `downbeat_s` by construction. The project tempo is not changed. The take stops by itself
after count-in + `bars × passes` + one beat of margin (a tap stops it earlier); loop mode is capped
at `riffclick.LOOP_MAX_S` = 10 min and stops where it is — golem.fm keeps whole loops. One long take
even for N passes: golem.fm cuts at `downbeat_s + k × bars × bar_length`. The preset's backing
returns afterwards.

**`pos` frames** on the uplink carry `compo` during a capture, at file time (`compo.riff_frame`):
`{person, state: "loading"}` · `{state: "count", beat, beats, count_in}` (beats left) ·
`{state: "rec", bar, bars, beat, beats, pass, passes}` (`beat` within the bar; in loop mode `bar` /
`bars` are within one loop, `pass` = current loop, `passes: 0`) · `{state: "arriving"}` during the
drop window and upload · `{state: "refused", why}` for 6 s after a refusal. The page shows these
numbers and never runs its own clock.
Every frame of a capture on an armed target also carries `target_id` (the target's opaque `id`, as
sent): two pages can arm the same person, and the id says which target is running. A free capture has no
`target_id`.

## 7. Starting from the page

`{"type": "cmd", "cmd": "compo-start", "person": …}` / `compo-stop`, sent by the golem.fm
**server** (`compo.remote`). Extra guards on top of the foot's:
- `compo-start`: the person must be **armed**; never while a capture or a take runs; never in a
  locked mode (`mode.ui.locked`: "start at the foot");
- `compo-stop`: only the person recording; nothing running → refused.
Both go through `app._compo_tap`, so every rule exists once. Refusals come back in `pos` frames.

## 8. On screen

- **Designer** — the Riff drawer has two columns: on the left, **the Rec settings it depends on,
  read-only**, with a verdict per line (recorder allowed by the mode; format — Mix ✗, Multitrack
  "no DI, no score"; each captured lane's input recorded or not; count-in); the whole column is one
  button that opens the Rec drawer. On the right: the lanes per person, transcription, who owns the
  switch.
- **/live** — the Riff tile's footer says where the tap goes and what the take becomes (`riffNote` in
  `app/page-live.js`, since 2026-10-29): "→ <section> · <mode>" when armed ("→ N armed" for several
  people, "· storage full" when the armed space is full), "… Riff" / "● REC", "Saved · N s" with a
  **✕ Drop** button that keeps the touch for itself, "→ golem.fm…" while sending, "Riff dropped";
  otherwise the golem.fm link state. Only when the displayed bank has no Riff tile does the top bar show
  **one** compact chip (≤ 120 px) with the same information.
- **Companion** — the armed target card; tap through `POST /api/compo/tap` with the device's person.

State published in `state.compo`: `targets`, `last` (last tap report), `riff = {state: counting |
loading | rec | held | sending | dropped, person, uid?, until?, take?}`, `riff_fail`.

## 9. Not built (PROPOSED)

- **Retro-capture** (tap = keep the last `keep_s` seconds): during a take REAPER writes under
  temporary names and the take folder only exists at finalisation, so there is nothing to cut while
  the recorder runs. Intended: a marker in the running take, cut at its close (`takecut._slice`).
- **Long press** (start now) and **double tap** (drop) on the footswitch: the Riff switch reaches
  the bridge only as a CC (`_do_stomp`), which carries no duration; the Note edges
  (`_on_stomp_edge`) have no Riff branch. Drop is on screen only.
- Passing the line's tuning to `transcribe.to_musicxml`.

## 10. Tests and tools

`tests/test_compo.py`, `test_standard_take.py`, `test_modes_services.py`, `test_foot_claims_follow_edit.py`;
`tools/check-foot.py` (the gesture without the foot), `tools/check-transcribe.py`;
`tools/check-rig-materialize.py --standard-take N` (N standard takes in an isolated REAPER, the armed start
measured on each take's `Mix.wav`, budget 1 ms); `tests/test_compo_bed.py` and
`tools/check-rig-materialize.py --compo-bed N` (§12).

## 11. Standard takes

> **Status: CODED** (2026-10-26, agreed with golem.fm: `plan-standard-takes.md` §3 on their side). The armed start
> is **measured** in an isolated REAPER (`check-rig-materialize.py --standard-take`): the grid's first beat lands
> 8 samples (0.17 ms) after the Riff click file's, identical over every take, and the loop resumes after the
> count-in. Not yet played on a rack with a real instrument.

A person records **over a Standard** (the chart's rhythm section), for golem.fm's personal stems. There is no
new block: it is the same `compo-target` arming, with a standard target.

**Arming** (`compo.set_target` → `compo.standard_params`):

```json
{"type": "cmd", "cmd": "compo-target", "person": "<handle>",
 "target": {"id": "st:<n>", "mode": "replace", "title": "…", "band": "<personal space public_id>",
            "kind": "standard-take", "standard": "<slug>", "key": "Cm", "bpm": 140, "count_in": 1,
            "choruses": 3, "role": "bass", "parts": {"keys": true, "bass": false, "drums": true, "guitar": false},
            "click": "count-in", "space": {"free_bytes": 0, "quota_bytes": 0}}}
```

- `kind: "standard-take"` is **declared** by golem.fm and copied into `take.json`, never deduced.
- `mode` is `replace` | `add` — its own modes, not the riff's `append` | `replace`.
- `standard` must resolve on this golem (`standards.get_grid`), else the arming is refused with
  `standard not on this golem` (also in the `pos` frames). `key` is optional: absent, the chart's key.
- `bpm` 20–400, `count_in` 0–4 bars, `choruses` 0–16 (**0 = loop until Stop**, capped at
  `riffclick.LOOP_MAX_S`), `role` `guitar` | `bass` | `keys`, `click` `count-in` | `always`.
- golem.fm does not send `bars`: the rack unrolls **one chorus** with `standards.flatten(choruses=1)` (1st/2nd
  endings inside the chorus, every chorus identical, one meter per chart). The take is then a riff armed take
  (`riffclick.timing`) with `bars` = one chorus and `passes` = `choruses`.

**The lane.** `lane` is normally absent: the rack takes the person's one **on** lane whose role plays `role`
(`guitar` → `guitar`, `bass` → `bass`, `keys` → `keys`, `keys-pads`). None → `lane not in this preset`; several →
refused, naming them — the rack never picks one. A given `lane` must be one of the person's on lanes.

**Refusals at the tap** (`compo._standard_refusal`, plus the riff's recorder and quota checks): the mode cuts
the `standard` service; the backing is playing; the drum machine is playing ("stop it first" — the take starts at
0 with the Standard, and a second clock would drift). A drums or backing block present but stopped is no conflict,
and the Standard does not have to be in the preset: if the preset has a Standard block **on the same chart**, its
playing settings (`standards.PLAY_KEYS`, voicing, groove, kit, arp) are used; otherwise the defaults.

**The start is armed on the transport** (`app._std_take_start`, off the foot thread):
1. the chart is rendered for the take (the target's `parts`, key, count-in, `bpm` for the groove; with
   `click: "count-in"` the grid's click ticks stop at the first beat);
2. `{"action": "standard", "op": "play", "arm": true, "bpm": …}`: `golem_chordseq.lua` sets the take's `bpm` as
   the **project tempo** (grid, click, delays, arpeggiator) and arms the JSFX (op 2). The armed JSFX waits for the
   first audio block where the transport runs, and puts its playhead on the **timeline**
   (`play_position × tempo`). The take starts at 0, so tick 0 of the grid lands on sample 0 of the file and the
   first beat at `downbeat_s` — as the riff's click file does, with no command jitter;
3. the Click block is held on for the take (the grid carries its ticks; it gives the hand back afterwards);
4. the take starts without the Rec count-in (the count-in is in the grid).

A transport-bound grid stops with the transport, and loops back to the **end of the count-in**, not to 0. The take
stops by itself after count-in + `bars × choruses` + one beat; afterwards the grid stops and the preset's tempo
comes back (`golem_chordseq.lua` restores it only if it is still the take's: a recall in between wins). A start
cancelled while loading disarms the grid — otherwise the next transport play would start it.

**`take.json`**, on top of the riff fields (`by`, `lanes[]` — the one lane, `rig`, `bpm`, `sig`, `count_in`,
`bars`, `passes`, `downbeat_s`, `upload`, `drop_window_s`):

| field | value |
|---|---|
| `kind` | `"standard-take"` |
| `target` | the target **as golem.fm sent it**, plus `lane` = the lane the rack took |
| `standard` | `{slug, etag, key, semis, bpm, beats, feel, choruses, parts_heard, bars}`, merged into the `standard` every take over a Standard carries (`id`, `title`, `played`, and `seq` = `standard.seq`, the sequence played). `bars` is the **form of one chorus as played**: one list of (transposed) chord symbols per bar. `etag` is golem.fm's `golem_etag` of this chart, `null` for a chart from a song folder or the bundled corpus |
| `tempo_source` | `"standard"` |

golem.fm compares `standard.bars` with its own unrolled form; a mismatch arrives marked, never silently re-aligned.
It counts whole choruses in the **measured** length of the file. `pos` frames are unchanged (`pass` = the chorus,
`bar`/`bars` within it), counted from the take's start since there is no backing file. The `standard-take` relay to
the armed pages is golem.fm's own, at `/complete`.

## 12. The bed of an armed take

> **Status: CODED** (2026-10-27, agreed with golem.fm: `message-golem-compo-bed.md` §7 on their side — P6 of their
> `plan-player-editable.md`). **Measured** in an isolated REAPER (`check-rig-materialize.py --compo-bed 3`,
> golem.fm's 96 bpm test bed): the bed's first sample lands **0 samples** from the take's downbeat in `Mix.wav` on every
> take; gain −60 / −6 / 0 dB gives peaks −64.4 / −10.4 / −4.4 dBFS (the bed peaks at −4.4); a cached file that is not
> its sha is removed and the take refused; a take without a bed is silent after the count-in; the backing is unloaded
> after each take. Download, 404 and the cache: `tests/test_compo_bed.py`. Not yet played on a rack with a real
> instrument over a real golem.fm bed.

An armed take plays only the click. To record a riff **over the band**, the musician hears the song's other
instruments: a riff is **one** instrument (golem.fm, validated by the maintainer on 2026-10-29), and the bed is built
from the riffs the musician picks in golem.fm's Backing panel. golem.fm premixes them into **one FLAC file addressed
by its sha256**, and the rack plays it as a **second stem of the Backing, at 0** like the click file — the take's
first beat stays at `downbeat_s` by construction. The rack mixes nothing and knows nothing of what is in it: it plays
a file. (Until 2026-10-29 the bed was the other layers of the same riff; the contract below did not change.)

**Arming** — `target.bed`, additive on `compo-target` (§6):

```json
"bed": {"sha256": "<64 hex>", "bytes": 1184623, "length_s": 25.0, "gain_db": -6.0, "format": "flac",
        "offset_s": 0.0, "url": "/api/ext/compo/beds/<band public_id>/<sha>.flac"}
```

- The file: FLAC 16-bit stereo 48 kHz, peak ≤ −1 dBFS, already unrolled over `passes` — the `count_in` bars of
  music before the section, then the section × `passes`; `length_s = (count_in + passes·bars)·bar_s`.
- `gain_db` is clamped to **−60…0** (default −6), applied as the stem's volume. `offset_s` ≠ 0 is not supported.
- **Refusals of the arming** (`compo._bed_of`): a bed with `passes: 0` (`bad take: no bed in loop mode`) or on a free
  capture (`bad take: a bed needs bpm and bars`). Anything else the rack cannot play (offset, format, malformed sha
  or url) arms the target with `bed: "failed: <reason>"`: the screen says it before the tap, and the tap is refused
  with that reason. The rack **never falls back to the click alone**.

**Fetching** (`bridge/compo_bed.py`): on arming, a background prefetch — `GET url` with the device token
(scope `files:read`), then the bytes are checked (size, sha256, the FLAC's STREAMINFO length within 20 ms; no decoding)
and stored in `presets/.cache/beds/<sha>.flac` (~200 MB, least recently served first out). A cached file is
re-checked against its sha once per start and is served without network: the re-sent arming on reconnection and a
second pass cost nothing. One download per sha at a time.

**State before the tap**: the armed target carries `bed.state` = `ready` \| `fetching` \| `failed: <reason>`
(≤ 120 chars); `pos` frames carry `compo_armed: [{person, target_id, bed}]` for every armed target with a bed, and
the capture's `compo` frame carries `bed` too.

**At the tap** (`compo._armed_start`, the `loading` state): the rack waits for the bed (≤ 8 s); absent, the take is
refused with `bed not available: <reason>` in the `refused` frame. Present, `app._riff_armed_start` loads the click
(`drums`) and the bed (`other`) in **one** backing command; after the take `_riff_restore` unloads both and the
preset's backing returns. The other refusals are unchanged (backing playing, mode, no lane).

**`take.json`** copies `bed: {"sha256": "<the sha>"}` — what the take heard, nothing else.

**Heartbeat**: `caps.compo_bed: true` (`blockstatus.caps`) — golem.fm sends a `bed` only to a rack that publishes it.

