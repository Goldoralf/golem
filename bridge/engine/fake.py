# SPDX-License-Identifier: GPL-3.0-or-later
"""Un moteur factice pour les tests : il enregistre tout ce qu'on lui demande, ne joue rien."""
import itertools

from .base import EngineAdapter


class FakeEngine(EngineAdapter):
    id = "fake"

    def __init__(self, actions=None, up=True):
        self.actions = None if actions is None else frozenset(actions)
        self.sent = []               # commandes acceptées, avec leur seq
        self.fast = []               # (méthode, args…) du chemin rapide
        self.up = up
        self._seq = itertools.count(1)
        self._on_message = None

    def _send(self, cmd):
        cmd = {**cmd, "seq": next(self._seq)}
        self.sent.append(cmd)
        return cmd["seq"]

    def set_fx_param(self, track, fx, param, norm):
        self.fast.append(("fx_param", track, fx, param, norm))
        return True

    def set_track_volume(self, track, value):
        self.fast.append(("volume", track, value))
        return True

    def set_track_mute(self, track, muted):
        self.fast.append(("mute", track, muted))
        return True

    def transport(self, op):
        self.fast.append(("transport", op))
        return True

    def refresh(self):
        self.fast.append(("refresh",))
        return True

    def start_feedback(self, on_message):
        self._on_message = on_message

    def push(self, address, *args):
        """Simule un message de télémétrie du moteur."""
        if self._on_message:
            self._on_message(address, args)

    def pid(self):
        return 4242 if self.up else None

    def ready_since(self, t0):
        return self.up

    def restart(self, why="requested"):
        self.fast.append(("restart", why))
        return {"ok": True, "restarting": True}

    def version(self):
        return "fake-1"
