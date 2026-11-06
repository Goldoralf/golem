# Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors
# SPDX-License-Identifier: MIT
"""Le fichier `.golem` — lire, écrire, vérifier (docs/golem-format.md, FIGÉ le 2026-10-08).

Une chanson (ou un album) dans un zip : `golem.json` (le manifeste, seul membre obligatoire), puis
`audio/`, `stems/`, `scores/`, `chart/`, `lyrics/`, `sync/`, `art/`, `booklet/`, `video/`, `tones/`,
`versions/`, `sheet.json`, `mine/`, `signatures/` (§2). Les médias sont rangés SANS recompression
(`ZIP_STORED`) : on les lit sans tout extraire, et réécrire le manifeste est une copie, pas un réencodage.

⚠ MODULE AUTONOME : bibliothèque standard seulement, aucun import du bridge. golem.fm le copie tel quel
(plan-song-sharing.md, lot 1 : « une bibliothèque partagée, Python des deux côtés »). Les messages
d'erreur sont en ANGLAIS : ils remontent jusqu'à l'écran.

Ce que la vérification garantit (et ce qu'elle ne garantit PAS) :
  - chemins sûrs (ni absolu, ni `..`, ni `\\`), aucune entrée qui sortirait du dossier à l'extraction ;
  - garde-fous contre le zip piégé : nombre de membres, taille décompressée totale, taux de compression ;
  - `format` = `golem/<majeure>` ; une majeure supérieure à la nôtre est REFUSÉE en le disant (§13) ;
  - `type` déclaré ET vérifié par la structure : un `song` ne contient pas de `songs/`, un `album`
    contient des `songs/*.golem` et pas d'`audio/` (§3) ;
  - audio : WAV, MP3, FLAC seulement — pour l'original comme pour les stems (§4, §5) ;
  - chaque fichier PRÉSENT et déclaré dans `files` a le bon sha256 (et la bonne taille si `bytes` est
    donné). Un fichier déclaré mais ABSENT n'est pas une erreur : `files` liste tout fichier attendu,
    présent ou non (§3) — `report["missing"]` le dit ;
  - ce qu'on ne connaît pas (dossier, fichier, champ) est IGNORÉ, jamais une erreur (§13) — il est
    rapporté dans `report["unknown"]` et n'est jamais extrait.
  Elle ne dit RIEN de la signature (lot 8) ni de la VÉRITÉ de `kind`/`rights`, qui sont déclarés (§3).
"""
import hashlib
import io
import json
import os
import re
import tempfile
import zipfile

FORMAT_MAJOR = 1
FORMAT = "golem/%d" % FORMAT_MAJOR
MANIFEST = "golem.json"
TYPES = ("song", "album")

# §2 : ce que le format connaît. Un dossier absent de cette liste est ignoré (§13), pas refusé.
KNOWN_DIRS = ("audio/", "stems/", "scores/", "chart/", "lyrics/", "sync/", "art/", "booklet/", "video/",
              "tones/", "versions/", "mine/", "signatures/", "songs/", "sheets/")
KNOWN_FILES = (MANIFEST, "sheet.json")
# HORS MANIFESTE (lot 8, golem.fm 2026-10-08) : écrits dans l'archive, JAMAIS inscrits dans `files`. `signatures/`
# parce que la signature couvre les octets de `golem.json` — inscrite dedans, elle changerait ce qu'elle signe
# (circulaire) ; `mine/` parce que c'est la couche du propriétaire, hors signature (§9 sexies) : y ajouter une prise
# ne doit pas toucher au manifeste signé. `verify` les range en `undeclared`.
UNLISTED_DIRS = ("signatures/", "mine/")


def listed(arc):
    """Ce membre est-il inscrit dans `files` ?"""
    return not arc.startswith(UNLISTED_DIRS)
AUDIO_EXT = (".wav", ".mp3", ".flac")          # §4 : trois formats, pas un de plus (2026-10-08)
AUDIO_DIRS = ("audio/", "stems/")
# rangés sans recompression : déjà compressés, et lus sans extraction (§2)
STORED_EXT = AUDIO_EXT + (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".mov", ".golem", ".gp", ".gpx")

# garde-fous (zip piégé) — larges : un album avec vidéo pèse lourd, mais pas 20 Go
MAX_MEMBERS = 5000
MAX_TOTAL = 20 * 1024 ** 3
MAX_RATIO = 200                                 # décompressé / compressé, au-delà de MIN_RATIO_SIZE
MIN_RATIO_SIZE = 16 * 1024 ** 2


class GolemError(Exception):
    """Un `.golem` refusé. Le message est montré à l'utilisateur (anglais)."""


# ── chemins ─────────────────────────────────────────────────────────────────────
def safe_path(p):
    """Chemin relatif sûr : ni absolu, ni `..`, ni antislash, ni lecteur Windows, ni vide."""
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or "\x00" in p:
        return False
    if re.match(r"^[A-Za-z]:", p):
        return False
    return all(x not in ("", ".", "..") for x in p.split("/"))       # ni segment vide, ni « . », ni « .. »


