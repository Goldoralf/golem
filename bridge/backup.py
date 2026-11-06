# SPDX-License-Identifier: GPL-3.0-or-later
"""Sauvegardes .zip du contenu GoleM (onglet Système ▸ Content).

Chaque catégorie produit un .zip AUTONOME (rangé dans backups/, gitignoré) :
  - presets : presets/*.json
  - banks   : setlists/fcb-banks.json (layout des banks) + mappings/*.json (config du pédalier FCB)
  - amps    : captures NAM d'amplis (gear amp/amp-cab) — sous-catalogue + fichiers .nam
  - cabs    : impulse responses (gear cab = les « Cabs / IRs ») — sous-catalogue + fichiers .wav
  - pedals  : captures NAM de pédales ET outboard (gear pedal, outboard) — sous-catalogue + fichiers .nam
  - songs   : la bibliothèque de chansons — songs/*.golem + les traces de synchro (.sync.json, .etag.json,
              .cards.json, .mix/) ; pas le cache de travail .work/ (reconstruit), ni .json-migrated/. LOCALE :
              jamais au vault (une reprise ne va pas chez golem.fm, song-sharing.md §2.3)
  - originals : les ORIGINAUX seulement (+ les mêmes traces) — eux PARTENT au vault : un groupe peut les vendre,
              golem.fm en garde forcément une copie (2026-10-08)
  - all     : tout (presets + banks + templates + catalogue complet + tous les assets) + les ORIGINAUX —
              jamais les reprises : « all » peut partir au vault de golem.fm

Les fichiers d'assets sont rangés à leur chemin RELATIF au repo (assets/…) : un zip est un
drop-in restaurable. Un manifeste catalog-<kind>.json accompagne les catégories de gear.
"""
import os, json, glob, time, zipfile, hashlib

from . import config as C

BACKUP_DIR = os.path.join(C.ROOT, "backups")
# LES CATÉGORIES (refonte du modal I/O, 2026-10-09 — mockups/io-modal.html, docs/backups.md) : celles qui manquaient
# (patches, settings, synths, grooves, standards) sont ajoutées ; les prises sortent de « kits » (recordings).
KINDS = ("presets", "patches", "banks", "settings", "blockpresets", "amps", "cabs", "pedals", "kits", "synths", "grooves",
         "songs", "originals", "recordings", "standards", "setlist", "all", "custom")
# ce que « all » contient : TOUT sauf les reprises (« songs » — un .golem de reprise ne va pas chez golem.fm, et « all »
# peut y partir) et la grappe (« setlist », un geste à part)
ALL_PARTS = ("presets", "patches", "banks", "settings", "blockpresets", "amps", "cabs", "pedals", "kits", "synths", "grooves",
             "originals", "recordings", "standards")
# ce que le VAULT de golem.fm accepte (routes/golem_vault.py, liste stricte). Jusqu'au 2026-10-09 : presets, banks, amps,
# cabs, pedals, all seulement — `originals` et `kits` y partaient en 400 sans que l'écran le dise. Élargie en prod le
# même jour (golem.fm v0.54.1, accord du mainteneur). `songs` n'y va JAMAIS (vault_refusal) : une reprise reste sur le rack.
VAULT_KINDS = ("presets", "patches", "banks", "settings", "amps", "cabs", "pedals", "kits", "synths", "grooves",
               "originals", "recordings", "standards", "setlist", "custom", "all")
# ce qu'une sauvegarde « all » contenait AVANT la refonte : l'ancienneté d'une catégorie neuve (patches, réglages…) ne
# se lit pas dans une sauvegarde complète qui ne la portait pas (vu au rendu : « 79 days » pour des patches jamais
# sauvegardés). Une sauvegarde complète d'après la refonte porte `kinds` dans son manifeste.
LEGACY_ALL = ("presets", "banks", "amps", "cabs", "pedals", "kits", "originals", "recordings")
REFONTE_T = 1791504000            # 2026-10-09 00:00 UTC
# les RÉGLAGES sauvegardés : une liste d'ACCEPTATION. Jamais un secret (integrations.json : clés et jeton golem.fm ;
# auth-devices.json : appareils appairés ; network.json : mots de passe Wi-Fi) ni l'identité de la machine (serial*.json).
SETTINGS_FILES = ("click.json", "compo.json", "devices.json", "io.json", "mixer.json", "pedals.json", "recorder.json",
                  "recordings.json", "setlist.json", "song-folders.json", "inbox.json", "diag.json", "genres.json",
                  "knobs.json")
