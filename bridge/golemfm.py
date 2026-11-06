# SPDX-License-Identifier: GPL-3.0-or-later
"""Client golem.fm (serveur de tablatures du user, sur le LAN) — backing tracks.

Trois responsabilités (cf. plan polished-watching-meadow) :
  1. APPAIRAGE : flux device-code — POST /api/ext/pair/start (code affiché dans l'UI
     GoleM + QR vers la page Appareils de golem.fm), puis poll de /api/ext/pair/poll
     jusqu'à l'approbation -> jeton `gmt_…` stocké dans config/integrations.json.
  2. CATALOGUE : GET /api/ext/songs (Bearer) — liste des chansons prêtes.
  3. STEMS : téléchargement des 6 mp3 séparés d'une chanson dans le CACHE local
     assets/backing/<slug>/ (+ meta.json : titre/artiste/durée/bpm + mix par défaut
     guitare muette). Thread démon + statut pollable (pattern routes_t3k._ST).

Cache-first : la lecture (bridge/backing.py) ne touche QUE le cache — golem.fm
éteint, tout rejoue. Seuls le lien d'une nouvelle chanson et la (re)synchro exigent
le serveur.
"""
import contextlib
import json
import re, os, shutil, threading, urllib.error, urllib.parse, urllib.request

from . import config as C
from .golog import get

log = get("golemfm")

STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")
# mix par défaut à la première synchro : la guitare est MUTÉE (on la joue !)
DEFAULT_MIX = {"guitar": {"mute": 1, "vol": 1.0}}

_TIMEOUT = 10           # métadonnées ; les stems ont leur propre timeout long


_refused = {"url": None}      # dernière adresse refusée (une ligne de journal par adresse, pas une par requête)


def _cfg():
    """(base, token). Audit 2026-10-15 (S2) : la règle https se vérifie ICI, là où l'adresse est LUE — pas
    seulement au POST /api/integrations, que contournent GOLEM_SERVER_URL et un integrations.json édité à la main.
    Un serveur en clair hors de cette machine / du réseau local recevrait le jeton : il vaut « non configuré »."""
    from .routes_content import _load_integrations, server_url_ok
    m = _load_integrations().get("golemfm") or {}
    base = (m.get("base_url") or "").rstrip("/")
    if base and not server_url_ok(base):
        if _refused["url"] != base:
            _refused["url"] = base
            log.warning(f"serveur golem.fm refusé : {base} n'est ni en https ni local — intégration désactivée")
        return "", ""                         # ni adresse ni jeton : rien ne peut partir vers ce serveur
    return base, m.get("token") or ""


def refused_url():
    """L'adresse configurée que _cfg refuse (pour le dire dans l'UI), ou None."""
    from .routes_content import _load_integrations, server_url_ok
    base = ((_load_integrations().get("golemfm") or {}).get("base_url") or "").rstrip("/")
    return base if base and not server_url_ok(base) else None


def error_text(body, fallback=""):
    """Le message d'un corps d'erreur de golem.fm, quelle que soit sa FORME (un seul lecteur pour tout /api/ext).
    FastAPI range tout sous `detail`, mais `detail` peut être une chaîne, un objet ({"error": "not_ready"},
    {"code", "message" | "errors"}) ou une LISTE (422 : [{loc, msg, type}]) ; `error`/`message` à la racine
    restent lus pour un corps qui ne vient pas de FastAPI. Le code machine est GARDÉ entre parenthèses quand
    il y a aussi une phrase : karaoke.fetch reconnaît « not_ready » dans le texte."""
    def _msgs(xs):
        out = []
        for x in xs:
            if isinstance(x, dict):
                t = x.get("msg") or x.get("message") or x.get("error")
                loc = [str(p) for p in (x.get("loc") or []) if p != "body"]
                if t:
                    out.append(f"{'.'.join(loc)}: {t}" if loc else str(t))
            elif x not in (None, ""):
                out.append(str(x))
        return "; ".join(out)

    def _obj(d):
        msg = d.get("message") or (_msgs(d["errors"]) if isinstance(d.get("errors"), list) else d.get("errors"))
        code = d.get("error") or d.get("code")
        if isinstance(msg, (dict, list)):
            msg = json.dumps(msg)
        if msg and code and str(code) not in str(msg):
            return f"{msg} ({code})"
        return str(msg or code or "")

    if isinstance(body, (bytes, bytearray)):
        try:
            body = json.loads(body or b"{}")
        except ValueError:
            return fallback
    if isinstance(body, str):
        return body or fallback
    if isinstance(body, list):
        return _msgs(body) or fallback
    if not isinstance(body, dict):
        return fallback
    d = body.get("detail")
    if isinstance(d, str) and d:
        return d
    if isinstance(d, dict):
        t = _obj(d)
        if t:
            return t
    if isinstance(d, list):
        t = _msgs(d)
        if t:
            return t
    return _obj(body) or fallback


def http_error_text(e):
    """Le message d'une urllib.error.HTTPError venue de golem.fm (corps lu une fois, jamais d'exception)."""
    try:
        return error_text(e.read() or b"{}", str(e))
    except Exception:
        return str(e)


def _save_token(token):
    from .routes_content import _INTEGRATIONS_PATH, _load_integrations, _write_json_atomic
    d = _load_integrations()
    d["golemfm"]["token"] = token
    # rangé AUSSI sous son serveur (panneau de dev) : une bascule vers l'autre serveur puis retour le retrouve
    cur = (d["golemfm"].get("base_url") or "").strip().rstrip("/")
    if cur:
        d["golemfm"]["servers"].setdefault(cur, {"label": "Custom", "token": ""})["token"] = token
    _write_json_atomic(_INTEGRATIONS_PATH, d)


_UNPAIRED_OK = ("/api/ext/pair/start", "/api/ext/pair/poll")


def _req(path, body=None, token=None, base=None, timeout=_TIMEOUT, raw=False, method=None):
    """GET (body=None), POST JSON, ou `method` explicite (DELETE…). Renvoie (status, data|bytes).
    Ne lève jamais : (0, str(err)) si le serveur est injoignable."""
    base = base if base is not None else _cfg()[0]
    if not base:
        return 0, "golem.fm server not configured"
    # UN GOLEM NON APPAIRÉ N'ENVOIE RIEN (README, golemfm-protocol.md) : depuis GOLEM_SERVER_URL l'adresse est TOUJOURS
    # connue (golem.fm par défaut), elle ne dit plus « appairé ». Sans jeton, seul l'appairage — un geste de
    # l'utilisateur — parle au serveur (2026-11-02)
    if not token and path not in _UNPAIRED_OK:
        return 0, "not paired"
    req = urllib.request.Request(base + path, method=method) if method else urllib.request.Request(base + path)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
            return r.status, blob if raw else json.loads(blob or b"null")
    except urllib.error.HTTPError as e:
        return e.code, http_error_text(e)
    except Exception as e:
        return 0, str(e)


def status():
    """Santé de l'intégration pour l'UI : configurée ? joignable ? authentifiée ?"""
    base, token = _cfg()
    out = {"configured": bool(base), "paired": bool(token), "reachable": False, "authed": False}
    if not base:
        bad = refused_url()
        if bad:
            out["error"] = f"{bad} refused: golem.fm must use https (plain http only on this machine or the local network)"
        return out
    if not token:                            # non appairé : on ne sonde pas golem.fm (rien ne part)
        return out
    st, _ = _req("/api/health", token=token, timeout=3)
    out["reachable"] = st == 200
    if out["reachable"]:
        st, _ = _req("/api/ext/songs", token=token, timeout=5)
        out["authed"] = st == 200
    return out


# ── appairage (device-code) ─────────────────────────────────────────────────
# Une seule demande en cours (le rack est UN appareil). L'UI lance /pair puis
# poll /pair/status ; le bridge relaie le poll vers golem.fm et sauve le jeton.
_pair = {"active": False, "code": None, "poll_token": None, "approve_url": None, "error": None}
_pair_lock = threading.Lock()


def put_ext(path, body):
    """PUT JSON authentifié vers golem.fm (rack → cloud). (status, data) ; (0, err) si injoignable."""
    base, token = _cfg()
    if not base or not token:
        return 0, "not paired"
    return _req(path, body=body, token=token, base=base, method="PUT")


def pair_start(device_name="GoleM rack"):
    base, _ = _cfg()
    if not base:
        return {"ok": False, "error": "set the golem.fm server URL first"}
    # champs `rack{}` (docs/private/exchanges/message-maestrium-installer.md §2) : version, profil, date d'installation,
    # installateur, version du catalogue — l'INSTALLATION RÉUSSIE se compte à l'approbation, une fois par
    # rack. Rien qui identifie quelqu'un (liste blanche, §5). Tous optionnels côté golem.fm.
    try:
        from . import rigstatus
        rack = rigstatus.rack_identity()
    except Exception:
        rack = {}
    st, data = _req("/api/ext/pair/start", body={"device_name": device_name, "rack": rack})
    if st != 200:
        return {"ok": False, "error": f"pair/start failed ({st}): {data}"}
    with _pair_lock:
        _pair.update(active=True, code=data["code"], poll_token=data["poll_token"],
                     approve_url=data.get("approve_url"), error=None)
    return {"ok": True, "code": data["code"], "approve_url": data.get("approve_url"),
            "expires_in": data.get("expires_in")}


def pair_status():
    """Pollé par l'UI (~2 s). Relaie le poll vers golem.fm ; à l'approbation, sauve le
    jeton (one-shot côté serveur) et clôt la demande."""
    with _pair_lock:
        if not _pair["active"]:
            return {"active": False}
        poll_token, code, url = _pair["poll_token"], _pair["code"], _pair["approve_url"]
    st, data = _req("/api/ext/pair/poll", body={"poll_token": poll_token})
    if st == 200 and isinstance(data, dict) and data.get("status") == "approved":
        _save_token(data["token"])
        try:                                            # le numéro à vie (docs/connect.md §4.5) — ou null
            from . import serial
            serial.record(data.get("serial"))
        except Exception as e:
            log.warning(f"serial de l'appairage non gardé : {e}")
        with _pair_lock:
            _pair.update(active=False, code=None, poll_token=None, approve_url=None)
        return {"active": False, "approved": True}
    # ⚠ TOUT 4xx clôt la demande, pas seulement 404 (demande golem.fm, 2026-09-09) : depuis que le
    # jeton naît AU POLL et non à l'approbation, deux polls simultanés peuvent se croiser — l'un
    # obtient le jeton, l'autre reçoit un 409 « déjà délivrée ». Traité en « pending », l'écran
    # Connect tournait alors INDÉFINIMENT sur une demande morte, en affichant « en attente ».
    # Rare, donc exactement le genre de chose qui se manifeste le soir d'une démo.
    if 400 <= st < 500:                             # expirée, consommée ailleurs, ou refusée
        why = "already claimed" if st == 409 else "expired"
        with _pair_lock:
            _pair.update(active=False, error=f"pair request {why}")
        return {"active": False, "error": why}
    return {"active": True, "code": code, "approve_url": url,
            "pending": True, "unreachable": st == 0}


