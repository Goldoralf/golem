# SPDX-License-Identifier: GPL-3.0-or-later
"""Verdict de QUALITÉ des packs d'IR — « pack à écho » (2026-09-14, « il faut qu'on puisse le
savoir »). Même lecture que la garde du compile (`compile_rig.ir_late_impulse`) : le fichier, jamais
une déclaration. Résultat par tone du catalogue (gear cab) dans `library/catalog/.ir-quality.json` :
  { "<tone id>": {"files": n, "bad": n, "worst_ms": ms, "worst_db": dB, "at": epoch, "sig": "…"} }
`sig` = taille+mtime des fichiers : un pack inchangé n'est pas relu. Calculé au démarrage (thread
démon) et après chaque installation (tones_jobs). Servi : /api/catalog (`echo` par tone), la
bibliothèque (badge), le tiroir de baffles (badge), le heartbeat (`captures[].echo`) — golem.fm
calcule le même verdict de son côté avec les mêmes seuils.
"""
import json
import os
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("ir-quality")
_lock = threading.Lock()


def _path():
    return os.path.join(C.ROOT, "library", "catalog", ".ir-quality.json")


def load():
    try:
        d = json.load(open(_path(), encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())


def _files_of(tone):
    out = []
    for m in tone.get("models") or []:
        f = m.get("file")
        if f:
            p = os.path.join(C.ROOT, f)
            if os.path.isfile(p) and p.lower().endswith(".wav"):
                out.append(p)
    return out


def _sig(files):
    return "|".join(f"{os.path.getsize(p)}:{int(os.path.getmtime(p))}" for p in files)


def scan(only=None, force=False):
    """Relit les packs d'IR (tous, ou `only` = ids) dont les fichiers ont changé. Rend le verdict complet."""
    from .compile_rig import ir_late_impulse
    from .store import _read_json
    idx = _read_json(C.CATALOG, {}) or {}
    tones = idx.get("tones") or []
    tones = tones.values() if isinstance(tones, dict) else tones
    with _lock:
        cur = load()
        seen, n_read, n_bad = set(), 0, 0
        for t in tones:
            if str(t.get("gear") or "") != "cab":
                continue
            tid = str(t.get("id"))
            if only is not None and tid not in {str(x) for x in only}:
                seen.add(tid); continue
            files = _files_of(t)
            if not files:
                continue
            seen.add(tid)
            sig = _sig(files)
            if not force and cur.get(tid, {}).get("sig") == sig:
                continue
            worst = None; bad = 0
            for p in files:
                try:
                    late = ir_late_impulse(p)
                except Exception as e:
                    _swallowed(e, "ir read"); continue
                n_read += 1
                if late:
                    bad += 1
                    if worst is None or late[1] > worst[1]:
                        worst = late
            cur[tid] = {"files": len(files), "bad": bad, "worst_ms": worst[0] if worst else None,
                        "worst_db": worst[1] if worst else None, "at": int(time.time()), "sig": sig}
            n_bad += 1 if bad else 0
        if only is None:
            cur = {k: v for k, v in cur.items() if k in seen}       # un pack désinstallé sort du verdict
        _save(cur)
    if n_read:
        log.info(f"IR relues : {n_read} fichier(s), {n_bad} pack(s) à écho")
    return cur


def echo_of(tid, table=None):
    """{bad, files, worst_ms, worst_db} si le pack a au moins une IR à écho, sinon None."""
    v = (table if table is not None else load()).get(str(tid))
    if not v or not v.get("bad"):
        return None
    return {"bad": v["bad"], "files": v["files"], "worst_ms": v.get("worst_ms"), "worst_db": v.get("worst_db")}


def scan_async(only=None, force=False):
    t = threading.Thread(target=lambda: scan(only, force), daemon=True, name="ir-quality")
    t.start()
    return t
