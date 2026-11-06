# Songs (the repertoire)

> **Status: CODED** — the song as a first-class object on the rack: identity, sheet, storage as a `.golem`
> file, resolution by setlist lines, creation on the rack and two-way sync with golem.fm (`bridge/songs.py`,
> `bridge/routes_content.py`, `bridge/golemfm.py`).

Related: [setlists.md](setlists.md) (lines, scope, merge), [arrangement.md](arrangement.md) (the arrangement
engine), [golem-format.md](golem-format.md) (the `.golem` container), [song-folders.md](song-folders.md)
(songs read from folders the golem does not own), [golemfm-protocol.md](golemfm-protocol.md).

## 1. Who owns what

| Level | Carries |
|---|---|
| **Preset** (the rig) | the pedal and the advance rule of the Arrangement block ([arrangement.md](arrangement.md)) |
| **Song** | the **sheet**: preset, arrangement (parts, `sig`, samples, `count_in`, `live_view`, blocks per part), backing, tempo, tuning, capo, note, per-song blocks |
| **Setlist** | the running order — and, per line, optional evening exceptions ([setlists.md](setlists.md) §5) |

Everything edited on the song page **is** the song: there is no scope switch in Songs. Editing a song changes
every setlist that plays it, except fields a line explicitly overrides.

## 2. Identity

`songs.BS = ^(bs|rs|us|ct):[A-Za-z0-9_-]{1,96}$`. An id is born with the song and **never changes**:

| Prefix | Born |
|---|---|
| `bs:<n>` | on golem.fm, in a band |
| `rs:<uuid4 hex>` | on a rack (`songs.new_id()`); golem.fm keeps it and sends it back as is |
| `us:<32 hex>` | on golem.fm, a personal song |
| `ct:<…>` | a circulating file, id derived from what the recording is; a `ct:` file of a recording the rack already has is attached to it (`_same_recording`) |

- Ids are **opaque**: copied, never interpreted, never renamed from one form to another (a rename between two
  syncing systems loses the write sent under the old name). Same namespace as the `target.id` of Riff targets
  ([compo.md](compo.md)).
- "Born here" is a **declared field**, `born: "rack"`, never read from the `rs:` prefix.
- **`song_slug` is not an identity**: it is a catalogue slug attached to 0..1 song (an original has none; two
  bands covering the same title share it).
- No merge by title: two songs with the same name stay two songs.

## 3. Storage: one `.golem` per song

`songs/<safe id>.golem` (`:` becomes `-` in the file name). Machine state, never committed. The format is
[golem-format.md](golem-format.md); the song module uses:

- **`golem.json`** (manifest): `type: "song"`, `id`, and the identity at top level (`title`, `artist`, `kind`).
  Repertoire sync state lives under the key **`repertoire`** (`rev`, `band`, `song_slug`, `born`, `pulled_at`) —
  not at top level, where the format reserves `rev` for something else.
- **`sheet.json`**: the sheet, plus `preset_doc`, a copy of the sheet's preset (§3.2).
- other members (audio, stems, scores, lyrics…) are copied byte for byte on rewrite (`golemfile.replace`).

**Factory songs** (`library/factory/songs/*.golem`, placed once by `factory.seed`, [factory.md](factory.md) §5.2)
are ordinary songs on disk. `songs.is_factory(sid)` makes them **never go up** to golem.fm: `sync_of` returns
`{"state": "factory"}` (the « ◆ Factory » chip) and `pending` skips them — they have no band.

Older `songs/<id>.json` files are migrated on first access (`songs._migrate()`): written as `.golem`, read back
and compared, then moved to `songs/.json-migrated/` (never deleted). An unreadable JSON stays in place, logged.

Other local files: `songs/.sync.json` (upload state, §6.2), `songs/.preset-seen.json`, `songs/.work/<id>/`
(the unpacked working copy used to play, rebuilt from the `.golem`, which is authoritative — `songs.workdir`).

### 3.1 The cleaned song

`songs.clean(doc)` returns `None` if the id does not match `BS`; otherwise `{id, rev ≥ 1, band?, title?,
artist?, song_slug?, kind?, born?, sheet, pulled_at?}` (texts ≤ 160).

- `kind` ∈ `cover | original`, **declared, never guessed**. Absent means "nature to say", a displayed state, not
  a default. `update()` ignores an empty or unknown `kind`.
