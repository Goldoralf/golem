# The read-only shell — the rack's interface shown by golem.fm

> **Status: CODED** (rack side) — the `?shell=ro` flag, the snapshot tool `tools/shell_snapshot.py` and its
> redaction rules, the GET read shapes golem.fm relies on, and the pure module `bridge/preset_view.py`.

Related: [`golemfm-protocol.md`](golemfm-protocol.md) (the rack ↔ golem.fm contract) ·
[`golem-format.md`](golem-format.md) (same copy pattern as `golemfile`) · [`backups.md`](backups.md)
(what never leaves the rack) · [`glossary.md`](glossary.md) ("shell").

## 1. The principle

golem.fm shows the **exact** rack interface, the whole app, in an iframe. `app/` is copied as is, pinned to a
commit, together with `library/catalog/*.json` and `library/block-presets/**` from the same commit. golem.fm
injects its own `shell.js` before `main.js`: it answers `/api/…` reads with JSON it owns, drops writes,
replaces the WebSocket with one pushed `state` snapshot, and isolates `localStorage`. There is no fake
bridge and no driven navigation. Uses: preset and patch pages, the builders (the AI makes, the screen
shows), the public site, and tutorials built on a **snapshot** of a real rack.

## 2. `?shell=ro` — an honest screen

`index.html?shell=ro` sets `data-shell="ro"` on `<html>` before any render (a script at the top of
`app/index.html`). `app/style.css` then hides editing controls with `display:none !important` on an
attribute selector, so that a more specific author rule cannot show them again (the `hidden` pitfall,
[`pitfalls/ui.md`](pitfalls/ui.md)). Without the flag a button would stay visible and do nothing (writes
are dropped): a dishonest screen.

**Hidden**: topbar actions (`.tb-right`, `.tb-action`, `.tb-new`, `.tb-io`), Songs page gestures
(`.sgn-acts`), delete buttons (`.mini.danger`, `.dv-fl.danger`, `.scn-danger`, `.del-foot`, `.rec-del`,
`.bkg-del`, `.amp-del`), the folder menu and the Storage "Clear" buttons, "Stop golem" (`.sys-halt`), the
Designer's add and save controls, and anything marked `edit-only`. The full list is the
`[data-shell=ro]` rule in `app/style.css`.

**Anchors**: `data-doc="…"` on an element is a contract with golem.fm's documentation (its halo and its taps);
the list is in [`user-docs.md`](user-docs.md) §4.

**Rule for new code**: a new editing control carries the class **`edit-only`**. A control that **shows a value**
(a segmented choice, a switch, the selected engine, the buffer size) carries **`ro-inert`** instead: it stays
on screen and ignores touches (`pointer-events: none`) — hiding it would hide the value with it. Better still, a screen
does not **render** it: `import { SHELL_RO } from './lib.js'`.

## 3. The snapshot — what is removed

```
./tools/shell_snapshot.py [--base URL] [--out DIR] [--list reads.txt] [--private-name NAME]…
```

It walks the app's GET reads on a running bridge and writes `<out>/api/<path>.json`. Each segment is
encoded (`rs:abc` → `rs%3Aabc`, portable to Windows; a query `?x=1` → `__x%3D1`). `--list` = the list
golem.fm recorded; without it, a default list (`DEFAULT_READS`) plus each preset (`/api/preset/<id>`),
patch (`/api/preset/patch:<id>`) and song (`/api/song/<id>`, `/api/songs/<id>/files`).

**Removed by field NAME** (`SECRET_KEYS`, compared case-insensitively with `-`, `_` and spaces ignored) →
`<redacted>`: `token`, `access_token`, `refresh_token`, `device_token`, `secret`, `client_secret`,
`password`, `passwd`, `psk`, `passphrase`, `api_key`, `publishable_key`, `private_key`, `hint`, `auth`,
`authorization`, `cookie`, `email`, `mail`, `owner_email`, `ip`, `ips`, `ipv4`, `ipv6`, `addr`, `address`,
`local_address`, `mac`, `mac_address`, `hostname`, `host`, `ssid`, `bssid`, `serial`, `serial_number`,
`issued_by`. **Not `key`**: that is a song's musical key ("Am").

**Removed by value SHAPE**, everywhere (keys included):

