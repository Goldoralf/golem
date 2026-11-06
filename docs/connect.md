# Joining the rack without typing an address — golem.fm/connect

> **Status: CODED** (rack side; the access-point DNS name is not yet checked on a rack, and phone
> behaviour is not measured, §8) — how a phone or tablet reaches the rack through golem.fm or by the rack's
> local name, how the rack announces itself, and its life-long serial (`bridge/connect.py`,
> `bridge/routes_connect.py`, `bridge/serial.py`, `app/connect.html`).

Related: [`devices-people.md`](devices-people.md) (a device carries a person), [`identity.md`](identity.md)
(no login on the rack), [`network.md`](network.md) (the stage access point),
[`golemfm-protocol.md`](golemfm-protocol.md) (every call listed here).

## 1. The problem

A phone joins the rack by the QR code in Settings ▸ Connect ▸ Devices: the rack's IP and a 15-minute
invitation. A browser stores data **per origin** (`http://192.168.0.22:8770` ≠ `http://10.42.0.1:8770`),
so when the IP changes — another router, a DHCP lease, the stage access point — the phone is no longer
paired. Nobody types an IP on a gig night.

The invitation QR uses the address of the **default route** (`connect.lan_ip` → `addresses()`), never a
virtual bridge (`_VIRTUAL`: docker, libvirt, VPN… are skipped); the access point address comes last.

## 2. Device types

golem.fm/connect detects the device (touch screen + smallest CSS dimension under 600 px = phone,
otherwise tablet; no touch = computer) and lets the person correct it. The ticket carries the type, and
the rack creates the device with it (`auth.connect_device`):

| `kind` | Opens | Rights ([`devices-people.md`](devices-people.md)) |
|---|---|---|
| `Phone` | the Companion (`/app/m.html`) | read; load/start only if conductor |
| `Tablet` | the full app (`/app/`) | those of a screen |
| `Computer` | the full app | same |

**"Use as the rack screen"** is offered only to the **rack's owner**, for a tablet: the device becomes
"Rack screen", with no person and admin rights — like the pairing code. A band member never gets admin
this way.

## 3. Online path (home, rehearsal room)

```
rack ──PUT presence (every 5 min + on address change)──▶ golem.fm
phone ──opens golem.fm/connect (signed in)──▶ golem.fm: racks this person can join · same network? · device type
phone ──"Open": ticket──▶ golem.fm ──▶ redirect http://<ip>:8770/app/connect.html#t=<ticket>
rack page ──POST /api/auth/connect {ticket}──▶ bridge ──POST redeem (rack token)──▶ golem.fm
bridge: creates or finds the device (person + kind) ──▶ token
rack page: does <host>.local answer? ──yes──▶ hand the token over to that origin (60 s code)
                                       ──no───▶ stay on the IP
──▶ Companion (Phone) or full app (Tablet, Computer)
```

