# Security

> **Status: CODED** — the bridge's trust model and access control, as implemented in
> [`bridge/auth.py`](bridge/auth.py) and applied by the HTTP middleware `_auth_guard` and the `/ws`
> handler in [`bridge/app.py`](bridge/app.py).

golem is a stage rack that runs on a band's local network. The bridge (FastAPI, port `8770`) is
started with `--host 0.0.0.0` (`provision/start.sh`, `provision/serve-rig.sh`), so every device on
the LAN or on the rack's own access point can reach it. Access control is therefore enforced in one
place: **every request goes through `auth.allowed_http()` (HTTP) or `auth.allowed_ws()`
(WebSocket)**. No route is decorated one by one, so a new route is protected by default according to
its method and path.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub:
the repository's **Security** tab ▸ **Report a vulnerability** (private vulnerability reporting).
Only the maintainers see the report.

Include the version (`GET /api/system`, or the git commit), the platform (Linux, Windows,
macOS), the request or steps that reproduce the issue, and what an attacker gains. We will
acknowledge the report, agree on a disclosure date with you, and credit you unless you prefer not.

## 1. Trust model

| Who | How the bridge recognises it | Rights |
|---|---|---|
| **The local screen** | The TCP peer is `127.0.0.1`, `::1` or `localhost` (`auth._is_local`). This covers the rack's own window (`golem desktop`), local tools (`tools/check-*`) and provisioning scripts. | **Admin.** Whoever touches the rack's screen controls the rig. |
| **A paired device** | It presents a **device token** (see §2). | Depends on its tier (§3). |
| **Anyone else on the LAN** | No token, or an unknown, revoked or expired one. | Nothing of the API except `PUBLIC_GET` (`/api/auth/whoami`, `/api/health`, `/api/app-build`, `/api/effects`, `/api/t3k/auth/callback`) and the pairing exchanges. The static app (`/app/`) and `/library/` stay readable. Everything else is refused with **403**. |

golem.fm, the optional cloud service, is **not** a client of the bridge: every rack ↔ cloud flow is
outgoing (the rack pulls jobs and pushes status). The bridge exposes no route for the cloud. See
[`docs/golemfm-protocol.md`](docs/golemfm-protocol.md).

Because the rack sends its golem.fm token to that server and runs the jobs it hands out, the server
must be `https://` — plain `http://` only to this machine, a `*.local` name, loopback or a private IP
(a dev server such as `http://localhost:5173`). The rule (`routes_content.server_url_ok`) is checked
when the address is saved (`POST /api/integrations`) **and** wherever it is read (`golemfm._cfg`), so
the `GOLEMFM_URL` environment variable or a hand-edited `config/integrations.json` cannot bypass it:
a refused server counts as "not configured", nothing (token included) is sent to it, the refusal is
logged once and `GET` of the golem.fm status reports it in `error`.

## 2. Device tokens

- **One token per device**, `secrets.token_urlsafe(32)`, stored in `config/auth-devices.json`
  (written with mode `0600`, not versioned) together with its record: `id`, `name`, `kind`
  (`Phone` / `Tablet` / `Computer`), `role`, `person`, `admin`, `conductor`, `expires`, `model`,
  `mac`, `ip`, `created`, `last_seen`. Tokens are compared with `secrets.compare_digest` and are
  **never** sent back over the network: `GET /api/auth/devices` (`list_devices`) omits them.
- **Where the token travels.**
  - **HTTP:** header `X-Golem-Token` or cookie `golem_token` only (`auth._presented`). A `?token=`
    query parameter is **not** accepted on HTTP, because a URL ends up in browser history, proxy
    logs and copied links.
  - **WebSocket `/ws`:** query `?token=`, cookie `golem_token` or header `X-Golem-Token`
    (`allowed_ws`). The query is allowed here only because a browser cannot set a header on a
    WebSocket.
  - The app stores the token in `localStorage` and in a `golem_token` cookie (`path=/`,
    `SameSite=Lax`, one year) — `app/lib.js`.
