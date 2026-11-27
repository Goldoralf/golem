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

- Date and time (local): 2026-11-27, 19:27 → 19:35
- golem commit on this box (`git log -1 --oneline`): `191664af Docs: handoff note for the Windows test of REAPER 7.86`
  (then `python -m provision.desktop setup`: golem-fx 0.8.2, Golem Engine 9.9-g8 already there)
- Engine selected at start, and at the end: REAPER / REAPER
- REAPER installed before (Settings ▸ About ▸ REAPER): **7.27**, not 7.79 — `REAPER (x64).golem-prev` already held
  7.79 (an earlier 7.27 → 7.79 update had been swapped back, see `bridge/desktop_reaper.py:163`)
- REAPER installed after: **7.86** (`reaper.exe` ProductVersion 7.86); `golem-prev` now holds 7.27 (the 7.79 copy is gone)
- REAPER title bar after (licence text): `golem-set [modified] - REAPER v7.86 - EVALUATION LICENSE`
- Sound card (ASIO driver name, buffer): Universal Audio Volt, 48 kHz, 256 samples (12.2 ms)

| # | Result | What was seen |
|---|---|---|
| 1 | PASS | `GET /api/system/reaper-update`: installed 7.27, pinned 7.86, status `update-available`; licence `registered` |
| 2 | FAIL (install PASS, rollback FAIL) | Download, `sha256 verified against the pinned release`, one UAC prompt, `keeping REAPER 7.27 next to it`, `REAPER 7.27 → 7.86`, engine restarted, OSC link alive. Then 7.86 ran in **EVALUATION** with this box's licence key (the same key 7.79 already refused) → golem started the automatic rollback, as designed. The rollback then **failed**: WM_CLOSE posted, REAPER 7.86 did not close in 180 s (no visible dialog among its windows, project still `[modified]`), worker ended `{"ok":false,"rolled_back":false,"error":"REAPER is still open — check its save prompt"}`. No second UAC prompt (never reached). The card then shows **installed 7.86 = pinned, status `up-to-date`** — it does not show that the update failed and the licence is lost |
| 3 | PASS | Played by the user on 7.86 (evaluation mode): "everything sounds good" |
| 4 | PASS (one oddity) | `tools\doctor.py`: no incident on REAPER, a plugin or the card; engine REAPER 7.86 talking to the bridge; 0 dropouts; setlist "Factory Guitar" 15 presets, every block ready. Only open incident: golem.fm unreachable (network, unrelated). Drift line: `REAPER 7.27 → 7.86 · plugins 673 → 614` (see below) |
| 5 | NOT RUN | — |

**Log excerpt** (card log, check 2):

```
⏳ downloading REAPER 7.86…
✓ downloaded reaper786_x64-install.exe
✓ sha256 verified against the pinned release
⏳ stopping audio engine (project saved)…
✓ project saved
✓ audio engine stopped
⏳ Windows asks for permission on the PC screen — approve it there
✓ sha256 OK (pinned)
→ keeping REAPER 7.27 next to it
✓ REAPER 7.27 → 7.86
✓ system step done
⏳ restarting audio engine…
⏳ verifying (engine boots + rig link alive)…
✗ REAPER 7.86 runs in EVALUATION — your license key is not accepted; going back to 7.27 (Windows asks once more)…
✓ project saved
✗ REAPER is still open — check its save prompt
```

**Anything else noticed** (even outside the checks):

- REAPER's plugin count fell from 673 to 614 across the update (`presets/.fx-inventory.json`, written 19:28:21 by
  7.86: 133 VST3, 61 VST, 29 VST3i, 8 VSTi, 151 LV2, 22 LV2i, 2 CLAP, 204 JS…). The 7.27 inventory was overwritten,
  so which 59 went missing is not known. No block of the factory setlist is affected.
- The licence refusal is not specific to 7.86: this box's key was already refused by 7.79. It is a property of the
  key, not of the 7.86 build — but every user whose key stops at 7.27-era versions will hit the same rollback path.
- The licence, checked after the test: REAPER 7.86 (Help ▸ About ▸ License) says **"license couldn't be decoded"**
  (REAPER's own text — not in golem's code). `%APPDATA%\REAPER\reaper-license.rk` is intact: 363 bytes, one line,
  pure ASCII, no BOM, no CR/LF, written 2024-11-15 11:08 — two minutes after REAPER 7.27 was installed, so by
  REAPER 7.27 itself when the key was typed; golem never rewrote it. Same file: accepted by 7.27, "couldn't be
  decoded" by 7.79 and 7.86 → the key's format/generation, not a copy or encoding fault. The file already survives
  every update (it lives outside the install folder): re-importing the same key changes nothing; a current key from
  Cockos, imported once, would be kept by every later update. Not confirmed with Cockos.
- What this means for users: someone holding an old key who taps Install 7.86 gets an update that loses the licence,
  then (as seen here) a rollback that can fail silently. The user owns the decision on this box (handled later).
- The box was left on REAPER 7.86 in evaluation (plays normally). Resolved the same evening: at 19:41 the user
  imported their current key (new `reaper-license.rk`, 560 bytes instead of 363) and reports REAPER 7.86 registered
  (seen by the user; the agent could not re-read the title, REAPER and the bridge were closed). Confirms the cause:
  the 2024 key's generation, not 7.86 nor golem's update.
- The user approved the update procedure as tested.

**Verdict of the Windows agent** — one of: `GO` (7.86 can ship for Windows) · `NO-GO` (say which check) · `GO WITH
RESERVE` (say what): **GO WITH RESERVE.** 7.86 installs through golem (pin hash, Cockos install, one UAC) and plays
on Windows. Reserve: the automatic rollback after a licence loss failed because REAPER did not close on WM_CLOSE,
and the card then reports `up-to-date` instead of the failure — the user is left in evaluation without being told.
Rollback (check 5) not tried.

## Sending it back

Commit **only this file** (`docs/windows-test-2026-11-27.md`), message `Windows test of REAPER 7.86: results`, and
push it **when the user says so**. If pushing is not possible, leave the file as it is: the Linux session can read it
from the Windows partition.