# + les CALIBRATIONS de ce rack (audit 2026-10-15) : profils de contrôleurs, banques de potards (knobs.json) et kits de
# batterie MESURÉS (drumkits.local/). Hors dépôt depuis le 2026-10-03, donc sauvegardés nulle part : une réinstallation
# perdait des mesures faites au pied, que rien ne régénère.
SETTINGS_DIRS = ("cards", "inputmaps", "drumkits", "drumkits.local", "controllers", "modes.local")
# LES SAUVEGARDES DE CHANSONS (2026-10-08) : reprises, standards, karaokés → LOCALES seulement ; originaux →
# aussi chez golem.fm. ⚠ « original » est une nature DÉCLARÉE (le `kind` de la fiche) : tant que la signature du
# lot 8 n'existe pas, rien ne prouve qu'un « original » en est un — c'est dit ici plutôt que tu. La garde du vault
# vit dans golemfm.push_backup (une sauvegarde « songs » n'y part jamais).
# les traces de synchro du répertoire, sauvegardées AVEC les .golem (sans elles, une chanson restaurée repartirait
# en « pending » vers golem.fm et retirerait un .golem qu'elle a déjà) — plan-song-sharing lot 8, 2026-10-08
SONG_STATE = (".sync.json", ".etag.json", ".cards.json")
# contenu SON user (drum/pad kits + samples + DI de réf Preview + prises de perf) — pas des captures
# de gear, pas restaurable par git : à sauvegarder comme le reste. sfz (Salamander) exclu = réinstallable.
KITS_DIR = os.path.join(C.ROOT, "library", "kits")
SAMPLES_DIR = os.path.join(C.ROOT, "assets", "samples")
RECORDINGS_DIR = os.path.join(C.ROOT, "recordings")
PATCHES_DIR = os.path.join(C.ROOT, "library", "patches")
BLOCK_PRESETS_DIR = os.path.join(C.ROOT, "library", "block-presets")   # les presets de BLOC (docs/archive/block-sheets.md)
VITAL_DIR = os.path.join(C.ROOT, "library", "synth", "vital")       # « factory » = installé ; tout autre pack = à toi
GROOVES_DIR = os.path.join(C.ROOT, "library", "grooves")            # tes .mid importés + index.json ; packs/ = installés
STANDARDS_DIR = os.path.join(C.ROOT, "library", "standards")
AUDIO_EXTS = (".wav", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".mp3", ".json")
MANIFEST = "golem-backup.json"      # manifeste d'intégrité (magic + hash par fichier) — lu à l'import
FORMAT = 1                          # version du format de backup


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def overall_checksum(entries):
    """Empreinte globale = hash des couples path:sha256 triés -> détecte tout ajout/retrait/altération."""
    body = "\n".join("%s:%s" % (e["path"], e["sha256"]) for e in sorted(entries, key=lambda x: x["path"]))
    return _sha256_bytes(body.encode())


def _tones():
    d = json.load(open(C.CATALOG)) if os.path.exists(C.CATALOG) else {"tones": []}
    return d.get("tones", []) or []


def _gear_tones(gears):
    return [t for t in _tones() if str(t.get("gear")) in gears]


# chaque helper d'ajout enregistre {path, sha256, size} dans `entries` (-> manifeste).
def _record_str(zf, arc, data, entries):
    zf.writestr(arc, data)
    entries.append({"path": arc, "sha256": _sha256_bytes(data), "size": len(data)})


def _add_file(zf, rel, seen, entries):
    """Ajoute ROOT/rel au zip sous `rel` (une seule fois — les packs partagent des fichiers)."""
    if not rel or rel in seen:
        return False
    src = os.path.join(C.ROOT, rel)
    if os.path.isfile(src):
        zf.write(src, rel)
        entries.append({"path": rel, "sha256": _sha256_file(src), "size": os.path.getsize(src)})
        seen.add(rel)
        return True
    return False


