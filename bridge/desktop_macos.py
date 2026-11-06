# SPDX-License-Identifier: GPL-3.0-or-later
"""Les sondes système sous macOS : le pendant de /proc et /sys du rack, et de ctypes/tasklist de Windows.

Né de l'état des lieux du 2026-10-04 (docs/platforms.md, lot M1) : sous macOS chaque sonde du
Dashboard retombait sur son chemin LINUX — `/proc/stat`, `/proc/meminfo`, `pgrep -x reaper` puis
`/proc/<pid>` — et rendait vide. Pire que vide pour REAPER : le process s'appelle « REAPER » sur un Mac,
le Dashboard aurait affiché « not running » devant un moteur qui joue.

Zéro dépendance (pas de psutil, comme rigstatus) : `sysctl`, `vm_stat`, `ps`, et `host_statistics` de
Mach par ctypes pour le CPU. Le PARSING est séparé des appels : il se teste partout, les appels ne se
prouvent que sur un Mac (la CI macos-26, puis la recette du mainteneur). Tout est tolérant : None, jamais
d'exception.
"""
import re
import subprocess
import time

_C_ENV = {"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}


def _run(args, timeout=3):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=_C_ENV)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


# ── mémoire ─────────────────────────────────────────────────────────────────────────────────────────
def parse_vm_stat(text):
    """{taille de page, compteurs en pages} depuis `vm_stat`. La 1re ligne porte la taille de page
    (« page size of 16384 bytes » sur Apple Silicon, 4096 sur Intel) : jamais la supposer."""
    m = re.search(r"page size of (\d+) bytes", text or "")
    if not m:
        return None
    pages = {k.strip().lower(): int(v) for k, v in re.findall(r'^"?([A-Za-z][^:"]*)"?:\s+(\d+)\.?\s*$',
                                                               text, re.M)}
    return {"page_size": int(m.group(1)), "pages": pages}


def ram_from(total_bytes, vm):
    """{total_mb, used_pct}. « Disponible » = libre + inactive + spéculative + purgeable : ce que macOS
    rend sans paginer — le même sens que MemAvailable de Linux, pas la « mémoire libre » (toujours
    proche de zéro sur un Mac, qui remplit sa RAM de cache)."""
    if not total_bytes or not vm:
        return None
    p = vm["pages"]
    avail = sum(p.get(k, 0) for k in ("pages free", "pages inactive", "pages speculative",
                                      "pages purgeable")) * vm["page_size"]
    avail = min(avail, total_bytes)
    return {"total_mb": round(total_bytes / 1048576), "used_pct": round(100 * (total_bytes - avail) / total_bytes)}


def ram():
    total = (_run(["sysctl", "-n", "hw.memsize"]) or "").strip()
    if not total.isdigit():
        return None
    return ram_from(int(total), parse_vm_stat(_run(["vm_stat"])))


# ── CPU ─────────────────────────────────────────────────────────────────────────────────────────────
def cpu_ticks():
    """(idle, total) en ticks depuis le démarrage, tous cœurs — host_statistics(HOST_CPU_LOAD_INFO)."""
    try:
        import ctypes
        lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
        lib.mach_host_self.restype = ctypes.c_uint
        ticks = (ctypes.c_uint * 4)()                     # user, system, idle, nice
        count = ctypes.c_uint(4)                          # HOST_CPU_LOAD_INFO_COUNT
        if lib.host_statistics(lib.mach_host_self(), 3, ticks, ctypes.byref(count)) != 0:
            return None
        return ticks[2], sum(ticks)
    except Exception:
        return None


def cpu_pct(interval=0.25):
    first = cpu_ticks()
    if first is None:
        return None
    time.sleep(interval)
    second = cpu_ticks()
    if second is None:
        return None
    idle, total = second[0] - first[0], second[1] - first[1]
    return round(100 * (total - idle) / total, 1) if total > 0 else None


# ── un process (REAPER) ─────────────────────────────────────────────────────────────────────────────
def parse_etime(s):
    """Durée écoulée de `ps -o etime` → secondes : « [[jj-]hh:]mm:ss »."""
    s = (s or "").strip()
    m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", s)
    if not m:
        return None
    d, h, mi, se = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + se


def parse_ps(line):
    """`ps -o rss=,etime= -p PID` → {rss_mb, uptime_s} (rss en Kio)."""
    parts = (line or "").split()
    if len(parts) < 2 or not parts[0].isdigit():
        return None
    return {"rss_mb": round(int(parts[0]) * 1024 / 1e6), "uptime_s": parse_etime(parts[1])}


def process_info(pid):
    return parse_ps(_run(["ps", "-o", "rss=,etime=", "-p", str(int(pid))]))


def process_started(pid):
    """Heure de démarrage (epoch, à la seconde) d'un process. Lève si illisible — comme le chemin Linux
    (/proc) : l'appelant (recall.rig_is_live) a son repli. À la seconde : la livemap qu'on compare a été
    écrite par CE REAPER bien après son démarrage (scripts, scan, build), l'écart se compte en secondes."""
    info = process_info(pid)
    if not info or info["uptime_s"] is None:
        raise OSError(f"ps -p {pid}: start time unreadable")
    return time.time() - info["uptime_s"]


# ── pare-feu applicatif (M4) ────────────────────────────────────────────────────────────────────────
_SOCKETFILTER = "/usr/libexec/ApplicationFirewall/socketfilterfw"


def parse_firewall(global_state, app_state=None):
    """GoleM est-il joignable malgré le pare-feu de macOS ? True (pare-feu éteint, ou Python autorisé),
    False (Python explicitement bloqué), None (pare-feu allumé, Python jamais vu : macOS posera la
    question « accepter les connexions entrantes ? » à la première tablette — l'écran le dit)."""
    g = (global_state or "").lower()
    if "disabled" in g or "state = 0" in g:
        return True
    if "enabled" not in g and "state = 1" not in g and "state = 2" not in g:
        return None
    a = (app_state or "").lower()
    if "is blocked" in a:
        return False
    if "permitted" in a or "not blocked" in a:
        return True
    return None


def firewall_open():
    """Lecture seule, sans droits (`--getglobalstate`, `--getappblocked`) ; None si illisible."""
    import os
    import sys
    g = _run([_SOCKETFILTER, "--getglobalstate"])
    if g is None:
        return None
    a = _run([_SOCKETFILTER, "--getappblocked", os.path.realpath(sys.executable)])
    return parse_firewall(g, a)
