# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes STANDARDS — le rack joue la grille, tu joues par-dessus (docs/standards.md).

  GET  /api/standards                 — le catalogue (1382 grilles, cache local golem.fm)
  GET  /api/standards/{slug}          — la grille compilée (+ surcouche locale)
  POST /api/standards/{slug}/preview   — rend SANS jouer : ce que le rack va faire
  POST /api/standards/play            — compile, rend, écrit la séquence, lance
  POST /api/standards/stop            — arrête (et coupe les notes tenues)
  GET  /api/standards/state           — ce que le lecteur joue en ce moment
  GET  /api/standards/grooves         — les grooves JOUÉS importés (packs .mid)
  GET  /api/standards/grooves/tree    — les mêmes, rangés pack > style > kit (navigateur)
  POST /api/standards/grooves/audition — écoute UNE prise, sans toucher au réglage du bloc
  GET  /api/standards/sync            — ce que golem.fm peut servir, croisé avec le rack
  POST /api/standards/sync            — met à jour les standards que le rack A DÉJÀ (ou {slug}) ; n'en ajoute ni n'en retire
  DEL  /api/standards/synced/{slug}   — retire une grille du rack (geste manuel)
  PUT  /api/standards/{slug}/overlay  — corrige une grille (défaut jamais écrasé)

