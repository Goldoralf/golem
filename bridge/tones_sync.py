# SPDX-License-Identifier: GPL-3.0-or-later
"""Push de la tone library vers golem.fm — Phase 1 du contrat docs/private/exchanges/maestrium-tones-api.md.

Miroir SENS UNIQUE rack → golem.fm : la lib locale (tones-index.json + fichiers
assets/ + presets Vital) reste le runtime ; golem.fm reçoit les packs (méta) et
les blobs (identité = sha256) pour la copie durable hors-boîtier. Rien n'est
jamais supprimé côté golem.fm par ce worker (le superset survit au ménage local).

Séquence du worker (un seul à la fois, pattern _PUSH du vault) :
  1. build des packs depuis le catalogue (+ .vital) — uid `t3k:<id>` si l'entrée
     vient de TONE3000 (url), sinon `local:<id|slug>` ;
  2. PUT des packs dont le doc a changé depuis le dernier push (hash du doc
     mémorisé dans l'état local — 176 packs ne font pas 176 PUT à chaque fois) ;
  3. GET manifest → missing_blobs = la liste de travail ; upload streamé de ceux
     qu'on a sur disque (reprise sur erreur gratuite : re-sync = repartir de là) ;
  4. PUT rig-manifest : la photo de l'installé (badges « on rig » côté golem.fm).

Déclenchement : POST /api/tones-sync (manuel) + schedule() débouncé appelé par
store._write_json_atomic à chaque écriture du catalogue (download T3K, import,
IR, suppression) — silencieux si non appairé.

État local : library/catalog/.tones-sync.json (gitignoré, régénérable) =
cache sha256 par (mtime,size) — la lib pèse ~800 Mo, on ne re-hashe pas tout à
chaque sync — + hashes des docs déjà poussés + résultat du dernier sync.

Les photos d'amplis (images.json) sont des FICHIERS locaux, pas des URLs : pas
de photo_url dans les packs v1 (le contrat le permet).
"""
import hashlib, json, os, re, socket, threading, time, urllib.error, urllib.parse, urllib.request

from .rig import nam_architecture
from . import config as C
from .golog import get
from .golog import swallowed as _swallowed

log = get("tones-sync")

STATE_PATH = os.path.join(C.ROOT, "library", "catalog", ".tones-sync.json")
VITAL_DIRS = (("factory", os.path.join(C.ROOT, "library", "synth", "vital", "factory")),
              ("user", os.path.join(C.ROOT, "library", "synth", "vital", "user")))
KINDS = ("amp", "amp-cab", "cab", "pedal", "outboard", "synth", "kit", "loop", "experimental")
DEVICE = "golem-rack"
_TIMEOUT = 15            # méta ; les blobs ont leur propre timeout long

_ST = {"state": "idle", "msg": "", "error": None, "done": 0, "total": 0, "last": None}
_lock = threading.Lock()
_timer = None            # debounce de schedule()


def status():
    return dict(_ST)


# ── état local (cache sha + docs poussés) ────────────────────────────────────
def _load_state():
    try:
        d = json.load(open(STATE_PATH))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_state(d):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, STATE_PATH)


def _norm_base(url):
    """Clé serveur normalisée (au minimum : / final retiré) — http://x:5173 et
    http://x:5173/ ne doivent pas faire deux entrées."""
    return (url or "").strip().rstrip("/")


def _pushed_for(state):
    """Le sous-dict des docs poussés POUR LE SERVEUR COURANT.

    Bug corrigé (reproduit le 2026-07-19) : `pushed` était un dict À PLAT
    {uid: hash}, non lié au serveur destinataire. Après bascule de base_url
    (dev ⇄ prod, migration…), le rack croyait tout déjà poussé et le nouveau
    serveur ne recevait presque rien — perte de données SILENCIEUSE.

    Nouvelle forme : pushed = {base_url_normalisée: {uid: hash}}. Un fichier à
    l'ancienne forme est JETÉ (traité comme vide) : on ne peut pas l'attribuer
    à un serveur sans risquer de reproduire le bug. Coût : un re-push complet,
    une fois — le sens d'erreur sûr. `sha_cache` (dépend des FICHIERS, pas du
    serveur) n'est pas touché.
    """
    base, _tok = _cfg()
    key = _norm_base(base)
    pushed = state.get("pushed")
    is_new_form = isinstance(pushed, dict) and all(isinstance(v, dict) for v in pushed.values())
    if not is_new_form:
        if isinstance(pushed, dict) and pushed:
            log.info(f"état 'pushed' à l'ancienne forme ({len(pushed)} entrées) — "
                     "jeté (ré-indexation par serveur, re-push complet une fois)")
        state["pushed"] = {}
    return state["pushed"].setdefault(key, {})


def _sha256_cached(path, cache):
    """sha256 d'un fichier, mémoïsé par (mtime, size) — clé = chemin relatif au repo."""
    rel = C.rel(path)
    st = os.stat(path)
    hit = cache.get(rel)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    cache[rel] = [st.st_mtime, st.st_size, h.hexdigest()]
    return cache[rel][2]