- `sheet` = exactly `setlists.SCOPED_FIELDS` (`preset, bpm, tuning, capo, note, backing, arrangement, blocks`),
  cleaned by **the same function as a line** (`songs.clean_sheet` borrows `setlists._clean_line`). A resolved
  line and a sheet must stay byte-comparable, otherwise sync loops on `resend`.

### 3.2 The preset copy

`snapshot_preset(sid)` stores in `sheet.json` (`preset_doc`) the export of the sheet's preset
(`preset_export.build_export`: preset, `deps`, `unresolved`, fingerprint, `source_mtime_ns`). It is expensive
(the zip is rewritten): run in the background, never while playing, and only once the preset has been stable for
`SNAPSHOT_SETTLE_S = 60` s (`preset_snapshot_stale`). A sheet without preset removes the copy. **A factory song never
gets the copy** (`is_factory`): it ships without one, never goes up to golem.fm, and rewriting it changed its
fingerprint — `factory.edited()` then called it changed one minute after the first boot, and factory updates skipped
it for good (2026-10-22). On install, a
carried preset is created if absent, kept if identical, and **the rack's own preset wins** if different
(`_adopt_preset`).

## 4. How a line plays a song

A setlist line that carries `band_song` plays its song ([setlists.md](setlists.md) §3–4):

- `songs.line_sheet(line)` = the song's sheet, overridden **only** by the keys listed in the line's
  `line_overrides`. A line without `band_song` uses its own fields; a song missing from the rack lets the line
  play what it carries.
- `setlists.pid_of(line)` returns the preset of that sheet — so changing a song's preset changes the bank of
  every setlist that plays it (reflash the foot controller chip if its claims depend on it,
  [pedalboards.md](pedalboards.md)).
- `songs.line_title(line)`: the line's own title (an evening exception such as "(acoustic)"), else the song's.
- `recall.effective_preset` applies the sheet when the song is played through a line **or** from the song page
  (▶ Play without a setlist line).

A line added from the repertoire stores only `{id, rev, band_song}`; screens read the resolved view
(`setlists.view_line`).

## 5. Gestures and endpoints

