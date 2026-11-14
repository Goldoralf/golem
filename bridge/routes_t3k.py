# SPDX-License-Identifier: GPL-3.0-or-later
"""Routes TONE3000 — recherche + INSTALL d'amplis/pédales depuis l'app (modal « + New »).

Proxy côté bridge (les tokens OAuth restent dans .env, jamais dans le navigateur) qui réutilise
les briques éprouvées de tools/ : t3k.py (auth/refresh/api), build-library.py (download, slugify,
style_of, layout assets/models/<creator>/<tid>_<slug>/), classify.py (marque/nom/pack).

L'install tourne en THREAD (la requête rend la main) : download des modèles cochés -> entrée
catalogue -> classification -> l'ampli apparaît dans Amps ET le tiroir Designer
(caches sur mtime). Suivi via GET /api/t3k/status.
"""
import importlib.util, json, os, sys, threading, urllib.parse

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from . import config as C
from .store import _read_json, _write_json_atomic

router = APIRouter()

_TOOLS = os.path.join(C.ROOT, "tools")


def _load(name, fname):
    import sys
    if _TOOLS not in sys.path:
        sys.path.insert(0, _TOOLS)          # build-library fait « import t3k » (voisin de tools/)
    spec = importlib.util.spec_from_file_location(name, os.path.join(_TOOLS, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_t3k = _load("golem_t3k", "t3k.py")
_t3k.IN_BRIDGE = True            # le bridge est LE propriétaire du jeton TONE3000 (audit 2026-09-13, M2)
_blib = _load("golem_buildlib", "build-library.py")
_clf = _load("golem_classify", "classify.py")

INDEX = os.path.join(C.ROOT, "library", "catalog", "tones-index.json")
MAX_MODELS = 8                      # même plafond anti-bloat que build-library
# OUTBOARD (2026-09-14) : un pack de préampli/compresseur capturé est un BALAYAGE de gain (« 40 dB »
# à « 70 dB Hard », canaux A et B) et le plafond tronquait dans l'ordre du pack — le BAE 1073MP
# perdait ses quatre prises les plus propres (A 40-60 dB) et le défaut « le plus propre » tombait sur
# 70 dB. Un modèle outboard pèse ~300 Ko : seize en font 5 Mo, le plafond n'y protège de rien.
MAX_MODELS_OUTBOARD = 16


def model_cap(gear):
    """Combien de modèles d'un pack on installe, selon sa nature."""
    return MAX_MODELS_OUTBOARD if gear == "outboard" else MAX_MODELS

# état d'install (un seul install à la fois — cas d'usage kiosk)
_ST = {"phase": "idle", "tone": None, "done": 0, "total": 0, "msg": "", "error": None}


def _installed_ids():
    d = _read_json(INDEX, {"tones": []}) or {}
    return {str(t.get("id")) for t in d.get("tones", [])}


def search_tones(q, gears="", page=1, fmt=None):
    """Recherche TONE3000 -> liste de captures normalisées (réutilisée par l'endpoint ET le créateur IA).
    Lève sur erreur d'API/auth. gears = amp_amp-cab_cab_pedal (underscore). `fmt` (nam | ir) filtre le FORMAT ;
    absent, il suit ce que golem sait jouer pour ces natures (bridge/playable.py : « outboard » -> nam seulement).
    Chaque résultat porte son format et son verdict (`playable`, `why`)."""
    from . import playable as PL
    qs = {"query": q, "page": str(page), "page_size": "24"}
    if gears:
        qs["gears"] = gears
    fmt = fmt if fmt in PL.FORMATS else PL.formats_for(gears)
    if fmt:
        qs["format"] = fmt
    st, res = _t3k.api_get("/api/v1/tones/search?" + urllib.parse.urlencode(qs))
    if st == 401:
        raise RuntimeError("auth TONE3000 expirée — relancer ./tools/t3k.py auth")
    if st != 200:
        raise RuntimeError(f"search {st}")
    have = _installed_ids()
    items = res.get("data", res if isinstance(res, list) else [])
    return [{"id": t.get("id"), "title": t.get("title") or t.get("name"),
             "gear": t.get("gear") or ",".join(t.get("gears") or []),
             "tags": [x.get("name") for x in (t.get("tags") or []) if isinstance(x, dict)] or t.get("tags") or [],
             "downloads": t.get("downloads_count", 0), "favorites": t.get("favorites_count", 0),
             "creator": (t.get("user") or {}).get("username", ""),
             "a2": bool(t.get("a2_models_count")),
             "format": t.get("format") or "nam",
             "count": t.get("irs_count") if (t.get("format") == "ir") else t.get("models_count"),
             **_verdict(t.get("gear") or ",".join(t.get("gears") or []), t.get("format")),
             "installed": str(t.get("id")) in have} for t in items]


def _verdict(gear, fmt):
    from . import playable as PL
    ok, why = PL.verdict(gear, fmt or "nam")
    return {"playable": ok, "why": why}


def _t3k_error(e):
    """Le message d'un échec TONE3000 tel que l'UI l'affiche (audit 2026-09-13, m6) : le JSON brut
    du serveur de jetons (« ✗ token endpoint 400: {"code":400,"error_code":"refresh_token_…) »)
    arrivait dans la feuille d'un bloc. Une session morte se dit en une phrase, avec le geste."""
    msg = str(e)
    # JAMAIS connecté n'est pas « expiré » (VM Windows vierge, 2026-10-16 : l'écran de chargement disait « session
    # expired » à quelqu'un qui ne s'était jamais connecté)
    if "Pas de token" in msg:
        return "TONE3000 not signed in — sign in from Settings ▸ Connect ▸ TONE3000"
    if "token endpoint" in msg or "refresh" in msg.lower() or "Pas de refresh" in msg:
        return "TONE3000 session expired — reconnect it in Settings ▸ Connect ▸ TONE3000"
    if "PUBLISHABLE_KEY" in msg:
        return "TONE3000 key missing — set it in Settings ▸ Connect ▸ TONE3000"
    return msg


@router.get("/api/t3k/search")
def t3k_search(q: str = "", gears: str = "", page: int = 1, format: str = ""):
    """Recherche TONE3000 (max 25/page). gears = amp_amp-cab_cab_pedal (underscore) ; format = nam | ir (sinon ce
    que golem sait jouer pour ces natures)."""
    try:
        return {"tones": search_tones(q, gears, page, format or None), "page": page}
    except SystemExit as e:                     # t3k sys.exit si clé absente / session morte
        return JSONResponse({"error": _t3k_error(e)}, status_code=401)
    except Exception as e:
        code = 401 if "auth" in str(e) else 502
        return JSONResponse({"error": _t3k_error(e)}, status_code=code)


# /models pagine par 10. 5 pages ne suffisaient PAS (2026-10-03) : le Big Muff 37818 a 50 modèles A1
# pile — la lecture s'arrêtait au plafond et ses captures « T-3 » standard n'étaient jamais vues.
MAX_PAGES = 15


def _page_all(path, required=True):
    """Toutes les pages d'une liste TONE3000 ({data, page, total_pages}). Lève sur la première
    page si `required`, sinon rend [] ; une page suivante qui échoue arrête la lecture."""
    out = []
    for page in range(1, MAX_PAGES + 1):
        st, res = _t3k.api_get(f"{path}&page={page}")
        if st != 200:
            if required and page == 1:
                raise RuntimeError(f"models {st}")
            break
        data = (res.get("data", res if isinstance(res, list) else []) or []) if res else []
        out.extend(data)
        if not isinstance(res, dict) or page >= int(res.get("total_pages") or 1):
            break
    return out


def _fetch_models(tid):
    """Modèles d'un tone, re-entraînements A2 EN TÊTE puis le défaut de l'API (A1+custom).
    L'endpoint /models ne renvoie que A1+custom par défaut ; les A2 (mêmes noms, ids
    distincts) sont une liste séparée derrière ?architecture=2. Lève si le défaut échoue.

    ⚠ 2026-09-14 : l'API pagine par 10 et on ne lisait que la première page — invisible tant
    que le plafond était à 8, révélé par le BAE 1073MP (12 modèles : les deux derniers manquaient,
    et le A1 « 40 dB - B » s'installait à côté de son jumeau A2). Un A1 dont un A2 porte le même
    nom est la MÊME capture ré-entraînée : on ne garde que l'A2 (politique de la migration A2)."""
    return _order_models(*_fetch_models_raw(tid))


def _fetch_models_raw(tid):
    """(A2, défaut de l'API) tels que TONE3000 les liste — sans aucun tri ni écart."""
    a2 = _page_all(f"/api/v1/models?tone_id={tid}&architecture=2", required=False)
    base = _page_all(f"/api/v1/models?tone_id={tid}")
    return a2, base


def _order_models(a2, base):
    seen_id = {m.get("id") for m in a2}
    from .rig import nam_unreadable
    if "SlimmableContainer" in nam_unreadable():
        # Machine qui NE LIT PAS l'A2 (Windows/macOS, docs/audit-2026-10-01-parite-coeurs-os.md) :
        # « A2 d'abord, jumeau A1 écarté » n'y installerait QUE des captures qui laissent passer la
        # guitare à sec. L'A1 passe en tête (le premier modèle est le défaut d'un bloc sans épingle)
        # et l'A2 jumeau RESTE derrière : un patch fait sous Linux l'épingle par son id, et sans lui
        # le résolveur retomberait sans un mot sur un autre réglage. Même règle que golem.fm.
        return [m for m in base if m.get("id") not in seen_id] + a2
    seen_name = {str(m.get("name") or "").strip().lower() for m in a2}
    return a2 + [m for m in base if m.get("id") not in seen_id
                 and str(m.get("name") or "").strip().lower() not in seen_name]


def _cap_models(models, cap):
    """Le plafond compte des RÉGLAGES (noms distincts), pas des fichiers : sur une machine qui garde
    l'A1 ET son jumeau A2, un pack de 12 réglages porte jusqu'à 24 fichiers."""
    keep, names = [], []
    for m in models:
        n = str(m.get("name") or "").strip().lower()
        if n not in names:
            if len(names) >= cap:
                continue
            names.append(n)
        keep.append(m)
    return keep


@router.get("/api/t3k/tone/{tid}")
def t3k_tone(tid: int):
    """Méta + liste des modèles d'un tone (pour cocher lesquels installer). A2 en tête."""
    st, meta = _t3k.api_get(f"/api/v1/tones/{tid}")
    if st != 200:
        return JSONResponse({"error": f"tone {st}"}, status_code=502)
    try:
        models = _fetch_models(tid)
    except Exception:
        models = []
    return {"id": tid, "title": meta.get("title"), "gear": meta.get("gear"),
            "creator": (meta.get("user") or {}).get("username", ""),
            "tags": [x.get("name") for x in (meta.get("tags") or []) if isinstance(x, dict)],
            "makes": [m.get("name") for m in (meta.get("makes") or [])],
            "downloads": meta.get("downloads_count", 0), "favorites": meta.get("favorites_count", 0),
            "format": meta.get("format") or "nam", **_verdict(meta.get("gear"), meta.get("format")),
            "installed": str(tid) in _installed_ids(),
            "models": [{"id": m.get("id"), "name": m.get("name"), "size": m.get("size"),
                        "arch": m.get("architecture_version")} for m in models if m.get("model_url")]}


def _validate_dl(path, m, fmt):
    """Intégrité (audit 2026-08-12, M-3) : T3000 ne publie pas de checksum, alors on
    vérifie ce qui est vérifiable — la MAGIE du fichier (un .nam est un JSON, une IR
    est un RIFF/WAVE) et la taille annoncée par l'API quand elle existe. Un fichier
    fabriqué livré à un parseur de plugin est exactement ce qu'on refuse ici."""
    import json as _json
    size = os.path.getsize(path)
    want = m.get("size")
    if isinstance(want, int) and want > 0 and size != want:
        raise RuntimeError(f"size mismatch ({size} vs {want} announced)")
    with open(path, "rb") as f:
        head = f.read(16)
    if fmt == "ir":
        if not (head[:4] == b"RIFF" and head[8:12] == b"WAVE"):
            raise RuntimeError("not a WAV file (bad RIFF header)")
    else:
        if not head.lstrip()[:1] == b"{":
            raise RuntimeError("not a NAM file (not JSON)")
        with open(path, encoding="utf-8", errors="strict") as f:
            _json.load(f)                        # JSON entier valide, sinon ça lève


def _download_model(m, reldir, title, fmt):
    """Un modèle TONE3000 posé dans `reldir`, vérifié. Rend son entrée de catalogue."""
    if not str(m.get("model_url") or "").startswith("https://"):
        raise RuntimeError(f"refusing non-https model_url: {str(m.get('model_url'))[:60]}")
    ext = os.path.splitext(urllib.parse.urlparse(m["model_url"]).path)[1] or (".wav" if fmt == "ir" else ".nam")
    # un re-entraînement A2 porte le MÊME nom que son jumeau A1 → suffixe anti-collision
    a2 = "-a2" if str(m.get("architecture_version")) == "2" else ""
    mname = _blib.slugify(m.get("name") or title) + a2 + ext
    rel = os.path.join(reldir, mname)
    r = _blib.download(m["model_url"], os.path.join(C.ROOT, rel))
    if str(r).startswith("err"):
        raise RuntimeError(f"download {mname}: {r}")
    try:
        _validate_dl(os.path.join(C.ROOT, rel), m, fmt)
    except Exception as ve:
        with __import__("contextlib").suppress(OSError):
            os.remove(os.path.join(C.ROOT, rel))      # jamais de fichier douteux au repos
        raise RuntimeError(f"{mname}: rejected ({ve})")
    return {"id": m.get("id"), "name": m.get("name"), "file": rel.replace(os.sep, "/"),
            "size": m.get("size"), "arch": m.get("architecture_version")}


# ── LES JUMELLES JOUABLES (2026-10-03) ─────────────────────────────────────────────────────────
# Un pack venu de golem.fm peut n'apporter que ses ré-entraînements A2 — muets hors Linux. TONE3000
# garde la capture d'origine sous le même nom : on va chercher CES jumelles-là (et seulement elles),
# on les AJOUTE à l'entrée du catalogue — l'A2 reste, un patch qui l'épingle la retrouve sous Linux —
# et resolver.playable_twin les fait jouer ici. Aucun document n'est réécrit.
def find_twins(tid, names):
    """{nom A2 -> modèle TONE3000 non-A2 du même nom} (standard avant feather/lite). Lève sur erreur API."""
    from .resolver import twin_name
    base = _page_all(f"/api/v1/models?tone_id={tid}")
    want = {twin_name(n): n for n in names if n}
    out = {}
    for m in base:
        if str(m.get("architecture_version")) == "2" or not m.get("model_url"):
            continue
        key = twin_name(m.get("name"))
        if key in want:
            exact = " ".join(str(m.get("name") or "").lower().split()) == key
            cur = out.get(want[key])
            if cur is None or (exact and not cur[1]):
                out[want[key]] = (m, exact)
    return {k: v[0] for k, v in out.items()}


def install_twins(tid, names):
    """Télécharge les jumelles non-A2 de `names` dans le pack `tid` déjà installé. Rend les noms posés."""
    d = _read_json(INDEX, {"tones": []}) or {"tones": []}
    entry = next((t for t in d.get("tones", []) if str(t.get("id")) == str(tid)), None)
    if entry is None:
        raise RuntimeError(f"tone {tid} is not installed on this rack")
    have = {m.get("id") for m in entry.get("models") or []}
    found = find_twins(tid, names)
    if not found:
        raise RuntimeError("TONE3000 has no classic version of this capture")
    twins = {n: m for n, m in found.items() if m.get("id") not in have}
    files = [m.get("file") for m in entry.get("models") or [] if m.get("file")]
    reldir = os.path.dirname(files[0]) if files else os.path.join(
        "assets", "models", entry.get("creator") or "unknown", f"{tid}_{entry.get('slug') or tid}")
    added = [_download_model(m, reldir, entry.get("title") or str(tid), entry.get("format") or "nam")
             for m in twins.values()]
    d = _read_json(INDEX, {"tones": []}) or {"tones": []}     # relu : rien d'écrit entre-temps n'est perdu
    for t in d.get("tones", []):
        if str(t.get("id")) == str(tid):
            t["models"] = (t.get("models") or []) + added
    _write_json_atomic(INDEX, d)
    return [m["name"] for m in added]


def _install_worker(tid, model_ids):
    try:
        _ST.update(phase="meta", tone=tid, done=0, total=0, msg="metadata…", error=None)
        st, meta = _t3k.api_get(f"/api/v1/tones/{tid}")
        if st != 200:
            raise RuntimeError(f"tone {st}")
        a2, base = _fetch_models_raw(tid)
        models = [m for m in _order_models(a2, base) if m.get("model_url")]
        if model_ids:
            # UN ID DEMANDÉ EST UNE RÉFÉRENCE (PC Windows neuf, 2026-11-03) : l'usine épinglait l'A1 75210 (tone 2282) ;
            # là où l'A2 se lit, _order_models écarte l'A1 qui a un jumeau A2 du même nom — le filtre ne gardait RIEN
            # (« no model selected » à chaque essai). L'écart A1/A2 est une préférence de navigation : il ne réécrit
            # pas ce qu'un preset pointe. Ce qui est demandé et existe chez TONE3000 s'installe, dans l'ordre préféré.
            want = set(model_ids)
            picked = [m for m in models if m.get("id") in want]
            got = {m.get("id") for m in picked}
            for m in a2 + base:
                if m.get("id") in want and m.get("id") not in got and m.get("model_url"):
                    picked.append(m)
                    got.add(m.get("id"))
            models = picked
        models = _cap_models(models, model_cap(meta.get("gear")))
        if not models:
            raise RuntimeError("no model selected")

        title = meta.get("title", f"tone-{tid}")
        creator = (meta.get("user") or {}).get("username", "unknown")
        gear = meta.get("gear", "amp")
        fmt = meta.get("format", "nam")
        from . import playable as PL
        ok, why = PL.verdict(gear, fmt)
        if not ok:                                  # docs/library-tones.md §7 : rien n'entre sans bloc pour le jouer
            raise RuntimeError(why)
        slug = _blib.slugify(title)
        sub = "irs" if fmt == "ir" else "models"
        reldir = os.path.join("assets", sub, creator, f"{tid}_{slug}")
        makes = [m["name"] for m in meta.get("makes", [])]
        tags = [t["name"] for t in meta.get("tags", [])]

        entry = {"id": tid, "title": title, "slug": slug, "creator": creator,
                 "url": meta.get("url", f"{_t3k.API}/tones/{tid}"),
                 "gear": gear, "format": fmt, "makes": makes, "tags": tags,
                 "style": _blib.style_of(tags + makes),
                 "downloads": meta.get("downloads_count", 0),
                 "favorites": meta.get("favorites_count", 0),
                 "source_group": "app-install", "models": []}

        _ST.update(phase="download", total=len(models), msg="download…")

        for i, m in enumerate(models):
            entry["models"].append(_download_model(m, reldir, title, fmt))
            _ST.update(done=i + 1)

        _ST.update(phase="classify", msg="classifying…")
        entry["brand"] = _clf.detect_brand(makes, title, gear)
        entry["pack"] = _clf.is_pack(makes, title, tid)
        entry["amp"] = title.strip() if entry["pack"] else _clf.clean_amp_name(makes, title, gear, entry["brand"])

        if fmt == "ir":                             # une IR longue (réverbe, écho) n'est pas un baffle : mesurée ici
            entry["ir_kind"] = PL.ir_kind_of([os.path.join(C.ROOT, m["file"]) for m in entry["models"] if m.get("file")])
        d = _read_json(INDEX, {"tones": []}) or {"tones": []}
        d["tones"] = [t for t in d["tones"] if str(t.get("id")) != str(tid)]   # ré-install = remplace
        d["tones"].append(entry)
        _write_json_atomic(INDEX, d)

        _ST.update(phase="done", msg=f"« {entry['amp']} » installed ({len(entry['models'])} model(s))")
    except Exception as e:
        _ST.update(phase="error", error=str(e), msg=str(e))


@router.post("/api/t3k/install")
async def t3k_install(body: dict):
    tid = body.get("id")
    if not tid:
        return JSONResponse({"error": "id required"}, status_code=400)
    if _ST["phase"] in ("meta", "download", "classify"):
        return JSONResponse({"error": "install already in progress"}, status_code=409)
    # passe SYNCHRONE en "meta" avant de lancer le thread : sinon un poll juste après voit encore le
    # "done"/"error" de l'install PRÉCÉDENTE (course) et croit celle-ci finie avant qu'elle démarre.
    _ST.update(phase="meta", tone=int(tid), done=0, total=0, msg="starting…", error=None)
    threading.Thread(target=_install_worker, args=(int(tid), body.get("model_ids")), daemon=True).start()
    return {"ok": True, "tone": tid}


@router.get("/api/t3k/status")
def t3k_status():
    return dict(_ST)


# ── LAN-relay QR : auth OAuth du RACK sans clavier ───────────────────────────
# Le rack affiche un QR (écran tactile) -> le téléphone (même LAN) ouvre l'URL d'autorisation
# TONE3000 -> après login, TONE3000 redirige le téléphone vers l'IP LAN du rack
# (/api/t3k/auth/callback) -> le bridge échange code+verifier (PKCE) et stocke les tokens (.env).
# ⚠ PRÉREQUIS UNE FOIS : enregistrer l'URI de callback (affichée par /auth/start) dans
#   tone3000.com -> Settings -> API Keys (redirect URIs), comme le localhost du flow desktop.
import secrets as _secrets
import socket as _socket

from fastapi.responses import HTMLResponse

_AUTH = {"verifier": None, "state": None}     # flow en cours (un seul à la fois)


def _lan_ip():
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def _redirect_uri():
    # The desktop launcher binds the bridge to loopback; a phone cannot reach its LAN IP.
    host = "127.0.0.1" if sys.platform in ("win32", "darwin") else _lan_ip()
    return f"http://{host}:{int(os.environ.get('GOLEM_PORT', '8770'))}/api/t3k/auth/callback"


# ── LE RELAIS DE golem.fm (2026-10-22 : « corrige le parcours ») ────────────────────────────────────────────────
# Un golem APPAIRÉ emprunte l'application TONE3000 de golem.fm, dont la clé et l'adresse de retour sont déjà déclarées :
# plus de clé à coller ni d'adresse à déclarer. Le golem GARDE son PKCE et fait l'échange lui-même — « un golem, une
# session » tient : golem.fm ne voit que le code, inutilisable sans le verifier. Contrat : golem.fm
# backend/app/routes/t3k_relay.py. La clé à soi reste le repli d'un golem sans golem.fm (« Advanced »).
_RELAY = {"state": None, "error": None, "running": False}
_RELAY_POLL_S, _RELAY_TTL_S = 2.0, 600


def _relay_cfg():
    """(base, jeton d'appareil) si le golem est appairé à golem.fm, sinon (None, None)."""
    from . import golemfm
    base, token = golemfm._cfg()
    return (base, token) if base and token else (None, None)


def _relay_poll(state, verifier):
    """Tâche de fond : interroge golem.fm jusqu'au code (une seule fois), puis l'échange PKCE — la page, qui sonde
    /api/t3k/auth/status, passe au vert d'elle-même."""
    import time as _time
    from . import golemfm
    deadline = _time.monotonic() + _RELAY_TTL_S
    try:
        while _time.monotonic() < deadline and _RELAY["state"] == state:
            base, token = _relay_cfg()
            if not base:
                _RELAY["error"] = "this golem is no longer paired with golem.fm — pair it, then connect again"
                return
            st, d = golemfm._req("/api/ext/t3k/relay/" + urllib.parse.quote(state, safe=""), token=token, base=base, timeout=8)
            if st == 202 or st == 0:                          # en attente, ou golem.fm injoignable un instant : on réessaie
                _time.sleep(_RELAY_POLL_S)
                continue
            if st == 410:
                _RELAY["error"] = "the sign-in expired — tap Connect and try again"
                return
            if st == 200 and isinstance(d, dict) and d.get("status") == "denied":
                _RELAY["error"] = "sign-in refused on TONE3000"
                return
            if st == 200 and isinstance(d, dict) and d.get("status") == "ready":
                try:
                    _t3k.token_request({"grant_type": "authorization_code", "code": d["code"],
                                        "redirect_uri": d["redirect_uri"], "client_id": d["client_id"],
                                        "code_verifier": verifier})
                    _RELAY["error"] = None
                except SystemExit as e:
                    _RELAY["error"] = "TONE3000 refused the sign-in — " + _t3k_error(e)
                except (KeyError, TypeError):
                    _RELAY["error"] = "golem.fm answered without a sign-in code"
                return
            _RELAY["error"] = "golem.fm could not relay the sign-in (" + str(st) + ")"
            return
        if _RELAY["state"] == state:
            _RELAY["error"] = "the sign-in expired — tap Connect and try again"
    finally:
        if _RELAY["state"] == state:
            _RELAY["running"] = False


def _qr(url):
    import qrcode
    q = qrcode.QRCode(border=2)
    q.add_data(url)
    q.make(fit=True)
    return [[1 if c else 0 for c in row] for row in q.get_matrix()]


@router.post("/api/t3k/auth/start")
async def t3k_auth_start(body: dict | None = None):
    """Démarre la connexion. Golem appairé : par le RELAIS de golem.fm (rien à déclarer). Sinon, ou `{advanced: true}` :
    la clé à soi — l'URL d'autorisation, la matrice QR et l'URI de retour à déclarer sur tone3000.com."""
    import threading
    base, token = _relay_cfg()
    if base and not (body or {}).get("advanced"):
        from . import golemfm
        verifier, challenge = _t3k.pkce()
        st, d = golemfm._req("/api/ext/t3k/relay", body={"challenge": challenge}, token=token, base=base, timeout=8)
        if st != 200 or not isinstance(d, dict) or not d.get("authorize_url") or not d.get("state"):
            why = "golem.fm is not reachable" if st == 0 else ("golem.fm cannot relay TONE3000 sign-ins yet" if st in (404, 405)
                                                              else f"golem.fm refused ({st})")
            return JSONResponse({"error": why + " — or use your own TONE3000 key (Advanced)", "relay": True}, status_code=502)
        _RELAY.update(state=d["state"], error=None, running=True)
        threading.Thread(target=_relay_poll, args=(d["state"], verifier), daemon=True, name="t3k-relay").start()
        return {"auth_url": d["authorize_url"], "relay": True, "desktop": sys.platform in ("win32", "darwin"),
                "expires_in": d.get("expires_in"), "qr": _qr(d["authorize_url"])}
    try:
        cid = _t3k.publishable_key()
    except SystemExit as e:
        # la clé publique manque (un poste fraîchement installé n'a pas le .env du rack) : on le dit en
        # anglais, avec le geste — le message de tools/t3k.py est celui de la ligne de commande
        msg = str(e)
        if "PUBLISHABLE_KEY" in msg:
            msg = ("no TONE3000 publishable key on this golem yet — paste it in the Publishable key field "
                   "(tone3000.com ▸ Settings ▸ API Keys), save 💾, then Connect")
        return JSONResponse({"error": msg}, status_code=400)
    verifier, challenge = _t3k.pkce()
    state = _t3k.b64url(_secrets.token_bytes(16))
    _AUTH.update(verifier=verifier, state=state)
    redirect = _redirect_uri()
    url = f"{_t3k.API}/api/v1/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state})
    return {"auth_url": url, "redirect_uri": redirect, "relay": False,
            "desktop": sys.platform in ("win32", "darwin"), "qr": _qr(url)}


@router.get("/api/t3k/auth/callback")
def t3k_auth_callback(code: str = "", state: str = "", error: str = ""):
    """Atterrissage du TÉLÉPHONE après le login TONE3000 — échange PKCE puis page de confirmation."""
    style = "<style>body{font:16px system-ui;background:#0d0f12;color:#e7ecf2;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}div{text-align:center}h1{font-size:42px}</style>"
    # audit 2026-11-04 (H4) : `error` et l'exception viennent de l'URL ou du serveur — échappés, jamais du HTML brut
    from html import escape as _esc
    if error or not code or state != _AUTH.get("state"):
        return HTMLResponse(style + f"<div><h1>✗</h1><p>golem: sign-in refused or the request expired.<br>{_esc(error or 'try again from the rack screen')}</p></div>", status_code=400)
    try:
        _t3k.token_request({"grant_type": "authorization_code", "code": code,
                            "redirect_uri": _redirect_uri(), "client_id": _t3k.publishable_key(),
                            "code_verifier": _AUTH.get("verifier")})
    except SystemExit as e:
        return HTMLResponse(style + f"<div><h1>✗</h1><p>The token exchange failed: {_esc(str(e))}</p></div>", status_code=502)
    _AUTH.update(verifier=None, state=None)
    return HTMLResponse(style + "<div><h1>✓</h1><p><b>golem is connected to TONE3000.</b><br>You can close this page and go back to the rack.</p></div>")


@router.get("/api/t3k/auth/status")
def t3k_auth_status():
    """Connecté ? (ping léger : 1 recherche vide). authed=False si clé/tokens absents ou expirés."""
    # `paired` : le golem passe par le relais de golem.fm (la page cache alors la clé à soi sous « Advanced ») ;
    # `relay` : la connexion en cours — en attente du téléphone, ou ce qui l'a arrêtée
    extra = {"paired": bool(_relay_cfg()[0]), "relay": {"running": _RELAY["running"], "error": _RELAY["error"]}}
    try:
        st, _ = _t3k.api_get("/api/v1/tones/search?query=&page_size=1")
        return {"authed": st == 200, **extra}
    except SystemExit as e:                     # clé absente, ou lignée morte (refresh refusé) — dit, jamais rejoué
        return {"authed": False, "reason": _t3k_error(e), **extra}
    except Exception as e:
        return {"authed": False, "reason": _t3k_error(e), **extra}


# ── LES CAPTURES D'USINE (docs/factory.md §0.1, 2026-10-13) : « Download the factory captures » ─────────────────
@router.get("/api/factory/visibility")
def factory_visibility():
    """Ce que l'utilisateur veut VOIR de l'usine, par sorte (Settings ▸ Content ▸ Factory). Masquer ne supprime rien."""
    from . import factory
    return {"show": factory.visibility(), "kinds": list(factory.VIS_KINDS)}


@router.get("/api/factory/status")
def factory_status():
    """Pour l'onglet Factory : ce que l'usine livre par sorte, et ce que l'utilisateur en a supprimé."""
    from . import factory
    cat = factory.catalog()
    return {"counts": {k: len(v) for k, v in cat.items()}, "removed": factory.removed(),
            "edited": factory.edited(), "show": factory.visibility()}


@router.post("/api/factory/restore")
def factory_restore(body: dict = None):
    from . import factory
    r = factory.restore((body or {}).get("files"))
    return {"ok": True, "placed": r.get("placed") or []}


@router.post("/api/factory/reset")
def factory_reset(body: dict = None):
    """« Reset to factory » : remplace des objets d'usine RETOUCHÉS par la version livrée (la retouche est perdue).
    Les anciennes versions intactes, elles, suivent l'usine toutes seules au démarrage (factory.seed)."""
    from . import factory
    return {"ok": True, "reset": factory.reset((body or {}).get("files")).get("reset") or []}


@router.post("/api/factory/visibility")
def factory_visibility_set(body: dict):
    from . import factory
    return {"ok": True, "show": factory.set_visibility((body or {}).get("show") or {})}


@router.get("/api/factory/captures")
def factory_captures():
    from . import factory as F
    st, _ = (200, None)
    try:
        connected = bool(_t3k.env_read().get("T3K_ACCESS_TOKEN"))
    except Exception:
        connected = False
    return {**F.captures(), "connected": connected, "download": F.download_status()}


@router.post("/api/factory/captures/download")
def factory_captures_download():
    from . import factory as F
    r = F.start_download()
    return r if r.get("ok") else JSONResponse(r, status_code=409)
