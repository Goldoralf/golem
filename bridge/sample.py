# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôleur du bloc SAMPLE — lanceur de one-shots au pied (foot_scene_claim,
doctrine 2026-07-21).

Moteur de GESTES sur les fronts press/release d'un switch (comme le looper) :
  - TAP (appui court)      -> à l'arrêt : lance le SUIVANT de la liste (le premier
                              au départ ; liste d'un seul = toujours lui). Cycle.
                              Pendant qu'il sonne : COUPE (bascule, 01/11).
  - APPUI LONG (>= LONG_S) -> STOP.
One-shot : chaque sample joue jusqu'au bout, ou jusqu'au tap / stop qui le coupe.

Décision du mainteneur (01/11) : le tap BASCULE — un tap lance, le suivant coupe. Le tap
« coupe + lance le suivant » d'avant laissait le seul appui long pour arrêter, et l'écran n'en
a pas (un clic de /live = un tap) : en répète, impossible d'arrêter un sample de quatre
minutes. Le lancement reste INSTANTANÉ (pas de fenêtre double-tap = on tape sur le temps) ;
l'appui long coupe toujours.

Émet des commandes {action:"sample", op:"play"|"stop", block, idx, samples} via
le callback `emit` (le bridge les écrit dans .command.json -> golem_watch relaie
-> golem_sample.lua joue en RS5k). État optimiste par bloc ; le retour
.sample.json (poll) réconcilie la fin naturelle d'un one-shot.
"""
import threading

LONG_S = 0.60          # appui long = stop


class SampleControl:
    """Thread-safe (fronts pied = thread lecteur MIDI + timers). Un état par bloc
    sample (plusieurs lanceurs peuvent coexister sur des switches différents)."""

    def __init__(self, emit, on_change=None):
        self._emit = emit                         # (dict) -> écrit la commande vers Reaper
        self._on_change = on_change or (lambda: None)
        self._state = {}                          # block_id -> {"playing": bool, "idx": int}
        self._press = {}                          # sw -> {block, samples, timer, hold_fired}
        self._lock = threading.Lock()

    # ── lecture d'état (pour le snapshot / l'UI) ──
    def snapshot(self):
        return {bid: dict(st) for bid, st in self._state.items()}

    def apply_feedback(self, fb):
        """Réconcilie l'état optimiste avec le retour de golem_sample.lua
        (.sample.json) : {block_id: {playing, idx}}. Détecte la fin d'un one-shot."""
        changed = False
        for bid, s in (fb or {}).items():
            cur = self._state.get(bid)
            if cur and cur.get("playing") and not s.get("playing"):
                cur["playing"] = False              # le one-shot s'est terminé seul
                changed = True
        if changed:
            self._on_change()

    # ── moteur de gestes ──
    def on_edge(self, sw, on, block_id=None, samples=None, foot_idx=None):
        """Front d'un switch portant un bloc sample. `on` = press. block_id +
        samples fournis au PRESS (l'état vit côté bridge, la liste vient du preset)."""
        with self._lock:
            if on:
                p = {"block": block_id, "samples": list(samples or []),
                     "foot_idx": list(foot_idx) if foot_idx is not None else None,
                     "hold_fired": False}
                t = threading.Timer(LONG_S, self._hold, args=(sw,))
                t.daemon = True
                p["timer"] = t
                self._press[sw] = p
                t.start()
            else:
                p = self._press.pop(sw, None)
                if not p:
                    return
                if p.get("timer"):
                    p["timer"].cancel()
                if not p["hold_fired"]:
                    self._tap(p["block"], p["samples"], p.get("foot_idx"))

    def _tap(self, block_id, samples, foot_idx=None):
        if not block_id or not samples:
            return
        # rotation À LA CARTE : on ne parcourt que les entrées marquées « au pied », mais on
        # émet leur index dans la liste COMPLÈTE (le Lua y a bâti ses RS5k).
        ring = [i for i in (foot_idx if foot_idx is not None else range(len(samples)))
                if 0 <= i < len(samples)]
        if not ring:
            return                                  # aucune entrée au pied : le switch ne fait rien
        st = self._state.setdefault(block_id, {"playing": False, "idx": -1})
        if st["playing"]:
            # tap pendant qu'il sonne = COUPER (bascule, voir l'en-tête) — le tap suivant lance
            # l'entrée d'après
            self._emit({"action": "sample", "op": "stop", "block": block_id})
            st["playing"] = False
            self._on_change()
            return
        pos = ring.index(st["idx"]) if st["idx"] in ring else -1
        idx = ring[0] if pos < 0 else ring[(pos + 1) % len(ring)]
        self._emit({"action": "sample", "op": "play", "block": block_id,
                    "idx": idx, "samples": samples})
        st["playing"], st["idx"] = True, idx
        self._on_change()

    def _hold(self, sw):
        with self._lock:
            p = self._press.get(sw)
            if not p:
                return
            p["hold_fired"] = True
            block_id = p["block"]
        if block_id:
            self._emit({"action": "sample", "op": "stop", "block": block_id})
            st = self._state.setdefault(block_id, {"playing": False, "idx": -1})
            st["playing"] = False
            self._on_change()

    # ── entrées directes (parité écran /api/sample, tests) ──
    def tap(self, block_id, samples, foot_idx=None):
        with self._lock:
            self._tap(block_id, list(samples or []), foot_idx)

    def stop(self, block_id):
        self._emit({"action": "sample", "op": "stop", "block": block_id})
        st = self._state.setdefault(block_id, {"playing": False, "idx": -1})
        st["playing"] = False
        self._on_change()

    def all_stop(self):
        """Coupe tous les samples (ex. changement de mode). Les samples SCENE-INVARIANT
        survivent aux scènes, donc à n'appeler que sur un vrai changement de preset/mode."""
        for bid in list(self._state):
            self._emit({"action": "sample", "op": "stop", "block": bid})
            self._state[bid]["playing"] = False
        self._on_change()


