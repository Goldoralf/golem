# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôleur du bloc DRUMS — boîte à rythmes au pied (foot_scene_claim, approche B,
doctrine 2026-07-21). Joue des patterns MIDI de batterie en boucle synchro-tempo à
travers un kit RS5k (golem_drums.lua).

Moteur de GESTES sur une seule pédale (fronts press/release), trois seuils :
  - ARRÊTÉ + tap                    -> PLAY (groove courant).
  - EN COURS + tap (< VAR_S)        -> STOP (2026-10-13 : « si je rappuie dessus ça doit couper » — un switch
                                       qui lance arrête ; le FILL au tap ne faisait RIEN sur un bloc sans fills, et
                                       les grooves d'usine n'en ont pas. Le fill n'a plus de geste au pied).
  - EN COURS + release VAR_S..STOP_S -> VARIATION (partie suivante, à la mesure).
  - EN COURS + maintenu >= STOP_S   -> STOP.

Émet {action:"drums", op:"play"|"variation"|"fill"|"stop", block, ...} vers
golem_drums.lua. État optimiste par bloc ; le retour .drums.json (poll) réconcilie.
"""
import threading
import time as _time

VAR_S = 0.60       # release entre VAR_S et STOP_S = variation
STOP_S = 1.50      # maintenu >= STOP_S = stop
FEEDBACK_GRACE_S = 2.5   # le temps laissé à golem_drums pour publier un play avant que son silence fasse foi


class DrumControl:
    def __init__(self, emit, on_change=None):
        self._emit = emit
        self._on_change = on_change or (lambda: None)
        self._state = {}                          # block -> {"playing": bool, "idx": int}
        self._press = {}                          # sw -> {block, patterns, fills, kit, t, timer, hold_fired}
        self._lock = threading.Lock()

    # ── lecture / réconciliation ──
    def snapshot(self):
        return {b: {k: v for k, v in s.items() if k != "t"} for b, s in self._state.items()}

    def apply_feedback(self, fb, authoritative=False):
        """`authoritative` : Reaper a publié un état VALIDE (.drums.json `present`). Un bloc que le bridge croit
        en cours mais que Reaper ne mentionne plus depuis FEEDBACK_GRACE_S est arrêté — sinon, après un crash ou
        une relance de Reaper, l'état optimiste restait « playing » pour toujours et le tap suivant devenait un
        FILL : SW10 ne relançait plus jamais la batterie (vécu le 2026-10-13, crash NAM pendant un rebuild)."""
        changed = False
        if authoritative:
            now = _time.monotonic()
            for b, cur in self._state.items():
                if cur.get("playing") and b not in (fb or {}) and now - cur.get("t", 0) > FEEDBACK_GRACE_S:
                    cur["playing"] = False
                    changed = True
        for b, s in (fb or {}).items():
            cur = self._state.get(b)
            if not cur:
                continue
            if cur.get("playing") and not s.get("playing"):
                cur["playing"] = False; changed = True
            if "idx" in s and cur.get("idx") != s.get("idx"):
                cur["idx"] = s.get("idx"); changed = True
        if changed:
            self._on_change()

    # ── moteur de gestes ──
    def on_edge(self, sw, on, block=None, patterns=None, fills=None, kit=None,
                sequence=None, seq_mode=None):
        with self._lock:
            if on:
                st = self._state.get(block, {"playing": False, "idx": 0})
                p = {"block": block, "patterns": list(patterns or []), "fills": list(fills or []),
                     "kit": kit, "sequence": list(sequence or []), "seq_mode": seq_mode,
                     "t": _time.monotonic(), "hold_fired": False, "timer": None}
                if st.get("playing"):                 # armer le STOP long
                    t = threading.Timer(STOP_S, self._stop_hold, args=(sw,))
                    t.daemon = True
                    p["timer"] = t
                    t.start()
                self._press[sw] = p
            else:
                p = self._press.pop(sw, None)
                if not p:
                    return
                if p.get("timer"):
                    p["timer"].cancel()
                if p["hold_fired"]:
                    return
                dt = _time.monotonic() - p["t"]
                st = self._state.setdefault(p["block"], {"playing": False, "idx": 0})
                if not st["playing"]:
                    self._play(p)
                elif dt < VAR_S:
                    self._stop_now(p["block"])
                else:                                  # VAR_S .. STOP_S
                    self._variation(p)

    def _play(self, p):
        st = self._state.setdefault(p["block"], {"playing": False, "idx": 0})
        idx = st.get("idx", 0)
        cmd = {"action": "drums", "op": "play", "block": p["block"], "kit": p.get("kit"),
               "patterns": p.get("patterns"), "fills": p.get("fills"), "idx": idx}
        # mode SONG : séquence d'étapes {i, times} + loop|once — golem_drums bascule en op=4
        if p.get("sequence"):
            cmd["sequence"] = p["sequence"]
            cmd["seq_mode"] = p.get("seq_mode") or "loop"
        # kit multi-micros : le mix voyage AVEC le play — golem_drums ne relit pas le preset.
        if p.get("mix"):
            cmd["mix"], cmd["master"] = p["mix"], p.get("master", -6)
        self._emit(cmd)
        st["playing"], st["idx"], st["t"] = True, idx, _time.monotonic()
        self._on_change()

    def _fill(self, p):
        if not p.get("fills"):
            return
        self._emit({"action": "drums", "op": "fill", "block": p["block"], "fill_idx": 0})
        self._on_change()

    def _variation(self, p):
        st = self._state.setdefault(p["block"], {"playing": False, "idx": 0})
        n = len(p.get("patterns") or []) or 1
        idx = (st.get("idx", 0) + 1) % n
        self._emit({"action": "drums", "op": "variation", "block": p["block"], "idx": idx})
        st["idx"] = idx
        self._on_change()

    def _stop_now(self, block):
        self._emit({"action": "drums", "op": "stop", "block": block})
        self._state.setdefault(block, {"playing": False, "idx": 0})["playing"] = False
        self._on_change()

    def _stop_hold(self, sw):
        with self._lock:
            p = self._press.get(sw)
            if not p:
                return
            p["hold_fired"] = True
            block = p["block"]
        self._emit({"action": "drums", "op": "stop", "block": block})
        st = self._state.setdefault(block, {"playing": False, "idx": 0})
        st["playing"] = False
        self._on_change()

    # ── entrées directes (parité écran /api/drums, tests) ──
    def tap(self, block, patterns, fills, kit, sequence=None, seq_mode=None):
        with self._lock:
            p = {"block": block, "patterns": list(patterns or []), "fills": list(fills or []), "kit": kit,
                 "sequence": list(sequence or []), "seq_mode": seq_mode}
            st = self._state.setdefault(block, {"playing": False, "idx": 0})
            self._stop_now(block) if st["playing"] else self._play(p)    # même geste qu'au pied : lance / arrête

    def variation(self, block, patterns):
        with self._lock:
            self._variation({"block": block, "patterns": list(patterns or [])})

    def stop(self, block):
        self._emit({"action": "drums", "op": "stop", "block": block})
        st = self._state.setdefault(block, {"playing": False, "idx": 0})
        st["playing"] = False
        self._on_change()

    # ── LA BATTERIE PILOTÉE PAR L'ARRANGEMENT (docs/arrangement.md §6, 2026-10-20) : le morceau la lance au premier
    # temps sur le groove de sa section, puis chaque section choisit le sien. Pas de séquence propre ici : la forme du
    # morceau n'a qu'un endroit, l'arrangement.
    def song_play(self, desc, idx=0):
        with self._lock:
            p = {"block": desc["block"], "patterns": list(desc.get("patterns") or []), "fills": list(desc.get("fills") or []),
                 "kit": desc.get("kit"), **({"mix": desc["mix"], "master": desc.get("master")} if desc.get("mix") else {})}
            self._state.setdefault(desc["block"], {"playing": False, "idx": 0})["idx"] = idx
            self._play(p)

    def song_pattern(self, block, idx):
        """Le groove `idx` à la prochaine mesure (le JSFX quantifie) — l'arrangement l'envoie pendant la dernière
        pulsation de la section, pour qu'il tombe sur la frontière."""
        with self._lock:
            self._emit({"action": "drums", "op": "variation", "block": block, "idx": int(idx)})
            self._state.setdefault(block, {"playing": True, "idx": 0})["idx"] = int(idx)
            self._on_change()

    def stop_orphans(self, valid_blocks, also_playing=None):
        """Stoppe les blocs drums EN COURS qui ne sont PLUS dans le preset rappelé (changement de
        preset). Le séquenceur JSFX boucle jusqu'à un stop explicite ; sans ça la batterie continue
        après un recall. Un simple changement de scène garde le bloc dans valid_blocks -> ne coupe pas
        (drums scene-invariant). `also_playing` = blocs rapportés EN COURS par Reaper (.drums.json) :
        source de vérité robuste après un reload du bridge (qui vide l'état optimiste _state)."""
        valid = set(valid_blocks or ())
        playing = {b for b, st in self._state.items() if st.get("playing")}
        playing |= set(also_playing or ())
        stopped = False
        for b in playing:
            if b and b not in valid:
                self._emit({"action": "drums", "op": "stop", "block": b})
                self._state.setdefault(b, {"playing": False, "idx": 0})["playing"] = False
                stopped = True
        if stopped:
            self._on_change()


def _resolve_sequence(pm):
    """Preset -> moteur : params.sequence = [{file, times}] (robuste aux réordonnancements de
    patterns). Rend (patterns_complets, sequence_indices) : les fichiers de la séquence absents de
    patterns sont AJOUTÉS en fin de banque, et chaque étape devient {i: index banque, times}."""
    patterns = list(pm.get("patterns") or [])
    seq = []
    for step in (pm.get("sequence") or []):
        f = step.get("file") if isinstance(step, dict) else None
        if not f:
            continue
        if f not in patterns:
            patterns.append(f)
        try:
            times = max(0, int(step.get("times", 1)))
        except (TypeError, ValueError):
            times = 1
        seq.append({"i": patterns.index(f), "times": times})
    return patterns, seq


def switches(preset):
    """{sw(int): {block, patterns, fills, kit, sequence, seq_mode}} des blocs `drums` au pied."""
    from . import store
    out = {}
    for b, _k in store._foot_blocks(preset or {}):
        if b.get("type") == "drums" and isinstance(b.get("foot"), int):
            pm = b.get("params") or {}
            patterns, seq = _resolve_sequence(pm)
            out[b["foot"]] = {"block": b.get("id"), "patterns": patterns,
                              "fills": pm.get("fills") or [], "kit": pm.get("kit"),
                              "sequence": seq, "seq_mode": pm.get("seq_mode") or "loop",
                              **resolve_mix(pm.get("kit"), pm)}
    return out


def blocks(preset):
    """Les blocs `drums` du preset, AU PIED OU NON — ceux que l'arrangement peut piloter :
    [{block, patterns, fills, kit, mix?, master?}]. Les motifs d'une séquence de bloc (mode SONG) y sont inclus, à la
    même place que pour le pied : un numéro de groove désigne le même fichier des deux côtés."""
    from . import store
    out = []
    for b, _lane in store.all_blocks(preset or {}):
        if isinstance(b, dict) and b.get("type") == "drums" and b.get("id"):
            pm = b.get("params") or {}
            patterns, _seq = _resolve_sequence(pm)
            out.append({"block": b["id"], "patterns": patterns, "fills": pm.get("fills") or [], "kit": pm.get("kit"),
                        **resolve_mix(pm.get("kit"), pm)})
    return out


def resolve_mix(kit_id, params):
    """Mix EFFECTIF d'un kit multi-micros : le mix D'USINE du kit, écrasé par les écarts du preset.

    Le preset ne stocke QUE les écarts (`mic<N>_gain` / `mic<N>_pan`, plus mix_master/mix_bleed) :
    un kit remplacé ou re-mixé en amont profite donc de son nouveau mix sans toucher au preset.
    Rend {} si le kit n'est pas multi-micros — la commande reste alors celle d'avant.
    """
    from . import kits as K
    k = K.get_kit(kit_id) if kit_id else None
    if not k or k.get("engine") != "drumgizmo" or not k.get("mix"):
        return {}
    pm = params or {}
    out = []
    for m in k["mix"]:
        ch = m.get("ch")
        g = pm.get(f"mic{ch}_gain")
        p = pm.get(f"mic{ch}_pan")
        out.append({"ch": ch,
                    "gain": float(g if g is not None else m.get("gain") or 0),
                    "pan": float(p if p is not None else m.get("pan") or 0)})
    master = pm.get("mix_master")
    return {"mix": out, "master": float(master if master is not None else -6)}