def is_known(p):
    return p in KNOWN_FILES or any(p.startswith(d) for d in KNOWN_DIRS)


def _ext(p):
    return os.path.splitext(p)[1].lower()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def _sha256_member(zf, name, chunk=1024 * 1024):
    h, n = hashlib.sha256(), 0
    with zf.open(name) as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
            n += len(blk)
    return h.hexdigest(), n


# ── le manifeste ─────────────────────────────────────────────────────────────────
def parse_format(fmt):
    """`golem/1` -> 1 ; None si illisible."""
    m = re.fullmatch(r"golem/(\d+)", str(fmt or ""))
    return int(m.group(1)) if m else None


def check_manifest(m):
    """Les champs que le lecteur exige. Lève GolemError ; rend le manifeste."""
    if not isinstance(m, dict):
        raise GolemError("golem.json is not an object")
    major = parse_format(m.get("format"))
    if major is None:
        raise GolemError("not a .golem file (unknown format %r)" % (m.get("format"),))
    if major > FORMAT_MAJOR:
        raise GolemError("this file is %s — this golem reads up to %s; update the golem" % (m.get("format"), FORMAT))
    if m.get("type") not in TYPES:
        raise GolemError("unknown type %r (song or album)" % (m.get("type"),))
    if not isinstance(m.get("id"), str) or not m["id"].strip():
        raise GolemError("the manifest has no id")
    files = m.get("files", {})
    if not isinstance(files, dict):
        raise GolemError("`files` must be an object (path → entry)")
    for p, e in files.items():
        if not safe_path(p):
            raise GolemError("unsafe path in the manifest: %s" % p)
        if not isinstance(e, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(e.get("sha256") or "")):
            raise GolemError("manifest entry without a valid sha256: %s" % p)
        if any(p.startswith(d) for d in AUDIO_DIRS) and _ext(p) not in AUDIO_EXT:
            raise GolemError("%s: audio must be WAV, MP3 or FLAC — convert it first" % p)
    g = m.get("genres")
    if g is not None and (not isinstance(g, list) or len(g) > 2
                          or not all(isinstance(x, dict) and isinstance(x.get("family"), str) for x in g)):
        raise GolemError("`genres`: one or two {family, subgenre} pairs")
    return m


