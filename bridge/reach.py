# SPDX-License-Identifier: GPL-3.0-or-later
"""JOINDRE GoleM SANS TAPER D'IP : `http://golem.local` — sur le rack Linux comme sur un poste Windows/macOS.

Deux morceaux, lancés au démarrage du bridge (app.py) :

  · le NOM : GoleM s'annonce en mDNS sous `golem.local` (python-zeroconf), avec TOUTES ses adresses —
    le WiFi de la maison (192.168.0.x), le point d'accès de scène (10.42.0.1 sur le rack, 192.168.137.1
    sous Windows) — et les ré-annonce quand elles changent (un point d'accès qui se lève). iOS et Android
    récents résolvent `.local` ; mesuré le 2026-10-03 sur le téléphone du mainteneur : `studiopc.local` (le nom
    que Windows annonce de lui-même) ouvrait GoleM. Le rack garde en plus `<machine>.local` (avahi) et le
    DNS de son point d'accès sert `golem.local` aux téléphones qui n'interrogent pas mDNS (provision/net.sh).
  · le PORT 80 : un petit serveur qui ne fait que RENVOYER vers le port du bridge (8770), pour que
    `http://golem.local` suffise — « Studiopc.local » sans le `:8770` affichait « site inaccessible ».
    Sous Linux le port 80 est réservé à root : provision/harden.sh l'ouvre aux utilisateurs
    (`net.ipv4.ip_unprivileged_port_start=80`). Port pris ou refusé : on le DIT au journal, rien d'autre.

Deux GoleM sur le même réseau (le rack et un PC) répondraient tous deux à `golem.local` : le second
prend `golem-<machine>.local` (NAME_TAKEN dans le statut, l'écran Network affiche le nom retenu).
"""
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .golog import get

log = get("reach")

NAME = "golem"
PORT = int(os.environ.get("GOLEM_PORT", "8770"))
_STATE = {"name": None, "mdns": None, "port80": None, "addresses": None}   # None = jamais annoncé


def status():
    """{host, url, mdns, port80} pour l'écran Network et le QR « Ouvrir GoleM »."""
    host = (_STATE["name"] or NAME) + ".local"
    url = f"http://{host}/" if _STATE["port80"] is True else f"http://{host}:{PORT}/"
    return {"host": host, "url": url, "mdns": _STATE["mdns"], "port80": _STATE["port80"],
            "addresses": list(_STATE["addresses"] or [])}


# ── le port 80 : un renvoi, rien d'autre ─────────────────────────────────────────────────────
class _Redirect(BaseHTTPRequestHandler):
    def do_GET(self):
        host = (self.headers.get("Host") or "golem.local").split(":")[0]
        self.send_response(302)
        self.send_header("Location", f"http://{host}:{PORT}{self.path or '/'}")
        self.send_header("Cache-Control", "no-store")     # le jour où le port change, on ne garde rien
        self.end_headers()

    do_HEAD = do_GET

    def log_message(self, *_):
        pass


def _serve_port80():
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", 80), _Redirect)
    except OSError as e:
        _STATE["port80"] = False
        log.info("port 80 indisponible (%s) — l'adresse reste http://golem.local:%d", e, PORT)
        return
    _STATE["port80"] = True
    log.info("port 80 -> %d : http://golem.local suffit", PORT)
    srv.serve_forever()


# ── le nom mDNS ──────────────────────────────────────────────────────────────────────────────
def _addresses():
    from . import connect
    return [a["ip"] for a in connect.addresses()["ipv4"]]


def _mdns_loop():
    try:
        from zeroconf import IPVersion, ServiceInfo, Zeroconf
    except ImportError as e:
        _STATE["mdns"] = False
        log.warning("zeroconf absent (%s) — pas de golem.local (pip install -r bridge/requirements.txt)", e)
        return
    zc = info = None
    while True:
        try:
            addrs = _addresses()
            if addrs != _STATE["addresses"]:
                if zc is None:
                    zc = Zeroconf(ip_version=IPVersion.V4Only)
                    name = NAME
                    # un autre GoleM répond déjà à golem.local sur ce réseau : on prend un nom à nous
                    try:
                        taken = zc.get_service_info("_http._tcp.local.", "GoleM._http._tcp.local.", timeout=1500)
                    except Exception:
                        taken = None
                    if taken is not None:
                        name = f"{NAME}-{socket.gethostname().split('.')[0].lower()}"
                    _STATE["name"] = name
                new = ServiceInfo("_http._tcp.local.", f"GoleM {_STATE['name']}._http._tcp.local."
                                  if _STATE["name"] != NAME else "GoleM._http._tcp.local.",
                                  addresses=[socket.inet_aton(a) for a in addrs], port=PORT,
                                  properties={"path": "/app/"}, server=f"{_STATE['name']}.local.")
                if info is None:
                    zc.register_service(new, allow_name_change=True)
                else:
                    zc.update_service(new)
                info = new
                _STATE.update(addresses=addrs, mdns=True)
                log.info("mDNS : %s.local -> %s", _STATE["name"], ", ".join(addrs) or "aucune adresse")
        except Exception as e:
            _STATE["mdns"] = False
            log.warning("mDNS indisponible : %s", e)
        time.sleep(15)                                   # un point d'accès qui se lève : ≤ 15 s


def start():
    if os.environ.get("GOLEM_NO_REACH") == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
        return                                           # tests, et qui ne veut rien annoncer
    threading.Thread(target=_serve_port80, name="golem-port80", daemon=True).start()
    threading.Thread(target=_mdns_loop, name="golem-mdns", daemon=True).start()
