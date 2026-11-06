# SPDX-License-Identifier: GPL-3.0-or-later
"""LA MISE À JOUR PAR ARCHIVE (docs/update.md §3, 2026-11-06) — pour une install SANS git : Windows et macOS (le bootstrap
y télécharge toujours l'archive et l'installateur copie sans .git), ou un Linux d'avant la v0.6.1 installé sans git.

Le bouton « Update to … » de Settings ▸ About y refait ce que fait l'installateur :
  1. GitHub dit la dernière release et ses notes (`releases/latest`, la requête du bootstrap) — seulement quand on
     clique « Check for releases » ; la réponse est gardée (presets/.release-check.json) pour la pastille d'About ;
  2. le zip du tag est téléchargé et extrait dans le cache ;
  3. le code est copié par-dessus l'install par la fonction de l'installateur (installer/desktop_steps.step_source) :
     presets, réglages, prises… ne sont jamais écrasés ;
  4. les fichiers que la nouvelle version n'a plus sont supprimés (manifeste de la version d'avant, .golem-files) ;
  5. la version est notée (.golem-release) ; si bridge/requirements.lock a changé, pip est relancé — après l'arrêt du
     bridge sous Windows et macOS (un module chargé ne se remplace pas sous Windows : drapeau .golem-pip-pending, lu
     par provision/desktop.py restart), tout de suite sous Linux.
L'appelant redémarre ensuite (routes_system.system_update_apply). Linux garde git quand il l'a (docs/update.md §1).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from . import config as C
from .golog import get

log = get("update")

REPO = os.environ.get("GOLEM_REPO", "https://github.com/Goldoralf/golem").removesuffix(".git").rstrip("/")
RELEASE_FILE = ".golem-release"          # {"tag": "v0.6.2", "at": "…"} — la version installée (installer/desktop_steps)
MANIFEST_FILE = ".golem-files"           # la liste des fichiers de code posés par cette version
PIP_FLAG = ".golem-pip-pending"          # bridge/requirements.lock a changé : pip à relancer au redémarrage
CHECK_FILE = os.path.join("presets", ".release-check.json")
LOCK = os.path.join("bridge", "requirements.lock")
UA = {"User-Agent": "golem-rack", "Accept": "application/vnd.github+json"}


def _p(*parts):
    return os.path.join(C.ROOT, *parts)


def _api():
    return "https://api.github.com/repos/" + REPO.split("github.com/", 1)[-1]


def vkey(tag):
    """« v0.6.10 » → (0, 6, 10) ; ce qui n'est pas une version → () (passe avant tout le reste)."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", str(tag or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def installed():
    """Le tag installé, ou None (une install d'avant ce fichier : version inconnue)."""
    try:
        with open(_p(RELEASE_FILE), encoding="utf-8") as f:
            return (json.load(f) or {}).get("tag")
    except (OSError, ValueError):
        return None


def write_installed(root, tag, files):
    from installer.desktop_steps import write_release_marker
    write_release_marker(root, tag, files)


def code_files(src):
    from installer.desktop_steps import code_files as cf
    return cf(src)


