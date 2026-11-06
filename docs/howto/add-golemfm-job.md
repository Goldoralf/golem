# How to add a golem.fm job action

**When:** golem.fm must make the rack *do* something (install, push, set a config, report).
golem.fm queues a job; the rack long-polls `GET /api/ext/tones/jobs`, runs it, then acknowledges.
All of it lives in `bridge/tones_jobs.py`.

## Files, in order

1. **Write the handler** in `bridge/tones_jobs.py`. It receives the job **flattened**: payload
   fields sit next to the envelope (`JOB_ENVELOPE = id, device, action, created_at, created,
   payload, _job, space`). Model: `_preset_delete`.
   ```python
   def _thing_set(job):
       """`{action:"thing-set", thing_id, …}` — what it does, which contract (docs/…)."""
       from .store import _safe_id
       _guard_quiet("thing set")                      # if it removes/replaces what is playing
       if not str(job.get("thing_id") or "").strip():          # check BEFORE _safe_id ("" → "untitled")
           raise RuntimeError("thing-set without thing_id")   # → ack {ok: false, error}
       tid = _safe_id(str(job["thing_id"]))
       ...
       return {"_log": f"thing '{tid}' set", "thing_id": tid}  # → ack {ok: true, result: {...}}
   ```
   - Return a `str` (logged) or a `dict`: everything but `_log` becomes the ack's `result`.
   - **Raise** to refuse: the ack carries `str(e)[:500]` and golem.fm shows it. Write it in English.
   - An ack (ok or error) is final: golem.fm never re-proposes an acknowledged job.
   - Never read `job["id"]` as the job id: a payload with its own `id` overwrites it. Use
     `job_id(job)` (prefers `_job`).
   - Fields to drop when you forward the rest: filter on `JOB_ENVELOPE` (see `_mode_set`).
2. **Register it in `_HANDLERS`** (same file): `"thing-set": lambda j: _thing_set(j),` with a
   comment naming the contract. Heavy optional modules are imported lazily inside the lambda
   (`song-separate`, `plugin-recipe`).
3. **Choose the lane — by the name.** `lane_of(action)` sends actions starting with one of
   `_SYNC_PREFIXES = ("take-", "setlist-", "push-catalog")` to the **sync** worker (network only,
   never REAPER); everything else to the **rig** worker (FIFO, one at a time: `patch-try` waits for
   the `preset-install` before it). Name the action so the prefix tells the truth, or extend
   `_SYNC_PREFIXES` and explain why. `reamp` is special-cased (waits for an idle rack).
4. **Guards.** `_guard_quiet(what)` refuses in a locked mode (Gig) or while a take records. Use it
   for anything that removes or rebuilds. Anything that takes the engine (rebuild, render) belongs
   to the rig lane; `_active_mode_busy` shows how to also refuse while a song plays.
5. **Progress (optional).** Long jobs post `POST /api/ext/tones/jobs/{job_id}/progress`
   best-effort, wrapped in `contextlib.suppress(Exception)` — see `on_scene` in
   `_generate_preview`. A job whose ack must wait (measured later) returns
   `plugin_recipes.ASYNC_ACK` and calls `async_done(job_id)` when the ack leaves.
6. **What the screen sees.** If the job adds/removes something listed in the app, add the action
   to `_KINDS` in `bridge/arrivals.py`: it bumps `library_rev` / `content_rev` (pages reload) and
   shows the "⤓ From golem.fm" notice. Otherwise the open page stays stale.
7. **Diagnostics.** Nothing to do: `_diag_job` records `{type: "job", action, ok, ms}` for every
   job. The timeline vocabulary is closed (`EVENTS` in `bridge/diag.py`): a new event type or field
   needs an entry there and in `docs/diagnostics.md`, or it is dropped.
8. **Document** the action, its payload, its ack `result`, its lane and its refusals in
   `docs/golemfm-protocol.md` §3 — `tests/test_golemfm_protocol_doc.py` fails until the table matches
   `_HANDLERS` (and the lane column matches the name prefix) — and in the topical contract.
9. `./provision/reload.sh`.

## Tests

- Call the handler directly, like `tests/test_modes_sync_m1.py`
  (`tones_jobs._mode_set({...})`, `pytest.raises(RuntimeError)` for refusals).
- Lane/ack behaviour: copy the `queue` fixture of `tests/test_jobs_lanes.py` (it monkeypatches
  `_req` and `_HANDLERS`) and assert your job is acked `(id, True)` on the expected lane.
- `tests/conftest.py` already blocks any call to the paired golem.fm server: a test that needs a
  server simulates it.

## Traps

- The lane is decided by a string prefix, not by what the job does: `setlist-push` runs on sync
  but `song-push` on rig; `push-catalog` on sync but `push-library` on rig.
- A job re-proposed while it runs is skipped through `_inflight`; an `ASYNC_ACK` job stays there
  until `async_done` — forget it and the job stays pending on golem.fm, skipped by this process.
- The handler runs in a worker thread: touch REAPER only through `write_command`, never directly.
