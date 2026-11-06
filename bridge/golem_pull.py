# SPDX-License-Identifier: GPL-3.0-or-later
"""Recevoir les `.golem` fabriqués par golem.fm (plan-song-sharing.md lot 2, côté rack — réglé avec
golem.fm le 2026-10-08).

Deux portes, UNE installation (`songs.install_golem` : vérification complète, puis fusion — le fichier
apporte médias et identité, le rack garde sa fiche, sa synchro et `mine/`) :

  1. LE JOB `song-install` — `{id, slug, url, etag}` : golem.fm pousse une chanson NOUVELLE (le rack ne peut
     pas tirer ce qu'il ne connaît pas). Le fichier reçu doit porter l'`id` annoncé : un `.golem` valide mais
     d'une autre chanson est REFUSÉ (bonne forme, mauvaise nature — CLAUDE.md).
  2. LE TIRAGE par `golem_etag` — même mécanisme que `bars_rev` : à chaque lecture du catalogue, pour chaque
     chanson que le rack porte DÉJÀ (en cache golem.fm sous ce slug, ou dans la bibliothèque avec ce slug) dont
     l'étiquette diffère de la dernière installée, le rack tire `GET /api/ext/songs/<slug>/golem`. Un rack éteint
     pendant la bascule se rattrape seul.

Le fichier (34 à 130 Mo) est écrit EN FLUX dans un temporaire de `songs/`, jamais tenu en mémoire. Les
étiquettes installées vivent dans `songs/.etag.json` ({slug: etag}) — une trace locale, jamais poussée."""
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid

from . import config as C
from .golog import get

log = get("golem_pull")

_lock = threading.Lock()          # un tirage à la fois : deux .golem de 100 Mo en parallèle n'apportent rien
_busy = set()                     # slugs en cours (le catalogue peut être relu pendant un tirage)
_ST = {"state": "idle", "slug": None, "error": None, "last": None}


def _etag_path():
    return os.path.join(C.SONGS_DIR, ".etag.json")


