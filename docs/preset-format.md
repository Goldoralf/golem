# Preset document format (lanes v2)

> **Status: REFERENCE — describes the code.** This page is derived from `bridge/preset_view.py`,
> `bridge/store.py`, `bridge/scene_bake.py`, `bridge/rig.py`, `bridge/compile_rig.py`,
> `bridge/lane_apply.py`, `bridge/patches.py` and `bridge/preset_export.py`. When the code and this
> page disagree, one of them is wrong: say so, do not settle it silently.
> The **legacy** shape (`guitar{pre,split,post}` / `voice` / `keys`) is still *read* (§7) but is not the current
> model — older notes that describe it are outdated.

## 1. Overview

| Word | What it is |
|---|---|
| **Preset** (a "song" in the UI) | One JSON document: N **lanes** + a table of **scenes** + a `config` holding the service blocks. `presets/<id>.json`. |
| **Lane** | One instrument input (guitar, bass, voice, keys, drums…) and its signal chain `{pre, split, post}`. A lane is mounted on one physical input. |
| **Block** | One brick in a chain (`{id, type, params, …}`); `type` is a key of `library/catalog/effects.json`. |
| **Scene** | A full **state** of the preset (which blocks are on, knob overrides, branch mutes, lane levels/mutes). Not a diff from the previous scene. |
| **Lane state** | A named slice of a scene for one lane (`lanes[].states[]`), pointed to by `scene.lanes[<lane>].state`. |
| **Patch** | One musician's sound, reusable between songs (`library/patches/<id>.json`). Copied into a lane when assigned; never linked. Can be played as a preset under id `patch:<id>`. |

**Where files live**

| Path | Content | In Git? |
|---|---|---|
| `presets/<id>.json` | the user's presets | no (local state) |
| `presets/.sandbox.json` | the Designer's edit buffer `{preset: …}` | no |
| `presets/.karaoke.json` | volatile karaoke preset | no |
| `library/patches/<id>.json` | patches | no |
| `library/factory/presets/*.json`, `library/factory/patches/*.json` | factory seeds, copied once into the live folders at startup if missing (`bridge/factory.py`, never overwrites) | yes |

Files starting with `.` in `presets/` are never listed as presets (`store.load_presets`).

**Ids.** `id` is the file stem, produced by `store._safe_id` (NFKD transliteration, lowercase, spaces → `-`,
only `[a-z0-9_-]`). Reserved ids, resolved by `store.load_preset` without a `presets/<id>.json` file:

| Id | Served from | Save |
|---|---|---|
| `sandbox-try` (`store.SANDBOX_TRY_ID`) | `presets/.sandbox.json` (a patch being tried) | refused by `POST /api/preset` (also `nouveau-preset`) |
| `karaoke` (`store.KARAOKE_ID`) | `presets/.karaoke.json` | written by `bridge/karaoke.py` only |
| `patch:<id>` | the Designer draft if it edits that patch, else `patches.as_preset(library/patches/<id>.json)` | refused: a patch saves as a patch |

**One funnel.** Every load and every save goes through `store.migrate_config(p)` =
`preset_view.migrate(p, imap)` (pure, shared byte-for-byte with golem.fm) + hydration of the machine
singletons (Rec/Click/Compo). It is idempotent and mutates the document in place. `GET /api/preset/<id>`
returns the migrated document, not the raw file.

## 2. Top-level fields

A v2 document is recognised by `preset_view.is_v2`: `lanes_v == 2` **and** `lanes` is a list.

