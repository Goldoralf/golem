# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes du lot 8 (docs/diagnostics.md §5) — pour les OUTILS et la case, pas pour une UI de rapports :
il n'y a aucun bouton « send » nulle part, par décision (2026-09-13).

  GET  /api/diag                 index des paquets, session courante, état de la case
  POST /api/diag/build           fabrique un paquet {kind, detail?} SANS l'envoyer (check-report.py, agent)
  GET  /api/diag/{id}/download   le zip (dépannage local sans golem.fm) — GET SENSIBLE (auth.py)
  POST /api/diag/settings        {auto: bool} — la case de Settings ▸ Connect ▸ golem.fm
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from . import diag
from .golog import get

log = get("diag-api")
router = APIRouter()


@router.get("/api/diag")
def diag_status():
    return diag.status()


@router.post("/api/diag/build")
def diag_build(body: dict = None):
    body = body or {}
    kind = body.get("kind") or "event"
    if kind not in diag.KINDS:
        return JSONResponse({"ok": False, "error": f"kind must be one of {list(diag.KINDS)}"}, status_code=400)
    ev = {"type": "requested", "detail": body.get("detail")} if kind == "event" else None
    try:
        r = diag.build(kind, event_=ev, force=True)
    except Exception as e:
        log.warning(f"fabrication refusée : {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
    return {"ok": True, **r}


@router.get("/api/diag/{report_id}/download")
def diag_download(report_id: str):
    p = diag.report_path(report_id)
    if not p:
        return JSONResponse({"ok": False, "error": "unknown report"}, status_code=404)
    return FileResponse(p, media_type="application/zip", filename=p.rsplit("/", 1)[-1])


@router.post("/api/diag/settings")
def diag_settings(body: dict):
    if "auto" not in body:
        return JSONResponse({"ok": False, "error": "auto required"}, status_code=400)
    on = diag.set_auto(bool(body["auto"]))
    log.info(f"rapports automatiques : {'ON' if on else 'OFF'}")
    return {"ok": True, "auto": on}


# ── les erreurs de l'app (docs/diagnostics.md §7.2) ─────────────────────────────────────────────────────────────────
# La page en envoie au plus 20 par chargement ; ici au plus UI_ERRORS_MAX par session du bridge. Jamais un déclencheur :
# `ui_error` part avec le paquet `session`. Une route POST : protégée par défaut (auth.py), un appelant anonyme du réseau
# est refusé ; l'écran du rack (localhost) et les appareils appairés passent.
UI_ERRORS_MAX = 60
UI_CLIENTS = ("rack", "companion", "phone")
_ui = {"session": None, "n": 0}


@router.post("/api/diag/ui-error")
def diag_ui_error(body: dict = None):
    b = body or {}
    sid = (diag.session() or {}).get("session_id")
    if _ui["session"] != sid:
        _ui.update(session=sid, n=0)
    if _ui["n"] >= UI_ERRORS_MAX:
        return {"ok": False, "dropped": True}
    _ui["n"] += 1
    s = lambda k, n: str(b.get(k) or "")[:n]
    where = s("src", 80).replace("\\", "/").rsplit("/", 1)[-1]
    if b.get("line") is not None:
        where += f":{s('line', 8)}"
    frames = [str(f)[:80].replace("\\", "/").rsplit("/", 1)[-1] for f in (b.get("frames") or [])[:5]]
    msg = s("msg", 200)
    row = diag.event("ui_error", page=s("page", 60).split("?", 1)[0], msg=msg, where=where,
                     # la forme de la signature : le message et OÙ (fichiers et lignes de la pile, jamais l'adresse)
                     sig_src=f"{msg} @ {where} {' '.join(frames)}".strip(),
                     client=b.get("client") if b.get("client") in UI_CLIENTS else "rack")
    return {"ok": bool(row), "sig": (row or {}).get("sig")}
