# SPDX-License-Identifier: GPL-3.0-or-later
"""La page Storage (Settings ▸ Content ▸ Storage, 2026-10-09 — mockups/storage.html) : la place que prend la MUSIQUE
sur le golem, catégorie par catégorie (les mêmes que les sauvegardes, docs/backups.md), ce qui est installé et se
réinstalle, et les CACHES qu'on peut vider.

Deux caches se vident d'un geste :
  · les APERÇUS DE FORME D'ONDE (`recordings/peaks/*.reapeaks`) dont le fichier audio n'existe plus — mesuré le
    2026-10-09 : 239 aperçus, 429 Mo, AUCUN n'avait son audio (les prises sont renommées et rangées par session, les
    aperçus gardaient l'ancien nom). Reaper en recrée un dès qu'un fichier audio est relu.
  · les CHANSONS DÉCOMPRESSÉES (`songs/.work/`), que `songs.workdir` reconstruit à la demande depuis le .golem. Celle
    qui est CHARGÉE n'est jamais touchée : le lecteur lit ses stems en direct.
"""
import os
import shutil

from . import backup as B
from . import config as C


def _tree(d):
    """{n, bytes} de tout un dossier (fichiers cachés compris : c'est de la place réelle)."""
    n = b = 0
    for root, _ds, fs in os.walk(d) if os.path.isdir(d) else []:
        for f in fs:
            p = os.path.join(root, f)
            try:
                b += os.path.getsize(p)
                n += 1
            except OSError:
                pass
    return {"n": n, "bytes": b}


def _peaks_dir():
    return os.path.join(B.RECORDINGS_DIR, "peaks")


def orphan_peaks():
    """Les aperçus de forme d'onde dont l'audio n'existe plus nulle part sous recordings/ ni les médias du rack."""
    d = _peaks_dir()
    try:
        peaks = [f for f in os.listdir(d) if f.endswith(".reapeaks")]
    except OSError:
        return []
    audio = set()
    for base in (B.RECORDINGS_DIR, os.path.join(C.ROOT, "assets"), C.SONGS_DIR, os.path.join(C.ROOT, "sets")):
        for root, _ds, fs in os.walk(base) if os.path.isdir(base) else []:
            if os.path.abspath(root) == os.path.abspath(d):
                continue
            audio.update(fs)
    return [os.path.join(d, f) for f in peaks if f[:-len(".reapeaks")] not in audio]


def _in_use():
    """Les dossiers de travail À NE PAS vider : la chanson chargée (backing, morceau joué)."""
    from . import songs
    from .state import state
    keep = set()
    for sid in ((state.backing or {}).get("slug"), (state.song or {}).get("band_song")):
        if sid:
            keep.add(songs._safe(sid))
    return keep


_CAT_CACHE = {}                  # chemin -> (mtime, taille, catégorie) : un .golem n'est rouvert que s'il a changé


def _songs_by_category():
    """Les .golem du golem, PAR CATÉGORIE : {"songs": {n, bytes}, "vocals": {n, bytes}}. Une ligne Vocals vit dans le
    même dossier qu'une chanson (songs/) : seule la catégorie que le fichier porte les sépare (golemfile.category_of).
    Un fichier sans catégorie (de l'audio seul) compte en chanson."""
    from . import golemfile as G
    out = {"songs": {"n": 0, "bytes": 0}, "vocals": {"n": 0, "bytes": 0}}
    try:
        names = [f for f in os.listdir(C.SONGS_DIR) if f.endswith(".golem") and not f.startswith(".")]
    except OSError:
        return out
    for f in names:
        p = os.path.join(C.SONGS_DIR, f)
        try:
            st = os.stat(p)
        except OSError:
            continue
        hit = _CAT_CACHE.get(p)
        if not hit or hit[:2] != (st.st_mtime, st.st_size):
            try:
                cat = G.category_of(p)
            except Exception:
                cat = None
            hit = _CAT_CACHE[p] = (st.st_mtime, st.st_size, cat)
        k = "vocals" if hit[2] == "vocals" else "songs"
        out[k]["n"] += 1
        out[k]["bytes"] += st.st_size
    return out


