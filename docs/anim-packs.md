# Tile animation packs

> **Status: CODED** (rack side) — how tile animations are packaged in packs of 20, stored in presets,
> installed from golem.fm and validated (`bridge/anim_packs.py`).

## 1. The rule

Tile animations (Live page tiles, arrangement sections) come in **packs of exactly 20 effects**
(`anim_packs.PACK_SIZE`).

| Pack | |
|---|---|
| **`default`** | The 20 effects shipped with golem (`anim_packs.DEFAULT`, same order as `ANIM_STYLES` in `app/designer-model.js`). Its CSS lives in `app/style.css`, not in a pack file. **Locked**: it cannot be modified, replaced or removed. Every preset can count on it, including one that came from another rack. Its first slot is `None` (no animation). |
| **Others** | Installed **only by golem.fm** (job `anim-pack-install`). The rack UI never offers "add a pack": a pack is distributed content, not a file edited on stage. |

## 2. What a preset stores

`preset.anims[key]` and `section.look.anim` hold:

- `"fire"` — an effect of the `default` pack (bare id);
- `"neon-city/flicker"` — `<pack>/<effect>` for an installed pack.

The CSS class follows: `anim-fire`, `anim-neon-city-flicker` (`designer-model.animClass`).

**A missing pack breaks nothing**: the tile loses its animation and keeps its colour. The missing pack
is visible in `GET /api/anim-packs`, and `GET /api/anim-pack/{id}/css` answers 404 (the log says why).

The golem.fm job `set-appearance` (`tones_jobs._set_appearance`) replaces `preset.colors` and `preset.anims`: display
metadata only, no engine rebuild.

## 3. On the rack

```
library/anim-packs/<id>/pack.json      # descriptor: schema, id, name, effects[20], optional palette
library/anim-packs/<id>/pack.css       # the animations, in the pack's namespace
```

| Route | |
|---|---|
| `GET /api/anim-packs` | `default` first, then the installed packs |
| `GET /api/anim-pack/{id}/css` | the CSS, **re-validated when served** |
| `POST /api/anim-packs/install` | body `{pack:{…}, css:"…"}`; 400 with `errors[]` if refused |
| `DELETE /api/anim-pack/{id}` | any pack except `default` (no UI button calls it yet) |

A pack's CSS is loaded **on demand** (`designer-model.ensurePackCss`): the app only opens a `<link>`
for packs actually displayed.

**golem.fm jobs** (see [`golemfm-protocol.md`](golemfm-protocol.md)): `anim-pack-install` carries
`pack_id`; the rack fetches `GET /api/ext/anim-packs/{id}`, which returns `{pack, css}` — exactly the
body of `POST /api/anim-packs/install` — and installs it (`tones_jobs._anim_pack_install`). The job's
result carries the `warnings[]` (§5). `anim-pack-remove` uninstalls any pack but `default`, even one the account lost access to.

## 4. Descriptor rules (`anim_packs.install`)

Everything is validated before anything is written: a half-installed pack is worse than none.

- `id`: `[a-z0-9][a-z0-9-]{1,31}`, and never `default`.
- `schema` must equal `anim_packs.SCHEMA` (1). Extra fields (for example `intensity` on an effect) pass
  through untouched into `pack.json`.
- `effects`: exactly 20, each with a valid `id` and a `name`; an optional `color` must be `#rrggbb`
  (it ends up in a `style=` attribute).
- `palette` (optional): an object whose values are `#rrggbb` colours or lists of them.

## 5. CSS validation (`anim_packs._check_css`)

CSS runs no JavaScript, but in a kiosk it can **call the network** (`url(https://…)`: a leak, and a
dependency on the connection in the middle of a show), **cover the screen** (`position:fixed`), or
inject text. The rack accepts free but bounded CSS, checked at install **and** when served:

| Rule | Why |
|---|---|
| Every selector starts with `.anim-<pack>-`; combinators `~` and `+` are refused | an animation never repaints the rest of the app or a neighbouring tile |
| `url()`: **`data:` only**; `image-set()`, `image()`, `cross-fade()`, `element()`, `src()` refused | the rack plays offline: no request when a tile renders |
| No `position:fixed/sticky` | an animation never leaves its tile |
| No `@import`, `@font-face`, `@page`, `expression()`, `javascript:` | a pack is self-contained |
| ≤ 512 KB of CSS, `data:` images included (`MAX_CSS`) | pack budget |

Implementation rules that prevent false refusals:

- Comments `/* … */` are stripped and CSS escapes decoded before any check.
- `url(` tokens are read by hand (quotes respected, parentheses counted) and the inside of a `data:` URI
  is never inspected — an SVG data URI contains `)` and `url(%23id)` that a regex would misread.
- The selector scan is **depth-aware**: the inside of `@keyframes` (`0%`, `50%`…) is not a selector; the
  inside of `@media`/`@supports` is. Declarations inside a rule body are not selector heads.

**Refuse, never sanitize**: a non-conforming pack is badly built, and naming the faulty line is more
useful than repairing it silently.

