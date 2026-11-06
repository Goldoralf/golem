# SPDX-License-Identifier: GPL-3.0-or-later
"""L'horloge d'ACTIVITÉ du rack — « quelqu'un s'en sert-il ? » (docs/reamp.md §2).

Trois sources l'écrivent, et seulement elles :
  - `screen` : une requête HTTP qui MODIFIE quelque chose (middleware d'app.py) — un geste d'écran,
    de Companion ou d'outil ;
  - `foot`   : un message du pédalier (foot.py) ;
  - `signal` : une entrée au-dessus de SIGNAL sur le vumètre OSC (app.py). C'est elle qui manque à
    toutes les autres gardes : un guitariste qui joue en Home sans lancer de chanson n'enregistre
    rien, ne lit rien, ne verrouille rien — seul son signal dit qu'il est là.

Lue par ce qui prend le moteur hors du jeu (le reamp). Mémoire seule : au démarrage du bridge,
l'horloge part de MAINTENANT — un rack qui vient de redémarrer n'est pas réputé inactif.
"""
import threading
import time

# Vumètre OSC normalisé (1,0 = 0 dBFS). ⚠ À CALIBRER au rig (docs/reamp.md §2) : trop haut, un jeu
# doux passe pour du silence ; trop bas, le souffle d'un micro ouvert retient le rack pour toujours.
SIGNAL = 0.2

_lock = threading.Lock()
_last = {"t": time.time(), "src": "boot"}


def touch(src):
    with _lock:
        _last["t"] = time.time()
        _last["src"] = src


def note_level(val):
    """Appelé à chaque lecture du vumètre d'une entrée : seul un signal réel compte."""
    if val is not None and val >= SIGNAL:
        touch("signal")


def idle_s():
    with _lock:
        return time.time() - _last["t"]


def last():
    with _lock:
        return {"src": _last["src"], "idle_s": round(time.time() - _last["t"], 1)}
