# SPDX-License-Identifier: GPL-3.0-or-later
"""Consommation des jobs golem.fm → rack (contrat docs/private/exchanges/maestrium-tones-api.md §4.2).

Le module GoleM de golem.fm met des actions en FILE ; le rack les tire ici et
les acquitte — jamais de push serveur, le rack reste maître de son disque :
  - install <uid>  : télécharge les blobs du pack (GET /assets/<sha>, reposés à
    leur chemin d'origine `extra.rel`, sinon assets/…/golemfm/) et upsert
    l'entrée au catalogue local. L'écriture du catalogue déclenche le push
    debounced habituel → le rig-manifest reflète l'install au sync suivant.
  - remove <uid>   : refuse si des presets/templates référencent le tone
    (ack ok:false avec la liste — pas de casse silencieuse), sinon réutilise le
    flux corbeille de routes_content.amp_delete (assets/.trash/<ts>/).
  - recall <preset> [scene] : _do_recall du bridge (avenant M3).
  - fetch-backup <backup_id> : tire un zip du vault dans backups/ (la restauration
    reste un geste sur l'écran du rack).
  - t3k-install <tone_id> : installe un tone TONE3000 avec le compte du rack (M4).
  - push-library : relance un tones-sync complet (bouton « rafraîchir » de la page
    /golem/library de golem.fm). Ack au DÉMARRAGE du sync (start_sync est
    asynchrone) ; un sync déjà en cours = ok aussi (le refresh voulu arrive).

Déclenchement : au début de chaque tones-sync + poller périodique (démon,
_POLL_EVERY s, silencieux si non appairé) + POST /api/tones-jobs/run (manuel).
Un seul passage à la fois (_lock) ; chaque job est TOUJOURS acquitté (ok ou
erreur) — un job qui plante n'est jamais re-tenté en boucle (contrat).
"""
import asyncio, contextlib, os, re, threading, time

from . import config as C
from .golog import get

log = get("tones-jobs")
from .tones_sync import _req
from .golog import swallowed as _swallowed

_POLL_EVERY = 300.0            # filet périodique ; le vrai débit vient des syncs
_lock = threading.Lock()
_ST = {"last": None, "processed": 0, "errors": 0, "log": []}

_SAFE = re.compile(r"[^\w.\- ]+")


def status():
    return dict(_ST, log=list(_ST["log"])[-10:], inflight=sorted(_inflight, key=str))


def _log(msg):
    log.info(f"{msg}")
    _ST["log"] = (_ST["log"] + [msg])[-20:]


# ── install ──────────────────────────────────────────────────────────────────
def _default_rel(pack, asset):
    """Chemin de repose quand le pack n'a jamais vécu sur ce rack (upload web) :
    rangé sous un dossier golemfm/ du bon type d'asset."""
    sub = {"ir": "irs"}.get(asset.get("format"), "models")
    slug = _SAFE.sub("-", pack["uid"].replace(":", "-"))
    return os.path.join("assets", sub, "golemfm", slug,
                        _SAFE.sub("-", asset.get("filename") or asset["sha256"][:12]))


# ── DEUX GARDES SUR CE QUI VIENT DE GOLEM.FM (audit 2026-09-13, B1 + M4) ────────────────────
# Le manifest dicte OÙ un asset se pose (`extra.rel`) et le job dicte QUEL blob on tire (`sha`) :
# deux chaînes de l'extérieur qui finissaient telles quelles dans un chemin disque et dans une URL
# portée par notre Bearer. Depuis que _settle_captures installe seul à chaque patch reçu, ces
# chemins s'exécutent sans un humain devant. Un `rel` sort d'assets/ -> refusé ; un `sha` qui
# n'est pas 64 hex -> refusé avant tout réseau.
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _check_sha(sha):
    sha = str(sha or "").lower()
    if not _SHA_RE.match(sha):
        raise RuntimeError(f"bad blob sha: {sha[:24]!r}")
    return sha


def _under_assets(rel):
    """Le chemin RELATIF normalisé d'un asset, garanti sous assets/ — ou RuntimeError."""
    root = os.path.realpath(os.path.join(C.ROOT, "assets"))
    p = os.path.realpath(os.path.join(C.ROOT, str(rel or "")))
    if p != root and not p.startswith(root + os.sep):
        raise RuntimeError(f"asset path escapes assets/: {str(rel)[:80]!r}")
    return C.rel(p).replace(os.sep, "/")


def _download_raw(sha, dest):
    """Téléchargement BRUT (hors _req qui suppose du JSON) + écriture atomique."""
    import urllib.request
    from .golemfm import _cfg as m_cfg
    sha = _check_sha(sha)
    base, token = m_cfg()
    if not base or not token:
        raise RuntimeError("not paired")
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return "skip"
    req = urllib.request.Request(base + f"/api/ext/tones/assets/{sha}")
    req.add_header("Authorization", "Bearer " + token)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, dest)
    return "ok"


def _entry_from_pack(pack, files):
    """Reconstruit une entrée tones-index depuis un doc Pack (l'inverse de
    tones_sync.build_packs). files = [(asset, rel)] effectivement posés."""
    extra = pack.get("extra") or {}
    uid = pack["uid"]
    if uid.startswith("t3k:"):
        raw = uid.split(":", 1)[1]
        tid = int(raw) if raw.isdigit() else raw
    else:
        tid = extra.get("catalog_id") or uid.split(":", 1)[1]
    # ── LA NATURE SE LIT, ELLE NE SE DÉCLARE PAS (2026-09-12) ──────────────────────────────
    # `format` et `gear` arrivaient tels quels du document de pack. Or golem.fm a trouvé chez lui
    # un `kind` DÉDUIT de l'endroit où l'utilisateur cherchait (un amp-cab installé depuis un bloc
    # d'ampli entrait en « amp ») — et ce champ voyage jusqu'ici, puisque notre `gear` en est la
    # copie. Une déclaration fausse en amont devient une vérité chez nous, et c'est elle que nos
    # gardes interrogent ensuite : contrôler la nature ne sert à rien si la nature est DÉCLARÉE.
    # On lit donc ce qui est LISIBLE — l'extension du fichier posé — et on ne laisse jamais la
    # déclaration contredire la lecture. Ce qui n'est pas lisible (amp seul vs amp-cab : deux
    # .nam) reste déclaré, faute de mieux, et c'est dit.
    ext = os.path.splitext(files[0][1])[1].lower() if files else ""
    fmt = {".nam": "nam", ".wav": "ir", ".flac": "ir", ".aidax": "aida-x"}.get(
        ext, (files[0][0].get("format") if files else "nam") or "nam")
    gear = pack.get("kind")
    if fmt == "ir" and gear not in ("cab", "experimental"):
        log.warning(f"pack {uid} : déclaré « {gear} » mais ses fichiers sont des IR ({ext}) — rangé en « cab »")
        gear = "cab"
    elif fmt in ("nam", "aida-x") and gear == "cab":
        log.warning(f"pack {uid} : déclaré « cab » mais ses fichiers sont des captures {fmt} — rangé en « amp-cab »")
        gear = "amp-cab"
    title = extra.get("t3k_title") or pack.get("title") or str(tid)
    return {
        "id": tid, "title": title,
        "slug": extra.get("slug") or _SAFE.sub("-", str(title)).lower(),
        "creator": pack.get("creator") or "", "url": pack.get("url") or "",
        "gear": gear, "format": fmt,
        "makes": extra.get("makes") or [], "tags": pack.get("tags") or [],
        "style": pack.get("style") or "rock",
        "downloads": 0, "favorites": 0, "source_group": "golemfm-install",
        "brand": __import__("bridge.store", fromlist=["brand_str"]).brand_str(pack.get("brand")), "pack": False,
        "amp": pack.get("title") or title,
        "models": [
            {"id": a.get("extra", {}).get("model_id") or a["sha256"][:12],
             "name": a.get("name") or a.get("filename"), "file": rel,
             "size": (a.get("extra") or {}).get("size"),
             "arch": (a.get("extra") or {}).get("arch")}
            for a, rel in files
        ],
        # une capture de plugin arrive avec sa provenance et reste privée (tones_sync._provenance) — sinon elle
        # devenait un tone « golemfm-install » sans histoire, que ce rack aurait pu croire partageable
        **_private_from_pack(pack),
    }


def _private_from_pack(pack):
    prov = pack.get("provenance") if isinstance(pack.get("provenance"), dict) else None
    if not (pack.get("private") or (prov or {}).get("kind") == "plugin-capture"):
        return {}
    cap = {"plugin": (prov or {}).get("plugin") or "", "at": (prov or {}).get("at") or "", "private": True,
           **({"os": prov["os"]} if (prov or {}).get("os") else {})}
    return {"private": True, "capture": cap, "source_group": "plugin-capture"}


def _install(uid):
    st, m = _req("GET", "/api/ext/tones/manifest?trashed=1")
    if st != 200:
        raise RuntimeError(f"manifest: {st or 'unreachable'} {m}")
    # NOS packs d'abord, puis ceux qu'un coéquipier prête à un de nos groupes (docs/library-loans.md) :
    # un prêt s'installe comme un pack à nous — le résolveur le trouve sans chemin spécial — et sa
    # provenance est notée À CÔTÉ, pour que la synchro ne le renvoie jamais comme le nôtre.
    from . import loans
    pack, lent_by = loans.find_pack(m, uid)
    if not pack:
        raise RuntimeError(f"pack {uid} unknown on golem.fm")
    if pack.get("kind") == "groove":
        return _install_groove(uid, pack, lent_by)
    # les fichiers d'un pack se tirent EN PARALLÈLE (audit 2026-09-13, M6) : un pack d'IR à dix
    # fichiers coûtait dix allers-retours en série dans la boucle de jobs, qui bloque tout le reste
    from concurrent.futures import ThreadPoolExecutor
    todo = [(a, _under_assets((a.get("extra") or {}).get("rel") or _default_rel(pack, a)))
            for a in (pack.get("assets") or [])]
    if not todo:
        raise RuntimeError(f"pack {uid} has no assets")
    with ThreadPoolExecutor(max_workers=min(4, len(todo))) as ex:
        list(ex.map(lambda ar: _download_raw(ar[0]["sha256"], os.path.join(C.ROOT, ar[1])), todo))
    files = todo
    if lent_by is not None:                               # AVANT le catalogue : son écriture relance la synchro
        loans.record_install(uid, pack, lent_by)
    if pack.get("kind") in ("synth", "kit", "loop", "sample"):
        # .vital, kits et samples vivent hors catalogue : reposer les fichiers suffit (`sample` manquait :
        # un pack de samples serait entré dans l'index des tones)
        return f"{len(files)} {pack['kind']} file(s) restored"
    entry = _entry_from_pack(pack, files)
    from .store import _read_json, _write_json_atomic
    cat = _read_json(C.CATALOG, {"tones": []}) or {"tones": []}
    cat["tones"] = [t for t in cat["tones"] if str(t.get("id")) != str(entry["id"])]
    cat["tones"].append(entry)
    _write_json_atomic(C.CATALOG, cat)                    # déclenche le push debounced
    return f"installed « {entry['amp']} » ({len(files)} file(s))"


def _install_groove(uid, pack, lent_by=None):
    """Un pack `groove` (2026-10-14) : son .mid va dans library/grooves/<id>.mid — PAS sous assets/, et JAMAIS dans
    le catalogue des tones (un groove n'est pas un ampli : bonne forme, mauvaise nature). Ses métadonnées (nom, genre,
    tempo, pack, usine) vont dans l'index des grooves, comme celles d'un groove importé."""
    from . import grooves, loans
    ex = pack.get("extra") or {}
    gid = grooves._safe_id(ex.get("groove_id") or uid.split("groove-", 1)[-1])
    assets = pack.get("assets") or []
    if not assets:
        raise RuntimeError(f"pack {uid} has no assets")
    root = os.path.realpath(grooves.GROOVES_DIR)
    dest = os.path.realpath(os.path.join(root, gid + ".mid"))
    if not dest.startswith(root + os.sep):
        raise RuntimeError(f"groove path escapes library/grooves: {gid[:80]!r}")
    _download_raw(assets[0]["sha256"], dest)
    if lent_by is not None:
        loans.record_install(uid, pack, lent_by)
    meta = grooves._read_meta()
    meta[gid] = {k: v for k, v in {"name": pack.get("title") or gid, "genre": ex.get("genre"), "tempo": ex.get("tempo"),
                                   "bars": ex.get("bars"), "pack": ex.get("pack"),
                                   "factory": True if ex.get("factory") else None}.items() if v is not None}
    grooves._write_meta(meta)
    return f"groove « {meta[gid]['name']} » installed"


# ── remove ───────────────────────────────────────────────────────────────────
def _tid_of_uid(uid):
    return uid.split(":", 1)[1] if ":" in uid else uid


