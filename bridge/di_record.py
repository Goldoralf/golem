# SPDX-License-Identifier: GPL-3.0-or-later
"""« Record your own DI » (job golem.fm `di-record`, validé par le mainteneur le 2026-11-18) : quelques secondes du
signal SEC d'une entrée — ce que le musicien joue, avant tout patch — enregistrées sur le rack, envoyées à golem.fm
comme une DI de l'utilisateur, et retirées du rack.

C'est une VRAIE PRISE, courte, par le chemin des prises (commande `perf_rec`, le moteur écrit ses fichiers), avec ce
que le mainteneur a tranché :
  · le mode « Tracks + DI » est FORCÉ le temps de cette prise (c'est lui qui donne la piste sèche), quel que soit le
    réglage de l'enregistreur ; une seule entrée est prise, sans mix ; le réglage du rack est remis ensuite ;
  · l'écran le montre comme toute prise (l'état « recording ») ;
  · rien n'est gardé : le dossier de la prise est retiré une fois la DI envoyée — ce n'est pas une prise du musicien.
Refusé, avec une phrase : mode Gig ou verrouillé, une prise ou un décompte en cours, un backing ou un arrangement qui
joue, un rig qui charge, un rendu en cours, plus assez de place, un moteur qui ne répond pas.

Pas de décompte dans cette première version (`count_in` est lu et refusé s'il n'est pas 0) : il demande le click et
un tempo, comme une prise armée."""
import contextlib
import json
import os
import shutil
import threading
import time

from . import config as C
from .golog import get

log = get("perf")
MIN_S, MAX_S = 3.0, 30.0
_lock = threading.Lock()
STATE = {"running": False, "input": None, "until": None}


def _perf():
    try:
        with open(os.path.join(C.PRESETS_DIR, ".perf.json"), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _wait(pred, secs, step=0.15):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return True
        time.sleep(step)
    return False


def sources_for(n):
    """Le fichier des sources (presets/.perfsrc.json) de CETTE prise : la seule entrée `n`, en « Tracks + DI », sans mix."""
    out = {"in1": False, "in2": False, "usb": False, "mode": "tracks_di", "mix": False, "di_record": True}
    out[f"in{int(n)}"] = True
    return out


def refusal(state):
    """La raison de ne pas enregistrer maintenant, ou None."""
    from . import disk, reamp
    if (_perf().get("recording")) or getattr(state, "perf_countin", None):
        return "a take is recording — try after it"
    why = reamp.busy_reason(idle=False)                 # Gig / verrouillé, backing, arrangement, rig qui charge, rendu
    if why:
        return why
    ok, why = disk.check_start()
    if not ok:
        return why
    return None


def record(n, max_s, state=None, write_command=None, restore=None, sleep=time.sleep):
    """Enregistre `max_s` secondes de l'entrée `n`. Rend {ok, folder, file} (le fichier sec de la prise) ou {ok: False,
    error}. Ne retire rien : c'est l'appelant qui envoie puis nettoie (`discard`)."""
    if state is None:
        from .state import state as _st
        state = _st
    if write_command is None:
        from .commands import write_command as _wc
        write_command = _wc
    try:
        n, max_s = int(n), float(max_s)
    except (TypeError, ValueError):
        return {"ok": False, "error": "input and max_s are numbers"}
    if n < 1 or n > 64:
        return {"ok": False, "error": f"no input {n} on this golem"}
    if not MIN_S <= max_s <= MAX_S:
        return {"ok": False, "error": f"a DI lasts between {MIN_S:g} and {MAX_S:g} seconds"}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "a DI is already being recorded"}
    src_path = os.path.join(C.PRESETS_DIR, ".perfsrc.json")
    try:
        why = refusal(state)
        if why:
            return {"ok": False, "error": why}
        before = _perf().get("file") or ""
        with open(src_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(sources_for(n), f)
        os.replace(src_path + ".tmp", src_path)
        STATE.update(running=True, input=n, until=time.time() + max_s)
        log.info(f"DI à la demande : entrée {n}, {max_s:g} s")
        write_command({"action": "perf_rec", "on": True})
        if not _wait(lambda: bool(_perf().get("recording")), 8.0):
            write_command({"action": "perf_rec", "on": False})
            return {"ok": False, "error": (_perf().get("error") or "the recording did not start")}
        sleep(max_s)
        write_command({"action": "perf_rec", "on": False})
        if not _wait(lambda: not _perf().get("recording") and (_perf().get("file") or "") not in ("", before), 25.0):
            return {"ok": False, "error": (_perf().get("error") or "the recording was not written")}
        folder = os.path.join(C.ROOT, _perf()["file"])
        dry = os.path.join(folder, f"DI-Sandbox-Input-{n}.wav")
        if not _wait(lambda: os.path.isfile(dry) and os.path.getsize(dry) > 1024, 8.0):
            return {"ok": False, "error": f"nothing was recorded from input {n} — is it an audio input of this sound card?",
                    "folder": folder if os.path.isdir(folder) else None}
        return {"ok": True, "folder": folder, "file": dry}
    finally:
        STATE.update(running=False, input=None, until=None)
        with contextlib.suppress(Exception):
            if restore is not None:
                restore()                              # le réglage du rack retrouve sa place
        _lock.release()


def discard(folder, recordings=None):
    """Retire le dossier de CETTE prise (rien n'est gardé sur le rack). Seulement un dossier `perf-…` de recordings/."""
    if recordings is None:
        from . import takes
        recordings = takes.RECORDINGS
    real, base = os.path.realpath(folder or ""), os.path.realpath(recordings)
    if not real.startswith(base + os.sep) or not os.path.basename(real).startswith("perf-") or not os.path.isdir(real):
        return False
    shutil.rmtree(real, ignore_errors=True)
    return True
