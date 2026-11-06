# Data and reference pitfalls

Presets, patches, catalog entries and capture references travel between the rack, the app and
golem.fm. The dangerous bugs here are not malformed data — validation catches those — but well-formed
data of the wrong nature, and guards that exist but are bypassed. They all end in silence.

---

## Right shape, wrong nature

**Symptom.** A lane is silent while every check is green: the reference resolves, the file exists,
the block status says "ready".

**Cause.** A reference was valid in form and pointed to something of the wrong kind. Observed
variants: a pack uid (`t3k:44209`) where a catalog id (`44209`) was expected; one id field in place of
another; an amp+cab NAM capture (`.nam`) placed on a `cab` block whose convolver only loads `.wav`/
`.flac`; an A2 NAM capture on an OS whose core cannot read A2 (dry signal, no error).

**Rule.** Checking that a reference EXISTS says nothing about what it CONTAINS. Wherever a reference
becomes a file, check the nature (extension, file header, architecture field) as well as presence,
with one shared function used by every path (compile, acknowledgement, block status, MCP `resolve`).

**Detect.** Block status `unavailable` with a reason; `unresolved[].why` in the export/ack; MCP tool
`resolve {type}`.

**Code.** `bridge/rig.py` `_wrong_kind`, `_wrong_kind_for_os`, `CAPTURE_EXT`, `_prep_block`; used by
`bridge/compile_rig.py`, `bridge/blockstatus.py`, `bridge/tones_jobs.py`, `bridge/mcp.py`.

---

## Read the nature, do not trust a declared one

**Symptom.** A guard on nature passes a wrong file because the nature field itself is wrong.

**Cause.** A "kind"/`gear` field was inferred upstream from context (where the user was browsing when
installing) instead of from the content, then copied downstream, where guards trust it.

**Rule.** At install time, READ what can be read (the extension of the file actually installed);
a declaration never contradicts a reading. What cannot be read (e.g. `amp` vs `amp-cab`, both `.nam`)
stays declared, and the code says so explicitly.

**Code.** `bridge/tones_sync.py` `kind_of` (IR files make a `cab` whatever `gear` says),
`bridge/tones_jobs.py` `_entry_from_pack` (logs "declared X but files are IRs"), `bridge/rig.py`
(comment on what stays declared).

---

## A guard nobody consults is not a guard

**Symptom.** A bypass/quarantine/format guard exists and is tested, yet the faulty item still plays.

**Cause.** A second path (e.g. the core renderer re-resolving the reference) does its own lookup and
never reads the guard's verdict.

**Rule.** Put the verdict on the data (a flag on the block) and make every consumer filter on it;
grep for every other place that resolves the same reference.

**Code.** `bridge/compile_rig.py` (core builders filter `usable = [b … if not b.get("_wrong_kind")]`).

---

## Be suspicious of an exception that explains why it is not checked

**Symptom.** A hole in a guard survives reviews.

**Cause.** A commented exclusion ("bundle: not judged", "algorithmic amp") reads as a reasoned
decision and is approved; an uncommented one would have been questioned. A comment that no longer
describes its era manufactures the justification for the next hole. When no justification exists,
it is tempting to invent one, and a freshly invented one does not get re-read.

**Rule.** Treat every "this case is excluded because…" in a guard or a test as a finding to verify
against the current code. Update or delete comments when the thing they describe changes. Look up
the actual table (e.g. `MODEL_GEARS`) instead of rewriting it from memory.

**Code.** `app/designer-model.js` `MODEL_GEARS` (block type → accepted capture gears).

---

## A rule can add something to the signal that no document contains

**Symptom.** Two cabinets in series ("a blanket over the amp"), while no preset and no patch contains
a second cab — so every document-based duplicate detector is blind.

**Cause.** A compile-time rule ("isolated amp → blend a default cab") was right for a HEAD and wrong
for a full rig (an `amp` block, "Head+Cab", or a capture declared `gear: amp-cab`).

**Rule.** When a rule adds anything to the signal, state what it is based on and check that basis
holds for every case it handles.

**Code.** `bridge/compile_rig.py` `_carries_cab`, `DEFAULT_CAB`, `_render_core_for` / `_native_core_for`.

---

## One source, and the verdict shown where the user acts

