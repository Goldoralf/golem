# Input map — physical connectors → named instruments, per card

> **Status: PARTLY CODED** — per-card input/output maps, numbered instruments, lane binding by (role, number), USB ports as rack inputs, stereo pairs, unmounted lanes and mode vetoes are built; a permanent badge for output fallback and selecting a MIDI input by device name in REAPER are not.

The input map is wiring only. ("Patch" means the musician's sound, see [patches.md](patches.md); the
module was renamed from "patch" and `inputmap._migrate()` moves an old `config/patches/` folder to
`config/inputmaps/` on load.)

| | |
|---|---|
| Files | `config/inputmaps/<card-slug>.json` — **local state** (git-ignored), created by `inputmap._seed()` on first sight of a card |
| Module | `bridge/inputmap.py` |
| Routes | `bridge/routes_inputmap.py` — `GET /api/inputmap`, `POST /api/inputmap`, `POST /api/inputmap/pair` |
| Broadcast | `state.inputmap` (= `inputmap.current()`), pushed on every change |

## 1. Three layers

```
CARD (physical)       INPUT MAP (assignment)          PRESET (musical)
IN 1 ──────────────── guitar  "Guitar 1"  ─────────── guitar lane
IN 2 ──────────────── voice   "Voice 1"   ─────────── voice lane
USB 1 (MIDI) ──────── keys-pads "Keys + Pads 1" ───── keys lane
```

- **The map belongs to the card.** Change card → golem loads that card's map.
- **A preset never names a port.** Its lanes bind to numbered instruments (§3), which is what makes
  a preset portable between a 2-input card and a 16-input mixer.

```
INPUT MAP : what EXISTS on this card
MODE      : what is ALLOWED in this situation (veto, see modes.md)
PRESET    : what is USED musically

mounted = exists ∧ allowed ∧ used
```

A mode never binds a port: it vetoes numbered instruments (`mode.inputs_off = ["voice#2"]`,
`"role#n"` keys, `bridge/modes.py`) and may **prefer a card** (`mode.card`). See [modes.md](modes.md).

## 2. File format

```json
{
  "card": "hw:V276",
  "inputs":  [{"ch": "1", "role": "guitar", "nth": 1, "person": "<roster id>"},
              {"ch": "2", "role": "voice"},
              {"ch": "5-6", "role": "drums"}],
  "outputs": [{"ch": "1-2", "role": "monitors"},
              {"ch": "3-4", "role": "iem", "person": "<roster id>", "type": "iem"}],
  "midi_in": "fcb",
  "midi_out": "whammy-dt",
  "inherited_from": "asio:…"
}
```

- **Card key** (`inputmap._card_device()`): Linux = `config/io.json` `device` (e.g. `hw:V276`);
  Windows = `asio:<driver>`; macOS = `coreaudio:<device>`. File name = slug of that key.
- `ch`: one channel (`"2"`) or a linked pair (`"5-6"`, one connector).
- Input roles (`INSTRUMENTS`): `guitar`, `bass`, `voice`, `keys`, `drums`, `pads`, `keys-pads`,
  `line`, `none`. Chosen by icon (no free text on a kiosk); the role id is the stable key.
- Output roles (`OUT_ROLES`): `monitors`, `pa`, `amp`, `click`, `iem`, `wedge`, `other`. An output
  may carry a `person` and a `type` (`iem` | `wedge`) — the returns, see [returns.md](returns.md).
- DIN MIDI ports: `midi_in` ∈ `fcb` (pedalboard), `controller` (shown as "soon", not wired),
  `none`; `midi_out` ∈ `whammy-dt`, `none`. `none` is a kill switch for a stray cable.
  `inputmap.din_role(kind)` serves them on the hot path (cached on file mtime) to `foot.feed` and
  `midi_out`.
- `person` is a property of the **input** (or output), not of the mode or the lane; names come from
  the roster ([identity.md](identity.md)). A person who left the band keeps their id.

### Seeding (`_seed`)

Sized by the card's real channel count (`_card_channels`: `config/cards/` registry, then the ALSA
probe, then the desktop driver's opened channels on Windows/macOS; `(2, 2)` only when nothing can
count). Volt 276: IN 1 `guitar`, IN 2 `voice`. Any other card: IN 1 `guitar`, the rest `none`.
Outputs in pairs: the first `monitors`, the rest `other`; an odd last channel is mono. A first seed
also calls `card_setups.first_seen()` (proposes shared setups for that card,
[card-setups-exchange.md](card-setups-exchange.md)).