- **How a device gets a token.** Four exchanges are open without a token
  (`auth.OPEN_EXCHANGES`); in each one the presented secret *is* the authentication, and each is
  still subject to the Host and Origin checks:

  | Route | Secret | Result |
  |---|---|---|
  | `POST /api/auth/claim` | A one-time **invitation** token, encoded in the QR code that **Network ▸ Devices** shows (`GET /api/auth/qr`, URL `http://<rack>:8770/app/?auth=<invite>`). An invitation expires after 15 min (`INVITE_TTL`). | A **fresh** device token; the invitation is consumed, so a photographed QR code is useless after the scan (`auth.claim`). |
  | `POST /api/auth/pair` | A six-digit **pairing code**, valid 10 min, single use, dropped after 10 wrong attempts (`PAIR_TTL`, `PAIR_TRIES`). Created by `golem pair` or `POST /api/auth/pair-code`, and published in the log at startup when the rack runs as `golem server` and no admin device exists. | An admin device named "Rack screen" (`auth.claim_pair`). This is how a rack without a screen gets its first tablet. |
  | `POST /api/auth/connect` | A ticket issued by golem.fm (see [`docs/connect.md`](docs/connect.md)). | The person's device, created or found again by its `client` id (`auth.connect_device`). |
  | `POST /api/auth/handoff/claim` | A one-time code (60 s, in memory) created by an already-paired device with `POST /api/auth/handoff`. | The **same** device token, set under another origin (for example `http://<rack>.local:8770`) — `auth.claim_handoff`. |

- **Revocation.** `DELETE /api/auth/devices/{id}` revokes one device (or cancels one invitation).
  `POST /api/auth/revoke` revokes every device and invitation; the local screen is not affected.
  A revoked or expired token makes `GET /api/auth/whoami` answer `"token": "unknown"`, and the app
  says the device is no longer paired.
- **Expiry.** A member's device never expires. A guest's device expires after 1, 7 or 30 days
  (`GUEST_DAYS`, default 1 day); `POST /api/auth/extend` extends it.

## 3. Tiers

| Tier | What makes it | Extra rights |
|---|---|---|
| **admin** | The local screen, or a device with `admin: true` (set by `POST /api/auth/promote`, or created by the pairing code or a golem.fm "screen" connect). A fresh rack has **no** admin device: system gestures are then only possible in front of the rack. | Everything, including the admin paths below. |
| **conductor** | A device of kind `Phone` with `conductor: true`. Set by `POST /api/auth/conductor`, or granted once at creation when the person is `owner` or `admin` of the band (`auth._grant_conductor`; never overwritten afterwards). | A phone may load, start or stop a song or a take only if it is conductor or admin. |
| **member** | Any other paired device attached to a person of the band, or to a role only. | All non-admin writes and sensitive reads. A **phone** member cannot use the conductor paths. Tablets and computers are not restricted by the conductor rule. |
| **guest** | A device with an `expires` date, or whose `person` starts with `guest:` (`auth.is_guest`). | Same as member, except that **any `DELETE` is refused** unless the device is also admin (a one-night guest does not delete the band's takes). |

## 4. The decision, in order (`auth.allowed_http`)

1. **Host allow-list** (`auth.host_ok`). The `Host` header must be an IP address, `localhost`, the
   machine's hostname (full or short), one of the `.local` names this rack announces (`golem.local`,
   `golem-<machine>.local`, `<machine>.local` — any other `.local` name could be answered by any device
   on the LAN over mDNS), a name ending in `.localhost`, or a name listed
   in the environment variable **`GOLEM_ALLOWED_HOSTS`** (comma-separated). A missing `Host` is
   accepted (not a browser). Any other name is refused: this blocks **DNS rebinding**, where a web
   page makes its own domain resolve to `127.0.0.1` and would otherwise be treated as the local
   screen. Set `GOLEM_ALLOWED_HOSTS` if you serve the rack under your own DNS name.
2. **Open exchanges** (`OPEN_EXCHANGES`): allowed if the Origin check passes.
3. **Unguarded requests.** A request is *guarded* if its method is `POST`, `PUT`, `DELETE` or
   `PATCH`, or if it is a sensitive `GET` (below). An unguarded `GET` or `HEAD` under `/api/` from a
   remote client passes only with a valid device token, unless it is in `PUBLIC_GET` (what a device
   needs before pairing: learn that it must pair, load the app, the launcher's pulse, the TONE3000
   sign-in landing). Unguarded requests outside `/api/` (the static app, `/library/`) and `OPTIONS` pass.
