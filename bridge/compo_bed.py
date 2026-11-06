# SPDX-License-Identifier: GPL-3.0-or-later
"""LE BED D'UNE PRISE ARMÉE (docs/compo.md §12 ter, P6 de golem.fm) — les autres instruments de la chanson (les riffs
choisis dans le panneau Backing de golem.fm), prémixés par golem.fm en UN fichier FLAC adressé par son sha256, joué dans
la Backing à côté du click, à 0 de la timeline comme lui : le « 1 » reste à `downbeat_s` par construction. Le rack ne
mixe rien et ne sait pas ce qu'il contient : il joue un fichier.

Ici : la validation de `target.bed`, le téléchargement (jeton d'appareil, scope files:read), la vérification (octets,
sha256, en-tête STREAMINFO du FLAC : durée ± 20 ms) et le cache par sha (presets/.cache/beds, ~200 Mo, le plus ancien
servi part d'abord). Stdlib seule : le bridge n'a pas de décodeur, STREAMINFO dit le nombre exact d'échantillons."""
import hashlib
import os
import re
import threading
import time
import urllib.error
import urllib.request

from . import config as C
from .golog import get

log = get("compo")

CACHE_DIR = os.path.join(C.PRESETS_DIR, ".cache", "beds")
CACHE_MAX = 200 * 1024 * 1024
BYTES_MAX = 64 * 1024 * 1024             # un bed = la section et son décompte, 1 à 3 Mo : au-delà, ce n'en est pas un
LENGTH_TOL_S = 0.020
GAIN_MIN, GAIN_MAX = -60.0, 0.0          # convenu le 2026-10-27 : 0 dB au plus (un bed à −1 dBFS ne pousse pas la Backing)
WAIT_S = 8.0                             # le tap attend le bed pendant `loading`, comme le click
URL_PREFIX = "/api/ext/compo/beds/"
_SHA = re.compile(r"^[0-9a-f]{64}$")

_lock = threading.Lock()
_fetching = {}                           # sha -> threading.Event (un seul téléchargement par fichier)
_failed = {}                             # sha -> raison du dernier échec
_verified = set()                        # (chemin, taille, inode) des fichiers du cache déjà revérifiés


def clean(bed):
    """`target.bed` validé : (bed|None, raison|None). La raison est celle que dira le refus (« bed not available: … »).
    `offset_s` ≠ 0 est refusé, pas ignoré : la Backing pose ses fichiers à 0."""
    if not isinstance(bed, dict):
        return None, "bad bed"
    sha = str(bed.get("sha256") or "").strip().lower()
    if not _SHA.match(sha):
        return None, "bad sha256"
    try:
        size = int(bed.get("bytes"))
        length = float(bed.get("length_s"))
        gain = float(-6.0 if bed.get("gain_db") is None else bed["gain_db"])
        offset = float(bed.get("offset_s") or 0.0)
    except (TypeError, ValueError):
        return None, "bytes, length_s, gain_db and offset_s are numbers"
    if not 0 < size <= BYTES_MAX:
        return None, "bad size"
    if not 0 < length <= 3600:
        return None, "bad length"
    if (bed.get("format") or "flac") != "flac":
        return None, f"format {bed.get('format')} not supported"
    if abs(offset) > 1e-9:
        return None, "offset not supported"
    url = str(bed.get("url") or "")
    if not url.startswith(URL_PREFIX) or ".." in url:
        return None, "bad url"
    if gain > GAIN_MAX:
        log.info(f"bed {sha[:8]} : gain {gain:+.1f} dB ramené à {GAIN_MAX:+.0f} dB")
    return {"sha256": sha, "bytes": size, "length_s": length, "gain_db": max(GAIN_MIN, min(GAIN_MAX, gain)),
            "format": "flac", "offset_s": 0.0, "url": url[:512]}, None


def path_of(sha):
    return os.path.join(CACHE_DIR, f"{sha}.flac")


def _sha_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached(bed):
    """Le fichier du cache s'il est là et qu'il VAUT son sha — revérifié une fois par fichier et par démarrage (un
    fichier abîmé ou posé à la main n'est jamais joué : il part, et sera retéléchargé)."""
    p = path_of(bed["sha256"])
    try:
        st = os.stat(p)
    except OSError:
        return None
    key = (p, st.st_size, st.st_ino)       # pas le mtime : servir un fichier le rajeunit (os.utime, le cache)
    if key in _verified:
        return p
    if st.st_size == bed["bytes"] and _sha_of(p) == bed["sha256"]:
        _verified.add(key)
        return p
    log.warning(f"bed {bed['sha256'][:8]} du cache abîmé — retiré")
    try:
        os.remove(p)
    except OSError:
        pass
    return None


