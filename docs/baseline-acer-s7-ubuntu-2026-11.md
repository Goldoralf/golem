# Baseline: Acer Aspire S7-391 on stock Ubuntu (November 2026)

**Status: FIXED** (a measurement record, not a contract). Written 2026-11-26, just before this laptop is reinstalled
with an audio-oriented Ubuntu flavour. It is the comparison point for the new install: same machine, same card, same
patch, same golem. Re-measure the "How to compare" items on the new system and add a column; do not edit the
numbers below.

## 1. Machine

| | |
|---|---|
| Model | Acer Aspire S7-391 (2013), Insyde BIOS V2.18 (2013-12-09), UEFI, Secure Boot **on** |
| CPU | Intel Core i5-3337U (Ivy Bridge, 17 W): 2 cores / 4 threads, 1.8 GHz, turbo 2.7 GHz. SMT siblings 0-1 and 2-3. AVX, **no AVX2/FMA** |
| GPU | Intel HD 4000 (shares RAM, cache and the 17 W package budget with the CPU) |
| RAM | 3 GB (3032 MB visible), not upgradable |
| Disk | 2 × LITEON CMT-64L3M 64 GB SSD (mSATA) |
| Audio | PreSonus AudioBox iTwo (USB 2, high speed), ALSA `hw:iTwo`; internal HDA Intel PCH unused |
| Panel | 1920×1080 13.3", golem window 1024×600 |

## 2. System as measured

| | |
|---|---|
| Distribution | Ubuntu 26.04.1 LTS (stock desktop, GNOME on Wayland) |
| Kernel | `7.0.0-44-generic`, `PREEMPT_DYNAMIC` (generic, not lowlatency), cmdline `quiet splash crashkernel=…` (no `threadirqs`, no `isolcpus`) |
| CPU governor | `performance` on all 4 CPUs |
| RT limits | `rtprio 95`, `memlock unlimited` (user in `audio`) |
| Swap | 3.7 GB swapfile, `vm.swappiness` 60 → **10** (2026-11-26) |
| Desktop indexer | `localsearch` running → **masked** (2026-11-26) |
| Browser | Chromium snap, dedicated profile, Wayland, GPU process on `renderD128` |
| Engines | REAPER 7.79 (ALSA `hw:iTwo`, `alsa_rtprio=80`); Golem Engine 9.9-g7 (`luasession`, ALSA, 3 periods) |
| golem | `main` at 2a6a0e4a |

## 3. Numbers

Patch **Eight-String Nu** (factory guitar, NAM + IR, the heaviest guitar patch on this box; the CPU chip says "CPU
tight in scene D"), 48 kHz.

### Golem Engine, before the fixes of 2026-11-26

| Measure | Value |
|---|---|
| Buffer | 1024 × 3 (21.3 ms cycle); 256 × 3 never recovered from an xrun, 512 held |
| Engine CPU | `luasession` 70–86 % of one CPU (sum of its 3 FIFO 78–80 DSP threads) |
| `dsp_load` | 93–100 % |
| Xruns | 352 since start; audible crackles on **/live only**, none on System ▸ CPU cores |
| Engine memory | RSS ~700 MB, swap 0 → **228 MB in one hour**, locked 79 MB (no `mlockall`) |
| System memory | ~140 MB free, ~600 MB available, 580–630 MB swap used, swap-in activity constant |
| Thermal | 66–68 °C package, no throttling |
| /live compositor | 43 composited layers, 3.0 Mpx (vs 5 layers, 0.6 Mpx on CPU cores) |

Causes and fixes: c9943d25 (Live tiles without animations on the local screen: 43 → 5 layers), bd86008c (engine
memory locked, swappiness 10, indexer off), 2a6a0e4a (launcher waits for the bridge). After them the maintainer
played on /live without crackles.

### REAPER, after the fixes (rig running, 60 s window)

| Measure | Value |
|---|---|
| Buffer | 512 (10.7 ms cycle), round-trip latency reported 23.2 ms |
| REAPER CPU | ~100 % of one CPU (`pidstat`, 4 `mediaafx` RR 79 + 3 `livefx` RR 80 threads), scene D |
| Xruns | 17 since start, **0 during the 60 s** |
| REAPER memory | RSS 416 MB, swap 0 |
| Bridge / UI | uvicorn 3.3 %, gnome-shell 2.7 %, Chromium processes < 0.6 % each |
| Whole machine | ~33 % user, 64 % idle (of 4 CPUs); PSI cpu some avg60 3.4, memory 0 |
| System memory | 114 MB free, 915 MB available, 629 MB swap used |
| Thermal | 78 °C package |

## 4. How to compare on the new system

Same patch, same scene, same buffer, nobody touching the window; record the values in a new column.

- Kernel and preemption: `uname -rv`, `cat /proc/cmdline` (lowlatency / `preempt=full` / `threadirqs`?).
- Idle memory before golem starts: `free -m` right after login (the stock desktop leaves ~1.5 GB used).
- Engine CPU and xruns: `pidstat -u -p $(pgrep -d, -x reaper) 60 1` (or `luasession`), and `xruns` from
  `GET /api/state` before and after. System ▸ CPU cores shows the same per core.
- Lowest stable buffer: walk down 1024 → 512 → 256 → 128 on Eight-String Nu and on Chill Jazz; "stable" = 0 xruns in
  5 minutes on /live while playing.
- Engine memory: `grep -E 'Vm(RSS|Lck|Swap)' /proc/$(pgrep -x luasession)/status` after one hour (`VmSwap` must
  stay 0, `VmLck` ≈ `VmRSS`).
- UI cost: the /live page with the window in front, Chromium GPU process and renderer in `top`.
- Thermal: `cat /sys/class/thermal/thermal_zone*/temp` after 10 minutes of playing.
- Boot to sound: time from power button to first note (golem autostart or `golem desktop`).
