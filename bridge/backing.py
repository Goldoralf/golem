# SPDX-License-Identifier: GPL-3.0-or-later
"""Contrôleur des BACKING TRACKS (stems golem.fm joués par Reaper).

Deux canaux vers Reaper (cf. plan + spike golem-reascript 2026-07-10) :
  - play/pause/stop/rewind : OSC /action natif (1007/1008/1016/40042) — zéro
    plomberie, latence pied minimale. Le bridge DÉCIDE d'après l'état publié
    (.backing.json) : plus prévisible qu'un toggle aveugle.
  - load/unload/seek/mix : .command.json {"action":"backing", op, …} -> branche
    golem_watch (exempte SETTLE) -> ProjExtState -> golem_backing.lua (qui
    manipule les ITEMS de ses propres pistes — jamais de FX).

⚠ RÉGRESSION 2026-07-26 (retour utilisateur : « je lance l'enregistrement, le backing
se lance, je le coupe, la prise est tronquée à la seconde ») : 1007/1008/1016/40042 sont
des actions de TRANSPORT GLOBAL — le SEUL transport de Reaper, celui que golem_perfrec
utilise pour enregistrer (mode "output"). 1016 (stop) en particulier CLÔT l'item en cours
d'enregistrement. Donc : PENDANT une prise perf-rec (presets/.perf.json.recording), on
NE TOUCHE PLUS au transport pour play/pause/stop/restart — on route vers golem_backing.lua
(op "mute") qui coupe/rétablit juste le bus, transport intact. Le cas symétrique (le
backing se met à jouer tout seul en lançant une prise) est traité côté golem_perfrec
(auto-mute au démarrage si le transport n'était pas DÉJÀ en lecture).

Gestes du pied (bloc virtuel « backing-track » assigné à un switch, Notes 6-10) :
  press  + à l'arrêt      -> PLAY immédiat (le timing du départ est musical)
  press  + en lecture     -> arme l'appui long ; l'action attend le release
  hold >= LONG_S          -> STOP + rewind
  release (lecture) : 2e release < DOUBLE_S -> RESTART (seek 0, reste en lecture)
                      sinon PAUSE différée de DOUBLE_S (fenêtre du double-tap)

Séquencement post-recall : un rig_recall lance des chargements NAM/IR asynchrones ;
on n'émet le `load` de la chanson du preset qu'après RECALL_SETTLE_S (> SETTLE 0,5 s
du veilleur) — cf. l'invariant anti-segfault. Cache-first : on ne charge que si les
stems sont dans assets/backing/<slug>/.
"""
import json, os, threading, time

from . import config as C
from . import golemfm
from .commands import write_command

ACT_PLAY, ACT_PAUSE, ACT_STOP, ACT_GOTO_START = 1007, 1008, 1016, 40042


def _perf_recording():
    """True pendant une prise perf-rec — cf. régression 2026-07-26 en tête de fichier."""
    try:
        with open(os.path.join(C.PRESETS_DIR, ".perf.json")) as f:
            return bool(json.load(f).get("recording"))
    except Exception:
        return False

DOUBLE_S = 0.40           # fenêtre double-tap (restart) ; aussi le délai de la pause différée
LONG_S = 0.60             # appui long = stop + rewind
RECALL_SETTLE_S = 0.7     # > SETTLE (0,5 s) de golem_watch : le load attend la fin du rebuild
OPTIMISTIC_S = 0.35       # override optimiste du playing (le retour .backing.json met ~50-250 ms)


