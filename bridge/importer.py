# SPDX-License-Identifier: GPL-3.0-or-later
"""Import d'un backup .zip GoleM — conçu pour qu'un import FOIREUX soit IMPOSSIBLE.

Garanties :
  1. Le zip doit porter le manifeste golem-backup.json (magic + hash SHA-256 par fichier + checksum
     global). Un zip étranger / tronqué / altéré est REFUSÉ avant toute écriture.
  2. Chaque fichier est vérifié (taille + sha256) contre le manifeste ; aucun membre inattendu toléré.
  3. Chaque chemin est validé (préfixe autorisé, pas de '..', pas d'absolu, pas de backslash) : aucune
     écriture hors des dossiers connus (presets/, banks/, templates/, library/, assets/).
  4. Phase d'ANALYSE (inspect) : renvoie un PLAN (doublons, nouveaux, remplacements) SANS rien écrire.
  5. À l'APPLICATION : re-validation complète, puis SAUVEGARDE PRÉ-IMPORT auto (rollback possible),
     puis écriture ATOMIQUE par fichier (temp+rename). Gestion des doublons : skip | overwrite | rename.

Un backup = une catégorie (presets|banks|amps|cabs|pedals|all). L'import route chaque section.
"""
import os, io, json, time, zipfile, hashlib, shutil

from . import config as C
from . import backup as _backup
from .store import _write_json_atomic, _read_json, _safe_id
from .golog import get as _get_log

log = _get_log("importer")

STAGING = os.path.join(_backup.BACKUP_DIR, ".staging")
MAX_ZIP = 2 * 1024 * 1024 * 1024        # garde-fou : 2 Go
STRATEGIES = ("skip", "overwrite", "rename")

# préfixes de chemin AUTORISÉS dans un backup (tout le reste = refus)
# ⚠ `recordings/` manquait (trouvé le 2026-10-09) : les sauvegardes « kits » et « all » y rangent les prises, et UN
# chemin refusé fait refuser TOUTE la sauvegarde — aucune sauvegarde complète d'un rack qui a enregistré ne se
# restaurait. Une liste d'acceptation se tient À JOUR avec ce que `backup.build` écrit (tests/test_backup_roundtrip.py).
_ALLOWED = ("presets/", "banks/setlists/", "banks/mappings/", "templates/",
            "library/catalog/", "library/", "assets/", "songs/", "recordings/")


class ImportError_(Exception):
    pass


# ── validation bas niveau ────────────────────────────────────────────────────
def _safe_path(p):
    """True si `p` est un chemin relatif SÛR sous un préfixe autorisé (ou un catalog-*.json racine)."""
    if not p or p.startswith("/") or "\\" in p or ".." in p.split("/") or p.endswith("/"):
        return False
    if p == _backup.MANIFEST:
        return True
    if p.startswith("catalog-") and p.endswith(".json") and "/" not in p:
        return True
    if p.startswith("config/"):
        # les RÉGLAGES (2026-10-09) : seulement ceux de la liste d'acceptation — jamais un secret ni l'identité du rack
        return _backup.settings_allowed(p)
    return any(p.startswith(pre) for pre in _ALLOWED)


def _load_manifest(zf):
    try:
        m = json.loads(zf.read(_backup.MANIFEST))
    except KeyError:
        raise ImportError_("not a golem backup (no golem-backup.json manifest)")
    except Exception:
        raise ImportError_("unreadable manifest (damaged zip?)")
    if not isinstance(m, dict) or m.get("golem_backup") != _backup.FORMAT:
        raise ImportError_("unknown backup format (incompatible version?)")
    if m.get("kind") not in _backup.KINDS:
        raise ImportError_("unknown backup category: %s" % m.get("kind"))
    return m


