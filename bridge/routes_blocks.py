# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes de l'ÉTAT DES BLOCS (docs/block-status.md §5) : ce qui manque se voit, se télécharge ou se
remplace. Le Designer demande l'état du document qu'il édite (POST, le preset en corps : il n'est pas
encore écrit) ; le reste du rack demande par id (GET)."""
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import blockstatus as BS
from . import commands

router = APIRouter()
log = logging.getLogger("golem.blocks")


def _preset_of(pid=None, doc=None):
    from . import recall
    from .store import _read_json, load_preset
    if isinstance(doc, dict):
        return doc
    if pid:
        return load_preset(str(pid))
    sb = _read_json(recall.SANDBOX_BUF, {}) or {}
    return sb.get("preset") if isinstance(sb.get("preset"), dict) else None


@router.get("/api/blocks/status")
def blocks_status(preset: str = ""):
    p = _preset_of(preset or None)
    if p is None:
        return JSONResponse({"error": f"unknown preset '{preset}'" if preset else "no preset loaded"}, 404)
    return BS.preset_status(p)


@router.post("/api/blocks/status")
def blocks_status_doc(body: dict):
    p = _preset_of(body.get("id"), body.get("preset"))
    if p is None:
        return JSONResponse({"error": "no preset"}, 404)
    return BS.preset_status(p)


def _replay(pid):
    """Le téléchargement a fini : si ce preset joue encore, il est reposé — le bloc se met à sonner
    sans autre geste (block-status.md §4). La sandbox d'abord (le Designer), sinon le preset courant."""
    from . import recall
    from .state import state
    from .store import _read_json
    sb = _read_json(recall.SANDBOX_BUF, {}) or {}
    if pid and isinstance(sb.get("preset"), dict) and sb["preset"].get("id") == pid:
        log.info(f"capture(s) téléchargée(s) pour {pid} — sandbox reposée")
        recall.reapply_sandbox()
    elif pid and state.preset_id == pid:
        log.info(f"capture(s) téléchargée(s) pour {pid} — preset rappelé")
        recall.do_recall(pid, state.scene_id)


@router.post("/api/blocks/fetch")
def blocks_fetch(body: dict):
    p = _preset_of(body.get("id"), body.get("preset"))
    if p is None:
        return JSONResponse({"error": "no preset"}, 404)
    ids = body.get("blocks") or None
    pid = p.get("id")
    try:
        started = BS.fetch(p, ids, on_done=lambda _done: _replay(pid))
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, 409)
    return {"started": started}


@router.get("/api/blocks/fetch")
def blocks_fetch_status():
    return BS.fetch_status()


@router.post("/api/blocks/playable")
def blocks_playable(body: dict):
    """Capture A2 sur un poste : télécharge sa jumelle classique depuis TONE3000 (même réglage, format
    que ce moteur NAM lit), puis repose le preset — le bloc se met à sonner. Le document ne change pas."""
    b = body.get("block") if isinstance(body.get("block"), dict) else {}
    p = _preset_of(body.get("id"), body.get("preset"))
    try:
        added = BS.install_playable(b)
    except SystemExit as e:                      # t3k.py sort par sys.exit quand la session est morte
        from .routes_t3k import _t3k_error
        return JSONResponse({"error": _t3k_error(e)}, 401)
    except Exception as e:
        from .routes_t3k import _t3k_error
        log.warning(f"jumelle jouable du bloc {b.get('id')} : {e}")
        return JSONResponse({"error": _t3k_error(e)}, 502)
    st = BS.block_state(b)
    if p and st.get("state") == "ready":
        _replay(p.get("id"))
    return {"ok": True, "added": added, "status": st}


@router.get("/api/blocks/alternatives")
def blocks_alternatives(type: str, role: str = ""):
    return BS.alternatives(type, role or None)


@router.post("/api/blocks/suggest")
def blocks_suggest(body: dict):
    """La capture que le NOM du bloc désigne — une proposition pour la feuille Replace (§6)."""
    b = body.get("block") if isinstance(body.get("block"), dict) else {}
    return {"suggestion": BS.suggestion(b)}


@router.get("/api/system/fx-inventory")
def fx_inventory():
    inv = BS.inventory()
    c = BS.caps()
    return dict(c, plugins=(inv or {}).get("n"))


@router.post("/api/system/fx-inventory")
def fx_inventory_refresh():
    """Redemande l'inventaire à Reaper (lecture seule : EnumInstalledFX, aucun plugin instancié)."""
    try:
        commands.write_command({"action": "fxinventory"})
    except Exception as e:
        return JSONResponse({"error": f"Reaper command slot unavailable: {e}"}, 503)
    return {"ok": True}
