# SPDX-License-Identifier: GPL-3.0-or-later
"""État live du RIG, partagé entre l'API, le WebSocket et le lien OSC.

Modèle (cf. conception §6bis) : un PRESET (rig) contient des SCENES A–H.
L'état courant = quel preset chargé + quelle scène active + niveaux + voix.
"""
import time


def _foot_heard():
    """Import local : state est importé par foot indirectement, on ne veut pas de cycle."""
    try:
        from . import foot
        return foot.last_heard()
    except Exception:
        return None


class RigState:
    def __init__(self):
        self.reaper_connected = False   # lien OSC actif (trafic reçu)
        self.reaper_running = False     # process Reaper détecté (allumé)
        self.reaper_gen = 0             # génération : +1 à chaque down/up de Reaper (invalide les caches de forme)
        self.preset_id = None        # preset (rig) courant
        self.preset_name = None
        self.scene_id = None         # scène active (A–H)
        self.voice_on = False
        self.whammy_on = False       # Whammy DT active (toggle stomp) — piloté par le bridge
        self.whammy_mode = None       # mode/intervalle Whammy armé par la scène (ex. "+12", "oct up")
        # 2e MOTEUR de la DT (Drop/Raise Tune), indépendant et combinable avec le premier. Mémorisé
        # parce que la pédale est un ÉTAT MATÉRIEL qu'on ne peut pas relire : sans le nom du mode
        # engagé, on ne sait plus quel PC de bypass envoyer pour l'éteindre (bug 2026-07-26).
        self.whammy_drop = None
        # pédales MIDI GÉNÉRIQUES (bloc midi-pedal, chantier ① audit 2026-08-12) : id du
        # descripteur -> {on, setting}. Même raison d'exister que whammy_mode : l'état est
        # MATÉRIEL et illisible, le nom du réglage engagé est ce qui permet de l'éteindre.
        # Les whammy_* historiques restent — la Whammy garde son chemin nominatif.
        self.midi_pedals = {}
        self.levels = {"guitar": 0.0, "voice": 0.0}   # 0..1 (meter/fader)
        # ÉCRÊTAGE d'entrée (2026-09-14) : {in1: {"at": epoch, "count": n}} — posé quand le vumètre d'une
        # piste d'entrée reste collé au plafond (≥ 0,995) sur 3 lectures. Mesuré sur une prise : la DI
        # touchait 0 dBFS sur 21 000 échantillons, plateaux de 63 — un gain de carte trop haut, que
        # rien n'affichait. La sortie, elle, était propre (limiteur). Le remède est un bouton, pas du code.
        self.clip = {}
        self.tempo = 120
        self.stomps = {}             # état on/off des stomps de la rangée haute (Live) : {type: bool}
        self.exp1 = 0               # pédale physique EXP 1 (ExpA, CC7) 0..127
        self.exp2 = 0               # pédale physique EXP 2 (ExpB, CC11) 0..127
        # derniere position de treadle ENVOYEE a la pedale : un CC identique ne se renvoie pas
        self.whammy_pedal = None
        self.exp2_target = "Whammy"   # cible du RÔLE bloc du rig émis (wah, mix…, sinon Whammy) — affichage Live
        # rôles -> pédale physique (config/pedals.json, exclusifs) : qui fait le volume, qui fait le bloc
        self.pedals = {"volume": "exp1", "block": "exp2"}
        # verrou live : armé depuis la page Live -> le Designer est gelé (une retouche ré-auditionnerait
        # le brouillon et remplacerait le son de scène en plein set). Partagé entre tous les écrans.
        self.live_lock = False
        self.latency_ms = None       # latence audio round-trip (ms) lue des hw_params ALSA — None si Reaper pas sur la carte
        self.audio_metrics = {}      # source, fréquence et buffer réellement ouverts (desktop)
        self.xruns = 0               # dropouts (xrun/overrun USB) loggués par le noyau depuis le démarrage du bridge
        # ce que l'ÉCRAN montre : les dropouts RÉCENTS (monitors.XRUN_RECENT_S), pas le cumul. Un
        # seul xrun laissait la tuile rouge jusqu'au redémarrage du bridge — même après avoir monté
        # le buffer, donc impossible de voir si le remède avait marché. Le cumul reste au diag.
        self.xruns_recent = 0
        self.xruns_last = None       # horodatage (epoch) du dernier dropout vu, None = aucun
        # « le thread audio avance-t-il ? » {ok, why}. Vide tant qu'on ne sait pas — on n'alarme
        # jamais sur une ignorance. Ni Audio_IsRunning() ni GetAudioDeviceInfo ne répondent
        # honnêtement : tous deux disaient « tout va bien » pendant 13 h de silence total
        # (carte ré-énumérée, 2026-08-08). Le seul fait honnête est un compteur qui n'avance plus.
        self.audio = {}
        # contrat MIDI (sentinelle golem_midi.lua) : {ok, issues[], fix}. Le rack portait ce
        # diagnostic sans jamais le montrer — une lane Keys morte se cherchait à la main.
        self.midi = {}
        # fichiers du rig : {t, ok, checked, issues[{track, fx, kind, expected, repaired}]} — golem_rig
        # relit EN CLAIR, 2 s après chaque recall, le modèle/IR que chaque plugin a réellement chargé
        # (un NAM ré-instancié vide sonnait comme un boost sec, 2026-09-07). Vide tant qu'on ne sait pas.
        self.rig_check = {}
        self.rig_unmounted = []          # lanes que la carte branchée ne peut pas prendre (scene_bake) — puce ⚠ LANES
        self.rig_error = None            # dernier recall REFUSÉ (compile, preset inconnu) — puce ⚠ RIG ; None = rien à dire
        # la LIGNE de setlist d'où vient le preset courant : {line, preset, title, slug, bpm} — None hors
        # ligne (rappel direct). C'est ce que Live affiche et ce que la découpe recopie (setlists.md §9).
        self.song = None
        # boost CPU (gouverneur `performance`) : suit le mode (Gig/Show) — montré d'un ⚡ sur Live, à côté
        # de la latence, parce qu'en Gig le dashboard n'est pas atteignable (2026-09-08)
        self.cpu_boost = None
        # pédalier : {id, source, stale}. Un « stale » veut dire « mesuré, mais la dernière
        # sonde n'a pas confirmé » — on continue de s'en servir, on ne le cache pas.
        self.pedalboard = {}
        # accordeur : on = armé (JSFX actif) ; active = note fiable détectée (sinon "listening…")
        self.tuner = {"on": False, "active": False, "note": None, "octave": None, "midi": None,
                      "cents": 0.0, "freq": 0.0, "conf": 0.0}
        # looper : enabled = preset courant a un looper ; present = piste+FX vivants dans Reaper ;
        # loops = la TABLE du preset [{sw, src, label}] (docs/looper.md §1, l'ordre fait le slot) ;
        # slots = son état vivant, une entrée par ligne {state: empty|rec|dub|play|stop, has, sw,
        # src, label} ; len/pos = loop maîtresse (s). Au plus 4 lignes — limite du PIED (6/7/8/9),
        # pas du moteur : le JSFX monte à 24 paires.
        self.looper = {"enabled": False, "present": False, "loops": [], "slots": [],
                       "len": 0.0, "pos": 0.0, "t": 0.0}
        # backing tracks (stems golem.fm via Reaper) : enabled = le preset lie des chansons ;
        # songs = liste du preset ; slug = chargée ; present/playing/pos/len = retour .backing.json ;
        # stems = mix par stem {mute,vol} ; t = horodatage du frame (extrapolation client).
        self.backing = {"enabled": False, "songs": [], "slug": None, "present": False,
                        "playing": False, "paused": False, "pos": 0.0, "len": 0.0,
                        "stems": {}, "loop": {"on": False, "a": 0.0, "b": 0.0}, "t": 0.0}
        # mode machine (docs/modes.md) : {id,name,icon,services,ui} — posé par app.py
        # au démarrage (modes.current()) et par POST /api/mode. Veto de services + surface UI.
        self.mode = {}
        # un document est ARRIVÉ dans l'edit-buffer sans passer par le Designer (job patch-try de
        # golem.fm) : le Designer ouvert voit le compteur bouger et propose d'ouvrir (patches.md §17)
        self.sandbox_rev = 0
        self.sandbox_from = None
        # ce que les jobs de golem.fm ont installé pendant que l'app est ouverte (bridge/arrivals.py) :
        # les pages Library/Songs rechargent leur liste quand le compteur bouge, le shell montre la notice
        self.library_rev = 0
        self.content_rev = 0
        self.notice = None
        # chef d'orchestre : où en est le morceau (docs/arrangement.md §8) — posé par
        # ArrangementCtl, lu par le pupitre et la page Live.
        self.arrangement = {}
        # switch qui porte le bloc arrangement (posé au recall) — le chemin CC lui cède,
        # comme au sample et à la boîte à rythmes : sinon tap = double déclenchement.
        self.arr_switch = None
        # input map de la carte ACTIVE (docs/input-map.md) : labels/icônes
        # par port — consommé par le Designer (onglets), Soundcard v2, Live.
        self.inputmap = {}
        # Décalage d'affichage des banks, posé par le descripteur du pédalier actif (0 ou 1).
        # 0 par défaut : sans pédalier connu, on affiche le slot brut plutôt qu'un numéro inventé.
        self.bank_base = 0
        # claims de la rangée scènes (doctrine foot_scene_claim) : {sw 1-5: [{id,type}]}
        # — la tuile Live du slot devient la tuile du service, le FCB route vers lui.
        self.scene_claims = {}
        self.lane_toggles = {}
        self.rig_loading = None          # {preset, since, by} pendant qu'un morceau se charge (lot F : « Start » attend)
        self.loaded_by = None            # qui a chargé le morceau courant
        self.rec_with_song = False       # la prise en cours suit le morceau (répète, « Record with the song »)
        self.rec_with_song_asked = False
        self.devices_online = []         # appareils appairés connectés au WS : [{id, name, person_name, kind}]       # bascules de blocs depuis un Companion : {block_id: {on, preset, scene}} (lane_stomps.py)
        self.sample_switches = {}    # switch -> {block, samples} des lanceurs de samples (posé au recall)
        self.samples = {}            # block_id -> {playing, idx} (état des one-shots, retour golem_sample)
        self.drum_switches = {}      # switch -> {block, patterns, fills, kit} des boîtes à rythmes
        self.standard_switches = {}  # switch -> {block, params} des blocs `standard` au pied
        self.standard = {}           # {playing} du lecteur de grilles (retour golem_chordseq)
        self.standard_meta = {}      # {slug: {title, composer}} des standards CITÉS par le preset :
                                     # /live nomme la chanson sur la tuile, le slug seul ne suffit pas
        self.standard_block = None   # params du bloc `standard` du preset, switch ou pas —
                                     # c'est LUI qui décide si /live propose la vue Chart
        self.drums = {}              # block_id -> {playing, idx} (état des grooves, retour golem_drums)
        # perf rec (magnétophone) : miroir de presets/.perf.json (golem_perfrec) -> badge REC sur Live
        self.perf = {"recording": False, "file": "", "started_at": ""}
        # dernier refus/arrêt lié à la place disque (roadmap 0.a). Il vit dans l'état parce que
        # le chemin le plus courant est le PIED : il n'y a pas de réponse HTTP à lire, l'écran
        # est le seul endroit où l'on peut apprendre pourquoi rien ne s'est passé.
        self.perf_error = ""
        self.perf_countin = None     # décompte avant une prise : {until (epoch), seconds} ou None
        self.disk = {}
        # transcription (docs/archive/tablature-study.md §12) : {available, current, queue, last}.
        # Un travail muet qui prend trente secondes est indiscernable d'un bouton cassé.
        self.transcribe = {}
        # mode SÉLECTION du pied (appui long switch 1 -> 2 chiffres) : {digits, timeout_s, switch}
        # ou None. Publié parce qu'invisible, il avalait les appuis de scène (2026-09-21).
        self.foot_select = None
        self.click = {"on": False, "present": False}   # métronome (piste Click, chantier 2026-07-25)
        # bloc COMPO (docs/compo.md) : cibles « Follow Golem » par personne (en mémoire, §10) + le
        # dernier tap (compte rendu : qui, quelles lanes, refus éventuel) — /live et le Companion lisent ici.
        self.compo = {"targets": {}, "last": None}
        self.cards = {"active": "", "candidates": []}  # cartes son : active + candidates au switch (gear-registry)
        # veille hotplug unifiée (audit 2026-08-12 §3, chantier ⑤) : appareils MIDI USB
        # présents et IDENTIFIÉS (profil calibré / pédalier USB / inconnu) + événements
        # récents. Posé par monitors._poll_hotplug, consommé par la bannière Soundcard.
        self.hotplug = {"devices": [], "events": []}
        self.updated = time.time()

    def touch(self):
        self.updated = time.time()

    def set_reaper(self, connected: bool):
        if self.reaper_connected != connected:
            self.reaper_connected = connected
            self.touch()

    def snapshot(self) -> dict:
        from . import boot_progress              # l'écran de chargement : des faits datés (mockups/loading.html)
        boot_progress.observe(self)
        from . import startup_home
        from . import health                     # le point de santé de la barre du haut (docs/health.md §3) — O(1)
        from . import first_check                # la vérification de première installation : à faire ? (§2)
        return {
            "boot": boot_progress.doc(),
            "health": health.brief(),
            "first_check": first_check.brief(),
            "startup": startup_home.describe(),      # l'accueil (chip ⌂ de /live, menus ⋯)
            "reaper_connected": self.reaper_connected,
            "reaper_running": self.reaper_running,
            "preset_id": self.preset_id,
            "preset_name": self.preset_name,
            "scene_id": self.scene_id,
            "voice_on": self.voice_on,
            "whammy_on": self.whammy_on,
            "whammy_mode": self.whammy_mode,
            "midi_pedals": self.midi_pedals,
            "levels": self.levels,
            # âge en secondes du dernier écrêtage par entrée (l'écran ne compare jamais deux horloges)
            "clip": {k: {"age": round(time.time() - v["at"], 1), "count": v["count"]} for k, v in self.clip.items()},
            "tempo": self.tempo,
            "stomps": self.stomps,
            "exp1": self.exp1,
            "exp2": self.exp2,
            "exp2_target": self.exp2_target,
            "pedals": self.pedals,
            "live_lock": self.live_lock,
            "latency_ms": self.latency_ms,
            "audio_metrics": self.audio_metrics,
            "xruns": self.xruns,
            "xruns_recent": self.xruns_recent,
            "xruns_last": self.xruns_last,
            "audio": self.audio,
            "midi": self.midi,
            "rig_check": self.rig_check,
            "rig_unmounted": self.rig_unmounted,
            "rig_error": self.rig_error,
            "song": self.song,
            "cpu_boost": self.cpu_boost,
            "pedalboard": self.pedalboard,
            "tuner": self.tuner,
            "looper": self.looper,
            "backing": self.backing,
            "mode": self.mode,
            "sandbox_rev": self.sandbox_rev,
            "sandbox_from": self.sandbox_from,
            "library_rev": self.library_rev,
            "content_rev": self.content_rev,
            "notice": self.notice,
            "arrangement": self.arrangement,
            "inputmap": self.inputmap,
            # Décalage d'affichage des banks — l'écran du rack doit montrer CE QUE MONTRE LE
            # PÉDALIER. La UnO2 numérote depuis 1 (slot 3 = « 04 »), la 1.0.4 depuis 0. Un écart
            # d'une unité entre les deux afficheurs se paie sur scène, en hésitation.
            # Le CONTRAT ne bouge pas : sur le fil, PC = slot, toujours 0-18.
            "bank_base": self.bank_base,
            # Quand le rack a ENTENDU le pied pour la dernière fois. Ce n'est PAS « quelle puce
            # est branchée » : une puce peut s'identifier parfaitement sans qu'un seul appui
            # n'arrive (câble de jeu débranché, MIDI IN coupé). C'est cette panne-là qu'on
            # rencontre en répète, et rien ne la montrait.
            "foot_heard": _foot_heard(),
            "scene_claims": self.scene_claims,
            "lane_toggles": self.lane_toggles,
            "rig_loading": self.rig_loading, "loaded_by": self.loaded_by,
            "rec_with_song": self.rec_with_song, "devices_online": self.devices_online,
            "sample_switches": self.sample_switches,
            "samples": self.samples,
            "drum_switches": self.drum_switches,
            "standard_switches": self.standard_switches,
            "standard_block": self.standard_block,
            "standard_meta": self.standard_meta,
            "standard": self.standard,
            "drums": self.drums,
            "perf": self.perf,
            "perf_error": self.perf_error,
            "perf_countin": self.perf_countin,
            "disk": self.disk,
            "transcribe": self.transcribe,
            "foot_select": self.foot_select,
            "click": self.click,
            "compo": self.compo,
            "cards": self.cards,
            "hotplug": self.hotplug,
            "updated": self.updated,
            # cet ordinateur (docs/installer.md §4) : `profile` desktop|server suit la fenêtre ; `ui.can_show`
            **_machine_state(),
        }


def _machine_state():
    try:
        from . import machine
        return machine.ui_state()
    except Exception:
        return {}


# Singleton d'état partagé du bridge (importé par app + routes + monitors).
state = RigState()
