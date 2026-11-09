# Platforms — Linux, Windows, macOS

> **Status: PARTLY CODED** — Linux is the reference platform. Windows is coded and tested on a
> virtual machine and on real hardware. macOS is coded but **has never run on a Mac**: every macOS
> path is proven only by tests with simulated outputs and by an on-demand CI job.

Related: [`installer.md`](installer.md) (the graphical installer on all three systems),
[`network.md`](network.md), [`rack-hardware.md`](rack-hardware.md), [`plugins.md`](plugins.md),
[`plugin-window.md`](plugin-window.md), [`troubleshooting.md`](troubleshooting.md).

## 1. One engine, three hosts

The same code runs everywhere: the bridge (`bridge/`), the app (`app/`), the REAPER scripts and
JSFX (`reaper/`). What differs per OS lives behind `sys.platform` branches, mostly in
`bridge/desktop_*.py` (`desktop_audio`, `desktop_midi`, `desktop_network`, `desktop_reaper`,
`desktop_macos`) and `provision/desktop.py` (the Windows/macOS launcher). Paths come from
`bridge/config.py`: `reaper_resource_dir()` is `~/.config/REAPER` on Linux, `%APPDATA%\REAPER` on
Windows, `~/Library/Application Support/REAPER` on macOS (`GOLEM_REAPER_RESOURCE_DIR` overrides).

