# Windows test of REAPER 7.86 — handoff note (2026-11-27, round 2 on 2026-11-28)

> **Status: TO DO (round 2)** — written on the Linux dev box for the agent session that opens on the Windows dev box
> (golem_3, the same PC in dual boot). The agent runs the checks below with the user, **fills in the "Results — round
> 2" section at the end of this file** (and nothing else), and the Linux session reads it back to decide. Delete this
> file once its conclusion is copied into `docs/release-checklist.md` or the release record.

## Round 1 (2026-11-27) in five lines

Verdict **GO WITH RESERVE**. REAPER 7.27 → 7.86 installed through golem (pinned sha256, Cockos installer, one UAC
prompt) and the rig played. This box's 2024 licence key was refused by 7.86 ("license couldn't be decoded", as by
7.79), so golem started the automatic rollback. **The rollback failed**: REAPER 7.86 ignored WM_CLOSE for 180 s. The
card then said `up-to-date` and "engine unchanged" while 7.86 ran in evaluation. At 19:41 the user imported a current
key: 7.86 registered. The box is on **7.86**, and `REAPER (x64).golem-prev` holds **7.27**.

## What changed since (commit `08da8299`)

- **The rollback force-closes REAPER.** It sends WM_CLOSE and, if REAPER is still open after 20 s, terminates it
  (`bridge/desktop_reaper.py`, `stop_engine(force_after=…)`; log line `⚠ REAPER did not close within 20 s — closing it
  by force`). The update itself still closes REAPER politely, never by force.
- **A failed rollback says what is true**: the new engine is still installed, `license_lost`, `rollback_error`.
- **The last result is written to disk** (`%LOCALAPPDATA%\GoleM\runtime\reaper-update-last.json`) with the version
  running at the end, so it survives a bridge restart.
- **The card reads REAPER's licence** (the window title). While a licence lost by an update is still in evaluation:
  badge `⚠ license not accepted — evaluation` and a box with the fix (current key from Cockos, or « Use 7.27 »).
  "engine unchanged" is no longer shown when the engine changed.

## First

```
cd <golem>
git pull
```

`git log --oneline -3` must show `08da8299` (or later). Then restart golem: the bridge must run the new code.
In `cmd`, set Python variables as `set "PYTHONUTF8=1"& python …` (without the quotes the value gets a trailing space
and Python refuses to start).

**Nobody plays during checks 2 to 4 (each one stops and restarts REAPER).**

## The checks, in this order

| # | What | How | Pass when |
|---|---|---|---|
| 1 | Starting point | Settings ▸ About ▸ REAPER. REAPER title bar. Does the **2024 key** (363 bytes, refused by 7.79/7.86) still exist somewhere on this box (a copy, the Recycle Bin, a backup)? Do **not** search the user's whole disk without asking | Card: installed 7.86 = pinned, `✓ matches this release`, « Use 7.27 » offered, no warning. Title: registered. Note whether the 2024 key is available: it decides between 3a and 3b |
| 2 | The way back, polite | « Use 7.27 » (two taps). One UAC prompt | REAPER 7.27 restarts and plays, registered with the current key (note what the title says). Card: installed 7.27, `⬆ update available`, « Use 7.86 » offered |
| 3a | **Only with the 2024 key**: the real scenario | Copy the current `%APPDATA%\REAPER\reaper-license.rk` aside first (**name the copy in the Results**). Put the 2024 key in its place, restart golem (REAPER reads its licence at start), check the title says registered on 7.27. Then « Update engine to 7.86 » | Log: `✗ REAPER 7.86 runs in EVALUATION…`, then either REAPER closes by itself, or `⚠ REAPER did not close within 20 s — closing it by force`. Then a second UAC prompt, `✓ rolled back — previous engine is up`. Card: installed **7.27**, the line `✗ REAPER 7.86 does not accept your license key (7.27 did) — rolled back to 7.27…`, no evaluation warning (7.27 is registered). Then **put the current key back** (the copy) and restart golem |
| 3b | **Without the 2024 key**: the forced close alone | REAPER running (7.27 from check 2). In REAPER, open a **modal** dialog (Help ▸ About REAPER, or File ▸ Render…) and leave it open. Then, from `<golem>`: `set "PYTHONUTF8=1"& .venv\Scripts\python -c "from bridge import desktop_reaper as D; print(D.stop_engine(print, force_after=20))"` (adjust the Python path if golem's venv is elsewhere) | Note which happened: REAPER closed politely (the modal did not block WM_CLOSE: then this check proves nothing, say so), or the line `⚠ REAPER did not close within 20 s — closing it by force` and REAPER gone within ~40 s. In both cases no `reaper.exe` left (Task Manager). Then restart golem: REAPER reopens on the set and plays |
| 4 | Back to 7.86 | Settings ▸ About ▸ REAPER ▸ « Update engine to 7.86 » (or « Use 7.86 » if offered). One UAC prompt | 7.86 runs **registered** with the current key. Card: `✓ matches this release`, no warning, no `✗` line about the licence |
| 5 | The result survives a restart | After check 3a (or 4): restart golem (bridge), reopen Settings ▸ About ▸ REAPER | The last result line is still shown, the same as before the restart. `%LOCALAPPDATA%\GoleM\runtime\reaper-update-last.json` exists and its `running` is the engine that runs |
| 6 | Plays | Recall a factory guitar patch, play; scene A→B | Sound with no crackle, scene change with no blank you can hear |

## If something fails

- Copy the **last 30 lines of the card's log** (Settings ▸ About ▸ REAPER) into the Results, and the content of
  `reaper-update-last.json`.
- A screenshot of the card helps: the Linux session checks the badge and the box against the code.
- If the licence is lost and stays lost: put the current key back (the copy from 3a), restart golem.
- **Do not fix code here.** Describe what you saw; the Linux session decides.

---

## Results — round 2

> Filled in by the Windows agent. One of `PASS`, `FAIL`, `NOT RUN` per check, then what was seen (versions, log lines,
> what the card said, what the user heard). Short and factual: no "I think".

- Date and time (local):
- golem commit on this box (`git log -1 --oneline`):
- 2024 key available (3a) or not (3b):
- Copy of the current key made in 3a (path):

| # | Result | What was seen |
|---|---|---|
| 1 | | |
| 2 | | |
| 3a / 3b | | |
| 4 | | |
| 5 | | |
| 6 | | |

**Log excerpt** (card log, check 3a or the output of 3b):

```
```

**Anything else noticed** (even outside the checks):

-

**Verdict of the Windows agent** — one of: `GO` (7.86 and the rollback fix can ship for Windows) · `NO-GO` (say which
check) · `GO WITH RESERVE` (say what):

## Sending it back

Commit **only this file** (`docs/windows-test-2026-11-27.md`), message `Windows test of REAPER 7.86: round 2 results`,
and push it **when the user says so**. If pushing is not possible, leave the file as it is: the Linux session can read
it from the Windows partition.