def _verify(zf, m):
    """Vérifie l'intégrité TOTALE : chemins sûrs, aucun membre inattendu, taille + sha256 par fichier,
    checksum global. Lève ImportError_ au moindre écart. Ne renvoie rien (soit ça passe, soit ça casse)."""
    files = m.get("files")
    if not isinstance(files, list):
        raise ImportError_("invalid manifest (no file list)")
    declared = {}
    for e in files:
        p = (e or {}).get("path")
        if not _safe_path(p):
            raise ImportError_("path not allowed in the backup: %s" % p)
        declared[p] = e
    # aucun membre du zip en dehors du manifeste (+ le manifeste lui-même) ; pas de doublon
    members = [n for n in zf.namelist() if not n.endswith("/")]
    for n in members:
        if n == _backup.MANIFEST:
            continue
        if not _safe_path(n):
            raise ImportError_("path not allowed in the zip: %s" % n)
        if n not in declared:
            raise ImportError_("file not in the manifest (tampered backup?): %s" % n)
    if len(members) - 1 != len(declared):        # -1 = le manifeste
        raise ImportError_("the zip does not match its manifest (file count)")
    # hash + taille de chaque fichier
    for p, e in declared.items():
        try:
            data = zf.read(p)
        except KeyError:
            raise ImportError_("file listed but missing: %s" % p)
        if len(data) != e.get("size") or hashlib.sha256(data).hexdigest() != e.get("sha256"):
            raise ImportError_("damaged file (hash/size): %s" % p)
    if _backup.overall_checksum(files) != m.get("checksum"):
        raise ImportError_("invalid overall checksum (altered backup)")


# ── staging (upload) ─────────────────────────────────────────────────────────
def stage(data: bytes):
    """Écrit le zip uploadé dans un slot de staging, renvoie (token, path). Nettoie les vieux slots."""
    if not data:
        raise ImportError_("empty body")
    if len(data) > MAX_ZIP:
        raise ImportError_("file too large (> 2 GB)")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise ImportError_("this is not a .zip file")
    os.makedirs(STAGING, exist_ok=True)
    now = time.time()
    for f in os.listdir(STAGING):                # purge des staging > 2 h
        fp = os.path.join(STAGING, f)
        try:
            if now - os.path.getmtime(fp) > 7200:
                os.remove(fp)
        except OSError:
            pass
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + hashlib.sha256(data[:4096]).hexdigest()[:8]
    path = os.path.join(STAGING, token + ".zip")
    with open(path, "wb") as f:
        f.write(data)
    return token, path


def stage_path(src):
    """Stage un zip DÉJÀ SUR LE DISQUE (ex. backup tiré du vault golem.fm) : copie
    disque-à-disque, jamais en RAM (un backup amps/all pèse des centaines de Mo).
    Mêmes garde-fous que stage(). Renvoie (token, path)."""
    if not src or not os.path.isfile(src):
        raise ImportError_("file not found")
    if os.path.getsize(src) > MAX_ZIP:
        raise ImportError_("file too large (> 2 GB)")
    if not zipfile.is_zipfile(src):
        raise ImportError_("this is not a .zip file")
    os.makedirs(STAGING, exist_ok=True)
    with open(src, "rb") as f:
        head = f.read(4096)
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + hashlib.sha256(head).hexdigest()[:8]
    path = os.path.join(STAGING, token + ".zip")
    shutil.copyfile(src, path)
    return token, path


def _staged_path(token):
    if not token or "/" in token or "\\" in token or ".." in token:
        return None
    p = os.path.join(STAGING, token + ".zip")
    return p if os.path.isfile(p) else None


# ── plan (dry-run) ───────────────────────────────────────────────────────────
def _preset_id_of(name, data):
    try:
        d = json.loads(data)
        return _safe_id(d.get("id") or d.get("name") or os.path.basename(name)[:-5]), d
    except Exception:
        return None, None


