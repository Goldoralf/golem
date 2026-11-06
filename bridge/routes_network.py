# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes réseau (onglet Network) — implémente docs/network.md.

Lectures = nmcli direct (pas de root nécessaire). Mutations = sudo -n sur le
wrapper root-owned /usr/local/sbin/golem-net (whitelist de verbes, validation
des args — cf. provision/net.sh + setup-net-sudo.sh). Le bridge n'appelle
JAMAIS nmcli en écriture.

Sécurité anti-verrouillage (l'invariant du doc) :
  - « confirmer-ou-revenir » : un join qui coupe la connexion courante doit
    être confirmé sous N secondes, sinon on remonte le dernier profil sain ;
  - l'AP ne s'oublie jamais, Ethernet n'est jamais touché.
"""
import json
import os
import re
import subprocess
import sys
import threading

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from . import config as C

router = APIRouter()

NET_BIN = "/usr/local/sbin/golem-net"
NET_CFG = os.path.join(C.CONFIG_DIR, "network.json")
CONFIRM_WINDOW_S = 20  # « confirmer dans 20 s ou retour auto » (pattern résolution d'écran)


# ── helpers nmcli (lecture seule) ────────────────────────────────────────────

def _run(cmd, timeout=15):
    """Exécute et rend (rc, stdout). Jamais d'exception vers l'appelant."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # nmcli absent (dev sans NM), timeout…
        return 1, str(e)


# ── Windows / macOS : le réseau appartient à l'OS ────────────────────────────────────────────
# Tout ce module est le WiFi du RACK Linux (NetworkManager + un wrapper sudo). Sur un poste, il
# appelait quand même `sudo -n …` : sous Windows 11, `sudo` EXISTE (sudo pour Windows) et répondait
# « unexpected argument '-n' » à qui voulait lever un point d'accès (2026-10-03) — au mieux une
# erreur absconse, au pire une élévation demandée pour une commande Linux. Et un point d'accès n'y
# servirait à rien : le bridge d'un poste écoute 127.0.0.1, une tablette ne le joindrait pas.
# Sous WINDOWS, les mêmes gestes passent par les outils de Windows (bridge/desktop_network.py : netsh,
# le point d'accès mobile) — 2026-10-03 : « regarde comment Linux gère ». macOS : pas encore.
WIN = sys.platform == "win32"
DESKTOP = sys.platform == "darwin"
DESKTOP_WHY = ("On this Mac the WiFi belongs to macOS — golem does not drive it yet. "
               "The access point and the WiFi switching are the rack's.")


def _desktop_refusal():
    return JSONResponse({"error": DESKTOP_WHY}, status_code=501)


def _sudo_net(*args):
    """Mutation via le wrapper root (sudo -n : jamais de prompt — si la règle
    sudoers manque, on échoue proprement avec le message d'installation)."""
    if DESKTOP or WIN:                                # jamais le `sudo` de Windows pour une commande Linux
        return 1, DESKTOP_WHY
    rc, out = _run(["sudo", "-n", NET_BIN, *args], timeout=90)
    if rc != 0 and "sudo" in out and "password" in out.lower():
        out = "network helper not installed — run ./provision/setup-net-sudo.sh on the rack"
    return rc, out


def _devices():
    """[{device, type, state, connection}] via nmcli -t."""
    rc, out = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
    devs = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4:
                devs.append({"device": parts[0], "type": parts[1],
                             "state": parts[2], "connection": ":".join(parts[3:])})
    return devs


def _dev_ip(dev):
    rc, out = _run(["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", dev])
    m = re.search(r"IP4\.ADDRESS\[\d+\]:([\d.]+)/", out) if rc == 0 else None
    return m.group(1) if m else None


def _ap_cfg():
    try:
        with open(NET_CFG) as f:
            return json.load(f).get("ap", {})
    except Exception:
        return {}


def _ap_clients():
    """Nombre de clients de l'AP via les baux DHCP de NM (best-effort)."""
    rc, out = _run(["sh", "-c", "cat /var/lib/NetworkManager/dnsmasq-*.leases 2>/dev/null"])
    return len([l for l in out.splitlines() if l.strip()]) if rc == 0 else 0


# ── confirmer-ou-revenir ─────────────────────────────────────────────────────

_pending = {"timer": None, "prev": None}  # prev = nom du profil sain à remonter
_pending_lock = threading.Lock()


def _current_station():
    """Nom du profil wifi actif (hors golem-ap), ou None."""
    if WIN:
        from . import desktop_network
        return desktop_network.station()["ssid"]
    for d in _devices():
        if d["type"] == "wifi" and d["state"] == "connected" and d["connection"] not in ("", "golem-ap"):
            return d["connection"]
    return None


def _schedule_revert(prev):
    def revert():
        with _pending_lock:
            _pending["timer"] = None
            _pending["prev"] = None
        if WIN:                                       # Windows : le profil d'avant, et pas de point d'accès forcé
            if prev:
                from . import desktop_network
                desktop_network.up(prev)
            return
        if prev:
            _sudo_net("up", prev)
        else:
            # pas de profil sain précédent : on lève l'AP pour rester joignable
            _sudo_net("ap-up")

    with _pending_lock:
        if _pending["timer"]:
            _pending["timer"].cancel()
        t = threading.Timer(CONFIRM_WINDOW_S, revert)
        t.daemon = True
        _pending["timer"] = t
        _pending["prev"] = prev
        t.start()


# ── endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/network")
def network_status():
    if DESKTOP:
        return _mac_status()
    if WIN:
        return _win_status()
    devs = _devices()
    eth = next((d for d in devs if d["type"] == "ethernet" and d["state"] == "connected"), None)
    wifi_devs = [d for d in devs if d["type"] == "wifi"]
    station = next((d for d in wifi_devs if d["state"] == "connected" and d["connection"] != "golem-ap"), None)
    ap = next((d for d in wifi_devs if d["connection"] == "golem-ap" and d["state"] == "connected"), None)
    cfg = _ap_cfg()

    eth_ip = _dev_ip(eth["device"]) if eth else None
    sta_ip = _dev_ip(station["device"]) if station else None
    port = os.environ.get("GOLEM_PORT", "8770")
    reachable = [f"http://{ip}:{port}/app/" for ip in (eth_ip, sta_ip) if ip]
    if ap:
        reachable.append(f"http://10.42.0.1:{port}/app/")

    mode = "ap" if ap else ("station" if station else "none")
    with _pending_lock:
        pending = _pending["timer"] is not None
    return {
        "mode": mode,
        "radios": len({d["device"] for d in wifi_devs}),
        "eth": {"up": bool(eth), "ip": eth_ip},
        "station": {"ssid": station["connection"] if station else None, "ip": sta_ip},
        "ap": {"up": bool(ap), "ssid": cfg.get("ssid", "golem"),
               "ip": "10.42.0.1" if ap else None, "clients": _ap_clients() if ap else 0},
        "reachable": reachable,
        "pending_confirm": pending,
        "confirm_window_s": CONFIRM_WINDOW_S,
        "nm_available": bool(devs),
        "golem": _reach(),
    }


def start_win_fallback():
    """Le « boot-fallback » du rack (provision/net.sh), pour Windows : au lancement de GoleM, si AUCUN
    réseau ne se présente en `fallback_timeout_s` (30 s, config/network.json), on lève le point d'accès
    mobile — sur scène il n'y a pas de WiFi, le téléphone rejoint GoleM directement. Un WiFi ou un câble
    présent (la maison, la répète) : rien ne bouge. `"auto_ap": false` dans network.json l'éteint."""
    if not WIN:
        return
    try:
        with open(NET_CFG) as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    if cfg.get("auto_ap") is False:
        return
    timeout = int(cfg.get("fallback_timeout_s") or 30)

    def watch():
        import time
        from . import connect as connect_mod, desktop_network
        from .golog import get
        log = get("network")
        for _ in range(timeout):
            if connect_mod._win_addresses()["ipv4"]:
                return                                    # un réseau est là : pas de point d'accès
            time.sleep(1)
        log.info("aucun réseau après %d s — point d'accès mobile de Windows (scène)", timeout)
        r = desktop_network.hotspot("on")
        if r.get("error"):
            log.warning("point d'accès non levé : %s", r["error"])
        else:
            log.info("point d'accès levé : %s, http://%s:%s/app/", r.get("ssid"),
                     connect_mod.WIN_AP_IP, os.environ.get("GOLEM_PORT", "8770"))

    threading.Thread(target=watch, name="golem-net-fallback", daemon=True).start()


def _mac_status():
    """macOS (2026-10-04, docs/platforms.md M4) : la MÊME forme que Linux et Windows — l'ancienne
    réponse {desktop, why, reachable} n'avait ni `ap` ni `station`, et la page lisait `net.ap.up` : elle
    plantait. GoleM ne pilote pas le WiFi du Mac (les gestes répondent 501, DESKTOP_WHY) ; il dit où on le
    joint, et si le pare-feu de macOS l'en empêche."""
    from . import connect as connect_mod
    from . import desktop_macos
    port = os.environ.get("GOLEM_PORT", "8770")
    local_only = os.environ.get("GOLEM_BIND", "127.0.0.1").startswith("127.")
    a = connect_mod.addresses()
    addrs = [] if local_only else [x["ip"] for x in a["ipv4"]]
    with _pending_lock:
        pending = _pending["timer"] is not None
    return {
        "mode": "station" if a["primary"] else "none",
        "radios": 1,
        "eth": {"up": False, "ip": None},
        "station": {"ssid": None, "ip": a["primary"]},
        "ap": {"up": False, "ssid": "", "ip": None, "clients": 0, "error": None},
        "reachable": [f"http://{ip}:{port}/app/" for ip in addrs] or [f"http://127.0.0.1:{port}/app/"],
        "local_only": local_only,
        "firewall_open": None if local_only else desktop_macos.firewall_open(),
        "pending_confirm": pending,
        "confirm_window_s": CONFIRM_WINDOW_S,
        "nm_available": True,
        "macos": True, "desktop": True, "why": DESKTOP_WHY,
        "golem": _reach(),
    }


def _win_status():
    """La même forme que la réponse Linux, lue chez Windows. ⚠ `local_only` : le bridge d'un poste écoute
    127.0.0.1 — une tablette sur ce réseau ou sur le point d'accès ne le JOINT PAS encore ; l'écran le dit
    plutôt que d'afficher une adresse qui ne répondrait pas."""
    from . import desktop_network as N
    from . import connect as connect_mod
    sta, hs = N.station(), N.hotspot("status")
    port = os.environ.get("GOLEM_PORT", "8770")
    with _pending_lock:
        pending = _pending["timer"] is not None
    ap_up = hs.get("state") == "On"
    # ouvert au réseau ? (provision/desktop.py lance le bridge sur GOLEM_BIND, 0.0.0.0 par défaut)
    local_only = os.environ.get("GOLEM_BIND", "127.0.0.1").startswith("127.")
    addrs = [] if local_only else [a["ip"] for a in connect_mod.addresses()["ipv4"]]
    reach = {} if local_only else N.reachability()
    return {
        "mode": "ap" if ap_up else ("station" if sta["ssid"] else "none"),
        "radios": max(2, sta["radios"]),                       # le point d'accès de Windows coexiste avec le WiFi
        "eth": {"up": False, "ip": None},
        "station": {"ssid": sta["ssid"],
                    "ip": ", ".join(a for a in N.lan_ips() if a != connect_mod.WIN_AP_IP) or None},
        "ap": {"up": ap_up, "ssid": hs.get("ssid") or "golem",
               "ip": connect_mod.WIN_AP_IP if ap_up else None,
               "clients": hs.get("clients") or 0, "error": hs.get("error")},
        "reachable": [f"http://{ip}:{port}/app/" for ip in addrs] or [f"http://127.0.0.1:{port}/app/"],
        "local_only": local_only,
        "firewall_open": reach.get("rule"),
        "pending_confirm": pending,
        "confirm_window_s": CONFIRM_WINDOW_S,
        "nm_available": True,
        "windows": True,
        "golem": _reach(),
    }


@router.post("/api/network/open")
async def network_open():
    """Windows : ouvrir GoleM aux réseaux privés (la règle du pare-feu) — une invite Windows à l'écran."""
    if not WIN:
        return JSONResponse({"error": "Windows only"}, status_code=400)
    import asyncio
    from . import desktop_network
    ok, text = await asyncio.to_thread(desktop_network.open_firewall)
    return {"ok": True, "log": text} if ok else JSONResponse({"error": text[-400:] or "failed"}, status_code=502)


@router.get("/api/network/scan")
def network_scan():
    if WIN:
        from . import desktop_network
        return {"networks": desktop_network.scan()}
    rc, out = _run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                    "--rescan", "yes"], timeout=30)
    nets, seen = [], set()
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) < 4 or not parts[1]:
                continue
            ssid = parts[1]
            if ssid in seen:  # dédoublonner les BSSID multiples, garder le 1er (plus fort)
                continue
            seen.add(ssid)
            nets.append({"in_use": parts[0] == "*", "ssid": ssid,
                         "signal": int(parts[2] or 0), "security": parts[3]})
    nets.sort(key=lambda n: -n["signal"])
    return {"networks": nets}


