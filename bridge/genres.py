# SPDX-License-Identifier: GPL-3.0-or-later
"""Genres — la taxonomie à deux niveaux (docs/genres.md, validée le 2026-10-06).

17 familles, ~1 000 sous-genres. golem.fm en est PROPRIÉTAIRE ; le rack en garde une copie dans
config/genres.json (copiée de docs/archive/genres.draft.json) jusqu'à ce que golem.fm la serve, versionnée.

Ce que le rack en fait :
  - un PRESET porte des FAMILLES seules, 0 à 2, ordonnées, facultatives (`styles`, `style` = le premier) —
    décision : Helix, Quad Cortex, Kemper et Fractal ne font choisir aucun genre sur l'appareil ;
  - la chanson porte des couples (famille, sous-genre) — c'est golem.fm qui l'édite, pas le rack.

Remplace les 20 styles à plat de `app/lib.js` (STYLES). Les anciens `styles` des presets sont migrés au
chargement (store.migrate_config), comme toute autre migration : jamais de réécriture de masse.
"""
import json
import os

from . import config as C

GENRES_FILE = os.path.join(C.CONFIG_DIR, "genres.json")            # copie embarquée (versionnée)
# la liste servie par golem.fm (GET /api/ext/genres), relue quand le battement annonce un `genres_version` plus
# récent — un ÉTAT LOCAL (gitignoré), qui passe devant la copie embarquée dès qu'il est au moins aussi récent
REMOTE_FILE = os.path.join(C.CONFIG_DIR, "genres.remote.json")

# Les 20 styles à plat d'avant (et les deux ajoutés chez golem.fm) -> la FAMILLE qui les contient
# (docs/genres.md §4). Le sous-genre (djent, manouche…) se perd pour un preset : il ne porte que des familles.
LEGACY = {
    "djent": "metal", "metal": "metal", "punk": "punk", "math rock": "rock", "rock": "rock", "pop": "pop",
    "funk": "rnb", "soul": "rnb", "blues": "blues", "jazz": "jazz", "manouche": "jazz", "rap": "hip-hop",
    "electronic": "electronic", "ambient": "electronic", "reggae": "caribbean", "latin": "latin",
    "folk": "folk", "world": "world", "traditionnal": "world", "classical": "classical",
    "brazilian": "latin", "country": "folk",
}
MAX_PRESET_STYLES = 2

_cache = {"key": None, "data": None}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if _valid(d) else None
    except (OSError, ValueError):
        return None


def _valid(d):
    """Une liste utilisable : des familles qui ont un id, un libellé et une liste de sous-genres."""
    fams = d.get("families") if isinstance(d, dict) else None
    return bool(fams) and all(isinstance(f, dict) and f.get("id") and f.get("label")
                              and isinstance(f.get("subgenres"), list) for f in fams)


def load():
    """La taxonomie complète ({version, families:[{id, label, subgenres:[…]}], legacy?}) : celle de golem.fm si le
    rack l'a reçue et qu'elle est au moins aussi récente que la copie embarquée, sinon la copie. Relue au changement."""
    key = tuple(os.path.getmtime(p) if os.path.exists(p) else None for p in (GENRES_FILE, REMOTE_FILE))
    if _cache["key"] != key:
        local, remote = _read(GENRES_FILE), _read(REMOTE_FILE)
        best = local or {"version": 0, "families": []}
        if remote and int(remote.get("version") or 0) >= int(best.get("version") or 0):
            best = remote
        _cache.update(key=key, data=best)
    return _cache["data"]


def version():
    return int(load().get("version") or 0)


def sync(announced):
    """Le battement annonce `genres_version` : si golem.fm a plus récent, on tire GET /api/ext/genres et on le
    garde (REMOTE_FILE). Ne lève jamais ; rend True si la liste a changé. Une réponse invalide ne remplace rien."""
    try:
        if int(announced or 0) <= version() and os.path.exists(REMOTE_FILE):
            return False
        from . import golemfm
        _base, token = golemfm._cfg()
        if not token:
            return False
        st, d = golemfm._req("/api/ext/genres", token=token)   # le jeton ne part que s'il est passé
        if st != 200 or not _valid(d):
            return False
        tmp = REMOTE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, REMOTE_FILE)
        return True
    except Exception:
        return False


def families():
    """[(id, label)] dans l'ordre de la taxonomie."""
    return [(f["id"], f["label"]) for f in load().get("families") or []]


def family_of(value):
    """La famille d'une valeur de style : un id de famille, un ancien style à plat, ou un id de sous-genre.
    None si rien ne correspond (la valeur est alors abandonnée, jamais devinée)."""
    v = str(value or "").strip().lower()
    if not v:
        return None
    ids = {fid for fid, _ in families()}
    if v in ids:
        return v
    # la table des anciens styles SERVIE par golem.fm ({style: [famille, sous-genre|null]}) avant la nôtre
    served = (load().get("legacy") or {}).get(v)
    if isinstance(served, list) and served and served[0] in ids:
        return served[0]
    if v in LEGACY:
        return LEGACY[v]
    for f in load().get("families") or []:
        if any(s.get("id") == v for s in f.get("subgenres") or []):
            return f["id"]
    return None


def label_of(gid):
    """Le libellé d'un id de famille OU de sous-genre (les deux espaces sont disjoints) ; l'id lui-même sinon.
    Sert aux grooves, dont `genre` est un seul id (forme choisie par golem.fm)."""
    for f in load().get("families") or []:
        if f["id"] == gid:
            return f["label"]
        for s in f.get("subgenres") or []:
            if s.get("id") == gid:
                return s.get("label") or gid
    return gid


def migrate_styles(p):
    """Ramène `styles`/`style` d'un preset à des FAMILLES (0 à 2, ordre gardé, sans doublon). Idempotent.
    Mute le preset en place ; rend True si quelque chose a changé."""
    if not isinstance(p, dict):
        return False
    raw = p.get("styles")
    if not isinstance(raw, list):
        raw = [p.get("style")] if p.get("style") else []
    out = []
    for v in raw:
        fam = family_of(v)
        if fam and fam not in out:
            out.append(fam)
    out = out[:MAX_PRESET_STYLES]
    before = (p.get("styles"), p.get("style"))
    p["styles"] = out
    p["style"] = out[0] if out else None
    return before != (p["styles"], p["style"])
