# SPDX-License-Identifier: GPL-3.0-or-later
"""Lien OSC bidirectionnel avec Reaper.

- Envoi  (bridge -> Reaper) : déclencher une action (ReaScript), régler un volume…
- Réception (Reaper -> bridge) : feedback OSC (transport, volumes, meters) -> callback.

Le device OSC est configuré côté Reaper via reaper/OSC/golem.ReaperOSC :
Reaper écoute sur REAPER_OSC_SEND_PORT, renvoie son feedback sur BRIDGE_OSC_RECV_PORT.
"""
import threading
from pythonosc.udp_client import SimpleUDPClient
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer


class ReaperLink:
    def __init__(self, send_host, send_port, recv_port, on_message=None):
        self._client = SimpleUDPClient(send_host, send_port)
        self._on_message = on_message
        disp = Dispatcher()
        disp.set_default_handler(self._recv)
        # On n'écoute que là d'où Reaper parle. Reaper local = boucle locale : écouter sur
        # 0.0.0.0 ouvrait un port UDP sans authentification à tout le réseau du rack, et sous
        # Windows c'est LUI qui déclenchait l'invite du pare-feu au premier lancement
        # (mesuré sur la VM le 2026-10-01 : seul socket du bridge hors 127.0.0.1).
        local = send_host in ("127.0.0.1", "localhost", "::1")
        self._addr = ("127.0.0.1" if local else "0.0.0.0", recv_port)
        self._disp = disp
        # le port s'ouvre au DÉMARRAGE, pas à l'import (audit 2026-10-15) : importer bridge.app — un test, un outil —
        # pendant qu'un bridge tourne échouait sur « Address already in use »
        self._server = None

    def start(self):
        self._server = ThreadingOSCUDPServer(self._addr, self._disp)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        """Arrête l'écoute ET libère le port (une bascule de moteur rouvre le même port pour l'autre moteur)."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # — réception —
    def _recv(self, address, *args):
        if self._on_message:
            self._on_message(address, args)

    # — envoi (best-effort : si Reaper n'écoute pas, l'UDP part dans le vide, sans erreur) —
    def send(self, address, value=1.0):
        try:
            self._client.send_message(address, value)
            return True
        except OSError:
            return False

    def trigger_action(self, command_id):
        """Déclenche une action Reaper.
        - named command ('_RS...' / '_SWS...') -> /action/str <string>  (pattern golem.ReaperOSC)
        - command number natif (int)           -> /action <int>
        """
        cid = str(command_id).strip()
        if cid.lstrip("-").isdigit():
            return self.send("/action", int(cid))
        return self.send("/action/str", cid)

    def set_track_volume(self, track_idx, value):
        return self.send(f"/track/{track_idx}/volume", float(value))

    def set_fx_param(self, track_idx, fx_idx, param_idx, norm):
        """Règle un param d'FX en NORMALISÉ (0..1), temps réel (pédale EXP). fx/param 0-based côté
        appelant -> 1-based côté OSC (pattern FX_PARAM de golem.ReaperOSC)."""
        return self.send(f"/track/{track_idx}/fx/{fx_idx + 1}/fxparam/{param_idx + 1}/value",
                         max(0.0, min(1.0, float(norm))))

    def set_track_mute(self, track_idx, muted):
        return self.send(f"/track/{track_idx}/mute", 1.0 if muted else 0.0)
