# Windows test of REAPER 7.86 — handoff note (2026-11-27)

> **Status: TO DO** — written on the Linux dev box for the agent session that opens on the Windows dev box (golem_3,
> the same PC in dual boot). The agent runs the checks below with the user, **fills in the "Results" section at the
> end of this file** (and nothing else), and the Linux session reads it back to decide. Delete this file once its
> conclusion is copied into `docs/release-checklist.md` or the release record.

## Why

`provision/windows/pins.json` now pins **REAPER 7.86** (commit `06e644ff`), up from 7.79:

| | |
|---|---|
| url | `https://www.reaper.fm/files/7.x/reaper786_x64-install.exe` |
| sha256 | `02af50cc5c5417b92efde1e8fbdb4f37564e8545c3da409782ecbe7c0e90df76` (today's download over HTTPS; Cockos publishes no checksum) |
| signer | `Cockos Incorporated` |

7.86 was installed and played on the Linux rack on 2026-11-27. On Windows it was never run. The next golem release
ships this pin to every Windows install (install line **and** Settings ▸ About ▸ REAPER), so it must be tried here
first. macOS will not be tried (no Mac at hand): the release goes out anyway, and the Linux session records that.

## First

```
cd <golem>
git pull
```

`git log -1 --oneline` must show `2bce9d8b` or later, and `provision\windows\pins.json` must say `"version": "7.86"`
for `reaper`. Then restart golem so the bridge reads the new pin. In `cmd`, set Python variables as
`set "PYTHONUTF8=1"& python …` (without the quotes the value gets a trailing space and Python refuses to start).

**Nobody plays during check 2 (the update stops and restarts REAPER).** Checks 3 and 4 need the user at the guitar.

## The checks, in this order

| # | What | How | Pass when |
|---|---|---|---|
| 1 | Starting point | Settings ▸ Engines: **REAPER** selected (switch to it if the Golem Engine is active, and note it). Settings ▸ About ▸ REAPER: read installed / pinned / status. Note the REAPER title bar (licence text) | The card shows installed 7.79 (or what it really is — note it), pinned **7.86**, status "behind" |
| 2 | The update from golem | Settings ▸ About ▸ REAPER ▸ Install 7.86. **One UAC prompt appears on the PC screen**: accept it. Read the card's log to the end | Log shows the download, `sha256` equal to the pin above, signature `Cockos Incorporated`, REAPER restarted, OSC link back. Card: installed **7.86** = pinned, nothing left to do. `C:\Program Files\REAPER (x64).golem-prev` exists (the old install, kept for the way back). No rollback line |
| 3 | Played on the rig | Recall a factory guitar patch (e.g. "Low Tide"), play: sound through the ASIO card. Change scene A→B→A with the foot (or the screen), press a stomp, record a short take and play it back. Recall one keys patch and play a few notes | Sound with no crackle, scene changes without a blank you can hear, the stomp acts, the take plays back with sound, the keys sound |
| 4 | Plugins and health | After check 3: `python tools\doctor.py` and Settings ▸ System ▸ Health | No new incident about REAPER, a plugin or the card. golem-fx and NAM blocks load (no "missing plugin" on the patch) |
| 5 | The way back (optional, only if time allows) | Settings ▸ About ▸ REAPER: go back to the previous version (7.79), check REAPER restarts and plays, then Install 7.86 again | Both moves work, each with one UAC prompt |

Not tested here, on purpose: a fresh install through `provision\windows\install-system.ps1` (it uses the same pin; the
hash and signature are checked the same way in check 2).

## If something fails

- Copy the **last 30 lines of the card's log** (Settings ▸ About ▸ REAPER) into the Results.
- If REAPER does not come back: golem should swap back to the old install by itself (`-ReaperSwap`). Note whether it
  did, and what Settings ▸ About ▸ REAPER says after.
- A crash of REAPER: the Windows Event Viewer ▸ Windows Logs ▸ Application, the "Application Error" for `reaper.exe`
  — copy the faulting module and the exception code.
- A UAC prompt refused or not seen: nothing is touched, REAPER restarts as it was; just run check 2 again.
- **Do not fix code here.** Describe what you saw; the Linux session decides (fix, or put the pin back to 7.79).

---

## Results

> Filled in by the Windows agent. Keep the shape: the Linux session reads it line by line. One of `PASS`, `FAIL`,
> `NOT RUN` per check, then what was seen (versions, log lines, what the user heard). Short and factual: no "I think".

- Date and time (local):
- golem commit on this box (`git log -1 --oneline`):
- Engine selected at start, and at the end:
- REAPER installed before (Settings ▸ About ▸ REAPER):
- REAPER installed after:
- REAPER title bar after (licence text):
- Sound card (ASIO driver name, buffer):

| # | Result | What was seen |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |

**Log excerpt** (only if a check failed, or if something looked odd):

```
```

**Anything else noticed** (even outside the checks):

**Verdict of the Windows agent** — one of: `GO` (7.86 can ship for Windows) · `NO-GO` (say which check) · `GO WITH
RESERVE` (say what):

## Sending it back

Commit **only this file** (`docs/windows-test-2026-11-27.md`), message `Windows test of REAPER 7.86: results`, and
push it **when the user says so**. If pushing is not possible, leave the file as it is: the Linux session can read it
from the Windows partition.
