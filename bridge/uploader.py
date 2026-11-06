# SPDX-License-Identifier: GPL-3.0-or-later
"""Le MONTEUR — ce qui fait monter une prise vers golem.fm, hors temps de jeu.

Contrat : docs/private/exchanges/message-maestrium-ranger-prises.md §2-3 (lot B) et la face rack de
`band_recordings.py` côté serveur — trois gestes :

    POST /api/ext/recordings           déclare la prise (IDEMPOTENT : rouvrir rend l'état
                                       par piste, c'est LA reprise après une coupure WiFi)
    PUT  …/{rec}/tracks/{idx}?offset=  une tranche d'octets ; au dernier, le serveur hache
    POST …/{rec}/complete              scelle

Cinq décisions, toutes dictées par le disque et le quota :

  - **FLAC, lanes traitées par défaut.** Brut, une répète de 3 h fait 17 Go ; les lanes
    traitées en FLAC pèsent 40 à 65 % du WAV selon la densité (mesuré le 2026-09-07 sur
    de vraies prises). DI et MIDI ne partent que sur demande — `kinds` du job, c'est le
    `request-di` du web (message « enregistrements » §7). Le mono ne gagne RIEN : FLAC
    exploite déjà la redondance des canaux (mesuré : 3,05 Mo dans les deux cas).
  - **Jamais pendant qu'on joue.** Un REC en cours ou le mode Gig arrêtent le monteur net.
    Le transcodage et le réseau sont du temps CPU et des I/O — pas pendant la musique.
  - **La reprise n'a pas d'état chez nous.** L'offset de reprise vient du SERVEUR, à
    l'ouverture. Un rack qui redémarre au milieu d'un envoi reprend où il en était sans
    avoir rien mémorisé — donc sans rien à désynchroniser.
  - **Un refus se lit.** 413 -> `upload.state = refused, code: "quota"` dans le manifeste,
    et on n'insiste pas : c'est l'écran web qui montre le quota AVANT le bouton.
  - **Les noms Reaper ne passent pas.** `FILENAME_RE` côté serveur interdit le `#`, et
    « 02-Sandbox #Input 2-260726_1807.wav » en porte un. On déclare un nom nettoyé ;
    l'original reste dans le `take.json`, qui monte tel quel (`kind: "meta"`).
"""
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

from . import config as C
from .golog import get

log = get("uploader")

CHUNK = 8 * 1024 * 1024              # le serveur en accepte 32 ; 8 = reprise fine sur un WiFi de salle
CACHE = os.path.join(C.ROOT, "recordings", ".upload")
DEFAULT_KINDS = ("mix", "track")     # les lanes TRAITÉES ; la DI est une demande, pas un défaut
_BAD_NAME = re.compile(r"[^A-Za-z0-9._ -]")

_lock = threading.Lock()             # une seule montée à la fois (le job ET la boucle)
_wake = threading.Event()
_last = {}                           # uid -> dernier rapport, pour l'UI et les tests


# ── ce qu'une piste EST ────────────────────────────────────────────────────────────────────
def kind_of(fn):
    """Le `kind` du serveur, déduit du nom — la même table que le message §3.2. `mix` avant
    `track` : « Mix.wav » est la lane qu'on écoute, pas une lane parmi d'autres."""
    low = fn.lower()
    if low.endswith(".mid") or low.startswith("midi-"):
        return "midi"
    if low.startswith("di-"):
        return "di"
    if low == "take.json":
        return "meta"
    if "mix" in low:
        return "mix"
    return "track"


def clean_name(fn):
    """Un nom que `FILENAME_RE` accepte : `^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$`. Le `#` de
    Reaper devient `-`, et un nom qui ne commence pas par un alphanumérique est préfixé —
    sinon le serveur refuse la DÉCLARATION entière, donc la prise, pour un caractère."""
    s = _BAD_NAME.sub("-", fn).strip()
    if not s or not s[0].isalnum():
        s = "t-" + s.lstrip("-. ")
    return s[:255]


