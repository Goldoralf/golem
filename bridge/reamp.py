# SPDX-License-Identifier: GPL-3.0-or-later
"""REAMP — rejouer une DI de prise à travers une lane d'un preset, hors ligne, et monter le son.

Contrat rack : docs/reamp.md (face golem.fm : golemfm conception/message-golem-reamp.md).

Trois morceaux :
  - `busy_reason()` : la règle « libre » (§2). Le rendu PREND le moteur live ; il ne se fait que
    quand personne ne s'en sert — jamais en Gig, jamais pendant qu'on joue ;
  - la FILE DIFFÉRÉE (§3) : un job `reamp` n'entre pas dans la voie « rig » en arrivant (il y
    bloquerait les installs) ; le veilleur l'y verse quand le rack est libre ;
  - `run(job)` (§4-6) : lane, DI, rendu (golem_preview.lua, op render, `tree`), montée.
"""
import contextlib
import hashlib
import os
import re
import threading
import time
import urllib.request
import wave

from . import config as C
from . import activity
from .golog import get

log = get("reamp")

IDLE_S = float(os.environ.get("GOLEM_REAMP_IDLE_S") or 600)   # 10 min sans geste ni signal
CHECK_EVERY = 15.0
CACHE = os.path.join(C.ROOT, "recordings", ".reamp")
CHUNK = 8 * 1024 * 1024
SETTLE_S = 3.0                    # après la pose du preset : le rig se construit, NAM charge
CLONE_SETTLE_S = 2.0              # après le clone (côté Lua) : NAM du clone charge à son tour
AUDIO_EXT = (".wav", ".flac")
_NAME_OK = re.compile(r"[^A-Za-z0-9._ -]")


class Deferred(Exception):
    """Le rack est occupé : ne PAS acquitter, remettre le job dans la file différée."""


# ── §2 la règle « libre » ────────────────────────────────────────────────────────────────────
def busy_reason(idle=True):
    """Pourquoi on ne peut PAS prendre le moteur maintenant — ou None si le rack est libre. `idle=False` : sans la
    règle des 10 min sans geste — pour ce qui ne prend PAS le moteur (la mesure d'une recette de capture tourne
    dans un REAPER séparé, sans carte son : docs/plugin-recipes.md §6)."""
    from .state import state
    mode = state.mode or {}
    if mode.get("id") == "gig":
        return "gig mode"
    if (mode.get("ui") or {}).get("locked"):
        return "mode locked"
    perf = state.perf or {}
    if perf.get("recording") or state.perf_countin:
        return "a take is recording"
    if (state.backing or {}).get("playing") or (state.arrangement or {}).get("running"):
        return "a song is playing"
    if state.rig_loading:
        return "a song is loading"
    with contextlib.suppress(Exception):
        from . import preview
        if preview.status().get("phase") == "render":
            return "a preview is rendering"
    if not idle:
        return None
    idle = activity.idle_s()
    if idle < IDLE_S:
        return f"in use ({activity.last()['src']}, {int(idle)} s ago)"
    return None


# ── §3 la file différée ──────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_queue = []                       # jobs en attente de « libre », ordre d'arrivée
_waker = None
_last_reason = {"why": None}


def enqueue(job):
    from . import tones_jobs as _tj
    with _lock:
        if not any(_tj.job_id(j) == _tj.job_id(job) for j in _queue):
            _queue.append(job)
    start()


def pending():
    with _lock:
        return [{"id": j.get("id"), "reamp": j.get("reamp"), "preset": j.get("preset")} for j in _queue]


def status():
    return {"pending": pending(), "waiting_for": _last_reason["why"], "idle_after_s": IDLE_S}


def _pump():
    """Verse UN job dans la voie « rig » si le rack est libre — un à la fois : le suivant attend que
    le précédent ait rendu la main (sinon deux rendus se suivraient sans que la règle soit relue)."""
    from . import tones_jobs as TJ
    why = busy_reason()
    _last_reason["why"] = why
    if why:
        return
    with _lock:
        if not _queue or _RUNNING.is_set():
            return
        j = _queue.pop(0)
    _RUNNING.set()
    TJ._lane("reamp").put(j)                   # voie « rig » : sérialisé avec les installs et les recalls


_RUNNING = threading.Event()


def start():
    global _waker
    if _waker is not None and _waker.is_alive():
        return

    def loop():
        while True:
            with contextlib.suppress(Exception):
                _pump()
            time.sleep(CHECK_EVERY)
    _waker = threading.Thread(target=loop, daemon=True, name="reamp-waker")
    _waker.start()