4. **Local client:** allowed if the Origin check passes. Even locally, a foreign `Origin` is
   refused.
5. **Origin check** (`auth._origin_ok`). No `Origin` header (curl, scripts) is fine. If present,
   its host must equal the request's host, or be local. This stops a third-party page on the LAN
   from replaying the device cookie (CSRF).
6. **Device token required.** No valid, unexpired token → refused.
7. **Admin paths** → admin only. **Admin writes** (non-`GET`) → admin only.
8. **Guest `DELETE`** → refused unless admin.
9. **Conductor paths** for a `Phone` → conductor or admin only.
10. Otherwise allowed.

The WebSocket `/ws` (`auth.allowed_ws`) applies steps 1 and 5 to **every** client, local ones
included — a browser does not hold a WebSocket to the same-origin policy, so without it a web page
opened on the rack's machine could read the state over `ws://localhost:8770/ws`. Then a local client
is allowed, and a remote one needs a valid token. The app, the Companion and the rack's window are
served by the bridge itself, so their socket is same-origin and passes.

A refused HTTP request gets **403** with `{"error": "unauthorized — …"}`. A refused WebSocket is
closed with code **4403**.

### Path lists and the matching rule

There are two kinds of lists in `bridge/auth.py`:

- **Exact lists** — the path must be **equal** to an entry: `SENSITIVE_GET`, `ADMIN_PATHS`,
  `ADMIN_WRITES`, `OPEN_EXCHANGES`, and the exact part of `CONDUCTOR_PATHS`.
- **Prefix lists** (`*_PREFIX`) — the path must **start with** an entry, using plain
  `str.startswith`. There is no segment boundary: `/api/loop` covers `/api/loops`,
  `/api/loop/{fn}` and `/api/loop-peaks/{fn}`; `/api/preset` covers `/api/presets` and
  `/api/preset/{id}`; `/api/backup` covers `/api/backups`. This is deliberate (many routes carry a
  file name or id), but it means a **new route whose path begins with an existing prefix inherits
  that protection** — check the lists when you name a route.

