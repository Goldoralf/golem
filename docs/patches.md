# Patches

> **Status: CODED** — a patch is one musician's sound, stored in `library/patches/`, played like a preset
> under `patch:<id>`, and copied (never linked) into songs.

Related references: [preset-format.md](preset-format.md) (the preset document a patch mirrors) ·
[setlists.md](setlists.md) (sound banks) · [modes.md](modes.md) (`foot_list`) ·
[input-map.md](input-map.md) (binding by role) · [drums-kit.md](drums-kit.md) (kit patches) ·
[golemfm-protocol.md](golemfm-protocol.md) (patch jobs) · [identity.md](identity.md) (people).

Code: `bridge/patches.py` (model), `bridge/routes_patches.py` (API), `bridge/store.py`
(`load_preset("patch:<id>")`), `bridge/tones_jobs.py` (jobs from golem.fm), `bridge/setlists.py` (sound
banks), `bridge/modes.py` (`apply_foot_list`).

---

## 1. What a patch is

**A preset is a song. A patch is the sound of one musician in it** — its lanes, its scenes, and the
settings it needs to be played alone at the foot.

- **One musician, one instrument.** Almost always one lane (guitar, bass, voice, keys). A drum kit with
  direct outputs has several lanes, still one instrument. All `lanes[].role` must equal the patch `role`
  (`patches.v2_fields` raises `a patch holds one instrument`).
- **Same shape as a preset, separate library.** A v2 patch document has the shape of a preset (`lanes`,
  `scenes`, `config`…) but lives in `library/patches/<id>.json`, never in `presets/`.
- **The rack plays a patch like a preset.** `store.load_preset("patch:<id>")` serves it; recall, foot,
  `/live` and the Companion use the same path as for any preset (§5).
- **A patch never has an arrangement.** The arrangement (scenes that change by themselves on the bar)
  is what makes a sound a song; it stays in presets. Accompaniment that plays while you change scenes
  yourself (backing, Standard grid, grooves, looper, samples) is allowed in a patch's ⚙ (§3).
- **A patch is portable.** It knows its role, never a card input: when played, its lanes bind to the
  inputs of that role on the current card (§5.2).

## 2. Document format

### 2.1 v2 (written by the rack)

```json
{
  "kind": "patch", "patch_v": 2, "lanes_v": 2,
  "id": "my-clean", "name": "My clean", "person": "<person id>|null", "role": "guitar",
  "origin": "golem.fm", "tags": ["indie"], "needs": [{"type": "amp", "ref": "…", "model": null}],

  "lanes": [{"id": "guitar-1", "role": "guitar", "name": "Guitar", "states": [...],
             "chain": {"pre": [...], "split": null, "post": [...]}}],
  "scenes": [{"id": "A", "name": "Verse", "blocks": {"b4": false}, "params": {...}, "branches": {...},
              "lanes": {"guitar-1": {"level": 0}}, "level": 0, "what": "…", "gain": "clean", "out": "mono"}],
  "config": {"gen": {"blocks": [...], "out": "1-2"}, "rec": {"blocks": [{"id": "…", "type": "rec", "foot": 9}]}},
  "exp": {...}, "exp2": {...}, "colors": {...}, "anims": [...], "backing": {...}, "bpm": 120,

  "chain": {"pre": [...], "split": null, "post": [...]},
  "deps": [...], "deps_sig": "…", "unresolved": [...]
}
```

