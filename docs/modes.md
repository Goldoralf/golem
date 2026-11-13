# Modes

> **Status: PARTLY CODED** — machine modes (data profiles that veto services and inputs, shape the UI and the
> Live view) are coded in `bridge/modes.py` and `bridge/routes_modes.py`; the band multitrack recorder of the
> Rehearsal mode (§8) is PROPOSED and not built.

A **mode** is an attention contract: "in this situation, this is what is mounted, this is what I can touch,
and nothing I touch can break the set." It belongs to the **machine**, not to the preset: it is persisted in
`config/.mode.json` (git-ignored) and restored when the bridge starts. See the **Mode** entry of the
[glossary](glossary.md) for the other meanings of the word.

## 1. A mode is data, not code

A mode is a declarative profile in `config/modes/<id>.json`. It **filters what is mounted**; it never changes
what the code knows how to do.

- No `if mode == …` in the bridge, the Lua or the app. Every behaviour a mode changes is read from a field
  (`services`, `ui.live`, `rec_scope`, `click_mode`, `perf_boost`…). Adding a mode never needs code.
- Modes are **subsets**, never different business logic.
- A preset is never invalid in a mode: it is *partly mounted* (§3).

State hierarchy, from the slowest and most expensive to the cheapest:

```
Mode    (re-veto + possible rebuild — changes when you arrive somewhere)
 └─ Preset   (rebuild — changes between songs)
     └─ Scene    (state switch, no rebuild — changes inside a song)
         └─ Stomp    (instant toggle)
```

A mode switch may take seconds. Switching modes in the middle of a song is not a goal.

## 2. Factory modes

Shipped in `config/modes/*.json`, sorted by `order`. The id is the stable technical key (persistence, local
overrides, take tags); the `name` is what the UI shows.

| id | Displayed name | Situation (`desc`) | Tools off | `ui.pages` | `ui.live` | `click_mode` | `perfrec_mode` | `take_kind` | Other |
|---|---|---|---|---|---|---|---|---|---|
| `pedalboard` | **Pedalboard** 🎸 | One-instrument rig — "the mode where nothing can go wrong" | **all** services `false` (voice, keys, pads, looper, backing, perfrec, sample, arrangement, standard, drummachine, compo, drums) | all | — (→ `pedalboard`) | `off` | — | `rehearsal` | |
| `studio` | **Home** 🏠 | Everything on — the full rig at home (default) | none | all | `pedalboard` | `manual` | `manual` | `rehearsal` | `DEFAULT_ID` |
| `accompaniment` | **Jam** 🔁 | Play along: backing, standards, drum machine drive the session | `looper` | all | `timeline` | `preset` | `manual` | `rehearsal` | |
| `rehearsal` | **Rehearsal** 🥁 | Rehearsal studio — your rig + band recorder | — | all | `rehearsal` | `manual` | `auto` | `rehearsal` | |
| `gig` | **Gig** 🎤 | On stage — locked UI, the take covers the whole set | `compo` | `["live"]` | `timeline` | `preset` | `manual` | `gig` | `ui.locked: true`, `rec_scope: "set"`, `perf_boost: true` |

**Rehearsal keeps the arrangement on** (2026-10-21). Its Live screen is the Rehearsal page, whose gestures
(start from a section, cue, loop) run through the arrangement engine; with `arrangement: false` the factory mode
refused its own page's main button ("the arrangement is off in this mode" — replayed on a disposable bridge).

All five ship `ui.boot: "live"`. Four ship `foot_list: "factory"` (the "Factory Golem" setlist of whole songs);
**Pedalboard ships `foot_list: "@instrument"`** — see below. Factory modes declare **no** `card` and **no**
`band`: a sound card or a space is a local fact, never a seed — those fields live only in the local overlay.

**Pedalboard puts the player's sound bank on the foot (CODED 2026-10-24).** A Windows tester entered Pedalboard
("one-instrument rig") and got "Factory Golem" on the foot — whole songs with drums, keys and voice, in a mode that
turns all of those off. He picked "Factory Guitar" by hand, then opened a song preset from the Designer, which is not
in that bank: no ◀ ▶ on /live, no word why. The one-instrument mode now names the **sound bank of the instrument**:
`"@instrument"` resolves, when the mode is entered, to the factory sound bank of the **first input given a role on
the active card** (input map, in channel order): guitar → `factory-guitar`, bass → `factory-bass`, voice →
`factory-voice`, keys → `factory-keys`, drums → `factory-drums`. No role on the card, another role, or that bank
missing → `factory-guitar`; if that one is missing too, the foot keeps its list and says so, like any missing
`foot_list` (`modes.apply_foot_list`). `@instrument` is accepted wherever a `foot_list` is (mode editor, golem.fm
`mode-set`); a list id stays a list id.

