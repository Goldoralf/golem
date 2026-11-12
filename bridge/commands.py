# SPDX-License-Identifier: GPL-3.0-or-later
"""Commandes vers le moteur audio : `write_command` (la porte, tous moteurs) et `enqueue` (le transport REAPER :
slot presets/.command.json lu par golem_watch.lua, accusé, file) — extrait d'app.py (P3)."""
import os, json, time, tempfile, itertools, sys, glob

from . import config as C

# Compteur de commandes : itertools.count = atomique (GIL), graine horloge = monotone même
# après restart du bridge (sinon un veilleur déjà lancé pourrait revoir un seq identique).
_cmd_seq = itertools.count(int(time.time() * 1000))

# ── ACK de consommation (audit 2026-08-12) ────────────────────────────────────────────────
# .command.json est un SLOT UNIQUE : écrire dessus pendant que golem_watch gèle une commande
# (SETTLE post-rebuild) la faisait disparaître SANS TRACE (panne du 2026-07-26, dumpfx périmé
# indéfiniment). golem_watch écrit désormais {seq, t} dans .command-ack.json à CHAQUE
# consommation ; write_command attend cet ack avant d'écraser un slot encore plein.
ACK_FILE = os.path.join(C.PRESETS_DIR, ".command-ack.json")
_SLOT_TIMEOUT = 0.9   # > SETTLE (0,5 s côté golem_watch) : couvre le gel post-rebuild
_STALE_S = 3.0        # slot ignoré depuis > 3 s = Reaper absent (ou golem_watch d'avant
                      # l'ack) -> on n'attend plus : comportement historique, on écrase
_last_ack_gc = 0.0


def _ack_path(seq=None):
    # Sous Windows, Lua os.rename ne remplace pas une destination existante. Un ACK par
    # séquence évite ce remplacement ; Linux/macOS gardent le protocole historique.
    return f"{ACK_FILE}.{seq}" if sys.platform == "win32" and seq is not None else ACK_FILE


def _acked_seq(pending=None):
    try:
        return int(json.load(open(_ack_path(pending))).get("seq") or 0)
    except Exception:
        return 0


def _gc_acks():
    """Les ACK Windows sont immuables ; effacer seulement les anciens, hors chemin live."""
    global _last_ack_gc
    if sys.platform != "win32" or time.monotonic() - _last_ack_gc < 60:
        return
    _last_ack_gc = time.monotonic()
    for path in glob.glob(ACK_FILE + ".*"):
        if not path.removeprefix(ACK_FILE + ".").isdigit():
            continue
        try:
            if time.time() - os.stat(path).st_mtime > 60:
                os.remove(path)
        except OSError:
            pass


def _wait_slot_free():
    """Attend (≤ _SLOT_TIMEOUT) que la commande EN ATTENTE dans le slot soit consommée.
    Ne lève jamais, n'attend jamais un slot périmé : au pire on retrouve l'ancien monde."""
    try:
        mtime = os.stat(C.COMMAND_FILE).st_mtime
        pending = json.load(open(C.COMMAND_FILE)).get("seq")
    except Exception:
        return
    if not pending:
        return
    if _acked_seq(pending) >= pending:
        return
    if time.time() - mtime > _STALE_S:
        return
    deadline = time.time() + _SLOT_TIMEOUT
    while time.time() < deadline:
        time.sleep(0.03)                      # ~1 tick defer de golem_watch
        if _acked_seq(pending) >= pending:
            return


# ── FILE DE COMMANDES (audit 2026-10-15) ──────────────────────────────────────────────────
# Le slot unique s'écrasait au bout de _SLOT_TIMEOUT (0,9 s) alors que REAPER peut tenir son fil principal
# plus longtemps (attente de chargement jusqu'à 3 s par piste pendant un rebuild, copie d'une prise) : un
# rig_recall ou un stomp en attente disparaissait sans trace. Attendre plus longtemps DANS write_command
# bloquerait le bridge. Donc : slot libre et file vide -> écriture immédiate (le chemin de toujours) ; sinon la
# commande entre dans une FILE, qu'un fil vide dans l'ordre à chaque accusé de golem_watch. Une commande n'est
# remplacée que par une plus récente QUI LA REND INUTILE (un rappel par un rappel, un mixage par un mixage) —
# jamais un stomp, qui est un geste. REAPER éteint : on écrase comme avant (golem_watch ignore la commande
# résiduelle à son démarrage, de toute façon). REAPER allumé qui ne lit plus rien pendant _HUNG_S : figé —
# la file avance quand même, en le journalisant.
import logging
import threading

log = logging.getLogger("golem.commands")
_HUNG_S = 30.0
_queue = []
_qcv = threading.Condition()
_drainer = None


