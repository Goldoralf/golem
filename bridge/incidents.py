# SPDX-License-Identifier: GPL-3.0-or-later
"""LES INCIDENTS ET COMMENT ILS ONT FINI (docs/assistant.md §3.1, maquette mockups/health-fix.html validée le
2026-10-20).

Les rapports de diagnostic disaient déjà QU'une panne était arrivée ; ils ne disaient pas COMMENT elle avait fini. Un
incident s'ouvre quand un fait de Health passe au rouge (ou à l'orange pour ceux qui le méritent), quand « Why no
sound? » ou la vérification de première installation rendent un verdict rouge. Il se ferme par le premier de :

  action   — une réparation du registre (bridge/fixes.py) a tourné et sa vérification est passée au vert ;
  restart  — vert après un redémarrage de REAPER ou du bridge ;
  outside  — vert SANS rien de golem entre les deux : le musicien a fait ce que golem ne voit pas (un câble, un
             bouton) — un tap facultatif le dit (`hint` : cable · gain · power · other) ;
  open     — toujours rouge à la fin de la session (dit tel quel dans le paquet de session).

Chaque étape part dans la chronologie de diagnostic (`incident`, `resolution` ; `fix` vient de fixes.py) : des
TYPES et des CODES, jamais de texte libre ni de nom. Le titre et le détail lisibles restent sur cette machine
(config/.incidents.json, local, 30 jours) : ils nomment le preset joué."""
import contextlib
import json
import os
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("incidents")
PATH = lambda: os.path.join(C.CONFIG_DIR, ".incidents.json")   # noqa: E731 — le dossier de config du MOMENT
KEEP_S = 30 * 86400
KEEP_N = 200
CLOSE_PASSES = 2                  # deux passages verts de suite (≈ 10 s) avant de fermer : pas de clignotement
OPEN_PASSES = 2                   # deux passages rouges de suite avant d'ouvrir — le même filtre dans l'autre sens
# un service RÉSEAU coupé dix secondes n'est pas une panne du rack (constaté 2026-10-20 : golem.fm de dev qui redémarre à
# chaque modification de son code — trois incidents en trois minutes) : une minute rouge avant d'ouvrir
OPEN_PASSES_BY_FACT = {"golemfm": 12}
# « What fixed it? » (câble · gain · alimentation) n'a de sens que pour ce qu'un GESTE peut régler ; pas pour golem.fm,
# le disque, un script ou un fichier
HINTABLE = {("fact", "audio"), ("fact", "pedalboard"), ("fact", "engine"), ("silence", None), ("first_check", None)}
START_GRACE_S = 45                # au démarrage du bridge, REAPER met quelques secondes à répondre : ce n'est pas une panne
                                  # (constaté 2026-10-20 : « REAPER not answering » ouvert à chaque reload)
HINTS = ("cable", "gain", "power", "other")
# les faits de Health qui ouvrent un incident, et à partir de quel niveau ; les autres (setlist, plugins,
# environnement) disent un état, pas une panne
WATCH = {"engine": "warn", "audio": "bad", "dropouts": "bad", "pedalboard": "warn", "playing": "bad",
         "disk": "warn", "scripts": "warn", "golemfm": "warn"}
TITLES = {"engine": "REAPER not answering", "audio": "Sound card stopped", "dropouts": "Audio dropouts",
          "pedalboard": "Pedalboard or MIDI problem", "playing": "Files not loaded", "disk": "Disk almost full",
          "scripts": "A script error in REAPER", "golemfm": "golem.fm unreachable"}
_RANK = {"ok": 0, "wait": 1, "warn": 2, "bad": 3}

_lock = threading.Lock()
_green = {}                       # id d'incident → passages verts consécutifs (mémoire du moment)
_red = {}                         # id de fait → passages rouges consécutifs, avant l'ouverture