### Performance warnings (not refusals)

`_perf_warnings` lists every `@keyframes` that animates a property that repaints each frame
(`background-position`, `box-shadow`, `filter`, `width`, `top`, `margin`, `border-radius`… — `_REPAINT`).
Measured in Chrome with 24 tiles, such animations cost about 100× the main-thread time of
`transform`/`opacity`, roughly 10 % of a core — on a rack that also runs a real-time audio engine.
`install()` returns them in `warnings[]` and golem.fm shows them to the pack author; installation is not
blocked.

## 6. Images

Allowed only as `data:` URIs inside the CSS, counted in the 512 KB. An optimized SVG or a CSS gradient is
far lighter than a bitmap and animates more smoothly.

## 7. Blank tiles on /live

An empty /live tile (no scene, no stomp assigned) plays the `monster` effect of `default`, in the variant
of its number (#1 → `m1` … #10 → `m10`, `app/style.css` `.anim-monster.mN`): same background and halo,
different eyes. This is a rack rendering detail, not a pack: golem.fm only knows `monster`, and a preset
that sets `monster` on a switch gets `m1`.

## 8. The still image of each effect

> **Status: CODED on the rack 2026-11-26** (`anim_packs.check_still`, `app/anim-stills.js`, `page-live.js`). golem.fm
> validates with the same `check_still`, ported as is, and adds a still to every effect it ships (not coded yet).

When tiles are still, the Live does not draw a paused animation. A frame caught mid-cycle looks like a bug (isolated
snow dots, a stray orange smudge), and a paused animation still costs a composited layer (docs/pitfalls/ui.md). Tiles
are still on the local screen with Display set to Auto, and everywhere with Display set to Off. Each effect therefore
carries its own **still image**, drawn to be looked at without moving.

### 8.1 The field

`effects[].still` is an SVG document, as a string:

```json
{"id": "fire", "name": "Fire", "still": "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200' preserveAspectRatio='xMidYMid slice'>…</svg>"}
```

- **Transparent background.** The tile paints its own colour underneath: the preset's colour for that tile
  (`preset.colors`, `--pc`). An image that fills its whole box with an opaque colour hides the tile colour, and the
  musician's colour choice with it.
- **`currentColor` is the tile colour.** Before drawing, the rack replaces `currentColor` with the tile's `#rrggbb`.
  Draw with `currentColor` whatever should follow the tile colour, and with fixed colours what should not (the orange of
  a fire, the red of a heartbeat). The same image then works on a gold tile and on a blue one.
- **Format.** Drawn on a square `viewBox` (200 × 200 is the reference), shown with `background-size: cover`, centred.
  Live tiles range from about 2:1 (compact scenes) to 1:1. Keep what matters inside the central 200 × 120 band.
- **No motion.** `<animate>`, `<animateTransform>`, `<animateMotion>`, `<set>`, `@keyframes` and `animation` are
  refused. An animated SVG would bring back exactly the cost the still removes.
- **Self-contained.** No `<script>`, `<foreignObject>`, `on…=` attributes, `<style>` with `@import`, or `href` other
  than `#id`. In `url(…)`, only `#id` references are allowed. The rack plays offline.
- **≤ 16 KB** per image. Gradients, patterns and a few paths are enough. A bitmap embedded inside the SVG is refused,
  because it would blow the budget and blur on a large screen.

Validation is the same as for the CSS: **refuse, never sanitize**. A pack with an invalid still is refused as a whole,
and the error names the effect.

### 8.2 Packs without stills

`still` is optional in schema 1, so the packs installed before 2026-11-26 still install and still play. An effect
without a still shows **only its tile colour** when tiles are still, never a paused frame. `install()` returns one
warning per effect without a still, and golem.fm shows it to the pack author. From now on, golem.fm ships a still with
every effect, including those of packs already published.

### 8.3 The default pack

Its 19 stills (`None` has none) live in `library/catalog/anim-stills.json`, `{id: svg}`, and `GET /api/anim-packs`
serves them in `effects[].still` like any other pack's. The blank tiles' monster (§7) uses the `monster` still. Its ten
eye variants are an animation detail and are not kept when tiles are still.

### 8.4 What the Live shows when tiles are still

Settings ▸ System ▸ Display ▸ **Still tiles** (`config/display.json` `still_tiles`) offers three styles. They apply
only when tiles are still; moving tiles do not change.

| Style | Stomps and service tiles | Scenes |
|---|---|---|
| **Pedals** (default) | the golem-fx pedal of the block, at its state (LED, knobs) | the effect's still |
| **Glyphs** | the block's golem-fx glyph, large, cropped in a corner | the scene letter, large, as a watermark |
| **Textures** | the effect's still | the effect's still |

In every style, a still tile changes only on a gesture or a state change: no `--vu` level, no cycling line, no ticking
faster than the musical beat (docs/pitfalls/ui.md).

## 9. Not built

- Uninstalling from the UI (the route exists, no button calls it).
- Previewing a pack before installation (golem.fm side).
