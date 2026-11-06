# Identity: devices and people

> **Status: PARTLY CODED** — no login on the rack; persons come from the golem.fm roster cached in `config/.band.json` (`bridge/roster.py`), are attributed per input, and carried by paired devices; the personal golem.fm token on phones and signed actions (§5) are PROPOSED.

Related: [devices-people.md](devices-people.md) (devices, the Companion, conductor),
[connect.md](connect.md) (joining through golem.fm/connect), [patches.md](patches.md) ("my lines",
patches by person), [input-map.md](input-map.md), [diagnostics.md](diagnostics.md),
[golemfm-protocol.md](golemfm-protocol.md) (pairing, heartbeat, roster pull).

## 1. Principles

1. **No login on the rack.** No form, no password, no identity keyboard on the shared screen. It is
   an instrument, not a workstation.
2. **Person identity comes from golem.fm**, cached on the rack. Offline, the last known roster is
   authoritative — a rehearsal never depends on Wi-Fi.
3. **Attribution ≠ authentication.** On the rack screen one **selects** ("IN 3 = <person>") from the
   roster; nothing is proven. Authentication exists only for personal devices.

The pattern on both levels is the **device flow** (RFC 8628): the shared device shows a code / QR,
someone approves from an authenticated device, the server hands a token to the device —
rack ↔ golem.fm pairing (`bridge/golemfm.py`, [golemfm-protocol.md](golemfm-protocol.md) §1) and
local device invitations / pairing codes (`bridge/auth.py`, [devices-people.md](devices-people.md)).

## 2. Devices

| device | is… | token | status |
|---|---|---|---|
| **the rack** | the band's device | one golem.fm device token (`config/integrations.json`, one per server) | coded |
| **each phone** (Companion) | a person's device | ① a rack device token (QR invitation or golem.fm/connect) · ② a personal golem.fm token, kept on the phone, never shown to the rack | ① coded · ② not built |
| **the rack's local screen** | nobody | none (loopback is authenticated automatically) | coded |

The rack writes to golem.fm **as the rack**, with attribution as metadata (`person`, `by`…). It never
impersonates a person.

## 3. The roster — the band in cache

`config/.band.json` (gitignored machine state). Source of truth: golem.fm `GET /api/ext/band`, which
serves **every** space the token owner belongs to (the personal space first).

```json
{ "band":   { "id": "<opaque id>", "name": "…", "slug": "…", "kind": "band", "source": "cache", "synced": "…" },
  "bands":  [ { "id": "<opaque id>", "name": "…", "slug": "…", "kind": "personal|band", "source": "cache",
                "people": [ { "id": "<handle>", "name": "…", "roles": ["guitar", "voice"], "gear": "…",
                              "rights": "owner|admin|member", "prefs": {}, "avatar": "…" } ] } ],
  "people": [ "… mirror of the current space's members …" ],
  "synced": "…" }
```

- `band` = the **current** space: only a default for future takes. The truth is the band tag frozen
  on each take.
- `bands[]` = the spaces this rack knows, **each with its members** (`roster._entry`), so switching
  space offline shows the right people.
- `people` at the root is written by the rack: the mirror of the current space, read by the input
  map and the screens. It follows every switch, even to an empty space.
- Person keys kept (`roster.PERSON_KEYS`): `id, name, roles, gear, rights, prefs, pending, avatar`.
  `roles[]` are input-map instrument ids (`guitar/bass/voice/keys/drums/pads/line`). `gear` is free
  display text, never interpreted. Avatars are downloaded at sync into `config/avatars/` (no Internet
  on stage) and served by `GET /api/band/avatar/{pid}`.

**Sync** (`roster.sync()` → pure `roster.reconcile(payload, cache)`): at bridge start, on the
periodic heartbeat tick, and by hand (`POST /api/band/sync`). Never raises; offline, the cache wins.
Rules, in order:
1. **The catalogue is replaced, the room's choice is not.** `bands[]` and rosters come from the
   server; the current space is kept **by its id**.