def _wire_rel(path):
    """Les chemins extra.rel échangés avec golem.fm utilisent toujours '/'."""
    return str(path).replace("\\", "/") if path is not None else None


# ── construction des packs depuis la lib locale ──────────────────────────────
IR_EXT = (".wav", ".flac")
NAM_EXT = (".nam", ".aidax")


def family_of(entry):
    """La famille d'une capture (guitar | bass) — LA règle du sélecteur (designer-drawer.famOf,
    docs/patches.md §12) : le champ `family` (override manuel de Library ▸ Amps) sinon l'heuristique
    tag/style `bass`. golem.fm la reçoit telle quelle au lieu de la deviner depuis les tags
    (Library golem.fm restructurée par rôle, 2026-09-14). None pour ce qui n'est pas une capture
    d'instrument (outboard, synth, kit…)."""
    if entry.get("gear") not in ("amp", "amp-cab", "cab", "pedal"):
        return None
    fam = entry.get("family")
    if fam in ("guitar", "bass"):
        return fam
    tags = [str(t).lower() for t in (entry.get("tags") or [])]
    named = re.search(r"\bbass\b", str(entry.get("amp") or entry.get("title") or ""), re.I)   # pas Bassman, pas Bassbreaker
    return "bass" if ("bass" in tags or str(entry.get("style") or "").lower() == "bass" or named) else "guitar"


def kind_of(gear, paths):
    """La NATURE d'un pack se LIT dans ses fichiers, elle ne se déclare pas (CLAUDE.md « bonne forme,
    mauvaise nature », même règle que tones_jobs._entry_from_pack à l'installation) : des IR
    (.wav/.flac) font un `cab` quoi que dise `gear` ; un `cab` déclaré dont les fichiers sont des
    captures est un `amp-cab`. `experimental` ne reste que quand les fichiers ne disent rien —
    deux packs d'IR y dormaient (t3k:64815, t3k:64921 ; retour golem.fm 2026-09-14)."""
    exts = {os.path.splitext(p)[1].lower() for p in paths}
    if exts and exts <= set(IR_EXT):
        return "cab"
    if exts and exts <= set(NAM_EXT):
        if gear in ("amp", "amp-cab", "pedal", "outboard"):
            return gear
        return "amp-cab"                                   # déclaré cab (ou rien) : deux .nam, faute de mieux
    return gear if gear in KINDS else "experimental"


def _uid(entry):
    eid = entry.get("id")
    if "tone3000.com" in (entry.get("url") or ""):
        return f"t3k:{eid}"
    return f"local:{eid if isinstance(eid, str) else (entry.get('slug') or eid)}"


def _provenance(entry):
    """UNE CAPTURE DE PLUGIN RESTE PRIVÉE (2026-10-11 ; accordé avec golem.fm) : elle remonte dans la bibliothèque
    du compte et se prête au groupe, jamais au store. Le pack dit d'où elle vient — `provenance` (pas `origin`, qui est
    déjà une CHAÎNE sur les patches de golem.fm) — et `private: true` ; côté serveur c'est un cliquet : un pack de
    provenance plugin-capture est privé même sans le champ, et le reste si un push l'oublie."""
    cap = entry.get("capture") if isinstance(entry.get("capture"), dict) else None
    if not cap and entry.get("source_group") != "plugin-capture" and not entry.get("private"):
        return {}
    import sys as _sys
    from .store import brand_str                       # local, comme dans build_packs
    os_name = {"win32": "windows", "linux": "linux", "darwin": "darwin"}.get(_sys.platform, _sys.platform)
    prov = {"kind": "plugin-capture", "plugin": (cap or {}).get("plugin") or "", "vendor": brand_str(entry.get("brand")) or "",
            "os": os_name, "at": (cap or {}).get("at") or ""}
    return {"provenance": prov, "private": True}


