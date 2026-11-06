# SPDX-License-Identifier: GPL-3.0-or-later
"""Karaoké au rack — docs/karaoke.md (lot 1, 2026-10-06).

golem.fm décide, le rack exécute : il reçoit une chanson (id stable + révision), son mix et le patch
voix, joue les stems ET traite le micro sur la même sortie, et renvoie son horloge. Ce n'est PAS un
bloc : un preset VOLATIL (id réservé `karaoke`, presets/.karaoke.json, store.KARAOKE_ID) chargé
uniquement par commande, sur le WS de follow (bridge/follow_uplink.py).

Ce qui est réutilisé, pas dupliqué :
  - le Backing Track joue les stems (les 6 emplacements du vocabulaire de stems de golem.fm, mix par stem — bridge/backing.py) ;
    un karaoké est un backing de slug `k-<id>` dans le même cache assets/backing/ ;
  - la lane voix est bâtie par le chemin de patch-try (tones_jobs._trial_preset), mais rappelée comme
    un preset de JEU — pas la sandbox ;
  - le rappel est do_recall : le mode, ses vetos, le pied, /live le voient comme un preset.

Toutes les commandes passent par UN worker (une file) : le WS ne bloque jamais, et deux karaoke-load
rapprochés s'exécutent dans l'ordre. Le préchargement a son propre fil (il ne touche pas à Reaper).
Les trames montantes passent par une boîte d'envoi que follow_uplink vide.
"""
import collections
import json
import os
import queue
import re
import threading
import time
import urllib.request

from . import config as C
from . import golemfm
from .golog import get
from .state import state

log = get("karaoke")

CACHE_MAX = 50                 # ~2 Go (2026-10-06) ; éviction des moins récemment JOUÉES
READY_TIMEOUT_S = 25           # stems chargés dans Reaper (rebuild + settle 0,7 s + items)
PROGRESS_EVERY_S = 1.0         # la progression d'un téléchargement : au plus une trame par seconde
VOCALS = ("off", "guide", "full")

_ctl = None                    # BackingControl, injecté par app.py
_outbox = collections.deque(maxlen=200)
_recent = collections.deque(maxlen=50)      # les dernières trames, pour GET /api/karaoke (diagnostic)
_out_lock = threading.Lock()
_cmds = queue.Queue()
_worker = None
_fetch_locks = collections.defaultdict(threading.Lock)

# L'état du karaoké monté. `prev` = le preset d'avant le PREMIER load (rappelé à karaoke-stop).
_cur = {"active": False, "id": None, "rev": None, "slug": None, "voice_key": None, "voice": None,
        "mix": None, "prev": None, "ends": None, "stopping": False, "prefetched": None, "local": False,
        "voice_in": None, "voice_src": None, "lyrics_from": None}
_mix_sent = {"mix": None}      # le dernier mix annoncé dans une trame pos (on ne le répète pas)


def init(ctl):
    global _ctl, _worker
    _ctl = ctl
    if _worker is None:
        _worker = threading.Thread(target=_work, name="karaoke", daemon=True)
        _worker.start()


# ── boîte d'envoi (rack -> golem.fm) ─────────────────────────────────────────────────────────
def emit(frame, local=False):
    """`local` : une commande injectée au rack (POST /api/karaoke/cmd, vérification sans golem.fm) —
    sa trame reste ici, jamais envoyée à golem.fm (ce serait un karaoké que leur écran ne connaît pas)."""
    with _out_lock:
        _recent.append({**frame, "at": round(time.time(), 2), **({"local": True} if local else {})})
        if not local:
            _outbox.append(frame)


def status():
    return {"active": _cur["active"], "id": _cur["id"], "rev": _cur["rev"], "slug": _cur["slug"],
            "voice": _cur["voice"], "mix": _cur["mix"], "prev": _cur["prev"], "local": _cur["local"],
            "recent": list(_recent)}


def drain():
    with _out_lock:
        out = list(_outbox)
        _outbox.clear()
    return out


def _reply(msg, **kw):
    frame = {"type": "karaoke", **kw}
    if msg.get("req") is not None:
        frame["req"] = msg["req"]
    emit(frame, local=bool(msg.get("_local")))


# ── l'état lu par follow_uplink ──────────────────────────────────────────────────────────────
def active():
    return bool(_cur["active"])


def pos_fields(slug):
    """Ce que la trame pos gagne pendant un karaoké : `src`, `id`, et le mix quand il a changé."""
    if not _cur["active"] or slug != _cur["slug"] or _cur["local"]:
        return {}
    out = {"src": "karaoke", "id": _cur["id"]}
    # la COPIE DU RACK joue (`golem: {id}`, 2026-10-17) : son slug golem.fm est None (une chanson née sur le rack n'en a
    # pas) — la page voyait une position pour « aucune chanson » et coupait aussitôt (pause < 0,5 s après play). La
    # trame porte donc le slug de la LIGNE, celui que golem.fm connaît (`k-<id>`), comme quand le cache joue
    if golemfm.is_song_key(slug) and not golemfm.golemfm_slug(slug):
        out["slug"] = slug_of(_cur["id"])
    if _cur["mix"] != _mix_sent["mix"]:
        _mix_sent["mix"] = _cur["mix"]
        out["mix"] = _cur["mix"]
    return out


