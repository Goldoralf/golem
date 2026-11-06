# Gear classifier — one source, two executions

> **Status: CODED** — `tools/classify.py` classifies TONE3000 captures (brand, device name, multi-amp pack); the rack runs it on its library, golem.fm runs a pinned copy on the market it scans.

## Why

A TONE3000 tone's `makes[]` lists the whole **recording chain** (microphone, speaker, load box,
preamp), not the captured device. Classified "by make", a Shure SM57 becomes an amp brand and a Neve
1073 used as mic preamp becomes an amp. The classifier reads the device through a **whitelist** of
brands and a **blacklist** of noise.

Each side runs the same module on its own data; neither pushes its result to the other. Copying the
tables would make two diverging implementations (`detect_brand`, `clean_amp_name`, `is_pack` are
logic as much as data); having the rack push a classified market would make a global table depend on
one owner's personal TONE3000 token and on a rack being on.

## Contract

1. **`tools/classify.py` is self-contained**: stdlib only (`sys os json re collections`), nothing
   from the bridge, nothing written at import. `main()` (rewriting the rack's catalogue files) concerns
   the rack only.
2. **Frozen signatures**: `detect_brand(makes, title, gear)` · `clean_amp_name(makes, title, gear,
   brand)` · `is_pack(makes, title, tid)` · `clean_title(title)` · `legendary()`.
3. **`CLASSIFIER_VERSION`** (integer, top of the module, currently 2): incremented on every change of
   **result** (table, pattern, rule). The rack sends it in the heartbeat, the pairing identity and the
   pushed catalogue, next to `catalog_version` (`rigstatus.classifier_version()`). A mismatch means
   "golem.fm is behind", not a failure. See [golemfm-protocol.md](golemfm-protocol.md).
4. **`tools/classify-data/legendary-amps.json`** travels with the module; `legendary()` returns it
   flat (`{make, search, style, tags, era, note, category, category_label}`).
5. **On the golem.fm side**: a **scripted** copy per release, pinned by ref, commit and sha256, never
   copied by hand — same ritual as `effects.json`. golem.fm applies it per scanned tone (`amp`,
   `amp-cab`, `cab`, `pedal`, `outboard` gears, NAM format): drop packs → brand → device name →
   aggregate by name → `curated` from `legendary()`.

## Rack usage

```
./tools/classify.py            # classify and write
./tools/classify.py --report   # print the report, write nothing
```

For each tone of `library/catalog/tones-index.json` (entries with `parent`, derived from a pack
split, are frozen): sets `brand`, `pack` (multi-amp pack → badge) and `amp` (device name, or the
title for a pack); writes `library/catalog/brands.json` (grouped view for the app) and
`stats.by_brand`. Fallback brands: `Cabs / IR`, `Custom / Other`. Tests:
`tests/test_classify_outboard.py`.

## Rules

- **One vote per text** (each make, plus the title): its most specific brand in table order
  (`_brand_of`, `_vote`, `_brands_of`); ties go to table order. "Specific before generic" applies
  *within* one make, not across makes: "Revv Generator 120 MK III" votes Mesa (MK) *and* Revv,
  "Revv RV30" votes Revv → Revv wins.
- **Noise depends on the nature looked for** (`_noisy_for(gear)`):
  - **amp**: microphones, cabs, pedals and chain preamps are noise — but not the word "overdrive"
    (Dumble Overdrive Special, Soldano Super Lead Overdrive);
  - **pedal**: pedal patterns *are* the device ("Ibanez TS808 Tube Screamer" is the name);
  - **outboard**: CAPI/VP28-type names are the device.
- **Cab makes do not vote** for an amp or a pedal (`CAB_MAKE`: 4x12, V30, greenback, load box…);
  **pedal makes do not vote** for an amp (`PEDAL_MAKE`). Microphones stay in the text: a make can be a
  whole chain that also names the amp.
- **Outboard** (`gear: outboard`): table `OUTBOARD_BRANDS`, clones (BAE, Warm Audio, Stam, RND,
  named 1073 clones) **before** Neve because they carry the number 1073; "Rupert Neve Designs" is RND
  even if a neighbouring make says "Neve"; "bus comp" is not SSL. For any other gear these names are
  noise for the device name (`PRE_NOISE`) — but not the word "preamp" (a bass DI-preamp is the amp of a
  bass capture).
- **Device name**: prefers a make that votes for the detected brand, then the richest one; noise
  (`NOISE` = mic + cab + pedal patterns) is excluded.
- The Mesa "MK" pattern is limited to Mesa series (IIC+, IV, V): MK II/III exist at Revv, Orange,
  Blackstar.
- `MULTI_PACK_IDS`: known multi-amp packs by TONE3000 id.

## Known limits

- A multi-amp pack has no brand; the one shown is the majority brand (a badge, not an identity).
- A single make naming a cab can stay as the name of a head.
- Gain settings in titles (`SETTING 1..3`, `Midboost 1..5`) are read by another module
  (`app/capture-gain.js`), see [blocks-doctrine.md](blocks-doctrine.md).