def _add_gear(zf, gears, name, seen, entries):
    tones = _gear_tones(gears)
    _record_str(zf, "catalog-%s.json" % name,
                json.dumps({"tones": tones}, ensure_ascii=False, indent=1).encode(), entries)
    n = 0
    for t in tones:
        for m in t.get("models", []):
            if _add_file(zf, m.get("file"), seen, entries):
                n += 1
        # Le modèle conditionné est la SOURCE des futurs réglages, pas un modèle jouable
        # parmi les snapshots. Le perdre à la restauration figerait tous ses potards.
        if (t.get("parametric") or {}).get("file"):
            _add_file(zf, t["parametric"]["file"], seen, entries)
    return len(tones), n


def _add_dir_files(zf, src_dir, arc_prefix, entries, exts=None):
    """Ajoute TOUS les fichiers d'un dossier (récursif), filtrés par extensions si `exts`.
    Pour le contenu son user (kits JSON + samples/DI/recordings .wav) — pas seulement des .json."""
    if not os.path.isdir(src_dir):
        return
    for root, _dirs, files in os.walk(src_dir):
        for b in sorted(files):
            if b.startswith(".") or (exts is not None and not b.lower().endswith(exts)):
                continue
            full = os.path.join(root, b)
            # TOUJOURS « / » dans un zip : sous Windows relpath rend « perf-…\take.wav », que l'import refuse (et que
            # le format zip ne connaît pas) — une prise en sous-dossier rendait la sauvegarde irrestaurable
            arc = arc_prefix + "/" + os.path.relpath(full, src_dir).replace(os.sep, "/")
            zf.write(full, arc)
            entries.append({"path": arc, "sha256": _sha256_file(full), "size": os.path.getsize(full)})


def _add_dir_json(zf, src_dir, arc_prefix, entries, only=None):
    """Ajoute les *.json d'un dossier. `only` = allowlist de basenames (ex. n'exporter que fcb-banks.json,
    pas les vieilles setlists reliques de la feature supprimée)."""
    for p in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
        b = os.path.basename(p)
        if b.startswith(".") or (only is not None and b not in only):
            continue
        arc = arc_prefix + "/" + b
        zf.write(p, arc)
        entries.append({"path": arc, "sha256": _sha256_file(p), "size": os.path.getsize(p)})