# ── lire / vérifier ──────────────────────────────────────────────────────────────
def _guard_zip(zf):
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_MEMBERS:
        raise GolemError("too many files in the archive (%d)" % len(infos))
    total = 0
    for i in infos:
        if not safe_path(i.filename):
            raise GolemError("unsafe path in the archive: %s" % i.filename)
        if i.flag_bits & 0x1:
            raise GolemError("encrypted archive member: %s" % i.filename)
        total += i.file_size
        if i.file_size > MIN_RATIO_SIZE and i.compress_size and i.file_size / i.compress_size > MAX_RATIO:
            raise GolemError("suspicious compression ratio: %s" % i.filename)
    if total > MAX_TOTAL:
        raise GolemError("the archive would unpack to more than %d GB" % (MAX_TOTAL // 1024 ** 3))
    names = [i.filename for i in infos]
    if len(set(names)) != len(names):
        raise GolemError("duplicate file names in the archive")
    return names


def read_manifest(path_or_zf):
    """Le manifeste seul (vérifié dans sa forme), sans lire les médias."""
    zf = path_or_zf if isinstance(path_or_zf, zipfile.ZipFile) else None
    try:
        if zf is None:
            with zipfile.ZipFile(path_or_zf) as z:
                return read_manifest(z)
        try:
            raw = zf.read(MANIFEST)
        except KeyError:
            raise GolemError("not a .golem file (golem.json missing)")
        try:
            m = json.loads(raw.decode("utf-8"))
        except Exception:
            raise GolemError("golem.json is not valid JSON")
        return check_manifest(m)
    except zipfile.BadZipFile:
        raise GolemError("not a zip archive (corrupted .golem?)")


def verify(path, hashes=True):
    """Vérification COMPLÈTE d'un `.golem`. Lève GolemError au premier défaut bloquant ; sinon rend
    `{manifest, present, missing, undeclared, unknown}` :
      present    — fichiers déclarés ET présents (sha256 vérifié si `hashes`)
      missing    — déclarés, absents (normal : `files` liste ce qui est attendu, §3)
      undeclared — présents dans un dossier connu sans entrée dans `files` (ex. `mine/`, hors signature)
      unknown    — membres que ce lecteur ne connaît pas : ignorés, jamais extraits (§13)"""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise GolemError("not a zip archive (corrupted .golem?)") from e
    with zf:
        names = _guard_zip(zf)
        m = read_manifest(zf)
        files = m.get("files") or {}
        rep = {"manifest": m, "present": [], "missing": [], "undeclared": [], "unknown": []}
        for n in names:
            if n == MANIFEST:
                continue
            if not is_known(n):
                rep["unknown"].append(n)
                continue
            if any(n.startswith(d) for d in AUDIO_DIRS) and _ext(n) not in AUDIO_EXT:
                raise GolemError("%s: audio must be WAV, MP3 or FLAC — convert it first" % n)
            if n not in files:
                rep["undeclared"].append(n)
        for p, e in files.items():
            if not is_known(p):
                continue                  # §13 : un dossier inconnu reste ignoré, même déclaré au manifeste
            if p not in names:
                rep["missing"].append(p)
                continue
            if hashes:
                h, size = _sha256_member(zf, p)
                if h != e["sha256"]:
                    raise GolemError("%s does not match its fingerprint (sha256) — the file was altered" % p)
                if isinstance(e.get("bytes"), int) and e["bytes"] != size:
                    raise GolemError("%s does not have the declared size" % p)
            rep["present"].append(p)
        # §3 : le type est déclaré ET vérifié par la structure
        if m["type"] == "song" and any(n.startswith("songs/") for n in names):
            raise GolemError("a song cannot contain songs/ — is it an album?")
        if m["type"] == "album":
            if any(n.startswith("audio/") for n in names):
                raise GolemError("an album has no audio/ of its own — its songs carry it")
            if not any(n.startswith("songs/") and n.endswith(".golem") for n in names):
                raise GolemError("an album must contain songs/*.golem")
        return rep


def open_member(path, name):
    """Un flux de lecture sur UN membre, sans rien extraire (un stem STORED se lit directement).
    À utiliser en `with`. Le membre doit être un chemin connu et sûr."""
    if not safe_path(name) or not is_known(name):
        raise GolemError("not a readable member: %s" % name)
    zf = zipfile.ZipFile(path)
    try:
        raw = zf.open(name)
    except KeyError:
        zf.close()
        raise GolemError("%s is not in this file" % name)

    class _Stream(io.RawIOBase):          # ferme le zip avec le flux
        def readable(self): return True
        def readinto(self, b):
            d = raw.read(len(b)); b[:len(d)] = d; return len(d)
        def close(self):
            try: raw.close(); zf.close()
            finally: super().close()
    return io.BufferedReader(_Stream())


def read_member(path, name):
    with open_member(path, name) as f:
        return f.read()


def extract(path, dest, hashes=True):
    """Le CACHE DE TRAVAIL (§2) : vérifie, puis décompresse les membres CONNUS dans `dest` (les inconnus
    ne sortent jamais). Écrit dans un dossier voisin puis le met en place d'un coup : un cache est
    complet ou absent. Rend le rapport de `verify`."""
    rep = verify(path, hashes=hashes)
    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".golem-x-", dir=parent)
    try:
        with zipfile.ZipFile(path) as zf:
            for n in [MANIFEST] + rep["present"] + rep["undeclared"]:
                out = os.path.abspath(os.path.join(tmp, n))
                if not out.startswith(tmp + os.sep):
                    raise GolemError("unsafe path in the archive: %s" % n)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with zf.open(n) as src, open(out, "wb") as dst:
                    for blk in iter(lambda: src.read(1024 * 1024), b""):
                        dst.write(blk)
        if os.path.isdir(dest):
            old = dest + ".old"
            if os.path.isdir(old):
                _rmtree(old)
            try:
                os.replace(dest, old)
            except PermissionError:
                # Windows : un fichier du cache est tenu ouvert (REAPER joue les stems) et le dossier ne se
                # renomme pas. Le cache se met à jour fichier par fichier, sans toucher à ce qui n'a pas changé.
                _merge_into(tmp, dest)
                _rmtree(tmp)
                return rep
            os.replace(tmp, dest)
            _rmtree(old)
        else:
            os.replace(tmp, dest)
    except BaseException:
        _rmtree(tmp)
        raise
    return rep


def _merge_into(src, dest):
    """Met `dest` à l'image de `src` membre par membre. Un fichier identique n'est pas réécrit : le stem que
    REAPER tient ouvert reste en place si la chanson n'a changé que de fiche. Un fichier ouvert ET changé
    lève PermissionError : `dest` reste jouable, à moitié à jour (`.from` n'est pas réécrit : on retentera)."""
    keep = {os.path.relpath(os.path.join(r, n), src) for r, _d, ns in os.walk(src) for n in ns}
    for rel in sorted(keep):
        s, d = os.path.join(src, rel), os.path.join(dest, rel)
        if os.path.isfile(d) and os.path.getsize(d) == os.path.getsize(s) and sha256_file(d) == sha256_file(s):
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        os.replace(s, d)
    for root, _dirs, names in os.walk(dest):                 # un membre retiré de la chanson quitte le cache
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), dest)
            if rel != ".from" and rel not in keep:
                try: os.remove(os.path.join(root, n))
                except OSError: pass


def _rmtree(p):
    import shutil
    shutil.rmtree(p, ignore_errors=True)


