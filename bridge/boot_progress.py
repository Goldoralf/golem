# SPDX-License-Identifier: GPL-3.0-or-later
"""L'écran de chargement (maquette mockups/loading.html, 2026-10-11) : des FAITS datés, jamais une barre de
progrès. Ce module observe l'état du bridge et note la PREMIÈRE fois où chaque module est prêt — bridge, moteur
REAPER (process), lien OSC, carte son, MIDI, golem.fm, premier preset — puis « done » quand le premier preset joue.
La page ne décide rien : elle lit `state.boot` et affiche. Les délais d'alerte sont les siens (par module, au double
du dernier démarrage) ; ici on ne fait que dater.

`config/.boot.json` (local) garde la durée du dernier démarrage : la référence honnête pour « ça traîne »."""
import json
import os
import sys
import threading
import time

from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("boot")
LAST_PATH = os.path.join(C.CONFIG_DIR, ".boot.json")
_lock = threading.Lock()
_B = {"t0": time.time(), "steps": {}, "done": None, "failed": None, "why": "start", "last_took": None,
      "needs_preset": True,
      # LES DEUX SERVICES (2026-10-11) : golem.fm et TONE3000 — « deux fonctionnalités importantes » que
      # l'écran de chargement signale si elles ne sont pas réglées. `ok: None` = pas encore vérifié.
      "services": {"fm": {"configured": None, "ok": None, "why": None},
                   "t3k": {"configured": None, "ok": None, "why": None},
                   # LA LICENCE REAPER (2026-10-16) : sans elle REAPER tourne en évaluation (le rappel d'achat) —
                   # dit sur l'écran de chargement, jamais une panne. `present` = un fichier posé ; `state` (Windows)
                   # = ce que REAPER affiche ; `ok: None` = pas encore lu. Jamais le contenu de la licence.
                   "reaper": {"present": None, "state": None, "ok": None}}}


def _check_services():
    """Une fois par démarrage, hors du fil principal : licence REAPER posée (local, d'abord) ? golem.fm appairé ?
    TONE3000 connecté (un ping léger) ?"""
    refresh_reaper_license()
    try:
        from .golemfm import _cfg
        base, token = _cfg()
        with _lock:
            _B["services"]["fm"].update(configured=bool(base and token),
                                       why=None if (base and token) else "not paired")
    except Exception as e:
        _swallowed(e)
    try:
        from .routes_t3k import t3k_auth_status
        r = t3k_auth_status() or {}
        why = str(r.get("reason") or "") or None
        # « not signed in » = jamais connecté (t3k.py vérifie le jeton AVANT la clé) : sans lui, un golem neuf lisait
        # « TONE3000: TONE3000 not signed in — … — tap to re-pair » (2026-10-22)
        absent = bool(why) and any(w in why.lower() for w in ("absent", "missing", "no key", "aucune", "not signed in"))
        with _lock:
            _B["services"]["t3k"].update(configured=not absent, ok=bool(r.get("authed")),
                                        why=None if r.get("authed") else (why or "not connected"))
    except Exception as e:
        with _lock:
            _B["services"]["t3k"].update(configured=None, ok=False, why=str(e))


def refresh_reaper_license():
    """La licence REAPER, en LECTURE seule, par la fonction de Settings ▸ About (présence, et sous Windows ce
    que REAPER affiche). Appelée au démarrage, toutes les 5 min, et juste après qu'une licence a été posée."""
    try:
        from .routes_system import reaper_license_status
        r = reaper_license_status() or {}
        present, lstate = bool(r.get("present")), r.get("state")
        # un fichier refusé par CE REAPER (Windows : titre « EVALUATION ») n'est pas une licence qui marche
        ok = lstate == "registered" or (present and lstate != "evaluation")
        with _lock:
            _B["services"]["reaper"].update(present=present, state=lstate, ok=ok)
    except Exception as e:
        _swallowed(e)


def check_services_async():
    threading.Thread(target=_check_services, name="golem-boot-services", daemon=True).start()


_PERIODIC = {"on": False}


def start_periodic(every_s=300):
    """Le même verdict, rafraîchi toutes les 5 min : la pastille des onglets Settings le lit (mockups/settings-badges.html)."""
    if _PERIODIC["on"]:
        return
    _PERIODIC["on"] = True

    def loop():
        while True:
            time.sleep(every_s)
            _check_services()

    threading.Thread(target=loop, name="golem-services-periodic", daemon=True).start()


def check_services_now():
    """À la demande (ouverture de la page API) : vérifie et rend le verdict."""
    _check_services()
    return doc()["services"]


