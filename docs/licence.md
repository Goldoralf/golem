# Licensing

> **Status: CODED** — which licence covers which part of the repository, as declared by
> [`LICENSE`](../LICENSE), [`LICENSE.MIT`](../LICENSE.MIT) and the `SPDX-License-Identifier`
> header of each file.

Related: [`CONTRIBUTING.md`](../CONTRIBUTING.md) (how contributions are signed),
[`TRADEMARK.md`](../TRADEMARK.md) and [`SECURITY.md`](../SECURITY.md).

## 1. The rule

**golem is GPL-3.0-or-later** ([`LICENSE`](../LICENSE)). Three deliberate exceptions:

| Part | Licence | Where it is declared |
|---|---|---|
| Everything not listed below: `bridge/`, `app/`, `reaper/Scripts/`, `provision/`, `tools/`, `plugins/` (Rust), tests, configs | **GPL-3.0-or-later** | `LICENSE`; `SPDX-License-Identifier: GPL-3.0-or-later` in each source file (`#`, `--` or `//` comment), `license = "GPL-3.0-or-later"` in `plugins/Cargo.toml` |
| The in-house JSFX, the interchange-format specifications and the `.golem` parser module (§2) | **MIT** | [`LICENSE.MIT`](../LICENSE.MIT), copied as `reaper/Effects/LICENSE`, lists the paths; `// SPDX-License-Identifier: MIT` on line 2 of each JSFX and at the top of `bridge/golemfile.py` |
| Factory presets, patches and drum grooves (§5 bis) | **CC0 1.0** | This page |
| `reaper/Effects/golem_super8` | **LGPL-2.0-or-later**, same terms as its upstream (§3) | Its header (`// SPDX-License-Identifier: LGPL-2.0-or-later`) |
| `tools/fcb/fcb1010.py` | **MIT**, copyright riban-bw (§4) | Its header and [`tools/fcb/LICENSE.fcb1010`](../tools/fcb/LICENSE.fcb1010) |

A redistributed fork of the rack must publish its source (GPL). The rack is an application, not a
library, so copyleft costs no adoption here. AGPL is not used: the rack runs on its owner's
machine and is not a network service.

The bundled **golem Capture** reader is GPL-3.0-or-later. It links pinned MIT NAM core,
CLAP and AudioDSPTools code, and MPL-2.0 Eigen. Notices are in
[`native/capture/licenses`](../native/capture/licenses/) and the reader archives;
complete source and dependency revisions are in
[`native/capture`](../native/capture/README.md).

## 2. The MIT subset

**Why MIT.** These are the only pieces that travel alone: a JSFX can be dropped into any REAPER
project, and a file format is only a format if anyone, including closed tools, may implement it.

### In-house JSFX — `reaper/Effects/` (35 files)

Every file below carries `// SPDX-License-Identifier: MIT`:

