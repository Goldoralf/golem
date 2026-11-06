# SPDX-License-Identifier: GPL-3.0-or-later
"""La DÉCOUPE — une répète de deux heures devient les morceaux qu'on y a joués.

Contrat : `docs/private/repete-vers-demo.md` §4.1-4.2 (mes décisions) et la décision commune du
2026-09-06 (`~/code/maestrium/conception/message-golem-modes-espaces.md` §1.4) — **le rack
découpe et NOMME à la montée, golem.fm groupe, corrige et re-résout**.

Pourquoi ici et pas là-bas, en trois faits mesurés :

  - **les octets** : 3 h × 6 lanes = 17 Go bruts. Découpés sur les marques et en FLAC, ~5 Go
    de morceaux joués. Monter le fichier entier ne passe ni le WiFi de la salle ni le quota ;
  - **la découpe est gratuite** : couper un WAV sur un marqueur est une COPIE DE FLUX
    (`-c copy`), sans réencodage ni moteur audio — quelques secondes pour trois heures ;
  - **le rack sait déjà** : `marks[]` journalise les recalls de preset, les scènes, le click
    et les flags. Lui faire redécouvrir ça par l'audio serait une perte d'information.

Quatre règles qui font la différence entre découper et abîmer :

  1. **On coupe sur le JOURNAL, jamais sur le silence.** Une pause, une rupture, une fin en
     suspens sont de la musique ; le silence n'est un blanc que là où le journal dit qu'on ne
     jouait pas (§4.1).
  2. **Une frontière trop rapprochée n'en est pas une.** Deux recalls à trois secondes
     d'intervalle — on cherchait le bon son — ne font pas un morceau de trois secondes : le
     segment est absorbé par le précédent.
  3. **Un segment muet ne monte pas.** Mesuré au `volumedetect` sur la lane Mix (la somme :
     si elle est vide, tout l'est). Les 19 Go de silence du 30/07 ont coûté un ménage ; ils
     auraient coûté un quota.
  4. **La source entière RESTE sur le rack** jusqu'à validation des frontières côté web. Une
     marque mal placée ne doit jamais coûter le morceau.

⚠ `ffmpeg -c copy` PERD le chunk BWF (mesuré) : un segment sortirait sans ancre d'échantillon.
On la RÉÉCRIT, décalée de l'offset (`-write_bext 1 -metadata time_reference=…`), pour que
chaque morceau reste honnête sur l'instant où il a été joué.
"""
import contextlib
import json
import os
import re
import subprocess
import time

from . import config as C
from .golog import get

log = get("takecut")

MIN_SEC = 20.0          # sous ça, ce n'est pas un morceau : c'est une frontière parasite
SILENT_DB = -80.0       # au-dessus, il y a du signal ; en dessous, du vide (mesuré)


# ── le nom d'un morceau ────────────────────────────────────────────────────────────────────
def song_of(preset_id):
    """`{slug, title}` de la chanson liée à ce preset, ou None. Le lien preset→chanson naît
    ICI (le bloc Backing du preset), et c'est pour ça que le nommage appartient au rack : il
    connaît le preset au recall. golem.fm le RE-RÉSOUT à l'ingestion — le preset est le fait
    gravé, la chanson une résolution qui peut changer après coup."""
    if not preset_id:
        return None
    from . import store
    p = store.load_preset(preset_id)
    slug = next(iter((p or {}).get("backing") or []), None)
    if not slug:
        return None
    title = slug
    with contextlib.suppress(Exception):
        from . import golemfm
        title = (golemfm.read_meta(slug) or {}).get("title") or slug
    return {"slug": slug, "title": title}


def title_of(seg):
    """« Under the Bridge — take 2 », ou « Jam · Clean Twin » quand le preset ne porte aucune
    chanson. Vrai dans les deux cas : on ne baptise jamais un morceau qu'on ne connaît pas."""
    base = (seg.get("song") or {}).get("title") or f"Jam · {seg.get('preset_name') or seg.get('preset') or 'take'}"
    n = seg.get("take_no") or 1
    return f"{base} — take {n}" if n > 1 and seg.get("song") else base


# ── les frontières ─────────────────────────────────────────────────────────────────────────
def duration_of(man, path):
    """La durée de la prise : les horodatages du manifeste d'abord (ils font foi), l'en-tête
    du premier WAV en repli — jamais un décodage."""
    with contextlib.suppress(Exception):
        t0 = time.mktime(time.strptime(man["started_at"], "%Y-%m-%dT%H:%M:%S"))
        t1 = time.mktime(time.strptime(man["ended_at"], "%Y-%m-%dT%H:%M:%S"))
        if t1 > t0:
            return t1 - t0
    from . import takes
    d = None
    if os.path.isdir(path):
        w = next((f for f in sorted(os.listdir(path)) if f.lower().endswith(".wav")), None)
        d = takes.wav_seconds(os.path.join(path, w)) if w else None
    elif os.path.isfile(path):
        d = takes.wav_seconds(path)
    return float(d or 0)