# ── LA CLÉ D'UN BACKING : un slug golem.fm OU l'id d'une chanson (plan-song-sharing lot 1.5) ──
# Une backing se désignait par le slug du catalogue golem.fm, et ses stems vivaient dans le cache
# `assets/backing/<slug>/`. Depuis qu'une chanson est un `.golem` (lot 1.3), ses stems peuvent vivre DANS
# le fichier : la clé est alors l'ID de la chanson (`bs:`/`rs:`/`us:`), et les fonctions de cache ci-dessous
# (song_dir, read_meta, is_cached, local_files, save_mix) savent lire l'une ou l'autre. Les deux mondes
# cohabitent : une clé slug joue l'ancien cache, exactement comme avant.
# ⚠ Ce qui PART vers golem.fm (suivi de la tab, temps de pratique, prises) reste le SLUG golem.fm :
# `golemfm_slug(clé)` le retrouve. Un id envoyé là-bas ne serait reconnu par personne.
def is_song_key(key):
    from . import songs as _songs
    return bool(key) and bool(_songs.BS.match(str(key)))


def _golem_stems(sid):
    """{nom de stem: chemin ABSOLU} des stems d'une chanson `.golem` (cache de travail reconstruit à la
    demande), ou None si elle n'en a pas. Le nom est la `part` du manifeste (`guitar-1`, `vocals`…) : depuis le
    lot 1.6, chaque stem a SA piste dans le bus Backing (les six noms historiques gardent les leurs)."""
    from . import songs as _songs, golemfile as _G
    p = _songs.source_path(sid)                        # le golem, sinon un dossier de chansons (lue sur place)
    try:
        mt = os.stat(p).st_mtime_ns
    except OSError:
        return None
    hit = _STEMS_CACHE.get(p)
    if not (hit and hit[0] == mt and (hit[1] is None or all(os.path.isfile(x) for x in hit[1].values()))):
        hit = (mt,) + _golem_stems_read(sid, p, _songs, _G)
        _STEMS_CACHE[p] = hit
    out, takes = dict(hit[1] or {}), hit[2]
    # un stem ENREGISTRÉ sur une autre version du standard (tonalité, tempo, forme) n'est pas chargé : il jouerait
    # faux (golem-format.md §6 ter). Recalculé à CHAQUE appel — la tonalité vit aussi dans le preset (bloc
    # Standard), qui change sans que le .golem bouge ; seulement pour une chanson qui a de tels stems.
    if takes:
        off = {t["stem"] for t in _songs.stem_takes(sid) if not t["ok"]}
        if off:
            out = {k: v for k, v in out.items() if os.path.relpath(v, _songs.workdir(sid) or "").replace(os.sep, "/") not in off}
    return out or None


# les clés de la commande `load` que golem_backing.lua lit par motif (relecture reascript, 2026-10-08) : un stem
# nommé « files » dans le mix serait pris pour la liste des fichiers
_RESERVED_STEM_NAMES = {"files", "mix", "slug", "dir", "ticks", "op", "seq", "action", "stem", "mute", "vol"}
_STEMS_CACHE = {}        # chemin .golem -> (mtime_ns, stems) : effective_preset le demande souvent

# ── LE VOCABULAIRE OUVERT des stems (docs/separation.md §7, 2026-10-12) ──────────────────────────────────────────────
# Tout nom `^[a-z][a-z0-9-]{0,31}$`, 16 au plus. La FAMILLE est ce qui précède le premier tiret (`guitar-2`,
# `guitar-electric` → `guitar`), avec deux alias (`voice` = `vocals`, `keys` = `piano`) : le mix par défaut et la voix du
# karaoké se décident par famille — « guitare coupée » coupe toutes les guitares, pas seulement la piste `guitar`.
STEM_NAME_RX = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAX_STEMS = 16
FAMILY_ALIAS = {"voice": "vocals", "keys": "piano"}


def stem_family(name):
    base = str(name or "").split("-", 1)[0]
    return FAMILY_ALIAS.get(base, base)


def keep_stems(files):
    """Le vocabulaire du §7 appliqué à {nom: chemin} : un nom hors forme, ou au-delà de 16, est IGNORÉ et signalé
    (journal), jamais renommé — la chanson se joue avec le reste. Rend (gardés, ignorés)."""
    kept, ignored = {}, []
    for name, path in (files or {}).items():
        if not STEM_NAME_RX.match(str(name)) or len(kept) >= MAX_STEMS:
            ignored.append(name)
            continue
        kept[name] = path
    if ignored:
        log.warning("%d stem(s) ignored (name outside the stem vocabulary, or more than %d): %s"
                    % (len(ignored), MAX_STEMS, ", ".join(str(x)[:40] for x in ignored[:8])))
    return kept, ignored


def expand_mix(mix, stems):
    """Le mix par FAMILLE (§7) : une entrée posée sur une famille (`guitar`) vaut pour chacun de ses stems qui n'a pas la
    sienne (`guitar-1`, `guitar-electric`). Une entrée propre à un stem gagne toujours."""
    out = {k: dict(v) for k, v in (mix or {}).items() if isinstance(v, dict)}
    for s in stems or ():
        if s in out:
            continue
        fam = stem_family(s)
        if fam != s and fam in out:
            out[s] = dict(out[fam])
    return out


def _golem_stems_read(sid, p, _songs, _G):
    try:
        m = _G.read_manifest(p)
        import zipfile
        with zipfile.ZipFile(p) as zf:
            names = set(zf.namelist())
    except (OSError, _G.GolemError):
        return None, False
    want = [(arc, e) for arc, e in sorted((m.get("files") or {}).items()) if arc.startswith("stems/") and arc in names]
    takes = any(isinstance(e, dict) and isinstance(e.get("take_of"), dict) for _a, e in want)
    if not want:
        return None, takes
    w = _songs.workdir(sid)
    if not w:
        return None, takes
    out = {}
    for arc, e in want:
        part = str(e.get("part") or os.path.splitext(os.path.basename(arc))[0]).lower()
        name = re.sub(r"[^a-z0-9_-]", "-", part)[:40] or "other"
        if name in _RESERVED_STEM_NAMES:              # un nom de clé de la commande Lua ne nomme pas un stem
            name = "stem-" + name
        out.setdefault(name, os.path.join(w, arc))      # deux fichiers pour la même partie : le premier
    return out, takes


def stems_of(key):
    """Les noms des stems d'une backing : les six historiques pour le cache golem.fm et un backing local,
    ceux du manifeste pour une chanson `.golem` (lot 1.6 : un stem par instrument, sans plafond)."""
    if is_song_key(key):
        return sorted((_golem_stems(key) or {}).keys(), key=lambda n: (n not in STEMS, STEMS.index(n) if n in STEMS else 0, n))
    meta = read_meta(key) or {}
    if meta.get("local") and isinstance(meta.get("stems"), dict) and meta["stems"]:
        return list(meta["stems"].keys())            # backing local, karaoké (lot 9) : ses stems à lui
    if isinstance(meta.get("files"), dict) and meta["files"]:
        return sorted(meta["files"], key=lambda n: (n not in STEMS, STEMS.index(n) if n in STEMS else 0, n))
    return list(STEMS)


def _mix_path(sid):
    from . import songs as _songs
    return os.path.join(C.SONGS_DIR, ".mix", _songs._safe(sid) + ".json")


def golemfm_slug(key):
    """Le slug golem.fm d'une clé de backing : elle-même si c'est un slug, sinon le `song_slug` de la chanson."""
    if not is_song_key(key):
        return key
    from . import songs as _songs
    return ((_songs.load(key) or {}).get("song_slug")) or None


def backing_key(slug, band_song=None):
    """La clé à JOUER pour une backing déclarée par `slug` (et la chanson de la ligne, si elle en a une) :
    1. la chanson de la ligne, si son `.golem` porte des stems ;
    2. sinon la chanson de la bibliothèque dont le slug golem.fm est `slug`, si elle porte des stems ;
    3. sinon `slug` lui-même (l'ancien cache)."""
    from . import songs as _songs
    if band_song and _golem_stems(band_song):
        return band_song
    if slug and not is_song_key(slug):
        for d in _songs.list_all():
            if d.get("song_slug") == slug and _golem_stems(d["id"]):
                return d["id"]
    return slug


def resolve_backing_songs(songs, band_song=None):
    """La liste `backing.songs` d'un preset effectif, clés résolues. Une entrée dont la clé devient un id
    garde son slug d'origine (`from_slug`) et reçoit le titre de la chanson."""
    from . import songs as _songs
    out = []
    for i, s0 in enumerate(songs or []):
        s = dict(s0) if isinstance(s0, dict) else {"slug": s0}
        k = backing_key(s.get("slug"), band_song if i == 0 else None)
        if k and k != s.get("slug"):
            d = _songs.load(k) or {}
            s = {**s, "from_slug": s.get("slug"), "slug": k, "title": s.get("title") or d.get("title")}
        out.append(s)
    return out


# ── catalogue + cache ───────────────────────────────────────────────────────
def song_dir(slug):
    if is_song_key(slug):
        from . import songs as _songs
        return _songs.workdir(slug) or os.path.join(C.SONGS_DIR, ".work", _songs._safe(slug))
    return os.path.join(C.BACKING_DIR, slug)


def read_meta(slug):
    if is_song_key(slug):
        from . import songs as _songs
        d = _songs.load(slug)
        if not d:
            return None
        try:
            mix = json.load(open(_mix_path(slug)))
        except Exception:
            mix = None
        sh = d.get("sheet") or {}
        return {"title": d.get("title"), "artist": d.get("artist"), "bpm": sh.get("bpm"), "golem": True,
                "slug": d.get("song_slug"), **({"mix": mix} if isinstance(mix, dict) else {})}
    try:
        return json.load(open(os.path.join(song_dir(slug), "meta.json")))
    except Exception:
        return None


def is_cached(slug):
    if is_song_key(slug):
        return bool(_golem_stems(slug))
    d = song_dir(slug)
    if not os.path.isfile(os.path.join(d, "meta.json")):
        return False
    meta = read_meta(slug) or {}
    if meta.get("local"):                              # backing LOCAL : ses stems sont des samples song
        return any(os.path.isfile(os.path.join(C.ROOT, rel)) for rel in (meta.get("stems") or {}).values())
    if isinstance(meta.get("files"), dict) and meta["files"]:     # téléchargé d'après la liste de golem.fm
        return any(os.path.isfile(os.path.join(C.ROOT, rel)) for rel in meta["files"].values())
    return any(os.path.isfile(os.path.join(d, s + ".mp3")) for s in STEMS)


# ── BACKING LOCAL (docs/samples-backings.md) ──────────────────────────────────────────────────
# Un backing local (`assets/backing/local-…/`, meta `local: true`, `stems: {slot: rel}` = des samples song) se JOUE
# comme un backing golem.fm. On ne le COMPOSE plus (2026-10-08) : un backing arrive de golem.fm, ou en
# important un .golem — la création (`save_local_backing`, POST /api/backing/local) est retirée. Ceux qui existent
# restent lus ici, et se suppriment par le cache.


