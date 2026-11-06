# Song folders

> **Status: CODED** — the golem reads libraries of `.golem` files it does not own, in place, and copies a song
> onto itself only when it must (`bridge/song_folders.py`, Settings ▸ Content ▸ **Storage**, source filter in Songs
> and Standards); the "newer in folder / Update from folder" gesture is not built.

Related: [songs.md](songs.md) (the repertoire, `install_golem`), [golem-format.md](golem-format.md) (the
format), `bridge/inbox.py` (the drop folder), [backups.md](backups.md).

## 1. Two kinds of folders

| | **Drop folder** (`bridge/inbox.py`) | **Song folder** (`bridge/song_folders.py`) |
|---|---|---|
| gesture | "I drop, the golem adds it" | "the golem looks at what is there" |
| the file | **copied** into `songs/`, becomes a song of the golem | **read in place**, never copied by default |
| volume | a few files at a time | hundreds, thousands |
| afterwards | the dropped file may disappear | the folder stays the reference |

## 2. Rules

### 2.1 A song folder is read, never written

The golem writes into the `.golem` of **its own** songs (sheet, `preset_doc`, `repertoire`, `mine/`). It never
creates, renames, deletes or indexes anything inside a song folder (a friend's disk, a network share). A song read
from a folder is read-only: its write gestures are **not rendered** in Songs (not greyed out).

### 2.2 Adoption

**In place**: listening, rehearsing, singing (Vocals), playing a standard — everything that only reads.

**Adopt** = copy into the golem through the single path `songs.install_golem` (full verification, merge,
recording-fingerprint attachment) — `song_folders.adopt(path)`. Adoption happens:

- on the gesture **"Use on this golem"** (`POST /api/song-folders/adopt {path}`);
- **automatically** when the song enters a **setlist** (`setlists.add_songs` / `place_song`) or when its **sheet
  is edited** (`songs.save` → `songs.ensure_local`). The screen says "Added to this golem — the folder copy is
  untouched".

Why: a disk unplugged or a NAS unreachable on the night of the gig would leave the song silent. **What goes on
stage is on the golem.**

- The category (`golemfile.category_of`) picks the destination: songs and Vocals into `songs/`, standards into
  `library/standards/golem/<slug>.golem` (the chart must be `.gsx` or iReal).
- Adoption is refused when the disk would end above **90 %** (`_check_room`), with the size needed.
- If the adopted file attaches by fingerprint to **another** song of the golem, a write under the folder's id is
  refused ("this file joined another song on this golem (same recording) — edit that one"): writing would create
  a sheet without media.
- Once adopted, the golem's copy is authoritative even if the folder later holds a newer version.
  *Not built:* flagging "newer in folder" and an "Update from folder" gesture.

### 2.3 Identity and duplicates

A song is its manifest `id` ([songs.md](songs.md) §2) everywhere. An entry whose id is already on the golem is
not listed again (`_adopted`). The same id in two folders gives one entry. Another id with the **same recording**
(fingerprint) is flagged `same_as` — never merged silently; adoption attaches.

### 2.4 The index is a cache

`songs/.folders/index.json`, on the golem, never in the folder read.

- An entry = the inventory card (`inventory.card_of`, one definition) + `{path, folder, size, mtime, seen_at,
  state, why?, slug?, same_as?}`. `state`: `ok`, or `bad` with the reason (refused files stay listed).
- **Incremental**: a pass does only `stat`; a manifest is re-read only when size or date changed. Indexing reads
  the **manifest only** (`golemfile.verify(hashes=False)`); full verification happens before playing in place
  (extraction into the working cache) and at adoption.
- Walk: `os.scandir`, no symlinks followed, hidden entries skipped, depth ≤ `MAX_DEPTH = 12`, at most
  `MAX_FILES = 50000` files per folder (beyond, the pass stops and says so). Non-`.golem` files are counted
  (`other_files`).
- When: at startup (background), when a folder is added, on "Rescan", and every `RESCAN_S = 600` s. No inotify
  (costly and unreliable on SMB/NFS).
- Deleting the index loses nothing: files are authoritative.

### 2.5 An absent folder erases nothing

Disk unplugged, NAS off: its entries keep their last known state, marked offline. An entry is removed only if
its folder was read **completely** and the file is really gone — a short listing may come from a failed read.
A folder that is unreadable or not found when being **added** is refused with the reason; folders that are too
wide (system directories, the golem's own tree — `_SYSTEM`, `_too_wide`) or already covered are refused too.

### 2.6 Playing in place

`songs.source_path(sid)` reads the golem's file, else a folder's (`song_folders.path_of`); writing never uses it.
The working copy of a folder song lives in `songs/.work/<id>/` like any other, marked `folder:` in its `.from`
file; only those folder copies are capped at `WORK_CAP_BYTES = 5 GB`, oldest first (`prune_work`).

### 2.7 golem.fm inventory

Folder songs are part of what the golem has and are published in the inventory with `where: "folder"` (golem
songs carry `where: "golem"`) — `song_folders.inventory_cards()`:

- each folder has **"Show on golem.fm"** (on by default); unticked, its titles never leave the machine;
- an offline or partly read folder makes the read **incomplete**: the inventory sends additions only, never
  removals; cards of an unplugged folder stay with their last-seen date.

Folders are not included in backups (they are external); adopted songs are (they are in `songs/`).

### 2.9 What a folder brings (2026-10-17)

A folder holds songs, Vocals lines and standards; the golem **sorts by content** — each `.golem` says what it is
(`golemfile.category`). A folder can also say what it **brings** (`kind`): `auto` (default — everything, sorted by
content), `song`, `vocals` or `standard`. A typed folder is a **filter, not a switch**:

- only entries of its kind are offered from it — in Songs, in the Standards catalogue, on golem.fm (inventory);
- the rest stays in the index, is **counted** (`ignored`, shown as "12 not Vocals — ignored"), and is never
  reclassified: a song in a "Vocals" folder stays a song, it is just not offered from there;
- after a complete pass, an `auto` folder holding a single kind **suggests** it (`suggest`: "Only Standards in this
  folder — mark it Standards").

Reading cost is the same either way (the manifest must be opened to know the kind); the gain is clarity — a
2 000-song karaoke library does not flood Songs.

## 3. Configuration and endpoints

`config/song-folders.json` (local, git-ignored): `{folders: [{path, show_on_golemfm, added_at}]}`.

| Route | Effect |
|---|---|
| `GET /api/song-folders` | every folder with state and counts (`overview()`), plus `drop_folder` |
| `POST /api/song-folders {path}` or `{paths: [...], show_on_golemfm?}` | add one or several folders; each refusal comes back in `refused` with its reason, without blocking the others |
| `PATCH /api/song-folders {path, show_on_golemfm}` | toggle inventory publication |
| `PATCH /api/song-folders {path, kind}` | what the folder brings: `auto` · `song` · `vocals` · `standard` (§2.9) |
| `DELETE /api/song-folders?path=` | stop reading the folder — **never** touches a file |
| `POST /api/song-folders/rescan {path?}` | rescan one folder or all |
| `GET /api/song-folders/browse?path=` | rack-served folder browser (sub-folders only, no file names), starting from bounded roots: home, mounted disks, network mounts; counts `.golem` files per folder within a small time budget |
| `GET /api/song-folders/songs?q=&category=&offset=&limit=` | folder songs, one per id, those already on the golem excluded; searched rack-side (limit ≤ 500) |
| `POST /api/song-folders/adopt {path}` | "Use on this golem" |
| `GET /api/storage`, `POST /api/storage/clear {cache: peaks\|work\|backing}` | the Storage page (disk, music by category with last backup age, caches); clearing never touches the loaded song |

A folder's **location** is read from the system, not declared (`song_folders.location`): this disk, another
disk, external (USB/removable) or network (cifs, nfs, sshfs, gvfs shares) — `/proc/mounts` + `/sys` on Linux,
`GetDriveTypeW` on Windows, `mount` on macOS. It is kept across passes, so an offline NAS keeps its label.

**UI.** Settings ▸ Content ▸ **Storage**: the golem's disk on top, music by category (Songs, **Vocals** and
**Standards** are three rows — Vocals lines live in `songs/` with the songs and are told apart by the category their
`.golem` carries, `storage._songs_by_category`), the song folders ("read where they are — golem never writes there";
per folder: its kind as a chip, "This folder brings Auto · Songs · Vocals · Standards", Rescan, Show on golem.fm,
"Stop reading this folder"; the ignored count and the suggestion under its name) and the clearable caches. "+ Add folders" (top bar) can tick several folders at once. In Songs and the Standards drawer, a
folder song carries a folder badge and "Use on this golem".
