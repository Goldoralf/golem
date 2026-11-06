# The looper

> **Status: CODED** — the `looper` block: a table of up to four loops on footswitches 1–4, each recording one lane's output, played by the `golem_super8` JSFX on the "Looper" track.

Related: [blocks-doctrine.md](blocks-doctrine.md) (service blocks, footswitch ownership),
[pedalboards.md](pedalboards.md) (the footswitch contract), [mixer.md](mixer.md).

## 1. The model — one table, one row per loop

The `looper` block (catalog `library/catalog/effects.json`: `unique`, `scene_invariant`,
`foot_mode: transport`) lives in the Players config lane (`preset.config.gen`). Its **presence**
turns the preset into a looper preset. Its param `loops` is a table:

| field | values | meaning |
|---|---|---|
| `sw` | `1` · `2` · `3` · `4` (`looper.LOOP_SWITCHES`) | the footswitch that carries this loop |
| `src` | a lane key (legacy: `"1"`, `"2"`, `"k"`) | the lane whose **output** is recorded |
| `label` | free text | what the loop holds, for humans |
| `level` | dB, −60..0 (optional) | playback level of this loop |
| `mute` | `true` (optional) | playback mute |

```json
{ "type": "looper", "id": "looper-1", "params": {
    "loops": [ { "sw": 1, "src": "guitar-1", "label": "Rhythm" },
               { "sw": 2, "src": "guitar-1", "label": "Lead" },
               { "sw": 3, "src": "keys-1",   "label": "Pad", "level": -6 } ],
    "length": "auto", "count_in": true, "rec_dub": false } }
```

- **Several rows may share a source** — the point of the table: the number of loops follows what
  the player wants, not the inputs.
- One row has exactly one `src` (a loop is never a mixer).
- **Row order is the engine slot**: row *n* uses stereo pair *n* of the JSFX. `normalize_loops`
  and the Designer (`loopRows`) sort by switch, so adding a loop never moves recorded content.
  Changing the table is a rebuild, not a live tweak.
- At most 4 rows (`MAX_LOOPS`); switches outside 1–4 and duplicate switches are dropped (first wins).
- **Legacy tables** (loops on 6–9) are **read** as 1–4 in the same order (`LEGACY_LOOP_SW` in
  `bridge/looper.py` and `app/designer-sheets.js`); nothing is rewritten silently.
- **Missing table** → default `[{sw:1, src:"1"}, {sw:2, src:"2"}, {sw:3, src:"k"}]`
  (`DEFAULT_LOOPS`). The default is never written into the preset; the drawer writes the table at
  the first edit.

Source of truth: `looper.normalize_loops()`, `rig.looper_loops(preset)` (reads the block wherever
it lives, else the legacy flag `preset.looper.loops`).

## 2. A loop records audio — it never recalls a sound

A loop captures its lane **post-fader**: the sound as heard, scene included. A loop switch never
recalls an instrument preset or a scene. Two loops from the same synth with two sounds = two
**moments** (record in scene B, then in scene C). One place decides the sound (the scene); the
loop captures it. Loops are scene-invariant: they keep playing across scene changes.

## 3. Footswitches

| switch | role |
|---|---|
| **1–4** | the loops (near row) |
| **5** | play / stop all (`ALL_SWITCH`) |
| **6–9** | free: ordinary stomps of the preset |
| **10** | hold ≥ 1.2 s = clear all (`KILL_SWITCH`, `CONFIRM_S`); a short tap does nothing |

Gestures on a loop switch (`LooperControl.on_edge`):

| state | gesture | action |
|---|---|---|
| empty | press | record (immediately — the press time *is* the loop start) |
| rec / dub | press | close → play (the first loop sets the master length) |
| play | tap | stop (deferred by `DOUBLE_S` = 0.4 s, the double-tap window) |
| play / dub | double tap | overdub on / off |
| stopped | tap | resume (re-enters at the global position) |
| play / stop | hold ≥ `LONG_S` = 0.6 s | clear this loop |

- The scene row already sends both edges (compiled as `preset`, its off face is a real NoteOff),
  so no special bank compile is needed: `looper_bank.gestures` in
  `config/pedalboard/contract.json` is empty.
- A scene tap on a switch that carries a loop does not change scene; the long-press bank select on
  SW1 is disabled when SW1 carries a loop (`bridge/foot.py`).
- The set of switches the looper owns depends on the preset: ask `LooperControl.switches()`, never
  the module constant `SWITCHES`.
- The factory "Loop Station" preset has one scene ("Loop"), loops on 1–4, effects on 6–8.

The same actions from the screen: `POST /api/looper {op: tap|dub|clear|toggle_all|clear_all, slot}`
(`app.py`, `LooperControl.api_action`).

## 4. First loop: snap to the bar and count-in

Block params, edited in the looper drawer:

| param | values | effect |
|---|---|---|
| `length` | `auto` (default) · `free` | **Loop length**. `auto`: when a grid plays (click, drum machine or backing), closing the first loop snaps to a whole number of bars at the preset tempo (nearest, ≥ 1 bar): closed late, it is cut at the bar and playback restarts in phase; closed early, recording continues to the bar. The start stays at the press. `free`: the loop lasts exactly between the two presses |
| `count_in` | `true` (default) · `false` | **Count-in** (`auto` only): empty looper and nothing playing → the press starts one bar of click, the first loop starts on the 1, the click stops, and the loop still snaps. Tapping again during the count-in cancels it. No count-in when a grid already plays |
| `rec_dub` | `false` (default) · `true` | **After a take**: "Play" or "Overdub" — with Overdub, the tap that closes a new loop immediately starts a layer on it; the next tap plays |

