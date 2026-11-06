# Preset preview — a short demo per scene

> **Status: PARTLY CODED** — the generation engine, the `generate-preview` and `patch-preview` jobs, playback and
> export are coded (`bridge/preview.py`), and the Patches page listens to a patch. **First run on the rig
> 2026-11-03**: the five guitar DIs are recorded (`library/di-refs/guitar/`, local until the `di-refs-v1` release),
> Jazz Clean renders its five scenes in stereo with their tails. Bass and voice DIs are not recorded yet.

A preset can carry a **short audio demo per scene**, made by re-amping a **reference DI phrase owned by golem**
through the preset's chain. The player's own playing is never recorded for this:

- **Rights.** Recording someone playing a known song and publishing it would distribute a cover. The reference DI
  is an original phrase owned by golem: the composition is golem's, the *sound* is the preset's, nothing
  third-party travels. Safe to publish by construction.
- **Comparability.** The same phrase through every preset: what you hear is the difference the preset makes.
- **Listening before installing**, on the rack and on golem.fm.

There is **no `preview` block**: any residual one is dropped on load (`preset_view.DROPPED_TYPES`). Demos are
generated from the Setlists/Patches pages and by golem.fm jobs.

## 1. Reference DIs (`library/di-refs/`)

`C.DI_REFS_DIR`. Index `library/di-refs/index.json`:

```json
{"refs": {"guitar/clean": {"file": "guitar/clean.wav", "name": "…"}}}
```

Flat keys `<role>/<bucket>`. Buckets the code selects: `guitar/clean|crunch|high-gain|djent`,
`bass/finger|pick`, `voice/male|female`, and the **MIDI references** (`kind: "midi"`, 2026-11-03)
`keys/piano|epiano|organ|pad|lead` and `drums/rock|funk|jazz|metal`. Those are composed by
`tools/make-midi-refs.py` — the script is the score, rerun it to rebuild them identically — and played by the
patch's instrument instead of re-amped; their selection is by tags too (the instrument named first: organ, pad,
lead, rhodes/dx7, piano; then the genre). Phrases must be original or CC0, never a recognizable riff; mono, dry,
short, with the last note left to ring. No tempo: a reference is rendered through patches of any BPM.

**Selection** (`preview.resolve_di`): an explicit `ref` from the request wins; otherwise `auto`. The role is the
one of the **lane** that plays on the rendered input (`_role_of`) — not the card's role for that input: the first
batch rendered the factory voice patches with the guitar DI, the card's input 1 being a guitar. The preset's or
patch's **tags** decide first (`_bucket_from_tags`, most specific wins: `djent` → djent; `metal`/`high-gain` →
high-gain; `clean`/`jazz`/`funk` → clean; `crunch`/`rock`/`blues`/`punk`/`fuzz` → crunch; bass `funk`/`jazz`/`soul`
→ finger, `metal`/`rock`/`punk` → pick) — a patch has tags, no style, and a patch open in the Designer renders
from its draft, which gets the patch's tags; then the style, as below:

- role = the role of the rendered input: input `1` → the preset's main role (`_main_role`: guitar or bass from the
  card's input map), other inputs → `input_role` (Soundcard role); voice defaults to `voice/male`;
- bucket from the preset's style family (`preset.style` or `styles[0]`, see [`genres.md`](genres.md)),
  `_bucket`: guitar `metal` → `high-gain`, `punk`/`math rock`/`rock`/`blues` → `crunch`, legacy `djent` →
  `djent`, else `clean`; bass `djent`/`metal`/`punk`/`rock`/`math rock` → `pick`, else `finger`.

A missing index entry or file → the generation ends in `phase: "error"` naming the missing reference.

## 2. Generation (`preview.generate`)

One generation at a time (`_gen_lock`, shared by the UI and jobs). It **takes the live engine** and gives it back:
for each scene of the preset (all scenes):

1. apply the scene on the live sandbox (`_apply_scene`, injected by the app) and wait 1.2 s;
2. delete `presets/.preview.json`, send `{action: "preview", op: "render", scene, di, out, tail: 5.0,
   chain: "Sandbox #Input <in_key>", _route: "preview"}`; `golem_preview.lua` clones the input track (no hardware
   output) and renders the DI through it offline; it deletes the output file first (an existing file opens a modal
   dialog in REAPER);
