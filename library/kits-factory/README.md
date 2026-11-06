# Factory kits — versioned seeds

> **Status: CODED** — the drum kits and pad kits that ship with every golem, re-seeded into `library/kits/` by the bridge
> at startup (`bridge/kits.py`, `factory_seeds`, `seed_factory`).

**Drum kits** (`engine` `avldrums` / `drumgizmo` / `sfz`) **ship with the rack**: they are not created, imported or
deleted from any screen, neither on the rack nor on golem.fm. This directory is their source. At startup,
`kits.seed_factory()` writes into `library/kits/` every seed that is missing — or whose copy there is not marked
`factory` (a same-id document is replaced by the seed). For a kit already seeded, it only refreshes the element→note
table (`notes`) when the seed's changes. It touches nothing else. The point of re-seeding: if `library/kits/` is ever
emptied, the factory kits come back on the next start instead of disappearing silently.

A new drum kit = one JSON file here (plus its DrumGizmo/SFZ files under `library/drumkits/` or `library/sfz/`, delivered
by `provision/`), shipped in a rack update. Drum engines and the kit format: [docs/drums-kit.md](../../docs/drums-kit.md).

## Factory pad kits

Pad kits (`engine` `rs5k`) normally follow the full cycle: created on golem.fm, installed by the `kit-install` job,
deletable from the screen. Exception: three pad kits ship with the golem — **House**, **Lo-fi**, **Trap**
(`pads-house`, `pads-lofi`, `pads-trap`). Their sounds were made by procedural synthesis, so they are ours, with no
licence or credit attached. `factory_seeds` accepts an `rs5k` seed only when it carries `factory: true`.

- 16 pads in **General MIDI**, like golem.fm and the grooves, laid out MPC-style: the rack programs each controller pad
  to the GM note of its sound (`kits.DEFAULT_NOTES`). Bank A, bottom row: kick 36 · snare 38 · closed hi-hat 42 ·
  open hi-hat 46; top row: clap 39 · rim 37 · tom 45 · crash 49. Bank B, bottom row: sub kick 35 · pedal hi-hat 44 ·
  low tom 41 · high tom 48; top row: ride 51 · crash 2 57 · bell 53 · cowbell 56.
- Every pad is one-shot (`"mode": "oneshot"`).
- The samples live under `assets/samples/kits/<id>/` and are versioned (about 2.5 MB for the three kits).