@router.get("/api/network/known")
def network_known():
    if WIN:
        from . import desktop_network
        return {"known": desktop_network.known()}
    rc, out = _run(["nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"])
    known = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "802-11-wireless" and parts[0] != "golem-ap":
                known.append({"name": parts[0], "autoconnect": parts[2] == "yes"})
    return {"known": known}


@router.post("/api/network/join")
async def network_join(payload: dict):
    if DESKTOP:
        return _desktop_refusal()
    ssid = (payload.get("ssid") or "").strip()
    psk = payload.get("psk") or ""
    if not ssid:
        return JSONResponse({"error": "ssid required"}, status_code=400)
    prev = _current_station()
    if WIN:
        from . import desktop_network
        rc, out = desktop_network.join(ssid, psk or None)
    else:
        args = ["join", ssid] + ([psk] if psk else [])
        rc, out = _sudo_net(*args)
    if rc != 0:
        return JSONResponse({"error": out.strip()[-400:]}, status_code=502)
    # jointure OK : fenêtre confirmer-ou-revenir (l'UI rappelle /confirm)
    _schedule_revert(prev)
    return {"ok": True, "confirm_within_s": CONFIRM_WINDOW_S}


@router.post("/api/network/confirm")
def network_confirm():
    """L'UI (rechargée depuis la nouvelle IP) confirme : on annule le retour."""
    if DESKTOP:
        return _desktop_refusal()
    with _pending_lock:
        if _pending["timer"]:
            _pending["timer"].cancel()
        _pending["timer"] = None
        _pending["prev"] = None
    return {"ok": True}