def counts():
    """Volumétrie par catégorie (pour l'UI) : nb d'items + taille approximative des fichiers."""
    tones = _tones()
    gsize, gtones = {}, {}
    for t in tones:
        gtones[str(t.get("gear"))] = gtones.get(str(t.get("gear")), 0) + 1
        for m in t.get("models", []):
            src = os.path.join(C.ROOT, m.get("file") or "")
            sz = os.path.getsize(src) if os.path.isfile(src) else 0
            g = str(t.get("gear"))
            gsize.setdefault(g, [0, 0])
            gsize[g][0] += 1
            gsize[g][1] += sz
    amp_c = sum(gsize.get(g, [0, 0])[0] for g in ("amp", "amp-cab"))
    amp_s = sum(gsize.get(g, [0, 0])[1] for g in ("amp", "amp-cab"))
    presets = len([p for p in glob.glob(os.path.join(C.PRESETS_DIR, "*.json")) if not os.path.basename(p).startswith(".")])
    # contenu son user : kits (JSON) + samples/DI/prises (audio)
    kits_n = len(glob.glob(os.path.join(KITS_DIR, "*.json")))
    snd_n, snd_b = 0, 0
    for d in (SAMPLES_DIR, C.DI_REFS_DIR):                 # les prises ont leur catégorie (« recordings »)
        for root, _dirs, files in os.walk(d) if os.path.isdir(d) else []:
            for b in files:
                if b.lower().endswith(AUDIO_EXTS) and not b.startswith(".") and not b.endswith(".json"):
                    snd_n += 1
                    snd_b += os.path.getsize(os.path.join(root, b))
    _origs = [p for p in glob.glob(os.path.join(C.SONGS_DIR, "*.golem")) if _song_kind(p) == "original"]
    return {
        # (2026-10-09) les octets comptent enfin, et les banks comptent les SETLISTS — plus un fcb-banks.json disparu
        "presets": {"n": presets, "bytes": _files_stat(C.PRESETS_DIR, (".json",), recursive=False)["bytes"],
                    "templates": _files_stat(C.TEMPLATES_DIR, (".json",), recursive=False)["n"]},
        "banks": {"n": _files_stat(C.SETLISTS_DIR, (".json",), recursive=False)["n"],
                  "mappings": _files_stat(C.MAPPINGS_DIR, (".json",), recursive=False)["n"],
                  "bytes": _files_stat(C.SETLISTS_DIR, (".json",), recursive=False)["bytes"]
                           + _files_stat(C.MAPPINGS_DIR, (".json",), recursive=False)["bytes"]},
        "amps": {"n": amp_c, "bytes": amp_s, "tones": gtones.get("amp", 0) + gtones.get("amp-cab", 0)},
        "cabs": {"n": gsize.get("cab", [0, 0])[0], "bytes": gsize.get("cab", [0, 0])[1], "tones": gtones.get("cab", 0)},
        "pedals": {"tones": gtones.get("pedal", 0), "outboard": gtones.get("outboard", 0),
                   "n": gsize.get("pedal", [0, 0])[0] + gsize.get("outboard", [0, 0])[0],
                   "bytes": gsize.get("pedal", [0, 0])[1] + gsize.get("outboard", [0, 0])[1]},
        "kits": {"n": kits_n, "sounds": snd_n, "bytes": snd_b},
        "songs": {"n": len(glob.glob(os.path.join(C.SONGS_DIR, "*.golem"))),
                  "bytes": sum(os.path.getsize(p) for p in glob.glob(os.path.join(C.SONGS_DIR, "*.golem")))},
        "originals": {"n": len(_origs), "bytes": sum(os.path.getsize(p) for p in _origs)},
        # ── les catégories NEUVES (2026-10-09) ──
        "patches": _files_stat(PATCHES_DIR, (".json",)),
        "blockpresets": _block_presets_stat(),
        "settings": {"n": len(_settings_rel()), "bytes": sum(_size(os.path.join(C.ROOT, r)) for r in _settings_rel())},
        "synths": _sum_stats([_files_stat(os.path.join(VITAL_DIR, p), (".vital",)) for p in _vital_user_packs()]),
        "grooves": _files_stat(GROOVES_DIR, (".mid",), recursive=False),
        "recordings": {**_files_stat(RECORDINGS_DIR, AUDIO_EXTS),
                       "audio": _files_stat(RECORDINGS_DIR, tuple(e for e in AUDIO_EXTS if e != ".json"))["n"],
                       "sessions": len([d for d in os.listdir(RECORDINGS_DIR) if os.path.isdir(os.path.join(RECORDINGS_DIR, d))])
                       if os.path.isdir(RECORDINGS_DIR) else 0},
        "standards": {"n": len(glob.glob(os.path.join(STANDARDS_DIR, "golem", "*.golem")))
                           + len(glob.glob(os.path.join(STANDARDS_DIR, "synced", "*.json"))),
                      "bytes": _files_stat(STANDARDS_DIR, None)["bytes"] - _size(os.path.join(STANDARDS_DIR, "jazz-standards.json"))},
    }


def _user_block_presets():
    """Les presets de bloc NON d'usine, en chemins relatifs au dépôt (library/block-presets/<type>/<slug>.json)."""
    out = []
    if not os.path.isdir(BLOCK_PRESETS_DIR):
        return out
    for btype in sorted(os.listdir(BLOCK_PRESETS_DIR)):
        d = os.path.join(BLOCK_PRESETS_DIR, btype)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(d, fn), encoding="utf-8") as f:
                    bp = json.load(f)
            except Exception:
                continue
            if isinstance(bp, dict) and not bp.get("factory"):
                out.append("library/block-presets/" + btype + "/" + fn)
    return out


def _block_presets_stat():
    mine = _user_block_presets()
    total = _files_stat(BLOCK_PRESETS_DIR, (".json",))["n"]
    return {"n": len(mine), "factory": max(0, total - len(mine)),
            "bytes": sum(_size(os.path.join(C.ROOT, r)) for r in mine)}


def _size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return 0


