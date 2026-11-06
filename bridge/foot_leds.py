# SPDX-License-Identifier: GPL-3.0-or-later
"""Les DIODES des stomps suivent le rack (docs/pedalboards.md § Diodes, 2026-10-08 : option A).

La diode d'un stomp `effect` de la UnO2 est une bascule LOCALE à la puce : elle change à l'appui, et jamais quand
le rack change de scène. Paper Kite, scène « Big Muff wall » : SW6, SW7, SW8 allumées (essais au pied) alors que
la scène n'allume que SW6 — et l'appui suivant sur SW7 envoyait « OFF » à un bloc déjà éteint (appui à vide).

Le remède : l'APPUI À DISTANCE de la puce (manuel UnO2 §4.3, firmware ≥ 1.3 — « ProgramChange 00-09 = click/release
footswitch 1-10 » sur le canal de télécommande). Après chaque changement de l'état des stomps, le rack compare la
diode qu'il CROIT allumée à l'état voulu, et appuie à distance sur les switches à corriger.

MESURÉ AU PIED le 2026-10-08 (PC 7 canal 16, deux fois) : la puce bascule SW8 et renvoie EXACTEMENT ce qu'un appui
du pied enverrait — `CC32 = 0 + Note 7`, puis `CC32 = 127 + Note 7`. Le rack, lui, l'a pris pour un coup de pied
(« stomp switch 8 OFF » puis « ON »). D'où les deux règles de ce module :
  · L'ÉCHO EST AVALÉ. Un switch « en attente » d'écho consomme son prochain CC et sa prochaine Note : sans ça, un
    switch à deux blocs (delay + reverb, l'un allumé dans la scène) recevrait « ON » et allumerait les deux.
  · L'ÉCHO DIT LA VÉRITÉ. Sa valeur est l'état réel de la diode : si on la croyait à tort (rack relancé, pédalier
    rallumé), elle est corrigée, et on réappuie UNE fois.

Ce que le rack croit d'une diode vient de chaque CC de stomp reçu (la valeur EST l'état de la diode : la puce alterne
127/0). Au démarrage on ne sait rien : une diode inconnue est appuyée quand même — l'écho étant avalé, l'appui ne
touche JAMAIS au son, et sa valeur dit l'état réel (déjà juste : le second appui la remet). Coût : un clignotement,
une fois, au premier alignement. Une première version n'éteignait jamais à l'aveugle — elle laissait allumées les
diodes du cas même qui a motivé ce module (rack rechargé, SW7/SW8 allumées au pied). Les stomps sont des objets GLOBAUX de la puce
(les mêmes `StompN` dans toutes les banks, tools/fcb/gen_uno2_syx.py) : une croyance par switch suffit.
"""
import logging
import threading
import time

log = logging.getLogger("golem.foot")

ECHO_WINDOW_S = 0.6        # un écho qui n'est pas revenu dans ce délai : le lien est muet, on ne croit plus rien
DEBOUNCE_S = 0.08          # plusieurs changements d'état en rafale (scène + paramètres) -> UN alignement

_LOCK = threading.Lock()
_LED = {}                  # sw -> True/False : ce qu'on croit de la diode (absent = inconnu)
_PENDING = {}              # sw -> {"until": t, "want": bool, "retry": bool, "cc": bool, "note": bool}
_TIMER = {"t": None}
_HOOK = {"desired": None, "press": None}


def configure(desired, press):
    """`desired()` -> {sw: bool} pour les switches qu'on a le droit d'aligner (app.py tranche : espèce `effect`, pas
    de geste, pas de service) ; `press(sw)` -> appui à distance, True si l'ordre est parti."""
    _HOOK["desired"], _HOOK["press"] = desired, press


def believed():
    with _LOCK:
        return dict(_LED)


def forget():
    """Le pédalier a pu changer d'état sans nous (rallumé, reflashé) : on ne croit plus rien."""
    with _LOCK:
        _LED.clear()
        _PENDING.clear()


# ── l'entrée : ce que la puce envoie ──────────────────────────────────────────────────────────

