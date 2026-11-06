# Source separation on the rack — an engine-agnostic runner

> **Status: CODED** — how the rack splits the songs of its owner's library into stems with an engine the
> user installs, and returns them to golem.fm (`bridge/separation.py`, `bridge/separation_run.py`,
> `bridge/routes_separation.py`, Settings ▸ Engines ▸ Separation).
>
> **Paid online services were removed on 2026-10-31 for v0.6** (the open-source launch plan):
> separation runs on this machine only. A `type: "service"` entry of golem.fm's list is ignored, and a
> service engine left in an older `config/separation.json` is dropped when it is read.

## 0. Principle

The user's **own rack** separates the songs of **their own library**, on their machine. golem.fm does not
separate. The rack ships **with no engine**: it is a neutral runner that executes any engine respecting the
contract below, and knows nothing about an engine beyond what it **reads** from the engine's file and
outputs.

## 1. Rules

1. **One code path for every engine.** No code specific to an engine, no weight format read other than
   ONNX, no "if engine X". Two engines of different architectures go through exactly the same path (the
   test engines in `tests/separation_engines.py`).
2. **The rack names no model.** golem neither names, hosts, downloads by itself nor recommends any
   separation model — in the UI, `docs/`, code comments, error messages and logs. A free-licence
   **program** (the plumbing) may be named, documented, detected and pre-filled (§4.2); the **model** it
   loads (its weights, or the file that designates them) never: that field is always left to the user.
3. **A listed engine installs in one gesture**, and is always simpler to install than one added by hand.

What this means outside the screen:

- **Logs**: the bridge writes "listed engine" or "custom engine" (`_origin_word`), never a
  command, a path, a file name typed by the user, a `golem.name`, a licence. An engine's stdout/stderr go to
  `presets/.separation/engine.log`, which `bridge/diag.py` does not read (diagnostic reports go to
  golem.fm).
- **Backups**: `config/separation.json` is never in `backup.SETTINGS_FILES`, and it is git-ignored, as is
  `assets/separation/`.
- **Acks**: neutral codes only (§8.4) — never a file name, an engine error line or a path.

## 2. Engines

### 2.1 Listed engines (golem.fm's list)

golem.fm keeps a list of engines whose code and default weights carry an explicit commercial licence and
lawful training data. The rack reads it: `GET /api/ext/separation-engines` (device token) →
`{rev, engines: [{slug, name, author, stems, kind, contract, download_url, sha256, size_bytes,
licence: {name, url}, attribution}]}` (`separation.remote_list`). An entry with `type: "service"` is
ignored.

- **Install** (`install_listed`, `POST /api/separation/install`): download `download_url`, check `sha256`
  (the exact `.onnx`), then run **the test of §6**. A wrong hash or a failed test: nothing is activated
  and the file is deleted.
- What the list declares (`stems`, `kind`, `contract`) is **displayed** before installing; once the file
  is there, **only the file counts** (`golem.*` metadata, outputs read by the test). A declaration that
  contradicts the reading is refused ("the file does not match the list").
- `slug` is stable for life: it links an installed engine to the list.
- **Removed from the list** (absent from an answer whose `rev` changed, `_withdrawn`): the engine **stays
  installed**, becomes **custom**, and is disabled until the user ticks the responsibility box again. Never
  deleted silently.
- `attribution` is shown on the Separation screen and in System ▸ Licenses ▸ Libraries while the engine
  is installed (`separation.attributions`).

### 2.2 Custom engines

"+ Add engine" → *Your own engine*: the user supplies one of the two local doors and a **Licence** field
(free text, displayed, never interpreted), and must tick: "You add this engine yourself. Check that its
licence allows your use. golem does not provide, recommend or check third-party engines."

- **ONNX** (§3): a local path, or a URL **the user types** (`add_onnx`; the rack never suggests a URL).
- **Program** (§4): an executable and its arguments (`add_program`).

Storage: `assets/separation/<id>/model.onnx` (nothing for a program); settings in
`config/separation.json` (`engines[]`, `active`, `threads`, `rtf`, test results). `<id>` is the `slug` for
a listed engine, a random id otherwise. Neither the typed name nor the file name become a folder name.

