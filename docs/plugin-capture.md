# Capturing a plugin as NAM

> **Status: PARTLY CODED** — capturing a VST block into NAM captures and IRs from the Designer drawer works on
> Windows and macOS (`bridge/plugin_capture.py`); capturing hardware gear (amp or pedal through the sound card)
> is not built.

**Control capture (experimental, coded).** The VST drawer also offers **With controls**: multiple
joint knob settings train one HyperWaveNet. The captured block can prepare ordinary NAM settings
at arbitrary in-range control values; it does not depend on the source VST for playback. This is
not audio-rate knob automation. See §9 for the workflow, validation and compatibility limits.

A NAM capture is always the same recipe: the standard training signal (v3, 190 s, 48 kHz) goes through the
device, the output is recorded, a model is trained on the pair. With a **plugin** there is no cable, no sound
card and no latency to measure: the render is offline, sample-aligned and repeatable. The point is portability:
a sound built on a Windows or macOS plugin plays on a Linux rack that does not have the plugin.

Captures are made **on the musician's own Windows or macOS computer** (where the plugin and the GPU live), never
on the rack. The rack only plays them. The routes refuse other platforms (`409 "Plugin captures are made on
Windows or macOS"`).

Hardware capture (a "Capture your gear" path with a cabling diagram, level check and on-rack training) was
designed but never built: nothing in the code records gear for training.

Related: [`plugin-recipes.md`](plugin-recipes.md) (how recipes are proposed and validated),
[`audit-2026-10-01-parite-coeurs-os.md`](audit-2026-10-01-parite-coeurs-os.md) (why WaveNet, not A2),
[`library-loans.md`](library-loans.md), [`golemfm-protocol.md`](golemfm-protocol.md).

---

## 1. What can be captured

| Block in the plugin | Captured? | How |
|---|---|---|
| amp, drive/fuzz pedal, preamp | yes, NAM | non-linear with short memory: what NAM models. **One setting = one capture**: the knobs are frozen |
| cab, EQ | yes, exactly | linear: an impulse through it **is** the IR (`.wav`), no training |
| compressor | roughly | attack and release last tens of ms, longer than what the model sees |
| chorus, phaser, delay, reverb, pitch, tremolo | no | time-varying or long memory. Delay, reverb and gate are **translated** into golem blocks (§5); modulation and pitch before the amp block the capture |

**Model format.** WaveNet "standard" (the official `nam_full_configs/models/wavenet.json` of the pinned
trainer), never A2: A2 does not play on Windows. The trainer writes the new `.nam` schema (`version 0.7.0`)
that the Windows NAM VST3 cannot read — it passes the guitar through dry, with no error. So every capture is
rewritten to the old schema (§4).

## 2. Recipes

A recipe says, for one plugin (exact REAPER name, e.g. `VST3: Example Amp Suite (Example Vendor)`), what to switch
off before each render, by **parameter name and displayed value** (`min`/`max` = end of travel), re-read before
the render. `plugin_capture.recipe_for(plugin)` reads, in order:

1. a recipe validated on this rack (`plugin_recipes.validated_recipe`, see [`plugin-recipes.md`](plugin-recipes.md));
2. the repository seed `library/catalog/plugin-captures.json` (`plugins.<name>`). One plugin ships there today.

Recipe fields:

| Field | Meaning |
|---|---|
| `vendor` | shown in the panel and copied into the catalog `brand` |
| `full.label`, `full.gear` | the single-capture mode and its nature (`amp-cab` if the plugin cab is in the sound) |
| `full.off` | parameters to switch off for the full capture (gate, time FX) |
| `full.keeps`, `full.drops` | shown in the panel |
| `full.refuse[]` | effects that **block** the capture: `label`, `kind`, `where`, `when`, optional `detail` |
| `full.refuse_why` | the sentence shown after the blocker names |
| `full.captured[]` | what the capture will contain (`label`, `when`, `detail`) |
| `split.parts[]` | one-capture-per-effect mode: `id`, `label`, `gear`, `block`, `when`/`when_any`, `off`, `ir: true` for the cab |
| `translate[]` | sections rebuilt as golem blocks: `block`, `at` (`before` the capture or after), `params` (`{golem_param: {from, scale?, as?}}`), `when`/`unless`, `show`, `detail`, `loss_if`/`loss`, `approx` |