def check(fetch=False):
    """{latest, notes, fetch_error} — de GitHub si `fetch`, sinon la dernière réponse gardée."""
    cached = {}
    try:
        with open(_p(CHECK_FILE), encoding="utf-8") as f:
            cached = json.load(f) or {}
    except (OSError, ValueError):
        pass
    if not fetch:
        return {"latest": cached.get("latest"), "notes": cached.get("notes") or "", "fetch_error": None}
    try:
        req = urllib.request.Request(_api() + "/releases/latest", headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        res = {"latest": d.get("tag_name"), "notes": (d.get("body") or "").strip()[:4000],
               "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        os.makedirs(os.path.dirname(_p(CHECK_FILE)), exist_ok=True)
        with open(_p(CHECK_FILE), "w", encoding="utf-8") as f:
            json.dump(res, f)
        return {"latest": res["latest"], "notes": res["notes"], "fetch_error": None}
    except Exception as e:                                  # hors ligne, GitHub muet : on le dit, la page reste
        return {"latest": cached.get("latest"), "notes": cached.get("notes") or "",
                "fetch_error": f"cannot reach GitHub ({e.__class__.__name__})"}


def status(fetch=False):
    """La réponse de GET /api/system/update pour une install sans git (mêmes clés que la voie git)."""
    cur = installed()
    c = check(fetch)
    latest = c["latest"]
    if not latest:
        st = "no-release"
    elif cur and vkey(cur) >= vkey(latest):
        st = "up-to-date"
    else:
        st = "update-available"                              # version inconnue : la poser ne coûte rien
    return {"current": cur or "unknown", "branch": None, "clean": True, "changes": [],
            "full_restart": sys.platform in ("win32", "darwin"), "latest": latest, "status": st, "log": [],
            "notes": c["notes"] if st == "update-available" else "", "fetch_error": c["fetch_error"],
            "signed": None, "mode": "archive"}


class _Ctx:
    """Le contexte que la fonction de l'installateur attend : un journal, pas de mode « dry »."""
    S = {"dry": False}

    def log(self, line, step=None):
        log.info(line)


def _sha(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def download(tag, dest_dir):
    """Le zip du tag (la même adresse que provision/bootstrap.ps1), extrait : rend le dossier de la version."""
    url = f"{REPO}/archive/refs/tags/{tag}.zip"
    zpath = os.path.join(dest_dir, f"golem-{tag}.zip")
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=120) as r, open(zpath, "wb") as f:
        shutil.copyfileobj(r, f)
    out = os.path.join(dest_dir, "x")
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():                              # jamais hors du dossier d'extraction
            if m.startswith("/") or ".." in m.replace("\\", "/").split("/"):
                raise ValueError(f"unsafe path in the archive: {m}")
        z.extractall(out)
    inner = [os.path.join(out, d) for d in os.listdir(out) if os.path.isdir(os.path.join(out, d))]
    if len(inner) != 1 or not all(os.path.isdir(os.path.join(inner[0], d)) for d in ("bridge", "provision")):
        raise ValueError("the downloaded archive is not a golem release")
    return inner[0]


def apply(tag, fetch_src=None):
    """Pose la release `tag` par-dessus cette install. Rend {"ok", "pip", "removed"} ou lève (le message va à l'écran).
    `fetch_src(tag, dir)` remplace le téléchargement (les tests)."""
    from installer import desktop_steps
    if not vkey(tag):
        raise ValueError(f"not a release tag: {tag}")
    old_lock = _sha(_p(LOCK))
    try:
        with open(_p(MANIFEST_FILE), encoding="utf-8") as f:
            old_files = set(json.load(f) or [])
    except (OSError, ValueError):
        old_files = set()                                    # une install d'avant le manifeste : rien à retirer
    work = tempfile.mkdtemp(prefix="golem-update-")
    try:
        src = (fetch_src or download)(tag, work)
        new_files = code_files(src)
        if desktop_steps.step_source(_Ctx(), src, C.ROOT) != 0:
            raise RuntimeError("copying the new version failed")
        # ce que la nouvelle version n'a plus — jamais l'état local (presets, réglages, prises…)
        removed = 0
        for rel in sorted(old_files - set(new_files)):
            if rel.split("/")[0] in desktop_steps.LOCAL_STATE:
                continue
            with __import__("contextlib").suppress(OSError):
                os.remove(_p(*rel.split("/")))
                removed += 1
        write_installed(C.ROOT, tag, new_files)
        pip = old_lock is not None and _sha(_p(LOCK)) != old_lock
        if pip:
            if sys.platform in ("win32", "darwin"):
                open(_p(PIP_FLAG), "w").close()              # au redémarrage, bridge arrêté (provision/desktop.py)
            else:
                py = os.path.join(C.ROOT, ".venv", "bin", "python")
                subprocess.run([py, "-m", "pip", "install", "--require-hashes", "-r", _p(LOCK)], check=True,
                               capture_output=True, timeout=900)
        log.info(f"release {tag} posée par archive : {len(new_files)} fichiers, {removed} retirés, pip={pip}")
        return {"ok": True, "pip": pip, "removed": removed}
    finally:
        shutil.rmtree(work, ignore_errors=True)