def _read():
    try:
        with open(PATH(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("items"), list) else {"items": []}
    except (OSError, ValueError):
        return {"items": []}


def _write(d):
    from .store import _write_json_atomic
    cut = time.time() - KEEP_S
    items = [i for i in d.get("items") or [] if i.get("state") != "closed" or float(i.get("closed_at") or 0) >= cut]
    d["items"] = items[-KEEP_N:]
    os.makedirs(os.path.dirname(PATH()), exist_ok=True)
    _write_json_atomic(PATH(), d)


def _event(type_, **fields):
    with contextlib.suppress(Exception):
        from . import diag
        diag.event(type_, **fields)


def _gen():
    with contextlib.suppress(Exception):
        from .state import state
        return int(state.reaper_gen)
    return 0


def _bridge_start():
    with contextlib.suppress(Exception):
        from . import health
        return float(health.START)
    return 0.0


def _open(d, kind, code, stage, title, detail, fact=None):
    now = round(time.time(), 3)
    d["seq"] = int(d.get("seq") or 0) + 1
    inc = {"id": f"i{d['seq']}", "kind": kind, "code": code, "stage": stage, "title": title, "detail": str(detail or "")[:200],
           "fact": fact, "state": "open", "opened_at": now, "gen": _gen()}
    d["items"].append(inc)
    _event("incident", id=inc["id"], state="open", kind=kind, code=code, stage=stage)
    log.info(f"incident ouvert {inc['id']} : {kind}/{code} — {title}")
    return inc


def _close(inc, resolved_by, **extra):
    now = round(time.time(), 3)
    inc.update(state="closed", closed_at=now, resolved_by=resolved_by, after_s=int(now - float(inc["opened_at"])), **extra)
    _green.pop(inc["id"], None)
    _event("incident", id=inc["id"], state="closed", kind=inc["kind"], code=inc["code"], stage=inc.get("stage"))
    _event("resolution", id=inc["id"], resolved_by=resolved_by, after_s=inc["after_s"])
    log.info(f"incident fermé {inc['id']} : {resolved_by} après {inc['after_s']} s")


def _how_it_came_back(inc):
    """restart si REAPER (génération) ou le bridge ont redémarré depuis l'ouverture ; sinon outside."""
    if _gen() != int(inc.get("gen") or 0) or _bridge_start() > float(inc["opened_at"]):
        return "restart"
    return "outside"


def observe(facts):
    """Appelé à chaque passage de Health (5 s) : ouvre un incident par fait surveillé qui passe au rouge, ferme
    celui dont le fait est revenu au vert deux passages de suite — sauf pendant qu'une réparation le vérifie (c'est
    elle qui conclut)."""
    by_id = {f.get("id"): f for f in facts or [] if isinstance(f, dict)}
    with _lock:
        d = _read()
        dirty = False
        open_by_fact = {i.get("fact"): i for i in d["items"] if i.get("kind") == "fact" and i.get("state") != "closed"}
        for fid, min_lvl in WATCH.items():
            f = by_id.get(fid)
            if not f:
                continue
            lvl = f.get("level")
            inc = open_by_fact.get(fid)
            if _RANK.get(lvl, 0) >= _RANK[min_lvl]:
                if inc:
                    _green.pop(inc["id"], None)
                    if inc.get("detail") != f.get("text"):
                        inc["detail"] = str(f.get("text") or "")[:200]
                        dirty = True
                elif time.time() - _bridge_start() >= START_GRACE_S:
                    _red[fid] = _red.get(fid, 0) + 1
                    if _red[fid] >= OPEN_PASSES_BY_FACT.get(fid, OPEN_PASSES):
                        _red.pop(fid, None)
                        _open(d, "fact", fid, lvl, TITLES.get(fid, f.get("name") or fid), f.get("text"), fact=fid)
                        dirty = True
            else:
                _red.pop(fid, None)
            if inc and lvl == "ok" and inc.get("state") == "open":
                n = _green.get(inc["id"], 0) + 1
                _green[inc["id"]] = n
                if n >= CLOSE_PASSES:
                    _close(inc, _how_it_came_back(inc))
                    dirty = True
        if dirty:
            _write(d)


def probe(kind, code, bad, title="", detail="", match_code=False):
    """Un contrôle à la demande (« Why no sound? », la vérification de première installation) : un verdict rouge
    ouvre un incident de ce `kind` (s'il n'y en a pas déjà un ouvert) ; un verdict vert ferme ceux qui l'étaient —
    tous ceux du `kind`, ou seulement ceux du même `code` (`match_code` : les trois gestes du premier check)."""
    with _lock:
        d = _read()
        opened = [i for i in d["items"] if i.get("kind") == kind and i.get("state") == "open"
                  and (not match_code or i.get("code") == code)]
        if bad:
            if opened:
                opened[-1].update(code=code, detail=str(detail or "")[:200])
            else:
                _open(d, kind, code, "bad", title or code, detail)
        else:
            for inc in opened:
                _close(inc, _how_it_came_back(inc))
        _write(d)


def fix_started(inc_id, rec):
    with _lock:
        d = _read()
        for inc in d["items"]:
            if inc["id"] == inc_id and inc.get("state") != "closed":
                inc.update(state="verifying", fix={"id": rec["id"], "action": rec["action"], "params": rec["params"],
                                                   "by": rec["by"], "label": rec.get("label")})
                _write(d)
                return


def fix_done(inc_id, rec, ok):
    """La réparation a conclu : vérifiée au vert → l'incident se ferme par `action` ; sinon il redevient ouvert, la
    tentative est gardée (une réparation qui ne marche pas est une information pour golem.fm)."""
    if not inc_id:
        return
    with _lock:
        d = _read()
        for inc in d["items"]:
            if inc["id"] != inc_id or inc.get("state") == "closed":
                continue
            att = {"action": rec["action"], "params": rec["params"], "by": rec["by"], "ok": bool(ok), "text": rec.get("text")}
            inc.setdefault("attempts", []).append(att)
            if ok:
                _close(inc, "action", action=rec["action"], by=rec["by"], undo=rec.get("undo"))
            else:
                inc["state"] = "open"
                inc.pop("fix", None)
            _write(d)
            return


def hintable(inc):
    return (inc.get("kind"), inc.get("code")) in HINTABLE or (inc.get("kind"), None) in HINTABLE


def hint(inc_id, value):
    """« What fixed it? » — seulement sur un incident fermé `outside`, une fois."""
    if value not in HINTS:
        raise ValueError(f"hint must be one of {', '.join(HINTS)}")
    with _lock:
        d = _read()
        for inc in d["items"]:
            if inc["id"] == inc_id:
                if inc.get("resolved_by") != "outside" or not hintable(inc):
                    raise ValueError("only an incident that came back by itself, from something a hand can fix, takes a hint")
                inc["hint"] = value
                _write(d)
                _event("resolution", id=inc_id, resolved_by="outside", after_s=inc.get("after_s"), hint=value)
                return {"ok": True, "id": inc_id, "hint": value}
    raise ValueError(f"unknown incident '{inc_id}'")


def items(limit=30):
    """Pour l'écran : les ouverts d'abord, puis les plus récents."""
    with _lock:
        d = _read()
    its = sorted(d["items"], key=lambda i: (i.get("state") == "closed", -float(i.get("closed_at") or i.get("opened_at") or 0)))
    return [{**i, "hintable": hintable(i)} for i in its[:limit]]


def by_fact(fid):
    """L'incident ouvert d'un fait (l'écran le joint à la réparation)."""
    with _lock:
        d = _read()
    for i in d["items"]:
        if i.get("kind") == "fact" and i.get("fact") == fid and i.get("state") != "closed":
            return i
    return None


def summary(rows):
    """La section `incidents` du paquet de session, calculée de la chronologie : combien se sont ouverts, comment ils
    ont fini (la DERNIÈRE résolution d'un id gagne : un `hint` arrive après la fermeture), lesquels restent ouverts.
    Des types et des codes — jamais un titre."""
    opened, last_res, state = {}, {}, {}
    for r in rows or []:
        if r.get("type") == "incident" and r.get("id"):
            if r.get("state") == "open":
                opened[r["id"]] = {"kind": r.get("kind"), "code": r.get("code"), "up": r.get("up") or 0}
            state[r["id"]] = r.get("state")
        elif r.get("type") == "resolution" and r.get("id"):
            last_res[r["id"]] = r
    if not opened and not last_res:
        return None
    resolved, hints = {}, {}
    for r in last_res.values():
        resolved[r.get("resolved_by") or "?"] = resolved.get(r.get("resolved_by") or "?", 0) + 1
        if r.get("hint"):
            hints[r["hint"]] = hints.get(r["hint"], 0) + 1
    ups = [r.get("up") for r in rows if isinstance(r.get("up"), (int, float))]
    end = max(ups) if ups else 0
    still = [{"kind": o["kind"], "code": o["code"], "age_s": int(max(0, end - o["up"]))}
             for i, o in opened.items() if state.get(i) != "closed"]
    return {"opened": len(opened), "resolved": resolved, "hints": hints, "open": still}