# ── écrire ───────────────────────────────────────────────────────────────────────
# UN .golem NE MÈNE À PERSONNE (song-sharing.md §2.8, FIGÉ le 2026-10-11) : aucune date de fabrication dans
# l'archive — la date d'un membre, croisée avec un journal, suffit à désigner quelqu'un. Tous les membres portent
# la même date (le minimum du zip), le même système, les mêmes droits ; le manifeste d'abord, le reste TRIÉ. Effet
# voulu : la même chanson donne le même fichier, octet pour octet. ⚠ `zf.write(chemin)` recopie la date du
# fichier disque : jamais ici, tout passe par `_info`.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _ct(arc):
    """La compression d'un membre : les médias rangés tels quels (STORED), le texte compressé."""
    return zipfile.ZIP_STORED if _ext(arc) in STORED_EXT else zipfile.ZIP_DEFLATED


def _info(arc, compress_type):
    zi = zipfile.ZipInfo(arc, date_time=ZIP_DATE)
    zi.compress_type = compress_type
    zi.create_system = 3                                 # le même octet sous Windows (0 par défaut) et ailleurs
    zi.external_attr = 0o644 << 16
    return zi


def _put(zf, arc, src, compress_type=None, size=None):
    """Écrit un membre (bytes, chemin disque, ou flux ouvert de `size` octets) avec une ZipInfo fixe."""
    zi = _info(arc, _ct(arc) if compress_type is None else compress_type)
    if isinstance(src, (bytes, bytearray)):
        zf.writestr(zi, bytes(src))
        return
    if isinstance(src, str):
        zi.file_size = os.path.getsize(src)
        with open(src, "rb") as f, zf.open(zi, "w", force_zip64=zi.file_size > 0x7FFFFFFF) as d:
            for blk in iter(lambda: f.read(1024 * 1024), b""):
                d.write(blk)
        return
    zi.file_size = size or 0
    with zf.open(zi, "w", force_zip64=(size or 0) > 0x7FFFFFFF) as d:   # un membre d'une autre archive
        for blk in iter(lambda: src.read(1024 * 1024), b""):
            d.write(blk)


def manifest_bytes(m):
    """Les octets de `golem.json` tels qu'ils sont ÉCRITS — `files` trié (l'ordre d'arrivée des membres ne se lit
    pas), JSON indenté. PUBLIQUE : ce sont ces octets qu'une signature couvre ; golem.fm les signe par CETTE
    fonction, jamais par un json.dumps à part (une règle copiée finit par diverger — vécu le 2026-10-11)."""
    if isinstance(m.get("files"), dict):
        m = {**m, "files": dict(sorted(m["files"].items()))}
    return json.dumps(m, ensure_ascii=False, indent=1).encode("utf-8")


def _put_manifest(zf, m):
    _put(zf, MANIFEST, manifest_bytes(m), zipfile.ZIP_DEFLATED)


def write(path, manifest, members):
    """Écrit un `.golem` d'un coup (fichier temporaire puis remplacement : un `.golem` est entier ou
    absent). `members` = {chemin dans l'archive: chemin disque | bytes}. Le sha256 et la taille de chaque
    membre sont CALCULÉS ici et rangés dans `manifest["files"]` (les autres clés d'une entrée existante —
    `part`, `origin`, `codec`… — sont gardées). Rend le manifeste écrit."""
    m = dict(manifest or {})
    m.setdefault("format", FORMAT)
    files = {k: dict(v) for k, v in (m.get("files") or {}).items()}
    for arc, src in members.items():
        if arc == MANIFEST or not safe_path(arc):
            raise GolemError("not a writable member: %s" % arc)
        if not listed(arc):
            continue                                    # écrit, jamais inscrit (UNLISTED_DIRS)
        if isinstance(src, (bytes, bytearray)):
            h, size = sha256_bytes(src), len(src)
        else:
            h, size = sha256_file(src), os.path.getsize(src)
        e = files.get(arc, {})
        e.update({"sha256": h, "bytes": size})
        files[arc] = e
    m["files"] = files
    check_manifest(m)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".golem-w-", suffix=".golem", dir=d)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            # le manifeste EN PREMIER : un lecteur qui ne veut que lui s'arrête là
            _put_manifest(zf, m)
            for arc, src in sorted(members.items()):
                _put(zf, arc, src)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return m


def write_raw(path, mbytes, members):
    """Écrit un `.golem` dont le manifeste arrive en OCTETS EXACTS (un plan de golem.fm, R6 — song-sharing §2.8) :
    posés tels quels, jamais recalculés, pour qu'une signature (`signatures/`) reste valide sans reposer sur « les
    octets devraient être identiques ». Mais ils ne sont pas CRUS : chaque membre inscrit doit avoir le sha256 et la
    taille que `files` déclare, sinon rien n'est écrit. Un membre hors `files` (signatures/, mine/) passe tel quel —
    l'appelant l'a vérifié contre le plan. `members` = {chemin: chemin disque | bytes}. Rend le manifeste."""
    try:
        m = json.loads(bytes(mbytes).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise GolemError("the manifest is not valid JSON") from e
    check_manifest(m)
    files = m.get("files") or {}
    for arc, src in members.items():
        if arc == MANIFEST or not safe_path(arc):
            raise GolemError("not a writable member: %s" % arc)
        if not listed(arc):
            continue
        e = files.get(arc)
        if not isinstance(e, dict):
            raise GolemError("member %s is not declared in the manifest" % arc)
        if isinstance(src, (bytes, bytearray)):
            h, size = sha256_bytes(src), len(src)
        else:
            h, size = sha256_file(src), os.path.getsize(src)
        if e.get("sha256") != h or ("bytes" in e and e["bytes"] != size):
            raise GolemError("member %s does not match the manifest" % arc)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".golem-w-", suffix=".golem", dir=d)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            _put(zf, MANIFEST, bytes(mbytes), zipfile.ZIP_DEFLATED)
            for arc, src in sorted(members.items()):
                _put(zf, arc, src)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return m


