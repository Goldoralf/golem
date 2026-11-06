# Pedal registry — descriptors for MIDI-controlled pedals

> **Status: PARTLY CODED** — descriptor schema, shipped catalogue, one-tap install, generic install stepper, on-rack verification, MIDNAM import and CI validation are built; automatic identification of pedals (USB VID:PID, SysEx) and contribution to golem.fm are not.

Goal: add a physical MIDI pedal (Whammy, delay, reverb…) and have it work **the first time**,
without anyone re-typing a table. The foot controller itself is a special case of this schema, see
[pedalboards.md](pedalboards.md).

## 1. The descriptor drives, verification decorates

For sound cards ([gear-registry.md](gear-registry.md)) the probe is the engine: ALSA reports
channels and VID:PID, the descriptor only enriches. **A DIN MIDI pedal cannot be probed**: the
wire is one-way, a Program Change gets no answer. So for pedals the **descriptor is the engine and
verification decorates**. Without a file, a DIN pedal cannot be right the first time.

## 2. Where descriptors live

| Location | Role |
|---|---|
| `library/pedals/*.json` | **the shipped catalogue** — versioned, read-only, never touched by an uninstall |
| `mappings/*.json` | **pedals installed on this rack** — local state (do not commit) |
| `config/pedalboard/devices/*.json` | foot controllers ([pedalboards.md](pedalboards.md)) |

Two places because a catalogue you can destroy by uninstalling is not a catalogue: the manual wizard
cannot rebuild everything (it cannot capture bypass PCs).

Shipped catalogue: `whammy-dt` (measured, verified), plus MIDNAM imports (`eventide-eclipse`,
`lexicon-mpx100`, `lexicon-mx200`, `line-6-echopro`, `line-6-filterpro`, `line-6-modpro`,
`tc-electronic-m3000`).

### Routes (`bridge/routes_content.py`)

| Route | Effect |
|---|---|
| `GET /api/pedals/catalog` | catalogue entries (brand, model, firmware, connection, mode count, confidence, source, install step count) + `installed` |
| `POST /api/pedals/install {id}` | copies catalogue → `mappings/<id>.json`, stamps `installed_at`, `installed_from: "catalog"`. **409 if already installed**: reinstalling over it would silently erase local settings |
| `DELETE /api/pedals/{id}` | uninstalls from this rack; the catalogue keeps the descriptor |
| `POST /api/pedals/{id}/verify {failed[], checked, scope}` | writes this rack's verdict into `provenance.verified_here` (`at`, `ok`, `scope` = `quick` canonical checks / `full` all modes, `checked`, `failed`). A failure downgrades `provenance.confidence` to `unconfirmed`. |
| `GET /api/mappings` | installed **pedals** only (header fields): a file is a pedal if `kind == "pedal"` (fallback for pre-schema files: it has `modes`) |
| `GET /api/mapping/{name}`, `POST /api/mapping` | read / write one installed mapping (the manual wizard) |

UI: **"+ Add pedal"** opens the catalogue first — a known pedal installs in one tap. The wizard is
the last resort for a model nobody has described. Installed pedals have **⏏ Uninstall**.
`InstallSteps` (`app/page-pedals.js`) is the single stepper of the app: it runs `install.phases` of
any device, pedals and pedalboards alike.

## 3. Schema

One file per pedal **and per firmware revision**, in tiers; every tier is optional (a file without
`install` simply has nothing to set on the device).

| Tier | Fields | Answers |
|---|---|---|
| Identity | `identity` | who the pedal is, how to recognise it |
| MIDI contract | `channel`, `midi_out`, `modes[]`, `families`, `pc_ranges`, `treadle`, `bypass_rule`… | what to send it |
| Procedure | `install` | what to set **on** the pedal, once (MIDI channel, receive on, merge off…) |
| Verification | `verify` | how to know it works |
| Provenance | `provenance` | where the data comes from and how far to trust it |

```jsonc
{
  "id": "whammy-dt",              // file slug, stable, never renamed
  "name": "Whammy DT",            // display name
  "kind": "pedal",                // pedal | controller | pedalboard
  "schema": 1,                    // schema version (readers refuse > SCHEMA_MAX)

  "identity": {
    "brand": "DigiTech", "model": "Whammy DT",
    "firmware": null,             // the revision makes the mapping (§4)
    "connection": "din",          // din | usb | usb+din
    "usb": {"vid": "0x…", "pid": "0x…"},
    "sysex_id": "…",              // only once observed answering an Identity Request
    "note": "…"                   // what the user must know before plugging in
  },

  "install": {
    "needs": ["Sound card MIDI OUT → Whammy DT MIDI IN"],
    "phases": [{"name": "Wire it up", "steps": [{
      "title": "Cable",
      "do": "Plug the sound card MIDI OUT into the Whammy DT MIDI IN.",
      "hint": "The pedal never answers on MIDI — the wire only goes one way.",
      "badge": "first install only",   // optional: skippable step
      "action": "pedalboard-load"      // optional: a gesture the rack offers at this step
    }]}]
  },

  "verify": {"checks": [
    {"label": "1 Octave Up", "send": {"pc": 1},        "expect": "toe down = one octave above"},
    {"label": "Bypass",      "send": {"pc": 22},       "expect": "dry signal only"},
    {"label": "Treadle",     "send": {"sweep_cc": 11}, "expect": "the pitch glides"}
  ]},

  "provenance": {"source": "measured", "confidence": "verified", "note": "…"}
}
```

