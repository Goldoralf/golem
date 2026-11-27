# Devices, people and the Companion

> **Status: CODED** — paired devices carry a person (or a guest), phones get the Companion (`/app/m.html`) showing that person's lines, a conductor right lets one phone run the songs and drive /live (Control: scenes and stomps), a phone signed in with golem.fm as the band's owner can pair devices and the rack, and a headless rack gets its first screen by pairing code; the per-person monitor mix and signed actions are not built.

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
   only with the conductor right — the song transport, the foot list, and the pedalboard's scenes and
   stomps (Live ▸ Control, decided 2026-11-26: before that, a phone never changed a scene). Nothing a
   pocket can press should be able to cut the band's sound by accident.

## 2. Devices — `bridge/auth.py`

Device table: `config/auth-devices.json` (0600, gitignored; tokens never sent back over the
network). Each device: `{id, name, role, kind, model, mac, ip, created, last_seen, admin, conductor,
person, person_name, expires, screen, via, guest_days}`.

| concept | rule | code |
|---|---|---|
| kinds | `Phone`, `Tablet`, `Computer` (`KINDS`); guessed from the user agent at scan | `kind_from_ua` |
| display | a phone's screen: `phone` (the Companion, default) or `tablet` (the full app, sideways, scaled — §4 ter); chosen on the invitation (`display`) or from the phone (`POST /api/auth/display`), or carried by a golem.fm/connect ticket. A screen choice, never a right: rights follow the kind | `set_display`, `DISPLAYS` |
| roles | `Guitar`, `Bass`, `Voice`, `Keys`, `Drums`, `Pads`, `Keys + Pads` (`ROLES`) — only chooses the view for a device **without** a person (a drummer without pads, a sound engineer) | |
| invitation | `{person | guest, kind, role?}` — one-shot QR, dies after 15 min (`INVITE_TTL`). `person` = a roster id (refused if not in the band); `guest` = a first name typed locally → `person: "guest:<slug>"` | `create_invite`, `claim` |
| guest | device expires after 1, 7 or 30 days (`GUEST_DAYS`, default 1 day), extendable | `guest_ttl`, `extend` |
| set the person later | from the device's row, without rescanning | `POST /api/auth/devices/{did}/person`, `set_person` |
| left the band | a device whose person is no longer in the synced roster is flagged `left_band`; revoked by a tap, never silently (the roster can be incomplete) | `list_devices` |
| stale token | `whoami.token` = `none` \| `ok` \| `unknown` (a presented token the rack no longer knows) → the app opens `app/unpaired.html` ("This device is no longer paired…", "I have a pairing code") instead of a frozen desktop view | `token_state` |
| conductor | a phone may load, start and stop songs, backing and takes, change the foot list and toggle the pedalboard's stomps only with `conductor` (or admin): `CONDUCTOR_PATHS` = `/api/recall` (a scene too), `/api/arrangement`, `/api/perf/start`, `/api/perf/stop`, `/api/backing`, `/api/stomp`, plus `/api/backing/*` (not `meta`) and `/api/setlists/<id>/activate` (`_conductor_path`). Tablets and computers keep their rights. A phone whose person is `owner`/`admin` of the space is conductor by default **at creation** (`_grant_conductor`); a manual choice is never overwritten | `set_conductor`, `POST /api/auth/conductor` |
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

**Top menu: two icons**, Live and System (mockups validated 2026-11-26). The address keeps the
screen: `?tab=live&mode=<mode>`, `?tab=system&page=<page>`; the old `?tab=now|song|mine|…` still lead to
the matching mode (`LEGACY_TAB`; the `golem phone` shell keeps `?tab=<mode>` or `?tab=system`). There is no bottom tab bar.

**Live modes**, picked from a sheet that reads like Settings ▸ Mode (name, what it does, the active
dot, 🔒), remembered by the phone (`localStorage golem.phone.mode`):

