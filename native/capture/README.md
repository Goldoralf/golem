# golem Capture

**Status: CODED.** One mono CLAP processor runs a captured plugin's NAM stages,
including continuous HyperWaveNet controls and independent drive switches.
The golem Designer and Companion provide its UI. Playback uses no Torch, Python
training environment or original VST. The bridge sends normalized host parameters;
it never bakes or reloads a NAM when a knob moves.

The complete capture is a `.gcap` JSON bundle containing learned models and their
control definitions. REAPER state embeds this bundle. Parameters have 32 fixed
automation IDs; the bundle maps its control order onto these slots. Each stage
keeps processing while bypassed, and its dry/wet switch fades over 8 ms. Knobs
have an 8 ms smoothing constant. NAM runs at 48 kHz; other host rates use the
pinned AudioDSPTools resampler. No per-position loudness normalization is applied.

Build with CMake 3.22+, a C++20 compiler and Ninja:

```sh
cmake -S native/capture -B build/capture -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/capture --parallel 2
```

Dependencies are pinned in `CMakeLists.txt`:

- [NeuralAmpModelerCoreParametric](https://github.com/phillipmself/NeuralAmpModelerCoreParametric/tree/fddcbc91e74ba79066a43c3b73cc690073529232), MIT.
- [CLAP headers](https://github.com/free-audio/clap/tree/a47f6badb49d948fd009998f28309cdab78979c9), MIT.
- Eigen, MPL-2.0, and AudioDSPTools, MIT, at the NAM core's pinned submodules.

The notices are in [licenses](licenses/). golem's own code is GPL-3.0-or-later.
Windows uses statically linked GCC runtimes under the GCC runtime exception.
`tools/package-capture-player.py` bundles a compiled reader with notices, source
hashes and binary/archive SHA-256. `provision/capture_player.py` verifies and installs
it as part of golem setup/start. The bundled Windows x64 and Linux x64 builds need
no compiler on the playback machine. Other Linux architectures build the same pinned
source during provisioning. macOS and ARM playback require hardware validation;
an unsupported desktop never starts a network build merely to launch golem.

On Linux the reader exports only `clap_entry`: its NAM core would otherwise share one registry with the
NAM plugin loaded in the same REAPER and kill it
([pitfall](../../docs/pitfalls/plugins.md#linux-two-plugins-embedding-the-nam-core-share-one-registry)).
The Linux build of 2026-10-25 carries that change.

**CPU.** x86-64 builds target `x86-64-v3` (AVX2/FMA), the level golem already requires for its NAM
plugin, and the reader uses the NAM core's fast tanh, as the NAM plugin does. Measured with
`capture_render` on 2026-10-25 (Ryzen, 48 kHz, 128 frames). Titan Dynamic Waters has three stages,
and each one runs even when it is bypassed. It went from 54 % of one core (worst block 4.5 ms, over the
2.67 ms budget) to 11.5 % (worst block 0.5–1.3 ms). Titan Enough Gain went from 21 % to 3.7 %. The output
differs from the `std::tanh` build by −50 to −58 dB RMS, which is below the capture's own error. The
Windows reader of 2026-10-25 is cross-built with Debian trixie's `g++-mingw-w64-ucrt64` (GCC 14, UCRT,
static runtimes). It has the same imports as the original WinLibs UCRT build: UCRT and KERNEL32 only, with
`clap_entry` as its only export. Under Wine, its `capture_render.exe` gives output bit-identical to the
Linux build on both Titan captures, at 48 and 44.1 kHz. It has not been run in REAPER on Windows.

`capture_render` is an offline float32 mono bench using the exact same DSP as
the CLAP processor. Its controls JSON accepts initial values plus optional
`events: [{frame, values: {control_id: value}}]` for movement in one live instance.
It reports processing time, real-time ratio and worst block time.