def write_stream(fileobj, manifest, members):
    """Écrit un `.golem` dans un flux NON POSITIONNABLE (une réponse HTTP, lot 2 de golem.fm : le fichier est
    assemblé à la demande et jamais stocké). Mêmes règles que `write` : sha256 et tailles calculés AVANT
    (une passe de hachage sur les fichiers disque), manifeste en premier, médias en STORED. zipfile écrit
    alors des « data descriptors » (bit 3) : aucun retour en arrière dans le flux. Rend le manifeste écrit."""
    m = dict(manifest or {})
    m.setdefault("format", FORMAT)
    files = {k: dict(v) for k, v in (m.get("files") or {}).items()}
    for arc, src in members.items():
        if arc == MANIFEST or not safe_path(arc):
            raise GolemError("not a writable member: %s" % arc)
        if not listed(arc):
            continue                                    # écrit, jamais inscrit (UNLISTED_DIRS)
        if isinstance(src, (bytes, bytearray)):
            h, size = sha256_bytes(src), len(src)
        else:
            h, size = sha256_file(src), os.path.getsize(src)
        e = files.get(arc, {})
        e.update({"sha256": h, "bytes": size})
        files[arc] = e
    m["files"] = files
    check_manifest(m)
    with zipfile.ZipFile(fileobj, "w") as zf:
        _put_manifest(zf, m)
        for arc, src in sorted(members.items()):
            zi = _info(arc, _ct(arc))
            if isinstance(src, (bytes, bytearray)):
                zi.file_size = len(src)
                with zf.open(zi, "w") as dst:
                    dst.write(bytes(src))
            else:
                zi.file_size = os.path.getsize(src)
                with open(src, "rb") as fsrc, zf.open(zi, "w", force_zip64=zi.file_size > 0x7FFFFFFF) as dst:
                    for blk in iter(lambda: fsrc.read(1024 * 1024), b""):
                        dst.write(blk)
    return m


def replace(path, mutate=None, members=None):
    """Réécrit un `.golem` EXISTANT : `mutate(manifest)` le modifie sur place, `members` = {chemin: bytes |
    chemin disque | None} remplace, ajoute ou (None) retire des membres ; leurs entrées de `files` suivent
    (sha256 et taille recalculés, autres clés gardées ; un membre retiré quitte `files`). Tout le reste est
    RECOPIÉ octet pour octet, avec sa méthode de compression (§2 : « une copie de fichier, pas un
    réencodage »). Écrit d'un coup. Rend le manifeste écrit."""
    members = dict(members or {})
    verify(path, hashes=False)
    with zipfile.ZipFile(path) as zf:
        m = json.loads(zf.read(MANIFEST).decode("utf-8"))
        if mutate:
            mutate(m)
        files = {k: dict(v) for k, v in (m.get("files") or {}).items()}
        for arc, src in members.items():
            if arc == MANIFEST or not safe_path(arc):
                raise GolemError("not a writable member: %s" % arc)
            if not listed(arc):
                continue                                # ni ajouté ni retiré de `files` : le manifeste signé ne bouge pas
            if src is None:
                files.pop(arc, None)
                continue
            if isinstance(src, (bytes, bytearray)):
                h, size = sha256_bytes(src), len(src)
            else:
                h, size = sha256_file(src), os.path.getsize(src)
            e = files.get(arc, {})
            e.update({"sha256": h, "bytes": size})
            files[arc] = e
        m["files"] = files
        check_manifest(m)
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(prefix=".golem-w-", suffix=".golem", dir=d)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as out:
                _put_manifest(out, m)
                kept = {i.filename: i for i in zf.infolist()
                        if not i.is_dir() and i.filename != MANIFEST and i.filename not in members}
                for arc in sorted(set(kept) | {a for a, v in members.items() if v is not None}):
                    if arc in kept:                     # recopié tel quel (STORED reste STORED), mais re-daté (§2.8)
                        with zf.open(kept[arc]) as src:
                            _put(out, arc, src, kept[arc].compress_type, kept[arc].file_size)
                    else:
                        _put(out, arc, members[arc])
        except BaseException:
            try: os.unlink(tmp)
            except OSError: pass
            raise
    try:
        os.replace(tmp, path)                           # HORS du `with` : Windows refuse de remplacer un fichier encore ouvert
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return m


def rewrite_manifest(path, mutate):
    """Change le manifeste seul (un offset, un titre) : les médias sont recopiés octet pour octet."""
    return replace(path, mutate)


