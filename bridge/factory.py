# SPDX-License-Identifier: GPL-3.0-or-later
"""L'USINE DU GOLEM (docs/factory.md) : la source VERSIONNÉE des patches, presets, setlists et grilles d'usine, et sa pose
sur un golem.

Les dossiers où ces objets VIVENT — library/patches/, presets/, setlists/, library/standards/golem/ — sont de l'état
local, hors Git (CLAUDE.md, règle 2) : un golem ne commite pas ce que son utilisateur change en jouant. L'usine a donc sa
propre source, `library/factory/<sorte>/`, suivie par Git, et le golem POSE au démarrage ce qui lui manque :

  - jamais d'écrasement d'une RETOUCHE : un objet déjà posé n'est remplacé que s'il est, octet pour octet (fins de ligne
    normalisées), une ANCIENNE version d'usine — l'historique livré `library/factory/history.json` (tools/gen-factory-history.py)
    les connaît toutes. Retouché, il reste tel quel et `edited()` le signale : « Reset to factory » le remplace sur demande
    (2026-10-22 : un golem posé le 19 jouait 37 objets d'usine périmés, et sa setlist d'usine ignorait le 9e preset) ;
  - jamais de résurrection : ce qui a été posé une fois est noté (presets/.factory.json) ; un objet d'usine que
    l'utilisateur a supprimé ne revient pas en douce au démarrage suivant. « Restore factory content » (phase 4,
    docs/factory.md §6) repassera par `seed(force_ids=…)`.

Le verrou (lecture seule, « Save as mine ») est la phase 4 : ici, seulement la livraison."""
import hashlib
import json
import os
import shutil

from . import config as C
from .golog import get

log = get("factory")

SRC = os.path.join(C.ROOT, "library", "factory")
# sorte -> (dossier source dans library/factory, dossier de vie, extension)
KINDS = {
    "patches": ("patches", os.path.join(C.ROOT, "library", "patches"), ".json"),
    "presets": ("presets", C.PRESETS_DIR, ".json"),
    "setlists": ("setlists", C.SETLISTS_DIR, ".json"),
    "standards": ("standards", os.path.join(C.ROOT, "library", "standards", "golem"), ".golem"),
    # les GROOVES d'usine (2026-10-13) : composés par tools/make-factory-grooves.py, à nous. Sans eux, un golem neuf
    # n'a AUCUN groove et le bloc Drum Machine n'a rien à proposer (library/grooves/ est de l'état local).
    "grooves": ("grooves", os.path.join(C.ROOT, "library", "grooves"), ".mid"),
    # les BANQUES DX7 d'usine (2026-10-14) : SynprezFM, telles que Dexed (GPL-3) les livre — library/factory/dx7/CREDITS.md.
    # Les banques d'origine du rack (ROM Yamaha, cartouches de la communauté) ne se redistribuaient pas.
    "dx7": ("dx7", os.path.join(C.ROOT, "library", "dx7"), ".syx"),
    # les CHANSONS d'usine (2026-10-20) : une chanson écrite de bout en bout — fiche, arrangement, pochette —, faite par
    # tools/make-factory-song.py. À nous, jamais poussée vers golem.fm (songs.sync_of : `factory`).
    "songs": ("songs", C.SONGS_DIR, ".golem"),
}
LEDGER = os.path.join(C.PRESETS_DIR, ".factory.json")
# toutes les versions qu'une release a pu poser, par fichier : {"<sorte>/<fichier>": [sha256, …]} — fait par
# tools/gen-factory-history.py depuis Git ; tests/test_factory.py exige que la version courante y soit
HISTORY = os.path.join(SRC, "history.json")


