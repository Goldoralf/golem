# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings ▸ Health (docs/health.md) : la couche « Now » en lecture. GET sensible (`/api/health/` dans
auth.SENSITIVE_GET_PREFIX) : les faits nomment le preset joué, la setlist et ses presets — pas pour un inconnu du LAN.
`/api/health` tout court (le pouls du lanceur) reste public et n'est pas touché."""
import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import assistant, first_check, fixes, health, incidents, silence

router = APIRouter()


@router.get("/api/health/facts")
def health_facts(fresh: int = 0):
    """Les faits datés, leur verdict et la garde « rack libre » — du cache (≤ 5 s), ou relus si `?fresh=1`."""
    return health.facts(fresh=bool(fresh))


# ── la vérification de première installation (docs/health.md §2) ─────────────────────────────────────────────────
@router.get("/api/health/first-check")
def first_check_status():
    """Où elle en est : les faits automatiques, les gestes faits, le délai du pédalier, l'heure du bridge."""
    return first_check.status()


@router.post("/api/health/first-check")
def first_check_act(body: dict):
    """{action: begin|step|finish|skip|reset, step?, ok?, measured?} — l'écran raconte le geste, le bridge vérifie ce
    qu'il peut (pédalier entendu APRÈS le départ, clic qui a tourné) et garde le tout dans config/.first-check.json."""
    body = body or {}
    action = str(body.get("action") or "")
    try:
        if action == "begin":
            return first_check.begin(body.get("step") or None)
        if action == "step":
            return first_check.record(str(body.get("step") or ""), body.get("ok"), body.get("measured") or {})
        if action == "finish":
            return first_check.finish()
        if action == "skip":
            return first_check.skip()
        if action == "reset":
            return first_check.reset()
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"error": "action must be begin, step, finish, skip or reset"}, status_code=400)


# ── « Why no sound? » (docs/health.md §4.1) : la chasse au silence, en lecture seule ─────────────────────────────
@router.get("/api/health/silence")
def silence_status():
    """Où en est la chasse : idle · listening (joue !) · reading · done (le rapport) · error."""
    return silence.status()


@router.post("/api/health/silence")
def silence_act(body: dict):
    """{seconds?: 1..10, waited?: bool} lance la chasse ({action: 'clear'} range le rapport). 409 avec la raison quand
    le rack n'est pas libre, qu'une chasse tourne déjà, ou que REAPER n'est pas là."""
    body = body or {}
    if body.get("action") == "clear":
        return silence.clear()
    r = silence.start(body.get("seconds") or 4.0, waited=body.get("waited", True))
    if not r.get("ok"):
        return JSONResponse({"error": r.get("why") or "cannot start"}, status_code=409)
    return r


# ── Health ▸ Fix et les incidents (docs/assistant.md §3, §3.1) ─────────────────────────────────────────────────────
@router.get("/api/health/fixes")
def fixes_registry():
    """Le registre : ce que cette machine sait faire, avec les schémas de paramètres de CETTE plateforme. C'est ce que
    `golem doctor` liste, et ce qu'un assistant recevra — la machine reste la seule source de ses actions."""
    return {"actions": fixes.registry()}


@router.get("/api/health/fix")
def fix_status():
    """La réparation en cours (phase running · verifying, et ce que la vérification voit) et la dernière finie."""
    return fixes.status()


@router.post("/api/health/fix")
async def fix_act(body: dict):
    """{action, params?, confirm?: bool, incident?, by?: button|doctor|assistant|undo}. Sans `confirm` : la FEUILLE
    (validée, décrite, avec la garde du moment) — rien n'est exécuté. Avec : exécute puis vérifie en arrière-plan.
    400 = action ou paramètres hors registre ; 409 = la garde (« not while a take is recording ») ou une réparation
    déjà en cours. Écriture admin (auth.ADMIN_WRITES)."""
    body = body or {}
    name, params = str(body.get("action") or ""), body.get("params") or {}
    if not isinstance(params, dict):
        return JSONResponse({"error": "params must be an object"}, status_code=400)
    if not body.get("confirm"):
        p = fixes.plan(name, params)
        return p if p.get("ok") else JSONResponse({"error": p["error"]}, status_code=400)
    r = await fixes.apply(name, params, by=str(body.get("by") or "button"), incident=body.get("incident") or None)
    if not r.get("ok"):
        return JSONResponse({"error": r.get("error") or "refused", "fix": r.get("fix")}, status_code=r.get("status") or 409)
    return r


@router.get("/api/health/incidents")
def incidents_list(limit: int = 30):
    """Les incidents de cette machine (30 jours) : les ouverts d'abord. Titres lisibles ici ; seuls les types et les
    codes partent dans les rapports."""
    return {"items": incidents.items(max(1, min(int(limit or 30), 200))), "hints": list(incidents.HINTS)}


@router.post("/api/health/incidents/{inc_id}/hint")
def incident_hint(inc_id: str, body: dict):
    """« What fixed it? » — {hint: cable|gain|power|other}, sur un incident revenu tout seul."""
    try:
        return incidents.hint(inc_id, str((body or {}).get("hint") or ""))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── « Ask golem » (docs/assistant.md §5–§8) : la question part vers golem.fm, la réponse revient revalidée ───────
@router.get("/api/health/assistant")
def assistant_status():
    """{available, why, consent} — le panneau n'existe que si le rack est appairé et que le mode le permet."""
    return assistant.status()


@router.post("/api/health/assistant")
async def assistant_act(body: dict):
    """{consent: bool} donne ou retire le consentement ; {question, history?} pose une question (jusqu'à 90 s : golem.fm
    attend son fournisseur). Un refus de golem.fm revient en 200 {ok: false, error, message, retry_after?} — c'est une
    réponse à dire dans le panneau, pas une erreur du rack. Écriture admin (auth.ADMIN_WRITES)."""
    body = body or {}
    if "consent" in body:
        return assistant.consent(bool(body["consent"]))
    hist = body.get("history") if isinstance(body.get("history"), list) else []
    return await asyncio.to_thread(assistant.ask, body.get("question"), hist)
