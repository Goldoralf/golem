# SPDX-License-Identifier: GPL-3.0-or-later
"""L'AFFICHAGE : les animations de l'écran (Settings ▸ System ▸ Display, décision du 2026-11-25).

Une case animée du Live fait redessiner l'écran sans arrêt : sur la machine qui joue le son, c'est du temps volé à
l'audio (docs/pitfalls/ui.md « An endless animation steals the audio thread » — 134 % d'un cœur pour le GPU de Chrome
avec les 14 cases de Jazz Box, 137 décrochages ALSA par minute sur le rack Linux à 2 cœurs). Sur une machine puissante,
elles ne coûtent rien d'audible (le rack Linux de dev, 2026-11-25) : le choix revient au musicien.

    animations : "auto" (défaut) — figées sur l'écran LOCAL (l'app servie par 127.0.0.1/localhost), animées sur une
                 tablette ou un téléphone, qui dessinent avec leur propre processeur ;
                 "on" — animées partout ; "off" — figées partout.
    blinks     : les voyants d'état clignotent (au pas : deux images par seconde, app/anim-stepper.mjs) ; faux = fixes.

Fichier : config/display.json (état local, .gitignore). Le choix part dans l'état diffusé (`display`) : chaque écran
l'applique sans recharger. Health le propose quand le son claque avec les animations actives (bridge/fixes.py)."""
import json
import os

from . import config as C

MODES = ("auto", "on", "off")
DEFAULTS = {"animations": "auto", "blinks": True}
PATH = lambda: os.path.join(C.CONFIG_DIR, "display.json")   # noqa: E731 — le dossier de config du MOMENT

_BRIEF = {"key": None, "value": None}


def get():
    try:
        with open(PATH(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    out = dict(DEFAULTS)
    if isinstance(d, dict):
        if d.get("animations") in MODES:
            out["animations"] = d["animations"]
        if isinstance(d.get("blinks"), bool):
            out["blinks"] = d["blinks"]
    return out


def set_(animations=None, blinks=None):
    """Change le réglage ; rend le réglage complet. ValueError si une valeur est hors liste."""
    cur = get()
    if animations is not None:
        if animations not in MODES:
            raise ValueError(f"animations must be one of {list(MODES)}")
        cur["animations"] = animations
    if blinks is not None:
        if not isinstance(blinks, bool):
            raise ValueError("blinks must be true or false")
        cur["blinks"] = blinks
    from .store import _write_json_atomic
    os.makedirs(os.path.dirname(PATH()), exist_ok=True)
    _write_json_atomic(PATH(), cur)
    return cur


def brief():
    """Pour `state.snapshot()` (jusqu'à 20 Hz) : un `stat`, et le fichier n'est relu que s'il a changé."""
    try:
        st = os.stat(PATH())
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if _BRIEF["key"] != key or _BRIEF["value"] is None:
        _BRIEF.update(key=key, value=get())
    return _BRIEF["value"]


def tiles_move_on_audio_machine():
    """Les cases bougent-elles sur l'écran de la machine qui joue le son ? (« on » seulement : « auto » les fige là)"""
    return get()["animations"] == "on"