| Field | Rule |
|---|---|
| `lanes[]` | Only what describes the sound: `id, role, name, states, midi, stereo, drumset, drumset_module, element` + `chain` (`patches._LANE_KEEP`). Never the current input/output/mount — except a kit lane, which keeps its nominal `in_sel`. |
| `scenes[]` | The preset's scenes filtered to the patch's blocks, branches and lanes (`v2_fields`). Names are kept. `what`/`gain`/`out` are descriptive fields produced by golem.fm and preserved across saves. One-lane patch: `level` repeats the lane level for v1 readers. |
| `config` | Only `gen` blocks of type `looper, sample, drums, standard, backing-track` (`PATCH_GEN_TYPES`), plus the foot switch of the global `rec`/`compo` singletons (`{id, type, foot}` only). Never arrangement, never Click. |
| `backing` | Kept only if a `backing-track` block is in `config.gen` — a backing without its block does not travel. |
| `exp*`, `colors`, `anims`, `bpm` | Copied from the bench. `bpm` is the tempo when the patch plays alone (synced delays); dropped into a song, the song's tempo wins. |
| `chain` | **Mirror** of `lanes[0].chain` for one-lane, non-kit patches, for older readers (golem.fm, older racks). Byte-identical by construction (`_lane_doc` uses the mirror shape). |
| `needs` | Captures referenced by the chain and the ⚙ (`needs_of`). |
| `deps`, `deps_sig`, `unresolved` | Dependencies in the shape of the preset export, computed by `patches.refresh_deps()` through `preset_export.build_export("patch:<id>")`, recomputed only when the patch signature (`_v2_sig`) changed. Written into the file before each catalogue push. |

`rev` and `snap` are dead keys from an abandoned revision model; `_write` drops them on the next write.

### 2.2 Shapes still read

The shape is **read, never deduced from `kind`/`patch_v`** (`patches.is_v2`: `lanes_v == 2` and a
non-empty `lanes[]`):

| Shape | Recognised by | Read as |
|---|---|---|
| v2 | `lanes_v == 2` + `lanes[]` | lanes as stored |
| v1 | `chain` (`{pre, split, post}` or `{chain: [...]}`) + `scenes` | one lane `<role>-1`, built by depositing the patch into an empty preset (`as_preset`) |
| kit v1 | `elements[]` (`{element, chain, scenes}`), role `drums` | one lane per element in a drum group (`drums-kit.md`) |

There is no migration: a v1 patch becomes v2 the next time the rack saves it (`save_patch`). A file
received from golem.fm is pushed back **as stored** — a v1 stays v1 until edited.

## 3. The patch's ⚙ (service blocks)

The Designer opens a patch with the tabs of its lanes plus ⚙, a subset of a preset's:

| Block / setting | In a patch | Why |
|---|---|---|
| Looper, Sample, Drums (grooves), Standard, Backing | yes | accompaniment: plays while you play alone |
| Expression pedals (`exp*`), switch colours and animations | yes | needed to play the patch at the foot |
| Rec, Riff (compo) | foot switch only | global singletons; settings live in `config/recorder.json`, `compo.json` |
| Click | no | global |
| Arrangement | no | the song's form |

Standard and backing stay mutually exclusive, as in a preset. **Depositing a patch into a song never
brings its ⚙** (§4.2).

## 4. Copy, never link

**A patch is autonomous. Assigning it to a song copies it. Nothing ever propagates.** The song keeps an
inline copy of the chain and scene entries; editing the song changes only the song, editing the patch
changes only the library. Both auto-save. Consequences:

- the rack **cannot** say "this patch is used in N songs" — nothing records it, deliberately (the lane
  is meant to be retouched in the song, so a provenance label would go stale);
- deleting a patch never breaks a song: the song plays its copy;
- to update several songs, deposit again and tick them (§4.2).

### 4.1 Create a patch

| Gesture | API | Function | Notes |
|---|---|---|---|
| Designer ▸ ⋯ ▸ "Save « <lane> » lane as patch" | `POST /api/patches` `{preset, lane, name?, person?, tags?, patch_id?, origin?}` | `create_from_lane` | Always a **new** patch (id suffixed `-2`, `-3`… if taken) unless `patch_id` + same `origin` designate the same patch coming back. From a song lane: the lane only, **no config**. From a patch bench (`__patch`): the whole bench and its ⚙. First tag seeded by the preset's `style`. |
| "Save the drum kit as patch" | `POST /api/patches` `{preset, drumset, name?, person?}` | `save_kit_patch` | All lanes of the drum group. |
| Auto-save in patch mode | `POST /api/patches/{id}` `{preset, lane}` or `{preset, drumset}` | `save_patch` / `save_kit_patch` | Writes v2 + mirror; no write if the v2 signature is unchanged. `lane` may be a legacy realm or a lane id of the bench. |
| Metadata | `POST /api/patches/{id}/meta` `{name?, person?, tags?}` | `update_meta` | Tags: free strings, deduplicated, ≤ 40 chars, ≤ 40 tags (`norm_tags`). The role is not a tag. |
| Delete | `DELETE /api/patches/{id}` | `delete_patch` | Sound-bank lines that played it lose their `patch` but keep their `title` (`setlists.forget_patch`). |
| List | `GET /api/patches` | `list_patches` | |

