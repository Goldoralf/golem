# Audit 2026-10-01 — REAPER crashing on rapid preset changes (IR convolver)

> **Status: CODED** — incident report. Cause: a race in the x42 **zeroconvo.lv2** IR convolver (the `cab` block),
> present in the Ubuntu package and in upstream v0.7.2. The rack builds its own patched copy:
> `provision/install-zconvo.sh` + `provision/patches/zconvo-retired-engines.patch`. Stress test:
> `./tools/check-recall-stress.sh`. Reported upstream: https://github.com/x42/zconvo.lv2/issues/12.

## 1. Symptom

Three preset rebuilds within three seconds (what `tools/check-foot.py` does, and what a hurried foot does) and
REAPER disappeared about one time in ten, with no error in the app. One defect, four signatures:

| Signature | Where | Convolver |
|---|---|---|
| `Assertion 'self->clv_online->ready ()' failed` (`src/lv2.cc:456`), signal 6 | `/tmp/golem-reaper.log` | Ubuntu package (built with assertions) |
| segfault, write to address 0 in `Convolver::run_buffered_mono`, thread `reaper/livefx` | `journalctl -k` | upstream v0.7.2 |
| `free(): corrupted unsorted chunks`, signal 6 | `/tmp/golem-reaper.log` | upstream v0.7.2 |
| segfault in REAPER's LV2 work queue (absurd element pointer), thread `reaper/mediaafx` | `journalctl -k` | Ubuntu package |

The first three are proven to share the cause (§3). The fourth is consistent with a heap corrupted by the same
double destruction and has not recurred, but it was never captured with instrumentation.

## 2. How it was found

- Two wrong hypotheses were chased in golem's own code first (a port change; a second chunk write destroying a
  plugin mid-load — 97 iterations of a dedicated probe and 30 gdb runs, no crash).
- **The answer was in REAPER's stderr since the first crash**: six assertion lines naming the plugin file and line.
  `journalctl -k` only shows segfaults and `apport.log` only the signal number. Lesson kept in
  [`CLAUDE.md`](../CLAUDE.md): read REAPER's error output first.
- Upstream v0.7.2 changed the signature (no assertion, a null write) without changing the frequency.
- **What settled it: instrumenting the plugin** — an in-memory event log (who calls what, on which thread, to the
  microsecond) dumped when `work_response` put a non-ready engine online. Four crashes, four identical sequences.

## 3. Cause

The plugin keeps two convolution engines: `clv_online` (used by `run()`) and `clv_offline`. The worker loads an IR
into `clv_offline`, the audio thread swaps them (`work_response`), then the worker destroys the old one
(`CMD_FREE`). The bug: the old engine was stored **in `clv_offline`**, and `CMD_FREE` destroyed "whatever is in
`clv_offline`".

On a **fresh instance** there is no old engine:

| t (ms) | Thread | Event |
|---|---|---|
| 0 | main | `instantiate`, `restore` → LOAD 1 scheduled |
| 2.2 | worker | LOAD 1: `clv_offline = C1`… |
| 42.9 | worker | …C1 ready, SWAP 1 response |
| 43.0 | main | **second `restore`** (golem rewrote the chunk) → LOAD 2 scheduled |
| 44.9 | audio | SWAP 1: C1 online; no old engine, `clv_offline = NULL`; FREE scheduled |
| 45.9 | worker | LOAD 2 runs before FREE: `clv_offline = C2`… |
| 87.2 | worker | …C2 ready, SWAP 2 response |
| 87.3 | worker | FREE: **destroys `clv_offline`, i.e. C2**, the engine waiting to be swapped |
| 87.5 | audio | SWAP 2: puts C2 online while it is being destroyed |
| ~90 | audio | `run()` on a destroyed engine → assertion, null write, or later heap corruption |

Two state restores ~40 ms apart on a fresh instance are enough — and `golem_rig` does exactly that when it places a
core: the `.RfxChain` arrives through `SetTrackStateChunk`, then later surgery (labels, file lines, `P_EXT` memory)
rewrites the chunk, and every rewrite makes **every** FX on the track restore its state. Whether it crashes depends
on a few-millisecond race, hence "one time in ten".