def _remove(uid):
    from . import routes_content
    tid = _tid_of_uid(uid)
    from .store import _read_json
    cat = _read_json(C.CATALOG, {"tones": []}) or {"tones": []}
    if not any(str(t.get("id")) == str(tid) for t in cat["tones"]):
        return f"{uid} not installed (nothing to do)"     # idempotent
    deps = routes_content._deps_of(tid)
    used = [p["name"] or p["id"] for p in deps["presets"]] + deps["templates"]
    if used:
        raise RuntimeError("used by: " + ", ".join(str(u) for u in used))
    r = asyncio.run(routes_content.amp_delete(str(tid), {}))
    if hasattr(r, "status_code") and r.status_code >= 400:
        raise RuntimeError(f"delete failed ({r.status_code})")
    return f"removed {uid} (trash)"


# ── recall (avenant M3) ──────────────────────────────────────────────────────
def _recall(payload):
    # appel SYNC depuis le thread worker : le verrou du moteur sérialise avec le reste
    from . import recall
    pid = payload.get("preset")
    ok = recall.do_recall(pid, payload.get("scene"))
    if not ok:
        raise RuntimeError(f"unknown preset '{pid}'")
    return f"recalled {pid}" + (f" scene {payload.get('scene')}" if payload.get("scene") else "")


# ── boucle de traitement ─────────────────────────────────────────────────────
def _t3k_install(payload):
    """Installe un tone TONE3000 avec le compte du RACK (avenant M4) — réutilise
    le pipeline complet du modal « + New » (download, catalogue, classif, photo),
    en SYNCHRONE : le worker jobs est déjà un thread."""
    from . import routes_t3k
    tid = int(payload.get("tone_id"))
    if routes_t3k._ST["phase"] in ("meta", "download", "classify"):
        raise RuntimeError("a TONE3000 install is already running on the rack")
    routes_t3k._install_worker(tid, None)
    st = routes_t3k._ST
    if st.get("phase") == "error":
        raise RuntimeError(st.get("error") or "install failed")
    return st.get("msg") or f"tone {tid} installed"


ROLES = ("guitar", "bass", "voice", "keys", "pads", "keys-pads", "line", "drums")   # drums : docs/drums-kit.md (2026-09-17)
MIDI_ROLES = ("keys", "pads", "keys-pads")


def _job_doc(job, tmp):
    import json as _json
    # un document DÉJÀ LU sur le rack (bridge/karaoke.py : le patch voix connu par son seul patch_id,
    # pris dans library/patches) — jamais posé par golem.fm : `doc` n'existe dans aucun job reçu
    if isinstance(job.get("_doc"), dict):
        return job["_doc"]
    try:
        d = _json.loads(_blob_bytes(job, tmp))
    except ValueError as e:
        raise RuntimeError(f"blob is not JSON: {e}")
    if not isinstance(d, dict):
        raise RuntimeError("blob is not a JSON object")
    return d


def _preset_install(job):
    """`{action:"preset-install", sha, name, preset_id}` ; blob = l'enveloppe d'export `{schema_version,
    preset}` (ou le preset nu). Mêmes règles que POST /api/preset : migration, volume système, ids de
    blocs UNIQUES (refus avec raison), `unresolved[]` gardé. JAMAIS de recall. Remplacement seulement si
    le preset local porte origin golem.fm avec le même id ; sinon suffixe -2."""
    from .store import _safe_id, migrate_config, ensure_volume, duplicate_block_ids, _write_json_atomic, _read_json
    env = _job_doc(job, ".preset-install.tmp")
    preset = env.get("preset") if isinstance(env.get("preset"), dict) else env
    pid = _safe_id(job.get("preset_id") or preset.get("id") or job.get("name") or preset.get("name") or "preset")
    path = lambda p: os.path.join(C.PRESETS_DIR, f"{p}.json")
    if os.path.exists(path(pid)) and (_read_json(path(pid), {}) or {}).get("origin") != "golem.fm":
        base, n = pid, 2
        while os.path.exists(path(pid)):
            pid, n = f"{base}-{n}", n + 1
    preset = dict(preset, id=pid, origin="golem.fm")
    preset.setdefault("name", job.get("name") or pid)
    migrate_config(preset)
    ensure_volume(preset)
    dupes = duplicate_block_ids(preset)
    if dupes:
        raise RuntimeError("duplicate block ids: " + ", ".join(dupes) + " — two blocks share an id across lanes")
    from .store import duplicate_branch_ids
    bdupes = duplicate_branch_ids(preset)
    if bdupes:
        raise RuntimeError("duplicate branch ids: " + ", ".join(bdupes) + " — two lanes share a split branch id; scene mutes would hit both")
    _write_json_atomic(path(pid), preset)
    unresolved = []
    try:
        from . import preset_export
        unresolved = (preset_export.build_export(pid) or {}).get("unresolved") or []
    except Exception as _e:
        _swallowed(_e)
    return {"_log": f"preset '{pid}' installed ({len(unresolved)} unresolved)", "preset_id": pid, "unresolved": unresolved}


def _patch_doc(job, tmp):
    """Le document d'un patch (patch-install / patch-try) : rôle, chaîne {pre,split,post} ou {chain}, scènes."""
    from . import patches as P
    from .store import duplicate_block_ids, rich_chain
    doc = _job_doc(job, tmp)
    role = job.get("role") or doc.get("role")
    if role not in ROLES:
        raise RuntimeError("role required: guitar | bass | voice | keys | pads | keys-pads | drums")
    chain = doc.get("chain")
    # UN PATCH v2 (docs/patches.md §9 bis) : la forme se LIT (lanes_v == 2 et lanes[]), jamais
    # `kind`/`patch_v` ; `lanes[0].chain` fait foi et un miroir `chain` qui en diverge est REFUSÉ (jamais un
    # choix silencieux) ; toutes les lanes sont du rôle du patch ; plusieurs lanes = un kit, bâti sur le rack.
    if P.is_v2(doc):
        import json as _json
        bad = [str(L.get("id")) for L in doc["lanes"] if (L.get("role") or role) != role]
        if bad:
            raise RuntimeError(f"lane {', '.join(bad)} is not {role} — a patch holds one instrument")
        if len(doc["lanes"]) > 1:
            raise RuntimeError("multi-lane patches (drum kits) are built on the rack — open the kit there")
        lane_chain = doc["lanes"][0].get("chain")
        if chain is not None and _json.dumps(chain, sort_keys=True) != _json.dumps(lane_chain, sort_keys=True):
            raise RuntimeError("chain and lanes[0].chain disagree — lanes[0].chain is the truth: send the mirror identical")
        chain = lane_chain
        doc = dict(doc, scenes=P.deposit_payload(doc)[1])   # `lanes` des scènes : ids de lane du patch, pas les nôtres
    if not isinstance(chain, (dict, list)):
        raise RuntimeError("chain required ({pre, split, post} or {chain: [...]})")
    shape = P._patch_shape(chain if isinstance(chain, dict) else {"chain": chain})
    if not P._has_blocks(shape):
        raise RuntimeError("the patch has no blocks")
    dupes = duplicate_block_ids({"lanes_v": 2, "scenes": [], "lanes": [{"id": role, "role": role, "chain": rich_chain(shape)}]})
    if dupes:
        raise RuntimeError("duplicate block ids: " + ", ".join(dupes))
    scenes = doc.get("scenes") if isinstance(doc.get("scenes"), list) and doc.get("scenes") else [{"id": "A", "name": "A", "blocks": {}, "params": {}}]
    shape, scenes = P.normalize_patch(shape, scenes)     # mode de split + ids de scène + ids de blocs
    return doc, role, shape, scenes


def _origin_of(job, doc):
    """D'où vient le document — golem.fm le date depuis le 2026-09-11 (`saved_at` + `rev`), et
    marque `draft: true` ce qui n'a jamais été sauvegardé. Sans ces champs : un job d'avant.
    On ne devine pas une date : « brouillon » et « inconnu » sont deux réponses différentes."""
    g = lambda k: job.get(k) if job.get(k) is not None else (doc or {}).get(k)
    if g("draft"):
        return "draft (never saved)"
    at, rev = g("saved_at"), g("rev")
    if at or rev is not None:
        return "saved " + str(at or "?") + (f" rev {rev}" if rev is not None else "")
    return "undated (job emitted before 2026-09-11)"


def _patch_install(job):
    """`{action:"patch-install"|"patch-push", sha, name, role, patch_id}` -> library/patches. Rien ne
    sonne, rien ne change dans le Designer : il apparaît dans Songs ▸ Patches. Remplacement seulement si
    le patch local porte origin golem.fm avec le même id ; sinon suffixe -2."""
    from . import patches as P
    doc, role, shape, scenes = _patch_doc(job, ".patch-install.tmp")
    name = (doc.get("name") or job.get("name") or "").strip() or f"golem.fm · {role}"
    base = P._safe_id(job.get("patch_id") or doc.get("id") or name)
    pid = base
    cur = P.get_patch(pid)
    if cur is not None and cur.get("origin") != "golem.fm":
        n = 2
        while os.path.exists(P._path(pid)):
            pid, n = f"{base}-{n}", n + 1
    settled = _settle_captures(P.shape_blocks(shape))     # un patch rangé porte ses captures (2026-09-12)
    new = {"id": pid, "name": name, "person": doc.get("person") or None, "role": role, "origin": "golem.fm",
           "chain": shape, "scenes": scenes, "needs": P.needs_of(shape),
           "tags": P.norm_tags(doc.get("tags") if isinstance(doc.get("tags"), list) else [])}
    if P.is_v2(doc):
        # rangé en v2 (docs/patches.md §3) : la lane, son ⚙ et ses réglages de pied, miroir IDENTIQUE
        lane = {k: doc["lanes"][0][k] for k in P._LANE_KEEP if doc["lanes"][0].get(k) is not None}
        new.update(kind="patch", patch_v=2, lanes_v=2, lanes=[dict(lane, role=role, chain=shape)])
        cfg = ((doc.get("config") or {}).get("gen") or {})
        blocks = [b for b in (cfg.get("blocks") or []) if (b or {}).get("type") in P.PATCH_GEN_TYPES]
        new["config"] = {"gen": {"blocks": blocks, "out": cfg.get("out") or "1-2"}} if blocks else {}
        for k, v in doc.items():
            if P._EXP_KEY.match(k) or k in P._PATCH_DOC_KEYS + ("bpm",):
                new[k] = v
    out = P._write(new)
    # Le document du RACK fait foi (docs/archive/patch-sync-avis.md §3) : ce qu'il vient de normaliser
    # (id, `needs`, captures réglées) repart à golem.fm tout de suite, comme après toute mutation
    # par l'API (`routes_patches._pushed`) — golem.fm recopiait l'ack en attendant la synchro
    # suivante (demande golem.fm, 2026-09-14). Débouncé, best-effort, muet si non appairé.
    from . import golemfm
    golemfm.push_patches()
    note = f"patch '{pid}' installed"
    if settled["matched"]:
        note += " — ⚑ " + "; ".join(f"{m['block']} « {m['label']} » → {m['ref']}" for m in settled["matched"])
    if settled["installed"]:
        note += " — ⤓ " + "; ".join(i["uid"] for i in settled["installed"])
    if settled.get("suggested"):
        note += " — ? " + "; ".join(f"{m['block']} « {m['label']} » ≈ {m['title']}" for m in settled["suggested"])
    return {"_log": note, "patch_id": out["id"], "matched": settled["matched"], "suggested": settled.get("suggested", []),
            "installed": settled["installed"], "install_failed": settled["failed"]}


def _guard_quiet(what):
    """Un geste qui retire quelque chose du rack ne se fait ni en mode verrouillé ni pendant une
    prise — même règle que patch-try / preset-install, refusée EN LE DISANT (l'ack porte la phrase)."""
    from .state import state
    mode = state.mode or {}
    if (mode.get("ui") or {}).get("locked"):
        raise RuntimeError(f"rack is in {mode.get('name') or 'a locked'} mode — {what} refused, try later")
    if (state.perf or {}).get("recording"):
        raise RuntimeError(f"a take is recording — {what} refused, try after it")


def _patch_delete(job):
    """`{action:"patch-delete", patch_id}` (golem.fm, patches.md §21) : le fichier part, les lanes
    qui l'avaient déposé gardent leur copie inline (§9.3, §15.2 : déposer COPIE — on ne refuse
    donc pas « parce qu'une chanson l'utilise »), et le catalogue repart en `complete: true` :
    c'est CE push qui confirme la suppression chez golem.fm. Un id absent n'est pas une erreur."""
    from . import patches as P, golemfm
    _guard_quiet("patch delete")
    if not str(job.get("patch_id") or "").strip():
        raise RuntimeError("patch-delete without patch_id")
    pid = P._safe_id(str(job.get("patch_id")))
    deleted = bool(P.get_patch(pid) is not None and P.delete_patch(pid))
    golemfm.push_patches()
    return {"_log": f"patch '{pid}' " + ("deleted" if deleted else "absent (nothing to delete)"),
            "patch_id": pid, "deleted": deleted}