## 3. ONNX door — `contract: "1"`

Checked by `separation_run.check_contract` in a separate process (a hostile file cannot crash the bridge).

- **Input** `mix`: float32 `[1, 2, segment]`, stereo, at `golem.sample_rate`, **fixed length** =
  `golem.segment` samples.
- **Outputs**: one per stem, float32 `[1, 2, segment]`, **named after the stem** (§7). Nothing else.
- **Metadata** (`metadata_props`), read from the file:

| Key | Required | Meaning |
|---|---|---|
| `golem.contract` | yes | `"1"` |
| `golem.sample_rate` | yes | rate of input and outputs (e.g. `44100`) |
| `golem.segment` | yes | input length in samples, ≥ 1024. The engine **imposes** it: a recurrent network's quality depends on it |
| `golem.overlap` | no | overlap in samples, 0 to half a segment; default `segment / 4` |
| `golem.licence` | no | text displayed as is |
| `golem.name` | no | text displayed as is, **never** logged or sent |

- All engine-specific signal processing (STFT, inverse STFT, masks, Wiener filtering) is **inside the
  graph**. A spectrogram in/out form is not offered: it would force the rack to carry per-engine transform
  parameters.
- Opset: whatever the bundled `onnxruntime` reads; an unreadable file is refused by the test.

## 4. Program door

### 4.1 Contract

- Stored as a list: `{"program": "<path>", "args": ["…", "{input}", "…", "{outdir}"]}`. `{input}` and
  `{outdir}` are **whole arguments**, each exactly once (`check_program`).
- `{input}`: a 16-bit 44.1 kHz stereo WAV written by golem, always named `input.wav` (so the names a tool
  derives from it are stable). `{outdir}`: an empty folder. The program writes **one WAV per stem**,
  `<stem>.wav`, or files the user mapped to stems (`map`: relative path, subfolders included → stem).
  Exit code 0 = success.
- Launched **without a shell** (argument list), working directory = a temporary folder, minimal environment
  (`_min_env`), low priority. **Windows**: `.bat`/`.cmd` are refused (Python would hand them to `cmd.exe`);
  direct executables only.
- Timeout `max(120 s, 4 × duration)`; on timeout the **whole process tree** is killed (POSIX process
  group, `taskkill /T` on Windows).
- Outputs are normalized once for all (`ffmpeg`): mono → stereo, other rates resampled, 24-bit/float read.

Help text, with a fictitious example only: "The program receives {input} (a stereo WAV) and {outdir} (an
empty folder), and must write one WAV per stem into {outdir}, named after the stem (vocals.wav,
drums.wav…)."

### 4.2 Helping the user configure

"+ Add engine" is a stepper (`app/separation-add.js`): *What* (program | ONNX | engine file) → *Program*
(checks one by one, `POST /api/separation/check-program`; **Browse…** = `GET /api/separation/browse`,
executables or `.onnx` only) → *Command* → *Try it* → *Name* → *Test*. ONNX path: *Model file*
(`POST /api/separation/inspect` reads the file before adding; a URL is downloaded once and kept as
`staged:<id>`) → *Name* → *Test*.

- **Program recipes** — data, not code: `config/separation-programs/<id>.json` (name, licence, project
  URL, where to find it, arguments with **fields** the user fills). `audio-separator.json` is the one
  shipped: its `{model}` field is **required and empty** ("golem does not choose a model for you"), and
  `{models_dir}` optional. `tests/test_separation_programs.py` checks that no recipe names a model.
  `detect_programs` (`GET /api/separation/programs`) looks for the recipe's program on `PATH`, then in the
  recipe's usual paths; a tap fills the program and its plumbing and asks for the **Model**.
- **Program help** (`POST /api/separation/program-help`): once *Program* is green, golem runs it with
  `--help` (else `-h`) — no shell, temporary folder, minimal environment, low priority, 15 s max, output
  truncated, cached per (path, mtime). Its options become chips at *Command*. Read, never guessed, never
  logged.
