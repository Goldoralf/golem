# SPDX-License-Identifier: GPL-3.0-or-later
"""Les DOSSIERS DE CHANSONS — le golem lit des bibliothèques de `.golem` qu'il ne possède pas (docs/song-folders.md,
2026-10-08 : « je valide le contrat song-folders »).

Trois règles qui tiennent tout :

1. **UN DOSSIER DE CHANSONS SE LIT, IL NE S'ÉCRIT JAMAIS** (§2.2). Le disque d'un ami, un partage réseau : le golem
   n'y crée, n'y renomme, n'y supprime rien — pas même un index. Écouter, répéter, chanter s'y font SUR PLACE ; ce
   qui écrirait (la fiche, une setlist) ADOPTE d'abord la chanson : elle est copiée dans le golem par le chemin
   unique (`songs.install_golem`), et c'est la copie qui reçoit l'écriture (§2.3). Ce qui part en concert est sur
   le golem : un NAS injoignable le soir du concert, et la chanson serait muette.

2. **L'INDEX EST UN CACHE, PAS UNE VÉRITÉ** (§2.5). `songs/.folders/index.json`, chez le golem. Un passage ne fait
   que des `stat` ; un manifeste n'est relu que si la taille ou la date du fichier a changé (~50 ms par fichier sur
   un partage réseau : 5 000 chansons = 4 min au premier passage, quelques secondes ensuite). Effacé, il se refait.
   On n'y lit que le MANIFESTE : la vérification complète (empreintes, chemins) a lieu à l'extraction pour jouer
   (`songs.workdir`) et à l'adoption.

3. **UN DOSSIER ABSENT N'EFFACE RIEN** (§2.6). Disque débranché, NAS éteint : ses entrées gardent leur dernier état,
   marquées `unavailable`. Une entrée n'est retirée que si son dossier a été lu EN ENTIER et que le fichier n'y est
   plus — la garde du miroir des standards et de l'inventaire : une liste courte peut venir d'une lecture ratée.

La liste des dossiers vit dans `config/song-folders.json` (local, jamais commité, comme `config/inbox.json`).
"""
import json
import logging
import os
import shutil
import sys
import threading
import time
import zipfile

from . import config as C
from . import golemfile as G

log = logging.getLogger("golem.song_folders")

CFG = os.path.join(C.CONFIG_DIR, "song-folders.json")
INDEX_VERSION = 1
MAX_DEPTH = 12                 # un dossier de chansons n'est pas un système de fichiers entier
MAX_FILES = 50000              # par dossier : au-delà, le passage s'arrête (dit, jamais en silence)
WORK_CAP_BYTES = 5 * 1024 ** 3     # le cache de travail des chansons lues sur place (§4.3 : 5 Go)
RESCAN_S = 600
# des dossiers qu'on n'offre jamais : le système, et le golem lui-même (ses chansons y seraient en double)
_SYSTEM = ("/", "/proc", "/sys", "/dev", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot", "/var", "/run",
           "/tmp", "/snap", "/opt", "/root", "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
           "/System", "/Library", "/private")

_lock = threading.RLock()
_ST = {"scanning": None, "done": 0, "found": 0, "queue": []}
_idx = {"data": None}
_wake = threading.Event()
_thread = {"t": None}


# ── la liste des dossiers ─────────────────────────────────────────────────────────────────────

def _cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("folders"), list) else {"folders": []}
    except (OSError, ValueError):
        return {"folders": []}


def _save_cfg(d):
    from .store import _write_json_atomic
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    _write_json_atomic(CFG, d)


def folders():
    """[{path, show_on_golemfm, added_at}] — tels que réglés."""
    return [f for f in _cfg()["folders"] if isinstance(f, dict) and f.get("path")]


def _norm(path):
    return os.path.normpath(os.path.abspath(os.path.expanduser(str(path or "").strip())))


def _inside(a, b):
    """`a` est-il `b` ou dedans ?"""
    a, b = os.path.normcase(a), os.path.normcase(b)
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


class FolderError(ValueError):
    pass