Conditions (`_applies`): `when` = all match, `when_any` = at least one, `unless` = none, on the plugin's
**displayed** values. `when` carries the **section** switch as well as the effect switch: an effect "Active"
inside a disabled section does not play and does not block.

`detail` (`_detail`) renders a setting as the plugin shows it: `{from, as: "text"}` or
`{from, label, scale, unit}` → "mix 39 %".

**A plugin without a recipe** is captured whole, as set (`generic_recipe`, nothing switched off). The musician
must confirm they checked the plugin (`confirmed: true`, "only drive, amp, EQ and cab may be on") and say whether
the plugin's cab is in the sound (`gear: "amp-cab" | "amp"`). The nature is declared by them, never guessed. No
split and no translation without a recipe.

## 3. The check panel (`plugin_capture.check`)

`GET /api/vst-host/capture?block=&plugin=` returns `{job, setup, check}`. `check` is the panel:

- `blockers[]` — every `refuse` entry that applies, named with its place and setting. **golem switches nothing
  off that blocks**: the musician turns the effect off in the plugin window and taps Done; the drawer re-checks
  (on Done and when focus returns).
- `captured[]`, `rebuilt[]` (translated blocks, each with the `loss` it implies when `loss_if` applies),
  `kept`, `dropped`, `gear`, `split[]` (parts available now).
- `source` — `{from: "golem.fm", shared, validated_at}` for a validated rack recipe, `{from: "built-in"}` for the seed.
- `env` — `environment()`: `{ready, missing[], device, gpu, home}`.
- `ok: false` + `why` when something blocks or the machine lacks its tools; without a recipe:
  `recipe: false, needs_confirm: true`.

## 4. The job (`plugin_capture.start` → `_worker`)

`POST /api/vst-host/capture` `{block, plugin, patch, mode: "full"|"split", name, dest: "new"|"replace",
new_patch, confirmed, gear}`. One job at a time (the GPU and the capture REAPER are not shared).
`POST /api/vst-host/capture/cancel` stops it. State in `status()`: `state` ∈ `render`, `train`, `test`,
`install`, `done`, `error`, `cancelled`, plus `msg`, `warning`, `self_esr`, `result`.

Per part (one part in `full`; in `split`, the parts whose `when` match):