2. **Root-level `band` and `people` in the payload are ignored** (transition fields reflecting the
   device's attachment); reading them would switch the room at every sync. Only `bands[]`,
   `default` and `synced` are read.
3. **A current space that disappeared** falls back to `default`, else the unique `personal` space —
   logged, never silent. "None" chosen explicitly stays none. First pairing → `default`.
4. **Migration of a hand-made seed**: a current space with `source: "local-temporary"` whose id
   matches (case/dash-insensitive) the slug, id or name of **exactly one** served space takes that
   space's opaque id, and takes carrying the old id are re-addressed with `band_history[]`
   (`takes.readdress`). Routing is by id, never by slug.

**The rack selects, it never creates.** `roster.set_current(bid)` (`POST /api/band/current`) only
picks among known spaces, or `None`; creating, inviting and excluding are golem.fm gestures. Callers:
the Rec block sheet's space choice and a mode declaring `mode.band` — one switching path.

### No golem.fm, no band

A rack never linked to golem.fm never says "band": `config/.band.json` is created by no script.
Checked by `tests/test_mode_band.py`:

| without roster | behaviour |
|---|---|
| `GET /api/band` | `{band: null, people: [], bands: []}` |
| `takes.resolve_band(<any id>)` | `None` — the rack never invents a tag |
| `take.json.band` | `null`: the take is kept on disk, nothing is lost |
| job `take-tag` from the web | `skipped: band_unknown_on_rack` |
| topbar, Rec block sheet, the mode's "Space" row | nothing shown |

Where a take's destination is set, from the most automatic to the most manual: the **mode**
(`mode.band`) · the **Rec block** sheet (for the evening) · the **session** card (Songs ▸ Recordings)
after the fact. The topbar has no space selector.

The rack **pulls** the roster; golem.fm never pushes it. (With "Let golem.fm find this rack" on,
golem.fm learns that the rack is up and its local addresses — [connect.md](connect.md) — but the
roster is still pulled.)

## 4. Attribution — the person is a property of the input

Each input of the input map (and each bound USB port) carries `person` — a roster id, nullable — set
by **selection** on the rack screen (Modes ▸ Inputs / Soundcard). Consequences:
- a phone shows "my lines": lanes whose input is its person's ([devices-people.md](devices-people.md) §3);
- the patch picker of a lane filters by input role and proposes the input person's patches first
  ([patches.md](patches.md));
- the Riff block's author and lanes ([compo.md](compo.md));
- who plays which input goes out with the heartbeat, guests without their name
  ([devices-people.md](devices-people.md) §8).

## 5. Signed actions — PROPOSED, not built

Some gestures commit a **person**, not the band (publishing a patch revision in their name, accepting
someone into the band). Intended mechanism: the rack posts the request to golem.fm with its token;
golem.fm notifies the person's phone (which holds their personal token); a tap approves; the rack sees
the approval on its next poll. Offline, the request queues; nothing ever blocks playing. None of this
exists: there is no personal token on phones and no approval queue.

## 6. Edge cases

| case | rule |
|---|---|
| **guest musician** (no account) | a local person on the device (`person: "guest:<slug>"`, a first name typed on the rack), time-limited; their name never leaves the rack. Patches they make stay on the rack |
| **leaving the band** | golem.fm removes the person from the roster; their devices are flagged `left_band` and revoked by a tap; **their patches stay** |
| **two musicians, one screen** | no UI session, no "who is logged in": per-input attribution is enough |
| **rack sold / reset** | revoke its token from golem.fm; the rack falls back to local use, everything keeps playing |

### 6 bis. What leaves the rack with a name — the written exceptions

The rule for what the rack sends **on its own** (diagnostic reports, [diagnostics.md](diagnostics.md))
is: **no name leaves** — no person, preset, lane or capture. What leaves with a name leaves because the
user did a gesture whose object is that name:

| what | gesture | where |
|---|---|---|
| a preset name linked to a song | linking a song and a preset | `golemfm.push_song_links` |
| setlists (titles, lines) | pushing a setlist | `golemfm.push_setlist` |
| published patches and presets | catalogue push | `golemfm.push_patches`, `tones_sync` |
| sorted takes (file names, roles, `people`, `by`) | sorting / sending takes, a Riff | `uploader` |
| tones and captures (names), drum-kit cards | library sync | `tones_sync` |
| who plays which input (member handles; guests as `null`) | linking the rack to golem.fm | `rigstatus.inputs_doc` |
| local addresses, `.local` name, Wi-Fi name, current space (opaque id) | "Let golem.fm find this rack" | `connect.push_presence` |

Anything not in this table that carries a name is **a bug**. Add a row here before adding a send.
The device table (`config/auth-devices.json`) is never sent.
