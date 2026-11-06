# The `.golem` format — a song or an album in one file

> **Status: PARTLY CODED** — the container, manifest, verification, writing rules, outbound filter,
> content id and signature check are coded in `bridge/golemfile.py` and `bridge/signatures.py`, and songs
> are installed by `bridge/songs.py`; several reserved parts (booklet, record tones, versions, fan layer,
> licence, albums on the rack, the desktop reader *golem player*) are **specified but not built** (§12); the album
> reader rules (§12.1) and the video rule (a clip, §12) are **FIXED**, not built.

`bridge/golemfile.py` is a **standalone module** (standard library only, no bridge import) so that golem.fm
can use the very same code; its error messages are in English because they reach the screen.

Related: [`songs.md`](songs.md) (the song record and its storage), [`bars-format.md`](bars-format.md)
(`sync/bars.json`), [`standards-format.md`](standards-format.md) (`.gsx`), [`samples-backings.md`](samples-backings.md)
(the Backing bus), [`separation.md`](separation.md) (stem names), [`karaoke.md`](karaoke.md),
[`golemfm-protocol.md`](golemfm-protocol.md).

## 1. Principle

- **One extension, `.golem`, for every golem object.** The type is in the manifest: `song` or `album`
  (`golemfile.TYPES`); other types later without a new extension.
- A `song` is the recording, its stems, tab, chord chart, lyrics, images, the timing of all of it, and
  optionally how someone plays it.
- **Samples are not included**: a sample used by `sheet.json` stays a reference, `unresolved` on a rack
  that lacks it.
- **Everything is optional except the manifest.** A public card is a `.golem` with only the manifest and
  the timing; a full song has everything. **Presence of files says what is there, never a declaration**:
  the manifest lists every expected file with its hash and a reader observes what is present. There is no
  `complete` field.
- **`.golem` is the rack's native storage**: every song of the library **is** a `.golem` in `songs/`
  ([`songs.md`](songs.md) §3). There is no export step.

## 2. The container

A **zip**. Layout (`golemfile.KNOWN_DIRS`, `KNOWN_FILES`):

```
<song>.golem
├── golem.json            the manifest — the only required member
├── audio/original.<ext>  the recording, original bytes
├── stems/                one stem per part (§5)
├── scores/song.gp        the tab: one .gp, one track per instrument (§6)
├── chart/song.gsx        the chord chart, optional (§6)
├── lyrics/song.lrc
├── sync/                 bars, tab timing, lyrics offset (§8)
├── art/                  images (§9)
├── booklet/ video/ tones/ versions/   reserved (§12)
├── sheet.json            how someone plays it — optional (§9)
├── sheets/               reserved for one sheet per musician; ignored by a golem/1 reader
├── mine/                 the owner's layer (their takes), outside the manifest and the signature
├── signatures/           only for a signed original (§10)
└── songs/                album only: one song .golem per track
```

Writing rules (`golemfile.write`, `replace`, `_put`):

- **Media are stored without recompression** (`ZIP_STORED` for audio, images, video, `.golem`, `.gp`;
  `golemfile.STORED_EXT`), text is deflated. A member can be read without extracting everything, and
  rewriting the manifest is a copy, not a re-encode.
- **No date in the archive**: every member is dated `1980-01-01` (`ZIP_DATE`), `create_system` and file
  mode are fixed, the manifest comes first, the rest is sorted, and `files` is written sorted
  (`manifest_bytes`). The same song gives the same file byte for byte, and no file says when (so by whom)
  it was made.