1. **Render** (`render` → `bench_run`) in a **separate REAPER** (`-newinst -cfgfile`, no audio device, the
   machine's plugin list, licence and `verchk=0` copied so no modal dialog blocks the script). The exact native
   state of the block (`vst_chunk`, read from the playing instance via `routes_content.vst_host_state`) is set,
   then the part's `off` overrides are written and re-read. The render happens **in the same session** after the
   plugin has finished restoring (saving and re-opening the project lost the overrides); the source is inserted
   with `InsertMedia` (a long file built with `PCM_Source_CreateFromFile` rendered silent). The playing REAPER
   is never touched. Silence → error.
2. **Level.** The render is float: a peak above 1.0 is not clipping (a boost pushes the amp). The target is
   brought to −1 dBFS and the removed gain (`output_db`, refused above 20 dB) is given back by the golem block's
   `output` parameter — except on blocks the compile normalizes (`compile_rig.NORMALIZED_TYPES`).
3. **Self-ESR** (`self_esr`). The v3 signal plays the same 9 s passage twice; a plugin with no time effect renders
   them identical. Above `SELF_ESR_MAX` (0.01, the NAM trainer's threshold) the job carries a `warning`
   ("…a chorus, delay, reverb or other moving effect is probably still on…") — a warning, never a stop.
4. **Train** (`train`): WaveNet standard, 100 epochs, low priority, on the GPU if it answers (CUDA, MPS) else
   the CPU (`trainer_python` asks torch; a CUDA build without a driver silently falls back to CPU). The NAM
   trainer's own checks are never disabled.
5. **Convert** (`legacy_nam`): rewrite to the old schema (`version 0.5.4`); the original is kept as
   `capture-v07.nam` (the NAM 0.13 library no longer reads the old schema, so measurements use it). Any real new
   feature (FiLM, groups, bottleneck, gating, mixed activations or kernels) refuses the conversion.
6. **Playback check** (`playback_check`): the machine's real NAM VST3 renders a test guitar through the converted
   file (gate and tone stack off, as the rig loads it). Pass = null ≤ −18 dB against the model **and** 10 dB
   better than against the dry guitar. A silent render is retried up to 3 times (offline renders sometimes start
   before NAM has loaded its model).
7. **Cab part** (`capture_ir`): an impulse through the plugin with only the cab on; the output, aligned on its
   onset, 0.5 s with a fade, is the IR. No training.
8. **Measure** (`test`): the chain of captures (NAM → NAM → IR convolution, plus `gain` stages) against the whole
   plugin on a synthetic guitar and a sweep never seen in training: level, equalized null, worst third-octave.
9. **Install** (`install`): `assets/models/captures/<slug>/<slug>.nam` or `assets/irs/captures/<slug>/<slug>.wav`,
   catalog entry `cap-<slug>` with `gear` **from the recipe** (what was rendered, not guessed),
   `source_group: "plugin-capture"`, `creator: "golem plugin capture"`, and `capture{plugin, patch, block, mode,
   part, set, train, test, at, private: true}`.

**Resume.** A job that failed after training reuses the latest unfinished work folder of the same name and mode
(`<train_home>/../captures/<slug>-<mode>-<stamp>`): trained parts are kept. If the plugin state changed since
(`state.json` chunk differs), everything is redone in a new folder.

**Split vs full.** Split gives the pedal (`pedal-nam`, not normalized: the head receives the level it was
trained on), the head without cab (`amp-nam`) and the cab as an exact IR. It measures more faithful than one
capture: one network learns a cab badly, an IR does not. The drawer preselects split when the recipe allows it.
In full mode the block follows the nature: `amp-cab` → `amp` (Head+Cab), `amp` → `amp-nam`, so the compile never
adds a second cab.

## 5. Using the result (`plugin_capture.replacement`)

`GET /api/vst-host/capture/replacement?block=&plugin=` returns `{blocks, notes}`: translated blocks `at:
"before"`, the captured core blocks, then the other translations (delay, reverb…). Values come from the plugin's
**displayed** parameters, clamped to the golem block's range (`library/catalog/effects.json`). Each approximate
translation adds a note (different reverb engine, untranslated low cut or delay modulation…).

Each core block is an ordinary `amp` / `amp-nam` / `pedal-nam` / `cab` block — no new engine type, so Linux, the
compile and golem.fm read it — with a `label` and
`origin {kind: "vst-capture", plugin, patch, mode, part, at, null_db}`. The Designer shows it with the VST icon
◈ and its name; its sheet says where it came from (`app/designer-sheets.js`). A block without `origin` is still
recognized: the origin is **read** from the catalog entry's `capture{}` (`app/page-designer.js`).

**Destination**, chosen before "Start capture" in the drawer form (`app/designer-vst-host.js` `NamCapture`:
*Capture* one / per effect, *Name*, *Result*) and kept in the job, since a capture lasts 10–17 min:

- **New patch** (default, prefilled "<patch> — capture"): `page-designer.js` `forkWithBlocks` creates a new
  document, already modified, with no inherited `patch_id` or `origin`. The open patch is never written.
- **Replace in this patch**: the VST block is replaced in place.

## 6. Installing the tools (`plugin_capture.start_setup`)

When `environment().ready` is false the drawer offers "Install capture tools" (`POST
/api/vst-host/capture/setup`, background job, `setup_status()`). It installs into `train_home()`:
`%LOCALAPPDATA%\GoleM\nam-train` (Windows), `~/Library/Application Support/GoleM/nam-train` (macOS),
`~/.cache/golem-build/nam-train` (Linux bench); `GOLEM_NAM_TRAIN` overrides.

- an isolated Python venv; torch CUDA (`venv-cuda`) if `nvidia-smi -L` lists a GPU (Windows;
  `GOLEM_NAM_FORCE_CPU` disables), else CPU torch (`venv`); macOS gets standard torch, which carries MPS;
- `neural-amp-modeler` **pinned** to `NAM_VERSION` (0.13.0);
- the v3 signal `v3_0_0.wav`, refused unless its MD5 is `V3_MD5` (the trainer recognizes it by MD5);
- `cfg/wavenet.json` from the same trainer version.

## 7. Captures stay private

A plugin capture syncs to the account's library and can be lent to the band
([`library-loans.md`](library-loans.md)), but it **never goes to a public store**, nor does a preset that depends
on it: commercial plugin licences forbid it. Rack side:

- `tones_sync._provenance` adds `provenance {kind: "plugin-capture", plugin, vendor, os, at}` and
  `private: true` to the pack (`provenance`, not `origin`, which is already a string on patches);
- `tones_jobs._private_from_pack` restores `private`, `capture{plugin, at, os}` and
  `source_group: "plugin-capture"` when the pack is installed on another rack — even from `private` alone.

The cloud treats `private` as a ratchet; see [`golemfm-protocol.md`](golemfm-protocol.md).

## 8. Repair and benches

- `plugin_capture.fix_library()` rewrites captures installed in the new schema to the old one under a new name
  (`…-std.nam`, so the engine reloads), each verified by `playback_check`.
- `recall.scene_shape` compares the **resolved file** of capture blocks, not just `ref`/`model`: a file replaced
  under the same id forces a rebuild instead of a state switch that would keep the old model loaded.
- `tools/capture-plugin.py` (`render` / `train` / `test`) is the Linux bench: any mono LV2 rendered offline by
  `tools/lv2_render.c` (knobs by port index), trained in `~/.cache/golem-build/nam-train`, measured against a real
  DI and a sweep through the rack's NAM LV2. Each `train.json` records the device it ran on.
- `stop_benches()` kills leftover capture REAPERs (called on shutdown by `desktop_audio` and `routes_dev`).

Lighter NAM architectures ("lite", "feather") are not used: a standard WaveNet capture costs about as much CPU as
the plugin it replaces; any lighter model must be measured with `playback_check` first.

## 9. Capturing controls (experimental)

`bridge/plugin_capture_parametric.py` extends the fixed-setting pipeline without changing its
trainer or its output files. In the VST drawer select **With controls**, select up to twelve
continuous gain/EQ controls and their normalized travel ranges, preview the capture plan, then
start. Switches, stepped parameters, effect selection, recipe overrides and translated time
effects remain fixed. A different amp channel or cab selection needs a separate model. For a
plugin without a recipe, the same user confirmation as the whole-plugin capture is required.

The planner is deterministic (seed 0 by default). It includes the current setting, each selected
control's endpoints, the combined low/high settings and Latin-hypercube interior points. Defaults
are `max(32, 15 × controls)` training positions and `max(8, 3 × controls)` unseen validation
positions. The validation positions never occur in training. The plan is bounded to 512 renders;
it samples the control space rather than enumerating every possible knob combination.

Every position starts from the **same native VST state** in a separate REAPER. The selected
parameters are set by index and checked against their names; normalized values are read back
after the plugin's restore has settled. A mismatch stops the job. The live VST is never edited.
The standard signal's checksum is checked before acquisition. Training uses seconds 10–48 of
the v3 signal; validation uses seconds 70–79, at 48 kHz.
Each returned file must have the expected length and finite, audible samples. Targets keep their
relative levels: independently normalizing each position would erase the gain control.
If floating-point renders exceed 0 dBFS, the trainer applies one shared attenuation to
all targets and reverses it in both exports, preserving their relative and absolute levels.

The work directory is keyed by native state, recipe and plan. Each complete render has a receipt
with its requested/read-back values and audio SHA-256. Retrying the same job reuses only complete,
verified renders; changing the native state or ranges starts a separate dataset. Cancellation
uses the fixed capture's shared job lock and subprocess registry. Failed or cancelled acquisition
does not install a partial model.

**Trainer.** The optional setup installs
[phillipmself/neural-amp-modeler-parametric](https://github.com/phillipmself/neural-amp-modeler-parametric)
at commit `a3684411076be69dab53505df14922487697f2cf` in its own `nam-parametric/venv` next to
`nam-train`. `tools/nam-parametric-worker.py` runs there; the bridge never imports torch. The
HyperWaveNet conditions a classic two-layer-array WaveNet on the selected controls. This classic
template can be exported to the NAM 0.5.4 schema used by golem's existing players. Training selects
its checkpoint using the held-out positions; the final report measures ESR at each unseen
position, on the separate validation signal. ESR above 0.1 produces a visible warning. This is
a quality measurement, not a guarantee that all unmeasured positions match the source VST.

**Using the result.** New captures install a live `.gcap` module as their primary model,
alongside the ordinary NAM snapshot and full HyperWaveNet source. The capture stays one
golem block. Its knobs work during playback, are saved by scene and appear on the paired
phone, without installing the trainer on the playback machine. The reader is installed
with golem. See [Controllable capture modules](capture-module.md) for internal MIDI
switches, portable transfer and platform checks.

The `/bake` route and Apply UI remain for older developer captures containing only a
parametric source and fixed NAM files. Those older entries still need the trainer for
a new snapshot; they are not live modules. Baked snapshots keep the default loudness
reference so amp normalization does not cancel Level changes. Backups include the module
and developer source. Export/import a module explicitly when moving it; golem.fm
tone-pack sync of this new format is not yet validated.

**Download parametric .nam** exports the full model for a compatible HyperWaveNet player such as
[NamParametricPlugin](https://github.com/phillipmself/NamParametricPlugin). Stock NAM cannot load
that full model. Captures remain private. The new downloads/status routes require an authenticated
device, and installing the trainer requires admin privileges. No automatic public upload is added.

API (under `/api/vst-host/capture/parametric`):

| Method/path | Purpose |
|---|---|
| `GET ?block=&plugin=` | Job, tool setup, capture verdict and selectable controls |
| `POST /plan` | Validate `{block, plugin, plan: {controls: [{i,min,max}], samples, validation, seed}}` and preview every position |
| `POST` | Start with that plan, plus `patch`, optional `name`, `confirmed` and `gear` |
| `POST /setup` | Install the isolated pinned trainer and standard signal |
| `GET /model?ref=&model=` | Read ranges and values of the selected exported setting |
| `POST /bake` | `{ref, values: {"Original knob name": normalized_value}}` → compatible model id |
| `GET /download?ref=` | Download the complete parametric model |

The existing `/api/vst-host/capture/cancel` and `/replacement` also serve these jobs.

### No plugin-specific bench in the repository

The benches, examples and packaged captures built on one named commercial amp suite (October 2026) were
**removed on 2026-10-20**, after the lawyer's opinion: the repository names no third-party plugin in its
examples, recipes or presets, and distributes no capture of a commercial plugin. The generic pipeline
stays covered by `tests/test_plugin_capture*.py`, `tests/test_capture_*.py` and `tests/test_plugin_recipes*.py`
(their recipe is a fixture under a fictional plugin name, `tests/fixtures/plugin-capture-recipe.json`).
`library/catalog/plugin-captures.json` ships **no** recipe: a recipe comes from golem.fm, validated on the
musician's own machine ([`plugin-recipes.md`](plugin-recipes.md)), or the plugin is captured whole, under the
musician's confirmation.