Every mutating route schedules a full catalogue push to golem.fm (`routes_patches._pushed` →
`golemfm.push_patches`).

### 4.2 Deposit a patch into songs

| Gesture | API | Function |
|---|---|---|
| Songs ▸ Patches ▸ "Deposit in songs…" (writes the songs) | `POST /api/patches/{id}/deposit` `{presets: [id…]}` | `deposit` |
| Designer lane title ▸ "⛓ Load a patch" (mutates the draft only; the Designer saves it) | `POST /api/patches/{id}/apply` `{preset, lane?}` → `{preset, lane, lost_scenes, added_scenes, skipped_elements?}` | `apply_to` |

Rules:

- **Destructive and confirmed.** The target lane is **replaced** in every song. The UI must say so
  before ("replaces the lane of the songs you pick").
- **Target lane** (`_target_lane`): the lane named in the request, else the first lane of the patch's
  role (guitar/bass/line are interchangeable as fallback). A drum patch never lands on a non-drum lane:
  no Drums lane = refusal with what to do.
- **Only instrument lanes are copied**, never the patch's `config` (`deposit_payload`): the song keeps
  its services, backing and arrangement.
- **Block-id collisions are renamed** (`_dedupe`), with the renames reported (`renamed`).
- **Scenes merge by id** (`_inject_scenes`): for each song scene, entries for the patch's blocks are
  replaced by the patch's. A patch scene the song lacks is **created** (id, name, entries, level) up to
  8 scenes (`MAX_SCENES`) → `added_scenes`; beyond the cap → `lost_scenes`. Existing song scenes keep
  their names. A patch with no `scenes` at all changes no scene entry.
- Patch scenes become named **lane states** of the target lane (`_inject_states`, see
  [band-scenes.md](band-scenes.md)).
- **Tags do not travel** to the song.
- **Kit patch** (`elements` or multi-lane): each element goes onto the lane of the song's drum group that
  has the same `element`; missing ones are reported in `skipped_elements`, never in `lost_scenes`. A song
  without a drum group gets the kit's lanes on the next **free** card inputs, in kit order
  (`add_kit_lanes`); extra lanes wait with `in_sel: "NONE"` — never two elements on one input. A song
  not yet in lanes v2 is refused.

### 4.3 Make a song from a patch

"▤ Make a song" (`POST /api/patches/{id}/song` `{name?}`) creates a **new** preset from the whole patch
— lanes, scenes, ⚙ including backing, pedals — via `as_preset` + `save_preset`. It never overwrites an
existing preset: the id is suffixed. The patch is unchanged; the arrangement is added afterwards.

## 5. Playing a patch

### 5.1 `patch:<id>`

- `POST /api/patches/{id}/play` `{scene?}` recalls `patch:<id>` (default: first scene) through
  `recall.recall_async` — the path of every recall. Lanes that could not bind (§5.2) → `409` with the
  reason.
- `store._load_patch_preset(id)`: if the Designer's edit buffer (`presets/.sandbox.json`) currently holds
  this patch (`__patch.id == id`), the **draft** is served (otherwise a foot scene change would rebuild
  from a save that lags behind the screen); else `patches.as_preset(get_patch(id))`.
- `as_preset` returns a preset with `id: "patch:<id>"`, `kind: "patch"`, `lanes_v: 2`, `bpm` (default 120),
  `config`, `exp*`, `colors`, `anims`, `origin`, `backing`, and the marker `__patch: {id, name, role, realm,
  drumset?}` that opens it in patch mode in the Designer. A patch with no scene gets one scene `A`.