def streaminfo(path):
    """(sample_rate, channels, bits, total_samples) lus dans le bloc STREAMINFO d'un FLAC, ou None s'il n'est pas lisible."""
    try:
        with open(path, "rb") as f:
            head = f.read(42)
    except OSError:
        return None
    # « fLaC », puis l'en-tête du premier bloc (type 0 = STREAMINFO, 34 octets), toujours le premier
    if len(head) < 42 or head[:4] != b"fLaC" or head[4] & 0x7F != 0 or int.from_bytes(head[5:8], "big") != 34:
        return None
    x = int.from_bytes(head[18:26], "big")           # 20 bits taux · 3 canaux-1 · 5 bits-1 · 36 échantillons
    rate, ch, bits, total = x >> 44, ((x >> 41) & 0x7) + 1, ((x >> 36) & 0x1F) + 1, x & 0xFFFFFFFFF
    return (rate, ch, bits, total) if rate else None


def check_file(path, bed):
    """Ce qui ne va pas dans le fichier `path` pour `bed`, ou None."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "file missing"
    if size != bed["bytes"]:
        return f"size {size} instead of {bed['bytes']}"
    if _sha_of(path) != bed["sha256"]:
        return "sha256 mismatch"
    si = streaminfo(path)
    if not si or not si[3]:
        return "unreadable flac"
    length = si[3] / si[0]
    if abs(length - bed["length_s"]) > LENGTH_TOL_S:
        return f"length {length:.3f} s instead of {bed['length_s']:.3f} s"
    return None


def _prune(keep):
    """Le cache sous CACHE_MAX : le moins récemment servi part d'abord, jamais `keep`."""
    try:
        files = [(os.path.getmtime(p), os.path.getsize(p), p) for p in
                 (os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR) if n.endswith(".flac"))]
    except OSError:
        return
    total = sum(s for _, s, _ in files)
    for _, s, p in sorted(files):
        if total <= CACHE_MAX:
            break
        if p != keep:
            try:
                os.remove(p)
                total -= s
            except OSError:
                pass


def _download(bed):
    """Le fichier, vérifié puis rangé dans le cache : (chemin|None, raison|None). Ne lève jamais."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not base or not token:
        return None, "golem.fm not paired"
    os.makedirs(CACHE_DIR, exist_ok=True)
    dst = path_of(bed["sha256"])
    tmp = f"{dst}.{os.getpid()}.part"
    req = urllib.request.Request(base + bed["url"])
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=20) as r, open(tmp, "wb") as f:
            n = 0
            for chunk in iter(lambda: r.read(1 << 16), b""):
                n += len(chunk)
                if n > bed["bytes"]:
                    raise ValueError(f"more than {bed['bytes']} bytes")
                f.write(chunk)
        why = check_file(tmp, bed)
        if why:
            return None, why
        os.replace(tmp, dst)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None, "golem.fm refused the token: pair again"
        return None, "not found on golem.fm" if e.code == 404 else f"golem.fm answered {e.code}"
    except ValueError as e:
        return None, str(e)
    except Exception as e:
        return None, f"download failed ({str(e)[:60]})"
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    _prune(dst)
    log.info(f"bed {bed['sha256'][:8]} reçu ({bed['bytes']} octets)")
    return dst, None


def fetch(bed):
    """Le bed en cache, téléchargé s'il le faut — un seul téléchargement par sha, les autres l'attendent.
    (chemin|None, raison|None). Un fichier en cache sert sans réseau (renvoi de l'armement, second tour)."""
    sha = bed["sha256"]
    while True:
        p = cached(bed)
        if p:
            try:
                os.utime(p)                        # servi : il est récent pour le cache
            except OSError:
                pass
            return p, None
        with _lock:
            ev = _fetching.get(sha)
            mine = ev is None
            if mine:
                ev = _fetching[sha] = threading.Event()
        if not mine:
            ev.wait(30)
            with _lock:
                why = _failed.get(sha)
            if why and not cached(bed):
                return None, why
            continue
        try:
            p, why = _download(bed)
        finally:
            with _lock:
                if why:
                    _failed[sha] = why
                else:
                    _failed.pop(sha, None)
                _fetching.pop(sha, None)
            ev.set()
        return p, why


def wait(bed, alive, timeout=WAIT_S):
    """Au tap (`loading`) : le bed, en attendant au plus `timeout` s un téléchargement en cours. (chemin|None, raison|None)."""
    out = {}
    th = threading.Thread(target=lambda: out.update(zip(("p", "why"), fetch(bed))), daemon=True, name="bed-wait")
    th.start()
    t_end = time.time() + timeout
    while th.is_alive() and time.time() < t_end:
        if not alive():
            return None, "cancelled"
        th.join(0.05)
    if th.is_alive():
        return None, "still downloading"
    return out.get("p"), out.get("why")


def state_of(why=None, path=None):
    """La forme publiée (≤ 120 car.) : `ready` | `fetching` | `failed: <raison>`."""
    if path:
        return "ready"
    return f"failed: {why}"[:120] if why else "fetching"
