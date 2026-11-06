# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes backing tracks / golem.fm (hors transport — POST /api/backing vit dans
app.py, à côté de /api/looper, car il pilote le BackingControl construit là-bas).

  GET    /api/golemfm/status      — configurée ? joignable ? appairée ?
  POST   /api/golemfm/pair        — démarre l'appairage (code + QR url)
  GET    /api/golemfm/pair/status — poll de l'approbation (relaie vers golem.fm)
  GET    /api/backing/catalog       — catalogue serveur fusionné avec l'état du cache
  POST   /api/backing/dl {slug}     — télécharge les 6 stems (thread démon)
  GET    /api/backing/dl/status     — progression du téléchargement
  GET    /api/backing/cache         — chansons en cache + usage disque
  DELETE /api/backing/cache/{slug}  — éviction manuelle
"""
import os
import json
import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import config as C
from . import golemfm

router = APIRouter()


# ── KARAOKÉ (docs/karaoke.md) : golem.fm le pilote par le WS de follow. Ces deux routes servent à le
# VÉRIFIER au rack sans golem.fm : l'état et les dernières trames, et une commande injectée — dont les
# réponses restent au rack (`_local`), jamais envoyées à golem.fm. L'injection est au palier admin.
@router.get("/api/karaoke")
def karaoke_status():
    from . import karaoke
    return karaoke.status()


@router.post("/api/karaoke/cmd")
def karaoke_cmd(body: dict):
    from . import karaoke
    msg = dict(body or {}, type="cmd", _local=True)
    if not str(msg.get("cmd") or "").startswith("karaoke-") or not karaoke.handle(msg):
        return JSONResponse({"error": "cmd must be karaoke-load | karaoke-mix | karaoke-stop | karaoke-prefetch"}, status_code=400)
    return {"ok": True, "queued": msg["cmd"]}


@router.get("/api/golemfm/status")
async def golemfm_status():
    # status() fait jusqu'à 2 requêtes réseau (health + songs) -> executor
    return await asyncio.get_running_loop().run_in_executor(None, golemfm.status)


def _qr_matrix(text):
    """Matrice 0/1 pour le rendu SVG côté app (même forme que /api/t3k/auth/start)."""
    import qrcode
    q = qrcode.QRCode(border=2)
    q.add_data(text)
    q.make(fit=True)
    return [[1 if c else 0 for c in row] for row in q.get_matrix()]


@router.post("/api/golemfm/pair")
async def golemfm_pair(body: dict | None = None):
    name = (body or {}).get("device_name") or "GoleM rack"
    r = await asyncio.get_running_loop().run_in_executor(None, golemfm.pair_start, name)
    if r.get("ok") and r.get("approve_url"):
        r["qr"] = _qr_matrix(r["approve_url"])
    return r


@router.get("/api/golemfm/pair/status")
async def golemfm_pair_status():
    return await asyncio.get_running_loop().run_in_executor(None, golemfm.pair_status)


@router.get("/api/backing/bars/{slug}")
def backing_bars(slug: str):
    """La carte des mesures de cette backing (docs/bars-format.md), telle que le rack la jouerait : source,
    mesures, ancres, temps approximés — ce que la page chanson affiche. {present: false} sans carte valide."""
    from . import bars as _bars
    # la carte de la clé JOUÉE (lot 1.5) : celle du .golem quand la chanson y porte ses stems
    return _bars.stats(_bars.load(golemfm.backing_key(slug)))


@router.post("/api/backing/drawer")
async def backing_drawer(body: dict):
    """Le tiroir Backing Track (docs/song-backing.md §6-7), LECTURE seule — un POST parce qu'il reçoit le preset TEL
    QU'IL EST dans le Designer (brouillon compris) : `{preset}`. Rend `own` (ce que ce preset joue sur ce golem),
    `song` (la chanson chargée, si elle joue ce preset : ses stems, ses propres coupures, d'où elle vient) et
    `used_by` (les chansons et lignes qui jouent ce preset — calculé, jamais stocké dans le preset)."""
    from . import backing_owner as BO
    from .state import state
    p = (body or {}).get("preset") or {}
    pid = p.get("id") or ""

    def work():
        out = {"own": BO.own_parts(p), "song": None, "used_by": BO.used_by(pid) if pid else {"songs": [], "lines": []},
               "families": list(BO.FAMILIES)}
        song = getattr(state, "song", None) or {}
        if song.get("preset") and song.get("preset") == pid:
            from . import recall
            eff = recall.effective_preset(p) or {}
            bs = ((eff.get("backing") or {}).get("songs") or [None])[0]
            if bs and bs.get("slug"):
                key = bs["slug"]
                meta = golemfm.read_meta(key) or {}
                mix = meta.get("mix") or {}
                art = golemfm.local_art(key, {"title": bs.get("title"), "artist": bs.get("artist")})
                fams = {}
                for stem, m in mix.items():
                    fam = str(stem).split("-")[0]
                    if (m or {}).get("mute") and fam in BO.FAMILIES:
                        fams[fam] = True
                where = None
                if song.get("line"):
                    from . import setlists as SL
                    sl = SL.load(song.get("setlist") or SL.active_id()) or {}
                    idx = next((i for i, ln in enumerate(sl.get("lines") or []) if ln.get("id") == song["line"]), None)
                    where = {"setlist": sl.get("id"), "name": sl.get("name"), "bank": idx, "line": song["line"]}
                out["song"] = {"slug": key, "id": song.get("band_song") or (key if golemfm.is_song_key(key) else None),
                               "title": bs.get("title") or song.get("title"), "artist": bs.get("artist") or art.get("artist"),
                               "duration_sec": bs.get("duration_sec"), "cached": golemfm.is_cached(key),
                               "has_cover": bool(art.get("cover")), "has_photo": bool(art.get("photo")),
                               "stems": golemfm.stems_of(key), "muted": sorted(fams), "from": where}
            else:
                out["song"] = {"slug": None, "title": song.get("title"), "id": song.get("band_song"), "stems": [],
                               "muted": [], "from": None, "no_backing": True}
        return out
    return await asyncio.get_running_loop().run_in_executor(None, work)


@router.get("/api/backing/catalog")
async def backing_catalog():
    return await asyncio.get_running_loop().run_in_executor(None, golemfm.catalog)


@router.get("/api/backing/asset/{slug}/{kind}")
async def backing_asset(slug: str, kind: str):
    """Pochette · photo d'artiste · MIX ORIGINAL d'une chanson. Proxy authentifié vers golem.fm
    + cache disque (le navigateur du rack n'a pas le jeton, et le rack peut être hors ligne en
    scène : une fois vue, la pochette reste). 404 franc si la chanson n'a pas ce média."""
    from fastapi.responses import FileResponse
    if kind not in ("cover", "photo", "original"):
        return JSONResponse({"error": "cover|photo|original"}, status_code=400)
    p = await asyncio.get_running_loop().run_in_executor(None, golemfm.asset, slug, kind)
    if not p:
        return JSONResponse({"error": "not available"}, status_code=404)
    # une image tirée d'un .golem garde son type réel (jpg, png ou webp — `art/band.*`, golem-format.md §9)
    img = {".png": "image/png", ".webp": "image/webp"}.get(os.path.splitext(p)[1].lower(), "image/jpeg")
    # l'original d'un .golem peut être en WAV ou FLAC (golem-format.md §3) : son type réel, pas mp3 d'office
    snd = {".wav": "audio/wav", ".flac": "audio/flac"}.get(os.path.splitext(p)[1].lower(), "audio/mpeg")
    return FileResponse(p, media_type=snd if kind == "original" else img)


@router.post("/api/backing/listen")
async def backing_listen(body: dict):
    """▶ d'une carte Library ▸ Tracks (2026-10-17) : l'ORIGINAL joué par REAPER (action sample_preview, la sortie
    par défaut = les enceintes du rack) — le navigateur sortait sur une autre carte que celle que REAPER tient.
    body = {slug} pour écouter (une écoute coupe la précédente), {} pour arrêter."""
    from .commands import write_command
    slug = (body or {}).get("slug")
    if not slug:
        write_command({"action": "sample_preview", "file": ""})
        return {"ok": True, "stopped": True}
    p = await asyncio.get_running_loop().run_in_executor(None, golemfm.listen_path, slug)
    if not p:
        return JSONResponse({"error": "nothing to play for this song on this golem"}, status_code=404)
    write_command({"action": "sample_preview", "file": os.path.abspath(p), "db": 0})
    return {"ok": True}


@router.post("/api/backing/dl")
async def backing_download(body: dict):
    slug = (body or {}).get("slug")
    if not slug:
        return JSONResponse({"error": "slug required"}, status_code=400)
    return golemfm.download(slug)


@router.get("/api/backing/dl/status")
def backing_dl_status():
    return golemfm.dl_status()


@router.get("/api/backing/cache")
def backing_cache():
    songs = golemfm.list_cache()
    return {"songs": songs, "bytes": sum(s.get("bytes") or 0 for s in songs)}


@router.delete("/api/backing/cache/{slug}")
def backing_cache_delete(slug: str):
    ok = golemfm.remove_cached(slug)
    return {"ok": ok} if ok else JSONResponse({"error": "not cached"}, status_code=404)

# ── mix par CHANSON (remarque 2026-07-23 : stems actifs/mutés éditables depuis la carte
# de la feuille backing, chanson chargée ou pas). Le mix appartient à la chanson (meta.json du
# cache) ; si elle est chargée dans Reaper, on pousse AUSSI en live via le contrôleur (qui
# re-persiste — idempotent). Éditable seulement en cache (pas de meta sinon).
@router.get("/api/backing/meta/{slug}")
def backing_meta(slug: str):
    """meta.json d'un morceau du cache (titre, bpm, lyrics… — Companion ▸ Stage chanteur)."""
    import re as _re
    slug = _re.sub(r"[^a-z0-9_\-]", "", str(slug or ""))
    try:
        return json.load(open(os.path.join(C.BACKING_DIR, slug, "meta.json")))
    except Exception:
        return JSONResponse({"error": "unknown song"}, status_code=404)


@router.get("/api/backing/mix/{slug}")
def backing_mix_get(slug: str):
    # le tiroir parle en SLUG du catalogue ; si cette chanson joue depuis son .golem (lot 1.5), c'est le mix de
    # la clé JOUÉE qu'on montre et qu'on règle — sinon une coupure n'atteindrait plus ce qui sonne
    key = golemfm.backing_key(slug)
    meta = golemfm.read_meta(key) or {}
    return {"stems": golemfm.stems_of(key), "cached": golemfm.is_cached(key), "key": key,
            "mix": meta.get("mix") or ({} if golemfm.is_song_key(key) else dict(golemfm.DEFAULT_MIX))}


@router.post("/api/backing/mix/{slug}")
async def backing_mix_set(slug: str, body: dict):
    stem = (body or {}).get("stem")
    slug = golemfm.backing_key(slug)               # la clé JOUÉE (lot 1.5) : voir backing_mix_get
    if stem not in golemfm.stems_of(slug):
        return JSONResponse({"error": "unknown stem"}, status_code=400)
    if not golemfm.is_cached(slug):
        return JSONResponse({"error": "not cached"}, status_code=404)
    mute = 1 if (body or {}).get("mute") else 0
    meta = golemfm.read_meta(slug) or {}
    mix = meta.get("mix") or ({} if golemfm.is_song_key(slug) else dict(golemfm.DEFAULT_MIX))
    mix[stem] = {**(mix.get(stem) or {}), "mute": mute}
    golemfm.save_mix(slug, mix)
    from . import app as app_mod                    # import tardif (app importe ce module)
    ctl = getattr(app_mod, "_backing_ctl", None)
    if ctl is not None and getattr(ctl, "_slug", None) == slug:
        # ce qui JOUE = la chanson, puis la règle du preset (song-backing.md §4) : rallumer un stem que le preset coupe
        # ne le fait pas jouer — la chanson est enregistrée, la scène ne change pas
        from .commands import write_command
        played = ctl.played_mix(slug).get(stem) or {}
        write_command({"action": "backing", "op": "mix", "stem": stem, "mute": 1 if played.get("mute") else 0})
    return {"ok": True, "mix": mix}
