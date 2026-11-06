# SPDX-License-Identifier: GPL-3.0-or-later
"""L'INVENTAIRE du golem sur golem.fm, et le STOCKAGE à la carte (docs/private/song-sharing.md §2.7, 2026-10-08).

Deux mouvements, et un seul est automatique :
  1. L'INVENTAIRE monte tout seul : une CARTE par `.golem` que le golem détient (chansons et Vocals dans `songs/`,
     standards dans `library/standards/golem/`). Une carte ne porte que des métadonnées — ce que le fichier porte,
     présent ou non, jamais le contenu. `PUT /api/ext/inventory` (l'instantané complet) la première fois ou quand la
     mémoire locale est perdue, `PATCH` (le diff) ensuite. ⚠ Un instantané n'est envoyé qu'après une lecture SANS
     ERREUR de la bibliothèque : une liste vide ou courte peut venir d'une lecture ratée, et golem.fm retirerait des
     cartes vraies (il refuse d'ailleurs `empty_snapshot` / `shrinking_snapshot` — on ne confirme jamais). Une lecture
     incomplète n'envoie que des ajouts, jamais de retrait.
  2. LE CONTENU ne monte que sur un GESTE : « Store on golem.fm » ici, ou le job `golem-upload` déposé par golem.fm
     quand le geste est fait là-bas. Complet, ou LÉGER (`golemfile.light_copy` : le texte seul, même manifeste).
     Après l'envoi, la version renvoyée (`golem_etag`, figée par golem.fm) est notée comme celle d'un tirage, et la
     chanson est reliée à son slug : la synchro suivante voit la même version et ne retire rien — sans quoi elle
     tirerait la même chanson une seconde fois (doublon de Paper Kite, 2026-10-08).

La catégorie (`song` | `standard` | `vocals`) est LUE par `golemfile.category`, la règle partagée avec golem.fm.
La mémoire de ce qui a été publié vit dans `songs/.inventory.json` ({id: etag}) — une trace locale.
"""
import hashlib
import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from . import config as C
from . import golemfile as G

log = logging.getLogger("golem.inventory")

_lock = threading.Lock()
_ST = {"published_at": None, "error": None, "cards": 0}
SECTION = {"song": "songs", "vocals": "songs", "standard": "standards", "track": "songs"}   # où une catégorie compte ses places


def _std_dir():
    from . import standards as S
    return S.GOLEM_DIR


def _mem_path():
    return os.path.join(C.SONGS_DIR, ".inventory.json")


