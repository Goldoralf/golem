# SPDX-License-Identifier: GPL-3.0-or-later
"""Le REGISTRE des commandes que le bridge envoie au moteur audio (docs/ardour-plan.md §7d, lot 4).

Le Golem Engine est resté trois jours sans que personne n'y touche pendant que le bridge gagnait des commandes côté
REAPER : rien ne le disait, l'adaptateur les écartait avec une ligne de journal. Ce registre classe CHAQUE commande ;
tests/test_engine_actions.py échoue dès qu'une commande apparaît dans le bridge sans y être, ou qu'un classement ne
correspond plus à ce que l'adaptateur accepte.

Pour le Golem Engine, une commande est :
  - True        : traitée par son veilleur (elle est dans `ArdourEngine.actions`) ;
  - "<feature>" : pas encore — elle appartient à cette fonction de config/engines/features.json, que le descripteur
                  du moteur ne déclare pas « yes » ; le jour où la fonction passe à « yes », la commande doit suivre ;
  - None        : sans objet sur ce moteur, avec la raison (`why`) — une sonde de REAPER, un outil de développement.
REAPER traite tout : son vocabulaire est le sien (`EngineAdapter.actions = None`).
"""

# le mot « action » sert aussi ailleurs : réponses d'API, noms de réparations de Health ▸ Fix — pas des commandes
NOT_COMMANDS = frozenset({"created", "kept_local", "same", "refused",                 # songs.py : ce qu'un import a fait
                          "repose_preset", "osc_refresh", "reaper_restart", "set_buffer",
                          "display_animations"})   # fixes.py : réparations

REAPER_PROBE = "a REAPER probe or dev tool; nothing reads it on this engine"

COMMANDS = {
    # le rig
    "rig_recall": {"ardour": True}, "scene_apply": {"ardour": True}, "stomp": {"ardour": True},
    "rig_verify": {"ardour": True}, "dump": {"ardour": True}, "snapshot": {"ardour": True},
    "ping": {"ardour": True}, "status": {"ardour": True},
    # /system : audio, inventaire, bancs, santé, mixer
    "audio_set": {"ardour": True}, "plugins": {"ardour": True}, "gapmeter": {"ardour": True},
    "dspstats": {"ardour": True}, "mixer_apply": {"ardour": True}, "peaks": {"ardour": True},
    "audio_reset": {"ardour": True}, "midi_reinit": {"ardour": True}, "midi_send": {"ardour": True},
    "perf_rec": {"ardour": True},              # la prise (lot 3) : mix, lanes, DI, MIDI des claviers
    "click": {"ardour": True},                 # le métronome (lot 3) : libre, accents, horloge muette ; pas le click joué
    "drums": {"ardour": True},                 # la boîte à rythmes (lot 3) : kits AVL, SFZ et samples ; pas DrumGizmo
    "standard": {"ardour": True},              # les standards (lot 3) : grille, quatre parties, click joué, départ armé
    "tuner": {"ardour": True}, "extstate": {"ardour": True},   # l'accordeur (lot 3) et son entrée
    "backing": {"ardour": True},               # la backing (lot 3) : stems, mix, seek, boucle, saut ; pas le click du morceau
    "preview": {"ardour": True},               # l'écoute sans jouer (lot 3) : DI et phrase MIDI ; les autres rendus disent non
    "sample": {"ardour": True}, "sample_preview": {"ardour": True},   # les samples (lot 3) et leur écoute dans la Library
    # le VST Host (lot 3) : inventaire VST3, paramètres d'une instance ; l'état natif répond « pas ici »
    "vst_list": {"ardour": True}, "vst_params": {"ardour": True}, "vst_state": {"ardour": True},
    # les services (lot 3, docs/ardour-plan.md §7d) : chacun attend sa fonction
    "drumlearn": {"ardour": None, "why": "learning an e-drum module's notes (Calibration) is not on this engine yet"},
    # pas encore, sans fonction déclarée dans features.json : dits ici
    "capture_params": {"ardour": True},        # les potards d'une capture pilotable (lecteur LV2 golem Capture)
    "plugin_trial": {"ardour": None, "why": "written by bridge/plugin_trial.py to its own separate trial engine, never to the one that plays"},
    "vst_open": {"ardour": None, "why": "the Golem Engine has no plugin window (headless)"},
    "plugin_window": {"ardour": None, "why": "plugin windows are not on this engine yet"},
    "meters": {"ardour": None, "why": "the per-block meter (dev route) is not on this engine yet"},
    # sondes et outils de REAPER
    "chunkdump": {"ardour": None, "why": REAPER_PROBE}, "dumpfx": {"ardour": None, "why": REAPER_PROBE},
    "fxinventory": {"ardour": None, "why": "REAPER's plugin inventory; this engine answers `plugins`"},
    "fxprobe": {"ardour": None, "why": REAPER_PROBE}, "lcbench": {"ardour": None, "why": REAPER_PROBE},
    "loadtest": {"ardour": None, "why": REAPER_PROBE}, "namtest": {"ardour": None, "why": REAPER_PROBE},
    "projreload": {"ardour": None, "why": REAPER_PROBE},
    "reload": {"ardour": None, "why": "hot reload of a REAPER script"},
}


def status(action, engine_id="ardour"):
    """True | nom de fonction | None, pour ce moteur. KeyError si la commande n'est pas classée."""
    return COMMANDS[action][engine_id]
