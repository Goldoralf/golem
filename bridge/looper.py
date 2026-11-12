# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôleur du LOOPER (fork golem_super8 sur la piste "Looper").

Deux responsabilités :
  1. DISPATCH : envoyer une note de commande au JSFX. Chemin primaire = OSC FX_PARAM sur le
     slider « GoleM Cmd » (valeur = seq*128 + note, seq 1..127 cycle -> retrigger garanti,
     normalisé V/16383 — chemin ~1-2 ms, prouvé par la pédale EXP). L'adresse (track/fx/param)
     vient de presets/.looper.json (publiée par golem_looper.lua). Fallback tant que l'adresse
     est inconnue : presets/.looper-cmd.json -> ring gmem (~15-35 ms, poll defer).
  2. GESTES du pied (fronts Note on/off du FCB, contrat v2) : tap / double-tap / appui long
     par slot + contrôles globaux, traduits en notes Super8 :
       switches 1-4 (LOOP_SWITCHES ; la table du preset dit lequel porte quelle boucle, l'ordre
       des lignes fait le slot — défaut 1/2/3 -> lanes 1/2/k) :
         press  + slot vide       -> REC (immédiat — le timing du press EST la loop)
         press  + slot rec/dub    -> ferme la loop -> PLAY (immédiat, définit la longueur maîtresse)
         press  + slot play/stop  -> arme le timer d'appui long (l'action attend le release)
         hold >= LONG_S           -> CLEAR du slot
         release + stop           -> PLAY (resume — Super8 ré-entre à la position globale)
         release + play, 2e release < DOUBLE_S -> OVERDUB ; sinon STOP différé de DOUBLE_S
       switch 5 : press -> PLAY/STOP ALL (toggle stock Super8), cf. SWITCHES
       switch 10 : hold >= CONFIRM_S -> KILL ALL (delete all ; le tap court ne fait rien)
       switches 6-9 : PAS au looper — des stomps normaux du preset