# ── identités et cache ───────────────────────────────────────────────────────────────────────
_SAFE = re.compile(r"[^a-z0-9_\-]+")


def slug_of(kid):
    """Le slug de cache d'un karaoké : préfixe `k-`, jamais en collision avec une chanson du catalogue."""
    s = _SAFE.sub("-", str(kid).lower()).strip("-")
    if not s:
        raise ValueError("karaoke id required")
    return "k-" + s[:80]


def _meta_path(slug):
    return os.path.join(golemfm.song_dir(slug), "meta.json")


def _write_meta(slug, meta):
    d = golemfm.song_dir(slug)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, ".meta.tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _meta_path(slug))


def is_cached(kid, rev=None):
    slug = slug_of(kid)
    if not golemfm.is_cached(slug):
        return False
    meta = golemfm.read_meta(slug) or {}
    return rev is None or meta.get("rev") == rev


def _local_golem(k):
    """L'id de la chanson du rack à jouer DEPUIS SON .golem, ou None (lot 9, contrat golem.fm 2026-10-08) : la ROUTE
    /api/ext/karaoke/{id} porte `song_id` (le golem_id) et `golem_etag` — pas la trame karaoke-load. Le rack joue son
    .golem s'il a cette chanson, avec des stems, À LA MÊME VERSION (l'étiquette notée au tirage). Sinon il télécharge
    comme avant — jamais une autre version que celle que golem.fm annonce."""
    sid, et = str((k or {}).get("song_id") or ""), (k or {}).get("golem_etag")
    if not sid or not et or not golemfm.is_song_key(sid):
        return None
    from . import songs as _songs, golem_pull
    d = _songs.load(sid)
    if not d or not golemfm.local_files(sid):
        return None
    return sid if golem_pull.etags().get(d.get("song_slug") or "") == et else None


NOT_HERE = "not on this golem"
NO_STEMS = "this song has no stems on this golem"


def _golem_target(msg, kid):
    """`golem: {id}` de karaoke-load (contrat golem.fm 2026-10-17) : jouer la COPIE DU RACK d'une ligne Vocals dont
    golem.fm n'a plus les stems (purge M8). Rend (où, clé, paroles) — où ∈ "golem" (le .golem joue) | "cache" (une
    entrée du cache de backings joue) —, None si la trame ne le demande pas ; lève RuntimeError (la raison est dite à
    golem.fm). Aucune version : c'est la copie du rack, il joue ce qu'il a. Jamais de téléchargement.
      - une clé de chanson (bs:/rs:/us:/ct:) : son .golem, s'il porte des stems ; sinon (un .golem allégé : tab et
        paroles seules, Black) le cache `k-<id>` de cette ligne s'il a les siens — les paroles restent celles du .golem ;
      - bk:<empreinte> : l'entrée du cache de backings de même id (inventory.backing_id)."""
    g = msg.get("golem")
    if not isinstance(g, dict):
        return None
    gid = str(g.get("id") or "")
    if golemfm.is_song_key(gid):
        from . import songs as _songs
        if not _songs.load(gid) or not os.path.exists(_songs.source_path(gid)):
            raise RuntimeError(NOT_HERE)
        if golemfm.local_files(gid):
            return "golem", gid, gid
        if kid and is_cached(kid):
            return "cache", slug_of(kid), gid
        raise RuntimeError(NO_STEMS)
    if gid.startswith("bk:"):
        from .inventory import backing_id
        for e in golemfm.list_cache():
            if e.get("cached") and backing_id(e["slug"]) == gid:
                return "cache", e["slug"], None
        raise RuntimeError(NOT_HERE)
    raise RuntimeError(NOT_HERE)


def _kmeta(slug):
    """Le meta d'un karaoké : celui du cache k-<id>, ou, pour une chanson jouée depuis son .golem, recomposé
    (ses stems, ceux de la voix — « vocals » ou « voice-N » —, son titre, son mix de CE rack)."""
    if not golemfm.is_song_key(slug):
        return golemfm.read_meta(slug) or {}
    from . import songs as _songs
    files = golemfm.local_files(slug) or {}
    d = _songs.load(slug) or {}
    m = golemfm.read_meta(slug) or {}
    return {"stems": files, "voice_stems": [n for n in files if golemfm.stem_family(n) == "vocals"],
            "title": d.get("title"), "mix": m.get("mix") or {}, "golem": True}


def _touch_played(slug):
    if golemfm.is_song_key(slug):                  # un .golem n'a pas de fiche de cache à dater
        return
    meta = golemfm.read_meta(slug) or {}
    meta["played_at"] = time.time()
    _write_meta(slug, meta)


def evict(keep=()):
    """Garde les CACHE_MAX karaokés les plus récemment JOUÉS (un jamais joué compte à son téléchargement).
    `keep` : jamais évincés (la chanson courante, celle qu'on vient de précharger)."""
    import shutil
    try:
        names = [n for n in os.listdir(C.BACKING_DIR) if n.startswith("k-")]
    except OSError:
        return []
    rows = []
    for n in names:
        m = golemfm.read_meta(n) or {}
        rows.append((float(m.get("played_at") or m.get("fetched_at") or 0), n))
    rows.sort(reverse=True)
    gone = []
    for _t, n in rows[CACHE_MAX:]:
        if n in keep:
            continue
        shutil.rmtree(golemfm.song_dir(n), ignore_errors=True)
        gone.append(n)
    if gone:
        log.info(f"cache karaoké : {len(gone)} chanson(s) évincée(s) (plafond {CACHE_MAX})")
    return gone


