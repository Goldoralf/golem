# Network

> **Status: CODED** (Linux rack and Windows; macOS reads only) — how a tablet or a phone reaches
> golem: Wi-Fi station, access-point fallback, the `golem.local` name, and the **Network** page.
> Simultaneous station + access point on a two-radio machine is **PROPOSED** (see §3).

Related: [`SECURITY.md`](../SECURITY.md) (who may connect), [`connect.md`](connect.md) (golem.fm
connect and the tablet hand-off), [`rack-hardware.md`](rack-hardware.md) §6 (Wi-Fi and Ethernet
hardware), [`platforms.md`](platforms.md).

## 1. The invariant: golem is always reachable

A rack has no keyboard on stage. Three safety nets, strongest first:

1. **Ethernet** is the permanent admin door. A cable always reaches the rack, whatever Wi-Fi does,
   so Wi-Fi may switch modes without bricking the box.
2. **Access-point fallback at boot.** If no known network connects within `fallback_timeout_s`
   (default 30 s), the rack raises its own access point. At home a known network connects and the
   access point stays down; on stage nothing is known and the access point comes up.
3. **Confirm-or-revert** on manual switches. Joining a network from the app applies it, then
   reverts to the previous profile unless the user confirms within **20 s**
   (`CONFIRM_WINDOW_S`, `_schedule_revert` in `bridge/routes_network.py`) — the screen-resolution
   pattern.

The **Network** page always shows how to reach golem right now.

## 2. Configuration — `config/network.json`

Local, not versioned (it holds the access-point passphrase). Created by
`provision/setup-net-sudo.sh` with a random passphrase (`golem-` + 16 random characters). If
`ap.ssid` is missing, `net.sh` uses `golem`.

```json
{
  "ap": { "ssid": "golem", "psk": "<8-63 chars>", "band": "bg" },
  "fallback_timeout_s": 30,
  "auto_ap": true
}
```

- `ap.band` — `bg` (2.4 GHz) by default; never 6 GHz on the reference Wi-Fi chip
  ([`rack-hardware.md`](rack-hardware.md) §6).
- `auto_ap: false` disables the fallback (Windows; on Linux, disable `golem-net.service`).
- The access point always uses WPA2-PSK; an open access point is refused (`net.sh` dies without a
  passphrase).

## 3. Linux rack

**Tools.** NetworkManager (`nmcli`) does both roles; no hand-written hostapd/dnsmasq. The access
point is a **persistent dedicated profile** `golem-ap` (`mode ap`, `ipv4.method shared`,
`wifi-sec.key-mgmt wpa-psk`, `autoconnect no`): fixed address **10.42.0.1**, DHCP and DNS from
NetworkManager's dnsmasq, raised only by the fallback or the app.

**Scoped sudo.** The bridge never calls `nmcli` to change anything. Mutations go through
`sudo /usr/local/sbin/golem-net <verb>`, a **root-owned copy** of `provision/net.sh` installed by
`provision/setup-net-sudo.sh` (a user-writable script under NOPASSWD would be a trivial
escalation). The sudoers rule `/etc/sudoers.d/golem-net` allows only the mutating verbs. `net.sh`
validates every argument (whitelisted verbs, SSID and passphrase checked, no option injection).

| Verb | Root | What it does |
|---|---|---|
| `status`, `scan`, `known`, `leases` | no | Device state, Wi-Fi scan, known profiles, DHCP leases of the access point |
| `join <ssid> [psk]` | yes | Join a network (creates and activates the profile) |
| `up <name>` / `down <name>` / `forget <name>` | yes | Reactivate, drop, delete a profile |
| `ap-up` / `ap-down` | yes | Create or update `golem-ap` from `config/network.json`, then bring it up / down |
| `boot-fallback` | yes | The boot state machine below |

**Boot** (`golem-net.service`, installed and enabled by `setup-net-sudo.sh`, after
NetworkManager):

```
boot
 ├─ Ethernet up ───────────────────────────────► reachable (admin), Wi-Fi continues in parallel
 └─ Wi-Fi: a known station profile connects < timeout ─► station
          otherwise ──────────────────────────► golem-ap up ─► access point (10.42.0.1)
```

**Rack name on the access point.** `ap-up` writes
`/etc/NetworkManager/dnsmasq-shared.d/golem-name.conf` so that `<hostname>.local` and `golem.local`
resolve to 10.42.0.1 for phones that do not query mDNS.

**One radio vs two.** With one Wi-Fi radio the modes are exclusive (station **or** access point).
The page reports `radios` and says "2 radios → station + AP simultaneously" when it sees two, but
**this is not built**: `net.sh` `wifi_dev()` always binds `golem-ap` to the **first** Wi-Fi device,
so there is no way to put the station on one radio and the access point on the other.

**Firewall** (`provision/harden.sh`, ufw): SSH, TCP 8770 (app/API), TCP 80 (`golem.local`
redirect), UDP 5353 (mDNS). `net.ipv4.ip_unprivileged_port_start=80` lets the bridge bind port 80
without root.

