# System tuning (Linux)

> **Status: PARTLY CODED** — the system settings a reliable real-time golem needs on Linux: what the provisioning
> scripts apply, and what remains manual (REAPER licence, low-latency kernel, BIOS).

## Real-time limits — `provision/install.sh`

- Adds the user to the `audio` group.
- Writes `/etc/security/limits.d/95-golem-audio.conf`:
  ```
  @audio   -  rtprio     95
  @audio   -  memlock    unlimited
  ```
  PipeWire already ships `@pipewire rtprio 95`; `@audio` is added for REAPER's threads.
- **Restart the computer** for the limits to apply; `ulimit -r` must then print 95. Logging out is not enough when
  golem is running: its bridge and REAPER survive the session (`setsid`) and keep their old limits — `golem stop` first.

## Engine memory — `provision/golem-mlock.c`

CODED 2026-11-26. The Golem Engine (`luasession`) never calls `mlockall`: it locks only its real-time pool and Lua
state (~80 MB of `mlock()`). The rest of its heap can be swapped out, and a DSP thread that touches a swapped page
waits for the disk: an xrun. Measured on the 3 GB Linux rack: `VmSwap` went from 0 to 228 MB in an hour with the
Live page open, while the engine crackled even at a 1024 buffer. The `memlock` limit above was already unlimited;
the call was missing.

- `provision/install-golem-engine.sh` compiles `golem-mlock.c` into `~/.local/lib/golem/libgolem-mlock.so` (needs
  `gcc`; without it the install warns and goes on).
- Both launchers preload it: `bridge/engine/ardour.py` (`mlock_shim`, the engine restart) and
  `provision/lib-engine.sh`; REAPER gets it from `provision/start.sh`, the only Linux path that starts it (the same
  day REAPER had 128 MB in swap for 113 MB in RAM while Firefox played next to it, and Chill Jazz dropped out
  at 512). Its constructor acts in `luasession` and `reaper` only (bash, `setsid`, `run.py` pass through it), calls
  `mlockall(MCL_CURRENT | MCL_FUTURE | MCL_ONFAULT)` and removes `LD_PRELOAD` for the engine's children.
- `MCL_ONFAULT`: a page stays in RAM once touched, but nothing is prefaulted. Without it, `MCL_CURRENT` would load
  the whole mapped space (~1.5 GB) instead of the real footprint (~1 GB).
