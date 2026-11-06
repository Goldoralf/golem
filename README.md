# golem

> An open-source stage rack that boots on its own touch screen and is played with your feet.
> Guitar · bass · voice · keys · drums → NAM amp sims, IRs, effects → front of house.
> The audio engine is **REAPER, running headless**; everything else is in this repository.

> **Status: an advanced prototype (v0.6).** Its authors use it on stage and in rehearsal, on Linux. Windows
> and macOS are **experimental**. golem ships **no amp captures**: without a free TONE3000 account the amp and pedal
> blocks stay silent (the app says so and downloads the factory captures once you connect). Expect rough edges, and
> please tell us about them ([reporting a bug](#reporting-a-bug)).

golem is **a stage machine, not a workstation**. It boots into its app on a 1024×600 touch screen
(or on a tablet), everything a set needs is preloaded, and nothing loads while you play: a scene
change switches state, it does not rebuild the rig ([`docs/live-engine.md`](docs/live-engine.md)).
The repository versions **recipes and seeds** — presets, setlists, catalogues, scripts, provisioning —
so a new rack is rebuilt from it; the sounds themselves (captures, IRs, samples) are downloaded.

## What it does

- **The rig.** A preset is a set of lanes (one per instrument input), each a chain of blocks: NAM
  amp and pedal captures, IR cabinets, in-house JSFX and open-source plugins, splits and several
  outputs. Scenes (A…H) switch blocks, knobs and lanes without a gap
  ([`docs/preset-format.md`](docs/preset-format.md), [`docs/blocks-doctrine.md`](docs/blocks-doctrine.md)).
- **The foot.** A MIDI foot controller (Behringer FCB1010 with the UnO2 chip, or another pedalboard
  described in data) selects presets, scenes and stomps; expression pedals drive any knob
  ([`docs/pedalboards.md`](docs/pedalboards.md)). MIDI pedals come from a catalogue
  ([`docs/pedal-registry.md`](docs/pedal-registry.md)).
- **Songs and setlists.** Songs, patches (one musician's sound), presets, banks and setlists; a list
  is played from the foot ([`docs/songs.md`](docs/songs.md), [`docs/setlists.md`](docs/setlists.md)).
- **Keys and drums.** Vital, SFZ instruments, pad kits, an electronic drum kit as a lane, grooves,
  chord-chart rhythm sections ("Standards"), click, looper, backing tracks
  ([`docs/drums-kit.md`](docs/drums-kit.md), [`docs/standards.md`](docs/standards.md),
  [`docs/looper.md`](docs/looper.md), [`docs/samples-backings.md`](docs/samples-backings.md)).
- **Machine modes.** Pedalboard · Home · Jam · Rehearsal · Gig (`config/modes/*.json`): what is
  mounted and what can be touched in each situation ([`docs/modes.md`](docs/modes.md)).
- **The screens.** The app has five hubs — **Live · Designer · Songs · Library · Settings** — and
  never scrolls ([`docs/ui-architecture.md`](docs/ui-architecture.md)). Each musician's phone runs the
  **Companion** (`/app/m.html`, tabs Now · Song · Mine · Lyrics · Beat · Rec), which shows that
  person's lines ([`docs/devices-people.md`](docs/devices-people.md)).
- **Recording.** One global Rec block records takes (with the DI), which can be reamped later
  ([`docs/reamp.md`](docs/reamp.md)).

Nothing about the hardware is hard-coded: the sound card is discovered and adopted, inputs are
patched by role, pedals come from descriptors ([`docs/gear-registry.md`](docs/gear-registry.md),
[`docs/input-map.md`](docs/input-map.md)). The reference rack is a 2U x86 machine
([`docs/rack-hardware.md`](docs/rack-hardware.md)); a laptop with a USB sound card works too.

## Install

The normal path on every OS is the graphical installer ([`docs/installer.md`](docs/installer.md)).

**Linux** (x86-64) — tested on Ubuntu 24.04 and 26.04, Debian 13 and Linux Mint 22; other apt-based
distributions install with a warning, Fedora, Arch and openSUSE are not supported yet. One line, no sudo needed to start it:

```sh
curl -fsSL https://raw.githubusercontent.com/Goldoralf/golem/main/provision/bootstrap.sh | bash
# or, from a clone (installs in place):
./install-linux.sh
```

Both open the graphical installer, which asks for your password when it needs it (do not start
them with `sudo`), runs `provision/install.sh`, and sets up the `golem` command and the desktop
icons. The one-liner fetches the latest release first. The first install ends with a restart of the
computer: the real-time audio rights only apply after it, and without them the audio will crackle
(logging out is not enough — golem, started during the install, would keep running without them).

For developers, the same steps by hand from a clone, without the screens (both replayable safely):

```sh
./provision/install.sh              # system packages, real-time limits, REAPER, plugins, bridge, sounds
# ./provision/install.sh --light    # the same without the large sound downloads (development machine)
./provision/install-desktop.sh      # the `golem` command and the desktop icons
```

**Windows 10/11** (experimental) — in PowerShell,
`irm https://raw.githubusercontent.com/Goldoralf/golem/main/provision/bootstrap.ps1 | iex`, or double-click
`install-windows.cmd` in a clone.

**macOS (Apple Silicon)** — double-click `install-macos.command` in a clone. The macOS support had
its **first real test** on a MacBook Air (Apple silicon, 2026-11-04), without an external audio interface:
it remains **experimental**.

Per-OS details, manual install and requirements: [`docs/platforms.md`](docs/platforms.md).

## First steps

```sh
golem desktop      # start golem and open its window (1024×600, the rack's format); `golem` alone does the same
golem server       # start golem without a window; prints the address and a pairing code for a tablet
golem status       # bridge / REAPER / OSC link
golem stop
```

On Windows and macOS the same commands are `python -m provision.desktop start|server|stop|restart`
and the shortcuts the installer creates. The two uses share one installation, and you switch from
one to the other without stopping the sound ([`docs/installer.md`](docs/installer.md) §4).

1. **A tablet as the screen** (optional): `golem pair` gives a six-digit code; enter it on
   `http://<rack>:8770/app/pair.html` ([`SECURITY.md`](SECURITY.md), [`docs/network.md`](docs/network.md)).
2. **The sound card**: **Settings ▸ Gear ▸ Soundcard** detects it and offers to adopt it; patch each input
   to a role (guitar, bass, voice, keys…).
3. **Controllers**: **Settings ▸ Gear** — pedalboard, MIDI pedals, keyboards and pads, drums
   ([`docs/calibration.md`](docs/calibration.md)).
4. **Play**: pick a factory song or preset in **Songs**, shape it in **Designer**, play it from
   **Live** ([`docs/factory.md`](docs/factory.md)).
5. **Amp sound**: **Settings ▸ Connect ▸ TONE3000** — create a free account and a key on tone3000.com, sign in,
   then **Settings ▸ Content ▸ Factory ▸ Download** fetches the captures the factory sounds use. golem never ships
   them: they belong to their creators.

## Platforms

Linux is the reference platform. Windows is coded and tested on virtual machines and real hardware;
a few blocks have no plugin there (guitarix, Calf, Freeze, Grit). macOS is coded, covered by
tests and has had one first real test on a Mac without an audio interface. The feature-by-feature table is in
[`docs/platforms.md`](docs/platforms.md) §3.

## golem.fm (optional)

golem.fm is a separate, closed-source web service, **not open yet**. **The rack works without it**, and an
unpaired rack sends nothing. When it opens, pairing (**Settings ▸ Connect**) will add: a sound library and capture
downloads, sharing of presets, patches, kits, grooves, samples and backing tracks, song sheets and
stems, backups to a vault, the band roster, and remote jobs the rack pulls. It is cache-first:
everything the rack plays is on its disk, so a lost connection never stops a song. The rack is
always the client; golem.fm never connects to it.

- What the rack sends and expects: [`docs/golemfm-protocol.md`](docs/golemfm-protocol.md)
- Everything that leaves a rack on its own, and how to check it: [`docs/telemetry.md`](docs/telemetry.md)

## Repository layout

| Path | What it holds |
|---|---|
| `bridge/` | The brain: Python FastAPI on port 8770, OSC to REAPER, rig state, every API the app calls |
| `app/` | The app (Preact + htm, **no build step**); `main.js` routes, one `page-*.js` per screen; `m.html` is the Companion |
| `reaper/` | REAPER scripts (`Scripts/golem_*.lua`), in-house JSFX (`Effects/`), FX chains |
| `library/` | Catalogues (blocks, sounds, pedals), factory content in `library/factory/` |
| `config/` | Modes, sound-card and controller descriptors, pedalboards, engines |
| `provision/` | Install, start, harden, update |
| `plugins/` | In-house plugins (Rust) |
| `tools/` | Checks and probes (`check-*`), offline builders |
| `tests/` | The Python test suite |
| `docs/` | References and contracts — start at [`docs/README.md`](docs/README.md) |

## Documentation

- [`docs/README.md`](docs/README.md) — the map of every document.
- [`docs/architecture.md`](docs/architecture.md) and [`docs/glossary.md`](docs/glossary.md) — how the
  code fits together, and its vocabulary.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — when the sound disappears.
- [`CLAUDE.md`](CLAUDE.md) — the briefing for AI coding agents working in this repository.

## Reporting a bug

Open an [issue](https://github.com/Goldoralf/golem/issues/new/choose) with:

- the output of **`golem doctor`** (`python tools/doctor.py` on Windows and macOS) — it works even when the bridge
  is down;
- your OS, your audio interface and the buffer size (**Settings ▸ Gear ▸ Sound**);
- what you did, what you expected, what happened.

Questions, ideas and "show your rig" go to [Discussions](https://github.com/Goldoralf/golem/discussions). golem
does not phone home: an issue is the only way we learn that something broke on your machine.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md): development setup, the checks CI runs, conventions, and
the Developer Certificate of Origin (`git commit -s`, no CLA). Security problems: please report
them privately, as described in [`SECURITY.md`](SECURITY.md).

## Licence

golem is free software: **GPL-3.0-or-later** ([`LICENSE`](LICENSE)). It comes with no warranty.

Deliberate exceptions, detailed in [`docs/licence.md`](docs/licence.md):

- the **in-house JSFX** (`reaper/Effects/`) and the **interchange formats** (preset format, `.gsx`
  chord grids, and their examples in `docs/examples/`) are **MIT** ([`LICENSE.MIT`](LICENSE.MIT)),
  so an effect or a format can travel on its own;
- `reaper/Effects/golem_super8` is a fork of a Cockos JSFX and stays under the **LGPL**;
- `tools/fcb/fcb1010.py` is third-party code under MIT.

The repository contains no NAM capture, IR or sample from third parties: they are referenced and
downloaded. REAPER and the plugins keep their own licences; **Settings ▸ About** lists them.
Amplifier, pedal and instrument names (Fender, Marshall, Mesa/Boogie, Boss, DigiTech, Vox…) are trademarks of
their respective owners and are used only to describe the sound a block aims at. golem is not affiliated with or
endorsed by them.
Because contributors keep their rights (DCO, no CLA), golem cannot be relicensed without every
contributor's agreement.
