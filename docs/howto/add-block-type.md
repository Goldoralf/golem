# How to add an effect block type

**When:** you want a new entry in the Designer's "+" drawer (a plugin or an in-house JSFX that
processes a lane). Not for instruments (`vital`, `drumkit`) or service blocks (`rec`, `click`) —
those have their own code paths. Model to copy: `tremolo` (plugin) or `killswitch` (in-house JSFX).

## Files, in order

1. **`library/catalog/effects.json` → `effects[]`** — the single source of truth. Copy the
   `tremolo` entry:
   ```json
   {"type": "tremolo", "name": "Tremolo", "category": "modulation", "engine": "plugin",
    "plugin": "Calf Pulsator", "icon": "◢", "short": "Tremolo", "color": "#2ecc71", "glyph": "∿",
    "params": [{"id": "rate", "name": "Frequency", "min": 2, "max": 12, "default": 5,
                "unit": "Hz", "map": {"mode": "raw"}}, ...],
    "bench": "pending"}
   ```
   - `plugin` is tried first by `TrackFX_AddByName` (`add_block_fx`, `reaper/Scripts/golem_rig.lua`).
   - Each param's `name` is the **plugin's own parameter name**: `golem_rig` resolves knobs by name.
   - `map.mode`: `raw` writes the value with `TrackFX_SetParam` (use it for JSFX and anything with a
     known range), `norm` (default) searches the normalized value by dichotomy on the displayed
     value, `pow` writes a known taper. See `apply_block_params` in `golem_rig.lua` (enum/bool/`scale`/
     `curve: pct_db`).
   - `category` must be one of `categories`; check `role_categories` (which lane roles see that
     category) and `role_blocks` (a role listed there sees **only** the listed blocks — e.g. drums).
   - Optional keys in use: `roles`, `exp` (knob worth the EXP pedal), `depends`, `unique`,
     `conflicts`, `foot_suggest`. Document any new key in a `_xxx_comment` at the top of the file.
   - **Renaming an enum's labels** (same values): presets store the label, so add
     `renamed: {old: new}` on the param — `bridge/option_renames.py` rewrites old labels on load. Never
     reuse an old label as a new option with another meaning: old documents would become ambiguous.
   - **Bump `catalog_version`.** golem.fm reads it in the heartbeat (`rigstatus.catalog_version`)
     and pulls the catalog (`push-catalog` job, `GET /api/catalog-blocks`). See
     `docs/golemfm-protocol.md` for the sync contract.
2. **`library/catalog/effects-windows.json` and `effects-macos.json`** — every catalog type must be
   either in `effects` (a mapped name, or `{"unsupported": "why"}`) or in `unmapped` with a
   `family` (`golem-jsfx`, `reaper-jsfx`, `reaper-plugin`, `untested` + `why`, …). An entry under
   `effects` switches the block to strict resolution on that OS. `tremolo` is `unsupported` on both.
3. **`reaper/Scripts/golem_rig.lua` → `ADD_ALIAS`** — only when the plugin's name differs between
   installs/formats (LV2 vs VST3, `JS:golem/...` vs `JS: golem/...`). Keep **one line per type**
   with the braces on that line: `tools/check-block-stall.py` parses this table with a regex.
   `FX_INIT` (same file) sets one-shot values at insertion (e.g. a plugin default that clips).
4. **`app/designer-model.js`** — usually nothing: `hydrateBlockMeta` copies `color`/`glyph` from
   the catalog. `CAT_COLOR` is needed only for a **new category**; `BLOCK_COLOR`/`ICON` are seeds
   for the first paint. `GET /api/catalog-blocks` reads `effects.json` only, so golem.fm never sees
   a colour that lives only in the JS maps.
5. **`library/block-presets/<type>/<slug>.json`** — factory settings, modelled on
   `library/block-presets/tremolo/surf.json`: `{name, type, inst, factory: true, params}`.
   `"default": true` = applied when the block is added on a lane of that `inst` (one per type+inst).
   Without `factory: true` the file is treated as a user preset by `bridge/backup.py`.
6. **Plugin availability** — Linux: add the package to `provision/install-plugins.sh` (it runs under
   `sudo`; user plugins go to `$USER_HOME`, not `/root`). REAPER only scans new plugins **at
   startup**. In-house JSFX: see [add-jsfx.md](add-jsfx.md).

## Checks

- `python3 -m pytest tests/test_windows_table_complete.py tests/test_macos_blocks.py
  tests/test_windows_effects.py tests/test_catalog_bench.py -q`, then `./tools/check-cold.sh`.
- For a JSFX block, write a test like `tests/test_killswitch_block.py` (catalog param names,
  bounds and enums match the `slider` lines; no negative minimum).
- On the rig, with nobody playing (it sounds a test tone): `./tools/check-block-stall.py "<plugin>"`.
  Clean → remove `"bench": "pending"`. It freezes the engine → `"quarantine": "<measured reason>"`
  instead (never both: `test_catalog_bench.py`). Quarantine removes the block from the drawer,
  the AI vocabulary and the compile (`bridge/rig.py: _drop_quarantined`).
- Put it in an empty lane and rebuild twice (crash test), then `./tools/check-params.py --block <id>`
  to prove each knob write lands.

## Traps

- If neither `plugin` nor an alias resolves, `golem_rig` finally tries the **raw type name**
  (`attempt(block.type)`): a block can "work" by accident on one machine.
- "Installed" is not "validated": two shipped plugins (a guitarix detune, an echo) crashed or froze
  REAPER. Run the stall bench before letting golem.fm's AI propose the block.
- A JSFX slider with a negative minimum is bipolar for REAPER: never map it in `norm`.