| | Linux | Windows | macOS |
|---|---|---|---|
| Target | x86-64, apt: Ubuntu 24.04 (reference) and 26.04, Debian 13, Linux Mint 22 | Windows 10 (build ≥ 19041) / 11 x64 | Apple Silicon (arm64) |
| Audio API | PipeWire / JACK / ALSA | ASIO (the card's **native** driver) | Core Audio |
| Plugin formats the core uses | LV2 (NAM LV2, x42 convolver — both compiled by the rack) | VST3 (official NAM `NeuralAmpModeler` 0.7.13 or 0.8.0) | VST3 (same) |
| REAPER hidden | Virtual X display (Xvfb, `provision/start.sh`) | Win32 window hiding (`provision/desktop_window.py`) | `open -j` + System Events |
| Launcher | `golem` (`provision/golem`) | `python -m provision.desktop` | `python -m provision.desktop` |

## 2. Installing

The normal path on every OS is the graphical installer ([`installer.md`](installer.md)).

**Linux.**

```sh
curl -fsSL https://get.golem.fm | sh        # or, from a clone: ./install-linux.sh
```

`provision/bootstrap.sh` checks the minimum (x86-64 is blocking, a system outside the tested ones is a warning,
`python3`, `curl`), fetches the latest release into `~/.cache/golem-installer/golem-<tag>`
(`GOLEM_REF` forces a tag, `GOLEM_SRC` uses a local tree), and starts the graphical installer, which
runs `provision/install.sh`. Without the GUI, from a clone: `./provision/install.sh`
(`--light` skips downloads, `--engine=<id>`, `GOLEM_PACKS=<list>`), then `provision/install-desktop.sh`
for the `golem` command and icons.

**Windows and macOS — graphical.** Windows: `irm https://get.golem.fm/win | iex`
(`provision/bootstrap.ps1`), or double-click `install-windows.cmd` in a clone. macOS: double-click
`install-macos.command` in a clone. Both install Python if needed (Windows) and open the installer.

**Windows and macOS — by hand,** from the repository root, REAPER closed, in a **writable** user
folder (presets, recordings and caches live under the project root, so not `Program Files` or
`/Applications`):

```text
python -m provision.desktop setup
python -m provision.desktop start
```

- `setup` creates `.venv`, installs `bridge/requirements.txt`, copies the scripts and JSFX into
  REAPER's resource folder and adds the `golem` OSC surface to `reaper.ini`. An existing user
  `__startup.lua` is kept as `__startup.golem-user.lua` and run before golem's scripts. On Windows,
  on first setup without audio settings, it pre-selects the **native** ASIO driver of a known card,
  recognised by its USB identity (`KNOWN_USB_ASIO`); generic drivers (ASIO4ALL, FlexASIO,
  ReaRoute…) are never preferred — see the pitfall in [`CLAUDE.md`](../CLAUDE.md).
- `start` launches the bridge, then REAPER in the background, and opens
  `http://127.0.0.1:8770/app/`. Other commands: `server` (no window), `stop`, `restart`,
  `shortcuts`, `connect`, `autostart on|off|status`.
- The bridge log is `GoleM/logs/bridge.log` under REAPER's resource folder.
- If `sets/golem-set.rpp` is missing, the launcher opens an empty project rather than REAPER's last
  one.

**Environment variables (Windows/macOS).**

| Variable | Use |
|---|---|
| `REAPER_BIN` | Absolute path of the REAPER executable when it is not in its usual place |
| `GOLEM_FCB_PORT` / `GOLEM_MIDI_PORT` | A distinctive part of the native MIDI port name for the foot controller input / pedal output (never an ALSA `hw:` id). A USB foot controller can use `transport.port_match` in its descriptor instead ([`pedalboards.md`](pedalboards.md)). |
| `GOLEM_BIND` | `127.0.0.1` closes the bridge to the network (default `0.0.0.0`) |
| `GOLEM_ASIO_DRIVER` | Force an ASIO driver name (Windows) |
| `GOLEM_PORT` | Bridge port (default 8770) |

**Desktop audio settings.** **Settings ▸ Gear ▸ Soundcard ▸ Configure ASIO…** (Windows) chooses the driver,
input/output range, rate and buffer; the Dashboard changes the buffer up to 2048 samples. golem saves
the project (an untitled one goes to `sets/golem-set.rpp`, or a new `sets/golem-session-*.rpp`),
closes REAPER politely, writes `reaper.ini` after it exits (previous settings in
`reaper.ini.golem-audio.bak`) and restarts it, then reads back what the driver actually accepted.
Latencies shown are those **reported by REAPER** (or two buffers nominal when it reports none), not a
measured round trip. The xrun counter is a minimum: several events between two polls count as one.

**The sizes the ASIO driver accepts (Windows, CODED 2026-10-24).** Many ASIO drivers take REAPER's buffer size as a
suggestion and open their own (a Universal Audio Volt: 192 asked, 128 opened). The driver says what it accepts through
ASIO `getBufferSize(min, max, preferred, granularity)` — granularity −1 = powers of two between min and max, 0 = the
preferred size only, n > 0 = steps of n. `bridge/asio_probe.py` asks it **in a separate process and only while REAPER
is closed** (many drivers are single-client: opening one REAPER holds can cut the sound): once per driver, by the
launcher before it starts REAPER and by a buffer change while REAPER is down. The answer is kept in
`<runtime>/asio-buffers.json`; a size the driver replaced when REAPER opened is recorded there too (`refused`), so it
greys out even without a probe. The Dashboard and the Soundcard page grey out what the driver does not offer and add
the sizes it offers beyond golem's list (32 for the Volt: 8–2048, powers of two); a request for a refused size is
answered before REAPER is closed, with the sizes the driver offers. The reported input/output latency is larger than
the buffer (Volt at 128: 194 / 198 samples): converters and the driver's USB safety buffer, as the driver declares them.

## 3. Status per feature

✅ works and has been exercised · ⚠ coded, not proven on this OS · ❌ not available

| Feature | Linux | Windows | macOS |
|---|---|---|---|
| Installation | ✅ | ✅ (VM and real PC) | ⚠ never run on a Mac |
| REAPER launched and hidden | ✅ Xvfb | ✅ Win32 | ⚠ `open -j` + System Events; permissions never seen |
| Sound card | ✅ ALSA | ✅ ASIO, native driver preferred | ⚠ Core Audio, emulated in tests only |
| MIDI foot controller and keyboards | ✅ | ✅ (hot-plug → `midi_reinit`) | ⚠ no real device seen |
| NAM / IR core | ✅ (plugins compiled by the rack) | ✅ parity measured | ⚠ CI render only |
| sfizz · Vital · AVL Drumkits | ✅ | ✅ installed (sfizz, AVL, Vitalium); see §5 for the catalog | ⚠ installer untested; Vitalium needs Rosetta |
| guitarix / Calf blocks, Freeze, Prisma (Grit) | ✅ | ❌ (§5) | ❌ (§5) |
| Looper, backing, stem separation | ✅ | ⚠ not in a full test pass | ⚠ never run |
| NAM capture of a plugin ([`plugin-capture.md`](plugin-capture.md)) | ❌ by design (captures are made on members' computers) | ✅ | ⚠ |
| Network: station / access point | ✅ | ✅ (mobile hotspot) | ⚠ addresses only; changes refused (501) |
| Start at boot / login | ✅ systemd + linger | ✅ Startup folder | ⚠ LaunchAgent never loaded |
| REAPER update from the app | ✅ | ✅ (UAC prompt on the PC) | ❌ "not available on macOS yet" (`bridge/reaper_update.py`) |
| Plugin window ([`plugin-window.md`](plugin-window.md)) | ✅ filmed view | ✅ native window | ⚠ main REAPER window may reappear |
| CPU boost (Dashboard ⚡) | ✅ governor | ✅ "Performance" power plan | ❌ 501 (`perf_mode`) |
| VST Host block (any scanned VST/VST3/CLAP) | ⚠ coded, first-use bench test, window not tried on the rack (§6.1) | ✅ | ⚠ (AU-only plugins are not listed) |
| REAPER licence state (registered / evaluation) | file presence only | ✅ read from the window title | file presence only |

## 4. Known limits

- **REAPER licence path on Windows/macOS.** The licence entry writes to `~/.config/REAPER`
  whatever the OS ([`audio-engine-choice.md`](audio-engine-choice.md) §4); install the licence from
  REAPER itself on Windows and macOS.
- **REAPER's first start on Windows.** `setup` writes `verchk=0` so the "New Version Notification"
  modal does not block `__startup.lua`. The evaluation window of an unlicensed REAPER comes back at
  every start; it does not block golem.
- **Windows firewall.** REAPER opens its OSC port on all interfaces; the installer blocks inbound
  traffic to `reaper.exe` so nobody on the network can drive REAPER ([`network.md`](network.md) §4).
- **Windows not done:** golem update from the installer; ffmpeg (preview encoding) is not installed. The uninstaller
  is coded for Windows but not yet run on the Windows VM ([`uninstall.md`](uninstall.md)).
- **macOS needs permissions** that have never been seen in practice: Automation / System Events
  (hide REAPER, quit it politely), Accessibility (closing REAPER's audio-device dialog for capture
  benches), Microphone for REAPER, and Gatekeeper quarantine on downloaded plugins. The installer
  installs Rosetta before PawPaw (Vitalium), whose package declares x86-64 only; if Rosetta is
  refused, Vitalium is skipped and the installer says so. No signing or notarisation.
- **macOS plugin cache names** for AU/CLAP on Apple Silicon are assumed, not read; a wrong guess
  only means a re-scan per capture.
- **Rig health on macOS:** CPU and RAM come from `host_statistics` / `sysctl` (`bridge/desktop_macos.py`);
  temperature is absent and reported as such.

## 5. Blocks without a plugin per OS

Each desktop OS has a translation table: [`library/catalog/effects-windows.json`](../library/catalog/effects-windows.json)
and [`library/catalog/effects-macos.json`](../library/catalog/effects-macos.json), read by
`reaper/Scripts/golem_rig.lua` (`DESKTOP_TABLE`) and `bridge/blockstatus.py`. The table is
**complete**: every catalog block type is either in `effects` (mapped to an exact scanned plugin name,
or `unsupported` with a reason) or in `unmapped`. `unmapped` gives each remaining type a `family`
saying where its code comes from — `core` (NAM/IR core), `reaper-jsfx`, `golem-jsfx`,
`reaper-plugin` (shipped with REAPER), `no-plugin` (a service block), `installed-plugin`, or
`untested`. An entry under `effects` switches the block to strict desktop resolution; `unmapped` is
documentation that the code does not read. For an `unsupported` block, `blockstatus.candidates()` returns
no plugin name, so the block reports itself unavailable on this OS instead of loading the wrong DSP.

**Unsupported (no plugin) — Windows (3):** `detune` (guitarix absent, quarantined anyway), `pitch-correct`
(x42-autotune absent; ReaTune, shipped with REAPER, was measured on 2026-10-22 to expose **no** automatable parameter —
Bypass, Wet, Delta only, key / scale / correction live in its state — so no parameter mapping is possible; it was decided
not to build a pitch corrector: too much CPU), `freeze` (CLAP not built for desktop; dropped). On 2026-10-22 the
three wahs, every Calf block, `octaver`, `vibrato`, `eq-graphic`, `limiter` and `delay-echo` left this list (in-house
JSFX, below), and the three `surge-*` blocks got a real mapping onto the Surge XT Effects VST3 (§5.1).

**Unsupported (no plugin) — macOS (2):** `detune` (guitarix has no macOS build; quarantined); `freeze`. Surge XT is a
`manual` pin on macOS (signed dmg); the `surge-*` mapping is the same VST3, unverified on a Mac.

### 5.2 NAM 0.7.15 built by golem — A2 captures on Windows and macOS (CODED 2026-10-22, measured on Windows)

The official NeuralAmpModeler 0.7.14 / 0.7.15 read A2 captures (`architecture: SlimmableContainer`) but publish **no
binaries**; 0.7.13, the last release with binaries, lets an A2 capture pass the guitar through dry. Every component is
permissively licensed (plugin and core MIT, iPlug2 zlib-like, VST3 SDK MIT, Eigen MPL-2), so golem builds the
upstream tag **unchanged** on GitHub Actions (fork `Goldoralf/NeuralAmpModelerPlugin`, the project's own
`build-native.yml`) and publishes the result as a release of the **public** repository `Goldoralf/golem-binaries`
(`nam-0.7.15-golem` — a release of the private golem repository answers 404 to an installer that is not signed in to
GitHub, 2026-10-23), pinned by
sha256 in both `pins.json` (`nam_golem`). The official 0.7.13 installer stays the owner of the plugin (registry
entry, uninstall); the elevated step then replaces **only the official 0.7.13 DLL** (recognised by its sha256) and
writes a witness (`golem-nam-version.txt` in the bundle on Windows, `.golem-nam-version` next to it on macOS, where a
file inside would break the signature; the macOS bundle is ad-hoc signed). A NAM someone installed themselves is
left alone. `rig.nam_unreadable()` reads the witness: with 0.7.15 present the A2 refusal is lifted, on the machine and
in the heartbeat golem.fm reads. The 0.7.15 state keeps the same header (magic, version, model, IR) plus one
parameter, `Slim` (the size an A2 capture plays at, default 0 = smallest): golem_rig accepts the "0.7.15" state and
sets `Slim` = 1 (the whole capture, as the Linux rack plays it).

Measured on the Windows dev box (bench REAPER, the same `nam_state_with_files` path as the engine): the official
`A2.nam` example through 0.7.13 → output minus input RMS 0.010 for a 0.157 input (dry); through 0.7.15 → **0.242**
(transformed); an A1 WaveNet capture gives the same result on both (0.287). macOS: built, pinned and installed by
`install-system.sh`, **not verified on a Mac** (unsigned, unnotarized; ad-hoc signing in the script). Pitfall met on
the way: REAPER resolves a VST3 by its class ID, so two NAM builds cannot be compared side by side in one REAPER —
the bench measured 0.7.15 only once it replaced 0.7.13.

### 5.1 Surge XT Effects on desktop — measured 2026-10-22

The Windows VST3 (`Surge XT Effects.vst3`, 1.3.4, installed per user by `provision/surge.py` into
`%LOCALAPPDATA%\Programs\Common\VST3\GoleM`, GPL-3, pinned by sha256) exposes **17 parameter slots**: `FX Type`
is a **normalised** 0..1 parameter over 29 types (Delay, Reverb 1, Phaser, Rotary, Distortion, EQ, Frequency Shifter,
Conditioner, Chorus, Vocoder, Reverb 2, Flanger, Ring Modulator, Airwindows, Neuron, Graphic EQ, Resonator, CHOW,
Exciter, Ensemble, Combulator, Nimbus, Tape, Treemonster, Waveshaper, Mid-Side Tool, Spring Reverb, Bonsai, Audio
Input — index/28), and the other slots **change name with the type** (Spring Reverb: Reverb Size, Reverb Decay, Reverb
Reflections, Reverb HF Damping, Modulation Spin, Modulation Chaos, Modulation Knock, Output Mix). Two traps, both
measured in a bench REAPER: the names refresh only after the next audio block, and the plugin **re-initialises its
parameters** after a type change — values written in the same tick are wiped (Size 0.95 read back 0.50). Hence the OS
table carries `fx_init: {"FX Type": 26/28}` (golem_rig applies it instead of the static FX_INIT, whose raw 27 lands on
"Audio Input" here) and `late_params: true`: `apply_block_params` queues the block and `flush_late_params` re-applies
its parameters 0.35 s after the build, by name, once the plugin is settled. Bench: Size 0.95 → a reverb tail (RMS
0.007 at 1–3 s), Size 0.05 → none. The catalog's `Wet` (mix) is REAPER's own wet knob and needs no mapping. On macOS
`limiter`, `pitch-correct` and `eq-para` resolve to x42 LV2 plugins the user installs.

**Untested on both (`unmapped`, family `untested`):** `ep` (Dexed), `organ` (setBfree), `pads`
(ReaSamplOmatic5000); `piano` (sfizz) on macOS only. **`piano` plays on Windows (CODED 2026-10-22):** the table
maps it to `VST3i: sfizz (SFZTools)` — sfizz 1.2.3 is installed by `install-system.ps1 -Sfizz`, and golem_rig loads
the `.sfz` through sfizz's VST3 state (`sfizz_vst3_set_file`, measured at render on 2026-10-11, see
[`drums-kit.md`](drums-kit.md) §8). The Windows installer now offers the piano pack (Salamander Grand v3, 450 MB,
`installer/desktop_steps._sound_piano`, same URL and pinned checksum as Linux). macOS keeps `untested` with a
reason that says so: the same VST3 path is coded, no Mac has played it. **Measured on the live Windows rig
(2026-10-22 15:17):** `factory-chill-jazz` rebuilt with the pack present — golem_rig logs `(sfizz VST3) vst_chunk sfzFile ->
true (état v5, fichier SalamanderGrandPiano-V3+20200602.sfz)` — then a five-note chord sent by the `midinote` dev
command (golem_apply: the lane's input is switched to REAPER's virtual keyboard for the note and put back) peaks at
**−32 dB** on the Keys track, against −154 dB at rest. Note for a bench: a separate REAPER (`plugin_capture.bench_run`)
could NOT instantiate sfizz that day while the live REAPER did — the bench is not the proof for shell VST3 plugins.

**Played by an in-house JSFX (CODED 2026-10-22):** a Linux block whose plugin has no desktop build is cloned
as a golem JSFX that keeps the Linux plugin's parameter **names, ranges and meaning**, so a preset made on Linux
plays unchanged: the OS table only names the file (`"plugin": "JS:golem/<file>"`), golem_rig resolves each knob by
slider name and writes it raw. The JSFX also keeps the plugin's **native defaults**: the rig writes only the
parameters a preset names, so an unnamed one plays the plugin default on both sides.

| Block | Linux plugin | Desktop JSFX | Where |
|---|---|---|---|
| `delay-tape` | Calf Vintage Delay | `golem_tapedelay.jsfx` — Calf's ping-pong loop, tick length, Medium filters and defaults, read from Calf's source; adds a 20 ms crossfade when the time changes (Calf jumps) | Windows, macOS |
| `reverb-shimmer` | GxShimmizita (guitarix) | `golem_shimmer.jsfx` — its parameter names, ranges and native defaults; the same public idea (8-line FDN reverb, a pitch shifter in every feedback line), our own code: close, not identical — check levels by ear | Windows, macOS |
| `grit` | Prisma (UnplugRed, AGPL) | `golem_grit.jsfx` — Prisma's parameter interface (names, the 23 modules, 4 bands × 2, log crossovers, band and Gain-module level laws); every module's DSP is ours, written from its name (no AGPL code): same family of sound, not identical | Windows, macOS |
| `eq-para` | x42-eq (fil4) Mono | `golem_eq.jsfx` — fil4's ranges and defaults; its bells and shelves as equivalent RBJ biquads (bells checked identical to fil4's section to 0.001 dB); the high-pass slope matches, not its exact knee | Windows (macOS resolves the x42 LV2 the user installs) |
| `wah` | Gxgcb_95 (guitarix, Cry Baby GCB-95) | `golem_wah.jsfx` — `Wah` and `Volume` (the slider spans −20..+20 dB to stay symmetric, the catalog writes −20..+4); the GCB-95's 4th-order filter was **evaluated at 48 kHz for seven pedal positions** (peak frequency 408 → 1736 Hz, Q 3–8.5, peak +19 dB, −3 dB below the peak, dc-blocker 228 Hz) and those facts drive a TPT state-variable filter (resonant lowpass + bandpass); same log, inverted pot law. Bench 2026-10-22: noise through the JSFX peaks at 401 / 1198 / 1796 Hz for Wah = 0 / 0.5 / 1 against 408 / 1222 / 1736 expected (±3 %) | Windows, macOS |
| `wah-color` | GxWahwah (guitarix colwah: Colorsound, Dallas, Foxx, Jen, Maestro, Selmer, Vox V847) | `golem_colwah.jsfx` — `MODEL`, `WAH`, `FREQ` (alien LFO in BPM), `WET_DRY` (native default 50), `MODE` (manual / auto / alien); each model's filter evaluated the same way (its own dc-blocker, pot law, auto-mode bounds and inversion read in the Faust sources). Bench: Vox manual WAH 0.5 → 932 Hz (947 expected), Foxx WAH 0.9 → 444 Hz (450). Maestro keeps guitarix's +43 dB resonance | Windows, macOS |
| `autowah` | GxAutoWah (guitarix dunwahauto) | `golem_autowah.jsfx` — the envelope follower of dunwahauto (instant attack, `exp(-10/fs)` release) pushes the GCB-95 filter; `Wah` = sensitivity (position = level × 20 × Wah, bounded), as the catalog promises — **the Linux plugin has no parameter at all** (its `Wah` port belongs to the manual GxWah of the same bundle), so on Linux this knob was a silent no-op | Windows, macOS |
| `chorus` | Calf Multi Chorus | `golem_chorus.jsfx` — Calf's 12 parameters with native defaults (`Dry Amount` 0.5, raised to 1.0 by golem_rig's FX_INIT as on Linux); N voices on one delay line (`Min Delay + Mod Depth × (1 + lfo) / 2`), voice phase spread and Overlap slicing as in Calf's sine_multi_lfo, Stereo Phase on the right channel, sum × 1/√N through two summed RBJ band-passes (Center Frq 1 / 2, Q). Bench 2026-10-22: one voice, Mod Depth 0.1 ms, rate 0.01 Hz → autocorrelation peak at 245 samples (244 expected: Min Delay + Mod Depth / 2 + 2) | Windows, macOS |
| `tremolo` | Calf Pulsator | `golem_tremolo.jsfx` — Timing (Hz by default, as Calf's `PERIODICAL_DEFINITIONS(2)`), BPM / ms / Frequency / Host BPM, Mode (Sine, Triangle, Square — Calf's two saws are not in the catalog), Modulation, Offset L / R (native 0 / 0.5: the right channel is a half-cycle off, as on Linux), Pulse Width; Calf's level law `in × (lfo/2 + mod/2) + in × (1 − mod)`. Bench: the envelope of noise modulates at the set Frequency | Windows, macOS |
| `phaser` | Calf Phaser | `golem_phaser.jsfx` — Center Freq, Mod depth in **cents** (the catalog said "Hz" — a wrong label, on Linux too; corrected to cents), Mod rate, Feedback (−0.99..0.99, symmetric), # Stages 1..12, Stereo phase, Amount, Dry Amount; first-order all-passes in cascade with the state feedback, triangle LFO, coefficients every 32 samples as Calf. Bench: 6 stages, Center 1 kHz, no modulation → notches 34–42 dB deep at 134 / 500 / 1866 Hz — where Calf's all-pass (−90° at **half** the Center Freq, `x = tan(π fc / 2 sr)`) predicts them | Windows, macOS |
| `octaver` | Gxoc_2 (guitarix, Boss OC-2) | `golem_octaver.jsfx` — `DIRECT`, `OCTAVE1`, `OCTAVE2`; the pedal's architecture (input low-pass, flip-flop divider on zero crossings, the divided square switches the filtered signal, one low-pass per octave); guitarix's three filters evaluated in `oc_2.lib` (−3 dB at 830 / 470 / 210 Hz, 3rd order), pre-gain 1 + 10/2.7 on the direct path too. Bench 2026-10-22: a 220 Hz sine gives a dominant 110.2 Hz on OCTAVE1 and 55.1 Hz on OCTAVE2 — the second flip-flop is clocked on the first octave's own zero crossings (clocked on the input, 3f/4 dominated) | Windows, macOS |
| `flanger` | Calf Flanger | `golem_flanger.jsfx` — Min delay, Mod depth, Mod rate, Feedback (−0.99..0.99, symmetric), Stereo phase, Amount, Dry Amount; one modulated tap with the feedback written into the line as Calf does. Bench: autocorrelation peak at 29 samples for 28 expected (Min delay 0.5 ms + depth/2 + 2) | Windows, macOS |
| `rotary` | Calf Rotary Speaker | `golem_rotary.jsfx` — Speed Mode 0..5 (Off / Chorale / Tremolo / Hold / ModWheel / Manual), Tap Spacing, Tap Offset, FM Depth, Treble Motor, Bass Motor, Mic Distance, Reflection, AM Depth, Input / Output Gain (Calf's default output is ×2); Calf's structure — mono `atan` into a delay line, treble rotor = three Doppler taps + reflections, damper, AM, 2 kHz band-pass; bass rotor = one tap, AM, 800 Hz low-pass; quadrature per channel, Mic Distance mixes the mics; speeds 48→400 / 40→342 rpm with Calf's ramps (rotors start fast and ramp, as Calf). Bench: at 400 / 342 rpm the envelope of noise beats at 6.67 Hz (treble AM) and a 200 Hz sine carries ±5.6–6.0 Hz Doppler sidebands from the bass rotor (5.7 expected; without FM the bass rotor does not modulate the amplitude, in Calf either) | Windows, macOS |
| `limiter` | x42-dpl (Digital Peak Limiter) | `golem_limiter.jsfx` — Input Gain, Threshold (slider −30..+30 to stay symmetric; the catalog writes −30..0), Release Time; a 64-sample look-ahead (declared as PDC) with instant attack and exponential release, plus a hard ceiling. Windows only: macOS resolves the x42 LV2 the user installs. Bench 2026-10-22: a 0 dBFS sine with Threshold −12 dB comes out at −12.0 dBFS, never above; the gain ramps down over the look-ahead (65-sample window), no step | Windows |
| `vibrato` | GxTubeVibrato (guitarix) | `golem_vibrato.jsfx` — SineWave, Depth, Speed (**Hz**, 0.1–14, default 3 — the catalog said 0..1 and is corrected), Drive, Output; gxtubevibrato.dsp's delay curve `(5 + 5·lfo) ms × Depth` between two soft tube stages, one band instead of four. Bench 2026-10-22: a 200 Hz sine at Speed 5 Hz, Depth 1, triangle LFO alternates between 190 and 210 Hz — exactly f0 × (1 ± Depth × 5 ms × 2 × Speed); the tube stage is unity at small signal (the first draft added +19 dB) | Windows, macOS |
| `eq-graphic` | GxGraphicEQ (guitarix) | `golem_geq.jsfx` — G1..G11 (slider −30..+30, native −30..+20, catalog ±12) on guitarix's eleven octave bands (filterbank edges 44…18110 Hz): an RBJ one-octave bell per band in cascade, shelves at both ends. Bench 2026-10-22: G6 +12 dB lifts 1 kHz by 12.7 dB against 250 Hz. The review caught a double memory offset that made the left-channel states of G1–G3 overwrite the gain memory (a thump on every parameter write) — fixed before shipping | Windows, macOS |
| `delay-echo` | GxEchoCat (guitarix) — **quarantined on Linux** (freezes the engine ~520 ms) | `golem_echocat.jsfx` — BPM, Sustain, Swell, Input, Head 1/2/3; the Copicat architecture (three heads at 30/60/90 ÷ BPM s, feedback loop 150 Hz–7.5 kHz, tape 40 Hz–6.5 kHz, 4 Hz wow, soft tube stages). The quarantine is a fact about a **plugin**: `rig.quarantined_types()` drops a type whose OS table plays it with a `JS:golem/` file, and `/api/effects` moves its `quarantine` to `quarantine_linux` so the drawer offers it. Bench 2026-10-22: a 50 ms burst at 120 BPM echoes at 0.25–0.30 s (head 1) and 0.75–0.80 s (head 3); engine-stall bench: see commit | Windows, macOS |

The rule (PROPOSED for the remaining blocks): clone a Linux-only block as a JSFX when its parameters can be
reproduced honestly in EEL2 — the factory then plays everywhere without forking a preset per OS. The candidates by
factory weight were `reverb-shimmer` (9 factory objects) and `grit` (7), both done; next are wah, autowah,
octaver, chorus, phaser, tremolo, rotary, spring (2–4 each). `tests/test_portable_jsfx_blocks.py` keeps catalog, tables and JSFX
in agreement and runs a Windows recall through the real engine. The engine-stall bench
(`tools/check-block-stall.py`) is run on every clone before it ships: measured 2026-10-22 on the Windows dev box
(REAPER 7.27, live rig, 8 switch-ons each), the four clones never stalled the engine (≤ 3 ms, witness 2 ms).
**Corrected the same evening:** `golem_shimmer` and `golem_tapedelay` carried an exponent literal (`1e-15`) that EEL2
does not parse — both had been passing audio **dry** since they shipped (`docs/pitfalls/jsfx.md`). Fixed, and now
measured by render: a burst through the shimmer at DRYWET = 1 leaves a tail (RMS 0.0023 at 1–1.8 s), through the
tape delay too (0.0071). The wah family bench below was written against that trap.

**Installed for these mappings (2026-10-22):** until then nothing installed the Dragonfly reverbs or Proteus on
Windows although the table named them — on the dev box 45 of the 47 factory objects lacked a reverb. The Windows setup
now installs Dragonfly Hall, Plate and Room (VST3, per user, `provision/dragonfly.py`), the installer's elevated step
installs Proteus (`install-system.ps1 -Proteus`). On macOS the elevated step installs both since 2026-11-04 (`install-system.sh --dragonfly --proteus`, pinned in
`provision/macos/pins.json`): the first real Mac test found the reverb silent on ~45 factory presets without them.

**Mapped on both:** `boost` (Proteus), the NAM-based `pedal-nam`, `preamp-nam`, `comp-nam`, the
Dragonfly reverbs, `granular` (ZamGrains), `pitch-spectral`, `spectral-comp`, `stretch`, the MDA
`ringmod`, `bitcrusher`, `rezfilter`, and `delay-tape-aw` (Airwindows TapeDelay2).

## 6. The VST Host block

On desktop systems a lane can host any plugin **this REAPER** has scanned. In the Designer, open the
lane's add drawer, then **VST Host** (`app/designer-vst-host.js`; routes `/api/vst-host/*` in
`bridge/routes_content.py`, refused on Linux). The picker lists every VST, VST3 and CLAP plugin
REAPER knows, including user-configured paths (`vst_list` command), with filters for
instrument/effect (from REAPER's `VSTi`/`VST3i`/`CLAPi` prefix), format and vendor (guessed from the
name, may be missing). AU-only plugins are not listed. Several VST Host blocks can share a chain.