def build_packs(cache):
    from .store import brand_str                       # local : store n'est pas un import de module ici
    """(packs, blob_map {sha256: chemin absolu}) depuis tones-index.json + .vital.
    Les modèles dont le fichier manque sur disque sont ignorés (pack partiel OK :
    le blob restera dans missing_blobs tant qu'il n'existe nulle part)."""
    packs, blob_map = [], {}
    cat = {}
    try:
        cat = json.load(open(C.CATALOG))
    except Exception as _e:
        _swallowed(_e)
    for entry in (cat.get("tones") or []):
        gear = entry.get("gear")
        assets = []
        paths = []
        for m in (entry.get("models") or []):
            path = os.path.join(C.ROOT, m.get("file") or "")
            if not os.path.isfile(path):
                continue
            paths.append(path)
            sha = _sha256_cached(path, cache)
            blob_map[sha] = path
            assets.append({
                "sha256": sha,
                "filename": os.path.basename(path),
                "name": m.get("name") or os.path.basename(path),
                "bytes": os.path.getsize(path),
                "format": entry.get("format") or "nam",
                # rel = où reposer le fichier à la restauration ; le reste = ce que
                # le catalogue local doit retrouver (opaque pour golem.fm)
                "extra": {"rel": _wire_rel(m.get("file")), "arch": m.get("arch"), "size": m.get("size"),
                          "model_id": m.get("id"),
                          # le format LU dans les octets (`architecture` du .nam), pas déclaré : golem.fm
                          # juge par lui ce qu'un golem cible peut jouer (caps.nam_unreadable)
                          "nam_arch": nam_architecture(path) if path.lower().endswith(".nam") else None},
            })
        if not assets:
            continue
        kind = kind_of(gear, paths)
        if kind != gear:
            log.info(f"pack {_uid(entry)} : déclaré « {gear} », ses fichiers disent « {kind} »")
        packs.append({
            "uid": _uid(entry), "kind": kind,
            # famille d'instrument (guitar | bass) : ce que la page Amps affiche, override compris
            **({"family": family_of({**entry, "gear": kind})} if kind in ("amp", "amp-cab", "cab", "pedal") else {}),
            # affichage = nom du matériel (entry.amp posé par la classif T3K), pas le contributeur
            "title": entry.get("amp") or entry.get("title") or entry.get("slug") or _uid(entry),
            "brand": brand_str(entry.get("brand")),
            "creator": entry.get("creator") or "",
            "url": entry.get("url") or "",
            "tags": entry.get("tags") or [],
            "style": entry.get("style") or "",
            "extra": {"t3k_title": entry.get("title"), "slug": entry.get("slug"),
                      "makes": entry.get("makes"), "catalog_id": entry.get("id")},
            "assets": assets,
            **_provenance(entry),
        })
    # kits de pads (docs/blocks-doctrine.md) : un pack par kit = son JSON + ses samples,
    # chaque asset porte extra.rel -> le job install les repose tels quels (kind "kit"
    # = pas d'entrée tones-index à la restauration, comme synth)
    from . import kits as _kits
    for k in _kits.list_kits():
        assets = []
        kpath = os.path.join(_kits.KITS_DIR, f"{k['id']}.json")
        # une batterie IMPORTÉE (kit_import, 2026-10-11) n'envoie que sa fiche : la CARTE — nom, moteur,
        # pièces, taille — jamais ses échantillons (des gigaoctets, « this golem only »)
        imp = k.get("imported") if isinstance(k.get("imported"), dict) else None
        for path, rel in [(kpath, C.rel(kpath))] + [
                (os.path.join(C.ROOT, p["sample"]), p["sample"])
                for p in k.get("pads", []) if p.get("sample")]:
            if not os.path.isfile(path):
                continue
            sha = _sha256_cached(path, cache)
            blob_map[sha] = path
            assets.append({"sha256": sha, "filename": os.path.basename(path),
                           "name": os.path.splitext(os.path.basename(path))[0],
                           "bytes": os.path.getsize(path),
                           "format": "kit" if path == kpath else "sample",
                           "extra": {"rel": _wire_rel(rel)}})
        if assets:
            # extra.engine (2026-09-14) : rs5k = pads (« Kits » chez golem.fm), sfz/avldrums/drumgizmo
            # = batteries (« Drums », lecture seule — jamais importées depuis le web)
            engine = k.get("engine") if k.get("engine") in _kits.ENGINES else "rs5k"
            extra = {"kit_id": k["id"], "engine": engine, "factory": bool(k.get("factory"))}
            if imp:
                extra.update({"card": True, "imported": True, "bytes": imp.get("bytes"), "files": imp.get("files"),
                              "pieces": sorted((k.get("notes") or {}).keys()), "mics": len(k.get("mix") or []) or None,
                              "sample_rate": imp.get("sample_rate"), "bits": imp.get("bits"),
                              # affichage seulement : golem.fm identifie le rack par le jeton qui pousse (accord 2026-10-11)
                              "installed_on": socket.gethostname()})
            packs.append({"uid": f"local:kit-{k['id']}", "kind": "kit",
                          "title": k.get("name") or k["id"], "brand": "GoleM",
                          "creator": "user", "url": "", "tags": ["kit", "pads" if engine == "rs5k" else "drums"] + (["card"] if imp else []),
                          "style": "", "extra": extra, "assets": assets})
    # ⚠ LE PACK `local:loops` A ÉTÉ RETIRÉ (2026-09-07, lot B — docs/message-golemfm-
    # ranger-prises.md §0.1). Il poussait TOUS les .wav de recordings/ vers le store de
    # TONES, comme des boucles de bibliothèque, **sans regarder le tag de groupe** : une
    # prise de répète d'un groupe serait partie dans le compte, hors de son espace, sans
    # que personne l'ait demandé. Il n'avait jamais tourné sur cette machine — c'était une
    # fuite en puissance, pas une fuite. Les prises montent désormais par le canal
    # recordings (bridge/uploader.py), qui lit le tag et respecte le quota.
    # samples one-shot du bloc `sample` (lane config Players) : UN pack, un asset par .wav
    # d'assets/samples/. extra.rel = le chemin QUE le preset référence (params.samples) et
    # où le job install repose le fichier (kind "sample", comme kit/loop : pas de tones-index).
    smp_dir = os.path.join(C.ROOT, "assets", "samples")
    if os.path.isdir(smp_dir):
        from . import kits as _k
        kinds = {_wire_rel(s["file"]): s for s in _k.list_samples()}
        assets = []
        for fn in sorted(os.listdir(smp_dir)):
            if not fn.lower().endswith((".wav", ".flac", ".ogg", ".aif", ".aiff")):
                continue
            path = os.path.join(smp_dir, fn)
            sha = _sha256_cached(path, cache)
            blob_map[sha] = path
            rel = _wire_rel(os.path.join("assets", "samples", fn))
            # extra.kind (2026-09-15) : short (one-shot) | song (stem d'un backing local) — golem.fm
            # range pareil (« short » / « songs ») et le renvoie dans ses sample-packs
            assets.append({"sha256": sha, "filename": fn, "name": os.path.splitext(fn)[0],
                           "bytes": os.path.getsize(path), "format": "sample",
                           "extra": {"rel": rel, "kind": (kinds.get(rel) or {}).get("kind") or "short",
                                     "loudness_db": (kinds.get(rel) or {}).get("loudness_db")}})
        if assets:
            packs.append({"uid": "local:samples", "kind": "sample",
                          "title": "One-shot samples", "brand": "GoleM",
                          "creator": "user", "url": "", "tags": ["sample", "one-shot"],
                          "style": "", "extra": {}, "assets": assets})
    # GROOVES (2026-10-14, accord golem.fm) : UN pack par groove de la bibliothèque — `local:groove-<id>`, kind
    # "groove", un asset = le .mid. Sans eux, un preset partagé partait sans les grooves de son bloc Drum Machine
    # (preset_export ne pouvait pas les citer en deps). Seuls les grooves de library/grooves/ (la liste de l'écran) :
    # les packs commerciaux rangés sous library/grooves/packs/ ne sont jamais publiés. Les grooves d'usine portent
    # extra.factory (golem.fm ne les transfère pas) ET leur sha (un golem resté sur une ancienne version vérifie).
    from . import grooves as _gr
    for g in _gr.list_grooves():
        path = os.path.join(C.ROOT, g["file"])
        if not os.path.isfile(path):
            continue
        sha = _sha256_cached(path, cache)
        blob_map[sha] = path
        rel = _wire_rel(g["file"])
        fac = bool(g.get("factory"))
        packs.append({"uid": f"local:groove-{g['id']}", "kind": "groove",
                      "title": g.get("name") or g["id"], "brand": "GoleM",
                      "creator": "factory" if fac else "user", "url": "",
                      "tags": ["groove"] + (["factory"] if fac else []), "style": g.get("genre") or "",
                      "extra": {"groove_id": g["id"], "rel": rel, "genre": g.get("genre"), "tempo": g.get("tempo"),
                                "bars": g.get("bars"), "pack": g.get("pack"), "factory": fac},
                      "assets": [{"sha256": sha, "filename": os.path.basename(path), "name": g.get("name") or g["id"],
                                  "bytes": os.path.getsize(path), "format": "mid", "extra": {"rel": rel}}]})
    for label, d in VITAL_DIRS:
        if not os.path.isdir(d):
            continue
        assets = []
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".vital"):
                continue
            path = os.path.join(d, fn)
            sha = _sha256_cached(path, cache)
            blob_map[sha] = path
            assets.append({"sha256": sha, "filename": fn, "name": fn[:-6].replace("_", " "),
                           "bytes": os.path.getsize(path), "format": "vital",
                           "extra": {"rel": _wire_rel(C.rel(path)), "meta": _vital_meta(path)}})
        if assets:
            packs.append({"uid": f"local:synth-vital-{label}", "kind": "synth",
                          "title": f"Vital presets ({label})", "brand": "Vital",
                          "creator": "user", "url": "", "tags": ["synth", "vital", label],
                          "style": "", "extra": {}, "assets": assets})
    return packs, blob_map