def _get_bytes(url, token, base):
    """Un stem : chemin relatif à golem.fm (jeton de l'appareil) ou URL absolue (jeton seulement si
    elle est chez golem.fm — une URL signée d'un stockage tiers ne le reçoit jamais)."""
    if url.startswith("/"):
        st, blob = golemfm._req(url, token=token, timeout=180, raw=True)
        if st != 200:
            raise RuntimeError(f"HTTP {st}")
        return blob
    headers = {"Authorization": "Bearer " + token} if base and url.startswith(base) and token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=180) as r:
        return r.read()


# Q2 (golem.fm, 2026-10-08) : un morceau PRÊTÉ ne sert aucun fichier à un autre compte. La route le dit
# (`stems_denied`) ; le golem joue SON .golem s'il l'a à la même version (R2), sinon il le dit — pas un échec HTTP.
LENT = "lent song: drop your own .golem on this golem"


def fetch(kid, rev=None, msg=None):
    """Télécharge les stems d'un karaoké dans assets/backing/k-<id>/ (GET /api/ext/karaoke/{id}).
    Rend le meta. Lève RuntimeError avec la raison (dite à golem.fm)."""
    slug = slug_of(kid)
    with _fetch_locks[slug]:
        if is_cached(kid, rev):
            return golemfm.read_meta(slug)
        base, token = golemfm._cfg()
        if not base or not token:
            raise RuntimeError("this rack is not paired with golem.fm")
        st, info = golemfm._req(f"/api/ext/karaoke/{urllib.request.quote(str(kid), safe='')}", token=token)
        if st == 404 and "not_ready" in str(info):
            raise RuntimeError(f"song {kid} is not ready yet on golem.fm (stems still separating)")
        if st != 200 or not isinstance(info, dict):
            raise RuntimeError(f"song {kid} not found on golem.fm ({st})")
        if info.get("stems_denied"):
            raise RuntimeError(LENT)
        # ── TOUS LES STEMS, sous leur NOM et leur EXTENSION (plan-song-sharing lot 9, 2026-10-08) ──
        # Un original enregistré a un stem PAR PARTIE (`guitar-1`, `voice-1`…, un .flac possible) : on ne garde plus
        # les six seuls (le reste était JETÉ, le morceau jouait incomplet) et on ne renomme plus tout en .mp3.
        # Le bus Backing les joue en fichiers explicites (meta `local` + `stems`, comme un backing local).
        stems = {}
        for k, v in (info.get("stems") or {}).items():
            name = re.sub(r"[^a-z0-9_-]", "-", str(k).lower())[:40]
            if name and isinstance(v, str) and v and name not in golemfm._RESERVED_STEM_NAMES:
                stems[name] = v
        if not stems:
            raise RuntimeError(f"song {kid} has no stems yet")
        d = golemfm.song_dir(slug)
        os.makedirs(d, exist_ok=True)
        files = {}
        done_b, last = 0, 0.0
        for i, (stem, url) in enumerate(stems.items()):
            try:
                blob = _get_bytes(url, token, base)
            except Exception as e:
                raise RuntimeError(f"stem {stem} failed ({e})")
            ext = os.path.splitext(url.split("?")[0])[1].lower()
            ext = ext if ext in (".mp3", ".flac", ".wav") else ".mp3"
            tmp = os.path.join(d, f".{stem}.tmp")
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, os.path.join(d, f"{stem}{ext}"))
            files[stem] = C.rel(os.path.join(d, f"{stem}{ext}"))
            done_b += len(blob)
            now = time.time()
            if msg is not None and (now - last >= PROGRESS_EVERY_S or i == len(stems) - 1):
                last = now
                _reply(msg, state="fetching", id=kid, rev=info.get("rev", rev),
                       done_mb=round(done_b / 1e6, 1), stems_done=i + 1, stems_total=len(stems))
        prev = golemfm.read_meta(slug) or {}
        # `voice_stems` (golem.fm, 2026-10-08) : les stems qui font la VOIX — ["vocals"] pour un morceau séparé,
        # ["voice-1", …] pour un original enregistré. Absent (golem.fm d'avant) : « vocals ».
        vs = [re.sub(r"[^a-z0-9_-]", "-", str(x).lower())[:40] for x in (info.get("voice_stems") or ["vocals"])]
        meta = {"slug": slug, "karaoke_id": str(kid), "rev": info.get("rev", rev),
                "local": True, "stems": files, "voice_stems": [x for x in vs if x in files],
                "title": info.get("title"), "duration_ms": info.get("duration_ms"),
                "mix": prev.get("mix") or {}, "fetched_at": time.time(), "played_at": prev.get("played_at")}
        _write_meta(slug, meta)
        evict(keep={slug, _cur["slug"]})
        return meta


# ── le mix : le vocabulaire de golem.fm -> le mix du backing ─────────────────────────────────
def _stems_of(meta):
    """(stems de la chanson, stems de la voix) d'après son meta — les six et « vocals » pour un karaoké d'avant."""
    st = list(((meta or {}).get("stems") or {}).keys()) or list(golemfm.STEMS)
    vs = [x for x in ((meta or {}).get("voice_stems") or ["vocals"]) if x in st]
    return st, vs