# ── préparation : le transcodage ───────────────────────────────────────────────────────────
def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def to_flac(src, dst):
    """WAV -> FLAC, sans perte, niveau 8. Rend True si le fichier est là et non vide.
    ⚠ `-map_metadata 0` : le chunk `bext` de Reaper porte l'horodatage d'échantillon
    (`TimeReference`) qui aligne les lanes entre elles — le perdre, c'est perdre le calage
    multipiste, donc le mini-DAW du web."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-map_metadata", "0",
                        "-c:a", "flac", "-compression_level", "8", dst],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        log.warning(f"flac: {os.path.basename(src)} — {(r.stderr or '').strip()[:160]}")
        return False
    return True


def prepare(name, kinds=None):
    """Les pistes à déclarer pour la prise `name` : transcodage des WAV retenus, take.json
    tel quel. Rend une liste `[{idx, filename, kind, path, sha256, size_bytes, orig}]`.

    Le cache vit dans `recordings/.upload/<name>/` et meurt avec la montée. Une piste déjà
    transcodée n'est pas refaite : reprendre une montée coupée ne re-paie pas le CPU.
    """
    from . import takes
    want = set(kinds or DEFAULT_KINDS) | {"meta"}
    src_dir = os.path.join(takes.RECORDINGS, name)
    # UN RIFF NE MONTE QUE LES FICHIERS DE SON AUTEUR (docs/compo.md §11) : ses lanes déclarées — ni le
    # Mix, ni les pistes des autres, qui n'ont rien demandé
    only = None
    rman = takes._read_json(takes.manifest_path_of(name) or "") or {}
    if rman.get("kind") in ("riff", "standard-take") and isinstance(rman.get("lanes"), list):
        only = {f for ln in rman["lanes"] for k, f in ((ln or {}).get("files") or {}).items() if k != "score"}
    flat = os.path.isfile(src_dir)                       # un .wav à plat est une prise aussi
    files = ([os.path.basename(src_dir)] if flat
             else sorted(f for f in os.listdir(src_dir) if f.lower().endswith((".wav", ".mid"))))
    base = os.path.dirname(src_dir) if flat else src_dir
    out, seen, idx = [], set(), 0
    cache = os.path.join(CACHE, takes.uid_of(name))

    for fn in files:
        k = kind_of(fn)
        if only is not None:
            if fn not in only:
                continue
        elif k not in want:
            continue
        src = os.path.join(base, fn)
        if fn.lower().endswith(".wav"):
            dst = os.path.join(cache, clean_name(os.path.splitext(fn)[0]) + ".flac")
            if not (os.path.isfile(dst) and os.path.getsize(dst) > 0) and not to_flac(src, dst):
                continue                                  # une lane illisible saute SEULE
            path, decl = dst, os.path.basename(dst)
        else:
            path, decl = src, clean_name(fn)
        while decl in seen:                               # deux noms nettoyés identiques
            decl = f"{idx:02d}-{decl}"
        seen.add(decl)
        out.append({"idx": idx, "filename": decl, "kind": k, "path": path,
                    "sha256": _sha(path), "size_bytes": os.path.getsize(path),
                    **({"orig": fn} if decl != fn else {})})
        idx += 1

    # UN RIFF DÉCLARE SES LANES PAR NOM DE FICHIER, et golem.fm les apparie AU NOM EXACT de la piste montée
    # (message golem.fm du 2026-09-30, `by_file[t.filename]`). Or le WAV part en FLAC sous un nom nettoyé,
    # et la partition vit dans `scores/` — un « / » que FILENAME_RE refuse. Donc : la partition monte
    # comme piste `score` sous son nom nu, et la COPIE du manifeste qui monte nomme chaque fichier de lane
    # exactement comme sa piste. Le take.json du rack garde ses chemins locaux.
    rename = {}
    if only is not None:
        rename = {t.get("orig") or t["filename"]: t["filename"] for t in out}
        for ln in rman.get("lanes") or []:
            sc = ((ln or {}).get("files") or {}).get("score")
            p = os.path.join(src_dir, sc) if sc else None
            if not p or not os.path.isfile(p):
                continue
            decl = clean_name(os.path.basename(sc))
            while decl in seen:
                decl = f"{idx:02d}-{decl}"
            seen.add(decl)
            out.append({"idx": idx, "filename": decl, "kind": "score", "path": p,
                        "sha256": _sha(p), "size_bytes": os.path.getsize(p), "orig": sc})
            rename[sc] = decl
            idx += 1

    man = takes.manifest_path_of(name)
    if "meta" in want and man and os.path.isfile(man):
        # ⚠ On monte une COPIE FIGÉE, jamais le manifeste vivant : le monteur écrit son
        # avancement (`upload.pct`) DANS ce fichier pendant qu'il l'envoie — le vrai
        # serveur a répondu « Chunk overflows the declared size » sur la piste meta, parce
        # que le fichier avait grossi entre la déclaration et le dernier octet. La copie
        # laisse aussi `upload` de côté : c'est l'état d'une montée, pas un constat de la
        # prise, et il n'a rien à faire dans ce qu'on archive.
        photo = os.path.join(cache, "take.json")
        os.makedirs(cache, exist_ok=True)
        d = takes._read_json(man) or {}
        d.pop("upload", None)
        if rename:
            for ln in d.get("lanes") or []:
                fs = (ln or {}).get("files") or {}
                for k, v in list(fs.items()):
                    if v in rename:
                        fs[k] = rename[v]
                    else:
                        fs.pop(k)                         # un fichier qui ne monte pas n'est pas déclaré
        with open(photo, "w") as f:
            json.dump(d, f, indent=1, ensure_ascii=False)
        out.append({"idx": idx, "filename": "take.json", "kind": "meta", "path": photo,
                    "sha256": _sha(photo), "size_bytes": os.path.getsize(photo)})
    return out


# ── la montée d'UNE prise ──────────────────────────────────────────────────────────────────
def _set_state(name, patch):
    """Écrit `upload` dans le manifeste — le SEUL champ que le monteur touche. Le reste est
    un constat de la prise (takes.retag dit la même chose du tag)."""
    from . import takes
    mp = takes.manifest_path_of(name)
    if not mp or not os.path.isfile(mp):
        return
    man = takes._read_json(mp) or {}
    up = man.get("upload") if isinstance(man.get("upload"), dict) else {}
    man["upload"] = {**up, **patch}
    tmp = mp + ".tmp"
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    os.replace(tmp, mp)


def refusal(st, detail):
    """Le refus de golem.fm, en UNE raison courte et stable (2026-10-14, lu dans leur code — band_recordings.py,
    auth_deps.py) : c'est elle que /live affiche sur la case Riff. Les codes `band_gone`/`band_forbidden` sont stables
    chez eux ; le quota (413) n'est qu'une phrase, reconnue au statut."""
    err = detail.get("error") if isinstance(detail, dict) else None
    text = str(detail or "").lower()
    if st == 0:
        return "offline"
    if st == 401 or (st == 403 and "scope" in text):
        return "relink"                                   # jeton absent, révoqué, ou sans le droit d'écrire
    if st == 403 and err == "band_forbidden":
        return "forbidden"
    if st == 404 and err == "band_gone":
        return "space_gone"
    if st == 413:
        return "quota"
    if st == 422:
        return "no_space"
    return f"open_{st}"


def upload_take(name, kinds=None):
    """Monte UNE prise, de la déclaration au sceau. Ne lève pas : rend un rapport.

    `{ok, uid, rec_id?, tracks?, bytes?, reason?, code?}` — et l'état est écrit dans le
    manifeste au fil de l'eau, parce que c'est lui que le heartbeat publie.
    """
    from . import golemfm, takes
    uid = takes.uid_of(name)
    man = takes._read_json(takes.manifest_path_of(name) or "") or {}
    band = man.get("band")
    bid = band.get("id") if isinstance(band, dict) else band
    if not bid:
        return {"ok": False, "uid": uid, "reason": "untagged", "why": "no_space"}

    base, token = golemfm._cfg()
    if not base or not token:
        return {"ok": False, "uid": uid, "reason": "not_paired", "why": "relink"}

    try:
        tracks = prepare(name, kinds)
    except OSError as e:
        return {"ok": False, "uid": uid, "reason": f"prepare: {e}"}
    if not tracks:
        return {"ok": False, "uid": uid, "reason": "nothing_to_upload"}

    _set_state(name, {"state": "uploading", "pct": 0, "at": _now()})
    decl = [{k: t[k] for k in ("idx", "filename", "kind", "sha256", "size_bytes")} for t in tracks]
    # ⚠ UNE SEULE VÉRITÉ DÉCLARÉE (golem.fm, 2026-09-30, prise 175) : golem.fm stocke le `take` de
    # l'ouverture, pas le take.json monté. On envoyait le manifeste LOCAL (fichiers de lane en .wav,
    # « scores/… ») pendant que la piste meta portait les noms montés : la lane arrivait sans aucun
    # fichier, le riff muet. La déclaration envoie désormais la MÊME copie figée que la piste meta.
    photo = next((t for t in tracks if t["kind"] == "meta"), None)
    take = man
    if photo:
        with contextlib.suppress(OSError, ValueError):
            take = json.load(open(photo["path"]))
    st, rec = golemfm._req("/api/ext/recordings", token=token,
                             body={"uid": uid, "take": take, "band": bid, "tracks": decl})
    if st == 413:
        _set_state(name, {"state": "refused", "code": "quota", "at": _now()})
        log.warning(f"{uid} : refusé — quota du groupe dépassé")
        return {"ok": False, "uid": uid, "reason": "quota", "code": 413, "why": "quota"}
    if st != 200 or not isinstance(rec, dict) or not rec.get("id"):
        why = refusal(st, rec)
        _set_state(name, {"state": "refused", "code": why, "at": _now()})
        log.warning(f"{uid} : ouverture refusée ({st}, {why}) {str(rec)[:160]}")
        return {"ok": False, "uid": uid, "reason": "open_failed", "code": st, "why": why}

    rid = rec["id"]
    served = {t["idx"]: t for t in (rec.get("tracks") or [])}
    total = sum(t["size_bytes"] for t in tracks) or 1
    bad = _send_tracks(name, uid, rid, tracks, served, token,
                       lambda pct: _set_state(name, {"state": "uploading", "pct": pct, "rec_id": rid}))
    if bad:
        _set_state(name, {"state": "refused", "code": f"put_{bad}", "at": _now()})
        return {"ok": False, "uid": uid, "reason": "put_failed", "code": bad}

    st, res = golemfm._req(f"/api/ext/recordings/{rid}/complete", token=token, body={})
    if st != 200:
        _set_state(name, {"state": "refused", "code": f"complete_{st}", "at": _now()})
        return {"ok": False, "uid": uid, "reason": "complete_failed", "code": st}

    _set_state(name, {"state": "done", "at": _now(), "rec_id": rid, "pct": 100})
    with contextlib.suppress(OSError):                    # le cache a fini son office
        shutil.rmtree(os.path.join(CACHE, uid), ignore_errors=True)
    log.info(f"{uid} monté : {len(tracks)} piste(s), {total // 1048576} Mo, rec {rid}")
    return {"ok": True, "uid": uid, "rec_id": rid, "tracks": len(tracks), "bytes": total}


def _send_tracks(name, uid, rid, tracks, served, token, progress):
    """Les tranches de chaque piste, à partir de l'offset que le SERVEUR rend (la reprise n'a pas d'état chez nous).
    Rend None si tout est passé, sinon le code HTTP du refus."""
    from . import golemfm
    total = sum(t["size_bytes"] for t in tracks) or 1
    sent = sum(min(served.get(t["idx"], {}).get("received", 0), t["size_bytes"]) for t in tracks)
    for t in tracks:
        got = served.get(t["idx"]) or {}
        if got.get("done"):
            continue                                      # déjà là : la reprise saute la piste
        off = int(got.get("received") or 0)
        with open(t["path"], "rb") as f:
            f.seek(off)
            while off < t["size_bytes"]:
                buf = f.read(CHUNK)
                if not buf:
                    break
                st, res = golemfm.put_bytes(
                    f"/api/ext/recordings/{rid}/tracks/{t['idx']}?offset={off}", buf,
                    token=token)
                if st == 409 and isinstance(res, str) and "expected offset" in res:
                    off = int(re.search(r"(\d+)", res.split("offset")[-1]).group(1))
                    f.seek(off)                           # le serveur fait foi, on le suit
                    continue
                if st != 200:
                    log.warning(f"{uid} piste {t['idx']} : {st} {str(res)[:120]}")
                    return st or 0
                off += len(buf)
                sent += len(buf)
                progress(round(100 * sent / total))
    return None


# ── LES DI, sur demande (job `upload-di` de golem.fm) ──────────────────────────────────────────
# La DI ne part que sur demande (« le mix suffit à décider si la prise vaut quelque chose »). Mais la prise est
# déjà MONTÉE — mix, lanes, take.json — et le serveur vérifie chaque piste re-déclarée par (idx, sha) : redéclarer la
# prise entière avec les DI décalerait les idx (numérotation dans l'ordre des fichiers retenus) et finirait en 409.
# Donc : on rouvre la prise SANS piste pour lire ce qu'elle a, puis on déclare SEULEMENT les DI, sous des idx libres —
# une DI déjà déclarée (même nom) garde le sien et reprend à l'offset du serveur. L'état vit à part (`upload_di`) :
# il ne touche pas l'état de la montée principale, que le web lit pour savoir si la prise est arrivée.
def _set_di_state(name, patch):
    from . import takes
    man = takes.manifest_path_of(name)
    if not man:
        return
    d = takes._read_json(man) or {}
    d["upload_di"] = {**(d.get("upload_di") or {}), **patch}
    tmp = man + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, man)


def upload_di(name, band=None):
    """Monte les pistes DI d'une prise DÉJÀ montée (ou non). Ne lève pas : rend un rapport."""
    from . import golemfm, takes
    uid = takes.uid_of(name)
    ok, why = can_run()
    if not ok:
        return {"ok": False, "uid": uid, "reason": why}
    man = takes._read_json(takes.manifest_path_of(name) or "") or {}
    tag = man.get("band")
    bid = band or (tag.get("id") if isinstance(tag, dict) else tag)
    if not bid:
        return {"ok": False, "uid": uid, "reason": "untagged", "why": "no_space"}
    base, token = golemfm._cfg()
    if not base or not token:
        return {"ok": False, "uid": uid, "reason": "not_paired", "why": "relink"}
    try:
        dis = [t for t in prepare(name, ("di",)) if t["kind"] == "di"]
    except OSError as e:
        return {"ok": False, "uid": uid, "reason": f"prepare: {e}"}
    if not dis:
        return {"ok": False, "uid": uid, "reason": "no_di", "why": "this take has no DI track (Rec in Multi + DI)"}
    _set_di_state(name, {"state": "uploading", "pct": 0, "at": _now()})
    # 1) ce que la prise a déjà, sans rien déclarer
    st, rec = golemfm._req("/api/ext/recordings", token=token, body={"uid": uid, "take": man, "band": bid, "tracks": []})
    if st != 200 or not isinstance(rec, dict) or not rec.get("id"):
        why = refusal(st, rec)
        _set_di_state(name, {"state": "refused", "code": why, "at": _now()})
        return {"ok": False, "uid": uid, "reason": "open_failed", "code": st, "why": why}
    have = {t.get("filename"): t for t in (rec.get("tracks") or [])}
    nxt = max([int(t.get("idx", -1)) for t in (rec.get("tracks") or [])] + [-1]) + 1
    for t in dis:
        if t["filename"] in have:
            t["idx"] = int(have[t["filename"]]["idx"])    # déjà déclarée : même idx, la reprise suit
        else:
            t["idx"] = nxt
            nxt += 1
    decl = [{k: t[k] for k in ("idx", "filename", "kind", "sha256", "size_bytes")} for t in dis]
    # 2) les DI seules
    st, rec = golemfm._req("/api/ext/recordings", token=token, body={"uid": uid, "take": man, "band": bid, "tracks": decl})
    if st != 200 or not isinstance(rec, dict) or not rec.get("id"):
        why = refusal(st, rec)
        _set_di_state(name, {"state": "refused", "code": why, "at": _now()})
        return {"ok": False, "uid": uid, "reason": "declare_failed", "code": st, "why": why}
    rid = rec["id"]
    served = {t["idx"]: t for t in (rec.get("tracks") or [])}
    bad = _send_tracks(name, uid, rid, dis, served, token, lambda pct: _set_di_state(name, {"pct": pct}))
    if bad:
        _set_di_state(name, {"state": "refused", "code": f"put_{bad}", "at": _now()})
        return {"ok": False, "uid": uid, "reason": "put_failed", "code": bad}
    st, res = golemfm._req(f"/api/ext/recordings/{rid}/complete", token=token, body={})
    if st != 200:
        _set_di_state(name, {"state": "refused", "code": f"complete_{st}", "at": _now()})
        return {"ok": False, "uid": uid, "reason": "complete_failed", "code": st}
    _set_di_state(name, {"state": "done", "pct": 100, "at": _now(), "rec_id": rid})
    log.info(f"{uid} : {len(dis)} DI montée(s), rec {rid}")
    return {"ok": True, "uid": uid, "rec_id": rid, "di": len(dis)}