def _vital_meta(path):
    """Ce que le .vital dit de lui (docs/preset-preview.md §9, demande golem.fm 2026-11-14) : golem.fm ne lit le contenu
    que des presets importés chez lui ; il lit ceux-ci ici plutôt que de deviner. {preset_name, style, author, comments,
    macros: [4 noms]} ; un champ que le fichier ne donne pas reste vide."""
    from . import vital
    name, author, style, macros, _vals = vital._meta(path, os.path.basename(path)[:-6].replace("_", " "))
    try:
        comments = str((json.load(open(path, encoding="utf-8")) or {}).get("comments") or "")
    except (OSError, ValueError, AttributeError):
        comments = ""
    return {"preset_name": name, "style": style, "author": author, "comments": comments, "macros": list(macros)}


def _doc_hash(pack):
    return hashlib.sha256(json.dumps(pack, sort_keys=True).encode()).hexdigest()


def _rig_state_doc():
    """Snapshot LISIBLE de l'état jouable (presets + setlists) pour la page
    /golem/rig de golem.fm — lecture seule là-bas, l'édition reste ici.
    Les blocs NAM portent le nom du matériel capturé (pas le contributeur) et
    l'arch (badge A2) du modèle effectivement résolu (épinglé ou models[0])."""
    import glob
    cat = {}
    try:
        cat = {str(t.get("id")): t for t in (json.load(open(C.CATALOG)) or {}).get("tones", [])}
    except Exception as _e:
        _swallowed(_e)

    def _block_out(b):
        out = {"type": b.get("type")}
        if b.get("label"):
            out["label"] = b["label"]
        # blocs-instruments de la lane Keys : montrer le contenu référencé (doctrine)
        if b.get("type") == "pads":
            from . import kits as _k
            k = _k.get_kit((b.get("params") or {}).get("kit") or "")
            out["capture"] = f"Pads · {k['name']}" if k else "Pads"
        if b.get("type") == "vital" and (b.get("params") or {}).get("preset"):
            out["capture"] = f"Vital · {b['params']['preset']}"
        if b.get("type") == "looper":
            out["label"] = "Looper"
        t = cat.get(str(b.get("ref", "")).split("/")[-1])
        if t:
            out["capture"] = t.get("amp") or t.get("title")
            models = t.get("models") or []
            cur = next((m for m in models if str(m.get("id")) == str(b.get("model"))), None) \
                if b.get("model") is not None else (models[0] if models else None)
            if cur and cur.get("arch"):
                out["arch"] = cur["arch"]
        return out

    def _iter_blocks(p):
        # LOT 4 : toutes les lanes (v2 ou legacy), même vitrine pour toutes
        from .store import all_blocks
        for b, lane in all_blocks(p):
            if lane not in ("gen", "rec", "arr"):
                yield b
        # presets en forme paths (tests, presets bas niveau) : chain + branches de split
        for path in p.get("paths") or []:
            for node in path.get("chain") or []:
                if isinstance(node, dict) and node.get("split"):
                    for br in node["split"].get("branches") or []:
                        yield from br.get("blocks") or []
                elif isinstance(node, dict):
                    yield node

    presets = []
    for path in sorted(glob.glob(os.path.join(C.ROOT, "presets", "*.json"))):
        if os.path.basename(path).startswith("."):
            continue
        try:
            p = json.load(open(path))
        except Exception:
            continue
        if not isinstance(p, dict) or not p.get("id"):
            continue
        presets.append({
            "id": p["id"], "name": p.get("name") or p["id"], "style": p.get("style"),
            "bpm": p.get("bpm"),
            "scenes": [{"id": s.get("id"), "name": s.get("name")} for s in p.get("scenes") or []],
            "blocks": [_block_out(b) for b in _iter_blocks(p) if b.get("type")],
        })
    setlists = []
    for path in sorted(glob.glob(os.path.join(C.ROOT, "setlists", "*.json"))):
        try:
            sl = json.load(open(path))
        except Exception:
            continue
        # `kind` sur CHAQUE setlist (docs/patches.md §9 bis-8) : golem.fm refuse de pousser sur une
        # bank de sons, et ne la mirroire pas avant sa S1 ; une liste d'avant les banks est « songs »
        setlists.append({"id": sl.get("id"), "name": sl.get("name") or sl.get("id"),
                         "fcb": bool(sl.get("fcb")), "presets": sl.get("presets") or [],
                         "kind": sl.get("kind") if sl.get("kind") in ("songs", "sounds") else "songs"})
    return {"device": DEVICE, "presets": presets, "setlists": setlists}


