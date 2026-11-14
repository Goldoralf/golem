# Library: Listen · Play it · Add to…

> **Status: CODED** (2026-11-15). The maintainer approved the mockup the same day: on every sound of the Library,
> "test my raw sound, and add the one I like to a patch or a song". Tried on the rig: an amp capture on the guitar
> input, a Vital preset from the MIDI keyboard with a macro turned live, Stop giving the patch back.

Related: [library-tones.md](library-tones.md), [preset-preview.md](preset-preview.md) §9, [drums-library.md](drums-library.md).

## 1. Three gestures on every page

The bottom bar of a capture's page (Amps, Pedals, Cabs, Outboard — NAM and IR units), a keys sound's page (the
instruments stand, the E-Piano page, a Vital preset) and a drum kit's page (`app/library-actions.js`):

| | |
|---|---|
| **Listen** | the rendered demo, a reference phrase — nothing to plug in |
| **Play it** | your instrument on the **raw** sound |
| **Add to…** | where to put it: the patch you are editing, a new patch, a patch or a song (and its lane) |

## 2. Play it

`POST /api/library/try {item}` (`bridge/try_sound.py`), `item` = `{capture, model}` · `{sound}` · `{kit}`:

- A **try rig of one lane** carrying only the sound — a capture becomes the block the playable rule gives it
  (`playable.block_for`: an amp, a head that gets the default cab, a pedal, a cab IR, an outboard preamp or
  compressor, an IR effect); a keys sound its instrument block; a kit a `drumkit` (or `pads`) block — bound to the
  instrument: the card's input of that role (guitar; a bass capture uses the guitar input when there is no bass one)
  or a connected MIDI controller (keys; for drums, an electronic kit, else pads, else a keyboard).
- Emitted under the id `library-try` by the path of every recall: **both engines** (REAPER and the Golem Engine)
  build it, nothing engine-specific. Nothing is written. The patch that was playing is set aside; **Stop**
  (`POST /api/library/try/stop`) recalls it (another id: a rebuild). Leaving the page stops it; any other recall
  (foot, screen) replaces it, and the page sees it.
- While trying, touching another capture or sound **swaps it in place** — compare them under your fingers.
- A Vital preset's **four macros turn live** (`POST /api/library/try/param {param, value}`: the try rig's livemap, then
  `engine.get().set_fx_param` — no rebuild).
- **No instrument, no pretending**: `POST /api/library/try/check {item}` says which instrument will play it, or why
  none can ("No keyboard is plugged in. Plug one: Play it lights up, nothing to restart."); the page polls it, so
  plugging a controller lights the button.
- Refused in a locked mode and during a take.

## 3. Add to…

A sheet with three destinations; all of them end **in the Designer, with the change as a draft** — nothing is
written until the musician saves (the project's rule: never edit a preset outside the Designer).

1. **The patch you're editing** — its lane of that role takes it.
2. **A new patch** — `POST /api/library/patch-doc {item}` gives a one-lane patch holding the sound; the Designer opens
   it as a new draft (`patchDraft`).
3. **A patch or a song** — patches of that role, or songs: a song shows its lanes of that role to pick from.

The Designer receives `{kind: 'block', role, block, lane?}` (`openInDesigner(target, null, act)`); when the target
document is loaded, `applyLibraryBlock` places the block by its nature, like the in-patch audition: an amp replaces
the first amp, a cab the first cab (or goes after the amp), a pedal or a preamp goes before the amp, a compressor
first, an IR effect last, an instrument replaces the lane's instrument. A replaced block keeps its id (scenes that
name it keep it) and its footswitch. The block's sheet opens.

A drum kit's page keeps **Use in my drum machine** (the Drum Machine block's kit, [drums-library.md](drums-library.md) §5)
beside Add to… (a drums lane's kit).

## 4. Not built

- **A new lane** in a song from Add to…: a song without a lane of that role says so ("Add one in the Designer
  first"); creating a lane needs an input choice that belongs to the Designer.
- Playing while a song plays: Play it replaces the rig, like any recall.
