# FCB1010 + UnO2 — compile and flash from the rack

> **Status: CODED** — the rack compiles the pedalboard contract into the UnO2 chip's memory image and sends it itself (Linux and Windows over MIDI; macOS through the vendor editor), with an offline checker.

The pedalboard model (intention, descriptor, detection, LEDs) is in
[../../pedalboards.md](../../pedalboards.md). This page is about the UnO2 chip itself.

## The chain

| Step | Where |
|---|---|
| Contract, as data | `config/pedalboard/contract.json` + `config/pedalboard/devices/fcb1010-uno2.json` |
| Binary format | `tools/fcb/uno2.py` — **the format knowledge lives here** (`Setup`, `Block`, `build_binary`, `to_sysex`, `setup_length`, `BUDGET = 2032`) |
| Compile | `./tools/fcb/gen_uno2_syx.py [-c contract] [-d device] [-o dump.syx] [--bin image.bin] [--no-looper-banks]` |
| Check, without the chip | `./tools/fcb/check-uno2.py` (`--update` re-baselines the witness after an intended change) |
| Identify the chip (read-only) | `./tools/fcb/flash_uno2.py --identify` |
| Compile and show, send nothing | `./tools/fcb/flash_uno2.py --dry-run` |
| Flash | `./tools/fcb/flash_uno2.py --write` (`-p <port>`, default `$GOLEM_MIDI_PORT` or `Volt`) |
| Flash without claims (way out) | `./tools/fcb/flash_uno2.py --write --no-claims` |
| Setup as text (vendor editor) | `python3 tools/fcb/uno2_text.py` |

From the app: Settings ▸ Gear ▸ Pedalboard ▸ Set up ▸ **Load** (`POST /api/pedalboard/load`,
recipe `uno2`). The production contract uses well under the 2032-byte budget.

## Where the format comes from

It is not published. It was established by measurement: differential compilations (vary one
construct, read which bytes move), then byte-for-byte equality with the vendor compiler on thirteen
configuration variants (production, all stomps `effect`, all `trigger`, channel 1 without remote,
channel 16, one slot, no pedal, each pedal alone, inverted sweep bounds, three scenes, no stomp…).

That comparison needed third-party software and cannot live in the repository. What remains is a
**witness**, `tools/fcb/uno2-witness.json`: the digest of the bytes produced when equality was
proven. `check-uno2.py` compares against it on every run; if it moves unintentionally, find out why
**before** flashing.

## What `check-uno2.py` verifies

- the configuration compiles, fits the budget, compiles deterministically, and the SysEx dump
  decodes back (parity, checksum, announced length, marker byte);
- **no looper slot → binary unchanged**; a looper bank is currently identical to the others (loops
  are on the scene row, `looper_bank.gestures` is empty); 19 looper banks cost no more than one;
- **no claim → binary unchanged**; a bank with claimed switches only changes those switches' species,
  other banks keep five scenes; 19 claimed banks cost no more than one (shared blocks);
- looper + claim in the same bank: SW4 becomes `effect`, SW5 stays the scene (looper play all);
- the select switch is never claimed; a backing alone keeps its edges (tap / double tap / hold);
- **the chip carries the claims the current setlist asks for** (compares `presets/.uno2-flashed.json`
  with the setlist) — i.e. whether a reflash is due;
- `bridge/foot.py` has no hard-coded contract channel (it must come from the descriptor).

## Bank species, decided by the setlist

All banks come from the same contract, but the chip fixes a switch's species **per bank**. Extra
blocks are added after all others and only if a bank uses them, so without them the binary equals
the witness bit for bit.

| Bank | When | What changes |
|---|---|---|
| ordinary | always | SW1–5 `preset` (scenes: PC slot + scene CC + Note), SW6–10 `effect` or `trigger` per the contract's `gestures` (SW10 is `trigger`) |
| looper | the slot's preset has a looper block (`gen.looper_slots_from_setlist()`) | the switches in `looper_bank.gestures` go `trigger` — currently none |
| claim | the slot's preset reserves SW2–5 for an on/off block (`gen.claim_slots_from_setlist()`) | that switch goes `effect`: PC + scene CC 127 / 0, on/off LED, no Note |