Rules:

- `send` reuses the vocabulary of `POST /api/calibrate/midi` (`pc`, `cc` + `val`, `sweep_cc`): no
  new verb.
- `action` is a **gesture id** known to the rack, not a boolean. Known ids
  (`tools/check-descriptors.py` `ACTIONS`): `fcb-flash`, `pedalboard-load`, `pedalboard-editor`,
  `pedalboard-hold`, `pedalboard-copy`, `pedalboard-flashed`.
- `provenance.source` ∈ `measured | manual | manual+hardware | imported | hardware`;
  `confidence` ∈ `verified | reported | unconfirmed`. The catalogue's `verified` means "verified
  somewhere"; `verified_here` is what *this* rack observed.
- All text shown to the user (`do`, `hint`, `label`, `expect`, `install.needs`) is English.

## 4. Firmware revision makes the mapping

Whammy IV, Whammy 5 and Whammy DT do not share a Program Change table. A registry keyed on
"Whammy" without revision produces silent errors (a semitone off, on stage). Identity carries
`model` **and** `firmware`; two files for two revisions are normal, and the UI makes the user
choose when it cannot tell. Never "roughly the same pedal".

## 5. Identification

| Connection | What can be known | Rack behaviour |
|---|---|---|
| USB-MIDI | VID:PID | **not built** for pedals (the mechanism exists for sound cards in `bridge/cards.py`) |
| DIN + SysEx Identity Request (`F0 7E 7F 06 01 F7`) | maker, model, firmware when the pedal answers | **not built** for pedals (built for the UnO2 pedalboard, [pedalboards.md](pedalboards.md) §4) |
| Silent DIN | nothing | the user picks the model in the catalogue |

The UI must show this asymmetry instead of promising magic. The Whammy DT is silent DIN.
`sysex_id` is filled only after an answer has been observed.

## 6. Importing MIDNAM files

Ardour's `patchfiles/*.midnam` (MMA standard "which program carries which name", GPL-2) describe
what the rack sends to a device — the registry's direction. Ardour's `midi_maps` describe the
opposite direction (controller → software) and are useless here; they would serve Calibration ▸
Controllers instead.

`./tools/import-midnam.py --list | --all | <name>` (`--dry-run`, `--force`):

- drops unnamed user slots instead of discarding the file (judge a file on its whole content: a
  bank of unnamed user slots can sit above hundreds of named factory presets);
- **never overwrites** an existing descriptor;
- writes `source: "imported"`, `confidence: "unconfirmed"`, never `verified`; provenance keeps the
  original author and path.

**Selection is data**: `tools/midnam-sources.json` lists what is imported and what is excluded,
with the reason. The criterion: is the device a **block in the chain** (delay, reverb,
pitch-shifter: imported) or does it **replace the chain** (a complete multi-effects rig such as a POD
or GT-8: excluded)? Synths and sound modules are out of scope.

A MIDNAM import is a **table, not a recipe**: no families, no install procedure, no verification
checks. It is a credible starting point; verification on the pedal promotes it.

## 7. Validation — `tools/check-descriptors.py`

Validates pedals (`library/pedals/`), pedalboards (`config/pedalboard/devices/`) and local mappings.
Fails on: id not matching the file name, unknown future `schema`, channel out of bounds, unknown
quirk/recipe/action/transport, confidence outside the vocabulary, missing provenance, French text
in UI fields (`install.needs` included).

A duplicate PC is **reported, not failed**: MIDNAM tables are organised in banks the format does not
capture, so a duplicate is an ambiguity (the pedal selects whatever bank it is on). It fails only if
the table claims `verified`, which an ambiguous table cannot be.

## 8. Propagation

- **Seed in the repository**: `library/pedals/` is what a new rack finds offline, without an
  account.
- **Pin, never follow latest**: a descriptor must never update itself under a pedal on a gig night;
  an update is proposed, never imposed.
- **Not built**: a live registry on golem.fm with a confidence ladder (`verified` by a maintainer,
  `reported` by N racks, `unconfirmed`), and the rack proposing to upload a descriptor once it
  passes `verify`. The exchange format, when built, belongs to [golemfm-protocol.md](golemfm-protocol.md).

Out of scope: calibration by audio measurement (send a PC, measure the returned pitch with the
tuner) — possible and complementary, not the chosen path.
