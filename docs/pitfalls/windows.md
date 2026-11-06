# Windows pitfalls

Windows runs the same bridge and Lua with a different audio stack (ASIO), a different MIDI service,
different file semantics and a hidden REAPER window. Platform status: [../dev-setup.md](../dev-setup.md).
MIDI-specific Windows traps are in [midi.md](midi.md).

---

## A generic ASIO driver can lose an input

**Symptom.** A patch only sounds when the instrument is on IN 1; on IN 2 neither ASIO channel
carries it, and channel 1 carries only the other input's noise. Not a swap: an input is gone.

**Cause.** Generic ASIO wrappers (ASIO4ALL, FlexASIO…) re-wrap the Windows endpoint of a card; they
are not the card's driver and may drop a channel without reporting anything.

**Rule.** Identify the card by its USB identity (VID/PID), prefer its native ASIO driver over the
automatic choice, warn on the Audio page when a generic driver runs while the native one is
installed, and carry the input-role mapping over when the driver changes — but never inherit roles
from a different USB card or from a card left at factory defaults.

**Detect.** Meter of an ARMED input track (it shows its input even when muted) per channel, with the
instrument moved between inputs.

**Code.** `provision/desktop.py` (`KNOWN_USB_ASIO`, `GENERIC_ASIO`, `is_generic_asio`,
`native_asio_driver`, `select_asio_driver`), `bridge/desktop_audio.py` `native_driver_advice`,
`bridge/cards.py`, `bridge/inputmap.py` `inherit`.

---

## `GetInputActivityLevel` is useless while REAPER is hidden

**Symptom.** Every input channel reads −150 dB.

**Cause.** REAPER does not update input activity while its window is hidden.

**Rule.** Do not use it as a probe on the rack. Use the meter of an armed input track instead.

---

## A hung REAPER does not close politely — and a dialog is not a hang

**Symptom.** Power button, "Restart REAPER" and the launcher leave REAPER running; it has to be
killed by hand.

**Cause.** `WM_CLOSE`, the OSC save and the Lua snapshot all wait on REAPER's main thread, which is
stuck (busy-wait, see [reaper.md](reaper.md#a-relative-clock-persisted-in-the-project-freezes-reaper)).
A modal "Save?" dialog, on the other hand, keeps pumping messages.

**Rule.** Terminate REAPER only if its main window answers no message for 15 s (`WM_NULL` via
`SendMessageTimeoutW` with `SMTO_ABORTIFHUNG`); a single probe is not enough (a legitimate rebuild
holds the thread for seconds). A window that answers — including one showing a dialog — is left to
the user. Without a bridge, the launcher recognises the rack's REAPER by its command line (a project
under `sets/`).

**Code.** `provision/desktop_window.py` `reaper_hung`, `bridge/desktop_audio.py` `_reaper_hung`,
`provision/desktop.py` (`_backend_pids`, `_golem_reaper_pids`).

---

## Replacing a file fails while another process has it open

**Symptom.** A config write is lost, or a command written to the command slot raises and never
reaches REAPER.

**Cause.** On Windows `os.replace` raises `PermissionError` while another process or thread holds the
target open (neither Python nor REAPER open files with delete sharing). Lua's `os.rename` refuses an
existing destination at all.

**Rule.** Python: replace through the retrying helper (short retries, temp file removed on final
failure). Lua: remove the destination then rename, and make readers tolerate a brief absence. For
files read on the live path, avoid replacement altogether (one acknowledgement file per sequence,
garbage-collected off the live path).

**Code.** `bridge/winfs.py` `replace`, `reaper/Scripts/golem_paths.lua` `paths.replace`,
`bridge/commands.py` (`_ack_path`, `_gc_acks`).

---

## Console encodings and BOMs

**Cause.** `tasklist` emits UTF-16 without a console and ANSI with one. Data piped from PowerShell may
start with a BOM.

**Rule.** Detect the encoding from the BOM before decoding; strip a leading BOM on stdin input. A
literal BOM in code can be intentional — write it as an escape (`"﻿"`) so it survives tooling.

**Code.** `bridge/monitors.py` `_reaper_pid` (tasklist decoding), `provision/desktop.py`
(`lstrip("﻿")` on stdin).

---

## Platform tests that only monkeypatch `sys.platform`

Tests that set `sys.platform = "win32"` prove the parsing, not the machine. Do not report a Windows
feature as working from them; check it on a real Windows install. See
[tooling.md](tooling.md#a-monkeypatched-platform-proves-nothing).

---

## A snapshot that does work starves the event loop

FIXED 2026-11-03 (first manual install on a fresh Windows 11 PC).

**Symptom.** The installer says "golem did not start within 90 s"; `/api/health` times out while the
bridge process is alive at 100 % CPU; connections stay in `SYN_SENT`. golem.fm shows the rack as
"Seen never". The bridge recovers by itself only when the work stops — or never.

**Cause.** Two things together. `RigState.snapshot` called `startup_home.describe`, which reloaded and
migrated the startup preset (the factory one, `factory-chill-jazz`, on every fresh install) — and the
migration probes the sound card several times. And every `broadcast_threadsafe` (OSC, monitors,
downloads — several threads, dozens per second) queued its own `_broadcast` task: the lock only merges
requests that arrive *during* a send, and with no screen connected there is no send at all. Once a
snapshot cost more than the gap between two requests, the queue never drained. Measured with
`py-spy dump`/`record`: 97 % of the main thread in that `load_preset`.

**Rule.** A snapshot does no I/O beyond a `stat`; anything it derives is cached and keyed on what can
change it. At most one broadcast is queued from threads, and none is computed without a screen.
When the bridge stops answering, `py-spy dump --pid <uvicorn pid>` before restarting tells which.

**Code.** `bridge/startup_home.py` `_missing_cached`, `bridge/app.py` `_broadcast` /
`broadcast_threadsafe`, `tests/test_bridge_saturation.py`.

---

## TONE3000 downloads refused with 403 "error code: 1010"

FIXED 2026-11-03.

**Symptom.** Factory captures fail with `err403` on Windows only, after minutes of retries.

**Cause.** Cloudflare in front of TONE3000 bans the `Python-urllib` User-Agent on
`/api/v1/models/<id>/download` from that machine (the same call passed from Linux). The download helper
treated every 403 as rate limiting and retried five times with growing pauses.

**Rule.** Every TONE3000 request carries an honest `golem (+https://golem.fm)` User-Agent — never a
browser's: it is a partner API. A 403 whose body says `error code: 1010` fails at once with that reason.

**Code.** `tools/t3k.py` `USER_AGENT` / `http_json`, `tools/build-library.py` `download`,
`tests/test_t3k_factory_download.py`.

---

## The installer started golem once per click

FIXED 2026-11-03.

**Symptom.** Several `pythonw -m provision.desktop server` processes after clicking "Sign in to
TONE3000 & download them" a few times; "golem server" message boxes hidden behind the installer.

**Rule.** `bridge_start` asks `/api/health` and launches only when nothing answers; the launcher it
starts carries `GOLEM_NO_DIALOG=1`, so `_notify` prints instead of opening a modal box nobody sees.

**Code.** `installer/platform_windows.py` and `installer/platform_macos.py` `bridge_start` /
`golem_answers`, `provision/desktop.py` `_notify`, `tests/test_installer_bridge_start.py`.
