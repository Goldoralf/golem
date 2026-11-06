# Separate a folder — a batch of the user's songs, one `.golem` each

> **Status: phase 1 CODED; phase 2 CODED on the rack and on golem.fm, validated by the lawyer (2026-10-21)** — Settings ▸ Engines ▸ Separation ▸
> **Separate a folder…** (`bridge/separation_batch.py`, `app/separation-batch.js`, mockup `mockups/separation-folder.html`).
> Nothing legal blocks production any more: golem.fm removed its sync registry (§8, maestrium `ab9b7f0`, 2026-10-21).

Related: [`separation.md`](separation.md) (the engines, the executor, the stem vocabulary),
[`golem-format.md`](golem-format.md) (the `.golem`), [`song-folders.md`](song-folders.md) (a folder is read, never
written).

## 1. What it does

The user picks a folder of their own recordings. golem lists the songs it finds, the user checks titles and artists,
chooses **Full stems** or **Vocals**, and starts. Each song is separated with the engine in use and becomes a
`.golem` in the golem's library — it shows in Library ▸ Tracks ▸ Backings like any song with stems.

## 2. Rules

1. **The folder is read, never written** (song-folders.md §2.2): nothing is created, renamed or deleted next to the
   user's audio. The work files live in `presets/.separation/batch-<id>/` and are deleted when a song is done.
2. **Same engine, same execution as golem.fm's `song-separate` job** (separation.md §5, §6, §8.4):
   `separation.separate`, the output checks (`analyse`), MP3 192 kb/s stems. A song that was interrupted resumes at
   its first missing segment.
3. **One song at a time on the engine** (`separation.RUN_LOCK`): a golem.fm job goes first; the batch waits.
4. **Nobody plays while it works**: the run stops when golem becomes busy (`reamp.busy_reason(idle=False)`: Gig, a
   locked mode, a take, a song playing or loading, a preview) and goes on by itself. Unlike a golem.fm job, the batch
   does **not** wait for 10 minutes without a gesture before starting: it comes from a gesture.
5. **Nothing leaves the golem without the gesture**: only "Store on golem.fm when done" (§7), with the declaration
   ticked for this batch, sends the songs — to the user's private library. golem never looks for a recording, a
   tablature or lyrics: only the user's files are used.

## 3. Reading the folder (`separation_batch.scan`)

- The folder and its sub-folders, **3 levels** deep, hidden files ignored, **2,000 audio files** at most.
- Audio: the extensions of `separation.AUDIO_EXTS`. `ffprobe` reads the duration and the tags.
- **Title and artist**: the file's tags (`title`, `artist`, else `album_artist`), else the file name
  ("Artist - Title", a leading track number dropped; else the whole name is the title). The screen says which.
- **Same-name companions**: `<name>.gp` becomes `scores/song.gp`, `<name>.lrc` becomes `lyrics/song.lrc`.
- **States**: `new` (selected by default) · `duplicate` (a song with the same normalized artist and title is already
  on this golem) · `twice` (the same artist and title appears twice in the folder) · `unreadable`.
- The last reading is kept 15 minutes, so starting does not read the folder again.

## 4. The `.golem` of a song

| Member | From |
|---|---|
| `audio/original.<ext>` | the file itself, byte for byte, if it is WAV, MP3 or FLAC; any other format is converted to FLAC, without metadata (a `.golem` accepts only these three) |
| `stems/<stem>.mp3` | the engine's stems, MP3 192 kb/s, `origin: separated`, `part` = the stem name |
| `scores/song.gp`, `lyrics/song.lrc` | the same-name companions, if any |

Manifest: `type: song`, `kind: cover` and `rights.work: third-party` **by default** (decision 2026-10-20),
`id` = `golemfile.content_id(artist, title, "cover")` (`ct:`), `title`, `artist`, `album` (from the tags),
`recording.duration_ms`. The file is written to the work folder, then installed by `songs.install_golem` — the single
path every incoming song takes.

**Modes**:

- **Full stems** — every stem the engine gives.
- **Vocals** — the stems of the `vocals` family (`vocals`, `vocals-*`, `voice*`), plus **everything else summed into
  one `other` stem**. Refused at start if the engine in use gives no vocals stem.

## 5. The batch (`presets/.separation/batch.json`)

Local state, out of the repository, the backups and the diagnostics. One batch at a time.

```json
{"id": "…", "dir": "/home/…/Covers", "mode": "full|vocals", "engine": "<engine id>", "paused": false,
 "items": [{"key": "…", "path": "Album/03.flac", "title": "…", "artist": "…", "album": "…", "duration_s": 252.1,
            "gp": "…", "lrc": "…", "state": "waiting|running|done|failed|cancelled", "song": "ct:…", "error": "…"}]}
```

- **Start** refuses: no tested engine in use; a batch still running; Vocals without a vocals stem.
- **Pause** keeps the done segments; **Cancel** turns everything waiting into `cancelled` (the songs already done
  stay in the library); **Try again** puts a failed or cancelled song back in the queue; **Done / Clear** closes a
  finished batch.
- **Bridge restart**: `separation_batch.resume()` at startup turns a `running` song back into `waiting` and goes on.

Routes (admin, `/api/separation` prefix): `GET /api/separation/batch` · `POST …/batch/scan {dir}` ·
`POST …/batch {dir, items: [{key, title, artist}], mode, store?, declared?}` · `POST …/batch/pause {paused}` ·
`POST …/batch/cancel` · `POST …/batch/retry {key}` · `DELETE …/batch`. `GET /api/separation/browse?want=audio`
lists folders and shows the audio, `.gp` and `.lrc` files (not selectable).

## 6. The screen

- **Separate a folder…** next to **+ Add engine**: active only with an engine in use that passed its test, and no
  batch running.
- A three-step modal, like Add engine: **Folder** (the same browser; "Use this folder"), **Songs** (the list,
  titles and artists editable, `.gp` / `.lrc` tags, what is skipped and why), **How** (Full stems or Vocals, the
  engine, the time estimated from the measured real-time factor, where the songs go). "Store on golem.fm when done" is active (greyed only offline or unpaired, `app/separation-batch.js`).
- The batch shows **in the card of the engine in use**: folder, mode, done count, the current song and its
  progress, the time left or the waiting reason, **Pause** and **Queue ›**. The Queue modal lists every song with its
  state and **Try again**.

## 7. Phase 2 — storing on golem.fm

**Rack — CODED (2026-10-21):**

- **A shared category** in `golemfile.category`: `track` = audio (present or declared) with no tab, no chart and no
  lyrics — a song waiting for its tab or lyrics. It counts in the songs section of the quota
  (`inventory.SECTION`). A batch song with a same-name `.gp` is a `song`, with a `.lrc` a `vocals` line.
- **Inventory**: `track` cards are announced. A golem.fm that does not know the category yet refuses the whole send
  (422 `bad_card`): the rack redoes it without them, and they go again on the next send — they pass the day golem.fm
  accepts them.
