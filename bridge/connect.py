# SPDX-License-Identifier: GPL-3.0-or-later
"""SE CONNECTER AU RACK SANS TAPER D'ADRESSE (docs/connect.md, lots R1/R2 — 2026-09-16).

Trois choses, et rien d'autre :

1. LES VRAIES ADRESSES du rack. `hostname -I` rend tout, dans l'ordre du noyau : sur la machine de dev,
   192.168.0.22 puis libvirt, quatre ponts Docker et trois IPv6. Le QR d'invitation prenait la
   première — la bonne par chance. Ici : l'adresse de la ROUTE PAR DÉFAUT d'abord, puis les autres
   interfaces physiques branchées, le point d'accès (10.42.0.1) s'il est levé, jamais un pont virtuel.

2. LA PRÉSENCE : le rack dit à golem.fm où le trouver ce soir (`PUT /api/ext/golem/connect/presence`),
   15 s après le démarrage, toutes les 5 min, et dans les 30 s qui suivent un changement d'adresse.
   Seulement si la case « Let golem.fm find this rack » est cochée (§5 : cochée par défaut sur un rack
   appairé ; décochée = la présence est retirée). Jamais : appareils, personnes, MAC, baux DHCP, mot de
   passe du Wi-Fi.

3. LE RACHAT D'UN TICKET : la page golem.fm/connect redirige le téléphone vers le rack avec un ticket
   (60 s, usage unique) dans le fragment ; le rack le rachète auprès de golem.fm avec SON jeton et crée
   (ou retrouve) l'appareil de la personne. Aucun secret partagé à garder des deux côtés.
"""
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time

from . import config as C
from .golog import get

log = get("connect")

PORT = int(os.environ.get("GOLEM_PORT", "8770"))
AP_IP = "10.42.0.1"                     # NetworkManager `shared` : l'adresse du point d'accès (docs/network.md)
PRESENCE_EVERY = 300                    # battement
ADDR_POLL = 30                          # un changement d'adresse part dans les 30 s
FIRST_PUSH = 15
SESSION = secrets.token_urlsafe(9)      # change à chaque démarrage du bridge
PRESENCE_PATH = "/api/ext/golem/connect/presence"
REDEEM_PATH = "/api/ext/golem/connect/redeem"

# interfaces qui ne sont PAS le réseau où vit un téléphone : boucle, Docker, libvirt, VPN, conteneurs
_VIRTUAL = re.compile(r"^(lo$|docker|br-|virbr|veth|vnet|tun|tap|wg|tailscale|zt|lxc|lxd|cni|flannel|podman|vmnet)")


# ── 1. les adresses ─────────────────────────────────────────────────────────────────────────────
def _ip_json(*args):
    try:
        out = subprocess.run(["ip", "-j", *args], capture_output=True, text=True, timeout=3).stdout
        return json.loads(out or "[]")
    except Exception:
        return []


WIN_AP_IP = "192.168.137.1"             # le point d'accès mobile de Windows (Internet Connection Sharing)


