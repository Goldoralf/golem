# SPDX-License-Identifier: GPL-3.0-or-later
"""Les captures d'usine téléchargées SANS que golem tourne (docs/install-v2.md, lot 4) : l'installation les prend en
arrière-plan pendant qu'elle télécharge les sons, dès que le compte TONE3000 a été connecté sur les premières pages
(ses jetons sont dans .env, posés par l'installateur).

    .venv/bin/python -m bridge.factory_fetch            # télécharge ce qui manque ; suit dans presets/.factory-fetch.json

C'est le MÊME travail que Settings ▸ Content ▸ Factory (bridge/factory.py `_download_worker`, une capture à la fois par
le pipeline « + New »), joué dans ce processus au lieu d'un fil du bridge. Codes de sortie : 0 tout est là (ou rien à
faire) · 2 pas de compte TONE3000 connecté · 1 au moins une capture en échec. Jamais lancé pendant que golem tourne :
le pipeline TONE3000 n'en tient qu'une à la fois, et le bridge a le sien."""
import json
import os
import sys
import threading
import time


def status_path():
    from . import config as C
    return os.path.join(C.PRESETS_DIR, ".factory-fetch.json")


def _write(d):
    p = status_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, p)


def run(tick=1.0):
    from . import factory as F
    from . import routes_t3k as T
    try:
        signed = bool(T._t3k.env_read().get("T3K_ACCESS_TOKEN"))
    except Exception:
        signed = False
    if not signed:
        _write({"phase": "skipped", "why": "no TONE3000 account", "done": 0, "total": 0, "failed": []})
        return 2
    todo = F.captures()["missing"]
    F._DL.update(phase="running", done=0, total=len(todo), current=None, failed=[], installed=[])
    _write({"phase": "running", "done": 0, "total": len(todo), "failed": []})
    if not todo:
        _write({"phase": "done", "done": 0, "total": 0, "failed": []})
        return 0
    th = threading.Thread(target=F._download_worker, args=(todo,), daemon=True)
    th.start()
    while th.is_alive():
        th.join(tick)
        d = F.download_status()
        _write({"phase": "running" if th.is_alive() else "done", "done": d["done"], "total": d["total"],
                "current": d.get("current"), "failed": d["failed"]})
    d = F.download_status()
    _write({"phase": "done", "done": d["done"], "total": d["total"], "failed": d["failed"], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    return 1 if d["failed"] else 0


if __name__ == "__main__":
    sys.exit(run())
