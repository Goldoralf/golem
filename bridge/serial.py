# SPDX-License-Identifier: GPL-3.0-or-later
"""Le NUMÉRO À VIE du golem — `golem_1`, `golem_2`… (docs/connect.md §4.5, contrat golem.fm du 2026-09-24).

L'identité est (utilisateur, MACHINE) : golem.fm attribue le numéro au `rack_id` (le dérivé salé de
/etc/machine-id de `connect.rack_id`, jamais montré tel quel), pas au jeton — révoquer ou ré-appairer la
même machine rend le MÊME numéro. Il arrive à l'approbation de l'appairage (`pair/poll`) ou, pour un rack
appairé avant le contrat, dans la réponse du premier battement qui porte `rack_id`. Idempotent : chaque
battement rend le même numéro.

Ici il s'écrit UNE FOIS dans config/serial.json (0444) et ne se réécrit jamais : un numéro différent qui
arriverait par la suite est une ANOMALIE, gardée dans config/serial.conflict.json et montrée sur l'écran
— pas corrigée en silence. La fiche machine (`machine()`) est ce que golem.fm affiche du rack : liste
blanche, rien qui nomme quelqu'un (le nom d'hôte est celui de la machine, pas d'une personne)."""
import json
import logging
import os
import platform
import re
import shutil
import socket
import sys
import time

from . import config as C

log = logging.getLogger("golem.serial")

_NAME = re.compile(r"^golem_\d+$")


def _path():
    return os.path.join(C.CONFIG_DIR, "serial.json")


def _provisional_path():
    return os.path.join(C.CONFIG_DIR, "serial.provisional.json")


# SEULE LA PROD GRAVE (docs/connect.md §4.5 bis). Une base de dev compte ses numéros depuis 1, comme la
# prod : un rack de dev peut avoir gravé le golem_1 de la base de DEV alors qu'en prod golem_1 est un autre
# rack. Un numéro « à vie » ne vient donc que de l'origine qui en tient le registre ; tout autre serveur rend
# un numéro PROVISOIRE, gardé à part et réécrivable.
PROD_HOSTS = ("golem.fm", "www.golem.fm")


def is_prod(base):
    from urllib.parse import urlparse
    try:
        u = urlparse(str(base or ""))
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in PROD_HOSTS


def _base():
    try:
        from .golemfm import _cfg
        return _cfg()[0]
    except Exception:
        return ""