⚠ Ordre des routes : `/{slug}` capture n'importe quel segment. Les verbes FIXES (`play`,
`stop`) sont donc déclarés AVANT — piège déjà payé sur `/api/patches/backfill-scenes`.
"""
import asyncio

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from . import golemfm
from . import standards as S
from .commands import write_command

router = APIRouter()


@router.get("/api/standards")
async def api_list(q: str = None, limit: int = 200, synced: int = 0):
    """`synced=1` : seulement ce que le groupe a rapatrié de golem.fm — c'est ce que le
    tiroir du bloc montre par défaut (personne n'a besoin de 1382 grilles sur scène)."""
    if not S.catalog_ready():
        return {"ready": False, "standards": [],
                "reason": "no charts — sync from golem.fm"}
    lst = S.list_standards(q=q, limit=None)
    n_sync = sum(1 for m in lst if m["synced"])
    if synced:
        lst = [m for m in lst if m["synced"]]
    from . import factory
    factory.mark("standards", lst, key="slug")
    return {"ready": True, "standards": lst[:limit] if limit else lst,
            "total": len(lst), "synced": n_sync}


@router.post("/api/standards/play")
async def api_play(body: dict = Body(...)):
    """Compile la grille, la rend en événements, écrit la séquence, lance le lecteur."""
    slug = (body or {}).get("standard")
    if not slug:
        return JSONResponse({"error": "standard missing"}, status_code=400)
    b = S.build(slug,
                key=body.get("key"), feel=body.get("feel"),
                motion=body.get("motion") or "comp", groove=body.get("groove"),
                groove_take=body.get("groove_take"),
                parts=body.get("parts"), choruses=int(body.get("choruses") or 1),
                count_in=int(body.get("count_in") or 0),
                rootless=body.get("voicing", "rootless") == "rootless",
                bpm=body.get("bpm"), play=body.get("play"))
    if not b:
        return JSONResponse({"error": f"unknown standard: {slug}"}, status_code=404)
    parts = b["parts"]                       # EFFECTIFS : défauts de la grille inclus
    write_command({"action": "standard", "op": "play", "standard": slug,
                   "file": b["file"], "loop": bool(body.get("loop", True)),
                   "arp": body.get("arp") or "", "kit": body.get("kit") or "black-pearl",
                   "keys": parts.get("keys", True), "bass": parts.get("bass", True),
                   "drums": bool(parts.get("drums")), "guitar": bool(parts.get("guitar"))})
    return {"ok": True, "standard": slug, "events": b["events"], "bars": b["bars"],
            "tempo": b["tempo"], "key": b["grid"]["key"], "semis": b["render"]["semis"],
            "feel": b["render"]["feel"], "unknown": b["render"]["unknown"],
            "fills": b["fills"], "chart": b["render"]["bars"]}


@router.post("/api/standards/stop")
async def api_stop():
    write_command({"action": "standard", "op": "stop"})
    return {"ok": True}


@router.get("/api/standards/sync")
async def api_sync_catalog():
    """Ce que le groupe a TAGUÉ sur golem.fm, croisé avec ce qui est déjà sur le rack.

    ⚠ AVANT `/{slug}`, qui capturerait « sync »."""
    return await asyncio.get_running_loop().run_in_executor(None, golemfm.standards_catalog)


@router.post("/api/standards/sync")
async def api_sync(body: dict = Body(default={})):
    """Met à jour les standards du rack (nouvelle version chez golem.fm) — ou rapatrie un seul standard si `slug` est
    donné. Un standard ARRIVE par « Send to <golem> » sur golem.fm (job song-install)."""
    loop = asyncio.get_running_loop()
    slug = (body or {}).get("slug")
    if slug:
        ok, msg = await loop.run_in_executor(None, golemfm.standards_import, slug)
        if ok:
            S.invalidate()
        return {"ok": ok, "slug": slug, **({} if ok else {"error": msg})}
    return await loop.run_in_executor(None, golemfm.standards_sync)


@router.delete("/api/standards/synced/{slug}")
async def api_unsync(slug: str):
    """Retire une grille du rack. Geste MANUEL : une synchro n'efface jamais toute seule."""
    return {"ok": golemfm.standards_remove(slug)}


@router.get("/api/standards/state")
async def api_state():
    """Ce que le lecteur fait EN CE MOMENT (écrit par golem_chordseq.lua).

    ⚠ Doit rester AVANT `/{slug}`, qui capturerait le segment « state »."""
    import json as _json
    import os as _os
    p = _os.path.join(S.config.ROOT, "presets", ".standard.json")
    try:
        with open(p, encoding="utf-8") as f:
            return _json.load(f)
    except (OSError, ValueError):
        return {"present": False, "playing": False}


@router.get("/api/standards/grooves/tree")
async def api_groove_tree():
    """L'arbre du navigateur : pack > style > kit > prises. ⚠ AVANT `/{slug}`."""
    return {"packs": S.pack_tree()}


@router.post("/api/standards/grooves/audition")
async def api_groove_audition(body: dict = Body(...)):
    """Écoute UNE prise (ou son fill) en boucle, SANS modifier le réglage du bloc.

    C'est le ▶ de chaque ligne du navigateur : comparer deux grooves ne doit pas obliger à
    changer le réglage puis à le remettre. La séquence écrite est la même que pour un
    standard — c'est le même lecteur, donc la même horloge.
    """
    fam = (body or {}).get("family")
    r = S.render_groove(fam, body.get("bpm"), int(body.get("bars") or 2),
                        body.get("meter") or "4/4", bool(body.get("fill")))
    if not r:
        return JSONResponse({"error": f"no groove: {fam}"}, status_code=404)
    path, n = S.write_seq(r)
    write_command({"action": "standard", "op": "play", "standard": fam, "file": path,
                   "loop": True, "arp": "", "kit": body.get("kit") or "black-pearl",
                   "keys": False, "bass": False, "drums": True})
    return {"ok": True, "family": fam, "events": n}


@router.get("/api/standards/grooves")
async def api_grooves(meter: str = None):
    """Les familles de grooves JOUÉS que le rack possède (packs .mid importés).

    Vide tant que `tools/import-drum-packs.py` n'a pas tourné : le tiroir ne montre alors
    que les motifs écrits. Aucun réglage à faire pour que ça marche sans pack.

    ⚠ Doit rester AVANT `/{slug}`."""
    return {"families": S.pack_families(meter)}


@router.get("/api/standards/{slug}")
async def api_grid(slug: str):
    g = S.get_grid(slug)
    if not g:
        return JSONResponse({"error": "unknown"}, status_code=404)
    return g


@router.post("/api/standards/{slug}/preview")
async def api_preview(slug: str, body: dict = Body(default={})):
    """Ce que le rack JOUERA — sans rien lancer. Sert la grille transposée à l'écran."""
    g = S.get_grid(slug)
    if not g:
        return JSONResponse({"error": "unknown"}, status_code=404)
    body = body or {}
    r = S.render(g, key=body.get("key") or g.get("key"), feel=body.get("feel"),
                 motion=body.get("motion") or "comp", groove=body.get("groove"),
                 groove_take=body.get("groove_take"),
                 parts=body.get("parts"),
                 choruses=int(body.get("choruses") or 1),
                 count_in=int(body.get("count_in") or 0),
                 rootless=body.get("voicing", "rootless") == "rootless",
                 bpm=body.get("bpm"),
                 # le style de pompe se DESSINE (onglet Guitar) : il faut le rendre pour le montrer
                 pompe=(body.get("play") or {}).get("pompe"))
    return {"slug": slug, "title": g["title"], "bars": r["bars"], "events": len(r["events"]),
            "semis": r["semis"], "feel": r["feel"], "unknown": r["unknown"],
            "tempo": g["tempo"], "key": g["key"], "key_inferred": g.get("key_inferred"),
            "fills": r.get("fills", 0), "groove_meter": r.get("groove_meter"),
            "roll": _roll(r)}


def _roll(r, bars=2):
    """Les notes des `bars` premières mesures, en TEMPS (pas en ticks) — pour l'aperçu.

    Le tiroir dessine ce que le réglage produit. Sans ça, « charleston » ou « drop 2 » ne
    sont que des mots : on ne saurait pas ce qu'ils font avant de lancer le son.
    """
    span = r["bar_ppq"] * bars
    t0 = r.get("count_in_ppq") or 0
    out = []
    for at, note, vel, lane in r["events"]:
        if vel and lane in (0, 1, S.LANE_GUITAR) and t0 <= at < t0 + span:
            out.append({"b": round((at - t0) / S.PPQ, 3), "n": note, "v": vel, "l": lane})
    return {"notes": out[:120], "beats": r["bar_ppq"] // S.PPQ, "bars": bars}


@router.put("/api/standards/{slug}/overlay")
async def api_overlay(slug: str, body: dict = Body(default={})):
    """Corrige une grille SANS toucher au corpus amont (défaut + surcouche)."""
    if not S.get_grid(slug):
        return JSONResponse({"error": "unknown"}, status_code=404)
    S.save_overlay(slug, body or None)
    return {"ok": True, "grid": S.get_grid(slug)}