# ── FORME D'UNE ENTRÉE (décision 2026-07-31) ──────────────────────────────────────────
# Une entrée de `params.samples` vaut soit "chemin/vers.wav" (forme historique, TOUJOURS lue),
# soit {"file": "…", "foot": false}. `foot: false` = le morceau peut le déclencher, mais il
# N'ENTRE PAS dans la rotation du pied.
# POURQUOI : la liste du bloc EST l'ordre de rotation (`_tap` fait (idx+1) % len). Sans ce
# drapeau, un morceau à douze cues ferait défiler douze sons sous le pied — absurde. La lane
# d'arrangement peut donc enrichir la palette sans toucher au geste du musicien.
def entry_file(e):
    return e if isinstance(e, str) else (e or {}).get("file") or ""


def entry_foot(e):
    """Une entrée sans drapeau reste AU PIED : les listes écrites avant ce contrat ne changent
    pas de comportement (aucune migration)."""
    return True if isinstance(e, str) else (e or {}).get("foot") is not False


def files_of(block):
    """La liste COMPLÈTE des chemins — c'est elle qui construit les RS5k côté Lua, donc les
    index restent stables quoi qu'il arrive au pied."""
    return [f for f in (entry_file(e) for e in ((block or {}).get("params") or {}).get("samples") or []) if f]


def foot_indices(block):
    """Les INDEX (dans la liste complète) que le pied fait défiler."""
    return [i for i, e in enumerate(((block or {}).get("params") or {}).get("samples") or [])
            if entry_file(e) and entry_foot(e)]


def switches(preset):
    """{sw(int): {block, samples, foot_idx}} des blocs `sample` assignés au pied (foot 1-10).
    Non-unique : plusieurs lanceurs possibles. Lu au recall pour router les fronts.
    `samples` = la liste COMPLÈTE (le Lua bâtit un RS5k par index) ; `foot_idx` = ceux que le
    pied parcourt. Deux listes plutôt qu'une : filtrer avant l'envoi décalerait les index."""
    from . import store
    out = {}
    for b, _k in store._foot_blocks(preset or {}):
        if b.get("type") == "sample" and isinstance(b.get("foot"), int):
            out[b["foot"]] = {"block": b.get("id"), "samples": files_of(b),
                              "foot_idx": foot_indices(b)}
    return out