| Key | Type | Req. | Meaning | Read by |
|---|---|---|---|---|
| `id` | string | yes | slug; forced to `_safe_id(id or name)` on save | `routes_content.save_preset` |
| `name` | string | yes | display name | everywhere |
| `lanes_v` | `2` | yes | "the `lanes` list is the truth" | `preset_view.is_v2` |
| `lanes` | Lane[] | yes | the instrument lanes (§3) | `preset_view.lanes_of` |
| `scenes` | Scene[] | yes | scene table, A…H (§5) | `scene_bake._scene`, `preset_view._foot_summary` |
| `config` | object | written by migration | service lanes `gen` / `rec` / `arr` (§6) | `preset_view.migrate`, `_config_blocks`, `_arr_blocks` |
| `bpm` | number | no | tempo | summary, click, arrangement, standards |
| `style` / `styles` | string / string[] | no | genre **families** (0–2); `style` = `styles[0]`; normalised by `genres.migrate_styles` | summary, golem.fm |
| `exp1` | `{block, param, min, max}` \| null | no | target of the expression pedal in the **volume** role; absent → first `volume` block, `gain` −60…0 | `app._set_exp_vol_from` |
| `exp2` | same | no | target of the pedal in the **block** role; absent or orphan → first `wah*`/`autowah` block, `wah` 0…1; else nothing (or "Loop level" in looper presets) | `app._set_exp_blk_from` |
| `colors` / `anims` | `{scene id or switch number: value}` | no | /live tile look; cosmetic, excluded from the sound fingerprint | `preset_view.preset_summary`, `preset_export.fingerprint` |
| `backing` | `{songs: [{slug, title, artist, duration_sec}]}` | no | backing tracks played with the preset | `backing.py`, summary |
| `tags` | string[] | no | free tags | summary |
| `artist` | string | no | shown in lists | summary |
| `preview` | object | no | per-scene demo clips (not a block) | summary, export |
| `perf_foot` / `tuner_foot` | int | no | legacy system switches (performance REC, tuner), still honoured by the foot handler | `app.py` foot handler |
| `looper` | `{enabled, loops}` | no | legacy looper flag; the current form is a `looper` block in `config.gen` | `rig.looper_enabled`, `rig.looper_loops` |
| `origin` | string | no | provenance (e.g. `golem.fm`) | informational |
| `factory` | bool | no | set by `factory.mark` on factory items in `/api/presets` | `backup.py` |
| `kind`, `__patch` | `"patch"`, marker | no | only on a patch played as a preset (`patches.as_preset`) | Designer, `store._load_patch_preset` |

**Mirrors (do not author).** For lanes whose id is literally `guitar`, `voice` or `keys`,
`preset_view._mirror_legacy` regenerates the legacy keys `guitar`, `voice`, `keys`, `in`, `out`, `names`
from the lanes at every load/save, and they are saved with the file. Lanes with modern ids (`guitar-1`)
get no mirror. Readers must use `lanes`.

## 3. Lanes

### 3.1 Stored fields

| Key | Meaning |
|---|---|
| `id` | stable lane id (`guitar-1`, `bass-1`, `keys-1`…); default `ln-<n>`. Never renamed. |
| `role` | instrument: `guitar` `bass` `voice` `keys` `drums` `pads` `keys-pads` `line`. Overridden by `in_role` when the bound input exists on the card. |
| `name` | display name (default `Lane <n>`) |
| `in_role` + `in_nth` | **binding by name**: "Guitar 2" = (`guitar`, 2). Resolved against the card's input map at every load; the physical number follows the card. |
| `in_sel` | physical input: `"1"`, `"3-4"` (stereo pair), `"usb"`/`"usbN"` (MIDI), `"NONE"` (disabled). Used when there is no name binding. `"—"` = bound by name and the card lacks that input. |
| `out_sel` | `"1"`, `"2"`, `"1-2"` (default), `"NONE"` |
| `midi` | true for a controller lane (also forced by a MIDI role or a `usb*` input) |
| `chain` | `{pre: Block[], split: Split \| null, post: Block[]}` |
| `states` | named lane states (§5.3) |
| `patch_from` | `{id, name}` of the patch this lane was copied from (display only) |
| `drumset`, `drumset_module`, `element` | multi-lane drum kit grouping (opaque to the engine) |

### 3.2 Derived fields (cache, recomputed)

`preset_view._norm_lane` rebuilds every lane at each load/save and the result is written back:
`key`, `input` (physical number, MIDI lanes start at 3 on a 2-input card, 101 otherwise), `out`
(**rank** of the lane, not an output — `out_sel` is the routing), `disabled` (`in_sel` or `out_sel` is
`NONE`), `stereo`, `level_key`, `in_name`, `on_card` (false = the input does not exist on this card: the
lane is not mounted and the reason is reported in `unmounted`).

