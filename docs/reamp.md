# Reamp — playing a DI back through a preset and returning the sound

> **Status: CODED** — the rack side of the `reamp` job: wait until the rack is free, render a recorded DI offline
> through one lane of a local preset, upload the result to golem.fm (`bridge/reamp.py`,
> `reaper/Scripts/golem_preview.lua` op `render`).

golem.fm queues a job `action: "reamp"`; the rack re-plays the DI of a take, offline, through **one lane** of one
of **its** presets at the requested scene, and uploads the result as one more track of the same take. It never
becomes the active sound automatically: a human picks it. Job envelope and calls:
[`golemfm-protocol.md`](golemfm-protocol.md).

## 1. The job

`{reamp (id, idempotency key), band, uid, recording, lane, role, preset, preset_lane, scene, bpm,
di {file, on_rack, url, sha256, size_bytes}, result {declare, complete, fail}}`.

## 2. When: the "free" rule (`reamp.busy_reason`)

The render **takes the live engine**: it sets the preset and scene, renders, then restores what was playing (the
preview path, `preview._apply_scene` / `_restore_live`). It runs only when all of these hold:

- the mode is neither **Gig** nor locked (`mode.id == "gig"`, `mode.ui.locked`);
- no take recording and no count-in (`perf.recording`, `perf_countin`);
- no song or arrangement playing (`backing.playing`, `arrangement.running`);
- no song loading (`rig_loading`) and no preview rendering;
- **nobody has used the rack for `IDLE_S`** (600 s, `GOLEM_REAMP_IDLE_S`).

"Used" is the single activity clock of `bridge/activity.py`, written by three sources only: `screen` (any HTTP
request that modifies something, app middleware), `foot` (a pedalboard message, `foot.py`) and `signal` (an input
above `activity.SIGNAL` = 0.2 on the normalized OSC meter). The signal source matters: a guitarist playing at home
without starting a song triggers none of the other guards. The clock lives in memory and starts at bridge launch
(a freshly restarted rack is not considered idle). `SIGNAL` is a guess to calibrate on the rig: too high and soft
playing reads as silence, too low and an open mic's hiss holds the rack forever.

`busy_reason(idle=False)` skips the idle clause; capture-recipe verification uses it because it runs in a separate
REAPER and does not take the engine ([`plugin-recipes.md`](plugin-recipes.md)).

## 3. The deferred queue

The "rig" job lane is a single FIFO worker that acks every job it processes; a reamp waiting inside it would block
`preset-install`, `patch-try`… So:

- `tones_jobs` does not put a `reamp` in a lane: it hands it to `reamp.enqueue` (the job stays in flight, so
  golem.fm does not offer it twice);
- a waker thread (`reamp.start`, every `CHECK_EVERY` = 15 s, `_pump`) moves **one** job into the "rig" lane only
  when the rack is free and no reamp is running; it is then serialized with installs and recalls;
- the rule is re-read before the render and between long steps (download, render, each upload chunk); busy →
  `reamp.Deferred`: **no ack**, the job goes back to the head of the deferred queue (`requeue`);
- the queue is in memory: a restart loses it and golem.fm offers the unacknowledged job again.

`GET /api/reamp` shows `{pending[], waiting_for, idle_after_s, activity}`.

## 4. What is rendered (`reamp.run`)

1. **Idempotence first**: `GET /api/ext/recordings/reamps/{id}`; `done` or `failed` → ack and skip.
2. **Preset**: `preset` must exist on disk (`store.load_preset`), else `preset <id> is not on this rack`.
3. **Scene**: `scene`, else the preset's first; absent → error.
4. **Lane** (`pick_lane`): `preset_lane` if given; else the same role as the take's lane (`role`, or read from the
   take with `take_role`), then the same number (`in_nth`); else the first instrumental lane. Nothing readable →
   error, never a random choice. The rack reads `in_role`/`in_nth` from the preset it renders rather than trusting
   a copy. `check_lane` refuses a **MIDI** lane, a lane not mounted on the connected card (`on_card: false`) and a
   disabled lane.
5. **DI** (`find_di`): in `recordings/<uid>/`, matched **without extension** to `di.file` (the rack writes `.wav`,
   golem.fm may hold `.flac`); else downloaded from `di.url` with the pairing token into `recordings/.reamp/<id>/`
   (resumed with `Range`, `sha256` checked, 4 attempts); else `di not found`.

## 5. How it is rendered (`reamp.render` → `golem_preview.lua`, op `render`)

The bridge applies preset + scene, waits `SETTLE_S` (3 s) and for `rig_loading` to clear, then sends
`{action: "preview", op: "render", di, out, tail: 0, tree: true, sr, settle, chain: "Sandbox #Input <n>"}`.

- **`chain`** selects the lane's input track.
- **`tree: true`** clones the **whole lane**: a split lane lives on several tracks (root `Sandbox #Input N`,
  branches `…/<id>`, folder `…/merge` carrying the output). All tracks are cloned by state chunk (NAM and IR
  included), internal sends between clones are recreated, hardware outputs and arming removed, and the track that
  carried the output goes to the master.
- **`settle`** (`CLONE_SETTLE_S` = 2 s): the render waits after cloning so NAM in the clone loads its model (a
  track chunk is empty while a plugin loads asynchronously).
- **`tail: 0`**: the render stops at the DI's last sample (reverb tail cut).
- **Sample rate**: rendered at the DI's rate; the bridge checks the file (RIFF WAV, same rate) and trims or pads it
  to the DI's exact length (`fit_length`).
- **Timeout**: `max(150 s, 3 × duration + 60 s)`.
- REAPER compensates plugin latency (PDC) in the render. `tools/check-reamp-align.py` measures the offset at the
  sample; budget 1 ms (measured: a constant ~0.3 ms).
- The preview output is deleted before rendering: rendering onto an existing file opens a modal dialog that freezes
  REAPER.

## 6. The result

`POST result.declare` `{filename: "<DI stem>.reamp<id>.wav", sha256, size_bytes}` → the track and its `upload`
URL; bytes go through the chunked upload (`golemfm.put_bytes`, 8 MB chunks, resumed at the offset the server
returns on 409); then `POST result.complete`. 413 → `quota — the band's storage is full`. Then the usual ack
`ok: true` with `{preset, scene, lane, filename, sha256, size_bytes, track, recording}`. Any failure in §4–5 →
ack `{ok: false, error}`. The local render folder is deleted after upload.

## 7. Bench

`POST /api/reamp/try` `{preset?, scene?, lane?, role?, di, out?}` renders a local DI through a lane **without
uploading** (default output `recordings/.reamp/try/<stem>.try.wav`). It refuses what the job refuses except the
idle clause (someone at the rack started it). `tools/check-reamp-align.py` drives it. It takes the engine for a few
seconds: run it when nobody is playing.

MIDI (keys) lanes are not reamped: that would need the take's MIDI, not a DI.