Two neighbouring defects: `clv_offline` was published **before** being configured (~40 ms) while `work_response`
swaps whatever it finds without a lock; and the Ubuntu 24.04 package (0.7.1) is built **with assertions** (an
`assert` on the audio thread aborts REAPER) and lacks two 2025 upstream fixes.

## 4. Fix

`provision/patches/zconvo-retired-engines.patch`, on upstream v0.7.2 (commit pinned in `install-zconvo.sh`):

- retired engines get **their own slots** (`clv_retired`, 8 atomic slots written by the audio thread at swap,
  emptied by the worker); `CMD_FREE` destroys nothing else;
- an engine enters `clv_offline` only once **ready**;
- if all 8 slots are full (never observed), the engine is abandoned rather than destroyed on the audio thread, and the
  worker logs it.

`provision/install-zconvo.sh` builds the pinned source + patch and installs it in `~/.lv2/zeroconvo.lv2`, after
checking the binary contains a marker string only the patch adds. When the plugin exists in both places REAPER loads
the `~/.lv2` one (checked in `/proc/<pid>/maps`); the `x42-plugins` package stays installed for its other plugins.
`provision/install.sh` calls it; `provision/components.json` lists it.

**A `git pull` does not fix an installed rack**: run `sudo ./provision/install-zconvo.sh`, restart REAPER, check
`/proc/<pid>/maps`.

## 5. Measurements

`./tools/check-recall-stress.sh` (one pass = one `check-foot.py` = three close rebuilds), same rack and REAPER.

| Convolver | Passes | Crashes |
|---|---|---|
| Ubuntu package 0.7.1 | 85 | 12 |
| upstream v0.7.2, unpatched | 20 | 1 |
| upstream v0.7.2 + event log, unpatched | 25 | 4 |
| upstream v0.7.2 unpatched, under gdb | 13 | 2 |
| v0.7.2 + patch + witness counter | 40 | 0 |
| **v0.7.2 + patch, shipped binary** | **124** | **0** |

The witness counter saw the dangerous moment (a `CMD_FREE` while an engine waited for its swap) 8 times in 40
passes, harmlessly. `check-reamp-align.py` confirmed the cab still sounds (three impulses found, 0.12 ms offset).

## 6. Follow-up

- `provision/patches/zconvo-repro/zc-double-restore.c` reproduces the bug **without a DAW** (minimal LV2 host;
  under AddressSanitizer, `heap-use-after-free` without the patch, none with it). **On every new upstream release,
  run it**: if it passes unpatched, drop the patch and `install-zconvo.sh`.
- `golem_rig` still restores each core's state two or three times per rebuild. No longer dangerous, but each
  restore reloads the IR (~40 ms of worker time); reducing chunk rewrites is a rebuild-time gain to measure.
- If the fourth signature returns alone, look at `schedule_work` called from the main thread (`restore`) while the
  audio thread schedules another — the NAM crash had exactly that cause
  ([`audit-2026-10-14-crash-nam.md`](audit-2026-10-14-crash-nam.md)).

## 7. Found on the way: a render that froze REAPER

Rendering onto an **existing** output file opens a modal "Render Warning — File already exists" that stops REAPER's
main thread (no command read for minutes, on a rack whose REAPER window is hidden). Worse, once the dialog closed
without rendering, the loop answered "render done" because `file_exists` saw the old file. Fixed in
`golem_preview.lua`: the output file is deleted before rendering (previews, reamp tries, reamp jobs).

Two observations left as is: after a reamp try the engine is restored to the Designer sandbox (`_restore_live`,
intended) while `GET /api/state` still names the preset recalled by the API; and the +2 s file verification
(`rig_verify`) can flag NAM models "not loaded" on a lane just muted after a render that are loaded seconds later —
a "⚠ FX FILE" alert can be a slow load, not a lost file.