Later loops follow the master loop. The count-in, its click and the snapping run **inside
`golem_super8`** (sample-accurate; a click from another JSFX would inherit the ~30 ms gmem/defer
jitter). The bridge writes the sliders `GoleM Tempo` (BPM) and `GoleM Mode`
(`beats×10 + 1·snap + 2·count_in + 4·rec_dub`) just before the start / close command
(`LooperControl._send_timing`, `app._looper_timing`). When the first loop is snapped by the JSFX,
the JSFX itself chains the overdub (flag 4). The count-in tick only exists at the looper output and
is never recorded. An older JSFX without these sliders ignores them and stays free. The count-in is
published in gmem `[4]` (beats left) and `[5]` (loop number) and shown on /live ("COUNT-IN").

## 5. Per-loop level

The four loops live in one plugin on one track (the JSFX folds the four pairs into one stereo
output), so track faders cannot separate them.

- `golem_super8` sliders `GoleM Loop 1-4 dB` (−60 = mute … 0) and `GoleM Loops level` (0..1), smoothed
  ~20 ms, applied **at playback** before the fold — recording is never touched
  (`LooperControl.push_levels`, slider offsets `cmd_param + 3..7`).
- /live mixer: one strip per loop after "Looper" (the "Looper" strip stays the level of the whole
  looper — the `D_VOL` of its send).
- `POST /api/looper {op: "level", slot, db | mute}` → sound immediately (OSC), then written to the
  preset file **and** to the Designer draft if it holds this preset (`app._persist_loop_level`),
  **without** a rig rebuild (a rebuild would interrupt running loops).
- **EXP1**, when it is neither volume nor assigned, drives the level of all loops in a looper
  preset ("Loop level" on /live); reset to 100 % at each recall.

## 6. The engine

`golem_super8` (`reaper/Effects/golem_super8`, a fork of Super8) is an 8-channel JSFX used as
**4 stereo pairs**, on the track "Looper" (`golem_rig.lua` `ensure_looper`; the FX is permanent,
never removed, so loops survive rebuilds).

| row | pair | channels | rec / play note | clear note |
|---|---|---|---|---|
| 1 | 0 | 1·2 | 36 / 37 | 24 |
| 2 | 1 | 3·4 | 41 / 42 | 25 |
| 3 | 2 | 5·6 | 45 / 46 | 26 |
| 4 | 3 | 7·8 | 50 / 51 | 27 |

Play-all = note 21, kill-all = note 20 (`looper.NOTES`, `PLAYALL_NOTE`, `KILL_NOTE`).

Data path:

```
looper block params.loops
  → scene_bake.to_paths_preset : plan.looper.loops (rig.looper_loops)
    → golem_rig.ensure_looper  : one send per row, path(src) → pair(row index)
  → bridge/looper.py           : switch → slot from the table (LooperControl.set_loops)
  → golem_looper.lua           : publishes slot states (presets/.looper.json), incl. which loop is master
```

Sends (`ensure_looper`): from each matching path's output track (not branch children), post-fader
(`I_SENDMODE 0`), `I_DSTCHAN` = pair×2, and **`I_MIDIFLAGS = 31` (no MIDI)** — `golem_super8` obeys
notes in the range of a pad controller, so a send carrying MIDI would let keyboard pads drive the
looper. The send index is the value returned by `CreateTrackSend`. The looper outputs straight to
OUT 1/2 (`B_MAINSEND = 0`), so a loop never re-records itself.

**Command dispatch** (`LooperControl.dispatch`): primary = OSC FX param on the slider `GoleM Cmd`
(value `seq*128 + note`, address from `presets/.looper.json`); fallback while the address is
unknown = `presets/.looper-cmd.json` → gmem ring. The displayed state is the gmem feedback with a
250 ms optimistic override after each dispatch.

## 7. Limits

- **4 loops maximum** — a limit of the foot (the near row), not of the engine.
- **One master length** shared by all loops.
- A `src` the preset does not have (empty lane, or cut by the mode) would record silence: the rig
  creates no send and logs "boucle MUETTE"; the Designer greys the cell ("THIS LANE IS NOT IN THE
  PRESET: the loop would record silence").
- Keys and pads on the same lane share one output: two loops of that lane capture the same thing at
  two moments.

## 8. On screen

- **Designer** — the looper drawer (`LooperTutor` / `LooperBoard` in `app/designer-sheets.js`): tap a
  loop cell to cycle its source through the lanes the preset offers, then "none" (row removed); the
  label is edited in the cell (default = the lane name); "Loop length", "Count-in", "After a take".
  The same board is shown read-only in the MIDI assign tab — one renderer, so help never
  contradicts the foot.
- **/live** — with a looper preset (`.live2.looping`), loops sit in the large near-row cells: state
  colour, position ring, timer while recording, **MASTER** on the loop that set the length, level,
  source in words, and the next gesture. SW5 shows "▶ / ■ ALL" and the master clock in bars; SW10
  "Clear all" (hold 1 s); the far row shows stomps 6–9. The label comes first, the source second.

Not built: undo of the last overdub.
