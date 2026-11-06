# SPDX-License-Identifier: GPL-3.0-or-later
"""Index des prises du rack — ce qui ATTEND de monter vers golem.fm.

Contrat : docs/private/exchanges/message-maestrium-ranger-prises.md (réponse à la demande « Ranger les prises
depuis le web », 2026-09-02). Deux consommateurs :
  - `rigstatus.light()` : le heartbeat PUT /api/ext/rig/status embarque `pending_takes` (les
    LIMIT plus récentes), `pending_total` et `pending_bytes` — l'écran « À ranger » du hub de
    groupe se construit dessus ;
  - le job `take-tag` (tones_jobs) : retag PARTIEL depuis le web, un uid inconnu n'annule pas
    le lot, `band: null` = « Aucun » (la prise reste ici, rien ne monte, rien n'est perdu).

Une prise = un dossier `recordings/perf-<ts>/` (multipiste, `take.json`) OU un `.wav` à plat
(mode mix, sidecar `<fichier>.wav.json`). 77 prises d'avant le 2026-08-02 n'ont AUCUN manifeste
(bug `state.patch`, cf. monitors._take_manifest) : elles sont indexées quand même — uid dérivé
du nom, date lue dans le nom, durée lue dans l'en-tête WAV — et un retag leur CRÉE le sidecar.
Sans ça, l'écran web afficherait 30 prises là où le disque en porte 107.

`uid` : le nom du dossier tel quel (`perf-20260804-192024`, déjà conforme) ; pour un .wav à
plat, le nom Reaper (`02-Sandbox #Input 2-260726_1807.wav`) est ramené à `[a-z0-9._-]` — c'est
la forme que golem.fm exige d'un uid de prise (UID_RE côté serveur), et elle est STABLE (dérivée
du nom de fichier, jamais tirée au sort), donc rejouable d'un heartbeat à l'autre.

`upload` : l'état de montée, tel que le manifeste le porte (`{state, code?, at?, rec_id?}`).
Absent = `pending`. `done` = sortie de l'index (« la liste est ce qui reste »). L'écriture de
cet état appartient au monteur (J2, non codé au 2026-09-02) et au refus lisible du §5 du
message « espaces » — ici on ne fait que le LIRE.
"""
import contextlib
import json
import os
import re
import struct
import time

from . import config as C
from .golog import get
from . import modes as _modes

log = get("takes")

RECORDINGS = os.path.join(C.ROOT, "recordings")
LIMIT = 50                              # les N plus récentes dans le heartbeat (le total est à côté)

_UID_BAD = re.compile(r"[^a-z0-9._-]+")
_PERF_TS = re.compile(r"^perf-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$")
_REAPER_TS = re.compile(r"-(\d{2})(\d{2})(\d{2})_(\d{2})(\d{2})(?:-\d+)?$")   # « -260726_1807[-01] »


# ── identité et dates ──────────────────────────────────────────────────────────────────────
def uid_of(name):
    """Nom de dossier / de fichier -> uid conforme (`^[a-z0-9][a-z0-9._-]{0,63}$`), stable."""
    base = name[:-4] if name.lower().endswith(".wav") else name
    u = _UID_BAD.sub("-", base.lower()).strip("-.")
    return (u or "take")[:64].rstrip("-.")


def started_at_of(name, man=None):
    """Date de départ : le manifeste d'abord, sinon le nom (perf-<ts> ou suffixe Reaper)."""
    s = (man or {}).get("started_at")
    if s:
        return s
    m = _PERF_TS.match(name[:-4] if name.lower().endswith(".wav") else name)
    if m:
        y, mo, d, h, mi, se = m.groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{se}"
    m = _REAPER_TS.search(os.path.splitext(name)[0])
    if m:
        y, mo, d, h, mi = m.groups()
        return f"20{y}-{mo}-{d}T{h}:{mi}:00"
    return None


def _ts(s):
    with contextlib.suppress(Exception):
        return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))
    return None


_dur_cache = {}


def wav_seconds(path):
    """Durée d'un WAV lue dans l'en-tête (fmt.byte_rate et data.size) — quelques centaines
    d'octets, jamais le fichier. BWF : le chunk `bext` précède `fmt `, d'où la marche de chunk
    en chunk. None si l'en-tête ne se lit pas."""
    try:
        st = os.stat(path)
        key = (path, st.st_size, int(st.st_mtime))
        if key in _dur_cache:
            return _dur_cache[key]
        with open(path, "rb") as f:
            if f.read(4) != b"RIFF":
                return None
            f.read(4)
            if f.read(4) != b"WAVE":
                return None
            rate, data = None, None
            while rate is None or data is None:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
                if cid == b"fmt ":
                    fmt = f.read(size + (size & 1))
                    rate = struct.unpack("<I", fmt[8:12])[0]
                elif cid == b"data":
                    data = size
                    break
                else:
                    f.seek(size + (size & 1), 1)
        out = round(data / rate) if rate and data is not None else None
        _dur_cache[key] = out
        return out
    except Exception:
        return None


