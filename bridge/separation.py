# SPDX-License-Identifier: GPL-3.0-or-later
"""Séparation de sources sur le golem — moteur agnostique (docs/separation.md, FIGÉ le 2026-10-12).

Le golem est livré VIDE. Deux origines de moteur : la liste de golem.fm (§2.1) et les moteurs que l'utilisateur
ajoute lui-même (§2.2) ; deux portes : un fichier ONNX (§3, exécuté par `separation_run` en processus séparé) et un
programme (§4, lancé sans shell). Un seul chemin pour tous : rien ici ne connaît un moteur par son nom.

Trois règles qui ne se relâchent pas (§1) :
- les journaux disent « listed engine » / « custom engine », jamais un nom, un chemin, une commande, une licence ;
  la sortie d'un moteur va dans presets/.separation/engine.log, que bridge/diag.py ne lit pas ;
- config/separation.json reste hors git et hors sauvegardes (backup.SETTINGS_FILES ne le liste pas) ;
- vers golem.fm : des codes neutres (§8.4) et `caps.separation` = {stems, rtf} — rien d'autre.

La nature se LIT (§6) : un moteur n'est activable qu'après un test qui lit ses sorties ; ce que la liste ou
l'utilisateur DÉCLARE est affiché, jamais utilisé pour décider."""
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import config as C
from .golog import get

log = get("separation")

CFG_PATH = os.path.join(C.CONFIG_DIR, "separation.json")
ENG_DIR = os.path.join(C.ROOT, "assets", "separation")
WORK_DIR = os.path.join(C.PRESETS_DIR, ".separation")
ENGINE_LOG = os.path.join(WORK_DIR, "engine.log")
# §6 (2026-10-12) : l'extrait de test est un fichier de l'UTILISATEUR, choisi sur sa machine — il n'en sort pas
# (presets/.separation : gitignoré, hors sauvegardes, hors diagnostics). Pas d'extrait livré pour l'instant.
EXCERPT_BASE = os.path.join(WORK_DIR, "excerpt")
EXCERPT_S = 30                  # la durée testée, prise dans le fichier
EXCERPT_MAX_BYTES = 300 << 20
AUDIO_EXTS = (".wav", ".flac", ".mp3", ".ogg", ".m4a", ".aac", ".aif", ".aiff", ".opus")
SR = 44100
STEM_RX = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
RESERVED = {"files", "mix", "slug", "dir", "ticks", "op", "seq", "action", "stem", "mute", "vol"}   # golemfm._RESERVED_STEM_NAMES
MAX_STEMS = 16
SILENT_DB = -60.0             # §6 : un stem sous ce RMS est « silencieux »
CORR_MAX = 0.98               # §6 : ≈ mix, ou deux stems identiques
RESIDUAL_MAX_DB = -10.0       # §6 : ‖Σ stems − mix‖² / ‖mix‖²
PROGRAM_SLACK_S = 0.05        # §6 : ± 50 ms pour un programme
MAX_ONNX_BYTES = 4 << 30
ERROR_CODES = ("engine_changed", "no_engine", "engine_failed", "source_unreadable", "upload_failed", "cancelled")

_lock = threading.RLock()
_TEST = {"id": None, "phase": None, "progress": None, "error": None}   # le test en cours (un à la fois)


class SeparationError(Exception):
    """Une raison LISIBLE (anglais : elle s'affiche), et un code neutre pour golem.fm (§8.4)."""
    def __init__(self, why, code="engine_failed"):
        super().__init__(why)
        self.code = code


# ── la configuration ──────────────────────────────────────────────────────────────────────────
def _default_threads():
    n = os.cpu_count() or 2
    return max(1, min(4, n // 2))     # §5 : un nombre FIXÉ — 8 fils vont plus lentement que 4 sur un hybride (annexe A.4)


def load():
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("engines", [])
    d.setdefault("active", None)
    d.setdefault("threads", None)
    d.setdefault("rtf", {})
    # les services payants en ligne sont retirés de la v0.6 (docs/private/launch-plan.md §3, 2026-10-31) : un moteur de ce
    # genre resté dans une config d'avant n'est plus montré ni utilisé — il disparaît à la prochaine écriture
    if any(e.get("kind") == "service" for e in d["engines"]):
        d["engines"] = [e for e in d["engines"] if e.get("kind") != "service"]
        if d["active"] and not _engine(d, d["active"]):
            d["active"] = None
    return d


def _save(d):
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    tmp = CFG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, CFG_PATH)


def threads():
    t = load().get("threads")
    return int(t) if t else _default_threads()


def _engine(d, eid):
    return next((e for e in d["engines"] if e["id"] == eid), None)


def _origin_word(e):
    return "listed engine" if e.get("origin") == "listed" else "custom engine"


# ── l'audio (ffmpeg, une fois pour tous les moteurs) ─────────────────────────────────────────
def _ffmpeg(args, what):
    code = "source_unreadable" if what == "decoding" else "engine_failed"
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y"] + args, capture_output=True, timeout=1800)
    except FileNotFoundError:
        # ffmpeg absent (Windows, macOS : §11) : une erreur dite, pas un 500 qui laisse ses fichiers temporaires
        raise SeparationError("%s needs ffmpeg, which is not installed" % what, code) from None
    except subprocess.TimeoutExpired:
        raise SeparationError("%s took too long" % what, code) from None
    if r.returncode != 0:
        raise SeparationError("%s failed" % what, code)


def decode(src, dst):
    """N'importe quel fichier audio → PCM float32 stéréo 44,1 kHz entrelacé, SANS métadonnées. Rend n (par canal)."""
    _ffmpeg(["-i", src, "-map_metadata", "-1", "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", dst], "decoding")
    n = os.path.getsize(dst) // 8
    if n < SR // 10:
        raise SeparationError("the audio is too short or unreadable", "source_unreadable")
    return n


def _pcm_args(src):
    return ["-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", src]


def write_wav16(f32, dst):
    _ffmpeg(_pcm_args(f32) + ["-c:a", "pcm_s16le", dst], "WAV writing")


def encode_mp3(f32, dst):
    """§8.4 : mp3 192 kb/s CBR (le format des stems de golem.fm)."""
    _ffmpeg(_pcm_args(f32) + ["-map_metadata", "-1", "-c:a", "libmp3lame", "-b:a", "192k", dst], "mp3 encoding")


# ── lancer un processus : sans shell, priorité basse, tué en ARBRE ───────────────────────────
def _spawn(argv, cwd, env=None, log_to=None):
    kw = {"cwd": cwd, "stdin": subprocess.DEVNULL, "env": env}
    out = open(log_to, "ab") if log_to else subprocess.DEVNULL
    kw["stdout"], kw["stderr"] = out, subprocess.STDOUT if log_to else subprocess.DEVNULL
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00004000   # BELOW_NORMAL_PRIORITY_CLASS
    else:
        kw["start_new_session"] = True
        kw["preexec_fn"] = lambda: os.nice(19)
    p = subprocess.Popen(argv, **kw)
    if log_to:
        out.close()
    return p


def _kill_tree(p):
    if p.poll() is not None:
        return
    with contextlib.suppress(Exception):
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, timeout=15)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    with contextlib.suppress(Exception):
        p.wait(timeout=10)


class Stopped(Exception):
    """Le rack est redevenu occupé (ou l'utilisateur annule) : le processus est tué, le travail fait est gardé."""


def _wait(p, stop, timeout, progress=None):
    t0 = time.monotonic()
    while p.poll() is None:
        why = stop() if stop else None
        if why:
            _kill_tree(p)
            raise Stopped(why if isinstance(why, str) else "stopped")
        if timeout and time.monotonic() - t0 > timeout:
            _kill_tree(p)
            raise SeparationError("the engine took too long and was stopped")
        if progress:
            progress()
        time.sleep(0.5)
    return p.returncode


