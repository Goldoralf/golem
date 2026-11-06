# Band scenes — lane states

> **Status: CODED** — a lane carries named **states**, a scene picks one state per lane; the scene dictionary, the parts table, footswitch capacity, the Companion's own stomps and "apply this lane to the setlist" are built on that model.

Related: [preset-format.md](preset-format.md) (lanes and scenes), [arrangement.md](arrangement.md)
(parts and cues), [patches.md](patches.md) (patches carry scenes), [setlists.md](setlists.md)
(the line carries the arrangement), [modes.md](modes.md) (Mode → Preset → Scene → Stomp),
[ui-architecture.md](ui-architecture.md), [devices-people.md](devices-people.md).

## 1. Invariants

1. **One scene axis.** A part picks a scene; a scene applies to everyone. There is no per-instrument
   scene and no part that picks a state per lane.
2. A cue references a **block**, never a switch.
3. The arrangement lives on the setlist line.
4. A patch is a one-lane mini-preset **with its scenes**; dropping it into a preset copies.
5. The pedalboard switches the **band's** chord of states, not just the guitar. A preset played
   outside a setlist line is recalled at the foot as usual.
6. One player alone (a few lanes, a looper, a backing) is the simple case of the same model: nothing
   below is mandatory.

Not in scope: per-lane scenes at the foot, one pedalboard per musician, provenance links on patches
(applying a lane to the setlist is an explicit, undoable copy, §5.6), driving third-party modeler
snapshots beyond a `midi-pedal` block.

## 2. The model

A lane carries its **states**. A state is what a patch scene already is: which blocks of the lane are
on, its knob values, its muted branches. A scene picks one state per lane.

```json
"lanes": [{ "id": "bass-1", "role": "bass", "chain": { … },
  "states": [
    { "id": "st-pick", "name": "Pick", "blocks": {"comp-1": true, "drive-1": false}, "params": {}, "branches": {} },
    { "id": "st-fuzz", "name": "Fuzz", "blocks": {"drive-1": true}, "params": {"drive-1": {"gain": 5.2}} },
    { "id": "…",       "name": "A",    "implicit": true, "blocks": {…} }
  ] }],
"scenes": [
  { "id": "B", "name": "Verse",
    "lanes": { "bass-1": {"state": "st-pick", "level": 0}, "voice-1": {"state": "st-dry", "mute": false} },
    "blocks": {…}, "params": {…}, "branches": {…} }
]
```

- `scene.lanes[<laneId>]` = `{state, level, mute}`. `level` is the lane's scene level (dB);
  `mute: true` sets that level to the floor (`scene_bake.LANE_MUTE_DB`, −150 dB) — the same `D_VOL`
  as the scene level, so muting a lane per scene is a state switch, never a rebuild, and the
  topology stays the same from scene to scene.
- **The scene's flat table** (`scene.blocks`, `scene.params`, `scene.branches`) is what the bake,
  the Designer and golem.fm read. A state is the **truth** when several scenes point to it; the flat
  slice of each scene pointing to it is its **mirror**. No engine path reads states directly.
- The scene name belongs to the song ("Verse"); the state name belongs to the musician ("Fuzz").
  Both are shown, never one instead of the other.
- **Implicit states**: `preset_view.ensure_lane_states(p)` (called by `store.migrate_config`, on load
  **and** save, idempotent) gives every (lane, scene) pair a state; a missing one is created as a
  copy of what the scene already said for that lane, named after the scene (its name, else its
  letter), flagged `implicit: true`. No sound changes. An implicit state no scene points to is
  removed; an **explicit** state (dropped with a patch, created or renamed by the user) stays.
- **Reconciliation** for writers other than the Designer (`ensure_lane_states`): among the scenes
  pointing to a state, those whose slice differs have been edited; if they all agree, their content
  becomes the state (and reaches every scene that points to it); if they contradict each other, the
  state wins. The Designer propagates client-side after every mutation
  (`designer-model.propagateLaneStates`, run by `upd` in `page-designer.js`).
- **Dropping a patch** (`patches._inject_states`): the patch's scenes become **explicit, named**
  states of the lane (`patchDraft` does the same in the Designer).

**Legacy branch mutes.** Before branch mutes moved to `scene.branches`, they were stored as
`scene.lanes[<branchId>].mute`. One criterion tells them apart —
`preset_view.is_legacy_branch_mute(v)` (app `isLegacyBranchMute`): `mute` with neither `state` nor
`level` is a legacy branch mute; anything else is a lane entry. `migrate_scene_branches` moves only
those mutes. golem.fm applies the same criterion. Every reader of `scene.lanes` must use it.

**Summary** published to screens (`preset_summary`): per scene, one row per lane
`scenes[].lanes[] = {id, role, state, implicit, block, mute, level, …}` (`preset_view.preset_summary`,
`scene_lane_states`).