def queue_di(uid, band=None):
    """Le job `upload-di` : vérifie que la prise existe et porte des DI, puis monte EN FOND (une seule montée à la
    fois, le verrou du monteur). L'ack dit `queued` ; la progression se lit dans le manifeste (`upload_di`)."""
    from . import takes
    by_uid = {takes.uid_of(e["name"]): e["name"] for e in takes._entries()}
    name = by_uid.get(uid)
    if not name:
        raise RuntimeError(f"upload-di: unknown take {uid!r}")

    def run():
        with _lock:
            _last[uid] = upload_di(name, band)
    threading.Thread(target=run, daemon=True).start()
    return {"queued": [uid]}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── la boucle ──────────────────────────────────────────────────────────────────────────────
def can_run():
    """(bool, raison). Le monteur se tait pendant qu'on joue — c'est la règle qui compte."""
    from .state import state
    if (getattr(state, "perf", None) or {}).get("recording"):
        return False, "rec"
    mode = getattr(state, "mode", None)
    mid = mode.get("id") if isinstance(mode, dict) else mode
    if mid == "gig":
        return False, "gig"
    return True, None


TRANSCRIBE_STALE_S = 20 * 60     # compo._transcribe abandonne à 15 min


def due(uids=None):
    """Les prises à monter, plus récentes d'abord : taguées, pas encore montées, et jamais
    celles qu'un refus a marquées — un quota dépassé ne se retente pas en boucle."""
    from . import takes
    out = []
    for r in takes.index():
        if uids is not None and r["uid"] not in uids:
            continue
        if not r.get("band") or r["upload"].get("state") in ("done", "refused", "cut", "dropped"):
            continue                       # `cut` : ce sont ses MORCEAUX qui montent, pas elle
        # un RIFF attend sa fenêtre de drop (docs/compo.md §11) ; `dropped` ne monte jamais
        if r["upload"].get("state") == "held" and time.time() < float(r["upload"].get("until") or 0):
            continue
        # puis sa TRANSCRIPTION (compo._settle) — sauf si elle a été abandonnée (bridge relancé en route) : passé
        # TRANSCRIBE_STALE_S, la prise monte sans partition plutôt que jamais
        if r["upload"].get("state") == "transcribing" and \
                time.time() < float(r["upload"].get("since") or 0) + TRANSCRIBE_STALE_S:
            continue
        out.append(r["uid"])
    return out