`flash_uno2.py --write` writes the chip **and** `presets/.uno2-flashed.json` (`_remember_flash`:
hash, looper slots, claims) — what the rack reads to know which switches send a state. See
[pedalboards.md §7](../../pedalboards.md#7-switch-species-claims-and-leds-uno2).

## Flash dialogue

`flash_uno2.py` identifies first (universal identity request), refuses if the answer is not a UnO2,
sends the dump, reads the chip's acknowledgements (`7C` progress, `7F` done) and records the flash
only on `7F`.

- **Linux**: through the ALSA sequencer, which accepts several clients, so the bridge can keep
  running during the flash (rawmidi does not: an external `amidi` would answer "busy").
  `python-rtmidi` is not in the system Python: the script re-executes itself in the bridge's venv;
  the re-exec guard is an environment variable, not a path comparison (a venv `python` is a link to
  the system binary, so paths compare equal).
- **Windows**: `routes_system._flash_uno2_native()` replays the same dialogue **inside the bridge**,
  reusing `flash_uno2.identify` / `flash`: out through `midi_out.send_sysex` (the ~1 KB dump in one
  message), in through the foot reader's SysEx subscription (`foot.native_sysex_stream()`). A
  second process could not open ports the bridge holds (WinMM: one owner per port). If a driver
  ever refuses the send, **Use FCB UnO Control Center instead** switches to the editor path.
- **macOS**: `load_mode: "editor"` — the screen runs the descriptor's `install_desktop` phases
  instead of `install`.

### Editor path (FCB UnO Control Center)

1. links to the editor (`editor.windows` / `editor.macos` in the descriptor);
2. **Release the pedalboard** — `POST /api/pedalboard/hold {on}` closes the foot reader's input and
   the MIDI output ports (auto-release after `foot.HOLD_MAX_S`, 15 min);
3. **Copy the setup** — `GET /api/pedalboard/setup-text`;
4. **I sent it from Control Center** — `POST /api/pedalboard/flashed` writes
   `presets/.uno2-flashed.json` with the same function as the wire flash plus `source: "editor"`,
   and takes the ports back. It is the user's word, not a chip acknowledgement: the next step (the
   foot checklist) verifies it.

**One source.** The text is not written from the contract: `tools/fcb/uno2_text.py` **decompiles**
it from the same `uno2.Setup` the binary comes from (`gen_uno2_syx.build`, looper and claim banks
of the active setlist included), then **re-parses** it: it must give back the binary bit for bit and
contain ASCII only (the editor rejects anything outside Latin-1). A text that fails is not served.
If the editor refuses a line, fix `render()` **and** `parse()` in `uno2_text.py`, never the text by
hand. On Windows the sound card's MIDI ports may need the vendor driver (stated in
`install_desktop.needs`).

Foot checklist after a flash: SW1 lights scene A, SW6 toggles, SW10 answers press **and** release,
both pedals sweep; the rack's MIDI monitor shows PC slot + CC 20 + Note 0 for SW1.

## Chip facts

- **`effect` and `trigger` are exclusive.** An `effect` switch keeps a status LED but **never sends a
  release** — the reader sees two presses in a row, so anything that depends on a duration (long
  press, looper gestures) is dead on that switch. A `trigger` gives both edges but its LED does not
  stay lit. No setting gives both: it is a per-switch trade-off.
- **A data byte with its high bit set is a variable reference**, not a value. That is what allows
  `ProgChange $slot`, and it limits literal values to 0–127.
- **Variable index 0 always exists** (`MidiChannel`, built in). Declared variables start at 1;
  forgetting it shifts every reference.
- **The display numbers banks 01–19**, while the Program Change stays the slot (0–18). The app
  aligns with the chip through `quirks.display_base` (formatting only).
- **Incoming goto bank** on the remote channel (16, CC 0, `index_base: 1`) and **remote press**
  (PC `switch-1` on channel 16, firmware ≥ 1.3) are used by the rack (`pedalboard.goto_bank()`,
  `bridge/foot_leds.py`).
- **MIDI THRU is not disableable**: everything entering MIDI IN goes back out, hence the separate
  contract channel (2) and the Whammy on channel 1.
- The compiler covers only the subset golem needs. The language has more (`GotoBank`, `Wait`,
  loops, relays, SysEx, `SendPedal`, `SendTrigger`, clock); add them when a need appears.

## Files in this folder

`setup-v1.txt`, `setup-v1.1.txt`, `setup-v1.2.txt` are **bench traces, not sources**: they do not
compile (box-drawing characters outside Latin-1) and were never flashed as is. The source is the
JSON contract.