- **Parameters.** Opening the block lists the parameters its REAPER instance exposes; search by name
  or index, **Saved only** limits to stored ones. `MIDI CC` parameters are hidden and excluded from
  **Capture all**. The first change stores the current value as the block's base and writes the new
  value to the active scene. **Capture all** stores every exposed value in the base (a plugin with
  thousands of parameters makes the preset grow accordingly). Scene switches re-apply values at
  runtime without re-instantiating the plugin.
- **Native state.** **Open plugin window** opens the original UI in a floating REAPER window
  ([`plugin-window.md`](plugin-window.md)). Back in the Designer, golem captures the instance's
  native VST/CLAP state (including a preset loaded in its window) and stores it with the block;
  recalling a patch re-applies that state before the scene knobs. **Capture all** forces the capture.
  Surge XT is excluded from native capture: reading its large state crashes REAPER.
- **Missing plugin.** If the plugin is uninstalled, the block stays in the preset, REAPER cannot
  instantiate it, and `presets/.golem-rig.log` names the missing plugin.

### 6.1 On Linux

> **Status: CODED (2026-11-09), not yet tried on the rack with a real plugin window** — validated by the maintainer the
> same day. The block was refused on Linux in five places (`get_effects`, `/api/vst-host/plugins`, `/api/vst-host/open`,
> `blockstatus`, `golem_rig.lua` `DESKTOP_FX`). No technical reason was written down; the remembered one is "fewer
> proprietary plugins on Linux". The rack itself scans hundreds (VST3/CLAP: Surge XT, Vital, Dexed, LSP, ZAM,
> Dragonfly, BYOD…), so the block opens on Linux, in three lots.