def tick(uids=None, kinds=None):
    """UNE passe : monte les prises dues, une par une, en s'arrêtant dès qu'on rejoue."""
    if not _lock.acquire(blocking=False):
        return {"ok": False, "reason": "busy"}
    try:
        from . import takes
        ok, why = can_run()
        if not ok:
            return {"ok": False, "reason": why}
        by_uid = {takes.uid_of(e["name"]): e["name"] for e in takes._entries()}
        done = []
        for uid in due(uids):
            ok, why = can_run()
            if not ok:
                log.info(f"monteur suspendu ({why}) — {len(done)} prise(s) montée(s)")
                break
            # une longue répète se DÉCOUPE d'abord — hors temps de jeu, c'est ici que ça
            # tombe (§1.4 : « automatique hors temps de jeu »). Les morceaux nés de la coupe
            # sont montés au tour suivant : ils sont dans l'index dès qu'ils existent.
            row = next((r for r in takes.index() if r["uid"] == uid), None)
            if row and row.get("cut_pending"):
                from . import takecut
                rep = takecut.cut(by_uid[uid])
                log.info(f"{uid} : {len(rep.get('uids') or [])} morceau(x) — montée au tour suivant")
                _last[uid] = rep
                done.append({"ok": rep.get("ok"), "uid": uid, "cut": rep.get("uids")})
                continue
            rep = upload_take(by_uid[uid], kinds)
            _last[uid] = rep
            with contextlib.suppress(Exception):          # un RIFF : sa case /live dit s'il est arrivé, et sinon pourquoi
                from . import compo
                compo.note_upload(by_uid[uid], rep)
            done.append(rep)
            with contextlib.suppress(Exception):
                from . import rigstatus
                rigstatus.push_soon()
        return {"ok": True, "uploaded": [r for r in done if r.get("ok")],
                "failed": [r for r in done if not r.get("ok")]}
    finally:
        _lock.release()