3. poll `.preview.json` for `{scene, done, wav}` (150 s);
4. encode to Opus with ffmpeg (`_encode_opus`: mono, `loudnorm=I=-16:TP=-1.5`, 48 kbps) into
   `library/previews/<preset id>[-in<key>]/<scene>.opus` (`C.PREVIEWS_DIR`, local, not versioned) and delete the WAV;
5. write `preset.preview` **incrementally** (scene A is playable while B renders) and call the job's `on_scene`
   hook;

then `_restore_live()` re-applies the sandbox. One clip = **one lane** (the input `in_key`), never a mix. Keys
(`in_key: "k"`) is refused: it would need MIDI rendering.

Progress: `GET /api/preview/status` → `{phase: idle|render|done|error, preset, done, total, msg, error}`.

## 3. Data on the preset

```json
"preview": {
  "instrument": "guitar", "ref": "guitar/high-gain", "fingerprint": "…",
  "generated": "2026-01-01T18:00:00Z",
  "scenes": {"A": "library/previews/my-preset/A.opus", "B": "library/previews/my-preset/B.opus"},
  "alt": {"2": {"instrument": "voice", "ref": "voice/male", "scenes": {…}}}
}
```

Input 1 lives at the top level; other inputs under `alt.<in_key>`. `fingerprint` is
`preset_export.fingerprint(preset)` at generation time (the sound fingerprint, which ignores `preview`, `colors`
and `anims`).

## 4. Entry points

| Entry | What |
|---|---|
| `POST /api/preview/{pid}` `{input?: "1"\|"2"\|"k", ref?}` | starts `generate` in a thread; 409 if one is running or a take records, 404 if the preset does not exist. `pid` may be `patch:<id>`: the patch renders as it plays (the input it binds to on this card, `preview.patch_input`) |
| Setlists page (`app/page-setlists.js` `genDemo`) | generate per input, voice reference Male/Female, plays clips per scene, shows the error |
| Patches page (`app/page-patches.js` `genDemo`, 2026-11-03) | "🎧 Listen — Guitar/Bass/Voice" on each patch → `patch:<id>`; then 🎧 plays the selected scene, ↻ regenerates. Keys and drums patches show nothing until MIDI rendering exists. A patch's demo is stored **next to its clips**, `library/previews/patch-<id>[-in<k>]/preview.json` — never in the patch file (factory patches are reseeded, patches go to golem.fm) — and `GET /api/patches` returns it as `preview` |
| job `generate-preview` `{preset, in_key?, ref?}` (`tones_jobs._generate_preview`) | refused in Gig/locked mode; each finished scene is uploaded (`preview.push_clip` → `POST /api/ext/tones/assets`) and reported (`POST …/jobs/{id}/progress {scene, clip}`); ack `{preset, preview: {ref, di_name, in_key, instrument, fingerprint, scenes: {scene: {sha256, duration}}}}` |
| job `patch-preview` (`tones_jobs._patch_preview`) | the same engine on a temporary trial preset built from a golem.fm patch ([`patches.md`](patches.md)); the input is the lane's `in_sel` |

Jobs: [`golemfm-protocol.md`](golemfm-protocol.md) §3.

## 5. Export

`preset_export` strips `preview` from the exported preset document and adds the clips as `deps` with
`kind: "preview"` (`preview.export_deps`: `uid: local:preview-<id>-<scene>`, `source: "golemfm"`), uploaded at
publish time. A missing clip never blocks publishing: a demo is a bonus, not a playability dependency. The
envelope carries `preview_fingerprint` so golem.fm can show a demo as possibly stale when the sound changed.

## 6. Not built

- the bass and voice reference DIs (to record);
- a demo per lane for the user's own presets from the Presets page (the batch covers the factory ones; the per-input
  « Listen » button renders a user preset);
- a stale-demo badge on the rack (only golem.fm compares fingerprints).

## 7. Proposed for the open-source launch

> **Status: PROPOSED (2026-10-31)** — needed by step 4 of the open-source launch plan: the shell shows
> every factory sound with its demo.

- **First run on the rig (2026-11-03, Jazz Clean, DI guitar/clean, nobody playing).** The offline render works
  while the rig runs, and a split lane renders whole once the command carries `tree` (it cloned the root's FX
  only before: no amps). Two defects fixed then: the clips were mono, and a patch with no style got its DI from a
  stale draft style (now tags first). Still to watch: xruns during a render while someone plays (never tried),
  and the clips' level on high-gain DIs recorded at a −5.3 dBFS ceiling.