def _superseded(new):
    """Les commandes en attente que `new` rend inutiles. Un REBUILD (rig_recall) remplace les rappels ET les scènes en
    attente : il pose lui-même sa scène, et une scène calculée pour l'ancien preset s'appliquerait sur le nouveau. Une
    SCÈNE ne remplace que les scènes arrivées après le dernier rebuild en attente. Le mixage et l'accordeur portent
    leur état complet : le dernier suffit."""
    a = new.get("action")
    if a == "rig_recall":
        return {id(c) for c in _queue if c.get("action") in ("rig_recall", "scene_apply")}
    if a == "scene_apply":
        last_rb = max([i for i, c in enumerate(_queue) if c.get("action") == "rig_recall"] or [-1])
        return {id(c) for c in _queue[last_rb + 1:] if c.get("action") == "scene_apply"}
    if a in ("mixer_apply", "tuner"):
        return {id(c) for c in _queue if c.get("action") == a}
    return set()


def _pending():
    """(seq en attente dans le slot, âge du fichier) — (None, 0) si le slot est libre."""
    try:
        mtime = os.stat(C.COMMAND_FILE).st_mtime
        pending = json.load(open(C.COMMAND_FILE)).get("seq")
    except Exception:
        return None, 0.0
    if not pending or _acked_seq(pending) >= pending:
        return None, 0.0
    return pending, time.time() - mtime


def _reaper_up():
    """Le moteur actif tourne-t-il ? (le nom reste : les tests le remplacent)"""
    try:
        from . import engine
        return engine.get().running()
    except Exception:
        return True                           # dans le doute : on attend (borné par _HUNG_S)


def _slot_free():
    pending, age = _pending()
    if pending is None:
        return True
    if age > _STALE_S and not _reaper_up():
        return True                           # REAPER éteint : comportement historique
    if age > _HUNG_S:
        log.warning(f"commande {pending} jamais lue en {age:.0f} s (REAPER figé ?) — la file avance")
        return True
    return False


def _write(cmd):
    os.makedirs(C.PRESETS_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=C.PRESETS_DIR, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(cmd, f)
    from . import winfs                       # golem_watch lit ce fichier : sous Windows, réessayer
    winfs.replace(tmp, C.COMMAND_FILE)
    _gc_acks()


def _drain():
    global _drainer
    while True:
        with _qcv:
            if not _queue:
                _drainer = None
                return
        if not _slot_free():
            time.sleep(0.03)                  # ~1 tick defer de golem_watch
            continue
        with _qcv:
            if not _queue:
                continue
            cmd = _queue.pop(0)
            _write(cmd)


def flush(timeout=5.0):
    """Attend que la file soit écrite (≤ timeout). Appelé à la sortie : un outil (tools/check-*.py) qui sort juste
    après sa commande la perdait avec le fil démon qui devait l'écrire — mesuré au premier essai."""
    end = time.time() + timeout
    while time.time() < end:
        with _qcv:
            if not _queue:
                return True
        time.sleep(0.03)
    return False


import atexit
atexit.register(flush)


def queued():
    """Les commandes en attente (diagnostic)."""
    with _qcv:
        return [{"seq": c["seq"], "action": c.get("action")} for c in _queue]


def write_command(cmd: dict):
    """LA porte des commandes vers le moteur audio (docs/ardour-plan.md §2) : le moteur actif la pose à sa façon.
    REAPER (le seul aujourd'hui) -> `enqueue` ci-dessous. Rend le `seq` posé, ou None si le moteur ne connaît pas
    l'action. Les ~80 sites d'appel ne changent pas : le dict `{"action": …}` est le contrat."""
    from . import engine
    return engine.get().send(cmd)


def enqueue(cmd: dict):
    """Transport REAPER : écrit la commande pour golem_watch.lua, de façon atomique. Rend le `seq` posé.
    + nonce `seq` : garantit que 2 commandes identiques successives re-déclenchent le veilleur.
    + politesse de slot : n'écrase jamais une commande PAS ENCORE LUE — elle attend son tour dans la file
      (ci-dessus), dans l'ordre d'arrivée."""
    global _drainer
    with _qcv:
        cmd = {**cmd, "seq": next(_cmd_seq)}
        if not _queue and _slot_free():
            _write(cmd)
            return cmd["seq"]
        gone = _superseded(cmd)
        if gone:
            _queue[:] = [c for c in _queue if id(c) not in gone]
            log.info(f"{cmd.get('action')} remplace {len(gone)} commande(s) en attente qu'il rend inutiles")
        _queue.append(cmd)
        log.info(f"slot occupé : {cmd.get('action')} ({cmd['seq']}) attend son tour — {len(_queue)} en file")
        if _drainer is None:
            _drainer = threading.Thread(target=_drain, name="golem-commands", daemon=True)
            _drainer.start()
    return cmd["seq"]