## 3. Screens

| screen | shows | writes |
|---|---|---|
| **/live**, scene row | letter + scene name, then **one line per lane** with the state name (an implicit state shows the lane's identity block instead, e.g. "Twin Reverb · GTR"), struck through when muted | scene recall only |
| **Parts table** — the part sheet of a setlist line (`app/designer-arrangement.js`) | under the Scene row, one read-only line per lane: state name, dotted and unnamed when unchanged from the previous part, "muted" struck | "＋ New scene for « <part> »" creates a scene named after the part, **a copy** of the scene playing there (state pointers included, the sound does not move), and points the part to it; "▦ Scenes" opens the dictionary |
| **Scene dictionary** — Designer tab ▦ (`app/designer-scenes.js`, `#/designer/scenes`) | rows = lanes, columns = scenes (switch, "taken by Click", "no switch"); cell = state · level · mute; dotted = same state as the previous scene; grey = implicit | tapping a cell opens the assignment bar: the lane's states (and where each is used), "Same as B", "＋ New state" (a copy of the current state, selected for this scene), "✎ Name it / Rename", level, "Mute", "Open <lane> on C →" |
| **Pedalboard capacity** (Designer pedalboard tab) | a count line: scenes at the foot, switches taken by services (which), scenes without a switch; scene cells stacked like /live; a row of scenes without a switch | tap a scene, then a switch of row 1–5: the service that held it returns to the palette |
| **Companion — my lane** | the current scene with my state, my stomps, my scene level | toggle **my** stomps only (§4) |
| **Apply a lane to the setlist** | what changed, the songs and the states each uses, exclusions said | bulk copy of the lane, one undo (§5) |

Rules: the parts table is the entry point; the dictionary is reached from it or from its tab. Scenes
without a switch appear in the pedalboard tab and the dictionary, not on /live. A phone never sees
other lanes' scenes. Scene ids are positions and are never renumbered (setlist arrangements
reference them); beyond E a scene has no switch on a five-scene pedalboard, and the screen says so.

The Designer edits the sandbox and keeps its draft in memory across pages: a scene created from the
parts table is also handed to it (`sandbox_apply` when the sandbox is this preset, and
`lib.queueDraftMutation` applied on return) — otherwise its next save would erase it.

## 4. The Companion toggles its own stomps

`bridge/lane_stomps.py`:
- `GET /api/lane/mine` — lanes of the device (by **person** when the device has one, through the
  input map; else by **role**: `LANE_ROLES_OF_DEVICE`, e.g. Guitar → `guitar`/`line`, Bass → `bass`,
  Voice → `voice`, Keys → `keys`/`keys-pads`, Drums → `drums`): the scene's state, level, blocks with
  their effective state. Without a device (rack screen, previews), `?role=` / `?person=` select a
  read-only view; `?preset=<id>` shows another song (scene A, read-only).
- `POST /api/lane/stomp {block, on?}` — `check_toggle`: a device toggles only blocks of **its**
  lanes; never an amp, a captured preamp, a cab, an instrument or a service; 403 with the reason. A
  block alone on a switch goes through `_do_stomp` (LED and `state.stomps` stay right); otherwise a
  command by block id. A toggle lives for the scene (`state.lane_toggles`, kept with preset and
  scene). The rack's own screen has no restriction. Allowed in locked modes (a playing gesture, not
  an edit).
- Known limit: when two blocks share a switch and a phone toggles one, the switch LED does not
  follow (it reflects the switch, not each block).

## 5. Apply a lane to the setlist

Designer ⋯ menu, "⇉ Apply « <lane> » to the setlist…" (`app/designer-lane-apply.js`,
`bridge/lane_apply.py`; `POST /api/lane-apply/plan`, `POST /api/lane-apply`,
`POST /api/lane-apply/undo`).

- **Plan**: the lines of the active setlist; target lane = same role, same id on a tie, never MIDI ↔
  audio; what changes, counted per song; exclusions stated (no lane of this role, lane held by
  another patch) — excluded songs are unticked and the reason is shown.
- **Apply**: the source lane replaces the target; block ids renamed if taken elsewhere
  (`patches._dedupe`); each scene keeps its state **by name** (else the state the same-letter scene
  plays at the source, else the base); each block keeps its **footswitch** (same id, else same type);
  scene levels, mutes, scenes, switches and other lanes are untouched.
- **Undo**: each preset written is first copied into `presets/.lane-apply-undo.json`; "↶ Undo for
  all". The source is the Designer's **document** (its draft may be ahead of the file).

## 6. Open points

- A state shared by two lanes of the same role (two guitars) is two copies, like two patch drops.

Tests: `tests/test_lane_states.py` (bake identical with or without states),
`tests/test_lane_stomps.py`, `tests/test_lane_apply.py`.