- `/live` shows "⛓ <name>" and its scenes; no sections.
- Anywhere an id may designate either a preset or a patch (heartbeat, `/api/state`, `foot_list`,
  `set-appearance`, bank lines), the patch id is **prefixed `patch:`**.
- A patch is published as a patch, never as a preset (`tones_sync` refuses `patch:` and `sandbox-try` on
  the preset publish path).

### 5.2 Input binding (`patches.bind_input`)

Each non-kit lane binds to the input of its role on the current card (`state.inputmap`): the k-th lane
of a role takes the input numbered k of that role (`nth`); without numbering, the first input serves
the first lane. MIDI roles (keys, pads) bind to `usb1` by default. Drums: a drum module bound on a USB
port first; else an audio Drums input; a lane holding a Drum Kit block with neither waits on `usb`
(MIDI, "auto by role"). No input of the role → the lane gets `in_sel: "NONE"` and a `bind_error` that
says where to fix it (Modes ▸ Inputs). Kit lanes keep their nominal inputs.

### 5.3 The trial: `sandbox-try`

`sandbox-try` is a reserved preset id served from `presets/.sandbox.json` (`store._load_sandbox_try`).
There is **no** `presets/sandbox-try.json`; `load_presets()` never lists it; `publish_preset` refuses it.

- **Adoption from the Designer** (`app.py` `sandbox_apply`): a draft that is not a named preset
  (`recall.is_trial_doc`: a patch bench with `__patch`, or the blank `nouveau-preset`) is recalled as the
  current preset on its first audition, under `recall.trial_id(preset)`: **`patch:<id>`** for a named
  patch, **`sandbox-try`** for an unnamed bench. A scene picked in the Designer becomes the current
  scene. Never in a locked mode.
- While the trial plays, `sandbox_apply` emits under the trial id (otherwise the next foot scene press
  would see a different rig and trigger a full rebuild).
- Opening a named preset in the Designer ends the trial: that preset is recalled under its own id.
- **Foot:** scenes and stomps act on the trial. The FCB bank does not move (a trial has no setlist
  slot); a PC (slot change) recalls that slot's preset, which is the way out.
- A bridge or rack restart re-adopts the trial (`.live.json` holds the id, `load_preset` serves it) as
  long as the sandbox file exists.
- Colours/animations: the patch's own if it has them, else defaults.
- **`patch-try` from golem.fm** (`tones_jobs._patch_try`): builds a one-lane trial preset on the
  first input of the role (`_trial_preset`), dry-runs it (`recall.check_preset`: a compile refusal
  writes nothing), copies the old buffer to `.sandbox.prev.json`, writes the sandbox, then
  `do_recall("sandbox-try", first scene)`; bumps `state.sandbox_rev` so the Designer shows a banner.

## 6. Sound banks and the foot list

- A setlist has `kind`: `songs` (default) or `sounds` (a bank of patches), fixed at creation
  (`setlists.KINDS`); a list never mixes both. A sound-bank line is `{id, rev, patch, title}`, `title`
  always present. 19 slots, one PC per slot, as for songs ([pedalboards.md](pedalboards.md)). A slot of a
  sound bank recalls `patch:<id>`.
- Songs ▸ Patches ▸ "Add to a bank" → `setlists.add_patches` (refused on a song setlist, unknown patch,
  full list). Songs ▸ Setlists shows both kinds: ▤ setlist, ⛓ sound bank.
- **One list on the foot at a time**: the active setlist (`config/setlist.json`, `setlists.active_id`),
  whatever its kind. Shown as "On the foot"; a tap changes it.
- **A mode sets the default foot list** with `foot_list` (a setlist id). Entering the mode puts that list
  on the foot if it still exists (`modes.apply_foot_list`); if it was deleted, the foot keeps its list and
  the reason is shown (and published in the heartbeat via `modes.last_foot`). A manual "On the foot" tap
  holds until the next mode change. No `foot_list` = entering the mode does not touch the foot. Four
  factory modes ship with `"foot_list": "factory"`; hiding the factory content does not remove that
  setlist, so a mode that names it still uses it. Pedalboard ships `"foot_list": "@instrument"`: the factory
  sound bank of the first instrument on the card ([modes.md](modes.md) §2, 2026-10-24).
