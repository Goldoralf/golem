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
    # un téléphone déjà appairé qui revient de golem.fm/connect (« Sign in with golem.fm ») présente son jeton :
    # c'est cet appareil qu'on met à niveau (docs/devices-people.md §5)
    # …ou, revenu sous une autre origine (golem.fm renvoie vers l'IP), celui qui est parti de cette IP (auth.start_signin)
    ip = request.client.host if request.client else ""
    dev = auth_mod.device_of(request)
    did = (dev or {}).get("id") or auth_mod.pending_signin(ip)
    st, out = await asyncio.get_running_loop().run_in_executor(
        None, lambda: connect.redeem(body.get("ticket"), ua=request.headers.get("user-agent", ""), ip=ip, device_id=did))
    if st == 200 and did and out.get("kind") == "Phone":
        out["open"] = "/app/m.html?tab=system&page=account"     # retour sur la page du compte, connecté
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


@router.post("/api/auth/signin")
def auth_signin(request: Request):
    """« Sign in with golem.fm » : retient l'appareil qui part (auth.start_signin) et rend l'adresse de golem.fm/connect.
    Le rack doit être appairé à golem.fm : c'est lui qui rachètera le ticket au retour."""
    from . import golemfm
    dev = auth_mod.device_of(request)
    if dev is None:
        return JSONResponse({"error": "no device token"}, status_code=400)
    base, token = golemfm._cfg()
    if not base or not token:
        return JSONResponse({"error": "This golem is not paired with golem.fm yet. Pair it first (System ▸ golem.fm)."},
                            status_code=409)
    auth_mod.start_signin(dev["id"], request.client.host if request.client else "")
    return {"url": base.rstrip("/") + "/connect/"}


@router.post("/api/auth/display")
async def auth_display(request: Request):
    """L'appareil qui parle choisit SON affichage (`phone` | `tablet`) — un choix d'écran, pas un droit."""
    dev = auth_mod.device_of(request)
    if dev is None:
        return JSONResponse({"error": "no device token"}, status_code=400)
    body = await _body(request)
    if not auth_mod.set_display(dev["id"], body.get("display")):
        return JSONResponse({"error": "display must be phone or tablet"}, status_code=400)
    return {"ok": True, "display": body.get("display")}


@router.post("/api/auth/signout")
def auth_signout(request: Request):
    """Se déconnecter de golem.fm sur CET appareil (docs/devices-people.md §5) : il reste appairé."""
    dev = auth_mod.device_of(request)
    if dev is None:
        return JSONResponse({"error": "no device token"}, status_code=400)
    auth_mod.sign_out(dev["id"])
    return {"ok": True}


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