# ── LE PLAN PAR CATÉGORIE (refonte du modal I/O, 2026-10-09) : pour chaque fichier, NOUVEAU (absent ici), DIFFÉRENT
# (présent, autre contenu : c'est là que « Keep mine · Use the backup · Keep both » tranche) ou IDENTIQUE (rien à faire).
CATS = (("presets/", "presets"), ("templates/", "presets"), ("banks/", "setlists"), ("library/patches/", "patches"),
        ("config/", "settings"), ("assets/models/", "gear"), ("assets/irs/", "gear"), ("library/catalog/", "gear"),
        ("catalog-", "gear"), ("library/kits/", "kits"), ("assets/samples/", "kits"), ("library/di-refs/", "kits"),
        ("library/synth/", "synths"), ("library/grooves/", "grooves"), ("recordings/", "recordings"),
        ("songs/", "songs"), ("library/standards/", "standards"))


def _cat(n):
    return next((c for pre, c in CATS if n.startswith(pre)), "other")


def _target(n, data_for_preset=None):
    """Le fichier LOCAL qu'un membre remplacerait (None : pas un fichier, ex. un catalogue fusionné)."""
    base = os.path.basename(n)
    if n.startswith("presets/") and n.endswith(".json"):
        pid, _d = _preset_id_of(n, data_for_preset) if data_for_preset is not None else (base[:-5], None)
        return os.path.join(C.PRESETS_DIR, (pid or base[:-5]) + ".json")
    if n.startswith("templates/"):
        return os.path.join(C.TEMPLATES_DIR, base)
    if n.startswith("banks/setlists/"):
        return os.path.join(C.SETLISTS_DIR, base)
    if n.startswith("banks/mappings/"):
        return os.path.join(C.MAPPINGS_DIR, base)
    if n.startswith("songs/"):
        rel = n[len("songs/"):]
        return os.path.join(C.SONGS_DIR, ".mix", base) if rel.startswith(".mix/") else os.path.join(C.SONGS_DIR, base)
    if n.startswith("catalog-"):
        return None
    return os.path.join(C.ROOT, n)


def _state(local, entry):
    """new | diff | same, d'après la taille puis l'empreinte du manifeste (aucun fichier n'est relu deux fois)."""
    if not local or not os.path.isfile(local):
        return "new"
    if isinstance(entry.get("size"), int) and os.path.getsize(local) != entry["size"]:
        return "diff"
    return "same" if _backup._sha256_file(local) == entry.get("sha256") else "diff"


def inspect(zip_path):
    """Valide TOUT et renvoie le plan (aucune écriture). Lève ImportError_ si le backup est refusé."""
    with zipfile.ZipFile(zip_path) as zf:
        m = _load_manifest(zf)
        _verify(zf, m)                            # <- refuse tout backup douteux ICI
        kind = m["kind"]
        plan = {"ok": True, "kind": kind, "created": m.get("created"),
                "presets": {"new": 0, "dup": 0, "items": []},
                "banks": {"replace": False, "files": []},
                "templates": {"new": 0, "dup": 0},
                "gear": {"tones_new": 0, "tones_dup": 0, "files_new": 0, "files_present": 0},
                "warnings": []}
        names = [n for n in zf.namelist() if not n.endswith("/") and n != _backup.MANIFEST]
        tone_ids = {str(t.get("id")) for t in _backup._tones()}
        for n in names:
            if n.startswith("presets/") and n.endswith(".json"):
                pid, d = _preset_id_of(n, zf.read(n))
                if not pid:
                    raise ImportError_("unreadable preset: %s" % n)
                exists = os.path.isfile(os.path.join(C.PRESETS_DIR, pid + ".json"))
                plan["presets"]["dup" if exists else "new"] += 1
                plan["presets"]["items"].append({"id": pid, "name": (d or {}).get("name") or pid, "dup": exists})
            elif n.startswith("banks/setlists/"):
                # TOUTES les setlists sont importées : elles sont au PLURIEL depuis 2026-07-27.
                # Le filtre « seul fcb-banks.json » datait de la feature retirée — il aurait rendu
                # impossible le retour d'une grappe poussée sur golem.fm.
                plan["banks"]["files"].append(os.path.basename(n))
                plan["banks"]["replace"] = True
            elif n.startswith("templates/") and n.endswith(".json"):
                exists = os.path.isfile(os.path.join(C.TEMPLATES_DIR, os.path.basename(n)))
                plan["templates"]["dup" if exists else "new"] += 1
            elif n.startswith("assets/"):
                if os.path.isfile(os.path.join(C.ROOT, n)):
                    plan["gear"]["files_present"] += 1
                else:
                    plan["gear"]["files_new"] += 1
            elif n.startswith("recordings/"):
                rc = plan.setdefault("recordings", {"new": 0, "present": 0})
                rc["present" if os.path.isfile(os.path.join(C.ROOT, n)) else "new"] += 1
            elif n.startswith("catalog-") and n.endswith(".json"):
                try:
                    cat = json.loads(zf.read(n))
                except Exception:
                    raise ImportError_("unreadable catalog: %s" % n)
                for t in cat.get("tones", []):
                    plan["gear"]["tones_dup" if str(t.get("id")) in tone_ids else "tones_new"] += 1
        # le plan PAR CATÉGORIE, fichier par fichier (le catalogue de gear compte ses entrées, pas un fichier)
        cats = {}
        entries = {e["path"]: e for e in m.get("files") or [] if isinstance(e, dict) and e.get("path")}
        for n in names:
            c = cats.setdefault(_cat(n), {"new": 0, "diff": 0, "same": 0})
            if n.startswith("catalog-"):
                continue
            data = zf.read(n) if n.startswith("presets/") else None
            c[_state(_target(n, data), entries.get(n) or {})] += 1
        plan["cats"] = cats
        plan["kinds"] = m.get("kinds") or ([kind] if kind not in ("all", "custom") else [])
        plan["files"] = len(names)
        plan["diff_total"] = sum(c["diff"] for c in cats.values())
        return plan


