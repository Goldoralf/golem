# Backups

> **Status: CODED** — what a backup carries, where it goes and how it is restored (`bridge/backup.py`,
> `bridge/importer.py`, the Backups modal in `app/io-modal.js`, opened by ⇅ Back up… in Settings ▸ Content ▸ Storage).

Neighbours: [`songs.md`](songs.md) (the song library), [`golemfm-protocol.md`](golemfm-protocol.md)
(the vault calls `/api/ext/backups`).

## 1. Categories (`backup.KINDS`, `backup._add_kind`)

| Category | What it carries | Vault |
|---|---|---|
| `presets` | `presets/` + `templates/` | yes |
| `patches` | `library/patches/` | yes |
| `banks` | every setlist (`banks/setlists`) + the pedalboard maps (`mappings/`) | yes |
| `settings` | an **allow-list** of `config/` (§2) | yes |
| `blockpresets` | the user's own block presets in `library/block-presets/` (factory ones come back with the code) | no |
| `amps` · `cabs` | captures and IRs of gear `amp`/`amp-cab` · `cab` (catalog entries + files) | yes |
| `pedals` | gear `pedal` **and** `outboard` (captured preamps, compressors) | yes |
| `kits` | kits, samples, reference DIs | yes |
| `synths` | the user's Vital packs (not `factory`, which is reinstalled) | yes |
| `grooves` | imported `.mid` + `index.json` in `library/grooves/` (not `packs/`, reinstalled) | yes |
| `recordings` | takes of the Rec block (`recordings/`) | yes |
| `standards` | `library/standards/{golem,synced,local}` + `golem/.etag.json` (pulled versions) | yes |
| `songs` | the whole song library — **stays on this rack** | never |
| `originals` | original songs only | yes |
| `setlist` | one setlist + exactly the presets it references (`build_setlist`, see [`setlists.md`](setlists.md)) | yes |
| `all` | `ALL_PARTS`: everything except `songs` and `setlist`, plus `tones-index.json` and `images.json` | yes |

- **A selection** (several categories ticked) makes ONE file, `golem-presets_patches_banks-<timestamp>.zip`,
  declared `custom` in the manifest with the list in `kinds`. The separator is `_` because golem.fm refuses
  `+` in a file name. Ticking everything except songs makes an `all`.
- **Not backed up, on purpose** (`NOT_BACKED`, the screen says so with the size): DrumGizmo kits, SFZ
  pianos, the golem.fm backing cache. The installer reinstalls them or they are pulled again on demand.
- **Manifest** `golem-backup.json` (`FORMAT = 1`): `golem_backup`, `kind`, `kinds`, `created`, `files`
  (SHA-256 per file), `checksum`. It is written last and checked on import.

## 2. Settings, without a secret

`settings` only takes what is named (`SETTINGS_FILES`, `SETTINGS_DIRS`): `click`, `compo`, `devices`, `io`,
`mixer`, `pedals`, `recorder`, `recordings`, `setlist`, `song-folders`, `inbox`, `diag`, `genres` (`.json`),
and the folders `cards/`, `inputmaps/`, `drumkits/`, `modes.local/`.

**Never**: `integrations.json` (keys, golem.fm token), `auth-devices.json` (paired devices), `network.json`
(Wi-Fi), `serial*.json` (the rack's identity). Import applies the same list (`settings_allowed`): a
setting outside it is refused, even if the manifest declares it.

## 3. Restoring (`importer.inspect`, `importer.apply`)

Import first verifies EVERYTHING (manifest, hashes, paths confined to known folders, `_safe_path`) and
writes nothing if one check fails. It then returns a **plan per category**: *new* (absent here),
*different* (present, other content), *identical*. Differences are settled with one strategy:

| UI label | Strategy | Effect |
|---|---|---|
| **Keep mine** | `skip` | the rack's file stays |
| **Use the backup** | `overwrite` | the backup replaces it |
| **Keep both** | `rename` | presets and templates get an `-imported` copy (name suffixed `(imported)`); elsewhere two files with one name cannot coexist, so the rack's file stays |

The strategy applies to presets, templates, setlists, mappings, library files, settings and songs.
**Captures** (`assets/`) and **recordings** (`recordings/`) are written when missing and **never
replaced**. A **safety copy** of the same selection is taken before any write; it appears in Vault under
"before import".

Routes: `POST /api/import/inspect` (upload), `POST /api/import/inspect-local` (a backup already on the
rack or pulled from the vault), `POST /api/import/apply`.

## 4. The vault

`backup.VAULT_KINDS` lists what golem.fm's vault accepts. `backup.vault_refusal(name)` returns the reason a
file cannot go there (shown in English): a backup that contains `songs` never leaves the rack, since
golem.fm never keeps a cover's audio. The `kind` sent must equal the manifest's `kind` (the vault answers
422 otherwise). `golemfm.list_remote` returns `{online, backups[], bytes, max_bytes}`.

A push happens when the user ticks "Also keep a copy on golem.fm", or on every backup when
`integrations.json` → `golemfm.auto_push` is on (Settings ▸ Connect). One push at a time
(`golemfm.push_backup`).

Routes: `POST /api/backup` (`{kind}` or `{kinds:[…]}`, optional `vault`), `GET /api/backups`,
`GET /api/backups/overview`, `GET /api/backup/remote`, `GET|DELETE /api/backup/{name}`,
`POST /api/backup/push/{name}`, `GET /api/backup/push/status`, `DELETE /api/backup/remote/{id}`,
`POST /api/backup/pull`.

## 5. The screen (the Backups modal)

- **Export**: tick categories, one button makes one file and downloads it. Each category shows its size and
  the age of its last backup (rack or vault); what is not backed up is listed.
- **Import**: drop or choose a file, or resume a backup from the rack or the vault; the plan is shown
  before any write.
- **Vault**: one list by date, wherever the backup lives; the auto-push state in plain words; a warning
  when the last full backup is older than 30 days.

Age of a category: a full backup made before the category list was extended (`REFONTE_T`) is counted with
its old content (`LEGACY_ALL`), otherwise categories never backed up would inherit the age of an old `all`.

## 6. Open points

- Safari on macOS unzips downloaded `.zip` files by default: not checked on a Mac yet.
- Windows paths inside the zip are written with `/`; covered by tests, not yet checked on a Windows machine.