| Route | Effect |
|---|---|
| `GET /api/songs` | the repertoire, sorted by title, each with `parts`, `setlists` (local, `setlists_of`), `preset_here`, `ready` (preset on this rack **and** at least one arrangement part — computed here so "stage-ready" means one thing everywhere), `sync` (§6.2), `file` (what the `.golem` carries); plus `spaces` and `default_space` |
| `POST /api/songs {title, kind, band?, preset?, bpm?, artist?}` | "+ New song": a rack-born song (`rs:`, `born: "rack"`). `title` and `kind` are **required** (no default kind); `band` must be one of the rack's spaces (roster), default = the personal space |
| `GET /api/song/{sid}` | `{song, setlists, sync}` |
| `POST /api/song/{sid} {…}` | edit: sheet fields go to `sheet`, `title/artist/song_slug/band/kind` to the top; an empty value **removes** the field ("no capo" is not "capo 0"); `rev` +1. A song read from a folder is adopted first |
| `POST /api/song-transfer/{sid} {band}` | "Give to <band>": a personal song moves to a band — same id, `band` changes, `rev` +1, no copy. Only personal → band (409 if already a band's) |
| `DELETE /api/song/{sid}` | remove the song **from this rack**; refused (409) while a setlist plays it (its line would be an empty bank) |
| `GET /api/songs/{sid}/files` | "What this song carries": each element of the `.golem`, present / expected-missing / not applicable |
| `GET /api/songs/{sid}/recording` | the identified recording and DRM-free purchase links (offline: last answer) |
| `POST /api/songs/{sid}/store {mode: full\|light}` | "Store on golem.fm" — an explicit gesture, never automatic |
| `POST /api/golem/drop?name=&replace=` | drop a `.golem` (raw body, streamed); only `.golem` is accepted. `replace` = "Replace with a file…": a file of the **same recording** replaces that song's media; its sheet stays |
| `POST /api/setlists/{sid}/songs {ids}`, `…/line/{lid}/to-song {kind, band?}` | add songs to a setlist; "◆ Make it a song" (a free line becomes a song, the line keeps only `band_song`) — [setlists.md](setlists.md) §6 |

Rules:

- A setlist never creates a song; "Add a song" picks from the repertoire. A free line can be turned into a song
  with "◆ Make it a song" (its sheet fields and title move to the song; the kind is asked then).
- Transfers do not change the id. The rack cannot check band membership; golem.fm does when the song is uploaded.
- **Stems come from golem.fm.** The song's "Stems" field picks a song of the golem.fm backing catalogue
  (`/api/backing/catalog`); its stems are cached under `assets/backing/<slug>/` and `sheet.backing` holds the
  slug. Not connected: the field stays empty and says so; cached stems keep playing. Local sample-built backings
  ([samples-backings.md](samples-backings.md)) are not offered to songs.
- Installing a `.golem` (`songs.install_golem`, the single path for the drop folder, the screen drop, folder
  adoption and the golem.fm `song-install` job): the file is fully verified first; an **unknown** song is created
  as it arrives (its `repertoire` key — another rack's sync state — is discarded); a **known** song takes media
  and identity from the file and **keeps its own sheet, `repertoire` and `mine/`**. Only songs are installed
  (not albums).

## 6. Sync with golem.fm

### 6.1 Down: job `song-push`

`{action: "song-push", band?, complete?, songs: [{id, rev, title, artist, kind, song_slug?, sheet}]}` →
`songs.merge_push()`, the same arbitration as a setlist line:

- incoming `rev` higher → golem.fm wins (written with `bump=False`);
- equal `rev`, same body → kept; **equal `rev` and different body, or lower → the rack wins** and the song is
  listed in `resend`;
- the compared body excludes `rev` and `pulled_at` (a local trace that changes without the song changing);
- `complete: true` removes local songs absent from the batch — only those of the given `band`. Without the flag,
  nothing is ever removed;
- every received rev is recorded in `songs/.sync.json`, so a later local edit goes back up and an unchanged
  received song does not.

### 6.2 Up: `POST /api/ext/golem/songs`

`golemfm.push_songs()` (debounced 3 s after any create, edit or transfer) and `push_songs_now(ids)`, which
`push_setlist` calls **before** pushing a setlist that cites those songs (otherwise golem.fm would receive a
reference it cannot resolve).

- `songs.pending()` = songs whose local `rev` is above the last accepted rev and not rejected at this rev. A song
  without `kind` or without `band` is not sent and is reported in `blocked`.
- Wire shape (`wire_song`): `{id, rev, band, title, kind, born, sheet, bpm?, song_slug?}` — `bpm` at top level,
  the sheet without it.
- `apply_ack()` records per song in `songs/.sync.json`: accepted rev, or the rejection reason and the rejected
  rev (a rejected song is resent only once it changes).
- `songs.sync_of()` → what the screen shows: `synced` ("☁ golem.fm · rev n"), `pending` ("↑ waiting for
  golem.fm"), `rejected` ("⚠ golem.fm: <why>"), `rack_only` (rack not paired).

The rack is autonomous: a rack-born song plays, is arranged and joins setlists without golem.fm.

### 6.3 Guards on setlist lines

- When a pushed setlist line comes back without the `band_song` of a **rack-born** song (golem.fm could not
  resolve it yet), the merge keeps the local `band_song` (`setlists._keep_ref`), and such a returned line is not
  counted as a divergence (`_tomb_of_ours`).
- A song line without a title is sent with its song's title **on the wire only** (`songs.wire_titles`); stored,
  it would become an evening exception masking a rename.
- At equal `rev`, a song line is compared on what it declares, never on the resolved copies golem.fm adds
  (`setlists._line_body`).

## 7. Not built

- Pulling a band's full repertoire on demand: `GET /api/songs/source` reports that no source is available yet
  (`available: false` with a sentence for the screen); songs arrive through `song-push` jobs and with setlists.
- Creating an evening exception **on the rack**. No rack screen sends `scope: "line"`: a song line is read in the
  setlist and edited in its song (`app/page-setlist-groups.js` `SongLine`), so every rack edit goes to the song.
  Exceptions are made on golem.fm and arrive with the setlist; the rack plays them (`line_overrides`).
  `POST /api/setlists/{sid}/line {scope: "line"}` and the Gig default (`setlists.default_scope`) exist for a
  future screen ([setlists.md](setlists.md) §5).
- Local propagation of a song edit to other racks' resolved lines: the rack writes into its local song; other
  setlists on golem.fm follow after sync.