| Shape | Becomes |
|---|---|
| e-mail | `<email>` |
| IPv4; IPv6 (at least 4 groups, or `::`) — a time like `02:45:05` is not one | `<ip>` |
| MAC address | `<mac>` |
| rack number `golem_N` | `golem_0` |
| a `*.local` name, the machine's host name | `<host>` |
| absolute path inside the rack | relative to the rack (`songs/a.golem`) |
| absolute path inside the home directory | `~/…` |
| any other absolute path (`/media`, `/mnt`, `/run`, `/tmp`, `/opt`, `/var`, `/Users`, `/Volumes`, `C:\…`…) | `<path>` |

A value that **starts** with an absolute path is a whole path, spaces included.

**People and devices** → `Musician A`, `Musician B`… and `Device A`…: a **constant pseudonym**, so the same
person keeps the same alias everywhere (id, short name, full name) and the screen stays coherent without
naming anyone. Two passes, because a person is not always in a "person" field:

1. **Collect** people from roster fields only (`person`, `person_name`, `loaded_by`, `owner_name`,
   `user_name`, `display_name`, `member_name`; `device_name`, `editor` for a device), from the containers
   `persons`, `people`, `members`, `roster` (`{person: {…}}` → the keys, `{n: "person"}` → the values,
   `[{id, name}]` → id and name — never the field names of a record), from `/api/band` (read to collect,
   never written), from the machine user's full name, the repository's git user name, and `--private-name`.
2. **Replace** each one wherever it appears, key or value, ignoring case and accents. A **full** name is
   replaced even inside a sentence; a one-word name only when it is the **whole** value (a short name must
   not hit "graphic").

**`author` and `by` are not person fields**: they also carry public credits (authors of free software,
capture creators) that a snapshot keeps. Treating them as people replaced "golem", product names and band
names everywhere. A private author is caught by pass 1 (the git user name), not by the field name.

**Never read, even redacted** (`NEVER`): `/api/auth…`, `/api/network…`, `/api/connect…`,
`/api/integrations`, `/api/golemfm/pair…`, `/api/t3k/auth…`, `/api/band/invite`, `/api/devices…`,
`/api/desktop…`, `/api/diag`, `/api/system/update`, `/api/system/reaper-update`,
`/api/system/reaper-license`, `/api/song-folders/browse`, `/api/meters`, `/api/calibrate…`,
`/api/ui/geometry`, `/api/backup/…`, `/api/import…`, `/api/separation…` (an excerpt's name, typed paths,
a key hint).