def requeue(job):
    from . import tones_jobs as _tj
    """Le handler a levé Deferred : le job revient EN TÊTE (il était le prochain)."""
    with _lock:
        if not any(_tj.job_id(j) == _tj.job_id(job) for j in _queue):
            _queue.insert(0, job)
    _RUNNING.clear()


def finished():
    _RUNNING.clear()


def _check_free(step):
    why = busy_reason()
    if why:
        raise Deferred(f"{why} — reamp paused before {step}")


# ── §4 ce qu'on rend ─────────────────────────────────────────────────────────────────────────
INSTRUMENTAL = ("guitar", "bass", "voice", "line", "drums", "keys", "pads", "keys-pads")


def pick_lane(lanes, preset_lane=None, role=None, nth=None):
    """La lane du preset à travers laquelle rendre — (lane, None) ou (None, raison lisible).
    `preset_lane` d'abord ; sinon même rôle (puis même numéro), sinon la première instrumentale."""
    if preset_lane:
        L = next((x for x in lanes if x.get("id") == preset_lane), None)
        return (L, None) if L else (None, f"lane {preset_lane} is not in this preset")
    cands = [x for x in lanes if not x.get("disabled")]
    if role:
        same = [x for x in cands if (x.get("in_role") or x.get("role")) == role]
        if nth is not None:
            exact = [x for x in same if x.get("in_nth") is not None and int(x["in_nth"]) == int(nth)]
            if exact:
                return exact[0], None
        if same:
            return same[0], None
    first = next((x for x in cands if (x.get("in_role") or x.get("role")) in INSTRUMENTAL), None)
    return (first, None) if first else (None, "no instrument lane in this preset")


def check_lane(L):
    """La lane peut-elle être rendue ICI ? None si oui, sinon la raison (anglais : elle s'affiche)."""
    if L.get("midi"):
        return f"lane {L['id']} is a MIDI lane — reamp renders audio lanes only"
    if L.get("on_card") is False:
        return f"lane {L['id']} is not mounted on this card"
    if L.get("disabled"):
        return f"lane {L['id']} has no input or output"
    return None


def _stem(fn):
    return os.path.splitext(os.path.basename(str(fn or "")))[0]


def take_dir(uid):
    """Le dossier d'une prise chez nous (perf-…), ou None — basename seulement (anti-traversal)."""
    p = os.path.join(C.ROOT, "recordings", os.path.basename(str(uid or "")))
    return p if os.path.isdir(p) else None


def local_di(uid, di_file):
    """La DI de la prise sur notre disque, comparée SANS extension (on écrit du .wav, golem.fm monte
    du .flac : c'est le même fichier). None si absente."""
    d = take_dir(uid)
    want = _stem(di_file)
    if not d or not want:
        return None
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith(AUDIO_EXT) and _stem(fn) == want:
            return os.path.join(d, fn)
    return None


def take_role(uid, di_file):
    """(rôle, numéro) de la lane de la prise, LUS : le nom de la DI porte l'entrée
    (« DI-Sandbox-Input-1 » -> 1), `take.json.roles` porte l'instrument à la prise. None si illisible."""
    d = take_dir(uid)
    m = re.search(r"input-(\d+)", _stem(di_file).lower())
    if not d or not m:
        return None, None
    from .store import _read_json
    man = _read_json(os.path.join(d, "take.json"), {}) or {}
    label = str((man.get("roles") or {}).get(m.group(1)) or "").strip().lower()
    role = {"keys + pads": "keys-pads"}.get(label, label) or None
    return role, None


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def download_di(job):
    """`di.url` -> recordings/.reamp/<id>/<di.file>, reprise par `Range`, sha256 vérifié."""
    from .golemfm import _cfg
    di = job.get("di") or {}
    url = di.get("url")
    if not url:
        return None
    base, token = _cfg()
    if not base or not token:
        raise RuntimeError("not paired with golem.fm — cannot fetch the DI")
    name = _NAME_OK.sub("-", os.path.basename(str(di.get("file") or "di.wav"))) or "di.wav"
    d = os.path.join(CACHE, str(int(job.get("reamp"))))
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, name)
    want = (di.get("sha256") or "").lower()
    if os.path.isfile(dest) and want and _sha(dest) == want:
        return dest
    part = dest + ".part"
    for _attempt in range(4):
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        req = urllib.request.Request(base + url if url.startswith("/") else url)
        req.add_header("Authorization", "Bearer " + token)
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                mode = "ab" if (have and r.status == 206) else "wb"
                with open(part, mode) as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
            break
        except urllib.error.HTTPError as e:
            if e.code == 403:
                raise RuntimeError("golem.fm refused the DI download (band_forbidden)")
            if e.code == 416:                                  # déjà tout reçu
                break
            raise RuntimeError(f"DI download failed: HTTP {e.code}")
        except OSError as e:                                   # coupure réseau : on reprend à l'offset
            log.warning(f"reamp {job.get('reamp')}: download interrupted ({e}), resuming")
            time.sleep(3)
    else:
        raise RuntimeError("DI download failed after 4 attempts")
    if want and _sha(part) != want:
        os.remove(part)
        raise RuntimeError("DI download corrupted (sha256 mismatch)")
    os.replace(part, dest)
    return dest


