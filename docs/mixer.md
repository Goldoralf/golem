# Output mixer — trims per source

> **Status: PARTLY CODED** — one trim and mute per source, applied hot on the REAPER hardware send and followed by the recording mix, is built for cards with one output pair; per-destination levels for multi-output cards and console (class 3) integration are not.

Goal: balance what leaves the rack (instrument lanes, backing, sample, drums, looper, click) against
each other, whatever the card, without the user needing to know which card they have.

## 1. Two stages, two owners

| Level | Where in REAPER | Owner |
|---|---|---|
| Scene level | track `D_VOL` (`scene.level`, `golem_rig`) | the **preset** |
| Mixer trim | **`D_VOL` / `B_MUTE` of the track's hardware send** | the **rig** (`config/mixer.json`) |
| Volume block (EXP pedal) | an FX on the guitar path, upstream | a playing control |

Rules that must not move:

- **Trims are rig state, not preset data.** A recall never touches them: your monitor mix does not
  change because the next song started.
- **The trim attenuates only.** Range −60…0 dB (`mixer.DB_MIN`, `DB_MAX`); 0 dB = unity, −60 = send
  at zero. Gain right before the converter brings back clipping.
- **The Volume block stays a playing control**, upstream; the mixer acts downstream on the send.
  Never two authorities on the same stage.
- **Recording DIs stay raw**: they do not go through the mixer.

## 2. Model

`bridge/mixer.py` — **sources × destinations**, even with one destination, because the recording
mix is a second (virtual) one.

**Sources** (`summary()`, derived, never a hard-coded list):

- one per assigned input of the card's input map: id `in<ch>`, label = instrument, sub = `IN <ch>`
  (+ person) — [input-map.md](input-map.md);
- the keys lane when a controller is bound: `in<midi_input_base>`;
- service blocks `backing`, `sample`, `drums`, `looper` (`SERVICE_SOURCES`, from `preset.config.gen`)
  — **all listed always**, `present: false` when the current preset lacks them: strips are greyed,
  never removed, since levels survive song changes;
- with a Standard block, **one strip per part it plays** (`std-keys` Piano, `std-bass`, `std-drums`, `std-guitar` —
  `STANDARD_PARTS`, sub « standard »): the Standard has its own tracks (`Standard Keys`… created by
  `golem_chordseq.lua`), trimmed on their hardware send like any service track. `golem_rig` re-applies them at each
  build (`MIXER_SERVICE_TRACKS`) and `golem_chordseq` applies the saved trim when it creates a track on the first
  play (2026-10-20 — before, the Standard had no strip at all);
- with a looper present, **one strip per loop** (`loop:<i>`): its level lives in the preset's looper
  table and is applied in the JSFX at playback (`/api/looper` op `level`), not in `config/mixer.json`
  ([looper.md](looper.md));
- `click`, always.

**Destinations**: the output pairs declared in the input map, plus **Rec mix** (`virtual: true`),
which follows the main mix.

**Storage**: `config/mixer.json` = `{"levels": {<source>: {"db": -6.0, "mute": false}}}` (local
state). Absent = 0 dB, not muted.

## 3. API and engine path

| | |
|---|---|
| `GET /api/mixer` | `{sources, levels, destinations, db_min, db_max}` |
| `POST /api/mixer {source, db?, mute?}` | one strip (`mixer.set_level`) |
| `POST /api/mixer {levels: {src: {db?, mute?}, …}}` | a linked group — **one** write and **one** command for the whole gesture (`mixer.set_levels`) |

Every change persists, then `mixer.push()` writes the command `{"action": "mixer_apply", "levels":
<all levels>}` (idempotent), which `golem_watch.lua` routes to `golem_rig.lua` `handle_mixer()` —
**no rebuild**, no undo block (a fader drag emits several times a second).

In `golem_rig.lua`:

- `mixer_tracks_for(src)`: `in<n>` → every track named `Sandbox #Input <n>` or a sub-track
  (`…/<branch>` **or** `…#merge`) that has a hardware send — on a split path it is the `#merge`
  track that carries the send. Services → fixed track names (`Backing Track`, `Sample`, `Drums`,
  `Looper`, `Click`). A missing track is not an error: the value applies at the next materialisation.
- `mixer_apply_track(tr, lv)`: sets `D_VOL` / `B_MUTE` on every hardware send of the track, **and**
  on its send to the `Recording` track (rec-follow). The PerfRec receive is post track fader, so
  without that copy the trim would never reach the take. The send destination is read natively
  (`P_DESTTRACK`), SWS `BR_GetMediaTrackSendInfo_Track` as fallback.
- After a rebuild, `route_monitor()` purges and recreates hardware sends; materialisation re-reads
  `config/mixer.json` (`read_mixer`) and re-applies the trims.
- **Probe**: action `mixer_dump` writes `presets/.mixerdump.json` (`{sends: [{src, track, hw_db,
  hw_mute, rec}]}`) — the real state of the sends; a log says what was intended, the probe says
  what REAPER holds. Read-only; used by `tools/check-routing.py`.

## 4. Screen

`/live` ▸ mixer button → `app/live-mixer.js`: one strip per source, attenuator faders, mute, absent
sources greyed.

**Grouping is not a mode**: each strip has a permanent link checkbox (it replaces the dB readout).
One checked = armed, its fader stays a normal fader. Two or more = coupled: moving one moves all by
the same delta, and a horizontal bar spans the gap between checked neighbours. The selection dies
when the mixer closes (an invisible persistent group is a trap).

**The delta is clamped, not the members**: clamping each member separately would crush the offsets
silently when one hits 0 dB. The common move is bounded so the group hits the wall as a block
(`−3 / −9` pushed up gives `0 / −6`). Since everything defaults to 0 dB, a fresh group can only go
down.

## 5. Card classes and doctrine

What decides the mixer is **the number of independent destinations the card delivers**.

| Class | Examples | Destinations | Who mixes |
|---|---|---|---|
| 0 — one pair | Volt 276, AudioBox iTwo, Scarlett 2i2 | 1 | golem, necessarily |
| 1 — two pairs | Scarlett 4i4, Volt 476 | 2 (room + one headphone mix) | golem |
| 2 — 4 to 8 outputs | 8×8 interfaces | 3–4 pairs | golem |
| 3 — digital console | XR18, X32 | aux buses + main | **the console** |

A headphone jack is usually **not** a destination: on entry-level cards it mirrors outputs 1–2. ALSA
gives the **number** of channels, never their **independence** — that must be declared in the card
descriptor ([gear-registry.md](gear-registry.md)), never guessed.

**Doctrine: golem only mixes what the hardware cannot.** Classes 0–2: golem mixes, one hardware send
per destination with its own volume. Class 3: the console mixes better and already has its app.

## 6. Not built

- **Per (source, destination) levels.** Today each source has one trim applied to all its hardware
  sends; the mute is per source. A multi-output card needs N sends per source (one per destination)
  with their own `D_VOL`, so that e.g. the click goes to every in-ear and never to the room.
- **Declaring output independence** in the card descriptor.
- **A decoupled recording mix** (today it follows the main mix).
- **Class 3**: send sources discretely and step aside, or drive the console over OSC — undecided.
- Per-source metering (`state.levels` covers guitar and voice only).
- Whether a preset or mode may *propose* a mix without imposing it.