- **Same network.** A public page cannot probe a local address (the browser blocks it), but a full-page
  navigation to `http://<lan-ip>:8770` is allowed. golem.fm therefore compares **public addresses** (the
  rack's public IPv4 vs the phone's, or the phone's IPv6 inside a prefix the rack announced) and offers
  "Try anyway" when they differ.
- **The ticket** is random, valid 60 seconds, **single use**, bound to ONE rack. It travels in the URL
  **fragment** (`#t=`), never sent to a server nor logged; the page removes it from history first. The
  rack **redeems** it online with its own token: no shared secret, and single use is enforced by the
  server.
- **The same phone does not create a new device each time.** golem.fm/connect keeps a random identifier
  in its own storage; golem.fm passes it to the rack hashed with the rack id (`client`), opaque and
  different per rack. The rack re-hashes it for disk (`connect.client_key`). A device already known by
  this `client` gets its record and **its token** back; the token stored under the IP and the one under
  the name both stay valid.
- **The person** comes from golem.fm. If they are not yet in the rack's roster, the rack re-syncs the
  roster first (`roster.sync`), then accepts them: golem.fm vouched for the membership.

## 4. Offline path (stage)

1. **One name for the rack everywhere**: `http://<host>.local:8770` (`connect.mdns_host`, announced only
   if avahi is active; on macOS, Bonjour's `LocalHostName`). At home it is mDNS. On the access point it is
   mDNS **plus** the rack's own DNS: `provision/net.sh` (`ap-up`) writes
   `/etc/NetworkManager/dnsmasq-shared.d/golem-name.conf` serving `<host>.local` and `golem.local` →
   `10.42.0.1`, for phones that do not query mDNS. One origin everywhere ⇒ **a phone connected at
   rehearsal is still connected on stage**: its token is stored under that name, not under an IP.
2. **golem.fm/connect works offline.** The page is cached on the phone with the racks already joined;
   without internet it opens the rack's name directly. On stage: join the rack's Wi-Fi, tap the icon.
3. **First night with no prior rehearsal**: the rack shows the Wi-Fi QR, then the invitation QR, which
   carries the rack's name when the access point is up. Two scans, no typing.

The rack cannot answer as `golem.fm` on its access point: golem.fm is HTTPS-only and the phone would
refuse a page claiming that domain without its certificate.

| Situation | Gesture | Result |
|---|---|---|
| Phone already joined once, `.local` name reachable that day | rack Wi-Fi, golem.fm/connect icon | cached page → `http://<host>.local:8770/app/connect.html` → token already there → app |
| Phone already joined, but only by IP | same | the page offers the known name and IP; no token under the name → rack QR |
| Never joined | rack screen ▸ Settings ▸ Connect ▸ Devices: Wi-Fi QR, then invitation QR | invitation under the rack's name when the access point is up |

## 5. Rack ↔ golem.fm contract

### 5.1 `PUT /api/ext/golem/connect/presence` — the rack announces itself (rack token)

Sent 15 s after start (`FIRST_PUSH`), every 5 minutes (`PRESENCE_EVERY`), and within 30 s of an address
change (`ADDR_POLL`). Only when "Let golem.fm find this rack" is ticked (§6). Body
(`connect.presence_payload`):

```json
{
  "session": "k3J9…",
  "rack_id": "9f2c…",
  "name": "GoleM",
  "host": "golem-rack.local",
  "port": 8770,
  "urls": ["http://192.168.0.22:8770", "http://golem-rack.local:8770"],
  "ipv6_prefixes": ["2a01:db8:9aa:1080::/64"],
  "wifi": {"ssid": "Studio", "ap": false, "ap_ssid": "golem"},
  "band": "b_…",
  "at": "…Z"
}
```

- `session` changes at each bridge start. `rack_id` is **stable** (`connect.rack_id`: a salted SHA-256 of
  `/etc/machine-id`, else a random id kept in `config/.rack-id`), never shown — `GET /api/connect/where`
  strips it.
- `host` is `null` if no mDNS name is announced. `urls` are in preference order: at most 5 IPs (default
  route first, access point last), then the name, 6 entries max. `ipv6_prefixes`: at most 8 public /64.
- `band`: the rack's current space id (`roster`), `null` without a roster or with a temporary local one.
- golem.fm validates it (only `http://` URLs to private, CGNAT, ULA or link-local addresses or `*.local`
  names; the first URL is an IP; limits above), or answers 422. A rack is **online** while its last
  presence is under 12 minutes old.
- `DELETE` on the same route when the box is unticked (`connect.withdraw`). **Not** on bridge stop: every
  `reload.sh` would make the rack vanish; a presence that is not renewed expires by itself.
- A refusal (404 when the server does not serve the route yet, network down) is retried at the next
  regular tick, not every 30 s; a new address is sent at once.

### 5.2 `POST /api/ext/golem/connect/redeem` — the rack redeems a ticket (rack token)

Request `{"ticket": "…"}`.

| Code | Body | Meaning |
|---|---|---|
| 200 | `{"person": {"id": "<handle>", "name": "…", "roles": ["guitar","voice"]}, "band": "b_…", "kind": "Phone", "screen": false, "client": "<sha256>"}` | valid ticket, consumed |
| 404 | `{"detail": "unknown ticket"}` | unknown, or issued for another rack |
| 410 | `{"detail": "ticket expired"}` / `"ticket already used"` | too late or replayed |

`person.id` is the global handle (the same as in `GET /api/ext/band`). `kind` is exactly `Phone`, `Tablet`
or `Computer`. `screen: true` only for the owner's "Use as the rack screen"; `person` is then `null`.

The rack turns every outcome into an English message for the phone (`connect.redeem`): not paired → 409
"scan the QR on the rack"; golem.fm unreachable → 502; 404/410 → 410 "This link has expired or was
already used"; a 200 without a person and without `screen` → 502.

The ticket URL golem.fm redirects to is the presence's first IP URL + `/app/connect.html#t=<ticket>`.

### 5.3 Rack routes

| Route | Open to | Role |
|---|---|---|
| `POST /api/auth/connect {ticket}` | anyone (Origin checked) | redeems the ticket, creates or finds the device → `{token, name, kind, screen, open, local_url}` |
| `POST /api/auth/handoff` | a device (token) | single-use code, 60 s, in memory, to set the same token under another origin |
| `POST /api/auth/handoff/claim {code}` | anyone (Origin checked) | → `{token, open}`; 410 when expired |
| `GET /api/connect/where` | local or device | what the presence announces (without `rack_id`, `session`), plus `enabled` and the last push status |
| `GET /api/connect` · `POST /api/connect/settings {presence}` | local or admin | the box of §6 |

`app/connect.html` is **self-contained** (no `lib.js`, like `pair.html`): fragment `#t=` → redeem;
`#h=` → handoff; neither → token already there? open the app; otherwise "Open golem.fm/connect, or scan
the QR on the rack". Settings ▸ Connect ▸ Devices shows "via golem.fm" on devices created this way.

## 6. Privacy — what leaves the rack

The presence tells golem.fm that the rack is on, and its **local** addresses: not a person's name, but
information about a place. Hence:

- a box **"Let golem.fm find this rack"** in Settings ▸ Connect ▸ golem.fm (`integrations.json` →
  `golemfm.connect_presence`; absent = ticked on a paired rack, since pairing is the gesture that motivates
  it), written at once like a consent;
- unticked: no presence is sent, the last one is withdrawn (`DELETE`), golem.fm/connect shows the rack
  offline and points to the QR.

**Never sent**: paired devices, their people, MAC addresses, the access point's DHCP leases, the Wi-Fi
password.

With pairing and the heartbeat, the rack also sends its **machine record** (`serial.machine`, a typed
allow-list): `arch`, `cpu`, `cores`, `ram_mb`, `disk_gb`, `hostname`, `board`. It describes the machine,
not a person; the hostname is the one the installer gave the box.

## 7. The life-long serial — `golem_1`, `golem_2`…

The public name of a machine. golem.fm assigns it to **(user, machine)** — the machine being `rack_id`,
never the token: revoking or re-pairing the same machine returns the **same** number. No route changes it.

| Where | What the rack does |
|---|---|
| `POST /api/ext/pair/start` | `rack{}` also carries `rack_id` and the machine record (`rigstatus.rack_identity`, `serial.machine`) |
| `POST /api/ext/pair/poll` → `approved` | `"serial": {number, name, issued_at, machine}` or `null` → `serial.record` |
| `PUT /api/ext/rig/status` (heartbeat) | carries `rack_id` + `machine` on every tick; the answer's `serial` → `serial.record`, so a rack paired before serials existed gets its number at the next heartbeat |
| `GET /api/ext/serial` | re-read (lost file): `POST /api/system/serial/recover` → `serial.fetch`; 404 while none is assigned |
| `GET /api/system` | `serial` = `serial.plate()`: the plate in the Settings ▸ System tab row |

`serial.record` rules:

- **Written once, never rewritten.** `config/serial.json` (mode 0444, local state) receives
  `{number, name, issued_at, recorded_at, server}` the first time. A `null` does not erase it.
- **Conflict.** A **different** number for the same machine is not applied: it is kept in
  `config/serial.conflict.json`, logged as an error, and the plate shows `⚠ <name>` with the explanation —
  an anomaly to report, not to settle on the rack. Mode 0444 is a signal, not a lock (the bridge runs
  without root).
- **Only production writes.** A number is written to `serial.json` only if it comes from a production
  origin (`serial.is_prod`: `https://` and a host in `serial.PROD_HOSTS`). A development or staging server
  counts from 1 like production, so its numbers would look real. Any other server gives a **provisional**
  number: kept in `config/serial.provisional.json` (0644) with its `server`, rewritten on change, never a
  conflict, ignored once a production number exists, shown greyed and dashed with "· TEST" (the tooltip
  names the server), and deleted when production writes the real one.

Tests: `tests/test_serial.py`.

## 8. Several golem.fm servers, one token each

A development rack can switch servers from Settings ▸ Connect ▸ golem.fm **without re-pairing**.
`config/integrations.json` keeps `golemfm.servers = {url: {label, token}}`; `golemfm.base_url` / `token`
remain the active pair (the whole bridge reads `golemfm._cfg`). Switching stores the token of the server
left and restores the one of the server chosen — a token is **never** presented to another server.
Pairing stores its token under the current server. What depends on the server is already keyed by it:
pushed packs, published presets (`.published.json`), the loans registry (whose guards check every
server, [`library-loans.md`](library-loans.md)); the serial is only written by production (§7). Tests:
`tests/test_servers_switch.py`.

## 9. Not verified, not decided

**To measure on real phones and on the rack** (nothing here can be checked from a desktop):

- Do Chrome Android and Safari iOS follow the redirect from https golem.fm to a local http IP?
- Does `http://<host>.local:8770` open on Android and iOS at home?
- On the rack's Wi-Fi **without internet**, with mobile data on, does the phone keep the Wi-Fi and reach
  `10.42.0.1` and the name? (Android sometimes moves everything to mobile data.) If not, the rack could
  answer the phones' connectivity probes (`/generate_204`, `/hotspot-detect.html`) as an online network —
  not done by default, since it also cuts messaging apps over mobile data during the show.
- Does the cached golem.fm/connect icon reopen offline?
- The access-point DNS name (`net.sh`) after re-running `provision/setup-net-sudo.sh` on a rack.

**Open decisions**:

- Two racks with the same name in one place: avahi renames the second `<host>-2.local`, its origin
  changes, and its phones lose their token. Naming machines `golem-<4 chars>` at install would avoid it.
- Local HTTPS: `navigator.wakeLock`, the clipboard and notifications need a secure context, absent on
  `http://…local`. A local certificate signed at pairing would fix it, at the cost of installing trust on
  every phone.
