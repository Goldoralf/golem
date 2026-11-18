# SPDX-License-Identifier: GPL-3.0-or-later
"""System ▸ System ▸ CPU cores (maquette mockups/cpu-cores.html, validée par le mainteneur le 2026-11-18) : ce que
chaque cœur fait PENDANT que ça joue, et la part du son de golem dedans — des mesures, pas l'estimation.

Trois lectures, toutes dans /proc (Linux) ; ailleurs la page dit qu'elle n'a rien à mesurer :
  · la charge de chaque cœur : /proc/stat, différence entre deux lectures ;
  · la part du moteur audio : le temps CPU de chacun de ses fils (/proc/<pid>/task/<tid>/stat), rangé sur le cœur où
    le fil se trouvait à la lecture. Le système DÉPLACE les fils d'un cœur à l'autre : c'est une bonne image sur
    quelques secondes, pas une affectation ;
  · le coût de chaque lane : les compteurs des plugins du Golem Engine (commande `dspstats`), en % d'un cycle audio.
    REAPER ne les donne pas : la page montre alors les cœurs seuls.
ON NE SAIT PAS « quelle lane tourne sur quel cœur » : le moteur distribue ses pistes sur ses fils à chaque cycle. La
page ne le prétend pas.

Pur et testable : `diff_cores`, `engine_share`, `lane_costs` prennent des lectures en argument ; `snapshot()` les fait."""
import contextlib
import json
import os
import sys
import threading
import time

from . import config as C

_lock = threading.Lock()
_PREV = {"t": None, "stat": None, "threads": None, "pid": None}
HZ = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100


def read_stat(text=None):
    """{n: (busy, total)} en jiffies, par cœur, depuis /proc/stat."""
    if text is None:
        with open("/proc/stat", encoding="ascii") as f:
            text = f.read()
    out = {}
    for line in text.splitlines():
        p = line.split()
        if not p or not p[0].startswith("cpu") or p[0] == "cpu":
            continue
        v = [int(x) for x in p[1:9]]
        idle = v[3] + v[4]                                    # idle + iowait
        out[int(p[0][3:])] = (sum(v) - idle, sum(v))
    return out


def diff_cores(a, b):
    """{n: % d'occupation} entre deux lectures de read_stat."""
    out = {}
    for n, (busy, total) in b.items():
        if n in a and total > a[n][1]:
            out[n] = max(0.0, min(100.0, 100.0 * (busy - a[n][0]) / (total - a[n][1])))
    return out


def read_threads(pid, root="/proc"):
    """{tid: (jiffies CPU, cœur courant)} des fils du process `pid` ; {} s'il n'existe pas."""
    out = {}
    base = os.path.join(root, str(pid), "task")
    try:
        tids = os.listdir(base)
    except OSError:
        return out
    for tid in tids:
        try:
            with open(os.path.join(base, tid, "stat"), encoding="ascii", errors="replace") as f:
                rest = f.read().rsplit(")", 1)[1].split()
            out[int(tid)] = (int(rest[11]) + int(rest[12]), int(rest[36]))     # utime + stime ; processor
        except (OSError, ValueError, IndexError):
            continue
    return out


def engine_share(a, b, dt, hz=HZ):
    """{cœur: % d'un cœur} pris par le moteur entre deux lectures de read_threads, rangé sur le cœur COURANT du fil."""
    out = {}
    if not dt or dt <= 0:
        return out
    for tid, (j, cpu) in b.items():
        d = j - (a.get(tid) or (j, cpu))[0]
        if d > 0:
            out[cpu] = out.get(cpu, 0.0) + 100.0 * d / hz / dt
    return {k: min(100.0, v) for k, v in out.items()}


def core_kinds(root="/sys/devices"):
    """{n: "P" | "E"} sur un processeur hybride (Intel : cpu_core / cpu_atom), {} ailleurs."""
    out = {}
    for kind, d in (("P", "cpu_core"), ("E", "cpu_atom")):
        try:
            with open(os.path.join(root, d, "cpus"), encoding="ascii") as f:
                spec = f.read().strip()
        except OSError:
            continue
        for part in spec.split(","):
            if not part:
                continue
            lo, _, hi = part.partition("-")
            for n in range(int(lo), int(hi or lo) + 1):
                out[n] = kind
    return out


def cpu_model():
    with contextlib.suppress(OSError):
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    return None


