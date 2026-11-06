# SPDX-License-Identifier: GPL-3.0-or-later
"""Le DOSSIER SURVEILLÉ — tout `.golem` déposé y est installé (plan-song-sharing.md lot 1.4 ;
golem-format.md §2 « Import par dossier surveillé », 2026-10-08).

Comme le dossier « Ajouter automatiquement » d'un lecteur de musique. Le CHOIX du dossier appartient à
l'utilisateur (`config/inbox.json` → `{"dir": "…"}`, local, jamais commité) ; défaut `~/golem-inbox`.
golem ne le relie à aucun logiciel ni réseau (song-sharing.md §2.4) : un fichier qui arrive par là n'est pas
plus fiable qu'un autre, il passe par la MÊME installation que le job `song-install` de golem.fm
(`songs.install_golem` : vérification complète, puis fusion).

Ce que le dossier devient :
  - `<f>.golem` en cours de copie : laissé tranquille tant que sa taille ou sa date bouge (deux relevés
    identiques à ~3 s d'écart) — on n'installe pas un fichier à moitié copié ;
  - installé : rangé dans `.imported/` (JAMAIS effacé : c'est le fichier de l'utilisateur) ;
  - refusé : rangé dans `.refused/`, avec `<f>.why.txt` qui dit pourquoi, en anglais.
Un fichier qui n'est pas un `.golem` (un MP3 déposé…) est ignoré ici — l'envoyer chez golem.fm est le lot 2.
Les derniers événements sont dans `recent()` (GET /api/inbox)."""
import asyncio
import json
import os
import time

from . import config as C
from .golog import get

log = get("inbox")

CFG = os.path.join(C.CONFIG_DIR, "inbox.json")
POLL_S = 3.0
_seen = {}            # chemin -> (taille, mtime_ns) du relevé précédent
_recent = []          # [{at, file, ok, id?, title?, created?, missing?, why?}] — les 20 derniers


def inbox_dir():
    try:
        with open(CFG, encoding="utf8") as fh:
            d = (json.load(fh) or {}).get("dir")
        if isinstance(d, str) and d.strip():
            return os.path.expanduser(d.strip())
    except (OSError, ValueError, AttributeError):
        pass
    return os.path.join(os.path.expanduser("~"), "golem-inbox")


def set_dir(path):
    """Change le dossier surveillé (réglage de l'utilisateur). Rend le chemin retenu."""
    path = os.path.expanduser(str(path or "").strip())
    if not path or not os.path.isabs(path):
        raise ValueError("give an absolute folder path")
    os.makedirs(path, exist_ok=True)
    tmp = CFG + ".tmp"
    with open(tmp, "w", encoding="utf8") as fh:
        json.dump({"dir": path}, fh)
    os.replace(tmp, CFG)
    _seen.clear()
    return path


def recent():
    return {"dir": inbox_dir(), "recent": list(_recent)}


def _note(ev):
    ev["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _recent.insert(0, ev)
    del _recent[20:]


def _park(path, sub, why=None):
    """Range le fichier traité (jamais effacé). Un nom déjà pris reçoit un suffixe horodaté."""
    d = os.path.join(os.path.dirname(path), sub)
    os.makedirs(d, exist_ok=True)
    base = os.path.basename(path)
    dest = os.path.join(d, base)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(base)
        dest = os.path.join(d, "%s.%s%s" % (stem, time.strftime("%Y%m%d-%H%M%S"), ext))
    os.replace(path, dest)
    if why:
        with open(dest + ".why.txt", "w", encoding="utf8") as fh:
            fh.write(why + "\n")
    return dest


def scan_once():
    """Un relevé du dossier : installe chaque `.golem` STABLE. Rend la liste des événements de ce relevé."""
    from . import songs
    d = inbox_dir()
    try:
        os.makedirs(d, exist_ok=True)
        names = sorted(os.listdir(d))
    except OSError as e:
        log.warning(f"dossier surveillé {d} illisible : {e}")
        return []
    out, live = [], set()
    for f in names:
        p = os.path.join(d, f)
        if f.startswith(".") or not f.lower().endswith(".golem") or not os.path.isfile(p):
            continue
        live.add(p)
        try:
            st = os.stat(p)
        except OSError:
            continue
        sig = (st.st_size, st.st_mtime_ns)
        if _seen.get(p) != sig:                      # nouveau ou encore en train d'arriver : on attend
            _seen[p] = sig
            continue
        _seen.pop(p, None)
        try:
            r = songs.install_golem(p)
            _park(p, ".imported")
            ev = {"file": f, "ok": True, **r}
            log.info(f"dossier surveillé : {f} installé ({r['id']})")
        except songs.InstallError as e:
            _park(p, ".refused", str(e))
            ev = {"file": f, "ok": False, "why": str(e)}
            log.warning(f"dossier surveillé : {f} refusé — {e}")
        except OSError as e:                         # disque : on réessaiera au prochain relevé
            log.warning(f"dossier surveillé : {f} — {e}")
            continue
        _note(ev)
        out.append(ev)
    for p in list(_seen):
        if p not in live:
            _seen.pop(p, None)
    return out


async def watch(on_change=None):
    """La boucle du bridge (lancée au démarrage). Le travail (hachage de gros fichiers) part dans un fil."""
    while True:
        try:
            evs = await asyncio.to_thread(scan_once)
            if evs and on_change:
                on_change(evs)
        except Exception as e:                       # la boucle ne meurt jamais d'un fichier
            log.warning(f"dossier surveillé : {e}")
        await asyncio.sleep(POLL_S)