def _preset_delete(job):
    """`{action:"preset-delete", preset_id}` (golem.fm, patches.md §21) : même corps que
    `DELETE /api/preset/{pid}` (store.delete_preset — banks libérées, preset courant oublié, liens
    de morceau repoussés), refusé en le disant si le preset JOUE, en mode verrouillé ou pendant une
    prise ; puis l'état repart à golem.fm pour que son miroir confirme sans attendre."""
    from .state import state
    from .store import delete_preset, _safe_id
    from . import rigstatus
    _guard_quiet("preset delete")
    if not str(job.get("preset_id") or "").strip():
        raise RuntimeError("preset-delete without preset_id")
    pid = _safe_id(str(job.get("preset_id")))
    if state.preset_id == pid:
        raise RuntimeError(f"preset '{pid}' is playing right now — recall another one first")
    r = delete_preset(pid)
    if r["deleted"]:
        rigstatus.push_soon()
    return {"_log": f"preset '{pid}' " + (f"deleted ({r['banks_freed']} bank slot(s) freed)" if r["deleted"] else "absent (nothing to delete)"),
            "preset_id": pid, **r}


def _patch_preview(job):
    """`{action:"patch-preview", sha, role, patch_id, ref?}` (golem.fm, Store : pas de publication sans
    écoute enregistrée par le rack de l'auteur — décision 2026-09-15). Le blob = le document du
    patch, comme patch-try. Le rack construit le preset d'essai (une lane du rôle), le pose SOUS UN ID
    TEMPORAIRE dans presets/ (le moteur de preview charge par id), re-ampe la DI de référence du rôle
    (`ref` explicite, sinon auto par style) à travers CHAQUE scène, uploade un clip par scène au fil
    de l'eau, puis efface le preset temporaire et ses clips. Le moteur live est PRIS pendant le rendu
    (~45 s par scène) et REMIS après (reapply_sandbox) ; l'edit-buffer du Designer n'est jamais écrit.
    Ack {patch_id, di, instrument, fingerprint, scenes{id:{sha256,duration}}, missing[]}. Refus dits :
    mode verrouillé/gig, prise en cours, rôle keys (rendu MIDI non supporté), DI de référence absente."""
    from . import preview as preview_mod
    from .state import state
    from .store import _write_json_atomic, _safe_id
    from . import patches as P
    mode = state.mode or {}
    if mode.get("id") == "gig" or (mode.get("ui") or {}).get("locked"):
        raise RuntimeError("rack is in a locked/gig mode — try later")
    if (state.perf or {}).get("recording"):
        raise RuntimeError("a take is recording — try after it")
    patch_id = P._safe_id(str(job.get("patch_id") or job.get("name") or "patch"))
    pid = _safe_id(f"preview-{patch_id}")
    preset, role, lane, scenes, settled, missing = _trial_preset(job, ".patch-preview.tmp", pid=pid)
    if lane.get("midi"):
        raise RuntimeError("keys preview needs MIDI rendering — not supported yet")
    in_key = str(lane.get("in_sel") or "1")
    ppath = os.path.join(C.PRESETS_DIR, f"{pid}.json")
    _write_json_atomic(ppath, preset)
    jid = job_id(job)
    clips = {}

    def on_scene(sc, rel):
        one = preview_mod.push_clip(f"patch-{patch_id}", sc, rel)
        if not one:
            return
        clips[sc] = one
        if jid is not None:
            with __import__("contextlib").suppress(Exception):
                _req("POST", f"/api/ext/tones/jobs/{jid}/progress", body={"scene": sc, "clip": one})
    try:
        preview_mod.generate(pid, next(_pv_seq), on_scene=on_scene, in_key=in_key, ref=job.get("ref"))
        st = preview_mod.status()
        if st.get("phase") != "done":
            raise RuntimeError(st.get("error") or "generation failed")
        from .store import load_preset
        fresh = load_preset(pid) or {}
        pv = fresh.get("preview") or {}
        if in_key != "1":
            pv = ((pv.get("alt") or {}).get(in_key)) or pv
    finally:
        # rien ne reste : ni le preset temporaire, ni ses clips locaux (ils vivent chez golem.fm)
        with __import__("contextlib").suppress(OSError):
            os.remove(ppath)
        import shutil as _sh
        _sh.rmtree(os.path.join(C.PREVIEWS_DIR, pid + ("" if in_key == "1" else "-in" + in_key)), ignore_errors=True)
    # di_name (golem.fm, 2026-09-15) : « reference DI : Strat bridge » sur la fiche du Store — le nom de
    # l'index quand il existe, sinon absent (la fiche retombe sur la clé `di`)
    di_name = ((preview_mod._di_index().get(pv.get("ref") or "") or {}).get("name")) or None
    return {"_log": f"patch '{patch_id}' previewed ({len(clips)} scene·s, DI {pv.get('ref')})",
            "patch_id": patch_id, "di": pv.get("ref"), "di_name": di_name, "instrument": pv.get("instrument") or role,
            "fingerprint": pv.get("fingerprint"), "scenes": clips,
            "missing": missing, "matched": settled["matched"], "installed": settled["installed"],
            "suggested": settled.get("suggested", [])}


# Blocs dont le SON vient d'un fichier : sans capture ils s'instancient VIDES, donc muets — et
# rien ne les attend, donc rien ne les vérifie (rig-check ne contrôle que ce qui a une ligne
# fichier à charger). C'est le silence qu'on a mis une soirée à nommer, le 2026-09-11.
CAPTURE_TYPES = ("amp", "amp-nam", "cab", "pedal-nam", "preamp-nam", "comp-nam", "ir-fx")


def _manifest_tones():
    """Les packs que golem.fm DÉTIENT pour ce compte, dans la forme de notre index de tones
    ({id, title, gear, uid}) — ce que le rack peut se faire envoyer. [] si non appairé/injoignable."""
    try:
        st, m = _req("GET", "/api/ext/tones/manifest")
    except Exception as e:
        log.warning(f"manifest golem.fm injoignable : {e}")
        return []
    if st != 200 or not isinstance(m, dict):
        return []
    out = []
    for p in m.get("packs") or []:
        uid = str(p.get("uid") or "")
        if not uid or p.get("trashed") or p.get("kind") not in ("amp", "amp-cab", "cab", "pedal"):
            continue
        out.append({"id": _tid_of_uid(uid), "uid": uid, "title": p.get("title") or "", "gear": p.get("kind"),
                    "bytes": sum(int(a.get("bytes") or 0) for a in (p.get("assets") or []))})
    # …et ce qu'un coéquipier prête à un de nos groupes (docs/library-loans.md §2) : un patch qui ARRIVE
    # et qui en a besoin le tire — c'est le « à la demande » (jamais d'office). Les nôtres d'abord.
    from . import loans
    with contextlib.suppress(Exception):
        loans.refresh(m)
    for uid, (p, who) in loans.lent_packs(m).items():
        if p.get("trashed") or p.get("kind") not in ("amp", "amp-cab", "cab", "pedal"):
            continue
        out.append({"id": _tid_of_uid(uid), "uid": uid, "title": p.get("title") or "", "gear": p.get("kind"),
                    "bytes": sum(int(a.get("bytes") or 0) for a in (p.get("assets") or [])), "lent_by": who})
    return out


# ── LA BOUCLE DE JOBS N'EST PAS UN TÉLÉCHARGEUR (audit 2026-09-13, M6). _settle_captures installe
# pendant la réception d'un patch, dans le thread qui sert TOUS les jobs (take-upload, setlist-push…) :
# un pack de 200 Mo y bloquerait tout pendant des minutes, ack compris. Deux bornes, et on le DIT :
#   · un pack plus gros que _INLINE_MAX_BYTES n'est pas tiré ici -> `install_failed[].why` demande
#     un job `install {uid}` d'abord (le chemin fait pour ça) ;
#   · le règlement entier a un BUDGET de temps ; passé, les installations restantes sont refusées de
#     la même façon. Le patch s'auditionne quand même, amputé de ce qui n'a pas pu venir.
_INLINE_MAX_BYTES = 48 * 1024 * 1024
_SETTLE_BUDGET_S = 90.0


def _settle_captures(blocks, budget_s=_SETTLE_BUDGET_S):
    """CE QUE L'UTILISATEUR A CHOISI, LE RACK SE LE FAIT ENVOYER — docs/patches.md §20, amendé par
    docs/block-status.md §6 (2026-09-30). Pour chaque bloc à capture :
      · `ref` posée mais absente ici → installée AVANT l'audition : golem.fm d'abord (nos packs, puis
        les prêts), sinon TONE3000 avec le compte du rack. Ce n'est pas une devinette : golem.fm envoie
        les refs que l'utilisateur a choisies EN LES ÉCOUTANT pendant la phase assistant ;
      · pas de `ref` → RIEN n'est posé. Le rapprochement par nom (l'ancien §20 : « Prism ») est
        calculé et rendu comme PROPOSITION (`suggested[]`) : un titre voisin n'est pas le son écouté,
        et l'appliquer sans demander, c'est la classe « bonne forme, mauvaise nature ». Le bloc reste
        `empty`, barré à l'écran, et la feuille Replace montre la suggestion en tête.
    Rend {matched: [] (gardé vide le temps que golem.fm cesse de le lire), suggested, installed, failed}."""
    from . import blockstatus as BS
    from .resolver import _components, _resolve
    comps = _components()
    suggested, installed, failed = [], [], []
    manifest = None
    import time as _t
    deadline = _t.monotonic() + budget_s

    def _man():
        nonlocal manifest
        if manifest is None:
            manifest = _manifest_tones()
        return manifest

    def _pack_of(tid):
        return next((t for t in _man() if str(t["id"]) == str(tid)), None)

    def _budget(block_id, uid, size):
        if size > _INLINE_MAX_BYTES:
            failed.append({"block": block_id, "uid": uid,
                           "why": f"pack is {size // (1024 * 1024)} MB — push an `install {uid}` job first, then retry"})
            return False
        if _t.monotonic() > deadline:
            failed.append({"block": block_id, "uid": uid,
                           "why": f"time budget exceeded ({int(budget_s)} s) — push an `install {uid}` job first, then retry"})
            return False
        return True

    def _pull(tone, block_id):
        if not _budget(block_id, tone["uid"], int(tone.get("bytes") or 0)):
            return False
        try:
            _install(tone["uid"])
            installed.append({"block": block_id, "uid": tone["uid"], "title": tone.get("title"), "source": "golem.fm"})
            return True
        except Exception as e:
            failed.append({"block": block_id, "uid": tone["uid"], "why": str(e)})
            return False

    def _pull_t3k(tid, block_id):
        uid = f"t3k:{tid}"
        if not _budget(block_id, uid, 0):
            return False
        try:
            _t3k_install({"tone_id": tid})
            installed.append({"block": block_id, "uid": uid, "title": None, "source": "tone3000"})
            return True
        except Exception as e:
            failed.append({"block": block_id, "uid": uid, "why": f"TONE3000: {e}"})
            return False

    for b in blocks:
        t = b.get("type")
        if t not in CAPTURE_TYPES:
            continue
        ref = b.get("ref")
        if ref:
            f = _resolve(ref, comps, b.get("model"))
            if f is None or (os.path.isabs(f) and not os.path.isfile(f)):
                tid = _tid_of_uid(str(ref).split("/")[-1])
                pack = _pack_of(tid)
                if pack is not None:
                    _pull(pack, b.get("id"))
                elif str(tid).isdigit():
                    _pull_t3k(tid, b.get("id"))
            continue
        with contextlib.suppress(Exception):
            sug = BS.suggestion(b, _man)
            if sug:
                suggested.append(sug)
    return {"matched": [], "suggested": suggested, "installed": installed, "failed": failed}