# ── HTTP (Bearer gmt_, conventions /api/ext — méthode PUT nécessaire, d'où
#    un helper local plutôt que golemfm._req qui ne fait que GET/POST) ─────
def _cfg():
    from .golemfm import _cfg as m_cfg
    return m_cfg()


def _req(method, path, body=None, raw_file=None, timeout=_TIMEOUT):
    """Renvoie (status, data). raw_file = chemin d'un fichier à streamer en corps
    brut (jamais en RAM). Ne lève jamais : (0, str(err)) si injoignable."""
    base, token = _cfg()
    if not base or not token:
        return 0, "not paired"
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    f = None
    try:
        if raw_file is not None:
            size = os.path.getsize(raw_file)
            req.add_header("Content-Type", "application/octet-stream")
            req.add_header("Content-Length", str(size))
            f = open(raw_file, "rb")
            req.data = f                                   # streamé par urllib
        elif body is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(body).encode()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        from .golemfm import http_error_text      # un seul lecteur des corps d'erreur de golem.fm
        return e.code, http_error_text(e)
    except Exception as e:
        return 0, str(e)
    finally:
        if f is not None:
            f.close()


# ── worker ───────────────────────────────────────────────────────────────────
def _worker():
    try:
        # la file de jobs d'abord : une install fraîche entre dans CE push
        try:
            from . import tones_jobs
            tones_jobs.process()
        except Exception as e:
            log.warning(f"jobs: {e}")

        state = _load_state()
        cache = state.setdefault("sha_cache", {})
        pushed = _pushed_for(state)        # indexé PAR SERVEUR (jamais partagé entre destinataires)

        _ST.update(state="build", msg="hashing library…")
        packs, blob_map = build_packs(cache)
        _save_state(state)                                 # le cache sha vaut d'être gardé même si le réseau tombe
        # UN PRÊT NE REMONTE JAMAIS (docs/library-loans.md §4) : sinon il entrerait dans la bibliothèque
        # du membre, sous SON quota — une copie en douce. Pack entier par uid, fichier d'un pack agrégé
        # (samples, Vital) par sha256 ; ces sha ne sont pas non plus téléversés.
        from . import loans
        packs, n_lent = loans.filter_packs(packs, blob_map)
        if n_lent:
            log.info(f"{n_lent} élément(s) prêté(s) gardé(s) hors de la synchro")

        changed = [p for p in packs if pushed.get(p["uid"]) != _doc_hash(p)]
        _ST.update(state="packs", msg=f"pushing {len(changed)} pack(s)…",
                   done=0, total=len(changed))
        for i, p in enumerate(changed):
            st, data = _req("PUT", "/api/ext/tones/packs/" + urllib.parse.quote(p["uid"]),
                            body=p)
            if st == 400 and p["kind"] in ("kit", "loop", "sample", "groove"):   # groove : 2026-10-14, golem.fm l'ajoute
                # serveur pas encore à jour (kind inconnu) : on saute SANS
                # marquer poussé — re-tenté au sync suivant, après déploiement
                log.warning(f"pack {p['uid']} sauté (serveur sans ce kind)")
                _ST.update(done=i + 1)
                continue
            if st != 200:
                raise RuntimeError(f"pack {p['uid']}: {st or 'unreachable'} {data}")
            pushed[p["uid"]] = _doc_hash(p)
            _ST.update(done=i + 1)
        _save_state(state)

        st, manifest = _req("GET", "/api/ext/tones/manifest")
        if st != 200:
            raise RuntimeError(f"manifest: {st or 'unreachable'} {manifest}")
        # le registre des prêts suit le manifeste : disponible, incomplet, redevenu nôtre, retiré (jamais effacé)
        try:
            loans.refresh(manifest)
        except Exception as e:
            log.warning(f"registre des prêts non relu : {e}")
        missing = [s for s in manifest.get("missing_blobs", []) if s in blob_map]
        _ST.update(state="blobs", msg=f"uploading {len(missing)} file(s)…",
                   done=0, total=len(missing))
        for i, sha in enumerate(missing):
            path = blob_map[sha]
            st, data = _req("POST",
                            "/api/ext/tones/assets?sha256=%s&filename=%s"
                            % (sha, urllib.parse.quote(os.path.basename(path))),
                            raw_file=path, timeout=300)
            if st == 507:
                # quota serveur atteint (les .wav de perf sont gros) : on saute,
                # le blob reste en missing_blobs et sera re-tenté plus tard
                log.warning(f"blob {os.path.basename(path)} sauté (quota 507)")
                _ST.update(done=i + 1)
                continue
            if st != 200:
                raise RuntimeError(f"blob {os.path.basename(path)}: {st or 'unreachable'} {data}")
            _ST.update(done=i + 1)

        if missing:                                        # re-lit le manifest APRÈS les uploads
            st, m2 = _req("GET", "/api/ext/tones/manifest")
            if st == 200:
                manifest = m2

        blobs_bytes = sum(os.path.getsize(p) for p in blob_map.values())
        rig = {"device": DEVICE, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "packs": [p["uid"] for p in packs], "blobs_bytes": blobs_bytes}
        st, data = _req("PUT", "/api/ext/tones/rig-manifest", body=rig)
        if st != 200:
            raise RuntimeError(f"rig-manifest: {st or 'unreachable'} {data}")

        # snapshot presets/banks (avenant M2 — page /golem/rig). Best-effort :
        # un serveur pas encore à jour (404) ne fait pas échouer le sync.
        try:
            st, data = _req("PUT", "/api/ext/golem/state", body=_rig_state_doc())
            if st not in (200, 404):
                log.warning(f"rig-state: {st} {data}")
        except Exception as e:
            log.warning(f"rig-state: {e}")

        # le catalogue des patches suit le sync (annexe 1, message « ranger les prises ») :
        # best-effort, débouncé, un serveur sans la route (404) reste silencieux.
        try:
            from . import golemfm as _maes
            _maes.push_patches(delay=0.5)
        except Exception as e:
            log.warning(f"patches: {e}")

        # RATTRAPAGE des presets (§6) : ce qui a changé de son pendant que le rack était hors
        # ligne part ici. La publication au fil de l'eau vit sur la sauvegarde ; cette passe
        # est le filet, parce qu'un rack de répète passe des soirées entières sans réseau.
        try:
            publish_dirty()
        except Exception as e:
            log.warning(f"presets: {e}")

        state["last"] = {"at": rig["at"], "packs": len(packs), "pushed": len(changed),
                         "uploaded": len(missing), "rev": manifest.get("rev"),
                         "remote_bytes": manifest.get("bytes")}
        _save_state(state)
        _ST.update(state="done", msg=f"{len(packs)} packs · {len(missing)} file(s) uploaded",
                   error=None, last=state["last"])
    except Exception as e:
        _ST.update(state="error", error=str(e), msg=str(e))
        log.error(f"KO: {e}")


