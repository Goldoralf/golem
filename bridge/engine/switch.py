# SPDX-License-Identifier: GPL-3.0-or-later
"""La BASCULE de moteur (lot E3, docs/audio-engine-choice.md ; docs/ardour-plan.md §7c).

Settings ▸ Engines ▸ Audio ▸ Select : le choix est écrit (config/engine.json), puis, en tâche de fond :
  1. stopping   — l'ancien moteur s'arrête (son process) et libère son port OSC ;
  2. starting   — le nouveau devient le moteur actif du bridge (engine.use), son retour OSC s'ouvre, il démarre ;
  3. remounting — dès qu'il répond, le moniteur voit un nouveau process et remonte le patch en cours (monitors.
                  _remount_after_restart, comme après un plantage) ; on attend que le livemap le dise ;
  4. done — ou, si le nouveau ne répond pas à temps : reverting (on remet l'ancien, son choix, son process) puis failed.
Une bascule à la fois. Jamais pendant une prise (le refus vient avant, dans la route).
"""
import logging
import os
import threading
import time

log = logging.getLogger("golem.engine")

START_TIMEOUT_S = 45.0
REMOUNT_TIMEOUT_S = 45.0

_lock = threading.Lock()
_job = {"phase": "idle"}


def status():
    with _lock:
        return dict(_job)


def _set(**kw):
    with _lock:
        _job.update(kw, at=time.time())
    log.info(f"bascule de moteur : {kw.get('phase')} {kw.get('error') or ''}".rstrip())


def _wait(cond, timeout, step=0.25):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def _talking(eng, state):
    t = eng.talking()
    return bool(t) if t is not None else bool(state.reaper_connected)


def start(target_id, on_osc=None, registry=None):
    """Lance la bascule vers `target_id` ; rend le statut. Refuse (ValueError) si une bascule tourne déjà."""
    with _lock:
        if _job.get("phase") in ("stopping", "starting", "remounting", "reverting"):
            raise ValueError("an engine switch is already running")
        _job.clear()
        _job.update(phase="stopping", to=target_id, at=time.time())
    threading.Thread(target=_run, args=(target_id, on_osc, registry), name="golem-engine-switch", daemon=True).start()
    return status()


def _run(target_id, on_osc, registry):
    from .. import recall
    from ..state import state
    from . import _registry, get, use
    old = get()
    _set(phase="stopping", **{"from": old.id})
    if on_osc is None:
        from .. import app
        on_osc = app.on_osc
    reg = registry or _registry()
    _diag_intent("switch")
    try:
        old.stop()
    except Exception as e:
        log.warning(f"arrêt de {old.id} : {e}")
    old.stop_feedback()
    # les TÉMOINS de l'ancien moteur partent avec lui : son .clock.json encore frais faisait passer le nouveau pour vivant
    # avant même son démarrage (mesuré 2026-11-10, Golem Engine -> REAPER : « starting » conclu en 0,6 s)
    for name in (".clock.json", ".engine-status.json"):
        try:
            os.remove(os.path.join(_presets_dir(), name))
        except OSError:
            pass
    new = reg[target_id]()
    try:
        new.adopt_audio(old.audio() or {})            # le buffer joué jusqu'ici, si le nouveau n'a pas de réglage à lui
    except Exception as e:
        log.warning(f"réglage audio non repris : {e}")
    use(new)
    recall.invalidate_shape()                         # le rig est à reconstruire sur le nouveau moteur
    _set(phase="starting")
    try:
        new.start_feedback(on_osc)
        new.restart("switch")
    except Exception as e:
        return _revert(old, new, on_osc, f"{target_id} did not start: {e}")
    if not _wait(lambda: new.running() and _talking(new, state), START_TIMEOUT_S):
        return _revert(old, new, on_osc, f"{target_id} did not answer within {int(START_TIMEOUT_S)} s")
    pid_preset = state.preset_id
    if pid_preset:
        _set(phase="remounting", preset=pid_preset)
        lm = os.path.join(_presets_dir(), ".livemap.json")
        t0 = time.time()

        def remounted():
            try:
                import json
                with open(lm, encoding="utf-8") as f:
                    doc = json.load(f) or {}
                return os.stat(lm).st_mtime >= t0 - 1 and doc.get("preset") == pid_preset
            except (OSError, ValueError):
                return False
        if not _wait(remounted, REMOUNT_TIMEOUT_S):
            log.warning(f"bascule : {pid_preset} pas remonté en {int(REMOUNT_TIMEOUT_S)} s sur {target_id} — le moteur tourne, "
                        "rappeler le preset")
            _set(phase="done", warning=f"{pid_preset} was not remounted — recall it")
            return
    _set(phase="done")


def _revert(old, new, on_osc, why):
    from .. import engines, recall
    from . import use
    _set(phase="reverting", error=why)
    try:
        new.stop()
    except Exception as e:
        log.warning(f"arrêt de {new.id} : {e}")
    new.stop_feedback()
    try:
        engines.write_choice(old.id, set_by="switch-revert")
    except ValueError as e:
        log.warning(f"choix {old.id} non réécrit : {e}")
    use(old)
    recall.invalidate_shape()
    try:
        old.start_feedback(on_osc)
        old.restart("switch back")
    except Exception as e:
        _set(phase="failed", error=f"{why}; {old.id} did not restart either: {e}")
        return
    _set(phase="failed", error=why)


def _presets_dir():
    from .. import config as C
    return C.PRESETS_DIR


def _diag_intent(why):
    """Un arrêt voulu n'est pas un plantage (diag §2.3) : l'intention avant d'arrêter."""
    try:
        from .. import diag
        diag.intent("reaper", why)
    except Exception:
        pass