- **Try it** (`POST /api/separation/probe`): runs the program on 10 s of the excerpt and lists the WAVs it
  wrote, subfolders included. golem proposes a stem per file from its name (`guess_stems`, looking only at
  what **distinguishes** the files: a tool that puts its model name, containing "vocals", in every file name
  would otherwise propose "vocals" twice). A stem proposed for two files is flagged and *Next* stays closed.
  The user confirms the mapping.
- **Hints by symptom** after a failed try or test (`separation.hints`): exit code 127, permission, other
  format, output folder, memory, timeout, unknown argument… Generic; no tool named. A failed program also
  shows, on this rack only, the tail of its output and the files found.
- **Engine file** `golem-engine/1` (`export_engine`, `read_engine_file`; `GET /api/separation/engines/{id}/export`,
  `POST /api/separation/import`): the run instructions of one's own program engine (program, args, output
  map, licence, label), or of a combination of two programs. golem ships none; users exchange them outside
  golem and golem.fm. Importing **pre-fills** the form; the responsibility box and the test remain.
- **Combine two of my engines** (`POST /api/separation/combine`, `kind: "combined"`): two tested engines;
  some stems of the first are **kept**, the **sum** of the others is the input of the second; a stem the
  second returns that is already kept joins `other`, so the stems still sum to the song. Same test.
  Removing an engine removes the combinations that use it (the screen says so first). This replaces any
  wrapper script.

## 5. The executor — the same for all

- **Separate process** (`python -m bridge.separation_run`), never in the bridge: a crash does not kill the
  rack, and cancelling is killing it.
- **ONNX**: cut into `golem.segment` segments, the last padded with silence; joined with a **cosine
  crossfade** over `golem.overlap` (windows sum to 1); outputs cut to the exact length.
- **Threads**: a **fixed** number (`intra_op_num_threads`, `inter_op = 1`), never "all": on a hybrid CPU, 8
  threads run slower than 4. Default `min(4, cores / 2)` (`_default_threads`); settable
  (`POST /api/separation/settings`).
- **Priority**: `nice 19` (Linux/macOS), `BELOW_NORMAL` (Windows).
- **Resume**: each finished segment is written to the work folder; an interrupted job resumes at the first
  missing segment. The folder is deleted at the ack.
- **NaN/Inf** are checked on **every segment**; one fails the job (`engine_failed`), never replaced by
  silence (exit code 3 of the runner).

## 6. The test — nature is READ

Run at install, when a custom engine is added, and whenever its file or command changes
(`POST /api/separation/engines/{id}/test`). **An engine can only be activated after a passed test.**

Input: the **user's own test excerpt**, chosen on the Separation screen (`POST /api/separation/excerpt`),
kept on the rack only (`presets/.separation/excerpt.*`: out of git, backups and diagnostics; its name never
logged). No excerpt is shipped. golem takes **30 s starting at 20 %** of its duration (past the intro).
Local engines then run a second pass on **30 s of silence**.

| Check | On the excerpt | On silence |
|---|---|---|
| output names in the §7 form, no duplicate, 16 max | refuse otherwise | — |
| no NaN/Inf | refuse | refuse |
| duration = input (exact for ONNX; ± 50 ms for a program) | refuse otherwise | refuse otherwise |
| at least **2 stems carrying sound** (RMS > −60 dBFS **and** within 40 dB of the loudest) | refuse otherwise | — |
| no stem ≈ mix (correlation > 0.98) | refuse | — |
| no two identical stems (correlation > 0.98) | refuse | — |
| residual `‖Σ stems − mix‖² / ‖mix‖²` ≤ −10 dB | refuse otherwise | — |
| same stem names as on the excerpt | — | refuse otherwise |

An excerpt can carry a single instrument: a refusal for "fewer than 2 stems" or "a stem is the mix" blames
**the excerpt** ("choose an excerpt with several instruments"), not the engine. The thresholds only catch
**fakes** (N copies of the mix ≈ +12 dB residual, N silences = 0 dB). A silent stem is allowed.