def _files_stat(d, exts, recursive=True):
    """{n, bytes} des fichiers d'un dossier (extensions filtrées si `exts`)."""
    n = b = 0
    if not os.path.isdir(d):
        return {"n": 0, "bytes": 0}
    walk = os.walk(d) if recursive else [(d, [], os.listdir(d))]
    for root, _ds, fs in walk:
        for f in fs:
            full = os.path.join(root, f)
            if f.startswith(".") or not os.path.isfile(full) or (exts and not f.lower().endswith(exts)):
                continue
            n += 1
            b += os.path.getsize(full)
    return {"n": n, "bytes": b}


def _sum_stats(xs):
    return {"n": sum(x["n"] for x in xs), "bytes": sum(x["bytes"] for x in xs)}


# ce qui n'est VOLONTAIREMENT pas sauvegardé : réinstallé par l'installateur, ou retiré de golem.fm à la demande
NOT_BACKED = (("DrumGizmo kits", ("library", "drumkits")), ("SFZ pianos", ("library", "sfz")),
              ("golem.fm backing cache", ("assets", "backing")))


def overview(remote=None):
    """L'écran Export : par catégorie, ce qu'elle porte et QUAND elle a été sauvegardée pour la dernière fois — sur ce
    rack ou au vault (`remote` = la liste de golem.fm). + la dernière sauvegarde complète, et ce qui n'est pas sauvegardé."""
    import datetime
    last = {}                                         # catégorie -> {"t": epoch, "where": {"rack", "vault"}}

    def seen(kinds, t, where):
        for k in kinds:
            cur = last.get(k)
            if not cur or t > cur["t"] + 60:
                last[k] = {"t": t, "where": {where}}
            elif abs(t - cur["t"]) <= 60:
                cur["where"].add(where)
    for b in list_backups():
        if b.get("safety"):
            continue
        ks = (ALL_PARTS if b["mtime"] >= REFONTE_T else LEGACY_ALL) if b["kind"] == "all" else (b.get("kinds") or [])
        seen(list(ks) + (["all"] if b["kind"] == "all" else []), b["mtime"], "rack")
    for r in (remote or []):
        try:
            t = int(datetime.datetime.fromisoformat(str(r.get("backup_created_at") or r.get("uploaded_at"))[:19])
                    .replace(tzinfo=datetime.timezone.utc).timestamp())
        except ValueError:
            continue
        name = r.get("filename") or ""
        kind = kind_of_name(name)
        parts = name[:-4].split("-")
        ks = ((ALL_PARTS if t >= REFONTE_T else LEGACY_ALL) if kind == "all"
              else (kinds_of(parts[1]) if len(parts) >= 2 else []))
        seen(list(ks) + (["all"] if kind == "all" else []), t, "vault")
    out = {k: {**v, "where": sorted(v["where"])} for k, v in last.items()}
    nb = []
    for label, parts in NOT_BACKED:
        st = _files_stat(os.path.join(C.ROOT, *parts), None)
        if st["n"]:
            nb.append({"label": label, "bytes": st["bytes"]})
    return {"counts": counts(), "last": out, "last_full": out.get("all"), "not_backed": nb,
            "vault_kinds": list(VAULT_KINDS), "all_parts": list(ALL_PARTS)}


def _song_kind(path):
    """La nature DÉCLARÉE d'un .golem (cover | original | None), lue dans son manifeste."""
    from . import golemfile as G
    try:
        return G.read_manifest(path).get("kind")
    except (G.GolemError, OSError):
        return None


