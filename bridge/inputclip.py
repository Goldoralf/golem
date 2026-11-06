# SPDX-License-Identifier: GPL-3.0-or-later
"""ÉCRÊTAGE D'ENTRÉE (2026-09-14). Mesuré sur une prise : la DI touchait 0 dBFS sur 21 000
échantillons (plateaux jusqu'à 63) — un gain de carte trop haut, que rien n'affichait ; la sortie,
elle, était propre (limiteur). Le vumètre OSC de Reaper est normalisé, 1,0 = 0 dBFS : trois lectures
consécutives collées au plafond sont un PLATEAU, pas une crête. Le remède est un bouton (le gain de
l'interface), pas du code : le rack le dit (puce /live, fiche Soundcard, chronologie)."""
import time

CLIP_LEVEL, CLIP_RUN, EPISODE_S = 0.995, 3, 3.0
_run = {}


def note_level(state, n, val, now=None):
    """Une lecture du vumètre de l'entrée `n`. Rend True quand un NOUVEL épisode d'écrêtage commence
    (l'appelant journalise), False sinon. `state.clip[in<n>] = {at, count}`."""
    now = time.time() if now is None else now
    key = f"in{n}"
    if val < CLIP_LEVEL:
        _run[key] = 0
        return False
    _run[key] = _run.get(key, 0) + 1
    if _run[key] < CLIP_RUN:
        return False
    _run[key] = 0                                  # un plateau compté, on repart
    prev = state.clip.get(key)
    fresh = prev is None or now - prev["at"] > EPISODE_S
    state.clip[key] = {"at": now, "count": (prev["count"] + 1 if prev else 1)}
    return fresh
