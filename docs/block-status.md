# Block status

> **Status: PARTLY CODED** — every block of a preset gets a state (`ready`, `download`, `unavailable`,
> `empty`) computed by the rack, shown on screen and published to golem.fm; captures, plugins,
> quarantine and drum kits are judged. sfz/Dexed banks, Vital presets and samples are **not judged yet**.

Related: [patches.md](patches.md) §8 (captures of a received patch) · [factory.md](factory.md) ·
[blocks-doctrine.md](blocks-doctrine.md) (quarantine) · [plugins.md](plugins.md) ·
[golemfm-protocol.md](golemfm-protocol.md) (`caps`, `block-status` job) ·
[library-loans.md](library-loans.md).

Code: `bridge/blockstatus.py`, `bridge/routes_blocks.py`, `reaper/Scripts/golem_fxinventory.lua`,
`golem_rig.lua` (observed plugins), `bridge/rig.py` (`_usable`, `_wrong_kind`, `nam_unreadable`), UI
`app/designer-blockstatus.js`.

---

## 1. Rule

A preset or patch arriving on a rack may reference what this rack does not have: a capture (NAM, IR)
never downloaded, a plugin absent from this machine (common across Linux, Windows and macOS), or a
quarantined block. **A block that is not `ready` is removed from the rig explicitly and shown struck
through. Never silent, never replaced without asking.**

## 2. States (`blockstatus.block_state`)

| State | When | Screen |
|---|---|---|
| `ready` | everything is there | normal tile |
| `download` | the capture is missing here but a source knows it: golem.fm (own packs or a loan) or TONE3000 (a `t3k:<id>` or numeric ref) | struck tile **⬇** + size when known |
| `unavailable` | nothing can bring it: plugin absent from this machine, quarantine, file of the wrong nature or unreadable format, capture unknown everywhere, file missing on disk | struck tile **✕** + reason |
| `empty` | capture block with no capture chosen | ∅ — tap to choose |

Every non-`ready` state carries `why` (English, displayed) and `reason`:

| `reason` | Meaning |
|---|---|
| `plugin` | plugin not installed on this machine; a type marked `unsupported` in this desktop OS's table (`effects-windows.json` / `effects-macos.json`): `why` is `LINUX_ONLY_WHY` ("only available on a Linux golem"), `linux_only: true`, the table's measured reason in `detail`; a `vst-host` block outside Windows/macOS; a drum kit that is absent or whose engine/samples are missing here (`_drumkit_state`, judged per kit used by the block and by each scene) |
| `quarantine` | the type (or a `vst-host` plugin, by the catalogue or by the first-use test) is quarantined; `why` is the generic English sentence `QUARANTINE_WHY`, the catalogue's measured reason goes in `detail` |
| `trial` | Linux, `vst-host` only: a plugin never tried on this rack is first loaded in a separate REAPER (`bridge/plugin_trial.py`, [`platforms.md`](platforms.md) §6.1) and is kept out of the rig until then; `why` = "being tested before it plays — a few seconds", `testing` says whether the test runs now. A plugin the test refuses becomes `quarantine`, the measured reason in `detail` |
| `engine` | the **active audio engine** does not carry the feature this block type belongs to (`config/engines/features.json` key `blocks`, the engine descriptor's `capabilities` ≠ `yes`; `blockstatus.engine_gate`). `why` = "not available on <engine> yet" (`planned`) or "<engine> can't play this block" (`no`); `engine_cap` = the declared value. REAPER declares every feature: never seen there |
| `capture` | capture missing, empty, or of the wrong nature (`rig._wrong_kind`) |
| `format` | the capture is present and correct, but this machine's NAM engine cannot read its format (`rig.A2_DESKTOP_WHY`): an A2 capture (`architecture: SlimmableContainer`, read in the file by `rig.nam_architecture`, never from its name) on Windows/macOS. Downloading it again would not help, so the UI does not offer "Download" |

**Playable twin** (`format`): TONE3000 publishes each A2 retraining next to its original capture under
the same name. "⬇ Download the playable version" (`POST /api/blocks/playable`) adds the non-A2 twin
(same name up to the size suffix — Feather, Lite… —, standard first) to the catalogue pack;
`resolver.playable_twin` plays it on machines that cannot read A2. The document is **not** rewritten:
on Linux the same patch plays the A2. No twin on TONE3000 → the error says so and "Pick another
capture" remains.

## 3. Sources of truth

- **Captures**: `resolver._resolve` **plus** the actual existence of the file. An index entry whose file
  was deleted is `download` or `unavailable`, and the compile drops it too (`rig._drop_empty_capture`).
  Nature: `rig._wrong_kind`, the guard shared by the compile, the acks and the MCP `resolve`.
- **Plugins**: what **REAPER** scanned, not what a package claims. `golem_fxinventory.lua` enumerates
  `EnumInstalledFX` (read-only, nothing instantiated) into `presets/.fx-inventory.json`, at watcher start
  and on the `fxinventory` command. The bridge tries the same names as `golem_rig`, in the same order
  (`blockstatus.candidates`): `effects.json` `plugin`, then `ADD_ALIAS` read from `golem_rig.lua`'s
  source, then the type. On Windows/macOS the desktop override tables
  (`library/catalog/effects-windows.json`, `effects-macos.json`) apply and are strict; `amp`, `amp-nam`,
  `cab` resolve to `VST3: NeuralAmpModeler`.
- **Observed beats predicted**: `golem_rig` records each block type it could or could not insert in
  `presets/.rig-plugins.json` (`{types: {<type>: {ok, name, at}}}`). That record wins over the
  inventory, also for non-plugin engines.
- **Unknown is said**: no readable inventory (REAPER never started, too old) → plugin state unknown
  (`caps.inventory: false`); nothing is struck on ignorance. Engines without a declared plugin name
  (rs5k, sfizz, dexed, b3…) are unknown unless observed.
- **Quarantine**: `rig.quarantined_types()` / `rig.quarantined_plugin()` (see
  [blocks-doctrine.md](blocks-doctrine.md) §4).

## 4. Screen

- When the Designer loads a preset with missing blocks: a banner "N blocks missing — ⬇ Download all
  (size)". "Download all" fetches only `download` blocks; `unavailable` ones are counted separately
  ("not available here").
- Tapping a struck tile opens a sheet: **Download** (if `download`, size and source shown), **Replace**
  (blocks of the same category available here for this role, and for a capture the usual capture
  picker with the name-based suggestion first, §6), on Windows/macOS **Use your own plugin (VST Host)**
  (the add drawer opens on its VST Host list only; the chosen plugin takes the block's place, same purge as
  Replace), **Keep it off** (the block stays struck here and
  will play on a rack that has it).
- Downloads run in the background. When they finish, if the preset is still in the Designer sandbox the
  sandbox is re-applied; else if it is the current preset it is recalled — the block starts sounding with
  no other gesture (`routes_blocks._replay`).
- What is downloaded from TONE3000 enters the rack catalogue and syncs to golem.fm as usual (except a
  loan, which never syncs).

## 5. API

| Route | Response |
|---|---|
| `GET /api/blocks/status?preset=<id>` (no `preset`: the sandbox) · `POST /api/blocks/status` `{id?, preset?: doc}` | `{preset, blocks: [{lane, id, type, label, state, why, reason, detail?, source?, uid?, tid?, bytes?, ref?, title?}], summary: {missing, download: {n, bytes, unknown}, unavailable, empty}, caps: {inventory}}` |
| `POST /api/blocks/fetch` `{id?, preset?, blocks?: [id]}` | starts the background download of `download` blocks (all if `blocks` absent; each uid fetched once). `{started}`; `409` if one is running |
| `GET /api/blocks/fetch` | `{running, done: [{block, msg}], failed: [{block, why}], total, preset}` |
| `POST /api/blocks/playable` `{block, id?, preset?}` | `format` reason: installs the non-A2 twin, re-applies. `{ok, added, status}`; `401`/`502` with a readable `error` |
| `GET /api/blocks/alternatives?type=<t>&role=<r>` | `{category, blocks: [{type, name}]}`: same category, available here, not quarantined, not `virtual`/`mode` engines, filtered by `role_blocks` and the block's `roles` |
| `POST /api/blocks/suggest` `{block}` | `{suggestion}` (§6) |
| `GET /api/system/fx-inventory` | `caps` + `plugins` (inventory size) |
| `POST /api/system/fx-inventory` | asks REAPER for a new inventory (`fxinventory` command) |

Sources of a `download` (`_fetch_one`): golem.fm `uid` → `tones_jobs._install`; TONE3000 `tid` →
`tones_jobs._t3k_install`.

## 6. Name matching: suggested, never applied

- A capture block **with** a `ref` (catalogue id or `t3k:<id>`) that is missing here is installed before an
  audition of a received patch (golem.fm packs, then loans, then TONE3000 with the rack's account) —
  it is the user's choice, not a guess. Inline limits: 48 MB per pack, 90 s for the whole settlement
  (`tones_jobs._INLINE_MAX_BYTES`, `_SETTLE_BUDGET_S`); beyond, the block stays `download` for the
  screen to offer.
- A capture block **without** `ref` is `empty`. The name match (`blockstatus.suggestion`, through
  `patches.match_capture_family`: rack library first, then the golem.fm manifest) is returned as
  `suggested[]` — `{block, type, label, ref, uid, title, score, source: rack|golem.fm, retyped?}` — in job
  acks and as the first proposal of the Replace sheet. It is **never written into the document**. `ref`
  is the rack's catalogue id; `uid` is the form golem.fm resolves (`t3k:<id>` or `local:…`); `retyped` is
  the amp type the capture implies (a head on `amp` → `amp-nam`, an amp+cab capture on `amp-nam` → `amp`).
  `matched[]` stays in acks, always empty, for older readers.
- A block whose state is `unavailable` carries `alternatives: [{type, name}]` in `preset_status.blocks[]`
  (the `block-status` job ack and `GET /api/blocks/status`): `blockstatus.alternatives(type, role)` — the
  same category, the plugin present here, not quarantined, allowed for the lane's role (none on the config
  lanes `gen`/`rec`/`arr`), at most 8 (`ALTS_MAX`), in catalogue order, **without** MIDI outboard blocks (`engine: midi`, e.g.
  `whammy-dt`): the rack knows its MIDI interface, not the pedal behind it. It is the Replace sheet's list
  minus those, and like `suggested[]` it is a **proposal, never applied**. `[]` means nothing here can replace
  it. Agreed with golem.fm on 2026-10-28 (its D2).

## 7. What the rack publishes

`rigstatus.light()` carries `caps` (`blockstatus.caps()`):

```json
{"os": "linux", "engine": "reaper", "engine_version": "7.27", "inventory": true,
 "inventory_at": "2026-09-30T10:12:03Z", "unavailable": ["reverb-shimmer"],
 "quarantine": ["detune", "delay-echo", "pitch"], "nam_unreadable": [], "compo_bed": true}
```

- `unavailable`: plugin block types absent here (inventory or observation).
- `quarantine`: quarantined types.
- `nam_unreadable`: capture architectures this machine's NAM engine cannot play (`rig.nam_unreadable`):
  `["SlimmableContainer"]` on Windows/macOS, `[]` on Linux. An empty list is authoritative.
- `separation`: stem separation capabilities, only when an engine is installed (`docs/separation.md`).
- `compo_bed`: `true` — the rack plays the bed of an armed take (`docs/compo.md` §12); golem.fm sends a
  `bed` only to a rack that publishes it.

With `captures` (also in the heartbeat), golem.fm can tell "N elements to download on the rack" before
sending anything. The `block-status` job (a patch document, or `{preset: <id>}` including `patch:<id>`)
returns the rack's own computation (`preset_status` + `caps` + `suggested`).

Expectations on golem.fm's side (send the `ref`/`model` chosen by listening, filter its vocabulary by
`caps.unavailable` and `caps.quarantine`, read `suggested[]`) are part of
[golemfm-protocol.md](golemfm-protocol.md).

## 8. Not built

- sfz/Dexed banks, Vital presets and samples are not judged: the compile still skips a missing one
  silently.
- Declared plugin names for non-plugin engines (rs5k, sfizz, dexed, b3), so their state can be
  predicted rather than only observed.