def backing_mix(mix, meta=None):
    """`{vocals: off|guide|full, guide_db, muted[]}` -> `{stem: {mute, vol}}` (vol = D_VOL linéaire).
    L'état COMPLET : chaque stem de LA CHANSON est réglé, rien n'est hérité d'un mix précédent. `vocals` vise
    les stems de la VOIX (`voice_stems`, lot 9) — `voice-1`, `voice-2` d'un original enregistré, pas seulement
    `vocals` : sinon sa voix jouait en entier."""
    mix = mix or {}
    vocals = mix.get("vocals", "full")
    if vocals not in VOCALS:
        raise ValueError(f"vocals must be one of {', '.join(VOCALS)}")
    db = max(-60.0, min(0.0, float(mix.get("guide_db", -14))))
    stems, voice = _stems_of(meta)
    muted = {s for s in (mix.get("muted") or []) if s in stems}
    out = {s: {"mute": 1 if s in muted else 0, "vol": 1.0} for s in stems}
    for v in voice:
        if vocals == "off":
            out[v]["mute"] = 1
        elif vocals == "guide":
            out[v]["vol"] = round(10 ** (db / 20.0), 4)
    return out


def public_mix(mix, meta=None):
    mix = mix or {}
    stems, _voice = _stems_of(meta)
    out = {"vocals": mix.get("vocals", "full"), "muted": sorted(s for s in (mix.get("muted") or []) if s in stems)}
    if out["vocals"] == "guide":
        out["guide_db"] = max(-60.0, min(0.0, float(mix.get("guide_db", -14))))
    return out


# ── la voix : un patch résolu par sha (la version exacte) ou par id (installé sur le rack) ───
def _voice_lane_preset(voice):
    """(preset | None, statut, raison). Le preset porte la lane voix (chemin de patch-try) ; None = pas de
    voix montée (statut 'none' | 'refused', avec la raison) — le karaoké se pose alors sur le preset joué
    (_base_preset). Les stems jouent dans tous les cas."""
    from . import modes, patches as P, tones_jobs
    empty = None
    if not voice:
        return empty, "none", None
    if not modes.allows("voice", state.mode):
        return empty, "none", f"the {(state.mode or {}).get('name') or 'current'} mode keeps the voice off"
    pid, sha = str(voice.get("patch_id") or "").strip(), str(voice.get("sha") or "").strip()
    job = {"role": "voice", "patch_id": pid or None}
    # LE RACK FAIT AUTORITÉ SUR SA VERSION (essai réel de 2026-10-06) : le patch installé ici est
    # celui qu'on règle au Designer ; la copie de golem.fm peut avoir des semaines de retard (1983-2 :
    # dernière synchro le 09-21). Le sha ne sert que si le rack n'a pas ce patch.
    doc = P.get_patch(P._safe_id(pid)) if pid else None
    if doc:
        job["_doc"] = doc
        _cur["voice_src"] = "rack"
    elif sha:
        job["sha"] = sha
        _cur["voice_src"] = "golem.fm"
    elif pid:
        return empty, "refused", f"patch {pid} is not on this rack"
    else:
        return empty, "refused", "voice needs a patch_id or a sha"
    try:
        preset, _role, lane, scenes, _settled, missing = tones_jobs._trial_preset(job, ".karaoke-voice.tmp")
    except Exception as e:
        return empty, ("none" if "no voice input" in str(e) else "refused"), str(e)
    lane = dict(lane, id="voice-karaoke", key="voice-karaoke", name=lane.get("name") or "Voice")
    # l'ENTRÉE ne vient pas du patch (un patch ne la porte pas) : c'est l'entrée « voice » de la CARTE
    # (Soundcard ▸ rôles des entrées, patches.bind_input). On la dit dans `ready` : un micro branché
    # ailleurs se voit sans ouvrir le rack.
    _cur["voice_in"] = lane.get("in_sel")
    preset = dict(preset, lanes=[lane])
    preset.pop("__patch", None)                    # pas un brouillon de patch : un preset de jeu
    if missing:
        log.warning(f"patch voix : {len(missing)} bloc(s) sans capture — {[m.get('block') for m in missing]}")
    return preset, "mounted", None


def _base_preset():
    """SANS VOIX, le karaoké se pose PAR-DESSUS le preset que le rack jouait (2026-10-06) : un rig n'existe
    pas sans lane (rig.normalize : « preset sans 'paths' », vu au rack réel), et la guitare du musicien
    continue de sonner pendant que les stems jouent. Le preset d'AVANT le karaoké, pas le karaoké lui-même.
    Rend (preset, scène) ou (None, None)."""
    from .store import load_preset, KARAOKE_ID
    pid, scene = (_cur["prev"] if _cur["active"] and _cur["prev"] else (state.preset_id, state.scene_id))
    if not pid or pid == KARAOKE_ID:
        return None, None
    p = load_preset(pid)
    if not p:
        return None, None
    p = json.loads(json.dumps(p))
    p.pop("__patch", None)
    scenes = [str(x.get("id")) for x in p.get("scenes") or []]
    return p, (scene if scene in scenes else (scenes[0] if scenes else "A"))