def queue(uids=None, kinds=None):
    """Le job `take-upload` : marque `queued` et réveille le monteur. La montée elle-même
    est asynchrone — l'ack dit `queued`, la progression passe par le heartbeat."""
    from . import takes
    by_uid = {takes.uid_of(e["name"]): e["name"] for e in takes._entries()}
    picked = due(set(uids) if uids else None)
    for uid in picked:
        _set_state(by_uid[uid], {"state": "queued", "at": _now()})
    # des uids DEMANDÉS dont aucun n'est dû = rien à monter — jamais « tout ce qui est dû » (c'est ainsi qu'un riff en
    # pleine transcription partait sans sa partition, 2026-10-29)
    threading.Thread(target=lambda: tick(set(picked) if uids else None, kinds),
                     daemon=True).start()
    return {"queued": picked, "skipped": sorted(set(uids or []) - set(picked))}


def start_worker(period=300):
    """Filet périodique : entre deux morceaux si le rack est au repos, sinon plus tard.
    Silencieux si non appairé (le `tick` s'arrête à la première prise sans jeton)."""
    def loop():
        while True:
            _wake.wait(period)
            _wake.clear()
            with contextlib.suppress(Exception):
                ok, _ = can_run()
                if ok and due():
                    tick()
    threading.Thread(target=loop, daemon=True).start()
    log.info("monteur armé")