- **"Store on golem.fm when done"** in the How step, with the places of the songs section (`/api/golemfm/quotas`; a
  warning when there are fewer places than songs). Ticking it shows the **declaration of lawful origin** the terms of
  use require at each deposit (lawyer's L4 §3.3); without it the start is refused. Each song, once filed, goes through
  `inventory.upload(…, declared=True)` — the "Store on golem.fm" path, `&declared=1`. Its state shows in the Queue
  (`to store`, `storing…`, `on golem.fm`, `not stored` with golem.fm's reason).
- **After the fact**: the Queue of a finished batch offers **Store N on golem.fm…** for the songs done and not
  stored (refused, or never asked), with the same declaration (`POST /api/separation/batch/store {keys?, declared}`).
- The enriched version comes back by the existing sync: `upload` links the song to its slug and its `golem_etag`;
  when golem.fm changes the file (a tab added, synced), its new `golem_etag` makes the rack pull it, and
  `songs.install_golem` merges it (the tab arrives in `scores/`, the category becomes `song`).

**golem.fm — CODED (2026-10-21, golem.fm session):**

- `track` is accepted in the inventory (`CATEGORIES`) and at import: a song **without a tab** (`SongStatus.WAITING`),
  its stems declared, waiting for a tab or lyrics. The import answers `kind: "track"`.
- `declared=1` is recorded with each deposit (date, account, text version, source "golem" or "web", song) and, since
  the lawyer's answer (§8), is **required for every deposit**: without it, 422 `rights_not_declared` (the rack says
  "tick the declaration…"). golem.fm's account declaration uses the lawyer's wording too (`RIGHTS_VERSION` 2): an
  account that has not declared again gets 403 `rights_not_declared` (the rack says "open golem.fm and confirm your
  rights declaration…").
  Since the lawyer's answer (§8), the rack asks for the declaration on **every** deposit — the song sheet's "Store on
  golem.fm" (whole file or text only, any category) and the batch — and sends `declared=1`. A `track`'s sheet also hides
  "Text only": a light `track` would carry nothing.
- **Add a tablature** (`POST /api/my/songs/{slug}/score`) / lyrics to a `track`: the user's own file only, with the
  upload declaration box, never searched or suggested; then the pipeline (sync, harmonic analysis) — no separation,
  the stems stay the declared ones. A new `golem_etag` makes the rack pull the enriched `.golem`.
- A `track` that gets a `.lrc` (no `.gp`) is read `vocals` on both sides (the shared rule): it leaves the Songs places
  and takes a Vocals place (403 `quota_exceeded`, section `vocals`, if none is free). golem.fm keeps the same song (same
  slug, same `golem_id`), so the rack's link and `golem_etag` stay; its inventory card goes again as `vocals`.
- golem.fm separates nothing: its load per song is syncing and analysis, capped by the quota.

## 8. The lawyer's answer (2026-10-21) — FIXED

To the "tablatures in batch" note (`~/golem-avocat-tablatures-2026-10-20.md`):

1. **The batch on the golem** (separating and filing `.golem` files locally, nothing sent) is covered whatever the
   number: the software is the container; the user's private copy has no quantitative cap.
2. **Tablatures**: their provenance is the user's responsibility. **No box locally** — reading a file of one's disk
   asks nothing. **One box at each deposit to golem.fm**, single or batch, in his words: "I declare that I hold the
   rights to, or own a lawfully acquired copy of, the recordings and tablatures I store in my private space on
   golem.fm." (`app/separation-batch.js` `DECLARATION`, used by the batch and the song sheet.)
3. **Private storage on golem.fm**, even hundreds of songs at once, is passive hosting (DSA art. 6) and a private cloud
   copy — **provided nothing is shared between accounts**: golem.fm must never keep `.gp` files or sync maps in a
   central base to offer them to another user who imports the same audio. Each account is a sealed silo. ⚠ golem.fm's
   sync registry (`services/sync_registry.py`: "once a pair is calibrated by someone, it is for everyone") does exactly
   that. **Decision (2026-10-21): the registry is removed**, not restricted — the module, its tables (migration
   `b5d7f9a1c3e6`, with purge), the "already synced by someone" offer and `accept-known` (maestrium `ab9b7f0`).
   Each song keeps its own sync.
4. **Syncing and harmonic analysis on golem.fm are lawful** (extraction of metadata, CPI L.122-5-3) **as long as the
   `.gp` stays untouched** and the sync is stored beside it. golem.fm complies: it no longer writes a `synced.gp` (since
   2026-10-12), serves the deposited `.gp` byte for byte, and the sync travels in `sync/score.json` / `sync/bars.json`.
   Checked end to end on 2026-10-21: the `.gp` the rack pulls back is identical to the one deposited.
5. **An audio-only `.golem` with a tab added later** is fine: a local file picker only, no search, no prebuilt link, no
   tab-site API, covered by the deposit declaration.