def _write_preset(preset):
    from .store import _write_json_atomic, KARAOKE_FILE
    _write_json_atomic(os.path.join(C.PRESETS_DIR, KARAOKE_FILE), preset)


def _refusal():
    """Ce qui refuse TOUT le karaoké (le reste refuse seulement la voix)."""
    from . import modes
    mode = state.mode or {}
    if (mode.get("ui") or {}).get("locked"):
        return f"the rack is in {mode.get('name') or 'a locked'} mode"
    if (state.perf or {}).get("recording"):
        return "a take is recording"
    if not modes.allows("backing", state.mode):
        return f"the {mode.get('name') or 'current'} mode keeps backing tracks off"
    if _ctl is None:
        return "the backing player is not ready"
    return None


def _wait_loaded(slug, timeout=READY_TIMEOUT_S):
    t0 = time.time()
    while time.time() - t0 < timeout:
        b = state.backing or {}
        if b.get("present") and b.get("slug") == slug:
            return True
        time.sleep(0.1)
    return False


# ── les commandes ────────────────────────────────────────────────────────────────────────────
def handle(msg):
    """Point d'entrée du WS (follow_uplink) : ne bloque jamais — tout part dans le worker, sauf le
    préchargement qui a son propre fil (téléchargement seul)."""
    cmd = msg.get("cmd")
    if cmd == "karaoke-prefetch":
        threading.Thread(target=_safe, args=(_prefetch, msg), daemon=True).start()
    elif cmd == "karaoke-queue":
        _safe(_queue_cmd, msg)                       # mémoire seule : rien à attendre
    elif cmd in ("karaoke-load", "karaoke-mix", "karaoke-stop"):
        _cmds.put(msg)
    else:
        return False
    return True


# ── LA FILE DE SOIRÉE (lot 5 Vocals, plan-vocals-library.md §6 ter) ─────────────────────────────────────
# golem.fm en est propriétaire et l'envoie EN ÉTAT COMPLET ; tant qu'il est connecté, c'est lui qui enchaîne (karaoke-load
# sur `ended`). Le rack ne la garde que pour SURVIVRE À UNE COUPURE : sur `ended` hors ligne, il charge la suivante lui-même,
# et à la reconnexion il dit où il en est ({"type":"karaoke","state":"queue","pos"}). Mémoire seule.
QUEUE_MAX = 500
_queue = {"items": [], "pos": -1, "mix": None, "voice": None}


def _queue_cmd(msg):
    items = msg.get("items")
    if not isinstance(items, list) or len(items) > QUEUE_MAX:
        raise ValueError("items: a list of at most %d songs" % QUEUE_MAX)
    keep = []
    for it in items:
        if not isinstance(it, dict):
            continue
        k = it.get("karaoke") if isinstance(it.get("karaoke"), dict) else None
        g = it.get("golem") if isinstance(it.get("golem"), dict) else None
        if (k and k.get("id")) or (g and g.get("id")):
            keep.append({**({"karaoke": {"id": k["id"], **({"rev": k["rev"]} if k.get("rev") is not None else {})}} if k and k.get("id") else {}),
                         **({"golem": {"id": str(g["id"])}} if g and g.get("id") else {})})
    try:
        pos = int(msg.get("pos") if msg.get("pos") is not None else -1)
    except (TypeError, ValueError):
        pos = -1
    _queue.update(items=keep, pos=pos if -1 <= pos < len(keep) else -1, mix=msg.get("mix"), voice=msg.get("voice"))
    _reply(msg, state="queue", pos=_queue["pos"], n=len(keep))
    _prepare_next()


def _item_id(it):
    return (it.get("karaoke") or {}).get("id") or (it.get("golem") or {}).get("id")


def _queue_at(kid):
    """La chanson chargée est dans la file : sa position devient la position courante."""
    for i, it in enumerate(_queue["items"]):
        if str(_item_id(it)) == str(kid):
            _queue["pos"] = i
            return


def _next_item():
    i = _queue["pos"] + 1
    return _queue["items"][i] if 0 <= i < len(_queue["items"]) else None


def _prepare_next():
    """La suivante PRÊTE pendant que celle-ci joue : une ligne golem.fm se télécharge (karaoke-prefetch), une copie du
    golem s'extrait (ses stems sortent du .golem). Du disque seulement — jamais pendant une prise (2026-10-17 :
    exception assumée à « pas de traitement pendant qu'on joue », sinon chaque chanson attend quelques secondes)."""
    nxt = _next_item()
    if not nxt:
        return
    from .backing import _perf_recording
    if _perf_recording():
        return
    msg = {"cmd": "karaoke-prefetch", **nxt, "_local": True}
    threading.Thread(target=_safe, args=(_prefetch, msg), daemon=True).start()


def _advance_offline():
    """`ended` sans golem.fm : le rack charge la suivante lui-même (golem.fm, connecté, le fait de son côté)."""
    from .follow_uplink import LINKED
    if LINKED.get("ok"):
        return False
    nxt = _next_item()
    if not nxt:
        return False
    _queue["pos"] += 1
    _cmds.put({"cmd": "karaoke-load", **nxt, "mix": _queue["mix"], "voice": _queue["voice"]})
    log.info(f"karaoké : golem.fm absent — la suivante de la file ({_item_id(nxt)}) part toute seule")
    return True