**Symptom.** The screen says IN 2, the engine plays IN 1; a lane is green while not mounted; a veto
uses an old copy of the input map.

**Cause.** The same fact computed by two paths (number vs name binding), a factory that reads the card
but is never called, an engine verdict (`rig_unmounted`) that no screen reads, a startup copy read
instead of the file.

**Rule.** One source per fact; derive, never copy. A binding (role, nth) wins over a raw number and
an unresolvable binding means "not mounted", never a silent fallback. Show the engine's verdict on the
screen where the user acts. New documents are born from the current card through a single gate.

**Code.** `bridge/preset_view.py` (`_norm_lane`, `_first_of_role`), `bridge/scene_bake.py`
`_one_lane_per_input`, `app/designer-model.js` (`seatPatchLane`, `alignBoundInputs`),
`bridge/inputmap.py`. Reference: `docs/audit-2026-10-10-entrees.md`.

---

## Hidden couplings that a grep does not show

- Block ids are addressed flat across lanes (scenes, scene knobs, arrangement cues, foot): an id must
  be unique per preset, and duplicating a lane must re-id its blocks.
- Anything indexed by ROLE (meters, mode chips, input veto, mixer levels) conflates two inputs of the
  same role; it stays invisible until a second instrument of that role exists.
- A field the UI lets the user set but that downstream code never reads is decorative — and a silent
  bug. When adding a field, find its reader.
- The physical-input → track binding must live in the plan, not only in the REAPER project.


---

## The Designer edits the sandbox, not the preset file

**Symptom.** A hand fix to `presets/<id>.json` does not show in the Designer and is overwritten at the
next save.

**Cause.** The Designer's edit buffer is `presets/.sandbox.json`, persistent across reloads; it wins on
the next save.

**Rule.** Change a preset through the app path (`POST /api/sandbox_apply` or the UI), never by editing
the file while the Designer runs.

**Code.** `bridge/app.py` `sandbox_apply`; `GET /api/sandbox`.

---

## A mass rename of a compared value breaks silently

**Symptom.** A feature stops working with no error after a search-and-replace (e.g. publishing a
preset no longer uploads its private captures).

**Cause.** A value renamed in one place (a comparison) but still written with the old value elsewhere
(an exporter), or stored in existing files.

**Rule.** A value that is written in one place and compared in another is a protocol: write the new
value, read both (old and new), and add a test that round-trips writer → reader.

**Code.** `bridge/preset_export.py` (`STORE_SOURCE`, `STORE_SOURCES`), `bridge/tones_sync.py`
`publish_preset`, `tests/test_store_source.py`.

---

## Never commit machine state

**Symptom.** Pull requests full of unrelated diffs; a fresh install inherits one machine's card,
setlist or roles; a `git pull` refuses or deletes local files.

**Cause.** REAPER rewrites `sets/*.rpp` while running; presets change while playing; mappings, cards
and input maps carry one machine's measurements.

**Rule.** The repository versions recipes and seeds, not state. Defaults live in code
(`store.*_DEFAULTS`, `inputmap._seed`); machine files are git-ignored. When files leave version
control, protect existing installs across the update.

**Code.** `.gitignore`, `bridge/local_state.py`, `tools/local-state.py pull`.

---

## A browsing preference must not rewrite a pinned reference

FIXED 2026-11-03.

**Symptom.** One factory capture (tone 2282) failed with "no model selected" on every retry.

**Cause.** The factory pinned the A1 model 75210. Where A2 plays, `routes_t3k._order_models` drops an
A1 that has an A2 twin of the same name — a browsing preference — and `_install_worker` then filtered
the requested ids out of that list: nothing left.

**Rule.** An id a preset asks for is a reference: it installs if TONE3000 has it, whatever the A1/A2
ordering says. Changing a pin from A1 to A2 is a sound decision made in `library/factory` (then
`tools/gen-factory-history.py`), never a fallback by name in the resolver. Decision 2026-11-03: the
5150 II clean pin moved to its A2 twin 419322 (`factory-guitar-modern-metal`, `factory-metal-for-all`);
it was the only factory A1 pin with an A2 twin (IRs appear in both lists with the same id — not twins).

**Code.** `bridge/routes_t3k.py` `_install_worker`, `tests/test_t3k_factory_download.py`.