## 4. Windows

Same two cases with Windows' own tools: `bridge/desktop_network.py` and
`provision/windows/hotspot.ps1`.

| | Linux rack | Windows |
|---|---|---|
| Home / rehearsal | NetworkManager station, `<hostname>.local` (avahi) | Windows Wi-Fi; `http://<PC address>:8770/app/` |
| Stage | `golem-net boot-fallback` → `golem-ap`, 10.42.0.1 | `routes_network.start_win_fallback`: no network 30 s after launch → Windows **mobile hotspot**, 192.168.137.1 |
| Access point SSID / passphrase | `config/network.json` | The mobile hotspot's, editable on the Network page |
| Firewall | ufw (`harden.sh`) | Rules written by `install-system.ps1 -Firewall`: **"GoleM - bridge"** (TCP 8770 and 80 for the bridge's Python, every network profile — pairing is the guard, not the Public/Private category), a UDP 5353 rule for mDNS, and an **inbound block** for `reaper.exe` (REAPER opens its OSC port on all interfaces) |

The desktop bridge listens on `0.0.0.0`; `GOLEM_BIND=127.0.0.1` closes it to the network
(`provision/desktop.py`). The mobile hotspot starts without Internet from any known profile. Its
DNS cannot be configured, so on stage the QR code (an IP address) is the reliable path.

## 5. macOS

The page shows addresses (`ifconfig`), the Bonjour name and the firewall state, read without
privileges. Every network **change** answers **501** (`_desktop_refusal`): golem does not drive the
Mac's Wi-Fi or Internet Sharing.

## 6. One address everywhere: `http://golem.local`

- **mDNS.** The bridge announces itself as `golem.local` (`bridge/reach.py`, python-zeroconf) with
  **all** its addresses (home Wi-Fi and access point) and re-announces within 15 s when they change.
  If the name is taken on the network, it uses `golem-<hostname>.local` and the page shows the name
  it got. The Linux rack also keeps `<hostname>.local` through avahi.
- **Port 80** redirects to 8770 (`reach._serve_port80`), so `http://golem.local` is enough.
- **Why one name matters.** A device token is stored under the **origin** of the URL
  (`localStorage` and cookie). A phone paired on one IP is not paired on another; one name keeps a
  home-screen shortcut paired at home and on stage. The pairing QR therefore encodes `golem.local`
  when mDNS works (`GET /api/auth/qr`), and `connect.md` describes the hand-off that moves a token to
  that origin.

## 7. API — `bridge/routes_network.py`

| Route | Behaviour |
|---|---|
| `GET /api/network` | `{mode: station\|ap\|none, radios, eth{up,ip}, station{ssid,ip}, ap{up,ssid,ip,clients}, reachable[urls], pending_confirm, confirm_window_s, nm_available, golem{host,url,mdns,port80}}` (Windows and macOS return the same shape from their own probes) |
| `GET /api/network/scan` | Visible networks (in use, SSID, signal, security) |
| `GET /api/network/known` | Known profiles |
| `POST /api/network/join {ssid, psk}` | Join, then **confirm within 20 s** or revert |
| `POST /api/network/confirm` | Keep the new network |
| `POST /api/network/forget {name}` | Delete a profile |
| `POST /api/network/ap {on, ssid?, psk?}` | Raise / drop the access point; `ssid`/`psk` update `config/network.json` (passphrase 8–63 characters) |
| `POST /api/network/open` | Windows only: add the firewall rule that opens golem to the network (a Windows prompt appears on the PC); 400 elsewhere |
| `GET /api/network/qr` | SVG Wi-Fi QR of the access point (`WIFI:T:WPA2;S:…;P:…;;`), generated by the bridge (`qrcode`, no CDN) |
| `GET /api/network/open-url`, `GET /api/network/open-qr` | The address to give a tablet (`golem.local` if it answers, else the first reachable URL) and its QR |

Access: every `POST` here is **admin** (`/api/network/` is in `ADMIN_PREFIX`), and
`GET /api/network/qr` is a sensitive read because it carries the passphrase
([`SECURITY.md`](../SECURITY.md)).

## 8. The Network page

`app/page-network.js`, two sub-tabs:

- **Connect** — "reachable now" first: mode, Ethernet / station / access-point badges with
  addresses, and two QR codes, "1 · <SSID> — joins the WiFi" (the access point) and "2 · <host> — opens golem"
  (`http://golem.local`). One QR does one thing. Then station (current network, scan, passphrase,
  known networks with forget) and access point (toggle, SSID and passphrase, band, client count).
  A switch that drops the current link shows the 20-second confirmation.
- **Devices** — paired devices and invitations ([`SECURITY.md`](../SECURITY.md),
  [`devices-people.md`](devices-people.md)). The old `#/system/sys/devices` route redirects here.

## 9. Not built

- Simultaneous station + access point on two radios (§3).
- A captive portal on the access point.
- Driving Wi-Fi on macOS.
