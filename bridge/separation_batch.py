# SPDX-License-Identifier: GPL-3.0-or-later
"""SÉPARER UN DOSSIER (docs/separation-batch.md, 2026-10-20) — un lot de morceaux de l'utilisateur, un `.golem` par morceau.

Le geste vient de Settings ▸ Engines ▸ Separation (« Separate a folder… »). Trois règles :

1. **Le dossier se LIT, il ne s'écrit jamais** (song-folders.md §2.2) : chaque morceau devient un `.golem` dans la
   bibliothèque du golem (`songs.install_golem`, le chemin unique), et rien n'est créé, renommé ni effacé à côté de
   l'audio de l'utilisateur.
2. **Le MÊME moteur et la MÊME exécution que le job de golem.fm** (separation.md §5) : `separation.separate`, la
   vérification des sorties (`analyse`), le MP3 192 kb/s. Un morceau interrompu reprend à son premier segment manquant.
   Le lot cède la place à un job de golem.fm (`separation.RUN_LOCK`) et à quelqu'un qui joue (`busy_reason`).
3. **Rien ne part sans le geste** : « Store on golem.fm when done » (phase 2, separation-batch.md §7) envoie chaque
   morceau fini dans le compte privé de l'utilisateur, par le chemin de « Store on golem.fm » (`inventory.upload`),
   avec la déclaration d'origine licite cochée POUR CE LOT (CGU de golem.fm §3.3). Sans la case, rien ne part.

L'état du lot vit dans `presets/.separation/batch.json` (local, hors dépôt, hors sauvegardes) : il survit à un
redémarrage du bridge. Un seul lot à la fois."""
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from . import golemfile as G
from . import separation as S

log = logging.getLogger("golem.separation")

GOLEM_AUDIO = (".wav", ".mp3", ".flac")      # ce qu'un .golem accepte tel quel ; le reste est converti en FLAC
TAB_EXT, LYRICS_EXT = ".gp", ".lrc"           # golem-format.md : UN .gp (Guitar Pro 7+) et des paroles LRC
MAX_FILES = 2000                              # un dossier de lot, pas un disque entier
MAX_DEPTH = 3                                 # le dossier et ses sous-dossiers (un par album), pas plus bas
MODES = ("full", "vocals")
STATES = ("waiting", "running", "done", "failed", "skipped", "cancelled")

_lock = threading.Lock()
_wake = threading.Condition(_lock)
_RUN = {"key": None, "phase": None, "progress": None, "waiting": None, "stop": None}
_worker = None
_SCAN = {"dir": None, "at": 0.0, "res": None}   # la dernière lecture : « Start » ne relit pas 40 fichiers une 2e fois
SCAN_TTL_S = 900


def _path():
    return os.path.join(S.WORK_DIR, "batch.json")


def _dir(bid, key=None):
    d = os.path.join(S.WORK_DIR, "batch-%s" % re.sub(r"[^A-Za-z0-9_-]", "_", str(bid))[:24])
    return os.path.join(d, key) if key else d


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            b = json.load(f)
        return b if isinstance(b, dict) and isinstance(b.get("items"), list) else None
    except (OSError, ValueError):
        return None


def _save(b):
    os.makedirs(S.WORK_DIR, exist_ok=True)
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())


