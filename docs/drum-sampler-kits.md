# Sampled drum kits: from a capture library to a rack kit

> **Status: PROPOSED** (2026-11-20) — design only, nothing is coded. Asked by the maintainer after a review of
> Greg's [`dunkean/drum-toolchain`](https://github.com/dunkean/drum-toolchain) (last commit 2026-09-01). **Blocked on
> one thing outside golem**: that repository carries no licence (see §2). Nothing below copies its code.

Related: [drums-kit.md](drums-kit.md) (rack kits, the `drumkit` block, kit import §8, General MIDI §8.1),
[calibration.md](calibration.md) §5 (Calibration ▸ Drums), [drums-library.md](drums-library.md) (Library ▸ Drums),
[licence.md](licence.md), [golemfm-protocol.md](golemfm-protocol.md) (kit cards).

## 1. What this is for

golem plays drum kits it did not make: three AVL banks, one DrumGizmo kit, and whatever the user imports. Nothing
lets a drummer turn **a kit they own** — an acoustic kit with mics, or their own e-drum module's sounds — into a rack
kit, and golem has no free multi-velocity kit of its own beyond those four.

Greg's `drum-sampler` does the hard part: it fires each articulation of a kit over MIDI at a grid of velocities and
repetitions, records the audio, checks it (peak, clipping, level outliers), and writes a **neutral sample library**
— a JSON manifest plus untouched WAV files — then exports that library as a DrumGizmo 2.0 kit.

The proposal: **golem reads that neutral library as an interchange format and turns it into a rack kit** through the
import pipeline it already has. Later, golem can also run the capture itself (§7).

## 2. The prerequisite: licences, two of them

**The code.** `drum-toolchain` has no `LICENSE`: by default all rights are reserved, and golem (GPL-3.0-or-later)
cannot take any of it, public or not. golem does not need its code — §4 writes golem's own reader and SFZ writer —
but it relies on the **format**. Ask Greg for:

- MIT (or Apache-2.0) on `contracts/schemas/sample-library.schema.json` and the capture-session schema, so golem can
  ship the schema and a validator as interchange specifications, MIT like golem's own (`licence.md` §2);
- ideally MIT or GPL on `apps/drum-sampler`, so that golem can run it as a tool, or take its exporter if a later
  decision says so.

Until he answers, golem reads only what the published schema says.

**The sounds.** Each take carries `source` and `license_statement`. Captured audio inherits the rights of what was
captured:

| captured from | the user may play it on their golem | golem may ship it or share it |
|---|---|---|
| an acoustic kit the user recorded | yes | if the user says so (a free licence) |
| the user's own sounds on a module (user samples) | yes | if the user says so |
| a module's factory sounds (DDrum4, Roland, Alesis…) | yes, local use | **no** |
| a commercial software drummer (Superior Drummer 3, EZdrummer, BFD…) | yes, local use | **no** — its EULA forbids redistributing its samples, re-recorded or not |

Greg's current campaigns capture SD3 through a loopback, so his libraries are of the last kind: playable on his own
golem, never a factory kit and never uploaded. golem therefore treats a sampled kit like an imported kit (§5): local
only, a card on golem.fm and never the audio, unless the library declares a free licence for **every** take.

## 3. The input: a neutral sample library

`schema_version: 1`, `kind: "neutral-sample-library"`, as Greg's schema defines it:

```json
{ "schema_version": 1, "kind": "neutral-sample-library", "id": "kit-metalcore-4",
  "channel_layout": ["left", "right"],
  "takes": [ { "instrument": "snare1", "articulation": "center", "note": 38, "channel": 10,
               "velocity": 104, "repetition": 2, "raw_file": "snare1__center__v104__rr02_raw.wav",
               "prepared_file": null, "sample_rate": 48000, "channels": ["left", "right"],
               "peak_dbfs": -3.1, "rms_dbfs": -18.4, "clipped": false, "sha256": "…",
               "source": "acoustic kit, studio B", "license_statement": "CC0-1.0",
               "processing_history": [], "status": "captured" } ] }
```

