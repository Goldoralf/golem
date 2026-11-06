---
name: reascript
description: Write or review golem's REAPER-side code (ReaScript Lua in reaper/Scripts — golem_watch, golem_rig the engine, service loops, golem_apply dev probes — and JSFX in reaper/Effects; chunks, P_EXT, sends, I_DSTCHAN, gmem, OSC, MIDI) with the golem-reascript-engineer agent. Use whenever a .lua or .jsfx under reaper/ changes.
user-invocable: true
disable-model-invocation: false
agent: golem-reascript-engineer
---

Ask the golem-reascript-engineer agent to handle:

$ARGUMENTS

The agent starts from `docs/architecture.md` and `docs/pitfalls/reaper.md` / `jsfx.md` / `plugins.md`, reads the real
script, checks REAPER API signatures against the ReaScript docs instead of guessing, traces the runtime path as REAPER
would (command, track, chunk state, SETTLE), and checks the known traps: unarmed service tracks, `SetTrackStateChunk`
erasing `P_EXT`, chunks that lie while a plugin loads, `gmem` re-attach, send index and MIDI flags, modal dialogs,
EEL2 case-insensitivity, code before `@init`, bipolar sliders. It runs `tools/check-syntax.py` and says plainly what
still needs validating in REAPER. It does not touch the Python bridge or the app.