- **Keys and drums from MIDI — CODED 2026-11-03.** A `kind: "midi"` reference (`tools/make-midi-refs.py`: five
  keys, four drums — composed for golem rather than taken from the factory grooves, so each phrase ends on a hit
  left to ring) is **played by the lane's own instrument** (Dexed, Vital, piano, organ, the AVL kit and its
  translator), then goes through the lane's chain. `in_key: "k"` renders the first MIDI lane; its root is
  `Sandbox #Input <lane input>` (3 on a two-input card, 101+ beyond). The bridge reads the `.mid` into events
  dated **in seconds** (`preview.midi_events`, tempo map included) and `golem_preview.lua` lays them on a new MIDI
  item with `MIDI_GetPPQPosFromProjTime`: the reference keeps its own tempo whatever the patch's BPM, and the
  project tempo (click, synced delays) is never touched. What the first runs on the rig showed, and what answers it:
  - the instrument wakes slowly when an offline render starts — Dexed cut the first chord in 0.1 s with the notes
    0.25 s in, sometimes with 1 s: the events start **2 s** in (`MIDI_LEAD_IN`) and the encoder trims all but
    0.25 s of it (`MIDI_KEEP_S`);
  - an instrument reloads its state in the clone: 4 s after the clone (5 s before the first scene) instead of 2/3;
  - a clip below −60 dBFS **re-applies its scene** and renders once more, twice as patient — seen when a demo
    was asked right after a bridge restart: the lane was not built (root muted, no FX), and a second render alone
    did not help. `golem_preview` logs what it cloned (`render <scene>/<track> : … racine mute=…, N FX`).
  Verified 2026-11-03 on every factory keys and drums patch (13): sound on every scene, first chord whole.
- **Batch — CODED 2026-11-03** (`preview.batch`). Every factory patch (pads excluded: they trigger samples), one
  at a time, each taking the engine and giving it back. `POST /api/preview/batch {ids?, force?}` (admin: the engine
  is taken for half an hour), `GET /api/preview/batch` (per patch: `rendered`, `skipped` with its reason, `failed`
  with the error), `POST /api/preview/batch/stop` (after the patch being rendered). **Resumable**: a demo whose
  sound fingerprint and per-scene references are unchanged, with every clip on disk, is skipped (`up to date`);
  a take that starts stops the batch, and running it again resumes. A patch that cannot render yet (no reference
  recorded, no input of its role on this card) is skipped with that reason, never silently. Settings ▸ Content ▸
  Factory ▸ **Sound demos**: how many factory patches can be heard, Render / Stop, progress.
- **A preset's demo, lane by lane — CODED 2026-11-03.** Each lane of a song has **its** demo, stored with the song
  (`library/previews/preset-<id>/<lane>/preview.json` and one clip per **song** scene; `GET /api/presets` returns
  `lane_previews`), with **no live link** to the patch it came from: retouching the patch or the lane does not
  touch a demo already made. To make it (`preview.lane_plan`): when the lane **sounds exactly like its origin
  patch** (`patch_from`, set at deposit) — same chain and, for each song scene, the same *effective* state
  (blocks on/off with their base state applied, branches muted or not, settings; renamed ids such as `comp-2`, the
  system volume and `1` vs `1.0` set aside) — the clip of the patch scene that sets that same state is **copied**;
  otherwise the lane is **rendered alone** (`render_lane`: a trial preset made of it, bound to an input of its role,
  the song's scenes, the DI of each scene from its origin patch's casting by state name, the tags of the origin
  patch). A scene where the lane is muted has no clip. The batch does it for every lane of the factory presets
  after the patches; a copy is redone when the patch demo was redone. The Presets page shows, for the selected
  lane, 🎧 for the scene on screen, read-only, whatever the sound card — a lane with no input on this card is heard
  too. First run: 27 lanes copied, 2 rendered (Metal for All: the 2nd guitar has no Whammy, the drums play another
  kit in their scenes), in under two minutes.
- **A borrowed input — CODED 2026-11-04** (`render_patch_borrowed`). Rendering a demo does not need the role of the
  card's inputs: the reference enters the clone, offline. A patch whose role has no input on this card (a bass on the
  maintainer's rack: voice and guitar) is rendered on an audio input **borrowed** for the render: the patch is bound to
  a copy of the card where that input carries its role; the real card is not touched. Bass, voice and guitar only.
