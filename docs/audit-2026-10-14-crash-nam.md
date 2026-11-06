# Audit 2026-10-14 — REAPER crashing on rapid patch changes: the NAM amp

> **Status: CODED** — incident report. Cause: two producers on the LV2 work queue in the NAM LV2 plugin (Oliphant,
> v0.2.2). Fix: `provision/patches/nam-thread-safe-worker.patch`, built and installed by `provision/install-nam.sh`
> (called by `install.sh` after the convolver). Sibling report:
> [`audit-2026-10-01-crash-convolveur.md`](audit-2026-10-01-crash-convolveur.md).

## 1. Symptom

REAPER died during a patch rebuild: `general protection fault` in `neural_amp_modeler.so` (thread
`reaper/mediaafx`) at `NeuralAudio::DenseLayerT<8,8,true>::Process` — model **computation**, not loading. Just
before, `/tmp/golem-reaper.log` showed the same captures "Restoring model" then "Staging model change" almost
simultaneously.

## 2. Reproduce, then measure

Recalls of 6 patches using NAM captures, every 0.5–0.8 s, through `POST /api/recall`:

| Plugin | Recalls | Result |
|---|---|---|
| release v0.2.2, instrumented | ~50 | `double free or corruption (out)` (glibc abort) |
| same | 18 | nothing |
| same | 58 | GPF **inside REAPER** (`mediaafx`): the loop draining the LV2 work queue reads an absurd pointer — the unexplained fourth signature of the convolver audit |
| fixed, instrumented | 180 | **no crash** |
| fixed, final clean binary | 120 | **no crash** (75 × "retired model(s) freed by the worker") |

The instrumentation (an in-memory ring drained by the worker: who calls `run` / `work_response` / `restore` / `work`,
on which thread, to the microsecond, plus `instantiate` / `cleanup`) **refuted** the obvious hypothesis (a model swap
during a `run()` on another thread): no swap during a computation, no destruction of the model in service, no double
destruction of a model. It showed what REAPER does:

- an instance's `run()` hops between threads constantly (a `mediaafx` pool + `livefx`); the LV2 worker runs on those
  same threads;
- `restore()` runs on the **main** thread;
- **15–20 % of `work_response()` calls run on the main thread**: when REAPER retires an instance (rebuild) it flushes
  pending responses there, in batches of 2–3, then destroys it.

## 3. Cause

The plugin schedules work (`schedule_work`) from the main thread while audio threads use the same queue — two
concurrent producers on a queue REAPER does not protect for that:

- `restore()` used the **instance's** scheduler (meant for `run()`), although the host passes a scheduler that is safe
  in that context in the restore `features` (REAPER provided it on every restore measured: 364/364; the convolver
  already uses it);
- `work_response()` scheduled the destruction of the old model — from the main thread when REAPER calls it there.

A corrupted queue explains all three signatures: an element freed twice (double free), an absurd pointer in REAPER's
loop (GPF in `reaper`), a destruction message aimed at the wrong model (GPF in `Process`).

## 4. Fix

`provision/patches/nam-thread-safe-worker.patch`, on tag v0.2.2 (commit pinned in `install-nam.sh`):

- `restore()` uses the host-provided scheduler (`LV2_WORKER__schedule` in its `features`), else the instance's;
- `work_response()` schedules nothing: the old model goes into a **locker** (8 atomic slots) the worker empties off the
  audio thread on its next job, with the destructor as last resort. Locker full (never observed): the model is
  abandoned — a bounded leak, never a crash.

`provision/install-nam.sh` builds the pinned source + patch (Release, x86-64-v3 like the official release), replaces
the binary in `~/.lv2/neural_amp_modeler.lv2`, and checks the binary contains a string only the patch adds
(`NAM_MARK`). `provision/plugins.sh` no longer reinstalls the release over a patched build.

## 5. Follow-up

- **A `git pull` does not fix an installed rack**: run `./provision/install-nam.sh` (no sudo needed if cmake, g++ and
  git are present), restart REAPER, check `/proc/<pid>/maps`.
- To report upstream (mikeoliphant/neural-amp-modeler-lv2). On every new upstream release, replay the recall series:
  if the release passes unpatched, drop the patch.
- Windows/macOS use the official NAM VST3, which does not use this LV2 worker: not affected, not measured.
- As with the convolver, `golem_rig` restores each core 2–3 times per rebuild; fewer chunk rewrites means fewer model
  loads (a rebuild-time gain, no longer a safety issue).