def segments(man, duration):
    """Les morceaux d'une prise, dérivés de `marks[]`. Un seul segment = il n'y a rien à
    découper (le REC a été coupé au pied entre les morceaux, et c'est le geste qu'on
    encourage : une frontière posée en jouant ne sera jamais battue par un algorithme).

    Chaque recall de preset ouvre un morceau. Les segments plus courts que MIN_SEC sont
    ABSORBÉS par le précédent — on cherchait un son, on n'a pas joué un morceau de 3 s.
    """
    marks = [m for m in (man.get("marks") or [])
             if isinstance(m, dict) and m.get("kind") == "preset" and m.get("value")]
    marks.sort(key=lambda m: float(m.get("sec") or 0))
    if not marks or duration <= 0:
        return []

    raw = []
    for i, m in enumerate(marks):
        start = max(0.0, float(m.get("sec") or 0))
        end = float(marks[i + 1].get("sec")) if i + 1 < len(marks) else duration
        raw.append({"start": start, "end": min(end, duration),
                    "preset": m.get("value"), "preset_name": m.get("name") or m.get("value"),
                    "song_hint": m.get("song") if isinstance(m.get("song"), dict) else None,   # la ligne de setlist, si le rappel en venait
                    "at": f"recall {m.get('value')}"})

    merged, carry = [], None
    for seg in raw:
        if carry is not None:                        # un début trop court traîne : on le reprend
            seg = {**seg, "start": carry}
            carry = None
        short = seg["end"] - seg["start"] < MIN_SEC
        if short and merged:
            merged[-1]["end"] = seg["end"]           # absorbé : la frontière n'en était pas une
            continue
        if short:
            # trop court ET en TÊTE : personne devant pour l'absorber. On ne jette pas l'audio
            # (le morceau commence bien là), mais c'est le preset SUIVANT qui le nomme — on
            # cherchait le bon son, on n'a pas joué un morceau de trois secondes.
            carry = seg["start"]
            continue
        merged.append(seg)
    if carry is not None and merged:                 # tout le début était court
        merged[0]["start"] = carry
    if len(merged) > 1 and merged[-1]["end"] - merged[-1]["start"] < MIN_SEC:
        merged[-2]["end"] = merged.pop()["end"]

    seen = {}
    out = []
    for seg in merged:
        hint = seg.pop("song_hint", None)
        # la LIGNE de setlist d'abord (slug opaque recopié dans la marque), le backing du preset en repli
        song = ({"slug": hint.get("slug") or hint.get("title"), "title": hint.get("title") or hint.get("slug")}
                if hint and (hint.get("slug") or hint.get("title")) else song_of(seg["preset"]))
        key = (song or {}).get("slug") or seg["preset"]
        seen[key] = seen.get(key, 0) + 1
        out.append({**seg, "song": song, "take_no": seen[key],
                    "duration": round(seg["end"] - seg["start"], 3),
                    "cut": {"by": "preset", "at": seg["at"], "confidence": "high"}})
    return out


def is_silent(path, start, dur):
    """Le segment contient-il du son ? Mesuré sur la lane MIX quand elle existe — c'est la
    somme de tout : si elle est vide, tout l'est, et une seule mesure suffit. Sans Mix, on
    prend la première lane. En cas de doute (ffmpeg muet, fichier illisible) : NON silencieux,
    parce que jeter une prise par erreur est bien pire que monter du vide."""
    if os.path.isdir(path):
        wavs = sorted(f for f in os.listdir(path) if f.lower().endswith(".wav"))
        pick = next((f for f in wavs if "mix" in f.lower()), wavs[0] if wavs else None)
        if not pick:
            return False
        path = os.path.join(path, pick)
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-ss", f"{start:.3f}",
                        "-i", path, "-t", f"{dur:.3f}", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr or "")
    return bool(m) and float(m.group(1)) <= SILENT_DB