1. **Open the block.** The refusals are lifted (`/api/vst-host/open`, the native-window path, stays Windows/macOS).
   The picker lists the VST, VST3 and CLAP plugins REAPER scanned, from REAPER's own scan paths (LV2 stays out — a
   later step). The list is for **new** plugins (decided the same day): golem's own plugins (vendor "golem": Freeze, the
   capture plugin) are never listed, and a plugin the catalogue already plays as a block (`effects.json` and the
   desktop tables, matched by bare name — `routes_content._catalog_plugin_blocks`) is marked `block` by
   `/api/vst-host/plugins` and shown folded at the bottom ("N plugins golem already uses"): a tap adds the **golem
   block** (its settings, its presets), the small **VST** chip still adds the plugin itself (Surge XT Effects holds
   more than the spring reverb golem uses). This applies on every OS. The **versions of one tool** are one row (`app/vst-host-model.mjs` `variantOf`): LSP
   publishes a plugin per channel layout and band count ("Compressor Mono / Stereo / LeftRight / MidSide",
   "Parametric Equalizer x16 Stereo") — 176 rows for 54 tools on the rack. A tap adds the Mono or Stereo version as the
   lane is mono or stereo, the smallest band count; "+N" unfolds the others (L/R, M/S, x32…). "Sidechain …" stays a
   tool of its own. **Open plugin window** uses the **filmed view** of [`plugin-window.md`](plugin-window.md) — the
   `plugin_window` action already targets any `golem:<id>` FX; `app/page-designer.js` `openPluginWindow(id, '', 'vst')`.
   When the window closes with a changed state, the page captures the native state (`/api/vst-host/state`,
   `applyHostState`) into the patch — the same capture as on Windows/macOS — even if the drawer was closed meanwhile.
   Reading the state of **Surge XT** is skipped in `plugin_window` too (the `vst_state` guard: its large chunk crashes
   REAPER): its window opens, its edits are not captured. The NAM capture of a plugin stays Windows/macOS
   (`vst_capture: false` in `/api/effects`): its card is shown greyed with that reason.