def start_sync():
    """Lance un sync (thread démon). {"ok": False} si déjà en cours ou non appairé."""
    base, token = _cfg()
    if not base or not token:
        return {"ok": False, "error": "not paired with golem.fm (Settings ▸ Connect ▸ golem.fm)"}
    with _lock:
        if _ST["state"] in ("build", "packs", "blobs"):
            return {"ok": False, "error": "sync already running"}
        _ST.update(state="build", msg="starting…", error=None, done=0, total=0)
    threading.Thread(target=_worker, daemon=True).start()
    return {"ok": True}


def schedule(delay=20.0):
    """Sync auto débouncé — appelé à chaque écriture du catalogue. Le délai laisse
    une rafale de mutations (install T3K multi-modèles) ne coûter qu'UN sync.
    No-op silencieux si non appairé."""
    global _timer
    base, token = _cfg()
    if not base or not token:
        return
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(delay, start_sync)
        _timer.daemon = True
        _timer.start()


# ── publication AU FIL DE L'EAU (docs/private/exchanges/message-maestrium-ranger-prises.md §6) ───────────────
# La condition posée le 2026-09-02 est levée : golem.fm a vérifié route par route qu'un preset
# poussé est PRIVÉ au compte (`GolemPresetDoc` scopé par user_id partout, le « Store » est un
# objet séparé). Un preset nommé « ZZ UX Test » ne sera donc vu de personne, et la cadence
# automatique est saine. Sans elle, `publish_preset` restait une route sans bouton que
# personne n'appelait — donc un miroir vide côté web.
_PUBLISHED = os.path.join(C.ROOT, "library", "catalog", ".published.json")
_pub_timers = {}
_pub_lock = threading.Lock()