def _trial_preset(job, tmp, pid="sandbox-try"):
    """Le PRESET D'ESSAI d'un patch (une lane du rôle sur l'entrée `<role>#1` de la carte du mode,
    scènes du patch, captures réglées, `missing[]` dit ce qui ne se résout pas) — partagé par
    patch-try (audition dans la sandbox) et patch-preview (re-amp de la DI de référence, 2026-09-15).
    Rend (preset, role, lane, scenes, settled, missing)."""
    from .state import state
    from . import patches as P, inputmap
    from .store import migrate_config, ensure_volume, rich_chain
    doc, role, shape, scenes = _patch_doc(job, tmp)
    name = (doc.get("name") or job.get("name") or "").strip() or f"golem.fm · {role}"
    midi = role in MIDI_ROLES
    lane = {"id": f"{role}-try", "key": f"{role}-try", "role": role, "name": name, "midi": midi, "out_sel": "1-2",
            "chain": rich_chain(shape if "chain" not in shape else {"pre": shape["chain"], "split": None, "post": []})}
    imap = state.inputmap or inputmap.current() or {}
    # la liaison d'entrée est CELLE d'un patch joué depuis une bank (patches.bind_input) : une seule règle
    try:
        P.bind_input(lane, role, imap)
    except ValueError as e:
        raise RuntimeError(str(e))
    # ⚠ LE DOCUMENT SE DÉCLARE COMME PATCH (corrigé le 2026-09-12). Sans ce marqueur, le Designer
    # ouvrait l'essai comme un brouillon de PRESET : « 💾 Save » rangeait le son d'un musicien dans
    # presets/ au lieu de la bibliothèque de patches — le mainteneur a créé `presets/hammer.json` avec une
    # seule lane `guitar-try`, ce qui n'est pas un rig. Le mode patch du Designer existait déjà et
    # savait tout faire (un onglet, Save = créer le patch) : il ne lui manquait que d'être prévenu.
    # `id: None` = patch pas encore en bibliothèque -> Save ouvre le nommage, puis POST /api/patches.
    # `realm` est l'id de LANE affichée (pmTab s'y accroche), pas le royaume historique.
    preset = {"id": pid, "name": name, "origin": "golem.fm", "lanes_v": 2, "lanes": [lane],
              "scenes": scenes, "bpm": doc.get("bpm") or 120,
              "__patch": {"realm": lane["id"], "id": None, "name": name, "role": role,
                          # l'IDENTITÉ vient avec : sauvé, le patch garde l'id de golem.fm — sinon
                          # chaque reprise fabrique un objet de plus (paper-kite-ii, -iii…)
                          "source_id": P._safe_id(job.get("patch_id") or doc.get("id") or name),
                          "origin": "golem.fm"}}
    if P.is_v2(doc):
        # un patch v2 s'essaie AVEC son ⚙ et ses réglages de pied (docs/patches.md §4)
        cfg = ((doc.get("config") or {}).get("gen") or {})
        blocks = [b for b in (cfg.get("blocks") or []) if (b or {}).get("type") in P.PATCH_GEN_TYPES]
        if blocks:
            preset["config"] = {"gen": {"blocks": blocks, "out": cfg.get("out") or "1-2"}}
        for k, v in doc.items():
            if P._EXP_KEY.match(k) or k in P._PATCH_DOC_KEYS:
                preset[k] = v
    migrate_config(preset)
    ensure_volume(preset)
    # ── CE QUI NE SE RÉSOUT PAS SE DIT (2026-09-11) ─────────────────────────────────────────
    # Un patch est arrivé avec des captures que ce rack n'a pas : le template a gardé « %MODEL% »
    # (_tpl ne substitue que si la valeur est non vide), le NAM s'est chargé SANS modèle — muet,
    # et l'ack disait « auditionné ». L'ack porte désormais la liste : golem.fm sait quoi pousser
    # (job `install {uid}`) avant de réessayer, et le journal du rack le dit à l'humain.
    from .store import all_blocks
    from .resolver import _components, _resolve
    _comps = _components()
    # ── LA CAPTURE CHOISIE EST INSTALLÉE, LA CAPTURE DEVINÉE EST PROPOSÉE (block-status.md §6) ──
    # Jusqu'au 2026-09-30 le rack APPLIQUAIT un appariement par nom (« Hammer » → une JC-120
    # possédée). golem.fm envoie maintenant la ref choisie à l'écoute : une ref absente est
    # installée, un bloc sans ref reste vide et l'appariement part en `suggested[]` — jamais posé.
    settled = _settle_captures(b for b, _l in all_blocks(preset))
    matched, installed = settled["matched"], settled["installed"]
    from .rig import _wrong_kind
    missing = []
    for b, _l in all_blocks(preset):
        ref, t = b.get("ref"), b.get("type")
        # TROIS silences distincts, et le troisième est le plus retors (patch « Titan ») :
        #   · la capture n'est pas installée ;
        #   · le patch n'en nomme aucune — un NAM sans modèle est muet, et rien ne l'attend donc
        #     rien ne le vérifie (rig-check ne contrôle que ce qui a un fichier à charger) ;
        #   · la capture EXISTE mais ne convient pas au bloc — une capture amp-cab au format NAM
        #     sur un `cab` RÉSOUT, et le convolver ne charge rien. Bonne forme, mauvaise nature.
        path = _resolve(ref, _comps, b.get("model")) if ref else None
        if path and os.path.isabs(path) and not os.path.isfile(path):
            path = None                                   # indexée mais effacée du disque : absente
        why = ("not installed on this rack" if ref and not path
               else "no capture referenced" if not ref and t in CAPTURE_TYPES
               else _wrong_kind(b, path))
        if why:
            missing.append({"block": b.get("id"), "type": t, "ref": ref,
                            "label": b.get("label") or b.get("name"), "why": why})
    # ── UN BLOC SANS CAPTURE EST RETIRÉ DE L'AUDITION (2026-09-11) ──────────────────────────
    # Réponse à la question ouverte de golem.fm : un NAM vide ne laisse RIEN passer, donc un seul
    # bloc sans capture faisait taire TOUTE sa branche — l'ampli qui la suit compris. Pour une
    # AUDITION, entendre l'ampli sans sa fuzz apprend plus que n'entendre rien : on retire, et on
    # le DIT (même patron que la quarantaine, rig._drop_quarantined — jamais en silence).
    # L'installation en bibliothèque, elle, ne touche à rien : le patch y est une recette, et
    # `unresolved[]` la qualifie (docs/private/exchanges/message-maestrium-patches-push-splits.md §1).
    # ⚠ Le bloc RESTE dans le document (corrigé le 2026-09-12). L'effacer pour que le reste
    # s'entende privait l'utilisateur du seul geste qui répare : lui donner une capture. La
    # branche apparaissait VIDE à l'écran, sans rien à taper. La compile, elle, ne le pose pas
    # (rig._drop_empty_capture) — donc le son est le même, et le bloc reste là, marqué « ∅ ».
    return preset, role, lane, scenes, settled, missing


def _patch_try(job):
    """`{action:"patch-try", sha, role}` : ESSAYER un patch sans laisser un preset derrière. Un preset
    minimal en mémoire (une lane du rôle sur l'entrée `<role>#1` de la carte du mode), auditionné par le
    chemin du Designer, l'edit-buffer remplacé (l'ancien gardé en .sandbox.prev.json), le Designer
    prévenu (state.sandbox_rev). L'ack revient APRÈS l'audition : « écoute maintenant » est vrai.
    Refus avec raison : mode verrouillé, prise en cours, pas d'entrée du rôle, compile."""
    import json as _json, shutil, time as _time
    from .state import state
    from . import patches as P, recall as recall_mod, inputmap
    from .store import migrate_config, ensure_volume, rich_chain, _write_json_atomic
    mode = state.mode or {}
    if (mode.get("ui") or {}).get("locked"):
        raise RuntimeError(f"rack is in {mode.get('name') or 'a locked'} mode — try later")
    if (state.perf or {}).get("recording"):
        raise RuntimeError("a take is recording — try after it")
    doc = None
    preset, role, lane, scenes, settled, missing = _trial_preset(job, ".patch-try.tmp")
    matched, installed = settled["matched"], settled["installed"]
    name = preset["name"]
    drop = {m["block"] for m in missing if m["why"] == "no capture referenced" and m.get("block")}
    scene = str(scenes[0].get("id") or "A")
    # ── L'ESSAI DEVIENT LE PRESET COURANT (décision 2026-09-12) ──────────────────────
    # On écrit la sandbox D'ABORD, puis on la RAPPELLE sous son id réservé par do_recall — le
    # chemin de tout recall (state.preset_id, scènes, stomps, registres du pied, .live.json,
    # émission). /live montre le patch, le pied le pilote, et la bank du FCB ne bouge pas :
    # l'essai n'a pas de slot de setlist, _align_pedalboard(None) est un no-op. Sortir de
    # l'essai = rappeler n'importe quel preset ; le brouillon d'avant reste en .sandbox.prev.json.
    from .store import SANDBOX_TRY_ID
    # à blanc d'abord : do_recall n'expose pas un refus de compile (quarantaine, routage) — et un
    # refus ne doit laisser NI sandbox écrite NI brouillon écrasé
    refused = recall_mod.check_preset(preset, scene)
    if refused:
        raise RuntimeError(refused)
    buf = recall_mod.SANDBOX_BUF
    prev = buf.replace(".sandbox.json", ".sandbox.prev.json")
    if os.path.exists(buf):
        shutil.copyfile(buf, prev)                 # le brouillon d'avant n'est jamais perdu
    _write_json_atomic(buf, {"preset": preset, "scene": scene, "from": "golem.fm", "at": _time.strftime("%Y-%m-%d %H:%M:%S")})
    err = None
    try:
        ok = recall_mod.do_recall(SANDBOX_TRY_ID, scene)   # sync, sous _RECALL_LOCK — le worker est un thread
        if not ok:
            err = "recall of the trial preset failed"
    except Exception as e:
        err = str(e)
    if err:
        raise RuntimeError(err)
    state.sandbox_rev = int(getattr(state, "sandbox_rev", 0) or 0) + 1
    state.sandbox_from = "golem.fm"
    state.touch()
    # deux baffles en série : audible, et indiagnosticable à l'oreille (cf. rig.stacked_cab)
    from .rig import stacked_cab
    from .resolver import _tones_index
    def _gear_of(ref):
        key = ref.split(":", 1)[1] if str(ref).startswith("t3k:") else str(ref)
        return (_tones_index().get(key) or {}).get("gear")
    warnings = []
    for L in preset.get("lanes") or []:
        ch = L.get("chain") or {}
        for seq in [ch.get("pre") or []] + [br.get("blocks") or [] for br in ((ch.get("split") or {}).get("branches") or [])]:
            for bid in stacked_cab(seq, _gear_of):
                warnings.append({"block": bid, "why": "amp-cab capture already carries its cabinet — "
                                                      "the cab block after it stacks a second one"})

    from .rig import silent_scenes
    for L in preset.get("lanes") or []:
        for w in silent_scenes(L, scenes):
            warnings.append({"block": None, "scene": w["scene"], "why": w["why"]})

    orphans = P.orphan_scene_keys({"pre": lane["chain"].get("pre"), "split": lane["chain"].get("split"),
                                   "post": lane["chain"].get("post")}, scenes)
    note = " [" + _origin_of(job, doc) + "]"
    if matched:
        note += " — ⚑ " + "; ".join(f"{m['block']} « {m['label']} » → {m['ref']} ({(m['title'] or '')[:34]}"
                                     + (f", now {m['retyped']}" if m.get("retyped") else "") + ")" for m in matched)
    if installed:
        note += " — ⤓ installed: " + "; ".join(f"{i['uid']} ({(i.get('title') or i.get('source') or 'golem.fm')[:34]})" for i in installed)
    if settled["failed"]:
        note += " — ✗ could not install: " + "; ".join(f"{f['uid']}: {f['why']}" for f in settled["failed"])
    if warnings:
        note += " — ⚠ " + "; ".join(w["why"].split(" — ")[0]
                                     + f" ({w.get('block') or 'scene ' + str(w.get('scene'))})" for w in warnings[:3])
    if orphans:
        note += (" — ⚠ %d scene key(s) point at nothing: " % len(orphans)
                 + ", ".join(f"{o['scene']}.{o['where']}[{o['key']}]" for o in orphans[:6]))
    if missing:
        note = " — ⚠ " + "; ".join(f"{m['block'] or m['type']}: {m['why']}" for m in missing)
        if drop:
            note += f" (dropped from the audition so the rest of the chain can be heard: {', '.join(sorted(drop))})"
    return {"_log": f"patch '{name}' auditioned on lane {lane['id']} (in {lane.get('in_sel')})" + note,
            "ok": True, "lane": lane["id"], "input": lane.get("in_sel"),
            "unresolved": missing, "dropped": sorted(drop), "warnings": warnings, "matched": matched,
            "suggested": settled.get("suggested", []),
            "installed": installed, "install_failed": settled["failed"],
            "scene_orphans": orphans, "doc": _origin_of(job, doc)}


def _push_catalog(_payload):
    """PUT /api/ext/rig/catalog : la liste EXHAUSTIVE du matériel que ce rack connaît par son nom
    (library/catalog/effects.json) et les types de blocs avec leurs potards et leur quarantaine — ce qui
    contraint l'assistant IA de golem.fm. ~100 Ko, jamais dans le heartbeat : ici, à la demande."""
    from . import rigstatus, golemfm
    cat = rigstatus.catalog()
    st, res = golemfm.put_ext("/api/ext/rig/catalog", cat)
    if st not in (200, 201, 204):
        raise RuntimeError(f"catalog push refused ({st}): {res}")
    gear = len(cat.get("amps") or []) + len(cat.get("pedals") or []) + len(cat.get("cabs") or [])
    return {"_log": f"catalog v{cat.get('catalog_version')} pushed ({gear} gear, {len(cat.get('blocks') or [])} blocks)",
            "catalog_version": cat.get("catalog_version"), "gear": gear, "blocks": len(cat.get("blocks") or []),
            "server": res if isinstance(res, dict) else None}


