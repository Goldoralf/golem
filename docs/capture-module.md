# Controllable capture modules

> **Status: CODED — experimental captures.** One captured plugin occupies one block
> in a golem chain. Its learned knobs move during playback, its drive stages switch
> independently, and scenes recall their values. The original VST and trainer are
> needed only to create the capture.

## Use

Import a `.gcap` with **Library → Tones → + Add → Import files** ([`tone-import.md`](tone-import.md)), then select it when adding
a Head+Cab capture block. Open its sheet for the controls and **Export autonomous
module**. There is no Apply/bake step. Knobs stay inside their measured ranges.

Each captured stage switch has a **MIDI switch** selector (6–10). These assignments
use golem's existing device contract: default CC30–34, on the device's wire channel.
They can share a switch with ordinary golem pedals. A stage switch does not bypass
the complete capture block.

On a paired phone, open **Mine** for the lane containing the module. Its switches
and knobs appear below the ordinary pedals. Phone writes are restricted to that
phone's lanes, carry the current preset/scene, and reject stale scene requests.
The screen refreshes MIDI switch changes. Phone knob edits are saved in the current
scene and reflected into a matching Designer draft with a new edit revision.
MIDI stomps remain live overrides until the next scene, like other golem stomps.

The preset still holds one capture block (`type: amp`, `amp-nam` or `pedal-nam`,
with `ref`/`model`). `capture_foot` maps its internal switches to physical switches.
Derived `capture_controls` describe the slots for the pure preset/MIDI view.
The audio compiler turns the block into one `capture-module` processor.

## Portable data and playback

A `.gcap` is JSON with `format: golem-capture-1`, a name, ordered `controls` and
ordered `stages`. Each stage embeds a complete NAM model, its ordered control IDs,
and an optional enable-control ID. Definitions include stable IDs, names, measured
min/max/default values, groups and `kind: knob|toggle`. Limits: 32 controls, eight
mono stages, 32 MiB. The complete bundle is also embedded in REAPER state.

This is golem's module format, **not a standard TONE3000 `.nam` file**. The separate
fixed A2 example pack remains usable in TONE3000 without live controls. A module
contains no VST path, plugin chunk, licence, executable or training environment.
Its reader is installed by golem; sources, pinned dependencies, notices and bundled
Windows/Linux x64 readers are in [`native/capture`](../native/capture/README.md).
Other Linux architectures compile the same reader during provisioning. macOS/ARM
need hardware validation; an unsupported desktop does not build a reader at launch.

The CLAP processor runs NAM HyperWaveNet directly. Knob changes update conditioned
weights without file generation, Python, Torch, subprocesses or model reloads.
Model histories are preserved. Knobs have an 8 ms smoothing constant; stage bypass
uses an 8 ms dry/wet ramp and keeps the model warm. Playback is raw: per-setting
loudness normalization would cancel a learned Level/Volume knob. The model rate
is 48 kHz, with resampling for other host rates. The captures are mono.

Capture backups include the selected `.gcap`. For another golem, export/import
the module file: every stage travels inside it. golem.fm tone-pack sync of this
format is not yet validated; there is no automatic public upload.

## Creating captures

**Capture → With controls** installs a live `.gcap` as the primary result, retaining
the ordinary NAM snapshot and full parametric source as developer exports.
Multiple independently captured stages can be assembled with
`bridge.capture_module.build`. Automatic decomposition of arbitrary VST signal graphs is not
implemented: stages must be captured with other stages disabled, then assembled in the original order.
A module approximates the sampled knob ranges; nothing establishes accuracy at every possible combination.

## Verification

- `python -m pytest -q tests/test_capture_module.py`: one block, scenes, actual MIDI
  reader/dispatcher, phone ownership, ranges and stale-scene rejection.

The benches that compared a module built on one named commercial plugin with the original, in REAPER
and in the UI, were removed on 2026-10-20 with that plugin's example ([`plugin-capture.md`](plugin-capture.md) §9).

Tests do not start a recording or replace the user's playing rig. The
automated MIDI check injects the controller's CC message format; physical hardware
still needs the corresponding golem device configuration.
