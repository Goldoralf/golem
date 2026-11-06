# Gear registry — sound cards and USB devices

> **Status: CODED** — the sound-card registry (`config/cards/`), card adoption and declaration, the "active card unplugged" banner, and the known-devices registry (`config/devices.json`, "known ≠ connected") are built.

**Probe first, enrich afterwards, never depend on a database to work.** An unknown card must be
usable generically (IN 1..N, OUT 1..N) with only what the system can probe (ALSA/USB). A descriptor
only adds comfort: printed labels, headphone behaviour, safe buffer. The stable identity of any USB
gear is its **VID:PID**, never its ALSA enumeration order.

Per family:

| Family | Approach | Where |
|---|---|---|
| Sound cards | registry filled by the probe, optional enrichment | `config/cards/` (this page) |
| USB MIDI devices (keyboards, pads, drum modules) | known-devices registry + calibration profiles | `config/devices.json` (this page), [calibration.md](calibration.md) |
| Foot controllers | curated integrations (a new model is work, not a file) + learned devices | [pedalboards.md](pedalboards.md) |
| Controlled MIDI pedals | data-driven descriptors | [pedal-registry.md](pedal-registry.md) |

The per-card role assignment ("port → instrument") is the input map, not the registry: the registry
describes the **hardware**, the input map describes **your use** ([input-map.md](input-map.md)).

## 1. Sound-card registry — `config/cards/<id>.json`

Local state (git-ignored). Module `bridge/cards.py`.

```json
{
  "id": "V276",                    // ALSA id — key of the registry and of the input maps
  "usb": "2b5a:0023",              // VID:PID from /proc/asound/cardN/usbid
  "name": "Universal Audio Volt 276",
  "inputs": 2, "outputs": 2,       // probed (stream0)
  "midi": {"in": true, "out": true},
  "phones": "mirror",              // optional enrichment: mirror | pair:<n-m> | none
  "labels": {"in1": "MIC/LINE 1"}, // optional enrichment
  "buffer_safe": 192,              // optional enrichment
  "seen": "2026-10-05", "probed": true,
  "declared": false, "ignored": false,
  "alias": "XR18", "merged_from": "XR18"   // after a declared card was merged (§3)
}
```