def _push_library(_payload):
    """Relance un miroir complet vers golem.fm (job « push-library », demandé
    depuis la page /golem/library). ACK AU DÉMARRAGE : start_sync() lance un
    thread démon et rend la main — ok = « demande acceptée, sync lancé », pas
    « bibliothèque à jour » (bloquer ici immobiliserait la boucle de jobs
    pendant l'upload des blobs). Un sync DÉJÀ EN COURS n'est pas une erreur du
    point de vue de la demande : l'utilisateur voulait un rafraîchissement, il
    en a un. Seul le cas non-appairé part en erreur (théorique : il a fallu un
    jeton valide pour tirer ce job)."""
    from . import tones_sync
    r = tones_sync.start_sync()
    if r.get("ok"):
        return "library sync started"
    if "already running" in (r.get("error") or ""):
        return "library sync already running — refresh underway"
    raise RuntimeError(r.get("error") or "start_sync refused")


def _fetch_backup(payload):
    """Tire un zip du vault dans la liste locale (backups/) — l'application
    (restore) reste un geste sur l'écran du rack (import inspect+apply)."""
    from . import golemfm
    r = golemfm.pull_backup(payload.get("backup_id"))
    if not r.get("ok"):
        raise RuntimeError(r.get("error") or "pull failed")
    return f"fetched {os.path.basename(r.get('file') or '')} into local backups"


import itertools
_pv_seq = itertools.count(1)


def _generate_preview(job):
    """Génère la démo audio d'un preset À LA DEMANDE DE GOLEMFM (l'user clique dans son
    navigateur ; le rack génère quand il est connecté), puis UPLOAD les clips au blob store
    golem.fm pour lecture navigateur (stockés là -> écoute même GoleM éteint). INCRÉMENTAL :
    chaque scène est uploadée + un progrès poussé DÈS qu'elle est prête (scène A jouable vite).
    Renvoie le mapping complet {scene:{sha256,duration}} -> ack.result. Refus si Gig/verrouillé."""
    from . import preview as preview_mod
    from .state import state
    pid = (job or {}).get("preset")
    jid = job_id(job)
    if not pid:
        raise RuntimeError("preset required")
    mode = state.mode or {}
    if mode.get("id") == "gig" or (mode.get("ui") or {}).get("locked"):
        raise RuntimeError("rack is in a locked/gig mode — try later")

    scenes = {}

    def on_scene(sc, rel):
        """Scène prête -> upload le clip + pousse un PROGRÈS à golem.fm (best-effort)."""
        one = preview_mod.push_clip(pid, sc, rel)          # {sha256, duration} | None
        if not one:
            return
        scenes[sc] = one
        if jid is not None:                                # progress incrémental (endpoint optionnel)
            with __import__("contextlib").suppress(Exception):
                _req("POST", f"/api/ext/tones/jobs/{jid}/progress",
                     body={"scene": sc, "clip": one})

    # `in_key` (2026-09-15, question golem.fm) : un clip = UNE lane (l'entrée), pas un mixage — "1" = la
    # lane principale (défaut), "2" = l'entrée 2 (voix…). `ref` = DI de référence explicite, sinon auto.
    in_key = str(job.get("in_key") or "1")
    preview_mod.generate(pid, next(_pv_seq), on_scene=on_scene, in_key=in_key, ref=job.get("ref"))   # prend le moteur, le remet après
    st = preview_mod.status()
    if st.get("phase") != "done":
        raise RuntimeError(st.get("error") or "generation failed")
    from .store import load_preset
    pv = (load_preset(pid) or {}).get("preview") or {}
    if in_key != "1":
        pv = ((pv.get("alt") or {}).get(in_key)) or pv
    di_name = ((preview_mod._di_index().get(pv.get("ref") or "") or {}).get("name")) or None
    return {"preset": pid,
            "preview": {"ref": pv.get("ref"), "di_name": di_name, "in_key": in_key, "instrument": pv.get("instrument"),
                        "fingerprint": pv.get("fingerprint"), "scenes": scenes},
            "_log": f"preview generated ({len(scenes)} scene·s) + uploaded incrementally"}


def _set_appearance(job):
    """Applique l'apparence (couleurs + animations de la grille Live) configurée sur GOLEMFM
    (Ré-réponse 13 : « configurer le pédalier = sur une app web »). Snapshot-REMPLACE preset.colors
    et preset.anims (métadonnée d'affichage : aucun rebuild moteur, aucun risque live). La page Live
    lit preset.colors[k]/anims[k] au prochain rendu/recall. Ne git-commit PAS (comme save_preset :
    l'écrit sur disque, le mainteneur commite quand il veut)."""
    from .store import load_preset, _write_json_atomic, _safe_id
    from .state import state
    pid = (job or {}).get("preset")
    if not pid:
        raise RuntimeError("preset required")
    mode = state.mode or {}
    if (mode.get("ui") or {}).get("locked"):
        raise RuntimeError("rack is in a locked mode — try later")
    if str(pid).startswith("patch:"):
        # UN PATCH (docs/patches.md, garantie 6) : ses couleurs vivent dans SON fichier — sinon
        # `_safe_id("patch:x")` fabriquait presets/patchx.json, un faux preset
        from . import patches as P
        doc = P.get_patch(str(pid)[len("patch:"):])
        if not doc:
            raise RuntimeError(f"unknown patch '{pid}'")
        doc = dict(doc)
        for k in ("colors", "anims"):
            if isinstance(job.get(k), dict):
                doc[k] = job[k]
        P._write(doc)
        if pid == state.preset_id:
            with __import__("contextlib").suppress(Exception):
                state.touch()
        return f"appearance applied to {pid} ({len(job.get('colors') or {})} colors, {len(job.get('anims') or {})} anims)"
    preset = load_preset(pid)
    if not preset:
        raise RuntimeError(f"unknown preset '{pid}'")
    if isinstance(job.get("colors"), dict):
        preset["colors"] = job["colors"]
    if isinstance(job.get("anims"), dict):
        preset["anims"] = job["anims"]
    _write_json_atomic(os.path.join(C.PRESETS_DIR, f"{_safe_id(pid)}.json"), preset)
    # si ce preset est le rig LIVE, republie l'état pour rafraîchir la grille Live sans attendre un recall
    if pid == state.preset_id:
        with __import__("contextlib").suppress(Exception):
            state.touch()
    return f"appearance applied to {pid} ({len(job.get('colors') or {})} colors, {len(job.get('anims') or {})} anims)"


def _blob_bytes(job, tmp_name):
    """Télécharge le blob (sha) d'un job d'install dans un tmp frais et renvoie ses octets.
    job.sha (ou job.blob.sha256) = adresse du blob dans le vault golem.fm."""
    sha = job.get("sha") or (job.get("blob") or {}).get("sha256")
    if not sha:
        raise RuntimeError("no blob sha")
    tmp = os.path.join(C.ROOT, "presets", tmp_name)
    try:
        os.remove(tmp)                                        # pas de skip sur un tmp périmé
    except OSError:
        pass
    _download_raw(sha, tmp)
    try:
        return open(tmp, "rb").read()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _kit_install(job):
    """Installe un kit poussé par golem.fm (docs/drums-kit.md § réception). job = {action:"kit-install",
    sha, name?} : télécharge le blob .golemkit puis kits.import_kit. Ack {kit:{id}}."""
    from . import kits
    data = _blob_bytes(job, ".kit-install.tmp")
    # la CARTE d'une batterie importée sur un autre rack (docs/drums-kit.md §8.2) : la fiche JSON seule, sans
    # échantillon — rien à installer ici, et surtout pas une fiche qui pointerait des fichiers absents
    try:
        import json
        doc = json.loads(data) if data[:1] in (b"{", b" ") else None
    except Exception:
        doc = None
    if isinstance(doc, dict) and doc.get("engine") in kits.DRUM_ENGINES:
        return {"kit": {"id": doc.get("id")}, "card": True, "installed": False,
                "why": "drum kit card — its samples live on the rack that imported it"}
    r = kits.import_kit(data)
    if not r.get("ok"):
        raise RuntimeError("kit-install: " + str(r.get("error")))
    return {"kit": {"id": (r.get("kit") or {}).get("id")}}


def _groove_install(job):
    """Installe un groove .mid GM poussé par golem.fm. job = {action:"groove-install", sha, name}."""
    from . import grooves
    r = grooves.save_groove(job.get("name") or "groove.mid", _blob_bytes(job, ".groove-install.tmp"))
    if not r.get("ok"):
        raise RuntimeError("groove-install: " + str(r.get("error")))
    return {"groove": {"id": (r.get("groove") or {}).get("id")}}


def _groove_pack(job):
    """Installe un LOT de grooves (.groovepack zip = pack.json + grooves/*.mid) — contrat Addendum 10
    + extensions Addendum 11/12 : `kit` (suggestion, propagée au sidecar de chaque groove) et `song`
    (arrangement segments[{file,mode,times}] -> _songs du sidecar, times 0=∞ pour mode loop).
    job = {action:"groove-pack", sha, name?}. Tolère le partiel : un SMF invalide -> skipped, le pack
    ne casse pas. Ack {name, grooves:[{id,name,file}], skipped:[{file,reason}], song?}."""
    import io, json, zipfile
    from . import grooves
    data = _blob_bytes(job, ".groove-pack.tmp")
    grooves_out, skipped = [], []
    relmap = {}                                                    # rel zip -> id groove installé
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        try:
            manifest = json.loads(zf.read("pack.json"))
        except Exception as e:
            raise RuntimeError("groove-pack: pack.json illisible (" + str(e) + ")")
        kit_sug = manifest.get("kit") or None
        for g in (manifest.get("grooves") or []):
            rel = g.get("file")
            try:
                mid = zf.read(rel)                                # chemin relatif au zip (grooves/x.mid)
            except Exception:
                skipped.append({"file": rel, "reason": "absent du zip"}); continue
            r = grooves.save_groove(g.get("name") or rel,
                                    mid, {"genre": g.get("genre"), "tempo": g.get("tempo"),
                                          "bars": g.get("bars"), "kit": kit_sug,
                                          "pack": job.get("name") or manifest.get("name")})
            if r.get("ok"):
                grooves_out.append(r["groove"]); relmap[rel] = r["groove"]["id"]
            else:
                skipped.append({"file": rel, "reason": r.get("error")})
        # arrangement optionnel : segments -> steps {id, times} (once=1, repeat=n, loop=0=∞)
        song_saved = None
        segs = ((manifest.get("song") or {}).get("segments")) or []
        if segs:
            steps = []
            for s in segs:
                gid = relmap.get(s.get("file"))
                if not gid:
                    skipped.append({"file": s.get("file"), "reason": "segment: groove non installé"}); continue
                mode = s.get("mode") or "repeat"
                times = 1 if mode == "once" else 0 if mode == "loop" else max(1, int(s.get("times") or 1))
                steps.append({"id": gid, "times": times})
            if steps:
                song_saved = grooves.save_song(job.get("name") or manifest.get("name"), kit_sug, steps)
    out = {"name": job.get("name") or manifest.get("name"), "grooves": grooves_out, "skipped": skipped}
    if song_saved:
        out["song"] = song_saved
    return out


def _sample_pack(job):
    """Installe un LOT de samples + son SET ordonné (bloc Sample) — contrat Addendum 15.
    zip = pack.json {name, samples:[{file, name?}]} (l'ORDRE de la liste = l'ordre de cycle
    au pied) + les fichiers audio. job = {action:"sample-pack", sha, name?}. Tolère le
    partiel (fichier absent/format refusé -> skipped). Ack {name, slug, samples, skipped}."""
    import io, json, zipfile
    from . import kits
    data = _blob_bytes(job, ".sample-pack.tmp")
    entries, skipped = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        try:
            manifest = json.loads(zf.read("pack.json"))
        except Exception as e:
            raise RuntimeError("sample-pack: pack.json illisible (" + str(e) + ")")
        for s in (manifest.get("samples") or []):
            rel = s.get("file")
            try:
                raw = zf.read(rel)
            except Exception:
                skipped.append({"file": rel, "reason": "absent du zip"}); continue
            r = kits.save_sample(os.path.basename(rel or ""), raw,
                                 kind=s.get("kind") if s.get("kind") in ("short", "song") else "short")
            if r.get("ok"):
                entries.append({"file": r["file"],
                                "name": s.get("name") or os.path.splitext(os.path.basename(rel))[0]})
            else:
                skipped.append({"file": rel, "reason": r.get("error")})
    name = job.get("name") or manifest.get("name") or "Sample set"
    out = {"name": name, "samples": entries, "skipped": skipped}
    if entries:
        from .routes_content import _SS_DIR, _bp_slug, _write_json_atomic
        slug = _bp_slug(name)
        os.makedirs(_SS_DIR, exist_ok=True)
        _write_json_atomic(os.path.join(_SS_DIR, slug + ".json"),
                           {"name": name, "samples": entries, "origin": "golemfm",
                            "pack": manifest.get("name")})
        out["slug"] = slug
    return out