def wav_info(path):
    """Ce que l'EN-TÊTE d'un WAV dit — sans décoder un octet d'audio : `{sample_rate, channels,
    bits, time_reference}`. `time_reference` est l'horodatage d'ÉCHANTILLON du chunk BWF `bext`
    (offset 338 : deux mots de 32 bits) — c'est lui qui aligne les lanes d'une prise entre
    elles, et golem.fm en a besoin pour poser une vidéo de téléphone sur sa timeline sans
    geste (message-golem-modes-espaces.md §1.5). Mesuré : les 9 lanes d'une prise portent la
    même valeur, et elle survit à l'encodage FLAC (tag Vorbis `time_reference`).
    {} si l'en-tête ne se lit pas — jamais d'exception."""
    out = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"RIFF":
                return {}
            f.read(4)
            if f.read(4) != b"WAVE":
                return {}
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                cid, size = hdr[:4], struct.unpack("<I", hdr[4:])[0]
                blob = f.read(size + (size & 1))
                if cid == b"fmt " and len(blob) >= 16:
                    ch, sr = struct.unpack("<HI", blob[2:8])
                    out.update(channels=ch, sample_rate=sr,
                               bits=struct.unpack("<H", blob[14:16])[0])
                elif cid == b"bext" and len(blob) >= 346:
                    lo, hi = struct.unpack("<II", blob[338:346])
                    out["time_reference"] = (hi << 32) | lo
                elif cid == b"data":
                    break
    except Exception:
        return out
    return out


# ── lecture ────────────────────────────────────────────────────────────────────────────────
def _read_json(path):
    with contextlib.suppress(Exception):
        with open(path) as f:
            d = json.load(f)
            return d if isinstance(d, dict) else None
    return None


def manifest_path_of(name):
    """Le manifeste d'une prise : take.json du dossier, ou sidecar du .wav à plat.
    Basename seulement (anti path-traversal, même garde que routes_content)."""
    p = os.path.join(RECORDINGS, os.path.basename(str(name or "")))
    if os.path.isdir(p):
        return os.path.join(p, "take.json")
    return (p + ".json") if os.path.isfile(p) else None


def _entries():
    """Chaque prise sur disque : nom, chemin, fichiers, octets, manifeste (ou None)."""
    out = []
    if not os.path.isdir(RECORDINGS):
        return out
    for fn in os.listdir(RECORDINGS):
        p = os.path.join(RECORDINGS, fn)
        try:
            if os.path.isdir(p) and fn.startswith("perf-"):
                files = sorted(f for f in os.listdir(p) if f.lower().endswith((".wav", ".mid")))
                if not files:
                    continue
                size = sum(os.path.getsize(os.path.join(p, f)) for f in files)
                man = _read_json(os.path.join(p, "take.json"))
                first = next((os.path.join(p, f) for f in files if f.lower().endswith(".wav")), None)
            elif fn.lower().endswith(".wav") and os.path.isfile(p):
                files, size, first = [fn], os.path.getsize(p), p
                man = _read_json(p + ".json")
            else:
                continue
        except OSError:
            continue
        out.append({"name": fn, "path": p, "files": files, "size": size, "man": man, "first": first,
                    "mtime": os.path.getmtime(p)})
    return out