- **The DI per scene — CODED 2026-11-03** (`_scene_refs`). A scene plays the phrase of ITS sound: a clean sound the
  clean DI, a riff the DI of its gain (crunch, high-gain = the 7-string, djent = the 8-string, funk), and only a
  real solo scene a lead DI (`guitar/lead-clean` behind a clean amp, `guitar/lead` behind a driven one). The
  **factory** patches have their casting listened to and decided scene by scene by the maintainer,
  `library/factory/demo-casting.json` (a reference not recorded yet falls back to the rule); other patches follow a
  careful rule on the scene's **name** — *solo*/*lead* → the lead DI, *clean* → the clean DI. A tag never puts a
  whole patch in solo any more (Singing Clean, tagged *lead*, played the solo on every scene). Only when the DI is
  chosen automatically, only with DIs that exist. The demo records `refs: {scene: ref}`.

## 8. What a block plays — drum machine and standard

> **Status: CODED 2026-11-06, not rendered on the rig yet** — asked for the golem.fm demo: a tap on a switch that carries
> a drums or a standard block plays what that block generates. **8 bars everywhere** (the maintainer's decision), at the
> preset's tempo, with a tail. The arrangement block waits (later, or a real-time take — to be discussed).

- **Where it lands.** `library/previews/block-<preset>/<switch>/<drums|standard>.opus` with a `.json` beside it (`kind`,
  `block`, `switch`, `bars`, `bpm`, `fingerprint`, `file`, `seconds`, `generated`). `<preset>` is written like a demo
  folder: `patch:<id>` → `patch-<id>`. `GET /api/presets` and `GET /api/patches` return them as `block_previews`
  (`{switch: {kind: entry}}`), which is how `tools/shell_snapshot.py` finds the clips for the demo's media (prefixes
  `block-factory-`, `block-patch-factory-`).
- **The notes are computed by the bridge, not recorded from the live players.** Drums: the block's groove 0 looped as
  the foot plays it (or its SONG sequence from the first step), read from the `.mid` the way `golem_drums` reads it
  (note-ons, the first time signature, length rounded up to the bar), channel 10 (`preview.drum_lines`). Standard:
  `standards.build` with the block's own settings (`standards.block_kwargs`, the same function the foot uses), no
  count-in, from the start of the chart, the preset's tempo; a chart shorter than 8 bars loops; notes held past bar 8
  stop there; one list per part on the channels `golem_chordseq` uses (`preview.standard_lines`). `build(write=False)`
  leaves `presets/.standard.seq` alone.
- **The sound is the engine's own.** The bridge asks the loop to set its instruments up **without playing** (new op
  `load` in `golem_drums` — kit and multi-mic mix — and in `golem_chordseq` — piano, bass, kit, pompe guitar and the
  keys' arpeggiator; no bank, no nonce, no mute touched), then `golem_preview` clones the `Drums` or `Standard …`
  tracks by their chunk **without their sequencer JSFX** (it would read the gmem bank shared with the live track),
  unmutes the clones, sends them to the empty master and lays each part's notes on its clone (command fields
  `chains`, `midis`, `strip`). No preset recall, no project tempo change, no hardware output.
- **Safeguards (Lua review of 2026-11-06).** `load` acts on the **live** tracks, so it never runs while they play: the
  bridge skips the block (and stops the batch) when `.drums.json` or `.standard.json` says playing, and both loops
  refuse `load` when their JSFX reports playing. The clone's chunk is written **unarmed** (its `REC` line), so it never
  joins the live graph; a chunk whose sfizz (LV2) has no `sfzfile` or whose drumgizmo has no kit config is refused as
  "still loading" rather than cloned empty; a clone left with no FX after the sequencer is stripped is refused ("no
  instrument"); `strip` defaults to both sequencers. Silence is judged on the **first bar** (a late instrument leaves
  it silent while the rest sounds): below −60 dBFS the block is rendered once more, twice as patient, and a second
  silent first bar is a failure, never stored. A drumgizmo kit waits 12 s after `load` instead of 4.
- **Batch.** `POST /api/preview/blocks {ids?, force?}` (admin), `GET /api/preview/blocks`, `POST
  /api/preview/blocks/stop`: every drums/standard block on a switch of the factory presets and patches (40 on
  2026-11-06), one at a time, resumable (a clip whose fingerprint — kind, block params, bpm, bars — is unchanged is
  skipped), stopped by a take. It shares the demos' lock: never at the same time as a demo render.
- **Known limit.** The keys' arpeggiator (`midi_arp`) follows the **project** tempo, not the preset's: a block with
  `arp` set renders at the wrong arpeggio rate when the two differ. No factory standard block uses it today.