def list_local_backings():
    """Les backings locaux présents — `kits.backing_usage` s'en sert pour qu'un sample en service ne se supprime pas."""
    return [{"slug": s["slug"], "title": s["title"], "bpm": s.get("bpm"),
             "stems": (read_meta(s["slug"]) or {}).get("stems") or {}}
            for s in list_cache() if s.get("local")]


def local_files(slug):
    """{slot: chemin ABSOLU} des stems d'un backing local — ce que golem_backing.lua charge. Une chanson
    `.golem` passe par le même chemin : ses stems sont des fichiers explicites, pas les six mp3 d'un dossier. Un
    backing golem.fm téléchargé depuis le 2026-10-09 aussi (`meta.files`, les stems que golem.fm nomme)."""
    if is_song_key(slug):
        g = _golem_stems(slug)
        return (keep_stems(g)[0] or None) if g else g
    meta = read_meta(slug) or {}
    table = meta.get("stems") if meta.get("local") else meta.get("files")
    if not isinstance(table, dict) or not table:
        return None                                   # un ancien cache : les six mp3 du dossier, comme avant
    return keep_stems({slot: os.path.join(C.ROOT, rel) for slot, rel in table.items()
                       if os.path.isfile(os.path.join(C.ROOT, rel))})[0]


def prefer_library(listed, lib=None):
    """(liste, {id de chanson: [slugs remplacés]}) — LA CHANSON DE LA BIBLIOTHÈQUE D'ABORD (2026-10-17) : une
    entrée du cache ou du catalogue golem.fm dont la chanson `.golem` rapprochée porte ses stems s'efface devant elle
    (la carte montre le `.golem`, pas un doublon téléchargé). Jamais une ligne Vocals (`k-*`), ni un backing local, ni
    une clé de chanson. Les slugs remplacés suivent la chanson : ses presets liés s'y lisent encore."""
    lib = _lib_songs() if lib is None else lib
    keep, aliases = [], {}
    for s in listed:
        slug = s.get("slug")
        if s.get("vocals") or s.get("local") or is_song_key(slug):
            keep.append(s)
            continue
        try:
            m = lib_match(slug, {"title": s.get("title"), "artist": s.get("artist")}, lib)
            ix = _golem_index(m)
        except Exception:
            m, ix = None, None
        if m and ix and ix[2]:
            aliases.setdefault(m["id"], []).append(slug)
            continue
        keep.append(s)
    return keep, aliases


def library_backings(listed, lib=None, aliases=None):
    """Les chansons `.golem` de la bibliothèque qui ont des stems et qu'AUCUNE entrée de la liste ne représente déjà
    (2026-10-16 : « il me manque des chansons » — une chanson installée par le dossier surveillé ou depuis une
    sauvegarde n'a jamais eu d'entrée dans le cache des backings). Clé = l'id de la chanson : `stems_of`, les images
    et l'original savent déjà la servir depuis le `.golem`. Rien n'est extrait ici : sommaire et manifeste seuls."""
    lib = _lib_songs() if lib is None else lib
    # {id: est-une-ligne-Vocals} des chansons déjà représentées. Une ligne Vocals (`k-*`) ne représente QUE la ligne
    # Vocals du même titre, jamais la chanson : Annie-Dog a sa ligne Vocals ET sa chanson, chacune dans son onglet
    taken = set()
    for s in listed:
        if is_song_key(s.get("slug")):
            taken.add((s["slug"], bool(s.get("vocals"))))
            continue
        try:
            m = lib_match(s.get("slug"), {"title": s.get("title"), "artist": s.get("artist")}, lib)
        except Exception:
            m = None
        if m:
            taken.add((m["id"], bool(s.get("vocals"))))
    out = []
    for d in lib:
        ix = _golem_index(d)
        if not ix or not (ix[2] or ix[4] == "vocals"):
            continue                                     # ni stems ni ligne Vocals : rien à jouer ici (un standard…)
        path, roles, stems, tab, cat, lrc = ix
        if (d["id"], cat == "vocals") in taken:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        out.append({"slug": d["id"], "title": d.get("title") or d["id"], "artist": d.get("artist"),
                    "has_cover": "cover" in roles, "has_photo": "band" in roles
                    or bool(local_art(d["id"], {"artist": d.get("artist")}, lib).get("photo")),
                    "parts": list(tab), "duration_sec": _golem_duration(path),
                    "cached": True, "library": True, "bytes": size, "vocals": cat == "vocals",
                    # des paroles synchronisées : la chanson se CHANTE — l'onglet Vocals la montre aussi (golem.fm,
                    # 2026-10-17 : Vocals est une vue, pas une catégorie ; la tab décide toujours « song »)
                    "lyrics": lrc,
                    "aliases": (aliases or {}).get(d["id"], [])})
    return out


def _golem_duration(path):
    """La durée que déclare le manifeste (`recording.duration_ms`), en secondes, sinon None."""
    from . import golemfile as _G
    try:
        ms = ((json.loads(_G.read_member(path, "golem.json")) or {}).get("recording") or {}).get("duration_ms")
        return round(ms / 1000) if ms else None
    except Exception:
        return None


def _song_without_stems(slug, meta, lib):
    """La chanson `.golem` rapprochée de ce slug est une CHANSON (catégorie « song ») sans stems ni audio à elle."""
    try:
        ix = _golem_index(lib_match(slug, meta, lib))
    except Exception:
        return False
    return bool(ix) and ix[4] == "song" and not ix[2]


def list_cache():
    """Chansons en cache : [{slug, title, artist, duration_sec, bpm, bytes}]."""
    out = []
    if not os.path.isdir(C.BACKING_DIR):
        return out
    lib = _lib_songs()                                   # lu UNE fois pour toute la liste (les images)
    for slug in sorted(os.listdir(C.BACKING_DIR)):
        d = song_dir(slug)
        if not os.path.isdir(d):
            continue
        meta = read_meta(slug) or {}
        size = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d)
                   if os.path.isfile(os.path.join(d, f)))
        try:
            art = local_art(slug, meta, lib)
        except Exception as e:
            log.warning(f"images de {slug} : {e}")
            art = {}
        out.append({"slug": slug, "title": meta.get("title") or slug,
                    "has_cover": bool(art.get("cover")), "has_photo": bool(art.get("photo")),
                    "parts": art.get("parts") or [],
                    "artist": meta.get("artist"),
                    # les entrées `k-*` de golem.fm disent leur durée en ms
                    "duration_sec": meta.get("duration_sec") or (round(meta["duration_ms"] / 1000) if meta.get("duration_ms") else None),
                    "bpm": meta.get("bpm"), "bytes": size, "cached": is_cached(slug),
                    # `k-<n>` = la LIGNE VOCALS n°<n> de golem.fm (2026-10-16) : l'onglet Tracks ▸ Vocals
                    "vocals": slug.startswith("k-"),
                    # …mais si la CHANSON du même titre n'a pas de stems à elle (un .golem allégé : tab et paroles seules,
                    # Black), ce sont ces stems-ci qui la jouent : la carte paraît AUSSI dans Backings
                    "also_song": slug.startswith("k-") and _song_without_stems(slug, meta, lib),
                    "local": bool(meta.get("local")), "stems_n": len(meta.get("stems") or {}) if meta.get("local") else None})
    return out


def remove_cached(slug):
    d = song_dir(slug)
    if os.path.isdir(d) and os.path.dirname(d) == C.BACKING_DIR:   # jamais hors du cache
        shutil.rmtree(d)
        try:
            from . import inventory
            inventory.request_publish()          # sa carte de backing sort de golem.fm au prochain PATCH
        except Exception as e:
            log.warning(f"inventaire après retrait de {slug} : {e}")
        return True
    return False


def catalog():
    """Catalogue golem.fm fusionné avec l'état du cache. Hors-ligne : cache seul.

    ── `?tagged=1` : le catalogue suit L'ÉTOILE de golem.fm (décision 2026-08-03) ──
    Même geste que pour les standards : c'est sur golem.fm qu'on choisit ce que le groupe
    travaille, et le rack n'a pas à proposer un fond de catalogue que personne n'a trié.
    golem.fm a livré le filtre en OPT-IN pour ne pas aveugler d'un coup les racks déjà
    appairés ; on le demande donc explicitement.

    ⚠ CE FILTRE NE SUPPRIME RIEN, contrairement au miroir des standards — et la différence
    est voulue : un backing pèse ses stems (des centaines de Mo par morceau, téléchargés
    une fois), pas un objet qu'on re-rapatrie en une seconde. Un morceau DÉ-étoilé mais
    déjà en cache reste donc listé et jouable (la fusion ci-dessous s'en charge) ; son
    éviction reste un geste manuel, comme avant.
    """
    base, token = _cfg()
    cached = {c["slug"]: c for c in list_cache()}
    lib = _lib_songs()

    def _with_artist(c):
        # une entrée du cache sans artiste (les `k-*`) prend celui de sa chanson `.golem` : la carte le montre
        if not c.get("artist"):
            m = lib_match(c["slug"], None, lib)
            if m and m.get("artist"):
                return {**c, "artist": m["artist"]}
        return c

    st, data = _req("/api/ext/songs?tagged=1", token=token)
    if st != 200 or not isinstance(data, list):
        songs, aliases = prefer_library([_with_artist(c) for c in cached.values() if c.get("cached")], lib)
        songs = songs + library_backings(songs, lib, aliases)
        prepare_listens(songs)
        return {"online": False, "error": data if st else "unreachable", "songs": songs}
    songs = []
    for s in data:
        slug = s.get("slug")
        art, alb = s.get("artist") or {}, s.get("album") or {}
        try:                                             # ce que le rack sert déjà sans golem.fm (pochette du .golem…)
            mine = cached[slug] if slug in cached else local_art(slug, {"title": s.get("title"),
                                                                        "artist": art.get("name")}, lib)
        except Exception as e:
            log.warning(f"images de {slug} : {e}")
            mine = {}
        songs.append({
            "slug": slug, "title": s.get("title"),
            "artist": art.get("name"),
            "style": s.get("style"), "duration_sec": s.get("duration_sec"),
            "genres": s.get("genres") or [],             # [{family, subgenre|null}] (docs/genres.md)
            "cached": slug in cached and cached[slug]["cached"],
            # golem.fm renvoyait déjà tout ceci et on le jetait : pochette, photo d'artiste,
            # album/année, difficulté, tonalité. C'est ce qui fait une CARTE plutôt qu'une ligne.
            "album": alb.get("name"), "year": alb.get("year"),
            "has_cover": bool(alb.get("cover_path")) or bool(mine.get("has_cover", mine.get("cover"))),
            "has_photo": bool(art.get("photo_path")) or bool(mine.get("has_photo", mine.get("photo"))),
            # les instruments de la bande en pied de carte : ceux du rack, sinon ceux qu'annonce golem.fm
            "parts": mine.get("parts") or [p for p in (s.get("parts") or []) if p in PARTS],
            "difficulty": s.get("difficulty"), "key": s.get("key_detected"),
            # la carte des mesures (docs/bars-format.md §2) : le catalogue annonce sa révision ; absente =
            # golem.fm d'avant le contrat, on ne touche à rien
            **({"bars_rev": s.get("bars_rev")} if "bars_rev" in s else {}),
            # l'étiquette du .golem de cette chanson (plan-song-sharing lot 2) : null = pas de droit au fichier
            **({"golem_etag": s.get("golem_etag")} if "golem_etag" in s else {}),
        })
    known = {s["slug"] for s in songs}
    # En cache mais plus au catalogue -> on le garde, il est jouable. ⚠ SEULEMENT s'il a
    # vraiment ses stems : un dossier qui ne contient qu'une pochette (téléchargement
    # interrompu) n'est pas un morceau sur le rack. Ça se voyait à peine tant que le
    # catalogue serveur les renommait au passage ; depuis `?tagged=1` ils apparaissaient
    # en clair, avec leur slug brut en guise de titre.
    songs += [_with_artist(c) for sl, c in cached.items() if sl not in known and c.get("cached")]
    songs, aliases = prefer_library(songs, lib)
    songs += library_backings(songs, lib, aliases)
    # une carte des mesures recalée chez golem.fm (bars_rev changé) : retirée en tâche de fond
    try:
        from . import bars as _bars
        _bars.refresh_async(songs)
    except Exception as e:
        log.warning(f"bars : {e}")
    # un .golem changé chez golem.fm (golem_etag) pour une chanson que le rack porte : tiré en tâche de fond.
    # Sur la liste COMPLÈTE, pas sur ce catalogue filtré par l'étoile (golem_pull.refresh_all)
    try:
        import threading as _th
        from . import golem_pull as _gp
        _th.Thread(target=_gp.refresh_all, daemon=True, name="golem-refresh").start()
    except Exception as e:
        log.warning(f"golem : {e}")
    prepare_listens(songs)
    return {"online": True, "songs": songs}


