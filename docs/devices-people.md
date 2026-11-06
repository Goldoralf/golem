# Devices, people and the Companion

> **Status: CODED** — paired devices carry a person (or a guest), phones get the Companion (`/app/m.html`) showing that person's lines, a conductor right lets one phone run the songs, and a headless rack gets its first screen by pairing code; the per-person monitor mix and signed actions are not built.

Related: [identity.md](identity.md) (no login on the rack, the roster, what leaves the rack),
[connect.md](connect.md)
(joining the rack through golem.fm/connect), [band-scenes.md](band-scenes.md) (a phone toggles its
lane's stomps), [patches.md](patches.md), [installer.md](installer.md) (`golem server`: a tablet is
the screen), [golemfm-protocol.md](golemfm-protocol.md).

## 1. Principles

1. **No login on the rack.** Choosing a person from the band list when creating an invitation is a
   *selection*, not an authentication ([identity.md](identity.md)).
2. **The person is a property of the input**; the device carries a person; a phone therefore shows
   the lanes whose input belongs to *its* person, on the card of the *active* mode (IN 1 at home,
   IN 3 at rehearsal: nothing to re-pair).
3. **The device table never leaves the rack.** Only what [identity.md](identity.md) §6 lists goes
   out with a name.
4. **The rack's screen belongs to the band, not to a person.** A tablet used as the rack screen is
   a device without a person, admin, opening the full app.
5. **A phone reads a lot and acts little**, within its musician's scope: its stomps, a flag, and —
   only with the conductor right — the song transport. Nothing a pocket can press should be able to
   cut the band's sound by accident.

## 2. Devices — `bridge/auth.py`

Device table: `config/auth-devices.json` (0600, gitignored; tokens never sent back over the
network). Each device: `{id, name, role, kind, model, mac, ip, created, last_seen, admin, conductor,
person, person_name, expires, screen, via, guest_days}`.

| concept | rule | code |
|---|---|---|
| kinds | `Phone`, `Tablet`, `Computer` (`KINDS`); guessed from the user agent at scan | `kind_from_ua` |
| roles | `Guitar`, `Bass`, `Voice`, `Keys`, `Drums`, `Pads`, `Keys + Pads` (`ROLES`) — only chooses the view for a device **without** a person (a drummer without pads, a sound engineer) | |
| invitation | `{person | guest, kind, role?}` — one-shot QR, dies after 15 min (`INVITE_TTL`). `person` = a roster id (refused if not in the band); `guest` = a first name typed locally → `person: "guest:<slug>"` | `create_invite`, `claim` |
| guest | device expires after 1, 7 or 30 days (`GUEST_DAYS`, default 1 day), extendable | `guest_ttl`, `extend` |
| set the person later | from the device's row, without rescanning | `POST /api/auth/devices/{did}/person`, `set_person` |
| left the band | a device whose person is no longer in the synced roster is flagged `left_band`; revoked by a tap, never silently (the roster can be incomplete) | `list_devices` |
| stale token | `whoami.token` = `none` \| `ok` \| `unknown` (a presented token the rack no longer knows) → the app opens `app/unpaired.html` ("This device is no longer paired…", "I have a pairing code") instead of a frozen desktop view | `token_state` |
| conductor | a phone may load, start and stop songs, backing and takes only with `conductor` (or admin): `CONDUCTOR_PATHS` = `/api/recall`, `/api/arrangement`, `/api/perf/start`, `/api/perf/stop`, `/api/backing`. Tablets and computers keep their rights. A phone whose person is `owner`/`admin` of the space is conductor by default **at creation** (`_grant_conductor`); a manual choice is never overwritten | `set_conductor`, `POST /api/auth/conductor` |
| admin | explicit gesture on the rack | `set_admin`, `POST /api/auth/promote` |

Routes (`bridge/routes_system.py`): `GET/POST /api/auth/devices`, `GET /api/auth/qr`,
`POST /api/auth/claim`, `GET /api/auth/whoami` (open; a device sees only its own record),
`POST /api/auth/promote`, `/conductor`, `/extend`, `/revoke`, `/pair-code`, `GET/POST /api/auth/pair`.