def on_reconnect():
    """Le lien est revenu : dire où en est la file (golem.fm recale sa barre)."""
    if _queue["items"]:
        emit({"type": "karaoke", "state": "queue", "pos": _queue["pos"], "n": len(_queue["items"])})


def _work():
    while True:
        msg = _cmds.get()
        fn = {"karaoke-load": _load, "karaoke-mix": _mix, "karaoke-stop": _stop}[msg["cmd"]]
        _safe(fn, msg)


def _safe(fn, msg):
    try:
        fn(msg)
    except Exception as e:
        log.warning(f"{msg.get('cmd')} refusé : {e}")
        k = msg.get("karaoke") or {}
        _reply(msg, state="refused", id=k.get("id") or _cur["id"], why=str(e))


def _ids(msg):
    """(id des réponses, rev, golem seul ?) — la ligne golem.fm (`karaoke.id`), sinon la COPIE DU GOLEM seule
    (`golem.id` sans `karaoke`, lot 5 Vocals, plan-vocals-library.md §6 ter : une chanson d'un dossier karaoké qui n'a
    pas de ligne chez golem.fm). L'id des réponses, des trames pos et lyrics est alors cet id golem."""
    k = msg.get("karaoke") if isinstance(msg.get("karaoke"), dict) else {}
    if k.get("id"):
        return k["id"], k.get("rev"), False
    g = msg.get("golem") if isinstance(msg.get("golem"), dict) else {}
    if g.get("id"):
        return str(g["id"]), None, True
    raise ValueError("karaoke.id or golem.id required")


def _prefetch(msg):
    kid, rev, alone = _ids(msg)
    if alone or isinstance(msg.get("golem"), dict):
        # la copie du golem : rien à télécharger — ses stems sont extraits d'avance (la chanson suivante démarre net)
        target = _golem_target(msg, None if alone else kid)
        if target and target[0] == "golem":
            golemfm.local_files(target[1])
        _reply(msg, state="cached", id=kid)
        return
    meta = fetch(kid, rev, msg)
    _cur["prefetched"] = slug_of(kid)
    _reply(msg, state="cached", id=kid, rev=meta.get("rev", rev))


