# Library ▸ Drums: kits drawn and heard, grooves read and placed

> **Status: CODED** (2026-11-14). The maintainer approved the mockup the same day (four screens: Kits, a drum set,
> Grooves, a groove) and asked to keep "Add to my drum machine". Drawings: golem-fx `drumKit` and `padKit`
> (vendored at a9e385f). Not rendered on the rig yet beyond one kit (Blonde Bop, its four demos, 13–19 s each)
> and one groove on a kit (variation_03 on Blonde Bop at 103 BPM, 22.9 s).

Related: [drums-kit.md](drums-kit.md) (the kits themselves, the drums lane), [preset-preview.md](preset-preview.md)
(the offline render the demos use), [library-tones.md](library-tones.md) (the same idea for captures).

## 1. One Kits tab

The Drums and Kits tabs are one tab, **Kits** (`#/library/drums/drums` still lands there): drum sets (avldrums,
drumgizmo, sfz) and pad kits (RS5K), as **cards drawn by golem-fx**, in sections by origin — *Drum sets · ships with
golem*, *Drum sets · yours*, *Pads · ships with golem*, *Pads · yours* — rather than a badge. Chips filter All /
Drum sets / Pads; the list scrolls. `+ Import` offers a drum set (the folder, USB key or URL sheet, this golem only)
or a pad kit (`.golemkit`).

The drawing type comes from the kit (`drum_preview.kit_type`): its style hint first (metal, jazz), then its name
(Pearl, Zeppelin → vintage; Hybrid → hybrid; 808/909/electronic → electronic), otherwise rock. golem-fx gives each
title its own finish, so two kits never look alike. `GET /api/drums/kits` returns each kit with `type` and `demo`.

## 2. Hearing a kit

- **Its demo**: the four drum MIDI references (`library/di-refs/drums/{rock,funk,jazz,metal}.mid`) played by the
  kit, offline: `golem_drums` loads the kit on the Drums track without playing (op `load`), `golem_preview` clones the
  track without its sequencer and plays the notes, no hardware output — the engine of the block renders
  ([preset-preview.md](preset-preview.md) §8). Stored in `library/previews/kit-<id>/<phrase>.opus` + `preview.json`.
- **The demo phrases can be changed.** Each clip records the sha256 of the phrase it played; a replaced `.mid`
  makes the kit `pending` again and the next render redoes it (the keys sounds of §9 of preset-preview.md follow the
  same rule since this lot).
- **Factory kits** render in the factory demo batch (items `kit:<id>`, after the keys sounds); **imported kits** at
  the rack's idle time, like the user's Vital presets (`sound_preview.idle_tick`).
- **A pad kit** is heard pad by pad: its samples play in the browser.
- Touching a card plays its first demo and opens its page: the large drawing, the four demos, a groove on this kit,
  delete or export, and **Use this kit** (§5).

## 3. Reading a groove

Imports come in every shape: 1, 2, 4, 8 bars, 4/4 or 6/8, played or quantized, in their library's mapping.
`grooves.analyze` reads:

| | |
|---|---|
| meter | the first time signature (4/4 when none) |
| bars | the end of track, not only the last hit: a bar that ends on a rest is still a bar |
| file tempo | the first tempo event |
| voices | hits per note; **unknown** = notes no kit plays (outside `KIT_NOTES`, the General MIDI drum pieces) |
| played | more than a quarter of the hits off the sixteenth and eighth-triplet grid (swing or a recorded performance) |
| use | `loop` · `oneshot` · `fill` · `intro` · `end`, set by hand, guessed from the name otherwise (a long played take: one-shot) |

`GET /api/grooves` carries them per groove, plus `targets` (the pieces an unknown note can become) and `pieces`.

**An unknown note** is assigned to a piece (`POST /api/groove/{id}/remap {mapping: {note: note}}`): the `.mid` is
rewritten (the engine reads it as it is when it plays), the original kept in `library/grooves/.orig/` (never served);
an empty mapping restores it. Factory grooves are never remapped. The MIDI channel does not matter: renders and the
drum machine play on channel 10.

## 4. The Grooves tab and a groove's page

Thin rows (the pattern needs the width to compare two rhythms): name, meter, bars, file tempo, played; the use;
a red badge for unknown notes; the pattern, one line per piece, cymbals on top, kick at the bottom, unknown notes in
orange. *Yours · imported* first, then *Ships with golem*; chips filter by meter, length (1, 2, 4, 8+) and use;
search, pack and genre as before. The list scrolls.

A groove's page: the pattern large with the pieces named; *From the file* (meter, length, tempo, feel, hits); *What
it is for* (the use); the unknown notes with their pieces; **Hear it on a kit** — a kit, the tempo of the file, its
half, or the patch's (`POST /api/groove/{id}/hear {kit, tempo}`, rendered offline the first time, a few seconds,
then kept: `library/previews/groove-on-kit/`, the 40 most recent; a short groove loops to 4 bars, a long one plays
once); **Add to my drum machine** (§5); download, delete.

## 5. To the Designer

"Add to my drum machine" (a groove) and "Use this kit" (a drum set) open the Designer on the patch being edited with
an action (`openInDesigner(null, 'cfg', {kind: 'drums-groove', file, list} | {kind: 'drums-kit', kit})`). When the
document is there, `applyDrumsAction` touches its **Drum Machine** block (the `gen` config), creating it when there
is none: the groove is added to *Grooves* (a fill to *Fills*), never twice; the kit becomes its *Kit*. The block's
sheet opens on the ⚙ tab. The edit auditions like any other; nothing plays until the foot starts the drum machine.

## 6. Not built

- Playing a kit live from the Library (on the drums lane, from the pads or an e-drum) — the maintainer's second step.
- Lighting the pieces of the drawing while a demo plays (`drumKit({lit})` is ready on golem-fx's side).
- Applying a remap to every groove of a pack at once.