# ── 1. lire le dossier ─────────────────────────────────────────────────────────────────────────
def _probe(path):
    """ffprobe : durée et tags (title, artist, album). None si le fichier n'est pas un audio lisible."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_entries",
                            "format=duration:format_tags=title,artist,album,album_artist:stream=codec_type",
                            path], capture_output=True, timeout=30, text=True)
        d = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not any(s.get("codec_type") == "audio" for s in d.get("streams") or []):
        return None
    fmt = d.get("format") or {}
    try:
        dur = float(fmt.get("duration") or 0)
    except ValueError:
        dur = 0.0
    if dur < 1:
        return None
    tags = {str(k).lower(): str(v).strip() for k, v in (fmt.get("tags") or {}).items() if str(v).strip()}
    return {"duration_s": round(dur, 2), "title": tags.get("title"), "artist": tags.get("artist") or tags.get("album_artist"),
            "album": tags.get("album")}


def _from_name(stem):
    """« Artiste - Titre » (tiret entouré d'espaces), « 03 - Titre », sinon le nom entier pour titre."""
    s = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", stem).strip()
    m = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", s)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    return s or stem, None


def _norm(artist, title):
    return G._norm_tag(artist), G._norm_tag(title)


def _library_keys():
    """(artiste, titre) normalisés de chaque chanson du golem : un morceau déjà là est sauté, pas doublé."""
    from . import songs
    out = set()
    for d in songs.list_all():
        if d.get("title"):
            out.add(_norm(d.get("artist"), d["title"]))
    return out


def scan(folder):
    """Ce que le dossier contient : un élément par fichier audio, avec sa tab (.gp) et ses paroles (.lrc) au MÊME nom.
    Rend {dir, items, total_s}. Lit seulement : aucun fichier n'est créé ni touché."""
    root = os.path.abspath(os.path.expanduser(folder or ""))
    if not folder or not os.path.isdir(root):
        raise S.SeparationError("folder not found")
    found, n = [], 0
    for cur, dirs, files in os.walk(root):
        depth = os.path.relpath(cur, root).count(os.sep) + (0 if cur == root else 1)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if depth < MAX_DEPTH else []
        names = {f.lower(): f for f in files if not f.startswith(".")}
        for f in sorted(files, key=str.lower):
            base, ext = os.path.splitext(f)
            if f.startswith(".") or ext.lower() not in S.AUDIO_EXTS:
                continue
            n += 1
            if n > MAX_FILES:
                raise S.SeparationError("more than %d audio files — choose a smaller folder" % MAX_FILES)
            found.append((cur, f, base, names.get((base + TAB_EXT).lower()), names.get((base + LYRICS_EXT).lower())))
    have = _library_keys()
    items, total, seen = [], 0.0, set()
    for cur, f, base, gp, lrc in found:
        rel = os.path.relpath(os.path.join(cur, f), root)
        info = _probe(os.path.join(cur, f))
        key = uuid.uuid5(uuid.NAMESPACE_URL, rel).hex[:12]
        if not info:
            items.append({"key": key, "path": rel, "title": f, "artist": None, "state": "unreadable"})
            continue
        title, artist, src = info["title"], info["artist"], "tags"
        if not title:
            title, guess = _from_name(base)
            artist, src = artist or guess, "name"
        k = _norm(artist, title)
        state = "duplicate" if k in have else ("twice" if k in seen else "new")
        seen.add(k)
        it = {"key": key, "path": rel, "title": title, "artist": artist, "album": info.get("album"),
              "duration_s": info["duration_s"], "from": src, "state": state}
        if gp:
            it["gp"] = os.path.relpath(os.path.join(cur, gp), root)
        if lrc:
            it["lrc"] = os.path.relpath(os.path.join(cur, lrc), root)
        items.append(it)
        if state == "new":
            total += info["duration_s"]
    res = {"dir": root, "items": items, "total_s": round(total)}
    _SCAN.update(dir=root, at=time.time(), res=res)
    return res


def _scanned(folder):
    root = os.path.abspath(os.path.expanduser(folder or ""))
    if _SCAN["dir"] == root and time.time() - _SCAN["at"] < SCAN_TTL_S:
        return _SCAN["res"]
    return scan(folder)


# ── 2. le lot ──────────────────────────────────────────────────────────────────────────────────
def state():
    """Ce que l'écran montre : le lot (sans chemins absolus de plus que le dossier), le morceau en cours, l'attente."""
    with _lock:
        b = load()
        if not b:
            return None
        cnt = {s: 0 for s in STATES}
        for it in b["items"]:
            cnt[it["state"]] = cnt.get(it["state"], 0) + 1
        left = sum(it.get("duration_s") or 0 for it in b["items"] if it["state"] in ("waiting", "running"))
        e, _ = S.active_engine()
        rtf = (S.caps() or {}).get("rtf") if e else None
        return {"id": b["id"], "dir": b["dir"], "name": os.path.basename(b["dir"].rstrip("/\\")) or b["dir"],
                "mode": b["mode"], "paused": bool(b.get("paused")), "created": b.get("created"),
                "items": [{k: v for k, v in it.items() if k != "work"} for it in b["items"]],
                "counts": cnt, "left_s": round(left * rtf) if rtf else None,
                "current": {"key": _RUN["key"], "phase": _RUN["phase"], "progress": _RUN["progress"]} if _RUN["key"] else None,
                "waiting": _RUN["waiting"], "store": bool(b.get("store")),
                "stored": sum(1 for it in b["items"] if it.get("store") == "stored"),
                "finished": not any(it["state"] in ("waiting", "running") or it.get("store") in ("waiting", "sending")
                                    for it in b["items"])}


def _check_store(declared):
    from . import golemfm
    if not golemfm._cfg()[1]:
        raise S.SeparationError("this golem is not paired with golem.fm")
    if not declared:
        raise S.SeparationError("tick the declaration to store these songs on golem.fm")


def start(folder, items, mode, store=False, declared=False):
    """Lance un lot sur `items` (des clés de `scan`, avec titre et artiste corrigés à l'écran). Refuse sans moteur testé
    en service, ou si un lot tourne déjà. `store` :
    chaque morceau fini part dans le compte golem.fm — seulement avec `declared` (la déclaration de CE lot)."""
    if mode not in MODES:
        raise S.SeparationError("unknown mode")
    if store:
        _check_store(declared)
    e, _ = S.active_engine()
    if not e or not (e.get("test") or {}).get("ok"):
        raise S.SeparationError("no tested engine is in use", "no_engine")
    if mode == "vocals" and not any(_is_voice(s) for s in e["test"].get("stems") or []):
        raise S.SeparationError("the engine in use gives no vocals stem — choose Full stems")
    found = {it["key"]: it for it in _scanned(folder)["items"]}
    root = os.path.abspath(os.path.expanduser(folder))
    chosen = []
    for want in items or []:
        it = found.get(str((want or {}).get("key") or ""))
        if not it or it["state"] == "unreadable":
            continue
        title = str(want.get("title") or it["title"]).strip()[:200]
        artist = (str(want.get("artist") or it.get("artist") or "").strip() or None)
        chosen.append({**{k: it[k] for k in ("key", "path", "album", "duration_s", "gp", "lrc") if it.get(k) is not None},
                       "title": title, "artist": artist and artist[:200], "state": "waiting"})
    if not chosen:
        raise S.SeparationError("no song selected")
    with _lock:
        b = load()
        if b and any(it["state"] in ("waiting", "running") for it in b["items"]):
            raise S.SeparationError("a batch is already running — cancel it or let it finish")
        if b:
            shutil.rmtree(_dir(b["id"]), ignore_errors=True)
        b = {"id": uuid.uuid4().hex[:12], "dir": root, "mode": mode, "engine": e["id"], "paused": False,
             "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "items": chosen, "store": bool(store),
             **({"declared_at": time.strftime("%Y-%m-%dT%H:%M:%S")} if store else {})}
        _save(b)
        _wake.notify_all()
    log.info("batch: %d song(s), mode %s, %s" % (len(chosen), mode, S._origin_word(e)))
    ensure_worker()
    return state()


def pause(on):
    with _lock:
        b = load()
        if not b:
            raise S.SeparationError("no batch")
        b["paused"] = bool(on)
        _save(b)
        if on and _RUN["key"]:
            _RUN["stop"] = "paused"
        _wake.notify_all()
    if not on:
        ensure_worker()
    return state()


def cancel():
    """Tout ce qui attend devient `cancelled` ; le morceau en cours s'arrête. Ce qui est fait reste dans la bibliothèque."""
    with _lock:
        b = load()
        if not b:
            raise S.SeparationError("no batch")
        for it in b["items"]:
            if it["state"] in ("waiting", "running"):
                it["state"] = "cancelled"
        _save(b)
        running = bool(_RUN["key"])
        if running:
            _RUN["stop"] = "cancelled"
        _wake.notify_all()
    if not running:
        shutil.rmtree(_dir(b["id"]), ignore_errors=True)
    return state()


def retry(key):
    with _lock:
        b = load()
        it = next((x for x in (b or {}).get("items", []) if x["key"] == key), None)
        if not it or it["state"] not in ("failed", "cancelled"):
            raise S.SeparationError("nothing to try again")
        it["state"] = "waiting"
        it.pop("error", None)
        _save(b)
        _wake.notify_all()
    ensure_worker()
    return state()


def store(keys=None, declared=False):
    """Envoie à golem.fm les morceaux FAITS du lot qui n'y sont pas (tous, ou `keys`) — après coup, ou après un refus.
    Même déclaration que le lancement : sans elle, rien ne part."""
    _check_store(declared)
    with _lock:
        b = load()
        if not b:
            raise S.SeparationError("no batch")
        n = 0
        for it in b["items"]:
            if it["state"] == "done" and it.get("song") and it.get("store") != "stored" and (not keys or it["key"] in keys):
                it["store"], n = "waiting", n + 1
                it.pop("store_error", None)
        if not n:
            raise S.SeparationError("nothing to store")
        b["store"], b["declared_at"] = True, time.strftime("%Y-%m-%dT%H:%M:%S")
        _save(b)
        _wake.notify_all()
    ensure_worker()
    return state()


def dismiss():
    """Ferme un lot terminé (la carte du moteur ne le montre plus). Un lot en cours se met en pause ou s'annule."""
    with _lock:
        b = load()
        if b and any(it["state"] in ("waiting", "running") or it.get("store") in ("waiting", "sending")
                     for it in b["items"]):
            raise S.SeparationError("the batch is not finished")
        if b:
            shutil.rmtree(_dir(b["id"]), ignore_errors=True)
        with contextlib.suppress(OSError):
            os.unlink(_path())
    return None


def resume():
    """Au démarrage du bridge : un lot qui avait du travail repart (un morceau `running` redevient `waiting`)."""
    with _lock:
        b = load()
        if not b:
            return
        changed = False
        for it in b["items"]:
            if it["state"] == "running":
                it["state"], changed = "waiting", True
            if it.get("store") == "sending":
                it["store"], changed = "waiting", True
        if changed:
            _save(b)
        todo = any(it["state"] == "waiting" or it.get("store") == "waiting" for it in b["items"])
    if todo:
        ensure_worker()


def ensure_worker():
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_work, daemon=True, name="separation-batch")
    _worker.start()