# ── téléchargement des stems (thread démon + statut pollable) ───────────────
_ST = {"state": "idle", "slug": None, "done": 0, "total": 0, "error": None}
_dl_lock = threading.Lock()


def dl_status():
    return dict(_ST)


def _dl_worker(slug):
    base, token = _cfg()
    try:
        st, song = _req(f"/api/ext/songs/{slug}", token=token)
        if st != 200:
            raise RuntimeError(f"song meta failed ({st}): {song}")
        d = song_dir(slug)
        os.makedirs(d, exist_ok=True)
        # LES STEMS SONT CEUX QUE golem.fm NOMME (2026-10-09) : la liste `stems` [{id, path, …}] de la réponse, chaque
        # `path` demandé TEL QUEL à /api/ext/files. On ne déduit plus `<stems_dir>/<stem>.mp3` : depuis le rangement par
        # compte, un stem est `blobs/<u|b><id>/<sha[:2]>/<sha>.<ext>` et le dossier ne porte plus que stems.json (404
        # sur toute chanson migrée) — et c'était déjà faux pour un original enregistré (`guitar-1`, `.flac`). N stems,
        # leur extension ; la table {stem: fichier} va dans meta.json (`files`), le lecteur charge ces fichiers.
        todo = []
        for e in song.get("stems") or []:
            if not isinstance(e, dict):
                continue
            rel = str(e.get("path") or "").strip("/")
            name = re.sub(r"[^a-z0-9_-]", "-", str(e.get("id") or "").lower())[:40]
            if not rel or ".." in rel.split("/") or not name or name in _RESERVED_STEM_NAMES:
                continue
            ext = os.path.splitext(rel)[1].lower()
            todo.append((name, rel, ext if ext in (".mp3", ".flac", ".wav") else ".mp3"))
        if not todo:
            raise RuntimeError("song has no stems (pipeline not finished?)")
        _ST.update(total=len(todo))
        files = {}
        for i, (name, rel, ext) in enumerate(todo):
            st, blob = _req("/api/ext/files/" + urllib.parse.quote(rel), token=token, timeout=120, raw=True)
            if st == 200:
                tmp = os.path.join(d, f".{name}.tmp")
                with open(tmp, "wb") as f:
                    f.write(blob)
                os.replace(tmp, os.path.join(d, name + ext))
                files[name] = os.path.relpath(os.path.join(d, name + ext), C.ROOT)
            elif st != 404:                          # 404 = stem absent (toléré) ; le reste = erreur
                raise RuntimeError(f"stem {name} failed ({st})")
            _ST.update(done=i + 1)
        if not files:
            raise RuntimeError("no stem downloaded")
        # meta.json : cache d'affichage + mix persistant (guitare mutée par défaut)
        prev = read_meta(slug) or {}
        meta = {
            "slug": slug, "title": song.get("title"),
            "artist": (song.get("artist") or {}).get("name"),
            "duration_sec": song.get("duration_sec"),
            "bpm": song.get("tempo_score_bpm") or song.get("tempo_avg_bpm"),
            "mix": prev.get("mix") or dict(DEFAULT_MIX),
            "files": files,
        }
        tmp = os.path.join(d, ".meta.tmp")
        with open(tmp, "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(d, "meta.json"))
        # la CARTE DES MESURES vient avec les stems (docs/bars-format.md §2) — son absence n'est pas une erreur
        try:
            from . import bars as _bars
            _bars.fetch(slug)
        except Exception as e:
            log.warning(f"bars de {slug} : {e}")
        _ST.update(state="done", error=None)
        try:
            from . import inventory
            inventory.request_publish()          # sa carte de backing monte sur golem.fm (inventory.backing_cards)
        except Exception as e:
            log.warning(f"inventaire après {slug} : {e}")
    except Exception as e:
        _ST.update(state="error", error=str(e))
        log.error(f"download {slug} KO: {e}")


# ── médias d'une chanson : pochette, photo d'artiste, MIX ORIGINAL ───────────────────────────
# golem.fm sert ses fichiers via /api/ext/files/<chemin>, authentifié. Le navigateur du rack
# n'a ni le jeton ni forcément la route : on PROXIE, et on met en cache sur disque (une pochette
# ne change pas, et le rack peut être hors ligne en scène — une fois vue, elle reste).
_ASSETS = {"cover": ("album", "cover_path", ".jpg"),
           "photo": ("artist", "photo_path", ".jpg"),
           "original": (None, "source_mp3_path", ".mp3")}


# ── l'IMAGE SANS golem.fm (2026-10-16) ─────────────────────────────────────────────────────────────
# Depuis la purge de golem.fm, le catalogue ne liste plus les chansons du cache : la page Tracks ▸ Backings n'avait
# plus aucune image, alors que le rack les PORTE — la pochette dans le `.golem` de la chanson (`art/cover.jpg`), la
# photo d'artiste dans le cache d'une autre chanson du même artiste (golem.fm l'y avait posée). On sert ce qu'on a,
# hors ligne, avant de demander à golem.fm. On ne réécrit JAMAIS un `.golem` : la pochette est COPIÉE dans le cache.
_ZIP_ART = {}          # chemin du .golem -> (mtime_ns, {rôle: membre}, [noms de stems])
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
_ROLE = {"cover": "cover", "photo": "band"}          # notre `kind` -> le rôle du manifeste (golem-format.md §9)


def _lib_songs():
    """Les chansons `.golem` du golem — [] si le répertoire est illisible (une image ne casse pas une page)."""
    try:
        from . import songs as _songs
        return _songs.list_all()
    except Exception as e:
        log.warning(f"pochettes : répertoire illisible ({e})")
        return []


def _norm(t):
    from .inventory import _norm_title
    return _norm_title(t or "")


def lib_match(slug, meta=None, lib=None):
    """La chanson `.golem` du golem qui EST ce backing, ou None. Dans l'ordre : la clé elle-même (`us:…`), la chanson
    dont `song_slug` vaut ce slug, sinon le MÊME titre ET le même artiste (casse, accents, ponctuation ignorés). Une
    entrée du cache sans artiste (les `k-*` de golem.fm) se rapproche au titre seul — mais seulement s'il est UNIQUE :
    deux « Black » ne se départagent pas, on préfère pas d'image à la pochette d'une autre chanson."""
    if is_song_key(slug):
        from . import songs as _songs
        return _songs.load(slug)
    lib = _lib_songs() if lib is None else lib
    for d in lib:
        if d.get("song_slug") == slug:
            return d
    meta = (read_meta(slug) or {}) if meta is None else meta
    t, a = _norm(meta.get("title")), _norm(meta.get("artist"))
    if not t:
        return None
    hits = [d for d in lib if _norm(d.get("title")) == t and (not a or _norm(d.get("artist")) == a)]
    return hits[0] if len(hits) == 1 else None


def _zip_stems(zf, names):
    """Les noms de stems que DÉCLARE le manifeste (`files[stems/…].part`, sinon le nom du fichier) — sans rien extraire
    (`_golem_stems` reconstruit le dossier de travail : des centaines de Mo pour afficher une carte)."""
    try:
        files = (json.loads(zf.read("golem.json").decode("utf-8")) or {}).get("files") or {}
    except Exception:
        return []
    out = []
    for arc, e in sorted(files.items()) if isinstance(files, dict) else ():
        if arc.startswith("stems/") and arc in names:
            out.append(str((e.get("part") if isinstance(e, dict) else None)
                           or os.path.splitext(os.path.basename(arc))[0]).lower())
    return out


def _art_members(zf):
    """{rôle: membre} des images d'un `.golem` : le rôle que DÉCLARE le manifeste (`files[…].role`), sinon le nom
    (`art/cover.*`, `art/band.*` — un fichier d'avant les rôles, ou un manifeste qui ne les dit pas)."""
    names = set(zf.namelist())
    out = {}
    try:
        files = (json.loads(zf.read("golem.json").decode("utf-8")) or {}).get("files") or {}
    except Exception:
        files = {}
    if isinstance(files, dict):
        for name, f in sorted(files.items()):
            role = f.get("role") if isinstance(f, dict) else None
            if role in ("cover", "band") and role not in out and name in names \
                    and os.path.splitext(name)[1].lower() in _IMG_EXT:
                out[role] = name
    for role in ("cover", "band"):
        if role not in out:
            for ext in _IMG_EXT:
                if f"art/{role}{ext}" in names:
                    out[role] = f"art/{role}{ext}"
                    break
    return out


def _tab_parts(m):
    from .golemfile import tab_parts
    return tab_parts(m)


def _golem_index(d):
    """(chemin du `.golem`, {rôle: membre}, [stems], [instruments de la tab], catégorie, a des paroles) de la chanson `d`,
    sinon None. Lecture du sommaire et du manifeste
    seuls, mémorisée par date du fichier."""
    if not d or not d.get("id"):
        return None
    import zipfile
    from . import songs as _songs
    p = _songs.source_path(d["id"])
    try:
        mt = os.stat(p).st_mtime_ns
    except OSError:
        return None
    hit = _ZIP_ART.get(p)
    if not hit or hit[0] != mt:
        try:
            with zipfile.ZipFile(p) as zf:
                names = set(zf.namelist())
                roles, stems = _art_members(zf), _zip_stems(zf, names)
                try:
                    m = json.loads(zf.read("golem.json").decode("utf-8")) or {}
                except (KeyError, ValueError):
                    m = {}
                tab = _tab_parts(m)
                from .golemfile import category as _category      # la règle partagée avec golem.fm (§2.7)
                files = m.get("files") if isinstance(m.get("files"), dict) else {}
                cat = _category(names, files.keys())
                lrc = "lyrics/song.lrc" in names
        except (OSError, zipfile.BadZipFile):
            roles, stems, tab, cat, lrc = {}, [], [], None, False
        hit = _ZIP_ART[p] = (mt, roles, stems, tab, cat, lrc)
    return (p, hit[1], hit[2], hit[3], hit[4], hit[5])


def _golem_art(d, kind):
    """(chemin du `.golem`, membre) de l'image `kind` (cover|photo) de la chanson `d`, sinon None."""
    ix = _golem_index(d)
    m = ix and ix[1].get(_ROLE[kind])
    return (ix[0], m) if m else None


# LA BANDE DES INSTRUMENTS de la carte golem.fm (Catalogue ▸ `.song-card__strip`) : les instruments que joue la TAB,
# dans cet ordre (golemfile.tab_parts) ; en ligne, ceux qu'annonce golem.fm ne passent que s'ils sont de ces ids.
PARTS = ("guitar", "bass", "piano", "drums", "voice")


def _art_base(slug, kind):
    """Le chemin SANS extension de l'image en cache. Une clé de chanson n'a pas de dossier de cache à elle (son dossier
    de travail se reconstruit en entier) : la sienne vit à part, sous `songs/.work/.art/` (un dossier sans `.from`, que
    `prune_work` ne compte pas)."""
    if is_song_key(slug):
        from . import songs as _songs
        return os.path.join(C.SONGS_DIR, ".work", ".art", f"{_songs._safe(slug)}-{kind}")
    return os.path.join(C.BACKING_DIR, slug, f"art-{kind}")


def _cached_img(base):
    """L'image déjà sur disque à ce chemin (jpg, png ou webp — le type réel du fichier d'origine), sinon None."""
    for ext in _IMG_EXT:
        p = base + ext
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            return p
    return None


def _artist_songs(slug, d, meta, lib):
    """Les chansons du golem du même artiste (la rapprochée d'abord) : une photo d'artiste vaut pour tous ses morceaux."""
    artist = _norm((meta or {}).get("artist") or (d or {}).get("artist"))
    out = [d] if d else []
    if artist:
        out += [x for x in lib if x is not d and _norm(x.get("artist")) == artist]
    return out


def _sibling_cached_photo(slug, cands):
    """Une photo d'artiste déjà dans le cache d'un AUTRE morceau du même artiste (golem.fm l'y avait posée)."""
    for x in cands:
        s = x.get("song_slug")
        if s and s != slug and not is_song_key(s) and "/" not in s and "\\" not in s and s not in (".", ".."):
            p = _cached_img(os.path.join(C.BACKING_DIR, s, "art-photo"))
            if p:
                return p
    return None


def local_art(slug, meta=None, lib=None):
    """{"cover": bool, "photo": bool, "artist": str|None} — ce que le rack sait servir SANS golem.fm pour ce slug, et
    l'artiste de la chanson `.golem` rapprochée (une entrée `k-*` n'en a pas). Ne copie rien : c'est le constat que
    rend le catalogue ; la copie se fait au premier affichage (`asset`)."""
    lib = _lib_songs() if lib is None else lib
    meta = (read_meta(slug) or {}) if meta is None else meta
    d = lib_match(slug, meta, lib)
    cands = _artist_songs(slug, d, meta, lib)
    photo = bool(_cached_img(_art_base(slug, "photo"))) or any(_golem_art(x, "photo") for x in cands) \
        or bool(_sibling_cached_photo(slug, cands))
    # les instruments : ceux que joue la TABLATURE du .golem rapproché (golem.fm, 2026-10-16) — pas les stems, qu'une
    # séparation sort toujours au complet ; sans .golem ou sans tab, pas de bande
    ix = _golem_index(d)
    return {"cover": bool(_cached_img(_art_base(slug, "cover"))) or bool(_golem_art(d, "cover")),
            "photo": photo, "artist": (d or {}).get("artist"), "parts": list(ix[3]) if ix else []}


def _extract_art(slug, kind, src):
    """Copie le membre image `src` = (golem, membre) dans le cache, à son extension réelle. Le `.golem` n'est que lu."""
    from . import golemfile as _G
    path, member = src
    try:
        data = _G.read_member(path, member)
    except (_G.GolemError, OSError) as e:
        log.warning(f"image {kind} de {slug} dans {os.path.basename(path)} : {e}")
        return None
    if not data:
        return None
    ext = os.path.splitext(member)[1].lower()
    own = _art_base(slug, kind) + (".jpg" if ext == ".jpeg" else ext)
    os.makedirs(os.path.dirname(own), exist_ok=True)
    tmp = own + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, own)
    return own


