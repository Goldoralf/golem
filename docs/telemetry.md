# Telemetry — what golem sends, when, and how to check it yourself

> **Status: CODED** — the complete list of what leaves a rack on its own, and the commands to see it on
> your machine. Details: [`diagnostics.md`](diagnostics.md) (reports),
> [`golemfm-protocol.md`](golemfm-protocol.md) (every call), [`connect.md`](connect.md) (presence).

golem is open source: everything below is read from the code it names. If a line here and the code
disagree, the code is what runs.

## 1. Nothing leaves an unpaired rack

Every automatic send goes to golem.fm with the token obtained when you paired the rack (Settings ▸ Connect).
**Not paired → none of the sends in §2 happens.** golem.fm never opens a connection into the rack: the
rack pushes and pulls.

## 2. What leaves on its own

| What | When | Switch | Code |
|---|---|---|---|
| **Heartbeat** | 15 s after start, every 5 min, and a few seconds after a change (preset, take, mode, card setup) | pairing | `bridge/rigstatus.py` `light()`, `push()` |
| **Usage and bug reports** | at start, at shutdown, on an incident (at most one per kind every 10 min) | "Allow this golem to send usage and bug reports to golem.fm" (ticked by default) | `bridge/diag.py` |
| **A question to « Ask golem »** | only when the musician sends one, after a one-time consent ("Stop sending" in the drawer withdraws it) | the consent in the drawer (`config/.assistant.json`) | `bridge/assistant.py` — the question, the Health facts **scrubbed** (no preset, song or person name), open incidents, block **types**, input roles, the action registry; golem.fm forwards it to its AI provider and keeps no text ([assistant.md](assistant.md) §6) |
| **Presence** (where to find the rack on the network) | 15 s after start, every 5 min, within 30 s of an address change | "Let golem.fm find this rack" (ticked by default) | `bridge/connect.py` `presence_payload()` |

### Heartbeat (`rigstatus.light`)

The full field list is in [`golemfm-protocol.md`](golemfm-protocol.md) §2. In short:

- **The machine**: golem and REAPER versions, disk, CPU/RAM/temperature gauges, xrun count, what the
  audio engine opened, `rack_id` (a salted hash of the machine id, never the id itself), and the machine
  record `{arch, cpu, cores, ram_mb, disk_gb, hostname, board}`.
- **What plays**: mode, lock, whether a take is recording, the current preset's id and **name**, the
  scene, the active setlist id.
- **What the rack can play**: installed captures (catalog id, type, family, title), keys instruments,
  drum kits, block types whose plugin is missing, catalog versions.
- **The setup**: sound cards (by name and USB id) with their input/output roles; the roster **ids** of
  the people assigned to inputs and outputs (a guest is sent as `guest: true`, no id); MIDI controllers
  and pedals by name; takes waiting for upload.

The heartbeat exists so the golem.fm pages of your rack show it. It never carries audio, files, keys,
Wi-Fi settings, or the list of paired devices.

### Usage and bug reports (`diag.WHITELIST`)

A zip built from an **allow-list**: a field not listed in `bridge/diag.py` `WHITELIST` cannot enter the
report, and a report that violates the list is not built. It carries the platform, versions, sound card
by USB id only, buffer and latency, mode kind, block **types** and a short hash of the preset (never its
name), component status, counts of captures, health, a timeline of events (recalls, scenes, stomps, chips,
xruns, errors — the bridge's and the app's own JavaScript errors (page, message, file and line, never an address) —,
each error with a short signature that is the same on every rack, incidents and how each one ended — fixed by golem, by a restart, or by the musician, with the
optional "what fixed it?" answer) and filtered logs. Every string passes a scrubber that replaces paths, tokens, private IPs,
MACs, hostname, user name, and every person, band, preset, lane, song and setlist name the rack knows.

### Presence (`connect.presence_payload`)

The rack's local URLs (`http://<lan-ip>:8770`, `http://<host>.local:8770`), public IPv6 /64 prefixes, the
current Wi-Fi name and whether the access point is up, the current band space id, `rack_id`. Untick the box
and the last presence is withdrawn.

## 3. What leaves because you asked

These only happen after a gesture of yours (or a setting you turned on):

- library and preset sync, publishing a preset, pushing patches, setlists, songs and song↔preset links
  (a link carries the preset's name: you made the link);
- backups to the golem.fm vault ("Also keep a copy on golem.fm", or `auto_push` in Settings ▸ Connect) —
  a backup containing songs never leaves ([`backups.md`](backups.md));
- uploading takes, karaoke stems requests, diagnostic reports requested from golem.fm (still governed by
  the reports box);
- an online stem-separation service, only if you configure one and start a job: the song's audio goes to
  that service ([`separation.md`](separation.md));
- downloads you start (TONE3000 captures with your own key, REAPER updates from reaper.fm, kit imports).
- **the install report**, when an install fails and you tap "Send this report to golem" on the installer's failure
  screen. It goes before any pairing, without an account. It contains the machine (system, processor, memory),
  the golem version, the install steps and their times, the failed step and its last error line (normalized), the
  checks, your choices on the installer's screens, and the last 1 MB of the install output. Your user name,
  computer name, folders, LAN addresses, password and the keys you typed are erased first
  ([`diagnostics.md`](diagnostics.md) §7.1).
- **the uninstall report** is the one exception to "after a gesture": when an **uninstall fails**, the uninstaller
  sends the same kind of report **by itself** and says so on its screen, with its code and "What is in it". A
  successful uninstall sends nothing.

## 4. Check it yourself

On the rack (or the machine running golem), with the bridge running on port 8770:

```bash
# the heartbeat exactly as it would be sent now
python3 -c "import json; from bridge import rigstatus; print(json.dumps(rigstatus.light(), indent=1))"

# the presence payload (without rack_id and session) and whether it is enabled
curl -s localhost:8770/api/connect/where

# the reports box, the current session and every package built so far (sent_at = when it left)
curl -s localhost:8770/api/diag

# build a report WITHOUT sending it, then open it
curl -s -X POST localhost:8770/api/diag/build -H 'Content-Type: application/json' -d '{"kind":"event"}'
curl -s -o report.zip localhost:8770/api/diag/<report_id>/download && unzip -l report.zip

# build one and audit it: manifest, hashes, whitelist, and a grep for the names this rack knows
./tools/check-report.py --kind boot
```

Run the Python line from the repository root. The local timeline that reports are built from is
`diag/timeline.ndjson`, one JSON event per line.

## 5. Turning things off

- **Reports**: untick the box in Settings ▸ Connect (`POST /api/diag/settings {"auto": false}`; stored in
  `config/diag.json`). Nothing is built or sent; requests from golem.fm are refused.
- **Presence**: untick "Let golem.fm find this rack" (`POST /api/connect/settings {"presence": false}`).
- **Everything**: unpair the rack in Settings ▸ Connect. The rack keeps working offline.

golem.fm keeps reports 90 days; "Delete all my reports" on golem.fm erases them from your account.
