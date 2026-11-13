# Glyphs, golem FX and the pedal view in the Designer

> **Status: CODED** (2026-11-13). Validated by the maintainer on the mockups, built on golem-fx's visuals
> (`golem-fx/visuals/`, copied at 4d16160 by `tools/sync-golem-visuals.py`).

Related: [ardour-plan.md](ardour-plan.md) (golem-fx effects on the Golem Engine), [blocks-doctrine.md](blocks-doctrine.md),
[block-status.md](block-status.md).

## 1. What was decided

| Where | Decision |
|---|---|
| **Glyphs** | golem-fx's SVG set (one per catalogue type, 24 × 24, stroked in `currentColor`) replaces the Unicode `glyph` of the catalogue everywhere a block is drawn. The Unicode character stays as the fallback. It removes today's duplicates (`∿` eq / tremolo / vibrato, `≈` chorus / stretch, `△` both boosts). |
| **Designer chain** | The UX and the look of `/designer` do not change: only the glyphs are swapped, and each glyph keeps its block's category colour. |
| **golem FX blocks** | Marked by a **clay fill**: a warm background on the tile. The border and the glyph keep the category colour. No `g_` badge on the tile. The clay is the material of golem-fx's pedals, so the same cue holds in both views. |
| **Add block drawer** | **Rows** (mockup B; the tile grid, mockup A, is not used): glyph, name, maker. golem FX in their own framed column (orange, "testing"), the other plugins next to it. |
| **Add block drawer, analog** | A **Blocks / Pedals** switch in the drawer's head. Pedals shows the same blocks as a shelf of pedals: golem FX (clay), then the other plugins (enamel). |
| **Designer, analog** | A secondary **pedalboard view** of the chain. It is switched from the top menu `⋯` ("View: Blocks · Pedals"), not by a new button: the Designer has enough. |

**Captures on the pedalboard** (decided 2026-11-13, after comparing both on Modern Metal): an `amp-nam` block, with
its cab, is drawn as an **amp** (head + cab, two side by side for a split): it is the heart of the tone, and a pedal
would read as one more overdrive. golem-fx's NAM "Specimen" pedals stay for what really is a pedal or a stage:
`pedal-nam`, `preamp-nam`, `comp-nam`. The amp-as-pedal form (one compact row) is kept for a possible `/live`
pedalboard view, where room matters more; it would need a label other than "NAM · preamp".

## 2. The pedal view: what it edits

No second settings grid. The pedal view edits through the existing model:

- **tap a pedal**: on / off in the current scene (what a tile's dot does today);
- **long press**: opens the block's existing sheet (Settings, Presets, MIDI assign);
- **knobs drawn on a pedal** show the real values and do not turn: at 1024 × 600, under a finger, they are too small;
- **adding, moving or removing a block** stays in the Blocks view.

## 3. What was open, and how it closed

1. ~~**Two amps.**~~ Done in golem-fx 4d16160. `GolemStage.render` takes `{split: {mode, gain, branches}}`: a SPLIT
   box, one taped strip per branch (A, B…), the stacks side by side, a MERGE box with its gain; a muted branch is
   drawn off ("B · MUTED"). `GolemStage.fromGolem(lane.chain, laneState)` reads golem's lanes-v2 chain and a scene
   state directly. A drawn block carries its chain path in `data-idx` ("3.1.0" = split item 3, branch 1, block 0);
   a branch strip carries `data-branch`, so a tap on it can mute the branch.
2. ~~**Every block appears.**~~ Done in golem-fx 4d16160: nothing is filtered, an unknown type falls back to a grey
   enamel pedal, and MIDI blocks look like hardware (a DIN socket and a MIDI stamp). `whammy-dt` is an enamel treadle.
   The two 5150 heads read the same: fixed in golem's catalogue (v42, aliases `peavey 5150` / `5150 ii` on the
   Peavey 6505, `5150 iii` on the EVH), and the app draws with golem's longest-keyword rule.
3. ~~**Fonts.**~~ Vendored (latin subset, OFL licences next to them), `tools/sync-golem-visuals.py --fonts`.
4. ~~**Archetypes.**~~ The pedal or amp family of a `pedal-nam` / `amp-nam` block comes from its capture's label
   through golem's catalogue (pedals, amps, cabs from `/api/effects`), not golem-fx's snapshot.
5. **`/live`.** Decided (mockup L1): an option of the view menu, "Pedals on the stomps": each stomp tile keeps its
   frame, number and ON/OFF and shows its pedal. Not the default.

## 4. Where it lives (code)

| What | Where |
|---|---|
| Glyphs | `app/glyphs.js` (generated). `designer-model.js` serves them through `ICON` (a proxy: a new SVG node per read, the Unicode glyph as fallback; `glyph(type)`, `glyphText(type)`). CSS `svg.glyph` in `style.css` and `style-m.css` |
| golem FX set | `/api/effects` → `golem_fx`: the types the **active** engine plays through golem-fx (`rig._engine_safe_types`; empty under REAPER) → `GOLEM_FX` in `designer-model.js` |
| Clay fill | `.tile.gfx` (`page-designer.js`, `style.css`) |
| Add block rows and shelf | `designer-drawer.js` (`bView`), pure helpers `drawer-rows.mjs` (maker of a plugin, split golem FX / others); view kept in `localStorage` `golem.drawer.view`. A category without golem FX takes the full width |
| Renderers | `app/golem-visuals.js` loads `app/vendor/golem-visuals/*` on demand, swaps in golem's catalogue archetypes and its longest-keyword rule, and draws a golem-fx (clay) pedal only where the active engine plays it through golem-fx (enamel otherwise) |
| Pedal view | `designer-pedalview.js` (`PedalView`, `refOfPath`: the renderer's `data-idx` path back to a Designer ref); `⋯ ▸ View: Blocks · Pedals`, kept in `localStorage` `golem.designer.view` |
| `/live` pedals | `live-tools.js` view menu ▸ "Pedals on the stomps" (`localStorage` `golem.live.pedals`, this screen only); `page-live.js` draws the pedal of the switch's first block |