def _too_wide(p):
    """Un dossier qu'on n'offre jamais. LU dans le système plutôt que listé : une racine de disque, quelle que
    soit sa lettre (`D:\\`, `\\\\nas\\share`), le dossier personnel et ce qui le contient (`C:\\Users`, `/home`),
    et sous Windows les dossiers système où qu'ils soient installés, dedans compris."""
    n = os.path.normcase
    if os.path.dirname(p) == p or n(p) in {n(s) for s in _SYSTEM}:
        return True
    if _inside(_norm("~"), p):
        return True
    if sys.platform == "win32":
        sysdirs = [os.environ.get(k) for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData")]
        return any(_inside(p, _norm(s)) for s in sysdirs if s)
    return False


def check_folder(path):
    """Le dossier qu'on peut ajouter, normalisé ; lève FolderError avec la raison (anglais : elle s'affiche)."""
    p = _norm(path)
    if not str(path or "").strip():
        raise FolderError("pick a folder")
    if _too_wide(p):
        raise FolderError("this folder is too wide — pick the folder that holds your songs")
    if any(_inside(p, os.path.abspath(r)) or _inside(os.path.abspath(r), p) for r in (C.ROOT, C.SONGS_DIR)):
        raise FolderError("this is golem's own folder — its songs are already here")
    if not os.path.isdir(p):
        raise FolderError("not found")
    try:
        with os.scandir(p) as it:
            next(it, None)
    except OSError:
        raise FolderError("not readable")
    for f in folders():
        q = _norm(f["path"])
        if q == p:
            raise FolderError("already in the list")
        if _inside(p, q) or _inside(q, p):
            raise FolderError("overlaps « %s », already in the list" % q)
    return p


# CE QU'UN DOSSIER APPORTE (§2.9, 2026-10-17) : `auto` = tout, rangé d'après le CONTENU (le .golem dit ce qu'il est) ;
# typé = seul ce type est proposé depuis ce dossier, le reste est ignoré ET compté. Un FILTRE, pas un aiguillage :
# c'est toujours le fichier qui dit sa nature — un dossier « Vocals » qui porte une chanson ne la fait pas karaoké.
KINDS = ("auto", "song", "vocals", "standard")


def _kinds():
    """{dossier normalisé: type} des dossiers réglés."""
    return {_norm(f["path"]): (f.get("kind") if f.get("kind") in KINDS else "auto") for f in folders()}


def _takes(kind, e):
    """Ce dossier propose-t-il cette entrée ?"""
    return kind in (None, "auto") or e.get("category") == kind


def add(path, show_on_golemfm=True, kind="auto"):
    p = check_folder(path)
    with _lock:
        d = _cfg()
        d["folders"].append({"path": p, "show_on_golemfm": bool(show_on_golemfm),
                             "kind": kind if kind in KINDS else "auto",
                             "added_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        _save_cfg(d)
    request_scan(p)
    return p


def remove(path):
    """Retire le dossier de la LISTE — jamais un fichier. Ses entrées quittent l'index. Rend True s'il y était."""
    p = _norm(path)
    with _lock:
        d = _cfg()
        keep = [f for f in d["folders"] if _norm(f.get("path")) != p]
        if len(keep) == len(d["folders"]):
            return False
        d["folders"] = keep
        _save_cfg(d)
        idx = _index()
        idx["entries"] = {k: e for k, e in idx["entries"].items() if e.get("folder") != p}
        idx["folders"].pop(p, None)
        _save_index()
    _changed()
    return True


def set_show(path, show):
    """« Show on golem.fm » : un dossier exclu ne monte pas dans l'inventaire (§2.7) — ses titres restent ici."""
    p = _norm(path)
    with _lock:
        d = _cfg()
        hit = False
        for f in d["folders"]:
            if _norm(f.get("path")) == p:
                f["show_on_golemfm"] = bool(show)
                hit = True
        if hit:
            _save_cfg(d)
    if hit:
        _changed()
    return hit


def set_kind(path, kind):
    """Ce que le dossier apporte (KINDS). Rend False si le dossier ou le type est inconnu."""
    if kind not in KINDS:
        return False
    p = _norm(path)
    with _lock:
        d = _cfg()
        hit = False
        for f in d["folders"]:
            if _norm(f.get("path")) == p:
                f["kind"] = kind
                hit = True
        if hit:
            _save_cfg(d)
    if hit:
        _changed()
    return hit


# ── l'index ───────────────────────────────────────────────────────────────────────────────────

def _index_path():
    return os.path.join(C.SONGS_DIR, ".folders", "index.json")


def _index():
    """L'index en mémoire (lu une fois). Illisible ou d'une autre version : on repart de zéro, il se refait."""
    if _idx["data"] is None:
        try:
            with open(_index_path(), encoding="utf-8") as f:
                d = json.load(f)
            if not (isinstance(d, dict) and d.get("version") == INDEX_VERSION):
                raise ValueError("version")
            d.setdefault("entries", {})
            d.setdefault("folders", {})
        except (OSError, ValueError):
            d = {"version": INDEX_VERSION, "entries": {}, "folders": {}}
        _idx["data"] = d
    return _idx["data"]


def _save_index():
    from .store import _write_json_atomic
    os.makedirs(os.path.dirname(_index_path()), exist_ok=True)
    _write_json_atomic(_index_path(), _index())


def reset():
    """Oublie l'index en mémoire (tests, ou index effacé à la main)."""
    with _lock:
        _idx["data"] = None


def _entry_of(path, folder, st):
    """Une entrée d'index : la carte d'inventaire (une seule définition, `inventory.card_of`) + l'emplacement."""
    from . import inventory, songs
    e = {"path": path, "folder": folder, "size": st.st_size, "mtime": st.st_mtime_ns,
         "seen_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    try:
        rep = G.verify(path, hashes=False)
        m = rep["manifest"]
        if m.get("type") != "song":
            return {**e, "state": "bad", "why": "albums are not read yet — only songs"}
        card = inventory.card_of(path, rep)
    except (G.GolemError, OSError, zipfile.BadZipFile, ValueError) as ex:
        return {**e, "state": "bad", "why": str(ex)[:200]}
    if not card.get("id") or not songs.BS.match(str(card["id"])):
        return {**e, "state": "bad", "why": "not a song id: %s" % card.get("id")}
    e.update(card)
    e["state"] = "ok"
    if card.get("category") == "standard":            # le nom du fichier ; `golemfm.standard` ignoré (song-sharing.md §2.8)
        e["slug"] = os.path.splitext(os.path.basename(path))[0]
    # LE MÊME ENREGISTREMENT sous un autre id (§2.4) : signalé, jamais fusionné — l'adoption rattache
    try:
        hit = songs._same_recording(m)
        if hit and hit[1].get("id") != card["id"]:
            e["same_as"] = {"id": hit[1]["id"], "title": hit[1].get("title")}
    except Exception:                                 # une comparaison d'empreintes ratée ne coûte pas l'entrée
        pass
    return e


def _walk(root, out, other, errors):
    """Les `.golem` sous `root`, sans suivre les liens symboliques ni entrer dans les dossiers cachés. `errors`
    reçoit les sous-dossiers illisibles : une lecture qui en a n'est pas COMPLÈTE (§2.6)."""
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            with os.scandir(d) as it:
                items = list(it)
        except OSError as ex:
            errors.append("%s: %s" % (d, ex.strerror or ex))
            continue
        for x in items:
            if x.name.startswith("."):
                continue
            try:
                if x.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH:
                        stack.append((x.path, depth + 1))
                elif x.is_file(follow_symlinks=False):
                    if x.name.lower().endswith(".golem"):
                        out.append(x)
                        if len(out) >= MAX_FILES:
                            errors.append("more than %d files — the rest is not read" % MAX_FILES)
                            return
                    else:
                        other[0] += 1
            except OSError as ex:
                errors.append("%s: %s" % (x.path, ex.strerror or ex))


def scan_folder(folder):
    """UN passage sur `folder` : incrémental, jamais destructif sur une lecture ratée. Rend l'état du dossier."""
    folder = _norm(folder)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _lock:
        _ST.update(scanning=folder, done=0, found=0)
    if not os.path.isdir(folder):
        with _lock:
            idx = _index()
            for e in idx["entries"].values():
                if e.get("folder") == folder and e.get("state") != "bad":
                    e["state"] = "unavailable"
            fs = idx["folders"].setdefault(folder, {})
            fs.update(state="offline", checked_at=now)
            _save_index()
            _ST.update(scanning=None)
        log.info("dossier de chansons absent : %s — ses entrées restent, « unavailable »" % folder)
        _changed()
        return fs
    found, other, errors = [], [0], []
    _walk(folder, found, other, errors)
    with _lock:
        _ST["found"] = len(found)
        old = {k: e for k, e in _index()["entries"].items() if e.get("folder") == folder}
    seen, n_read = set(), 0
    wanted = lambda: any(_norm(f["path"]) == folder for f in folders())
    for i, x in enumerate(found):
        if i % 200 == 0 and i and not wanted():
            break                                          # retiré pendant le passage : on s'arrête (vérifié plus bas)
        p = os.path.normpath(x.path)
        seen.add(p)
        try:
            st = x.stat(follow_symlinks=False)
        except OSError as ex:
            errors.append("%s: %s" % (p, ex.strerror or ex))
            continue
        cur = old.get(p)
        if cur and cur.get("size") == st.st_size and cur.get("mtime") == st.st_mtime_ns and cur.get("state") != "unavailable":
            continue                                       # inchangé : un stat, rien d'autre
        if cur and cur.get("size") == st.st_size and cur.get("mtime") == st.st_mtime_ns:
            e = {**cur, "state": cur.get("prev_state") or "ok"}   # revenu en ligne, inchangé
            e.pop("prev_state", None)
        else:
            e = _entry_of(p, folder, st)
            n_read += 1
        with _lock:
            _index()["entries"][p] = e
            _ST["done"] = i + 1
            if n_read and n_read % 200 == 0:
                _save_index()                              # la liste se remplit pendant le premier passage
    complete = not errors
    with _lock:
        idx = _index()
        if not wanted():
            # RETIRÉ PENDANT LE PASSAGE (vu le 2026-10-09 : un NAS en cours d'indexation, retiré de la liste) : rien de ce
            # passage ne s'écrit, sinon le dossier revenait en fantôme dans l'index
            idx["entries"] = {k: e for k, e in idx["entries"].items() if e.get("folder") != folder}
            idx["folders"].pop(folder, None)
            _save_index()
            _ST.update(scanning=None)
            return {"state": "removed"}
        gone = [p for p in old if p not in seen]
        for p in gone:
            if complete:
                idx["entries"].pop(p, None)                # lu EN ENTIER et absent : vraiment parti
            elif idx["entries"][p].get("state") != "unavailable":
                idx["entries"][p]["prev_state"] = idx["entries"][p].get("state")
                idx["entries"][p]["state"] = "unavailable"
        ents = [e for e in idx["entries"].values() if e.get("folder") == folder]
        counts = {}
        for e in ents:
            if e.get("state") == "ok":
                counts[e.get("category") or "other"] = counts.get(e.get("category") or "other", 0) + 1
        fs = {"state": "online" if complete else "partial", "checked_at": now, "scanned_at": now,
              "location": location(folder)["kind"],                 # gardé : un dossier débranché garde son étiquette
              "counts": counts, "bad": sum(1 for e in ents if e.get("state") == "bad"),
              "other_files": other[0], "errors": errors[:20]}
        idx["folders"][folder] = fs
        _save_index()
        _ST.update(scanning=None, done=len(found))
    log.info("dossier de chansons %s : %d .golem (%d relus), %s%s"
             % (folder, len(found), n_read, counts, " — lecture incomplète : %s" % errors[:3] if errors else ""))
    _changed()
    return fs


def scan_all():
    for f in folders():
        try:
            scan_folder(f["path"])
        except Exception as e:                         # un dossier qui casse le passage n'emporte pas les autres
            log.warning("dossier de chansons %s : %s" % (f.get("path"), e))
            with _lock:
                _ST.update(scanning=None)


def _changed():
    """L'index a bougé : le catalogue des standards et l'inventaire golem.fm le relisent."""
    try:
        from . import standards
        standards.invalidate()
    except Exception:
        pass
    try:
        from . import inventory
        inventory.request_publish(delay=10.0)
    except Exception:
        pass


def _runner():
    while True:
        _wake.wait(RESCAN_S)
        _wake.clear()
        with _lock:
            q, _ST["queue"] = list(_ST["queue"]), []
        if q == ["*"] or not q:
            scan_all()
        else:
            for p in dict.fromkeys(q):
                if p == "*":
                    scan_all()
                elif any(_norm(f["path"]) == p for f in folders()):
                    scan_folder(p)


def request_scan(path=None):
    """Un passage en tâche de fond (`path` = un dossier, sinon tous). Démarre le passeur au premier appel ; il
    repasse ensuite tout seul toutes les 10 min (§2.5 : pas d'inotify sur un dossier large ou réseau)."""
    with _lock:
        _ST["queue"].append(_norm(path) if path else "*")
        if not _thread["t"]:
            t = threading.Thread(target=_runner, name="song-folders", daemon=True)
            _thread["t"] = t
            t.start()
    _wake.set()


# ── lire l'index ──────────────────────────────────────────────────────────────────────────────

def _online(e):
    return e.get("state") == "ok"


def _local_ids():
    try:
        return {os.path.splitext(f)[0] for f in os.listdir(C.SONGS_DIR) if f.endswith(".golem") and not f.startswith(".")}
    except OSError:
        return set()


def _local_std_slugs():
    from . import standards
    try:
        return {os.path.splitext(f)[0] for f in os.listdir(standards.GOLEM_DIR) if f.endswith(".golem")}
    except OSError:
        return set()


def _adopted(e, local=None, std=None):
    """La chanson de cette entrée est-elle déjà sur le golem ? (par son id ; un standard, par son slug)"""
    from . import songs
    if e.get("category") == "standard":
        return e.get("slug") in (std if std is not None else _local_std_slugs())
    return songs._safe(e.get("id")) in (local if local is not None else _local_ids())


def path_of(gid):
    """Le fichier d'un dossier qui porte cet id, LISIBLE maintenant (en ligne, fichier présent), ou None. Plusieurs
    copies : la plus récente (§2.4)."""
    with _lock:
        hits = [e for e in _index()["entries"].values() if e.get("id") == gid and _online(e)]
    hits.sort(key=lambda e: e.get("mtime") or 0, reverse=True)
    for e in hits:
        if os.path.isfile(e["path"]):
            return e["path"]
    return None


def entry_of_path(path):
    with _lock:
        e = _index()["entries"].get(os.path.normpath(path))
        return dict(e) if e else None


def entries(q=None, category=None, offset=0, limit=200, include_adopted=False):
    """Les chansons des dossiers, UNE par id (§2.4 : les copies sont listées dans `copies`), triées par titre.
    `adopted` = déjà sur le golem (exclues par défaut : la liste du golem les montre déjà). Rend {total, items}."""
    local, std = _local_ids(), _local_std_slugs()
    kinds = _kinds()
    with _lock:
        all_e = [dict(e) for e in _index()["entries"].values()
                 if e.get("folder") in kinds and _takes(kinds[e.get("folder")], e)]
        fstate = {k: v.get("state") for k, v in _index()["folders"].items()}
    by = {}
    for e in all_e:
        if e.get("state") == "bad":
            continue
        by.setdefault(e.get("id"), []).append(e)
    out = []
    for gid, es in by.items():
        es.sort(key=lambda e: (e.get("state") != "ok", -(e.get("mtime") or 0)))
        best = es[0]
        best["copies"] = [{"path": x["path"], "folder": x["folder"], "state": x.get("state")} for x in es]
        best["adopted"] = _adopted(best, local, std)
        best["folder_state"] = fstate.get(best["folder"])
        out.append(best)
    if not include_adopted:
        out = [e for e in out if not e["adopted"]]
    if category:
        cats = set(category.split(","))
        out = [e for e in out if e.get("category") in cats]
    if q:
        ql = q.lower()
        out = [e for e in out if ql in ((e.get("title") or "") + " " + (e.get("artist") or "") + " "
                                        + os.path.basename(e["path"])).lower()]
    out.sort(key=lambda e: ((e.get("title") or os.path.basename(e["path"])).lower(), e["path"]))
    return {"total": len(out), "items": out[offset:offset + limit]}


def overview():
    """L'onglet System ▸ Song folders : chaque dossier, son état, ses comptes, et le passage en cours."""
    with _lock:
        idx = _index()
        st = dict(_ST)
        rows = []
        for f in folders():
            p = _norm(f["path"])
            fs = dict(idx["folders"].get(p) or {})
            ents = [e for e in idx["entries"].values() if e.get("folder") == p]
            if st.get("scanning") == p:
                fs["state"] = "indexing"
                fs["progress"] = {"done": st.get("done"), "found": st.get("found")}
            elif not fs:
                fs["state"] = "waiting"
            if fs.get("state") in ("online", "partial") and not os.path.isdir(p):
                fs["state"] = "offline"                    # débranché depuis le dernier passage : dit tout de suite
            bad = [{"file": os.path.relpath(e["path"], p), "why": e.get("why")}
                   for e in ents if e.get("state") == "bad"][:50]
            kind = f.get("kind") if f.get("kind") in KINDS else "auto"
            ok = [e for e in ents if e.get("state") == "ok"]
            cats = {e.get("category") for e in ok if e.get("category")}
            # IGNORÉ = lisible mais pas du type du dossier : dit, jamais en silence
            ignored = sum(1 for e in ok if not _takes(kind, e))
            # la SUGGESTION, après un passage : un dossier « auto » qui ne porte qu'un type peut le dire
            suggest = next(iter(cats)) if kind == "auto" and len(cats) == 1 and fs.get("state") == "online" else None
            rows.append({**f, "path": p, **fs, "kind": kind, "ignored": ignored, "suggest": suggest,
                         "songs": len(ents), "bad_files": bad,
                         "bytes": sum(int(e.get("size") or 0) for e in ents if e.get("state") != "bad"),
                         "last_seen": max((e.get("seen_at") or "" for e in ents), default=None)})
    for r in rows:                                    # où est le dossier (hors verrou : macOS lance `df`/`mount`)
        r["label"] = display_name(r["path"])
        r["location"] = (location(r["path"])["kind"] if r.get("state") != "offline" else None) or r.get("location")
    return {"folders": rows, "scanning": st.get("scanning")}


# ── l'inventaire golem.fm (§2.7) ──────────────────────────────────────────────────────────────

def inventory_cards():
    """(cartes, lecture_complète) des dossiers MONTRÉS sur golem.fm. Une chanson déjà sur le golem n'y est pas : sa
    carte « golem » la couvre. Un dossier absent ou lu en partie rend la lecture INCOMPLÈTE — l'inventaire n'enverra
    alors aucun retrait (§2.6), et ses cartes restent chez golem.fm avec leur « vu pour la dernière fois »."""
    from . import inventory
    show = {_norm(f["path"]) for f in folders() if f.get("show_on_golemfm", True)}
    if not show:
        return {}, True
    kinds = _kinds()
    local, std = _local_ids(), _local_std_slugs()
    cards, complete = {}, True
    with _lock:
        idx = _index()
        for p in show:
            fs = idx["folders"].get(p) or {}
            if fs.get("state") != "online" or not os.path.isdir(p):
                complete = False
        for e in idx["entries"].values():
            if e.get("folder") not in show or e.get("state") != "ok" or not e.get("category"):
                continue
            if not _takes(kinds.get(e.get("folder")), e):         # le dossier ne l'apporte pas : pas montré non plus
                continue
            if _adopted(e, local, std) or e["id"] in cards:
                continue
            cards[e["id"]] = {**{k: e.get(k) for k in inventory.CARD_FIELDS}, "where": "folder"}
    return cards, complete


def has_standards():
    kinds = _kinds()
    with _lock:
        return any(e.get("category") == "standard" and e.get("state") == "ok"
                   and e.get("folder") in kinds and _takes(kinds[e.get("folder")], e)
                   for e in _index()["entries"].values())


def standards_entries():
    """Les standards des dossiers lisibles maintenant (le catalogue les joue sur place) : [(slug, chemin, id)]."""
    kinds = _kinds()
    with _lock:
        es = [dict(e) for e in _index()["entries"].values()
              if e.get("category") == "standard" and e.get("state") == "ok" and e.get("folder") in kinds
              and _takes(kinds[e.get("folder")], e)]
    es.sort(key=lambda e: -(e.get("mtime") or 0))
    out, seen = [], set()
    for e in es:
        if e.get("slug") in seen or not os.path.isfile(e["path"]):
            continue
        seen.add(e.get("slug"))
        out.append((e["slug"], e["path"], e.get("id")))
    return out


def sig():
    """Pour la signature du cache des standards : change quand l'index OU le réglage des dossiers change (le type
    d'un dossier décide si ses standards sont proposés)."""
    out = 0.0
    for p in (_index_path(), CFG):
        try:
            out += os.path.getmtime(p)
        except OSError:
            pass
    return out


# ── adopter (§2.3) ────────────────────────────────────────────────────────────────────────────

class AdoptError(RuntimeError):
    pass


def adopt(path):
    """« Use on this golem » : la chanson du dossier est COPIÉE dans le golem, vérifiée en entier — chanson et Vocals
    par `songs.install_golem` (fusion, rattachement par empreinte), standard dans son rayon. Le fichier du dossier
    n'est pas touché. Rend {id, category, title, created, …}. Lève AdoptError."""
    from . import songs
    p = os.path.normpath(_norm(path))
    e = entry_of_path(p)
    if not e:
        raise AdoptError("this file is not in a song folder")
    if not os.path.isfile(p):
        raise AdoptError("the folder is offline — plug it in and try again")
    try:
        cat = G.category_of(p)
    except (G.GolemError, OSError, zipfile.BadZipFile) as ex:
        raise AdoptError(str(ex)) from ex
    if cat == "standard":
        res = _adopt_standard(p, e)
    else:
        _check_room(os.path.getsize(p))
        try:
            res = songs.install_golem(p)
        except songs.InstallError as ex:
            raise AdoptError(str(ex)) from ex
        res["category"] = cat
    log.info("adoptée depuis un dossier : %s (%s) <- %s" % (res.get("id"), cat, p))
    _changed()
    return res


def _check_room(size):
    """§4.1 : une adoption ne remplit pas le disque — refusée au-delà de 90 %, avec la taille."""
    try:
        du = shutil.disk_usage(C.SONGS_DIR if os.path.isdir(C.SONGS_DIR) else C.ROOT)
    except OSError:
        return
    if du.used + size > 0.9 * du.total:
        raise AdoptError("not enough room on this golem (%.0f MB needed, the disk would be over 90 %% full)"
                         % (size / 1e6))


def _adopt_standard(p, e):
    from . import standards as S
    slug = e.get("slug") or os.path.splitext(os.path.basename(p))[0]
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        raise AdoptError("not a standard name: %s" % slug)
    _check_room(os.path.getsize(p))
    os.makedirs(S.GOLEM_DIR, exist_ok=True)
    tmp = os.path.join(S.GOLEM_DIR, ".adopt-%s.golem" % slug)
    try:
        shutil.copyfile(p, tmp)
        G.verify(tmp)
        raw = json.loads(G.read_member(tmp, "chart/song.gsx").decode("utf-8"))
        if not (S.is_gsx(raw) or raw.get("Sections")):
            raise AdoptError("the chart is neither .gsx nor iReal")
        dest = os.path.join(S.GOLEM_DIR, slug + ".golem")
        created = not os.path.exists(dest)
        os.replace(tmp, dest)
    except (G.GolemError, OSError, ValueError) as ex:
        raise AdoptError(str(ex)) from ex
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    S.invalidate()
    return {"id": e.get("id"), "slug": slug, "category": "standard", "title": e.get("title"), "created": created}


# ── le cache de travail des chansons lues sur place (§4.3) ────────────────────────────────────

def prune_work(keep=None):
    """Les dossiers de travail des chansons LUES SUR PLACE (marqués `folder:` dans leur `.from`) au-delà du plafond :
    les plus anciens partent. Ceux des chansons du golem ne sont jamais comptés ici."""
    base = os.path.join(C.SONGS_DIR, ".work")
    rows = []
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for n in names:
        d = os.path.join(base, n)
        mark = os.path.join(d, ".from")
        try:
            if not open(mark, encoding="utf8").read().startswith("folder:"):
                continue
            size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs)
            rows.append((os.path.getmtime(mark), d, size))
        except OSError:
            continue
    total = sum(r[2] for r in rows)
    gone = 0
    for _, d, size in sorted(rows):
        if total <= WORK_CAP_BYTES:
            break
        if keep and os.path.abspath(d) == os.path.abspath(keep):
            continue
        shutil.rmtree(d, ignore_errors=True)
        total -= size
        gone += 1
    return gone


# ── l'explorateur (« + Add folder ») ──────────────────────────────────────────────────────────

# ── OÙ EST UN DOSSIER : ce disque, un autre disque, un disque EXTERNE, le RÉSEAU (page Storage, 2026-10-09) ────
# Lu dans le système, jamais deviné au chemin : Linux /proc/mounts (+ /sys pour l'USB), Windows GetDriveTypeW, macOS
# `mount`. Un dossier externe ou réseau ne prend PAS de place sur le golem — la page le dit.
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "sshfs", "davfs", "fuse.davfs2", "9p", "afpfs",
              "webdav", "fuse.rclone", "ceph", "glusterfs", "fuse.glusterfs"}
GVFS_NET = ("smb-share", "ftp", "sftp", "dav", "davs", "afp-volume", "nfs")


def _linux_mounts():
    out = []
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    mp = parts[1].replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")
                    out.append((mp, parts[2], parts[0]))
    except OSError:
        pass
    return out


def _mount_of(path, mounts):
    p = os.path.realpath(path)
    best = None
    for mp, fs, dev in mounts:
        if (p == mp or p.startswith(mp.rstrip("/") + "/")) and (not best or len(mp) > len(best[0])):
            best = (mp, fs, dev)
    return best


def _usb(dev):
    """Le périphérique bloc est-il branché en USB (ou amovible) ?"""
    name = os.path.basename(str(dev or ""))
    if not name or not str(dev).startswith("/dev/"):
        return False
    try:
        real = os.path.realpath("/sys/class/block/" + name)
        if "/usb" in real:
            return True
        disk = os.path.basename(os.path.dirname(real)) if os.path.isfile(os.path.join(real, "partition")) else name
        with open("/sys/block/%s/removable" % disk) as f:
            return f.read().strip() == "1"
    except OSError:
        return False


def location(path):
    """{"kind": this-disk | other-disk | external | network, "mount": point de montage}. Hors ligne : {"kind": None}."""
    p = os.path.realpath(_norm(path))
    try:
        same = os.path.isdir(p) and os.stat(p).st_dev == os.stat(C.ROOT).st_dev
    except OSError:
        return {"kind": None, "mount": None}
    if sys.platform.startswith("win"):
        try:
            import ctypes
            if p.startswith("\\\\"):
                return {"kind": "network", "mount": p}
            root = os.path.splitdrive(p)[0] + "\\"
            t = ctypes.windll.kernel32.GetDriveTypeW(root)
            kind = "network" if t == 4 else "external" if t == 2 else "this-disk" if same else "other-disk"
            return {"kind": kind, "mount": root}
        except Exception:
            return {"kind": "this-disk" if same else "other-disk", "mount": None}
    if sys.platform == "darwin":
        try:
            import subprocess
            mp = subprocess.run(["df", "-P", p], capture_output=True, text=True, timeout=3).stdout.splitlines()[-1].split()[-1]
            out = subprocess.run(["mount"], capture_output=True, text=True, timeout=3).stdout
            line = next((l for l in out.splitlines() if " on %s (" % mp in l), "")
            fs = line.split("(")[-1].split(",")[0] if "(" in line else ""
            kind = ("network" if fs in ("smbfs", "nfs", "afpfs", "webdav") else "this-disk" if same
                    else "external" if mp.startswith("/Volumes/") else "other-disk")
            return {"kind": kind, "mount": mp}
        except Exception:
            return {"kind": "this-disk" if same else "other-disk", "mount": None}
    m = _mount_of(p, _linux_mounts())
    if same:
        return {"kind": "this-disk", "mount": m[0] if m else "/"}
    if not m:
        return {"kind": "other-disk", "mount": None}
    mp, fs, dev = m
    if fs in NETWORK_FS:
        return {"kind": "network", "mount": mp}
    if fs == "fuse.gvfsd-fuse":                       # Nautilus / gio : /run/user/UID/gvfs/<schéma>:…
        share = p[len(mp):].lstrip("/").split("/")[0]
        return {"kind": "network" if share.startswith(GVFS_NET) else "external", "mount": os.path.join(mp, share)}
    if _usb(dev) or mp.startswith(("/media/", "/run/media/")):
        return {"kind": "external", "mount": mp}
    return {"kind": "other-disk", "mount": mp}


def _disk(path, timeout=2.0):
    """{total, free} du disque qui porte `path`, sans jamais bloquer plus de `timeout` (un NAS qui dort)."""
    res = {}

    def run():
        try:
            du = shutil.disk_usage(path)
            res.update(total=du.total, free=du.free)
        except OSError:
            pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    return res


def _gvfs_label(name):
    """« smb-share:server=starnas.local,share=music » -> « music on starnas.local »."""
    kv = dict(x.split("=", 1) for x in name.split(":", 1)[-1].split(",") if "=" in x)
    host = kv.get("server") or kv.get("host") or ""
    return ("%s on %s" % (kv["share"], host)) if kv.get("share") else (host or name)


def display_name(path):
    """Le chemin tel qu'on le lit : un partage monté par gvfs (« /run/user/1000/gvfs/smb-share:server=nas,share=music/jazz »)
    devient « music on nas / jazz » ; le dossier personnel devient « ~ »."""
    p = str(path or "")
    i = p.find("/gvfs/")
    if i >= 0:
        rest = p[i + len("/gvfs/"):]
        share, _, sub = rest.partition("/")
        return _gvfs_label(share) + (" / " + sub if sub else "")
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p == home or p.startswith(home + os.sep) else p


def roots():
    """Les points de départ de l'explorateur : le dossier personnel, les disques branchés, les partages réseau montés.
    [{path, label, kind, total?, free?}]."""
    home = os.path.expanduser("~")
    cand = [(home, "Home")]
    if sys.platform.startswith("win"):
        import string
        cand += [("%s:\\" % L, "%s:" % L) for L in string.ascii_uppercase if os.path.isdir("%s:\\" % L)]
    elif sys.platform == "darwin":
        try:
            for n in sorted(os.listdir("/Volumes")):
                pth = os.path.join("/Volumes", n)
                if os.path.realpath(pth) != "/":
                    cand.append((pth, n))
        except OSError:
            pass
    else:
        user = os.path.basename(home)
        for base in ("/media/" + user, "/run/media/" + user, "/mnt"):
            try:
                for n in sorted(os.listdir(base)):
                    pth = os.path.join(base, n)
                    if os.path.isdir(pth):
                        cand.append((pth, n))
            except OSError:
                pass
        gv = "/run/user/%d/gvfs" % os.getuid()
        try:
            for n in sorted(os.listdir(gv)):
                cand.append((os.path.join(gv, n), _gvfs_label(n)))
        except OSError:
            pass
    out, seen = [], set()
    for pth, label in cand:
        if pth in seen:
            continue
        seen.add(pth)
        loc = location(pth)
        out.append({"path": pth, "label": label, "kind": loc["kind"] or "other-disk", **_disk(pth, 1.5)})
    return out


# les dossiers système d'un disque Windows / macOS : jamais proposés (un disque externe en NTFS en porte toujours)
_SYSTEM_DIRS = {"System Volume Information", "RECYCLER", "lost+found", "Recovered files"}


def _count_golem(p, budget):
    """Combien de `.golem` sous `p` (3 niveaux, sans dossiers cachés), dans le temps qui reste : (n, complet)."""
    n, stack = 0, [(p, 0)]
    while stack:
        if time.monotonic() > budget:
            return n, False
        d, depth = stack.pop()
        try:
            with os.scandir(d) as it:
                for x in it:
                    if x.name.startswith("."):
                        continue
                    try:
                        if x.is_dir(follow_symlinks=False):
                            if depth < 3:
                                stack.append((x.path, depth + 1))
                        elif x.name.lower().endswith(".golem"):
                            n += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return n, True


def browse(path=None):
    """Les sous-dossiers de `path` (aucun nom de fichier) avec, pour chacun, combien de `.golem` il porte (3 niveaux,
    1,5 s au plus pour toute la liste : un NAS n'est jamais attendu) et s'il peut être ajouté. Sans `path` : les racines."""
    if not path:
        return {"path": None, "parent": None, "roots": roots(), "dirs": [], "golem_here": 0}
    p = _norm(path)
    if not os.path.isdir(p):
        raise FolderError("not found")
    dirs, n = [], 0
    try:
        with os.scandir(p) as it:
            for x in it:
                if x.name.startswith((".", "$")) or x.name in _SYSTEM_DIRS:
                    continue
                try:
                    if x.is_dir(follow_symlinks=False):
                        dirs.append({"name": x.name, "path": os.path.join(p, x.name)})
                    elif x.name.lower().endswith(".golem"):
                        n += 1
                except OSError:
                    continue
    except OSError:
        raise FolderError("not readable")
    dirs.sort(key=lambda d: d["name"].lower())
    dirs = dirs[:500]
    budget = time.monotonic() + 1.5
    for d in dirs[:60]:
        d["golem"], d["complete"] = _count_golem(d["path"], budget)
        d["can_add"] = _can_add(d["path"])
    parent = os.path.dirname(p)
    return {"path": p, "parent": parent if parent != p else None, "dirs": dirs, "golem_here": n,
            "can_add": _can_add(p), "location": location(p)}


def _can_add(p):
    try:
        check_folder(p)
        return {"ok": True}
    except FolderError as e:
        return {"ok": False, "why": str(e)}
