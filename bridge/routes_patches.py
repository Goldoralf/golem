# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes des PATCHES — le son d'un musicien (docs/patches.md, Lot 2).

Deux modes d'appel, deux vies :
  · mode DOC (Designer) : le body porte le preset ENTIER en cours d'édition ; on le mute
    et on le RENVOIE sans l'écrire — c'est le Designer qui sauve, par son flux normal.
    (Écrire le fichier sous ses pieds = son prochain auto-commit écraserait tout.)
  · mode FICHIER (extraction de masse, Songs) : on travaille sur presets/*.json direct.
"""
import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from . import config as C
from . import patches as P
from . import roster
from .golog import get as _get_log

log = _get_log("patches")

router = APIRouter()


def _pushed(res):
    """Toute mutation du catalogue repart vers golem.fm (débouncé, best-effort) — annexe 1 de
    docs/private/exchanges/message-maestrium-ranger-prises.md : le web n'a plus à attendre un geste manuel."""
    from . import golemfm
    golemfm.push_patches()
    return res


@router.get("/api/patches")
def api_list():
    from . import factory, preview
    out = factory.mark("patches", P.list_patches())
    for x in out:                    # la démo vit à côté de ses clips, pas dans le patch (preview.patch_preview)
        if isinstance(x, dict) and x.get("id"):
            pv = preview.patch_preview(x["id"])
            if pv:
                x["preview"] = pv
            bp = preview.block_previews(preview.PATCH_PREFIX + x["id"])     # 8 mesures de ses blocs drums / standard
            if bp:
                x["block_previews"] = bp
    return {"patches": out}


# Le roster vit dans bridge/roster.py : UN seul chemin, UNE seule écriture atomique, et la
# réconciliation avec golem.fm au même endroit que la lecture. Ces deux alias gardent les
# appelants (takes.resolve_band, l'UI) intacts.
_BAND_FILE = roster.FILE


def _read_band():
    return roster.read()


@router.get("/api/band")
def api_band():
    """Le roster en cache (config/.band.json — docs/identity.md §3). Absent = pas de
    groupe : l'UI propose juste « sans personne ».

    `bands[]` = les groupes que CE RACK connaît (poussés par golem.fm). `band` reste le
    COURANT — c'est-à-dire un simple DÉFAUT pour les prises à venir, jamais une vérité :
    la vérité, c'est le tag gelé sur chaque prise (docs/private/repete-vers-demo.md §4).
    Le champ est facultatif et additif : un rack mono-groupe garde exactement sa forme.
    """
    d = _read_band()
    if not d:
        return {"band": None, "people": [], "bands": []}
    known = d.get("bands")
    if not isinstance(known, list) or not known:
        b = d.get("band") or {}
        known = [{"id": b["id"], "name": b.get("name") or b["id"]}] if b.get("id") else []
    # la photo de chaque membre : `has_avatar` si elle est en cache (roster.fetch_avatars) — l'écran la
    # demande à /api/band/avatar/<id>, servie d'ici, sans Internet
    from . import roster
    mark = lambda ps: [{**p, "has_avatar": bool(roster.avatar_file(p.get("id")))} if isinstance(p, dict) else p
                       for p in (ps or [])]
    known = [{**b, "people": mark(b.get("people"))} if isinstance(b, dict) and "people" in b else b for b in known]
    return {**d, "people": mark(d.get("people")), "bands": known}


@router.get("/api/band/avatar/{pid}")
def api_band_avatar(pid: str):
    """La photo d'un membre, tirée de golem.fm à la synchro et gardée sur le rack (config/avatars/)."""
    from fastapi.responses import FileResponse
    from . import roster
    f = roster.avatar_file(pid)
    if not f:
        return JSONResponse({"error": "no photo"}, status_code=404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


@router.post("/api/band/current")
def api_band_current(body: dict):
    """Change le groupe COURANT du rack — parmi ceux qu'il connaît, jamais un nouveau.

    ⚠ LE RACK SÉLECTIONNE, IL NE CRÉE PAS. Il n'y a pas de login ici : aucune autorité pour
    inventer un groupe. Créer, inviter, exclure sont des gestes de golem.fm ; le rack choisit
    dans un cache et fonctionne hors ligne avec (docs/identity.md).
    """
    ok, res = roster.set_current((body or {}).get("id"))
    if not ok:
        return JSONResponse({"error": res}, status_code=404)
    return {"ok": True, "band": res}


def _band_of(space=None):
    d = _read_band()
    if space:
        return next((b for b in d.get("bands") or [] if isinstance(b, dict) and b.get("id") == space), None)
    return d.get("band") or None


def _invite_url(space=None):
    """L'adresse de la page du GROUPE sur golem.fm. Le rack ne crée pas d'invitation (docs/identity.md §1,
    docs/devices-people.md §8) : il montre où elle se fabrique. Le QR ouvre le groupe sur le téléphone de
    celui qui a les droits, et c'est golem.fm qui décide s'il peut inviter."""
    from .golemfm import _cfg                          # la règle https vaut aussi pour un lien montré à l'écran
    base = _cfg()[0]
    b = _band_of(space) or {}
    slug = b.get("slug") or b.get("id")
    if not base or not slug or b.get("kind") == "personal":
        return None, b
    return f"{base}/band/{slug}", b


@router.get("/api/band/invite")
def api_band_invite(space: str = ""):
    url, b = _invite_url(space or None)
    if not url:
        return JSONResponse({"error": "no band invitation for this space"}, status_code=404)
    return {"url": url, "band": {k: b.get(k) for k in ("id", "name", "slug")}}


@router.get("/api/band/invite/qr")
def api_band_invite_qr(space: str = ""):
    """Le QR de cette adresse (SVG, fabriqué ici — pas de CDN, CSP du kiosk)."""
    url, _b = _invite_url(space or None)
    if not url:
        return JSONResponse({"error": "no band invitation for this space"}, status_code=404)
    try:
        import io
        import qrcode
        import qrcode.image.svg
        buf = io.BytesIO()
        qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=12).save(buf)
        return Response(content=buf.getvalue(), media_type="image/svg+xml")
    except ImportError:
        return JSONResponse({"error": "module qrcode absent (bridge-setup.sh)"}, status_code=501)


@router.post("/api/band/sync")
def api_band_sync():
    """Tire le roster de golem.fm et réconcilie le cache (`roster.sync`, docs/message-
    maestrium-espaces.md §7). Geste EXPLICITE — l'UI, un test, ou le démarrage du bridge.

    Ce qu'elle ne fait pas, et c'est le point : elle ne bascule pas d'espace. Le courant est
    préservé par son id ; il ne bouge que s'il a disparu du roster (repli journalisé) ou si
    c'est le seed d'avant la synchro, qui retrouve alors son vrai id — et ses prises avec.
    """
    rep = roster.sync()
    if not rep.get("ok"):
        return JSONResponse({"error": rep.get("error") or "sync impossible",
                             "status": rep.get("status")}, status_code=502)
    return rep


@router.post("/api/patches")
async def api_create(body: dict):
    preset, lane = (body or {}).get("preset"), (body or {}).get("lane")
    # UN KIT ENTIER (docs/drums-kit.md §6.7) : `drumset` au lieu de `lane` — le patch porte les N
    # éléments du groupe, pas une lane. Même geste, même modèle copie, un seul fichier.
    ds = (body or {}).get("drumset")
    if ds:
        if not isinstance(preset, dict):
            return JSONResponse({"error": "need {preset:doc, drumset:<group id>}"}, status_code=400)
        try:
            doc = P.save_kit_patch(body.get("patch_id") or body.get("name") or "drum-kit", preset, ds,
                                   name=body.get("name"), person=body.get("person"))
        except ValueError as e:
            log.warning(f"patch de kit refusé ({ds}) : {e}")             # un 400 muet ne se diagnostique pas
            return JSONResponse({"error": str(e)}, status_code=400)
        return _pushed({"ok": True, "patch": doc, "preset": preset})
    if not isinstance(preset, dict) or lane not in P.lane_ids(preset):
        log.warning(f"patch refusé : lane « {lane} » absente du preset (lanes : {P.lane_ids(preset) if isinstance(preset, dict) else '—'})")
        return JSONResponse({"error": "need {preset:doc, lane:<lane id>}"}, status_code=400)
    try:
        doc = P.create_from_lane(preset, lane, name=body.get("name"), person=body.get("person"), tags=body.get("tags"),
                                 pid=body.get("patch_id"), origin=body.get("origin"))
    except ValueError as e:
        log.warning(f"patch refusé (lane {lane}) : {e}")
        return JSONResponse({"error": str(e)}, status_code=400)
    return _pushed({"ok": True, "patch": doc, "preset": preset})


# ⚠ ROUTE À SEGMENT LIBRE : elle doit rester APRÈS toutes les routes à verbe fixe
# (/api/patches/extract…), sinon FastAPI prend le verbe pour un `pid`. C'est ce qui est arrivé à
# /api/patches/backfill-scenes, déclarée plus bas : elle répondait « need {preset, lane} ».
# Même piège que /api/backup/remote vs /api/backup/{name}.
@router.post("/api/patches/{pid}")
async def api_save(pid: str, body: dict):
    """SAUVEGARDE (automatique) d'un patch : la lane du banc devient le patch.

    Aucun morceau n'en est affecté — modèle COPIE (docs/patches.md §15). C'est pour ça que
    l'enregistrement peut être automatique : il n'engage que le catalogue.
    """
    preset, lane = (body or {}).get("preset"), (body or {}).get("lane")
    # UN PATCH DE KIT s'enregistre par son GROUPE (docs/drums-kit.md §6.7) : `lane` ne désignerait
    # qu'un élément, et les six autres seraient perdus à la première sauvegarde automatique.
    ds = (body or {}).get("drumset")
    if ds:
        if not isinstance(preset, dict):
            return JSONResponse({"error": "need {preset:doc, drumset:<group id>}"}, status_code=400)
        try:
            return _pushed({"ok": True, "patch": P.save_kit_patch(pid, preset, ds)})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
    # `lane` = un royaume historique (guitar/voice/keys) OU l'id d'une lane v2 du banc — un patch
    # essayé depuis golem.fm vit sur la lane `guitar-try` (tones_jobs._patch_try : `__patch.realm`
    # est l'id de LANE, celui auquel l'onglet s'accroche). Ce guard ne connaissait que les royaumes :
    # chaque auto-save d'un patch venu du web rendait 400 en silence, et la suppression d'une
    # scène « marchait » à l'écran sans jamais atteindre le fichier (le mainteneur, patch 1983, 2026-09-14).
    if not isinstance(preset, dict) or not (lane in P.REALM_CHAIN_KEYS or P._lane_v2(preset, lane) is not None):
        return JSONResponse({"error": "need {preset:doc, lane} — lane must be a realm or a lane id of the doc"}, status_code=400)
    try:
        return _pushed({"ok": True, "patch": P.save_patch(pid, preset, lane)})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.post("/api/patches/{pid}/play")
async def api_play(pid: str, body: dict = None):
    """JOUER UN PATCH comme un preset (docs/patches.md §6) : rappel de `patch:<id>`, le chemin de
    tout rappel — /live, le pied, les scènes et les stomps suivent. body {scene?}, défaut : la 1re scène."""
    from . import recall as recall_mod
    from .store import load_preset
    doc = P.get_patch(P._safe_id(pid))
    if not doc:
        return JSONResponse({"error": "unknown patch"}, status_code=404)
    p = load_preset(P.PATCH_PREFIX + doc["id"])
    if not p:
        return JSONResponse({"error": "this patch cannot be played"}, status_code=400)
    unbound = [L.get("bind_error") for L in p.get("lanes") or [] if L.get("bind_error")]
    if unbound:
        return JSONResponse({"error": unbound[0]}, status_code=409)
    scene = (body or {}).get("scene") or ((p.get("scenes") or [{}])[0].get("id") or "A")
    r = await recall_mod.recall_async(P.PATCH_PREFIX + doc["id"], scene)
    return {"ok": bool(r) if r is not None else True, "preset": P.PATCH_PREFIX + doc["id"], "scene": scene}


@router.post("/api/patches/{pid}/song")
async def api_make_song(pid: str, body: dict = None):
    """« ▤ MAKE A SONG » (docs/patches.md §4 bis) : un MORCEAU naît du patch entier — ses lanes, ses
    scènes, son ⚙ (backing comprise), ses pédales. C'est une CRÉATION, pas un dépôt : le patch reste intact,
    le morceau en a une copie, et on y pose ensuite l'arrangement. body {name?} ; un nom déjà pris ne remplace
    JAMAIS un morceau existant (POST /api/preset écraserait) : on suffixe."""
    import os
    from . import config as C
    from .routes_content import save_preset
    from .store import _safe_id as _sid
    doc = P.get_patch(P._safe_id(pid))
    if not doc:
        return JSONResponse({"error": "unknown patch"}, status_code=404)
    pre = P.as_preset(doc)
    if not pre:
        return JSONResponse({"error": "this patch cannot become a song"}, status_code=400)
    for k in ("__patch", "kind", "origin"):
        pre.pop(k, None)
    name = str((body or {}).get("name") or doc.get("name") or doc["id"]).replace("⛓", "").strip() or doc["id"]
    base = _sid(name) or _sid(doc["id"])
    sid, n = base, 1
    while sid in ("sandbox-try", "nouveau-preset") or os.path.exists(os.path.join(C.PRESETS_DIR, f"{sid}.json")):
        n += 1
        sid = f"{base}-{n}"
    pre.update(id=sid, name=name if n == 1 else f"{name} {n}")
    r = await save_preset(pre)
    if isinstance(r, JSONResponse):
        return r
    return {"ok": True, "id": sid, "name": pre["name"], "from_patch": doc["id"]}


@router.post("/api/patches/{pid}/deposit")
async def api_deposit(pid: str, body: dict):
    """LE DÉPÔT : copie la chaîne du patch dans la lane de N morceaux.

    ⚠ DESTRUCTIF — la lane visée est REMPLACÉE dans chaque morceau. L'UI doit l'avoir annoncé
    (« la lane guitare de 3 morceaux sera remplacée ») ; ici on exécute et on rend le compte
    rendu, scènes perdues comprises.
    """
    ids = (body or {}).get("presets")
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"error": "need {presets:[id,…]}"}, status_code=400)
    try:
        return {"ok": True, **P.deposit(pid, ids)}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.post("/api/patches/{pid}/apply")
async def api_apply(pid: str, body: dict):
    """Dépôt dans le BROUILLON du Designer : {preset: doc} -> {preset: doc muté, lane, lost_scenes}.
    Rien n'est écrit ici — le Designer enregistre son brouillon comme d'habitude."""
    preset = (body or {}).get("preset")
    if not isinstance(preset, dict):
        return JSONResponse({"error": "need {preset: doc}"}, status_code=400)
    try:
        p, realm, lost, added, skipped = P.apply_to(preset, pid, lane=(body or {}).get("lane"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    # `skipped_elements` : un patch de KIT dont un élément n'a pas de lane ici (docs/drums-kit.md
    # §6.7). Nommé à part des scènes perdues — deux natures, deux champs.
    return {"ok": True, "preset": p, "lane": realm, "lost_scenes": lost, "added_scenes": added,
            **({"skipped_elements": skipped} if skipped else {})}


@router.post("/api/patches/{pid}/meta")
async def api_meta(pid: str, body: dict):
    try:
        return _pushed({"ok": True, "patch": P.update_meta(pid, name=(body or {}).get("name"),
                                                           person=(body or {}).get("person"),
                                                           tags=(body or {}).get("tags"))})
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


@router.delete("/api/patches/{pid}")
def api_delete(pid: str):
    """Supprime le fichier — les lanes liées deviennent orphelines et jouent toujours
    leur copie inline (§9.3)."""
    return _pushed({"ok": P.delete_patch(pid)})