**Checked, not assumed**: every file is **re-read** after redaction. If a trace remains (one of the shapes
above, a non-empty secret field, a person's name that is not a pseudonym), the file is **not** written,
the tool says so and exits with an error. The check reads the same shapes as the redaction, so it cannot
see what no shape describes: a **human review** of the output folder is required before any publication.

Band names, setlist names and song titles are **kept**, even in a public snapshot: a band is meant to be
known, and a tutorial shows a real screen. Hiding one specific name would need a dedicated option (not
`--private-name`, which would turn it into a "Musician").

## 3 bis. The factory snapshot

`./tools/shell_snapshot.py --factory [--rev COMMIT] --out DIR` makes the snapshot of the **musicians'
documentation**: a disposable bridge with factory content only (the one `tools/check-ui.py` uses), every page
crawled in headless Chrome with the reads it **actually** makes, the same redaction and check as above, named
**examples** replayed on that bridge, and a `SNAPSHOT.json` (commit, catalog version, reads, examples, images,
`machine` reads). Only in this mode, `/api/separation` and `/api/separation/batch` are
read. Details, the examples and the doc plan: [`user-docs.md`](user-docs.md).

**The audio of the demo (2026-11-04).** A visitor **hears** the factory sounds. The app loads audio with
`<audio src>`, outside `fetch`, so `shell.js` cannot answer it: golem.fm serves each file on a **real route**, at the
exact address the app asks for. The snapshot puts them in `media/` and lists them in `SNAPSHOT.json` →
`media: {address: {file, type}}`:

| Address the app asks for | What | Where it comes from |
|---|---|---|
| `/library/previews/patch-<id>[-in<k>]/<scene>.opus` | the demo of a factory patch, per scene ([`preset-preview.md`](preset-preview.md)) | copied from the rack's demos into the bench (`--no-demos` to leave them out) |
| `/library/previews/preset-<id>/<lane>/<scene>.opus` | the demo of a lane of a factory preset | same |
| `/api/loop/<take>/<track>.wav` | a track of the demo take in Library ▸ Tracks ▸ Recordings — **Ogg Opus** content (96 kb/s), same address | `--take recordings/perf-…`: a real take, cleaned by `tools/demo_take.py` (no band, members, session, guitar or machine mode; the music only, a title) |
| `/api/sample?file=assets/samples/kits/…` | a sound of a factory pad kit (CC0, synthesized by golem) — Library ▸ Drums ▸ Kits | the bench |

Their JSON companions are ordinary reads: `/api/patches` (`preview`), `/api/presets` (`lane_previews`), `/api/loops`,
`/api/loop-peaks/<take>/<track>`, `/api/peaks?file=…`.

**The Separation page of the demo** (`--separation-from URL`): the one of the **reference rack**, its engines and
settings, read on that bridge — the only read of a factory snapshot that does not come from the bench. Its home
folder becomes `/home/golem` (`DEMO_HOME`, the only absolute path a snapshot lets through), and the test excerpt (a
file of the owner, its title included) is renamed `Golem Rising (mix).wav`. The page renders as on a golem
from that read, "Details" included; every action (Test, Use, Stop using, Remove, Add engine, Separate a folder,
Change…, the Share row with Export engine file) is `edit-only`, and the Threads value stays on screen, inert. A shell without that read
shows a fixed placeholder that says what the page does.

## 4. Read shapes golem.fm relies on

- `GET /api/preset/:id` = `store.load_preset(pid)`: the native migrated document, the same as
  `PresetExport.preset` of `POST /api/ext/golem/presets`. Reserved ids are served too: `sandbox-try`, the
  karaoke preset, `patch:<id>`.
- `GET /api/sandbox` = the **raw** content of `presets/.sandbox.json` (`{preset, scene, edit_rev,
  editor…}`): the Designer's edit buffer, not an exported preset. `?prev=1` = the previous version.
- `GET /api/effects` = `library/catalog/effects.json` as is, plus `vst_host: true`, `vst_capture` (true on Windows and
  macOS only) and a `vst-host` block at the end of the list (Linux too since 2026-11-09, [`platforms.md`](platforms.md) §6.1).
- `GET /api/block-defaults` = computed from `library/block-presets/<type>/*.json` marked `default: true`:
  `{defaults: {<type>: {<inst>: params}}}`.
- `GET /api/anim-pack/<id>/css`: loaded by a `<link>` (`designer-model.js`), which escapes `shell.js`'s
  `fetch`; golem.fm serves it on a real route.
- `GET /api/gestures`: golem.fm serves it from its copy of `config/pedalboard/gestures.json` (same commit
  as `app/`).
- **Two JS exports are a contract**: golem.fm replays "open a patch" with
  `openInDesigner(patchDraft(patch))` (`lib.js`, `designer-model.js`).

**A change of SHAPE of a GET read, or of one of these exports, is stated in the commit message.** golem.fm
detects new **addresses** automatically; a shape that changes at the same address would slip past it.

## 5. The preset card — `bridge/preset_view.py`

/live, the Presets card and the foot do not read a preset document: they read a computed **card** (an
entry of `GET /api/presets`) and `state.stomps`. golem.fm has neither, and a TypeScript copy would drift.
The computation therefore lives in a **pure** module that golem.fm copies byte for byte at the same commit
as `app/` (with a fingerprint test), and that the rack itself calls (`store.preset_summary`,
`store.migrate_config`, `recall.stomp_states`): one source.

- `summary(doc, imap=None, migrate_styles=None)` → the `/api/presets` entry for this document, migration
  included.
- `stomps(doc, scene_id, whammy_on=False, imap=None)` → `{switch: bool}`, what the rack puts in
  `state.stomps` (integer keys; strings in JSON).
- `migrate(p, imap=None, migrate_styles=None)` → the document migration **without** the machine
  singletons: the Rec, Click, Compo and Arrangement blocks are placed; their parameters
  (`config/recorder|click|compo.json`) are filled afterwards by `store.migrate_config`. No card field
  depends on them.

**Machine-dependent input is a parameter**: `imap` = the card's input map (`{inputs: [{ch, role, nth}],
midi: {role}}`) — absent, the default roles and no "off card" input (`on_card` true); `migrate_styles` =
the genre taxonomy — absent, styles stay as they are.

**Module rules, held by `tests/test_preset_view.py`**: standard library only (`copy`, `json`, `re`), no
relative import, no file read or write; the document passed in is never modified; without a card, the
module's card equals the rack's.

**Changing the NAME or SHAPE of `summary`, `stomps`, `migrate`, `preset_summary` or `stomp_states` is a
contract change**: say it in the commit message.

## 6. Not built

- Emitting `golem:nav` events (scene, tab, block) in shell mode, so golem.fm can follow the screen.