Display names differ from ids on purpose: `studio` shows **Home**, `accompaniment` shows **Jam**. Always
reason on ids in code.

## 3. The veto: effective = preset ∧ mode

### 3.1 Services

`modes.SERVICES` = `guitar, bass, voice, drums, line, keys, pads` (inputs and controllers, the vocabulary of
the input map) + `looper, backing, sample, perfrec, arrangement, standard, drummachine, compo` (software
tools). `drums` is the **drum input** (mics, e-kit); the drum machine is `drummachine`.

- `modes.allows(service, mode)` — a service **absent** from the mode is **allowed**. That is why a new mode
  is always created *from* an existing one (§5): a blank mode would be Home under another name.
- A vetoed tool is not offered in the "Add service" drawer, a placed tile says "Off in <mode>", it gets no
  foot switch and no Live tile. Editing stays possible everywhere: you build at home, you play on stage.
- `routes_modes._re_veto()` applies the veto **at the switch**, without waiting for the next recall:
  looper/backing/sample/drum-machine/standard switches are recomputed, a running drum machine or standard
  is stopped, the click policy (§4.3) is applied, and the rig is re-emitted
  (`recall.submit(recall.emit_sandbox, …)`) because an input veto changes the topology.
  Fixed 2026-10-24: the running drum machine was never stopped — `stop_orphans` received `True` instead of the
  blocks REAPER reports playing (`.drums.json`), raised "'bool' object is not iterable" on every mode edit, and the
  standard stop that followed in the same `try` was skipped too. The playing blocks are now read from the report
  (as `/api/drums/stop-all` does), and the drum machine and the standard are stopped independently.

### 3.2 Inputs — per lane, per numbered input

`recall.input_veto(preset)` returns the keys of the lanes the mode unmounts. A vetoed lane is **not mounted**
by `scene_bake.to_paths_preset` (like `IN/OUT NONE`), but it is **never removed** from the preset.

A lane is vetoed when:

1. its **role** is vetoed (`services[role]` false; `keys-pads` falls only if both `keys` and `pads` are off),
   **or**
2. its **numbered input** is in the mode's `inputs_off` list — keys `"<role>#<n>"`, e.g. `"voice#2"`
   (`modes.input_key`, `modes.input_allowed`). The lane is identified by its `(in_role, in_nth)`, or else by
   the input-map entry its `in_sel` points to (an audio input, or a rack USB port for a MIDI lane).

The mode never binds a **port**: it cuts a numbered instrument ("Guitar 2", "Voice 1", "Keys + Pads 1"), which
follows the input map of the card in use ([input-map.md](input-map.md)). The input map is read from the card
file (`store._imap()`), the same source `lanes_of` uses.

**A sound with nothing left to mount says why (CODED 2026-10-24).** A Windows tester tapped through the Inputs
row of Pedalboard; every guitar sound was then refused with « preset sans 'paths' » — French, on screen, and no hint
that the mode had cut his only input. When no lane is left, `to_paths_preset` records the reason (`why_empty`) and
`rig.normalize` raises it instead, in English: the lanes the **mode** cut (`nothing to play: Guitar 1 is off in mode
« Pedalboard » — turn it back on in Settings ▸ Mode`), else the lanes the **card** cannot take (`nothing to play:
Rhythm Guitar needs Guitar 2, this card has 20 inputs and no Guitar 2`), else `nothing to play: this sound has no
lane`. The refusal reaches the Designer banner and the "Files not loaded" incident as it is.