def find_di(job):
    di = job.get("di") or {}
    p = local_di(job.get("uid"), di.get("file"))
    if p:
        return p
    p = download_di(job)
    if p:
        return p
    raise RuntimeError("di not found")


def wav_info(path):
    """(fréquence, nombre d'échantillons, canaux) d'un .wav — FLAC : via ffprobe."""
    if path.lower().endswith(".wav"):
        with contextlib.closing(wave.open(path, "rb")) as w:
            return w.getframerate(), w.getnframes(), w.getnchannels()
    import json as _json
    import subprocess
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                                   "stream=sample_rate,channels,duration_ts", "-of", "json", path], timeout=30)
    s = (_json.loads(out).get("streams") or [{}])[0]
    return int(s.get("sample_rate") or 0), int(s.get("duration_ts") or 0), int(s.get("channels") or 0)


def fit_length(path, frames):
    """Coupe (queue) ou complète (silence) le rendu à `frames` échantillons exacts : la piste doit se
    superposer aux autres lanes de la prise, pas les déborder d'un bloc de rendu."""
    with contextlib.closing(wave.open(path, "rb")) as w:
        params = w.getparams()
        have = w.getnframes()
        if have == frames:
            return 0
        data = w.readframes(min(have, frames))
    width = params.sampwidth * params.nchannels
    if have < frames:
        data += b"\x00" * ((frames - have) * width)
    tmp = path + ".fit"
    with contextlib.closing(wave.open(tmp, "wb")) as o:
        o.setparams(params)
        o.writeframes(data)
    os.replace(tmp, path)
    return frames - have


# ── §5 le rendu ──────────────────────────────────────────────────────────────────────────────
_seq = iter(range(1, 1 << 30))


def _poll(key, timeout):
    """presets/.preview.json {scene:key, done} -> (wav, None) | (None, erreur)."""
    from .store import _read_json
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = _read_json(C.PREVIEW_FILE, None)
        if d and d.get("scene") == key and d.get("done"):
            return (None, d["error"]) if d.get("error") else (d.get("wav"), None)
        time.sleep(0.5)
    return None, f"Reaper did not finish the render in {int(timeout)} s"


def render(pid, scene, lane, di_path, out_path, key):
    """Pose preset+scène sur le moteur, rend la lane ENTIÈRE hors ligne, remet le moteur d'avant."""
    from . import preview
    from .commands import write_command
    from .state import state
    if preview._apply_scene is None or preview._restore_live is None:
        raise RuntimeError("scene engine unavailable")
    sr, frames, _ch = wav_info(di_path)
    dur = frames / float(sr or 48000)
    if not preview._gen_lock.acquire(blocking=False):
        raise Deferred("a preview is rendering")
    try:
        preview._apply_scene(pid, scene)
        t0 = time.time()
        time.sleep(SETTLE_S)
        while state.rig_loading and time.time() - t0 < 20:
            time.sleep(0.3)
        with contextlib.suppress(OSError):
            os.remove(C.PREVIEW_FILE)
        write_command({"action": "preview", "seq": next(_seq), "op": "render", "scene": key,
                       "di": di_path, "out": out_path, "tail": 0, "tree": True, "sr": sr,
                       "settle": CLONE_SETTLE_S, "chain": f"Sandbox #Input {lane['input']}",
                       "_route": "preview"})
        wav, err = _poll(key, max(150.0, 3 * dur + 60))
    finally:
        with contextlib.suppress(Exception):
            preview._restore_live()
        preview._gen_lock.release()
    if err or not wav or not os.path.isfile(wav):
        raise RuntimeError(f"render failed: {err or 'no file'}")
    rsr, rframes, _ = wav_info(wav)
    if rsr != sr:
        raise RuntimeError(f"render came out at {rsr} Hz, the DI is {sr} Hz")
    fit_length(wav, frames)
    return wav