- Off switch: `GOLEM_ENGINE_MLOCK=0` in the bridge's environment.
- Check, after an engine restart: `grep golem-mlock /tmp/golem-engine.log` (or the bridge's engine log) prints
  `mlockall(onfault) ok`; `grep -E 'Vm(RSS|Lck|Swap)' /proc/$(pgrep -x luasession)/status` shows `VmLck` ≈ `VmRSS`
  and `VmSwap` 0.
- Cost: the engine's memory can no longer yield to the rest. On a 3 GB machine Chrome and the desktop swap more
  instead: the UI may lag, the sound does not. Never set a finite `memlock` limit with this: with `MCL_FUTURE`, an
  allocation past the limit fails and the engine crashes.
- To remove when the engine calls `mlockall` itself.

## CPU governor

- `provision/perf-mode.sh on|off|status` switches every CPU between `performance` and `powersave`. Without
  `performance`, a low clock gives xruns when neural chains load. It is reset at reboot.
- `provision/setup-perf-sudo.sh` (run by `install.sh`) installs a root-owned copy (`/usr/local/sbin/golem-perf-mode`)
  with a NOPASSWD sudoers rule, so the bridge can switch it (`bridge/routes_system.py`, `apply_perf`,
  `apply_perf_for_mode`).
- On a dedicated box, `golem autostart on` installs `golem-perf.service`, which sets `performance` at every boot
  ([autostart/README.md](autostart/README.md)).

## Hardening a dedicated box — `provision/harden.sh`

Idempotent, and refuses to run unless the hostname is `golem-vm`, `golem-rack` or `rack*` (override:
`GOLEM_KIOSK_OK=1`). It applies:

- SSH keys only, root login denied — **only if** `~/.ssh/authorized_keys` exists (otherwise skipped, to avoid a
  lock-out).
- Firewall (`ufw`): deny incoming, allow SSH, 8770/tcp (app/API), 80/tcp (redirect to 8770) and 5353/udp (mDNS).
- mDNS (`avahi-daemon`): `<hostname>.local`, plus `golem.local` announced by the bridge; unprivileged port 80 via
  `/etc/sysctl.d/90-golem-port80.conf`.
- Automatic updates frozen (apt timers masked, unattended-upgrades off): an update is a deliberate act, never the day
  before a gig.
- **USB autosuspend off**: `/etc/udev/rules.d/90-golem-usb-power.rules` sets `power/control=on` on every USB device, so
  the audio interface, keyboards and pedalboard never get suspended (xruns, disconnections).
- **Memory** (2026-11-26): `vm.swappiness=10` (`/etc/sysctl.d/90-golem-swappiness.conf`, the kernel default is 60) and
  the desktop file indexer off (`localsearch-3`, `-control-3`, `-writeback-3` masked, its Tracker folders emptied).
  On the 3 GB Linux rack the engine was being swapped out and the indexer kept reading the disk. The uninstaller puts
  both back (`dedicated:swappiness`, `dedicated:localsearch`). The engine's own lock is in "Engine memory" above.

Network fallback (access point) is separate: [docs/network.md](../docs/network.md).

## Audio

- REAPER uses ALSA directly. `provision/reaper-ini-setup.py` inserts default `alsa_indev`/`alsa_outdev` keys only when
  absent (it never overwrites an existing value); the card is then chosen in the app (Soundcard page, which rewrites
  those keys after REAPER has exited — `bridge/routes_system.py`).
- **Real-time priority for REAPER's audio threads**: `reaper-ini-setup.py` inserts `alsa_rtprio=80` when the key is
  absent (an existing value is never changed). Without it, a fresh `reaper.ini` leaves `reaper/audio` and
  `reaper/livefx` on normal scheduling even though `@audio` may use rtprio 95: they compete with the browser and the
  desktop, and the result is xruns every few seconds (measured 2026-11-24 on an Acer Aspire S7, i5-3337U, 3 GB).
  Check with `ps -L -o tid,cls,rtprio,comm -p $(pgrep -x reaper)`: the audio threads must show `RR 80`, not `TS`.
  `start.sh` runs the script before every REAPER launch, so a restart applies it.
- **Memory on small machines**: on 3 GB, a browser with a few tabs is enough to push REAPER into swap. The audio
  thread then takes major page faults (`/proc/<pid>/task/<tid>/stat`, field 12) and every one of them is a likely
  xrun. Close other applications on such a machine. Real-time priority does not cure this.
- golem's dropout counter (`state.xruns`) reads the kernel log only on Linux: it does **not** see REAPER's own
  xruns, so it can show 0 while the sound crackles.
- Target 48 kHz; lower the buffer step by step (256 → 128 → 64) while watching xruns.
- Make sure REAPER opens the audio interface, not a secondary "Generic USB Audio" device.
- `reaper-ini-setup.py` also forces `norunmute=0` (`ENGINE_FORCED`): REAPER must keep processing muted tracks, because
  split branches are silenced by a track mute ([docs/live-engine.md](../docs/live-engine.md)) and waking their plugins
  on every scene change stalls the engine.

## REAPER auto-mute: must be OFF

`reaper.ini`, section `[reaper]`: `automute=0`. REAPER's "auto-mute tracks that are too loud" protection
(Preferences ▸ Audio, threshold around +6 dB) mutes a track in the middle of a song, with nothing in golem's logs. On a
live rig a surprise mute is the worst outcome; golem's own protection is a zero-latency safety limiter (ceiling
−1 dBFS, `reaper/Effects/golem_safety.jsfx`) placed last on every track that feeds a hardware output
(`golem_rig.lua`, `ensure_safety_limiter`).

Forced by provisioning: `ENGINE_FORCED` in `provision/reaper-ini-setup.py` (Linux) and `configure_ini` in
`provision/desktop.py` (Windows/macOS) write `automute=0`, like `norunmute=0`. Both refuse to run while REAPER is open
(it rewrites `reaper.ini` when it quits).

## Kernel

The generic distribution kernel is enough to validate sound and MIDI. For deterministic latency on a dedicated box, use
`linux-lowlatency` or a PREEMPT_RT kernel. Not automated.

## REAPER licence (dedicated box)

An unlicensed REAPER shows an evaluation nag screen with a countdown at launch; no configuration flag removes it. On a
box that must boot on its own, buy a licence and import it once (splash → *Import license key*, or Options →
*Purchase / authorize*). An evaluation copy is not restricted otherwise.

⚠ The licence file (`*.rk`) is personal and secret: it is gitignored and must never be committed. Keep it outside the
repository, like API keys.

## Still manual

BIOS auto-power-on, WiFi/Bluetooth off on stage if unused, a low-latency kernel, the REAPER licence, and
remote access beyond the LAN if wanted.

## Useful diagnostics

```bash
cat /proc/asound/cards          # ALSA cards
wpctl status                    # PipeWire graph
pw-top                          # live latency / xruns
aseqdump -p "<MIDI port>"       # incoming MIDI (pedalboard, keyboard)
ulimit -r                       # effective rtprio (95 after re-login)
```