def _inputmap_set(job):
    """Le patch d'une carte écrit DEPUIS golem.fm (docs/returns.md §3, R1 2026-09-26) :
    `{action:"inputmap-set", card, entries:[{slot:"IN 3"|"USB 1", role?, nth?, person?}],
      outputs:[{slot:"OUT 3-4", role?, person?, type?}], pairs:[{kind, a, b, linked}]}`.
    Par LES MÊMES fonctions que l'écran (inputmap.set_*), donc les mêmes gardes — plus trois qui
    n'existent que parce que l'appelant est loin : tout-ou-rien (un refus = rien d'écrit, les fichiers
    sont remis tels quels), `person` = un handle du roster (jamais un invité créé depuis le web), et la
    carte ACTIVE ne se recâble pas pendant une prise, une chanson ou un mode verrouillé — une carte non
    active (celle du concert, préparée le mardi) s'écrit sans condition."""
    import json as _j
    import re as _re
    from . import config as C, inputmap, rigstatus, cards as _cards
    from .state import state
    card = str(job.get("card") or "")
    if not card:
        raise RuntimeError("inputmap-set: need card")
    dev = inputmap.device_of(card)
    known = {f"hw:{c.get('id')}" for c in _cards.registry() if c.get("id")}
    if dev not in known and not os.path.exists(inputmap._path(dev)):
        raise RuntimeError(f"inputmap-set: unknown card {card} — declare it on the rack first")
    if dev == inputmap._card_device():
        if (state.perf or {}).get("recording"):
            raise RuntimeError("refused: a take is recording on the active card")
        if (state.backing or {}).get("playing") or (state.arrangement or {}).get("running"):
            raise RuntimeError("refused: a song is playing on the active card")
        if ((state.mode or {}).get("ui") or {}).get("locked"):
            raise RuntimeError("refused: the mode is locked — unlock on the rack first")
    people = set(inputmap._people())
    def person_ok(p):
        return p is None or (isinstance(p, str) and p and not p.startswith("guest:") and p in people)
    def ch_of(slot, prefix):
        m = _re.fullmatch(r"\s*(IN|OUT|USB)\s+([0-9]+(?:-[0-9]+)?)\s*", str(slot or ""), _re.I)
        if not m:
            raise ValueError(f"bad slot {slot!r}")
        k, n = m.group(1).upper(), m.group(2)
        if k == "USB":
            return f"usb{n}"
        if k != prefix:
            raise ValueError(f"slot {slot!r} is not an {prefix} slot")
        return n
    # instantané des deux fichiers que les setters touchent : le patch de la carte, le registre USB
    paths = [inputmap._path(dev), os.path.join(C.CONFIG_DIR, "devices.json")]
    before = {}
    for pth in paths:
        try:
            before[pth] = open(pth, encoding="utf-8").read()
        except OSError:
            before[pth] = None
    refused, applied = [], []
    try:
        for e in job.get("entries") or []:
            slot = e.get("slot")
            try:
                ch = ch_of(slot, "IN")
                if "person" in e and not person_ok(e.get("person")):
                    raise ValueError(f"unknown person {e.get('person')!r} — a roster handle, never a guest")
                if e.get("role") is not None:
                    inputmap.set_role("input", ch, str(e["role"]), dev)
                if "nth" in e:
                    inputmap.set_nth(ch, e.get("nth"), dev)
                if "person" in e:
                    inputmap.set_person(ch, e.get("person"), dev)
                applied.append(slot)
            except ValueError as ex:
                refused.append({"slot": slot, "why": str(ex)})
        for o in job.get("outputs") or []:
            slot = o.get("slot")
            try:
                ch = ch_of(slot, "OUT")
                if "person" in o and not person_ok(o.get("person")):
                    raise ValueError(f"unknown person {o.get('person')!r} — a roster handle, never a guest")
                if o.get("role") is not None:
                    inputmap.set_role("output", ch, str(o["role"]), dev)
                if "person" in o or "type" in o:
                    inputmap.set_out_person(ch, o.get("person") if "person" in o else None,
                                            o.get("type", ...), dev)
                applied.append(slot)
            except ValueError as ex:
                refused.append({"slot": slot, "why": str(ex)})
        for pr in job.get("pairs") or []:
            try:
                inputmap.set_pair(pr.get("kind") or "input", pr.get("a"), pr.get("b"), bool(pr.get("linked")), dev)
                applied.append(f"pair {pr.get('a')}-{pr.get('b')}")
            except ValueError as ex:
                refused.append({"slot": f"pair {pr.get('a')}-{pr.get('b')}", "why": str(ex)})
        if refused:
            raise ValueError("refused")
    except ValueError:
        for pth, txt in before.items():                       # TOUT-OU-RIEN : on remet les fichiers tels quels
            try:
                if txt is None:
                    if os.path.exists(pth):
                        os.remove(pth)
                else:
                    tmp = pth + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(txt)
                    os.replace(tmp, pth)
            except OSError as _e:
                _swallowed(_e, "inputmap-set rollback")
        raise RuntimeError("refused, nothing written: " + "; ".join(f"{r['slot']}: {r['why']}" for r in refused))
    if dev == inputmap._card_device():
        state.inputmap = inputmap.current()
        state.touch()
    rigstatus.push_soon()
    cards = rigstatus.cards_doc()
    return {"card": dev, "applied": applied, "cards": cards, "patch_version": rigstatus.patch_version(cards),
            "_log": f"{dev}: {len(applied)} slot(s) written"}


# l'ENVELOPPE commune de tout job (`GET /api/ext/tones/jobs` → {id, device, action, created_at, **payload}) :
# jamais des champs du mode. Trouvé au premier job réel (2026-09-26 : « device: unknown field »).
JOB_ENVELOPE = ("id", "device", "action", "created_at", "created", "payload", "_job", "space")


def job_id(j):
    """L'id du JOB (pour l'ack, la progression, « en cours »). golem.fm aplatit le payload APRÈS l'enveloppe :
    un payload qui porte `id` (song-install, golem-upload, standards, Vocals…) ÉCRASE celui du job, et l'ack
    partait vers /jobs/rs:…/ack (trouvé par golem.fm en codant song-separate, 2026-10-12). `_job`, posé par
    golem.fm APRÈS le payload, ne peut pas être écrasé ; `id` reste le repli tant qu'il ne l'envoie pas."""
    j = j or {}
    return j["_job"] if j.get("_job") is not None else j.get("id")


def _reamp(job):
    from . import reamp
    return reamp.run(job)


def _active_mode_busy():
    """Pourquoi le mode ACTIF ne s'édite pas depuis loin en ce moment — ou None."""
    from .state import state
    if (state.perf or {}).get("recording"):
        return "a take is recording"
    if (state.backing or {}).get("playing") or (state.arrangement or {}).get("running"):
        return "a song is playing"
    if ((state.mode or {}).get("ui") or {}).get("locked"):
        return "the mode is locked — exit it on the rack first"
    return None


def _mode_set(job):
    """Un mode réglé DEPUIS golem.fm (docs/modes.md, addendum 2026-09-26) :
    `{action:"mode-set", mode:"rehearsal", space?:"b_…", name?, icon?, desc?, services?, inputs_off?,
      card?, band?, click_mode?, live_view?}` — par le MÊME chemin que la feuille du rack
    (modes.validate_update / apply_update / commit). Gardes distantes : tout-ou-rien (un champ refusé =
    rien d'écrit), carte du registre ou "", `band` = un espace du roster (le rack ne crée jamais d'espace),
    la règle d'espace TENUE si le job porte `space` (le mode doit être de cet espace), refus sur le mode
    ACTIF pendant une prise, une chanson ou un verrouillage. Jamais : le verrou, les pages, le boot,
    perf_boost, perfrec_mode, take_kind (modes.NEVER_REMOTE)."""
    from . import modes as _modes, rigstatus, cards as _cards, roster as _roster
    from .state import state
    # `mode` seul : `id` est l'id du JOB dès que le payload ne le porte pas (enveloppe aplatie) — le prendre
    # pour un id de mode visait un mode au hasard. golem.fm envoie `mode` (band_dashboard, vérifié 2026-10-15).
    mid = str(job.get("mode") or "")
    if not mid:
        raise RuntimeError("mode-set: missing id (the job carries no `mode`)")
    m = next((x for x in _modes.list_modes() if x["id"] == mid), None)
    if m is None:
        raise RuntimeError(f"mode-set: unknown mode {mid!r}")
    fields = {k: v for k, v in job.items() if k not in JOB_ENVELOPE and k != "mode"}   # `mode` = la cible, ici
    if job.get("space") and (m.get("band") or None) != str(job["space"]):
        raise RuntimeError(f"refused: mode {mid} belongs to space {m.get('band') or 'none'}, not {job['space']}")
    known_cards = {c.get("id") for c in _cards.registry() if c.get("id")}
    known_bands = {b.get("id") for b in (_roster.read().get("bands") or []) if b.get("id")}
    refused = _modes.validate_update(fields, known_cards, known_bands)
    if refused:
        raise RuntimeError("refused, nothing written: " + "; ".join(f"{k}: {why}" for k, why in refused))
    if (state.mode or {}).get("id") == mid:
        why = _active_mode_busy()
        if why:
            raise RuntimeError(f"refused: {mid} is the active mode and {why}")
    _modes.apply_update(m, fields)
    saved = _modes.commit(m)
    if (state.mode or {}).get("id") == mid:                  # le mode courant se re-propage (state + veto)
        try:
            from . import routes_modes
            routes_modes._refresh_if_current(mid)
        except Exception as _e:
            _swallowed(_e, "mode refresh")
    rigstatus.push_soon(with_modes=True)
    ctx = rigstatus.modes_ctx()
    return {"mode": _modes.doc({**saved, "_factory": mid in {x["id"] for x in _modes.list_modes() if x.get("_factory")},
                                 "_modified": m.get("_modified"), "_custom": m.get("_custom")}),
            "modes": rigstatus.modes_table(), "modes_version": ctx["modes_version"],
            "_log": f"mode {mid}: {', '.join(sorted(fields))} written"}


def _recorder_set(job):
    """La config GLOBALE du magnétophone depuis golem.fm — `{action:"recorder-set", in1?, in2?, usb?, mode?,
    mix?, transcribe?, count_in?}` (mêmes clés que POST /api/recorder, clés inconnues refusées). Jamais
    pendant une prise."""
    from . import store, rigstatus
    from .state import state
    if (state.perf or {}).get("recording"):
        raise RuntimeError("refused: a take is recording")
    fields = {k: v for k, v in job.items() if k not in JOB_ENVELOPE}
    bad = [k for k in fields if not (re.fullmatch(r"in\d+", k) or k in ("usb", "mode", "mix", "transcribe", "count_in"))]
    if bad:
        raise RuntimeError("refused, nothing written: unknown field(s) " + ", ".join(bad))
    if "mode" in fields and fields["mode"] not in ("mix", "tracks", "tracks_di"):
        raise RuntimeError("refused, nothing written: mode is one of mix, tracks, tracks_di")
    if "transcribe" in fields and fields["transcribe"] not in ("manual", "auto"):
        raise RuntimeError("refused, nothing written: transcribe is manual or auto")
    cfg = store.save_recorder_cfg(fields)
    try:
        from .store import load_preset, rec_sources, _write_json_atomic
        cur = load_preset(state.preset_id) if state.preset_id else None
        _write_json_atomic(os.path.join(C.PRESETS_DIR, ".perfsrc.json"), rec_sources(cur), indent=None)
    except Exception as _e:
        _swallowed(_e, "perfsrc")
    rigstatus.push_soon(with_modes=True)
    return {"recorder": cfg, "modes_version": rigstatus.modes_ctx()["modes_version"], "_log": "recorder config written"}


def _block_status(job):
    """`{action:"block-status", sha, role}` (le même document qu'un patch-try) ou `{action:"block-status",
    preset:<id>}` : l'ÉTAT de chaque bloc calculé par le rack lui-même (docs/block-status.md §7) — prêt,
    à télécharger (source, taille), indisponible ici (raison), vide. Rien n'est installé ni joué : c'est
    ce qui permet à golem.fm d'écrire « 3 elements to download on the rack » quand son estimation ne
    suffit pas. `caps` vient avec (OS, moteur, types absents)."""
    from . import blockstatus as BS
    from .store import load_preset, rich_chain
    if job.get("preset"):
        preset = load_preset(str(job["preset"]))
        if preset is None:
            raise RuntimeError(f"unknown preset '{job['preset']}'")
    else:
        _doc, role, shape, _scenes = _patch_doc(job, ".block-status.tmp")
        preset = {"id": "block-status", "lanes_v": 2, "lanes": [{
            "id": f"{role}-try", "role": role,
            "chain": rich_chain(shape if "chain" not in shape else {"pre": shape["chain"], "split": None, "post": []})}]}
    st = BS.preset_status(preset)
    st["caps"] = BS.caps()
    st["suggested"] = [x for x in (BS.suggestion(b, BS.manifest_tones) for b in _capture_blocks(preset)) if x]
    s = st["summary"]
    st["_log"] = (f"{s['missing']} block(s) not ready — {s['download']['n']} to download, "
                  f"{s['unavailable']} unavailable here, {s['empty']} empty")
    return st