**The Inputs row asks before leaving the mode silent (CODED 2026-10-24).** In the mode editor, a tap on an input
chip toggles it in `inputs_off`. When that tap would leave **no** input chip played, the chip first arms ("tap again —
nothing would play in this mode"); a second tap within three seconds applies it. Turning inputs back on never asks.

## 4. Fields of a mode

| Field | Meaning | Code |
|---|---|---|
| `id`, `name`, `icon`, `order`, `desc` | identity; `order` sorts the strip | `list_modes()` |
| `services` | `{service: bool}` veto (§3.1) | `allows()` |
| `inputs_off` | `["role#n", …]`, ≤ 64 (§3.2) | `input_allowed()` |
| `ui.pages` | visible pages; `null`/absent = all | `app/main.js` |
| `ui.boot` | page at boot | |
| `ui.locked` | locked kiosk (§6) | |
| `ui.live` | default view of the Live page (§4.1) | `live_view()` |
| `ui.widgets` | widgets of the Live pages, `{page: {slot: widget \| null}}` | `widgets()`, [live-pages.md](live-pages.md) |
| `click_mode` | `off` \| `preset` \| `manual` (§4.3) | `click_mode()` |
| `perfrec_mode` | `manual` (REC button on /live) \| `auto` (records as soon as /live is open) | `app/page-live.js`, `app/live-stageboard.js` |
| `rec_scope` | `song` (default) \| `set` (§4.4) | `rec_scope()` |
| `take_kind` | what a take recorded in this mode says about itself (§4.5) | `take_kind()` |
| `perf_boost` | CPU governor `performance` while in this mode — and always while the Golem Engine runs, whatever the mode (2026-11-13) | `routes_system.wants_boost()` / `apply_perf_for_mode()` |
| `foot_list` | default setlist/bank put on the foot when entering the mode | `apply_foot_list()` |
| `card` | declared sound card (`"hw:X"`); absent = any card (§4.6) | `card_of()`, `for_card()` |
| `band` | declared space for takes; absent = keep the current space | `band_of()` |

### 4.1 `ui.live` — which view the Live page shows

`modes.LIVE_VIEWS`:

| Value | View |
|---|---|
| `pedalboard` (default) | the foot controller mirror: stomps, scenes, banks |
| `rehearsal` | Rehearsal page — pick a section, start from it, loop it |
| `timeline` | **Concert** page — the music stand, readable from 2 m, the foot plays |

Rules:

- A missing or unknown value (hand-written overlay, mode imported from another rack) falls back to
  `pedalboard` (`live_view()`): never an empty screen because a string did not match.
- The mode only gives the **default**. The song can claim the view: in `app/page-live.js`, a playing Standard
  shows its chart (unless its block says `live_view: "Pedalboard"`); an Arrangement with
  `live_view: "Timeline"` always shows the stand; a **running** arrangement shows the stand unless it says
  `"Pedalboard"`. A per-screen view override (Live tools) lasts until the next mode change.
- Editable in Settings ▸ Mode, row **Live screen** (`POST /api/mode/update {live_view}`).

### 4.2 Recorder

There is **one** recorder configuration, global (`config/recorder.json`, `GET/POST /api/recorder`) — not per
mode, not per preset. A mode only says whether it records (`services.perfrec`) and how REC is triggered
(`perfrec_mode`). The mode sheet's REC ✎ opens the same panel as the Rec block of the Designer.

### 4.3 Click policy

The metronome configuration is global (`config/click.json`); its triggering depends on the mode:

- `off` — never starts; a running click is stopped at the switch.
- `preset` — follows the Click block of the loaded (effective) preset.
- `manual` — a global switch independent of presets.

An absent or unknown value means `manual`.

### 4.4 `rec_scope`

- `song` — the take follows the song (the conductor's "Record with the song").
- `set` — the take starts with the **first** song of the setlist if nothing is recording, covers the whole
  evening (it does not stop at the end of a song), and a REC stopped on purpose does not restart by itself.

Read by `bridge/song_rec.py` and `bridge/app.py` (`_on_song`). Unknown value = `song`.

### 4.5 `take_kind`

Engraved in `take.json` at REC time; golem.fm treats a concert and a rehearsal differently, and only the rack
knows at recording time. `TAKE_KINDS = ("rehearsal", "gig", "show")`: the rack **writes** `rehearsal` or `gig`
(and `riff` for the Riff block, [compo.md](compo.md)); `show` is still **read** because old takes carry it.
Takes are never rewritten. Without the field, `take_kind_of_id()` falls back on the id.

### 4.6 Declared card

A mode may declare `card`. When a card is **adopted** (`POST /api/cards/adopt`, never from a poll),
`modes.for_card(device)` decides whether to switch:

- switch **only** if the current mode declares **another** card (it is no longer playable);
- target = first mode (display order) declaring the adopted card, else the first declaring none
  (Pedalboard with the factory set);
- a mode with no card never triggers anything; a **locked** mode is never left.

## 5. Creating and editing modes

- At most **8 modes** (`modes.MAX_MODES`, published as `max` by `GET /api/modes`; checked server-side too).
- Factory files live in `config/modes/`; user edits and user-created modes live in the git-ignored overlay
  `config/modes.local/` (same id = override). `list_modes()` merges them and flags each mode `_factory`,
  `_modified` (factory + overlay) or `_custom` (overlay only).
- `modes.commit()` deletes the overlay when an edit brings a mode back to its factory definition.

Endpoints (`bridge/routes_modes.py`):

| Route | Effect |
|---|---|
| `GET /api/modes` | `{modes, current, max}` |
| `POST /api/mode {id, confirm?}` | switch (§6) |
| `POST /api/mode/update {id, …}` | edit the `EDITABLE` fields; refused (409) on the active locked mode |
| `POST /api/mode/new {name, from, icon?, desc?}` | create from an existing mode; `from` is required; the id is derived from the name (`new_id`), never typed; 409 when 8 slots are taken |
| `POST /api/mode/reset {id}` | factory mode → reset; custom mode → delete (refused if active) |

`/api/mode/update`, `/new` and `/reset` are admin writes (`bridge/auth.py`).

`modes.EDITABLE` = `name, icon, desc, services, click_mode, inputs_off, card, band, live_view, foot_list,
widgets`. `apply_update()` is the single edit path for the rack sheet **and** the golem.fm job: services are
filtered to known keys as booleans, texts are trimmed to 80 characters, `card`/`band`/`foot_list` set to
`""`/`null` **remove** the field (never an empty string stored).

### 5.1 Remote edition (golem.fm)

The modes table is pushed with the heartbeat out of cadence (boot and every change): `modes[]` = `modes.doc(m)`
per mode, plus `modes_ctx` (recorder, click, vocabularies from `modes.vocab()`, spaces, cards, foot lists,
`modes_version`). Jobs `mode-set` and `recorder-set` (`tones_jobs._mode_set`, `_recorder_set`) go through
`validate_update` → `apply_update` → `commit`:

- all-or-nothing: one refused field = nothing written;
- `card` must be in the card registry, `band` in the roster — the rack never creates a space;
- if the job carries `space`, the mode must belong to that space;
- on the **active** mode: refused during a take, a song or a lock.

Never remote (`modes.NEVER_REMOTE`): `ui`/`locked`/`pages`/`boot` (a lock set from the web would trap the
screen), `perf_boost`, `perfrec_mode`, `take_kind`, `order`, `id`. Switching the active mode, creating,
resetting or deleting modes are rack-only gestures. Protocol: [golemfm-protocol.md](golemfm-protocol.md).

## 6. Switching, locking, exiting

`POST /api/mode {id}`:

1. If the target declares a `band` different from the current space **and** a take is recording or the
   current mode is locked, the bridge answers **409** `{needs_confirm: true, message}` unless `confirm: true`.
   Exception: leaving a locked mode for an unlocked one never asks (it is the kiosk's exit). The take in
   progress keeps its space; the next one changes.
2. Persist (`set_current`, atomic write), clear the rehearsal loop/cue, log a `mode` diagnostic event,
   switch the space if declared (an unknown space keeps the current one; the mode switches anyway).
3. `_re_veto()` (§3.1), apply pending setlists (`setlists.apply_pending`), apply the mode's `foot_list`
   (a vanished list is reported, the foot keeps its own), apply `perf_boost` in a thread, broadcast the state.

**Lock.** `ui.locked` does not freeze controls: the Live page stays interactive (it is the backup if the
foot controller dies). What reduces the surface is `ui.pages`. The lock only means:

- exit is a deliberate gesture: **hold the golem logo 2 s** (`app/main.js` `exitDown`), which sends
  `{id: "studio"}`; holding the **mode badge** exits any mode;
- the active locked mode cannot be edited or reset until you leave it;
- `for_card` never leaves it; Live tools do not offer assignment.

**Any non-2xx answer to `POST /api/mode` must be read by the exit gesture**: on 409 `needs_confirm` the app
asks the question and resends with `confirm: true`; on failure it says so visibly. A kiosk without a tested
exit traps the user.

At boot, `migrate_show_to_gig()` (called from `bridge/app.py`) archives a leftover local `show.json` overlay
as `show.json.merged` (outside the `*.json` glob) and moves a rack persisted in `show` to `gig`. The former
`show` mode no longer exists; a song claims the stand view instead (§4.1).

## 7. Hardware guards

- An enabled service is a possible hardware dependency (keys ⇒ a controller plugged in). A missing device is
  **reported, never blocking**: the rack always boots, the service is simply not mounted. An unplugged
  instrument is said on its lane, not as a scene alert.
- Not applied by modes today: the audio buffer (it stays in Settings) and a sound-card swap.

## 8. Rehearsal: band multitrack recorder (PROPOSED, not built)

The Rehearsal mode today is the rig + the global recorder in `auto`. What follows is the target, not code:

- golem is the player's rig **plus** a multitrack recorder for the band — **not** the room's console. Band
  monitoring stays on the room's amps/PA; a golem failure loses the recording, not the rehearsal.
- One card at a time (two USB clocks drift). The band card's input map declares ports → roles, labels and
  people ([input-map.md](input-map.md)); inputs marked to traverse the rig get golem chains, the others are
  recorded dry.
- One dry track per input (DI + processed for a rig guitar), e-drum stereo audio + MIDI in parallel.
- Continuous recording with **markers** (foot Note or screen), cut afterwards; a disk gauge before REC.
- A session = a dated folder (`manifest.json`, `tracks/*.wav`, `midi/*.mid`) that golem.fm can ingest as
  stems without migration.
- UI: Soundcheck (one meter per input), REC (button, timer, disk gauge, marker), Session (rename/delete/export
  segments). Foot: usual mapping plus REC toggle and marker Notes.