| List | Kind | Entries (summary — read the file for the full list) | Effect |
|---|---|---|---|
| `SENSITIVE_GET` | exact | `/api/network/qr` (Wi-Fi passphrase), `/api/auth/qr`, `/api/auth/devices`, `/api/backups`, `/api/system/autostart`, `/api/system/harden`, `/api/integrations`, `/api/system/update`, `/api/system/reaper-update` (so the admin tier applies to reading them) | `GET` treated like a write: needs local or a token. |
| `SENSITIVE_GET_PREFIX` | prefix | Band data and rack state: `/api/state`, `/api/sandbox`, `/api/preset`, `/api/patch`, `/api/setlist`, `/api/mode`, `/api/inputmap`, `/api/song`, `/api/roster`, `/api/band`; recordings and assets: `/api/loop`, `/api/take/`, `/api/peaks`, `/api/sample`, `/api/backing/asset/`, `/api/backup/`; `/api/diag`, `/api/separation`, `/api/golemfm/pair`; the rack's file system: `/api/kits/import`, `/api/song-folders`, `/api/inbox`, `/api/storage` | Same. |
| `ADMIN_PATHS` | exact | `/api/auth/qr` (an invitation's QR is its token); network and pairing management (`/api/connect/settings`, `/api/auth/revoke`, `/promote`, `/conductor`, `/extend`, `/pair-code`); engine and system (`/api/system/update`, `/reaper-update`, `/reaper-restart`, `/reaper-switch`, `/reaper-license`, `/bridge-restart`, `/api/audio-buffer`, `/api/ui/quit`); this computer (`/api/ui/show`, `/api/system/autostart`, `/api/system/harden` — docs/installer.md §4); pedalboard flashing (`/api/fcb/flash`, `/api/pedalboard/load`, `/hold`, `/flashed`, `/select`, `/learn/save`); `/api/integrations` (golem.fm server and keys written to `.env`); `/api/karaoke/cmd`; the development probes of `routes_dev` (`/api/rig_recall`, `/api/loadtest`, `/api/chunkdump`, `/api/namtest`, `/api/projreload`, `/api/fxprobe`, `/api/fxdump`, `/api/gapmeter`, `/api/lcbench`) | Admin only for every **guarded** request. A `GET` is guarded only if it is also in a sensitive list: the read routes above are listed in `SENSITIVE_GET` for that reason. |
| `ADMIN_PREFIX` | prefix | `/api/network/`, `/api/auth/devices`, `/api/backup`, `/api/cards/`, `/api/separation`, `/api/import` (restoring a backup rewrites presets, library and settings), `/api/diag` (a report holds the bridge log), `/api/golemfm/pair`, and browsing the rack's folders (`/api/kits/import/browse`, `/scan`, `/read`, `/volumes`, `/api/song-folders/browse`) | Admin only for every **guarded** request (writes, and the sensitive `GET`s among them). |
| `ADMIN_WRITES` | exact | `/api/mode/update`, `/api/mode/new`, `/api/mode/reset`, `/api/recorder`, `/api/inputmap`, `/api/inputmap/pair`, `/api/tones-jobs/run` | Admin only for non-`GET`; reading stays allowed to members. |
| `ADMIN_WRITE_PREFIX` | prefix | `/api/devices/` | Same. |
| `CONDUCTOR_PATHS` | exact, plus prefix `/api/backing/` | `/api/recall`, `/api/arrangement`, `/api/perf/start`, `/api/perf/stop`, `/api/backing` and `/api/backing/*` — except `/api/backing/meta` and `/api/backing/meta/*` | Phones: conductor or admin only. |

Note that `ADMIN_PATHS` and `ADMIN_PREFIX` entries only bite on guarded requests: a plain
`GET /api/network/status` from a paired member is answered, because it is neither a write nor a
sensitive `GET` (an unpaired device gets 403, step 3). **An admin route that must also be admin to read goes in a sensitive list too.**

Other rules outside the lists: `POST /api/system/harden` (it carries the user's password) and
`POST /api/system/save-local` are refused unless the client is the rack's own screen; catalog files
resolve only under `assets/` (`config.ASSET_ROOTS`), and a backup import drops a catalog entry whose
files point elsewhere (`importer._tone_files_ok`); the bridge strips `token=` from uvicorn's log lines
and the diagnostic scrubber erases device tokens; every response carries `X-Frame-Options: SAMEORIGIN`,
`X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`.

### Static files

`/library/*` is served to everyone, except hidden segments (any path segment starting with `.`,
for example `/library/.import/`), which answer **404** (`_auth_guard` in `bridge/app.py`). `/app/*`
is public static code.

## 5. What is NOT covered

- **Transport encryption.** The bridge speaks **plain HTTP and WS** on the LAN. A token can be
  sniffed on an open or hostile network. The rack's own access point uses WPA2 (see
  [`docs/network.md`](docs/network.md)); do not expose port `8770` to the Internet or to an
  untrusted network.
- **Paired readers of non-sensitive `GET` routes.** Any paired device, guests included, reads every
  `GET` that is not in a sensitive or admin list. A new route that returns secrets, or something a
  guest should not see, goes in those lists; an unpaired device reads nothing new by default.
- **Local processes.** Anything running on the rack's machine connects from `127.0.0.1` and is
  admin. The machine itself must be trusted.
- **Identity is a selection, not a login.** The person attached to a device is chosen on the rack
  screen or vouched for by golem.fm; the rack does not authenticate people. See
  [`docs/identity.md`](docs/identity.md) and [`docs/devices-people.md`](docs/devices-people.md).

## 6. Checking it

From another device on the LAN (or from the rack with `curl http://<lan-ip>:8770/...`, which is not
a local peer):

- `POST /api/system/bridge-restart`, `POST /api/pedalboard/load` or `POST /api/network/forget`
  without a token → **403**; with a member token → **403** (admin paths); with an admin token → OK.
- `GET /api/network/qr` or `GET /api/state` without a token → **403**.
- `/ws` without a token → closed with **4403**; on the rack, `/ws` with `Origin: http://evil.example`
  → closed with **4403** too.
- Any request with `Host: evil.example` → **403**.