def _capture_blocks(preset):
    from .store import all_blocks
    return [b for b, _l in all_blocks(preset) if isinstance(b, dict) and b.get("type") in CAPTURE_TYPES and not b.get("ref")]


_HANDLERS = {
    "install": lambda j: _install(j["uid"]),
    "block-status": lambda j: _block_status(j),     # docs/block-status.md §7 : ce qui manque, dit par le rack
    "remove": lambda j: _remove(j["uid"]),
    "recall": lambda j: _recall(j),
    "fetch-backup": lambda j: _fetch_backup(j),
    "t3k-install": lambda j: _t3k_install(j),
    "push-library": lambda j: _push_library(j),
    # le catalogue du matériel (amplis, pédales, baffles, blocs + quarantaine) : golem.fm le tire quand
    # `catalog_version` change dans le heartbeat (docs/private/exchanges/message-maestrium-installer-2.md §1)
    "push-catalog": lambda j: _push_catalog(j),
    # patches et presets depuis golem.fm (docs/private/exchanges/message-maestrium-patches-push-splits.md, patches.md §17)
    "preset-install": lambda j: _preset_install(j),
    "patch-install": lambda j: _patch_install(j),
    "patch-push": lambda j: _patch_install(j),          # alias : le job de PUBLICATION de l'assistant
    "patch-try": lambda j: _patch_try(j),
    "patch-preview": lambda j: _patch_preview(j),       # Store : l'écoute enregistrée d'un patch (patches.md §22)
    # suppression depuis golem.fm (patches.md §21) : un id absent n'est pas une erreur
    "patch-delete": lambda j: _patch_delete(j),
    "preset-delete": lambda j: _preset_delete(j),
    "generate-preview": lambda j: _generate_preview(j),
    # docs/reamp.md : n'arrive ici que versé par le veilleur de reamp.py, quand le rack est libre
    "reamp": lambda j: _reamp(j),
    "set-appearance": lambda j: _set_appearance(j),
    "kit-install": lambda j: _kit_install(j),
    "groove-install": lambda j: _groove_install(j),
    "groove-pack": lambda j: _groove_pack(j),
    "sample-pack": lambda j: _sample_pack(j),
    "rig-status": lambda j: _rig_status(j),
    "inputmap-set": lambda j: _inputmap_set(j),     # le patch d'une carte depuis golem.fm (docs/returns.md R1)
    "mode-set": lambda j: _mode_set(j),             # un mode depuis golem.fm (docs/modes.md, addendum 2026-09-26)
    "recorder-set": lambda j: _recorder_set(j),     # la config globale du magnétophone, idem
    "diagnostic-report": lambda j: _diagnostic_report(j),   # lot 8 (docs/diagnostics.md §4.4)
    "setlist-push": lambda j: _setlist_push(j),
    "song-push": lambda j: _song_push(j),      # le RÉPERTOIRE (docs/songs.md)
    # un .golem fabriqué par golem.fm (plan-song-sharing lot 2) : téléchargé, vérifié, fusionné (golem_pull.py)
    "song-install": lambda j: _song_install(j),
    # le geste « Store on golem.fm » fait sur golem.fm : le golem envoie le .golem qu'il détient (song-sharing §2.7)
    "golem-upload": lambda j: _golem_upload(j),
    # séparer l'original d'une chanson avec le moteur actif du golem (docs/separation.md §8) : file à part, ack différé
    "song-separate": lambda j: __import__("bridge.separation", fromlist=["on_job"]).on_job(j),
    # une recette de capture proposée par l'IA de golem.fm : mesurée À CÔTÉ de la file (docs/plugin-recipes.md §5-6)
    "plugin-recipe": lambda j: __import__("bridge.plugin_recipes", fromlist=["on_job"]).on_job(j),
    # la configuration de carte d'un AUTRE rack, proposée par golem.fm : gardée, montrée, jamais appliquée seule
    "card-setup-offer": lambda j: __import__("bridge.card_setups", fromlist=["on_job"]).on_job(j),
    "take-tag": lambda j: _take_tag(j),
    "take-upload": lambda j: _take_upload(j),
    "upload-di": lambda j: _upload_di(j),
    "take-cut": lambda j: _take_cut(j),
    "take-recut": lambda j: _take_recut(j),
    "take-source-release": lambda j: _take_source_release(j),
    "anim-pack-install": lambda j: _anim_pack_install(j),
    "anim-pack-remove": lambda j: _anim_pack_remove(j),
}


def _anim_pack_install(job):
    """Installe un pack d'animations poussé par golem.fm (docs/anim-packs.md).

    job = {action:"anim-pack-install", pack_id, version} — payload APLATI comme les 15 autres
    actions. Ma spec annonçait `GET /jobs` avec {kind, payload:{…}} : c'était FAUX, l'agent
    golem.fm l'a relevé et le canal réel est bien /api/ext/tones/jobs avec `action`.
    Le serveur rend `{pack, css}` — exactement le corps de POST /api/anim-packs/install, donc
    aucun réassemblage ici.
    """
    from . import anim_packs
    pid = job.get("pack_id")                   # jamais `id` : c'est celui du JOB quand le payload n'en porte pas
    if not pid:
        raise RuntimeError("anim-pack-install: missing id (the job carries no `pack_id`)")
    st, doc = _req("GET", f"/api/ext/anim-packs/{pid}")
    if st != 200 or not isinstance(doc, dict):
        raise RuntimeError(f"anim-pack-install: catalogue {st}")
    r = anim_packs.install(doc.get("pack") or {}, doc.get("css") or "")
    if not r.get("ok"):
        # on remonte TOUS les motifs : ils sont écrits pour l'auteur du pack, pas pour nous
        raise RuntimeError("anim-pack-install: " + " · ".join(r.get("errors") or ["refusé"]))
    return {"pack": {"id": r.get("id"), "effects": r.get("effects")},
            "warnings": r.get("warnings") or []}


def _anim_pack_remove(job):
    """Retire un pack. Enfilé sans vérifier le droit côté serveur (à dessein : on doit pouvoir
    retirer un pack dont on a perdu l'accès) — c'est ICI que `default` est refusé."""
    from . import anim_packs
    pid = job.get("pack_id")                   # jamais `id` : c'est celui du JOB quand le payload n'en porte pas
    if not pid:
        raise RuntimeError("anim-pack-remove: missing id (the job carries no `pack_id`)")
    r = anim_packs.remove(pid)
    if not r.get("ok"):
        raise RuntimeError("anim-pack-remove: " + str(r.get("error")))
    return {"pack": {"id": pid}}


def _rig_status(job):
    """Status rig on-demand (Addendum 13) : ack = objet COMPLET (sondes actives incluses)."""
    from . import rigstatus
    return rigstatus.full()


def _diagnostic_report(job):
    """Un paquet `event` demandé depuis golem.fm — gouverné par LA case du rack : décochée, l'ack
    dit `reports disabled on this rack` et golem.fm l'affiche tel quel. Le paquet est envoyé
    AVANT l'ack, qui porte son report_id et son sha256."""
    from . import diag
    if not diag.auto():
        raise RuntimeError("reports disabled on this rack")
    r = diag.build("event", event_={"type": "requested", "detail": str(job.get("detail") or "requested from golem.fm")})
    if not r:
        raise RuntimeError("report not built")
    ok, detail = diag.send(r["report_id"])
    if not ok:
        raise RuntimeError(f"report built but not sent: {detail}")
    return {"report_id": r["report_id"], "sha256": r["sha256"], "size": r["size"],
            "_log": f"event report {r['file']} sent"}


def _setlist_push(job):
    """Une setlist entière depuis le web (docs/setlists.md §9.5) : `{action:"setlist-push",
    setlist:{id, name, rev, fcb, complete, lines:[…]}}`. Fusion par id/rev (égalité au rack),
    `complete` supprime, jamais sous les pieds (mode verrouillé -> attente, §9.6). Les lignes que
    le rack a gardées contre le web repartent (push miroir) pour qu'il converge."""
    from . import golemfm, setlists as _sl
    doc = job.get("setlist")
    if not isinstance(doc, dict) or not doc.get("id"):
        raise RuntimeError("setlist-push: need setlist:{id, lines}")
    out = _sl.receive_push(doc)
    if not out.get("deferred") and out.get("resend"):
        golemfm.push_setlist(_sl._safe_id(doc["id"]), delay=2.0)
    out["_log"] = ("deferred (locked mode)" if out.get("deferred") else
                   f"added {len(out.get('added', []))}, updated {len(out.get('updated', []))}, "
                   f"removed {len(out.get('removed', []))}, resend {len(out.get('resend', []))}")
    return out


def _song_install(job):
    """Un .golem fabriqué par golem.fm : `{id, slug, url, etag}` -> ack `{song: {id}, missing}` (golem_pull.py)."""
    from . import golem_pull
    return golem_pull.song_install(job)


def _golem_upload(job):
    """`{id, category, mode, url, room, asked_at}` -> ack `{ok, kind, slug, golem_etag}` (inventory.py)."""
    from . import inventory
    return inventory.golem_upload_job(job)


def _song_push(job):
    """Un lot du RÉPERTOIRE depuis le web (docs/songs.md §7) : `{action:"song-push",
    band?, complete?, songs:[{id:"bs:…", rev, title, artist, kind, song_slug?, sheet:{…}}]}`.

    Même arbitrage qu'une setlist, et pour la même raison : le rack garde ce qui a réellement
    joué. `complete` retire les chansons locales absentes du lot — et seulement celles de
    l'espace concerné, un rack servant plusieurs groupes.

    ⚠ Cette action n'a PAS encore d'émetteur : au 2026-09-20 aucune route de golem.fm ne liste le
    répertoire d'un groupe pour un appareil apparié (§7, mesuré par leur agent). Le récepteur
    existe d'abord pour que leur moitié ait une cible, pas parce qu'il est déjà nourri."""
    from . import songs as _sg
    rows = job.get("songs")
    if not isinstance(rows, list):
        raise RuntimeError("song-push: need songs:[{id, sheet}]")
    out = _sg.merge_push(rows, band=job.get("band"), complete=bool(job.get("complete")))
    out["_log"] = (f"added {len(out['added'])}, updated {len(out['updated'])}, "
                   f"removed {len(out['removed'])}, resend {len(out['resend'])}")
    return out


def _take_tag(job):
    """Retag de prises depuis le web (docs/private/exchanges/message-maestrium-ranger-prises.md §2) :
    job = {action:"take-tag", takes:[{uid, band|null}]}. Ack {tagged:[uid…], skipped:[{uid,
    reason}]} — PARTIEL TOLÉRÉ, un uid inconnu n'annule pas le lot. Ne DÉCLENCHE PAS la montée :
    le tag est l'intention, le monteur (J2) la lit à son tour. Un heartbeat part dans la foulée
    pour que l'écran web voie le nouveau tag sans attendre 5 min."""
    from . import rigstatus, takes
    items = job.get("takes")
    if not isinstance(items, list):
        raise RuntimeError("take-tag: need takes:[{uid, band}]")
    out = takes.tag(items)
    rigstatus.push_soon()
    out["_log"] = f"tagged {len(out['tagged'])}, skipped {len(out['skipped'])}"
    return out


def _take_upload(job):
    """La MONTÉE, depuis le web (message ranger-prises §2, lot B) :
    `{action:"take-upload", takes?:[uid], kinds?:["di","midi"]}`.

    `takes` ABSENT = tout ce qui est tagué (leur contrat : la liste vide, elle, est un 400
    chez eux — on ne devine pas entre « rien » et « tout »). `kinds` ajoute les DI et le
    MIDI aux lanes traitées : c'est le « Request DI » de l'écran, qui n'avait pas de
    consommateur (message « enregistrements » §7).

    L'ack dit `queued`, pas `done` : monter une répète prend des minutes, et la boucle du
    monteur s'interrompt dès qu'on rejoue. La progression se lit dans le heartbeat
    (`pending_takes[].upload`), là où l'écran la regarde déjà.
    """
    from . import uploader
    uids = job.get("takes")
    if uids is not None and not isinstance(uids, list):
        raise RuntimeError("take-upload: takes must be a list of uid")
    kinds = job.get("kinds")
    if kinds is not None and not isinstance(kinds, list):
        raise RuntimeError("take-upload: kinds must be a list")
    kinds = tuple(uploader.DEFAULT_KINDS) + tuple(kinds) if kinds else None
    out = uploader.queue(uids, kinds)
    out["_log"] = f"queued {len(out['queued'])}, skipped {len(out['skipped'])}"
    return out


