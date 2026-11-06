---
name: sound-engineer
description: Ask the golem-sound-engineer agent a sound-engineering question about golem (signal chain and block order, gain staging, NAM capture vs IR cab, stereo/mono and the mono fallback, split lanes, scene level jumps, output trims, MIDI outboard pedals). Useful to settle an audio decision before coding the routing, the block catalogue or a preset.
user-invocable: true
disable-model-invocation: false
agent: golem-sound-engineer
---

Ask the golem-sound-engineer agent:

$ARGUMENTS

The agent reasons in signal flow (where in the lane, at what level, why) from golem's real model —
`docs/preset-format.md`, `docs/live-engine.md`, `docs/mixer.md`, `library/catalog/effects.json` — takes a position on
trade-offs, names the failure modes (clipping, phase, mono collapse, double cab, level jumps between scenes, a plugin
that stalls the engine), and answers in golem's terms: lanes, splits, blocks, scene states, stomps, trims. It does
not write code unless asked.