def overview():
    """Le disque, la musique par catégorie, les sons installés, les caches."""
    du = shutil.disk_usage(C.ROOT)
    c = B.counts()
    music = {k: (c.get(k) or {}).get("bytes", 0) for k in ("amps", "cabs", "pedals", "presets", "patches", "banks",
                                                         "settings", "kits", "synths", "grooves", "songs", "recordings",
                                                         "standards")}
    # Songs, Vocals et Standards sont TROIS lignes de « Your music » (2026-10-17) : les .golem de songs/ séparés
    # par leur catégorie ; la sauvegarde, elle, garde une seule catégorie « songs »
    split = _songs_by_category()
    music["songs"], music["vocals"] = split["songs"]["bytes"], split["vocals"]["bytes"]
    c = {**c, "songs": {**(c.get("songs") or {}), "n": split["songs"]["n"]}, "vocals": split["vocals"]}
    installed = [
        {"label": "DrumGizmo kits", **_tree(os.path.join(C.ROOT, "library", "drumkits"))},
        {"label": "SFZ pianos", **_tree(os.path.join(C.ROOT, "library", "sfz"))},
        {"label": "Factory synth presets", **_tree(os.path.join(B.VITAL_DIR, "factory"))},
    ]
    op = orphan_peaks()
    work = os.path.join(C.SONGS_DIR, ".work")
    caches = [
        {"id": "peaks", "label": "Waveform previews", "n": len(op), "bytes": sum(os.path.getsize(p) for p in op if os.path.isfile(p)),
         "clear": True},
        {"id": "work", "label": "Songs ready to play", **_tree(work), "clear": True},
        {"id": "backing", "label": "golem.fm backings", **_tree(os.path.join(C.ROOT, "assets", "backing")), "clear": True,
         "n": len(unused_backings())},
    ]
    m, i, k = sum(music.values()), sum(x["bytes"] for x in installed), sum(x["bytes"] for x in caches)
    return {"disk": {"total": du.total, "used": du.used, "free": du.free},
            "music": music, "music_total": m, "counts": c,
            "installed": installed, "installed_total": i,
            "caches": caches, "caches_total": k,
            "other": max(0, du.used - m - i - k)}


def unused_backings():
    """Les entrées du cache de backings dont PLUS RIEN n'a besoin (2026-10-17 : le ménage du cache quitte la page
    Backings pour celle-ci) : une chanson de la bibliothèque porte ses stems et la remplace à l'écran
    (golemfm.prefer_library), et aucun preset ne la joue encore sous ce slug sans être redirigé vers cette chanson
    (golemfm.backing_key). Jamais une ligne Vocals (`k-*`), jamais un backing local."""
    from . import golemfm
    from .store import load_presets
    try:
        entries = [e for e in golemfm.list_cache() if e.get("cached")]
    except OSError:
        return []
    _, aliases = golemfm.prefer_library(entries)
    replaced = {sl for v in aliases.values() for sl in v}
    linked = set()
    for p in load_presets() or []:
        linked.update(p.get("backing") or [])
    return [sl for sl in sorted(replaced) if sl not in linked or golemfm.backing_key(sl) != sl]


class StorageError(RuntimeError):
    pass


def clear(cache):
    """Vide un cache. Rend {freed, n}. Lève StorageError (anglais : ça s'affiche)."""
    if cache == "peaks":
        files = orphan_peaks()
        freed = 0
        for p in files:
            try:
                freed += os.path.getsize(p)
                os.remove(p)
            except OSError:
                pass
        return {"freed": freed, "n": len(files)}
    if cache == "work":
        from .state import state
        if (state.backing or {}).get("playing"):
            raise StorageError("a song is playing — stop it first")
        keep, freed, n = _in_use(), 0, 0
        work = os.path.join(C.SONGS_DIR, ".work")
        for name in os.listdir(work) if os.path.isdir(work) else []:
            if name in keep:
                continue
            d = os.path.join(work, name)
            freed += _tree(d)["bytes"]
            shutil.rmtree(d, ignore_errors=True)
            n += 1
        return {"freed": freed, "n": n, "kept": sorted(keep)}
    if cache == "backing":
        from . import golemfm
        from .state import state
        if (state.backing or {}).get("playing"):
            raise StorageError("a song is playing — stop it first")
        freed, n = 0, 0
        for slug in unused_backings():
            d = golemfm.song_dir(slug)
            freed += _tree(d)["bytes"]
            golemfm.remove_cached(slug)
            n += 1
        return {"freed": freed, "n": n}
    raise StorageError("unknown cache: %s" % cache)
