# SPDX-License-Identifier: GPL-3.0-or-later
"""La SIGNATURE DES ORIGINAUX, vérifiée HORS LIGNE (golem-format.md §10, plan-song-sharing.md lot 8, golem.fm v0.53.0).

Ce que golem.fm signe : les octets EXACTS du membre `golem.json` tel qu'écrit dans l'archive, sans canonicalisation,
par la clé Ed25519 du compte (personne ou groupe). `signatures/manifest.json` = `{v:1, alg:"ed25519",
key_id:"k:<16 hex>", signer:{type, id, name}, signed_at, sig:<base64>}`. Les clés publiques : `GET /api/ext/keys` →
`{version, keys:[{key_id, alg, owner:{type, id}, public_key:<base64 32 octets>, created_at, revoked_at}]}`.

Une signature est VALIDE si : la clé est connue, non révoquée, son `owner` est le `signer` déclaré, Ed25519 vérifie
`sig` sur les octets signés — ET chaque fichier de la couche du groupe correspond encore à l'empreinte que le manifeste
signé lui donne (la signature couvre le manifeste, le manifeste couvre les fichiers).

⚠ LE PIÈGE DU RACK : il RÉÉCRIT le `golem.json` de ses chansons (`repertoire` à l'installation, la fiche ensuite).
Vérifier le `golem.json` courant invaliderait tout original dès son installation. D'où : `songs.install_golem` garde
les octets SIGNÉS dans `signatures/golem.json` (hors manifeste, `golemfile.UNLISTED_DIRS`), et c'est sur eux qu'on
vérifie. La couche du PROPRIÉTAIRE n'est pas contrôlée : `sheet.json` (la fiche, que le rack réécrit), `mine/` (ses
prises), `signatures/` — §9 sexies.

La signature ne CONDITIONNE RIEN : le golem ouvre tout `.golem` (song-sharing.md §2.1). Elle se MONTRE — « signed by
<groupe> · verified » — et prouve un original.

Les clés sont gardées dans `songs/.keys.json` : hors ligne, on vérifie avec la dernière liste connue (révocations
comprises) et on le dit. Une clé inconnue déclenche UNE relecture de la liste (une rotation vient d'avoir lieu).
"""
import base64
import hashlib
import json
import os
import threading
import time
import zipfile

from . import config as C
from . import ed25519
from . import golemfile as G
from .golog import get

log = get("signatures")

SIG_MEMBER = "signatures/manifest.json"
SIGNED_MANIFEST = "signatures/golem.json"         # les octets signés, gardés par le rack quand il réécrit golem.json
OWNER_LAYER = ("sheet.json",)                     # + mine/ et signatures/ (G.UNLISTED_DIRS) : la couche du propriétaire
KEYS_MAX_AGE_S = 6 * 3600

_lock = threading.Lock()
_verdicts = {}                                    # (chemin, mtime_ns, taille) -> verdict


# ── les clés publiques ────────────────────────────────────────────────────────────────────────

def _keys_path():
    return os.path.join(C.SONGS_DIR, ".keys.json")


