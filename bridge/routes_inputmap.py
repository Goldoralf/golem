# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes de l'input map (branchement d'entrées/sorties par carte — docs/input-map.md).

GET  /api/inputmap  → input map enrichie de la carte active + catalogues d'icônes
POST /api/inputmap  → {kind:"input"|"output", ch, role} assigne un instrument/destination
POST /api/inputmap/pair → {kind, a, b, linked} maillon stéréo ⛓ (2 ports = 1 connecteur)
Chaque mutation re-pousse state.inputmap (WS) → les labels suivent partout (Designer…).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import inputmap as inputmap_mod
from .state import state
from .golog import get

log = get("inputmap")

router = APIRouter()


@router.get("/api/inputmap")
def get_inputmap(card: str = None):
    """Sans `card` : la carte active. Avec (« V276 », « hw:V276 ») : le patch de CETTE carte, même
    débranchée — semé depuis le registre si elle n'a jamais été patchée (2026-09-09)."""
    dev = inputmap_mod.device_of(card) if card else None
    # LA MÊME CARTE SOUS UN AUTRE NOM (2026-10-10) : le mode « studio » déclare `hw:V276`, nom Linux de la Volt ;
    # sous Windows elle joue en `asio:Universal Audio Volt`. Le Designer préparait les lanes d'un patch neuf pour
    # la carte Linux (guitare sur 1) alors que le moteur résout sur la carte branchée (guitare sur 2). Dite ici,
    # par la clé USB, l'appelant prend la carte branchée.
    live = inputmap_mod._card_device()
    if dev and dev != live:
        from . import cards
        if cards.same_card(dev, live):
            return {**inputmap_mod.current(), "same_as_live": True, "asked": dev,
                    "instruments": inputmap_mod.INSTRUMENTS, "out_roles": inputmap_mod.OUT_ROLES,
                    "midi_in_roles": inputmap_mod.MIDI_IN_ROLES, "midi_out_roles": inputmap_mod.MIDI_OUT_ROLES}
    return {**inputmap_mod.current(dev),
            "instruments": inputmap_mod.INSTRUMENTS,
            "out_roles": inputmap_mod.OUT_ROLES,
            "midi_in_roles": inputmap_mod.MIDI_IN_ROLES,
            "midi_out_roles": inputmap_mod.MIDI_OUT_ROLES}


_REEMIT = {"timer": None}


def _reemit_later():
    """Un rôle d'entrée a changé : la lane liée « Guitar 1 » doit changer de prise SUR LE RIG, pas seulement à
    l'écran (audit 2026-10-10 : la page disait IN 2 = guitare, la piste armait encore IN 1 jusqu'au rappel
    suivant). Rejoué 1 s après la dernière écriture, par le chemin normal du rappel."""
    import threading
    from . import recall

    def go():
        pid = getattr(state, "preset_id", None)
        if pid:
            try:
                recall.do_recall(pid, getattr(state, "scene_id", None) or "A")
            except Exception as e:
                log.warning(f"rig non rejoué après la carte d'entrées : {e}")
    if not getattr(state, "reaper_running", False) or not getattr(state, "preset_id", None):
        return                                             # moteur éteint ou rien ne joue : rien à rejouer (et pas sous pytest)
    t = _REEMIT.get("timer")
    if t:
        t.cancel()
    _REEMIT["timer"] = threading.Timer(1.0, go)
    _REEMIT["timer"].daemon = True
    _REEMIT["timer"].start()


def _refresh(reemit=False):
    state.inputmap = inputmap_mod.current()
    state.touch()
    if reemit:
        _reemit_later()


@router.post("/api/inputmap")
async def set_inputmap(body: dict):
    kind = (body or {}).get("kind") or "input"
    dev = inputmap_mod.device_of((body or {}).get("card")) if (body or {}).get("card") else None
    # le NUMÉRO d'une entrée dans son rôle (« Guitar 2 ») : body {kind:'input', ch, nth} SANS role
    if kind == "input" and "nth" in (body or {}) and "role" not in (body or {}):
        try:
            p = inputmap_mod.set_nth((body or {}).get("ch"), (body or {}).get("nth"), dev)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        _refresh(reemit=True)
        return {"ok": True, "inputmap": p}
    # un RETOUR (docs/returns.md) : body {kind:'output', ch, person?, type?} SANS role
    if kind == "output" and "role" not in (body or {}) and ("person" in (body or {}) or "type" in (body or {})):
        try:
            p = inputmap_mod.set_out_person((body or {}).get("ch"), (body or {}).get("person"),
                                            (body or {}).get("type", ...), dev)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        _refresh(reemit=True)
        return {"ok": True, "inputmap": p}
    # attribution de PERSONNE (Lot 5) : body {kind:'input', ch, person} SANS role
    if kind == "input" and "person" in (body or {}) and "role" not in (body or {}):
        p = inputmap_mod.set_person((body or {}).get("ch"), (body or {}).get("person"), dev)
        _refresh(reemit=True)
        return {"ok": True, "inputmap": p}
    try:
        p = inputmap_mod.set_role(kind, (body or {}).get("ch"), (body or {}).get("role"), dev)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if kind == "midi_out":
        # arme/ferme la ligne Whammy tout de suite — la LED MIDI OUT suit le rôle
        from . import midi_out
        midi_out.warm()
    _refresh(reemit=True)
    return {"ok": True, "inputmap": p}


@router.post("/api/inputmap/pair")
async def set_pair(body: dict):
    b = body or {}
    try:
        p = inputmap_mod.set_pair(b.get("kind") or "input", b.get("a"), b.get("b"), bool(b.get("linked")))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _refresh()
    return {"ok": True, "inputmap": p}