# ── ce qu'un .golem EST : chanson, standard ou ligne Vocals (song-sharing.md §2.7, point 4) ──────
# UNE règle, LUE dans le contenu et appelée des deux côtés (le rack et golem.fm, qui recopie ce fichier) : une
# catégorie déclarée d'un côté et lue de l'autre finirait par diverger (CLAUDE.md, « bonne forme, mauvaise nature »).
SCORE = "scores/song.gp"
# LES INSTRUMENTS d'une chanson (golem.fm, 2026-10-16) : ceux que sa TABLATURE joue — `files["scores/song.gp"].tracks[].part`,
# ramenés à leur porte par le préfixe, dans cet ordre, sans doublon. Pas les stems : une séparation en sort toujours six.
# Pas de tab (ou pas de `tracks`) = aucun instrument. Les ids sont ceux de golem.fm (KEYS = "piano").
TAB_PARTS = (("guitar", "guitar"), ("bass", "bass"), ("keys", "piano"), ("drums", "drums"), ("voice", "voice"))


def tab_parts(manifest):
    """["guitar" | "bass" | "piano" | "drums" | "voice"] que joue la tablature du manifeste — [] sans tab."""
    files = (manifest or {}).get("files") or {}
    tracks = (files.get(SCORE) or {}).get("tracks") if isinstance(files, dict) and isinstance(files.get(SCORE), dict) else None
    have = set()
    for t in tracks if isinstance(tracks, list) else ():
        part = str((t or {}).get("part") or "") if isinstance(t, dict) else ""
        for prefix, gate in TAB_PARTS:
            if part == prefix or part.startswith(prefix + "-"):
                have.add(gate)
    return [gate for _, gate in TAB_PARTS if gate in have]
CHART = "chart/song.gsx"
LYRICS = "lyrics/song.lrc"
LIGHT_DIRS = ("audio/", "stems/", "video/")    # ce qu'une copie LÉGÈRE ne porte pas (§2.7, point 3)


def category(present, declared=()):
    """`"song"` | `"standard"` | `"vocals"` | `"track"` | None. `present` = les chemins de membres PRÉSENTS ; `declared` = ceux
    que `files` déclare (présents ou non).

    L'audio compte s'il est présent OU déclaré : une copie légère (texte seul) déclare son `audio/original` sans le
    porter, et une ligne Vocals légère doit rester une ligne Vocals. Le texte (tab, grille, paroles), lui, doit être
    PRÉSENT — c'est lui qui fait la chanson, le standard ou la ligne :
      - `song`     : `scores/song.gp` présent ;
      - `standard` : `chart/song.gsx` présent, et aucun audio (ni présent ni déclaré) ;
      - `vocals`   : de l'audio (présent ou déclaré) et `lyrics/song.lrc` présent ;
      - `track`    : de l'audio (présent ou déclaré), sans tab, ni grille, ni paroles — une chanson EN ATTENTE de sa tab
                     ou de ses paroles (separation-batch.md §7, 2026-10-21 : un dossier séparé sur le golem) ;
      - None       : rien de cela."""
    present = set(present or ())
    every = present | set(declared or ())
    audio = any(p.startswith(AUDIO_DIRS) and _ext(p) in AUDIO_EXT for p in every)
    if SCORE in present:
        return "song"
    if CHART in present and not audio:
        return "standard"
    if audio and LYRICS in present:
        return "vocals"
    if audio and CHART not in present:
        return "track"
    return None


def category_of(path):
    """La catégorie d'un `.golem` sur disque (sans vérifier les empreintes). Lève GolemError."""
    rep = verify(path, hashes=False)
    files = rep["manifest"].get("files") or {}
    return category(rep["present"] + rep["undeclared"], files.keys())


def light_copy(src, dst):
    """Écrit dans `dst` la copie LÉGÈRE de `src` : tout sauf `audio/`, `stems/` et `video/` — avec le MÊME manifeste
    (leurs entrées restent dans `files`, et `verify` les range en `missing`). La copie légère reste la même chanson.
    Rend la taille écrite."""
    verify(src, hashes=False)
    with zipfile.ZipFile(src) as zf, zipfile.ZipFile(dst, "w") as out:
        infos = [i for i in zf.infolist() if not i.is_dir() and not i.filename.startswith(LIGHT_DIRS)]
        infos.sort(key=lambda i: (i.filename != MANIFEST, i.filename))      # le manifeste d'abord, le reste trié
        for i in infos:
            with zf.open(i) as s:
                _put(out, i.filename, s, i.compress_type, i.file_size)
    return os.path.getsize(dst)


# ── LE FILTRE DE SORTIE (song-sharing.md §2.8 et §4.5 de la règle, FIGÉ le 2026-10-11) ──────────────────────
# « Un .golem dit ce qu'est la chanson et qui la joue. Il ne dit jamais qui l'a fabriqué, ni pour qui. » UNE
# fonction, appelée des deux côtés sur tout fichier qui quitte une machine : le rack (dépôt chez golem.fm, export),
# golem.fm (tout ce qu'il sert à une personne). La copie INTERNE du rack n'y passe pas : `repertoire` est sa synchro.
SIG_MEMBER = "signatures/manifest.json"
SIGNED_MANIFEST = "signatures/golem.json"
BARS = "sync/bars.json"
# les clés qui désignent un compte, une personne, un golem ou un patch local — dans la couche du propriétaire
# (`sheet.json`, `mine/`) : retirées où qu'elles soient
OWNER_KEYS = frozenset(("person", "persons", "foot_person", "patch_from", "band", "user", "user_id", "account",
                        "owner", "rack", "rack_id", "serial", "device", "editor", "editor_name", "by_user"))
