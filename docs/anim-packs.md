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

## 8. Not built

- Uninstalling from the UI (the route exists, no button calls it).
- Previewing a pack before installation (golem.fm side).