2. **Knobs.** A row of up to 8 knobs the musician picks from the plugin's parameters (`/api/vst-host/params`), on one
   row (1024×600). They live on the block (`block.knobs = [{i, name}]`, so a shared patch carries them); a value is the
   normalized `p<i>` of `block.params` or of the scene (the existing `setHostParam` path), shown in %. The choice is
   also remembered **per plugin** in `config/vst-knobs.json` (local state; `GET/POST /api/vst-host/knobs`) and given to
   the next block of the same plugin. A knob takes the expression pedal (`exp2 = {block, param: "p<i>", min: 0, max: 1}`):
   `golem_rig.lua` publishes the knobs in `.livemap.json` (`p<i>`, range 0–1) and /live names the knob, not `p12`.
3. **Bench test on first use** (`bridge/plugin_trial.py`). A plugin never tried on this rack is kept out of the rig
   (`rig._drop_quarantined`, said in the log) and loaded in a separate REAPER: its own `-cfgfile` folder, dummy audio
   (`linux_audio_mode=2`), the rack's virtual screen (never the user's), the machine's licence and plugin caches. The
   track is armed like a rig track (`I_RECMODE = 2`) — otherwise REAPER renders its FX ahead and a stall goes unseen.
   A JSFX meter placed before the plugin records the longest gap between two audio blocks while the plugin is switched
   on and off four times. Verdicts, kept per plugin in `config/vst-trials.json` (local state): REAPER crashed, froze
   (15 s without a sign of life), or the audio stopped longer than **50 ms** → refused (`quarantine`, the measured
   reason in `detail`); otherwise the draft is re-applied (`recall.reapply_sandbox`) and the block plays. A plugin
   that does not load (uninstalled, stale name) gets no verdict. Meanwhile `blockstatus` says `reason: "trial"` and
   the Designer re-reads it every 2 s. `GOLEM_VST_TRIAL=0` turns the bench off (the test suite does).
   **Calibrated on REAPER 7.82 (2026-11-09):** background 12 ms (ReaEQ, ZamComp, Surge XT, ~8 s per plugin); a JSFX
   that blocks its audio thread 67 / 83 ms is read 67 / 83 ms. **Not proven:** ReaPitch, measured freezing the live
   engine 435 ms in September, read 12 ms on this bench — its freeze needs conditions the bench does not reproduce
   (real input, its settings). The bench catches crashes, freezes and stalls in a plugin's processing; the catalogue
   quarantine stays the answer for what only the live rig shows.

