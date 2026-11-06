# SPDX-License-Identifier: GPL-3.0-or-later
"""Enregistrer un fichier dans les TÉLÉCHARGEMENTS de la machine, sans passer par le navigateur (2026-10-12).

La fenêtre `golem desktop` est un Chrome en mode application : un téléchargement y fait surgir la bulle de
téléchargements de Chrome, HORS de l'interface golem. Quand l'écran est la machine elle-même (client local), le bridge
écrit donc le fichier lui-même et l'app dit où il est. Depuis une tablette ou un téléphone, le téléchargement du
navigateur reste le bon geste : le fichier doit arriver sur CET appareil-là."""
import os
import re
import shutil
import subprocess
import sys


def downloads_dir():
    """Le dossier Téléchargements de l'utilisateur (XDG sous Linux, profil sous Windows, ~/Downloads sous macOS)."""
    d = None
    if sys.platform.startswith("linux"):
        try:
            r = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=3)
            cand = (r.stdout or "").strip()
            if r.returncode == 0 and cand and os.path.abspath(cand) != os.path.expanduser("~"):
                d = cand
        except (OSError, subprocess.SubprocessError):
            d = None
    elif os.name == "nt":
        d = os.path.join(os.environ.get("USERPROFILE") or os.path.expanduser("~"), "Downloads")
    d = d or os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(d, exist_ok=True)
    return d


def _safe(name):
    base = os.path.basename(str(name or "")).strip() or "golem-file"
    base = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", "-", base)[:120]
    return base.lstrip(".") or "golem-file"


def _unique(folder, name):
    stem, ext = os.path.splitext(name)
    path, k = os.path.join(folder, name), 2
    while os.path.exists(path):
        path = os.path.join(folder, "%s (%d)%s" % (stem, k, ext))
        k += 1
    return path


def save_bytes(name, data):
    """Écrit `data` sous `name` (jamais écrasé : « nom (2) »). Rend {path, name, folder}."""
    folder = downloads_dir()
    path = _unique(folder, _safe(name))
    with open(path, "wb") as f:
        f.write(data)
    return {"path": path, "name": os.path.basename(path), "folder": folder}


def save_copy(src, name=None):
    """Copie un fichier existant (une sauvegarde : jamais relue en mémoire). Rend {path, name, folder}."""
    folder = downloads_dir()
    path = _unique(folder, _safe(name or os.path.basename(src)))
    shutil.copyfile(src, path)
    return {"path": path, "name": os.path.basename(path), "folder": folder}


def save_stream(name, readable, chunk=1 << 20):
    """Écrit un flux (une réponse HTTP du rack lui-même) sans le garder en mémoire : une prise multipiste pèse des
    centaines de Mo. Rend {path, name, folder}."""
    folder = downloads_dir()
    path = _unique(folder, _safe(name))
    try:
        with open(path, "wb") as f:
            shutil.copyfileobj(readable, f, chunk)
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise
    return {"path": path, "name": os.path.basename(path), "folder": folder}


def filename_of(disposition, url):
    """Le nom que le rack donne au fichier (Content-Disposition), sinon le dernier segment de l'adresse."""
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition or "")
    if m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    from urllib.parse import urlsplit, unquote
    return unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]) or "golem-file"