def _row(e):
    man = e["man"] or {}
    started = started_at_of(e["name"], man)
    dur = None
    t0, t1 = _ts(started or ""), _ts(man.get("ended_at") or "")
    if t0 is not None and t1 is not None and t1 >= t0:
        dur = int(round(t1 - t0))
    elif e["first"]:
        dur = wav_seconds(e["first"])
    band = man.get("band")
    up = man.get("upload") if isinstance(man.get("upload"), dict) else {}
    row = {
        "uid": uid_of(e["name"]),
        "started_at": started,
        "duration_sec": dur,
        "size_bytes": e["size"],
        "tracks": len(e["files"]),
        "mode": man.get("mode") or ("mix" if os.path.isfile(e["path"]) else None),
        # le TAG ACTUEL : l'id seul voyage ; `band_name` n'est qu'un libellé de confort
        "band": (band.get("id") if isinstance(band, dict) else band) or None,
        "band_name": (band.get("name") if isinstance(band, dict) else None) or None,
        "session": man.get("session"),
        "preset_name": man.get("preset_name"),
        # le nom DONNÉ à la prise (écran Loops, ou posé par la découpe : « Under the Bridge —
        # take 2 »). golem.fm le respecte s'il est là, sinon il titre depuis backing / standard
        # / compo / preset (message-golem-enregistrements.md §8).
        "title": man.get("title"),
        # le MODE MACHINE de la prise (`studio` — affiché « Home » —, `rehearsal`, `gig`…) :
        # il est dans le take.json depuis toujours mais pas dans l'index, et la carte « On the
        # rack » de golem.fm l'affiche (message-golem-modes-espaces.md §1.3). L'ID seulement :
        # le libellé se résout via /api/modes, sinon un mode réédité rendrait l'index menteur.
        "machine_mode": man.get("machine_mode"),
        # ce que la prise EST (show / gig / rehearsal) — gravé au REC depuis le 2026-09-08 ;
        # une prise d'avant le dérive de son mode machine (même règle, jamais « inconnu »).
        # + `riff` : une capture COMPO (docs/compo.md §11) n'est pas une prise de mode, elle se déclare
        "kind": man.get("kind") if man.get("kind") in _modes.TAKE_KINDS + ("riff", "standard-take") else _modes.take_kind_of_id(man.get("machine_mode")),
        # ce que la prise attend AVANT de monter : une longue répète se découpe d'abord.
        # Calculé à la lecture depuis `marks[]` (aucun état à désynchroniser) — golem.fm
        # affiche « 2:04 brutes · 10 morceaux » avant le bouton « Cut & upload » (§1.4).
        **dict(zip(("cut_pending", "songs_detected"), _cut_state(man, dur))),
        **({"parent": man["parent"], "offset_sec": man.get("offset_sec")}
           if man.get("parent") else {}),
        "upload": {"state": up.get("state") or "pending",
                   **{k: up[k] for k in ("code", "at", "rec_id", "pct", "until", "since") if k in up}},
    }
    return row


def _cut_state(man, dur):
    """(cut_pending, songs_detected) — délégué à takecut, en best-effort : un index qui
    échoue vaut mieux qu'un heartbeat qui tombe."""
    try:
        from . import takecut
        return takecut.pending_cut(man, dur)
    except Exception:
        return False, 0


def index():
    """Toutes les prises, plus récentes d'abord (date de départ, sinon mtime)."""
    rows = []
    for e in _entries():
        r = _row(e)
        r["_sort"] = _ts(r["started_at"] or "") or e["mtime"]
        rows.append(r)
    rows.sort(key=lambda r: -r["_sort"])
    for r in rows:
        r.pop("_sort", None)
    return rows


def pending(limit=LIMIT):
    """Le bloc du heartbeat : ce qui n'est PAS monté (state != done), borné à `limit`
    entrées, avec le compte et les octets de TOUT ce qui reste."""
    rows = [r for r in index() if r["upload"].get("state") != "done"]
    return {"pending_takes": rows[:limit], "pending_total": len(rows),
            "pending_bytes": sum(r["size_bytes"] for r in rows)}


# ── retag ──────────────────────────────────────────────────────────────────────────────────
def _read_band():
    from .routes_patches import _read_band as rb
    return rb()


def resolve_band(bid):
    """Un id de groupe -> le tag `{id, name, source}` à graver, ou None si CE RACK ne connaît
    pas le groupe. On n'invente rien : un id libre ferait un tag fantôme que le serveur
    refuserait, et la prise resterait bloquée sans qu'on sache pourquoi. Le web envoie le
    `public_id` du serveur : tant que le roster n'est pas synchronisé (config/.band.json seedé
    en `local-temporary`), il est inconnu ici — et c'est dit, pas avalé."""
    d = _read_band()
    known = {b.get("id"): b for b in (d.get("bands") or []) if isinstance(b, dict)}
    cur = d.get("band") or {}
    if cur.get("id"):
        known.setdefault(cur["id"], cur)
    bid = bid.get("id") if isinstance(bid, dict) else bid
    k = known.get(bid)
    if not k:
        return None
    src = k.get("source") or (cur.get("source") if cur.get("id") == bid else None) or "cache"
    return {"id": bid, "name": k.get("name") or bid, "source": src}


