# Live engine — scene switch without rebuild

> **Status: CODED** — a preset change rebuilds the rig in REAPER; a scene change (and any Designer edit that
> keeps the rig's shape) is a state switch on the tracks already in place: the `scene_apply` command, run by
> `golem_rig.lua` `reapply_scene`. Preloading the next presets is PROPOSED, not built.

Related: [`architecture.md`](architecture.md) §1–2 (command slot, routing in REAPER, the journey of a recall)
and §5 (what makes a change a rebuild) · [`preset-format.md`](preset-format.md) §5 (baking a scene, lane
states) · [`pitfalls/reaper.md`](pitfalls/reaper.md) · [`pitfalls/plugins.md`](pitfalls/plugins.md).

## 1. Scene = state, preset = topology

| Gesture | What happens | Path |
|---|---|---|
| **Preset change** | rebuild: tracks, FX, routing and files are materialised again | `rig_recall` → `golem_rig.lua` `materialize` |
| **Scene change**, or a Designer edit that keeps the shape (knob, bypass, scene toggle, lane mute, level, foot…) | state switch on the existing tracks: no `TrackFX_Add`/`Delete`, so reverb and delay tails ring through | `scene_apply` → `golem_rig.lua` `reapply_scene` |
| **Stomp** (foot, screen, arrangement cue) | toggles blocks by stamp `golem:<id>` | `stomp` command → `golem_rig.lua` (`ids` or `on_ids`/`off_ids`) |
| **Expression pedal** | writes one FX parameter | OSC `set_fx_param`, indexed by `presets/.livemap.json` (`app._apply_exp`) |
| **Whammy DT** | hardware MIDI | `_whammy_dt_glue` in `bridge/app.py` |

Rebuilding a preset takes in the order of 100–200 ms, which is not noticeable between songs, so presets are
**not** preloaded on persistent tracks: one materialisation path (the sandbox), no divergence. A scene must
be heard as instantaneous in the middle of a song, so it never rebuilds. Rebuilding during audio also
exposed plugin crashes on fast recalls; the state switch removes FX surgery from the scene path entirely.

## 2. Union materialisation

`scene_bake.to_paths_preset(preset, scene, union=True, veto=…)` mounts **every** lane and every split branch
that any scene uses, each block carrying its state for the current scene. The track topology is therefore
identical for all scenes of a preset. Two kinds of silence:

- **A split branch off in a scene** carries `mute: true` (`_lane_path`, union). REAPER silences it with the
  branch track's **`B_MUTE`**; its `D_VOL` stays at 0 dB. One lever, one meaning: mute for silence, volume
  for level. This requires REAPER to **process** muted tracks: `norunmute=0`, forced by
  `provision/reaper-ini-setup.py` (`ENGINE_FORCED`). Otherwise a muted branch stops and its return wakes its
  plugins.
- **A whole lane off in a scene** (`scene.lanes[<id>].mute`) is kept, with its path level set to
  `LANE_MUTE_DB` (−150 dB, `scene_bake.py`).

A scene that mutes every lane gives clean silence (a de facto kill switch).

## 3. Deciding rebuild vs scene switch (bridge)

1. `recall.do_recall(pid, scene, line)` updates the state, then calls `emit_sandbox()`. A Designer edit goes
   through `emit_sandbox_preset()` directly (`POST /api/sandbox_apply`).
2. `recall.emit_sandbox_preset(preset, scene, action="rig_recall")` bakes with `union=True`, compiles
   (`compile_rig.compile_preset` writes `reaper/FXChains/<id>.rig.json` in both cases, since `golem_rig` reads
   the baked states from it), and computes `scene_shape(preset, scene)`.
3. The requested `rig_recall` is downgraded to **`scene_apply`** only when the preset id, the shape and
   `state.reaper_gen` equal those of the last emission (`_LAST_EMIT`), REAPER is running, and
   `rig_is_live(pid)` holds. `invalidate_shape()` clears the cache when REAPER restarts, so a scene switch is
   never sent to an empty project.
4. The command is written with `"_route":"rig_recall"`; `golem_watch.lua` routes it to `golem_rig.lua`
   ([`architecture.md`](architecture.md) §1.2).

**What the shape covers** (`recall.scene_shape`): paths (id, input, output, MIDI), each block's id, type,
`ref`, `cab`, `model` **and the resolved capture file**, split structure, the Vital sound, piano `sfz` and EP
bank, the set of drum kits used by any scene, the pads kit and its contents, the looper (on/off and its loop
table), and the controller channels. It ignores bypass, knobs, levels and lane mutes: those switch without a
rebuild. Anything loaded by chunk surgery (a file, a sound bank) must be in the shape, or an edit would
switch state and leave the old file loaded.

## 4. What `reapply_scene` does (REAPER)

`golem_rig.lua` `reapply_scene(root, plan)` applies the **complete** state of the target scene to every
track of the plan, not a diff, so it is idempotent and independent of history.

- **Guard**: if the plan's tracks are missing or carry no FX at all (REAPER restarted without a build), it
  returns false and `main()` falls back to `materialize`. Never worse than a rebuild.
- **Stamped blocks** (`golem:<id>`): knobs **before** enable (`apply_block_params`), so a block turned on
  never processes a cycle with its old settings; then `fx_set_on`. `scene.blocks` may address a block by
  id or by type.
- **Core** (amp, cab — not always stamped): found by `core_fx_index` (stamp first, then name); knobs, then
  `apply_core_enabled` sets the NAM's enable (or the IR of a `cab` block) for the scene. The default cab of
  an isolated amp head follows its amp.
- **Drum kit union**: every kit pair used by the preset is mounted; the scene turns one on by stamp.
- **Branch mutes are collected and applied last, unmute first**: tracks are processed in plan order, and
  muting a branch while the other one is still being configured would leave a moment where no branch
  sounds.
- **Path level** (dB) is written to the output track's `D_VOL`.
- Every switch is logged ("scene applied without rebuild (N blocks, muted lanes: …)") in
  `presets/.golem-rig.log`. A file that is not loaded is logged and the scene is applied anyway; the deferred
  file check (`rig_verify`) reports it in `presets/.rig-check.json`.

## 5. Rules the engine keeps

- **A muted branch does not change the state of its plugins.** Silence is the track mute only; blocks are
  not bypassed and the core stays loaded. A bypass requested by the scene inside an **active** branch stays
  a bypass.
- **An IR convolver is never bypassed.** Turning the x42 convolver back on with its IR stalls the whole
  engine (~0.5 s). `fx_set_on` (via `switch_param_of`) leaves it enabled for REAPER and drives its internal
  **"Enable"** parameter instead (0–2 ms). The same applies to golem Freeze ("Freeze" parameter). Scenes,
  cores and stomps all use `fx_set_on`, so the Designer has nothing to forbid.
- **The core is built whatever the scene.** `compile_rig._render_core_for` removes a block from the core only
  when its file has the wrong nature (`_wrong_kind`, set by `rig._prep_block`), never because the current
  scene bypasses it. Otherwise a branch built during a scene where the amp is off would have no NAM, and no
  scene switch could bring it back. A scene bypass is a state, applied by `apply_core_enabled`.
- **A knob touched in one scene is written in every scene.** `scene_bake.touched_params(preset)` collects the
  parameters overridden by at least one scene; each scene then writes them: the scene's override, else the
  block's base, else the catalogue default. A parameter no scene touches is never written.
  (`tests/test_scene_bake.py`.)
- **The live map stays valid between scenes**: `.livemap.json` (expression-pedal index) is rewritten at
  every rebuild, not at every `scene_apply`, since the topology does not move. Per-scene knobs go through
  `apply_block_params`, not the live map.

## 6. Watch points

- **Muted lanes still run** (a muted track is not an offline FX): their CPU is spent. Acceptable on the rack;
  to watch on smaller machines.
- **Some plugins stall the whole engine when they turn on.** A scene that enables one is heard as a gap on
  every track. Such blocks are quarantined by data (`effects.json` `quarantine`); test a block with
  `tools/check-block-stall.py` before offering it
  ([`pitfalls/reaper.md`](pitfalls/reaper.md), "A plugin can freeze the whole audio engine when it turns on").
- Measuring a gap between scenes: `tools/check-scene-gap.py`; scene latency at the real foot:
  `tools/check-scene-latency.py`.

## 7. Not built (PROPOSED)

- Preloading the next N presets of the setlist on persistent tracks, only if rebuild time ever becomes
  audible.
