<!--
RESOLVED: fixed upstream by 05405cb (2026-10-02, "Work around double restore"); golem pins that commit and dropped
its patch on 2026-11-03 (provision/install-zconvo.sh). The patch named below no longer exists in this tree.
Text of the upstream issue https://github.com/x42/zconvo.lv2/issues/12 (filed 2026-10-01), kept here for reference.
It is in English, the language of the upstream repository. The issue body starts below the "---" line.
Title: CMD_FREE can delete a freshly loaded engine: second state restore is lost, or use-after-free in run()
Attached files:
  provision/patches/zconvo-repro/zc-double-restore.c   (the reproduction host)
  provision/patches/zconvo-retired-engines.patch         (the fix: attach only the diff part, without the header —
                                                          sed -n '/^diff --git/,$p' provision/patches/zconvo-retired-engines.patch > zconvo-fix.patch)
-->

---

**CMD_FREE can delete a freshly loaded engine: second state restore is lost, or use-after-free in `run()`**

Hi Robin, and thanks for zeroconvo — it is the cab stage of every preset on our guitar rack.

We hit a lifetime bug in the worker logic that shows up when a host restores the plugin's state twice in quick succession on a **fresh instance**. It is present in v0.7.2 (`c6b88d5`, current master) and in 0.7.1. Below: the sequence, a host-independent reproducer (no DAW involved), and a patch we have been running since.

## Sequence

Line numbers refer to `src/lv2.cc` at `c6b88d5`.

1. `restore()` #1 schedules LOAD(A).
2. Worker: `load_ir_worker_locked` sets `clv_offline = A` (l. 604), responds SWAP.
3. `restore()` #2 arrives while the worker is idle and schedules LOAD(B).
4. `work_response` (SWAP): `clv_online = A`, `clv_offline = old`, and on a fresh instance `old` is **NULL** (l. 556–559). It then schedules CMD_FREE, which is queued *behind* LOAD(B).
5. Worker: LOAD(B) finds `clv_offline == NULL`, so it loads B into it and responds SWAP.
6. Worker: CMD_FREE deletes "whatever is in `clv_offline`" (l. 663), and that is now **B**, whose SWAP response is already on its way.
7. Then one of two things happens:
   - **Deterministic outcome:** `clv_offline` is NULL by the time the second SWAP is delivered. The swap is skipped and the plugin keeps IR **A**: the second restore is silently lost.
   - **Concurrent outcome:** the second SWAP is delivered while `delete` is still running (stopping the convolver threads takes milliseconds). `clv_online` becomes a dangling pointer, and the next `run()` reads freed memory.

With a real host, step 7b produced four different signatures for us (Linux, REAPER 7.79):

- `src/lv2.cc:456: Assertion 'self->clv_online->ready ()' failed` with the Ubuntu 24.04 package (0.7.1 is built there without `-DNDEBUG`);
- a NULL write in `Convolver::run_buffered_mono`;
- `free(): corrupted unsorted chunks`;
- and, we believe, a segfault inside the host's worker queue (not captured with instrumentation).

Our host rebuilds tracks from a state chunk, which made each instance receive two or three restores about 40 ms apart. That crashed REAPER on roughly 1 preset change in 10.

## Reproducer, without a DAW

`zc-double-restore.c` (attached) is a minimal LV2 host of about 290 lines: `dlopen`, `CfgMono`, `urid:map`, `options`, `worker:schedule`, and a jalv-like worker that delivers responses right after `run()`.

```sh
cc -O1 -g -fsanitize=address -pthread zc-double-restore.c -o zc-double-restore -ldl
./zc-double-restore /path/to/zeroconvolv.so $PWD/a.wav $PWD/b.wav seq
./zc-double-restore /path/to/zeroconvolv.so $PWD/a.wav $PWD/b.wav threads 200
```

**`seq` mode** (single thread, fully deterministic) restores A then B and reads the IR back with `save()`:

| Build | Result |
|---|---|
| Ubuntu 0.7.1 package | `plugin now holds: a.wav` → BUG |
| v0.7.2 (`c6b88d5`) | `plugin now holds: a.wav` → BUG |
| v0.7.2 + patch below | `plugin now holds: b.wav` → OK |

**`threads` mode** uses a worker thread plus an "audio" thread calling `run()` every 2.7 ms, with the plugin built with `-fsanitize=address`. Unpatched v0.7.2 aborted in 3 of 5 runs of 200 iterations:

```
ERROR: AddressSanitizer: heap-use-after-free
READ of size 4 ... in ZeroConvoLV2::Convolver::artificial_latency() const src/convolver.h:114
    #1 in run src/lv2.cc:457
    #2 in run_cfg src/lv2.cc:1133
freed by thread T469 here:
    #0 in operator delete(void*, unsigned long)
    #1 in work src/lv2.cc:663                      <- CMD_FREE
previously allocated by thread T469 here:
    #0 in operator new(unsigned long)
    #1 in load_ir_worker_locked src/lv2.cc:604     <- LOAD(B)
```

With the patch: 1,000 iterations, no ASan report, B every time.

## Proposed fix

The root cause is that `clv_offline` has two meanings: the engine being loaded, and the engine being retired. The patch (attached, 59 lines in `src/lv2.cc` only) separates them:

- `work_response` sets `clv_offline = NULL` and hands the old online engine to a small array of atomic slots (`clv_retired[8]`), written by the audio thread and drained by CMD_FREE;
- CMD_FREE deletes only retired engines, never `clv_offline`;
- `load_ir_worker_locked` builds and `reconfigure()`s the new engine in a local variable, and publishes it to `clv_offline` only once it is ready. `work_response` swaps `clv_offline` without a lock, so it must never see a half-configured engine there.
- If all 8 slots are full (the worker did not run during 8 consecutive swaps, which we never observed), the engine is leaked rather than deleted on the audio thread, and the worker logs a warning.

On our rack (REAPER 7.79, Ubuntu 24.04, 128-sample buffer), the same stress test went from 12 crashes in 85 passes to 0 in 164.

I'm happy to turn this into a PR, or to adapt it if you would rather solve it differently (for instance with a dedicated "retired" pointer and an explicit swap counter). Thanks again for the plugin.
