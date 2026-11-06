# SPDX-License-Identifier: GPL-3.0-or-later
"""L'accueil au démarrage (bridge/startup_home.py, maquette mockups/startup-home.html)."""
import contextlib

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import startup_home as SH
from .state import state

router = APIRouter()


async def _touch():
    """Le changement part TOUT DE SUITE aux écrans. `state.touch()` seul ne pousse rien : l'écran ne l'apprenait qu'à
    la diffusion suivante, et « ⌂ Open at startup » semblait sans effet jusqu'au redémarrage (vécu le 2026-11-06)."""
    state.touch()
    with contextlib.suppress(Exception):
        from . import app as _app
        await _app._broadcast()


@router.post("/api/services/check")
async def services_check():
    """La page API redemande le verdict golem.fm / TONE3000 (pastilles, mockups/settings-badges.html)."""
    import asyncio
    from . import boot_progress
    r = await asyncio.to_thread(boot_progress.check_services_now)
    state.touch()
    return {"ok": True, "services": r}


@router.get("/api/startup")
def startup_get():
    return SH.describe()


@router.post("/api/startup")
async def startup_policy(body: dict):
    try:
        r = SH.set_policy((body or {}).get("policy"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    await _touch()
    return {"ok": True, **r}


@router.post("/api/startup/home")
async def startup_home_set(body: dict):
    try:
        r = SH.set_home(body or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    await _touch()
    return {"ok": True, **r}


@router.delete("/api/startup/home")
async def startup_home_clear():
    r = SH.clear_home()
    await _touch()
    return {"ok": True, **r}
