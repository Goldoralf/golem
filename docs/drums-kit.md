# Drums: electronic kits, rack kits and the drums lane

> **Status: PARTLY CODED** — an electronic drum kit is an ordinary instrument lane (audio, MIDI or both), described by a module descriptor in data and played through the rack's kits; everything below is coded except the kit bus (§6.8, PROPOSED).

Related references: [input-map.md](input-map.md) (the input map, USB ports and roles),
[calibration.md](calibration.md) (Calibration ▸ Drums, measuring a module),
[patches.md](patches.md) (patches), [blocks-doctrine.md](blocks-doctrine.md) (the drum machine
`drums` block, pad kits), [pedal-registry.md](pedal-registry.md) (the same "one device = one
descriptor" pattern), [golemfm-protocol.md](golemfm-protocol.md) (jobs and packs).

Two different things are called "kit" in this repository — keep them apart:

| word | what it is | where |
|---|---|---|
| **module descriptor** (`drumkit` descriptor) | what a physical e-drum module *sends*: its note table, hi-hat pedal, choke, audio outs | `config/drumkits/<id>.json`, `bridge/drumkits.py` |
| **rack kit** | a sound the rack *plays*: an engine plus its content | `library/kits/<id>.json`, `bridge/kits.py` |
| `drumset` (lane field) | the physical kit a group of lanes belongs to | §6 |

The `kit` param of the `drumkit` block is a **rack kit** id (e.g. `drums-black-pearl`); a lane never
carries a field named `kit`.

## 1. The rule

A drum kit is **a lane like any other**: a person on an input, scenes, takes, a Companion. Its role
is `drums`. Nothing is special beyond what the instrument imposes. The drum machine (Players lane,
`drums` block, grooves) is a separate thing and is not covered here.

## 2. Two input paths, one lane

| path | what is plugged | who makes the sound |
|---|---|---|
| **Audio** | the module's L/R out → a **linked pair** of card inputs (`"3-4"`, parsed by `store._parse_in`); mono accepted | the module |
| **MIDI** | the module's USB-MIDI (or DIN through an interface) → a USB port bound to the role **Drums** | the rack, with its kits (§4, §5) — and the only path that records *what was played* |
| **Both** | **two lanes**: one audio lane on the pair, one MIDI lane on the USB port | choose per scene by muting one lane — a scene state change, not a rebuild |

- `drums` is a USB role (`inputmap.USB_ROLES`) and is exclusive: a port bound to drums is neither
  keys nor pads. Soundcard ▸ USB n shows a "drums" chip and a **Kit** row (the descriptor).
- A lane on a USB port is MIDI whatever its role (`store._norm_lane`, app `normLane`); in audio, a
  drums lane behaves like a bass lane.
- `lane_stomps.lane_person` resolves a MIDI lane through its USB port and an audio lane through its
  input, so a drummer who holds both lanes sees both on the Companion.
- The drawer is filtered by role: `role_categories.drums` and the exact list `role_blocks.drums`
  in `library/catalog/effects.json` (dynamics, preamp, lofi, EQ, a few modulations, delays,
  reverbs, utility — never amp, cab, drive, wah, pitch).
- The tuner is hidden on a drums lane; the pedalboard view treats `drums` like voice/keys/pads.
- Several audio outputs of one module = **N lanes**, never a multichannel lane (§6).

Pitfalls: asking for a pair `"1-2"` on a card whose inputs are declared mono leaves the lane
unmounted (`rig_unmounted` says so). Binding a USB port to `drums` while a keyboard is plugged
there makes the keyboard play the drums — the rack obeys the binding.

## 3. The module descriptor — data, never a hard-coded table

One file per module model: `config/drumkits/<id>.json`. Validation in `drumkits.validate()`, shared
with `tools/check-descriptors.py`; an invalid file is logged and ignored by `drumkits.load_all()`.

```json
{ "schema": 1, "kind": "drumkit", "id": "alesis-nitro", "name": "Alesis Nitro",
  "identity": { "brand": "Alesis", "model": "Nitro", "connection": "usb+din", "usb_names": ["Nitro"] },
  "channel": 10,
  "editable_on_module": true,
  "map": { "36": "kick", "38": "snare", "40": "snare-rim", "42": "hh-closed", "46": "hh-open", "44": "hh-pedal", "…": "…" },
  "hihat": { "cc": null, "positions": 2, "notes": "distinct" },
  "choke": "none",
  "audio_outs": { "master": "stereo", "direct": 0, "assignable": false },
  "provenance": { "source": "measured", "confidence": "verified", "note": "…" } }
```

| field | rule |
|---|---|
| `id` | slug, equal to the file name |
| `kind`, `schema` | `"drumkit"`, `1` |
| `identity` | `brand`, `model` required; `connection` = `usb` \| `din` \| `usb+din`; `usb_names` = substrings of the ALSA/OS device name (empty list = not identifiable) |
| `channel` | 1..16 |
| `map` | note (string `"0"`..`"127"`) → element of the closed vocabulary `drumkits.ELEMENTS`; must contain `kick` and `snare`; an element mapped twice is an error |
| `hihat.cc` | 0..127, or `null` = the pedal is a switch (no CC). With a CC: `open_value` and `closed_value` (the **direction** is declared: Roland 0→90, Medeli/Yamaha 0→127) |
| `hihat.positions` | 2 or 3; with 3, `bands` = two percentages `0 < a < b < 100` |
| `hihat.notes` | `distinct` (open/closed are two notes) \| `single` (one note + CC) |
| `choke` | `poly-aftertouch` \| `note-off` \| `none` \| `unknown` |
| `audio_outs` | optional, §6.4 |
| `provenance` | `source` = `manual` \| `imported` \| `measured`; `confidence` = `verified` \| `reported` \| `unconfirmed`; `note` required. `verified` requires `source: measured` |

Confidence means: `reported` = read in a manual, `unconfirmed` = assumed (GM until measured),
`verified` = measured on **one** kit under the sticks. Every module lets its user rewrite the note
table, so a verified descriptor describes one kit, not a model. `check-descriptors.py` validates the
shape, never the truth.

**Shipped descriptors**: Alesis Nitro (measured), Turbo, Crimson II, Strike; Millenium MPS-1000,
MPS-850, MPS-450; Roland TD family; Yamaha DTX402, DTX6; and `general-midi`, the fallback.

**Measured descriptors are machine state**: Calibration ▸ Drums ("Save as measured",
`POST /api/drumkits/measure`, `bridge/drumlearn.py`) writes to `config/drumkits.local/<id>.json`,
outside the repository; a local file wins over the shipped one with the same id.

**Identification** (`drumkits.identify(device_name)`): the descriptor whose `usb_names` entry is a
case-insensitive substring of the device name; the longest pattern wins ("TD-17" before "TD-").
No match → `general-midi`, flagged `fallback: true`, and the screen says "GM fallback".
`drumkits.resolve(binding)`: an explicit `kit` on the USB binding (still existing) wins, otherwise
identification. The module is a fact of the rack, learned in Calibration ▸ Drums — never chosen in
a patch. `GET /api/drumkits` lists descriptors (fallback last) with their normalised `audio_outs`.

Lessons that hold for any module (from measuring a real one):
- A gesture produces a **sequence**, not a note ("closed" = aftertouch burst + pedal chick + the
  hit). The hit is the loudest note.
- Poly aftertouch on hi-hat notes can be the **pedal closing** (a choke order for the open sample),
  not a cymbal choke. Where an event arrives names it, not its presence.
- When a measurement proposes two elements for one note, nothing is written and both are named.
- Most shipped tables declare `cc: 4, positions: 3` from third-party sources; treat every
  `reported` / `unconfirmed` descriptor as a starting point to measure.

`tools/check-drums.py` listens to the module directly (`--learn`, `--compare`, `--write`); it only
works when REAPER does not hold the raw MIDI port. The on-screen version goes through REAPER
([calibration.md](calibration.md)).

## 4. Rack kits — `library/kits/<id>.json`

A rack kit is a library object referenced by a block (`drumkit` on a lane, `drums` drum machine,
`pads`). Format `{id, name, role: "drum"|"pad", engine, …}`; the engine decides the rest
(`kits.save_kit`):

| `engine` | content | required fields |
|---|---|---|
| `avldrums` | none (samples inside the LV2 plugin) | `bank` ∈ `kits.AVL_BANKS` (`black-pearl`, `red-zeppelin`, `blonde-bop`) |
| `drumgizmo` | a multi-mic kit folder under `library/drumkits/` | `drumkit` (the kit `.xml`) and `midimap` (`.xml`) — both required, the plugin has no default map; `mix[]` = factory mix, one `{ch, name, short, group, gain, pan}` per mic (≤ 16, groups `kits.MIC_GROUPS`, `trig` outputs muted); optional `bleed` |
| `sfz` | a `.sfz` + samples under `library/sfz/` | `sfz` (path) |
| `rs5k` | pad kit: up to 16 `pads[] {note, sample, mode, level}` | samples under `assets/samples/`; `mode` = `gate` \| `oneshot` \| `toggle`; level in dB. Default notes `kits.DEFAULT_NOTES` = GM in MPC placement |

A drum engine (`avldrums`, `drumgizmo`, `sfz`) also carries `notes` (element → kit note, vocabulary
`drumkits.ELEMENTS`, read by `kits.kit_notes`), `notes_note` (provenance), `hint`, and `imported`
for an imported kit.

**Where rack kits come from**

- **Factory seeds** — `library/kits-factory/*.json` (drum engines, plus rs5k pad kits flagged
  `factory`). `kits.seed_factory()` reseeds missing ones into `library/kits/` at bridge start and
  refreshes the `notes` table of an already-placed factory kit when the seed changes. Shipped:
  `drums-black-pearl`, `drums-red-zeppelin`, `drums-blonde-bop` (AVL banks), `drums-aasimonster`
  (DrumGizmo, 16 mics), and pad kits. A factory kit is never created, deleted (403) or overwritten
  from a screen; a new factory kit is a rack update.
- **Imported drum kits** — "+ Add" in Library ▸ Drums (§8). `kits.is_factory()`: `factory`, or a
  drum engine **without** `imported`. An imported kit can be deleted, and its folder goes with it.
- **Pad kits (rs5k)** — full lifecycle: created on golem.fm and pushed by the `kit-install` job
  (`tones_jobs._kit_install`, a `.golemkit`), edited and deleted on screen, and exchanged offline
  as `.golemkit` (zip = `kit.json` with `golemkit: 1` + `samples/`): `GET /api/kit/{id}/export`,
  `POST /api/kit/import` (`kits.export_kit` / `import_kit`; samples never overwritten, id suffixed
  on collision). `save_kit` refuses a drum engine from a screen.
- **Grooves** (`.mid` for the drum machine) are content too: `POST /api/groove/import`.

`kits.availability(kit)` says whether a drum kit can sound on **this** machine (files present,
plugin in REAPER's inventory); `GET /api/kits` carries `available` / `unavailable_why`, and the
kit picker uses it.

Routes: `GET /api/kits`, `POST /api/kit`, `DELETE /api/kit/{id}`, `POST /api/kit/audition`,
`GET /api/kit/{id}/export`, `POST /api/kit/import` (`bridge/routes_content.py`).

## 5. The `drumkit` block — a MIDI drums lane plays a rack kit

Block `drumkit` (category `drums`, `input_claim: drums`, one per lane; param `kit` is scene-first).
It lives **on the lane's track**, never on the drum machine's "Drums" track.

**Compile** (`compile_rig.py`): a `drumkit` on an **audio** lane is removed with a warning (the module
makes the sound there). On a MIDI lane, for each kit: `drumkits.translation(descriptor, kit_notes)`
→ 128 entries (−1 = the kit lacks the element; fallbacks in `drumkits.HH_FALLBACK`: rim → head,
tom 4 → last tom, china → crash…) plus the three hi-hat notes; elements the kit cannot play are
logged (`lost`). Each block gets a gmem slot.

**Union of kits** (`scene_bake.annotate_drumkit_union`): the preset materialises **every** kit its
scenes use; a scene switches on one. Adding a kit to a scene is a rebuild (`recall.scene_shape`
includes the set), switching scenes is 2–3 `SetEnabled`.

**REAPER side** (`golem_rig.lua` `build_drumkit_block`), one pair per kit:
- JSFX `golem_drumtrans` first, stamped `drumtrans:<block>:<kit>`, slider *Slot*; its table is
  written to gmem `golem_drumtrans` on **every** materialisation (gmem is not saved in the `.rpp`).
- the engine, stamped `drumkit:<block>:<kit>`: `avldrums` (bank by name) or DrumGizmo
  (`build_drumkit_dg`: LV2 state = `<config>` XML in the chunk, track at 16 channels — see
  `wants_nchan` — followed by `golem_drummix` stamped `drumkit-mix:<block>:<kit>` with the kit's
  factory mix). DrumGizmo streams gigabytes: the kit sounds when loading finishes, not at rebuild.
- `sfz` / `rs5k` engines are **not ported to a lane** and are logged as such.
- The active kit's pair is enabled, the others bypassed. **Block bypass cuts the engine**, never
  the translator (a bypassed translator would pass raw module notes to the kit).

**`golem_drumtrans.jsfx`** (`reaper/Effects/`): gmem slot of 256 per block — `[0..127]` kit note or
−1, `[128]` hi-hat CC (−1 = switch pedal), `[129]` open value, `[130]` closed value, `[131..132]`
bands, `[133]` positions, `[134..136]` closed/half/open notes, `[137]` nonce (0 = passthrough,
"no table"), `[138]` expected module channel. Note-off follows the note actually sent; the hi-hat
CC is swallowed; aftertouch and other CCs pass. Output is always **channel 10** (the rack kits
listen only there). Read-only sliders `hhpos`, `lastcc`, `loaded` are readable with `fxparams`.

**Input selection**: by port (`in_sel usbN` → binding), then by role (`vital.midi_input_for`). A
drums lane with no module bound has **no input and says so** (`midi_strict`) — never the keyboard
heuristic; the Keys lane never falls back to a port bound to drums (`midi_avoid`). The `knob-tap`
sniffer is never put on a drums lane (the hi-hat CC would drive a synth macro).

The lane's IN chip in the Designer lists card inputs **and** bound USB ports; switching USB ↔
audio keeps the chain. On an audio lane, the Drum Kit tile stays visible, greyed, tagged "USB",
with the reason.

## 6. The drum group — N inputs, one instrument on screen

A module outputs audio on one, two, or up to eight jacks (master stereo plus assignable direct
outs on high-end modules). The model stays **one lane = one input or one linked pair**; the group
is a way to show and create lanes, not an engine container: nothing in `golem_rig.lua` or
`compile_rig` knows about it.

### 6.3 Lane fields

All optional and opaque to the engine (kept by `preset_view`, `patches._LANE_KEEP`):

| field | value |
|---|---|
| `drumset` | the group id; lanes sharing it are one instrument (two drummers = two groups). Default = descriptor id, suffixed `-2` on collision |
| `drumset_module` | a descriptor id (display name, audio outs); a memory of where the patch was made — the rack's calibrated module wins |
| `element` | an element of `drumkits.ELEMENTS`, or `kit-mix` (`drumkits.KIT_MIX`) = the master, i.e. the rest of the kit. `kit-mix` is not an element and never enters `ELEMENTS` |

### 6.4 `audio_outs` in a descriptor

```json
"audio_outs": { "master": "stereo", "direct": 8, "assignable": true,
                "default": ["kick", "snare", "hh-closed", "tom1", "tom2", "ride"] }
```

`master` = `stereo` \| `mono` \| `null`; `direct` 0..16; `assignable` bool; `default` ≤ `direct`
entries from `ELEMENTS` or `kit-mix`; declaring no output at all is an error. Absent →
`drumkits.audio_outs_of()` returns "stereo master, no direct out" with `declared: false`; missing
`default` → `GENERIC_OUTS`, flagged `generic: true`. This field is **declared, never measured**: the
rack reads how many inputs the card has, not what the module sends on each, so `default` is only a
proposal, editable line by line.

### 6.5 The "Add a drum kit" sheet

`app/designer-drumset.js`. Opens automatically when a drums patch is created; also from Designer ▸
⋯ ▸ "＋ Add an instrument" ▸ Drums (preset mode), the patch menu "Add a drum kit" / "Change the
drum kit" (patch mode — the Designer has **two** ⋯ menus, one per mode), and Songs ▸ Patches ▸
＋ Add ▸ Drums.
- It reads the rack's **calibrated** module (Calibration ▸ Drums); without one it says so and offers
  only generic forms.
- What is cabled: "MIDI only" · "Stereo pair" · "Direct outs (N)". Forms the module lacks are greyed,
  not hidden.
- One row per free input, element proposed by `default`. One button poses all lanes, pairs and names.
- It counts inputs on the card **being edited** (the mode's card, `modePatch`), not the plugged one,
  so a kit for a larger console can be prepared in advance.

### 6.6 On screen

- Designer: lanes of one `drumset` fold under one header (module name, input count, person),
  folded by default; "▾ Show elements" unfolds them into full lanes.
- Elsewhere (/live, Companion, pedalboard) the group is called "Drums"; elements are reachable by tap.
- A group lane with no input on the plugged card is shown "not cabled", not as an error.

### 6.7 A drums patch carries the whole kit

A patch of role `drums` may carry `elements[]` instead of a single `chain`:

```json
{ "id": "my-kit", "role": "drums",
  "elements": [ {"element": "kick", "chain": {…}, "scenes": […]},
                {"element": "kit-mix", "chain": {…}} ] }
```

Other roles are unchanged. Patches are copied, never linked ([patches.md](patches.md)). Saved by
`patches.save_kit_patch` (`kit_elements`); routes take `drumset` instead of `lane`. On apply, each
element goes to the group lane with the same `element`; an element with no matching lane is skipped
**and named**. In patch mode the Designer opens an N-lane bench with **nominal** inputs 1..N (a patch
knows no card).

**Binding a drums patch to a card** (`patches.bind_input`): a USB port bound to drums (MIDI) >
the card's audio input "Drums" (the module makes the sound; the `drumkit` is dropped at compile) >
if the lane carries a `drumkit`, wait in MIDI on `"usb"` ("USB · auto (by role)") > otherwise a
refusal that says what to do. golem.fm `patch-install` / `patch-try` follow the same order.

### 6.8 The kit bus — PROPOSED, not built

A gate/comp/EQ over all elements needs a bus. Chosen design: **one more lane of the group,
`element: "bus"`, without input**, that the others feed — reusing the `merge` split topology
(`rig._path_tracks`: parent `role: "merge"`, children `folder: "child"`). None of this exists.
What it requires:
1. `element == "bus"` as a third reason for a lane to exist (today `in_sel: "NONE"` sets `disabled`
   in `store._norm_lane` and the lane silently disappears).
2. `scene_bake`: the bus path becomes the parent, the group's other paths its children.
3. `rig._path_tracks`: a child track **with** a physical input (merge children have `input: None`).
4. Path order becomes a contract: `golem_rig.lua` needs the parent before its children.
5. `validate_routing`: group lanes no longer need their own physical output.
6. UI: the bus in the group header, a gesture to add it.
Topology can be checked with the `golem-rig-tester` agent; sound cannot without a real module.

## 7. Takes keep the MIDI

`golem_perfrec.lua` captures every MIDI lane (`midi_candidates()`: any `Sandbox #Input N` track with
`I_RECINPUT >= 4096`), **in every recording mode**, muted or not. A file is written only if it
contains at least one note-on (REAPER closes every MIDI item with an all-notes-off CC, so counting
events would write empty files). The captured stream is the **raw** module stream (before
`golem_drumtrans`), so `take.json` records `drums: [{slot, device, descriptor, descriptor_auto,
fallback}]` (`monitors._drums_ctx`) — the descriptor **id**, never the table. If the sound comes
only from an audio lane there is no MIDI capture: use the two-lane setup of §2.

## 8. Importing a drum kit ("+ Add" in Library ▸ Drums)

`bridge/kit_import.py` + `bridge/routes_kit_import.py`; sheet `app/drums-import.js` (opened by
"+ Add" in `page-kits.js`, Drums mode; dev: `?drumadd=1`). Import goes through the rack (a folder, a
USB volume, or a URL the rack downloads), never through the browser.

| step | function / route |
|---|---|
| sources | `GET /api/kits/import/volumes` (removable first), `/browse`, `POST /api/kits/import/url` (`fetch_url`: `.zip`/`.tar` or a bare `.sfz` into `library/.import/`, safe extraction, public hosts only) |
| scan | `GET /api/kits/import/scan` → `scan()`: a DrumGizmo folder = a `<drumkit>` `.xml` + a `<midimap>`; an SFZ kit = each `.sfz` |
| read (before writing) | `GET /api/kits/import/read` → `read()`: name, engine and its availability, pieces → notes **read** from the midimap or `.sfz` keys (`#include`, `default_path`, `<global>/<master>/<group>` inheritance, note names), mics/regions, size, files, rate/bits, free space, name collision; `sfz_choices` when a folder has several `.sfz` (the first is taken; no picker on screen yet) |
| install | `POST /api/kits/import/install` → `install()`: copy into `library/drumkits/<id>/` or `library/sfz/<id>/`, tracked in bytes by a job (`GET /api/kits/import/job/{jid}`), then the kit file |

An imported kit file carries `imported: {at, from, bytes, files, dir, sample_rate, bits}`, `notes`,
`notes_note` (provenance and **unrecognised pieces**, listed rather than guessed; a piece with two
notes keeps the lowest), `hint`, and for DrumGizmo a factory `mix` built from channel names.
In the list it shows "this golem only" and a delete button, and its line says where it came from. Deleting it removes its folder
(`delete_kit` returns `freed_bytes`; only a folder named by `imported.dir` under
`library/drumkits/` or `library/sfz/` is touched). The Install button stays grey while the engine
is missing.

**Engines per OS**

| engine | Linux | Windows | macOS |
|---|---|---|---|
| avldrums | apt `avldrums.lv2` | x42 package | x42 package (not verified) |
| sfizz (SFZ kits) | `install-sfizz.sh`, LV2 | VST3 (installer `-Sfizz`; REAPER does not see the Windows LV2 bundle) | VST3 (`--sfizz`, not verified) |
| DrumGizmo | apt `drumgizmo` | none | none |

A DrumGizmo kit is importable only on Linux; elsewhere the sheet says it would be silent and
installs nothing. SFZ loading (`golem_drums.lua`, and the piano in `golem_rig.lua`): LV2 → `sfzfile`
path in the LV2 state; VST3 → `sfizz_vst3_set_file` replaces only `sfzFile` in the `vst_chunk`
state (handles paths with spaces). A freshly installed sfizz needs a REAPER restart before the
inventory sees it, and the sheet says so.

**Toward golem.fm**: an imported kit is never uploaded. `tones_sync` sends its **card** — a pack
`kind: "kit"`, tag `card`, `extra: {kit_id, engine, card: true, imported, bytes, files, pieces, mics,
sample_rate, bits, installed_on}` and the kit JSON as the only asset. The sync is scheduled after an
import or a deletion (`kits._sync_soon`) so the card appears / disappears from the rig-manifest.
`kit-install` of a card is acknowledged `{card: true, installed: false}` without installing
anything. See [golemfm-protocol.md](golemfm-protocol.md).

## 9. Tests and tools

`tests/test_drumkits.py`, `test_drums_lane.py`, `test_drums_patch.py`,
`test_patches_drums_bind.py`, `test_kit_import.py`, `test_role_categories.py`,
`test_inputmap_usb.py`, `test_lane_stomps.py`. Tools: `tools/check-descriptors.py` (shape),
`tools/check-drums.py` (listen to a module), `tools/import-drum-packs.py`.
