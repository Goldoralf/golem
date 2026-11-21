# SPDX-License-Identifier: GPL-3.0-or-later
"""LES DÉMOS D'USINE, TÉLÉCHARGÉES PLUTÔT QUE RENDUES (docs/preset-preview.md §10, 2026-11-15).

Les démos d'usine (patchs, lanes des presets, blocs, sons claviers, kits) sont rendues une fois sur le rack du
mainteneur et publiées en asset de release (tools/pack-factory-demos.py -> golem-binaries `factory-demos-vN`).
QUAND (décision du mainteneur, 2026-11-15) : à l'INSTALLATION (provision/install.sh, installer/desktop_steps) et à la
MISE À JOUR (release_update.apply), pas à chaque démarrage. Le démarrage ne rattrape que ce que ces deux-là n'ont pas
fait (hors ligne ce jour-là, mise à jour par git) : il ne télécharge que si l'état posé ne nomme pas TAG.
On lit l'index publié (quelques Ko) et, s'il MANQUE des démos, on télécharge l'archive et ne pose que les fichiers
absents : une démo déjà là n'est jamais écrasée ; une démo périmée se refait par le lot habituel. Sans réseau : rien.

Ce module n'importe que la bibliothèque standard quand on lui donne le dossier (`fetch(dest)`) : l'installateur le
charge par son chemin, sans le bridge. `python -m bridge.factory_demos [dossier]` le lance à la main.
GOLEM_FACTORY_DEMOS=0 coupe le rattrapage du démarrage (la suite de tests) ; GOLEM_FACTORY_DEMOS_BASE change la source."""
import hashlib
import json
import logging
import os
import sys
import tarfile
import threading
import urllib.request

log = logging.getLogger("golem.factory-demos")

TAG = "factory-demos-v4"   # v4 (2026-11-21) : le lot partagé avec golem.fm (index étendu, basses rendues) ; v3 = 2026-11-16
NAME = "golem-factory-demos"
BASE = os.environ.get("GOLEM_FACTORY_DEMOS_BASE") or f"https://github.com/Goldoralf/golem-binaries/releases/download/{TAG}/"
STATE_NAME = ".factory-demos.json"
_ST = {"state": "idle", "added": 0, "error": None}


def status():
    return dict(_ST, tag=TAG)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "golem-rack"})
    return urllib.request.urlopen(req, timeout=timeout)


def _previews_dir():
    from . import config as C
    return C.PREVIEWS_DIR


def missing(index, root=None):
    """Les fichiers de l'index absents ici : {dossier: [fichiers]}."""
    root = root or _previews_dir()
    out = {}
    for d, files in (index.get("items") or {}).items():
        if d.startswith("/") or ".." in d.split("/") or "\\" in d:       # un dossier relatif, jamais au-dessus
            continue
        want = [f for f in files if "/" not in f and ".." not in f
                and not os.path.isfile(os.path.join(root, *d.split("/"), f))]
        if want:
            out[d] = want
    return out


def fetch(dest=None):
    """Télécharge et complète `dest` (défaut : library/previews du bridge). Ne lève jamais : rend l'état."""
    root = dest or _previews_dir()
    try:
        _ST.update(state="index", error=None)
        index = json.loads(_get(BASE + NAME + ".json").read())
        need = missing(index, root)
        if not need:
            _ST.update(state="done", added=0)
            _save(index, root)
            return status()
        _ST.update(state="download")
        os.makedirs(root, exist_ok=True)
        tmp = os.path.join(root, ".factory-demos.tar.part")
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
                dst = os.path.join(root, *d.split("/"), f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                data = tf.extractfile(m).read()
                if hashlib.sha256(data).hexdigest() != index["items"][d][f]:
                    continue
                with open(dst + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(dst + ".tmp", dst)
                added += 1
        os.remove(tmp)
        _save(index, root)
        _ST.update(state="done", added=added)
        log.info(f"démos d'usine : {added} fichier(s) posé(s) depuis {TAG}")
    except Exception as e:                                   # pas de réseau, pas encore publié : le lot local reste
        _ST.update(state="error", error=str(e))
        log.info(f"démos d'usine : pas de téléchargement ({e})")
    return status()


def _save(index, root):
    try:
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, STATE_NAME), "w") as f:
            json.dump({"tag": TAG, "sha256": index.get("sha256"), "generated": index.get("generated")}, f)
    except OSError:
        pass


def placed_tag(root=None):
    """Le TAG que l'installation ou la dernière mise à jour a posé ici (None : jamais)."""
    try:
        with open(os.path.join(root or _previews_dir(), STATE_NAME)) as f:
            return json.load(f).get("tag")
    except (OSError, ValueError):
        return None


def start():
    """Au démarrage du bridge : le RATTRAPAGE seulement — rien si l'installation ou la mise à jour a déjà posé TAG."""
    if os.environ.get("GOLEM_FACTORY_DEMOS", "1") == "0" or placed_tag() == TAG:
        return
    threading.Thread(target=fetch, daemon=True, name="factory-demos").start()


if __name__ == "__main__":                                   # provision/install.sh, release_update.apply
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    st = fetch(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"factory demos ({TAG}): " + (f"{st['added']} file(s) placed" if st["state"] == "done"
                                        else f"not downloaded ({st['error']})"))