# ── §6 le retour ─────────────────────────────────────────────────────────────────────────────
def upload(job, path):
    from . import golemfm
    base, token = golemfm._cfg()
    res = job.get("result") or {}
    rid = int(job.get("reamp"))
    declare = res.get("declare") or f"/api/ext/recordings/reamps/{rid}/result"
    complete = res.get("complete") or f"/api/ext/recordings/reamps/{rid}/complete"
    size, sha = os.path.getsize(path), _sha(path)
    st, d = golemfm._req(declare, token=token,
                           body={"filename": os.path.basename(path), "sha256": sha, "size_bytes": size})
    if st == 413:
        raise RuntimeError("quota — the band's storage is full")
    if st != 200 or not isinstance(d, dict) or not d.get("upload"):
        raise RuntimeError(f"result declare refused ({st}): {str(d)[:160]}")
    track = d.get("track") or {}
    off = int(track.get("received") or 0)
    if not track.get("done"):
        with open(path, "rb") as f:
            f.seek(off)
            while off < size:
                _check_free("upload")
                buf = f.read(CHUNK)
                if not buf:
                    break
                st, r = golemfm.put_bytes(f"{d['upload']}?offset={off}", buf, token=token)
                if st == 409 and isinstance(r, str) and "expected offset" in r:
                    off = int(re.search(r"(\d+)", r.split("offset")[-1]).group(1))
                    f.seek(off)
                    continue
                if st != 200:
                    raise RuntimeError(f"upload refused ({st}): {str(r)[:160]}")
                off += len(buf)
    st, r = golemfm._req(complete, token=token, body={})
    if st != 200:
        raise RuntimeError(f"complete refused ({st}): {str(r)[:160]}")
    return {"filename": os.path.basename(path), "sha256": sha, "size_bytes": size,
            "track": track.get("idx"), "recording": d.get("recording")}


def remote_status(rid):
    from . import golemfm
    st, d = golemfm._req(f"/api/ext/recordings/reamps/{int(rid)}", token=golemfm._cfg()[1])
    return (d or {}).get("status") if st == 200 and isinstance(d, dict) else None


def run(job):
    """Le handler du job `reamp` (voie « rig », versé par le veilleur quand le rack est libre)."""
    from .store import load_preset, lanes_of
    rid = job.get("reamp")
    if rid is None:
        raise RuntimeError("reamp id missing")
    st = remote_status(rid)
    if st in ("done", "failed"):
        return {"_log": f"reamp {rid} already {st} on golem.fm", "status": st}
    _check_free("start")
    pid = job.get("preset")
    preset = load_preset(pid) if pid else None
    if not preset:
        raise RuntimeError(f"preset {pid} is not on this rack")
    scenes = [s.get("id") for s in preset.get("scenes") or [] if s.get("id")]
    scene = job.get("scene") or (scenes[0] if scenes else None)
    if not scene or scene not in scenes:
        raise RuntimeError(f"scene {job.get('scene')} is not in preset {pid}")
    role, nth = job.get("role"), None
    if not role and not job.get("preset_lane"):
        role, nth = take_role(job.get("uid"), (job.get("di") or {}).get("file"))
    lane, why = pick_lane(lanes_of(preset), job.get("preset_lane"), role, nth)
    if why:
        raise RuntimeError(why)
    why = check_lane(lane)
    if why:
        raise RuntimeError(why)
    di = find_di(job)
    _check_free("render")
    out_dir = os.path.join(CACHE, str(int(rid)))
    os.makedirs(out_dir, exist_ok=True)
    name = _NAME_OK.sub("-", f"{_stem(di)}.reamp{int(rid)}") + ".wav"
    wav = render(pid, scene, lane, di, os.path.join(out_dir, name), key=f"reamp-{int(rid)}")
    info = upload(job, wav)
    with contextlib.suppress(OSError):
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
    return {"_log": f"reamp {rid}: {pid}·{scene} lane {lane['id']} -> {info['filename']}",
            "preset": pid, "scene": scene, "lane": lane["id"], **info}