class BackingControl:
    """Transport + gestes + séquencement. Thread-safe (timers + callbacks pied).
    `osc` = ReaperLink (trigger_action). Le feedback (playing/pos/len/slug) est
    poussé par monitors._poll_backing."""

    def __init__(self, osc, on_change=None):
        self._osc = osc
        self._on_change = on_change or (lambda: None)
        self._fb = {"present": False, "playing": False, "paused": False,
                    "pos": 0.0, "len": 0.0, "slug": None}
        self._opt = None                # (playing_bool, expiry) — override optimiste
        self._songs = []                # chansons du preset courant [{slug,title,…}]
        self._mute = {}                 # la règle des stems du preset courant {famille: raison} (song-backing.md §3)
        self._slug = None               # chanson sélectionnée (runtime)
        self._press_t = {}              # switch -> horodatage du press
        self._last_release = {}         # switch -> horodatage du dernier release (double-tap)
        self._timers = {}               # switch -> Timer (long-press / pause différée)
        self._recall_timer = None
        self._practice_t0 = None        # horodatage du début de lecture (journal de pratique)
        self._practice_slug = None
        self._lock = threading.Lock()

    # ── feedback (.backing.json via monitors) ──
    def transport(self):
        """Le dernier état lu du transport : {present, playing, paused, pos, at, slug} — `at` = heure (epoch)
        à laquelle Reaper a publié `pos`. L'horloge de l'arrangement quand la backing joue (§5)."""
        with self._lock:
            return dict(self._fb)

    def set_feedback(self, fb):
        with self._lock:
            was_playing = bool(self._fb.get("playing"))
            prev_slug = self._fb.get("slug")
            self._fb = fb
            if fb.get("present") and fb.get("slug"):
                self._slug = fb["slug"]
        # journal de pratique : temps RÉEL de transport (horloge murale — les
        # boucles A/B comptent, les pauses non). Flush sur arrêt/pause ET sur
        # changement de chanson pendant la lecture.
        now_playing = bool(fb.get("playing"))
        slug_changed = prev_slug and fb.get("slug") != prev_slug
        if now_playing and (not was_playing or slug_changed):
            if slug_changed and self._practice_t0 is not None:
                self._flush_practice(prev_slug)
            self._practice_t0 = time.time()
            self._practice_slug = fb.get("slug")
        elif was_playing and not now_playing:
            self._flush_practice(prev_slug)

    def _flush_practice(self, slug):
        t0 = self._practice_t0
        self._practice_t0 = None
        if t0 is None or not slug:
            return
        played_ms = (time.time() - t0) * 1000
        if played_ms >= 3000:                      # < 3 s = faux départ, pas une session
            golemfm.post_practice(golemfm.golemfm_slug(slug) or slug, played_ms)   # golem.fm compte par slug

    def playing(self):
        with self._lock:
            if self._opt and time.time() < self._opt[1]:
                return self._opt[0]
            return bool(self._fb.get("playing"))

    def _set_opt(self, playing):
        with self._lock:
            self._opt = (playing, time.time() + OPTIMISTIC_S)
        self._on_change()

    def snapshot_extra(self):
        """Champs pilotés bridge-side, fusionnés dans state.backing par monitors."""
        with self._lock:
            return {"songs": list(self._songs), "slug": self._slug}

    # ── transport (partagé pied/écran) ──
    # Pendant une prise perf-rec, on ne touche JAMAIS au transport (cf. régression en tête de
    # fichier) : on coupe/rétablit juste le bus via golem_backing (op "mute"), le transport de
    # golem_perfrec continue de rouler intact et la prise n'est plus jamais tronquée.
    def play(self):
        if _perf_recording():
            write_command({"action": "backing", "op": "mute", "on": False})
        else:
            self._osc.trigger_action(ACT_PLAY)
        self._set_opt(True)

    def pause(self):
        if _perf_recording():
            write_command({"action": "backing", "op": "mute", "on": True})
        else:
            self._osc.trigger_action(ACT_PAUSE)
        self._set_opt(False)

    def stop(self):
        if _perf_recording():
            write_command({"action": "backing", "op": "mute", "on": True})
        else:
            self._osc.trigger_action(ACT_STOP)
            self._osc.trigger_action(ACT_GOTO_START)
        self._set_opt(False)

    def restart(self):
        if _perf_recording():
            # pas de seek pendant une prise (déplacerait la tête d'enregistrement) : on se
            # contente de démasquer le bus, la chanson continue depuis sa position courante.
            write_command({"action": "backing", "op": "mute", "on": False})
            self._set_opt(True)
            return
        self.seek(0.0)
        # un bus resté COUPÉ par une prise précédente (stop pendant une prise = B_MUTE, que rien ne rouvre) : une
        # backing qu'on relance hors prise doit s'entendre (2026-10-07)
        write_command({"action": "backing", "op": "mute", "on": False})
        if not self.playing():
            self._osc.trigger_action(ACT_PLAY)
            self._set_opt(True)

    def toggle(self):
        if self.playing():
            self.pause()
        else:
            self.play()

    def seek(self, pos):
        write_command({"action": "backing", "op": "seek", "pos": float(max(0.0, pos))})

    def loop(self, a, b):
        """Boucle A/B (travail d'un passage) : repeat NATIF Reaper sur [a, b] —
        échantillon-précis, zéro glitch au bouclage. a/b en secondes."""
        a, b = float(max(0.0, a)), float(max(0.0, b))
        if b <= a + 0.25:                       # boucle dégénérée : ignorée
            return
        write_command({"action": "backing", "op": "loop", "a": a, "b": b})

    def loop_off(self):
        """Lève la boucle A/B ET un saut armé (docs/live-pages.md §6.3 bis : rien d'armé ne survit à un stop)."""
        write_command({"action": "backing", "op": "loop", "off": 1})

    def jump(self, at, to):
        """Le saut de section de la page Répète (docs/live-pages.md §6.2), fait PAR REAPER à la position `at` :
        vers l'arrière ou sur place, boucle native [to, at] levée par le Lua au premier rebouclage (à l'échantillon) ;
        vers l'avant, seek du Lua quand le transport atteint `at` (gigue du defer, ~30 ms)."""
        write_command({"action": "backing", "op": "jump", "at": float(max(0.0, at)), "to": float(max(0.0, to))})

    def play_from_cursor(self):
        """Démarre là où le curseur a été POSÉ (seek fait avant le décompte, §6.1) — jamais de seek(0) ici : la
        commande de position et l'ordre de lecture n'empruntent pas le même chemin, partir de 0 puis sauter ferait
        entendre l'intro. Le démute est parti avec la position, avant le décompte : il ne reste que PLAY."""
        if not self.playing():
            self._osc.trigger_action(ACT_PLAY)
            self._set_opt(True)

    def mix(self, stem, mute=None, vol=None):
        cmd = {"action": "backing", "op": "mix", "stem": stem}
        if mute is not None:
            cmd["mute"] = 1 if mute else 0
        if vol is not None:
            cmd["vol"] = float(vol)
        write_command(cmd)
        # persiste dans meta.json (le mix appartient à la chanson, pas au preset)
        if self._slug:
            meta = golemfm.read_meta(self._slug) or {}
            m = meta.get("mix") or {}
            entry = dict(m.get(stem) or {})
            if mute is not None:
                entry["mute"] = 1 if mute else 0
            if vol is not None:
                entry["vol"] = float(vol)
            m[stem] = entry
            golemfm.save_mix(self._slug, m)

    def load(self, slug):
        """Charge les stems en cache de `slug` dans Reaper (mix depuis meta.json)."""
        if not golemfm.is_cached(slug):
            return {"ok": False, "error": f"{slug} not in cache — sync it first"}
        meta = golemfm.read_meta(slug) or {}
        with self._lock:
            self._slug = slug
        cmd = {"action": "backing", "op": "load", "slug": slug,
               "dir": golemfm.song_dir(slug),
               "mix": meta.get("mix") or dict(golemfm.DEFAULT_MIX)}
        # LE CLICK DU MORCEAU (docs/bars-format.md) : les vrais temps de la carte des mesures, posés en item MIDI sur
        # la piste Click par golem_backing.lua. Sans carte : rien (et l'item d'une chanson précédente est retiré).
        try:
            from . import bars as _bars
            tk = _bars.write_ticks(slug)
        except Exception:
            tk = None
        if tk:
            cmd["ticks"] = tk
        files = golemfm.local_files(slug)                # backing LOCAL : les stems sont des samples song
        if files is not None:
            cmd["files"] = files
            cmd["mix"] = meta.get("mix") or {}             # pas le DEFAULT_MIX golem.fm (guitare mutée)
        # le mix par FAMILLE (docs/separation.md §7) : « guitare coupée » coupe guitar-1, guitar-electric… — et la
        # RÈGLE du preset par-dessus (docs/song-backing.md §4) : coupé par la chanson OU par le preset ; jamais écrit
        # dans la chanson
        from . import backing_owner as _bo
        self._mute_applied = dict(getattr(self, "_mute", {}) or {})
        cmd["mix"] = _bo.apply(cmd["mix"], list(getattr(self, "_mute", {}) or {}),
                               list(files) if files is not None else golemfm.stems_of(slug))
        write_command(cmd)
        self._on_change()
        return {"ok": True}

    def played_mix(self, slug):
        """Le mix JOUÉ de `slug` : celui de la chanson, puis la règle du preset courant (song-backing.md §4)."""
        from . import backing_owner as _bo
        meta = golemfm.read_meta(slug) or {}
        files = golemfm.local_files(slug)
        base = (meta.get("mix") or {}) if files is not None or golemfm.is_song_key(slug) \
            else (meta.get("mix") or dict(golemfm.DEFAULT_MIX))
        return _bo.apply(base, list(self._mute or {}), list(files) if files is not None else golemfm.stems_of(slug))

    def remix(self):
        """Rejoue le mix de la chanson CHARGÉE (sans la recharger) : la règle du preset a changé dans le Designer."""
        slug = self._fb.get("slug") if self._fb.get("present") else self._slug
        if not slug:
            return
        for stem, m in (self.played_mix(slug) or {}).items():
            write_command({"action": "backing", "op": "mix", "stem": stem, "mute": 1 if m.get("mute") else 0})
        self._mute_applied = dict(self._mute or {})

    def load_files(self, slug, files, mix):
        """Charge des FICHIERS locaux dans les emplacements du backing (golem_backing « backing LOCAL ») —
        le click d'une prise armée (docs/compo.md §12) : `files={"drums": "/abs/x.wav"}`."""
        import os
        with self._lock:
            self._slug = slug
        first = next(iter(files.values()))
        write_command({"action": "backing", "op": "load", "slug": slug, "dir": os.path.dirname(first),
                       "files": files, "mix": mix})
        self._on_change()

    def unload(self):
        with self._lock:
            self._slug = None
            # Reaper n'a plus rien : on l'oublie AUSSI dans le retour. Sinon, backing coupé, le moniteur ne
            # nourrit plus `_fb` (monitors._poll_backing) et la garde « déjà chargée » d'on_recall croyait
            # encore à la chanson d'avant — la recharger ne faisait rien (karaoké, 2026-10-06 : arrêt puis
            # rechargement du même karaoké, « the stems did not load in Reaper »).
            self._fb = {**self._fb, "present": False, "slug": None, "playing": False}
        write_command({"action": "backing", "op": "unload"})
        self._on_change()

    # ── recall de preset : arme la liste + auto-load différé de songs[0] ──
    def adopt(self, songs, mute=None):
        """Démarrage du bridge sur un rig DÉJÀ monté : on arme la liste sans recharger les stems."""
        with self._lock:
            self._songs = songs
            self._mute = dict(mute or {})

    def on_recall(self, preset, allowed=True):
        """`allowed` = le VETO du mode (docs/modes.md) : un mode qui coupe le backing ne charge rien.
        Mesuré le 2026-09-21 en mode Pedalboard : il chargeait quand même les six stems, et À CHAQUE
        CHANGEMENT DE SCÈNE — la garde « déjà chargée » lit `_fb`, que le moniteur ne nourrit plus
        quand le backing est coupé (monitors.py), donc elle ne voyait jamais rien de chargé. Six
        items mp3 vidés et recréés sur le thread principal de Reaper 0,7 s après chaque scène."""
        songs = ((preset or {}).get("backing") or {}).get("songs") or [] if allowed else []
        with self._lock:
            self._songs = songs
            # la RÈGLE DES STEMS du preset (docs/song-backing.md §3) : posée sur le mix de la chanson au chargement
            self._mute = dict(((preset or {}).get("backing") or {}).get("mute") or {})
            if self._recall_timer:
                self._recall_timer.cancel()
                self._recall_timer = None
        if not songs:
            # preset sans backing, ou mode qui le coupe : décharge UNE fois (piste muette, plus de
            # chanson armée). `_slug` et pas seulement `_fb` : sous veto, `_fb` n'est plus nourri.
            if self._fb.get("present") or self._slug:
                self.unload()
            return
        slug = songs[0].get("slug")
        cur = self._fb.get("slug") if self._fb.get("present") else None
        if slug and slug == cur:
            # déjà chargée : on ne rejoue le mix QUE si la règle du preset a changé (Designer) — pas à chaque scène
            if self._mute != getattr(self, "_mute_applied", self._mute):
                self.remix()
            return
        if not slug or not golemfm.is_cached(slug):
            return                                    # pas en cache -> rien
        # SÉQUENCEMENT : jamais de load pendant le settle d'un rebuild (chargements async)
        t = threading.Timer(RECALL_SETTLE_S, lambda: self.load(slug))
        t.daemon = True
        with self._lock:
            self._recall_timer = t
        t.start()

    # ── API écran (POST /api/backing) ──
    def api_action(self, op, **kw):
        if op == "play":
            self.play()
        elif op == "pause":
            self.pause()
        elif op == "toggle":
            self.toggle()
        elif op == "stop":
            self.stop()
        elif op == "restart":
            self.restart()
        elif op == "seek":
            self.seek(kw.get("pos") or 0)
        elif op == "loop":
            if kw.get("off"):
                self.loop_off()
            else:
                self.loop(kw.get("a") or 0, kw.get("b") or 0)
        elif op == "select":
            slug = kw.get("slug")
            if not slug:
                return {"ok": False, "error": "slug required"}
            return self.load(slug)
        elif op == "unload":
            self.unload()
        elif op == "mix":
            stem = kw.get("stem")
            if stem not in golemfm.stems_of(self._slug):        # lot 1.6 : les stems de CETTE chanson
                return {"ok": False, "error": "unknown stem"}
            self.mix(stem, kw.get("mute"), kw.get("vol"))
        else:
            return {"ok": False, "error": "unknown op"}
        return {"ok": True}

    # ── moteur de gestes du pied (Notes on/off du switch du bloc backing) ──
    def on_edge(self, sw, on):
        now = time.time()
        if on:
            self._press_t[sw] = now
            self._cancel(sw)
            if not self.playing():                     # départ : timing musical -> PLAY au press
                self.play()
                self._press_t.pop(sw, None)            # press consommé (le release ne fait rien)
                # un hold après le départ vaut quand même stop+rewind (annulation du faux départ)
                self._arm(sw, LONG_S, lambda w=sw: self._long_fire(w, self.stop))
            else:                                      # en lecture : l'action attend le release
                self._arm(sw, LONG_S, lambda w=sw: self._long_fire(w, self.stop))
            return

        # release
        pressed_at = self._press_t.pop(sw, None)
        self._cancel(sw)                               # l'appui long n'a pas atteint son seuil
        last_rel = self._last_release.get(sw, 0)
        self._last_release[sw] = now
        if pressed_at is None:                         # press consommé (play au press / long)
            return
        if now - last_rel < DOUBLE_S:                  # double-tap -> restart (reste en lecture)
            self.restart()
        else:                                          # tap simple -> PAUSE, différée (fenêtre du double)
            self._arm(sw, DOUBLE_S, self.pause)

    def _long_fire(self, sw, action):
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


def backing_switch(preset):
    """Le switch (6-10) portant un bloc « backing-track » dans ce preset, sinon None.
    Même traversée que store._foot_summary (assignation libre block.foot, toutes chaînes)."""
    if not preset:
        return None
    from .store import _foot_blocks
    for b, _key in _foot_blocks(preset):
        if b.get("type") == "backing-track" and b.get("foot"):
            return int(b["foot"])
    return None