### 6.2 Installing a plugin, and letting REAPER see it

> **Status: CODED (2026-11-09)**, all three OSes; the restart is not tried on Windows/macOS from this button.

golem keeps **no list of plugin folders of its own**: only REAPER's counts — the block can only add what REAPER can
load, and the picker already reads REAPER's inventory (`EnumInstalledFX`), user-added paths included. A second list
could only drift. What the drawer adds:

- **Where to install plugins** (`GET /api/vst-host/folders`, not readable from the LAN: absolute paths) shows the folders
  REAPER scans here: those of `reaper.ini` when set (`vstpath*` for VST/VST3, `clap_path_*` for CLAP — key names read in
  the REAPER 7.82 binary), otherwise its defaults for the OS (Linux: `~/.vst3`, `~/.clap`, `~/.vst` and their
  `/usr/lib`, `/usr/local/lib` twins; Windows: `Common Files\VST3` / `\CLAP`; macOS: `…/Audio/Plug-Ins/VST3|CLAP|VST`).
  The folder one can write to without a password is highlighted.
- **Rescan plugins** (`POST /api/vst-host/rescan`, admin like `reaper-restart`): REAPER only scans at start, so the
  button restarts it (`routes_system.reaper_restart`), waits until it is back and linked for 3 s, then re-applies the
  draft (a restarted REAPER reopens an empty project). Two taps, the first one says the sound stops; refused during
  a take, a song, a load or in Gig mode (`reamp.busy_reason`). The drawer re-reads the inventory when REAPER answers.

