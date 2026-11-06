# Audit 2026-10-10 — input assignment, from the sound card to patches and presets

> **Status: CODED** — incident report: how lanes are bound to sound-card inputs, the defects found when a card had
> its inputs in the opposite order (IN 1 = voice mic, IN 2 = guitar), and their fixes; §5 lists points left open.

Trigger: an evening lost on a patch where the screen, the engine and the plugins disagreed on which input played,
on Windows. Three independent reviews (Designer, bridge, Linux/macOS) were crossed with the measured symptoms.
Background: [`input-map.md`](input-map.md), [`preset-format.md`](preset-format.md) §3.

## 1. The chain

```
card (driver)  ──►  config/inputmaps/<card>.json      inputs {ch, role, nth, name, person}, USB ports
                    (inputmap.current(), seeded by _seed)
                             │
  Designer ◄── GET /api/inputmap[?card=<mode>]  (same_as_live: the mode's card IS the connected card)
     │  a lane = {in_sel "2", in_role "guitar", in_nth 1, in_name "Guitar 1", role, name}
     ▼
  preset / patch (file, or draft in .sandbox.json)
     │
  preset_view._norm_lane: the BINDING (in_role, in_nth) wins over the number; resolved on the current card;
     │  absent → lane not mounted (on_card false), never a fallback to the raw number
     ▼
  scene_bake.to_paths_preset: one path per mounted lane; ONE lane per input (_one_lane_per_input)
     ▼
  golem_rig.lua: one "Sandbox #Input N" track per input, I_RECINPUT = N-1 (mono) / 1024+N-1 (pair)
```

The input number means the same on all three OSes (REAPER record input index). What differs per OS is the card
**name**, hence the input-map **file** (§5.1).

## 2. What broke, in the order it showed

