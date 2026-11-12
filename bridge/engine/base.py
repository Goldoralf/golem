# SPDX-License-Identifier: GPL-3.0-or-later
"""Le contrat d'un moteur audio (docs/ardour-plan.md §2).

Le bridge ne parle plus à REAPER : il parle à un `EngineAdapter`. Deux canaux, comme aujourd'hui :
  - les COMMANDES : un dict `{"action": …}` (rig_recall, scene_apply, stomp, mixer_apply…). Le vocabulaire
    est celui que golem_watch.lua lit depuis toujours ; c'est lui, le contrat. `send` rend le `seq` posé, ou
    None quand le moteur ne sait pas faire cette action (il le dit, il ne la perd pas en silence) ;
  - le CHEMIN RAPIDE : potard, volume, mute, transport — sans file, sans accusé, au mieux (UDP).
Les témoins (presets/.rig-check.json, .livemap.json, .fxdump.json…) restent des fichiers aux schémas
inchangés : un moteur les écrit, le bridge les lit, sans savoir qui les a écrits.

Les adresses du chemin rapide (`track`, `fx`, `param`) sont celles que le moteur a lui-même publiées dans
le livemap : le bridge les recopie sans les interpréter.
"""
import logging

log = logging.getLogger("golem.engine")

TRANSPORT_OPS = ("play", "pause", "stop", "start")      # start = retour au début


class EngineAdapter:
    id = "none"
    # actions de commande acceptées ; None = toutes (REAPER : le vocabulaire est le sien)
    actions = None

    # ── commandes ────────────────────────────────────────────────────────────────────────
    def supports(self, action):
        return self.actions is None or action in self.actions

    def send(self, cmd):
        """Pose la commande. Rend son seq, ou None si le moteur ne la connaît pas."""
        if not self.supports(cmd.get("action")):
            self._unsupported(cmd.get("action"))
            return None
        return self._send(cmd)

    def _send(self, cmd):
        raise NotImplementedError

    _said = None

    def _unsupported(self, action):
        # une ligne par action, pas une par appel : un stomp au pied ne doit pas noyer le journal
        if self._said is None:
            self._said = set()
        if action not in self._said:
            self._said.add(action)
            log.warning(f"{self.id} : action « {action} » non prise en charge — ignorée")

    # ── chemin rapide ────────────────────────────────────────────────────────────────────
    def set_fx_param(self, track, fx, param, norm):
        return False

    def set_track_volume(self, track, value):
        return False

    def set_track_mute(self, track, muted):
        return False

    def transport(self, op):
        return False

    def refresh(self):
        """Redemande au moteur tout son état de télémétrie (sans le redémarrer)."""
        return False

    # ── télémétrie poussée par le moteur ─────────────────────────────────────────────────
    def start_feedback(self, on_message):
        """Ouvre le retour du moteur ; `on_message(address, args)` à chaque message."""

    def stop_feedback(self):
        pass

    # ── cycle de vie ─────────────────────────────────────────────────────────────────────
    def pid(self):
        """Le PID du process moteur, None s'il est éteint. Un PID (pas un booléen) : une relance plus rapide que la
        période de poll change le PID même si l'arrêt n'a jamais été vu."""
        return None

    def running(self):
        return self.pid() is not None

    def talking(self):
        """Le moteur répond-il au bridge ? None = on ne sait pas le dire autrement que par le trafic OSC (REAPER : le
        drapeau reaper_connected, posé par chaque message reçu) ; True/False = l'adaptateur le sait (un battement)."""
        return None

    def engine_started(self):
        """Appelé une fois le veilleur d'un NOUVEAU process moteur prêt (monitors) : ce que le moteur oublie à chaque
        démarrage se repose ici (Golem Engine : l'abonnement au retour de la surface OSC). REAPER : rien."""

    def ready_since(self, t0):
        """Le moteur lancé après `t0` lit-il ses commandes ? (seule preuve qu'un rappel ne sera pas perdu)"""
        return False

    def stop(self, timeout=10.0):
        """Arrête le process moteur et attend sa mort ; True si mort."""
        return self.pid() is None

    def restart(self, why="requested"):
        """(Re)lance le moteur sans bloquer : rend un dict pour l'API. Lève ValueError/RuntimeError/OSError si la
        relance ne peut pas partir (l'API répond 409)."""
        raise RuntimeError(f"{self.id}: restart not supported")

    def version(self):
        return None

    def descriptor(self):
        """Le descripteur config/engines/<id>.json, {} s'il manque."""
        from .. import engines
        return next((e for e in engines.descriptors() if e["id"] == self.id), None) or {}

    # ── carte son, vue du moteur (lot A2.2 : Dashboard) ─────────────────────────────────────
    def audio(self):
        """{buffer, rate, backend, device, dsp_load} — ce que le moteur sait de sa carte ; clés absentes = inconnu."""
        return {}

    def xruns(self):
        """Les xruns que le MOTEUR a comptés depuis son démarrage (surcharge DSP comprise), None s'il ne les compte pas
        (REAPER : le journal du noyau seul, monitors._read_xruns)."""
        return None

    def adopt_audio(self, audio):
        """À une bascule : reprendre le réglage audio du moteur d'avant ({buffer…}) quand on n'en a pas à soi."""

    def set_buffer(self, size):
        """Change le buffer ; rend un dict pour l'API. Lève ValueError/RuntimeError/OSError (409)."""
        raise RuntimeError(f"{self.id}: buffer change not supported")

    def inventory(self):
        """L'inventaire des plugins vu par le moteur, quand il en tient un à lui ; None = celui de REAPER fait foi
        (blockstatus.inventory, .fx-inventory.json)."""
        return None

    def missing_plugin(self, block_type):
        """Le moteur sait jouer ce type mais son plugin manque sur cette machine (REAPER : blockstatus le juge)."""
        return False

    def plays(self, block_type):
        """Ce moteur a-t-il un plugin pour ce type de bloc ? (REAPER : tous ; un autre moteur : sa table)"""
        return True

    def capabilities(self):
        """Les capacités déclarées par le descripteur (yes / no / planned)."""
        return dict(self.descriptor().get("capabilities") or {})