L'état AFFICHÉ est celui du retour gmem (.looper.json, 50-150 ms de latence) avec un override
OPTIMISTE de 250 ms après chaque dispatch (sinon un double press rapide relit un état périmé).
Notes Super8 par slot (défauts stock + fork) : 36/37 · 41/42 · 45/46 · 50/51 · playall 21 · kill 20 ·
clear 24/25/26/27. Cf. reaper/Effects/golem_super8 (en-tête) et docs/looper.md.
"""
import json, os, threading, time

from . import config as C
from .golog import get

log = get("looper")

# (rec_note, play_note, clear_note) par slot — défauts stock Super8 (paires liées) + fork.
# QUATRE paires : le JSFX est un 8 canaux, GoleM l'exploite en 4 stéréo. La 4e (canaux 7·8,
# notes 50/51, clear 27) dormait depuis le début — cf. docs/looper.md §6.
NOTES = {0: (36, 37, 24), 1: (41, 42, 25), 2: (45, 46, 26), 3: (50, 51, 27)}
MAX_LOOPS = len(NOTES)
PLAYALL_NOTE = 21
KILL_NOTE = 20
# Switches ASSIGNABLES à une boucle (docs/looper.md, amendement 2026-10-14 soir) : la rangée PROCHE du pied.
# 5 et 10 sont des gestes GLOBAUX : ils ne portent jamais de boucle. SW 6-9 redeviennent des stomps.
LOOP_SWITCHES = (1, 2, 3, 4)
# une table d'AVANT l'amendement (boucles sur la rangée du fond) se lit sur la rangée proche, dans le même ordre
LEGACY_LOOP_SW = {6: 1, 7: 2, 8: 3, 9: 4}
# Table par DÉFAUT (docs/looper.md §2). Elle n'est jamais écrite dans le preset en silence — le tiroir la
# matérialise à la 1re édition.
DEFAULT_LOOPS = ({"sw": 1, "src": "1"}, {"sw": 2, "src": "2"}, {"sw": 3, "src": "k"})
SLOT_OF_SWITCH = {1: 0, 2: 1, 3: 2}     # carte par défaut ; le preset la remplace (set_loops)
# ── QUELS SWITCHES LE LOOPER POSSÈDE (docs/looper.md §3) ────────────────────────────────
# Les boucles sur la rangée PROCHE (1-4), « tout jouer / tout arrêter » en SW5 — le geste qu'on
# fait sans regarder, et SW5 donne les deux fronts (la rangée des scènes est compilée en
# `preset`, dont la face off est un vrai NoteOff) — et « tout effacer » en appui long sur SW10.
# SW6-9 restent des stomps : un preset looper sans le moindre effet au pied n'aurait pas de sens.
# ⚠ La source est ICI, jamais une plage de switches recopiée ailleurs.
ALL_SWITCH  = 5                         # play / stop de toutes les boucles ensemble
KILL_SWITCH = 10                        # appui long (CONFIRM_S) = tout effacer
SWITCHES = frozenset({ALL_SWITCH, *SLOT_OF_SWITCH, KILL_SWITCH})   # défaut : 1,2,3,5,10
# ⚠ SWITCHES est le DÉFAUT. Le jeu réel dépend du preset (une 4e boucle prend SW4) et vit dans
# `LooperControl.switches()`. Tout appelant qui décide « ce switch est-il au looper ? » doit
# interroger l'instance, pas cette constante — sinon SW4 resterait une scène alors qu'il boucle.


def normalize_loops(loops):
    """Table de boucles -> liste propre [{sw, src, label}], au plus MAX_LOOPS lignes.
    Rejette les switches hors LOOP_SWITCHES et les doublons de switch (premier arrivé gagne).
    Une table vide/absente rend le DÉFAUT (docs/looper.md §2)."""
    if not loops:
        return [dict(r) for r in DEFAULT_LOOPS]
    out, seen = [], set()
    for r in loops:
        if not isinstance(r, dict):
            continue
        try:
            sw = int(r.get("sw"))
        except (TypeError, ValueError):
            continue
        sw = LEGACY_LOOP_SW.get(sw, sw)
        src = str(r.get("src") or "").strip()
        if sw not in LOOP_SWITCHES or sw in seen or not src:
            continue
        seen.add(sw)
        row = {"sw": sw, "src": src}
        if r.get("label"):
            row["label"] = str(r["label"])
        # le volume de la boucle à la lecture (mixer de /live, 2026-10-14) : dB −60..0, et son mute
        if r.get("level") is not None:
            try:
                row["level"] = round(max(-60.0, min(0.0, float(r["level"]))), 1)
            except (TypeError, ValueError):
                pass
        if r.get("mute"):
            row["mute"] = True
        out.append(row)
        if len(out) >= MAX_LOOPS:
            break
    return out
SLOT_NAMES = ["gtr", "vox", "syn", "aux"]     # noms de journal, pas d'UI

DOUBLE_S = 0.40      # fenêtre double-tap (release->release) ; aussi le délai du stop différé
LONG_S = 0.60        # appui long = clear du slot
CONFIRM_S = 1.2      # appui long du switch 10 = kill all (confirmation par la durée)
OPTIMISTIC_S = 0.25  # durée de l'override optimiste post-dispatch (le retour gmem met 50-150 ms)


class LooperControl:
    """Moteur de gestes + dispatch. Thread-safe (timers threading + callbacks foot).
    `osc` = le moteur actif (EngineAdapter.set_fx_param) ; `get_state`/`set_slot_opt` branchés sur RigState par app.py."""

    def __init__(self, osc, on_change=None):
        self._osc = osc
        self._on_change = on_change or (lambda: None)
        self._seq = 0
        self._addr = None            # {"track","fx","cmd_param"} — publié par .looper.json (monitors)
        self._addr_after = 0.0       # une adresse publiée avant ce moment est périmée (forget_addr)
        self._opt = {}               # slot -> (state, expiry) : override optimiste
        self._fb = {}                # slot -> état du retour gmem ("empty|rec|dub|play|stop")
        # Table du preset COURANT (docs/looper.md §1) : [{sw, src, label}], l'index = le slot,
        # donc la paire stéréo du JSFX. Posée au recall par app._bind_foot_services.
        self._loops = [dict(r) for r in DEFAULT_LOOPS]
        self._slot_of_sw = dict(SLOT_OF_SWITCH)
        self._press_t = {}           # switch -> horodatage du press en cours
        self._last_release = {}      # switch -> horodatage du DERNIER release (double-tap)
        self._timers = {}            # switch -> Timer actif (long-press ou stop différé)
        self._lock = threading.Lock()
        # docs/looper.md, addendum 2026-10-14 : () -> {"bpm", "beats", "snap", "count_in"} ou None — posé par app.py
        # (le tempo du preset, la mesure du click, « une grille joue-t-elle ? », le réglage du bloc)
        self.timing = None
        self._pending_cfg = None     # calage à joindre à la PROCHAINE commande quand elle passe par le fichier
        self._fresh = set()          # slots dont c'est la 1re prise (vide -> rec) : leur fermeture peut enchaîner une couche
        self._first_snap = False     # la 1re boucle est-elle calée par le JSFX (calage ou décompte) ?
        self._all_level = 1.0        # le niveau de toutes les boucles (EXP1) — remis à 1 à chaque rappel

    # ── table de boucles du preset courant (docs/looper.md §1) ──
    def set_loops(self, loops):
        """Pose la table du preset : l'ORDRE fait le slot (ligne n -> paire n du JSFX).
        Une table absente rend le défaut 1/2/3 -> lanes 1/2/k."""
        rows = normalize_loops(loops)
        with self._lock:
            self._loops = rows
            self._slot_of_sw = {r["sw"]: i for i, r in enumerate(rows)}
        self._all_level = 1.0
        self.push_levels()                  # sans adresse (rappel en cours) : reposé dès qu'elle est publiée

    # ── le volume de chaque boucle, à la lecture (docs/looper.md, mixer des boucles du 2026-10-14) ──
    # sliders « GoleM Loop N dB » (cmd+3..cmd+6, −60..0) et « GoleM Loops level » (cmd+7, 0..1 : la pédale EXP1)
    def push_levels(self):
        """Pose le volume de CHAQUE boucle de la table (muette = −60) sur le JSFX. Un slot sans ligne = 0 dB."""
        addr = self._addr
        if not (addr and self._osc):
            return False
        with self._lock:
            rows = [dict(r) for r in self._loops]
        for i in range(MAX_LOOPS):
            r = rows[i] if i < len(rows) else {}
            db = -60.0 if r.get("mute") else float(r.get("level") or 0.0)
            self._osc.set_fx_param(addr["track"], addr["fx"], addr["cmd_param"] + 3 + i, (db + 60.0) / 60.0)
        self._osc.set_fx_param(addr["track"], addr["fx"], addr["cmd_param"] + 7, self._all_level)
        return True

    def set_slot_level(self, slot, db=None, mute=None):
        """Le fader d'une boucle (mixer de /live) : la table du preset courant change, le son tout de suite."""
        with self._lock:
            if not (0 <= slot < len(self._loops)):
                return None
            r = self._loops[slot]
            if db is not None:
                r["level"] = round(max(-60.0, min(0.0, float(db))), 1)
            if mute is not None:
                if mute:
                    r["mute"] = True
                else:
                    r.pop("mute", None)
            out = dict(r)
        self.push_levels()
        return out

    def set_all_level(self, norm):
        """La pédale EXP1 d'un preset looper (quand elle n'est assignée à rien) : le niveau de TOUTES les boucles."""
        self._all_level = max(0.0, min(1.0, float(norm)))
        addr = self._addr
        if addr and self._osc:
            self._osc.set_fx_param(addr["track"], addr["fx"], addr["cmd_param"] + 7, self._all_level)

    def loops(self):
        with self._lock:
            return [dict(r) for r in self._loops]

    def switches(self):
        """Les switches que le looper POSSÈDE avec ce preset : les boucles + les deux gestes
        globaux. C'est LA source — SWITCHES (constante) n'est que le défaut."""
        with self._lock:
            return frozenset({ALL_SWITCH, KILL_SWITCH, *self._slot_of_sw})

    def _slot(self, sw):
        with self._lock:
            return self._slot_of_sw.get(sw)

    # ── adresse de commande + retour d'état (posés par monitors._poll_looper) ──
    def set_addr(self, addr, published_at=None):
        """L'adresse OSC publiée par golem_looper.lua. Un INDEX de piste, qui change quand le rig se reconstruit
        (vécu le 2026-10-14 : piste 21, puis 20 après un rappel) — d'où `forget_addr` au rappel : on n'accepte
        plus qu'une adresse publiée APRÈS lui."""
        if published_at is not None and published_at < self._addr_after:
            return
        fresh = addr and addr != self._addr
        self._addr = addr
        if fresh:
            self.push_levels()              # une piste (re)trouvée : ses volumes de boucle repartent de la table

    def forget_addr(self):
        """Au rappel d'un preset (le rig se reconstruit, la piste du Looper peut changer de numéro). Vécu le
        2026-10-14 : « au premier chargement, le premier appui sur SW6 ne marche pas, le second oui » — l'OSC
        partait vers l'ANCIEN index (une autre piste, dont il pouvait écrire un paramètre de plugin). D'ici à la
        prochaine publication, les commandes passent par le fichier : golem_looper.lua retrouve la piste par NOM."""
        self._addr = None
        self._addr_after = time.time()

    def set_feedback(self, slots, firstrec=0):
        """slots = [{"st","has"}×4] bruts du .looper.json ; firstrec = canal (1-based) qui définit la
        loop maîtresse en ce moment. st==2 = enregistre : REC si c'est la prise maîtresse initiale,
        DUB sinon (recouche calée sur la grille existante)."""
        fb = {}
        for i, s in enumerate(slots[:MAX_LOOPS]):
            st, has = int(s.get("st", 0)), bool(s.get("has"))
            in_pair = firstrec and (firstrec - 1) in (i * 2, i * 2 + 1)
            if st == 2:
                fb[i] = "rec" if in_pair else "dub"
            elif st == 1:
                fb[i] = "play"
            else:
                fb[i] = "stop" if has else "empty"
        with self._lock:
            self._fb = fb

    def slot_state(self, slot):
        """État effectif d'un slot : override optimiste (récent) sinon retour gmem."""
        with self._lock:
            opt = self._opt.get(slot)
            if opt and time.time() < opt[1]:
                return opt[0]
            return self._fb.get(slot, "empty")

    def _set_opt(self, slot, st):
        with self._lock:
            self._opt[slot] = (st, time.time() + OPTIMISTIC_S)
        self._on_change()

    # ── dispatch d'une note de commande ──
    def dispatch(self, note):
        self._seq = (self._seq % 127) + 1              # 1..127 (jamais 0 : le fork ignore < 128)
        addr = self._addr
        if addr and self._osc:
            v = (self._seq * 128 + int(note)) / 16383.0
            ok = self._osc.set_fx_param(addr["track"], addr["fx"], addr["cmd_param"], v)
            if ok:
                return True
        # fallback : fichier poll é par golem_looper.lua (ring gmem) — il porte aussi le calage de la 1re boucle,
        # que le Lua pose sur les sliders AVANT les notes (sans adresse OSC, _send_timing n'a rien pu écrire)
        try:
            tmp = C.LOOPER_CMD_FILE + ".tmp"
            doc = {"seq": self._seq, "notes": [int(note)]}
            if self._pending_cfg:
                doc["cfg"], self._pending_cfg = self._pending_cfg, None
            with open(tmp, "w") as f:
                json.dump(doc, f)
            os.replace(tmp, C.LOOPER_CMD_FILE)
            return True
        except Exception as e:
            log.error("dispatch KO: %s" % (e,))
            return False

    # ── le calage de la 1re boucle (docs/looper.md, addendum 2026-10-14) ──
    def _send_timing(self):
        """Rend le calage envoyé (dict) — ou None — après l'avoir posé sur les sliders (ou mis de côté pour le fichier)."""
        return self._send_timing_impl()

    def _send_timing_impl(self):
        """Tempo + mode posés sur les sliders « GoleM Tempo » / « GoleM Mode » JUSTE AVANT la commande : le JSFX
        décide à l'échantillon (décompte d'une mesure, fermeture calée sur la barre). Un JSFX d'avant (sans ces
        sliders) ignore l'écriture : le looper reste libre, comme avant."""
        addr, t = self._addr, None
        try:
            t = self.timing() if self.timing else None
        except Exception as e:                        # jamais fatal : sans calage, le looper reste libre
            log.warning("looper timing: %s" % (e,))
        if not t:
            return None
        bpm = max(0.0, min(400.0, float(t.get("bpm") or 0)))
        beats = max(1, min(16, int(t.get("beats") or 4)))
        mode = (beats * 10 + (1 if t.get("snap") else 0) + (2 if t.get("count_in") else 0)
                + (4 if t.get("rec_dub") else 0))
        if not (addr and self._osc):
            self._pending_cfg = {"tempo": round(bpm, 2), "mode": mode}   # voyagera avec la commande (fichier)
            return t
        self._osc.set_fx_param(addr["track"], addr["fx"], addr["cmd_param"] + 1, bpm / 400.0)
        self._osc.set_fx_param(addr["track"], addr["fx"], addr["cmd_param"] + 2, mode / 999.0)
        return t

    def _all_empty(self):
        return all(self.slot_state(s) == "empty" for s in NOTES)

    # ── actions par slot (partagées pied/écran) ──
    def slot_tap(self, slot):
        """Cycle : vide -> REC ; rec/dub -> PLAY (ferme la loop) ; stop -> PLAY ; play -> STOP."""
        st = self.slot_state(slot)
        rec, play, _ = NOTES[slot]
        self._pending_cfg = None
        first = st == "empty" and self._all_empty()
        t = None
        if first or st == "rec":
            t = self._send_timing()                    # la 1re boucle : son départ (décompte) et sa fermeture (barre)
        if first:
            self._first_snap = bool(t and float(t.get("bpm") or 0) > 0 and (t.get("snap") or t.get("count_in")))
        if st == "empty":
            self.dispatch(rec); self._set_opt(slot, "rec")
            self._fresh.add(slot)
        elif st in ("rec", "dub"):
            fresh = slot in self._fresh
            self._fresh.discard(slot)
            if t is None and fresh:
                try:
                    t = self.timing() if self.timing else None
                except Exception:
                    t = None
            dub = bool(fresh and t and t.get("rec_dub"))
            self.dispatch(play)
            if dub and not (st == "rec" and self._first_snap):
                self.dispatch(rec)                     # « Rec → Dub » : la couche suivante, dans la foulée
            # (la 1re boucle CALÉE se ferme à la barre, dans le JSFX — c'est lui qui enchaîne, drapeau 4)
            self._set_opt(slot, "dub" if dub else "play")
        elif st == "stop":
            self.dispatch(play); self._set_opt(slot, "play")
        else:                                          # play -> stop
            self.dispatch(play); self._set_opt(slot, "stop")
        log.info("slot %s tap: %s -> %s" % (SLOT_NAMES[slot], st, self.slot_state(slot)))

    def slot_dub(self, slot):
        """PLAY <-> OVERDUB (note rec sur une loop existante)."""
        st = self.slot_state(slot)
        rec, _, _ = NOTES[slot]
        if st in ("play", "dub"):
            self.dispatch(rec)
            self._set_opt(slot, "play" if st == "dub" else "dub")
            log.info("slot %s overdub -> %s" % (SLOT_NAMES[slot], self.slot_state(slot)))

    def slot_clear(self, slot):
        self._fresh.discard(slot)
        self.dispatch(NOTES[slot][2]); self._set_opt(slot, "empty")
        log.info("slot %s CLEAR" % SLOT_NAMES[slot])

    def toggle_all(self):
        self.dispatch(PLAYALL_NOTE)
        log.info("play/stop ALL")
        self._on_change()

    def clear_all(self):
        self.dispatch(KILL_NOTE)
        for s in NOTES:
            self._set_opt(s, "empty")
        log.info("KILL ALL")

    # ── API écran (POST /api/looper) ──
    def api_action(self, op, slot=None):
        if op == "tap" and slot in NOTES:
            self.slot_tap(slot)
        elif op == "dub" and slot in NOTES:
            self.slot_dub(slot)
        elif op == "clear" and slot in NOTES:
            self.slot_clear(slot)
        elif op == "toggle_all":
            self.toggle_all()
        elif op == "clear_all":
            self.clear_all()
        else:
            return {"ok": False, "error": "unknown op"}
        return {"ok": True}

    # ── moteur de gestes du pied (fronts Note on/off des switches 1-10) ──
    def on_edge(self, sw, on):
        now = time.time()
        if on:
            self._press_t[sw] = now
            self._cancel(sw)
            slot = self._slot(sw)
            if slot is not None:
                st = self.slot_state(slot)
                if st == "empty":                      # timing critique : REC au press
                    self.slot_tap(slot)
                    self._press_t.pop(sw, None)        # action consommée (le release ne fait rien)
                elif st in ("rec", "dub"):             # fermer la loop au press (définit la longueur)
                    self.slot_tap(slot)
                    self._press_t.pop(sw, None)
                else:                                  # play/stop : l'action attend le release ; arme le clear
                    self._arm(sw, LONG_S, lambda s=slot, w=sw: self._long_fire(w, lambda: self.slot_clear(s)))
            elif sw == ALL_SWITCH:
                self.toggle_all()
            elif sw == KILL_SWITCH:
                self._arm(sw, CONFIRM_S, lambda w=sw: self._long_fire(w, self.clear_all))
            return

        # release
        pressed_at = self._press_t.pop(sw, None)
        self._cancel(sw)                               # l'appui long n'a pas atteint son seuil
        if pressed_at is None:                         # press déjà consommé (rec/close/long)
            return
        slot = self._slot(sw)
        if slot is None:
            return
        st = self.slot_state(slot)
        last_rel = self._last_release.get(sw, 0)
        self._last_release[sw] = now
        if st == "stop":                               # resume immédiat
            self.slot_tap(slot)
        elif st in ("play", "dub"):
            if now - last_rel < DOUBLE_S:              # double-tap -> overdub on/off
                self.slot_dub(slot)
            elif st == "play":                         # tap simple -> STOP, différé (fenêtre du double-tap)
                self._arm(sw, DOUBLE_S, lambda s=slot: self.slot_tap(s))

    def _long_fire(self, sw, action):
        """Le seuil d'appui long est atteint : consomme le press (le release ne fera rien) et agit."""
        self._press_t.pop(sw, None)
        action()

    def _arm(self, sw, delay, fn):
        self._cancel(sw)
        t = threading.Timer(delay, fn)
        t.daemon = True
        self._timers[sw] = t
        t.start()

    def _cancel(self, sw):
        t = self._timers.pop(sw, None)
        if t:
            t.cancel()