**First screen of a headless rack** (`create_pair_code` / `claim_pair`): a six-digit code, valid
10 minutes (`PAIR_TTL`), single use, dies after 10 failed tries. Created locally (`golem pair`, or
`POST /api/auth/pair-code` from local or an admin); the bridge also publishes one at start while no
admin device exists (log and headless notification). Entered on `app/pair.html`; the device becomes
"Rack screen": Tablet, no person, admin.

## 3. "My lines"

The lanes of the current preset whose input carries the device's person: audio → the active card's
input; MIDI → the USB port (`lane_stomps.lane_person`). `GET /api/lane/mine` and the guard of
`POST /api/lane/stomp` use them; without a person, the device's role. `GET /api/lane/mine` also
carries the person's `prefs` and `rights` from the roster, and `?preset=<id>` shows the lines in
another song (read-only). Details of the stomp rights: [band-scenes.md](band-scenes.md) §4.

## 4. The Companion — `/app/m.html`

A device of kind `Phone` never lands on the full app: at boot (`app/lib.js`) `whoami.device.kind
== "Phone"` redirects to `/app/m.html`. Debug escape: `?desktop=1`. The local screen is never
routed. Same API and WebSocket as the app, a different shell (`app/mobile.js`). Dark, one hand, no
scroll except lyrics, automatic WS reconnection, screen kept awake.

**Tabs** (at most 5, in this order, `Companion` in `app/mobile.js`; the open tab survives a reload
through `?tab=`):

| tab | shown when | content |
|---|---|---|
| **Now** | always | title, tempo, key (from the backing catalogue `key`; none without a backing), scene, next song. Opens **Between songs** when the arrangement is finished or loaded but not started, and **Ready for the show** (Show mode, conductor, nothing played yet) |
| **Song** | always | **conductor**, stopped: the setlist with "Load", "Start", "Record with the song" (rehearsal). Running: part, next part, rail, "Next part" (foot mode) or nothing (bars mode), "■ Hold to stop" (0.6 s). **Musician**: "<who> started the song", part, next, "You in the chorus" (from the preset summary `scenes[].lanes`) |
| **Mine** | the person has lanes | my lanes: state of the scene, level, my stomps (tap = toggle); keys lanes show sound, instrument, zone, transposition per scene (`lane_stomps.instruments_by_scene`); opens the **Tuner** sheet |
| **Lyrics** | the person has a voice lane | lyrics of the backing (`/api/backing/meta/<slug>`); `[Chorus]`-style markers follow the current part, else the whole text; size from `prefs.lyrics_size`, "A− text" / "A+ text" for the session. "No lyrics for this song" / "No lyrics: this song has no backing track" |
| **Beat** | the device has no lines | bar and beat, count-in, next part |
| **Rec** | always | REC state and elapsed time, a big "Mark that" flag, last takes |

- **Between songs** computes what to prepare: tuning and capo against the previous line, instruments
  to put down or pick up (my lines now vs in the next song, `GET /api/lane/mine?preset=`), "You
  sing", the line note, the first part and count-in.
- **Tuner**: the rack tuner is global (it does not mute but covers /live): never armed automatically
  during a song, and switched off only by the phone that switched it on.
- **Flags**: during a take, each tap adds `{at, sec, by}` with the person, song and part
  (`POST /api/take/flag`, 409 when nothing records); they go into `take.json` `flags[]`;
  `GET /api/take/flags`.
- **Conductor rules**: loading while a song plays asks for confirmation (`/api/recall` 409
  `confirm`); "Start" is greyed (and refused 409) while the rig loads (`rig_loading`) or when the
  mode forbids the arrangement, and says why. The foot stays alive: the last gesture wins and every
  phone shows who started or stopped (`loaded_by`, arrangement `by`). In Show mode, REC starts with
  the first song unless someone started it before ("Ready for the show"). "Next part" from a phone
  goes over Wi-Fi (up to ~100 ms); the count-in comes from the rack clock.
- **Online devices** are broadcast on the WebSocket (`devices_online`).
- Wake lock: `navigator.wakeLock` does not exist over plain http on the LAN, so `lib.keepAwake`
  falls back to a muted looping video (`app/media/keepawake.*`). Web app manifests
  `app/manifest.webmanifest` and `app/m.webmanifest` give full screen from "Add to home screen"
  (mostly iOS; Chrome Android needs HTTPS for an installed app).

