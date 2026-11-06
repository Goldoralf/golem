# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes de la séparation (docs/separation.md §9 — l'écran Settings ▸ Engines ▸ Separation)."""
import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import separation as S
from . import separation_batch as SB

router = APIRouter()


def _err(e, status=400):
    return JSONResponse({"ok": False, "why": str(e)}, status_code=status)


@router.get("/api/separation")
async def api_separation(remote: bool = True):
    return await asyncio.to_thread(S.overview, remote)


@router.post("/api/separation/engines")
async def api_separation_add(body: dict):
    """{kind: "onnx", source, licence, accepted, label?} | {kind: "program", program, args[], licence, accepted, label?}.
    Ajouté PUIS testé : un moteur n'est activable qu'après un test réussi (§6)."""
    b = body or {}
    try:
        if b.get("kind") == "onnx":
            e = await asyncio.to_thread(S.add_onnx, b.get("source"), b.get("licence") or "", bool(b.get("accepted")),
                                        b.get("label") or "")
        elif b.get("kind") == "program":
            e = await asyncio.to_thread(S.add_program, b.get("program"), b.get("args") or [], b.get("licence") or "",
                                        bool(b.get("accepted")), b.get("label") or "", b.get("outputs") or None)
        else:
            return _err("kind must be onnx or program")
    except S.SeparationError as e:
        return _err(e)
    tested = None
    try:
        S.test(e["id"])
        tested = "started"
    except S.SeparationError as ex:
        tested = str(ex)
    return {"ok": True, "engine": e["id"], "test": tested}


@router.post("/api/separation/install")
async def api_separation_install(body: dict):
    try:
        e = await asyncio.to_thread(S.install_listed, (body or {}).get("slug") or "")
    except S.SeparationError as ex:
        return _err(ex)
    try:
        S.test(e["id"])
    except S.SeparationError as ex:
        return {"ok": True, "engine": e["id"], "test": str(ex)}
    return {"ok": True, "engine": e["id"], "test": "started"}


@router.post("/api/separation/engines/{eid}/test")
async def api_separation_test(eid: str):
    try:
        return S.test(eid)
    except S.SeparationError as ex:
        return _err(ex)


@router.post("/api/separation/engines/{eid}/activate")
async def api_separation_activate(eid: str, body: dict = None):
    try:
        S.activate(eid, bool((body or {}).get("accepted")))
        return {"ok": True}
    except S.SeparationError as ex:
        return _err(ex)


@router.post("/api/separation/deactivate")
async def api_separation_deactivate():
    S.deactivate()
    return {"ok": True}


@router.delete("/api/separation/engines/{eid}")
async def api_separation_remove(eid: str):
    try:
        return {"ok": await asyncio.to_thread(S.remove, eid)}
    except S.SeparationError as ex:
        return _err(ex)


@router.post("/api/separation/settings")
async def api_separation_settings(body: dict):
    try:
        S.set_threads((body or {}).get("threads"))
    except (TypeError, ValueError):
        return _err("threads must be a number")
    return {"ok": True, "threads": S.threads()}


@router.post("/api/separation/cancel")
async def api_separation_cancel():
    return {"ok": S.cancel()}


@router.post("/api/separation/excerpt")
async def api_separation_excerpt(request: Request, name: str = ""):
    """L'extrait de test de l'utilisateur (§6) : corps BRUT = les octets du fichier, `?name=` son nom. Il reste sur ce
    golem (presets/.separation) — rien ne part vers golem.fm."""
    from .http_body import read_body, TooLarge
    try:
        blob = await read_body(request, S.EXCERPT_MAX_BYTES)       # audit 2026-11-04 (M9) : borné à la lecture
    except TooLarge as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=413)
    try:
        return {"ok": True, "excerpt": await asyncio.to_thread(S.set_excerpt, blob, name)}
    except S.SeparationError as ex:
        return _err(ex)


@router.delete("/api/separation/excerpt")
async def api_separation_excerpt_clear():
    S.clear_excerpt()
    return {"ok": True}


# ── l'aide à la configuration (avis de l'avocat du 2026-10-12 : rien n'est nommé, tout est lu ou importé) ─────────────
@router.post("/api/separation/probe")
async def api_separation_probe(body: dict):
    """Essai à blanc d'un programme sur 10 s de l'extrait : les WAV qu'il écrit, et une proposition de stem pour chacun."""
    b = body or {}
    try:
        return await asyncio.to_thread(S.probe_program, b.get("program"), b.get("args") or [])
    except S.SeparationError as ex:
        return _err(ex)


@router.get("/api/separation/engines/{eid}/export")
async def api_separation_export(eid: str):
    try:
        return S.export_engine(eid)
    except S.SeparationError as ex:
        return _err(ex)


@router.post("/api/separation/import")
async def api_separation_import(body: dict):
    try:
        return {"ok": True, "form": S.read_engine_file(body)}
    except S.SeparationError as ex:
        return _err(ex)


