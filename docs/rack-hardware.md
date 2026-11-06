# Reference rack hardware and OS tuning

> **Status: PARTLY CODED** — the reference x86 rack and how to prepare its OS for real-time audio.
> RT limits, the CPU governor, USB autosuspend and the access point are applied by `provision/`;
> core pinning, IRQ pinning, the kernel command line, the low-latency kernel and the Wi-Fi
> regulatory domain are **manual** steps described here.

Related: [`network.md`](network.md) (Wi-Fi station / access point), [`rack-classes.md`](rack-classes.md)
(other machine classes), [`installer.md`](installer.md) (what the installer does),
[`platforms.md`](platforms.md) (Windows and macOS).

## 1. Reference build

golem runs on any recent x86-64 Linux PC; this is the configuration the scripts are tuned for.

| Part | Reference | What matters |
|---|---|---|
| Board | Mini-ITX AM5 (ASRock B650I Lightning WiFi) | 2.5 GbE Realtek RTL8125BG (`r8169`), Wi-Fi 6E MediaTek MT7922 (`mt7921e`) |
| CPU | AMD Ryzen 5 8500G | **Heterogeneous cores**: 2 × Zen 4 (~5.0 GHz) + 4 × Zen 4c (~3.7 GHz), 12 threads, 65 W |
| RAM / storage | 16 GB DDR5, NVMe | Room for the OS and the NAM/IR library |
| Case | 2U rack case | CPU cooler height limited (65 mm in the reference case) |
| Audio / MIDI | USB audio interface (reference: Universal Audio Volt 276), foot controller on the interface's DIN MIDI, USB keyboard | No PCIe card |
| Second Wi-Fi radio (optional) | USB dongle with an in-kernel driver (reference: MediaTek MT7612U, `mt76x2u`) | Lets the rack be a Wi-Fi client **and** an access point at the same time ([`network.md`](network.md)) |
| Touch screen (optional) | 7″–10″ HDMI panel with USB capacitive touch | Driver-free on Ubuntu (HID). The app is laid out for 1024×600 landscape without scroll |

## 2. OS and kernel

- **Ubuntu 24.04 LTS**: every script in `provision/` targets it (PipeWire, NetworkManager, HWE
  kernel). The HWE kernel covers AM5/B650, RTL8125BG, MT7922 and `amd-pstate`.
- **Kernel: `linux-lowlatency-hwe-24.04`, not PREEMPT_RT.** For USB audio at 64–128 samples the
  low-latency kernel (1000 Hz, full preemption) is the right trade-off; PREEMPT_RT costs
  throughput that heavy NAM chains need, and USB audio cannot use the latency below ~32 samples
  that it would buy. Install it by hand: `sudo apt install linux-lowlatency-hwe-24.04`.
  `provision/harden.sh` lists it as a manual step.
- **Real-time limits** (applied by `provision/install.sh`): the user joins the `audio` group and
  `/etc/security/limits.d/95-golem-audio.conf` sets `@audio - rtprio 95` and
  `@audio - memlock unlimited`. Log out and in (or reboot) for them to apply; check with
  `ulimit -r`.
- **Kernel command line** (manual, `/etc/default/grub` → `GRUB_CMDLINE_LINUX_DEFAULT`, then
  `sudo update-grub`):
  ```
  threadirqs usbcore.autosuspend=-1
  ```
  `threadirqs` lets you pin the USB controller's IRQ thread (§3). `usbcore.autosuspend=-1`
  complements the udev rule below.
- **USB autosuspend off** (applied by `provision/harden.sh`): udev rule
  `/etc/udev/rules.d/90-golem-usb-power.rules` sets `power/control=on` on every USB device. An
  audio interface that suspends and re-enumerates mid-set is lost to REAPER (see the pitfall in
  [`CLAUDE.md`](../CLAUDE.md) on REAPER not noticing a vanished sound card).
- **CPU governor `performance`** (applied at boot by `provision/autostart/system/golem-perf.service`,
  installed by `provision/autostart/install-autostart.sh`; by hand: `provision/perf-mode.sh on|off`).
  On a powersave governor the frequency drops and neural chains xrun.
- **Automatic updates frozen** (`provision/harden.sh`): `apt-daily` timers disabled and
  unattended upgrades off. Update by hand, never before a gig.

Audio server and REAPER settings (PipeWire in JACK mode, 48 kHz, quantum lowered step by step from
256 to 64 while watching xruns, `automute=0` in `reaper.ini`) are in `provision/system-tuning.md`.

## 3. Real time on heterogeneous cores (manual)

The 8500G's two core types share the ISA, IPC and L3; **only the clock differs**, so a thread on a
Zen 4c core runs about 26 % slower. At 64 samples / 48 kHz (1.33 ms per block), REAPER's audio
thread migrating to a slow core mid-set cuts the per-block budget by that much: an isolated xrun on
a heavy NAM chain. The remedy is to keep the audio path on the fast cores. **Nothing in
`provision/` does this yet.**

