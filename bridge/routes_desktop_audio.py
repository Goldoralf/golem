# SPDX-License-Identifier: GPL-3.0-or-later
"""GoleM audio configuration on Windows and macOS."""
import sys

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import desktop_audio


router = APIRouter()


@router.get("/api/platform")
def platform_info():
    return {"platform": sys.platform}


def _desktop_only():
    return sys.platform in ("win32", "darwin")


@router.get("/api/desktop/audio")
def audio_settings():
    if not _desktop_only():
        return JSONResponse({"error": "desktop audio only"}, status_code=404)
    try:
        current = desktop_audio.settings()
        return {**current, "native_advice": desktop_audio.native_driver_advice(current), "apply": desktop_audio.status()}
    except (OSError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@router.post("/api/desktop/audio")
def apply_audio_settings(body: dict):
    if not _desktop_only():
        return JSONResponse({"error": "desktop audio only"}, status_code=404)
    try:
        return {"ok": True, "apply": desktop_audio.start_apply(body)}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@router.get("/api/desktop/audio/status")
def audio_apply_status():
    if not _desktop_only():
        return JSONResponse({"error": "desktop audio only"}, status_code=404)
    return desktop_audio.status()