# ── application (écritures) ──────────────────────────────────────────────────
def _uniq_preset_id(base):
    pid, n = base, 2
    while os.path.isfile(os.path.join(C.PRESETS_DIR, pid + ".json")):
        pid = "%s-%d" % (base, n); n += 1
    return pid


def apply(zip_path, strategy="skip"):
    """Applique le backup APRÈS re-validation + sauvegarde pré-import. `strategy` = doublons presets/
    templates (skip|overwrite|rename). Renvoie un récap. Lève ImportError_ si invalide (rien écrit)."""
    if strategy not in STRATEGIES:
        raise ImportError_("unknown strategy: %s" % strategy)
    with zipfile.ZipFile(zip_path) as zf:
        m = _load_manifest(zf)
        _verify(zf, m)                            # re-valide : jamais d'écriture sur un backup douteux
        kind = m["kind"]

        # SAUVEGARDE PRÉ-IMPORT (rollback) — de la MÊME catégorie que ce qu'on va toucher
        pre = None
        try:
            # la MÊME sélection que le fichier importé (une sauvegarde « custom » n'est pas une catégorie)
            pre = _backup.build(m.get("kinds") or kind if kind == "custom" else kind, prefix="preimport")["file"]
        except Exception as e:
            pre = "(échec pré-backup: %s)" % e

        res = {"ok": True, "kind": kind, "preimport": pre, "strategy": strategy,
               "presets": 0, "presets_skipped": 0, "presets_renamed": 0,
               "templates": 0, "banks": 0, "mappings": 0, "tones": 0, "assets": 0, "config": 0,
               "songs": 0, "songs_skipped": 0, "kept": 0, "settings": 0, "recordings": 0}
        names = [n for n in zf.namelist() if not n.endswith("/") and n != _backup.MANIFEST]

        for n in names:
            data = zf.read(n)
            base = os.path.basename(n)
            # ── presets
            if n.startswith("presets/") and n.endswith(".json"):
                pid, d = _preset_id_of(n, data)
                dst = os.path.join(C.PRESETS_DIR, pid + ".json")
                if os.path.isfile(dst):
                    if strategy == "skip":
                        res["presets_skipped"] += 1; continue
                    if strategy == "rename":
                        pid = _uniq_preset_id(pid + "-imported")
                        d["id"] = pid; d["name"] = (d.get("name") or pid) + " (imported)"
                        dst = os.path.join(C.PRESETS_DIR, pid + ".json")
                        _write_json_atomic(dst, d); res["presets_renamed"] += 1; continue
                _write_json_atomic(dst, d if d is not None else json.loads(data)); res["presets"] += 1
            # ── templates
            elif n.startswith("templates/") and n.endswith(".json"):
                dst = os.path.join(C.TEMPLATES_DIR, base)
                if os.path.isfile(dst) and strategy == "skip":
                    continue
                if os.path.isfile(dst) and strategy == "rename":
                    stem = base[:-5]; k = 2; dst = os.path.join(C.TEMPLATES_DIR, "%s-imported.json" % stem)
                    while os.path.isfile(dst):
                        dst = os.path.join(C.TEMPLATES_DIR, "%s-imported-%d.json" % (stem, k)); k += 1
                os.makedirs(C.TEMPLATES_DIR, exist_ok=True)
                _write_atomic_bytes(dst, data); res["templates"] += 1
            # ── banks (config du pédalier — remplace ; couvert par le pré-backup)
            elif n.startswith("banks/setlists/"):
                # toutes les setlists sont acceptées (pluriel depuis 2026-07-27) ; une setlist DIFFÉRENTE de la nôtre suit
                # la stratégie (2026-10-09 : « Keep mine » la garde — elle était remplacée d'office)
                dst = os.path.join(C.SETLISTS_DIR, base)
                why = _keep_ours(dst, data, strategy)
                if why:
                    res["kept"] += why == "keep"; continue
                os.makedirs(C.SETLISTS_DIR, exist_ok=True)
                _write_atomic_bytes(dst, data); res["banks"] += 1
            elif n.startswith("banks/mappings/"):
                dst = os.path.join(C.MAPPINGS_DIR, base)
                why = _keep_ours(dst, data, strategy)
                if why:
                    res["kept"] += why == "keep"; continue
                os.makedirs(C.MAPPINGS_DIR, exist_ok=True)
                _write_atomic_bytes(dst, data); res["mappings"] += 1
            # ── chansons (lot 8) : le .golem est remis TEL QUEL (sa synchro, son rev compris) — ce n'est pas
            # l'installation d'un fichier venu d'ailleurs, qui écarterait sa synchro. Vérifié en entier avant d'être
            # posé. Déjà présente : `skip` garde la nôtre ; `overwrite` (et `rename`, sans objet ici) la remplace —
            # le pré-backup de la même catégorie couvre le retour en arrière.
            elif n.startswith("songs/"):
                res_k = _restore_song(n, data, strategy)
                res["songs" if res_k else "songs_skipped"] += 1
            # ── assets (fichiers NAM/IR) : copie si absent (path = identité ; validé par hash)
            elif n.startswith("assets/"):
                dst = os.path.join(C.ROOT, n)
                if not os.path.isfile(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _write_atomic_bytes(dst, data); res["assets"] += 1
            # ── prises (Rec) : comme les assets, posées si ABSENTES — une prise ne s'écrase jamais
            elif n.startswith("recordings/"):
                dst = os.path.join(C.ROOT, n)
                if not os.path.isfile(dst):
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    _write_atomic_bytes(dst, data); res["recordings"] += 1
            # ── catalogue de gear : fusion par id dans tones-index.json
            elif n.startswith("catalog-") and n.endswith(".json"):
                res["tones"] += _merge_catalog(json.loads(data).get("tones", []), strategy)
            # ── config bibliothèque (all) : effects/images/components -> overwrite
            # ── bibliothèque (kits, patches, synthés, grooves, standards, catalogue) et RÉGLAGES : un fichier absent est
            # posé ; un fichier DIFFÉRENT suit la stratégie (il était écrasé d'office, même avec « skip »)
            elif n.startswith(("library/", "config/")):
                dst = os.path.join(C.ROOT, n)
                why = _keep_ours(dst, data, strategy)
                if why:
                    res["kept"] += why == "keep"; continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                _write_atomic_bytes(dst, data)
                res["settings" if n.startswith("config/") else "config"] += 1

        return res


def _keep_ours(dst, data, strategy):
    """Ne PAS écrire ce membre ? « same » s'il est déjà là à l'identique ; « keep » s'il diffère et que la stratégie
    garde le nôtre (tout sauf « overwrite » = « Use the backup » ; « rename » = « Keep both » ne vaut que pour les presets
    et templates : ailleurs deux fichiers au même nom ne coexistent pas) ; None = écrire."""
    if not os.path.isfile(dst):
        return None
    try:
        with open(dst, "rb") as f:
            if f.read() == data:
                return "same"
    except OSError:
        return None
    return None if strategy == "overwrite" else "keep"


def _restore_song(n, data, strategy):
    """Un membre `songs/…` d'une sauvegarde. Rend True si écrit."""
    from . import golemfile as G
    rel = n[len("songs/"):]
    if rel.startswith(".mix/"):
        dst = os.path.join(C.SONGS_DIR, ".mix", os.path.basename(rel))
    else:
        dst = os.path.join(C.SONGS_DIR, os.path.basename(rel))
    if os.path.isfile(dst) and strategy == "skip":
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if rel.endswith(".golem"):
        tmp = dst + ".restore.tmp"
        _write_atomic_bytes(tmp, data)
        try:
            G.verify(tmp)                            # un .golem abîmé ne remplace jamais une chanson
        except G.GolemError as e:
            os.remove(tmp)
            raise ImportError_("%s : %s" % (n, e))
        os.replace(tmp, dst)
    else:
        _write_atomic_bytes(dst, data)
    return True


def _write_atomic_bytes(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _asset_rel_ok(rel):
    """Un chemin de fichier du catalogue : relatif, sans `..`, sous assets/."""
    if rel in (None, ""):
        return True
    rel = str(rel)
    return (rel.startswith("assets/") and "\\" not in rel and ".." not in rel.split("/")
            and not os.path.isabs(rel) and ":" not in rel)


def _tone_files_ok(t):
    """audit 2026-11-04 (H1) : une entrée importée est écrite TELLE QUELLE dans tones-index.json, et ses chemins sont
    ensuite servis ou déplacés par le bridge — une entrée qui pointe hors d'assets/ est écartée."""
    if not isinstance(t, dict):
        return False
    files = [t.get("file"), (t.get("parametric") or {}).get("file") if isinstance(t.get("parametric"), dict) else None]
    files += [m.get("file") for m in t.get("models") or [] if isinstance(m, dict)]
    ok = all(_asset_rel_ok(f) for f in files)
    if not ok:
        log.warning("import : entrée de catalogue %r écartée (fichier hors assets/)", t.get("id"))
    return ok


def _merge_catalog(tones, strategy):
    """Fusionne des tones dans library/catalog/tones-index.json (dédup par id). skip = garde l'existant,
    overwrite = remplace l'entrée. Renvoie le nb d'entrées ajoutées/mises à jour."""
    tones = [t for t in (tones or []) if _tone_files_ok(t)]
    if not tones:
        return 0
    cat = _read_json(C.CATALOG, {"tones": []}) or {"tones": []}
    cat.setdefault("tones", [])
    by_id = {str(t.get("id")): i for i, t in enumerate(cat["tones"])}
    n = 0
    for t in tones:
        tid = str(t.get("id"))
        if tid in by_id:
            if strategy == "overwrite":
                cat["tones"][by_id[tid]] = t; n += 1
        else:
            cat["tones"].append(t); by_id[tid] = len(cat["tones"]) - 1; n += 1
    _write_json_atomic(C.CATALOG, cat)
    return n


def discard(token):
    p = _staged_path(token)
    if p:
        try:
            os.remove(p)
        except OSError:
            pass