def _local_asset(slug, kind):
    """L'image servie hors ligne, ou None. Pochette : le cache, puis celle du `.golem` rapproché (copiée UNE fois dans
    le cache). Photo : le cache, la photo (`band`) du `.golem` rapproché, puis celle d'un autre morceau du même
    artiste — dans son cache, sinon dans son `.golem`."""
    own = _cached_img(_art_base(slug, kind))
    if own:
        return own
    lib = _lib_songs()
    meta = read_meta(slug) or {}
    d = lib_match(slug, meta, lib)
    if kind == "cover":
        src = _golem_art(d, "cover")
        return _extract_art(slug, kind, src) if src else None
    cands = _artist_songs(slug, d, meta, lib)
    src = _golem_art(d, "photo")
    if src:
        return _extract_art(slug, kind, src)
    p = _sibling_cached_photo(slug, cands)
    if p:
        return p
    for x in cands:
        src = _golem_art(x, "photo")
        if src:
            return _extract_art(slug, kind, src)
    return None


def asset(slug, kind):
    """Chemin LOCAL du média `kind` de `slug`, téléchargé au besoin. None si indisponible. Une image se cherche
    d'abord sur le rack (`_local_asset`) : hors ligne, la page garde ses pochettes."""
    spec = _ASSETS.get(kind)
    if not spec:
        return None
    if not slug or "/" in slug or "\\" in slug or slug in (".", ".."):
        return None
    parent, field, ext = spec
    if kind in ("cover", "photo"):
        p = _local_asset(slug, kind)
        if p:
            return p
        if is_song_key(slug):
            return None                                # une chanson .golem n'a rien chez golem.fm sous cette clé
    if kind == "original" and is_song_key(slug):
        return _golem_original(slug)                   # le mix original d'une chanson de la bibliothèque : son `.golem`
    d = song_dir(slug)
    local = os.path.join(d, f"art-{kind}{ext}" if kind != "original" else "original.mp3")
    if os.path.isfile(local) and os.path.getsize(local) > 0:
        return local
    base, token = _cfg()
    st, song = _req(f"/api/ext/songs/{slug}", token=token)
    if st != 200 or not isinstance(song, dict):
        return None
    rel = ((song.get(parent) or {}) if parent else song).get(field)
    if not rel:
        return None
    st, blob = _req(f"/api/ext/files/{str(rel).strip('/')}", token=token, timeout=120, raw=True)
    if st != 200 or not blob:
        return None
    os.makedirs(d, exist_ok=True)
    tmp = local + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, local)
    return local


def _stem_paths(slug):
    """{stem: chemin} des stems sur le disque d'une chanson (clé de chanson) ou d'une entrée du cache."""
    lf = local_files(slug) or {}
    if lf:
        return {k: (v if os.path.isabs(v) else os.path.join(C.ROOT, v)) for k, v in lf.items()}
    d = song_dir(slug)
    out = {}
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else ():
        stem, ext = os.path.splitext(f)
        if ext.lower() in (".mp3", ".flac", ".wav") and stem not in ("original", "preview", "original-mix"):
            out[stem] = os.path.join(d, f)
    return out