def _engine_log_header(e):
    os.makedirs(WORK_DIR, exist_ok=True)
    with open(ENGINE_LOG, "a", encoding="utf-8") as f:
        f.write("\n── %s · %s ──\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), _origin_word(e)))
    with contextlib.suppress(OSError):                     # le journal d'un moteur ne grossit pas sans fin
        if os.path.getsize(ENGINE_LOG) > 2 << 20:
            with open(ENGINE_LOG, "rb") as f:
                f.seek(-(1 << 20), 2)
                tail = f.read()
            with open(ENGINE_LOG, "wb") as f:
                f.write(tail)


# ── les deux portes ───────────────────────────────────────────────────────────────────────────
def _runner_argv(*a):
    return [sys.executable, "-m", "bridge.separation_run", *a]


def inspect_onnx(path):
    """Ce que le fichier dit de lui, lu dans un processus à part (un fichier hostile ne fait pas tomber le bridge)."""
    r = subprocess.run(_runner_argv("inspect", path), cwd=C.ROOT, capture_output=True, timeout=300)
    if r.returncode != 0:
        raise SeparationError("this file could not be read as an ONNX model")
    from .separation_run import ContractError, check_contract
    d = json.loads(r.stdout)
    try:
        sr, seg, ov, names = check_contract(d)
    except ContractError as ex:
        raise SeparationError(str(ex))
    return {"sample_rate": sr, "segment": seg, "overlap": ov, "outputs": names,
            "name": d["meta"].get("golem.name") or "", "licence": d["meta"].get("golem.licence") or ""}


def _onnx_file(e):
    return os.path.join(ENG_DIR, e["id"], "model.onnx")


def _run_onnx(e, f32, n, workdir, outdir, stop, progress):
    spec = {"model": _onnx_file(e), "input": f32, "n": n, "outdir": outdir, "workdir": workdir,
            "threads": threads(), "sample_rate": SR}
    os.makedirs(workdir, exist_ok=True)
    sp = os.path.join(workdir, "spec.json")
    with open(sp, "w") as f:
        json.dump(spec, f)
    _engine_log_header(e)
    p = _spawn(_runner_argv("run", sp), C.ROOT, log_to=ENGINE_LOG)

    def prog():
        if progress:
            with contextlib.suppress(Exception):
                with open(os.path.join(workdir, "progress.json")) as f:
                    progress(json.load(f))
    rc = _wait(p, stop, max(600, 10 * n / SR), prog)
    if rc != 0:
        why = "the engine failed"
        with contextlib.suppress(Exception):
            with open(os.path.join(outdir, "error.json")) as f:
                why = json.load(f)["why"]
        raise SeparationError(why)
    with open(os.path.join(outdir, "result.json")) as f:
        res = json.load(f)
    return {s: os.path.join(outdir, s + ".f32") for s in res["stems"]}, res["compute_s"], res["load_s"]


def check_program(program, args):
    """§4 : un exécutable direct, {input} et {outdir} chacun UNE fois, en argument entier."""
    if not program or not os.path.isfile(program):
        raise SeparationError("program not found")
    if os.name == "nt" and os.path.splitext(program)[1].lower() in (".bat", ".cmd"):
        raise SeparationError(".bat and .cmd files are not accepted — choose an executable")
    if os.name != "nt" and not os.access(program, os.X_OK):
        raise SeparationError("this file is not executable")
    args = [str(a) for a in (args or [])]
    for tok in ("{input}", "{outdir}"):
        if args.count(tok) != 1:
            raise SeparationError("%s must appear exactly once, as a whole argument" % tok)
        if any(tok in a and a != tok for a in args):
            raise SeparationError("%s must be a whole argument, not part of one" % tok)
    return args


def _min_env():
    keep = ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL")
    return {k: os.environ[k] for k in keep if k in os.environ}


class ProgramFailed(SeparationError):
    """L'échec d'un programme, avec ce qui aide à le réparer — montré sur CE golem seulement (jamais journalisé dans le
    bridge, jamais envoyé) : les dernières lignes de sa sortie et les fichiers qu'il a écrits."""
    def __init__(self, why, log_tail="", files=()):
        super().__init__(why)
        self.log_tail, self.files = log_tail, list(files)


def _log_tail(offset, lines=20):
    try:
        with open(ENGINE_LOG, "rb") as f:
            f.seek(offset)
            txt = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(txt.strip().splitlines()[-lines:])


def _wavs(root):
    """Tous les WAV écrits par un programme, SOUS-DOSSIERS compris, en chemins relatifs « / »."""
    out = []
    for r, _ds, fs in os.walk(root):
        for f in fs:
            if f.lower().endswith(".wav"):
                out.append(os.path.relpath(os.path.join(r, f), root).replace(os.sep, "/"))
    return sorted(out)


def _exec_program(program, args, f32, n, stop, tmp):
    """Lance le programme sur le PCM : rend (dossier de sortie, WAV écrits, durée, fin du journal). Lève ProgramFailed."""
    args = check_program(program, args)
    wav = os.path.join(tmp, "input.wav")                 # toujours « input.wav » : les noms que l'outil en tire sont STABLES
    write_wav16(f32, wav)
    od = os.path.join(tmp, "out")
    os.makedirs(od)
    argv = [program] + [wav if a == "{input}" else od if a == "{outdir}" else a for a in args]
    try:
        off = os.path.getsize(ENGINE_LOG)
    except OSError:
        off = 0
    t0 = time.monotonic()
    try:
        p = _spawn(argv, tmp, env=_min_env(), log_to=ENGINE_LOG)
    except OSError:
        raise ProgramFailed("the program could not be started (not executable, or blocked by the system?)")
    rc = _wait(p, stop, max(120, 4 * n / SR))
    took = time.monotonic() - t0
    files = _wavs(od)
    if rc != 0:
        raise ProgramFailed("the program exited with code %d" % rc, _log_tail(off), files)
    if not files:
        raise ProgramFailed("the program wrote no WAV file into {outdir}", _log_tail(off), files)
    return od, files, took, _log_tail(off)


def _run_program(e, f32, n, workdir, outdir, stop):
    """§4 : la porte programme. Les sorties se LISENT : soit l'association fichier → stem retenue à l'ajout (`map`,
    chemins relatifs, sous-dossiers compris), soit des WAV nommés par leur stem à la racine de {outdir}."""
    tmp = tempfile.mkdtemp(prefix="golem-sep-")
    try:
        _engine_log_header(e)
        od, files, took, tail = _exec_program(e.get("program"), e.get("args"), f32, n, stop, tmp)
        m = e.get("map") or {}
        if m:
            missing = [rel for rel in m if rel not in files]
            if missing:
                raise ProgramFailed("the program did not write %s (it wrote: %s)" % (missing[0], ", ".join(files[:6])), tail, files)
            pick = {stem: rel for rel, stem in m.items() if stem}
        else:
            pick = {rel[:-4]: rel for rel in files if "/" not in rel}
            bad = [r for r in files if "/" in r or not STEM_RX.match(r[:-4])]
            if not pick or (bad and not any(STEM_RX.match(k) for k in pick)):
                raise ProgramFailed("the files are not named after stems — match each file to a stem", tail, files)
        os.makedirs(outdir, exist_ok=True)
        out = {}
        for name, rel in pick.items():
            dst = os.path.join(outdir, name + ".f32")
            _ffmpeg(["-i", os.path.join(od, rel), "-ac", "2", "-ar", str(SR), "-f", "f32le", dst], "reading a stem")
            out[name] = dst
        return out, took, 0.0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def probe_program(program, args):
    """L'ESSAI À BLANC (aide à la configuration, avis de l'avocat du 2026-10-12 : rien n'est nommé, tout est lu) : le
    programme tourne sur 10 s de l'extrait, et le golem rend les WAV qu'il a écrits — l'utilisateur associe chaque
    fichier à un stem. Rien n'est enregistré. Rend {files, took, log_tail} ou {error, log_tail, files}."""
    program = (program or "").strip()
    why = _busy(idle=False)
    if why:
        raise SeparationError("golem is busy (%s) — try again later" % why)
    if not excerpt_path():
        raise SeparationError("choose a test excerpt first")
    tmp = tempfile.mkdtemp(prefix="golem-sep-probe-")
    try:
        full = os.path.join(tmp, "x.f32")
        n = _excerpt_pcm(full)
        short = min(n, 10 * SR)
        with open(full, "rb") as f:
            blob = f.read(short * 8)
        with open(full, "wb") as f:
            f.write(blob)
        _engine_log_header({"kind": "program", "origin": "custom"})
        try:
            _od, files, took, tail = _exec_program(program, args, full, short, None, tmp)
        except ProgramFailed as ex:
            return {"ok": False, "error": str(ex), "log_tail": ex.log_tail, "files": ex.files,
                    "hints": hints(str(ex), ex.log_tail, ex.files)}
        return {"ok": True, "files": files, "took": round(took, 1), "log_tail": tail, "guess": guess_stems(files)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_STEM_WORDS = (("instrumental", "other"), ("no_vocals", "other"), ("accompan", "other"), ("vocal", "vocals"),
               ("voice", "vocals"), ("drum", "drums"), ("bass", "bass"), ("guitar", "guitar"), ("piano", "piano"),
               ("keys", "keys"), ("string", "strings"), ("wind", "wind"), ("other", "other"))


def _tokens(rel):
    return [t for t in re.split(r"[^a-z0-9]+", rel.lower().rsplit("/", 1)[-1][:-4]) if t]


def guess_stems(files):
    """Une PROPOSITION de stem par fichier, confirmée par l'utilisateur. Ce que TOUS les fichiers ont en commun (`input`,
    le nom du modèle…) ne dit rien : seul ce qui les DISTINGUE compte — vécu le 2026-10-13, un outil nommait ses sorties
    `input_(other)_<modèle>.wav` et `input_(vocals)_<modèle>.wav`, et le nom de son modèle contenait « vocals » : il le
    disait aux deux.
    Jamais deux fichiers proposés pour le même stem."""
    toks = {f: _tokens(f) for f in files}
    common = set.intersection(*(set(t) for t in toks.values())) if len(files) > 1 else set()
    out, used = {}, set()
    for f in files:
        distinct = " ".join(t for t in toks[f] if t not in common)
        g = _guess_stem(distinct + ".wav") if distinct else _guess_stem(f)
        out[f] = g if g and g not in used else ""
        if out[f]:
            used.add(out[f])
    return out


def _guess_stem(rel):
    """Une PROPOSITION de stem d'après le nom du fichier (`…(Vocals)….wav` → vocals) — l'utilisateur la confirme."""
    low = rel.lower().rsplit("/", 1)[-1]
    for word, stem in _STEM_WORDS:
        if word in low:
            return stem
    return ""


def _sum_f32(paths, dst, n):
    """La somme de plusieurs PCM (même longueur n) dans `dst`, par morceaux — jamais tout en mémoire."""
    import numpy as np
    maps = [np.memmap(p, dtype=np.float32, mode="r", shape=(2 * n,)) for p in paths]
    with open(dst, "wb") as f:
        step = 1 << 20
        for a in range(0, 2 * n, step):
            b = min(2 * n, a + step)
            acc = np.zeros(b - a, np.float32)
            for m in maps:
                acc += m[a:b]
            f.write(acc.tobytes())
    return dst


def _run_combined(e, f32, n, workdir, outdir, stop, progress):
    """« Combine » (2026-10-12 — mockups/separation-combine.html) : deux moteurs DÉJÀ ajoutés, enchaînés par golem.
    Passe 1 : le premier moteur ; on GARDE ses stems choisis (`keep`). Le reste (la somme des autres) est l'entrée de la
    passe 2. Un stem que le second sort ET qu'on a déjà gardé (la voix résiduelle) rejoint « other » : la somme des stems
    reste le morceau. Générique : golem ne sait rien des deux moteurs, il lit leurs sorties."""
    d = load()
    e1, e2 = _engine(d, e.get("first")), _engine(d, e.get("second"))
    if not e1 or not e2:
        raise SeparationError("an engine this combination uses was removed")
    keep = list(e.get("keep") or [])
    def prog(k):
        return (lambda p: progress({**p, "pass": k}) if progress else None)
    s1, t1, l1 = separate(e1, f32, n, os.path.join(workdir, "p1"), os.path.join(outdir, "p1"), stop, prog(1))
    _fit(e1, s1, n)
    if any(k not in s1 for k in keep):
        raise SeparationError("the first engine no longer gives %s" % ", ".join(k for k in keep if k not in s1))
    rest = [p for k, p in s1.items() if k not in keep]
    if not rest:
        raise SeparationError("nothing is left for the second engine — keep fewer stems from the first")
    rest_f32 = _sum_f32(rest, os.path.join(outdir, "rest.f32"), n)
    s2, t2, l2 = separate(e2, rest_f32, n, os.path.join(workdir, "p2"), os.path.join(outdir, "p2"), stop, prog(2))
    _fit(e2, s2, n)
    out = {k: s1[k] for k in keep}
    residue = [p for k, p in s2.items() if k in out]
    for k, p in s2.items():
        if k not in out:
            out[k] = p
    if residue:                                          # la voix laissée dans le reste : dans « other », jamais perdue
        base = [out["other"]] if "other" in out else []
        out["other"] = _sum_f32(base + residue, os.path.join(outdir, "other.f32"), n)
    return out, t1 + t2, l1 + l2


def separate(e, f32, n, workdir, outdir, stop=None, progress=None):
    """Le chemin UNIQUE (§1.1) : un moteur, un PCM d'entrée → {stem: chemin .f32}, temps de calcul, temps de chargement."""
    if e.get("kind") == "onnx":
        return _run_onnx(e, f32, n, workdir, outdir, stop, progress)
    if e.get("kind") == "program":
        return _run_program(e, f32, n, workdir, outdir, stop)
    if e.get("kind") == "combined":
        return _run_combined(e, f32, n, workdir, outdir, stop, progress)
    raise SeparationError("unknown engine kind")


# ── la lecture des sorties (§6, §8.4) ─────────────────────────────────────────────────────────
def check_names(names):
    if not names:
        raise SeparationError("the engine produced no stem")
    if len(names) > MAX_STEMS:
        raise SeparationError("more than %d stems" % MAX_STEMS)
    if len(set(names)) != len(names):
        raise SeparationError("two stems have the same name")
    for s in names:
        if not STEM_RX.match(s) or s in RESERVED:
            raise SeparationError("stem name not accepted: %s" % s[:40])


def analyse(stems, mix_f32, n, slack=0):
    """Lit les stems sans tout charger en mémoire. Rend {stems, silent, residual_db, corr_mix, corr_pairs, finite,
    durations_ok}. Une durée hors tolérance ou un NaN lève ; le reste se juge ensuite (test ou vrai morceau)."""
    import numpy as np
    names = list(stems)
    check_names(names)
    maps = {}
    for s, p in stems.items():
        k = os.path.getsize(p) // 8
        if abs(k - n) > slack:
            raise SeparationError("stem %s does not have the length of the input" % s)
        maps[s] = np.memmap(p, dtype=np.float32, mode="r", shape=(k * 2,))
    mix = np.memmap(mix_f32, dtype=np.float32, mode="r", shape=(n * 2,))
    m = len(names)
    e = np.zeros(m)
    dmix = np.zeros(m)
    pairs = np.zeros((m, m))
    emix = 0.0
    eres = 0.0
    step = 1 << 20
    total = 2 * n
    for a in range(0, total, step):
        b = min(total, a + step)
        x = mix[a:b].astype(np.float64)
        blk = np.zeros((m, b - a))
        for i, s in enumerate(names):
            v = maps[s][a:min(b, maps[s].shape[0])].astype(np.float64)
            blk[i, :v.shape[0]] = v
        if not np.isfinite(blk).all():
            raise SeparationError("the engine returned NaN or Inf")
        e += (blk ** 2).sum(1)
        dmix += blk @ x
        pairs += blk @ blk.T
        emix += float(x @ x)
        r = blk.sum(0) - x
        eres += float(r @ r)
    rms_db = 10 * np.log10(np.maximum(e / max(1, total), 1e-20))
    silent = [s for i, s in enumerate(names) if rms_db[i] < SILENT_DB]
    def corr(num, a, b):
        return float(num / np.sqrt(max(a * b, 1e-30)))
    corr_mix = {s: corr(dmix[i], e[i], emix) for i, s in enumerate(names)}
    corr_pairs = {}
    for i in range(m):
        for j in range(i + 1, m):
            if names[i] not in silent and names[j] not in silent:
                corr_pairs["%s/%s" % (names[i], names[j])] = corr(pairs[i, j], e[i], e[j])
    residual = 10 * np.log10(max(eres, 1e-30) / max(emix, 1e-30)) if emix > 0 else None
    return {"stems": names, "silent": silent, "rms_db": {s: round(float(rms_db[i]), 1) for i, s in enumerate(names)},
            "residual_db": None if residual is None else round(float(residual), 1),
            "corr_mix": {k: round(v, 3) for k, v in corr_mix.items()},
            "corr_pairs": {k: round(v, 3) for k, v in corr_pairs.items()}}


def judge_test(a):
    """Les seuils du §6, sur l'extrait. Rend la raison d'un refus, ou None."""
    # « porte du son » : au-dessus de −60 dBFS ET à moins de 40 dB du stem le plus fort — un résidu de filtre sur un
    # extrait d'un seul instrument n'est pas un second instrument
    top = max(a["rms_db"].values()) if a["rms_db"] else SILENT_DB
    loud = [s for s in a["stems"] if s not in a["silent"] and a["rms_db"][s] > top - 40]
    if len(loud) < 2:
        # un extrait pris au hasard peut ne porter qu'un instrument : c'est l'EXTRAIT qu'on met en cause, pas le moteur
        return "fewer than 2 stems carry sound — choose an excerpt with several instruments"
    for s in loud:
        if a["corr_mix"][s] > CORR_MAX:
            return "stem %s is the mix itself — if your excerpt has a single instrument, choose one with several" % s
    for k, v in a["corr_pairs"].items():
        if v > CORR_MAX:
            return "stems %s are identical" % k.replace("/", " and ")
    if a["residual_db"] is None or a["residual_db"] > RESIDUAL_MAX_DB:
        return "the stems do not add up to the mix (%s dB)" % a["residual_db"]
    return None


def _fit(e, stems, n):
    """Programme : ± 50 ms tolérés (§6), puis tout à la longueur exacte de l'entrée. ONNX : exact, rien à faire."""
    import numpy as np
    if e.get("kind") != "program":
        return
    slack = int(PROGRAM_SLACK_S * SR)
    for s, p in stems.items():
        if abs(os.path.getsize(p) // 8 - n) > slack:
            raise SeparationError("stem %s does not have the length of the input" % s[:40])
    for p in stems.values():
        k = os.path.getsize(p) // 8
        if k == n:
            continue
        x = np.fromfile(p, dtype=np.float32)
        y = np.zeros(2 * n, np.float32)
        y[:min(2 * n, x.size)] = x[:2 * n]
        y.tofile(p)


# ── le test d'un moteur (§6) ─────────────────────────────────────────────────────────────────
def _busy(idle):
    from .reamp import busy_reason
    return busy_reason(idle=idle)


def test(eid, wait=False):
    """Lance le test (un à la fois). L'extrait PUIS 30 s de silence. Refus si le rack est occupé (pas en Gig, pas de
    prise, rien en lecture) — mais sans exiger 10 min sans geste : le test vient d'un geste."""
    with _lock:
        d = load()
        e = _engine(d, eid)
        if not e:
            raise SeparationError("unknown engine")
        if _TEST["id"]:
            raise SeparationError("a test is already running")
        why = _busy(idle=False)
        if why:
            raise SeparationError("golem is busy (%s) — try again later" % why)
        if not excerpt_path():
            raise SeparationError("choose a test excerpt first — a recording of yours with several instruments")
        _TEST.update(id=eid, phase="starting", progress=None, error=None)
    t = threading.Thread(target=_test_run, args=(eid,), daemon=True, name="separation-test")
    t.start()
    if wait:
        t.join()
    return {"ok": True}


def excerpt_path():
    for x in AUDIO_EXTS:
        if os.path.isfile(EXCERPT_BASE + x):
            return EXCERPT_BASE + x
    return None


def _meta_path():
    return EXCERPT_BASE + ".json"


def excerpt_info():
    p = excerpt_path()
    if not p:
        return None
    try:
        with open(_meta_path(), encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    return {"name": m.get("name") or os.path.basename(p), "seconds": m.get("seconds"), "start": m.get("start")}


def set_excerpt(blob, name):
    """L'utilisateur choisit un fichier : il est lu (décodable, assez long), puis gardé ICI pour les tests suivants.
    Rien ne part vers golem.fm ; le nom n'est jamais journalisé."""
    ext = os.path.splitext(name or "")[1].lower()
    if ext not in AUDIO_EXTS:
        raise SeparationError("choose an audio file (WAV, FLAC, MP3…)")
    if not blob or len(blob) > EXCERPT_MAX_BYTES:
        raise SeparationError("this file is empty or too large")
    os.makedirs(WORK_DIR, exist_ok=True)
    tmp = EXCERPT_BASE + ".new" + ext
    with open(tmp, "wb") as f:
        f.write(blob)
    work = tempfile.mkdtemp(prefix="golem-sep-x-")
    try:
        n = decode(tmp, os.path.join(work, "x.f32"))
    except SeparationError:
        os.unlink(tmp)
        raise SeparationError("this file could not be read as audio")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if n < 10 * SR:
        os.unlink(tmp)
        raise SeparationError("this recording is too short — at least 10 seconds")
    clear_excerpt()
    os.replace(tmp, EXCERPT_BASE + ext)
    start = _window(n)[0]
    with open(_meta_path(), "w", encoding="utf-8") as f:
        json.dump({"name": os.path.basename(name)[:120], "seconds": round(min(n, EXCERPT_S * SR) / SR, 1),
                   "start": round(start / SR, 1)}, f)
    log.info("test excerpt chosen")
    return excerpt_info()


def clear_excerpt():
    for x in AUDIO_EXTS + (".json",):
        with contextlib.suppress(OSError):
            os.unlink(EXCERPT_BASE + x)


def _window(n):
    """30 s au cœur du morceau : à partir de 20 % (passé l'intro), sans déborder la fin."""
    w = min(n, EXCERPT_S * SR)
    return max(0, min(int(n * 0.2), n - w)), w


def _excerpt_pcm(dst):
    """L'extrait choisi → les 30 s testées, en PCM float32 dans `dst`. Rend n."""
    import numpy as np
    full = dst + ".full"
    try:
        n = decode(excerpt_path(), full)
        a, w = _window(n)
        x = np.memmap(full, dtype=np.float32, mode="r", shape=(2 * n,))
        np.asarray(x[2 * a:2 * (a + w)]).tofile(dst)
        del x
        return w
    finally:
        with contextlib.suppress(OSError):
            os.unlink(full)


def _set_test(eid, **kw):
    with _lock:
        d = load()
        e = _engine(d, eid)
        if e is not None:
            e["test"] = {**(e.get("test") or {}), **kw}
            _save(d)


def _test_run(eid):
    work = tempfile.mkdtemp(prefix="golem-sep-test-")
    try:
        e = _engine(load(), eid)
        mix = os.path.join(work, "mix.f32")
        n = _excerpt_pcm(mix)
        def stop():
            return _busy(idle=False)
        _TEST["phase"] = "excerpt"
        stems, comp, load_s = separate(e, mix, n, os.path.join(work, "w1"), os.path.join(work, "o1"), stop,
                                       lambda p: _TEST.update(progress=p))
        _fit(e, stems, n)
        a = analyse(stems, mix, n)
        why = judge_test(a)
        # la passe sur le silence vérifie que le moteur rend toujours les mêmes stems
        if not why:
            _TEST.update(phase="silence", progress=None)
            sil = os.path.join(work, "silence.f32")
            with open(sil, "wb") as f:
                f.write(b"\0" * (30 * SR * 8))
            st2, _, _ = separate(e, sil, 30 * SR, os.path.join(work, "w2"), os.path.join(work, "o2"), stop)
            _fit(e, st2, 30 * SR)
            a2 = analyse(st2, sil, 30 * SR)
            if sorted(a2["stems"]) != sorted(a["stems"]):
                why = "the engine returns other stems on silence"
        rtf = round(comp / (n / SR), 3)
        _set_test(eid, ok=not why, why=why, stems=a["stems"], rtf=rtf, load_s=round(load_s, 2), log_tail="", files=[],
                  hints=hints(why) if why else [],
                  tested_at=time.strftime("%Y-%m-%dT%H:%M:%S"), analysis=a)
        with _lock:
            d = load()
            d["rtf"][eid] = [rtf]
            if why and d.get("active") == eid:
                d["active"] = None
            _save(d)
        log.info("%s tested: %s" % (_origin_word(e), "ok" if not why else "refused"))
    except Stopped:
        _set_test(eid, ok=False, why="the test was interrupted (golem became busy)",
                  tested_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    except SeparationError as ex:
        extra = {"log_tail": ex.log_tail, "files": ex.files} if isinstance(ex, ProgramFailed) else {"log_tail": "", "files": []}
        extra["hints"] = hints(str(ex), extra["log_tail"], extra["files"])
        _set_test(eid, ok=False, why=str(ex), tested_at=time.strftime("%Y-%m-%dT%H:%M:%S"), **extra)
        log.info("%s tested: refused" % _origin_word(_engine(load(), eid) or {}))
    except Exception as ex:  # noqa: BLE001 — un test qui casse se DIT, il ne fait pas tomber le bridge
        _set_test(eid, ok=False, why="the test could not run", tested_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        log.warning("separation test crashed: %s" % type(ex).__name__)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _TEST.update(id=None, phase=None, progress=None)
        _publish()


# ── ajouter, installer, activer, retirer ──────────────────────────────────────────────────────
def _new_id():
    return "c-" + secrets.token_hex(5)


def _fetch(url, dest, auth=False, limit=MAX_ONNX_BYTES):
    req = urllib.request.Request(url)
    if auth:
        from . import golemfm
        base, token = golemfm._cfg()
        req = urllib.request.Request(base + url)
        req.add_header("Authorization", "Bearer " + token)
    h = hashlib.sha256()
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=1800) as r, open(dest, "wb") as f:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                got += len(chunk)
                if got > limit:
                    raise SeparationError("the file is too large")
                h.update(chunk)
                f.write(chunk)
    except urllib.error.URLError:
        raise SeparationError("download failed")
    return h.hexdigest()


# ── le stepper « + Add engine » (mockups/separation-add-stepper.html) : vérifier, lire, parcourir, aider ─────────────
STAGING = None          # posé à l'usage : WORK_DIR/staging (un .onnx téléchargé en attendant l'ajout)


def _staging_dir():
    d = os.path.join(WORK_DIR, "staging")
    os.makedirs(d, exist_ok=True)
    return d


def _staged(source):
    m = re.match(r"^staged:([a-f0-9]{16})$", source or "")
    if not m:
        return None
    p = os.path.join(_staging_dir(), m.group(1) + ".onnx")
    return p if os.path.isfile(p) else None


def add_combined(first, keep, second, label="", accepted=False):
    """« Combine two of my engines » : deux moteurs déjà testés, les stems gardés du premier, le second sur le reste."""
    if not accepted:
        raise SeparationError("tick the box: you combine these engines yourself")
    d = load()
    e1, e2 = _engine(d, first), _engine(d, second)
    if not e1 or not e2 or first == second:
        raise SeparationError("choose two different engines")
    for x in (e1, e2):
        if x.get("kind") == "combined":
            raise SeparationError("a combination cannot use another combination")
        if not (x.get("test") or {}).get("ok"):
            raise SeparationError("“%s” has not passed its test" % x.get("label"))
    stems1 = list(e1["test"].get("stems") or [])
    keep = [k for k in (keep or []) if k in stems1]
    if not keep:
        raise SeparationError("keep at least one stem from the first engine")
    if len(keep) == len(stems1):
        raise SeparationError("leave at least one stem for the second engine")
    e = {"id": "cmb-" + secrets.token_hex(5), "origin": "custom", "kind": "combined",
         "label": (label or "%s + %s" % (e1.get("label"), e2.get("label")))[:60], "first": first, "second": second,
         "keep": keep, "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "test": {}}
    with _lock:
        d = load()
        d["engines"].append(e)
        _save(d)
    log.info("custom engine added (combined)")
    return e


_IMPORT = {"phase": None, "error": None, "engine": None}


def install_combined(form, accepted=False):
    """Un fichier de moteur COMBINÉ importé (deux programmes et la règle) : les deux moteurs sont ajoutés et testés l'un
    après l'autre, puis la combinaison, testée à son tour — chacun comme si l'utilisateur l'avait fait. En tâche de fond ;
    l'avancement se lit dans `overview()["import"]`."""
    if not accepted:
        raise SeparationError("tick the box: you add these engines yourself")
    if _IMPORT["phase"] not in (None, "done", "failed"):
        raise SeparationError("an import is already running")
    if not excerpt_path():
        raise SeparationError("choose a test excerpt first")
    _IMPORT.update(phase="first engine", error=None, engine=None)

    def run():
        try:
            ids = []
            for which in ("first", "second"):
                f = form[which]
                _IMPORT["phase"] = "adding and testing the %s engine" % which
                e = add_program(f["program"], f["args"], f.get("licence") or "", True, f.get("label") or "", f.get("outputs"))
                test(e["id"], wait=True)
                if not (_engine(load(), e["id"]).get("test") or {}).get("ok"):
                    raise SeparationError("the %s engine did not pass its test — see it in the list" % which)
                ids.append(e["id"])
            _IMPORT["phase"] = "testing the combination"
            c = add_combined(ids[0], form["keep"], ids[1], form.get("label") or "", True)
            test(c["id"], wait=True)
            _IMPORT.update(phase="done", engine=c["id"])
        except SeparationError as ex:
            _IMPORT.update(phase="failed", error=str(ex))
        except Exception as ex:  # noqa: BLE001
            _IMPORT.update(phase="failed", error="the import could not finish")
            log.warning("combined import crashed: %s" % type(ex).__name__)
        _publish()
    threading.Thread(target=run, daemon=True, name="separation-import").start()
    return {"ok": True}


def program_checks(program):
    """Étape « Program » : chaque contrôle, dit séparément — l'erreur se voit là où elle est faite."""
    program = (program or "").strip()
    exists = bool(program) and os.path.isfile(program)
    runnable = exists and (os.name == "nt" or os.access(program, os.X_OK))
    script = exists and os.name == "nt" and os.path.splitext(program)[1].lower() in (".bat", ".cmd")
    why = (None if exists and runnable and not script else
           "file not found" if not exists else
           "this file cannot be run (not executable)" if not runnable else
           ".bat and .cmd files are not accepted — choose the program itself")
    return {"ok": why is None, "why": why, "exists": exists, "runnable": runnable, "not_script": exists and not script}


PROGRAMS_DIR = os.path.join(C.CONFIG_DIR, "separation-programs")


def program_recipes():
    """§4 quinquies (avocat, 2026-10-14) : les RECETTES de programmes libres — des DONNÉES, jamais du code propre à un
    outil. Une recette porte la plomberie (entrée, sortie, format) et des CHAMPS que l'utilisateur remplit lui-même ;
    elle ne nomme jamais un modèle (tests/test_separation_programs.py)."""
    out = []
    try:
        names = sorted(n for n in os.listdir(PROGRAMS_DIR) if n.endswith(".json"))
    except OSError:
        return out
    for n in names:
        try:
            with open(os.path.join(PROGRAMS_DIR, n), encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and r.get("id") and isinstance(r.get("args"), list):
            out.append(r)
    return out


def _find_program(find):
    """Où l'utilisateur a installé le programme : son PATH, puis les emplacements usuels que la recette décrit."""
    import glob
    for name in (find or {}).get("names") or []:
        p = shutil.which(name)
        if p and program_checks(p)["ok"]:
            return p
    for pat in (find or {}).get("paths") or []:
        for p in sorted(glob.glob(os.path.expanduser(pat))):
            if program_checks(p)["ok"]:
                return p
    return None


def detect_programs():
    """Les programmes de séparation libres DÉTECTÉS sur cette machine — un acte technique neutre (avis du 2026-10-14).
    Rend la recette et le chemin trouvé ; jamais journalisé."""
    out = []
    for r in program_recipes():
        p = _find_program(r.get("find"))
        if p:
            out.append({k: r.get(k) for k in ("id", "name", "licence", "url", "args", "fields")} | {"path": p})
    return out


_HELP = {}                   # (chemin, mtime) -> résultat : l'aide ne se relance que si le programme change
HELP_TIMEOUT_S = 15          # un outil qui charge une grosse bibliothèque met plusieurs secondes rien que pour s'afficher
HELP_MAX_LINES = 400
_OPT_RX = re.compile(r"(?<![\w/.-])(--?[A-Za-z][A-Za-z0-9_-]*)")


def program_help(program):
    """L'AIDE que le programme donne sur lui-même (2026-10-12) — `--help`, sinon `-h` — pour l'étape Command.
    Lue, jamais devinée : golem n'y ajoute rien et ne la journalise pas (elle reste sur l'écran de cette machine).
    Mêmes garde-fous qu'un essai : sans shell, dossier temporaire, environnement minimal, priorité basse, délai court,
    arbre tué au dépassement, sortie tronquée. Rend {ok, text, flag, options} ou {ok: False, why}."""
    chk = program_checks(program)
    if not chk["ok"]:
        return {"ok": False, "why": chk["why"]}
    program = program.strip()
    key = (program, os.path.getmtime(program))
    if key in _HELP:
        return _HELP[key]
    res = {"ok": False, "why": "this program prints no help — check its documentation"}
    for flag in ("--help", "-h"):
        tmp = tempfile.mkdtemp(prefix="golem-sep-help-")
        try:
            kw = {"cwd": tmp, "env": _min_env(), "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE,
                  "stderr": subprocess.STDOUT}
            if os.name == "nt":
                kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00004000
            else:
                kw["start_new_session"] = True
                kw["preexec_fn"] = lambda: os.nice(19)
            try:
                p = subprocess.Popen([program, flag], **kw)
            except OSError:
                return {"ok": False, "why": "the program could not be started"}
            try:
                out, _ = p.communicate(timeout=HELP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                _kill_tree(p)
                res = {"ok": False, "why": "the program did not answer %s within %d s" % (flag, HELP_TIMEOUT_S)}
                continue
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        lines = (out or b"")[:256 << 10].decode("utf-8", "replace").replace("\r", "").splitlines()
        text = "\n".join(lines[:HELP_MAX_LINES]).strip()
        opts = []
        for ln in lines[:HELP_MAX_LINES]:
            for m in _OPT_RX.findall(ln):
                if m not in opts and m not in ("--help", "-h") and len(m) > 2 - (not m.startswith("--")):
                    opts.append(m)
        if text and (p.returncode == 0 or opts):
            res = {"ok": True, "text": text, "flag": flag, "options": opts[:120],
                   "truncated": len(lines) > HELP_MAX_LINES}
            break
    _HELP[key] = res
    return res


def inspect_source(source):
    """Étape « Model file » : ce que le fichier dit de lui AVANT l'ajout. Une URL est téléchargée une fois, gardée en
    attente (`staged:<id>`) et réutilisée par l'ajout. Rend {stems, segment, overlap, sample_rate, licence, name,
    size_bytes, source}."""
    source = (source or "").strip()
    if re.match(r"^https?://", source):
        tok = secrets.token_hex(8)
        dst = os.path.join(_staging_dir(), tok + ".onnx")
        try:
            _fetch(source, dst)
            info = inspect_onnx(dst)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(dst)
            raise
        path, src = dst, "staged:" + tok
    elif os.path.isfile(source):
        info, path, src = inspect_onnx(source), source, source
    else:
        raise SeparationError("file not found")
    return {"stems": info["outputs"], "segment": info["segment"], "overlap": info["overlap"],
            "sample_rate": info["sample_rate"], "licence": info["licence"], "name": info["name"],
            "size_bytes": os.path.getsize(path), "source": src}


def browse(path=None, want="program"):
    """Le « Browse… » du stepper : les dossiers, et les fichiers qui PEUVENT servir — exécutables (programme), .onnx
    (modèle), tout fichier (`file` : le champ d'une recette) ou aucun (`dir` : choisir un dossier). Sans `path` : le
    dossier personnel. Réservé à l'admin (préfixe /api/separation)."""
    p = os.path.abspath(os.path.expanduser(path or "~"))
    if not os.path.isdir(p):
        raise SeparationError("folder not found")
    dirs, files = [], []
    try:
        with os.scandir(p) as it:
            for x in it:
                if x.name.startswith("."):
                    continue
                try:
                    if x.is_dir():
                        dirs.append(x.name)
                    elif x.is_file():
                        if want == "onnx" and x.name.lower().endswith(".onnx"):
                            files.append(x.name)
                        elif want == "file":
                            files.append(x.name)
                        elif want == "audio" and x.name.lower().endswith(AUDIO_EXTS + (".gp", ".lrc")):
                            files.append(x.name)          # « Separate a folder » : on VOIT les morceaux, on choisit le dossier
                        elif want == "program" and (os.access(x.path, os.X_OK) if os.name != "nt"
                                                    else x.name.lower().endswith((".exe", ".com"))):
                            files.append(x.name)
                except OSError:
                    continue
    except OSError:
        raise SeparationError("folder not readable")
    parent = os.path.dirname(p)
    return {"path": p, "parent": parent if parent != p else None,
            "dirs": sorted(dirs, key=str.lower)[:400], "files": sorted(files, key=str.lower)[:400]}


def hints(why="", log_tail="", files=()):
    """Les aides PAR SYMPTÔME d'un essai ou d'un test raté — génériques, aucun outil nommé (avis de l'avocat, 2026-10-12)."""
    w, t = (why or "").lower(), (log_tail or "").lower()
    out = []
    if "code 127" in w or "not found" in t and "command" in t:
        out.append("The program could not find a command or a library it needs — check that it runs from a terminal.")
    if "code 126" in w or "permission denied" in t or "not executable" in w:
        out.append("The system refused to run it — make the file executable, or choose the program itself.")
    if "no wav" in w:
        if any(x in t for x in (".flac", ".mp3", ".ogg", ".m4a")):
            out.append("It wrote another format — find its option for WAV output.")
        out.append("It may write somewhere else by default — find its option for the output folder and give it {outdir}.")
        out.append("It may download what it needs the first time — try again.")
    if "not named after stems" in w or "did not write" in w:
        out.append("Match each file it writes to a stem (Try it).")
    if any(x in t for x in ("out of memory", "memoryerror", "cuda error", "cannot allocate")):
        out.append("It ran out of memory — look for an option that processes smaller segments, or that uses the CPU.")
    if "too long" in w:
        out.append("It took longer than golem allows (4 × the length of the audio) — look for a faster setting.")
    if "unknown argument" in t or "unrecognized argument" in t or "usage:" in t:
        out.append("It did not understand an argument — compare the command with what the program expects.")
    if "do not add up" in w:
        out.append("Its stems do not add up to the song — a stem may be missing: match every file it writes.")
    if "fewer than 2 stems" in w or "is the mix itself" in w:
        out.append("Choose a test excerpt with several instruments.")
    return out


def add_onnx(source, licence="", accepted=False, label=""):
    """§2.2 : un chemin local ou une URL SAISIE par l'utilisateur. La case de responsabilité est obligatoire."""
    if not accepted:
        raise SeparationError("tick the box: you add this engine yourself")
    source = (source or "").strip()
    eid = _new_id()
    folder = os.path.join(ENG_DIR, eid)
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, "model.onnx")
    try:
        staged = _staged(source)
        if staged:
            shutil.move(staged, dst)                     # lu à l'étape précédente du stepper (inspect_source)
        elif re.match(r"^https?://", source):
            _fetch(source, dst)
        elif os.path.isfile(source):
            shutil.copyfile(source, dst)
        else:
            raise SeparationError("file not found")
        info = inspect_onnx(dst)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    e = {"id": eid, "origin": "custom", "kind": "onnx", "label": (label or info["name"] or "Custom engine")[:60],
         "licence": (licence or info["licence"] or "")[:500], "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "declared_stems": info["outputs"], "segment": info["segment"], "test": {}}
    with _lock:
        d = load()
        d["engines"].append(e)
        _save(d)
    log.info("custom engine added (onnx)")
    return e


def _clean_map(m):
    """{chemin relatif d'un WAV: stem} — un stem dans la forme du §7, au plus une fois ; une valeur vide = ignoré."""
    out, seen = {}, set()
    for rel, stem in (m or {}).items():
        rel, stem = str(rel).strip(), str(stem or "").strip()
        if not rel.lower().endswith(".wav") or rel.startswith("/") or ".." in rel.split("/"):
            raise SeparationError("not an output file: %s" % rel[:60])
        if not stem:
            continue
        if not STEM_RX.match(stem) or stem in RESERVED or stem in seen:
            raise SeparationError("stem name not accepted: %s" % stem[:40])
        seen.add(stem)
        out[rel] = stem
    return out


ENGINE_FILE_FORMAT = "golem-engine/1"


def export_engine(eid):
    """Le « fichier de moteur » (avis de l'avocat, 2026-10-12 : interopérabilité, L.122-6-1) : la consigne d'exécution
    d'un moteur À SOI, que l'utilisateur peut garder ou partager HORS de golem et de golem.fm. golem n'en fournit aucun.
    Ni clé, ni moteur de la liste, ni service : seulement ce que l'utilisateur a saisi."""
    d = load()
    e = _engine(d, eid)
    if e and e.get("kind") == "combined":
        parts = [_engine(d, e.get("first")), _engine(d, e.get("second"))]
        if not all(p and p.get("kind") == "program" for p in parts):
            raise SeparationError("only a combination of two programs can be exported")
        return {"format": ENGINE_FILE_FORMAT, "kind": "combined", "label": e.get("label") or "", "keep": list(e["keep"]),
                "first": _program_doc(parts[0]), "second": _program_doc(parts[1])}
    if not e or e.get("kind") != "program":
        raise SeparationError("only an engine of your own (a program) can be exported")
    return {"format": ENGINE_FILE_FORMAT, **_program_doc(e)}


def _program_doc(e):
    return {"kind": "program", "label": e.get("label") or "", "program": e.get("program"), "args": list(e.get("args") or []),
            "outputs": dict(e.get("map") or {}), "licence": e.get("licence") or ""}


def _part(doc, key):
    part = doc.get(key)
    if not isinstance(part, dict):
        raise SeparationError("this is not a golem engine file")
    return {**part, "format": ENGINE_FILE_FORMAT}


def read_engine_file(doc):
    """Lit un fichier de moteur importé : il PRÉ-REMPLIT le formulaire, rien de plus — l'utilisateur relit, coche la case
    de responsabilité et ajoute (le test suit). Rend les champs du formulaire."""
    if not isinstance(doc, dict) or doc.get("format") != ENGINE_FILE_FORMAT or doc.get("kind") not in ("program", "combined"):
        raise SeparationError("this is not a golem engine file")
    if doc.get("kind") == "combined":
        keep = [str(k) for k in (doc.get("keep") or [])][:16]
        return {"kind": "combined", "label": str(doc.get("label") or "")[:60], "keep": keep,
                "first": read_engine_file(_part(doc, "first")), "second": read_engine_file(_part(doc, "second"))}
    args = [str(a) for a in (doc.get("args") or [])][:64]
    return {"kind": "program", "program": str(doc.get("program") or "")[:500], "args": args,
            "outputs": _clean_map(doc.get("outputs")), "label": str(doc.get("label") or "")[:60],
            "licence": str(doc.get("licence") or "")[:500]}


def add_program(program, args, licence="", accepted=False, label="", outputs=None):
    if not accepted:
        raise SeparationError("tick the box: you add this engine yourself")
    args = check_program((program or "").strip(), args)
    e = {"id": _new_id(), "origin": "custom", "kind": "program", "label": (label or "Custom program")[:60],
         "program": program.strip(), "args": args, "map": _clean_map(outputs), "licence": (licence or "")[:500],
         "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "test": {}}
    with _lock:
        d = load()
        d["engines"].append(e)
        _save(d)
    log.info("custom engine added (program)")
    return e


_REMOTE = {"at": 0.0, "data": None}


def remote_list(fresh=False):
    """§2.1 : la liste de golem.fm. Un moteur listé qui en disparaît passe en custom, désactivé jusqu'à ce que la case
    soit recochée — jamais supprimé en silence. Les entrées `type: "service"` (services payants, retirés de la v0.6
    le 2026-10-31) sont ignorées."""
    if not fresh and _REMOTE["data"] is not None and time.monotonic() - _REMOTE["at"] < 120:
        return _REMOTE["data"]
    from . import golemfm
    base, token = golemfm._cfg()
    if not (base and token):
        return {"ok": False, "why": "not paired with golem.fm", "engines": []}
    st, data = golemfm._req("/api/ext/separation-engines", token=token, timeout=10)
    if st != 200 or not isinstance(data, dict):
        return {"ok": False, "why": "golem.fm unreachable", "engines": []}
    engines = [x for x in (data.get("engines") or []) if isinstance(x, dict) and x.get("slug")
               and x.get("type", "engine") != "service"]
    out = {"ok": True, "rev": data.get("rev"), "engines": engines}
    _withdrawn(engines, data.get("rev"))
    _REMOTE.update(at=time.monotonic(), data=out)
    return out


def _withdrawn(listed, rev):
    slugs = {x["slug"] for x in listed}
    with _lock:
        d = load()
        if rev and d.get("list_rev") == rev:
            return
        changed = False
        for e in d["engines"]:
            if e.get("origin") == "listed" and e.get("slug") not in slugs:
                e["origin"], e["accepted_at"], changed = "custom", None, True
                e["withdrawn_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                if d.get("active") == e["id"]:
                    d["active"] = None
                log.info("listed engine withdrawn from the list: now custom, disabled")
        d["list_rev"] = rev
        _save(d)
    if changed:
        _publish()


def install_listed(slug):
    """« Install » = un geste (§2.1) : téléchargé, sha256 vérifié, lu, puis testé comme tout moteur."""
    lst = remote_list(fresh=True)
    x = next((x for x in lst.get("engines", []) if x.get("slug") == slug), None)
    if not x:
        raise SeparationError("this engine is not in the list")
    if x.get("type", "engine") != "engine" or x.get("kind") != "onnx":
        raise SeparationError("this golem cannot install this kind of engine yet — update golem")
    url, want = x.get("download_url") or "", (x.get("sha256") or "").lower()
    if not url or not re.match(r"^[0-9a-f]{64}$", want):
        raise SeparationError("the list entry is incomplete")
    eid = slug
    folder = os.path.join(ENG_DIR, eid)
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    dst = os.path.join(folder, "model.onnx")
    try:
        got = _fetch(url, dst, auth=url.startswith("/"))
        if got != want:
            raise SeparationError("the downloaded file does not match the list (sha256)")
        info = inspect_onnx(dst)
        if x.get("stems") and sorted(x["stems"]) != sorted(info["outputs"]):
            raise SeparationError("the file does not match the list")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    e = {"id": eid, "origin": "listed", "slug": slug, "kind": "onnx", "label": (x.get("name") or slug)[:60],
         "author": (x.get("author") or "")[:120], "licence": ((x.get("licence") or {}).get("name") or "")[:200],
         "licence_url": (x.get("licence") or {}).get("url") or "", "attribution": (x.get("attribution") or "")[:500],
         "declared_stems": info["outputs"], "segment": info["segment"], "test": {}}
    with _lock:
        d = load()
        d["engines"] = [o for o in d["engines"] if o["id"] != eid] + [e]
        _save(d)
    log.info("listed engine installed")
    return e


def activate(eid, accepted=False):
    with _lock:
        d = load()
        e = _engine(d, eid)
        if not e:
            raise SeparationError("unknown engine")
        if not (e.get("test") or {}).get("ok"):
            raise SeparationError("test this engine first")
        if e.get("origin") != "listed" and not e.get("accepted_at"):
            if not accepted:
                raise SeparationError("tick the box: you add this engine yourself")
            e["accepted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        d["active"] = eid
        _save(d)
    log.info("%s activated" % _origin_word(e))
    _publish()
    return e


def deactivate():
    with _lock:
        d = load()
        d["active"] = None
        _save(d)
    _publish()


def used_by(d, eid):
    return [o for o in d["engines"] if o.get("kind") == "combined" and eid in (o.get("first"), o.get("second"))]


def remove(eid):
    """Retire un moteur — et les combinaisons qui l'utilisent (l'écran l'a dit et demandé avant)."""
    with _lock:
        d = load()
        e = _engine(d, eid)
        if not e:
            return False
        gone = {eid} | {o["id"] for o in used_by(d, eid)}
        if d.get("active") in gone and RUN_LOCK.locked():
            # ses fichiers servent la séparation en cours (job de golem.fm ou lot d'un dossier) : on ne les efface pas dessous
            raise SeparationError("this engine is separating a song right now — remove it when it is done")
        d["engines"] = [o for o in d["engines"] if o["id"] not in gone]
        if d.get("active") in gone:
            d["active"] = None
        for g in gone:
            d["rtf"].pop(g, None)
        _save(d)
    shutil.rmtree(os.path.join(ENG_DIR, eid), ignore_errors=True)
    log.info("%s removed" % _origin_word(e))
    _publish()
    return True


def set_threads(n):
    with _lock:
        d = load()
        d["threads"] = None if not n else max(1, min(64, int(n)))
        _save(d)


# ── ce que golem.fm apprend (§10) ─────────────────────────────────────────────────────────────
def active_engine():
    d = load()
    e = _engine(d, d.get("active")) if d.get("active") else None
    if not e or not (e.get("test") or {}).get("ok"):
        return None, d
    if e.get("origin") != "listed" and not e.get("accepted_at"):
        return None, d
    return e, d


def attributions():
    """Les cartes de System ▸ Licenses ▸ Libraries pour les moteurs installés depuis la liste (§2.1)."""
    out = []
    for e in load()["engines"]:
        if e.get("origin") != "listed":
            continue
        out.append({"name": e.get("label") or e.get("slug"), "by": e.get("author") or "",
                    "what": e.get("attribution") or "Separation engine", "license": e.get("licence") or "?",
                    "url": e.get("licence_url") or "", "kind": "separation", "installed": True})
    return out


def caps():
    """`caps.separation` = {stems, rtf} du moteur ACTIF testé — jamais son nom, son origine, sa porte. None sinon."""
    e, d = active_engine()
    if not e:
        return None
    hist = d["rtf"].get(e["id"]) or [e["test"].get("rtf")]
    hist = [x for x in hist if isinstance(x, (int, float))]
    return {"stems": list(e["test"].get("stems") or []), "rtf": round(sum(hist) / len(hist), 3) if hist else None}


def _note_rtf(eid, rtf):
    with _lock:
        d = load()
        h = (d["rtf"].get(eid) or [])[-2:] + [round(rtf, 3)]   # §6 : moyenne glissante des trois dernières
        d["rtf"][eid] = h
        _save(d)


def _publish():
    """Le battement porte caps : on le relance tout de suite après un changement visible par golem.fm."""
    with contextlib.suppress(Exception):
        from . import rigstatus
        rigstatus.push_soon()


# ── le job song-separate (§8) ────────────────────────────────────────────────────────────────
_JOBS = []                        # la file (mémoire) : golem.fm re-propose ce qui n'est pas acquitté
_JOB = {"cur": None, "phase": None, "progress": None, "waiting": None, "cancel": set(), "last": None}
_jcond = threading.Condition()
_worker = None
RUN_LOCK = threading.Lock()       # UN morceau à la fois sur le moteur : le job de golem.fm et le lot d'un dossier
                                  # (separation_batch) ne se marchent pas dessus


def on_job(job):
    """Handler de tones_jobs pour `song-separate` : mis en file, acquitté plus tard par le worker (ASYNC_ACK)."""
    from .plugin_recipes import ASYNC_ACK
    from .tones_jobs import job_id
    with _jcond:
        if not any(job_id(j) == job_id(job) for j in _JOBS) and job_id(_JOB["cur"] or {}) != job_id(job):
            _JOBS.append(job)
        _jcond.notify()
    _ensure_worker()
    return ASYNC_ACK


def _ensure_worker():
    global _worker
    if _worker and _worker.is_alive():
        return
    _worker = threading.Thread(target=_work, daemon=True, name="separation-jobs")
    _worker.start()


def cancel(jid=None):
    """Annuler depuis le golem : le job courant (ou celui qu'on nomme) est acquitté `cancelled`."""
    from .tones_jobs import job_id
    with _jcond:
        target = jid if jid is not None else job_id(_JOB["cur"] or {})
        if target is None:
            return False
        _JOB["cancel"].add(target)
        _jcond.notify()
    return True


def jobs_state():
    from .tones_jobs import job_id
    with _jcond:
        cur = _JOB["cur"]
        return {"current": None if not cur else {"job": job_id(cur), "kind": cur.get("kind"), "phase": _JOB["phase"],
                                                  "progress": _JOB["progress"]},
                "waiting": _JOB["waiting"], "queued": len(_JOBS), "last": _JOB["last"]}


# §10 : la raison d'attente part en CODE — jamais le texte de busy_reason (il porte la source du geste)
_WHY_CODES = (("gig mode", "gig"), ("mode locked", "locked"), ("a take is recording", "recording"),
              ("a song is playing", "playing"), ("a song is loading", "loading"),
              ("a preview is rendering", "preview"), ("in use (", "in_use"))


def why_code(why):
    for text, code in _WHY_CODES:
        if why and why.startswith(text):
            return code
    return None


def heartbeat_job():
    """`separation_job` du battement (§10) : le job song-separate TENU, s'il y en a un — sinon None (pas de clé)."""
    from .tones_jobs import job_id
    with _jcond:
        cur, phase, why, progress = _JOB["cur"], _JOB["phase"], _JOB["waiting"], _JOB["progress"]
    if not cur:
        return None
    out = {"job": job_id(cur), "phase": "waiting" if phase == "waiting" else "running"}
    if out["phase"] == "waiting":
        code = why_code(why)
        if code:
            out["why"] = code
        if code == "in_use":
            from . import activity
            from .reamp import IDLE_S
            out["starts_in_s"] = max(0, int(IDLE_S - activity.idle_s()))
    elif progress is not None:
        out["progress"] = round(max(0.0, min(1.0, float(progress))), 3)
    return out


def _ack(job, body):
    from .tones_jobs import _req, async_done, job_id
    jid = job_id(job)
    try:
        _req("POST", f"/api/ext/tones/jobs/{jid}/ack", body=body)
    finally:
        async_done(jid)


def _work():
    from .tones_jobs import job_id
    while True:
        with _jcond:
            while not _JOBS:
                _jcond.wait(30)
            job = _JOBS.pop(0)
            _JOB.update(cur=job, phase="waiting", progress=None)
        jid = job_id(job)
        locked = False
        try:
            # §8.3 : la règle « libre » du reamp, 10 min sans geste comprises, avant de PRENDRE le processeur
            told, told_at = None, None
            while True:
                if jid in _JOB["cancel"]:
                    raise SeparationError("cancelled", "cancelled")
                why = _busy(idle=True)
                if not why:
                    # le lot d'un dossier tient le moteur : on ATTEND ici (annulable), jamais « running » bloqué
                    # sur le verrou — sans code §10, golem.fm dit seulement « waiting » (revue 2026-10-25)
                    if RUN_LOCK.acquire(blocking=False):
                        locked = True
                        break
                    why = "a folder is being separated"
                _JOB["waiting"] = why
                code = why_code(why)
                starts = (heartbeat_job() or {}).get("starts_in_s") if code == "in_use" else None
                # §10 : la raison change, ou un geste a relancé les 10 min → golem.fm le sait tout de suite
                if code != told or (starts is not None and told_at is not None and time.time() + starts - told_at > 30):
                    told, told_at = code, (time.time() + starts if starts is not None else None)
                    _publish()
                with _jcond:
                    _jcond.wait(15)
            _JOB["waiting"] = None
            _JOB["phase"] = "download"                 # §10 : `running` dès qu'on tient le moteur
            _publish()
            res = _run_job(job)
            _ack(job, {"ok": True, "result": res})
            _JOB["last"] = {"job": jid, "ok": True, "at": time.strftime("%H:%M:%S")}
            log.info("song-separate done (%d stems)" % len(res["stems"]))
        except Stopped:
            # quelqu'un joue : pas d'ack, le job revient EN TÊTE — il reprendra au premier segment manquant
            with _jcond:
                _JOBS.insert(0, job)
            log.info("song-separate paused: golem became busy")
        except SeparationError as ex:
            code = ex.code if ex.code in ERROR_CODES else "engine_failed"
            _ack(job, {"ok": False, "error": code})
            _JOB["last"] = {"job": jid, "ok": False, "error": code, "why": str(ex)[:200],
                            "at": time.strftime("%H:%M:%S")}
            _cleanup(jid)
            log.info("song-separate failed: %s" % code)
        except Exception as ex:  # noqa: BLE001
            _ack(job, {"ok": False, "error": "engine_failed"})
            _JOB["last"] = {"job": jid, "ok": False, "error": "engine_failed", "at": time.strftime("%H:%M:%S")}
            _cleanup(jid)
            log.warning("song-separate crashed: %s" % type(ex).__name__)
        finally:
            if locked:
                RUN_LOCK.release()
            _JOB["cancel"].discard(jid)
            _JOB.update(cur=None, phase=None, progress=None, waiting=None)
            _publish()                                 # §10 : plus de job tenu → la clé disparaît


def _job_dir(jid):
    return os.path.join(WORK_DIR, "job-%s" % re.sub(r"[^A-Za-z0-9_-]", "_", str(jid))[:40])


def _cleanup(jid):
    shutil.rmtree(_job_dir(jid), ignore_errors=True)


def _run_job(job):
    from .tones_jobs import job_id
    jid = job_id(job)
    e, _ = active_engine()
    if not e:
        raise SeparationError("no engine is active", "no_engine")
    have = list(e["test"].get("stems") or [])
    wanted = [s for s in (job.get("stems_wanted") or []) if isinstance(s, str)] or have
    if not set(wanted) <= set(have):
        raise SeparationError("the active engine changed", "engine_changed")
    src, up = job.get("source_url") or "", job.get("upload_url") or ""
    if not src.startswith("/") or not up.startswith("/"):
        raise SeparationError("unexpected urls in the job", "source_unreadable")
    jd = _job_dir(jid)
    os.makedirs(jd, exist_ok=True)
    mix = os.path.join(jd, "mix.f32")
    if not os.path.isfile(mix):                        # reprise : la source n'est tirée qu'une fois
        _JOB["phase"] = "download"
        raw = os.path.join(jd, "source")
        try:
            from .golem_pull import _download
            _download(src, raw)
        except Exception:
            raise SeparationError("the song could not be downloaded", "source_unreadable")
        decode(raw, mix + ".tmp")
        os.replace(mix + ".tmp", mix)
        with contextlib.suppress(OSError):
            os.unlink(raw)
    n = os.path.getsize(mix) // 8
    _JOB["phase"] = "separate"

    def stop():
        if jid in _JOB["cancel"]:
            return "cancelled"
        return _busy(idle=False)
    out = os.path.join(jd, "out")
    try:
        stems, comp, _load = separate(e, mix, n, os.path.join(jd, "segments"), out, stop,
                                      lambda p: _JOB.update(progress=p))
    except Stopped:
        if jid in _JOB["cancel"]:
            raise SeparationError("cancelled", "cancelled")
        raise
    _fit(e, stems, n)
    a = analyse(stems, mix, n)                          # NaN, durée, noms : relus sur le vrai morceau (§8.4)
    if not set(wanted) <= set(a["stems"]):
        raise SeparationError("the engine did not return the expected stems", "engine_changed")
    _note_rtf(e["id"], comp / (n / SR))
    _JOB.update(phase="upload", progress=None)        # §10 : la progression de la séparation ne vaut pas pour l'envoi
    sent = []
    for s in wanted:
        mp3 = os.path.join(jd, s + ".mp3")
        if not os.path.isfile(mp3):
            encode_mp3(stems[s], mp3 + ".tmp.mp3")
            os.replace(mp3 + ".tmp.mp3", mp3)
        _upload(up, s, mp3)
        sent.append(s)
    _cleanup(jid)
    return {"stems": sent, "silent": [s for s in a["silent"] if s in sent]}


def _upload(path, stem, mp3, tries=3):
    """§8.4 : UN POST multipart par stem (champ `stem` + le fichier), idempotent chez golem.fm."""
    from . import golemfm
    base, token = golemfm._cfg()
    if not (base and token):
        raise SeparationError("not paired with golem.fm", "upload_failed")
    with open(mp3, "rb") as f:
        blob = f.read()
    boundary = "golem" + secrets.token_hex(12)
    body = b"".join([
        ("--%s\r\nContent-Disposition: form-data; name=\"stem\"\r\n\r\n%s\r\n" % (boundary, stem)).encode(),
        ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s.mp3\"\r\n"
         "Content-Type: audio/mpeg\r\n\r\n" % (boundary, stem)).encode(),
        blob, ("\r\n--%s--\r\n" % boundary).encode()])
    last = None
    for k in range(tries):
        req = urllib.request.Request(base + path, data=body, method="POST")
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                if 200 <= r.status < 300:
                    return
                last = r.status
        except urllib.error.HTTPError as ex:
            last = ex.code
            if 400 <= ex.code < 500 and ex.code not in (408, 429):
                break
        except Exception as ex:  # noqa: BLE001
            last = type(ex).__name__
        time.sleep(2 * (k + 1))
    raise SeparationError("the stems could not be sent (%s)" % last, "upload_failed")


# ── l'état pour l'écran ──────────────────────────────────────────────────────────────────────
def overview(remote=True):
    d = load()
    engines = []
    for e in d["engines"]:
        x = {k: v for k, v in e.items() if k not in ("program",)}
        if e.get("kind") == "program":
            x["program"] = e.get("program")
        x["active"] = d.get("active") == e["id"]
        x["needs_consent"] = e.get("origin") != "listed" and not e.get("accepted_at")
        x["used_by"] = [o["label"] for o in used_by(d, e["id"])]
        if e.get("kind") == "combined":
            parts = {o["id"]: o.get("label") for o in d["engines"]}
            x["first_label"], x["second_label"] = parts.get(e.get("first")), parts.get(e.get("second"))
        engines.append(x)
    out = {"engines": engines, "active": d.get("active"), "threads": threads(), "threads_default": _default_threads(),
           "test": dict(_TEST), "jobs": jobs_state(), "caps": caps(), "excerpt": excerpt_info(), "import": dict(_IMPORT)}
    if remote:
        out["list"] = remote_list()
    return out