| Symptom | Cause | Fix |
|---|---|---|
| a new guitar patch landed on IN 1 | "＋ New" started from a frozen blank bench (guitar "1", voice "2") | `seatPatchLane` (`app/designer-model.js`) |
| screen says IN 2, engine plays IN 1 | lane bound to "Voice 1" (set from the mode's Linux card); the screen showed the number, the engine followed the binding | `alignBoundInputs` |
| VST "not loaded", guitar dry then silent | two lanes on IN 2 (guitar + the blank bench's empty voice lane): one track per input, the last rebuilt wins | `scene_bake._one_lane_per_input`; a new patch keeps only its own lane |
| "I can't open the VST anymore" | the displayed draft was not the one playing | opening plays first |

## 3. Further defects found by the review — fixed

**The hidden problem at creation.** The factory that reads the card (`newBlank`: one lane per input carrying an
instrument, bound by role and number) was called by nobody: "+ Add" on Presets sent `blank()` as is, "+ New patch"
did not seat the patch, and a Designer opened without a draft edited the frozen bench. On a voice-first card each
of these gestures put the guitar chain on the mic. Now **one gate** (`loadDraft`) seats every new document on the
card, wherever it comes from (`{__new: true}` for a preset, `__patch.id == null` for a patch); the mounting bench too.

| # | Where | Defect | Fix |
|---|---|---|---|
| 1 | `preset_view._norm_lane` | a v2 lane with neither input nor binding took the number from its NAME (`guitar` → "1" = the mic) | seats on the input of its role (`_first_of_role`); the legacy number is only the fallback for a card without that role |
| 2 | `preset_view` (legacy presets) | a pre-lanes preset put its guitar chain on "1" and took that input's role ("voice": wrong mode veto) | without explicit `p.in`, the input of the role; the role is read from the resolved input |
| 3 | `preset_view`, `setIn` | a bound lane's title was rewritten lowercase on each save; a guitar lane kept the title "Voice 1" after moving to IN 2; the app changed the role with the input, the bridge did not | `in_name` = the input's name on the card ("Guitar 1"); the role follows the binding on both sides; `setIn` renames a lane whose name was the old input's |
| 4 | `patches.as_preset`, `patchDraft` | two lanes of one role both bound to "Guitar 1"; the second dropped silently | k-th lane of a role → "Role k"; a card without that number → `bind_error` that says so |
| 5 | `alignBoundInputs` | realigning a draft from another card auditioned and saved it on first render ("reopening is not playing") | the realigned document is marked `quiet`: shown, neither played nor written |
| 6 | `inputmap.inherit` | a driver change inherited the roles of ANOTHER card, or of a card left at its defaults (`asio:unconfigured`, the macOS default device) | no inheritance between two different known USB ids; none from a card still equal to its seed |
| 7 | `desktop_audio`, `recall.input_veto` | `state.inputmap` (a startup copy) served binding and mode veto: after a driver change, the old driver until restart | the copy follows the driver; the veto reads the file, like `lanes_of` — one source |
| 8 | `POST /api/inputmap` | changing a role on the Soundcard page did not touch the rig until the next recall | delayed re-recall (1 s) of the current preset when REAPER runs |
| 9 | `inputmap._card_device` (macOS) | "system default devices" is not a card, yet the input map keyed on that name | keyed on the device REAPER actually opened when known (not verified on a Mac) |
| 10 | Designer lane tabs | the engine's verdict (`rig_unmounted`) was read nowhere: a green tab for an unmounted lane | orange tab + reason in its title |

Tests: `tests/test_input_binding_audit.py`, `app/designer-model.test.mjs`; `test_scene_bake` pinned on a test card
(it read the machine's card and passed by chance); `test_lanes_v2` on the new labels.

## 4. Verified correct

- `bind_input` / `_trial_preset` (patches from golem.fm): same rule, first input of the role; role absent → none +
  reason.
- `_norm_lane`: binding absent from the card → lane not mounted, never the raw number.
- `recall.scene_shape` includes `input`: an input change forces a rebuild.
- `boot_recall`: on Windows the card comes from `reaper.ini`, no race with REAPER; no legacy fallback at boot.
- `golem_rig.lua`: `sandbox_idle` only clears roots no path uses; `I_RECINPUT` correct for mono, pair and MIDI.
- `same_as_live`: `hw:V276` ↔ `asio:Universal Audio Volt` ↔ `coreaudio:Volt 276` through USB id `2b5a:0023`; the
  Designer then edits the connected card.
- A patch does not persist its binding (`_lane_doc`): it rebinds on open. A preset persists it, which makes it
  portable across OSes (the number is recomputed on the current card).

## 5. Open points

1. **One card, N files.** The same interface has one input map per OS name (`hw-V276`, `asio-Universal-Audio-Volt`,
   `coreaudio-Volt-276`) and nothing links them; they were measured with opposite roles. A preset bound to
   "Guitar 1" then changes **jack** depending on the OS. Options: seed a new OS's map from the map of the same USB
   id; one file per USB id with OS names as aliases; or keep per-OS files and say so on the Soundcard page.
2. **`rigstatus.cards_doc` can list one interface twice** (declared by modes under its Linux name, active under its
   Windows/macOS name) without merging by USB id.
3. **A card adopted on Windows/macOS is not registered with its USB id** (`cards.remember` probes on Linux), so
   `same_card` is false for it; the Volt works because `config/cards/V276.json` is versioned.
4. **MIDI and stereo pairs**: `midi_input_base` counts inputs, not channels; a card set as pairs `["1-2","3-4"]` puts
   the MIDI root on "Input 3" along with pair 3-4, and a pair "3-4" plus a mono lane "4" feed two tracks from one
   channel. No guard on either side.
5. Legacy documents the app derives itself (`lanesFromLegacy`, golem.fm documents without lanes) stay bound by
   number until the bridge corrects them on first save.
6. At boot a rig built by a previous bridge is **adopted** without rebuild: a rig built by older code stays wrong
   until the first recall.

## 6. Lesson

All five failures shared one shape: **correct data on one path, read by another.** The screen read the number, the
engine the binding; the factory could read the card, nobody called it; the engine knew a lane was unmounted, no
screen read it; the veto read a copy, the lanes the file. The remedy is never one more guard: **one source, and the
verdict shown where the user acts.**