def _mem():
    try:
        with open(_mem_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _set_mem(d):
    from .store import _write_json_atomic
    os.makedirs(C.SONGS_DIR, exist_ok=True)
    _write_json_atomic(_mem_path(), d)


# ── les cartes ────────────────────────────────────────────────────────────────────────────────────

CARD_REV = b"card-5"          # changer quand la carte gagne ou perd un champ : toutes les cartes .golem repartent
CARD_FIELDS = ("id", "etag", "category", "title", "artist", "kind", "duration_ms", "bytes", "carries", "album", "genres")


def card_of(path, rep=None):
    """La carte d'un `.golem` : des métadonnées, AUCUN contenu. Lève GolemError / OSError si illisible. `rep` = le
    rapport de `verify` déjà lu (l'index des dossiers de chansons : un partage réseau fait payer chaque ouverture)."""
    rep = rep or G.verify(path, hashes=False)
    m = rep["manifest"]
    files = m.get("files") or {}
    present = set(rep["present"]) | set(rep["undeclared"])
    rec = m.get("recording") if isinstance(m.get("recording"), dict) else {}
    with zipfile.ZipFile(path) as zf:
        raw = zf.read(G.MANIFEST)
    stems = sorted(str((files.get(n) or {}).get("part") or os.path.splitext(os.path.basename(n))[0])
                   for n in present if n.startswith("stems/"))
    has = lambda pre: any(n.startswith(pre) for n in present)
    return {
        "id": m.get("id"),
        # la VERSION locale : l'empreinte du manifeste, qui porte le sha256 de chaque membre — elle change dès qu'un
        # fichier change, et ne coûte qu'une lecture du manifeste
        # + la FORME de la carte (CARD_REV) : une carte qui gagne des champs (album, genres, 2026-10-16) doit repartir,
        # même si le fichier n'a pas bougé — sinon les cartes déjà publiées ne les recevaient jamais
        "etag": "rk-" + hashlib.sha1(raw + CARD_REV).hexdigest()[:20],
        "category": G.category(present, files.keys()),
        "title": m.get("title"), "artist": m.get("artist"), "kind": m.get("kind"),
        # de quoi faire une carte « premium » chez golem.fm (2026-10-16) — des MÉTADONNÉES : golem.fm va chercher lui-même
        # pochette et photo d'artiste, aucune image ne part d'ici
        **({"album": m["album"]} if isinstance(m.get("album"), str) and m["album"].strip() else {}),
        **({"genres": [{"family": g.get("family"), "subgenre": g.get("subgenre")}
                       for g in m["genres"] if isinstance(g, dict) and g.get("family")][:4]}
           if isinstance(m.get("genres"), list) else {}),
        "duration_ms": rec.get("duration_ms") or m.get("duration_ms"),
        "bytes": os.path.getsize(path),
        "carries": {"audio": has("audio/"), "stems": stems, "tab": G.SCORE in present, "lyrics": G.LYRICS in present,
                    "chart": G.CHART in present, "bars": "sync/bars.json" in present, "booklet": has("booklet/"),
                    "video": has("video/"),
                    # la bande des instruments de la carte golem.fm : ceux que joue la tab (golem.fm, 2026-10-16)
                    "parts": G.tab_parts(m)},
    }


def _files():
    """Les `.golem` que le golem détient : [(chemin, origine)]."""
    out = []
    for d, origin in ((C.SONGS_DIR, "songs"), (_std_dir(), "standards")):
        try:
            names = sorted(os.listdir(d))
        except FileNotFoundError:
            continue
        for fn in names:
            if fn.endswith(".golem") and not fn.startswith("."):
                out.append((os.path.join(d, fn), origin))
    return out


def collect():
    """(cartes, lecture_complète). Une carte sans id ni catégorie n'est pas publiée (rien à montrer, rien à stocker) ;
    un fichier ILLISIBLE rend la lecture incomplète — et interdit l'instantané comme les retraits."""
    cards, ok = {}, True
    for path, _ in _files():
        try:
            c = card_of(path)
        except (G.GolemError, OSError, zipfile.BadZipFile, ValueError) as e:
            log.warning("inventaire : %s illisible (%s) — lecture incomplète" % (os.path.basename(path), e))
            ok = False
            continue
        if c["id"] and c["category"]:
            cards[c["id"]] = {**c, "where": "golem"}
    # les DOSSIERS DE CHANSONS (song-folders.md §2.7) : marqués « folder », un dossier exclu n'y est pas, et un
    # dossier absent rend la lecture incomplète — aucun retrait tant qu'il n'est pas relu en entier
    try:
        from . import song_folders
        more, fok = song_folders.inventory_cards()
    except Exception as e:
        log.warning("inventaire : dossiers de chansons illisibles (%s) — lecture incomplète" % e)
        more, fok = {}, False
    for gid, c in more.items():
        cards.setdefault(gid, c)
    # le CACHE DE BACKINGS (page Tracks), en cartes « coquille » (accord golem.fm, 2026-10-16) : les chansons tirées de
    # golem.fm avant la purge n'ont pas de `.golem` — sans carte, golem.fm ne montrait que Paper Kite
    bk, bok = backing_cards(cards)
    for gid, c in bk.items():
        cards.setdefault(gid, c)
    return cards, ok and fok and bok


def _norm_title(t):
    """Un titre comparable : minuscules, sans accents, SANS ponctuation ni espaces — « Knockin' On Heaven's Door » et
    « KNOCKIN ON HEAVENS DOOR », « Annie-Dog » et « Annie Dog » se rejoignent."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in t if ch.isalnum())


def _duration_ms(golemfm, slug, entry):
    """La durée d'une piste du cache : `duration_ms` du meta.json (les chansons k-* de golem.fm), sinon `duration_sec`."""
    meta = golemfm.read_meta(slug) or {}
    ms = meta.get("duration_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        return int(ms)
    sec = entry.get("duration_sec") if entry.get("duration_sec") is not None else meta.get("duration_sec")
    return int(sec * 1000) if isinstance(sec, (int, float)) and sec > 0 else None


def backing_id(slug):
    """L'id d'une carte de backing : `bk:` + 32 hexa (golem.fm range 40 caractères ; le préfixe dit « pas un .golem »)."""
    return "bk:" + hashlib.sha256(str(slug).encode("utf-8")).hexdigest()[:32]


def backing_cards(golem_cards=None):
    """({id: carte}, lecture_complète) — une carte par entrée du cache de backings qui n'est PAS déjà une chanson `.golem` :
    ni une clé de chanson (sa carte `.golem` la porte), ni un slug que porte déjà une chanson du golem — et qui a ses
    stems (ce que montre la page Tracks). Aucun contenu, comme toute carte. Une erreur de lecture du
    cache rend la lecture incomplète : aucun retrait tant qu'il n'est pas relu en entier."""
    from . import golemfm
    covered, titles = set(), set()
    try:
        from . import songs as _songs
        for gid, c in (golem_cards or {}).items():
            if c.get("where") == "golem" and c.get("category") in ("song", "vocals", "track"):
                if c.get("title"):
                    titles.add(_norm_title(c["title"]))
                sl = (_songs.load(gid) or {}).get("song_slug")
                if sl:
                    covered.add(sl)
    except Exception as e:
        log.warning("inventaire : slugs des chansons illisibles (%s)" % e)
    try:
        entries = golemfm.list_cache()
    except OSError as e:
        log.warning("inventaire : cache de backings illisible (%s) — lecture incomplète" % e)
        return {}, False
    out = {}
    for e in entries:
        slug = e.get("slug")
        # CE QUE LA PAGE TRACKS MONTRE : une entrée du cache qui a SES STEMS (golemfm.catalog fait la même coupe) — un
        # dossier sans stems est un téléchargement interrompu, pas une chanson.
        if not slug or not e.get("cached") or golemfm.is_song_key(slug) or slug in covered:
            continue
        # `k-<n>` = la LIGNE VOCALS n°<n> de golem.fm (2026-10-16) : publiée en catégorie « vocals », et golem.fm
        # la reconnaît à son id (bk: + sha256("k-<n>"))
        vocals = slug.startswith("k-")
        # le MÊME TITRE qu'un .golem du golem, chanson OU ligne Vocals (casse et ponctuation ignorées) : une vieille
        # entrée du cache de la même chanson — sa carte ferait un doublon, ou une carte vide chez golem.fm (golem.fm,
        # 2026-10-16). On ne supprime rien du cache : c'est au musicien de décider
        if _norm_title(e.get("title") or slug) in titles:
            continue
        try:
            st = os.stat(golemfm.song_dir(slug))
        except OSError:
            continue
        stems = sorted(golemfm.stems_of(slug))
        out[backing_id(slug)] = {
            "id": backing_id(slug), "category": "vocals" if vocals else "song", "where": "backing",
            "title": e.get("title") or slug, "artist": e.get("artist"),
            "duration_ms": _duration_ms(golemfm, slug, e),
            "bytes": e.get("bytes"),
            # stable tant que le dossier ne change pas — et la FORME de la carte (CARD_REV), comme une carte .golem
            "etag": "bk-%d-%d-%s" % (int(st.st_mtime), int(e.get("bytes") or 0), CARD_REV.decode()),
            "carries": {"audio": True, "stems": stems},
        }
    return out, True


def path_of(gid):
    """Le fichier qui porte cet id (chanson, ligne Vocals ou standard), ou None. Le golem d'abord, puis les dossiers
    de chansons en ligne : « Store on golem.fm » lit le fichier où il est (song-folders.md §2.7)."""
    for path, _ in _files():
        try:
            if G.read_manifest(path).get("id") == gid:
                return path
        except (G.GolemError, OSError):
            continue
    from . import song_folders
    return song_folders.path_of(gid)


PATCH_BATCH = 500        # des milliers de cartes avec les dossiers de chansons : un PATCH par lot (song-folders.md §2.7)


def _patch(upsert, remove, token):
    """Le diff, par lots de PATCH_BATCH cartes. Le premier refus arrête l'envoi (rendu tel quel) ; la réponse
    rendue est celle du DERNIER lot, qui porte le `rev` complet de l'appareil."""
    from . import golemfm
    st, data = 200, {}
    chunks = [upsert[i:i + PATCH_BATCH] for i in range(0, len(upsert), PATCH_BATCH)] or [[]]
    for i, chunk in enumerate(chunks):
        body = {"upsert": chunk, "remove": remove if i == len(chunks) - 1 else []}
        st, data = golemfm._req("/api/ext/inventory", body=body, token=token, method="PATCH", timeout=60)
        if st not in (200, 201):
            break
    return st, data


# ── publier ───────────────────────────────────────────────────────────────────────────────────────

def publish():
    """Publie l'inventaire : PUT si golem.fm ne nous connaît pas encore, PATCH du diff sinon. Rend un résumé."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not (base and token):
        return {"ok": False, "error": "not paired with golem.fm"}
    with _lock:
        cards, complete = collect()
        mem = _mem()
        if not mem and not complete:
            # pas d'instantané sur une lecture ratée — mais un dossier de chansons débranché pour de bon ne doit pas
            # bloquer l'inventaire : les AJOUTS partent, aucun retrait (song-folders.md §2.6)
            st, data = _patch(list(cards.values()), [], token)
            sent = {"upsert": len(cards), "remove": 0}
        elif not mem:
            st, data = golemfm._req("/api/ext/inventory", body={"cards": list(cards.values())}, token=token,
                                      method="PUT", timeout=60)
            sent = {"put": len(cards)}
        else:
            upsert = [c for gid, c in cards.items() if mem.get(gid) != c["etag"]]
            remove = [gid for gid in mem if gid not in cards] if complete else []
            if not upsert and not remove:
                _ST.update(error=None, cards=len(cards))
                return {"ok": True, "unchanged": True}
            st, data = _patch(upsert, remove, token)
            sent = {"upsert": len(upsert), "remove": len(remove)}
        NEW = ("bk:", "ct:")          # les formes d'id qu'un golem.fm d'avant ne connaît pas (prod, 2026-10-16)
        if st == 422 and any(c.get("category") == "track" for c in cards.values()):
            # la catégorie « track » (separation-batch.md §7, 2026-10-21) : un golem.fm qui ne la connaît pas encore refuse
            # l'envoi EN ENTIER (`bad_card`) — refait sans elles ; elles repartent au prochain envoi, et passent le jour où
            # golem.fm les accepte
            log.warning("inventaire : golem.fm refuse les cartes « track » (%s) — renvoyé sans elles" % (data,))
            held = {gid for gid, c in cards.items() if c.get("category") == "track"}
            cards = {gid: c for gid, c in cards.items() if gid not in held}
            mem = {gid: e for gid, e in mem.items() if gid not in held}
            if not mem:
                st, data = golemfm._req("/api/ext/inventory", body={"cards": list(cards.values())}, token=token,
                                          method="PUT", timeout=60)
            else:
                upsert = [c for gid, c in cards.items() if mem.get(gid) != c["etag"]]
                remove = [gid for gid in mem if gid not in cards] if complete else []
                st, data = _patch(upsert, remove, token)
            _ST["track_refused"] = True
        if st == 422 and any(str(gid).startswith(NEW) for gid in cards):
            # un golem.fm qui ne connaît pas encore les cartes de backing (la prod avant son déploiement, 2026-10-16)
            # refuse l'envoi EN ENTIER : on le refait sans elles, plutôt que de laisser tout l'inventaire en erreur
            log.warning("inventaire : golem.fm refuse les cartes bk:/ct: (%s) — renvoyé sans elles" % (data,))
            cards = {gid: c for gid, c in cards.items() if not str(gid).startswith(NEW)}
            mem = {gid: e for gid, e in mem.items() if not str(gid).startswith(NEW)}
            if not mem:
                st, data = golemfm._req("/api/ext/inventory", body={"cards": list(cards.values())}, token=token,
                                          method="PUT", timeout=60)
            else:
                upsert = [c for gid, c in cards.items() if mem.get(gid) != c["etag"]]
                remove = [gid for gid in mem if gid not in cards] if complete else []
                st, data = _patch(upsert, remove, token)
            _ST["backing_refused"] = True
        if st not in (200, 201):
            _ST.update(error="%s %s" % (st, data))
            log.warning("inventaire refusé par golem.fm (%s) : %s" % (st, data))
            return {"ok": False, "status": st, "error": data}
        # la mémoire suit ce que golem.fm a gardé (sa réponse `rev` = {id: etag}), sinon ce qu'on a envoyé
        rev = (data or {}).get("rev") if isinstance(data, dict) else None
        new = dict(rev) if isinstance(rev, dict) else {**{k: v for k, v in mem.items() if k in cards or not complete},
                                                        **{gid: c["etag"] for gid, c in cards.items()}}
        _set_mem(new)
        import datetime
        _ST.update(published_at=datetime.datetime.now().isoformat(timespec="seconds"), error=None, cards=len(cards))
        log.info("inventaire publié : %s" % sent)
        return {"ok": True, **sent}


def forget():
    """golem.fm a perdu notre inventaire (ou on change de compte) : le prochain envoi est un instantané."""
    with _lock:
        _set_mem({})


_pending = {"t": None}


def request_publish(delay=5.0):
    """Une publication regroupée, en tâche de fond (après un dépôt, un tirage, une suppression)."""
    t = _pending["t"]
    if t:
        t.cancel()

    def run():
        try:
            publish()
        except Exception as e:                       # jamais fatal : l'inventaire se rattrape au passage suivant
            log.warning("inventaire : %s" % e)
    t = threading.Timer(delay, run)
    t.daemon = True
    _pending["t"] = t
    t.start()


def status():
    return dict(_ST)


# ── stocker sur golem.fm (un GESTE) ───────────────────────────────────────────────────────────────

class UploadError(RuntimeError):
    def __init__(self, msg, status=None, detail=None):
        super().__init__(msg)
        self.status, self.detail = status, detail


def quotas():
    """Les places par section, lues chez golem.fm : `{songs:{used, limit}, standards:{…}}`, ou None hors ligne."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not token:
        return None
    st, data = golemfm._req("/api/ext/quotas", token=token, timeout=10)
    return data if st == 200 and isinstance(data, dict) else None


def upload(gid, mode="full", url=None, declared=False):
    """Envoie le `.golem` de `gid` à golem.fm (`POST /api/ext/golem`), complet ou léger. `url` = celle d'un job
    `golem-upload` (porte son id), sinon la route nue (geste fait ici). `declared` : l'utilisateur vient de déclarer,
    POUR CE DÉPÔT, que ses fichiers sont des copies licites (CGU de golem.fm §3.3, avis de l'avocat du 2026-10-20) —
    porté par `&declared=1`. Rend la réponse de golem.fm. Lève UploadError."""
    from . import golemfm, golem_pull, songs
    if mode not in ("full", "light"):
        raise UploadError("mode must be full or light")
    base, token = golemfm._cfg()
    if not (base and token):
        raise UploadError("not paired with golem.fm")
    path = path_of(gid)
    if not path:
        raise UploadError("no file on this golem for %s" % gid)
    url = url or "/api/ext/golem?mode=%s" % mode
    if declared:
        url += ("&" if "?" in url else "?") + "declared=1"
    if not url.startswith("/"):
        raise UploadError("unexpected url (must be a path on the paired server): %s" % url)
    tmp = light = None
    try:
        # UN .golem NE MÈNE À PERSONNE (song-sharing.md §2.8) : ce qui part n'est pas notre copie interne, c'est sa
        # copie de SORTIE — sans `repertoire` (le groupe, le slug), sans personnes ni captures privées, dates figées.
        # L'id ne change pas : golem.fm le relie dans NOTRE compte (§4.2 : un `ct:` ne sert qu'à ce qui circule).
        os.makedirs(C.SONGS_DIR, exist_ok=True)         # jamais à côté : un dossier de chansons ne s'écrit pas
        tmp = os.path.join(C.SONGS_DIR, ".out-%s.golem" % uuid.uuid4().hex[:8])
        try:
            G.outbound(path, tmp)
        except G.GolemError as e:
            raise UploadError(str(e)) from e
        send = tmp
        if mode == "light":
            light = os.path.join(C.SONGS_DIR, ".light-%s.golem" % uuid.uuid4().hex[:8])
            G.light_copy(tmp, light)
            send = light
        size = os.path.getsize(send)
        with open(send, "rb") as f:
            req = urllib.request.Request(base + url, data=f, method="POST")
            req.add_header("Authorization", "Bearer " + token)
            req.add_header("Content-Type", "application/zip")
            req.add_header("Content-Length", str(size))
            try:
                with urllib.request.urlopen(req, timeout=1800) as r:
                    res = json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                try:
                    body = json.loads(e.read() or b"{}")
                except ValueError:
                    body = {}
                det = body.get("detail", body) if isinstance(body, dict) else body
                code = det.get("error") if isinstance(det, dict) else det
                if e.code == 409 and isinstance(det, dict) and det.get("slug"):
                    res = {**det, "already_here": True}  # déjà chez lui : on se relie quand même (pas de doublon)
                else:
                    raise UploadError(_why(e.code, code, det), e.code, det) from e
    except urllib.error.URLError as e:
        raise UploadError("golem.fm unreachable (%s)" % e.reason) from e
    finally:
        for t in (tmp, light):
            if t and os.path.exists(t):
                os.unlink(t)
    slug, et = res.get("slug"), res.get("golem_etag")
    # la version FIGÉE par golem.fm, notée comme un tirage ; et la chanson reliée à son slug
    if slug and et:
        golem_pull._set_etag(slug, et)
    if slug and os.path.dirname(path) == os.path.abspath(C.SONGS_DIR):
        d = songs.load(gid)
        if d and not d.get("song_slug"):
            songs.update(gid, song_slug=slug)
    log.info("stocké sur golem.fm : %s (%s, %s) -> %s %s" % (gid, mode, "%.1f MB" % (size / 1e6), res.get("kind"), slug))
    request_publish()
    return res


def _why(status, code, det):
    """Le refus de golem.fm, dit en clair (anglais : il remonte à l'écran)."""
    if code == "rights_not_declared":
        # deux refus sous un code (golem.fm, 2026-10-21) : 422 = la case de CE dépôt manque ; 403 = le COMPTE doit
        # (re)faire sa déclaration sur golem.fm — la formule a changé (RIGHTS_VERSION 2), chaque compte redéclare une fois
        return ("tick the declaration before storing on golem.fm" if status == 422
                else "open golem.fm and confirm your rights declaration (its wording changed), then try again")
    if code == "quota_exceeded" and isinstance(det, dict):
        return "no room left in your %s on golem.fm (%s of %s used)" % (det.get("section", "library"), det.get("used"), det.get("limit"))
    return {"nothing_to_import": "golem.fm found nothing it can keep in this file",
            "bad_golem": "golem.fm refused the file",
            "album_not_yet": "albums cannot be stored on golem.fm yet",
            "unknown_job": "golem.fm no longer expects this upload",
            # déclaration sur l'honneur du COMPTE, faite sur golem.fm (2026-10-12) : rien à cocher ici
            "rights_not_declared": "open golem.fm and confirm your rights declaration, then try again"}.get(
        code, _their_message(det) or "golem.fm refused (%s %s)" % (status, code))


def _their_message(det):
    """Un code qu'on ne connaît pas : le `message` du detail de golem.fm est écrit pour l'utilisateur (2026-10-24)."""
    msg = det.get("message") if isinstance(det, dict) else None
    return msg.strip()[:200] if isinstance(msg, str) and msg.strip() else None


def golem_upload_job(job):
    """Le job `golem-upload` de golem.fm (geste fait là-bas) : `{id, category, mode, url, room, asked_at}`.
    Ack `{ok, kind, slug, golem_etag}` ; une erreur lève (le job répond l'erreur)."""
    gid = job.get("id")
    if not gid:
        raise RuntimeError("golem-upload: id required")
    res = upload(gid, job.get("mode") or "full", url=job.get("url"))
    return {"ok": True, "kind": res.get("kind"), "slug": res.get("slug"), "golem_etag": res.get("golem_etag")}