PRIVATE_REF = "local:"                                # une capture faite sur un golem (plugin-capture.md §12)


def _strip_serials(x):
    """`production.*.serial`, à toute profondeur (le manifeste, `versions[].production`) : le numéro à vie d'un golem
    est attaché à un compte."""
    if isinstance(x, dict):
        for k, v in list(x.items()):
            if k == "production" and isinstance(v, dict):
                _drop_keys(v, ("serial",))
            else:
                _strip_serials(v)
    elif isinstance(x, list):
        for v in x:
            _strip_serials(v)


def _drop_keys(x, keys):
    if isinstance(x, dict):
        for k in [k for k in x if k in keys]:
            del x[k]
        for v in x.values():
            _drop_keys(v, keys)
    elif isinstance(x, list):
        for v in x:
            _drop_keys(v, keys)


def _private(v):
    return isinstance(v, str) and v.startswith(PRIVATE_REF)


_SONG_ID = re.compile(r"^(?:bs|rs|us|ct):[A-Za-z0-9_-]{1,96}$")


def _strip_owner(x, rep, sid=None, in_backing=False):
    """La couche du propriétaire : sans personne, sans patch local, sans capture privée, sans slug. Une capture privée
    ne part pas — ni sa référence (`local:cap-…` mène à un compte), ni son empreinte dans `deps` (le sha256 d'un .nam
    unique désigne qui l'a capturé) : le bloc reste, sans référence, et le receveur le voit `unresolved`.
    Le slug golem.fm mène à la ligne de la chanson, donc à son compte : la backing d'une chanson qui sort est
    la chanson ELLE-MÊME — son slug devient l'id du fichier (`sid`), que le rack joue par ses stems ; tout autre
    `slug` est retiré."""
    if isinstance(x, dict):
        for k in [k for k in x if k in OWNER_KEYS]:
            del x[k]
            rep["owner_keys"] += 1
        if isinstance(x.get("backing"), str) and x["backing"] and not _SONG_ID.match(x["backing"]):
            x["backing"] = sid
            rep["owner_keys"] += 1
        if isinstance(x.get("slug"), str):
            if in_backing and sid:
                x["slug"] = sid
            else:
                del x["slug"]
            rep["owner_keys"] += 1
        if any(_private(x.get(k)) for k in ("ref", "uid")):
            for k in ("ref", "uid", "model", "sha256", "file"):
                x.pop(k, None)
            rep["private_refs"] += 1
        for k, v in list(x.items()):
            if k == "deps" and isinstance(v, list):
                keep = [d for d in v if not (isinstance(d, dict) and (_private(d.get("uid")) or _private(d.get("ref"))
                                                                      or d.get("private") is True))]
                rep["private_refs"] += len(v) - len(keep)
                x[k] = keep
                v = keep
            _strip_owner(v, rep, sid, in_backing or k == "backing")
    elif isinstance(x, list):
        for v in x:
            _strip_owner(v, rep, sid, in_backing)


def outbound_manifest(m, signed, id=None):
    """La part MANIFESTE du filtre de sortie, sur place : retire `golemfm`, `repertoire`, tout `production.*.serial`
    et, hors original signé, `credits.recording.performers[].person` ; pose `id` (un signé garde le sien : en demander
    un autre lève GolemError). PUBLIQUE : golem.fm, qui sert en flux depuis un plan (`write_stream`), l'appelle avant
    d'écrire — la même règle que `outbound`, pas une copie. Rend `m`."""
    if id is not None and id != m.get("id"):
        if signed:
            raise GolemError("a signed original keeps its artist's id — not %s" % id)
        m["id"] = id
    m.pop("golemfm", None)
    m.pop("repertoire", None)
    _strip_serials(m)
    if not signed:
        credits = m.get("credits") if isinstance(m.get("credits"), dict) else {}
        rec = credits.get("recording") if isinstance(credits.get("recording"), dict) else {}
        for p in rec.get("performers") or []:
            if isinstance(p, dict):
                p.pop("person", None)
    return m