def _add_songs(zf, entries, only_kind=None):
    """La bibliothèque de chansons (lot 8). Les .golem sont rangés SANS recompression : ils contiennent déjà des
    médias compressés, et les redégonfler coûterait du temps pour rien. `only_kind="original"` : les originaux
    seulement (ce qui peut partir au vault)."""
    d = C.SONGS_DIR
    if not os.path.isdir(d):
        return
    for b in sorted(os.listdir(d)):
        full = os.path.join(d, b)
        if b.endswith(".golem") and only_kind and _song_kind(full) != only_kind:
            continue
        if os.path.isfile(full) and (b.endswith(".golem") and not b.startswith(".") or b in SONG_STATE):
            arc = "songs/" + b
            zf.write(full, arc, compress_type=zipfile.ZIP_STORED if b.endswith(".golem") else zipfile.ZIP_DEFLATED)
            entries.append({"path": arc, "sha256": _sha256_file(full), "size": os.path.getsize(full)})
    mixd = os.path.join(d, ".mix")
    if os.path.isdir(mixd):
        for b in sorted(os.listdir(mixd)):
            full = os.path.join(mixd, b)
            if b.endswith(".json") and os.path.isfile(full):
                arc = "songs/.mix/" + b
                zf.write(full, arc)
                entries.append({"path": arc, "sha256": _sha256_file(full), "size": os.path.getsize(full)})


def _add_kits(zf, entries):
    """Contenu son user : drum/pad kits (JSON) + samples (one-shots + samples des kits) + DI de réf
    Preview + prises de perf. Tout .wav/.json — jamais restaurable par git."""
    _add_dir_files(zf, KITS_DIR, "library/kits", entries, exts=(".json",))
    _add_dir_files(zf, SAMPLES_DIR, "assets/samples", entries, exts=AUDIO_EXTS)
    _add_dir_files(zf, C.DI_REFS_DIR, "library/di-refs", entries, exts=AUDIO_EXTS)
    # les PRISES ont leur catégorie (« recordings », 2026-10-09) : elles pesaient des centaines de Mo dans « kits »


_GRAPPE = {}          # paramètres de la grappe en cours (kind "setlist") — cf. build_setlist


def build_setlist(sid, dest_dir=None):
    """Zip d'une GRAPPE : la setlist `sid` + les presets qu'elle référence, rien d'autre.
    Le format et le manifeste sont ceux des sauvegardes — donc l'import existant sait déjà le
    relire, y compris ses règles anti-collision. Renvoie aussi ce qui MANQUAIT : une grappe ne
    doit pas arriver « verte » avec des presets absents."""
    from . import setlists as _sl
    from .store import load_preset
    sl = _sl.load(sid)
    if not sl:
        raise ValueError("setlist inconnue : %s" % sid)
    pids = list(dict.fromkeys(sl.get("presets") or []))          # dédup, ordre conservé
    missing = [p for p in pids if load_preset(p) is None]
    _GRAPPE.clear()
    _GRAPPE.update(sid=_sl._safe_id(sid), presets=[p for p in pids if p not in missing])
    r = build("setlist", dest_dir=dest_dir, prefix="golem")
    _GRAPPE.clear()
    return {**r, "setlist": sid, "presets": len(pids) - len(missing), "missing": missing}


def _settings_rel():
    """Les fichiers de réglages sauvegardés (chemins relatifs au rack), selon la liste d'acceptation."""
    out = []
    for f in SETTINGS_FILES:
        if os.path.isfile(os.path.join(C.CONFIG_DIR, f)):
            out.append("config/" + f)
    for d in SETTINGS_DIRS:
        root = os.path.join(C.CONFIG_DIR, d)
        for r, _ds, fs in os.walk(root) if os.path.isdir(root) else []:
            for f in sorted(fs):
                if not f.startswith("."):
                    out.append("config/" + os.path.relpath(os.path.join(r, f), C.CONFIG_DIR).replace(os.sep, "/"))
    return out


def settings_allowed(rel):
    """Ce chemin `config/…` est-il un réglage qu'une sauvegarde peut porter (et l'import poser) ?"""
    if not rel.startswith("config/"):
        return False
    sub = rel[len("config/"):]
    return sub in SETTINGS_FILES or any(sub.startswith(d + "/") for d in SETTINGS_DIRS)


def _vital_user_packs():
    try:
        return [p for p in sorted(os.listdir(VITAL_DIR)) if p != "factory" and os.path.isdir(os.path.join(VITAL_DIR, p))]
    except OSError:
        return []