# ── le stepper « + Add engine » ───────────────────────────────────────────────────────────────────────────────────
@router.post("/api/separation/check-program")
async def api_separation_check_program(body: dict):
    return S.program_checks((body or {}).get("program"))


@router.get("/api/separation/programs")
async def api_separation_programs():
    """§4 quinquies : les programmes libres détectés ici, avec leur plomberie — jamais un modèle."""
    return {"programs": await asyncio.to_thread(S.detect_programs)}


@router.post("/api/separation/inspect")
async def api_separation_inspect(body: dict):
    try:
        return {"ok": True, **(await asyncio.to_thread(S.inspect_source, (body or {}).get("source")))}
    except S.SeparationError as ex:
        return _err(ex)


@router.get("/api/separation/browse")
async def api_separation_browse(path: str = "", want: str = "program"):
    try:
        return await asyncio.to_thread(S.browse, path or None, want if want in ("onnx", "file", "dir", "audio") else "program")
    except S.SeparationError as ex:
        return _err(ex)


@router.post("/api/separation/program-help")
async def api_separation_program_help(body: dict):
    """Ce que le programme dit de lui-même (`--help`, sinon `-h`) — affiché à l'étape Command, jamais journalisé."""
    return await asyncio.to_thread(S.program_help, (body or {}).get("program"))


# ── « Combine two of my engines » (mockups/separation-combine.html) ─────────────────────────────────────────────────
@router.post("/api/separation/combine")
async def api_separation_combine(body: dict):
    b = body or {}
    try:
        e = await asyncio.to_thread(S.add_combined, b.get("first"), b.get("keep") or [], b.get("second"),
                                    b.get("label") or "", bool(b.get("accepted")))
    except S.SeparationError as ex:
        return _err(ex)
    try:
        S.test(e["id"])
    except S.SeparationError as ex:
        return {"ok": True, "engine": e["id"], "test": str(ex)}
    return {"ok": True, "engine": e["id"], "test": "started"}


@router.post("/api/separation/import-combined")
async def api_separation_import_combined(body: dict):
    b = body or {}
    try:
        form = S.read_engine_file(b.get("doc") or {})
        if form.get("kind") != "combined":
            return _err("this engine file is not a combination")
        return S.install_combined(form, bool(b.get("accepted")))
    except S.SeparationError as ex:
        return _err(ex)


# ── séparer un dossier (docs/separation-batch.md) ──────────────────────────────────────────────
@router.get("/api/separation/batch")
async def api_batch_state():
    return {"batch": await asyncio.to_thread(SB.state)}


@router.post("/api/separation/batch/scan")
async def api_batch_scan(body: dict):
    """{dir} → {dir, items, total_s} : ce que le dossier contient. Lit seulement."""
    try:
        return await asyncio.to_thread(SB.scan, (body or {}).get("dir") or "")
    except S.SeparationError as e:
        return _err(e)


@router.post("/api/separation/batch")
async def api_batch_start(body: dict):
    """{dir, items: [{key, title, artist}], mode: full|vocals, store?, declared?} → le lot lancé."""
    b = body or {}
    try:
        st = await asyncio.to_thread(SB.start, b.get("dir") or "", b.get("items") or [], b.get("mode") or "full",
                                     bool(b.get("store")), bool(b.get("declared")))
    except S.SeparationError as e:
        return _err(e)
    return {"ok": True, "batch": st}


@router.post("/api/separation/batch/pause")
async def api_batch_pause(body: dict):
    try:
        return {"ok": True, "batch": await asyncio.to_thread(SB.pause, bool((body or {}).get("paused", True)))}
    except S.SeparationError as e:
        return _err(e)


@router.post("/api/separation/batch/cancel")
async def api_batch_cancel():
    try:
        return {"ok": True, "batch": await asyncio.to_thread(SB.cancel)}
    except S.SeparationError as e:
        return _err(e)


@router.post("/api/separation/batch/retry")
async def api_batch_retry(body: dict):
    try:
        return {"ok": True, "batch": await asyncio.to_thread(SB.retry, str((body or {}).get("key") or ""))}
    except S.SeparationError as e:
        return _err(e)


@router.delete("/api/separation/batch")
async def api_batch_dismiss():
    try:
        await asyncio.to_thread(SB.dismiss)
    except S.SeparationError as e:
        return _err(e)
    return {"ok": True, "batch": None}


@router.post("/api/separation/batch/store")
async def api_batch_store(body: dict):
    """{keys?, declared} : les morceaux faits du lot partent dans le compte golem.fm (separation-batch.md §7)."""
    b = body or {}
    try:
        return {"ok": True, "batch": await asyncio.to_thread(SB.store, b.get("keys") or None, bool(b.get("declared")))}
    except S.SeparationError as e:
        return _err(e)

