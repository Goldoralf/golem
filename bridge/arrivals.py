# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce qui ARRIVE sur le rack sans passer par son écran — dit à l'écran (2026-10-04).

Les jobs de golem.fm installent des packs, des presets, des patches pendant que l'app est
ouverte. Sans signal, les pages Library et Songs gardaient leur liste du montage : 168 packs
installés, rien à l'écran avant un rechargement complet (le mainteneur, premier rack Windows).

Deux compteurs dans l'état diffusé par /ws, que les pages mettent dans leurs dépendances :
  - `library_rev` : tones, kits, grooves, samples, synthés (ce que tu POSSÈDES) ;
  - `content_rev` : presets, patches, setlists, chansons (ce que tu JOUES).
Et une `notice` courte ({id, text, route}) que le shell affiche quelques secondes.

UNE rafale = UN signal : les jobs arrivent par dizaines (168 installs en 2 min), et chaque
diffusion fait recharger les listes ouvertes. On accumule, et on ne publie qu'après
_QUIET s sans nouveau job — le compte de la notice est celui de toute la rafale.
"""
import threading, time

_QUIET = 1.5

# action du job -> (domaine, singulier, pluriel, verbe). Seuls les jobs RÉUSSIS comptent.
_KINDS = {
    "install": ("library", "pack", "packs", "installed"),
    "t3k-install": ("library", "pack", "packs", "installed"),
    "remove": ("library", "pack", "packs", "removed"),
    "kit-install": ("library", "kit", "kits", "installed"),
    "groove-install": ("library", "groove", "grooves", "installed"),
    "groove-pack": ("library", "groove pack", "groove packs", "installed"),
    "sample-pack": ("library", "sample pack", "sample packs", "installed"),
    "preset-install": ("content", "preset", "presets", "installed"),
    "preset-delete": ("content", "preset", "presets", "removed"),
    "patch-install": ("content", "patch", "patches", "installed"),
    "patch-push": ("content", "patch", "patches", "installed"),
    "patch-delete": ("content", "patch", "patches", "removed"),
    "setlist-push": ("content", "setlist", "setlists", "updated"),
    "song-push": ("content", "song", "songs", "updated"),
}
# où mène le bouton de la notice : la Library pour l'inventaire, Songs pour le répertoire
_ROUTE = {"library": "library", "content": "songs"}

_lock = threading.Lock()
_pending = {}          # (domaine, singulier, pluriel, verbe) -> nombre
_timer = None
_seq = 0


def note(action):
    """Un job `action` vient de réussir. Sans effet pour une action qui ne change pas de liste."""
    global _timer
    kind = _KINDS.get(action)
    if not kind:
        return
    with _lock:
        _pending[kind] = _pending.get(kind, 0) + 1
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(_QUIET, _publish)
        _timer.daemon = True
        _timer.start()


def _text(batch):
    parts = [f"{n} {plural if n > 1 else one} {verb}" for (_d, one, plural, verb), n in batch.items()]
    return " · ".join(parts)


def _publish():
    global _timer, _seq
    with _lock:
        batch, _timer = dict(_pending), None
        _pending.clear()
    if not batch:
        return
    from .state import state
    domains = {k[0] for k in batch}
    if "library" in domains:
        state.library_rev += 1
    if "content" in domains:
        state.content_rev += 1
    # la notice mène là où il y a le plus à voir
    top = max(batch.items(), key=lambda kv: kv[1])[0][0]
    _seq += 1
    state.notice = {"id": f"{int(time.time())}-{_seq}", "text": _text(batch), "route": _ROUTE[top]}
    try:
        from .app import broadcast_threadsafe
        broadcast_threadsafe()
    except Exception:
        pass                                   # hors du bridge (outil, test) : l'état suffit