def _add_kind(zf, kind, seen, entries):
    """Ajoute au zip les fichiers d'UNE catégorie."""
    if kind == "presets":
        _add_dir_json(zf, C.PRESETS_DIR, "presets", entries)
        _add_dir_json(zf, C.TEMPLATES_DIR, "templates", entries)
    elif kind == "patches":
        _add_dir_files(zf, PATCHES_DIR, "library/patches", entries, exts=(".json",))
    elif kind == "blockpresets":
        # LES TIENS seulement (2026-10-11) : les presets d'usine sont versionnés et reviennent avec le code —
        # un preset de bloc que tu sauves n'existait, lui, nulle part ailleurs que sur ce rack
        for rel in _user_block_presets():
            _add_file(zf, rel, seen, entries)
    elif kind == "banks":
        # TOUTES les setlists (les setlists sont au PLURIEL depuis 2026-07-27) : le filtre
        # only={"fcb-banks.json"} datait de la feature retirée et aurait fait perdre
        # silencieusement toutes les autres à la sauvegarde.
        _add_dir_json(zf, C.SETLISTS_DIR, "banks/setlists", entries)
        _add_dir_json(zf, C.MAPPINGS_DIR, "banks/mappings", entries)
    elif kind == "settings":
        for rel in _settings_rel():
            _add_file(zf, rel, seen, entries)
    elif kind == "amps":
        _add_gear(zf, {"amp", "amp-cab"}, "amps", seen, entries)
    elif kind == "cabs":
        _add_gear(zf, {"cab"}, "cabs", seen, entries)
    elif kind == "pedals":
        # + l'OUTBOARD (préamplis, compresseurs capturés : gear `outboard`) — sauvegardé nulle part jusqu'au 2026-10-09
        _add_gear(zf, {"pedal", "outboard"}, "pedals", seen, entries)
    elif kind == "kits":
        _add_kits(zf, entries)
    elif kind == "synths":
        for pack in _vital_user_packs():
            _add_dir_files(zf, os.path.join(VITAL_DIR, pack), "library/synth/vital/" + pack, entries, exts=(".vital",))
    elif kind == "grooves":
        for f in sorted(os.listdir(GROOVES_DIR)) if os.path.isdir(GROOVES_DIR) else []:
            if f.endswith(".mid") or f == "index.json":
                _add_file(zf, "library/grooves/" + f, seen, entries)
    elif kind == "recordings":
        _add_dir_files(zf, RECORDINGS_DIR, "recordings", entries, exts=AUDIO_EXTS)
    elif kind == "standards":
        for sub in ("golem", "synced", "local"):
            _add_dir_files(zf, os.path.join(STANDARDS_DIR, sub), "library/standards/" + sub, entries)
        _add_file(zf, "library/standards/golem/.etag.json", seen, entries)   # les versions tirées : rien ne se retélécharge
    elif kind == "songs":
        _add_songs(zf, entries)
    elif kind == "originals":
        _add_songs(zf, entries, only_kind="original")
    elif kind == "setlist":
        # GRAPPE : une setlist + EXACTEMENT les presets qu'elle référence (contrat
        # docs/setlists.md §5). `only_setlist` est posé par build_setlist() ci-dessous.
        sid, pids = _GRAPPE.get("sid"), _GRAPPE.get("presets") or []
        _add_dir_json(zf, C.SETLISTS_DIR, "banks/setlists", entries, only={f"{sid}.json"})
        _add_dir_json(zf, C.PRESETS_DIR, "presets", entries, only={f"{pid}.json" for pid in pids})


def kinds_of(kind):
    """Les catégories qu'un type de sauvegarde contient. `all` = ALL_PARTS ; `a_b_c` = une sélection."""
    if kind == "all":
        return list(ALL_PARTS)
    parts = str(kind or "").split("_")
    return parts if parts and all(p in KINDS and p not in ("all", "custom") for p in parts) else []