**Find the fast cores — never hard-code `cpu0-1`:**

```bash
# max frequency per CPU: Zen 4 ≈ 5076000, Zen 4c ≈ 3731000
for c in /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq; do
  echo "$(dirname $(dirname $c) | grep -o 'cpu[0-9]*') $(cat $c)"; done | sort -t u -k2 -n
cat /sys/devices/system/cpu/cpu*/topology/thread_siblings_list | sort -u   # SMT pairs
```

**Partition with systemd `AllowedCPUs`, not `isolcpus`** (`isolcpus` is too blunt on six cores and
needs a reboot to undo). Example drop-ins, with the CPU lists taken from the detection above:

```ini
# REAPER: fast cores and their SMT siblings
[Service]
AllowedCPUs=0 1 6 7
Nice=-10
```

```ini
# bridge (golem-server.service) and the app window: slow cores
[Service]
AllowedCPUs=2 3 4 5 8 9 10 11
```

`amd-pstate` preferred-core support (kernel ≥ 6.9) already biases the scheduler towards the fast
cores; pinning makes it a guarantee.

**Pin the audio interface's USB controller IRQ** to a fast core (needs `threadirqs`):

```bash
grep -i xhci /proc/interrupts
echo 0 | sudo tee /proc/irq/<IRQ>/smp_affinity_list
```

## 4. Cooling — the main xrun risk in 2U

A 65 W CPU held at full clock by the `performance` governor, in a shallow 2U case with front-to-back
airflow, throttles under a sustained NAM load with a stock cooler. Throttling is the same per-block
budget cut as a slow core (§3).

- Use a low-profile cooler made for this (reference: Noctua NH-L9a-AM5, 37 mm), populate the case
  fans and duct the airflow front to back.
- **Soak test before relying on it** (30 min):
  ```bash
  watch -n1 'sensors | grep -E "Tctl|Tccd"; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'
  # in parallel: stress-ng --cpu 6 --timeout 1800s, plus a real heavy preset playing
  ```
  Target: Tctl well below 95 °C, fast cores holding their clock. If it throttles, it is the cooler,
  not the configuration.

## 5. USB topology

What matters is the **root hub**, not the port count.

- Put the **audio interface alone on its own root hub**, on a USB 3 port, away from the screen and
  keyboards. Isochronous audio is sensitive to a chatty neighbour on the same bus. Check with
  `lsusb -t` after cabling.
- The foot controller uses the interface's **DIN MIDI**: no USB port.
- Low-bandwidth devices (USB keyboard, touch screen) go on another hub; a **powered** hub keeps a
  current spike from dropping the bus. A touch screen powered from USB draws up to ~2 A: never on
  the audio interface's hub.

## 6. Network hardware

- **Ethernet** (`r8169`, in-kernel) works out of the box and is the always-available admin port.
  Some RTL8125 chips link-flap under `r8169`; only if you see it, switch to `r8125-dkms` and
  blacklist `r8169` (DKMS modules break on kernel updates, so do not do it pre-emptively). Validate
  with `ethtool -i <if>` and a sustained `iperf3` run.
- **Wi-Fi access point** (`provision/net.sh ap-up`, profile `golem-ap`): WPA2-PSK, band from
  `config/network.json` `.ap.band`, default **`bg` (2.4 GHz)** — reliable on the MT7922 and better
  range for a tablet. **Never run the access point in 6 GHz** on the MT7922 (no-IR channels,
  mandatory WPA3-SAE, broken channel selection).
- **Regulatory domain** (manual): without a country, a boot in world domain `00` can refuse to start
  the access point. Set it (`sudo iw reg set <CC>`, persisted with `REGDOMAIN=<CC>` in
  `/etc/default/crda` or your distribution's equivalent) and check with `iw reg get`.
- **Second radio**: prefer MediaTek USB dongles with in-kernel drivers (`mt76x2u`). Avoid Realtek
  dongles that need out-of-tree DKMS drivers (`88x2bu`, `8821au`): they break on kernel updates.

## 7. Bring-up checklist

1. `provision/install.sh`, then log out and in; `ulimit -r` → 95.
2. `provision/harden.sh` (USB autosuspend, frozen updates, firewall, mDNS).
3. `provision/autostart/install-autostart.sh` (governor service, `golem-server.service`).
4. Manual: low-latency kernel, kernel command line, regulatory domain.
5. Manual: detect fast cores, add the `AllowedCPUs` drop-ins, pin the xhci IRQ.
6. `lsusb -t`: audio interface alone on its root hub.
7. 30-minute thermal soak with a real preset; `iperf3` on Ethernet.