On Windows/macOS, `_load()` appends channels that the driver opens later (as `none` / `other`)
without touching assigned roles. When the **driver** changes but not the card (generic ASIO → native),
`inherit(old, new)` copies the map to the new key — unless the USB identities differ (another card)
or the old map is still factory defaults.

## 3. Numbered instruments, and how a lane binds

Each input has a **number within its role** (`nth`, 1–10, unique per role on the card; when not
declared, its rank) and a **derived name**: "Guitar 2", "Voice 1" (`with_nth()`, `_enrich()`).
There are no free-text input names.

A preset lane binds to **(role, number)**: `lane.in_role` + `lane.in_nth`, set when the user picks
the input. Resolution (`preset_view` lane normalisation):

- the card has that (role, nth) → the lane takes that physical input, and its instrument is the
  input's role;
- **bound by name and absent from this card** → the lane **waits for its card**: never mounted on its
  raw number ("Guitar 2" on a Volt would land on IN 2, the microphone);
- a lane without a name binding, or a card without a map: its own input number (`in_sel`); without
  even that, the first input of its role.

**Unmounted lanes are said, never silenced.** `scene_bake` puts them in `plan.unmounted`
(`{id, name, input, reason}`, e.g. "needs Guitar 2, this card has 2 inputs and no Guitar 2"); the
bridge logs them and publishes `state.rig_unmounted`; the Designer greys the tab with the reason. The
preset is untouched; there is no automatic fallback to another input — changing who hears what on
stage is decided, not suffered.

**Empty lanes.** A v2 lane with no block is a passthrough (a checked input is played). A legacy
preset's empty `voice: {chain: []}` stays silent: mounting a bare microphone into the monitors when
reopening an old preset is feedback on stage.

Changing an input's role or number re-runs the current recall 1 s after the last write
(`routes_inputmap._reemit_later`) so the rig follows, not only the screen.

## 4. USB ports are rack inputs, not card inputs

The MIDI controller is plugged into the golem server and is there whatever the audio card.

- **Four fixed ports, USB 1–4** (`USB_PORTS = 4`), always listed under the card's inputs. Source:
  the Soundcard binding (`config/soundcard.json` `usb<n>`: device, role, `nth`, `person`) —
  `usb_ports()`, `_usb_update()`. An unbound port is shown greyed; hotplug proposes a binding.
- Roles: `keys`, `pads`, `keys-pads`, `drums` (a USB-MIDI drum module, [drums-kit.md](drums-kit.md)),
  `none` — never an audio instrument. One person per port.
- **Numbering is shared** between audio inputs and USB ports within a role (a keyboard on audio IN 5
  = "Keys 1"; the controller on USB 1 = "Keys + Pads 1"). A mode vetoes a numbered input without
  knowing whether it is audio or USB.
- A MIDI lane occupies a port: `in_sel: "usb1"` (legacy `"usb"` = USB 1). `current()` serves
  `usb[]` for every card; `midi` remains (first bound port, compatibility).
- The pedalboard and the Whammy are service ports, not instruments, and are not listed there.
- **Not built:** REAPER still takes a MIDI lane's input by device rank (`midi_input_base` + rank).
  With a second USB controller, `golem_rig` will have to pick the MIDI input by device **name**;
  validate on the rack, never in simulation.

## 5. Stereo pairs

A drum module or keyboard outputs L/R on two jacks = one instrument. `POST /api/inputmap/pair
{kind, a, b, linked}` (`set_pair`) merges two adjacent ports into one connector `"a-b"` with a single
role, or splits it back into two mono ports (`none` / `other`). Shown as a ⛓ link in Soundcard. The
same applies to outputs.

## 6. Routes