def build(kind, dest_dir=None, prefix="golem"):
    """Construit le zip d'une catégorie, d'une SÉLECTION (liste de catégories : un seul fichier, type `custom`), ou de
    tout (`all`). Écrit un MANIFESTE d'intégrité (golem-backup.json : magic + hash SHA-256 par fichier + checksum
    global, + `kinds`) lu et vérifié à l'import. Renvoie {ok, file, size, kind, kinds} ou lève ValueError."""
    if isinstance(kind, (list, tuple)):
        kinds = list(dict.fromkeys(kind))
        if not kinds or any(k not in KINDS or k in ("all", "custom", "setlist") for k in kinds):
            raise ValueError("catégories inconnues : %s" % kinds)
        label = kinds[0] if len(kinds) == 1 else "_".join(kinds)     # « _ » : golem.fm refuse « + » dans un nom
        mkind = kinds[0] if len(kinds) == 1 else "custom"
    else:
        if kind not in KINDS or kind == "custom":
            raise ValueError("catégorie inconnue : %s" % kind)
        kinds = list(ALL_PARTS) if kind == "all" else [kind]
        label = mkind = kind
    dest_dir = dest_dir or BACKUP_DIR
    os.makedirs(dest_dir, exist_ok=True)
    fn = "%s-%s-%s.zip" % (prefix, label, time.strftime("%Y%m%d-%H%M%S"))
    path = os.path.join(dest_dir, fn)
    seen, entries = set(), []
    # compresslevel bas : les .nam/.wav se compressent peu, on privilégie la vitesse sur 100s de Mo
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        if kind == "all":
            # catalogue : uniquement ce qui DIVERGE de git au fil de l'usage (téléchargements TONE3000).
            # effects.json / components.json sont statiques et git-trackés -> restaurés par git, pas de la donnée user.
            for rel in ("library/catalog/tones-index.json", "library/catalog/images.json"):
                _add_file(zf, rel, seen, entries)
        for k in kinds:
            _add_kind(zf, k, seen, entries)
        # manifeste EN DERNIER (il décrit tout le reste) — jamais listé dans ses propres entries. `kind` = celui déclaré
        # au vault (golem.fm vérifie l'égalité, 422 sinon) ; `kinds` = ce que le fichier contient.
        manifest = {"golem_backup": FORMAT, "kind": mkind, "kinds": kinds, "created": int(time.time()),
                    "files": entries, "checksum": overall_checksum(entries)}
        zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))
    return {"ok": True, "file": fn, "size": os.path.getsize(path), "kind": mkind, "kinds": kinds}


def kind_of_name(name):
    """Le type DÉCLARÉ d'un fichier de sauvegarde, lu dans son nom : une catégorie, `all`, `custom` (une sélection
    « a_b_c »), ou « ? »."""
    parts = os.path.basename(str(name or ""))[:-4].split("-")
    if len(parts) < 2:
        return "?"
    if parts[1] in KINDS:
        return parts[1]
    return "custom" if len(kinds_of(parts[1])) > 1 else "?"


def vault_refusal(name):
    """Pourquoi ce fichier ne peut PAS partir au vault de golem.fm (anglais : ça s'affiche), ou None."""
    parts = os.path.basename(str(name or ""))[:-4].split("-")
    kinds = kinds_of(parts[1]) if len(parts) >= 2 else []
    if "songs" in kinds:
        return "a songs backup stays on this rack — golem.fm never keeps a cover's audio"
    kind = kind_of_name(name)
    if kind not in VAULT_KINDS:
        return "golem.fm can't keep this kind of backup yet (%s) — it stays on this rack" % kind
    return None


def list_backups():
    """Liste les .zip présents (récents d'abord) : {file, size, kind, mtime}."""
    out = []
    for p in glob.glob(os.path.join(BACKUP_DIR, "*.zip")):
        st = os.stat(p)
        base = os.path.basename(p)
        # nom = "<prefix>-<kind>-<ts>.zip" (prefix = golem | preimport) -> extrait la catégorie ; une SÉLECTION
        # s'écrit « a_b_c » (type custom)
        parts = base[:-4].split("-")
        kind = kind_of_name(base)
        out.append({"file": base, "size": st.st_size, "kind": kind, "kinds": kinds_of(parts[1]) if len(parts) >= 2 else [],
                    "mtime": int(st.st_mtime), "safety": base.startswith("preimport-")})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def backup_path(name):
    """Chemin absolu SÛR d'un backup (empêche le path-traversal). None si invalide/absent."""
    if not name or "/" in name or "\\" in name or ".." in name or not name.endswith(".zip"):
        return None
    p = os.path.join(BACKUP_DIR, name)
    return p if os.path.isfile(p) else None


def delete_backup(name):
    p = backup_path(name)
    if not p:
        return False
    os.remove(p)
    return True
