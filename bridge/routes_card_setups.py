# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes de la synchronisation des configurations de carte son (docs/card-setups-exchange.md, maquette
mockups/soundcard-sync.html). Tout passe par bridge/card_setups.py ; rien ici ne touche un fichier."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import card_setups as CS

router = APIRouter()


def _dev(body):
    from . import inputmap
    return (body or {}).get("card") or inputmap._card_device()


@router.get("/api/card-setups")
def card_setups_get(card: str = "", fresh: int = 0):
    from . import inputmap
    return CS.status(card or inputmap._card_device(), fresh=bool(fresh))


@router.post("/api/card-setups/apply")
async def card_setups_apply(body: dict):
    try:
        return {"ok": True, **CS.use_sibling(_dev(body), (body or {}).get("rack"))}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/card-setups/offer")
async def card_setups_offer(body: dict):
    st, res = CS.offer(_dev(body), (body or {}).get("to_rack"))
    if st != 202:
        return JSONResponse({"error": (res or {}).get("error") or f"golem.fm answered {st}"}, status_code=502 if st else 503)
    return {"ok": True, **res}


@router.post("/api/card-setups/separate")
async def card_setups_separate(body: dict):
    try:
        CS.separate(_dev(body), (body or {}).get("rack"))
        return {"ok": True}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@router.post("/api/card-setups/later")
async def card_setups_later(body: dict):
    CS.ask_later(_dev(body))
    return {"ok": True}


@router.post("/api/card-setups/offers/{offer_id}/reply")
async def card_setups_reply(offer_id: str, body: dict):
    try:
        return CS.reply(_dev(body), offer_id, (body or {}).get("status"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