Kept: `{ok, why, stems, rtf, load_s, tested_at, analysis, hints}`. `rtf` (real-time factor) is computed
**without** load time. The announced `rtf` is never a default: the test's value until the first real
separation, then the rolling mean of the last three (`_note_rtf`). A failed re-test deactivates the engine.

## 7. Stem vocabulary — open

- Form `^[a-z][a-z0-9-]{0,31}$`, **16 max** per engine and per `.golem`: `vocals`, `drums`, `guitar-2`,
  `strings`, `voice-1`…
- Forbidden (keys of the Lua command): `files mix slug dir ticks op seq action stem mute vol`
  (`separation.RESERVED` = `golemfm._RESERVED_STEM_NAMES`). A refused name is **never renamed by guess**.
- **Family** of a stem = what precedes the **first hyphen** (`guitar-2` → `guitar`, `guitar-electric` →
  `guitar`, `voice-1` → `voice`; `golemfm.stem_family`). Known backing families with aliases: `vocals`
  (= `voice`), `drums`, `bass`, `guitar`, `piano` (= `keys`), `other`. An unknown family (`strings`) is
  allowed.
- **`golem_backing.lua`** keeps six permanent tracks `vocals drums bass guitar piano other` (karaoke, tab
  follow and saved mixes name them); any other name gets its own "Backing Track `<name>`" track, created on
  demand, sent to the bus as audio only, never deleted (empty and muted on the next song).
- Bridge side (`golemfm.expand_mix`, `keep_stems`; `tests/test_stem_families.py`): the default mix applies
  **by family** ("guitar muted" mutes `guitar`, `guitar-1`…); karaoke voice stems = family `vocals`; beyond
  16 stems or a name outside the form, the `.golem` is read and the stem is **ignored and reported**.

## 8. The `song-separate` job

### 8.1 Who receives it

The rack whose owner owns the song. golem.fm decides by data; the rack cannot check it.

### 8.2 Payload

`{song, kind, source_url, upload_url, stems_wanted}` — flattened after the job envelope, which already
carries `id`; the job id the rack acks is `tones_jobs.job_id` (`_job`). `song` is golem.fm's internal song
id, copied as is. `kind` = `song` | `vocals`. `source_url` and `upload_url` must be server paths (start with
`/`). `stems_wanted` ⊆ `caps.separation.stems` at request time (empty = all).

### 8.3 When

The job is queued in memory and acked later (`ASYNC_ACK`). Before taking the CPU it waits for the reamp
"free" rule (`reamp.busy_reason(idle=True)`, [`reamp.md`](reamp.md)): not in Gig, mode not locked, no take or count-in, nothing playing
or loading, no preview rendering, 10 minutes without a gesture or input signal. While busy: no ack, the job stays pending on
golem.fm, and `GET /api/separation` shows the reason. The rule is **re-read during the run**: if someone
starts playing, the executor is killed and the job goes back to the head of the queue, resuming at the next
missing segment. Cancel: `POST /api/separation/cancel` (acks `cancelled`).

### 8.4 Run and ack (`separation._run_job`)

1. Download the original (`source_url`) once, decode to 44.1 kHz stereo.
2. Separate with the **active** engine; if `stems_wanted` is not included in its tested stems →
   `engine_changed`.
3. Re-read every stem with the checks of §6 that apply to a real song (NaN/Inf, duration, names); a
   **silent stem is accepted and reported** (`silent`).
4. Encode to **MP3 192 kb/s CBR**, tags stripped, and **POST each stem** to `upload_url` (multipart: field `stem` + the file), up to 3
   tries. One call per stem: a cut upload only redoes the missing stem; each call is idempotent.
5. Ack `{ok: true, result: {stems, silent}}`. Errors, **codes only** (`separation.ERROR_CODES`):
   `engine_changed`, `no_engine`, `engine_failed`, `source_unreadable`, `upload_failed`, `cancelled`.

## 9. The screens