def _upload_di(job):
    """`{action:"upload-di", uid, band?}` — « Request DI » du web : monter les pistes DI d'UNE prise, même déjà montée
    (son mix et ses lanes sont là ; la DI ne part que sur demande). `take-upload` avec `kinds:["di"]` ne le pouvait pas :
    une prise montée sort de la file du monteur. L'ack dit `queued` ; l'avancement est dans le manifeste (`upload_di`)."""
    from . import uploader
    uid = job.get("uid")
    if not isinstance(uid, str) or not uid:
        raise RuntimeError("upload-di: missing uid")
    band = job.get("band")
    out = uploader.queue_di(uid, band if isinstance(band, str) and band else None)
    out["_log"] = f"DI of {uid} queued"
    return out


def _take_cut(job):
    """`{action:"take-cut", takes?:[uid]}` — découpe une longue prise en morceaux nommés
    (message-golem-modes-espaces.md §1.4). `takes` absent = toutes les longues prises taguées.

    Ack `queued` : la découpe tourne dans la boucle du monteur, donc jamais pendant un REC ni
    en mode Gig, et la progression se lit dans `pending_takes[]` comme celle d'une montée.
    Le bouton du web s'appelle « Cut & upload » : la montée suit, au tour suivant."""
    from . import uploader
    uids = job.get("takes")
    if uids is not None and not isinstance(uids, list):
        raise RuntimeError("take-cut: takes must be a list of uid")
    out = uploader.queue(uids, None)
    out["_log"] = f"queued {len(out['queued'])} (cut+upload)"
    return out


def _take_recut(job):
    """`{action:"take-recut", parent:"perf-…", bounds:[{offset_sec, duration_sec}]}` — la
    CORRECTION venue du web : fusionner deux segments, couper là où on entend un blanc.

    Le rack re-découpe DEPUIS LA SOURCE, qu'il a gardée exprès jusqu'à validation — c'est tout
    l'intérêt de ne pas l'effacer à la montée. Les morceaux de la passe précédente sont
    remplacés ; l'ack dit lesquels vivent maintenant et lesquels ont disparu."""
    from . import takecut, takes
    parent = job.get("parent")
    bounds = job.get("bounds")
    if not parent or not isinstance(bounds, list) or not bounds:
        raise RuntimeError("take-recut: need parent and non-empty bounds[]")
    name = next((e["name"] for e in takes._entries() if takes.uid_of(e["name"]) == parent), None)
    if name is None:
        raise RuntimeError(f"take-recut: unknown take {parent}")
    before = set((takes._read_json(takes.manifest_path_of(name) or "") or {})
                 .get("cut", {}).get("children") or [])
    rep = takecut.cut(name, bounds=bounds)
    if not rep.get("ok"):
        raise RuntimeError(f"take-recut: {rep.get('reason')}")
    uids = rep.get("uids") or []
    out = {"ok": True, "uids": uids, "removed": sorted(before - set(uids)),
           "skipped": rep.get("skipped") or []}
    out["_log"] = f"recut {parent}: {len(uids)} morceau(x), {len(out['removed'])} retiré(s)"
    return out


def _take_source_release(job):
    """`{action:"take-source-release", takes:[uid]}` — golem.fm a validé les frontières, la
    source entière peut partir du disque (§1.4). Seul le `take.json` reste.

    Refuse une prise NON DÉCOUPÉE : libérer la source de quelque chose qui n'a pas encore de
    morceaux, ce serait effacer la prise elle-même."""
    from . import takecut, takes
    uids = job.get("takes")
    if not isinstance(uids, list) or not uids:
        raise RuntimeError("take-source-release: need a non-empty takes[]")
    by_uid = {takes.uid_of(e["name"]): e["name"] for e in takes._entries()}
    freed, done, skipped = 0, [], []
    for u in uids:
        if u not in by_uid:
            skipped.append({"uid": u, "reason": "unknown_take"})
            continue
        r = takecut.release_source(by_uid[u])
        if r.get("ok"):
            freed += r["freed_bytes"]
            done.append(u)
        else:
            skipped.append({"uid": u, "reason": r.get("reason")})
    out = {"released": done, "skipped": skipped, "freed_bytes": freed}
    out["_log"] = f"released {len(done)}, freed {freed // 1048576} Mo"
    return out


def process(wait=0):
    """Tire la file et traite tout. Rend {"processed": n, "errors": n} ;
    {"ok": False} si non appairé ou passage déjà en cours.
    `wait` (s) : LONG-POLL — demande à golem.fm de BLOQUER jusqu'à un job (ou timeout wait),
    pour une prise en charge quasi-instantanée (au lieu d'attendre le prochain tick). Dégrade
    proprement : un serveur qui ignore `?wait` répond tout de suite (comportement d'avant)."""
    from .golemfm import _cfg as m_cfg
    base, token = m_cfg()
    if not base or not token:
        return {"ok": False, "error": "not paired"}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "already running"}
    try:
        if wait:
            st, res = _req("GET", f"/api/ext/tones/jobs?wait={int(wait)}", timeout=int(wait) + 15)
        else:
            st, res = _req("GET", "/api/ext/tones/jobs")
        if st != 200:
            return {"ok": False, "error": f"jobs: {st or 'unreachable'} {res}"}
        # ── DEUX VOIES (audit 2026-09-13, M6, fin) : la file est ordonnée PAR FAMILLE, pas globalement.
        # Un `install` de 200 Mo n'a aucune raison de retenir un `take-tag` ; mais un `patch-try` DOIT
        # attendre le `preset-install` qui le précède. Chaque voie est un worker FIFO ; process() ne
        # fait que DISPATCHER (et se souvenir de ce qui est en cours : golem.fm re-propose un job tant
        # qu'il n'est pas acquitté — sans ce registre, on le lancerait deux fois).
        dispatched = 0
        for j in res.get("jobs", []):
            jid = job_id(j)
            with _inflight_lock:
                if jid in _inflight:
                    continue
                _inflight.add(jid)
            if j.get("action") == "reamp":
                # docs/reamp.md §3 : il PREND le moteur, donc il attend que le rack soit libre — hors
                # des voies, sinon il bloquerait tout ce qui le suit. Reste dans _inflight : pas de doublon.
                from . import reamp
                reamp.enqueue(j)
            else:
                _lane(j.get("action")).put(j)
            dispatched += 1
        import time
        _ST.update(last=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        # `processed` compte les jobs PRIS (le poller s'en sert pour son cadencement) ; les acquittés
        # et les erreurs se comptent dans les workers.
        return {"ok": True, "processed": dispatched, "errors": 0, "inflight": len(_inflight)}
    finally:
        _lock.release()


_poller = None

# ── les voies : « sync » (prises, setlists, catalogue — du réseau, jamais Reaper) et « rig »
# (tout ce qui installe, monte ou fait sonner : ordonné, un à la fois). Un nom de voie par job,
# jamais un choix par taille : l'ordre entre `preset-install` et `patch-try` est un contrat.
import queue as _queue
_SYNC_PREFIXES = ("take-", "setlist-", "push-catalog")
_LANES = {"sync": _queue.Queue(), "rig": _queue.Queue()}
_inflight = set()
_inflight_lock = threading.Lock()
_workers = {}


def lane_of(action):
    return "sync" if str(action or "").startswith(_SYNC_PREFIXES) else "rig"


def _lane(action):
    _ensure_workers()
    return _LANES[lane_of(action)]


def _diag_job(j, ok, t0):
    """lot 8 : chaque job dans la chronologie (action, issue, durée) — jamais son contenu."""
    try:
        from . import diag
        diag.event("job", action=str(j.get("action")), ok=bool(ok), ms=round((time.monotonic() - t0) * 1000))
    except Exception as _e:
        _swallowed(_e, "diag job")


def _run_job(j):
    """Un job : handler, ack (ok OU erreur — jamais re-proposé), journal, compteurs. Le contrat
    d'avant, déplacé du poller vers le worker de sa voie."""
    j.pop("_doc", None)          # réservé au rack (_job_doc) : un job reçu ne le porte jamais
    handler = _HANDLERS.get(j.get("action"))
    _t0 = time.monotonic()
    if j.get("action") == "reamp":
        from . import reamp
        try:
            _run_one(j, handler, _t0)
        except reamp.Deferred as e:
            # le rack est redevenu occupé : PAS d'ack (golem.fm le garde pending), retour en file,
            # et il reste dans _inflight — le veilleur le reversera quand le rack sera libre
            reamp.requeue(j)
            _log(f"job #{job_id(j)} reamp deferred: {e}")
            return
        reamp.finished()
        with _inflight_lock:
            _inflight.discard(job_id(j))
        return
    try:
        _run_one(j, handler, _t0)
    finally:
        if not j.get("_async"):
            with _inflight_lock:
                _inflight.discard(job_id(j))


def async_done(job_id):
    """L'ack d'un job ASYNC_ACK est parti : il quitte « en cours » (bridge/plugin_recipes.py)."""
    with _inflight_lock:
        _inflight.discard(job_id)


def _run_one(j, handler, _t0):
    """Le cœur de `_run_job` : handler + ack (ok OU erreur). `reamp.Deferred` traverse sans ack."""
    try:
        if handler is None:
            raise RuntimeError(f"unknown action '{j.get('action')}'")
        msg = handler(j)
        _diag_job(j, True, _t0)
        from .plugin_recipes import ASYNC_ACK
        if msg is ASYNC_ACK:                     # l'ack partira de la vérification (≈1 min, rack libre)
            j["_async"] = True                   # … et le job reste « en cours » jusque-là : pas de doublon
            _log(f"job #{job_id(j)} {j['action']}: accepted, ack when measured")
            return
        if j.get("action") in ("install", "t3k-install", "push-library"):
            try:                                             # verdict « pack à écho » des IR fraîchement posées
                from . import ir_quality
                ir_quality.scan_async()
            except Exception as _e:
                _swallowed(_e, "ir quality")
        ack = {"ok": True}
        if isinstance(msg, dict):
            ack["result"] = {k: v for k, v in msg.items() if k != "_log"}
            msg = msg.get("_log", "done")
        _req("POST", f"/api/ext/tones/jobs/{job_id(j)}/ack", body=ack)
        _log(f"job #{job_id(j)} {j['action']}: {msg}")
        _ST["processed"] += 1
        from . import arrivals                   # l'écran ouvert voit arriver ce qui vient d'être posé
        arrivals.note(j.get("action"))
    except Exception as e:                        # ack erreur : jamais re-proposé
        from . import reamp
        if isinstance(e, reamp.Deferred):
            raise                                 # rack occupé : aucun ack, l'appelant le remet en file
        _diag_job(j, False, _t0)
        _req("POST", f"/api/ext/tones/jobs/{job_id(j)}/ack",
             body={"ok": False, "error": str(e)[:500]})
        _log(f"job #{job_id(j)} {j['action']} KO: {e}")
        _ST["errors"] += 1


def _ensure_workers():
    for name, q in _LANES.items():
        w = _workers.get(name)
        if w is not None and w.is_alive():
            continue

        def loop(q=q, name=name):
            while True:
                j = q.get()
                try:
                    _run_job(j)
                except Exception as e:                 # le worker ne meurt JAMAIS sur un job
                    log.warning(f"lane {name}: {e}")
                finally:
                    q.task_done()
        _workers[name] = threading.Thread(target=loop, daemon=True, name=f"jobs-{name}")
        _workers[name].start()


def drain(timeout=30.0):
    """Attend que les deux voies soient vides (tests, arrêt propre)."""
    import time
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if all(q.unfinished_tasks == 0 for q in _LANES.values()):
            return True
        time.sleep(0.02)
    return False


_LONG_POLL = 50.0             # durée du blocage demandé à golem.fm (< son timeout serveur)


def start_poller():
    """Boucle LONG-POLL (démon) : demande à golem.fm de bloquer jusqu'à un job -> prise en charge
    quasi-instantanée. S'AUTO-ADAPTE : si le serveur ne supporte pas `?wait` (réponse immédiate +
    file vide), on back-off jusqu'à _POLL_EVERY (comportement filet d'avant). Non appairé = pause."""
    global _poller
    if _poller is not None:
        return

    def loop():
        import time
        from .golemfm import _cfg as m_cfg
        backoff = 3.0
        while True:
            try:
                base, token = m_cfg()
                if not base or not token:
                    time.sleep(30); continue                 # pas appairé : rien à tirer
                t0 = time.monotonic()
                r = process(wait=_LONG_POLL)                 # bloque côté serveur jusqu'à un job
                elapsed = time.monotonic() - t0
                # serveur qui a VRAIMENT bloqué (~_LONG_POLL) OU a traité un job -> reboucle direct.
                if (r.get("processed") or 0) > 0 or elapsed >= _LONG_POLL * 0.6:
                    backoff = 3.0
                else:                                        # réponse instantanée + rien : pas de long-poll côté serveur
                    time.sleep(backoff); backoff = min(backoff * 1.6, _POLL_EVERY)
            except Exception as e:
                log.warning(f"poller: {e}")
                time.sleep(30)

    _poller = threading.Thread(target=loop, daemon=True)
    _poller.start()
