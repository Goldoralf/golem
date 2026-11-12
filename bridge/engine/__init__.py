# SPDX-License-Identifier: GPL-3.0-or-later
"""Le moteur audio actif (docs/ardour-plan.md §2).

`get()` rend l'adaptateur du moteur choisi sur cette machine (bridge/engines.py lit config/engine.json et
les descripteurs). Un seul adaptateur par process : il porte le lien OSC et sa file de commandes.
`use(adapter)` le remplace (tests, et plus tard la bascule de moteur, lot E3).
"""
import logging
import os
import threading

from .base import EngineAdapter, TRANSPORT_OPS  # noqa: F401  (réexportés)

log = logging.getLogger("golem.engine")

_lock = threading.Lock()
_active = None


def _registry():
    from .ardour import ArdourEngine
    from .reaper import ReaperEngine
    return {"reaper": ReaperEngine, "ardour": ArdourEngine}


def _make():
    from .. import engines
    eid = None
    # DEV seulement : GOLEM_ENGINE=ardour lance un bridge (de banc) sur un autre moteur sans passer par la bascule,
    # qui reste le lot E3 (docs/audio-engine-choice.md). Un rack ne pose jamais cette variable.
    forced = os.environ.get("GOLEM_ENGINE")
    if forced in _registry():
        log.warning(f"moteur forcé par GOLEM_ENGINE : {forced}")
        return _registry()[forced]()
    try:
        eid = engines.current()
    except Exception as e:                      # descripteurs illisibles : on ne casse pas le rack
        log.warning(f"moteur choisi illisible ({e}) — REAPER")
    cls = _registry().get(eid)
    if cls is None:
        if eid:
            log.warning(f"aucun adaptateur pour le moteur « {eid} » — REAPER")
        cls = _registry()["reaper"]
    return cls()


def get():
    global _active
    if _active is None:
        with _lock:
            if _active is None:
                _active = _make()
    return _active


def use(adapter):
    """Remplace l'adaptateur actif ; rend le précédent (pour le remettre)."""
    global _active
    with _lock:
        prev, _active = _active, adapter
    return prev


def send(cmd):
    return get().send(cmd)


class _Active:
    """Le moteur ACTIF, quel qu'il soit au moment de l'appel : ce que les modules gardent (app.reaper, le looper, le
    backing) suit une bascule de moteur (bridge/engine/switch.py) au lieu de parler à l'ancien."""

    def __getattr__(self, name):
        return getattr(get(), name)

    def __repr__(self):
        return f"<moteur actif : {get().id}>"


def active():
    return _Active()
