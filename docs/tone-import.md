# Importing sound files

> **Status: CODED (2026-10-24).** One gesture for the sounds that do not come from TONE3000: **Library ▸ Tones ▸
> + Add ▸ Import files**. Code: `bridge/tone_import.py`, route `POST /api/tones/import`, sheet in `app/page-amps.js`.
> Tests: `tests/test_tone_import.py`.

## Why

Before this, the only way to add a `.nam` received by hand (a friend's capture, a pack exported by golem on another
rack) was to write `library/catalog/tones-index.json` yourself. On 2026-10-24 such a hand edit saved the catalog in the
wrong encoding and every rig compile failed ("The rig refused this draft … can't decode byte 0x97"). The `.gcap` import
existed, but nothing for `.nam`, nothing for a `.zip`.

## What it accepts

Several files at once, one request per file (`?name=<file name>`, raw body, 512 MB at most):

| File | What happens |
|---|---|
| `.nam` | One tone, one model, under `assets/models/captures/imported/<id>/`. Nature (`gear`) from the NAM metadata `gear_type` (`amp_cab` → `amp-cab`, `pedal` → `pedal`…), `amp-cab` when absent. |
| `.gcap` | `capture_module.install` — the same as the former "Import a golem capture" entry ([`capture-module.md`](capture-module.md)). |
| `.wav` | A cab IR through `irlib.save_upload` — only when it lasts **2 s or less**. |
| `.zip` | Unpacked in memory, see below. |

Inside a `.zip`, in this order:

1. **golem catalog fragments** — any `library/catalog/*.json` holding `{"tones": [...]}` (the packs golem's plugin
   capture exports carry one). Each entry keeps its id, title, nature and model names ("HOT Amp Gain 29.9%…"); each
   model file must sit in the archive under `assets/models/` or `assets/irs/` (no `..`), and is written at that same
   path.
2. every remaining `.gcap` → installed as a module;
3. every remaining `.nam` → grouped **by folder**, one tone per folder, one model per file (`<zip name> <folder>`, or
   the zip name alone for a root or `models/` folder);
4. every remaining short `.wav` → a cab IR. Longer `.wav` files are listening A/B recordings: counted as ignored.

Anything else (README, JSON reports, pictures, those recordings) is counted as "ignored", in one line. Nothing executable is ever taken from an
archive: data only.

## What is said, never guessed

The sheet lists what was **added** and what was **left out, with its reason**:

- a **parametric** `.nam` (`HyperWaveNet`) plays only inside a `.gcap` module → left out;
- an **A2** capture (`SlimmableContainer`) on a rack whose NAM cannot read it (`rig.nam_unreadable()`) → added, with a
  warning (the resolver's `playable_twin` falls back to an A1 twin when one exists);
- a `.wav` longer than 2 s, imported on its own → "audio of N s, not an impulse response".

Re-importing the same file replaces the same entries (same ids): nothing is doubled. Imported tones are `private` —
they never sync to golem.fm by themselves.

## Who may call it

Like `/api/ir/upload`: the rack's screen and paired devices; not an unpaired device on the LAN (any POST needs a
token, `bridge/auth.py`).
