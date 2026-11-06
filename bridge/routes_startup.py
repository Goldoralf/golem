# SPDX-License-Identifier: GPL-3.0-or-later
"""L'accueil au démarrage (bridge/startup_home.py, maquette mockups/startup-home.html)."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import startup_home as SH
from .state import state

router = APIRouter()


def _touch():
    state.touch()


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
    _touch()
    return {"ok": True, **r}


@router.post("/api/startup/home")
async def startup_home_set(body: dict):
    try:
        r = SH.set_home(body or {})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    _touch()
    return {"ok": True, **r}


@router.delete("/api/startup/home")
async def startup_home_clear():
    r = SH.clear_home()
    _touch()
    return {"ok": True, **r}
