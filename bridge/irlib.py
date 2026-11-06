# SPDX-License-Identifier: GPL-3.0-or-later
"""Import d'IR (impulse responses de baffle) déposés depuis l'UI (onglet Library ▸ IR).

Un .wav d'IR est un petit fichier (quelques centaines de Ko). On l'écrit sous assets/irs/user/ et
on l'inscrit au catalogue (tones-index.json) comme un tone gear='cab' / format='ir' — exactement la
forme des cabs téléchargés depuis TONE3000 (cf. routes_t3k._install_worker) — pour qu'il apparaisse
dans le picker de blocs Cab du Designer et se résolve à la compilation (resolver._resolve : lookup
par str(id), fichier = models[0].file). La suppression réutilise le flux amp (/api/amp/{id})."""
import os, re, struct, wave

from . import config as C
from .store import _read_json, _write_json_atomic

IR_DIR = os.path.join(C.ROOT, "assets", "irs", "user")     # dépôt des IR importés à la main
_REL_ROOT = C.ROOT
MAX_BYTES = 25 * 1024 * 1024                                # garde-fou (un IR reste petit)


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "ir"


def _safe_stem(filename):
    stem = os.path.basename(filename or "").strip()
    if stem.lower().endswith(".wav"):
        stem = stem[:-4]
    stem = re.sub(r"[^A-Za-z0-9._ -]", "_", stem).strip()
    return stem or "ir"


def _is_wav(data: bytes):
    """RIFF/WAVE minimal + lisible par le module wave (rejette un fichier corrompu/mal nommé)."""
    if len(data) < 44 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        return False
    try:
        import io
        with wave.open(io.BytesIO(data), "rb") as w:
            return w.getnframes() >= 0
    except Exception:
        return False


def _human_size(n):
    return f"{n // 1024} kB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def _unique_id(cat, base):
    """Id de tone unique (string, préfixé pour ne jamais heurter les ids numériques TONE3000)."""
    have = {str(t.get("id")) for t in cat.get("tones", [])}
    tid = f"ir-user-{base}"
    n = 2
    while tid in have:
        tid = f"ir-user-{base}-{n}"; n += 1
    return tid


def save_upload(filename: str, data: bytes):
    """Écrit un IR .wav et l'inscrit au catalogue. Renvoie {ok, id, name} ou {ok:False, error}."""
    if not data:
        return {"ok": False, "error": "empty body"}
    if len(data) > MAX_BYTES:
        return {"ok": False, "error": "file too large (>25 MB)"}
    if not _is_wav(data):
        return {"ok": False, "error": "not a valid WAV (IR expected as .wav)"}

    stem = _safe_stem(filename)
    os.makedirs(IR_DIR, exist_ok=True)
    dst = os.path.join(IR_DIR, stem + ".wav")
    n = 2
    while os.path.exists(dst):                             # ne jamais écraser un IR existant
        dst = os.path.join(IR_DIR, f"{stem}-{n}.wav"); n += 1
    with open(dst, "wb") as f:
        f.write(data)
    rel = os.path.relpath(dst, _REL_ROOT).replace(os.sep, "/")
    name = os.path.basename(dst)[:-4]

    cat = _read_json(C.CATALOG, {"tones": [], "stats": {}}) or {"tones": [], "stats": {}}
    cat.setdefault("tones", [])
    tid = _unique_id(cat, _slug(name))
    entry = {
        "id": tid, "title": name, "amp": name, "brand": "Cabs / IR", "creator": "user",
        "slug": _slug(name), "url": "", "gear": "cab", "format": "ir", "style": "",
        "tags": ["ir", "user"], "makes": [], "pack": False, "downloads": 0, "favorites": 0,
        "models": [{"id": tid + "-0", "name": name, "file": rel, "arch": None, "size": _human_size(len(data))}],
    }
    cat["tones"].append(entry)
    _write_json_atomic(C.CATALOG, cat)
    return {"ok": True, "id": tid, "name": name}