| File | What it is |
|---|---|
| `b3-ctl.jsfx` | setBfree (B3 organ) CC injector |
| `drum-tap.jsfx` | Sniffs notes, aftertouch and CC from a drum module into gmem `golem_drumlearn` (pass-through) |
| `dx7-ctl.jsfx` | Dexed cartridge loader and patch select (`dx7-cart.txt` is its data file) |
| `golem_chordseq.jsfx` | Tempo-synced MIDI chord and bass player (standards) |
| `golem_click.jsfx` | Tempo-synced audio click |
| `golem_deesser.jsfx` | De-esser |
| `golem_eq.jsfx` | Parametric EQ, the `eq-para` block on Windows (x42-eq parameter names) |
| `golem_drummix.jsfx` | Drum mixer, 16 mic channels to the stereo bus |
| `golem_drumseq.jsfx` | Tempo-synced MIDI drum pattern player |
| `golem_drumtrans.jsfx` | E-drum module notes to rack kit notes |
| `golem_gapmeter.jsfx` | Sample-accurate gap detector (`tools/check-scene-gap.py`) |
| `golem_grit.jsfx` | Multiband grit, the `grit` block on Windows and macOS (Prisma's parameter interface; own DSP) |
| `golem_killswitch.jsfx` | Tempo-synced stutter (Kill Switch block) |
| `golem_safety.jsfx` | Zero-latency safety limiter, ceiling −1 dBFS |
| `golem_tapedelay.jsfx` | Tape delay, the `delay-tape` block on Windows and macOS (Calf Vintage Delay parameter names) |
| `golem_shimmer.jsfx` | Shimmer reverb, the `reverb-shimmer` block on Windows and macOS (GxShimmizita parameter names; own DSP) |
| `golem_wah.jsfx` | Cry Baby wah, the `wah` block on Windows and macOS (Gxgcb_95 parameter names; own DSP tuned on the measured response) |
| `golem_colwah.jsfx` | Multi wah, the `wah-color` block on Windows and macOS (GxWahwah parameters, 7 models, 3 modes; own DSP) |
| `golem_autowah.jsfx` | Auto-wah, the `autowah` block on Windows and macOS (GxAutoWah parameter; own DSP) |
| `golem_chorus.jsfx` | Multi-voice chorus, the `chorus` block on Windows and macOS (Calf Multi Chorus parameters; own DSP) |
| `golem_tremolo.jsfx` | Tremolo, the `tremolo` block on Windows and macOS (Calf Pulsator parameters; own DSP) |
| `golem_phaser.jsfx` | Phaser, the `phaser` block on Windows and macOS (Calf Phaser parameters; own DSP) |
| `golem_octaver.jsfx` | Octaver, the `octaver` block on Windows and macOS (Gxoc_2 / Boss OC-2 parameters; own DSP) |
| `golem_rotary.jsfx` | Rotary speaker, the `rotary` block on Windows and macOS (Calf Rotary Speaker parameters; own DSP) |
| `golem_limiter.jsfx` | Look-ahead peak limiter, the `limiter` block on Windows (x42-dpl controls; own DSP) |
| `golem_vibrato.jsfx` | Pitch vibrato, the `vibrato` block on Windows and macOS (GxTubeVibrato parameters; own DSP) |
| `golem_geq.jsfx` | 11-band graphic EQ, the `eq-graphic` block on Windows and macOS (GxGraphicEQ parameters; own DSP) |
| `golem_echocat.jsfx` | Tape echo, the `delay-echo` block on Windows and macOS (GxEchoCat parameters; own DSP, no engine stall) |
| `golem_sample_trig.jsfx` | Fires note-on/off into the RS5k behind it |
| `golem_tuner` | Tuner (pitch to gmem) |
| `knob-tap.jsfx` | Sniffs incoming CC into gmem `golem_knobs` (full MIDI pass-through) |
| `midi-clock.jsfx` | Free-running 24 PPQN MIDI clock at project tempo |
| `note-zone.jsfx` | Keyboard split/layer filter |
| `sysex-io.jsfx` | Receives and sends a controller's SysEx (gmem `golem_sysex`) |

A new JSFX added to `reaper/Effects/` is MIT only if it carries the MIT header; without one it falls
under the repository's GPL. Put the header on line 2, after `desc:`.

### Format specifications and examples

| Spec | Files |
|---|---|
| `.gsx` chord grids | [`standards-format.md`](standards-format.md) and the `.gsx` files in [`examples/`](examples/) |
| Preset format | [`preset-format.md`](preset-format.md) and the `.json` examples in [`examples/`](examples/) |
| `.golem` archive | [`golem-format.md`](golem-format.md) and its parser module `bridge/golemfile.py` (since 2026-10-20, on the lawyer's advice: golem.fm and a future desktop reader embed it) |

[`LICENSE.MIT`](../LICENSE.MIT) lists these paths; the tables above are the exact list. Other format
documents are under the repository's GPL until they are added here.

## 3. The LGPL exception — `golem_super8`

`reaper/Effects/golem_super8` is a minimal fork of Cockos' stock **Super8** looper JSFX, which
ships under the LGPL. It stays under **the same terms as its upstream**: it cannot be relicensed as
MIT, and it does not need to become GPL (the LGPL is compatible). Every golem change is marked
`// GOLEM:` in the file.

**Version:** the Cockos header kept in the file says "LICENSE: LGPL v2 or later", so the file is
**LGPL-2.0-or-later**; it carries `// SPDX-License-Identifier: LGPL-2.0-or-later` on line 2, after
`desc:`.

## 4. Third-party code in the tree

- **`tools/fcb/fcb1010.py`** comes from <https://github.com/riban-bw/fcb1010> and keeps its **MIT**
  licence (`# SPDX-License-Identifier: MIT`, full text and copyright in
  [`tools/fcb/LICENSE.fcb1010`](../tools/fcb/LICENSE.fcb1010)). The rest of `tools/fcb/` is
  GPL-3.0-or-later.
- **`golem_super8`**: see §3.

Any other file copied from elsewhere must keep its original licence and say so in its header, with
the upstream URL and the licence file next to it.

## 5. What the repository does not contain

- **REAPER** is proprietary and keeps its own licence. golem installs it (`provision/install-reaper.sh`,
  `provision/desktop.py`); it does not redistribute it.
- **Plugins** (NAM, Vital, Surge XT, sfizz, guitarix, Calf, x42, ZamAudio, BYOD, DrumGizmo,
  Airwindows…) each keep their own licence. None is in the repository: the installer downloads or
  builds them from pinned sources. **Settings ▸ About** in the app lists the embedded components
  and their licences (`app/page-licenses.js`, `GET /api/system/libraries` from
  `provision/components.json`).
- **Played content** — NAM captures, IRs, takes, the DrumGizmo kits — is never versioned. The repository versions
  recipes and seeds, and three exceptions: the factory pad kits (`assets/samples/kits/`, 48 one-shots synthesized by
  golem's own drum synthesizer), the three example chord grids of [`examples/`](examples/) (the factory standards) and the test content's grids
  (`library/test-content/`). The attributions that third-party content requires ship with it:
  `library/drumkits/CREDITS.md` (The Aasimonster, CC BY 4.0), `library/factory/dx7/CREDITS.md`.
- **golem.fm** is a separate, closed service. The rack works without it.

## 5 bis. Factory content

- **Everything golem's authors made for the factory** is dedicated to the public domain under **CC0 1.0
  Universal**: use it, change it and record commercial music with it, with no restriction and no attribution
  required (decided 2026-11-02). That is the factory presets, patches, drum grooves and setlists
  (`library/factory/presets/`, `patches/`, `grooves/`, `setlists/`), the three factory standards
  (`library/factory/standards/`, original compositions, and their copies in `docs/examples/`), the factory pad kits
  (`assets/samples/kits/`, synthesized by golem's own drum synthesizer), the block presets
  (`library/block-presets/`) and the demonstration song **Golem Rising** (`library/factory/songs/`: the
  composition, its parts and its artwork — the artwork was made by golem's authors with an image generator).
- **Third-party content keeps its own licence**, credited next to it: the DX7 cartridge
  (`library/factory/dx7/`, SynprezFM as distributed with Dexed, GPL-3.0 — `CREDITS.md`), the Vital presets
  (`library/synth/vital/factory/`: 17 by unfa, CC0; *Hard Synthwave* by "JH", licence not found — being sorted out), the DrumGizmo kit credits (`library/drumkits/CREDITS.md`, CC BY 4.0),
  and the TONE3000 captures, which golem never ships: a factory patch names the capture (title and creator) and the
  user downloads it from TONE3000 with their own account.
- **The name and the logo** (`app/icons/`, `logo.png`, made by golem's authors) are not covered by CC0: they are
  trademarks (§6, `TRADEMARK.md`).

## 6. Trademarks

The GPL-3.0-or-later covers the source code only and grants no right to the names and logos "golem", "Golem ONE"
and "golem.fm" (GPL v3 Section 7(e)). A fork or a modified redistribution must remove the name "golem" and its
logos from its interface and its binaries. The policy, from the lawyer's text of 2026-10-20, is
[`TRADEMARK.md`](../TRADEMARK.md).

## 7. Contributions: DCO, no CLA

Contributions are signed off under the Developer Certificate of Origin ([`DCO`](../DCO),
`git commit -s`); there is no CLA. A contribution lands under the licence of the file it touches
(§1). Because nobody assigns their rights, the project can never be relicensed without every
contributor's agreement. Details: [`CONTRIBUTING.md`](../CONTRIBUTING.md).
