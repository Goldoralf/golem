# SPDX-License-Identifier: GPL-3.0-or-later
"""« + Add » d'une batterie, par le rack (docs/drums-kit.md §8, maquette mockups/drums-add.html) :
d'où (volumes, un chemin, une URL), ce que le rack y LIT, puis l'installation — un job suivi en octets."""
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/kits/import/volumes")
def volumes():
    from . import kit_import
    return {"volumes": kit_import.volumes()}


@router.get("/api/kits/import/browse")
def browse(path: str = ""):
    """Les dossiers et les .sfz d'un dossier de ce poste — l'explorateur de la feuille d'import."""
    from . import kit_import
    try:
        return kit_import.browse(path or None)
    except ValueError as ex:
        return JSONResponse({"error": str(ex)}, status_code=404)


@router.get("/api/kits/import/scan")
def scan(path: str):
    """Les kits trouvés sous un dossier (DrumGizmo : drumkit + midimap ; SFZ : chaque .sfz)."""
    from . import kit_import
    import os
    if not os.path.isdir(path):
        return JSONResponse({"error": "no such folder"}, status_code=404)
    return {"path": path, "hits": kit_import.scan(path)}


@router.get("/api/kits/import/read")
def read(path: str):
    """Ce que le rack lit dans un kit AVANT d'écrire : pièces, micros, taille, moteur disponible ou non."""
    from . import kit_import
    r = kit_import.read(path)
    return r if r.get("ok") else JSONResponse(r, status_code=400)


@router.post("/api/kits/import/install")
def install(body: dict):
    from . import kit_import
    try:
        jid = kit_import.install(body.get("path"), body.get("name"), body.get("sfz_file"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "job": jid}


@router.post("/api/kits/import/url")
def url(body: dict):
    from . import kit_import
    kit_import.cleanup_downloads()                                      # les archives d'il y a plus d'une semaine
    try:
        jid = kit_import.fetch_url(body.get("url"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, "job": jid}


@router.get("/api/kits/import/job/{jid}")
def job(jid: str):
    from . import kit_import
    j = kit_import.job(jid)
    return j if j else JSONResponse({"error": "unknown job"}, status_code=404)