def _conflict_path():
    return os.path.join(C.CONFIG_DIR, "serial.conflict.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip().strip("\0")
    except OSError:
        return ""


# ── la fiche machine ────────────────────────────────────────────────────────────────────────────
def machine():
    """{arch, cpu, cores, ram_mb, disk_gb, hostname, board} — sondes gratuites (/proc, /sys, DMI). Une
    sonde qui manque laisse son champ à None ; golem.fm filtre par nature et ignore le reste."""
    out = {"arch": platform.machine() or None, "cpu": None, "cores": os.cpu_count(),
           "ram_mb": None, "disk_gb": None, "hostname": None, "board": None}
    m = re.search(r"^model name\s*:\s*(.+)$", _text("/proc/cpuinfo"), re.M)
    if m:
        out["cpu"] = " ".join(m.group(1).split())
    m = re.search(r"^MemTotal:\s*(\d+)", _text("/proc/meminfo"), re.M)
    if m:
        out["ram_mb"] = round(int(m.group(1)) / 1024)
    try:
        out["disk_gb"] = round(shutil.disk_usage(C.CONFIG_DIR if os.path.isdir(C.CONFIG_DIR) else "/").total / 1e9)
    except OSError:
        pass
    try:
        out["hostname"] = socket.gethostname() or None
    except OSError:
        pass
    # x86 : la carte mère par DMI ; ARM (Raspberry Pi…) : le modèle du device-tree
    vendor, name = _text("/sys/devices/virtual/dmi/id/board_vendor"), _text("/sys/devices/virtual/dmi/id/board_name")
    board = " ".join(x for x in (vendor, name) if x) or _text("/proc/device-tree/model")
    out["board"] = board or None
    if sys.platform == "win32":
        out.update({k: v for k, v in _machine_windows().items() if v})
    return out


def _machine_windows():
    """Windows (2026-10-05) : /proc et DMI n'existent pas — cpu, ram_mb et board partaient à null. Le
    registre les donne sans droits d'administrateur, la RAM vient de GlobalMemoryStatusEx."""
    out = {"cpu": None, "ram_mb": None, "board": None}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
            out["cpu"] = " ".join(str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).split()) or None
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
            parts = []
            for v in ("BaseBoardManufacturer", "BaseBoardProduct"):
                try:
                    parts.append(str(winreg.QueryValueEx(k, v)[0]).strip())
                except OSError:
                    pass
            out["board"] = " ".join(x for x in parts if x) or None
    except OSError:
        pass
    try:
        import ctypes

        class _Mem(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = _Mem()
        m.dwLength = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            out["ram_mb"] = round(m.ullTotalPhys / 1048576)
    except Exception:
        pass
    return out


# ── le numéro ───────────────────────────────────────────────────────────────────────────────────
def read():
    """Le numéro gardé : {number, name, issued_at, recorded_at} ou None."""
    d = _read(_path())
    return d if d and _valid(d) else None


def conflict():
    return _read(_conflict_path())


def _valid(s):
    return (isinstance(s, dict) and isinstance(s.get("number"), int) and not isinstance(s.get("number"), bool)
            and s["number"] > 0 and isinstance(s.get("name"), str) and bool(_NAME.match(s["name"])))


def provisional():
    return _read(_provisional_path())


def record(serial, base=None):
    """Ce que golem.fm rend (`serial` de pair/poll ou du battement) : None tant qu'aucun numéro n'est
    attribué, sinon {number, name, issued_at, machine}. Rend {"status", "serial"} :
    `none` (rien reçu) · `written` (première fois) · `kept` (le même) · `conflict` (un AUTRE numéro pour
    cette machine : le fichier ne bouge pas, l'anomalie est gardée à côté) · `invalid` (mal formé) ·
    `provisional` (le serveur n'est pas la prod : rien n'est gravé, le numéro est gardé à part).
    `base` = le serveur qui a répondu (défaut : celui de l'appairage)."""
    cur = read()
    if serial is None:
        return {"status": "none", "serial": cur}
    if not _valid(serial):
        log.warning(f"serial ignoré, mal formé : {serial!r}")
        return {"status": "invalid", "serial": cur}
    got = {"number": serial["number"], "name": serial["name"], "issued_at": serial.get("issued_at")}
    base = _base() if base is None else base
    if not is_prod(base):
        # un numéro d'une base de dev n'est pas un numéro à vie : réécrit à chaque fois, jamais gravé,
        # jamais un « conflit » avec celui de la prod
        from urllib.parse import urlparse
        prov = {**got, "server": urlparse(str(base or "")).netloc or None,
                "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if (provisional() or {}).get("name") != got["name"] or (provisional() or {}).get("server") != prov["server"]:
            _write(_provisional_path(), prov, 0o644)
        return {"status": "provisional", "serial": cur, "provisional": prov}
    if cur is not None:
        if cur["number"] == got["number"] and cur["name"] == got["name"]:
            return {"status": "kept", "serial": cur}
        # UNE MACHINE, DEUX NUMÉROS : on ne tranche pas ici. Le premier reste, l'autre est montré.
        log.error(f"numéro à vie en conflit : le rack porte {cur['name']}, golem.fm rend {got['name']}")
        _write(_conflict_path(), {"kept": cur, "received": got, "at": time.strftime("%Y-%m-%d %H:%M:%S")}, 0o644)
        return {"status": "conflict", "serial": cur, "received": got}
    got["recorded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    got["server"] = "golem.fm"                        # d'où il vient — relu si une plaque est contestée
    _write(_path(), got, 0o444)
    with __import__("contextlib").suppress(OSError):   # le provisoire a fini son office
        os.remove(_provisional_path())
    log.info(f"numéro à vie reçu : {got['name']}")
    return {"status": "written", "serial": got}


def _write(path, data, mode):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def plate():
    """Ce que l'écran montre (System, la plaque) : le numéro, et l'anomalie s'il y en a une."""
    s, c = read(), conflict()
    if not s:
        # pas encore de numéro à vie : le provisoire d'un serveur de dev se montre, marqué comme tel
        p = provisional()
        if p and _valid(p):
            return {"name": p["name"], "number": p["number"], "issued_at": p.get("issued_at"),
                    "conflict": None, "provisional": True, "server": p.get("server")}
    return {"name": s["name"] if s else None, "number": s["number"] if s else None,
            "issued_at": s.get("issued_at") if s else None,
            "conflict": c["received"]["name"] if c and isinstance(c.get("received"), dict) else None,
            "provisional": False}


def fetch():
    """Relire son numéro chez golem.fm (`GET /api/ext/serial`, Bearer) — fichier perdu, vérification.
    Rend le résultat de `record` ; `absent` = 404 (aucun numéro attribué encore), `error` sinon."""
    from .golemfm import _cfg, _req
    base, token = _cfg()
    if not base or not token:
        return {"status": "error", "error": "not paired", "serial": read()}
    st, data = _req("/api/ext/serial", token=token, base=base, method="GET")
    if st == 404:
        return {"status": "absent", "serial": read()}
    if st != 200 or not isinstance(data, dict):
        return {"status": "error", "error": f"{st}: {data}", "serial": read()}
    return record(data, base=base)                   # le corps EST le document (même objet que `serial` du poll)