def _win_addresses():
    """Windows : `ip` n'existe pas. L'adresse de la route par défaut (socket UDP, rien n'est envoyé), puis
    les IPv4 des cartes branchées, sans les cartes virtuelles (WSL, Hyper-V, VPN, VirtualBox)."""
    import socket
    primary = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            primary = s.getsockname()[0]
    except OSError:
        pass
    v4 = []
    try:
        out = subprocess.run(
            # UTF-8 IMPOSÉ : le nom d'interface du point d'accès est « Connexion au réseau local* 10 » — en
            # page de code OEM, l'« é » cassait le décodage et la liste revenait VIDE (mesuré 2026-10-03)
            ["powershell.exe", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.AddressState -eq 'Preferred' } | "
             "Select-Object IPAddress,InterfaceAlias | ConvertTo-Json -Compress"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        rows = json.loads(out or "[]")
        rows = [rows] if isinstance(rows, dict) else rows
    except Exception:
        rows = []
    for r in rows:
        ip, dev = str(r.get("IPAddress") or ""), str(r.get("InterfaceAlias") or "")
        if ip.startswith(("127.", "169.254.")) or re.search(r"(?i)vethernet|wsl|hyper-v|virtualbox|vmware|vpn|loopback|tailscale|zerotier", dev):
            continue
        v4.append({"ip": ip, "dev": dev})
    ap = any(x["ip"] == WIN_AP_IP for x in v4)
    if primary not in [x["ip"] for x in v4]:
        primary = None
    v4.sort(key=lambda x: (x["ip"] != primary, x["ip"] == WIN_AP_IP))
    return {"primary": primary or (v4[0]["ip"] if v4 else None), "ipv4": v4, "ap": ap, "ipv6_prefixes": []}


# macOS (2026-10-04, docs/platforms.md M4) : `ip` n'existe pas non plus — la page Network n'avait
# ni adresse ni QR, et golem.local (bridge/reach.py, qui lit CETTE liste) s'annonçait sans adresse.
# `ifconfig` est là sur tout Mac ; on garde les interfaces UP+RUNNING, sans les virtuelles d'Apple
# (utun = VPN/iCloud Private Relay, awdl/llw = AirDrop, bridge = partage Internet et VM, anpi, gif, stf).
_MAC_VIRTUAL = re.compile(r"^(lo\d|utun|awdl|llw|bridge|anpi|gif|stf|ap\d|vmnet|vboxnet|feth)")


def parse_ifconfig(text):
    """[{ip, dev}] des IPv4 des interfaces UP et RUNNING de `ifconfig` (macOS), virtuelles exclues."""
    out, dev, up = [], None, False
    for line in (text or "").splitlines():
        m = re.match(r"^([A-Za-z0-9]+): flags=\d+<([^>]*)>", line)
        if m:
            dev, flags = m.group(1), m.group(2).split(",")
            up = "UP" in flags and "RUNNING" in flags and not _MAC_VIRTUAL.match(dev)
            continue
        m = re.match(r"^\s+inet (\d+\.\d+\.\d+\.\d+)\s", line)
        if m and dev and up and not m.group(1).startswith(("127.", "169.254.")):
            out.append({"ip": m.group(1), "dev": dev})
    return out


def _default_route_ip():
    """L'adresse locale de la route par défaut (socket UDP connecté : rien n'est envoyé)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _mac_addresses(ifconfig=None, primary=None):
    if ifconfig is None:
        try:
            ifconfig = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3).stdout
        except Exception:
            ifconfig = ""
    v4 = parse_ifconfig(ifconfig)
    primary = primary if primary is not None else _default_route_ip()
    if primary not in [x["ip"] for x in v4]:
        primary = None
    v4.sort(key=lambda x: x["ip"] != primary)
    return {"primary": primary or (v4[0]["ip"] if v4 else None), "ipv4": v4, "ap": False, "ipv6_prefixes": []}


def addresses(links=None, route=None):
    """{primary, ipv4: [{ip, dev}], ap, ipv6_prefixes: ["…::/64"]} — interfaces physiques branchées.
    `links`/`route` : sorties de `ip -j addr` / `ip -j route get 1.1.1.1`, injectables pour les tests."""
    if links is None and route is None and sys.platform == "win32":
        return _win_addresses()
    if links is None and route is None and sys.platform == "darwin":
        return _mac_addresses()
    links = _ip_json("addr", "show") if links is None else links
    route = _ip_json("route", "get", "1.1.1.1") if route is None else route
    v4, v6, ap = [], [], False
    for L in links or []:
        name = str(L.get("ifname") or "")
        flags = L.get("flags") or []
        if _VIRTUAL.match(name) or "LOWER_UP" not in flags:
            continue
        for a in L.get("addr_info") or []:
            if a.get("scope") != "global" or not a.get("local"):
                continue
            if a.get("family") == "inet":
                ap = ap or a["local"] == AP_IP
                v4.append({"ip": a["local"], "dev": name})
            elif a.get("family") == "inet6" and not a.get("deprecated"):
                try:
                    net = str(ipaddress.ip_network(f"{a['local']}/64", strict=False))
                except ValueError:
                    continue
                if net not in v6 and not ipaddress.ip_network(net).is_private:
                    v6.append(net)
    primary = (route[0].get("prefsrc") if route and isinstance(route[0], dict) else None)
    if primary not in [x["ip"] for x in v4]:
        primary = None
    # la route par défaut d'abord, le point d'accès en dernier (un téléphone du salon n'est pas dessus)
    v4.sort(key=lambda x: (x["ip"] != primary, x["ip"] == AP_IP))
    return {"primary": primary or (v4[0]["ip"] if v4 else None), "ipv4": v4, "ap": ap, "ipv6_prefixes": v6}


def lan_ip():
    """L'adresse qu'un QR d'invitation doit porter : la route par défaut, sinon le point d'accès."""
    return addresses()["primary"]


def mdns_host():
    """`<machine>.local` si avahi tourne (provision/harden.sh), sinon None : on n'annonce pas un nom
    que personne ne résout. macOS : Bonjour (mDNSResponder) fait partie du système — le nom local de la
    machine (`scutil --get LocalHostName`) se résout toujours."""
    if sys.platform == "darwin":
        try:
            h = subprocess.run(["scutil", "--get", "LocalHostName"], capture_output=True, text=True,
                               timeout=3).stdout.strip()
        except Exception:
            h = ""
        return f"{h}.local" if h else None
    try:
        r = subprocess.run(["systemctl", "is-active", "avahi-daemon"], capture_output=True, text=True, timeout=3)
        if r.stdout.strip() != "active":
            return None
    except Exception:
        return None
    h = socket.gethostname().split(".")[0].strip()
    return f"{h}.local" if h else None


def local_url():
    h = mdns_host()
    return f"http://{h}:{PORT}" if h else None


def _wifi():
    """{ssid, ap, ap_ssid} — le profil station actif (son nom = le SSID dans l'usage courant) et le point
    d'accès. Lecture seule, tolérant : nmcli absent ⇒ tout à None."""
    try:
        from . import routes_network as rn
        cfg = rn._ap_cfg()
        return {"ssid": rn._current_station(), "ap": False, "ap_ssid": cfg.get("ssid") or "golem"}
    except Exception:
        return {"ssid": None, "ap": False, "ap_ssid": None}


def _band():
    try:
        from . import roster
        b = roster.read().get("band") or {}
        return b.get("id") if b.get("source") != "local-temporary" else None
    except Exception:
        return None


def rack_id():
    """Un identifiant STABLE du rack, jamais montré (docs/connect.md §4.1) : golem.fm hache le `client` du
    téléphone avec lui. L'id du jeton golem.fm ne convient pas — il change à chaque réappairage, et tous
    les téléphones deviendraient des appareils neufs. Dérivé de /etc/machine-id (salé : l'id de la
    machine ne sort pas tel quel), sinon tiré au sort une fois et gardé dans config/."""
    try:
        mid = open("/etc/machine-id").read().strip()
    except OSError:
        mid = ""
    if mid:
        return hashlib.sha256(("golem-connect:" + mid).encode()).hexdigest()[:24]
    path = os.path.join(C.CONFIG_DIR, ".rack-id")
    try:
        v = open(path).read().strip()
        if v:
            return v
    except OSError:
        pass
    v = secrets.token_hex(12)
    with open(path, "w") as f:
        f.write(v)
    return v


def presence_payload(addr=None):
    addr = addr or addresses()
    host = mdns_host()
    # au plus 6 (golem.fm refuse au-delà) : cinq IP au plus, le nom en dernier mais jamais coupé
    urls = [f"http://{x['ip']}:{PORT}" for x in addr["ipv4"]][:5 if host else 6]
    if host:
        urls.append(f"http://{host}:{PORT}")
    w = _wifi()
    w["ap"] = bool(addr["ap"])
    return {"session": SESSION, "rack_id": rack_id(), "name": "golem", "host": host, "port": PORT, "urls": urls,
            "ipv6_prefixes": addr["ipv6_prefixes"][:8], "wifi": w, "band": _band(),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


# ── 2. la présence ──────────────────────────────────────────────────────────────────────────────
def presence_enabled():
    """La case du §5 : cochée par défaut (absente = oui)."""
    try:
        from .routes_content import _load_integrations
        return (_load_integrations().get("golemfm") or {}).get("connect_presence") is not False
    except Exception:
        return True


def set_presence(on):
    from .routes_content import _INTEGRATIONS_PATH, _load_integrations, _write_json_atomic
    d = _load_integrations()
    d.setdefault("golemfm", {})["connect_presence"] = bool(on)
    _write_json_atomic(_INTEGRATIONS_PATH, d)
    _last["sig"] = None
    if on:
        threading.Thread(target=push_presence, daemon=True).start()
    else:
        threading.Thread(target=withdraw, daemon=True).start()
    return bool(on)


_last = {"sig": None, "at": 0.0, "status": None, "warned": False}


def push_presence(payload=None):
    """PUT de la présence. Rend le code HTTP (0 = injoignable ou non appairé)."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not base or not token or not presence_enabled():
        return 0
    body = payload or presence_payload()
    st, err = golemfm._req(PRESENCE_PATH, body=body, token=token, method="PUT", timeout=8)
    _last.update(status=st, at=time.time())
    if st == 404 and not _last["warned"]:
        log.warning("golem.fm n'expose pas encore /api/ext/golem/connect/presence (lot W) — présence ignorée")
        _last["warned"] = True
    elif st == 200:
        _last["warned"] = False
    elif st not in (0, 404):
        log.warning(f"présence refusée ({st}) : {err}")
    return st


def withdraw():
    """La case décochée (ou l'arrêt propre) : golem.fm oublie où est le rack. Best effort."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not base or not token:
        return 0
    st, _ = golemfm._req(PRESENCE_PATH, token=token, method="DELETE", timeout=4)
    return st


def _signature(p):
    return json.dumps({k: p.get(k) for k in ("urls", "ipv6_prefixes", "wifi", "band", "host")}, sort_keys=True)


def tick(now=None):
    """Un passage de la boucle : pousse si les adresses ont changé ou si le battement est dû."""
    from . import golemfm
    now = time.time() if now is None else now
    base, token = golemfm._cfg()
    if not base or not token or not presence_enabled():
        _last["sig"] = None              # appairé plus tard, ou case recochée : la présence partira tout de suite
        return None
    p = presence_payload()
    sig = _signature(p)
    if sig != _last["sig"] or now - _last["at"] >= PRESENCE_EVERY:
        st = push_presence(p)
        # quel que soit le verdict : un refus (404 tant que golem.fm n'a pas le lot W) ou un réseau coupé
        # se retente au BATTEMENT, pas toutes les 30 s ; une nouvelle adresse, elle, repart aussitôt
        _last.update(sig=sig, at=now)
        return st
    return None


_loop = None


def start():
    """Thread démon, idempotent. Silencieux tant que le rack n'est pas appairé."""
    global _loop
    if _loop is not None:
        return

    def run():
        time.sleep(FIRST_PUSH)
        while True:
            try:
                tick()
            except Exception as e:
                log.warning(f"présence : {e}")
            time.sleep(ADDR_POLL)

    _loop = threading.Thread(target=run, daemon=True, name="connect-presence")
    _loop.start()


def where():
    """Ce que la présence annonce (diagnostic, écran du rack) + l'état de la case."""
    p = presence_payload()
    return {**p, "enabled": presence_enabled(), "last_status": _last["status"],
            "last_at": _last["at"] or None, "local_url": local_url()}


# ── 3. le rachat du ticket ──────────────────────────────────────────────────────────────────────
def redeem(ticket, ua="", ip=""):
    """Ticket golem.fm ⇒ appareil. Rend (code HTTP, corps) — les messages sont pour l'écran du téléphone."""
    from . import auth, golemfm
    ticket = str(ticket or "").strip()
    if not ticket or len(ticket) > 256:
        return 400, {"error": "This link is incomplete. Open golem.fm/connect again."}
    base, token = golemfm._cfg()
    if not base or not token:
        return 409, {"error": "This golem is not paired with golem.fm. Scan the QR on the rack instead."}
    st, d = golemfm._req(REDEEM_PATH, body={"ticket": ticket}, token=token, timeout=8)
    if st == 0:
        return 502, {"error": "This golem can't reach golem.fm right now. Scan the QR on the rack instead."}
    if st in (404, 410):
        return 410, {"error": "This link has expired or was already used. Open golem.fm/connect again."}
    if st != 200 or not isinstance(d, dict):
        return 502, {"error": f"golem.fm refused this link ({st})."}
    person = d.get("person") if isinstance(d.get("person"), dict) else None
    screen = bool(d.get("screen"))
    if not screen and not (person and person.get("id")):
        return 502, {"error": "golem.fm did not say who you are."}
    if person and person["id"] not in auth._people():
        # golem.fm s'est porté garant ; le cache du groupe a peut-être un jour de retard
        try:
            from . import roster
            roster.sync()
        except Exception as e:
            log.warning(f"roster avant connexion : {e}")
    got = auth.connect_device(person=person, kind=d.get("kind"), screen=screen,
                              client=client_key(d.get("client")), ua=ua, ip=ip)
    if got.get("error"):
        return 400, got
    log.info(f"appareil connecté par golem.fm : {got['name']}")
    return 200, {**got, "local_url": local_url()}


def client_key(raw):
    """Un `client` venu de golem.fm est déjà un haché ; on le borne et on le re-hache court pour le disque."""
    raw = str(raw or "").strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:32] if raw else None