- `modes_ctx.foot_lists: [{id, name, kind}]` (`rigstatus`) lists the lists golem.fm may name in
  `mode-set`.
- After changing the list on the foot, `tools/fcb/check-uno2.py` says whether the chip needs a reflash
  (service blocks in a patch reserve switches like in a preset).

## 7. Designer patch mode

A preset carrying `__patch` opens in patch mode: the tabs of its lanes plus ⚙ (§3), scene chips A–E
editing the patch's scenes (with their names, `designer-model.js` `patchDraft`), the stomp strip (a
block's `foot` assignment travels with the chain), auto-save (`✓ saved`), "New patch" for a blank bench (shown "· not saved" until its first save),
◀ ▶ arrows that stay within the role, and a simple browser (instrument + name). The BPM field reads
"BPM when alone": it is saved in the patch as `bpm`, the tempo when the patch plays on its own; dropped
into a song, the song's tempo wins.

**Foot union**: the foot gathers every `foot: N` block of every lane. Two patches with a block on
switch 6 in the same preset give one stomp 6 that toggles both.

## 8. Patches from golem.fm

Job contracts (payloads, acks) are in [golemfm-protocol.md](golemfm-protocol.md). Rack-side rules:

- **Validation of a received document** (`tones_jobs._patch_doc`): the role is required; a v2 document
  must have all lanes of that role and **one** lane (multi-lane kits are built on the rack); if both
  `chain` and `lanes[0].chain` are present they must be identical, else refusal
  (`lanes[0].chain is the truth`); duplicate block ids are refused; a document without blocks is refused.
  Missing split `mode` and scene/block ids are **completed, never rewritten** (`normalize_patch`).
- **`patch-install` / `patch-push`** → `library/patches/`; replaces a local patch only if it has
  `origin: "golem.fm"` and the same id, else suffixes. Pushes the catalogue back at once.
- **Captures** (`tones_jobs._settle_captures`, for install, try and preview): a block with a `ref` not
  installed here is installed **before** the audition (golem.fm packs, then loans, then TONE3000 with the
  rack's account), within a size cap and a time budget; a failure is reported in `install_failed[]` and
  only that block is missing. A capture block **without** `ref` is left empty: a name match is only
  returned as a proposal in `suggested[]` and shown first in the Replace sheet, never applied.
  `matched[]` stays empty for compatibility. See [block-status.md](block-status.md).
- **`patch-delete` / `preset-delete`**: same body as the local delete, then the push that confirms.
  An absent id is `ok` with `deleted: false`. Refused, with the reason in the ack, in a locked mode,
  during a take, or (preset) if it is playing. Never refused because a song uses the patch (copy model).
- **`patch-preview`**: builds the trial preset under a temporary id `preview-<patch_id>`, re-amps the
  reference DI (`ref`, else chosen by role and style, `preview.resolve_di`) through each scene, uploads
  one clip per scene, then deletes the temporary preset and local clips. The live engine is taken during
  the render and restored after; the Designer buffer is never written. Refused in a locked or gig mode,
  during a take, for a MIDI (keys) lane, or when no reference DI exists. See
  [preset-preview.md](preset-preview.md).
- **Catalogue push** (`golemfm.push_patches`, debounced): `refresh_deps()` then every file as stored,
  with `complete: true` — the batch is the full catalogue.

Patch creation by AI lives on golem.fm, not on the rack; the rack validates what arrives. The block
categories offered per role are data: `library/catalog/effects.json` → `role_categories` (a role absent
from the table sees every category), read by the Designer drawer and pushed in the catalogue.

## 9. People

A patch has an optional `person` (attribution, not ownership or permission — anyone can edit any
patch). People come from the band roster; the rack selects a band and assigns a person to each input,
it never creates accounts and never asks for a login. See [identity.md](identity.md) and
[devices-people.md](devices-people.md). A patch whose author left the band stays.