def _published_all():
    """{base_url_normalisée: {pid: empreinte}}. INDEXÉ PAR SERVEUR (bug du 2026-09-29, le même que celui
    de `pushed` corrigé le 2026-07-19) : le map était à plat, donc après le passage de la base de DEV à
    la prod, un preset déjà publié vers la dev passait pour publié en prod — `1983` n'y serait jamais
    arrivé tant que son son ne changeait pas. Un fichier à l'ancienne forme est JETÉ : on ne peut pas
    l'attribuer à un serveur, et tout republier une fois est le sens d'erreur sûr."""
    try:
        d = json.load(open(_PUBLISHED))
    except Exception:
        return {}
    if isinstance(d, dict) and all(isinstance(v, dict) for v in d.values()):
        return d
    if d:
        log.info(f"presets publiés à l'ancienne forme ({len(d)}) — jetés (ré-indexation par serveur)")
    return {}


def _published_map():
    """Les presets publiés vers le SERVEUR COURANT : {pid: empreinte}."""
    return _published_all().get(_norm_base(_cfg()[0]), {})


def _mark_published(pid, fp):
    from . import store
    with _pub_lock:
        d = _published_all()
        d.setdefault(_norm_base(_cfg()[0]), {})[pid] = fp
        store._write_json_atomic(_PUBLISHED, d)


def needs_publish(pid, preset=None):
    """Le preset a-t-il changé DE SON depuis sa dernière publication ? On compare l'empreinte
    `preset_export.fingerprint`, qui ignore preview/colors/anims : renommer une couleur de
    tuile ne renvoie rien, changer un ampli si. None (preset absent) = non."""
    from . import preset_export, store
    p = preset if preset is not None else store.load_preset(pid)
    if not p:
        return False
    return _published_map().get(pid) != preset_export.fingerprint(p)


def publish_soon(pid, delay=5.0, preset=None):
    """Publie ce preset dans `delay` secondes, si son empreinte a bougé. DÉBOUNCÉ PAR PRESET :
    le Designer sauvegarde à chaque geste, et une rafale de réglages ne doit coûter qu'un POST.

    Best-effort de bout en bout : non appairé -> rien ; asset non résolu sur le rack -> sauté
    et JOURNALISÉ (jamais bloquant : un preset qui référence une capture absente n'est pas une
    panne, c'est un preset en cours) ; serveur injoignable -> on retente au prochain
    tones-sync, qui repasse sur tout ce qui est en retard."""
    if not needs_publish(pid, preset):
        return

    def worker():
        from . import store
        base, token = _cfg()
        if not base or not token:
            return
        r = publish_preset(pid)
        if r.get("ok"):
            p = store.load_preset(pid)
            if p:
                from . import preset_export
                _mark_published(pid, preset_export.fingerprint(p))
            log.info(f"preset « {pid} » publié ({r.get('deps')} deps, {r.get('uploaded')} blob(s))")
        elif r.get("unresolved"):
            log.info(f"preset « {pid} » non publié : {len(r['unresolved'])} asset(s) non résolu(s) "
                     f"sur le rack — normal tant qu'il est en cours")
        else:
            log.warning(f"preset « {pid} » non publié : {r.get('error')}")

    with _pub_lock:
        t = _pub_timers.get(pid)
        if t is not None:
            t.cancel()
        t = threading.Timer(delay, worker)
        t.daemon = True
        _pub_timers[pid] = t
        t.start()