def _load(msg):
    from . import recall as recall_mod
    from .store import KARAOKE_ID
    kid, rev, alone = _ids(msg)
    why = _refusal()
    if why:
        raise RuntimeError(why)
    mix = msg.get("mix") or {}
    backing_mix(mix)                                # vérifie le mix AVANT tout téléchargement
    # la COPIE DU RACK, désignée par golem.fm (`golem: {id}`) : ni route, ni téléchargement, ni version
    # golem seul : jamais le cache k-<id> (l'id est celui d'une chanson du golem, pas d'une ligne golem.fm)
    target = _golem_target(msg, None if alone else kid)
    lyrics_from = target[2] if target else None
    # le lien vers une chanson est sur la ROUTE : on la lit (un petit JSON) avant de télécharger quoi que ce soit.
    # Déjà en cache k-<id> à cette révision : rien à lire, le cache joue comme avant (et hors ligne).
    local = target[1] if target and target[0] == "golem" else None
    if target is None and not is_cached(kid, rev):
        base, token = golemfm._cfg()
        if base and token:
            st, info = golemfm._req(f"/api/ext/karaoke/{urllib.request.quote(str(kid), safe='')}", token=token)
            if st == 200 and isinstance(info, dict):
                local = _local_golem(info)
    if target and target[0] == "cache":
        # une entrée du CACHE joue (bk:, ou les stems d'une ligne Vocals pour un .golem qui n'en a pas) : rien à tirer
        slug = target[1]
        meta = golemfm.read_meta(slug) or {}
        bmix = backing_mix(mix, meta)
        meta = dict(meta, mix=bmix, played_at=time.time())
        _write_meta(slug, meta)
        log.info(f"karaoké {kid} : joué depuis le cache {slug} (copie du rack)")
    elif local:
        # la chanson est SUR LE RACK, à la version annoncée : son .golem joue, rien n'est téléchargé
        slug = local
        meta = _kmeta(local)
        bmix = backing_mix(mix, meta)
        golemfm.save_mix(local, bmix)
        meta = dict(meta, mix=bmix)
        log.info(f"karaoké {kid} : joué depuis le .golem de {local}")
    else:
        slug = slug_of(kid)
        if not is_cached(kid, rev):
            _reply(msg, state="fetching", id=kid, rev=rev, done_mb=0, stems_done=0)
        meta = fetch(kid, rev, msg)
        meta = golemfm.read_meta(slug) or meta
        bmix = backing_mix(mix, meta)               # les stems de CETTE chanson (lot 9)
        meta = dict(meta, mix=bmix, played_at=time.time())
        _write_meta(slug, meta)
    # PAS DE VOIX SÉPARÉE, PAS DE KARAOKÉ (2026-10-17 : « ce n'est pas la promesse du golem ») — jamais un mix
    # complet joué en ersatz ; golem.fm le dit sur la carte et propose la séparation
    if not _stems_of(meta)[1]:
        raise RuntimeError("no vocal stem")
    _queue_at(kid)
    # LA CHANSON QUI JOUE DÉJÀ (lot 5, point 3) : golem.fm renvoie karaoke-load sur `ended` alors que le rack a pu
    # enchaîner seul pendant une coupure — sans effet : le mix s'applique, le transport n'est pas touché
    if _cur["active"] and _cur["slug"] == slug and (state.backing or {}).get("present") \
            and (state.backing or {}).get("slug") == slug:
        for stem, m in bmix.items():
            _ctl.mix(stem, m["mute"], m["vol"])
        _cur["mix"] = public_mix(mix, meta)
        _reply(msg, state="ready", id=kid, rev=_cur["rev"], voice=_cur["voice"], mix=_cur["mix"])
        return
    voice = msg.get("voice") or None
    vkey = json.dumps([str((voice or {}).get("patch_id") or ""), str((voice or {}).get("sha") or "")]) if voice else None
    song = {"slug": slug, "title": meta.get("title") or slug}
    chain = _cur["active"] and state.preset_id == KARAOKE_ID and vkey == _cur["voice_key"]
    if chain:
        # ENCHAÎNEMENT (§2.3) : même voix -> les stems changent, le preset et la lane voix restent
        from .store import _read_json, KARAOKE_FILE
        doc = _read_json(os.path.join(C.PRESETS_DIR, KARAOKE_FILE), {}) or {}
        _write_preset(dict(doc, backing={"songs": [song]}))
        _ctl.adopt([song])
        r = _ctl.load(slug)
        if not r.get("ok"):
            raise RuntimeError(r.get("error") or "load failed")
        vstat, vwhy = ("kept" if _cur["voice"] in ("mounted", "kept", "rebuilt") else _cur["voice"]), None
    else:
        preset, vstat, vwhy = _voice_lane_preset(voice)
        scene = str(((preset or {}).get("scenes") or [{}])[0].get("id") or "A")
        refused = recall_mod.check_preset(dict(preset, backing={"songs": [song]}), scene) if preset else None
        if refused:
            vstat, vwhy, preset = "refused", refused, None      # la voix ne compile pas : les stems jouent quand même
        if preset is None:
            preset, scene = _base_preset()
            if preset is None:
                raise RuntimeError("no preset is loaded on the rack to play the song over")
        # « Vocals » (2026-10-06) : le NOM AFFICHÉ (/live) ; l'id `karaoke` est un identifiant, il reste
        preset = dict(preset, id=KARAOKE_ID, name="Vocals", origin="golem.fm",
                      backing={"songs": [song]}, karaoke={"id": kid})
        refused = recall_mod.check_preset(preset, scene)
        if refused:
            raise RuntimeError(refused)
        if vstat == "mounted" and _cur["active"]:
            vstat = "rebuilt"                        # la voix change entre deux chansons : le micro coupe
        if not _cur["active"] and state.preset_id != KARAOKE_ID:
            _cur["prev"] = (state.preset_id, state.scene_id)
        already = (state.backing or {}).get("present") and (state.backing or {}).get("slug") == slug
        _write_preset(preset)
        if not recall_mod.do_recall(KARAOKE_ID, scene):
            raise RuntimeError(state.rig_error or "the Vocals preset did not build")
        if already:
            # la même chanson était déjà chargée : le rappel ne la recharge pas (backing.on_recall), donc
            # il n'applique pas non plus le mix du meta — on le pose ici, stem par stem
            for stem, m in bmix.items():
                _ctl.mix(stem, m["mute"], m["vol"])
    _cur.update(active=True, id=kid, rev=meta.get("rev", rev), slug=slug, voice_key=vkey,
                voice=vstat, mix=public_mix(mix, meta), stopping=False, local=bool(msg.get("_local")),
                lyrics_from=lyrics_from or (slug if golemfm.is_song_key(slug) else None))
    if not _wait_loaded(slug, timeout=4):
        # le chargement automatique du rappel (backing.on_recall, +0,7 s) ne vient pas : on ne le suppose
        # pas, on le demande — puis on attend que Reaper le DISE (.backing.json)
        log.info(f"stems {slug} pas encore dans Reaper : chargement explicite")
        _ctl.load(slug)
        if not _wait_loaded(slug):
            raise RuntimeError("the stems did not load in Reaper")
    out = {"state": "ready", "id": kid, "rev": meta.get("rev", rev), "voice": vstat, "mix": _cur["mix"]}
    if local or target:
        out["from_golem"] = slug                       # joué depuis la copie du rack, rien n'a été téléchargé
    if vstat in ("mounted", "kept", "rebuilt") and _cur.get("voice_in"):
        out["voice_input"] = f"IN {_cur['voice_in']}"           # l'entrée de la carte que la voix écoute
        out["voice_src"] = _cur.get("voice_src")                # rack (version installée) | golem.fm (sha)
    if vwhy:
        out["voice_why"] = vwhy
    _reply(msg, **out)
    if local or target:
        send_lyrics()                                  # golem.fm n'a peut-être pas le droit de les servir (§2.3)
    log.info(f"karaoké prêt : {kid} (voix {vstat}{' — ' + vwhy if vwhy else ''})")
    _prepare_next()


