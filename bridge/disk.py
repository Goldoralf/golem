# SPDX-License-Identifier: GPL-3.0-or-later
"""Garde-fou de place disque pour l'enregistrement de performance (roadmap 0.a).

POURQUOI CE MODULE EXISTE
Une prise multipiste écrit du PCM 24 bits / 48 kHz : **1,04 Go par heure et par lane** (mesuré —
une prise de 62 min pèse 1,07 Go). Une répète de 3 h à 6 lanes fait 19 Go, et le rack n'a pas
toujours 19 Go. Sans garde-fou, l'écriture échoue **au milieu d'un morceau** : on perd la prise,
et on cherche le bug ailleurs pendant une soirée.

LES TROIS TEMPS, ET POURQUOI ILS SONT DIFFÉRENTS
1. **Avant** : on REFUSE de démarrer s'il n'y a pas de quoi tenir. C'est le seul moment où dire
   non ne coûte rien. Estimation prudente, faute de savoir combien de pistes Reaper armera.
2. **Pendant** : on MESURE la place libre qui décroît — plus besoin d'estimer, et l'autonomie
   affichée devient exacte. (Pas la taille des fichiers : ils ne sont pas là où on croit, cf. Watch.)
3. **Au plancher** : on ARRÊTE proprement plutôt que de laisser le disque se remplir. Une prise
   coupée et annoncée vaut mieux qu'un fichier tronqué qu'on découvrira au montage.

CE QUE CE MODULE NE FAIT PAS : effacer. Tant que la montée vers golem.fm n'existe pas, aucune
prise n'a de copie ailleurs — une purge automatique détruirait le seul exemplaire d'une bonne
prise. La reprise de place reste MANUELLE (la corbeille de l'onglet Recordings existe déjà). La
rétention automatique attendra d'avoir un signal « c'est en sécurité ailleurs » (jalon J2 de
docs/private/repete-vers-demo.md).
"""
import contextlib
import json
import os
import shutil
import time

from . import config as C

RECORDINGS = os.path.join(C.ROOT, "recordings")
CONF = os.path.join(C.CONFIG_DIR, "recordings.json")

# PCM 24 bits stéréo 48 kHz = 288 000 o/s par lane. C'est ce que Reaper écrit (vérifié à
# l'ffprobe sur une prise réelle : pcm_s24le, 48000 Hz, 2 canaux).
LANE_BPS = 48000 * 3 * 2

DEFAULTS = {
    "min_free_gb": 6.0,      # en dessous : on refuse de démarrer
    "min_minutes": 20.0,     # ou si l'autonomie estimée tombe sous ça
    "floor_minutes": 3.0,    # pendant la prise : arrêt propre sous ce seuil
    "warn_minutes": 15.0,    # l'écran le dit avant que ça devienne un problème
}


def conf():
    out = dict(DEFAULTS)
    with contextlib.suppress(Exception):
        d = json.load(open(CONF))
        if isinstance(d, dict):
            out.update({k: v for k, v in d.items() if k in DEFAULTS})
    return out


def _free_bytes():
    """Place libre du système de fichiers QUI PORTE recordings/ — pas celui de la racine du
    dépôt : les deux peuvent différer (montage dédié pour les prises)."""
    d = RECORDINGS if os.path.isdir(RECORDINGS) else C.ROOT
    with contextlib.suppress(Exception):
        return shutil.disk_usage(d).free
    return 0


def _takes_bytes():
    """Ce que les prises occupent déjà — pour dire à l'écran où est passée la place."""
    total = 0
    with contextlib.suppress(Exception):
        for root, _dirs, files in os.walk(RECORDINGS):
            for f in files:
                with contextlib.suppress(OSError):
                    total += os.path.getsize(os.path.join(root, f))
    return total


def _lanes_planned():
    """Combien de fichiers Reaper va écrire, d'après le bloc Rec (presets/.perfsrc.json, écrit
    par le bridge au recall). ESTIMATION PRUDENTE : on préfère refuser une prise qui serait
    passée que d'en couper une au milieu.

    mix         -> 1
    tracks      -> une piste par source cochée (+ le mix si « Song mix »)
    tracks_di   -> idem + une DI par entrée AUDIO (donc pas l'USB, qui est MIDI : son
                   équivalent de DI est un .mid, dont le poids est négligeable)
    """
    src = {}
    with contextlib.suppress(Exception):
        src = json.load(open(os.path.join(C.PRESETS_DIR, ".perfsrc.json"))) or {}
    mode = src.get("mode") or "mix"
    if mode == "mix":
        return 1
    import re as _re
    midi_ins = {f"in{n}" for n in (src.get("midi_inputs") or [3])}                             # lot 5 : les lanes MIDI ne sont pas de l'audio
    audio = sum(1 for k, v in src.items() if _re.fullmatch(r"in\d+", k) and v and k not in midi_ins)
    n = audio + (1 if src.get("usb") else 0)
    n = max(n, 1)
    if mode == "tracks_di":
        n += audio                                  # la DI d'une entrée audio, pas de l'USB
    if src.get("mix", True):
        n += 1                                      # coche « Song mix » : le stéréo en plus
    return n