## 7. What proves a platform

- **Tests that only set `sys.platform`** (`monkeypatch.setattr(sys, "platform", "darwin")` and the
  like — about 77 places in `tests/`, e.g. `test_macos_*.py`, `test_desktop_*.py`,
  `test_installer_*.py`) prove the **parsing and branching** of simulated outputs. They do **not**
  prove the platform: no real Core Audio, ASIO, CoreMIDI, permission prompt or REAPER behaviour is
  exercised. A green suite on Linux says nothing about whether golem runs on a Mac.
- **`.github/workflows/desktop-tests.yml`** (manual trigger only, `workflow_dispatch`) runs the full
  test suite on Ubuntu 24.04, Windows Server 2025 and macOS 26, provisions desktop resources, smoke-tests
  a local bridge (`tools/check-desktop-bridge.py`, which fails on any Linux-only value), and renders a
  DI offline through REAPER + NAM VST3 on Windows and macOS (`tools/check-native-nam.py`: NAM alone,
  IR alone, NAM + IR, checked to really change the signal after save and reload). It measures no
  latency or dropouts on a physical interface.
- **`.github/workflows/ci.yml`** runs on every push and pull request (Linux).
- What only real hardware proves: sound-card behaviour, MIDI devices, permission prompts, firewall
  prompts, latency and xruns. Report platform results with the machine, OS version, interface and
  driver.