Safety (`_guard_zip`, `safe_path`), checked before anything else: no absolute path, `..` or `\`; no
encrypted member; no duplicate name; at most 5000 members, 20 GB unpacked, and a compression ratio of 200
for members above 16 MB.

**Watched folder** (`bridge/inbox.py`): every `.golem` dropped into the user's chosen folder
(`config/inbox.json` `{"dir": …}`, default `~/golem-inbox`) is installed by the same path as golem.fm's
`song-install` job (`songs.install_golem`). A file still being copied (size or mtime changing between two
reads 3 s apart) is left alone; installed files move to `.imported/`, refused ones to `.refused/` with a
`<file>.why.txt`. Nothing is ever deleted. Non-`.golem` files are ignored. `GET /api/inbox` lists recent
events.

## 3. The manifest — `golem.json`

```json
{
  "format": "golem/1",
  "type": "song",
  "id": "rs:3f2a…",
  "title": "…", "artist": "…", "album": "…",
  "genres": [ { "family": "rock", "subgenre": "instrumental-rock" },
              { "family": "metal", "subgenre": null } ],
  "credits": {
    "work":      { "composers": ["…"], "lyricists": [], "iswc": "<ISWC>" },
    "recording": { "performers": [ { "name": "…", "part": "guitar-1" } ],
                   "producer": "…", "label": "…", "year": 1990 }
  },
  "kind": "cover",
  "rights": { "work": "third-party" },
  "recording": {
    "isrc": "<ISRC>",
    "fingerprint": { "algo": "chromaprint", "value": "AQAA…", "duration_ms": 362480 },
    "duration_ms": 362480
  },
  "files": {
    "audio/original.mp3": { "sha256": "…", "bytes": 8701233, "codec": "mp3", "rate": 44100, "channels": 2 },
    "stems/vocals.mp3":   { "sha256": "…", "part": "vocals", "origin": "separated" },
    "scores/song.gp":     { "sha256": "…", "tracks": [ { "track": 0, "part": "guitar-1" } ] },
    "lyrics/song.lrc":    { "sha256": "…" },
    "sync/bars.json":     { "sha256": "…" }
  },
  "production": { }
}
```

Checked by `golemfile.check_manifest`:

- `format` = `golem/<major>`. A major **above** the reader's (`FORMAT_MAJOR = 1`) is refused with "update
  the golem"; unknown fields, files and folders are **ignored**, never an error. Within one major only
  optional things are added; anything that breaks an existing reader raises the major.
- `type` ∈ `song`, `album` — **declared and checked against the structure** (`verify`): a `song` cannot
  contain `songs/`; an `album` has no `audio/` and must contain `songs/*.golem`.
- `id`: required, opaque, never rewritten — `bs:`, `rs:`, `us:` or `ct:` for a song
  ([`songs.md`](songs.md) §2; `ct:` in §4).
- `files`: **every expected file**, present or not, keyed by a safe path, each with a 64-hex `sha256`.
  Audio under `audio/` or `stems/` must be **WAV, MP3 or FLAC** ("convert it first"); nothing is decoded on
  import, and a file is never transcoded (the original bytes keep a stable hash, and the timing was made on
  that exact file).
- `genres`: one or two ordered `{family, subgenre}` pairs, `subgenre` may be `null`
  ([`genres.md`](genres.md)).
- `kind` (`cover` | `original`) and `rights.work` (`own` | `public-domain` | `third-party`, absent =
  `third-party`) are **declared**. What proves an original is the **signature** (§10), not `kind`.
- `release.kind` = `"demo"`: golem.fm publishes the track as a demo (free listen and download, never sold).
  Absent = sold or unknown. The rack reads it as the song's `demo: true` (`songs._read_golem`), only to show it;
  it proves nothing and the rack never writes it.
- `credits.work` (the composition: composers, lyricists, ISWC) and `credits.recording` (who plays which
  `part`, producer, label, year) are separate because rights separate them.
- `production`: what a golem did (`recorded`, `mixed`, `mastered`, each `{by, at, …}`); absent = not done
  by a golem. `"by": "external"` with a `tool` is a declaration by the band, shown as such. It is not
  attested yet: the screen shows it as a declaration.
- A legacy `separation` field is ignored: a `.golem` never names the engine that separated its stems.

**Verification** (`golemfile.verify`) returns `{manifest, present, missing, undeclared, unknown}`: a
declared file that is **absent** is normal (`missing`); a present file whose hash or declared `bytes` does
not match is an **error**; files in known folders without an entry are `undeclared` (`mine/`,
`signatures/`); members in unknown places are `unknown`, ignored and never extracted.

## 4. Leaving the machine — the outbound filter

"A `.golem` says what the song is and who plays it. It never says who made it, nor for whom."
`golemfile.outbound(src, dst, id=None)` writes the copy that may **leave** a machine (deposit on golem.fm,
export); golem.fm applies the same function to everything it serves. The rack's internal copy does not go
through it.

- From the manifest (`outbound_manifest`): `golemfm` and `repertoire` (sync state, slug) and every
  `production.*.serial` (a rack's serial is tied to an account); outside a signed original, also
  `credits.recording.performers[].person`.
- From `sheet.json` and `mine/*.json` (`_strip_owner`): every key of `OWNER_KEYS` (person, band, user,
  account, rack, serial, device, editor…); **private captures** (refs `local:…`) lose their reference and
  their `deps` entry (the hash of a unique `.nam` would designate who captured it) — the block stays and the
  receiver sees it `unresolved`; a golem.fm `slug` is removed, except a backing's, which becomes the file's
  id.
- From `sync/bars.json` (unsigned files only): its `slug`.
- `id`: a new id may be given (a `ct:` id); a **signed** original keeps its artist's id, and its signed
  manifest bytes are kept under `signatures/golem.json` so the signature stays verifiable.

**Content id `ct:`** (`golemfile.content_id`, `CONTENT_ID_VERSION = "golem-ct/1"`), derived from what the
song **is**, never from the account, so two people with the same song get the same id: the key is a valid
ISRC (dashes and spaces removed, upper case), else the MusicBrainz recording id, else artist + title
normalized (NFKD, accents removed, casefolded, non-alphanumerics → one space) + kind (`original` or
`cover`). id = `ct:` + the first 32 hex of `sha256("golem-ct/1|" + key)`. golem.fm computes it; the rack
passes it to `outbound(id=…)`. Changing the rule means changing `CONTENT_ID_VERSION`.

**Light copy** (`golemfile.light_copy`): everything except `audio/`, `stems/`, `video/`, with the **same**
manifest (those entries then read as `missing`). It is still the same song.

**Category** (`golemfile.category`): `song` if `scores/song.gp` is present; `standard` if
`chart/song.gsx` is present and there is no audio (present or declared); `vocals` if there is audio
(present or declared) and `lyrics/song.lrc` is present; `track` if there is audio (present or declared) and no
tab, no chart and no lyrics — a song **waiting for its tab or lyrics**, as a folder separated on the golem gives
([`separation-batch.md`](separation-batch.md) §7, 2026-10-21); otherwise none. A `track` counts in the songs
section of the quota.

## 5. Stems — `stems/`

**One stem per instrument, no cap other than the 16 of the stem vocabulary**
([`separation.md`](separation.md) §7). The manifest says where each comes from (`files[…].origin`) and
which part it is (`files[…].part`) — the manifest counts, not the file name.

| `origin` | From | `part` |
|---|---|---|
| `separated` | a separation engine, from the original | the engine's stem names: `vocals`, `drums`, `bass`, `guitar`, `piano`, `other`… |
| `recorded` | lane takes (an original made on a golem) | the part, with lane roles: `guitar-1`, `bass-1`, `voice-1`, `keys-1`, `drums-1`… |
| `imported` | stems made elsewhere and deposited by the band | the part, chosen by the band |

- A stem is one instrument, mixed (the drums are one stem even if recorded with eight mics).
- Formats: WAV, MP3 or FLAC; the manifest notes the codec. All stems **start at zero and have the same
  length** ([`samples-backings.md`](samples-backings.md)).
- A `.golem` filed by a golem always carries its stems: the rack cannot regenerate them.
- For a recorded original, `audio/original` is the **reference mix** rendered from the stems; the
  fingerprint and `sync/` are based on it. If imported stems come without a mix, golem.fm renders
  `audio/original` as their sum.
- **A stem recorded over a standard** carries the version it was played in:
  `"take_of": {"key": "Gm", "tempo": 132, "form": ["A","A","B","C"], "chorus": 3}`. If the song's current
  key, tempo, form or chorus count differ, the rack **mutes that stem and says why** rather than play out
  of tune (`songs.stem_takes`).

## 6. Tab and chord chart

- **Tab** `scores/song.gp`: **one Guitar Pro 7/8 file**, original bytes, one track per instrument.
  `files["scores/song.gp"].tracks` maps track index → part; a track without a part stays displayable. All
  tracks share one timing.
- **Chord chart** `chart/song.gsx`: any song may carry one ([`standards-format.md`](standards-format.md));
  the `.golem` carries it unchanged. golem.fm displays the chart while playing; the rack's Standard block
  can play it as a simulated accompaniment.
- **A standard** is a `song` with **no `audio/original`**: `chart/song.gsx`, `sheet.json` (Standard block
  settings and the arrangement) and a `sync/` **computed** from the chart (tempo × bars × form), not
  calibrated. Musicians can add their own `recorded` stems (with `take_of`, §5).

## 7. Lyrics — `lyrics/`

`song.lrc`, original bytes. The rack carries it and never displays it. A `.golem` is enough for the Vocals
mode: stems (including `vocals` or `voice-*`), lyrics and timing; when the karaoke plays a `.golem` of the
rack that golem.fm may not serve, the rack relays the lyrics text over the follow WebSocket, in transit
only ([`karaoke.md`](karaoke.md) §6).

## 8. Timing — `sync/`

**Produced by golem.fm** (its calibration interface); the rack files these files and computes none. All
times are in the original's time base: another copy whose leading silence differs re-times everything with
**one offset**, measured by the fingerprint.

| File | Content |
|---|---|
| `bars.json` | the bar map: each bar's start, meter and beats, the end of the song, named sections ([`bars-format.md`](bars-format.md)). Played by the rack (parts, click on the real bars) |
| `score.json` | tab timing: `{"v": 1, "start_ms", "points": [{"barIndex", "barOccurence", "barPosition", "millisecondOffset"}…]}` (alphaTab sync points, repeats unrolled); instant in the original = `start_ms + millisecondOffset`. Produced and read by golem.fm; **the rack carries it without reading it** |
| `lyrics.json` | global lyrics offset, if the `.lrc` is not already timed on this original |

A public card carries `sync/` **without** the content of tabs or lyrics: times and bar numbers, not a note
nor a word.

**No video timing** (FIXED, the maintainer's decision of 2026-10-26): a video is a clip with its own audio (§12)
and is **never** synchronised with `audio/original`. `sync/video.json` is no longer part of the format; a reader
that finds one ignores it.

## 9. How someone plays it — `sheet.json`, and images

`sheet.json` is the song's sheet (preset, scenes, arrangement, tempo, tuning, capo — [`songs.md`](songs.md)).
The preset travels **by content**, under the key `preset_doc` (`songs.PRESET_KEY`):
`{schema_version, id, fingerprint, source_mtime_ns, preset, deps, unresolved, catalog_version}`, the same
shape as a preset export ([`preset-format.md`](preset-format.md) §8). Captures and kits are designated by
`sha256`, **never embedded**; what was missing on the writing rack is listed.

- **Refresh**: the copy is rewritten **in the background** when the preset has been stable for 60 s
  (`SNAPSHOT_SETTLE_S`) and **never while playing** (backing, take, arrangement) — `app.py`
  `_golem_preset_snapshots`, `songs.snapshot_preset`. Editing only the sheet keeps the copy.
- **On arrival** (`songs._adopt_preset`): preset absent → **created** (migration, system volume, unique
  block and branch ids checked); present with the same `fingerprint` → nothing; present and **different**
  → the rack **keeps its own** and the install report says so. Missing captures are **listed**, never
  downloaded automatically.

**Images** `art/`: cover, band photo, others; `files[…].role` ∈ `cover` | `band` | `other`. A cover's
images are a private copy for its owner, never in a public card; a signed original shows its images
publicly.

## 10. Signatures — `signatures/`

Only for an **original** published in the clear. golem.fm signs the **exact bytes** of the `golem.json`
member as written (no canonicalization) with the account's Ed25519 key (person or band).

- `signatures/manifest.json` = `{v: 1, alg: "ed25519", key_id: "k:<16 hex>", signer: {type: "user"|"band",
  id, name}, signed_at, sig: <base64>}`. Public keys: `GET /api/ext/keys`, cached in `songs/.keys.json`;
  offline, the last known list (revocations included) is used and the screen says so; an unknown key
  triggers one refresh.
- `signatures/` and `mine/` are written in the archive but **never listed in `files`**
  (`golemfile.UNLISTED_DIRS`): listing the signature would change what it signs, and adding a take to
  `mine/` must not touch the signed manifest.
- **The rack rewrites `golem.json`** (the `repertoire` key, then the sheet). So at installation,
  `songs.install_golem` keeps the signed bytes under `signatures/golem.json`, and verification
  (`signatures.check`) uses that member if present, else `golem.json`.
- A signature is **valid** if the key is known, not revoked, its owner is the `signer`, Ed25519 verifies
  (pure Python, RFC 8032, `bridge/ed25519.py`) — **and** the content is still what was signed: the current
  manifest's `id`, `type`, `title`, `artist`, `kind` equal the signed ones; every band-layer file has its
  signed hash (an absent file, e.g. in a light copy, is not a fault); no band-layer file is outside the
  signed manifest. The owner's layer (`sheet.json`, `mine/`, `signatures/`) is not checked. Without these
  checks, keeping the signed bytes would lend a real signature to any other content.
- The signature **conditions nothing**: every `.golem` opens. It is shown ("Signed · by <band> ·
  verified").

## 11. What the rack does with an incoming song (`songs.install_golem`)

1. Verify the whole file (paths, zip guards, version, type, audio formats, hashes). Only `song` is
   installed ("albums are not installed yet — only songs"); the id must be `bs:`, `rs:`, `us:` or `ct:`.
2. **Attach by fingerprint** (`_same_recording`, `bridge/fingerprint.py`) when the id is **unknown**:
   same recording = duration within ±2 s, then Chromaprint fingerprints compared by bit error rate at the
   best offset (≤ 0.15, `SAME_MAX_BER`) — never by title. The rack **compares**, it never computes a
   fingerprint (the manifest's `recording.fingerprint`, or the one golem.fm put on the catalogue card).
   - like a song of the rack **without media** (a sheet, a card) → its media **complete** it: it keeps its
     id, sheet and sync;
   - like a song that **already has its media** → refused: "same recording as your song … — already
     complete";
   - like nothing → a new song.
   "Replace with a file…" (`replace_into`) replaces the media of a song by a file of the **same recording**,
   even if complete; another recording is refused.
3. **Merge**: an unknown song is created as it arrives, minus its `repertoire` key (another rack's sync
   state); its golem.fm slug comes from the transport (the job, or the catalogue cards), never from the file.
   A known song takes the file's media and identity, and **keeps** its own `sheet.json`, `repertoire` and
   `mine/`. The old file is replaced in one move.
4. The rack receives **only `.golem` files**: an MP3 is not dropped on the rack for processing; golem.fm is
   where a `.golem` is made from an audio file.

## 12. Specified, not built

These parts are reserved in the format (their folders are known, so a reader ignores them gracefully) but
nothing on the rack produces or uses them yet:

- **Album** `type: "album"`: `golem.json` (title, artist, track order), `art/`, `booklet/`, `songs/*.golem`
  — verified by the rack, not installed.
- **Booklet** `booklet/`: `booklet.json` (theme + pages), `img/`, optional `scan.pdf`. Pages are **data**
  (no HTML): blocks (`image`, `text`, `lyrics`, `credits`, `quote`, `tracklist`), page templates with named
  slots (`cover`, `photo-full`, `photo-left-text-right`, `lyrics`, `lyrics-over-photo`, `credits`, `grid-4`,
  `quote`, `tracklist`), and themes. Square pages; `at` anchors a page to a section of `sync/bars.json` so
  it turns with the music; an unknown template or theme falls back to stacked blocks. golem.fm owns
  templates and themes.
- **Video** `video/` (FIXED, the maintainer's decisions of 2026-10-26; not built): a video is a **clip** — its own audio
  track, its own edit, its own length, even for a live video edited on golem.fm. It is **never** synchronised with
  `audio/original`: no video offset, no `sync/video.json`, no lyrics laid over a video. A reader plays the clip on
  its own sound. **One codec**: MP4 with H.264 video and AAC audio, **faststart** (the `moov` atom at the front, so
  a reader reading by ranges, §12.2, can start playback before the end of the file); golem.fm converts at upload,
  one version, 1080p at most and never upscaled. A `video/` member in any other container or codec is ignored by a reader ("unsupported
  video"); a non-faststart MP4 may be played only once fully downloaded. **Who may carry a clip is decided
  where a clip is added, not where it is read**: golem.fm at upload and the rack accept a clip only on a song recorded
  on a golem (an attested `production.recorded`) or a signed original. A reader plays any conforming clip and never
  ignores one because of the song's kind, rights or production. The light copy still leaves `video/` out (§4). The code does not narrow yet: `golemfile.STORED_EXT` still lists `.webm` and `.mov`,
  `verify` checks no video codec, and nothing on the rack adds a clip or checks who may carry one
  (`golemfile.replace` writes any member).
- **Record tones** `tones/`: one preset per part (`guitar-1.json`…) and the band's own captures in
  `tones/captures/`; third-party captures stay references.
- **Versions** `versions/`: earlier versions (idea, demo, live), each with a label, date, audio and
  `production`.
- **Owner's layer** `mine/`: the owner's own takes with `mine/mine.json` (takes, part, date — no person or
  account id), outside the signature; never replaces a band stem.
- **Machine-readable licence** `license: {tier: "repertoire" | "cover" | "open", attribution, since}`, and
  **revisions** (`rev`, `changelog`), and `credits.supporters` (only with each supporter's consent).
- **Attested production**: by golem.fm (the `sha256` of `recorded.takes` match uploaded takes) or by a
  per-machine key. Until then, `production` is a declaration.
- **Readers outside the rack**: golem.fm's reader (stem player, lyrics, booklet; it also opens a local file
  without uploading it) and **golem player**, the desktop reader (decided 2026-10-26; Tauri + React,
  `github.com/Goldoralf/golem-player`, spec in its `docs/concept.md`). golem player plays local `.golem` files for
  free (local library, playlists, A-B loop, slow-down without pitch change). With an
  account (optional) it also streams from golem.fm **what the account owns** — bought records and the songs of the
  user's private space — and nothing else. A purchase downloads as a `.golem` **without DRM** and contains
  everything. The player shows `audio/original`, lyrics, the booklet and the clip (`video/`); it **never** shows the
  tab or the chord chart (`scores/`, `chart/` stay golem.fm's and the rack's), even when the file carries them.
  **It plays no stems** (FIXED 2026-10-26): `stems/` is neither played nor summed, even when `audio/original` is
  missing — such a song is listed as **not playable**, and a file with no audio at all (a standard) is skipped.
  It renders golem.fm's booklet templates and themes from an embedded copy of golem.fm's booklet catalogue.

### 12.1 Reading an album (FIXED 2026-10-26 — golem player is the first reader that needs it)

Nothing writes an album `.golem` yet (neither the rack nor golem.fm); these rules, validated by the maintainer on
2026-10-26, are what a reader does, and what a writer must therefore produce.

- **Track order**: the album manifest carries `tracks: [{"file": "songs/<name>.golem", "disc": 1}, …]` (`disc`
  optional, default 1); **the order of the list is the order of the record**. Each listed file is also in `files`
  with its `sha256` like any member. Without `tracks`, the order is the sorted file names of `songs/` (a writer
  names them `01-…`, `02-…`). A `songs/*.golem` present but not listed is **not played** (undeclared, as on the
  rack); a listed track that is absent is shown as missing, like any `missing` member.
- **Title, artist**: the album's come from the album manifest; each track shows its **own** song manifest (a
  featuring, another artist on a compilation).
- **Art**: the album's `art/` is the cover of the record. On a track, the song's own `art/` wins; a track without
  art shows the album cover.
- **Booklet**: inside an album, the album's `booklet/` is **the** booklet; song-level booklets are not merged into
  it (a song's booklet shows when that song is opened on its own). The track that is playing anchors the pages:
  an album page with `"at": {"section": "chorus"}` turns on that section of **whichever** track plays (its
  `sync/bars.json`). **Open**: a page aimed at one track needs a way to name it (e.g.
  `"at": {"track": 2, "section": "chorus"}`); nothing reads or writes that yet.
- **A track that fails verification**: the album container is checked first (zip guards, manifest, structure,
  §2–§3) — if it fails, the whole file is refused. A track whose bytes do not match the album manifest's `sha256`,
  or that fails its own verification as a song, is shown **unavailable** ("damaged"), never played and never
  repaired; the other tracks play. A signed album with a damaged track is no longer shown as an original (the
  signature covers the manifest, so the content was altered). This isolation is the reader's; the rack, which does
  not install albums (§11), keeps its all-or-nothing `verify`.
- **Kind of release** (validated by the maintainer on 2026-10-29): `release.kind` on the album manifest ∈
  `album` | `ep` | `single` | `live` | `compilation` | `demo`; absent = unknown. golem.fm writes only `album`, `ep`,
  `single` and `demo` on an album; `live` and `compilation` are reserved. A song manifest may carry its own
  `release.kind` (`demo`, §3; `live` on a live track). A track that says nothing **inherits** its album's kind. A
  reader **ignores** an unknown value — it never refuses the file. A reader may guess a missing kind (track count,
  title) to arrange its pages, but never writes the guess into a file. The rack reads only `demo`, on a song.
- **Dates**: `release.date` (`"YYYY-MM-DD"`, the publication date) on the album and its tracks is the sort key of
  releases; `credits.recording.year` stays the recording year (same shape as a song's). Without `release.date`, a
  reader sorts by the album's `credits.recording.year`, else by its first track's.

### 12.2 Reading a `.golem` over HTTP Range

Reading member by member through Range requests works, with these facts from the writer (`golemfile.py`):

- **The central directory, at the end of the file, is the index** — not "manifest first". Read the end of central
  directory (the last 22 bytes + up to 64 KB of comment), then the central directory, then each member: its
  **local header** (30 bytes + its own name and extra-field lengths, which can differ from the central
  directory's) and its data. "Manifest first" only makes `golem.json` the first bytes of the file.
- **ZIP64 must be supported.** `_put` forces ZIP64 for a member above 2 GiB, and Python's `zipfile` writes the ZIP64
  end records by itself as soon as the central directory starts past 2 GiB (`zipfile.ZIP64_LIMIT`); the guards
  allow 20 GB (an album with video).
- **Take sizes and CRC from the central directory.** A file written to a non-seekable stream (`write_stream`, how
  golem.fm assembles a `.golem` on demand) has **data descriptors** (bit 3): its local headers say size 0.
- **Media are `ZIP_STORED`**: a stem or the recording is a plain byte range of the file, seekable for playback.
  Text members (manifest, lyrics, sync, booklet JSON) are deflated: read them whole (they are small). A song inside
  an album is itself stored, so it is a contiguous range: read it as a nested zip over that range.
- **Hashes**: a member's `sha256` can only be checked once the member has been read entirely. A player may play a
  stream from golem.fm before it is complete (owned content, over HTTPS), but checks every member it keeps, and
  never keeps or exports one that fails.
- **`_guard_zip` does not assume a local file**: it reads only the central directory (`infolist`). `read_manifest`
  and `verify(hashes=False)` read the central directory and the manifest only; `verify(hashes=True)` reads every
  declared member (a full download); `open_member`, `read_member` and `extract` take a path. A non-Python reader
  reimplements the same guards over the central directory.
- **Range needs a known length.** A `.golem` streamed by `write_stream` has no length until it ends; a reader can
  seek in it only if golem.fm serves it with a `Content-Length` and `Accept-Ranges` — golem.fm's choice (the
  writing is deterministic, byte for byte, so the same file can be served again identically).

### 12.3 "Send to my golem" from a reader

No new path. A `.golem` reaches a rack by one of the existing doors, all ending in `songs.install_golem`:
golem.fm's `song-install` job (the song is on golem.fm: owned, bought, or in the private space); the **watched
folder** (`inbox.py`) when the reader runs on the rack's own machine or the folder is shared; or `POST
/api/golem/drop` on the rack's LAN, which needs a paired device token (a non-local caller). The rack installs
**songs only**: an album is refused ("albums are not installed yet — only songs") — a reader sends an album's
songs one by one, or waits for albums on the rack.
