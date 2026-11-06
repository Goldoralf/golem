# SPDX-License-Identifier: GPL-3.0-or-later
"""Cet ordinateur, depuis l'app (docs/installer.md §4, FIXÉ 2026-10-16) — la logique vit dans bridge/machine.py.

  POST /api/ui/show              rouvre la fenêtre golem sur l'ordinateur (« Show on this computer »)
  GET  /api/system/autostart     démarre-t-il avec l'ordinateur ? (+ la phrase d'ouverture de session automatique)
  POST /api/system/autostart {on}
  GET  /api/system/harden        Linux : la machine est-elle verrouillée ? (et le job en cours)
  POST /api/system/harden {password}

Toutes au palier ADMIN (bridge/auth.py, ADMIN_PATHS ; les GET dans SENSITIVE_GET pour être gardés) : l'ordinateur
lui-même (localhost) ou un appareil promu. Un téléphone de musicien n'ouvre pas de fenêtre ni ne verrouille la machine.
"""
import asyncio
import os

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

from . import machine

router = APIRouter()


def _port():
    return int(os.environ.get("GOLEM_PORT", "8770"))


@router.post("/api/ui/show")
async def ui_show(body: dict = Body(default=None)):
    r = await asyncio.to_thread(machine.show, _port())
    return r if r.get("ok") else JSONResponse(r, status_code=409)


@router.get("/api/system/autostart")
async def autostart_get():
    return await asyncio.to_thread(machine.autostart_status)


@router.post("/api/system/autostart")
async def autostart_post(body: dict = Body(default=None)):
    body = body or {}
    if not isinstance(body.get("on"), bool):
        return JSONResponse({"ok": False, "error": "say on: true or on: false"}, status_code=400)
    r = await asyncio.to_thread(machine.autostart_set, body["on"])
    return r if r.get("ok") else JSONResponse({**r, "error": r.get("why")}, status_code=500)


@router.get("/api/system/harden")
async def harden_get():
    return await asyncio.to_thread(machine.harden_status)


@router.post("/api/system/harden")
async def harden_post(request: Request, body: dict = Body(default=None)):
    # audit 2026-11-04 (M5) : le mot de passe de l'utilisateur ne traverse pas le Wi-Fi en HTTP clair — l'écran du rack
    from . import auth as auth_mod
    if not auth_mod._is_local(request.client.host if request.client else ""):
        return JSONResponse({"ok": False, "error": "only on this machine's own screen"}, status_code=403)
    pw = (body or {}).get("password")
    r = await asyncio.to_thread(machine.harden_start, pw)
    pw = None
    if r.get("ok"):
        return r
    status = 400 if r.get("why") in ("type your password", "wrong password") else 409
    return JSONResponse({**r, "error": r.get("why")}, status_code=status)