| mode | shown when | content |
|---|---|---|
| **Now** | always | title, tempo, key (from the backing catalogue `key`; none without a backing), scene, next song; while the arrangement runs, the count-in, the part now and the next one. Opens **Between songs** when the arrangement is finished or loaded but not started, and **Ready for the show** (Show mode, conductor, nothing played yet) |
| **Control** | always (🔒 without the right) | `app/mobile-control.js`. ① the foot lists: setlists ▤ or banks ⛓, the one on the foot marked; ② a list's lines: a tap loads the line (`/api/recall {slot}`); a line of another list arms first ("tap again: play this list"), then activates the list and loads; while a song plays the rack answers 409 and the second tap confirms ("stop & load"); ▶ Start / ⏭ Next part / ■ Hold to stop (the former Song tab); ③ the play screen: ◀ ▶ (the foot list's playable lines, like `live-bankbar.js`), the title opens the lines, the five stomps SW 6-10 (`/api/stomp {switch}`; service blocks show whether they play, like /live) and a Tuner tile, the scenes at the bottom under the thumb (`/api/recall {scene}`), colours, names and **animations** from the preset (`preset.anims`; the rules are read from `app/style.css` by `app/anim-tiles.mjs`, still tiles when Display ▸ Animations is Off). **Phone turned sideways**: the rack's real /live page, `/app/?desktop=1&embed=live#/live` (no top menu, no Designer/Songs/Library links, no tools, no automatic REC; the setlist chip of the top menu moves into the lines window opened by the title — "⇄ Change setlist or bank" in place of "Open in Designer", `live-bankbar.js`), scaled to the phone (logical height 552 px). Without `rights.control` the same screen, greyed (sideways: a veil takes the taps), says why and offers "Sign in with golem.fm" |
| **Mine** | the person has lanes | my lanes: state of the scene, level, my stomps (tap = toggle); keys lanes show sound, instrument, zone, transposition per scene (`lane_stomps.instruments_by_scene`); opens the **Tuner** sheet |
| **Lyrics** | the person has a voice lane | lyrics of the backing (`/api/backing/meta/<slug>`); `[Chorus]`-style markers follow the current part, else the whole text; size from `prefs.lyrics_size`, "A− text" / "A+ text" for the session. "No lyrics for this song" / "No lyrics: this song has no backing track" |
| **Beat** | the device has no lines | bar and beat, count-in, next part |
| **Rec** | always | REC state and elapsed time, a big "Mark that" flag, last takes |

**System** (`app/mobile-system.js`) is not the rack's Settings: four pages. What needs a right says so
on its row before the tap; the rights come from `whoami.rights` (`auth.rights_of`), never re-derived.

