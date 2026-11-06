# Tooling, testing and measurement pitfalls

The `tools/check-*` scripts run against the live rig. They write real files, send real MIDI and can
crash REAPER. These rules keep a probe from becoming an incident, and a measurement from lying.

---

## Measure with a clock that does not depend on what you measure

**Symptom.** A tool reports "0 gap" while the user hears a blank; a peak meter polled at 30 Hz shows
a continuous signal across a hole.

**Cause.** A JSFX that counts processed samples cannot see an engine that processes nothing. A polled
peak meter fills a gap with its own decay.

**Rule.** Compare the instrument's clock against an independent clock (wall clock vs audio-thread
counter); detect gaps at sample level, not by polling.

**Code.** `tools/check-scene-gap.py` + `reaper/Effects/golem_gapmeter.jsfx`,
`tools/check-block-stall.py`, `bridge/monitors.py` (audio-thread witness vs wall clock).

---

## Check that the gesture reached its target before trusting the measurement

**Symptom.** A tool measures "0 ms" on an effect that was never touched.

**Cause.** The command targeted an identifier the target did not carry (cores are not always stamped
`golem:<id>`).

**Rule.** Every probe confirms its action landed (read the parameter back) before measuring.

---

## A probe must not start a take

**Symptom.** A verification run leaves a recording and the backing track running.

**Cause.** A probe replayed the message of a switch reserved to Rec.

**Rule.** A verification tool restores every service it touches to its prior state, and never
triggers anything that records or makes sound (Rec, backing): it lists those as "check at the foot".

**Code.** `tools/check-foot.py` (reserved switches: `rec`, `backing-track` not injected; others
restored).

---

## Clean up test writes

Test scripts write into real presets, setlists and mappings. Restore them afterwards and say so.
Destructive stress tools (`./tools/check-recall-stress.sh`, `./tools/check-reamp-align.py`) take the
engine: run them only when nobody is playing. Heavy processing (separation, GPU, training) is never
run while playing.

---

## A measurement started together with an instruction measures nothing

**Rule.** When a measurement needs a person to act (plug a device, play, press a switch), give the
instruction, wait for their "done", then measure. Launching both at once records the "before".

---

## Run the diagnostic before restarting

**Rule.** When sound disappears, photograph the state first (`./tools/check-silence.py`: audio
witness, per-track peaks while playing, armed input, NAM/IR loaded, verdict "where the signal
stops"). Restarting REAPER erases the evidence.

---

## Killing by pattern matches yourself

**Symptom.** A `pkill -f` / `pgrep -f` / `ps | grep` finds its own command line (or the calling
shell), kills the caller or reports a process that is not running.

**Rule.** Match exact process names (`pgrep -x`), or PIDs recorded at launch. When `-f` is
unavoidable, use a marker that cannot appear in the matching command itself.

**Code.** `tools/check-recall-stress.sh` (`pgrep -x reaper`), `provision/stop.sh` (`_kill` with an
explicit `-x`/`-f` flag).

**Same family: a pattern that also matches someone else's process.** Before 2026-10-25,
`reload.sh` ran `pkill -f "uvicorn bridge.app"`, which also killed the disposable bridge of a
`check-rig-materialize` or `check-ui` run going on next to it. And `start.sh` took that
disposable bridge for the rack's own and did not start it. The rack's bridge is the one on
**its port**: `reload.sh`, `start.sh` and `stop.sh` match
`uvicorn bridge.app:app --host … --port $GOLEM_PORT` (`BRIDGE_PAT`). `stop.sh` still stops
every `reaper` (`pgrep -x`), including a probe's isolated REAPER.

---

## On a process or action name, compare — never search inside

**Symptom.** "REAPER is running" while it is dead: a substring test on `/proc/*/comm` matched the
kernel thread `oom_reaper`. Same family: command routing on a bare substring.

**Rule.** Use equality on names; quote tokens when matching raw JSON.

**Code.** `bridge/monitors.py` `_reaper_pid`; `reaper/Scripts/golem_watch.lua` (quoted patterns).

---

## `.gitignore` does not accept trailing comments

**Symptom.** A pattern ignores nothing.

**Cause.** `pattern  # comment` is read as a pattern containing `#`.

**Rule.** Comments go on their own line. Note also that `.env.*` matches a tracked `.env.example`:
git keeps tracking it, but every other tool that reads `.gitignore` (rsync filters, build contexts)
excludes it — add `!.env.example`.

---

## A monkeypatched platform proves nothing

**Rule.** Tests that only set `sys.platform` prove parsing, not behaviour on that OS. Claim platform
support only after running on the real OS; keep a list of what was actually verified there.

---

## Swallowed exceptions hide real bugs

**Symptom.** A feature silently stops (e.g. a MIDI program change no longer sent on recall).

**Cause.** A `NameError` (a variable local to another function) inside `contextlib.suppress(Exception)`.

**Rule.** Do not wrap more than the one call that may legitimately fail; log what is swallowed. Run
a narrow linter (syntax + undefined names) on every push.

**Code.** `ruff.toml`, `tools/check-syntax.py`, `.github/workflows/ci.yml`, `bridge/golog.py`
(`swallowed`).

---

## A literal BOM in code can be intentional

Before stripping BOMs or invisible characters in bulk, check whether the code relies on them
(stripping a BOM from Windows input). Write such characters as escapes (`"﻿"`).

---

## Read the contract before coding, and say when an instruction rests on a false premise

`docs/*.md` contracts carry a status (FIGÉ/PROPOSÉ/CORRIGÉ). If code and contract disagree, one is
wrong: report it rather than silently choosing. Verify a premise ("this table has no UI") before
executing an instruction built on it. Read the existing table or function before rewriting it from
memory.