- **Settings ▸ Engines ▸ Separation** (`app/page-separation.js`): the engine in service at the top (stems,
  measured speed, test, queue), the others below, each with plain **Details** (a program's command, an
  ONNX's metadata — local, never logged); the test excerpt and threads at the
  bottom. Buttons per engine: **Test** / **Test again**, **Use this engine**,
  **Remove**. "+ Add engine" opens a stepper whose first screen offers *A program on this machine*, *A model
  file (ONNX)*, *An engine file* and *Combine two of my engines*. *Checked by golem.fm* shows
  when the list carries a free engine.
  **Separate a folder…** separates every song of a folder of the user's into `.golem` files in the library
  ([`separation-batch.md`](separation-batch.md)).
- The old addresses `#/system/engines/separation/keys` and `#/system/api/sep` open the engines list.
- Text: "A separation engine splits a recording into stems, so you can mute, solo or slow each part. golem
  separates the songs of your own library, on this machine. Nothing leaves it but the stems, which go back
  to your private library."
- No list, name or link to an engine outside golem.fm's list.

Routes: `GET /api/separation` (`overview`: engines, active, threads, test, jobs, caps, excerpt, list), `POST /api/separation/engines` (add), `/install`, `/engines/{id}/test`, `/engines/{id}/activate`,
`/deactivate`, `DELETE /engines/{id}`, `/settings`, `/cancel`, `/excerpt` (POST/DELETE),
`/probe`,
`/engines/{id}/export`, `/import`, `/check-program`, `/programs`, `/inspect`, `/browse`, `/program-help`,
`/combine`, `/import-combined`.

## 10. `caps.separation` (heartbeat)

`{"separation": {"stems": [...], "rtf": 0.15}}` — stems and real-time factor of the **active, tested**
engine, as **read** (`separation.caps`). Never: name, slug, origin, door, licence, command, path, URL. No
active tested engine → no `separation` key.
golem.fm estimates "~N min" from `rtf × duration`.

### 10.1 `separation_job` (heartbeat, top level) — CODED 2026-10-24

What the rack does with the `song-separate` job it **holds** (`_JOB["cur"]`, the current one only), so the
song card on golem.fm can say "will separate when it is free — a song is playing" instead of claiming it
runs (`separation.heartbeat_job`). **Absent** when no job is held.

```json
"separation_job": {"job": 131, "phase": "waiting", "why": "in_use", "starts_in_s": 200}
"separation_job": {"job": 131, "phase": "running", "progress": 0.42}
```

- `phase`: `waiting` (the §8.3 "free" rule holds it) or `running` (download, separate, upload).
- `why` (waiting only): a **code**, never the text of `busy_reason` — `gig` "gig mode", `locked` "mode locked",
  `recording` "a take is recording", `playing` "a song is playing", `loading` "a song is loading", `preview`
  "a preview is rendering", `in_use` "in use (…)". An unknown reason sends no `why`. So does a folder batch
  ([separation-batch.md](separation-batch.md)) holding the engine: the job stays `waiting`, and can be
  cancelled, until the batch's song is done.
- `starts_in_s` (`in_use` only): `IDLE_S` (600) − seconds since the last gesture or input signal.
- `progress` (running only, when known): 0–1, the executor's progress. Absent during the upload.
- Pushed off-cadence (`rigstatus.push_soon`) when the waiting code changes, when a gesture restarts the
  10-minute window (`starts_in_s` up by more than 30 s), when the run starts and when the job ends; progress
  otherwise rides the 5-minute heartbeat.

## 11. Dependencies and open points

- `onnxruntime` (CPU) and `numpy` are in the bridge's venv on the three OSes. Decoding and encoding use
  `ffmpeg`; on Windows and macOS it must be bundled or replaced (`libsndfile ≥ 1.1` reads and writes MP3) —
  not settled.
- Not measured on the rack hardware.
- `tests/separation_engines.py` holds the test engines that prove the single path: an ONNX band splitter
  with no learned network (fixed FIR filters, stems `low` / `mid` / `high`, summing exactly to the mix), a
  small program that writes `low.wav` and `high.wav`, and two fakes the test must refuse (N copies of the
  mix, NaN on silence). They are never listed or shipped, and pass §6 **without any threshold exception**: if a threshold
  refuses them, the test engine changes, not the threshold.