def _set(key, **kw):
    with _lock:
        b = load()
        for it in (b or {}).get("items", []):
            if it["key"] == key:
                it.update(kw)
                for k in [k for k, v in kw.items() if v is None]:
                    it.pop(k, None)
        if b:
            _save(b)


def _send(it):
    """Un morceau fait → son compte golem.fm (`inventory.upload`, le chemin de « Store on golem.fm »)."""
    from . import inventory
    _set(it["key"], store="sending")
    try:
        res = inventory.upload(it["song"], "full", declared=True)
        _set(it["key"], store="stored", store_error=None, slug=res.get("slug"))
    except inventory.UploadError as ex:
        _set(it["key"], store="failed", store_error=str(ex)[:160])
    except Exception as ex:  # noqa: BLE001
        _set(it["key"], store="failed", store_error="golem.fm unreachable (%s)" % type(ex).__name__)


def _work():
    while True:
        with _lock:
            b = load()
            if not b or b.get("paused"):
                return
            up = next((x for x in b["items"] if x.get("store") == "waiting" and x["state"] == "done"), None)
            it = next((x for x in b["items"] if x["state"] == "waiting"), None)
            if not it and not up:
                return
            bid, mode, root = b["id"], b["mode"], b["dir"]
        if up:                                         # ce qui est fait part d'abord : le réseau, pas le moteur
            _send(up)
            continue
        e, _ = S.active_engine()
        # la règle « libre » sans les 10 min sans geste : le lot vient d'un geste, on ne fait pas attendre celui qui l'a
        # lancé ; un job de golem.fm passe devant (il attend son ack), quelqu'un qui joue arrête tout
        why = "no tested engine is in use" if not e else (
            "a golem.fm song comes first" if (S._JOBS or S._JOB["cur"]) else S._busy(idle=False))
        if why:
            _RUN["waiting"] = why
            with _lock:
                _wake.wait(15)
            continue
        _RUN.update(waiting=None, key=it["key"], phase="decode", progress=None, stop=None)
        _set(it["key"], state="running")
        try:
            with S.RUN_LOCK:
                sid = _run_item(bid, it, mode, root, e)
            with _lock:
                want_store = bool((load() or {}).get("store"))
            _set(it["key"], state="done", song=sid, error=None, **({"store": "waiting"} if want_store else {}))
            shutil.rmtree(_dir(bid, it["key"]), ignore_errors=True)
            log.info("batch: one song done")
        except S.Stopped:
            why = _RUN["stop"]
            _set(it["key"], state="cancelled" if why == "cancelled" else "waiting")
            if why == "cancelled":
                shutil.rmtree(_dir(bid, it["key"]), ignore_errors=True)
            elif not why:
                _RUN["waiting"] = "golem is busy"
                with _lock:
                    _wake.wait(15)
        except S.SeparationError as ex:
            _set(it["key"], state="failed", error=str(ex)[:160])
            log.info("batch: one song failed (%s)" % (ex.code or "error"))
        except Exception as ex:  # noqa: BLE001
            _set(it["key"], state="failed", error="engine failed")
            log.warning("batch: one song crashed: %s" % type(ex).__name__)
        finally:
            _RUN.update(key=None, phase=None, progress=None, stop=None)