Dev: `golem phone` opens the Companion at 390×844 with a **Who** selector and a 🎼 conductor switch.

## 5. Two screens do not edit the same draft silently

Each open Designer has an editor id (`EDITOR`). The draft revision and its last editor live **inside**
`presets/.sandbox.json` (`bridge/sandbox_edit.py`), so a bridge reload resets nothing. An audition or
save from an outdated revision **and** another editor is refused (`sandbox_apply` → 409 `conflict`).
The refused Designer shows "This draft was changed on another screen" with "Load the newer draft"
and "Keep mine" (rewrites knowingly) and neither auditions nor saves until a choice is made. Forced
writes: opening a preset, dropping a patch, "Keep mine". Other writers (tags, a scene created from the
setlist, lane apply) are not editors and are not blocked. A client without an editor id (an old app
build) is not protected.

## 6. Settings ▸ Connect ▸ Devices — by band

`app/page-devices.js`:
- Chips at the top: one per space the rack knows, plus "Guests & screens". Choosing a chip does
  **not** change the rack's current space (that is the mode and the Rec block, [identity.md](identity.md)).
- The chosen space shows one card per person: rights, instruments, inputs played on this rack, devices
  (conductor, admin, delete); adding a device starts from the card. Inputs of the active card without
  a person are listed ("⚠ No one on …", "Set who ›"): an input with no one shows on no phone.
- "Guests & screens": guests (with time left, extendable 1 / 7 / 30 days), screens, system tools
  (pairing code, Wi-Fi QR of the rack's access point, revoke all) and unassigned devices.
- Invite sheet: the QR of the band page on golem.fm (`GET /api/band/invite[/qr]`) — the rack never
  creates golem.fm invitations. Sync sheet: what comes down, what goes up, what never leaves
  (`GET /api/connect`).
- Without a roster (rack never linked), there is no band: every device is a guest (Guests & screens), with a pass of a day, a week or a month (`app/page-devices.js`).

## 7. From golem.fm: rights and personal settings

The roster (`GET /api/ext/band`, [identity.md](identity.md) §3) carries per person and **per space**
`rights` = `owner` \| `admin` \| `member`, and `prefs` — always present (`{}` if empty), flat,
snake_case, string / number / boolean values, at most 20 keys and 200 chars per string; unknown keys
are ignored on both sides; prefs belong to the person and are the same in every space
(`roster.prefs`). Keys used today:

| key | values | use on the rack |
|---|---|---|
| `lyrics_size` | `s` · `m` · `l` · `xl` | Companion Lyrics text size |
| `tuner_ref_hz` | 415–466 | not used (the tuner JSFX has A4 = 440 hard-coded) |
| `left_handed` | boolean | not used |

Read-only: the rack never writes into a person's account.

## 8. Who plays which input — sent with the heartbeat

`rigstatus.inputs_doc()` sends, inside `PUT /api/ext/rig/status` under `inputs`, the **active** card
only (on every input-map save and every 5-minute heartbeat):

```json
{"card": "hw:V276", "mode": "studio", "entries": [
  {"slot": "IN 1", "kind": "audio", "role": "guitar", "name": "Guitar 1", "person": "<handle>"},
  {"slot": "USB 1", "kind": "midi", "role": "keys-pads", "name": "Keys + Pads 1", "device": "MPK Mini Mk II", "person": null}]}
```

`person` = the global handle or `null`; a **guest** goes out as `{"person": null, "guest": true}` —
a name typed on the rack never leaves. Bounds: 64 entries; `slot`, `role` ≤ 32, `name`, `device` ≤ 64,
`card`, `mode` ≤ 120 chars; `kind` ∈ {audio, midi}. golem.fm re-checks the handle against its
spaces. See [golemfm-protocol.md](golemfm-protocol.md) §2.

## 9. Not built

- A per-musician monitor mix ("more me") — needs a mixer with one headphone mix per musician.
- Scene control from a phone: the pedalboard switches the band's chord.
- Writing personal settings back to golem.fm.
- An approval flow for signed actions ([identity.md](identity.md) §5).
- Auto-scrolling lyrics, cue countdowns, line-check, replay of the last take on the phone.
