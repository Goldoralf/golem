# Audit 2026-09-21 — scene and stomp latency, and the A→B blank

> **Status: PARTLY CODED** — incident report. The engine-stall findings are fixed in code and data (quarantines,
> convolver "Enable", branch mute); the latency reduction tiers (§4) are proposed, not built.

Question asked: the original rule was "everything is loaded for a preset, so there is no latency" — why does a
scene change take time, and why is there sometimes a blank? Instruments: `tools/check-scene-latency.py` (passive
observer at the real foot controller), `tools/check-scene-gap.py` (sample-accurate gap detector),
`tools/check-block-stall.py` (engine stall per plugin), a dry profile of the bridge. Engine design:
[`live-engine.md`](live-engine.md).

## 1. The blank was an engine stall, not latency

On every entry into scene B of one song, **REAPER stopped processing all tracks for ~520 ms**.

- **How it showed**: the gap detector JSFX counts the samples it *processes*. Over one real second its clock only
  advanced 0.48 s on every A→B, on all four tracks of the lane and on the voice lane too. Other transitions: 0 ms.
- **Culprit**, isolated block by block with the `stomp` command: the **voice lane's echo delay, GxEchoCat**
  (guitarix LV2). Switching it on froze the engine ~524 ms, about one time in two or three. Scene B was the only one
  enabling it. A voice effect can "cut the guitar" because it does not cut the guitar: it stops the engine.
- **Why it was missed**: the first gap tool reported "0 gaps" because a detector that is not running does not see
  silence. **Fixed**: `check-scene-gap.py` compares the JSFX clock with REAPER's and reports "engine frozen n ms".
  Rule kept in [`CLAUDE.md`](../CLAUDE.md): always compare the instrument's clock with a clock independent of what
  is measured.
- **Effect or lane?** `check-block-stall.py` placed a fresh GxEchoCat on a guitar lane: frozen 7 times out of 8,
  519–529 ms. ReaDelay, Calf Vintage Delay and the seven other guitarix plugins of the catalog: 0 stalls in 80. It
  is this plugin, on any lane.

**Whole catalog measured** (`check-block-stall.py --catalog`, then `--rig` with files loaded):

| Plugin | Stall | Action (in code/data) |
|---|---|---|
| GxEchoCat (`delay-echo`) | ~520 ms on enable, 7/8 | `quarantine` in `library/catalog/effects.json`; replaced by Tape Delay (Calf) in the affected presets |
| ReaPitch (`pitch`, ships with REAPER) | ~435 ms on enable, ~97 ms on disable, 12/12 | `quarantine` |
| x42 IR convolver (`cab`), re-enabled with its IR | ~540 ms (0 ms when empty) | never bypassed: the engine toggles its internal **"Enable"** parameter (`golem_rig.lua` `switch_param_of` → `fx_set_on`): 0–2 ms |
| 34 other plugins, NAM captures included | 0 | — |

A quarantined block is removed from the drawer, the AI vocabulary and the compile (`rig._drop_quarantined`).

Two more findings applied the same day:

- **Branches are silenced by track/send MUTE again**, not by volume 0: the volume workaround rested on a wrong
  cause; measured no audible difference (0 gaps, 0 stalls, ~11 ms transition, no click). One lever, one meaning.
- **Instrument trap**: `stomp` targets a block by its `golem:<id>` label, which core blocks (NAM amp, cab) did not
  always carry; a first pass "measured" them at 0 ms without touching them. The tool now toggles by **position**
  (`fxenable` command). Always verify the gesture reached its target before trusting the measure.

Still unexplained: one event where a scene took 1.07 s, the next five waited 20 s and REAPER died with no crash
trace; on restart the B-branch captures were not loaded.

## 2. Latency: what the engine does on a scene press

The engine keeps its promise (no plugin load, no FX surgery, tails ring through) but **no time budget was ever
set**. Everything is loaded; what is recomputed on each press is the **path** to the plugins. Measured at the real
foot controller (17 presses): **~100 ms from press to scene applied** (max 108), for any scene.