| Request | Effect |
|---|---|
| `GET /api/inputmap[?card=<id>]` | the enriched map (`card`, `inputs[]`, `usb[]`, `outputs[]`, `midi`, `midi_in`, `midi_out`) + icon catalogues (`instruments`, `out_roles`, `midi_in_roles`, `midi_out_roles`). With `card`: that card's map even unplugged (seeded from the registry if never mapped). If the asked card is the same physical card as the live one under another name (USB identity, `cards.same_card`), the live map is returned with `same_as_live: true`. |
| `POST /api/inputmap {kind:"input", ch, role, card?}` | assign an instrument (`set_role`; also `midi_in` / `midi_out` kinds; `midi_out` re-arms the Whammy line) |
| `POST /api/inputmap {kind:"input", ch, nth, card?}` | set the number within the role (`set_nth`) |
| `POST /api/inputmap {kind:"input", ch, person, card?}` | assign a person (`set_person`; USB ports included) |
| `POST /api/inputmap {kind:"output", ch, person?, type?, card?}` | declare a return (`set_out_person`) |
| `POST /api/inputmap/pair {kind, a, b, linked}` | stereo link (active card only) |

`card` lets the map of an unplugged card be edited (Settings ▸ Mode ▸ Inputs ▸ ✎, "Inputs of
«card»"): a mode declares its card and names its inputs without duplicating the map — two modes on
one card see the same inputs.

**Declared cards.** A card can be declared before it exists (`POST /api/cards/declare`,
`declared: true`) to prepare its map at home. If its real ALSA id differs from the declared name,
`cards._merge_declared()` (called by `cards.remember` on an unknown id) merges them on adoption: the
map file is renamed, modes pointing at the declared card follow, the declared descriptor disappears,
the probed one keeps `alias` and `merged_from`. One card, never two. See [gear-registry.md](gear-registry.md).

## 7. Designer: lanes come from inputs

- **"＋ Add an instrument"** (⋯ menu of a preset, `app/designer-lanes.js`) offers Guitar · Bass ·
  Voice · Keys · Drums and lists the preset's lanes below (uncheck = remove, two-step confirm).
  Drums opens the kit drawer ([drums-kit.md](drums-kit.md)). The others list the inputs of the
  edited card with what a tap would do: already that instrument → the lane; no instrument → name the
  input, then the lane; another instrument → rename it, in two taps, saying it applies to every
  preset and that the lane playing it here goes silent; a lane already exists → go to it. Keys adds
  the USB ports bound as keys/pads.
- **The instrument is written in the card's map** (`POST /api/inputmap {kind:'input', ch, role,
  card?}`), never in the preset. The lane is then created from the input the card returns.
- The lane **name** is the input name ("Guitar 2"); the old per-lane `names` field is read, never
  written. A **new** lane's id derives from the input (`guitar-2`, `voice-1`); existing lanes keep
  their id (scenes, levels and the Companion address it).
- **Tab order** is the card's: physical inputs first (IN 1, IN 2…), then USB ports, then lanes
  without input; ties by name (`designer-model.sortLanes`). The app writes the document sorted; the
  bridge does not sort.
- A stereo pair is one row. A legacy lane bound by plain number whose chain is not the input's
  instrument is flagged. Lanes of another card stay listed, checked and greyed (⏳ waits / ⚠ absent)
  and can only be unchecked; inputs without an instrument cannot be checked. A preset keeps at least
  one lane.
- **The Designer edits lanes on the mode's card**: when the active mode prefers a card that is not
  plugged, the sheet lists **that** card's map (`/api/inputmap?card=`); its lanes show "⏳ waits for
  «card»" and mount when the card arrives.

## 8. Soundcard page

Settings ▸ Gear ▸ Soundcard shows two rows: **CARD** (the plugged card: inputs, outputs, phones) and
**RACK** (USB 1–4 and MIDI DIN, always in the same place). Tap a connector to set its instrument,
number, person, pair. Above 6 jacks in a group, round glyphs become 38 px chips in rows of 9 (number +
icon; name and person in the detail). When the mode prefers an absent card, the CARD row shows
"⏳ <mode> prefers «card» — not connected" with **Prepare its patch →**. It fits 1024×600 without
scrolling.

## 9. Fallback rule

On stage **the sound never dies**, and **golem degrades by itself but never hides that it degraded**.
For inputs this is built (§3: unmounted lanes, always shown). For outputs, a lane routed to an output
the card does not have is **not** yet folded to OUT 1/2 with a permanent badge: `golem_rig.lua`
`route_monitor()` routes `out_sel` as given (`"a-b"` stereo, `"n"` mono, default 1/2). The global
mono fold-down (`config/io.json` `mono_fallback`) is separate.
