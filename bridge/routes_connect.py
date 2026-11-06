# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes « se connecter sans taper d'adresse » (docs/connect.md §4.4, lot R1 — 2026-09-16).

`POST /api/auth/connect` et `POST /api/auth/handoff/claim` sont ouvertes sans jeton comme
`/api/auth/claim` (auth.OPEN_EXCHANGES, Origin vérifié) : le ticket golem.fm et le code de transfert
SONT l'authentification, à usage unique et courts. Le reste suit les règles habituelles d'auth.py.
"""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import auth as auth_mod
from . import connect

router = APIRouter()


async def _body(request):
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


@router.post("/api/auth/connect")
async def auth_connect(request: Request):
    """Ticket golem.fm ⇒ appareil de la personne. Le rachat est un appel réseau : hors de la boucle."""
    body = await _body(request)
    st, out = await asyncio.get_running_loop().run_in_executor(
        None, lambda: connect.redeem(body.get("ticket"), ua=request.headers.get("user-agent", ""),
                                     ip=request.client.host if request.client else ""))
    return out if st == 200 else JSONResponse(out, status_code=st)


@router.post("/api/auth/handoff")
def auth_handoff(request: Request):
    """Code à usage unique pour poser le jeton de l'appareil qui parle sous une autre origine (le nom
    `.local`). Réservé à un appareil : l'écran local n'a pas de jeton à transférer."""
    dev = auth_mod.device_of(request)
    if dev is None:
        return JSONResponse({"error": "no device token"}, status_code=400)
    return auth_mod.create_handoff(dev["id"])


@router.post("/api/auth/handoff/claim")
async def auth_handoff_claim(request: Request):
    body = await _body(request)
    got = auth_mod.claim_handoff(body.get("code"))
    if not got:
        return JSONResponse({"error": "This link has expired. Open golem.fm/connect again."}, status_code=410)
    return got


@router.get("/api/connect/where")
def connect_where():
    """Ce que la présence annonce — sans `rack_id`, qui ne se montre jamais (§4.1)."""
    w = connect.where()
    w.pop("rack_id", None)
    w.pop("session", None)
    return w


@router.get("/api/connect")
def connect_settings_get():
    return {"presence": connect.presence_enabled()}


@router.post("/api/connect/settings")
async def connect_settings(request: Request):
    """La case « Let golem.fm find this rack » (§5) : écrite tout de suite, comme un consentement."""
    body = await _body(request)
    if "presence" not in body:
        return JSONResponse({"ok": False, "error": "presence required"}, status_code=400)
    on = await asyncio.get_running_loop().run_in_executor(None, lambda: connect.set_presence(bool(body["presence"])))
    return {"ok": True, "presence": on}