⚠ `_norm_lane` builds the lane from the fields listed above **only**: any other key put on a lane
(`level`, `mute`, `bind_error`, …) is dropped at the next load.

### 3.3 Split

```json
"split": { "mode": "merge", "gain": -3,
           "branches": [ { "id": "gtr-a", "blocks": [ … ] },
                         { "id": "gtr-b", "blocks": [ … ], "out": "2" } ] }
```

- `mode: "merge"` — branches are summed (folder track, `gain` dB, **default −3** when absent:
  `rig.MERGE_GAIN_DEFAULT`), then `post` runs, then the lane's `out_sel`. `gain` is one value applied
  to the **sum** (the `#merge` folder's volume, `rig._path_tracks` `merge_gain`), whatever the number of
  branches; the summing itself is unweighted. The relative level of a branch is set **inside** the
  branch (a `volume` block, an amp's output), never in `split`.
- `mode: "fanout"` — each branch goes to its own `out` (`"1"`, `"2"`, `"1-2"`); the split ends the
  path, **`post` is ignored**. Several branches (or lanes) may target the same output: they sum.
  ⚠ The live compile (`compile_rig.plan_preset`) calls `rig.build_plan(…, strict_out=False)`, so
  `rig.validate_routing` (an output channel beyond the card's count → `RigError`) does **not** run on a
  recall: an out-of-card branch output is not refused there.
- A split without `mode` coming from outside is completed by `patches.normalize_patch`: merge if there is
  a `post`, else fanout.
- **Branch count.** The engine (`rig._validate_path`, `_path_tracks`) accepts any N ≥ 2 and **rejects a
  split with fewer than 2 branches** for the whole preset (`RigError`). The Designer draws and creates at
  most 2 (`app/page-designer.js` `addBranch`) and removes the split when one branch is left. Documents
  from golem.fm may carry 3+; they play.
- A branch may carry a base `mute: true`. Branch ids must be unique **across lanes**
  (`store.duplicate_branch_ids`, 409 on save): scene branch mutes are looked up flat.

### 3.4 Mounting rules (`scene_bake.to_paths_preset`)

A lane is **not** mounted when: it is `disabled`; it is vetoed by the current mode
(`recall.input_veto`, by role); `on_card` is false; or another lane uses the same physical input — then
only the lane with **the most blocks** is mounted (ties: first in order), the other is reported in
`unmounted`. An empty v2 lane is a passthrough (a checked input is played); an empty *legacy* voice/keys
chain is not mounted.

## 4. Blocks

```json
{ "id": "ts", "type": "pedal-nam", "ref": "36827", "model": "381612",
  "params": { "input": 0, "output": -2 }, "bypass": false, "foot": 7,
  "label": "Ibanez TS9 Tube Screamer", "variant": "tube-screamer" }
```

| Key | Meaning |
|---|---|
| `id` | **unique across the whole preset** (all lanes and config): scenes, cues and EXP address blocks by id, flat. Duplicates → 409 on save (`store.duplicate_block_ids`). Missing ids are assigned at compile (`rig._assign_ids`: `type`, `type2`…) but then scenes cannot address them. |
| `type` | key in `effects.json` `effects[].type` (73 types). Defines the plugin (`plugin`), engine (`plugin`, `midi`, `mode`, `virtual`, `rs5k`, `sfizz`…), params with `id/min/max/default/map`. |
| `params` | `{param id: value}`. Absent params are **not written** to the plugin (it keeps its own default) — except types marked `defaults: "compile"` in the catalog. Out-of-range numbers are clamped at compile (`compile_rig._clamp_params`). |
| `bypass` | base state; absent = on |
| `foot` | FCB switch. 6–10 = stomp row (one switch may hold several blocks, any lane). 1–5 = scene row, only for blocks whose type has `foot_scene_claim` (tuner, rec, click, whammy-dt, backing…). |
| `ref`, `model` | capture identity (below) |
| `label`, `variant` | display name of a named amp/pedal (shown instead of the capture title) |

**Captures.** Six types load a file: `amp` (head+cab capture, `.nam`), `amp-nam` (head, `.nam`), `cab`
(IR, `.wav`/`.flac`), `pedal-nam`, `preamp-nam`, `comp-nam` (`.nam`) — `rig.CAPTURE_TYPES` /
`rig.CAPTURE_EXT`. `ref` is the **catalog id** (`"36827"`); the pack uid form `"t3k:36827"` and a
path-like `"…/36827"` are also resolved (`resolver._resolve`), the catalog id is canonical. `model` pins
one capture inside the pack; absent = the pack's first model. At compile:
- no `ref`, or a file that does not resolve / is missing on disk → the block is **removed from the rig**
  with a warning (the document keeps it);
- a file of the wrong kind (a `.nam` on a `cab`, an A2 capture on a NAM engine that cannot read it) →
  the block is **bypassed** and marked `_wrong_kind`;
- a branch emptied this way is muted (unless every branch was emptied: one stays open);
- an `amp-nam` with no `cab` downstream in its path gets a default IR fused in; an `amp` (or a capture
  declared `gear: amp-cab`) never does.

Other blocks reference their asset by a param: `vital` → `params.preset`, `pads`/`drums`/`drumkit` →
`params.kit`, `piano` → `params.sfz`, `ep` → `params.bank`, `sample` → `params.samples[]`.

**Quarantine.** A type with a `quarantine` reason in `effects.json` (`pitch`, `delay-echo`, `detune`)
stays in the document but is dropped from every compile with a warning (`rig._drop_quarantined`); a
`vst-host` block whose `plugin` matches a quarantined plugin is dropped the same way.

**System block.** On save, `store.ensure_volume` adds one `{"type": "volume", "id": "volume-sys"}` to the
guitar lane if no lane has a `volume` block (end of `post` with a merge split, else end of `pre`). It is
the default target of `exp1`.

**Service types** (`looper`, `backing-track`, `sample`, `drums`, `standard`, `rec`, `click`, `compo`,
`arrangement`) do not belong in lanes: the migration moves any found in a chain to `config` (§6).
`preview` blocks are deleted.

## 5. Scenes

```json
{ "id": "B", "name": "Solo",
  "blocks":   { "ts": true, "dly": true, "reverb-room": false },
  "params":   { "dly": { "mix": 30 } },
  "branches": { "gtr-b": { "mute": true } },
  "lanes":    { "guitar-1": { "state": "st-guitar-1-B", "level": 3 },
                "voice-1":  { "state": "st-voice-1-B", "mute": true } },
  "whammy":   { "mode": "…" } }
```

### 5.1 Ids and count

Scene ids are **positions**: `A`, `B`, … `H` (`SCENE_IDS`, max 8). The Designer renumbers on every
edit/load (`designer-model.renumberScenes`); `patches.normalize_patch` fills missing ids by position.
Lane state ids embed the scene id (`st-<lane>-<scene>`).

### 5.2 Baking a scene (exact order)

The live engine bakes with `scene_bake.to_paths_preset(preset, scene_id, union=True)`. Unknown
`scene_id` → first scene. For each block (`scene_bake._bake_block`):

1. **On/off** — first match wins:
   1. `scene.blocks[<block id>]` → `bypass = not value`;
   2. else `scene.blocks[<block type>]` ("stomp semantics": applies to every block of that type, any lane);
   3. else the block's own `bypass` (absent = on).
2. **Knobs** — `params = {**block.params, **scene.params[<block id>]}` (by id only; type keys are not read).
3. **A scene is a state** — every param that *any* scene overrides for this block
   (`scene_bake.touched_params`) is written in *every* scene: the scene value, else the block's base
   value, else the catalog `default`. Params never overridden anywhere are not written.

Per lane (`_lane_path`):
- **Level** — `scene.lanes[<lane id>].level` (dB); else, **only for a lane whose id is `guitar`**, the
  legacy `scene.levels.guitar`. `levels.voice`/`levels.keys` are never applied.
- **Lane mute** — `scene.lanes[<lane id>].mute === true` → level −150 dB (not removed: same topology in
  every scene, no rebuild).
- **Branch mute** — `scene.branches[<branch id>].mute`, else the branch's base `mute`. In union mode all
  branches stay built and the mute is a track mute.

Scene-level extras: `whammy: {mode}` arms the Whammy DT on recall; `voice` (bool) sets `state.voice_on`.

⚠ A `null` value in `scene.blocks` means **off** to the bake (`not None`) but **on** to the summary and
the foot LEDs (`_block_on_in_scene` tests `is not False`). Write `true`/`false` only.

### 5.3 Lane states

`lanes[].states[]` = `{id, name, implicit?, blocks, params, branches}` — the slice of a scene that
belongs to one lane (ids of its blocks, its block **types**, its branch ids:
`preset_view.scene_lane_slice`). Each scene points one state per lane in `scene.lanes[<lane>].state`.

The **flat scene table stays what the bake reads**; states are reconciled with it at every load/save
(`ensure_lane_states`):
- a scene without a valid pointer gets an `implicit` state copied from its own slice, named after the
  scene;
- a state shared by several scenes: if the scenes that differ from the state all agree, their version
  becomes the state and is copied to every pointing scene; if they disagree, the state wins;
- implicit states no scene points to are deleted; explicit ones (from a patch, or named by the user) stay.

`assign_lane_state(p, lane, scene, state)` points a state and rewrites the scene's slice.
`lane_apply` replaces a lane (chain + states) across a setlist by role, keeping each scene's state by
**name** and each switch by block id, then type.

### 5.4 The two lives of `scene.lanes`

`scene.lanes[k]` is a legacy **branch mute** (moved to `branches`) when it has `mute` and neither `state`
nor `level`, and `k` is not a lane id (`is_legacy_branch_mute`). Otherwise it is a lane entry. Only
write `branches` for branches and `lanes` for lanes.

## 6. Service lanes in `config`

```json
"config": {
  "gen": { "blocks": [ looper | backing-track | sample | drums | standard ], "out": "1-2" },
  "rec": { "blocks": [ rec-global, click-global, compo-global ], "click_out": "1-2" },
  "arr": { "blocks": [ { "id": "arrangement", "type": "arrangement", "params": { "advance": "bars", "sections": [] } } ] }
}
```

The migration always creates the three lanes and the permanent blocks: `rec` (`rec-global`), `click`
(`click-global`, **created bypassed** — an active Click plays the metronome), `compo` (`compo-global`),
and `arrangement`. Singletons:

| Block | Settings live in | What the preset keeps |
|---|---|---|
| `rec` | `config/recorder.json` | `foot`; its `params` are **replaced** at every load (`in1`, `in2`, `inN`, `usb`, `rec_mode`, `mix`, `count_in`, `transcribe`) |
| `click` | `config/click.json` | `foot`, `bypass`; `params.level/beats` overwritten from the global file; `rec.click_out` = effective output |
| `compo` | `config/compo.json` | `foot`; `params` replaced |
| `arrangement` | the preset (block) + the setlist line / song sheet (sections) | `foot`, `params.advance`; `recall.effective_preset` swaps in the line's arrangement and backing |

On save, edits to these blocks are first **extracted** into the global files
(`store.save_recorder_cfg_from`), then re-hydrated: editing Rec in one preset changes it everywhere.
`gen` blocks are per preset (`foot` gestures: tap/double/long press, `store.GESTURE_CLAIMS`).

## 7. Legacy shapes still read (never the target)

Everything below is accepted on load by the migration and normalised in memory; nothing writes these
shapes as the source of truth.

| Legacy | Becomes | Where |
|---|---|---|
| no `lanes_v`: `guitar` / `voice` / `keys` realms + `in` / `out` / `names` | lanes `guitar`, `voice`, `keys` (keys `1`, `2`, `k`) | `lanes_of` (legacy branch) |
| `guitar.chain` (linear) | `{pre: chain}` | `_rich_chain` |
| `guitar.lanes` + `guitar.merge.gain` | a merge split at the start | `_rich_chain`, `scene_bake._to_chain` |
| `voice.chain` / `keys.chain` with bare string types | blocks `{type}` | `_rich_chain` |
| a lane `chain` given as `{chain: […]}` | `{pre: […]}` | `rich_chain` |
| `scene.lanes[<branch>].mute` | `scene.branches` | `migrate_scene_branches` |
| `scene.levels.guitar` | read as the level of lane `guitar` only | `scene_bake._lane_path` |
| service blocks inside chains | moved to `config.gen/rec/arr` | `migrate` |
| flat `style` values (djent, …) | genre families | `genres.migrate_styles` |
| `preset.looper.enabled/loops` | still honoured if no `looper` block | `rig.looper_enabled` |
| dep `source: "maestrium"` | read as `"golemfm"`, never written | `preset_export.STORE_SOURCES` |

Two **one-shot file migrations** run at startup and rewrite preset files once
(`bridge/arrangement.py`): `migrate_stacks_to_starts` (rec/click/backing blocks stacked on the
arrangement's switch lose their `foot`; the song gets "When the song starts" ticks instead) and
`migrate_foot_to_rig` (the arrangement pedal moves from the setlist line to the preset's `arrangement`
block). The `show` → `gig` migration in `bridge/modes.py` concerns the current **mode**, not presets.

Legacy v1 patches (`chain` + `scenes`, no `lanes`) are played by depositing them into an empty v2
preset (`patches.as_preset`).

## 8. Export envelope

`GET /api/preset/<id>/export` (`preset_export.build_export`) — read-only preview; `POST
/api/preset/<id>/publish` builds the same envelope and uploads blobs to golem.fm.

| Key | Meaning |
|---|---|
| `schema_version` | `1` (envelope version) |
| `catalog_version` | `effects.json` `catalog_version` — bumped when block types change |
| `preset` | the **migrated** document (derived lane fields and hydrated Rec included) |
| `inputs[]` | `{lane, role, label, port}` per lane with at least one block (`port` = `in_sel`, `usb`, or `—` when not on this card) |
| `deps[]` | assets deduplicated by `sha256`: `{sha256, uid, kind, bytes, name, source, amp?, arch?, brand?, creator?, url?, factory?}`; `source` = `"t3k"` (uid `t3k:…`, pulled with the rack's TONE3000 account) or `"golemfm"` (golem.fm blob store; `"maestrium"` accepted on read) |
| `unresolved[]` | `{what: "asset", id, type, reason: "missing", ref/model \| kit \| preset \| sample \| groove}` or `{what: "block", id, type, reason: "retired"}`; absent = fully resolvable; publish refuses while assets are missing |
| `foot_context` | `{bank, slots[]}` of the active setlist where the preset is pinned; absent otherwise |
| `preview_fingerprint` | sha256[:16] of the document without `preview`, `colors`, `anims` |

Real output for `factory-blues-night`, trimmed (`…`):

```json
{
  "schema_version": 1,
  "catalog_version": 28,
  "preset": {
    "id": "factory-blues-night", "name": "Blues Night", "lanes_v": 2, "bpm": 96,
    "style": "blues", "styles": ["blues"], "factory": true,
    "lanes": [
      { "id": "guitar-1", "key": "guitar-1", "role": "guitar", "name": "Guitar 1",
        "in_role": "guitar", "in_nth": 1, "in_name": "Guitar 1", "in_sel": "2", "out_sel": "1-2", "input": 2, "out": 1,
        "midi": false, "stereo": false, "disabled": false, "on_card": true, "level_key": "guitar-1",
        "patch_from": { "id": "factory-guitar-texas-blues", "name": "Texas Blues" },
        "chain": {
          "pre": [ { "id": "gate", "type": "gate", "params": { "thresh": -62, "attack": 3, "release": 150 } } ],
          "split": { "mode": "merge", "gain": -3, "branches": [
            { "id": "lane-a", "blocks": [
              { "id": "klon", "type": "pedal-nam", "variant": "klon", "foot": 6, "label": "Klon Centaur",
                "ref": "2599", "model": "419209", "params": { "input": 0, "output": 0 } }, … ] },
            { "id": "lane-b", "blocks": [ … ] } ] },
          "post": [ { "id": "dly", "type": "delay-tape", "foot": 9, "params": { "time": "1/4", "mix": 16 } }, …,
                    { "type": "volume", "id": "volume-sys" } ] },
        "states": [ { "id": "st-guitar-1-A", "name": "Texas Rhythm",
                      "blocks": { "klon": true, "ts": false }, "params": {},
                      "branches": { "lane-b": { "mute": true } } }, … ] },
      …
    ],
    "scenes": [ { "id": "A", "name": "Theme", "blocks": { "klon": true, "ts": false, … },
                  "params": { "plexi": { "input": -12, "output": 6 } },
                  "branches": { "lane-b": { "mute": true } },
                  "lanes": { "guitar-1": { "state": "st-guitar-1-A" },
                             "guitar-2": { "state": "st-guitar-2-D", "level": -1 } } }, … ],
    "config": { "gen": { "blocks": [ { "type": "standard", "id": "standard", "foot": 10, "params": { … } } ], "out": "1-2" },
                "rec": { "blocks": [ … ], "click_out": "1-2" }, "arr": { "blocks": [ … ] } },
    "colors": { "A": "#2f6bff", … }, "anims": { "A": "ripple", … }
  },
  "inputs": [ { "lane": "guitar-1", "role": "guitar", "label": "Guitar 1", "port": "2" },
              { "lane": "guitar-2", "role": "guitar", "label": "Guitar 2", "port": "—" },
              { "lane": "keys-1", "role": "keys", "label": "Keys", "port": "usb" }, … ],
  "deps": [ { "sha256": "3ca89ed7…", "uid": "t3k:2599", "kind": "pedal", "bytes": 295893,
              "name": "KLON 2", "source": "t3k", "amp": "Klon Centaur", "arch": "2", "brand": "Klon",
              "creator": "seanashe", "url": "https://www.tone3000.com/tones/klon-centaur-silver-2599" }, … ],
  "preview_fingerprint": "e762a030795221b7",
  "foot_context": { "bank": "factory", "slots": [1] }
}
```

## 9. A minimal valid preset

Accepted by the save path (`POST /api/preset`: `save_recorder_cfg_from` → `migrate_config` →
`ensure_volume` → duplicate block/branch id checks) and by the engine (`to_paths_preset(…, union=True)`
→ `rig.normalize`: ≥ 2 branches per split, a path `out`, unique block ids). Checked by running
`preset_view.migrate`, `scene_bake.to_paths_preset` and `rig.normalize` on it.

```json
{
  "id": "my-song",
  "name": "My Song",
  "lanes_v": 2,
  "bpm": 120,
  "styles": ["rock"],
  "lanes": [
    { "id": "guitar-1", "role": "guitar", "name": "Guitar",
      "in_role": "guitar", "in_nth": 1, "out_sel": "1-2",
      "chain": {
        "pre": [ { "id": "gate", "type": "gate", "params": { "thresh": -60 } },
                 { "id": "ts", "type": "pedal-nam", "ref": "36827", "foot": 6, "bypass": true } ],
        "split": { "mode": "merge", "gain": -3, "branches": [
          { "id": "gtr-a", "blocks": [ { "id": "plexi", "type": "amp", "ref": "65578" } ] },
          { "id": "gtr-b", "blocks": [ { "id": "ac30", "type": "amp", "ref": "2696" } ] } ] },
        "post": [ { "id": "dly", "type": "delay-tape", "foot": 7, "params": { "mix": 18 } },
                  { "id": "verb", "type": "reverb-room", "params": { "mix": 14 } } ] } }
  ],
  "scenes": [
    { "id": "A", "name": "Verse", "blocks": { "ts": false, "dly": false },
      "branches": { "gtr-b": { "mute": true } } },
    { "id": "B", "name": "Solo", "blocks": { "ts": true, "dly": true },
      "params": { "dly": { "mix": 30 } }, "lanes": { "guitar-1": { "level": 3 } } }
  ]
}
```

After the first load or save the file also carries: the derived lane fields (§3.2), `states`
`st-guitar-1-A` / `st-guitar-1-B` with `scene.lanes["guitar-1"].state` pointers, `config` with
`rec-global`, `click-global` (bypassed), `compo-global` and `arrangement`, and `volume-sys` at the end of
`post`. Baked, scene A plays with `dly.mix = 18` (the base value is re-written because scene B touches
`mix`) and branch `gtr-b` muted; scene B plays `mix = 30` at +3 dB. Switches 6 and 7 are lit in B only.