def lane_costs(stats, cycle_us):
    """Le coût de chaque lane en % d'un cycle, depuis la réponse `dspstats` du Golem Engine : les routes « GoleM:<lane>… »
    regroupées par lane (racine, branches « /lane-x », fusion « #merge »), le reste sous `services`. La charge d'une lane
    est son CHEMIN : la racine et la fusion en série, la plus lourde des branches (elles tournent en parallèle)."""
    lanes, services = {}, 0.0
    for r in (stats or {}).get("routes") or []:
        us = sum(float(p.get("avg") or 0) for p in r.get("procs") or [] if isinstance(p, dict))
        name = str(r.get("name") or "")
        if not name.startswith("GoleM:"):
            services += us
            continue
        rest = name[len("GoleM:"):]
        lane = rest.split("/", 1)[0].split("#", 1)[0]
        L = lanes.setdefault(lane, {"serial": 0.0, "branches": []})
        if "/" in rest:
            L["branches"].append(us)
        else:
            L["serial"] += us
    out = []
    for lane, L in lanes.items():
        us = L["serial"] + (max(L["branches"]) if L["branches"] else 0.0)
        out.append({"id": lane, "us": round(us, 1), "pct": round(100.0 * us / cycle_us, 1) if cycle_us else None,
                    "branches": len(L["branches"])})
    out.sort(key=lambda x: -x["us"])
    return out, (round(100.0 * services / cycle_us, 1) if cycle_us else None)


def _engine_stats(timeout=2.5):
    """Les compteurs des plugins, remis à zéro à chaque lecture : la moyenne DEPUIS la lecture d'avant. None sous REAPER
    ou si le moteur ne répond pas."""
    from . import engine
    eng = engine.get()
    if eng.id in ("reaper", "none", "fake"):
        return None
    from . import silence
    txt = silence._probe({"action": "dspstats", "clear": True}, os.path.join(C.PRESETS_DIR, ".engine-dspstats.json"), timeout=timeout)
    try:
        return json.loads(txt) if txt else None
    except ValueError:
        return None


def snapshot(now=None, with_lanes=True):
    """Ce que la page lit. La première lecture n'a pas de différence à faire : `warming: true`, la suivante mesure."""
    if not os.path.isdir("/proc") or sys.platform != "linux":
        return {"available": False, "why": "golem cannot measure the cores on this system yet"}
    from . import engine
    from .state import state
    now = now or time.time()
    eng = engine.get()
    pid = None
    with contextlib.suppress(Exception):
        pid = eng.pid() if hasattr(eng, "pid") else None
    if pid is None and eng.id == "reaper":
        with contextlib.suppress(Exception):
            from .routes_system import _reaper_proc
            pid = (_reaper_proc() or {}).get("pid")
    stat = read_stat()
    threads = read_threads(pid) if pid else {}
    with _lock:
        prev = dict(_PREV)
        _PREV.update(t=now, stat=stat, threads=threads, pid=pid)
    kinds = core_kinds()
    doc = {"available": True, "cpu": cpu_model(), "engine": {"id": eng.id, "pid": pid},
           "cores": [{"n": n, "kind": kinds.get(n)} for n in sorted(stat)], "warming": True}
    if prev["t"] and prev["stat"] and 0.3 < now - prev["t"] < 30:
        dt = now - prev["t"]
        use = diff_cores(prev["stat"], stat)
        share = engine_share(prev["threads"] or {}, threads, dt) if prev["pid"] == pid else {}
        for c in doc["cores"]:
            c["pct"] = round(use.get(c["n"], 0.0), 1)
            c["engine_pct"] = round(min(share.get(c["n"], 0.0), c["pct"]), 1)
        busiest = max(doc["cores"], key=lambda c: c["pct"])
        doc.update(warming=False, window_s=round(dt, 1), busiest={"n": busiest["n"], "pct": busiest["pct"]},
                   engine_total=round(sum(share.values()), 1))
    audio = {}
    with contextlib.suppress(Exception):
        audio = eng.audio() or {}
    m = getattr(state, "audio_metrics", None) or {}
    bsize = audio.get("buffer") or m.get("buffer_size")
    rate = audio.get("rate") or m.get("sample_rate") or 48000
    cycle_us = (float(bsize) / float(rate) * 1e6) if bsize and rate else None
    doc["audio"] = {"buffer": bsize, "rate": rate, "cycle_ms": round(cycle_us / 1000.0, 1) if cycle_us else None,
                    "dsp_load": audio.get("dsp_load"), "xruns": getattr(state, "xruns", None)}
    doc["playing"] = {"preset": getattr(state, "preset_id", None), "name": getattr(state, "preset_name", None),
                      "scene": getattr(state, "scene_id", None)}
    if with_lanes:
        stats = _engine_stats()
        if stats is not None and cycle_us:
            lanes, services = lane_costs(stats, cycle_us)
            doc["lanes"], doc["services_pct"] = lanes, services
        else:
            doc["lanes"] = None                               # ce moteur ne dit pas ce que coûte chaque lane
    return doc