def _keys_cached():
    try:
        with open(_keys_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and isinstance(d.get("keys"), list) else None
    except (OSError, ValueError):
        return None


def refresh_keys():
    """Relit la liste chez golem.fm. Rend la liste gardée (la nouvelle, sinon l'ancienne)."""
    from . import golemfm
    _base, token = golemfm._cfg()
    if not token:
        return _keys_cached()
    st, data = golemfm._req("/api/ext/keys", token=token, timeout=10)
    if st == 200 and isinstance(data, dict) and isinstance(data.get("keys"), list):
        from .store import _write_json_atomic
        d = {"version": data.get("version"), "fetched_at": time.time(), "keys": data["keys"]}
        os.makedirs(C.SONGS_DIR, exist_ok=True)
        _write_json_atomic(_keys_path(), d)
        with _lock:
            _verdicts.clear()                     # une révocation change les verdicts déjà rendus
        return d
    log.info("clés publiques : golem.fm répond %s — dernière liste gardée" % st)
    return _keys_cached()


def _keys(key_id=None):
    """La liste des clés : la gardée si elle est fraîche et connaît `key_id`, sinon relue."""
    d = _keys_cached()
    stale = not d or (time.time() - float(d.get("fetched_at") or 0)) > KEYS_MAX_AGE_S
    unknown = key_id and d and not any(k.get("key_id") == key_id for k in d["keys"])
    if stale or unknown or not d:
        d = refresh_keys() or d
    return d


# ── vérifier ──────────────────────────────────────────────────────────────────────────────────

def _owner_layer(arc):
    return arc in OWNER_LAYER or arc.startswith(G.UNLISTED_DIRS)


def check_bytes(signed, sigdoc, keys):
    """Le verdict sur des octets signés : {valid, reason?, key_id, signer, signed_at, revoked?}. `keys` = la liste."""
    out = {"key_id": sigdoc.get("key_id"), "signer": sigdoc.get("signer"), "signed_at": sigdoc.get("signed_at")}
    if sigdoc.get("v") != 1 or sigdoc.get("alg") != "ed25519":
        return {**out, "valid": False, "reason": "unknown signature format"}
    if keys is None:
        return {**out, "valid": None, "reason": "golem.fm's public keys were never fetched — connect once to check"}
    key = next((k for k in keys.get("keys") or [] if k.get("key_id") == sigdoc.get("key_id")), None)
    if not key:
        return {**out, "valid": False, "reason": "unknown key"}
    if key.get("revoked_at"):
        return {**out, "valid": False, "revoked": True, "reason": "the key was revoked on %s" % str(key["revoked_at"])[:10]}
    sg, ow = sigdoc.get("signer") or {}, key.get("owner") or {}
    if (sg.get("type"), str(sg.get("id"))) != (ow.get("type"), str(ow.get("id"))):
        return {**out, "valid": False, "reason": "the signer is not the owner of the key"}
    try:
        pub = base64.b64decode(key.get("public_key") or "", validate=True)
        sig = base64.b64decode(sigdoc.get("sig") or "", validate=True)
    except (ValueError, TypeError):
        return {**out, "valid": False, "reason": "unreadable key or signature"}
    if not ed25519.verify(pub, signed, sig):
        return {**out, "valid": False, "reason": "the signature does not match the manifest"}
    return {**out, "valid": True}


def check(path):
    """Le verdict d'un `.golem` : None s'il n'est pas signé ; sinon {signed: True, valid: True|False|None, reason?,
    key_id, signer, signed_at, altered?: [membres], offline?}. Mis en cache par (chemin, date, taille)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    sig_key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if sig_key in _verdicts:
            return _verdicts[sig_key]
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if SIG_MEMBER not in names:
                v = None
            else:
                sigdoc = json.loads(zf.read(SIG_MEMBER).decode("utf-8"))
                signed = zf.read(SIGNED_MANIFEST) if SIGNED_MANIFEST in names else zf.read(G.MANIFEST)
                keys = _keys(sigdoc.get("key_id"))
                v = {"signed": True, **check_bytes(signed, sigdoc if isinstance(sigdoc, dict) else {}, keys)}
                if keys and (time.time() - float(keys.get("fetched_at") or 0)) > KEYS_MAX_AGE_S:
                    v["offline"] = True             # vérifié avec une liste de clés ancienne : on le dit
                if v["valid"]:
                    # la signature couvre le MANIFESTE ; le manifeste couvre les fichiers : chacun de la couche du
                    # groupe doit avoir encore l'empreinte signée (un fichier absent — copie légère — n'est pas une faute)
                    m0 = json.loads(signed.decode("utf-8"))
                    files = m0.get("files") or {}
                    altered = []
                    # L'IDENTITÉ montrée est celle du manifeste COURANT : elle doit être celle qui a été signée. Sans
                    # ce contrôle, la signature authentique d'un original, recopiée sous signatures/golem.json, se
                    # prêterait à n'importe quel autre fichier (un autre titre, d'autres médias sous d'autres noms).
                    cur = json.loads(zf.read(G.MANIFEST).decode("utf-8"))
                    for k in ("id", "type", "title", "artist", "kind"):
                        if cur.get(k) != m0.get(k):
                            altered.append("golem.json:" + k)
                    for arc in sorted(names):                # un fichier du groupe que le manifeste signé ignore
                        if arc not in files and arc != G.MANIFEST and not arc.endswith("/") and not _owner_layer(arc):
                            altered.append(arc)
                    for arc, e in sorted(files.items()):
                        if _owner_layer(arc) or arc not in names or not isinstance(e, dict):
                            continue
                        h = hashlib.sha256()
                        with zf.open(arc) as f:
                            for blk in iter(lambda: f.read(1 << 20), b""):
                                h.update(blk)
                        if h.hexdigest() != e.get("sha256"):
                            altered.append(arc)
                    if altered:
                        v.update(valid=False, altered=altered, reason="files changed since it was signed: %s" % ", ".join(altered[:3]))
    except (OSError, zipfile.BadZipFile, ValueError, KeyError) as e:
        v = {"signed": True, "valid": False, "reason": "unreadable signature (%s)" % e}
    with _lock:
        _verdicts[sig_key] = v
    return v


def signed_manifest_member(src):
    """À l'installation : les octets de `golem.json` d'un fichier SIGNÉ, à garder sous `signatures/golem.json` avant que
    le rack ne réécrive le manifeste. None si le fichier n'est pas signé (ou en porte déjà la copie)."""
    try:
        with zipfile.ZipFile(src) as zf:
            names = set(zf.namelist())
            if SIG_MEMBER not in names or SIGNED_MANIFEST in names:
                return None
            return zf.read(G.MANIFEST)
    except (OSError, zipfile.BadZipFile):
        return None