def rate_bps(measured=None):
    """Octets par seconde. `measured` (consommation réelle du disque) gagne toujours sur
    l'estimation : pendant la prise, on ne devine plus."""
    if measured and measured > 0:
        return measured
    return _lanes_planned() * LANE_BPS


def status(measured=None):
    """Ce que l'écran affiche, et ce sur quoi les décisions se prennent."""
    free, rate = _free_bytes(), rate_bps(measured)
    c = conf()
    return {
        "free": free,
        "takes": _takes_bytes(),
        "rate": rate,
        "lanes": _lanes_planned(),
        "measured": bool(measured),
        # autonomie : ce qui reste MOINS la réserve, sinon on annonce une durée qui va jusqu'au
        # disque plein — c'est-à-dire jusqu'à l'endroit exact qu'on veut éviter.
        "seconds": max(0, int((free - c["min_free_gb"] * 1e9) / rate)) if rate else 0,
        "warn_minutes": c["warn_minutes"],
    }


def check_start():
    """(ok, motif). Appelée par TOUS les chemins de démarrage — l'API et le pied. Le motif est
    écrit pour être lu sur un écran de scène : il dit quoi faire, pas ce qui est cassé."""
    c = conf()
    st = status()
    gb = st["free"] / 1e9
    if st["free"] < c["min_free_gb"] * 1e9:
        return False, (f"disk full — {gb:.1f} GB free, {c['min_free_gb']:.0f} GB needed. "
                       "Delete takes in Recordings.")
    mins = st["seconds"] / 60
    if mins < c["min_minutes"]:
        return False, (f"only {mins:.0f} min of recording possible "
                       f"({gb:.1f} GB, {st['lanes']} tracks). Delete takes, or set the Rec "
                       "block to mix.")
    return True, ""


class Watch:
    """Suit la consommation RÉELLE pendant la prise en cours, et déclenche l'arrêt propre au
    plancher. Instancié une fois, réarmé à chaque démarrage.

    ⚠ ON MESURE LA PLACE LIBRE, PAS LES FICHIERS. Premier jet : additionner la taille du dossier
    de la prise. Il ne marche pas — **le dossier `recordings/perf-<ts>/` n'existe pas pendant
    l'enregistrement** (vérifié : absent pendant, présent après). Reaper écrit à plat dans son
    `RECORD_PATH` et c'est le Lua qui assemble le dossier à la finalisation ; le `file` publié
    dans `.perf.json` est donc une destination FUTURE, pas un chemin vivant. Le débit restait
    muet et l'autonomie affichée n'était jamais autre chose qu'une estimation.

    Mesurer la place libre est mieux que de réparer ce chemin : c'est indépendant de l'endroit
    où Reaper écrit, ça survivra à un changement de son côté, et c'est **exactement la grandeur
    qui décide** — peu importe qui consomme le disque, ce qui compte est ce qu'il en reste.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._t0 = self._f0 = None
        self._rate = None
        self.stopped_for_disk = False

    def tick(self, _rel=None):
        """Appelée à chaque poll pendant la prise. Renvoie un motif d'arrêt, ou None."""
        free = _free_bytes()
        t = time.monotonic()
        if self._t0 is None or free > (self._f0 or 0):
            # départ, ou la place a AUGMENTÉ (quelqu'un a vidé la corbeille pendant la prise) :
            # on repart de là plutôt que d'afficher un débit négatif.
            self._t0, self._f0 = t, free
            return None
        dt = t - self._t0
        if dt >= 8 and free < self._f0:              # 8 s : assez pour lisser les à-coups d'écriture
            # PLAFONNÉ à 3× ce que la prise peut écrire (2026-10-27, tools/check-use.py) : la place libre baisse aussi
            # quand AUTRE CHOSE écrit (une sauvegarde, une séparation, un téléchargement) — 1,6 Go écrits ailleurs en
            # 8 s faisaient « 0 min » avec 18 Go libres, et la prise s'arrêtait. Plafonner ne retarde pas l'arrêt utile :
            # l'autonomie se calcule sur la place RÉELLEMENT libre, qui reste la vraie mesure.
            self._rate = min((self._f0 - free) / dt, 3 * rate_bps())
        c = conf()
        st = status(self._rate)
        if st["seconds"] < c["floor_minutes"] * 60:
            self.stopped_for_disk = True
            return (f"recording stopped: only {free / 1e9:.1f} GB left "
                    f"({st['seconds'] // 60} min). The take is saved up to here.")
        return None

    @property
    def rate(self):
        return self._rate