def retag(name, band):
    """Réécrit le SEUL champ `band` du manifeste, en place — le reste est un constat de la
    prise, jamais réécrit après coup. Une prise SANS manifeste (les 77 d'avant le 2026-08-02)
    en reçoit un minimal : sans lui, le tag n'aurait nulle part où vivre."""
    mp = manifest_path_of(name)
    if not mp:
        raise FileNotFoundError(name)
    man = _read_json(mp)
    if man is None:
        if os.path.isfile(mp):
            raise ValueError(f"manifeste illisible : {os.path.basename(mp)}")
        p = os.path.join(RECORDINGS, os.path.basename(name))
        files = ([os.path.basename(p)] if os.path.isfile(p)
                 else sorted(f for f in os.listdir(p) if f.lower().endswith((".wav", ".mid"))))
        man = {"kind": "take", "mode": "mix" if os.path.isfile(p) else None,
               "started_at": started_at_of(name) or "", "files": files,
               "manifest": "reconstructed"}              # dit d'où il vient : pas un constat de prise
    man["band"] = band
    tmp = mp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    os.replace(tmp, mp)
    return man


def tag(items):
    """Le job `take-tag` : `[{uid, band}]` -> `{tagged: [uid…], skipped: [{uid, reason}]}`.
    PARTIEL TOLÉRÉ (comme groove-pack) : un uid inconnu, un groupe inconnu du rack ou un
    manifeste illisible saute SEUL, le reste du lot passe. `band: null` = « Aucun »."""
    by_uid = {uid_of(e["name"]): e["name"] for e in _entries()}
    tagged, skipped = [], []
    for it in (items or []):
        if not isinstance(it, dict) or not it.get("uid"):
            skipped.append({"uid": (it or {}).get("uid") if isinstance(it, dict) else None,
                            "reason": "malformed"})
            continue
        uid = str(it["uid"])
        name = by_uid.get(uid)
        if name is None:
            skipped.append({"uid": uid, "reason": "unknown_take"})
            continue
        band = it.get("band")
        if band is not None:
            tagref = resolve_band(band)
            if tagref is None:
                skipped.append({"uid": uid, "reason": "band_unknown_on_rack",
                                "band": band if isinstance(band, str) else (band or {}).get("id")})
                continue
            band = tagref
        try:
            retag(name, band)
            tagged.append(uid)
        except Exception as e:
            skipped.append({"uid": uid, "reason": f"{type(e).__name__}: {e}"[:160]})
    if tagged:
        log.info(f"take-tag : {len(tagged)} taguée(s), {len(skipped)} sautée(s)")
    return {"tagged": tagged, "skipped": skipped}


def set_title(name, title):
    """Nomme une prise — le SEUL champ d'agrément qu'un humain écrit dans un manifeste, et le
    seul qu'on laisse effacer (`title: None` rend son nom automatique à la prise). Le reste
    est un constat, jamais réécrit après coup.

    Une prise sans manifeste en reçoit un, comme au retag : sans lui, le nom n'aurait nulle
    part où vivre."""
    mp = manifest_path_of(name)
    if not mp:
        raise FileNotFoundError(name)
    man = _read_json(mp)
    if man is None:
        man = {"kind": "take", "started_at": started_at_of(name) or "",
               "manifest": "reconstructed"}
    t = (title or "").strip()[:120]
    if t:
        man["title"] = t
    else:
        man.pop("title", None)
    tmp = mp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    os.replace(tmp, mp)
    return man.get("title")


def readdress(old_id, band):
    """Ré-adresse EN BLOC les prises taguées `old_id` vers `band` — la migration du seed
    (`roster.sync`, décision commune du 2026-09-02). Rend le nombre de prises touchées.

    L'ancien tag n'est PAS perdu : il est empilé dans `band_history[]`. Une prise doit
    toujours pouvoir dire d'où vient son groupe — c'est ce qui rend le geste réversible et
    audité, et c'est la condition qui a fait préférer l'automatique au tap (un tap sur un
    écran que personne n'ouvre laisse 30 prises bloquées, et le symptôme est un 404 muet).

    ⚠ On ne touche QUE les prises dont le tag porte exactement `old_id`. Une prise « Aucun »
    reste « Aucun » : le ré-adressage corrige une adresse, il n'en attribue jamais une.
    """
    n = 0
    for e in _entries():
        man = e["man"] or {}
        b = man.get("band")
        bid = b.get("id") if isinstance(b, dict) else b
        if not bid or bid != old_id:
            continue
        mp = manifest_path_of(e["name"])
        if not mp:
            continue
        cur = _read_json(mp) or man
        hist = cur.get("band_history")
        cur["band_history"] = (hist if isinstance(hist, list) else []) + [
            {"band": b, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": "seed-readdress"}]
        cur["band"] = dict(band)
        tmp = mp + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cur, f, indent=1, ensure_ascii=False)
        os.replace(tmp, mp)
        n += 1
    if n:
        log.info(f"ré-adressage : {n} prise(s) {old_id} -> {band.get('id')}")
    return n