def outbound(src, dst, id=None):
    """Écrit dans `dst` la copie de `src` qui peut QUITTER la machine. Rend {id, signed, owner_keys, private_refs}.

    Retire du manifeste `golemfm` et `repertoire` (le slug et la synchro mènent à un compte, un groupe, un rack) et
    tout `production.*.serial`. Hors original signé, retire aussi `credits.recording.performers[].person`. Retire de
    `sheet.json` et de `mine/*.json` les personnes, les patchs locaux et les captures privées (`OWNER_KEYS`,
    `_strip_owner`). Les dates et l'ordre sont figés (`ZIP_DATE`, membres triés) : pas de tatouage, la même chanson
    donne le même fichier.

    `id` : l'id que le fichier SORTANT doit porter (`ct:…`, §4.2) — DÉRIVÉ ailleurs, jamais ici (golem.fm connaît
    l'ISRC et l'id MusicBrainz). None = l'id ne change pas (un dépôt chez son propre compte : golem.fm le relie).
    Un original SIGNÉ garde son id (celui de l'artiste) : en demander un autre lève GolemError. Sa signature
    reste vérifiable : les octets signés de `golem.json` sont gardés sous `signatures/golem.json`."""
    verify(src, hashes=False)
    rep = {"owner_keys": 0, "private_refs": 0}
    with zipfile.ZipFile(src) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        raw = zf.read(MANIFEST)
        m = json.loads(raw.decode("utf-8"))
        signed = SIG_MEMBER in names
        outbound_manifest(m, signed, id)
        out_members = {}
        if signed and SIGNED_MANIFEST not in names:
            out_members[SIGNED_MANIFEST] = raw            # la signature porte sur CES octets (signatures.check)
        for n in names:
            if n == MANIFEST:
                continue
            bars = n == BARS and not signed               # signé : la carte est couverte par la signature
            if n == "sheet.json" or (n.startswith("mine/") and n.endswith(".json")) or bars:
                try:
                    doc = json.loads(zf.read(n).decode("utf-8"))
                except ValueError:
                    raise GolemError("%s is not readable JSON — not sent" % n)
                if bars:                                    # golem.fm y écrit le slug de la chanson (bars-format.md)
                    if not (isinstance(doc, dict) and "slug" in doc):
                        continue
                    del doc["slug"]
                    rep["owner_keys"] += 1
                else:
                    _strip_owner(doc, rep, m["id"])
                out_members[n] = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
                if listed(n) and n in (m.get("files") or {}):     # `sheet.json` est déclaré : son entrée suit
                    m["files"][n].update(sha256=sha256_bytes(out_members[n]), bytes=len(out_members[n]))
        check_manifest(m)
        d = os.path.dirname(os.path.abspath(dst))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".golem-o-", suffix=".golem", dir=d)
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as out:
                _put_manifest(out, m)
                infos = {i.filename: i for i in zf.infolist() if not i.is_dir()}
                for n in sorted(set(names) | set(out_members)):
                    if n == MANIFEST:
                        continue
                    if n in out_members:
                        _put(out, n, out_members[n])
                    else:                                 # même compression partout : la règle de `_ct`, pas celle d'origine
                        with zf.open(infos[n]) as s:
                            _put(out, n, s, _ct(n), infos[n].file_size)
        except BaseException:
            try: os.unlink(tmp)
            except OSError: pass
            raise
    try:
        os.replace(tmp, dst)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise
    return {"id": m["id"], "signed": signed, **rep}


# ── L'ID D'UN FICHIER QUI CIRCULE : `ct:` (song-sharing.md §2.8, validé le 2026-10-11) ────────────────────
# Dérivé de ce qu'EST la chanson, jamais du compte : deux personnes qui ont la même chanson ont le même id. golem.fm
# le calcule (il connaît l'ISRC et l'id MusicBrainz), le pose dans ce qu'il sert à une personne et l'annonce sur la
# carte (`ct_id`) ; le rack le passe à `outbound(id=…)`. Spécification de golem.fm (2026-10-11), suivie à la lettre :
# cette fonction est LA règle, appelée des deux côtés — jamais recopiée. Toujours un hash, même pour l'ISRC : l'id a
# la même forme quelle que soit la source. Changer la règle = changer CONTENT_ID_VERSION.
CONTENT_ID_VERSION = "golem-ct/1"
_ISRC = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$")


def _norm_tag(s):
    """NFKD, sans combinants (accents), casefold, chaque suite de caractères hors [a-z0-9] → un espace, strip.
    « Beyoncé — Halo! » → « beyonce halo »."""
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", str(s or "")) if not unicodedata.combining(c)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def content_id(artist, title, kind, isrc=None, mbid=None):
    """L'id `ct:<32 hex>` d'une chanson. La clé, dans l'ordre : l'ISRC valide (tirets et espaces retirés, majuscules),
    sinon l'id MusicBrainz de l'enregistrement, sinon artiste + titre normalisés + kind (`original` ou `cover`, tout
    autre → `cover`). id = "ct:" + sha256("golem-ct/1|" + clé)[:32]."""
    i = re.sub(r"[-\s]", "", str(isrc or "")).upper()
    m = str(mbid or "").strip().lower()
    if _ISRC.match(i):
        key = "isrc:" + i
    elif m:
        key = "mbid:" + m
    else:
        key = "tk:%s|%s|%s" % (_norm_tag(artist), _norm_tag(title), kind if kind in ("original", "cover") else "cover")
    return "ct:" + hashlib.sha256((CONTENT_ID_VERSION + "|" + key).encode("utf-8")).hexdigest()[:32]