# ── la coupe ───────────────────────────────────────────────────────────────────────────────
def _slice(src, dst, start, dur, anchor=None):
    """Une lane, un segment : COPIE DE FLUX, aucun réencodage, aucune perte.

    ⚠ `-c copy` perd le chunk `bext` (mesuré le 2026-09-07) : on le réécrit avec l'ancre
    DÉCALÉE de l'offset. Sans ça le morceau porterait l'heure du début de la répète, et la
    vidéo du téléphone se poserait deux heures trop tôt sur la timeline de golem.fm."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{dur:.3f}",
           "-c", "copy"]
    if anchor is not None:
        cmd += ["-write_bext", "1", "-metadata", f"time_reference={int(anchor)}"]
    cmd.append(dst)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        log.warning(f"coupe ratée {os.path.basename(src)} @{start:.1f}s : "
                    f"{(r.stderr or '').strip()[:160]}")
        return False
    return True


def _child_manifest(man, seg, parent_uid, files, sr, anchor):
    """Le `take.json` d'un morceau : le constat du PARENT, plus ce qui fait de lui un morceau.

    Le protocole de montée ne change pas d'un iota (§1.4) — un enfant est une prise comme une
    autre, avec `parent` renseigné. Les marques sont RELATIVES au morceau : une marque à
    23'14 de la répète est à 1'02 du morceau, et c'est celle-là qui a du sens pour l'écouter.
    """
    start = seg["start"]
    child = {k: v for k, v in man.items()
             if k not in ("marks", "flags", "files", "upload", "cut", "started_epoch_ms",
                          "started_at_utc", "bwf_time_reference", "ended_at")}
    with contextlib.suppress(Exception):
        t0 = time.mktime(time.strptime(man["started_at"], "%Y-%m-%dT%H:%M:%S")) + start
        child["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
        child["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 + seg["duration"]))
        child["started_epoch_ms"] = int(t0 * 1000)
        child["started_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))
    child.update({
        "parent": parent_uid, "offset_sec": round(start, 3), "duration_sec": seg["duration"],
        "cut": seg["cut"], "preset": seg["preset"], "preset_name": seg["preset_name"],
        "song": seg["song"], "take_no": seg["take_no"], "title": title_of(seg),
        "sample_rate": sr, "files": files,
        # les marques du PARENT qui tombent dans ce morceau, ramenées à son propre temps
        "marks": [{**m, "sec": round(float(m.get("sec") or 0) - start, 3)}
                  for m in (man.get("marks") or [])
                  if isinstance(m, dict) and start <= float(m.get("sec") or 0) < seg["end"]],
        "flags": [{**f, "sec": round(float(f.get("sec") or 0) - start, 3)}
                  for f in (man.get("flags") or [])
                  if isinstance(f, dict) and start <= float(f.get("sec") or 0) < seg["end"]],
    })
    if anchor is not None:
        child["bwf_time_reference"] = int(anchor)
    return child


def cut(name, bounds=None):
    """Découpe la prise `name` en morceaux. Rend `{ok, uids, skipped, reason?}`.

    `bounds` = la correction venue du web (job `take-recut`) : une liste
    `[{offset_sec, duration_sec}]` qui REMPLACE les frontières dérivées. Le rack re-coupe
    depuis la source — qu'il a gardée exprès.

    Ne touche JAMAIS à la source : les morceaux sont des dossiers frères, et le parent garde
    tout. Idempotent : re-découper efface d'abord les enfants de la passe précédente, donc
    une frontière corrigée ne laisse pas de morceau fantôme derrière elle.
    """
    from . import takes
    path = os.path.join(takes.RECORDINGS, name)
    if not os.path.isdir(path):
        return {"ok": False, "reason": "not_a_folder"}       # un .wav à plat est déjà un morceau
    man = takes._read_json(os.path.join(path, "take.json")) or {}
    dur = duration_of(man, path)
    uid = takes.uid_of(name)

    if bounds:
        segs = []
        for i, b in enumerate(bounds):
            s = float(b.get("offset_sec") or 0)
            d = float(b.get("duration_sec") or 0) or max(0.0, dur - s)
            segs.append({"start": s, "end": s + d, "duration": round(d, 3),
                         "preset": man.get("preset"), "preset_name": man.get("preset_name"),
                         "song": song_of(man.get("preset")), "take_no": i + 1,
                         "cut": {"by": "manual", "at": "web", "confidence": "high"}})
    else:
        segs = segments(man, dur)
        if len(segs) <= 1:
            return {"ok": True, "uids": [], "skipped": [], "reason": "single_song"}

    wavs = sorted(f for f in os.listdir(path) if f.lower().endswith(".wav"))
    if not wavs:
        return {"ok": False, "reason": "no_audio"}
    info = takes.wav_info(os.path.join(path, wavs[0]))
    sr = info.get("sample_rate") or man.get("sample_rate") or 48000
    # ⚠ une ancre à ZÉRO n'est pas une ancre, c'est « minuit » — les prises d'avant le
    # tamponnage BWF (2026-08-02) en portent une. On préfère alors n'en poser AUCUNE sur les
    # morceaux : un fichier sans bext est honnête, un fichier qui dit minuit ment, et golem.fm
    # se cale de toute façon sur `offset_sec` + `parent.started_epoch_ms`.
    base_anchor = info.get("time_reference") or None

    for old in (man.get("cut") or {}).get("children") or []:     # re-découpe : on repart net
        p = os.path.join(takes.RECORDINGS, old)
        if os.path.isdir(p) and p != path:
            for f in os.listdir(p):
                with contextlib.suppress(OSError):
                    os.remove(os.path.join(p, f))
            with contextlib.suppress(OSError):
                os.rmdir(p)

    uids, skipped = [], []
    for i, seg in enumerate(segs, 1):
        if seg["duration"] < MIN_SEC:
            skipped.append({"at": seg["start"], "reason": "too_short"})
            continue
        if is_silent(path, seg["start"], seg["duration"]):
            skipped.append({"at": seg["start"], "reason": "silent"})
            log.info(f"{uid} : segment @{seg['start']:.0f}s muet — pas de morceau")
            continue
        child_uid = f"{uid}-{i:02d}"
        cpath = os.path.join(takes.RECORDINGS, child_uid)
        os.makedirs(cpath, exist_ok=True)
        anchor = (base_anchor + int(seg["start"] * sr)) if base_anchor is not None else None
        files = []
        for w in wavs:
            if _slice(os.path.join(path, w), os.path.join(cpath, w), seg["start"],
                      seg["duration"], anchor):
                files.append(w)
        if not files:
            with contextlib.suppress(OSError):
                os.rmdir(cpath)
            skipped.append({"at": seg["start"], "reason": "cut_failed"})
            continue
        child = _child_manifest(man, seg, uid, files, sr, anchor)
        with open(os.path.join(cpath, "take.json"), "w") as f:
            json.dump(child, f, indent=1, ensure_ascii=False)
        uids.append(child_uid)

    man["cut"] = {"done": True, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "children": uids, "songs": len(uids), "skipped": skipped}
    # ⚠ le parent NE MONTE PLUS : ce sont ses morceaux qui montent. Mais il RESTE sur le
    # disque — la source entière est gardée jusqu'à validation des frontières côté web
    # (§1.4). Une marque mal placée ne doit jamais coûter le morceau.
    man["upload"] = {**(man.get("upload") or {}), "state": "cut",
                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    tmp = os.path.join(path, "take.json.tmp")
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    os.replace(tmp, os.path.join(path, "take.json"))
    log.info(f"{uid} découpée : {len(uids)} morceau(x)"
             + (f", {len(skipped)} segment(s) sauté(s)" if skipped else ""))
    return {"ok": True, "uids": uids, "skipped": skipped}


def release_source(name):
    """Efface les MÉDIAS d'une prise-source dont golem.fm a validé les frontières (job
    `take-source-release`, §1.4). Rend `{ok, freed_bytes, files}`.

    C'est l'autre moitié de « la source reste sur le rack » : sans libération, le disque se
    remplit d'originaux dont plus personne n'a besoin — et le disque est ce qui mord en
    premier (repete-vers-demo.md §4.2 : une répète de 3 h prend les deux tiers de ce qui
    reste). On ne l'efface QUE sur ordre explicite, jamais sur un délai deviné.

    `take.json` SURVIT, avec `source_released`. Un manifeste pèse deux kilo-octets et reste
    la trace de ce qui a été joué : effacer les octets d'une répète est une chose, effacer
    le fait qu'elle a eu lieu en est une autre.
    """
    from . import takes
    path = os.path.join(takes.RECORDINGS, name)
    if not os.path.isdir(path):
        return {"ok": False, "reason": "not_a_folder"}
    man = takes._read_json(os.path.join(path, "take.json")) or {}
    if not (man.get("cut") or {}).get("done"):
        return {"ok": False, "reason": "not_cut"}          # on ne libère que ce qui a des morceaux
    freed, gone = 0, []
    for f in sorted(os.listdir(path)):
        if f.lower().endswith((".wav", ".mid")):
            p = os.path.join(path, f)
            with contextlib.suppress(OSError):
                freed += os.path.getsize(p)
                os.remove(p)
                gone.append(f)
    man["source_released"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "files": gone, "bytes": freed}
    with open(os.path.join(path, "take.json"), "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    log.info(f"{takes.uid_of(name)} : source libérée — {len(gone)} fichier(s), "
             f"{freed // 1048576} Mo rendus au disque")
    return {"ok": True, "freed_bytes": freed, "files": gone}


def pending_cut(row_man, duration=None):
    """La prise attend-elle d'être découpée, et combien de morceaux y a-t-on joué ?
    Calculé À LA LECTURE depuis `marks[]` : aucun état à écrire, donc rien à désynchroniser.
    Rend `(cut_pending, songs_detected)`."""
    if (row_man.get("cut") or {}).get("done"):
        return False, len((row_man.get("cut") or {}).get("children") or [])
    if row_man.get("parent"):
        return False, 0                                   # un morceau ne se re-découpe pas
    n = len(segments(row_man, duration or 0))
    return n > 1, n