| Step | Where | Cost |
|---|---|---|
| controller sends PC + CC + Note | MIDI | ~3 ms |
| `foot.py`: the PC is queued first (a no-op: preset already loaded) | bridge, MIDI thread | ~1 ms + a queue slot |
| CC hops to the asyncio loop, then the engine's single-worker queue | bridge | variable |
| `do_recall`: re-reads the preset, re-bakes the scene, recompiles the plan (~177 JSON reads), rewrites `<id>.rig.json`, `.perfsrc.json`, `.live.json`, foot summary, reservations | bridge | ~50 ms (13 ms is the compile itself) |
| `write_command`: waits for the single command slot (up to 0.9 s) | bridge | 0–900 ms |
| — command written | | +54 ms median |
| `golem_watch` reads it on its `defer` tick | REAPER main thread | 0–33 ms |
| `dofile(golem_rig.lua)`: recompiles ~3000 lines, decodes the command, the plan, the preset and `effects.json` (117 KB, pure-Lua JSON) | REAPER | — |
| `reapply_scene`: checks files, sets tempo, then for every block of every lane: enable + every parameter | REAPER | — |
| **last**: the branch mutes — the only audible change | REAPER | — |
| — scene applied | | +99 ms median |

A stomp follows the same path. The **expression pedal** goes straight: OSC `set_fx_param` with an address from the
livemap computed at load — the only path that matches the original intent.

**Why it is sometimes worse** (from the code; the first two measured):

| Cause | Effect |
|---|---|
| long-press slot capture on SW1 swallowed the next scene | fixed (1.5 s + banner) |
| one command slot shared by every service (click, backing, drums `stop_orphans` 0.8 s after each scene, tuner, probes); a scene behind waits for the ack | 100 → 1000 ms |
| file verification re-runs ~2 s after every scene on REAPER's main thread (`golem_watch` `verify_at`) | a scene ~2 s after the previous one waits |
| the scene CC crosses the bridge's asyncio loop, which any slow route holds | variable |
| the PC before each press recalls the whole preset if the active setlist line is not the expected one | ×2 on the first press |

## 3. SWS LiveConfigs

The app's licence page claimed "the scene engine relies on" SWS LiveConfigs. Measured: no Live Config existed and
no code called a `_S&M_LIVECFG_…` action; an early Lua imitation borrowed the name and was later disconnected. The
claim was removed from `provision/components.json`. The plugin itself (one row = one track, small mute fades,
triggered inside REAPER, configured by hand in the project with no ReaScript API) cannot express a golem scene (N
lanes, blocks and knobs on shared tracks), but it confirms the direction: everything preloaded, mute/unmute with a
short fade, trigger inside REAPER. `tools/bench-liveconfigs.py` was written to measure it as a reference; it did not
switch on the third try and remains unfinished.

## 4. Proposed: three tiers (not built)

Principle: **a scene is a table computed when the preset loads; playing it is reading it, never recomputing it.**
Budget: press → scene applied ≤ 40 ms at the 95th percentile, measured with `check-scene-latency.py`.

1. **Trim the current path (~45 ms)**: the scene CC bypasses the asyncio loop; a same-slot PC is dropped in the MIDI
   thread; all scene plans compiled at preset load; send the command first, bookkeeping after; branch mutes first in
   `reapply_scene` (keeping unmute-then-mute order); no file verification on a scene (only after a rebuild); keep
   `effects.json`, the plan and the BPM in memory; set tempo only if it changes.
2. **Resident scene table (~20 ms)**: at load `golem_rig` resolves, per scene, the exact writes that differ (FX
   enable, normalized param values, volumes); a resident `defer` loop holds them; a separate channel for *playing*
   (scene, stomp) that does not share the command slot.
3. **Switch in the audio thread (a few ms)**: a JSFX per branch driven by `gmem`, 5 ms crossfade. Going below the
   `defer` tick would need the controller's MIDI inside REAPER too, which conflicts with the bridge holding the ALSA
   port — to prove first.

Each tier is judged by measurement at the real foot before the next, with `check-scene-gap.py` after every engine
change.