What golem uses: `instrument` + `articulation` (what the piece is), `velocity` and `repetition` (the layer and the
round robin), `prepared_file` or else `raw_file` (relative to the manifest), `sample_rate`, `channel_layout` (one to
four named channels), `rms_dbfs` (the layer's real level), `clipped`, `sha256`, `source`, `license_statement`. Only
`status: "captured"` takes count. The capture's `note` is the note that triggered the source; it says nothing about
the rack's notes.

The masters are 48 kHz, 32-bit float, the rack's rate — no resampling.

## 4. What golem does with it

### 4.1 Recognised by the existing import

Library ▸ Drums ▸ "+ Add" (`bridge/kit_import.py`) gains a third kind of folder next to DrumGizmo and SFZ. `scan()`
recognises a `*.json` whose `kind` is `neutral-sample-library`; `read()` reports before writing, as it does today:

- name, number of pieces, layers per piece (velocities) and round robins, channels, rate, total size, free space;
- the **licence verdict** of §2: "free for every take" or "this golem only", with the takes that decide it;
- takes refused, each with its reason: missing file, `sha256` mismatch, `clipped: true`, a different sample rate;
- the pieces → elements mapping of §4.2, with the pieces it did not recognise listed, never guessed.

`install()` copies the WAV files (hard links when the volume allows, never moves: the library stays intact), writes
the kit, and keeps the manifest next to it as `library.json`, so a later golem can rebuild the kit with a better
writer without the user re-importing.

### 4.2 Pieces become golem elements

The rack's vocabulary is `drumkits.ELEMENTS` (kick, snare, snare-rim, snare-xstick, tom1…tom4 and rims, hh-open,
hh-half, hh-closed, hh-pedal, hh-splash, crash1/2 and edges, ride, ride-edge, ride-bell, splash, china, aux1–3…).
A sampled library names pieces freely (`kick_metalcore` / `head`, `snare1` / `rimshot`, `hihat` / `edge-half`).

- A table **in data** — `library/catalog/sample-articulations.json` — maps articulation names to the element suffix
  (`center`/`head` → piece, `rimshot` → `-rim`, `sidestick`/`xstick` → `-xstick`, `edge` → `-edge`, `bell`,
  `closed`, `half`/`semi-open`, `open`, `pedal`, `splash`); the instrument name goes through the existing
  `kit_import.guess_element()`.
- Two instruments that land on the same element (`snare1` and `snare2`, `kick_metalcore` and `kick_dnb`): the first
  takes the element and the next ones become `aux1`…`aux3`, then free notes. That is the existing import rule
  ("nothing is lost"), and each move is written in `notes_note`.
- Then the kit is rewritten in **General MIDI** exactly as an imported kit is (`_gm_moves`, §8.1), so grooves, demos
  and the drum machine play it on the right pieces, and an e-drum reaches it through its descriptor.

Greg's model of **one pad, one logical sound per scene** (the stack that plays "Glitch" in a DnB song) is not part of
this import: on golem it is several rack kits in one patch, one per scene (`scene_bake.annotate_drumkit_union`).
Whether a single kit should switch sounds per scene is the subject of another design.

### 4.3 The written kit: SFZ first, DrumGizmo for several mics

| library | engine written | why |
|---|---|---|
| 1 or 2 channels (stereo mix) | **SFZ** (`library/sfz/<id>/kit.sfz`, played by sfizz) | sfizz plays on Linux, Windows and macOS; DrumGizmo has no Windows or macOS build (`drums-kit.md` §8) |
| 3 or 4 named channels (`kick`, `snare`, `left`, `right`…) | **DrumGizmo** on Linux (`library/drumkits/<id>/`), plus an SFZ of the summed stereo everywhere | DrumGizmo keeps the mics apart and golem already gives it a factory `mix[]` |

**The SFZ, written by golem** (it already writes flat SFZ in `kit_import.py`):

- one `<group>` per element, `key=` its GM note;
- one velocity layer per captured velocity: `lovel`/`hivel` split halfway between neighbouring captured velocities;
  the layer's `amp_velcurve` follows its measured `rms_dbfs`, not the MIDI velocity, so a soft layer is not
  turned up to the level of a hard one;
- round robins: `seq_length` = repetitions, `seq_position` = repetition (deterministic; `lorand`/`hirand` would be
  the random choice — §8);
- hi-hat: `group`/`off_by` so a closed or pedal note chokes the open and half-open ones; cymbal choke by aftertouch
  is §8;
- `<control> default_path=` points at the kit folder, and paths stay relative.

**The DrumGizmo kit**: `drumkit.xml`, `midimap.xml` (GM, so no `midimap-gm.xml` rewrite is needed), one instrument
per element, one `<sample>` per take. A sample's `power` must be its **measured energy** (from `rms_dbfs`): DrumGizmo
picks the sample whose power is closest to the hit. Greg's exporter writes `velocity / 127` there — fine for its own
use, not for a kit whose layers were captured at uneven levels. The `mix[]` comes from channel names (`kick` → group
`kick`, `snare` → `snare`, `left`/`right` → `oh` panned hard), as an imported DrumGizmo kit does today.

The kit file is an ordinary imported kit (`drums-kit.md` §4) with one more field:

```json
{ "id": "kit-metalcore-4", "name": "Metalcore 4 (sampled)", "role": "drum", "engine": "sfz",
  "sfz": "library/sfz/kit-metalcore-4/kit.sfz", "notes": { "kick": 36, "snare": 38, "…": 0 },
  "notes_note": "sampled: 31 pieces, 3 kept on free notes (kick_dnb → aux1 …)",
  "imported": { "at": "…", "from": "…/kit-metalcore-4/library.json", "bytes": 0, "files": 0,
                "sample_rate": 48000, "bits": 32 },
  "sampled": { "library_id": "kit-metalcore-4", "layers": 7, "round_robins": 3, "channels": ["left", "right"],
               "licence": "local-only", "sources": ["Superior Drummer 3 (Toontrack)"] } }
```

## 5. What it does not change

- **Imported means local.** A sampled kit is deletable and shows "this golem only"; its folder goes with it. golem.fm
  gets its card (`tones_sync`, `kind: "kit"`, `card: true`) and never the audio — unless `sampled.licence` is a free
  licence declared for every take, and even then only when the user chooses to share it (golem.fm work, not this
  design).
- **No factory kit is made this way** until the maintainer records a kit with a free licence and adds its seed to
  `library/kits-factory/` as a rack update.
- The drum machine, the Standards player and the e-drum path are untouched: they all reach the kit through its
  `notes` and the GM rules of §8.1.

## 6. A prerequisite inside golem: SFZ on a drums lane

Today the `drumkit` block on a lane plays **avldrums and DrumGizmo only**; `sfz` and `rs5k` are "not ported to a lane"
and logged as such (`drums-kit.md` §5). The drum machine already loads SFZ (`golem_drums.lua`). Without that port, a
sampled SFZ kit would play in the drum machine and in demos, and stay silent on an e-drum's lane — exactly where a
drummer wants it. **Step 1 of §9 is that port**, in `golem_rig.lua` `build_drumkit_block` (the sfizz LV2 state on
Linux, `sfizz_vst3_set_file` on Windows and macOS, as the piano already does) and in the Golem Engine's watcher.

## 7. Later: golem runs the capture itself

The rack already holds every piece of a capture rig: a MIDI output to the module (`midi_out.py`), the module's audio
on a lane, a recorder, and an idle gate (`reamp.busy_reason`). Calibration ▸ Drums (`calibration.md` §5) already
knows the module's notes from its descriptor. A "Sample this module" action would:

1. propose the grid from the descriptor (every element it has, 6–8 velocities, 2–3 round robins) and show its
   duration — for 30 articulations × 8 velocities × 3 repetitions at ~5.4 s a hit (pre-roll, tail, cooldown), about
   65 minutes;
2. ask for the source and the licence before starting (§2), and require an explicit start: it plays sound and
   records, so it never starts by itself and refuses while the rack is busy;
3. write a neutral sample library (§3) — the same file Greg's tool writes — and hand it to §4.

It sends notes only. It never writes to a module (no SysEx, no bank transfer): Greg's DDrum4 bank builder, DDTi
editor and Arduino firmware stay in his repository.

## 8. Open questions

- **For Greg**: the licence (§2); whether `rms_dbfs` is measured on the prepared or the raw file; whether he wants
  golem's SFZ writer upstream (it would give his libraries a Windows player besides SD3).
- **sfizz**: whether its `output=` opcode (several stereo outputs) is reliable enough on all three OS to drop the
  DrumGizmo path for multi-mic libraries; how it chokes a cymbal on polyphonic aftertouch (the descriptor's
  `choke: "poly-aftertouch"`). To measure before step 3.
- **Round robins**: fixed sequence (`seq_*`, a reproducible demo fingerprint) or random (`lorand`, more natural)?
  Proposal: fixed in demos and the drum machine, random on a played lane — needs two writes or a switch.
- **Size**: a dense library is gigabytes. Install keeps the masters (32-bit float); a 24-bit copy would halve it at no
  audible cost. To decide with the maintainer.

## 9. Steps, when it is coded

1. SFZ on a drums lane (§6) — under REAPER and the Golem Engine, with `tests/test_rig_lua.py` cases.
2. The neutral-library reader: `scan`/`read` in `kit_import.py`, the articulation table in data, the licence verdict,
   take refusals. Tests on a fixture library (a few generated WAV files, no capture).
3. The SFZ writer (§4.3): layers from measured levels, round robins, hi-hat chokes. A golden render of the fixture
   through `tools/check-rig-materialize.py --render`.
4. The DrumGizmo writer for 3–4 channels (Linux).
5. Library ▸ Drums: the read sheet shows the licence verdict and the refused takes (mockup first).
6. Capture from golem (§7), after its own mockup.

Tests: `tests/test_kit_import.py` (the third kind of folder), a new `tests/test_sample_library.py` (schema, mapping,
licence verdict, SFZ text), `tests/test_rig_lua.py` (SFZ on a lane).
