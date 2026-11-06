# SPDX-License-Identifier: GPL-3.0-or-later
"""L'ACCUEIL AU DÉMARRAGE (maquette mockups/startup-home.html, validée le 2026-10-11) : ce que golem ouvre
sur /live une fois le moteur et la carte prêts. UN seul accueil ; trois politiques :
  - "bank0" (défaut, le comportement d'avant) : la bank 00 de la setlist active ;
  - "last"  : ce que /live avait à l'arrêt (presets/.live.json : preset, scène, ligne de setlist) ;
  - "home"  : un objet posé depuis son menu ⋯ — {kind: preset|patch|song|setlist|bank, …}.
Posé depuis l'objet, lu et changé depuis /live (le chip ⌂). Rien dans Settings.

État local : config/.startup.json — {"policy": "...", "home": {...}|null}. Un accueil dont l'objet a disparu
retombe sur la bank 00, et le dit (`missing`)."""
import json
import os
import threading

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("startup")
PATH = os.path.join(C.CONFIG_DIR, ".startup.json")
KINDS = ("preset", "patch", "song", "setlist", "bank")
POLICIES = ("bank0", "last", "home")
_lock = threading.Lock()
_cache = {"mtime": None, "doc": None}


def get():
    try:
        m = os.path.getmtime(PATH)
    except OSError:
        return {"policy": "bank0", "home": None}
    if _cache["mtime"] == m and _cache["doc"] is not None:
        return dict(_cache["doc"])
    try:
        with open(PATH, encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception:
        d = {}
    doc = {"policy": d.get("policy") if d.get("policy") in POLICIES else "bank0",
           "home": d.get("home") if isinstance(d.get("home"), dict) and d["home"].get("kind") in KINDS else None}
    if doc["policy"] == "home" and not doc["home"]:
        doc["policy"] = "bank0"
    _cache.update(mtime=m, doc=dict(doc))
    return doc


def _save(doc):
    from .store import _write_json_atomic
    _write_json_atomic(PATH, doc, indent=1)
    _cache.update(mtime=None, doc=None)


def set_home(home):
    """Pose l'accueil : {kind, id, name, setlist?, line?, slot?}. Remplace le précédent (un seul), politique "home"."""
    kind = (home or {}).get("kind")
    if kind not in KINDS:
        raise ValueError("kind: preset | patch | song | setlist | bank")
    h = {"kind": kind, "name": str((home or {}).get("name") or "")[:120]}
    if kind in ("preset", "patch", "setlist"):
        if not (home or {}).get("id"):
            raise ValueError("id required")
        h["id"] = str(home["id"])
    if kind == "song":
        if not (home or {}).get("setlist") or not (home or {}).get("line"):
            raise ValueError("song: setlist and line required")
        h.update(setlist=str(home["setlist"]), line=str(home["line"]), id=str(home.get("id") or ""))
    if kind == "bank":
        try:
            h["slot"] = int((home or {}).get("slot"))
        except (TypeError, ValueError):
            raise ValueError("bank: slot required")
        if (home or {}).get("setlist"):
            h["setlist"] = str(home["setlist"])
    with _lock:
        prev = get().get("home")
        _save({"policy": "home", "home": h})
    log.info(f"accueil : {kind} « {h['name'] or h.get('id')} »" + (f" (remplace « {prev.get('name')} »)" if prev else ""))
    return describe()


def set_policy(policy):
    if policy not in POLICIES:
        raise ValueError("policy: bank0 | last | home")
    with _lock:
        d = get()
        if policy == "home" and not d.get("home"):
            raise ValueError("no startup object set — pick one from its ⋯ menu first")
        d["policy"] = policy
        _save(d)
    log.info(f"politique de démarrage : {policy}")
    return describe()


def clear_home():
    with _lock:
        _save({"policy": "bank0", "home": None})
    log.info("accueil retiré : bank 00")
    return describe()


def is_home(kind, id_=None, setlist=None, line=None):
    h = get().get("home") or {}
    if h.get("kind") != kind:
        return False
    if kind == "song":
        return h.get("setlist") == setlist and h.get("line") == line
    if kind == "bank":
        return str(h.get("slot")) == str(id_)
    return h.get("id") == id_


# ── l'objet existe-t-il encore ? ──────────────────────────────────────────────────────────────────────────
def _line_index(sl, lid):
    for i, ln in enumerate((sl or {}).get("lines") or []):
        if isinstance(ln, dict) and ln.get("id") == lid:
            return i
    return None


def _missing(h):
    """None si l'objet de l'accueil existe, sinon la raison (en anglais : c'est l'écran qui la montre)."""
    try:
        from . import store, setlists as _sl
        k = h.get("kind")
        if k in ("preset", "patch"):
            return None if store.load_preset(h.get("id")) else "not found"
        if k == "setlist":
            return None if _sl.load(h.get("id")) else "setlist not found"
        if k == "song":
            sl = _sl.load(h.get("setlist"))
            if not sl:
                return "its setlist is gone"
            return None if _line_index(sl, h.get("line")) is not None else "no longer in its setlist"
        if k == "bank":
            sl = _sl.load(h.get("setlist") or _sl.active_id()) or {}
            pres = sl.get("presets") or []
            return None if 0 <= int(h.get("slot", -1)) < len(pres) and pres[h["slot"]] else "that bank is empty"
    except Exception as e:
        _swallowed(e)
        return None
    return None


# ── LE SNAPSHOT NE RECHARGE RIEN (PC Windows neuf, 2026-11-03) ──────────────────────────────────────────────────────
# describe() est appelé par CHAQUE snapshot (RigState.snapshot, donc chaque broadcast). _missing d'un preset le
# recharge ET le migre — sonde de carte comprise. L'accueil d'usine (config/.startup.json, alors factory-chill-jazz) le
# faisait sur toute install neuve : sous Windows, un snapshot coûtait plus que l'écart entre deux broadcasts, la
# boucle asyncio ne rendait plus la main et le bridge ne répondait plus (97 % du temps dans ce load_preset, py-spy).
# La réponse ne change que si l'accueil change ou si un objet apparaît / disparaît : la clé porte l'accueil, la date
# des DOSSIERS qui le contiennent (une création, une suppression ou un os.replace — _write_json_atomic, le chemin
# d'écriture de tous les presets — la font bouger) et celle des FICHIERS de l'objet (une écriture en place).
# _missing ne lit QUE l'existence : load_preset rend le preset que ses captures soient installées ou non, et l'input
# map n'y décide de rien — ni assets/ ni la carte n'entrent dans la clé.
_missing_cache = {"key": None, "val": None}


def _object_files(h):
    from . import patches as _patches, setlists as _sl
    from .store import _safe_id
    k, out = h.get("kind"), []
    if k in ("preset", "patch") and h.get("id"):
        pid = str(h["id"])
        out.append(_patches._path(pid[len("patch:"):]) if pid.startswith("patch:")
                   else os.path.join(C.PRESETS_DIR, f"{_safe_id(pid)}.json"))
    for sid in (h.get("setlist"), h.get("id") if k == "setlist" else None):
        if sid:
            out.append(_sl._path(sid))
    if k == "bank" and not h.get("setlist"):
        out.append(_sl._active_cfg())            # la bank d'une setlist ACTIVE : changer de setlist change la réponse
    return out


def _rev(h):
    from . import patches as _patches
    out = []
    for p in (C.PRESETS_DIR, C.SETLISTS_DIR, _patches.PATCHES_DIR, *_object_files(h)):
        try:
            out.append(os.stat(p).st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def _missing_cached(h):
    key = (json.dumps(h, sort_keys=True), _rev(h))
    c = _missing_cache
    if c["key"] == key:
        return c["val"]
    val = _missing(h)
    c.update(key=key, val=val)
    return val


def describe():
    d = get()
    h = d.get("home")
    if h:
        h = dict(h, missing=_missing_cached(h))
    return {"policy": d["policy"], "home": h}


# ── au démarrage ──────────────────────────────────────────────────────────────────────────────────────────
def first_slot(sl=None):
    """La PREMIÈRE bank qui porte quelque chose (2026-10-18) : « bank 00 » ouvrait une bank VIDE quand la setlist
    commence par un trou — le musicien arrivait sur rien. Rend 0 si la setlist est vide ou introuvable."""
    from . import setlists as _sl
    sl = sl if sl is not None else (_sl.load(_sl.active_id()) or {})
    for i, ln in enumerate((sl or {}).get("lines") or (sl or {}).get("presets") or []):
        if _sl.pid_of(ln):
            return i
    return 0

def plan():
    """Ce que boot_recall doit faire — None = la bank 00 d'aujourd'hui. Une liste d'étapes :
    ("setlist", sid) | ("slot", n) | ("recall", pid, scene)."""
    d = get()
    if d["policy"] == "last":
        try:
            with open(os.path.join(C.PRESETS_DIR, ".live.json"), encoding="utf-8") as f:
                live = json.load(f) or {}
        except Exception:
            live = {}
        if not live.get("preset"):
            log.info("démarrage : rien de noté à l'arrêt — bank 00")
            return None
        steps = []
        if live.get("setlist"):
            steps.append(("setlist", live["setlist"]))
        if live.get("line"):
            from . import setlists as _sl
            sl = _sl.load(live.get("setlist") or _sl.active_id()) or {}
            idx = _line_index(sl, live["line"])
            if idx is not None and _sl.pid_of((sl.get("lines") or [])[idx]) == live["preset"]:
                steps.append(("slot", idx))
                return steps
        steps.append(("recall", live["preset"], live.get("scene") or "A"))
        return steps
    if d["policy"] != "home" or not d.get("home"):
        return None
    h = d["home"]
    why = _missing(h)
    if why:
        log.warning(f"accueil « {h.get('name') or h.get('id')} » : {why} — bank 00 à la place")
        return None
    k = h["kind"]
    if k in ("preset", "patch"):
        return [("recall", h["id"], "A")]
    if k == "setlist":
        from . import setlists as _sl
        return [("setlist", h["id"]), ("slot", first_slot(_sl.load(h["id"]) or {}))]
    if k == "song":
        from . import setlists as _sl
        idx = _line_index(_sl.load(h["setlist"]), h["line"])
        return [("setlist", h["setlist"]), ("slot", idx)]
    if k == "bank":
        return ([("setlist", h["setlist"])] if h.get("setlist") else []) + [("slot", int(h["slot"]))]
    return None


def apply(steps):
    """Exécute un plan (hors boucle asyncio, comme tout rappel). Rend True si le dernier pas a réussi."""
    from . import recall, setlists as _sl
    ok = False
    for step in steps or []:
        if step[0] == "setlist":
            r = _sl.set_active(step[1])
            ok = bool(r.get("ok"))
            if not ok:
                log.warning(f"démarrage : {r.get('error')}")
                return False
        elif step[0] == "slot":
            ok = bool(recall.do_recall_slot(int(step[1])))
        elif step[0] == "recall":
            ok = bool(recall.do_recall(step[1], step[2]))
    log.info(f"démarrage : accueil {'joué' if ok else 'REFUSÉ'} — {steps}")
    return ok