def on_stomp_cc(sw, on):
    """Un CC de stomp arrive (pied OU écho). Rend True si c'est l'ÉCHO d'un appui à distance — à avaler."""
    with _LOCK:
        _LED[sw] = bool(on)
        p = _PENDING.get(sw)
        if not p or p["cc"] or time.monotonic() > p["until"]:
            if p and time.monotonic() > p["until"]:
                _PENDING.pop(sw, None)
            return False
        p["cc"] = True
        p["redo"] = bool(on) != p["want"] and p["retry"]   # on croyait mal : l'écho a dit la vérité
        if p["redo"]:
            log.info("diode SW%d : l'écho dit %s, voulu %s -> second appui à distance"
                     % (sw, "ON" if on else "OFF", "ON" if p["want"] else "OFF"))
        done = p["note"]
        if done:
            _PENDING.pop(sw, None)
    if done:
        _settle(sw, p)
    return True


def _settle(sw, p):
    """L'écho est COMPLET (CC + Note) : seulement maintenant on peut réappuyer. Réappuyer dès le CC laissait la Note du
    premier écho en vol — prise pour celle du second, dont la Note fuyait alors vers le rack (trouvé au test)."""
    if p.get("redo"):
        _press(sw, p["want"], retry=False)


def on_stomp_note(sw):
    """La Note d'un stomp arrive. True si elle accompagne un appui à distance — à avaler aussi."""
    with _LOCK:
        p = _PENDING.get(sw)
        if not p or p["note"] or time.monotonic() > p["until"]:
            return False
        p["note"] = True
        done = p["cc"]
        if done:
            _PENDING.pop(sw, None)
    if done:
        _settle(sw, p)
    return True


# ── la sortie : aligner ───────────────────────────────────────────────────────────────────────

def _press(sw, want, retry):
    press = _HOOK["press"]
    if not press:
        return False
    with _LOCK:
        _PENDING[sw] = {"until": time.monotonic() + ECHO_WINDOW_S, "want": bool(want), "retry": retry,
                        "cc": False, "note": False, "redo": False}
    if not press(sw):
        with _LOCK:
            _PENDING.pop(sw, None)
        return False
    t = threading.Timer(ECHO_WINDOW_S + 0.05, _expire, args=(sw,))
    t.daemon = True
    t.start()
    return True


def _expire(sw):
    with _LOCK:
        p = _PENDING.get(sw)
        if not p or time.monotonic() <= p["until"]:
            return                                     # rien à expirer (ou un appui PLUS RÉCENT est en vol)
        _PENDING.pop(sw, None)
        if not p["cc"]:                                # aucun écho : le lien ne mène pas au pédalier
            _LED.pop(sw, None)
            log.info("diode SW%d : appui à distance sans écho — état de la diode inconnu" % sw)
            return
    if p["cc"] and not p["note"]:                      # le CC est venu, pas la Note : l'écho ne sera pas plus complet
        _settle(sw, p)


def align():
    """Appuie à distance sur chaque switch dont la diode (crue) diffère de l'état voulu. Rend les switches pressés."""
    fn = _HOOK["desired"]
    if not fn:
        return []
    try:
        want = fn() or {}
    except Exception as e:                             # un état de preset illisible ne doit pas tuer le pied
        log.warning("diodes : état voulu illisible (%s)" % e)
        return []
    todo = []
    with _LOCK:
        for sw, on in sorted(want.items()):
            if sw in _PENDING:
                continue                               # un appui est déjà en vol : son écho décidera
            cur = _LED.get(sw)
            if cur is None or cur != bool(on):         # inconnue : on appuie, l'écho dira la vérité
                todo.append((sw, bool(on)))
    for sw, on in todo:
        if _press(sw, on, retry=True):
            log.info("diode SW%d -> %s (appui à distance)" % (sw, "ON" if on else "OFF"))
    return [sw for sw, _ in todo]


def request_align():
    """Demande un alignement, regroupé : une scène qui change plusieurs choses d'un coup -> un seul passage."""
    with _LOCK:
        t = _TIMER["t"]
        if t:
            t.cancel()
        t = threading.Timer(DEBOUNCE_S, align)
        t.daemon = True
        _TIMER["t"] = t
    t.start()
