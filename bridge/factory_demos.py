# SPDX-License-Identifier: GPL-3.0-or-later
"""LES DÉMOS D'USINE, TÉLÉCHARGÉES PLUTÔT QUE RENDUES (docs/preset-preview.md §10, 2026-11-15).

Les démos d'usine (patchs, lanes des presets, blocs, sons claviers, kits) sont rendues une fois sur le rack du
mainteneur et publiées en asset de release (tools/pack-factory-demos.py -> golem-binaries `factory-demos-vN`). Au
démarrage, un golem lit l'index publié (quelques Ko) et, s'il lui MANQUE des démos, télécharge l'archive et ne pose
que les fichiers absents : une démo déjà là (rendue ici, peut-être plus récente) n'est jamais écrasée ; une démo
périmée se refait par le lot habituel. Sans réseau : rien, en silence — le lot des démos d'usine reste là.

GOLEM_FACTORY_DEMOS=0 le coupe (la suite de tests) ; GOLEM_FACTORY_DEMOS_BASE change la source."""
import hashlib
import json
import os
import tarfile
import threading
import urllib.request

from . import config as C
from .golog import get

log = get("factory-demos")

TAG = "factory-demos-v1"
NAME = "golem-factory-demos"
BASE = os.environ.get("GOLEM_FACTORY_DEMOS_BASE") or f"https://github.com/Goldoralf/golem-binaries/releases/download/{TAG}/"
STATE = os.path.join(C.PREVIEWS_DIR, ".factory-demos.json")
_ST = {"state": "idle", "added": 0, "error": None}


def status():
    return dict(_ST, tag=TAG)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "golem-rack"})
    return urllib.request.urlopen(req, timeout=timeout)


def missing(index):
    """Les fichiers de l'index absents ici : {dossier: [fichiers]}."""
    out = {}
    for d, files in (index.get("items") or {}).items():
        if d.startswith("/") or ".." in d.split("/") or "\\" in d:       # un dossier relatif, jamais au-dessus
            continue
        want = [f for f in files if "/" not in f and ".." not in f
                and not os.path.isfile(os.path.join(C.PREVIEWS_DIR, *d.split("/"), f))]
        if want:
            out[d] = want
    return out


def fetch():
    """Télécharge et complète. Ne lève jamais : l'état dit ce qui s'est passé."""
    try:
        _ST.update(state="index", error=None)
        index = json.loads(_get(BASE + NAME + ".json").read())
        need = missing(index)
        if not need:
            _ST.update(state="done", added=0)
            _save(index)
            return
        _ST.update(state="download")
        os.makedirs(C.PREVIEWS_DIR, exist_ok=True)
        tmp = os.path.join(C.PREVIEWS_DIR, ".factory-demos.tar.part")
        h = hashlib.sha256()
        with _get(BASE + NAME + ".tar", timeout=120) as r, open(tmp, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != index.get("sha256"):
            os.remove(tmp)
            raise ValueError("the archive does not match its index (sha256)")
        added = 0
        with tarfile.open(tmp) as tf:
            for m in tf.getmembers():
                d, _, f = m.name.rpartition("/")
                if not m.isfile() or f not in need.get(d, []):        # seulement ce que l'index nomme et qui manque
                    continue
                dst = os.path.join(C.PREVIEWS_DIR, *d.split("/"), f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                data = tf.extractfile(m).read()
                if hashlib.sha256(data).hexdigest() != index["items"][d][f]:
                    continue
                with open(dst + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(dst + ".tmp", dst)
                added += 1
        os.remove(tmp)
        _save(index)
        _ST.update(state="done", added=added)
        log.info(f"démos d'usine : {added} fichier(s) posé(s) depuis {TAG}")
    except Exception as e:                                   # pas de réseau, pas encore publié : le lot local reste
        _ST.update(state="error", error=str(e))
        log.info(f"démos d'usine : pas de téléchargement ({e})")


def _save(index):
    try:
        os.makedirs(C.PREVIEWS_DIR, exist_ok=True)
        json.dump({"tag": TAG, "sha256": index.get("sha256"), "generated": index.get("generated")}, open(STATE, "w"))
    except OSError:
        pass


def start():
    """Au démarrage du bridge, une fois, en tâche de fond."""
    if os.environ.get("GOLEM_FACTORY_DEMOS", "1") == "0":
        return
    threading.Thread(target=fetch, daemon=True, name="factory-demos").start()