def publish_dirty():
    """La passe de RATTRAPAGE, à la fin de chaque tones-sync : tout ce qui a changé de son
    pendant que le rack était hors ligne part enfin. Rend le nombre de presets traités."""
    from . import store
    n = 0
    for p in store.load_presets():
        pid = p.get("id")
        if pid and needs_publish(pid, p):
            publish_soon(pid, delay=0.5 + n * 2, preset=p)   # étalé : on ne rafale pas le serveur
            n += 1
    if n:
        log.info(f"publication au fil de l'eau : {n} preset(s) en retard")
    return n


def publish_preset(pid):
    """Publie un preset COMPLET vers le Store golem.fm (Sprint 5.A.4).
    1) refuse si un asset est non résoluble sur le rack (miroir de la validation
       golem.fm « capture/kit manquant ») ;
    2) garantit les blobs `source=golemfm` sur le serveur (upload des manquants
       — les `source=t3k` sont tirés du compte TONE3000 du rack à l'install) ;
    3) POST le doc natif + manifest de deps à POST /api/ext/golem/presets.
    Ne lève jamais : renvoie {ok, ...} / {ok:False, error, ...}."""
    from . import preset_export, store
    # L'ESSAI n'est pas un preset (docs/patches.md §19) : load_preset le sert sous son id réservé,
    # donc sans cette garde POST /api/preset/sandbox-try/publish l'enverrait au miroir golem.fm —
    # un preset sans fichier, entré une fois là-bas, y resterait pour toujours (question golem.fm,
    # 2026-09-12). Un id réservé d'un côté n'est réservé de l'autre que si quelqu'un l'écrit.
    if pid == store.SANDBOX_TRY_ID or str(pid).startswith("patch:"):     # un patch se publie comme PATCH
        return {"ok": False, "error": "the trial is not a preset — save it first"}
    if pid == store.KARAOKE_ID:                     # le preset volatil du karaoké (docs/karaoke.md) : jamais publié
        return {"ok": False, "error": "the karaoke is not a preset"}
    out, dep_blobs = preset_export.build_export(pid)
    if out is None:
        return {"ok": False, "error": "preset not found"}
    if out.get("unresolved"):
        return {"ok": False, "error": "unresolved assets on rack", "unresolved": out["unresolved"]}

    # UN PRÊT NE SE PUBLIE PAS (docs/library-loans.md §4) : on copierait la capture du prêteur dans le vault
    # du membre ET on la publierait sous son nom. golem.fm pose la même garde (`not_lent`, 422).
    from . import loans
    lent = loans.lent_deps(out.get("deps"))
    if lent:
        x = lent[0]
        return {"ok": False, "error": f"uses {x['title']}" + (f", lent by {x['owner']}" if x.get("owner") else ", a lent sound")
                                      + " — keep a copy first", "lent": lent}
    # les deps servies par le store golem.fm (« maestrium » = son ancien nom, encore porté par des docs publiés)
    from .preset_export import STORE_SOURCES
    maes = {d["sha256"] for d in out["deps"] if d.get("source") in STORE_SOURCES}
    uploaded = 0
    if maes:
        st, manifest = _req("GET", "/api/ext/tones/manifest")
        if st != 200:
            return {"ok": False, "error": "manifest: %s" % (st or "unreachable"), "detail": manifest}
        for sha in [s for s in (manifest.get("missing_blobs") or []) if s in maes and s in dep_blobs]:
            path = dep_blobs[sha]
            st, data = _req("POST", "/api/ext/tones/assets?sha256=%s&filename=%s"
                            % (sha, urllib.parse.quote(os.path.basename(path))), raw_file=path)
            if st != 200:
                return {"ok": False, "error": "asset upload %s: %s" % (sha[:12], st or "unreachable"),
                        "detail": data}
            uploaded += 1

    # ⚠ le récepteur (golem_module.ext_push_presets) attend une LISTE d'enveloppes
    # `{presets: [...]}` et répond 400 « Body must carry a 'presets' list » à une enveloppe nue —
    # ce que cette fonction envoyait jusqu'au 2026-09-02. Il compte les enveloppes malformées
    # en `skipped` : un skipped ici, c'est NOTRE doc qui est refusé, on le dit.
    st, data = _req("POST", "/api/ext/golem/presets", body={"presets": [out]})
    if st == 200:
        if isinstance(data, dict) and data.get("skipped"):
            return {"ok": False, "error": "server skipped the preset envelope", "detail": data}
        return {"ok": True, "published": pid, "deps": len(out["deps"]), "uploaded": uploaded}
    return {"ok": False, "error": "POST /api/ext/golem/presets: %s" % (st or "unreachable"),
            "detail": data}