def _read():
    try:
        with open(_etag_path(), encoding="utf8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def etags():
    """{slug: etag} des .golem INSTALLÉS."""
    return {k: v for k, v in _read().items() if k != "_refused"}


def refused():
    """{slug: {etag, why}} — un fichier refusé n'est retiré QUE quand golem.fm en sert une autre version
    (sinon chaque lecture du catalogue retéléchargerait 55 Mo pour le refuser encore)."""
    r = _read().get("_refused")
    return r if isinstance(r, dict) else {}


def _write(d):
    from .store import _write_json_atomic
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    _write_json_atomic(_etag_path(), d)


def _set_etag(slug, etag):
    d = _read()
    d[slug] = etag
    (d.get("_refused") or {}).pop(slug, None)
    _write(d)


def _set_refused(slug, etag, why):
    d = _read()
    d.setdefault("_refused", {})[slug] = {"etag": etag, "why": str(why)[:300]}
    _write(d)


class Refused(RuntimeError):
    """Le FICHIER est refusé (autre chanson, .golem invalide, type non installable) — pas une panne réseau.
    Un refus est mémorisé par étiquette ; une panne se retente à la lecture suivante du catalogue."""


def status():
    return dict(_ST)


def _download(url_path, dest):
    """GET authentifié (jeton de l'appareil) écrit en flux dans `dest`. Rend l'en-tête ETag (ou None)."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not (base and token):
        raise RuntimeError("not paired with golem.fm")
    if not url_path.startswith("/"):
        raise RuntimeError("unexpected url (must be a path on the paired server): %s" % url_path)
    req = urllib.request.Request(base + url_path)
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=900) as r, open(dest, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                f.write(chunk)
            return r.headers.get("ETag")
    except urllib.error.HTTPError as e:
        raise RuntimeError("download failed (%s)" % e.code) from e


def _plan_path(url_path):
    """`/api/ext/songs/<slug>/golem?id=…` → `/api/ext/songs/<slug>/golem/plan?id=…` (golem.fm M6, 2026-10-12)."""
    base, _, q = url_path.partition("?")
    return base.rstrip("/") + "/plan" + ("?" + q if q else "")


class _NoPlan(Exception):
    """golem.fm ne sert pas (encore) le plan de cette chanson : on tire l'archive, comme avant."""


def _local_members(want_id):
    """Les membres de la copie que le rack a DÉJÀ, par sha256 : un rafraîchissement ne retire que ce qui a changé."""
    from . import golemfile as G, songs
    if not want_id:
        return None, {}
    p = songs._path(want_id)
    if not os.path.isfile(p):
        return None, {}
    try:
        files = G.read_manifest(p).get("files") or {}
    except Exception:
        return None, {}
    return p, {v.get("sha256"): k for k, v in files.items() if isinstance(v, dict) and v.get("sha256")}


def fetch_plan(url_path, want_id=None, workdir=None):
    """R6 (song-sharing §2.8) : tire le PLAN d'un `.golem` — {format, manifest (base64, octets EXACTS), members
    [{path, sha256, bytes, url | data}], etag} — et assemble l'archive ICI, avec golemfile.write_raw. Chaque membre
    est vérifié contre le sha256 du plan ET (pour les inscrits) contre celui du manifeste ; le moindre écart : refus,
    rien n'est posé. Un membre que le rack a déjà au même sha256 est repris de sa copie, pas retéléchargé.
    Rend (chemin de l'archive assemblée, etag). Lève _NoPlan si golem.fm ne sert pas de plan."""
    import base64
    import hashlib
    import re
    from . import golemfile as G, golemfm
    base, token = golemfm._cfg()
    if not (base and token):
        raise RuntimeError("not paired with golem.fm")
    st, plan = golemfm._req(_plan_path(url_path), token=token, timeout=30)
    if st in (404, 405):
        raise _NoPlan()
    if st != 200 or not isinstance(plan, dict):
        raise RuntimeError("plan download failed (%s)" % (st or "unreachable"))
    if plan.get("format") != 1 or not isinstance(plan.get("members"), list):
        raise Refused("unknown plan format")
    try:
        mbytes = base64.b64decode(plan.get("manifest") or "", validate=True)
        man = json.loads(mbytes.decode("utf-8"))
    except Exception as e:
        raise Refused("the plan manifest is unreadable") from e
    if want_id and man.get("id") != want_id:
        raise Refused("the file is song %s, not %s — refused" % (man.get("id"), want_id))
    local, have = _local_members(want_id or man.get("id"))
    members, seen = {}, set()
    os.makedirs(workdir, exist_ok=True)
    for i, mem in enumerate(plan["members"]):
        path, want = mem.get("path") or "", str(mem.get("sha256") or "").lower()
        if not G.safe_path(path) or path == G.MANIFEST or path in seen or not re.match(r"^[0-9a-f]{64}$", want):
            raise Refused("the plan lists an invalid member")
        seen.add(path)
        dst = os.path.join(workdir, "m%05d" % i)

        def ok():
            h = hashlib.sha256()
            with open(dst, "rb") as f:
                for blk in iter(lambda: f.read(1 << 20), b""):
                    h.update(blk)
            return h.hexdigest() == want and ("bytes" not in mem or os.path.getsize(dst) == mem["bytes"])
        if "data" in mem:
            try:
                blob = base64.b64decode(mem["data"] or "", validate=True)
            except Exception as e:
                raise Refused("the plan lists an invalid member") from e
            with open(dst, "wb") as f:
                f.write(blob)
        else:
            reused = False
            if local and want in have:                     # déjà ici au même sha256 : repris, puis RE-vérifié
                try:
                    with G.open_member(local, have[want]) as r, open(dst, "wb") as f:
                        for blk in iter(lambda: r.read(1 << 20), b""):
                            f.write(blk)
                    reused = ok()
                except Exception:
                    reused = False
            if not reused:
                u = mem.get("url") or ""
                if not u.startswith("/"):
                    raise Refused("the plan points outside the paired server")
                _download(u, dst)
        if not ok():
            raise Refused("member %s does not match the plan" % path)
        members[path] = dst
    out = os.path.join(workdir, "assembled.golem")
    try:
        G.write_raw(out, mbytes, members)
    except G.GolemError as e:
        raise Refused(str(e)) from e
    return out, plan.get("etag")


def fetch_install(url_path, want_id=None, slug=None):
    """Tire puis installe un `.golem` : par son PLAN (R6) quand golem.fm le sert, sinon l'archive. `want_id` : l'id
    que le fichier DOIT porter. Rend le résultat d'install_golem (+ `etag`). Lève RuntimeError (message montrable)."""
    import shutil
    from . import songs
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    work = os.path.join(C.SONGS_DIR, ".plan-%s" % uuid.uuid4().hex[:8])
    try:
        try:
            path, etag = fetch_plan(url_path, want_id, work)
        except _NoPlan:
            return _fetch_archive_install(url_path, want_id, slug)
        try:
            r = songs.install_golem(path, slug=slug)       # le slug vient du TRANSPORT, jamais du fichier
        except songs.InstallError as e:
            raise Refused(str(e)) from e
        return {**r, "etag": etag}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _fetch_archive_install(url_path, want_id=None, slug=None):
    """L'archive entière, fabriquée par golem.fm (avant R6, et tant qu'il la sert)."""
    from . import golemfile as G, songs
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    tmp = os.path.join(C.SONGS_DIR, ".dl-%s.golem" % uuid.uuid4().hex[:8])
    try:
        etag = _download(url_path, tmp)
        if want_id:
            try:
                got = G.read_manifest(tmp).get("id")
            except G.GolemError as e:
                raise Refused(str(e)) from e
            if got != want_id:
                raise Refused("the file is song %s, not %s — refused" % (got, want_id))
        try:
            r = songs.install_golem(tmp, slug=slug)        # le slug vient du TRANSPORT, jamais du fichier
        except songs.InstallError as e:
            raise Refused(str(e)) from e
        return {**r, "etag": etag}
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def song_install(job):
    """Le job `song-install` de golem.fm : `{id, slug, url, etag, category}`. Ack `{song: {id}, missing}`.

    `category` (song-sharing.md §2.7, « Send to <golem> » : un seul chemin pour les trois) : `song` et `vocals`
    s'installent dans la bibliothèque, `standard` dans le rayon des standards (même slug que le miroir des tags).
    Absente = `song` (les jobs d'avant le 2026-10-08)."""
    sid, slug, url = job.get("id"), job.get("slug"), job.get("url")
    if job.get("category") == "standard":
        from . import golemfm, standards as S
        if not slug:
            raise RuntimeError("song-install: slug required for a standard")
        ok, msg = golemfm.standards_import_golem(slug, job.get("etag"))
        if not ok:
            raise RuntimeError("standard %s: %s" % (slug, msg))
        S.invalidate()
        from . import inventory
        inventory.request_publish()
        log.info(f"song-install standard {slug}")
        return {"standard": {"slug": slug}, "missing": []}
    if not url:
        raise RuntimeError("song-install: url required")
    if not sid:
        raise RuntimeError("song-install: id required")
    with _lock:
        _ST.update(state="busy", slug=slug, error=None)
        try:
            r = fetch_install(url, want_id=sid, slug=slug)
        except Exception as e:
            _ST.update(state="error", error=str(e))
            raise
        if slug:
            _set_etag(slug, job.get("etag") or r.get("etag") or "")
        _ST.update(state="idle", last={"slug": slug, "id": r["id"], "created": r["created"]})
    log.info(f"song-install {sid} ({slug}) : {'nouvelle' if r['created'] else 'mise à jour'}, "
             f"{len(r['missing'])} fichier(s) attendu(s) absent(s)")
    from . import inventory
    inventory.request_publish()
    return {"song": {"id": r["id"]}, "missing": r["missing"]}


def wanted(cards):
    """Les cartes du catalogue à TIRER : étiquette annoncée (non nulle), différente de la dernière installée,
    et chanson que le rack porte déjà — en cache golem.fm sous ce slug, ou dans la bibliothèque avec ce slug."""
    from . import songs
    have, bad = etags(), refused()
    mine = {d.get("song_slug") for d in songs.list_all() if d.get("song_slug")}
    out = []
    for c in cards or []:
        slug, et = c.get("slug"), c.get("golem_etag")
        if not slug or not et or have.get(slug) == et or slug in _busy:
            continue
        if (bad.get(slug) or {}).get("etag") == et:      # même fichier déjà refusé : on attend une autre version
            continue
        if c.get("cached") or slug in mine:
            out.append((slug, et))
    return out


def id_for_slug(slug):
    """L'id de la chanson de la bibliothèque qui porte ce slug golem.fm, ou None.

    ⚠ VÉCU le 2026-10-08, au premier tirage réel : golem.fm a servi Paper Kite sous `us:83b5…` (sa chanson
    PERSO) alors que le rack la porte sous `rs:39ed…` (la chanson du GROUPE, rev 138, avec sa fiche). Sans
    cette garde, le rack a créé une SECONDE « Paper Kite », vide de fiche — deux fichiers bien formés, pas la
    même chanson. Le fichier tiré pour un slug que le rack porte déjà DOIT porter l'id que le rack connaît."""
    from . import songs
    hit = [d["id"] for d in songs.list_all() if d.get("song_slug") == slug]
    return hit[0] if len(hit) == 1 else None


def refresh_async(cards):
    """Lancé par la lecture du catalogue : tire, en tâche de fond, ce que `wanted` désigne."""
    todo = wanted(cards)
    if not todo:
        return
    for slug, _ in todo:
        _busy.add(slug)

    def run():
        for slug, et in todo:
            with _lock:
                _ST.update(state="busy", slug=slug, error=None)
                try:
                    # `?id=` (golem.fm, 2026-10-08) : un même morceau sert plusieurs chansons (Annie-Dog est bs:2 chez
                    # le groupe et bs:5 en perso) — le rack le demande SOUS SON id ; golem.fm vérifie et l'écrit
                    want = id_for_slug(slug)
                    url = f"/api/ext/songs/{slug}/golem" + (f"?id={urllib.parse.quote(want, safe='')}" if want else "")
                    r = fetch_install(url, want_id=want, slug=slug)
                    _set_etag(slug, et)
                    _ST.update(state="idle", last={"slug": slug, "id": r["id"], "created": r["created"]})
                    log.info(f"golem tiré {slug} → {r['id']} ({'nouvelle' if r['created'] else 'mise à jour'})")
                except Refused as e:                       # le FICHIER est refusé : mémorisé par étiquette
                    _ST.update(state="error", error=f"{slug}: {e}")
                    log.warning(f"golem {slug} refusé : {e}")
                    _set_refused(slug, et, e)
                except Exception as e:                     # panne (réseau, disque) : retentée plus tard
                    _ST.update(state="error", error=f"{slug}: {e}")
                    log.warning(f"golem {slug} : {e}")
                finally:
                    _busy.discard(slug)
    threading.Thread(target=run, daemon=True, name="golem-pull").start()


def refresh_all():
    """Tire ce qui a changé, en interrogeant la liste COMPLÈTE des chansons auxquelles l'appareil a droit
    (`/api/ext/songs`, SANS `?tagged=1`). ⚠ Le catalogue de l'écran suit l'ÉTOILE de golem.fm (décision 
    2026-08-03) : le 2026-10-08 il ne portait que 2 chansons, et Paper Kite — que le rack porte — n'en était
    pas. L'étoile trie ce que l'écran PROPOSE ; elle ne décide pas de ce qui reste à jour. Rend la liste visée."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not token:
        return []
    st, data = golemfm._req("/api/ext/songs", token=token, timeout=30)
    if st != 200 or not isinstance(data, list):
        log.warning(f"golem : liste des chansons indisponible ({st})")
        return []
    # l'empreinte de chaque carte (golem-format.md §12.5) : c'est elle qui rattache un .golem venu d'ailleurs à
    # une chanson du golem qui n'a pas encore ses médias
    from . import songs as _songs
    _songs.remember_cards(data)
    cached = {c["slug"] for c in golemfm.list_cache() if c.get("cached")}
    cards = [{"slug": c.get("slug"), "golem_etag": c.get("golem_etag"), "cached": c.get("slug") in cached}
             for c in data if isinstance(c, dict)]
    todo = wanted(cards)
    refresh_async(cards)
    return todo