@router.post("/api/network/forget")
async def network_forget(payload: dict):
    if DESKTOP:
        return _desktop_refusal()
    name = (payload.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    if WIN:
        from . import desktop_network
        rc, out = desktop_network.forget(name)
    else:
        rc, out = _sudo_net("forget", name)
    return {"ok": True} if rc == 0 else JSONResponse({"error": out.strip()[-400:]}, status_code=502)


@router.post("/api/network/ap")
async def network_ap(payload: dict):
    """Toggle AP. ssid/psk optionnels = mise à jour de config/network.json
    (le wrapper les relit à ap-up)."""
    if DESKTOP:
        return _desktop_refusal()
    on = bool(payload.get("on"))
    ssid = (payload.get("ssid") or "").strip()
    psk = payload.get("psk") or ""
    if WIN:                                           # le point d'accès mobile de Windows (hotspot.ps1)
        if psk and not 8 <= len(psk) <= 63:
            return JSONResponse({"error": "access point password: 8-63 characters"}, status_code=400)
        from . import desktop_network
        r = desktop_network.hotspot("on" if on else "off", ssid or None, psk or None)
        return JSONResponse({"error": r["error"]}, status_code=502) if r.get("error") else {"ok": True}
    if ssid or psk:
        try:
            cfg = {}
            if os.path.exists(NET_CFG):
                with open(NET_CFG) as f:
                    cfg = json.load(f)
            ap = cfg.setdefault("ap", {})
            if ssid:
                ap["ssid"] = ssid
            if psk:
                if not 8 <= len(psk) <= 63:
                    return JSONResponse({"error": "access point password: 8-63 characters"}, status_code=400)
                ap["psk"] = psk
            ap.setdefault("band", "bg")
            cfg.setdefault("fallback_timeout_s", 30)
            with open(NET_CFG, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            return JSONResponse({"error": f"network.json: {e}"}, status_code=500)
    rc, out = _sudo_net("ap-up" if on else "ap-down")
    if rc != 0:
        return JSONResponse({"error": out.strip()[-400:]}, status_code=502)
    return {"ok": True}


def _reach():
    """L'adresse simple de GoleM (bridge/reach.py) : {host, url, mdns, port80}."""
    from . import reach
    return reach.status()


def open_url():
    """L'adresse à donner à une tablette : le nom (golem.local) s'il répond, sinon la première adresse
    joignable. Partagée par le QR et par « Continue on tablet » (app/device.html)."""
    r = _reach()
    if r.get("mdns"):
        return r["url"]
    try:
        reach = network_status().get("reachable") or []
    except Exception:
        reach = []
    return reach[0] if reach else r["url"]


@router.get("/api/network/open-url")
def network_open_url():
    """{url, named} — ce que le QR « opens GoleM » encode, en clair."""
    url = open_url()
    return {"url": url, "named": bool(_reach().get("mdns"))}


@router.get("/api/network/open-qr")
def network_open_qr():
    """Le SECOND QR (2026-10-03) : celui du WiFi fait rejoindre le réseau, pas ouvrir une page — un QR
    ne fait qu'une chose. Celui-ci ouvre GoleM, à son nom (http://golem.local) : le même à la maison et
    sur scène, et c'est l'adresse qu'on garde sur l'écran d'accueil du téléphone.
    ⚠ SEULEMENT si le nom répond (2026-10-06) : sans mDNS, le QR encodait quand même golem.local et
    menait nulle part — on prend alors la première adresse joignable, celle que la page affiche."""
    url = open_url()
    try:
        import io
        import qrcode
        import qrcode.image.svg
        buf = io.BytesIO()
        qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12).save(buf)
        return Response(content=buf.getvalue(), media_type="image/svg+xml")
    except ImportError:
        return JSONResponse({"error": "qrcode module missing"}, status_code=501)


@router.get("/api/network/qr")
def network_qr():
    """QR WiFi de l'AP (SVG, généré localement — pas de CDN, CSP kiosk)."""
    cfg = _ap_cfg()
    if WIN:
        from . import desktop_network
        cfg = desktop_network.hotspot("status")
    ssid, psk = cfg.get("ssid", "golem"), cfg.get("psk", "")
    if not psk:
        return JSONResponse({"error": "access point not configured (provision/setup-net-sudo.sh)"}, status_code=404)
    esc = lambda s: re.sub(r'([\\;,:"])', r"\\\1", s)
    payload = f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};;"
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(payload, image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
        import io
        buf = io.BytesIO()
        img.save(buf)
        return Response(content=buf.getvalue(), media_type="image/svg+xml")
    except ImportError:
        return JSONResponse({"error": "module qrcode absent (bridge-setup.sh)"}, status_code=501)