def _sha(path):
    """Empreinte d'un fichier, fins de ligne normalisées (core.autocrlf pose les JSON en CRLF sous Windows)."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


# CE QUE LA MACHINE ÉCRIT DANS UN OBJET D'USINE sans que la personne y touche (2026-10-24) : un rack Windows avait 9 objets
# « retouchés », dont des patches que personne n'avait ouverts — refresh_deps() y avait écrit les `deps` de SA bibliothèque
# (poids d'une IR locale, capture absente), le Designer les liaisons d'entrée de SA carte, le Rec SA config. Bloqués, ils
# ne suivaient plus l'usine. L'empreinte CANONIQUE les ignore ; tout le reste (chaîne, réglages, scènes) reste une retouche.
_LOCAL_TOP = ("deps", "deps_sig", "unresolved")
_LOCAL_LANE = ("in_sel", "in_name", "in_role", "in_nth", "bind_error")
_LOCAL_FALSY = ("stereo", "disabled")                   # `false` écrit par l'écran = absent dans l'usine


def canon_sha(data, ext=".json"):
    """Empreinte d'un objet d'usine (octets) sans ce que la machine y écrit. None hors JSON ou illisible."""
    if ext != ".json":
        return None
    try:
        d = json.loads(data)
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    for k in _LOCAL_TOP:
        d.pop(k, None)
    if isinstance(d.get("config"), dict):
        d["config"].pop("rec", None)
    for lane in d.get("lanes") or []:
        if isinstance(lane, dict):
            for k in _LOCAL_LANE:
                lane.pop(k, None)
            for k in _LOCAL_FALSY:
                if lane.get(k) in (False, None):
                    lane.pop(k, None)
    return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _canon_file(path, ext):
    if ext != ".json":
        return None
    try:
        with open(path, "rb") as f:
            return canon_sha(f.read(), ext)
    except OSError:
        return None


def carry_local(new, old):
    """La version d'usine `new`, avec les liaisons de CETTE machine reprises de la copie posée `old` (dicts)."""
    out = json.loads(json.dumps(new))
    olds = {lane.get("id"): lane for lane in old.get("lanes") or [] if isinstance(lane, dict)}
    for lane in out.get("lanes") or []:
        prev = olds.get(lane.get("id")) if isinstance(lane, dict) else None
        if prev:
            lane.update({k: prev[k] for k in _LOCAL_LANE if k in prev})
    rec = (old.get("config") or {}).get("rec") if isinstance(old.get("config"), dict) else None
    if rec is not None:
        out["config"] = dict(out.get("config") or {}, rec=rec)
    return out


def _status(sub, fn, ext, target, hist):
    """État d'un objet posé : « current », « old » (ancienne version intacte), « old-local » (ancienne version, seules
    les écritures de la machine diffèrent) ou « edited »."""
    src = os.path.join(SRC, sub, fn)
    have = _sha(target)
    if have == _sha(src):
        return "current"
    if have in set(hist.get(f"{sub}/{fn}") or []):
        return "old"
    mine = _canon_file(target, ext)
    if mine is None:
        return "edited"
    if mine == _canon_file(src, ext):
        return "current"
    if mine in set(hist.get(f"canon:{sub}/{fn}") or []):
        return "old-local"
    return "edited"