# ── 3. un morceau → un .golem ─────────────────────────────────────────────────────────────────
def _is_voice(stem):
    from .golemfm import stem_family
    return stem_family(stem) in ("vocals", "voice")


def _run_item(bid, it, mode, root, e):
    src = os.path.join(root, it["path"])
    if not os.path.isfile(src):
        raise S.SeparationError("the file is no longer in the folder")
    wd = _dir(bid, it["key"])
    os.makedirs(wd, exist_ok=True)
    mix = os.path.join(wd, "mix.f32")
    if not os.path.isfile(mix):                        # reprise : le décodage n'est fait qu'une fois
        S.decode(src, mix + ".tmp")
        os.replace(mix + ".tmp", mix)
    n = os.path.getsize(mix) // 8
    _RUN["phase"] = "separate"

    def stop():
        if _RUN["stop"]:
            return _RUN["stop"]
        return S._busy(idle=False)
    stems, comp, _load = S.separate(e, mix, n, os.path.join(wd, "segments"), os.path.join(wd, "out"), stop,
                                    lambda p: _RUN.update(progress=p))
    S._fit(e, stems, n)
    a = S.analyse(stems, mix, n)                       # NaN, durée, noms : relus sur le vrai morceau (§8.4)
    S._note_rtf(e["id"], comp / (n / S.SR))
    if mode == "vocals":
        voice = [s for s in stems if _is_voice(s)]
        if not voice:
            raise S.SeparationError("the engine gave no vocals stem")
        rest = [p for s, p in stems.items() if s not in voice]
        keep = {s: stems[s] for s in voice}
        if rest:
            keep["other"] = S._sum_f32(rest, os.path.join(wd, "other-sum.f32"), n)
        stems = keep
    _RUN["phase"] = "file"
    members, files = {}, {}
    for s, p in stems.items():
        mp3 = os.path.join(wd, s + ".mp3")
        if not os.path.isfile(mp3):
            S.encode_mp3(p, mp3 + ".tmp.mp3")
            os.replace(mp3 + ".tmp.mp3", mp3)
        members["stems/%s.mp3" % s] = mp3
        files["stems/%s.mp3" % s] = {"part": s, "origin": "separated", "codec": "mp3"}
    ext = os.path.splitext(src)[1].lower()
    if ext in GOLEM_AUDIO:                             # l'original tel quel : ses octets font son empreinte
        orig, codec = src, ext[1:]
    else:                                              # .ogg, .m4a… : le .golem n'accepte que WAV, MP3, FLAC
        orig, codec = os.path.join(wd, "original.flac"), "flac"
        if not os.path.isfile(orig):
            S._ffmpeg(["-i", src, "-map_metadata", "-1", "-vn", "-c:a", "flac", orig + ".tmp.flac"], "decoding")
            os.replace(orig + ".tmp.flac", orig)
        ext = ".flac"
    members["audio/original" + ext] = orig
    files["audio/original" + ext] = {"codec": "wav" if codec == "wav" else codec}
    if it.get("gp"):
        members["scores/song.gp"] = os.path.join(root, it["gp"])
    if it.get("lrc"):
        members["lyrics/song.lrc"] = os.path.join(root, it["lrc"])
    artist, title = it.get("artist") or "", it["title"]
    m = {"type": "song", "id": G.content_id(artist, title, "cover"), "title": title, "kind": "cover",
         "rights": {"work": "third-party"}, "recording": {"duration_ms": int(n * 1000 / S.SR)}, "files": files}
    if artist:
        m["artist"] = artist
    if it.get("album"):
        m["album"] = it["album"]
    out = os.path.join(wd, "song.golem")
    G.write(out, m, members)
    from . import songs
    try:
        res = songs.install_golem(out)
    except songs.InstallError as ex:
        raise S.SeparationError(str(ex)) from ex
    with contextlib.suppress(OSError):
        os.unlink(out)
    log.info("batch: %d stem(s), %s" % (len(stems), "silent: %d" % len(a["silent"]) if a["silent"] else "none silent"))
    return res.get("id")