- `cards.probe(cid)`: the descriptor of a **connected** card (Linux: `/proc/asound`, channels from
  `stream0`, MIDI presence; ALSA does not expose MIDI direction, so `in`/`out` are both the presence;
  Windows/macOS: the driver's opened channels).
- `cards.remember(cid)`: probe + write. Enriched fields (`phones`, `labels`, `buffer_safe`) of an
  existing descriptor are **kept**; the probe only refreshes what it can measure.
- `cards.known(cid)`, `cards.registry()`, `cards.usb_of(device)`, `cards.same_card(a, b)` (two names of
  one card, by USB identity across OS keys — [returns.md](returns.md) §2).
- ALSA gives the **number** of channels, never their **independence** (a headphone jack usually
  mirrors OUT 1–2). That is declared (`phones`), never guessed ([mixer.md](mixer.md) §5).

### Routes (`bridge/routes_system.py`, admin)

| Route | Effect |
|---|---|
| `GET /api/cards` | `{active, connected[], registry[]}`; connected cards carry `known`, `ignored`, `active`, `candidate` (connected, not active, not ignored — drives the "switch" banner); registry cards carry `connected`, `active`, `prepared` (an input map exists) |
| `POST /api/cards/adopt {id}` | adopt a connected card (§2) |
| `POST /api/cards/declare {id, name, inputs, outputs}` | declare a card never plugged (§3) |
| `POST /api/cards/ignore {id}` | never propose this card (e.g. a dock's audio); descriptor kept |

## 2. Adopting a card

Linux (`cards_adopt`): `remember` → refuse a device without audio (a MIDI controller) → validate
`reaper.ini` has `alsa_indev`/`alsa_outdev` (backup `reaper.ini.golem.bak` once) → write
`config/io.json` (`device: hw:<id>`, `outputs_count`, `midi_out` = the card's MIDI port so the
Whammy follows) → reset MIDI output caches and rebind the foot reader → restart the engine, writing
`alsa_indev`/`alsa_outdev` into `reaper.ini` **after** REAPER has exited (it rewrites the file on
quit). `audio_reset` is not enough to change device. MIDI masks are not touched here:
`provision/reaper-ini-setup.py` computes them before each engine start.

Windows: the card is an ASIO driver; macOS: a Core Audio device — adoption goes through
`desktop_audio.start_apply()`.

The input map of the new card seeds itself on first access (`inputmap._load`); the replaced card's
map stays in `config/inputmaps/`, so switching back needs no reconfiguration.

## 3. Declared cards

A card can be declared before it exists (`cards.declare`: `declared: true`, `probed: false`) so a
mode can name its inputs and presets can be prepared at home. Refused if the id is already probed.

When a card is plugged for real under a different ALSA id, `remember` → `_merge_declared()` merges
it if **exactly one** declared, unprobed card has the **same input count**: the input-map file is
renamed (and its `card` rewritten), local modes pointing at `hw:<declared>` follow, the declared
descriptor is removed, the probed one keeps `alias` and `merged_from`. One card, never two.

## 4. Active card unplugged

The screen says it; the rack never switches by itself. A gig output silently moving to another card
is worse than a visible silence.

- `monitors._poll_cards()` (every ~3 s) publishes `state.cards` with `active_present` and
  `active_name`.
- The app shows a **global banner** on every page (`app/main.js`): the expected card "is not plugged
  in", and one button per **plugged** card (same gesture as "Switch to it": `POST /api/cards/adopt`,
  engine restart ~10 s).
- The `/live` chip says **NO CARD** instead of NO AUDIO.
- The audio watchdog does not spend its single `audio_reset` while the card is missing; it keeps it
  for the first tick the card is back.
- Out of reach: REAPER's own "error opening input device" dialog at startup; adopting from the banner
  restarts REAPER, which closes it.

## 5. Known ≠ connected — `config/devices.json`

> **A device that has been connected to the rack is KNOWN. It stops being known only by an explicit
> gesture ("Forget"). Connected or not is a STATE shown everywhere, never a condition of existence.**

"USB n" is not a physical socket: it is the **rank** of the device among detected USB MIDI devices
(other than the sound card). Binding by rank lost devices when unplugged and let a new device
overwrite another's binding. So the rack binds **devices**, and the rank is a consequence.

Local state (git-ignored). Module `bridge/devices.py`. One entry per device, key = **VID:PID** when
ALSA gives it, else `name:<slug>` (re-keyed by VID:PID as soon as it is seen again,
`mark_seen()`):

```json
"09e8:0045": {"name": "AKAI MPK Mini Mk II", "usb": "09e8:0045", "kind": "midi",
              "roles": ["keys", "pads"], "person": "<roster id>", "nth": 1,
              "first_seen": "…", "last_seen": "…"},
"13b2:009c": {"name": "Alesis Nitro", "roles": ["drums"], "kit": "alesis-nitro", …}
```

- **The port is derived**: `devices.bindings()` returns `{usbN: {enabled, device, kind, roles, person?,
  nth?, kit?, key}}` for each known device currently detected at rank N — the shape every reader uses
  (`inputmap`, `vital`, hotplug, `routes_system`, `drumkits.resolve`, `compile_rig`,
  `provision/reaper-ini-setup.py`).
- **A known device that reappears, at any rank, is active without a gesture.** Two known devices
  plugged = two ranks, two lanes. An unknown device taking a rank **erases nothing**: it is listed
  with `known: false`, and binding it is a gesture.
- **Unplugged**: no rank, still known (roles, person, number, kit), listed as "○ not connected · last
  seen …". Actions that need presence (Measure, Calibrate) are disabled with their reason, never
  hidden.
- **`forget(key)`** is the only exit; `enabled: false` on `POST /api/soundcard/usb` and role `none`
  in the lanes sheet lead there, both explicit.
- **A calibrated controller profile is a known device** (`controllers.save` registers it). REAPER
  provisioning reads **all** known devices, unplugged included, so a controller plugged after boot
  keeps its MIDI mask bit.
- **Detection is cheap**: `devices.detected()` reads `/proc/asound/cards` only, with a 2 s cache. A
  shared source of truth must not cost the price of a probe (`aconnect -l` + PCM probes took
  ~900 ms per call).
- **Migration** (idempotent, first load): `config/soundcard.json` → devices, plus every
  `config/controllers/*.json` → known (keys + pads); the old file becomes `soundcard.json.migrated`,
  never deleted.

### Routes

| Route | Effect |
|---|---|
| `GET /api/devices` | known ∪ detected, each with `known`, `connected`, `port`, `hw`, `roles`, `person`, `kit` (resolved), `calibrated`, `first_seen`, `last_seen` |
| `POST /api/devices/{key} {roles?, person?, kit?}` | edit a known device, plugged or not (admin) |
| `DELETE /api/devices/{key}` | forget (admin) |
| `POST /api/soundcard/usb` | bind the device detected at a rank, or forget it (unchanged shape) |

Screens: Calibration ▸ Controllers and ▸ Drums list known ∪ detected with their state
("● connected · USB n" / "○ not connected · last seen …") and **Forget**; Soundcard ▸ an empty USB
port names the absent known devices ("plug it in, it activates by itself").

Out of scope: controlled MIDI pedals (`mappings/`) have no connected state — nothing can detect a
pedal on a DIN output. The pedalboard has its own (`measured` / `declared`).