| page | content | right |
|---|---|---|
| **Display** (`page=display`) | Phone display or Tablet display (§4 ter) | paired |
| **This golem** (`page=connect`) | name (`golem_N`), mode, network, IP, `.local` name, the local URLs with Copy (`/api/connect/where`, `/api/system`) | paired |
| **Pair a device** (`page=pair`) | Phone (a person of the roster, or a guest for 1 day) or Tablet → the invitation QR (`POST /api/auth/devices`, `/api/auth/qr`), 15 min, once | owner (§5 bis) |
| **golem.fm** (`page=golem.fm`) | paired or not; "Pair this golem": the device code and "Approve on golem.fm" opened in the same browser (already signed in there), a QR for another device; polls `/api/golemfm/pair/status` | owner; a conductor while the rack is not paired yet |
| **Account** (`page=account`) | signed in or not, what this phone can do, "Sign in with golem.fm" / "Sign out" | paired |

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
  (mostly iOS; Chrome Android needs HTTPS for an installed app, or the flag "Insecure origins treated as
  secure" set to the golem's address). `m.webmanifest` leaves the orientation free (`any`): locked upright,
  an installed Companion would never show Control sideways nor the tablet display.
- **Full screen on Android without installing** (2026-11-26, `app/fullscreen.mjs`): System ▸ Display ▸ Full
  screen, and a ⛶ button next to 📱 in the tablet display, call the Fullscreen API, which works over plain
  http after a tap and hides the address bar and the status bar. A reload leaves full screen (a browser rule):
  the button stays. Not shown where the API is missing (iPhone Safari).
- **Full screen at the first tap** (Settings ▸ System ▸ Display, `display.fullscreen`, **on by default**, one setting for
  every device): a browser never enters full screen without a gesture, so on any phone or tablet (touch screen, not
  the rack's own screen, not inside an iframe, not a browser already covering the screen) a transparent veil takes the
  first tap: it goes to full screen and does **nothing else** (a tap to wake the screen never toggles a stomp). The
  veil also covers the iframes of the tablet display and of Control sideways. It comes back after a reload or an exit
  by the system (back gesture), not after "Leave full screen". `app/fullscreen.mjs`, `bridge/display.py`.

Dev: `golem phone` opens the Companion at 390×844 with a **Who** selector and a 🎼 conductor switch.

### 4 ter. A phone with the tablet display

Some musicians only have a phone and want the full app (2026-11-26). A `Phone` device whose `display` is
`tablet` still lands on `/app/m.html`, which then shows, sideways, the full app (`/app/?desktop=1`) in a
1024×600 frame scaled to fit (about 0.65 on a phone: small, but allowed); upright, "Turn your phone sideways".
The way back is always on screen: the 📱 button in a corner, and "Back to the phone display" upright
(`POST /api/auth/display {display: "phone"}`). From the Companion: System ▸ Display. On an invitation for a
phone, Pair a device asks "Phone display / Tablet display". The rack keeps deciding rights by the kind: a phone
with the tablet display still needs the conductor right to load songs, scenes and stomps, and never gets admin.

### 4 bis. Signed in with golem.fm — the owner's gestures from a phone

A device created or upgraded through a golem.fm/connect ticket was **authenticated by golem.fm**: its
person is not a selection made on the rack screen ([identity.md](identity.md) §1.3). The rack keeps
`fm_auth = {at, person, rights}` on the device (`auth.connect_device`; `rights` from the ticket's
`person.rights`, else the cached roster), valid 30 days (`FM_AUTH_TTL`).

- **Sign in** (System ▸ Account): `POST /api/auth/signin` → the rack remembers this device under the
  phone's IP for 5 minutes (`auth.start_signin`) and returns `<golem.fm>/connect/`; the person opens the
  rack there; golem.fm sends the ticket to the presence's **first URL, the IP** — often another origin
  than the one holding the phone's token (`golem.local`). `POST /api/auth/connect` therefore upgrades
  the device that presented its token, else the one remembered for that IP (`auth.pending_signin`, one
  return only), instead of creating a duplicate; the phone lands on `?tab=system&page=account`.
- **Owner's gestures** (`OWNER_PATHS`: `GET/POST /api/auth/devices`, `GET /api/auth/qr`,
  `POST /api/golemfm/pair`, `GET /api/golemfm/pair/status`): an admin device, or a signed-in device
  whose person is `owner` or `admin` of the band (`auth.owner_ok`). Revoking, promoting, the conductor
  switch stay admin gestures (the rack screen). While the rack is **not paired** with golem.fm, a
  conductor may start the pairing (no existing link to hijack); re-linking a paired rack is an owner's
  gesture. The pairing status follows the same rule as the pairing (audit 2026-11-04, H3).
- **Sign out**: `POST /api/auth/signout` drops `fm_auth`; the phone stays paired (its lines, its
  pedals, its conductor right). Nothing is written to golem.fm.
- Playing never needs golem.fm: offline, a paired phone works as before; only the owner's gestures
  wait for a sign-in, or are made on the rack screen or the tablet.

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
