# Rack classes — what a machine declares about what it can play

> **Status: PARTLY CODED** — the machine card sent in the heartbeat is coded; the measured
> capacity, the `class` label, `blocks_missing` and ARM provisioning are **PROPOSED** (not built).

Related: [`rack-hardware.md`](rack-hardware.md) (the reference x86 rack),
[`platforms.md`](platforms.md) (Linux, Windows, macOS), [`installer.md`](installer.md),
[`diagnostics.md`](diagnostics.md), [`golemfm-protocol.md`](golemfm-protocol.md) (heartbeat).

## 1. The problem

Machines are not equal: a recent x86 rack plays several NAM lanes and IRs at a few milliseconds of
latency without an xrun; a small ARM board will not. If a rack never says what it can play, golem.fm
can send it a capture or a patch it cannot run, and the musician discovers it while playing.

**Rule: a class is measured, never deduced from a CPU name.** A rack that has not measured declares
no capacity, and "unknown" must be treated as unknown, never as "it fits".

## 2. What is coded

**Machine card.** `bridge/serial.py` `machine()` returns
`{arch, cpu, cores, ram_mb, disk_gb, hostname, board}` from free probes (`platform.machine()`,
`/proc/cpuinfo`, `/proc/meminfo`, disk usage, DMI board name on x86 or `/proc/device-tree/model`
on ARM; on Windows the registry via `_machine_windows()`). A missing probe leaves its field `null`.
`bridge/rigstatus.py` adds it as `machine` to every status push, next to `rack_id`. Diagnostic
bundles carry `arch` and `cpu_count` (`bridge/diag.py`).

**Capacity benchmark.** `tools/bench-lanes.py` measures how many NAM lanes this machine holds
(`--lanes N`, `--extremes` for the lightest and heaviest capture in the library). It cleans the
transport, any running take and loaded drum kits before measuring, and reports CPU and **xruns**,
which are what decides. It prints its result; it does **not** write a file or feed the heartbeat.

Two facts it relies on:

- The cost of a NAM instance depends on the **capture**, not on "NAM": the library ranges from
  61 KB to 2.25 MB across four architectures, about 5× in cost between lightest and heaviest.
- An `amp` block instantiates **two** plugins (NAM + IR convolver); the cost reported is the pair.

**Architecture.** Provisioning is x86-64 only: `provision/bootstrap.sh` stops on any other
`uname -m`, because the installer downloads x86-64 assets and packages.

## 3. Proposed: what a rack would declare

Added to the heartbeat, next to `machine` and `catalog_version`:

```json
"engine":   { "reaper": "7.x", "samplerate": 48000, "buffer": 128, "latency_ms": 5.3 },
"class":    "stage",
"capacity": { "measured_at": "<ISO time>", "nam_lanes": 1, "nam_bytes_max": 400000,
              "xruns_at": { "64": 3, "128": 0 } },
"blocks_missing": ["grit", "surge-spring"]
```

- **`class`** — `rack` (the band's x86 machine), `stage` (one small machine per instrument),
  `desktop` (a musician's Windows or Mac computer). A product label only; `capacity` is what
  constrains.
- **`capacity`** — written by `bench-lanes.py` (to a file such as `presets/.capacity.json`) with
  its date. Absent means never measured. `nam_bytes_max` is the capture size that still plays
  without xruns.
- **`blocks_missing`** — block types whose plugin does not load on this machine. The pushed catalog
  already carries blocks and their quarantine; this lists what this machine cannot mount. On
  Windows and macOS the `unmapped` lists in `library/catalog/effects-*.json` already hold this
  information statically ([`platforms.md`](platforms.md) §5).

### What golem.fm would do with it

1. Before sending a capture: if `capacity` exists and the model exceeds `nam_bytes_max`, refuse
   with the reason displayed, and offer a lighter capture of the same gear if one exists.
2. Before composing a patch: never propose a block listed in `blocks_missing`, the same way a
   quarantined block is never proposed.
3. Never refuse or degrade silently. A heavy pack may be **stored** on the rack, but must not be
   presented as playable.

### Proposed rack-side work

| Step | What it does |
|---|---|
| Capacity file | `bench-lanes.py` writes its result; the heartbeat carries it |
| `blocks_missing` | Computed from the plugins that fail to load on this machine |
| ARM provisioning | Architecture switch in `provision/` (ARM64 REAPER, ARM builds of the NAM LV2 plugin, Debian arm64 packages for guitarix, Calf, x42, Zam, sfizz, Dragonfly) and a reduced block set |

## 4. ARM boards — assumptions to verify

Upstream ships REAPER for Linux `aarch64`, and the NAM LV2 plugin publishes Raspberry Pi 4 and 5
builds; the other LV2 plugins golem uses are packaged for Debian arm64. The bridge and app are
architecture-independent. **Not measured:** how many NAM lanes a Pi-class board holds, at which
buffer and capture size — that is what `bench-lanes.py` answers on the real machine.

A Raspberry Pi has no usable audio input, so it needs either an I²S audio HAT (often line level:
a guitar then needs a buffer or DI in front) or a USB audio interface. A board without an input is
not a golem rig.