def listen_path(slug):
    """Le fichier à ÉCOUTER pour le ▶ d'une carte Tracks (2026-10-17) : l'original de la chanson, sinon la SOMME
    de ses stems, rendue UNE fois par ffmpeg et gardée à côté (une ligne Vocals de golem.fm n'avait que ses stems, et
    golem.fm les a purgés ; golem-format.md §5 : sans mix, l'original EST la somme des stems). None si rien ne joue."""
    if not slug or "/" in slug or "\\" in slug or slug in (".", ".."):
        return None
    p = asset(slug, "original")
    if p:
        return p
    stems = _stem_paths(slug)
    if not stems:
        return None
    out = _art_base(slug, "mix") + ".mp3" if is_song_key(slug) else os.path.join(song_dir(slug), "original-mix.mp3")
    newest = max(os.path.getmtime(x) for x in stems.values())
    if os.path.isfile(out) and os.path.getmtime(out) >= newest:
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part.mp3"
    cmd = ["ffmpeg", "-loglevel", "error", "-y"]
    for x in stems.values():
        cmd += ["-i", x]
    # normalize=0 : les stems se SOMMENT (c'est l'original), un limiteur doux pour les crêtes de la somme
    cmd += ["-filter_complex", f"amix=inputs={len(stems)}:normalize=0,alimiter=limit=0.95",
            "-c:a", "libmp3lame", "-q:a", "2", tmp]
    import subprocess
    try:
        subprocess.run(cmd, check=True, timeout=300, capture_output=True)
        os.replace(tmp, out)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning(f"mix d'écoute de {slug} : {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return None
    return out


def _golem_original(sid):
    """`audio/original.*` d'une chanson `.golem`, pour l'ÉCOUTE. Le SEUL membre de l'original est copié à part
    (songs/.work/.art/<id>-original.<ext>) — extraire le dossier de travail entier (stems compris, 40 à 130 Mo) pour
    l'entendre coûtait des secondes au premier ▶ (2026-10-17). Le dossier de travail, s'il existe, sert tel quel."""
    import zipfile
    from . import songs as _songs
    src = _songs.source_path(sid)
    if not os.path.isfile(src):
        return None
    wd = os.path.join(C.SONGS_DIR, ".work", _songs._safe(sid), "audio")
    try:
        with zipfile.ZipFile(src) as zf:
            arc = next((n for n in sorted(zf.namelist())
                        if n.startswith("audio/") and os.path.splitext(os.path.basename(n))[0] == "original"), None)
            if not arc:
                return None
            ext = os.path.splitext(arc)[1].lower()
            done = os.path.join(wd, "original" + ext)
            if os.path.isfile(done) and os.path.getmtime(done) >= os.path.getmtime(src):
                return done                                # déjà extrait pour le jouer
            out = _art_base(sid, "original") + ext
            if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(src):
                return out
            os.makedirs(os.path.dirname(out), exist_ok=True)
            tmp = out + ".part"
            with zf.open(arc) as fi, open(tmp, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
            os.replace(tmp, out)
            return out
    except (OSError, zipfile.BadZipFile, KeyError) as e:
        log.warning(f"original de {sid} : {e}")
        return None


# ── la PRÉPARATION des écoutes (2026-10-17 : « un gros temps de latence avant que la chanson se lance ») ──
# Une chanson sans original (une ligne Vocals, une copie faite de stems) se mixe à la demande : ~9 s au premier ▶.
# Le catalogue les prépare donc en tâche de fond, une à la fois, jamais pendant que ça joue — le ▶ trouve le fichier.
_prep = {"busy": False}


def prepare_listens(songs):
    # ⚠ PAS pendant les tests : le fil de fond survit au test qui lit le catalogue, et ses appels à golem.fm tombaient
    # dans le test SUIVANT (test_backing_art échouait selon l'ordre — l'échec intermittent des 17-18/10)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    def needs(s):
        sl = s.get("slug")
        if not sl or not s.get("cached"):
            return False
        if is_song_key(sl):
            return False                                   # son original est extrait au ▶ (un membre, rapide)
        return not os.path.isfile(os.path.join(song_dir(sl), "original.mp3")) \
            and not os.path.isfile(os.path.join(song_dir(sl), "original-mix.mp3"))
    todo = [s["slug"] for s in songs if needs(s)]
    # une copie .golem faite de stems seuls (Céline) : mixée elle aussi
    from . import songs as _songs
    for s in songs:
        sl = s.get("slug")
        if is_song_key(sl) and s.get("library") and not os.path.isfile(_art_base(sl, "mix") + ".mp3"):
            try:
                ix = _golem_index(_songs.load(sl))
                import zipfile
                with zipfile.ZipFile(ix[0]) as zf:
                    if not any(n.startswith("audio/") for n in zf.namelist()):
                        todo.append(sl)
            except Exception:
                pass
    if not todo or _prep["busy"]:
        return

    def run():
        _prep["busy"] = True
        try:
            from .backing import _perf_recording
            from .state import state
            for sl in todo:
                if (state.backing or {}).get("playing") or _perf_recording():
                    return                                  # on reprendra au prochain catalogue
                listen_path(sl)
        except Exception as e:
            log.warning(f"préparation des écoutes : {e}")
        finally:
            _prep["busy"] = False
    threading.Thread(target=run, daemon=True, name="listen-prep").start()


def download(slug):
    """Lance le téléchargement des stems de `slug` (un seul à la fois)."""
    with _dl_lock:
        if _ST["state"] == "busy":
            return {"ok": False, "error": "download already in progress"}
        # état posé AVANT le thread : l'UI qui poll juste après voit déjà "busy"
        _ST.update(state="busy", slug=slug, done=0, total=len(STEMS), error=None)
    threading.Thread(target=_dl_worker, args=(slug,), daemon=True).start()
    return {"ok": True}


def save_mix(slug, mix):
    """Persiste le mix par stem dans meta.json (appelé par backing.py à chaque changement). Pour une chanson
    `.golem` : `songs/.mix/<id>.json`, hors du fichier — le mix change à chaque geste, et réécrire 100 Mo pour
    un fader n'a pas de sens ; c'est un réglage de CE rack."""
    if is_song_key(slug):
        from .store import _write_json_atomic
        p = _mix_path(slug)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _write_json_atomic(p, mix)
        return
    meta = read_meta(slug)
    if not meta:
        return
    meta["mix"] = mix
    d = song_dir(slug)
    tmp = os.path.join(d, ".meta.tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(d, "meta.json"))


# ── vault : push/pull des backups GoleM vers golem.fm ─────────────────────
# Upload en CORPS BRUT STREAMÉ (jamais le zip en RAM — amps/all = centaines de Mo) :
# urllib accepte un file-like en `data` si Content-Length est posé. Le sha256 est
# calculé en 1er passage local (rapide) et annoncé en query — le serveur revérifie
# en hashant le flux reçu (intégrité de bout en bout).
_PUSH = {"state": "idle", "file": None, "error": None, "result": None}
_push_lock = threading.Lock()


def _file_sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def push_status():
    return dict(_PUSH)


def _push_worker(name):
    from . import backup as _backup
    base, token = _cfg()
    try:
        path = _backup.backup_path(name)
        if not path:
            raise RuntimeError(f"unknown backup {name}")
        # kind depuis le nom (prefix-kind-ts.zip) — même parsing que list_backups ; golem.fm exige qu'il soit celui
        # du manifeste (422 sinon) et qu'il soit dans SA liste (400 sinon) : push_backup a déjà refusé le reste
        kind = _backup.kind_of_name(name)
        if kind not in _backup.VAULT_KINDS:
            raise RuntimeError(_backup.vault_refusal(name) or f"cannot infer kind from {name}")
        sha = _file_sha256(path)                     # 1er passage : hash (rapide, local)
        size = os.path.getsize(path)
        url = (base + "/api/ext/backups?filename=" + urllib.parse.quote(name)
               + "&kind=" + kind + "&sha256=" + sha)
        req = urllib.request.Request(url, method="POST")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Content-Type", "application/zip")
        req.add_header("Content-Length", str(size))
        with open(path, "rb") as f:
            req.data = f                             # streamé par urllib (Content-Length posé)
            with urllib.request.urlopen(req, timeout=600) as r:
                body = json.loads(r.read() or b"null")
        _PUSH.update(state="done", error=None, result=body)
    except urllib.error.HTTPError as e:
        detail = http_error_text(e)
        _PUSH.update(state="error", error=f"{e.code}: {detail}")
    except Exception as e:
        _PUSH.update(state="error", error=str(e))
        log.error(f"push {name} KO: {e}")


def push_backup(name):
    """Pousse backups/<name> vers le vault (un seul push à la fois, thread démon).

    ⚠ UNE SAUVEGARDE DE CHANSONS NE PART JAMAIS AU VAULT (2026-10-08, en attente de la décision) : elle
    porte des .golem complets, audio des reprises compris, et golem.fm ne garde que la CARTE d'une reprise venue
    d'un golem (song-sharing.md §2.3). Vécu le jour même : l'envoi automatique est actif sur ce rack."""
    # ⚠ ET SEULEMENT CE QUE LE VAULT ACCEPTE (golem.fm, 2026-10-09 : liste stricte presets, banks, amps, cabs, pedals,
    # all — 400 sinon). `originals` et `kits` partaient en 400 depuis le lot 8, sans que l'écran le dise.
    from . import backup as _backup
    if not all(_cfg()):                      # jamais appairé : rien ne part, et l'écran ne doit pas dire « envoyé » (audit 31/10)
        return {"ok": False, "error": "not paired with golem.fm"}
    why = _backup.vault_refusal(name)
    if why:
        return {"ok": False, "error": why}
    with _push_lock:
        if _PUSH["state"] == "busy":
            return {"ok": False, "error": "push already in progress"}
        _PUSH.update(state="busy", file=name, error=None, result=None)
    threading.Thread(target=_push_worker, args=(name,), daemon=True).start()
    return {"ok": True}


def list_remote():
    """Backups présents dans le vault. {online, backups[], bytes, max_bytes}."""
    base, token = _cfg()
    st, data = _req("/api/ext/backups", token=token)
    if st != 200 or not isinstance(data, dict):
        return {"online": False, "error": data if st else "unreachable", "backups": []}
    return {"online": True, **data}


def delete_remote(backup_id):
    """Retire une sauvegarde DU VAULT. Le serveur l'expose depuis toujours
    (`DELETE /api/ext/backups/{id}`) ; le rack ne s'en servait pas, si bien qu'aucune
    sauvegarde poussée ne pouvait plus jamais être reprise — et qu'un outil de vérification
    aurait pollué le coffre à chaque passage."""
    base, token = _cfg()
    if not base or not token:
        return {"ok": False, "error": "not paired"}
    st, data = _req(f"/api/ext/backups/{int(backup_id)}", token=token, method="DELETE")
    if st not in (200, 204):
        return {"ok": False, "error": f"delete failed ({st}): {data}"}
    return {"ok": True, "id": int(backup_id)}


def pull_backup(backup_id):
    """Télécharge un backup du vault dans backups/ (streamé, tmp+rename).
    Renvoie {ok, file} — le fichier entre dans la liste locale, restaurable
    par le pipeline d'import existant."""
    from . import backup as _backup
    base, token = _cfg()
    if not base or not token:
        return {"ok": False, "error": "not paired"}
    # métadonnées d'abord (filename + sha attendus)
    st, data = _req("/api/ext/backups", token=token)
    if st != 200:
        return {"ok": False, "error": f"list failed ({st}): {data}"}
    row = next((b for b in data.get("backups", []) if b["id"] == backup_id), None)
    if not row:
        return {"ok": False, "error": "unknown remote backup"}
    os.makedirs(_backup.BACKUP_DIR, exist_ok=True)
    dest = os.path.join(_backup.BACKUP_DIR, os.path.basename(row["filename"]))
    tmp = dest + ".pull.tmp"
    req = urllib.request.Request(base + f"/api/ext/backups/{backup_id}/download")
    req.add_header("Authorization", "Bearer " + token)
    try:
        import hashlib
        h = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
                h.update(chunk)
        if h.hexdigest() != row["sha256"]:
            os.remove(tmp)
            return {"ok": False, "error": "sha256 mismatch after download"}
        os.replace(tmp, dest)
        return {"ok": True, "file": os.path.basename(dest)}
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"ok": False, "error": str(e)}


# ── journal de pratique + liens preset↔chanson (best-effort vers le serveur) ──
def post_practice(slug, played_ms):
    """Session de jeu terminée (temps réel de transport). Thread démon, best-effort :
    serveur down = perdu, tant pis (c'est de la stat, pas de la donnée critique)."""
    def worker():
        base, token = _cfg()
        if base and token:
            st, r = _req("/api/ext/practice", body={"slug": slug, "played_ms": int(played_ms)},
                         token=token)
            if st == 200:
                log.info(f"practice: {slug} +{int(played_ms/1000)}s")
    threading.Thread(target=worker, daemon=True).start()


def push_song_links():
    """Pousse l'état COMPLET des liens chanson↔preset (dérivé de tous les presets —
    le serveur remplace tout : jamais de lien périmé). Thread démon, best-effort."""
    def worker():
        base, token = _cfg()
        if not base or not token:
            return
        from .store import load_presets
        links = []
        for p in load_presets():
            for slug in p.get("backing") or []:
                links.append({"slug": slug, "preset_id": p.get("id") or "",
                              "preset_name": p.get("name") or p.get("id") or ""})
        st, r = _req("/api/ext/song-links", body={"links": links}, token=token)
        if st == 200:
            log.info(f"song-links poussés ({len(links)})")
    threading.Thread(target=worker, daemon=True).start()


def put_bytes(path, data, token=None, timeout=180, method="PUT"):
    """Envoi d'octets BRUTS — `_req` ne sait poster que du JSON, et une tranche de piste
    n'est pas du JSON (`PUT /api/ext/recordings/{id}/tracks/{n}`, message ranger-prises §2).
    Même contrat de retour que `_req` : `(status, data|str)`, et jamais d'exception."""
    base, tok = _cfg()
    tok = token or tok
    if not base or not tok:
        return 0, "not paired"
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Authorization", "Bearer " + tok)
    req.add_header("Content-Type", "application/octet-stream")
    req.data = data
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            blob = r.read()
            return r.status, json.loads(blob or b"null")
    except urllib.error.HTTPError as e:
        detail = http_error_text(e)
        return e.code, detail
    except Exception as e:
        return 0, str(e)


def band_fetch():
    """`GET /api/ext/band` — le roster MULTI-ESPACES (contrat « un rack, N espaces » du
    2026-09-01, servi depuis le 2026-09-06) : tous les espaces dont le propriétaire du jeton
    est membre, le personnel en tête, chacun avec son roster. La réconciliation avec le cache
    local vit dans `roster.reconcile` — ici on ne fait que tirer le fil.

    Rend `(status, data)`. Non appairé -> `(0, "not paired")` : ce n'est pas une erreur, c'est
    un rack qui n'a pas encore de compte, et le cache continue de faire foi."""
    base, token = _cfg()
    if not base or not token:
        return 0, "not paired"
    return _req("/api/ext/band", token=token)


_patches_timer = None
_patches_lock = threading.Lock()


_setlist_timers = {}


def push_songs_now(ids=None):
    """Fait MONTER les chansons en attente (docs/songs.md §9.8, lot 4) — `POST /api/ext/golem/songs`.
    `ids` restreint aux chansons qu'une setlist cite (push_setlist : la chanson part AVANT la setlist qui
    la cite, sinon golem.fm en fait une pierre tombale). Synchrone ; silencieux si non appairé ; ne lève
    jamais. Rend la réponse rangée, ou None."""
    base, token = _cfg()
    if not base or not token:
        return None
    from . import songs as _songs
    docs, blocked = _songs.pending(ids)
    for b in blocked:
        log.info(f"chanson {b['id']} gardée au rack : {b['why']}")
    if not docs:
        return {"applied": [], "rejected": []}
    st, r = _req("/api/ext/golem/songs", body={"songs": [_songs.wire_song(d) for d in docs]}, token=token)
    if st == 200 and isinstance(r, dict):
        out = _songs.apply_ack(r, {d["id"]: d.get("rev") or 1 for d in docs})
        log.info(f"chansons montées : {len(out['applied'])} acceptée(s), {len(out['rejected'])} refusée(s)"
                 + "".join(f" · {x.get('id')} : {x.get('why')}" for x in (r.get("rejected") or [])))
        return out
    if st == 404:
        log.warning("push chansons : 404 sur /api/ext/golem/songs — golem.fm d'avant le 2026-09-22 ?")
    else:
        log.warning(f"push chansons : {st} {str(r)[:120]}")
    return None


_songs_timer = {"t": None}


def push_songs(delay=3.0):
    """push_songs_now, débouncé : une page chanson qu'on édite ne coûte qu'un envoi. Thread démon."""
    import threading as _th
    t = _songs_timer.get("t")
    if t is not None:
        t.cancel()
    t = _th.Timer(delay, lambda: push_songs_now())
    t.daemon = True
    _songs_timer["t"] = t
    t.start()


def push_setlist(sid, delay=5.0):
    """Pousse UNE setlist entière vers golem.fm (`POST /api/ext/golem/setlists`, docs/setlists.md
    §9.5) — miroir de push_patches : débouncé par setlist, `complete: true` (le fichier du rack
    EST la setlist), thread démon, silencieux si non appairé. Jamais appelé par le récepteur du
    push (pas d'écho) : seulement par les gestes du rack."""
    import threading as _th

    def worker():
        base, token = _cfg()
        if not base or not token:
            return
        from . import setlists as _sl
        sl = _sl.load(sid)
        if not sl:
            return
        doc = {k: v for k, v in sl.items() if k != "presets"}      # `presets` est dérivé, pas du contrat
        doc["complete"] = True
        # Une ligne ajoutée depuis le répertoire ne porte que `band_song` (docs/songs.md §9.6) : on lui
        # joint le TITRE de sa chanson, sur le fil seulement — jamais stocké, sinon il deviendrait une
        # exception du soir qui masquerait un renommage de la chanson. Sans lui, tant que golem.fm ne sait
        # pas recevoir une chanson née ici, la ligne s'affichait « — » chez eux (leur pierre tombale prend
        # ce titre pour `was`) ; après, un titre égal à celui de la chanson n'y crée pas d'exception.
        from . import songs as _songs
        doc["lines"] = _songs.wire_titles(doc.get("lines") or [])
        # §9.12 : `scopes` = les CONSIGNES d'écriture en attente ({line_id: song|line}) — elles
        # voyagent avec le miroir et sont EFFACÉES dès qu'il est accepté. Une consigne n'est pas un
        # état : la garder ferait dire à une vieille ligne où irait une retouche qu'on ne fait plus.
        # ⚠ `scopes` part TOUJOURS, même VIDE (golem.fm, 2026-09-18) : sa PRÉSENCE dit que ce rack sait
        # déclarer une portée. Sans elle, leur récepteur ne distingue pas « ce rack n'a rien retouché »
        # (garder leur état) de « ce rack ne sait pas le dire » (préserver ses valeurs comme des
        # retouches). Une capacité se LIT, elle ne se devine pas.
        sent_scopes = dict(doc.get("scopes") or {})
        doc["scopes"] = sent_scopes
        # LA CHANSON AVANT LA SETLIST QUI LA CITE (docs/songs.md §9.8.5) : sinon golem.fm reçoit une
        # référence qu'il ne sait pas résoudre et en fait une pierre tombale.
        cited = {ln.get("band_song") for ln in (doc.get("lines") or []) if ln.get("band_song")}
        if cited:
            push_songs_now(cited)
        st, r = _req("/api/ext/golem/setlists", body={"setlist": doc}, token=token)
        if st == 0 and "timed out" in str(r):          # UN retry après un timeout (redémarrage du serveur
            log.info(f"push setlist « {sid} » : timeout, un second essai")   # dev, 2026-09-17) — jamais plus :
            st, r = _req("/api/ext/golem/setlists", body={"setlist": doc}, token=token)   # le prochain geste repoussera
        if st == 200:
            if sent_scopes:
                # consignes consommées : on efface CHAMP par CHAMP (une écriture survenue pendant le
                # push garde la sienne — sinon elle partirait avec le bébé)
                cur = _sl.load(sid) or {}
                left = {}
                for lid, fields in (cur.get("scopes") or {}).items():
                    sent = sent_scopes.get(lid) or {}
                    keep = {f: s for f, s in (fields or {}).items() if sent.get(f) != s}
                    if keep:
                        left[lid] = keep
                if left:
                    cur["scopes"] = left
                else:
                    cur.pop("scopes", None)
                _sl.save(cur)
            log.info(f"setlist « {sl.get('name')} » poussée ({len(sl.get('lines') or [])} lignes)"
                     + (f" · {len(sent_scopes)} consigne(s) scope" if sent_scopes else ""))
        elif st == 404:                                # exposé depuis le 2026-09-17 : un 404 est une PANNE, pas une attente
            log.warning(f"push setlist « {sid} » : 404 sur /api/ext/golem/setlists — serveur golem.fm d'avant le 2026-09-17 ?")
        else:
            log.warning(f"push setlist « {sid} » : {st} {str(r)[:120]}")

    t = _setlist_timers.get(sid)
    if t is not None:
        t.cancel()
    t = _th.Timer(delay, worker)
    t.daemon = True
    _setlist_timers[sid] = t
    t.start()


def push_patches(delay=5.0):
    """Pousse le CATALOGUE ENTIER des patches vers golem.fm (`POST /api/ext/golem/patches`,
    docs/private/exchanges/message-maestrium-ranger-prises.md annexe 1) — débouncé : une rafale de sauvegardes
    automatiques du banc ne coûte qu'un POST (25 patches ≈ 108 Ko). Le serveur compte les docs
    malformés en `skipped` sans refuser le lot ; on le journalise, on ne le cache pas.
    Thread démon, best-effort, silencieux si non appairé."""
    global _patches_timer

    def worker():
        base, token = _cfg()
        if not base or not token:
            return
        from .patches import list_patches, refresh_deps
        # un patch v2 porte ses `deps[]` (docs/patches.md §9 bis, garantie 4) — écrites DANS le
        # fichier (le push envoie le fichier tel qu'il est stocké, garantie 5), recalculées s'il a changé
        with contextlib.suppress(Exception):
            refresh_deps()
        docs = list_patches()
        # `complete: true` : le lot EST le catalogue — ce qui n'y est plus est supprimé côté
        # web (leur réponse du 2026-09-02, question 1). On l'ANNONCE au lieu de le laisser
        # déduire : le jour où une régression pousse une liste vide, « absent = supprimé »
        # viderait le catalogue sans que personne l'ait demandé. Un drapeau se relit.
        st, r = _req("/api/ext/golem/patches", body={"patches": docs, "complete": True},
                     token=token)
        if st == 200:
            info = {k: (r or {}).get(k) for k in ("stored", "skipped", "removed")
                    if isinstance(r, dict) and (r or {}).get(k)}
            log.info(f"patches poussés ({len(docs)}" + (f" — {info}" if info else "") + ")")
        elif st not in (404,):                             # 404 = serveur pas encore à jour
            log.warning(f"patches: {st} {r}")

    with _patches_lock:
        if _patches_timer is not None:
            _patches_timer.cancel()
        _patches_timer = threading.Timer(delay, worker)
        _patches_timer.daemon = True
        _patches_timer.start()


# ═══════════════════════════════════════════════════════════════════════════
# STANDARDS — grilles d'accords synchronisées depuis golem.fm
# ═══════════════════════════════════════════════════════════════════════════
# Même patron que les backings (catalogue serveur ∪ cache local), à une différence
# près qui compte : **on ne rapatrie pas un catalogue, on rapatrie une SÉLECTION**.
# golem.fm ne renvoie que les standards TAGUÉS pour la synchro sur la webapp — c'est
# là qu'on décide ce que le groupe travaille, pas ici. Le rack, lui, n'a aucune raison
# de porter 1382 grilles dont il n'en jouera jamais dix.
#
# Un standard synchronisé = UN fichier `library/standards/synced/<slug>.json` portant
# l'objet iReal tel quel + une enveloppe `_golem` (slug, date, source). Contenu importé,
# donc hors Git (cf. .gitignore).

def _std_dir():
    from . import standards as S
    return os.path.join(S.STD_DIR, "synced")


def _std_golem_dir():
    """Le rayon des standards en .golem (plan-song-sharing lot 10, 2026-10-08 : « on passe au .golem », dans leur
    PROPRE rayon — pas la bibliothèque de chansons, qui se remplirait de grilles). Même slug que l'ancien JSON :
    les blocs Standard des presets désignent leur grille par slug."""
    from . import standards as S
    return S.GOLEM_DIR


def _std_etags():
    try:
        with open(os.path.join(_std_golem_dir(), ".etag.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _std_set_etag(slug, etag):
    from .store import _write_json_atomic
    d = _std_etags()
    if etag:
        d[slug] = etag
    else:
        d.pop(slug, None)
    os.makedirs(_std_golem_dir(), exist_ok=True)
    _write_json_atomic(os.path.join(_std_golem_dir(), ".etag.json"), d)


def standards_cache():
    """Les standards déjà sur le rack : {slug: {slug, title, synced_at}} — les .golem ET les anciens JSON."""
    out = {}
    gd = _std_golem_dir()
    if os.path.isdir(gd):
        from . import golemfile as G
        for fn in sorted(os.listdir(gd)):
            if fn.endswith(".golem") and not fn.startswith("."):
                try:
                    m = G.read_manifest(os.path.join(gd, fn))
                except (G.GolemError, OSError):
                    continue
                slug = fn[:-6]                          # <slug>.golem (standards_import_golem) ; jamais `golemfm` (§2.8)
                out[slug] = {"slug": slug, "title": m.get("title") or slug, "composer": m.get("artist"),
                             "synced_at": None, "golem": True}
    d = _std_dir()
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            continue
        env = raw.get("_golem") or {}
        slug = env.get("slug") or fn[:-5]
        out[slug] = {"slug": slug, "title": raw.get("Title") or slug,
                     "composer": raw.get("Composer"), "synced_at": env.get("synced_at")}
    return out


def standards_catalog():
    """Ce que golem.fm peut SERVIR (`/api/ext/standards`, avec la version `golem_etag`), fusionné avec ce qui est déjà sur
    le rack. Le champ `tagged` est historique (l'étoile, retirée le 2026-10-08) : la synchro ne le lit plus.

    Hors-ligne (ou endpoint pas encore livré) : on rend le cache seul et on le DIT —
    un catalogue vide sans explication ferait croire que le groupe n'a rien tagué.
    """
    base, token = _cfg()
    cached = standards_cache()
    st, data = _req("/api/ext/standards", token=token)
    if st != 200 or not isinstance(data, list):
        return {"online": False,
                "error": data if st else ("golem.fm unreachable" if base else "not configured"),
                "not_implemented": st == 404,
                "standards": [dict(c, synced=True, tagged=False) for c in cached.values()]}
    out, seen = [], set()
    for s in data:
        slug = s.get("slug") or s.get("Slug")
        if not slug:
            continue
        seen.add(slug)
        out.append({"slug": slug, "title": s.get("title") or s.get("Title"),
                    "composer": s.get("composer") or s.get("Composer"),
                    "rhythm": s.get("rhythm") or s.get("Rhythm"),
                    "key": s.get("key") or s.get("Key"),
                    "updated_at": s.get("updated_at"),
                    # la version de son .golem (golem.fm v0.49) : présente = le standard se tire en .golem
                    **({"golem_etag": s.get("golem_etag")} if s.get("golem_etag") else {}),
                    "tagged": True, "synced": slug in cached,
                    "synced_at": (cached.get(slug) or {}).get("synced_at")})
    # Présent sur le rack mais pas servi par golem.fm : il RESTE (la synchro ne retire plus rien, standards_sync).
    out += [dict(c, tagged=False, synced=True) for sl, c in cached.items() if sl not in seen]
    return {"online": True, "standards": out}


def standards_import_golem(slug, etag=None):
    """Rapatrie UN standard en .golem (GET /api/ext/standards/{slug}/golem) dans son rayon. Vérifié EN ENTIER, la
    grille (`chart/song.gsx`) doit être lisible ; l'ancien JSON du même slug est alors retiré. Même étiquette que la
    dernière fois : rien n'est retéléchargé. Rend (ok, message)."""
    import urllib.parse
    from . import golemfile as G, standards as S
    if etag and _std_etags().get(slug) == etag and os.path.isfile(os.path.join(_std_golem_dir(), slug + ".golem")):
        return True, slug                                   # déjà à cette version
    base, token = _cfg()
    if not (base and token):
        return False, "not paired with golem.fm"
    d = _std_golem_dir()
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".dl-%s.golem" % slug)
    url = "/api/ext/standards/%s/golem" % urllib.parse.quote(slug, safe="")
    work = os.path.join(d, ".plan-%s" % slug)
    try:
        # R6 (song-sharing §2.9) : le PLAN, assemblé ici ; l'archive seulement si golem.fm ne sert pas de plan
        from . import golem_pull
        try:
            out, _et = golem_pull.fetch_plan(url, None, work)
            os.replace(out, tmp)
        except golem_pull._NoPlan:
            req = urllib.request.Request(base + url)
            req.add_header("Authorization", "Bearer " + token)
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    f.write(chunk)
        except RuntimeError as e:
            return False, str(e)
        _std_place(tmp, slug)
    except urllib.error.HTTPError as e:
        return False, "HTTP %s" % e.code
    except (G.GolemError, OSError, ValueError) as e:
        return False, str(e)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
        shutil.rmtree(work, ignore_errors=True)
    _std_installed(slug, etag)
    return True, slug


def _std_place(tmp, slug):
    """Vérifie EN ENTIER un standard .golem (`tmp`) et le met à sa place, `<rayon>/<slug>.golem`, d'un coup. Lève
    GolemError / OSError / ValueError. La grille (`chart/song.gsx`) doit être lisible, en .gsx ou en iReal."""
    from . import golemfile as G, standards as S
    G.verify(tmp)
    raw = json.loads(G.read_member(tmp, "chart/song.gsx").decode("utf-8"))
    if not (S.is_gsx(raw) or raw.get("Sections")):
        raise G.GolemError("the chart is neither .gsx nor iReal")
    os.replace(tmp, os.path.join(_std_golem_dir(), slug + ".golem"))


def _std_installed(slug, etag):
    _std_set_etag(slug, etag)
    legacy = os.path.join(_std_dir(), slug + ".json")     # le .golem fait foi : l'ancien JSON s'en va
    if os.path.isfile(legacy):
        os.remove(legacy)


def standards_install_file(src, slug, etag=None):
    """Installe un standard .golem DÉJÀ sur le disque (un export de golem.fm, avec son slug et son étiquette) : les
    MÊMES contrôles et le même rangement que `standards_import_golem`, sans le téléchargement. `src` n'est pas touché
    (copié d'abord). Rend (ok, message)."""
    from . import golemfile as G
    if not slug or "/" in slug or slug.startswith("."):
        return False, "bad slug"
    d = _std_golem_dir()
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".in-%s.golem" % slug)
    try:
        shutil.copyfile(src, tmp)
        _std_place(tmp, slug)
    except (G.GolemError, OSError, ValueError) as e:
        return False, str(e)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _std_installed(slug, etag)
    return True, slug


def standards_import(slug):
    """Rapatrie UN standard tagué (l'ancien format JSON — repli pour un golem.fm sans route .golem). (ok, message)."""
    _, token = _cfg()
    st, raw = _req(f"/api/ext/standards/{slug}", token=token)
    if st != 200 or not isinstance(raw, dict):
        return False, (raw if st else "golem.fm unreachable")
    # ⚠ LES DEUX FORMATS. On refusait tout ce qui n'avait pas `Sections` (iReal) — donc les
    # six .gsx de golem.fm étaient rejetés en bloc (« 0/6 imported »). Le discriminant est la
    # FORME : `v` + `sections` en objet = .gsx ; `Sections` en tableau = iReal.
    from . import standards as _S
    if not (_S.is_gsx(raw) or raw.get("Sections")):
        return False, "ni .gsx (v + sections) ni iReal (Sections) — refusé"
    raw["_golem"] = {"slug": slug, "synced_at": _now_iso(), "source": "golem.fm"}
    d = _std_dir()
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, slug + ".json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    os.replace(tmp, p)
    return True, slug


def standards_sync():
    """MISE À JOUR des standards que le golem A DÉJÀ — plus un miroir des étoiles (2026-10-08 : l'étoile de
    golem.fm disparaît au profit de « Send to <golem> » et de l'inventaire, song-sharing.md §2.7).

    Ce que ça veut dire, et ce que ça ne veut plus dire :
      · un standard ARRIVE par le job `song-install` (`category: "standard"`, golem_pull) — jamais par cette synchro.
        `/api/ext/standards` liste ce que golem.fm PEUT servir : tout importer remplirait le golem d'un catalogue que
        personne n'a choisi ;
      · un standard que le golem a, et dont golem.fm annonce une autre version (`golem_etag`), est retéléchargé — un
        ancien JSON passe ainsi en `.golem` ;
      · RIEN N'EST RETIRÉ par la synchro. L'ancien miroir effaçait ce qui n'était plus tagué : pendant la transition
        (quelques standards encore tagués), il aurait vidé le golem du reste. Retirer est un geste au golem (🗑),
        et l'inventaire dit ensuite à golem.fm qu'il ne l'a plus.
    """
    cat = standards_catalog()
    if not cat.get("online"):
        return {"ok": False, "error": cat.get("error"), "not_implemented": cat.get("not_implemented"),
                "imported": 0, "updated": 0, "removed": 0, "failed": []}
    have, etags = standards_cache(), _std_etags()
    todo = [s for s in cat["standards"]
            if s.get("golem_etag") and s["slug"] in have and etags.get(s["slug"]) != s["golem_etag"]]
    ok, failed = 0, []
    for s in todo:
        good, msg = standards_import_golem(s["slug"], s["golem_etag"])
        if good:
            ok += 1
        else:
            failed.append({"slug": s["slug"], "error": msg})
    from . import standards as S
    S.invalidate()
    if ok:
        from . import inventory
        inventory.request_publish()
    return {"ok": True, "imported": ok, "updated": ok, "checked": len(have), "tagged": len(have),
            "removed": 0, "removed_slugs": [], "failed": failed}


def standards_remove(slug, _quiet=False):
    gone = False
    for p, d in ((os.path.join(_std_dir(), slug + ".json"), _std_dir()),
                 (os.path.join(_std_golem_dir(), slug + ".golem"), _std_golem_dir())):
        if os.path.isfile(p) and os.path.dirname(p) == d:
            os.remove(p)
            gone = True
    if gone:
        if os.path.isdir(_std_golem_dir()):
            _std_set_etag(slug, None)
        if not _quiet:
            from . import standards as S, inventory
            S.invalidate()
            inventory.request_publish()          # retirer est un geste AU GOLEM : l'inventaire le dit à golem.fm (§2.7)
    return gone


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