# ── LE RELAIS DES PAROLES (lot 9, contrat golem.fm 2026-10-08 ; prérequis de la fermeture des prêts, Q2) ──
# Quand le karaoké joue un .golem du RACK (la copie d'un membre sur le golem du groupe, un fichier venu d'ailleurs),
# golem.fm n'a pas forcément le droit d'en servir les paroles au navigateur : le rack les envoie lui-même, sur le WS
# de follow, en transit — jamais stockées chez golem.fm. Texte BRUT du .lrc (useKaraokeCues le passe à parseLrc).
def send_lyrics():
    """Envoie les paroles de la chanson jouée depuis un .golem. Rend True si une trame est partie."""
    # les paroles d'un .golem : celui qui joue, ou celui que golem.fm a désigné quand ce sont les stems du cache qui
    # jouent (Black : tab et paroles dans le .golem, stems dans k-4)
    sid = _cur.get("lyrics_from") or _cur.get("slug")
    if not _cur.get("active") or not golemfm.is_song_key(sid):
        return False
    from . import golemfile as G, songs as _songs
    path = _songs.source_path(sid)
    try:
        m = G.read_manifest(path)
        arc = next((a for a in sorted(m.get("files") or {}) if a.startswith("lyrics/") and a.endswith(".lrc")), "lyrics/song.lrc")
        text = G.read_member(path, arc).decode("utf-8", errors="replace")
    except (G.GolemError, OSError):
        return False                                   # pas de paroles dans ce fichier : rien à relayer
    rev = ((m.get("files") or {}).get(arc) or {}).get("sha256")
    emit({"type": "lyrics", "karaoke_id": _cur.get("id"), "song_id": sid, "rev": rev,
          "format": "lrc", "text": text}, local=_cur.get("local"))
    return True


def lyrics_get(msg):
    """`{"type": "lyrics-get", "karaoke_id"?, "song_id"?}` — le navigateur les redemande (la route des paroles lui a
    répondu 404 pendant qu'une soirée joue au golem). On ne répond que pour la chanson EN COURS."""
    if not _cur.get("active"):
        return False
    kid, sid = (msg or {}).get("karaoke_id"), (msg or {}).get("song_id")
    if (kid and str(kid) == str(_cur.get("id"))) or (sid and sid in (_cur.get("slug"), _cur.get("lyrics_from"))):
        return send_lyrics()
    return False


def _mix(msg):
    if not _cur["active"]:
        raise RuntimeError("no song loaded")
    mix = msg.get("mix") or {}
    meta = _kmeta(_cur["slug"])
    for stem, m in backing_mix(mix, meta).items():
        _ctl.mix(stem, m["mute"], m["vol"])
    _cur["mix"] = public_mix(mix, meta)
    _reply(msg, state="ready", id=_cur["id"], rev=_cur["rev"], voice=_cur["voice"], mix=_cur["mix"])


def _stop(msg):
    from . import recall as recall_mod
    from .store import load_preset
    if not _cur["active"]:
        _reply(msg, state="stopped", id=None)
        return
    _cur["stopping"] = True
    kid = _cur["id"]
    try:
        _ctl.stop()
        _ctl.unload()
        prev = _cur["prev"]
        if prev and prev[0] and load_preset(prev[0]):
            recall_mod.do_recall(prev[0], prev[1])
    finally:
        _deactivate()
    _reply(msg, state="stopped", id=kid)


def _deactivate():
    _cur.update(active=False, id=None, rev=None, slug=None, voice_key=None, voice=None, mix=None,
                prev=None, stopping=False, local=False, lyrics_from=None)
    _mix_sent["mix"] = None


# ── ce que le rack observe ───────────────────────────────────────────────────────────────────
def on_backing(data):
    """Appelé par monitors._poll_backing à chaque lecture de .backing.json. La FIN vient du compteur
    `ends` de golem_backing.lua (il ne bouge qu'en fin de chanson) — jamais d'une pause ni d'un stop."""
    ends = (data or {}).get("ends")
    if not isinstance(ends, int):
        return
    last = _cur["ends"]
    _cur["ends"] = ends
    if last is None or ends <= last:                 # première lecture, ou Reaper relancé (compteur à zéro)
        return
    if _cur["active"] and (data.get("slug") == _cur["slug"]):
        meta = _kmeta(_cur["slug"])
        _touch_played(_cur["slug"])
        # la longueur que Reaper a JOUÉE, pas la durée annoncée par golem.fm : « Black » (id 4) annonçait
        # 424 283 ms pour des stems de 345,7 s (2026-10-06) — la barre de golem.fm finissait à 81 %
        played = round(float(data.get("len") or 0) * 1000)
        emit({"type": "karaoke", "state": "ended", "id": _cur["id"],
              "posMs": played or meta.get("duration_ms") or 0}, local=_cur["local"])
        log.info(f"karaoké terminé : {_cur['id']}")
        _advance_offline()


def on_recall(pid):
    """Un preset rappelé au rack (écran, pied, setlist) quitte le karaoké — et golem.fm l'apprend."""
    from .store import KARAOKE_ID
    if not _cur["active"] or _cur["stopping"] or not pid or pid == KARAOKE_ID:
        return
    kid, local = _cur["id"], _cur["local"]
    _deactivate()
    emit({"type": "karaoke", "state": "left", "id": kid}, local=local)
    log.info(f"karaoké quitté : preset {pid} rappelé au rack")