def _load_last():
    try:
        with open(LAST_PATH, encoding="utf-8") as f:
            return (json.load(f) or {}).get("last_took")
    except Exception:
        return None


_B["last_took"] = _load_last()


def _mark(step, when=None):
    with _lock:
        if step not in _B["steps"]:
            _B["steps"][step] = round(when or time.time(), 3)


def _observe_fm():
    try:
        from . import follow_uplink
        link = getattr(follow_uplink, "LINKED", None) or {}
    except Exception:
        return
    linked = bool(link.get("ok"))
    if linked:
        _mark("fm")
    with _lock:
        fm = _B["services"]["fm"]
        fm["ok"] = linked
        # le motif d'une coupure que le LIEN connaît (4409 : une autre connexion de ce golem l'a pris) ; effacé quand il revient
        if link.get("why"):
            fm["why"], fm["link_why"] = link["why"], True
        elif fm.pop("link_why", None):
            fm["why"] = None


def observe(state):
    """Appelé à chaque instantané de l'état (bon marché) : date les transitions, conclut quand tout y est."""
    try:
        # LE LIEN golem.fm EST SUIVI APRÈS LE DÉMARRAGE (2026-10-11) : la pastille des onglets Settings lit
        # `services.fm.ok` ; posé seulement avant « done », un golem.fm revenu après le chargement restait en panne
        _observe_fm()
        if _B["done"]:
            return
        now = time.time()
        if getattr(state, "reaper_running", False):
            _mark("reaper", now)
        if getattr(state, "reaper_connected", False):
            _mark("osc", now)
        audio = getattr(state, "audio", None) or {}
        if "osc" in _B["steps"] and audio.get("ok"):
            _mark("audio", now)
        midi = getattr(state, "midi", None) or {}
        if "ok" in midi:                                 # sondé (ok ou pas : l'écran dit lequel)
            _mark("midi", now)
        # « FINI » ATTEND LA CARTE (2026-10-11 : /live arrivait avec « ⚠ No sound card » une seconde) : la bank 00
        # est rappelée avant que la télémétrie de la carte (golem_clock) ne soit lue — le preset ET la carte, pas l'un
        if _B["needs_preset"] and "preset" in _B["steps"] and "audio" in _B["steps"]:
            _finish(now)
        if not _B["needs_preset"] and "audio" in _B["steps"] and getattr(state, "preset_id", None) \
                and not getattr(state, "rig_loading", None):
            _finish(now)                                 # après un restart de REAPER : le preset était déjà là
    except Exception as e:
        _swallowed(e)


def preset_done(ok=True):
    """Le rappel de démarrage a fini (bank 00 rappelée, ou rig adopté) : le golem joue."""
    _mark("preset", time.time())
    if not ok:
        fail("the first preset could not be loaded")
        return
    with _lock:
        has_audio = "audio" in _B["steps"]
    if has_audio:
        _finish(time.time())                            # sinon observe() conclura quand la carte sera lue


def fail(reason):
    with _lock:
        if not _B["failed"]:
            _B["failed"] = str(reason)
    log.warning(f"démarrage : {reason}")


def _finish(now):
    with _lock:
        if _B["done"]:
            return
        _B["done"] = round(now, 3)
        took = round(now - _B["t0"], 1)
        _B["last_took"] = took
    try:
        from .store import _write_json_atomic
        _write_json_atomic(LAST_PATH, {"last_took": took, "at": int(now)})
    except Exception as e:
        _swallowed(e)
    log.info(f"démarrage terminé en {took} s")


def reset(why="restart", needs_preset=False):
    """REAPER relancé depuis l'app : l'écran de chargement revient, depuis maintenant. Le preset courant est déjà
    connu du bridge (il n'y a pas de bank 00 à rappeler) : « done » dès que la carte rejoue."""
    with _lock:
        _B.update(t0=time.time(), steps={}, done=None, failed=None, why=why, needs_preset=needs_preset)
        for k, s in _B["services"].items():
            s.update(**({"present": None, "state": None, "ok": None} if k == "reaper"
                        else {"configured": None, "ok": None, "why": None}))
    log.info(f"écran de chargement relancé ({why})")
    if why != "test":
        check_services_async()


def doc():
    with _lock:
        d = {k: _B[k] for k in ("t0", "steps", "done", "failed", "why", "last_took")}
        d["steps"] = dict(d["steps"])
        d["services"] = {k: dict(v) for k, v in _B["services"].items()}
    d["now"] = round(time.time(), 3)
    d["os"] = {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}.get(sys.platform, sys.platform)
    return d
