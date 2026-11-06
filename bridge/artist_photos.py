# SPDX-License-Identifier: GPL-3.0-or-later
"""La PHOTO DE L'ARTISTE et la POCHETTE dans les `.golem` du répertoire (golem-format.md §9, rôles `band` et `cover` ;
2026-10-16).

golem.fm la met dans les fichiers qu'il génère (`art/band.<ext>`). Les chansons qui ne vivent que sur le golem n'en
ont pas : on la lui demande par le nom de l'artiste et le titre (GET /api/ext/artists/photo), puis on la range dans
la copie du golem par golemfile.replace — le reste du fichier recopié octet pour octet. Une fois rangée, elle
s'affiche sans réseau.

Règles :
  - jamais sur un original SIGNÉ : réécrire le manifeste casserait la signature ;
  - jamais dans un dossier de chansons (on n'y écrit pas) — seulement `songs/` ;
  - une chanson par passage, en tâche de fond, jamais pendant que ça joue (le zip entier est réécrit) ;
  - un « pas de photo » est retenu 24 h (golem.fm ne retente pas sa recherche avant) ; un serveur injoignable ou un
    golem non appairé ne retient rien.
"""
import json
import logging
import os
import threading
import time
import urllib.parse
import zipfile

from . import config as C

log = logging.getLogger("golem.artist_photos")

ROUTES = {"band": "/api/ext/artists/photo", "cover": "/api/ext/albums/cover"}
ROLES = ("cover", "band")
RETRY_S = 24 * 3600                      # un 404 de golem.fm vaut pour 24 h
MAX_BYTES = 5 * 1024 * 1024              # une photo, pas un fichier quelconque
_MAGIC = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"))
_lock = threading.Lock()                 # une chanson à la fois


def _state_path():
    return os.path.join(C.SONGS_DIR, ".artist-photos.json")


def _state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(d):
    p = _state_path()
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _key(role, artist, title):
    from .inventory import _norm_title
    k = _norm_title(artist) + "|" + _norm_title(title)
    return k if role == "band" else role + ":" + k       # la clé d'avant les pochettes reste celle de la photo


def image_ext(blob):
    """L'extension que disent les OCTETS (jpg | png | webp), sinon None — jamais l'en-tête seul."""
    for magic, ext in _MAGIC:
        if blob.startswith(magic):
            return ext
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return ".webp"
    return None


def _missing(zf):
    """Les rôles d'image (cover, band) que ce `.golem` n'a pas."""
    from .golemfm import _art_members
    have = _art_members(zf)
    return [r for r in ROLES if r not in have]


def candidates(now=None):
    """[(id, rôle, artiste, titre)] : chaque image manquante d'une chanson de `songs/`, non signée, pas en attente d'un 404."""
    from . import golemfile as G
    from . import songs as S
    now = time.time() if now is None else now
    st = _state()
    out = []
    for d in S.list_all():
        artist = (d.get("artist") or "").strip()
        p = S._path(d["id"])
        if not artist or not os.path.isfile(p):
            continue
        title = d.get("title") or ""
        try:
            with zipfile.ZipFile(p) as zf:
                if G.SIG_MEMBER in zf.namelist():
                    continue
                miss = _missing(zf)
        except (OSError, zipfile.BadZipFile):
            continue
        for role in miss:
            if role == "cover" and not title:
                continue                    # golem.fm exige le titre pour une pochette
            none_at = (st.get(_key(role, artist, title)) or {}).get("none_at")
            if none_at and now - none_at < RETRY_S:
                continue
            out.append((d["id"], role, artist, title))
    return out


def _album(sid):
    """L'album que déclare le manifeste — le choix le plus sûr pour une pochette (golem.fm)."""
    from . import songs as S
    try:
        with zipfile.ZipFile(S._path(sid)) as zf:
            a = json.loads(zf.read("golem.json")).get("album")
        return (a.get("title") or a.get("name")) if isinstance(a, dict) else (a or None)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def fetch(role, artist, title, album=None):
    """(status, octets|message) de golem.fm. 0 = injoignable ou golem non appairé."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not base or not token:
        return 0, "not paired"
    if role == "cover":
        q = {"artist": artist, "title": title}
        if album:
            q["album"] = album
    else:
        q = {"name": artist}
        if title:
            q["title"] = title              # lève les homonymes (golem.fm : « envoie toujours title »)
    return golemfm._req(ROUTES[role] + "?" + urllib.parse.urlencode(q), token=token, base=base, timeout=30, raw=True)


def fill(sid, role="band"):
    """Range l'image `role` (band | cover) dans la chanson `sid`. Rend "added" | "none" | "skip" | "error"."""
    from . import golem_pull, golemfile as G, songs as S
    d = S.load(sid)
    if not d or not (d.get("artist") or "").strip():
        return "skip"
    artist, title = d["artist"].strip(), d.get("title") or ""
    what = "pochette" if role == "cover" else "photo d'artiste"
    st, blob = fetch(role, artist, title, _album(sid) if role == "cover" else None)
    if st == 404:
        s = _state()
        s[_key(role, artist, title)] = {"none_at": int(time.time())}
        _save_state(s)
        log.info(f"{what} : golem.fm n'en a pas pour « {artist} — {title} » ({sid})")
        return "none"
    if st != 200 or not isinstance(blob, (bytes, bytearray)):
        if st:
            log.warning(f"{what} : golem.fm répond {st} pour « {artist} » ({sid})")
        return "error"
    ext = image_ext(blob)
    if not ext or len(blob) > MAX_BYTES:
        log.warning(f"{what} : réponse refusée pour « {artist} » ({len(blob)} octets, type {ext})")
        return "error"
    arc = f"art/{role}{ext}"
    p = S._path(sid)
    with golem_pull._lock:                     # pas en même temps qu'un tirage qui réécrirait ce fichier
        with zipfile.ZipFile(p) as zf:         # relu sous le verrou : le fichier a pu changer depuis la liste
            if G.SIG_MEMBER in zf.namelist() or role not in _missing(zf):
                return "skip"

        def mutate(m):
            files = m.setdefault("files", {})
            files.setdefault(arc, {})["role"] = role
        G.replace(p, mutate, {arc: bytes(blob)})
    log.info(f"{what} rangée : {sid} ({artist}, {len(blob)} octets)")
    return "added"


def step():
    """Un passage : au plus UNE chanson complétée. Rend le résultat, ou None s'il n'y avait rien à faire."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        todo = candidates()
        if not todo:
            return None
        res = fill(todo[0][0], todo[0][1])
        if res == "added":
            from . import inventory
            inventory.request_publish()
        return res
    finally:
        _lock.release()