def _history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ledger():
    try:
        with open(LEDGER, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def catalog():
    """{sorte: [nom de fichier, …]} — ce que l'usine livre."""
    out = {}
    for kind, (sub, _dst, ext) in KINDS.items():
        d = os.path.join(SRC, sub)
        try:
            out[kind] = sorted(f for f in os.listdir(d) if f.endswith(ext) and not f.startswith("."))
        except OSError:
            out[kind] = []
    return out


# ── VISIBILITÉ DE L'USINE (Settings ▸ Content ▸ Factory, 2026-10-13) ───────────────────────────────────────────
# L'usine se MASQUE, elle ne se supprime pas. Un interrupteur par sorte ; masqué = les pages de navigation ne RENDENT
# pas ces objets (filtrés avant le rendu — jamais un `hidden` qu'une autre feuille réafficherait). Les routes listent
# toujours tout, marqué `factory: true` : ce qui résout un objet par son id (le preset qui joue, un kit utilisé par un
# preset visible) ne doit jamais le perdre. État local (presets/), hors Git.
VIS_KINDS = ("patches", "presets", "setlists", "kits", "grooves", "standards")
VIS_FILE = os.path.join(C.PRESETS_DIR, ".factory-show.json")


def visibility():
    try:
        with open(VIS_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {k: bool(d.get(k, True)) for k in VIS_KINDS}


def set_visibility(changes):
    from .store import _write_json_atomic
    cur = visibility()
    for k, v in (changes or {}).items():
        if k in VIS_KINDS:
            cur[k] = bool(v)
    _write_json_atomic(VIS_FILE, cur, indent=1)
    return cur


def ids(kind):
    """Les ids d'usine d'une sorte : les fichiers de library/factory/<sorte>/ (kits : les graines kits-factory)."""
    if kind == "kits":
        try:
            return {f[:-5] for f in os.listdir(os.path.join(C.ROOT, "library", "kits-factory")) if f.endswith(".json")}
        except OSError:
            return set()
    ext = (KINDS.get(kind) or (None, None, ".json"))[2]
    return {f[: -len(ext)] for f in catalog().get(kind) or []}


def removed():
    """Ce que l'usine a posé un jour et que l'utilisateur a supprimé depuis : [{kind, file, id}] (rien n'est posé)."""
    led, out = _ledger(), []
    for kind, files in catalog().items():
        _sub, dst, ext = KINDS[kind]
        for fn in files:
            if fn in set(led.get(kind) or []) and not os.path.exists(os.path.join(dst, fn)):
                out.append({"kind": kind, "file": fn, "id": fn[: -len(ext)],
                            "name": _display_name(os.path.join(SRC, KINDS[kind][0], fn)) or fn[: -len(ext)]})
    return out


def restore(files=None):
    """Remet ce qui a été supprimé (tout, ou les fichiers nommés). C'est le « Restore factory content »."""
    want = [r["file"] for r in removed() if not files or r["file"] in set(files)]
    return seed(force_ids=want) if want else {"placed": [], "present": 0, "removed_by_user": []}


def edited():
    """Les objets d'usine posés qui ne sont NI la version courante NI une ancienne version : retouchés ici (par la
    personne, ou réécrits par le rack en jouant). [{kind, file, id}] — rien n'est touché."""
    hist, out = _history(), []
    for kind, files in catalog().items():
        sub, dst, ext = KINDS[kind]
        for fn in files:
            target = os.path.join(dst, fn)
            if not os.path.exists(target):
                continue
            if _status(sub, fn, ext, target, hist) == "edited":
                out.append({"kind": kind, "file": fn, "id": fn[: -len(ext)],
                            "name": _display_name(os.path.join(SRC, sub, fn)) or fn[: -len(ext)]})
    return out


def _display_name(path):
    """Le nom que l'écran montre (« Chill Jazz », « Golem Rising »), pas l'id de fichier."""
    try:
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as f:
                return (json.load(f) or {}).get("name")
        if path.endswith(".golem"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                d = json.loads(z.read("golem.json"))
            return d.get("title") or d.get("name")
    except (OSError, ValueError, KeyError, AttributeError):
        return None
    return None


def reset(files=None):
    """« Reset to factory » : remplace les objets retouchés (tous, ou les fichiers nommés) par la version d'usine.
    La retouche est PERDUE — l'écran le dit avant. Rend {reset: [...]}."""
    want = {r["file"] for r in edited() if not files or r["file"] in set(files)}
    done = []
    for kind, fns in catalog().items():
        sub, dst, _ext = KINDS[kind]
        for fn in fns:
            if fn in want:
                shutil.copyfile(os.path.join(SRC, sub, fn), os.path.join(dst, fn))
                done.append(f"{kind}/{fn}")
    if done:
        log.info(f"usine : {len(done)} objet(s) remis à l'usine — " + ", ".join(done))
        try:
            from . import standards
            standards.invalidate()
        except Exception:
            pass
    return {"reset": done}


def mark(kind, items, key="id"):
    """Pose `factory: true` sur les objets d'usine d'une liste (sans rien retirer). Rend la liste."""
    have = ids(kind)
    for it in items or []:
        if isinstance(it, dict) and str(it.get(key)) in have:
            it["factory"] = True
    return items


def seed(force_ids=None):
    """Pose ce qui manque. Rend {posés: [...], déjà là: n, retirés par l'utilisateur: [...]}.
    `force_ids` : des noms de fichier à reposer même s'ils ont déjà été posés (la restauration, plus tard)."""
    from .store import _write_json_atomic
    led = _ledger()
    force = set(force_ids or [])
    hist = _history()
    placed, updated, skipped_user, present = [], [], [], 0
    for kind, files in catalog().items():
        sub, dst, _ext = KINDS[kind]
        seen = set(led.get(kind) or [])
        for fn in files:
            target = os.path.join(dst, fn)
            if os.path.exists(target):
                present += 1
                seen.add(fn)
                src = os.path.join(SRC, sub, fn)
                # une ANCIENNE version d'usine intacte suit l'usine ; une retouche ne bouge pas (edited())
                status = _status(sub, fn, _ext, target, hist)
                if status == "old":
                    shutil.copyfile(src, target)
                    updated.append(f"{kind}/{fn}")
                elif status == "old-local":
                    # la nouvelle version, sans perdre l'entrée branchée ni la config du Rec de CETTE machine
                    with open(src, encoding="utf-8") as f, open(target, encoding="utf-8") as g:
                        merged = carry_local(json.load(f), json.load(g))
                    _write_json_atomic(target, merged, newline=True)
                    updated.append(f"{kind}/{fn}")
                continue
            if fn in seen and fn not in force:
                skipped_user.append(f"{kind}/{fn}")          # posé un jour, supprimé depuis : on ne le ressuscite pas
                continue
            os.makedirs(dst, exist_ok=True)
            shutil.copyfile(os.path.join(SRC, sub, fn), target)
            seen.add(fn)
            placed.append(f"{kind}/{fn}")
        led[kind] = sorted(seen)
    if placed or led != _ledger():
        _write_json_atomic(LEDGER, led, indent=1)
    if any(x.startswith("grooves/") for x in placed):
        _groove_meta([x.split("/", 1)[1][:-4] for x in placed if x.startswith("grooves/")])
    if updated:
        log.info(f"usine : {len(updated)} objet(s) mis à jour (ancienne version intacte) — " + ", ".join(updated))
    if placed or updated:
        if placed:
            log.info(f"usine : {len(placed)} objet(s) posé(s) — " + ", ".join(placed))
        try:
            from . import standards
            standards.invalidate()
        except Exception:
            pass
    return {"placed": placed, "updated": updated, "present": present, "removed_by_user": skipped_user}


def _groove_meta(ids):
    """Les métadonnées (nom, pack « golem », genre, tempo, kit conseillé) des grooves qu'on vient de POSER, dans le
    sidecar de la bibliothèque — sans toucher à celles des autres grooves."""
    try:
        with open(os.path.join(SRC, "grooves", "meta.json"), encoding="utf-8") as f:
            src = json.load(f)
    except (OSError, ValueError):
        return
    from . import grooves
    cur = grooves._read_meta()
    for gid in ids:
        if gid in src and gid not in cur:
            cur[gid] = src[gid]
    grooves._write_meta(cur)


# ── LES CAPTURES D'USINE (docs/factory.md §0.1 : des LIENS TONE3000, téléchargés en un clic s'il le souhaite) ─────────
# Les patches d'usine nomment leurs captures (`ref` = id TONE3000, `model` = le modèle précis). Le golem ne les livre
# pas : il les télécharge avec le compte TONE3000 de l'UTILISATEUR (OAuth, Settings ▸ Connect ▸ TONE3000), par le pipeline du « + New »
# (routes_t3k._install_worker). Un tone déjà au catalogue garde ses modèles : on demande l'UNION, jamais moins.
_CAP_TYPES = ("amp", "amp-nam", "cab", "pedal-nam", "preamp-nam", "comp-nam")
_DL = {"phase": "idle", "done": 0, "total": 0, "current": None, "failed": [], "installed": []}
_dl_lock = __import__("threading").Lock()


def _factory_refs():
    """{tone id: {model ids}} des patches d'usine LIVRÉS (library/factory/patches)."""
    refs = {}
    for fn in catalog().get("patches") or []:
        try:
            with open(os.path.join(SRC, "patches", fn), encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue

        def walk(o):
            if isinstance(o, dict):
                if o.get("type") in _CAP_TYPES and o.get("ref"):
                    tid = str(o["ref"]).split("/")[-1].replace("t3k:", "")
                    if tid.isdigit():
                        refs.setdefault(tid, set())
                        if o.get("model") is not None:
                            refs[tid].add(str(o["model"]))
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(doc)
    return refs


def captures():
    """Ce qu'il faut à l'usine, ce qui est là, ce qui manque — lu sur le disque, pas supposé."""
    from .resolver import _components, _resolve, _tones_index
    comps, idx = _components(), _tones_index()
    missing, present = [], 0
    for tid, models in sorted(_factory_refs().items(), key=lambda x: int(x[0])):
        want = models or {None}
        gone = [m for m in want if not ((p := _resolve(tid, comps, m)) and (not os.path.isabs(p) or os.path.isfile(p))
                                        and (m is None or any(str(x.get("id")) == m for x in (idx.get(tid) or {}).get("models") or [])))]
        if gone:
            missing.append({"tone": int(tid), "models": sorted(x for x in gone if x), "title": (idx.get(tid) or {}).get("title")})
        else:
            present += 1
    return {"total": present + len(missing), "present": present, "missing": missing}


def download_status():
    return dict(_DL, failed=list(_DL["failed"]), installed=list(_DL["installed"]))


def start_download():
    """Lance le téléchargement des captures manquantes (un thread, une à la fois — le pipeline TONE3000 n'en tient
    qu'une). Rend l'état ; refuse si une installation tourne déjà."""
    import threading
    from . import routes_t3k as T
    with _dl_lock:
        if _DL["phase"] == "running" or T._ST.get("phase") in ("meta", "download", "classify"):
            return {"ok": False, "error": "a TONE3000 download is already running"}
        todo = captures()["missing"]
        _DL.update(phase="running", done=0, total=len(todo), current=None, failed=[], installed=[])
    threading.Thread(target=_download_worker, args=(todo,), daemon=True).start()
    return {"ok": True, **download_status()}


def _download_worker(todo):
    from . import routes_t3k as T
    from .resolver import _tones_index
    for i, item in enumerate(todo):
        tid = item["tone"]
        _DL.update(current=item.get("title") or f"tone {tid}")
        have = [str(m.get("id")) for m in ((_tones_index().get(str(tid)) or {}).get("models") or [])]
        want = sorted(set(have) | set(item.get("models") or []))
        ids = [int(x) for x in want if str(x).isdigit()] or None
        try:
            T._ST.update(phase="meta", tone=tid, done=0, total=0, msg="starting…", error=None)
            T._install_worker(tid, ids)
            if T._ST.get("phase") == "error":
                raise RuntimeError(T._ST.get("error") or "install failed")
            _DL["installed"].append(tid)
        except Exception as e:
            _DL["failed"].append({"tone": tid, "title": item.get("title"), "why": str(e)[:200]})
        _DL.update(done=i + 1)
    _DL.update(phase="done", current=None)
    log.info(f"usine : captures — {len(_DL['installed'])} téléchargée(s), {len(_DL['failed'])} en échec")
