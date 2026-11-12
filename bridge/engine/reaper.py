# SPDX-License-Identifier: GPL-3.0-or-later
"""REAPER derrière le contrat (docs/ardour-plan.md §2, étape A1 : AUCUN changement de comportement).

Commandes : la file + le slot presets/.command.json lus par golem_watch.lua (bridge/commands.py, inchangé).
Chemin rapide : le lien OSC (bridge/reaper_osc.py, inchangé), device reaper/OSC/golem.ReaperOSC.
"""
from .. import config as C
from .base import EngineAdapter

# actions natives de REAPER (numéros de commande)
_TRANSPORT = {"play": 1007, "pause": 1008, "stop": 1016, "start": 40042}
_REFRESH_SURFACES = 41743            # « Control surface: refresh all surfaces »


class ReaperEngine(EngineAdapter):
    id = "reaper"
    actions = None                   # le vocabulaire des commandes est celui de golem_watch.lua

    def __init__(self, link=None):
        self._link = link
        self._on_message = None

    # ── commandes ────────────────────────────────────────────────────────────────────────
    def _send(self, cmd):
        from .. import commands
        return commands.enqueue(cmd)

    # ── lien OSC ─────────────────────────────────────────────────────────────────────────
    @property
    def link(self):
        """Le lien OSC, créé au premier usage (le port de retour ne s'ouvre qu'à start_feedback)."""
        if self._link is None:
            from ..reaper_osc import ReaperLink
            self._link = ReaperLink(C.REAPER_OSC_HOST, C.REAPER_OSC_SEND_PORT, C.BRIDGE_OSC_RECV_PORT,
                                    self._dispatch)
        return self._link

    def _dispatch(self, address, args):
        if self._on_message:
            self._on_message(address, args)

    def start_feedback(self, on_message):
        self._on_message = on_message
        self.link.start()

    def stop_feedback(self):
        if self._link:
            self._link.stop()

    def set_fx_param(self, track, fx, param, norm):
        return self.link.set_fx_param(track, fx, param, norm)

    def set_track_volume(self, track, value):
        return self.link.set_track_volume(track, value)

    def set_track_mute(self, track, muted):
        return self.link.set_track_mute(track, muted)

    def transport(self, op):
        return self.link.trigger_action(_TRANSPORT[op])

    def refresh(self):
        return self.link.trigger_action(_REFRESH_SURFACES)

    def trigger_action(self, command_id):
        """Propre à REAPER : une action par son numéro ou son nom (_RS…). Hors contrat."""
        return self.link.trigger_action(command_id)

    # ── cycle de vie ─────────────────────────────────────────────────────────────────────
    def pid(self):
        from .. import monitors
        return monitors._reaper_pid()

    def talking(self):
        """REAPER parle par son OSC — mais il se tait quand rien ne bouge (aucun signal aux entrées : pas de vumètre), et
        le bridge le croyait muet : « REAPER not answering » ouvert après chaque rechargement du bridge sur un rack au
        repos (mesuré 2026-11-10, deux incidents, REAPER accusait pourtant chaque commande). Le battement de
        golem_clock.lua (presets/.clock.json, réécrit en continu ; toutes les boucles Lua partagent un contexte, donc
        golem_watch vit aussi) suffit à dire OUI. Son absence ne dit rien : on retombe sur le trafic OSC (None)."""
        import os
        import time
        try:
            if time.time() - os.stat(os.path.join(C.PRESETS_DIR, ".clock.json")).st_mtime < 6.0:
                return True
        except OSError:
            pass
        return None

    def ready_since(self, t0):
        from .. import monitors
        return monitors._watch_started_since(t0)        # golem_watch.lua a écrit « démarré » dans .watch.log

    def stop(self, timeout=12.0):
        """Arrête le REAPER de CE rack (jamais celui d'un banc) et attend sa mort réelle (il sauve sa config d'abord)."""
        import os
        import signal
        from .. import routes_system
        for pid in routes_system._rack_reaper_pids():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        return routes_system._wait_reaper_dead(timeout)

    def restart(self, why="requested"):
        """Linux : SIGTERM au REAPER du rack, attente de sa mort, provision/start.sh (routes_system). Windows/macOS :
        on réapplique les réglages audio en cours, ce qui relance REAPER avec eux (desktop_audio)."""
        import sys
        if sys.platform in ("win32", "darwin"):
            from .. import desktop_audio
            current = desktop_audio.settings()
            keys = ("sample_rate", "sample_rate_use", "buffer_size", "buffer_size_use")
            keys += (("driver", "input_first", "input_last", "output_first", "output_last")
                     if sys.platform == "win32" else ("input_device", "output_device"))
            apply = desktop_audio.start_apply({key: current[key] for key in keys}, ensure_running=True)
            return {"ok": True, "restarting": True, "apply": apply}
        from .. import routes_system
        routes_system._restart_reaper_async(why=why)
        return {"ok": True, "restarting": True}

    def audio(self):
        from ..routes_system import _read_bsize           # reaper.ini (Linux) ou la carte réelle (Windows/macOS)
        return {"buffer": _read_bsize()}

    def version(self):
        from ..rigstatus import reaper_version
        return reaper_version()
