# SPDX-License-Identifier: GPL-3.0-or-later
"""Capturer un bloc VST en NAM, sur le poste (Windows/macOS) — docs/plugin-capture.md.

Décision 2026-10-05 : « partir du patch TEST VST (une suite d'ampli commerciale) et en faire une capture NAM »,
pour qu'un son Windows joue sous Linux. Les captures se font sur les PC et les Mac des membres (leur
plugin, leur carte graphique), jamais sur le rack.

Trois étapes, chacune MESURÉE plutôt que supposée :
  1. render : le signal d'entraînement NAM (v3, 48 kHz) traverse le plugin dans un REAPER SÉPARÉ
     (`-newinst -cfgfile`, sans carte son : le REAPER qui joue n'est jamais touché), avec l'état
     natif EXACT du bloc (vst_chunk) et les sections que NAM ne sait pas modéliser coupées
     (delay, reverb, gate — voir la recette du plugin).
  2. train  : l'entraîneur NAM officiel, en WaveNet CLASSIQUE (l'A2 ne joue pas sous Windows),
     sur la carte graphique si elle RÉPOND (CUDA, MPS), sinon le processeur.
  3. test   : un balayage et une vraie prise, passés dans le plugin (même état, mêmes coupures)
     et dans la capture (NAM VST3 de la machine) : niveau, nul égalisé, pire tiers d'octave.

La recette d'un plugin (quelles sections couper, par NOM de paramètre et valeur AFFICHÉE) vit en
données : library/catalog/plugin-captures.json. Sans recette, pas de capture : un delay gardé
dans le rendu donnerait un modèle faux qui « réussit ».
"""
import contextlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import config as C
from .golog import get

log = get("plugin-capture")

ROOT = Path(C.ROOT)
RECIPES = ROOT / "library" / "catalog" / "plugin-captures.json"
SR = 48000
PRE_S = 2          # pré-roulement : un plugin qui charge son état en tâche de fond a le temps
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
BELOW_NORMAL = 0x00004000 if sys.platform == "win32" else 0


# ── l'environnement d'entraînement (hors dépôt, posé une fois par machine) ─────────────────────
def train_home():
    if os.environ.get("GOLEM_NAM_TRAIN"):
        return Path(os.environ["GOLEM_NAM_TRAIN"])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GoleM" / "nam-train"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GoleM" / "nam-train"
    return Path.home() / ".cache" / "golem-build" / "nam-train"


def _venv_python(venv):
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


_PROBE = ("import torch\n"
          "if torch.cuda.is_available(): print('cuda', torch.cuda.get_device_name(0))\n"
          "elif torch.backends.mps.is_available(): print('mps', 'Apple GPU (MPS)')\n"
          "else: print('cpu', 'CPU')")


def trainer_python():
    """(python, appareil) : le GPU s'il RÉPOND, sinon le processeur. Un torch CUDA sans pilote retombe
    en silence sur le processeur — 47 min au lieu de 4 (mesuré le 2026-10-02) : on le demande à torch."""
    home = train_home()
    for venv in ("venv-cuda", "venv"):
        py = _venv_python(home / venv)
        if not py.exists():
            continue
        r = subprocess.run([str(py), "-c", _PROBE], capture_output=True, text=True, creationflags=NO_WINDOW)
        kind, _, name = ((r.stdout.strip().splitlines() or ["cpu CPU"])[-1]).partition(" ")
        if r.returncode == 0:
            return py, name or "CPU", kind
    return None, None, None


def environment():
    """Ce qui manque pour capturer sur cette machine, en anglais (affiché tel quel)."""
    home = train_home()
    py, device, kind = trainer_python()
    missing = []
    if not py:
        missing.append("NAM trainer (Python + torch + neural-amp-modeler)")
    if not (home / "v3_0_0.wav").is_file():
        missing.append("NAM training signal v3_0_0.wav")
    if not (home / "cfg" / "wavenet.json").is_file():
        missing.append("WaveNet model config")
    return {"ready": not missing, "missing": missing, "device": device, "gpu": kind in ("cuda", "mps"),
            "home": str(home)}


# ── les recettes (données) ─────────────────────────────────────────────────────────────────────
def recipe_for(plugin):
    """La recette VALIDÉE sur ce rack (proposée par golem.fm, mesurée, validée : docs/plugin-recipes.md) d'abord,
    puis la graine du dépôt (plugin-captures.json)."""
    from . import plugin_recipes
    local = plugin_recipes.validated_recipe(plugin)
    if local:
        return local
    try:
        data = json.loads(RECIPES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (data.get("plugins") or {}).get(str(plugin or ""))


# ── 1. le rendu, dans un REAPER séparé ─────────────────────────────────────────────────────────
def _lua(s):
    return json.dumps(str(s).replace("\\", "/"), ensure_ascii=False)


def _nam_helpers():
    """Les fonctions de golem_rig.lua qui posent un modèle dans l'état du NAM VST3 (nam_state_with_files) :
    la vérification d'une capture passe par le MÊME chemin de chargement que le rig."""
    src = (ROOT / "reaper" / "Scripts" / "golem_rig.lua").read_text(encoding="utf-8")
    start = src.index('local B64C = "ABCDEFGHIJKLMNOPQRSTUVWXYZ')
    return src[start:src.index("local function load_native_core", start)]


def _state_lua(chunk, nam_model):
    if nam_model:
        return f'''local okst, st0 = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
if not okst then die("état NAM illisible") end
local st1, errst = nam_state_with_files(st0, {_lua(nam_model)}, "")
if not st1 then die("modèle refusé : " .. tostring(errst)) end
if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", st1) then die("état NAM refusé") end'''
    if not chunk:
        return "-- aucun état à poser : le plugin garde ses défauts"
    return f'if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", {_lua(chunk)}) then die("état natif refusé") end'


def _render_script(plugin, chunk, overrides, src, project, trace, name, rate=SR, nam_model=None, controls=None):
    """Lua exécuté au démarrage du REAPER séparé : une piste, le signal, le plugin dans son état, les
    coupures de la recette visées par VALEUR AFFICHÉE et relues — puis le rendu, DANS LA MÊME SESSION.
    ⚠ Mesuré le 2026-10-05 : sauver le projet puis le rendre par `-renderproject` laissait la reverb
    de l'Archetype allumée (« FX Section = Inactive » relu, queue d'une seconde au rendu) — à la
    réouverture, le plugin restaure son état et la coupure n'y était pas. Ce qu'on rend est donc ce
    qu'on vient de relire, et on attend que le plugin ait fini de restaurer avant de couper."""
    ov = "{" + ",".join(f"[{_lua(k)}]={_lua(v)}" for k, v in overrides.items()) + "}"
    controls_lua = "{" + ",".join(
        "{i=" + str(int(p["i"])) + ",name=" + _lua(p["name"]) + ",value=" + repr(float(p["value"])) + "}"
        for p in (controls or [])) + "}"
    head = _nam_helpers() if nam_model else ""
    return head + f'''
local f = assert(io.open({trace if trace == "{TRACE}" else _lua(trace)}, "w"))
local function say(m) f:write(m .. "\\n"); f:flush() end
local function die(m) say("error=" .. tostring(m)); f:close(); error(m) end
for i = reaper.CountTracks(0) - 1, 0, -1 do reaper.DeleteTrack(reaper.GetTrack(0, i)) end
reaper.InsertTrackAtIndex(0, true)
local tr = reaper.GetTrack(0, 0)
-- InsertMedia, le chemin standard : une source créée par PCM_Source_CreateFromFile puis rendue dans la
-- même session sortait MUETTE sur le signal v3 (190 s) alors qu'un balayage de 9 s passait (mesuré)
reaper.SetOnlyTrackSelected(tr)
reaper.SetEditCurPos({PRE_S}, false, false)
if reaper.InsertMedia({_lua(src)}, 0) ~= 1 then die("signal illisible") end
local item = reaper.GetTrackMediaItem(tr, 0)
if not item then die("signal non inséré") end
local LEN = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
say("item " .. reaper.GetMediaItemInfo_Value(item, "D_POSITION") .. " +" .. LEN)
local fx = reaper.TrackFX_AddByName(tr, {_lua(plugin)}, false, -1)
if fx < 0 then die("plugin introuvable : " .. {_lua(plugin)}) end
{_state_lua(chunk, nam_model)}
local function shown(p) local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, ""); return s end
local controls = {controls_lua}
local function control_index(c)
  if c.i < 0 or c.i >= reaper.TrackFX_GetNumParams(tr, fx) then die("control index missing") end
  local _, actual = reaper.TrackFX_GetParamName(tr, fx, c.i, "")
  if actual ~= c.name then die("control changed: " .. c.name) end
  return c.i
end
local function apply()
  local want = {ov}
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, pname = reaper.TrackFX_GetParamName(tr, fx, p, "")
    local v = want[pname]
    if v ~= nil then
      if v == "min" or v == "max" then
        reaper.TrackFX_SetParamNormalized(tr, fx, p, v == "min" and 0 or 1)
      else
        local hit = false
        for i = 0, 100 do
          reaper.TrackFX_SetParamNormalized(tr, fx, p, i / 100)
          if shown(p) == v then hit = true; break end
        end
        if not hit then die("valeur « " .. v .. " » introuvable pour " .. pname) end
      end
      want[pname] = nil
    end
  end
  for k, _ in pairs(want) do die("paramètre absent : " .. k) end
  for _, c in ipairs(controls) do
    reaper.TrackFX_SetParamNormalized(tr, fx, control_index(c), c.value)
  end
end
local function verify()                                   -- relu juste avant le rendu
  local want = {ov}
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, pname = reaper.TrackFX_GetParamName(tr, fx, p, "")
    local v = want[pname]
    if v ~= nil then
      local s = shown(p)
      say("set " .. pname .. " = " .. s)
      if v ~= "min" and v ~= "max" and s ~= v then die("le plugin a remis " .. pname .. " à « " .. s .. " »") end
    end
  end
  for _, c in ipairs(controls) do
    local actual = reaper.TrackFX_GetParamNormalized(tr, fx, control_index(c))
    if math.abs(actual - c.value) > 0.000001 then die("control did not settle: " .. c.name) end
    say("param " .. c.i .. " " .. string.format("%.9f", actual))
  end
end
reaper.GetSetProjectInfo(0, "PROJECT_SRATE", {rate}, true)
reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
reaper.GetSetProjectInfo_String(0, "RENDER_FILE", {_lua(project.parent)}, true)
reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", {_lua(name)}, true)
reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdyAAAQ==", true)   -- WAV 32 bits flottants
reaper.GetSet_LoopTimeRange(true, false, 0, {PRE_S} + LEN, false)
reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)
reaper.GetSetProjectInfo(0, "RENDER_SRATE", {rate}, true)
reaper.GetSetProjectInfo(0, "RENDER_TAILFLAG", 0, true)
-- le plugin restaure son état en tâche de fond : on lui laisse le temps AVANT de couper, puis encore
-- un peu avant de relire (une coupure écrasée par une restauration tardive se verrait à la relecture)
local t0 = reaper.time_precise()
local step = 0
local function tick()
  local dt = reaper.time_precise() - t0
  if step == 0 and dt >= 3 then apply(); step = 1; t0 = reaper.time_precise()
  elseif step == 1 and dt >= 2 then
    verify()
    local tr0 = reaper.time_precise()
    reaper.Main_OnCommand(42230, 0)                       -- File: Render project (réglages du projet, sans boîte)
    say("render_s=" .. string.format("%.3f", reaper.time_precise() - tr0))   -- coût CPU (rendu hors ligne, 1 fil)
    say("rendered")
    f:close()
    return
  end
  reaper.defer(tick)
end
tick()
'''


def _process_mb(pid):
    """Mémoire privée d'un processus, en Mo (Windows ; None ailleurs ou en cas d'échec)."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {int(pid)}).PrivateMemorySize64"],
                             capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout.strip()
        return round(int(out) / 1048576) if out.isdigit() else None
    except Exception:
        return None


# ── ANNULER une capture (2026-10-05 : « j'ai voulu l'annuler mais aucun moyen de le faire ») ─────────
# Tout processus d'une capture (entraînement, mesure, vérification, REAPER de rendu) passe par ici et reste
# connu jusqu'à sa fin : `cancel()` les arrête où qu'en soit la capture, et le worker sort par Cancelled.
_cancel = threading.Event()
_procs = set()


class Cancelled(RuntimeError):
    pass


def _check_cancel():
    if _cancel.is_set():
        raise Cancelled("capture cancelled")


def _run(args, low_priority=False):
    """subprocess.run(capture_output, text) annulable."""
    _check_cancel()
    p = subprocess.Popen([str(a) for a in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         creationflags=NO_WINDOW | (BELOW_NORMAL if low_priority else 0))
    _procs.add(p)
    try:
        out, err = p.communicate()
    finally:
        _procs.discard(p)
    _check_cancel()
    return subprocess.CompletedProcess(args, p.returncode, out, err)


def cancel():
    """Arrête la capture en cours. Rend {ok} ; sans capture en cours, ok:false."""
    if _job.get("state") not in ("render", "train", "test", "install"):
        return {"ok": False, "error": "No capture is running"}
    _cancel.set()
    _set(state="cancelling", msg="Cancelling…")
    for p in list(_procs):
        with contextlib.suppress(Exception):
            p.kill()
    return {"ok": True}


# ── LES REAPER DE BANC SONT INSCRITS (2026-10-10, docs/platforms.md §5 point 5) ──────────────────
# Un REAPER de capture ou de recette s'appelle « reaper.exe » / « REAPER » comme le principal : le lanceur et la page
# Audio le prenaient pour lui (« Close REAPER first », 180 s d'attente pour rien), et sur Mac un « quit » par
# identifiant d'app pouvait viser la mauvaise instance. Chaque banc inscrit son PID dans un fichier du runtime
# (lu aussi par le lanceur, autre processus) ; provision/desktop.reaper_running() les ignore.
def bench_pids_file():
    return Path(C.runtime_file("bench-reaper-pids.json"))


_bench_lock = threading.Lock()


def _bench_register(pid, add):
    with _bench_lock:
        f = bench_pids_file()
        try:
            pids = set(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pids = set()
        (pids.add if add else pids.discard)(int(pid))
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(sorted(pids)), encoding="utf-8")
        except OSError as e:
            log.warning(f"banc REAPER non inscrit : {e}")


def _launch(reaper_exe, config, args, log_path):
    with open(log_path, "wb") as out:
        proc = subprocess.Popen([str(reaper_exe), "-newinst", "-nosplash", "-cfgfile", str(config), *args],
                                stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    _bench_register(proc.pid, True)
    return proc


def _stop(proc):
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    finally:
        _bench_register(proc.pid, False)


def stop_benches():
    """Arrête tous les REAPER de banc de ce bridge (capture, recette) — avant de fermer le REAPER PRINCIPAL : il
    n'en reste qu'un, et ni un « quit » par identifiant d'app (macOS) ni une attente « REAPER fermé » ne peuvent se
    tromper d'instance. Une capture en cours est annulée proprement ; une vérification de recette finit en « pas pu
    mesurer » (ack ok:false). Rend le nombre de REAPER arrêtés."""
    if _job.get("state") in ("render", "train", "test", "install"):
        cancel()
    n = 0
    for p in list(_procs):
        with contextlib.suppress(Exception):
            _stop(p)
            n += 1
    return n


def _bench_dir(work):
    """Le dossier d'un REAPER séparé : sans carte son, licence et caches de plugins de la machine."""
    from provision.desktop import resource_dir
    bench = Path(work) / "reaper"
    (bench / "Scripts").mkdir(parents=True, exist_ok=True)
    config = bench / "reaper.ini"
    # sans carte son : le moteur du rack garde la sienne ; la liste des plugins déjà scannés est
    # reprise du REAPER de la machine (sinon un premier lancement rescannerait tout le disque).
    # ⚠ 2026-10-05 : sans la LICENCE de la machine ni `verchk=0`, ce REAPER neuf ouvrait « EVALUATION
    # LICENSE » et « New Version Notification » — deux boîtes MODALES qui bloquent son script : le rendu
    # attendait sans fin (vu sur un dossier de travail neuf). Licence et réglage repris de la machine.
    # ⚠ macOS (passe du 2026-10-10, docs/platforms.md §5) : `[audioconfig] mode=4` est un réglage WINDOWS
    # (pas de carte) que macOS ignore — REAPER y garde ses préférences Core Audio dans [REAPER]. Sans elles, il peut
    # ouvrir « You have not yet selected an audio device », une boîte MODALE avant __startup.lua : le rendu attendait
    # 300 à 600 s puis échouait. Les périphériques par défaut, comme tools/check-native-nam.py (CI macos-26).
    audio = ("coreaudioindevnew=<default system devices>\ncoreaudiooutdevnew=<default system devices>\n"
             if sys.platform == "darwin" else "[audioconfig]\nmode=4\n")
    config.write_text("[REAPER]\nnolastproject=1\nopenallrecent=0\nsplashfast=1\nverchk=0\n" + audio, encoding="ascii")
    caches = ["reaper-license.rk", "reaper-vstplugins64.ini", "reaper-vstplugins.ini",
              "reaper-vstplugins_arm64.ini", "reaper-auplugins64.ini", "reaper-clap-win64.ini"]
    # les noms des caches AU / CLAP de REAPER sur Mac varient (Apple Silicon, versions) : tous ceux qui existent,
    # sinon chaque capture rescanne les plugins — lent, et une autorisation de plugin peut s'ouvrir
    caches += [p.name for p in Path(resource_dir()).glob("reaper-*plugins*.ini")]
    caches += [p.name for p in Path(resource_dir()).glob("reaper-clap-*.ini")]
    for cache in dict.fromkeys(caches):
        if (Path(resource_dir()) / cache).is_file():
            shutil.copyfile(Path(resource_dir()) / cache, bench / cache)
    return bench


_MAC_AUDIO_DIALOG = """tell application "System Events"
  set p to first application process whose unix id is {pid}
  repeat with w in windows of p
    set hit to false
    repeat with e in (entire contents of w)
      try
        if (role of e as text) is "AXStaticText" and ((value of e as text) contains "audio device" or (name of e as text) contains "audio device") then set hit to true
      end try
    end repeat
    if hit then
      try
        click button "No" of w
        return "dismissed"
      end try
    end if
  end repeat
  return "none"
end tell"""


def _mac_dismiss_audio_dialog(pid):
    """Filet de sécurité (macOS) : la boîte « You have not yet selected an audio device » d'un REAPER séparé, fermée
    par « No » — le moyen de tools/check-native-nam.py. Rend True si une boîte a été fermée. NON VÉRIFIÉ sur un Mac
    autre que la CI ; demande l'autorisation « Accessibilité » pour le processus qui lance golem."""
    if sys.platform != "darwin":
        return False
    try:
        out = subprocess.run(["osascript", "-e", _MAC_AUDIO_DIALOG.format(pid=int(pid))],
                             capture_output=True, text=True, timeout=15).stdout
        return "dismissed" in out
    except Exception as e:
        log.info(f"boîte audio de REAPER non fermée : {e}")
        return False


def bench_run(work, name, script, timeout=600, done="rendered"):
    """Lance un REAPER séparé (`_bench_dir`) qui exécute `script` (Lua, au démarrage) et attend que sa trace
    porte `done` (ou `error=`). Le script reçoit sa trace en `{TRACE}`. Rend (lignes de la trace, Mo du REAPER).
    Sert au rendu d'une capture ET à la lecture/vérification d'une recette (bridge/plugin_recipes.py)."""
    from provision.desktop import reaper_binary
    bench = _bench_dir(work)
    trace = bench / f"{name}.trace.txt"
    trace.unlink(missing_ok=True)
    startup = bench / "Scripts" / "__startup.lua"
    startup.write_text(script.replace("{TRACE}", _lua(trace)), encoding="utf-8")
    _check_cancel()
    proc = _launch(reaper_binary(), bench / "reaper.ini", [], bench / f"{name}.log")
    _procs.add(proc)
    mem_mb = None
    try:
        deadline = time.monotonic() + timeout
        t_start, dismissed = time.monotonic(), False
        while time.monotonic() < deadline:
            _check_cancel()
            text = trace.read_text(encoding="utf-8", errors="replace") if trace.is_file() else ""
            # macOS : 15 s sans trace = le script n'a pas démarré, une boîte de REAPER le tient peut-être
            if not text and not dismissed and sys.platform == "darwin" and time.monotonic() - t_start > 15:
                dismissed = True
                if _mac_dismiss_audio_dialog(proc.pid):
                    log.warning("REAPER séparé : boîte « audio device » fermée — sa config Core Audio n'a pas suffi")
            if "error=" in text:
                raise RuntimeError(text.split("error=", 1)[1].strip())
            if done in text:
                mem_mb = _process_mb(proc.pid)            # mémoire du REAPER, plugin chargé (avant de l'arrêter)
                break
            if proc.poll() is not None:
                raise RuntimeError("REAPER (capture) stopped before rendering")
            time.sleep(0.5)
        else:
            raise RuntimeError("REAPER (capture) did not render in time")
    finally:
        _procs.discard(proc)
        _stop(proc)
        startup.unlink(missing_ok=True)
    return trace.read_text(encoding="utf-8").splitlines(), mem_mb


def render(plugin, chunk, overrides, src, work, name, timeout=600, rate=SR, nam_model=None, controls=None):
    """Rend `src` à travers `plugin` (état `chunk`, coupures `overrides`) -> work/<name>.wav (premier
    canal, pré-roulement retiré). Rend aussi la trace des paramètres posés (preuve des coupures)."""
    work = Path(work)
    bench = _bench_dir(work)
    project = bench / f"{name}.rpp"
    for p in (project, bench / f"{name}.wav"):
        p.unlink(missing_ok=True)
    lines, mem_mb = bench_run(work, name, _render_script(plugin, chunk, overrides, Path(src).resolve(), project,
                                                         "{TRACE}", name, rate, nam_model, controls), timeout)
    rendered = bench / f"{name}.wav"
    if not rendered.is_file():
        raise RuntimeError("REAPER produced no render")
    x, got = read_wav(rendered)
    if got != rate:
        raise RuntimeError(f"render at {got} Hz, expected {rate}")
    x = x[PRE_S * rate:]
    peak = max((abs(v) for v in x), default=0.0)
    write_wav(work / f"{name}.wav", x, rate)
    sets = [l[4:] for l in lines if l.startswith("set ")]
    render_s = next((float(l.split("=", 1)[1]) for l in lines if l.startswith("render_s=")), None)
    actual = {int(l.split()[1]): float(l.split()[2]) for l in lines if l.startswith("param ")}
    return {"peak": peak, "seconds": len(x) / rate, "set": sets, "render_s": render_s, "mem_mb": mem_mb,
            "controls": actual}


# ── WAV (sans numpy : le bridge n'en dépend pas) ───────────────────────────────────────────────
def read_wav(path):
    """Premier canal d'un WAV PCM 16/24/32 bits ou float 32 -> (liste de float, taux)."""
    import struct
    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise RuntimeError(f"not a WAV file: {path}")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
            if fmt[0] == 0xFFFE and len(body) >= 26:    # WAVE_FORMAT_EXTENSIBLE : le vrai format est le sous-format
                fmt = (struct.unpack("<H", body[24:26])[0],) + fmt[1:]
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if not fmt or raw is None:
        raise RuntimeError(f"incomplete WAV file: {path}")
    tag, chans, rate, _br, align, bits = fmt
    n = len(raw) // align
    if tag == 3 and bits == 32:
        vals = struct.unpack_from(f"<{n * chans}f", raw)
        return list(vals[::chans]), rate
    if bits == 16:
        vals = struct.unpack_from(f"<{n * chans}h", raw)
        return [v / 32768 for v in vals[::chans]], rate
    if bits == 24:
        out = []
        for i in range(n):
            b = raw[i * align:i * align + 3]
            out.append(int.from_bytes(b, "little", signed=True) / 8388608)
        return out, rate
    if bits == 32:
        vals = struct.unpack_from(f"<{n * chans}i", raw)
        return [v / 2147483648 for v in vals[::chans]], rate
    raise RuntimeError(f"unsupported WAV format ({tag}, {bits} bits): {path}")


def write_wav(path, x, rate=SR):
    """WAV mono float 32 — le format que l'entraîneur NAM lit sans conversion."""
    import struct
    payload = struct.pack(f"<{len(x)}f", *x)
    head = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(payload), b"WAVE", b"fmt ", 16, 3, 1, rate,
                       rate * 4, 4, 32, b"data", len(payload))
    Path(path).write_bytes(head + payload)


# ── 2. l'entraînement ──────────────────────────────────────────────────────────────────────────
# exécuté DANS le venv d'entraînement : l'entraîneur officiel, avec le WaveNet classique à la place
# de son modèle « packed » (A2) par défaut (docs/plugin-capture.md §2)
_TRAIN = r'''
import json, sys, time, torch
from nam.train import core
cfg_path, x, y, outdir, epochs = sys.argv[1:6]
model_cfg = json.load(open(cfg_path))
model_cfg.pop("_notes", None)
core._get_packed_model_config = lambda: model_cfg
t0 = time.time()
res = core.train(x, y, outdir, epochs=int(epochs), silent=True, modelname="capture")
device = (torch.cuda.get_device_name(0) if torch.cuda.is_available()
          else "Apple GPU (MPS)" if torch.backends.mps.is_available() else "CPU")
if res is None or res.model is None:
    print("FAILED: the trainer rejected the data (checks)"); sys.exit(1)
res.model.net.export(outdir, basename="capture")
print(json.dumps({"validation_esr": res.metadata.validation_esr, "seconds": round(time.time() - t0),
                  "epochs": int(epochs), "device": device}))
'''


def train(work, epochs=100, progress=None):
    work = Path(work)
    py, device, _kind = trainer_python()
    home = train_home()
    if not py:
        raise RuntimeError("NAM trainer not installed on this computer")
    script = work / "_train.py"
    script.write_text(_TRAIN, encoding="utf-8")
    outdir = work / "train"
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir()
    if progress:
        progress(device)
    # priorité basse : le moteur audio joue peut-être pendant ce temps, l'entraînement passe après le son
    r = _run([py, script, home / "cfg" / "wavenet.json", home / "v3_0_0.wav", work / "target.wav", outdir, epochs],
             low_priority=True)
    tail = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
    if r.returncode or not tail:
        (work / "train.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        raise RuntimeError("training failed: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1][:300])
    res = json.loads(tail[-1])
    nam = next(outdir.glob("**/capture.nam"))
    # le format que le plugin qui JOUE sait lire (§8) — l'original est gardé à côté
    shutil.copyfile(nam, work / "capture-v07.nam")
    legacy_nam(work / "capture-v07.nam", work / "capture.nam")
    res["architecture"] = json.loads((work / "capture.nam").read_text(encoding="utf-8")).get("architecture")
    (work / "train.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


# ── 3. la mesure : la (les) capture(s) contre le plugin, sur des signaux jamais vus ─────────────
def synth_di(seconds=20, seed=7):
    """Une « guitare » de synthèse (Karplus-Strong) : accords grattés, notes seules, notes étouffées,
    à plusieurs intensités. Ce n'est PAS une vraie prise — la mesure le dit — mais elle a ce qu'une DI
    a et que le balayage n'a pas : des attaques, des accords qui intermodulent, des fins de notes."""
    import random
    rnd = random.Random(seed)
    out = [0.0] * (seconds * SR)

    def pluck(t0, freq, amp, dur, damp=0.996):
        n = max(2, int(SR / freq))
        buf = [rnd.uniform(-1, 1) * amp for _ in range(n)]
        start, length = int(t0 * SR), int(dur * SR)
        for i in range(length):
            k = start + i
            if k >= len(out):
                break
            j = i % n
            v = buf[j]
            buf[j] = damp * 0.5 * (v + buf[(j + 1) % n])
            out[k] += v

    e2 = 82.41
    chords = [[0, 7, 12, 16, 19, 24], [5, 12, 17, 21, 24], [7, 14, 19, 23, 26], [3, 10, 15, 19, 22]]
    t = 0.2
    while t < seconds - 2:
        kind = rnd.random()
        amp = rnd.choice((0.08, 0.15, 0.25))
        if kind < 0.45:                                   # accord gratté
            for s, semi in enumerate(rnd.choice(chords)):
                pluck(t + s * 0.012, e2 * 2 ** (semi / 12), amp, 1.6)
            t += rnd.choice((0.8, 1.2, 1.6))
        elif kind < 0.8:                                  # notes seules
            for _ in range(4):
                pluck(t, e2 * 2 ** (rnd.randint(0, 24) / 12), amp, 0.5)
                t += 0.25
        else:                                             # notes étouffées, rapides
            for _ in range(8):
                pluck(t, e2 * 2 ** (rnd.choice((0, 0, 5, 7)) / 12), amp, 0.12, damp=0.95)
                t += 0.125
    peak = max(abs(v) for v in out) or 1.0
    return [v * (10 ** (-6 / 20)) / peak for v in out]   # crête à -6 dBFS, comme une DI franche


def sweep(seconds=8, level_db=-12.0):
    import math
    k = seconds / math.log(20000 / 20)
    a = 10 ** (level_db / 20)
    return [a * math.sin(2 * math.pi * 20 * k * (math.exp(t / SR / k) - 1)) for t in range(seconds * SR)] + [0.0] * SR


# exécuté DANS le venv d'entraînement (numpy + la bibliothèque NAM) : le signal traverse la CHAÎNE des
# captures (NAM, puis IR par convolution), et la sortie est comparée au plugin entier — même métrique
# que tools/check-core-parity.py. En mode « une capture », la chaîne n'a qu'un maillon.
_TEST = r"""
import json, sys
import numpy as np, torch
from nam.models import init_from_nam
chain_json, pairs_json, out_json = sys.argv[1:4]
SR = 48000
def rd(p):
    return np.fromfile(p, dtype="<f4", offset=44).astype(float)
stages = []
for kind, path in json.load(open(chain_json)):
    if kind == "nam":
        m = init_from_nam(json.load(open(path))); m.eval(); stages.append(("nam", m))
    elif kind == "gain":
        stages.append(("gain", 10 ** (float(path) / 20)))
    else:
        stages.append(("ir", rd(path)))
def run(x):
    for kind, s in stages:
        if kind == "nam":
            with torch.no_grad():
                x = s(torch.tensor(x, dtype=torch.float32), pad_start=True).numpy().astype(float)
        elif kind == "gain":
            x = x * s
        else:
            n = len(x); size = 1 << int(np.ceil(np.log2(n + len(s))))
            x = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(s, size), size)[:n]
    return x
def metrics(a, b):
    n = min(len(a), len(b)); a, b = a[:n], b[:n]
    size = 1 << int(np.ceil(np.log2(2 * n)))
    xc = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    lags = np.concatenate([xc[:4097], xc[-4096:]])
    k = int(np.argmax(np.abs(lags))); lag = k if k <= 4096 else k - len(lags)
    a2, b2 = (a[lag:], b[:n - lag]) if lag > 0 else ((a[:n + lag], b[-lag:]) if lag < 0 else (a, b))
    rms = lambda v: float(np.sqrt(np.mean(v * v)) + 1e-15)
    g = float(np.dot(a2, b2) / (np.dot(b2, b2) + 1e-30))
    win = np.hanning(8192)
    def psd(v):
        fr = [v[i:i + 8192] * win for i in range(0, len(v) - 8192, 4096)]
        return np.mean([np.abs(np.fft.rfft(f)) ** 2 for f in fr], axis=0)
    pa, pb = psd(a2), psd(g * b2); freqs = np.fft.rfftfreq(8192, 1 / SR)
    worst, where, fc = 0.0, 0.0, 40.0
    while fc < 16000:
        sel = (freqs >= fc / 2 ** (1 / 6)) & (freqs < fc * 2 ** (1 / 6))
        ea, eb = pa[sel].sum(), pb[sel].sum()
        if ea > 1e-12 * pa.sum():
            d = 10 * np.log10((eb + 1e-30) / (ea + 1e-30))
            if abs(d) > abs(worst): worst, where = float(d), fc
        fc *= 2 ** (1 / 3)
    return {"lag": lag, "level_db": float(20 * np.log10(rms(b2) / rms(a2))),
            "null_db": float(20 * np.log10(rms(a2 - g * b2) / rms(a2))), "band_db": worst, "band_hz": where}
res = {}
for name, x_path, y_path in json.load(open(pairs_json)):
    res[name] = metrics(rd(y_path), run(rd(x_path)))
json.dump(res, open(out_json, "w"), indent=1)
print(json.dumps(res))
"""


def test(work, plugin, chunk, reference_off, chain):
    """La chaîne `chain` ([("nam"|"ir", fichier)]) contre le plugin ENTIER (coupures `reference_off`, celles
    du mode « une capture » : on compare au son qu'on veut reproduire). Rend {signal: métriques}."""
    work = Path(work)
    tst = work / "test"
    tst.mkdir(exist_ok=True)
    pairs = []
    for name, sig in (("synth", synth_di()), ("sweep", sweep())):
        write_wav(tst / f"{name}-in.wav", sig)
        render(plugin, chunk, reference_off, tst / f"{name}-in.wav", tst, f"{name}-plugin")
        pairs.append((name, str(tst / f"{name}-in.wav"), str(tst / f"{name}-plugin.wav")))
    (tst / "pairs.json").write_text(json.dumps(pairs), encoding="utf-8")
    (tst / "chain.json").write_text(json.dumps([[k, f if k == "gain" else str(f)] for k, f in chain]), encoding="utf-8")
    (tst / "_test.py").write_text(_TEST, encoding="utf-8")
    py, _device, _kind = trainer_python()
    r = _run([py, tst / "_test.py", tst / "chain.json", tst / "pairs.json", work / "test.json"])
    if r.returncode:
        raise RuntimeError("capture test failed: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1][:300])
    return json.loads((work / "test.json").read_text(encoding="utf-8"))


# ── 3 bis. une IR : un baffle est LINÉAIRE, une impulsion suffit (pas d'entraînement) ──────────
IR_SECONDS = 0.5


def capture_ir(plugin, chunk, off, work):
    """Une impulsion traverse le plugin (seul le baffle actif) : la sortie EST l'IR. Recalée sur son
    attaque (le plugin déclare une latence que REAPER compense, parfois d'un cheveu de trop), 0,5 s,
    fondu de fin. Le niveau est gardé tel quel : le bloc cab de GoleM règle le sien."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    amp = 0.5                                       # une impulsion pleine échelle pourrait saturer en entrée
    pad = 4096
    write_wav(work / "impulse.wav", [0.0] * pad + [amp] + [0.0] * (SR - 1))
    r = render(plugin, chunk, off, work / "impulse.wav", work, "ir-render")
    y, _ = read_wav(work / "ir-render.wav")
    peak = max(abs(v) for v in y) or 0.0
    if peak < 1e-4:
        raise RuntimeError("the cab rendered silence — nothing to capture")
    thr = peak * 10 ** (-60 / 20)
    onset = next(i for i, v in enumerate(y) if abs(v) >= thr)
    start = max(0, min(onset, pad) - 16)            # jamais avant l'impulsion de plus de 16 échantillons
    ir = [v / amp for v in y[start:start + int(IR_SECONDS * SR)]]
    fade = len(ir) // 10
    for i in range(fade):
        ir[len(ir) - fade + i] *= 1 - i / fade
    write_wav(work / "cab.wav", ir)
    return {"set": r["set"], "onset": onset - pad, "peak": peak / amp}


# ── 4. ranger dans la bibliothèque ─────────────────────────────────────────────────────────────
def _slug(text):
    import re
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return s[:60] or "capture"


def install(src_file, meta):
    """Un fichier capturé (`.nam` ou IR `.wav`) -> assets/, entrée de catalogue `cap-<slug>`. La NATURE
    (`gear`) vient de la recette — on sait ce qu'on a rendu, on ne la devine pas (CLAUDE.md : bonne
    forme, mauvaise nature). L'écriture du catalogue déclenche la synchro vers golem.fm."""
    from .store import _read_json, _write_json_atomic
    is_ir = meta["gear"] == "cab"
    slug = _slug(meta.get("slug") or meta["name"])
    tid = f"cap-{slug}"
    rel_dir = Path("assets") / ("irs" if is_ir else "models") / "captures" / slug
    (ROOT / rel_dir).mkdir(parents=True, exist_ok=True)
    rel_file = (rel_dir / (f"{slug}.wav" if is_ir else f"{slug}.nam")).as_posix()
    shutil.copyfile(src_file, ROOT / rel_file)
    entry = {
        "id": tid, "title": meta["name"], "slug": slug, "creator": "golem plugin capture",
        "gear": meta["gear"], "format": "ir" if is_ir else "nam", "brand": meta.get("vendor") or "",
        "amp": meta["name"], "source_group": "plugin-capture", "pack": False, "tags": ["capture"],
        "models": [{"id": f"{tid}-1", "name": meta["name"], "file": rel_file,
                    "size": None if is_ir else "standard", "arch": None if is_ir else "1",
                    **({"controls": meta["controls"]} if "controls" in meta else {})}],
        # d'où vient le son, et ce qu'il vaut : la capture le dit, on ne le reconstitue pas plus tard
        "capture": {k: meta[k] for k in ("plugin", "patch", "block", "mode", "part", "set", "train", "test",
                                          "at", "private") if k in meta},
    }
    if "parametric" in meta:
        entry["parametric"] = meta["parametric"]
    cat = _read_json(C.CATALOG, {"tones": []}) or {"tones": []}
    cat["tones"] = [t for t in cat.get("tones", []) if str(t.get("id")) != tid] + [entry]
    _write_json_atomic(C.CATALOG, cat)
    return entry


# ── 5. la tâche de fond (une à la fois : le GPU et le REAPER de capture ne se partagent pas) ───

_job = {"state": "idle"}
_lock = threading.Lock()
MODES = ("full", "split")


def status():
    return dict(_job)


def _normalized():
    from .compile_rig import NORMALIZED_TYPES          # LUE dans la compile : une copie finirait par diverger
    return NORMALIZED_TYPES


def _set(**kw):
    _job.update(kw, updated=time.time())


def _live_params(block):
    from .routes_content import vst_host_params
    r = vst_host_params(block)
    return r.get("params", []) if isinstance(r, dict) else []


def _live_state(block):
    from .routes_content import vst_host_state
    r = vst_host_state(block)
    if not isinstance(r, dict):
        raise RuntimeError(json.loads(r.body).get("error", "plugin state unavailable"))
    return r


def _parts(recipe, mode, shown):
    """Les parties à capturer pour `mode`, selon ce qui est ALLUMÉ dans le plugin. « full » = une partie."""
    full = recipe["full"]
    if mode == "full":
        # le bloc suit la NATURE de la capture (app/designer-model.js MODEL_GEARS) : `amp` = « Head+Cab », il
        # porte son baffle ; une tête seule va sur `amp-nam` — sinon, le baffle retiré plus tard, la compile la
        # croirait déjà baffée et n'en fondrait aucun (golem.fm, 2026-10-10 : la classe du 12 septembre)
        return [{"id": "full", "label": full.get("label", "Full rig"), "gear": full["gear"],
                 "block": "amp" if full["gear"] == "amp-cab" else "amp-nam",
                 "off": full["off"]}]
    out = []
    for p in (recipe.get("split") or {}).get("parts", []):
        if any(shown.get(k) != v for k, v in (p.get("when") or {}).items()):
            continue
        if p.get("when_any") and not any(shown.get(k) == v for k, v in p["when_any"].items()):
            continue
        out.append(p)
    return out


# ── le BILAN du panneau (2026-10-10, docs/plugin-capture.md §11) ──────────────────────────────────
# golem ne coupe RIEN de ce qui bloque (« c'est l'utilisateur lui-même qui gère cela ») : il NOMME ce qui
# empêche la capture, ce que la capture contiendra et ce qui deviendra un bloc golem ; le musicien règle son plugin.
SELF_ESR_MAX = 0.01      # le seuil de l'entraîneur NAM (nam.train.core._check_v3) : au-delà, « ne sonne pas pareil deux fois »


def _applies(entry, shown):
    """`when` (tout vrai), `when_any` (au moins un), `unless` (aucun) — sur les valeurs AFFICHÉES du plugin."""
    if any(shown.get(k) != v for k, v in (entry.get("when") or {}).items()):
        return False
    if entry.get("when_any") and not any(shown.get(k) == v for k, v in entry["when_any"].items()):
        return False
    return not any(shown.get(k) == v for k, v in (entry.get("unless") or {}).items())


def _detail(spec, shown):
    """« mix 39 % », « CLN Amp », « -80.0 dB » : le réglage tel que le plugin l'affiche, ou mis à l'échelle."""
    if not spec or shown.get(spec["from"]) is None:
        return None
    raw = str(shown[spec["from"]]).strip()
    if spec.get("as") == "text":
        val = raw
    else:
        try:
            val = str(round(float(raw.split()[0]) * spec.get("scale", 1)))
        except (ValueError, IndexError):
            return None
    return " ".join(x for x in (spec.get("label"), val, spec.get("unit")) if x)


def _vendor(plugin):
    m = re.findall(r"\(([^()]*)\)", str(plugin or ""))
    return next((x for x in reversed(m) if not re.fullmatch(r"(?i)mono|stereo|\d+\s*outs?|\d+(->\d+)?ch", x)), "")


def generic_recipe(plugin, gear):
    """Un plugin SANS recette se capture ENTIER, tel que le musicien l'a réglé : il a confirmé que seuls drive,
    ampli, EQ et baffle sont allumés, et dit si le baffle du plugin est dans le son (`gear` : amp-cab | amp) —
    une nature DITE par lui, pas devinée (golem ne lit pas les pédales d'un plugin inconnu)."""
    return {"vendor": _vendor(plugin), "generic": True,
            "full": {"label": "The whole plugin", "gear": gear, "off": {}}}


def check(block, plugin, training_env=None):
    """Peut-on capturer ce bloc ? Rend le BILAN du panneau : `blockers` (nommés, à couper par le musicien),
    `captured`, `rebuilt` (blocs golem, avec leurs pertes), puis la machine. Sans recette : `recipe: False`,
    capture possible après confirmation du musicien (`needs_confirm`)."""
    recipe = recipe_for(plugin)
    env = environment() if training_env is None else training_env
    if not recipe or "full" not in recipe:
        if not env["ready"]:
            return {"ok": False, "recipe": False, "why": "This computer is missing: " + ", ".join(env["missing"]), "env": env}
        return {"ok": True, "recipe": False, "needs_confirm": True, "env": env, "blockers": [], "captured": [],
                "rebuilt": [], "split": []}
    full = recipe["full"]
    shown = {p.get("name"): p.get("display") for p in _live_params(block)}
    blockers = [{"label": r["label"], "kind": r.get("kind"), "where": r.get("where"), "detail": _detail(r.get("detail"), shown)}
                for r in full.get("refuse") or [] if _applies(r, shown)]
    captured = [{"label": c["label"], "detail": _detail(c.get("detail"), shown)}
                for c in full.get("captured") or [] if _applies(c, shown)]
    rebuilt = [{"label": t.get("show") or t["block"], "detail": _detail(t.get("detail"), shown),
                "loss": t.get("loss") if t.get("loss_if") and _applies({"when": t["loss_if"]}, shown) else None}
               for t in recipe.get("translate", []) if _applies(t, shown)]
    from . import plugin_recipes
    local = plugin_recipes.load(plugin) or {}
    source = ({"from": "golem.fm", "shared": bool(local.get("shared")), "validated_at": local.get("validated_at")}
              if local.get("state") == "validated" else {"from": "built-in"})
    out = {"recipe": True, "source": source, "env": env, "blockers": blockers, "captured": captured, "rebuilt": rebuilt,
           "label": full.get("label"), "kept": full.get("keeps", []), "dropped": full.get("drops", []), "gear": full.get("gear")}
    if blockers:
        names = ", ".join(b["label"] for b in blockers)
        return dict(out, ok=False, why=f"{names} {'is' if len(blockers) == 1 else 'are'} on. {full.get('refuse_why', '')}".strip())
    if not env["ready"]:
        return dict(out, ok=False, why="This computer is missing: " + ", ".join(env["missing"]))
    split = _parts(recipe, "split", shown) if recipe.get("split") else []
    return dict(out, ok=True, split=[{"id": p["id"], "label": p["label"], "gear": p["gear"]} for p in split])


def self_esr(target, n_input, t_validate=432_000):
    """Le plugin sonne-t-il pareil DEUX fois ? Le signal v3 joue le même passage de 9 s au début et à 3:01 ;
    l'entraîneur NAM compare les deux sorties (self-ESR) mais ne fait que l'IMPRIMER. Un plugin sans effet
    temporel rend 0 au bit près (mesuré 2026-10-10 sur les 7 rendus de ce poste) ; un chorus, un delay ou une
    reverb oubliés montent au-dessus de SELF_ESR_MAX. Rend l'ESR, ou None si le rendu est trop court."""
    x, _rate = read_wav(target)
    if len(x) < n_input or n_input < 2 * t_validate:
        return None
    a, b = x[:t_validate], x[n_input - t_validate:n_input]
    den = sum(v * v for v in b)
    return sum((u - v) ** 2 for u, v in zip(a, b)) / den if den > 0 else None


def start(block, plugin, patch_name, mode="full", epochs=100, name=None, dest="new", new_patch=None,
          confirmed=False, gear=None):
    """`name` : le nom de la capture dans la bibliothèque (défaut « <patch> — <plugin> »). `dest` : où va la
    chaîne à la fin — « new » (défaut, 2026-10-05 : « un patch que j'aime, je ne vais pas avoir envie de
    l'écraser ») = un NOUVEAU patch nommé `new_patch`, « replace » = dans le patch ouvert. Retenus dans le job :
    la capture dure 10-17 min, le tiroir peut avoir été fermé entre-temps. Sans recette : `confirmed` (le musicien
    a vérifié son plugin) et `gear` (« amp-cab » si le baffle du plugin est dans le son, « amp » sinon) sont exigés."""
    if mode not in MODES:
        return {"ok": False, "error": "unknown capture mode"}
    with _lock:
        if _job.get("state") in ("render", "train", "test", "install", "cancelling"):
            return {"ok": False, "error": "A capture is already running"}
        c = check(block, plugin)
        if not c["ok"]:
            return {"ok": False, "error": c["why"]}
        if mode == "split" and not c["split"]:
            return {"ok": False, "error": "This plugin cannot be split into captures yet"}
        if not c.get("recipe"):
            if not confirmed:
                return {"ok": False, "error": "Check the plugin first: only drive, amp, EQ and cab may be on"}
            if gear not in ("amp-cab", "amp"):
                return {"ok": False, "error": "Say whether the plugin's cab is in the sound"}
        if dest not in ("new", "replace"):
            return {"ok": False, "error": "unknown destination"}
        short = str(plugin).split(':', 1)[-1].split('(')[0].strip()
        name = (str(name or "").strip() or f"{patch_name} — {short}")[:80]
        new_patch = (str(new_patch or "").strip() or f"{patch_name} — capture")[:80]
        # REPRISE (2026-10-05) : une capture qui a échoué APRÈS l'entraînement (« capture test failed ») ne
        # refait ni le rendu ni les ~7 min d'entraînement — le dernier dossier du même nom et du même mode,
        # non terminé, est repris ; ses parties déjà entraînées sont gardées (le rendu et la mesure non)
        root = train_home().parent / "captures"
        prev = sorted(root.glob(f"{_slug(name)}-{mode}-*"), key=lambda d: d.name, reverse=True) if root.is_dir() else []
        work = next((d for d in prev if not (d / "done.json").exists()
                     and any((d / x / "train.json").is_file() or (d / x / "cab.wav").is_file() for x in ("full", "pedal", "head", "cab"))),
                    root / f"{_slug(name)}-{mode}-{time.strftime('%Y%m%d-%H%M%S')}")
        _cancel.clear()
        _job.clear()
        _set(state="render", msg="Rendering the training signal through the plugin…", block=block, mode=mode,
             plugin=plugin, name=name, patch=patch_name, dest=dest, new_patch=new_patch, work=str(work),
             started=time.time(), error=None, result=None, warning=None, self_esr=None,
             gear=None if c.get("recipe") else gear)
    threading.Thread(target=_worker, args=(block, plugin, name, work, mode, epochs), daemon=True).start()
    return {"ok": True, "job": status()}


def _worker(block, plugin, name, work, mode, epochs):
    try:
        work.mkdir(parents=True, exist_ok=True)
        recipe = recipe_for(plugin) or generic_recipe(plugin, status().get("gear") or "amp-cab")
        state = _live_state(block)
        # une reprise n'a de sens que pour le MÊME son : si l'état du plugin a changé depuis (un potard
        # tourné), les parties entraînées sont celles d'un autre son -> dossier neuf, tout est refait
        old = work / "state.json"
        if old.is_file():
            try:
                same = json.loads(old.read_text(encoding="utf-8")).get("chunk") == state.get("chunk")
            except ValueError:
                same = False
            if not same:
                work = work.parent / f"{work.name.rsplit('-', 2)[0]}-{time.strftime('%Y%m%d-%H%M%S')}"
                work.mkdir(parents=True, exist_ok=True)
                _set(work=str(work))
                log.info(f"capture : réglages du plugin changés depuis la tentative précédente — tout est refait dans {work}")
        (work / "state.json").write_text(json.dumps(state), encoding="utf-8")
        shown = {p.get("name"): p.get("display") for p in _live_params(block)}
        parts = _parts(recipe, mode, shown)
        done, chain, trains = [], [], {}
        for n, part in enumerate(parts, 1):
            pw = work / part["id"]
            pw.mkdir(exist_ok=True)
            step = f" — {part['label']}, {n}/{len(parts)}" if len(parts) > 1 else ""
            if part.get("ir"):
                _set(state="render", msg=f"Capturing the cab as an impulse response{step}…")
                r = {"set": None, "resumed": True} if (pw / "cab.wav").is_file() else capture_ir(plugin, state["chunk"], part["off"], pw)
                done.append((part, pw / "cab.wav", r, None))
                chain.append(("ir", pw / "cab.wav"))
                continue
            if all((pw / f).is_file() for f in ("train.json", "capture.nam", "capture-v07.nam")):
                res = json.loads((pw / "train.json").read_text(encoding="utf-8"))      # déjà entraînée : reprise
                r = {"set": res.get("set"), "resumed": True}
                log.info(f"capture : partie {part['id']} reprise de {pw}")
            else:
                _set(state="render", msg=f"Rendering the training signal through the plugin{step}…")
                r = render(plugin, state["chunk"], part["off"], train_home() / "v3_0_0.wav", pw, "target")
                if r["peak"] < 1e-3:
                    raise RuntimeError(f"the plugin rendered silence{step} — nothing to capture")
                # AU-DESSUS DE 1,0 n'est pas saturé : le rendu est en flottant (32 bits). Mesuré le 2026-10-10 sur le
                # Fortin Nameless, partie « pédale » (Booster + Hex, ampli coupé) : crête 1,457 (+3,3 dBFS) — une pédale
                # de boost POUSSE l'ampli, c'est son rôle. On ramène le rendu à −1 dBFS pour l'entraînement et on RENDRA
                # ce gain par le réglage « output » du bloc golem (−20…+20 dB) : l'ampli capturé reçoit le même niveau.
                r["output_db"] = 0.0
                if r["peak"] >= 0.999:
                    gain_db = 20 * math.log10(r["peak"] / 0.891)
                    if gain_db > 20:
                        raise RuntimeError(f"the plugin output is {gain_db:.0f} dB too hot{step} — more than a golem "
                                           f"block can give back; lower its output level, then capture again")
                    y, _rate = read_wav(pw / "target.wav")
                    k = 10 ** (-gain_db / 20)
                    write_wav(pw / "target.wav", [v * k for v in y])
                    r["output_db"] = round(gain_db, 2)
                    log.info(f"capture : crête {r['peak']:.3f}{step} — rendu ramené à −1 dBFS, rendu par output +{gain_db:.2f} dB")
                # UN AVERTISSEMENT, jamais une coupure (2026-10-10) : le musicien décide d'annuler ou non
                try:
                    esr = self_esr(pw / "target.wav", len(read_wav(train_home() / "v3_0_0.wav")[0]))
                except Exception as e:                  # la mesure ne doit jamais faire tomber une capture
                    log.warning(f"capture : self-ESR non mesurée ({e})")
                    esr = None
                r["self_esr"] = esr
                if esr is not None and esr > SELF_ESR_MAX:
                    _set(self_esr=round(esr, 4),
                         warning="The plugin doesn't sound the same when played twice: a chorus, delay, reverb or "
                                 "other moving effect is probably still on. The capture will come out blurred. Cancel "
                                 "and check the plugin, or let it finish.")
                    log.warning(f"capture : self-ESR {esr:.4f} > {SELF_ESR_MAX}{step} — effet temporel probable")
                res = train(pw, epochs, progress=lambda dev, s=step: _set(state="train",
                                                                             msg=f"Training the NAM model{s} on {dev}…"))
                res["set"] = r.get("set")
                res["self_esr"] = r.get("self_esr")
                res["output_db"] = r.get("output_db") or 0.0
                (pw / "train.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
            _set(state="test", msg=f"Checking the capture plays in this computer's NAM{step}…")
            pc = playback_check(pw / "capture.nam", pw / "playcheck", reference=pw / "capture-v07.nam")
            res["playback"] = pc
            if pc.get("ok") is False:
                raise RuntimeError(f"the capture does not play correctly in NAM{step} "
                                   f"(match {pc['null_vs_model_db']} dB, dry {pc['null_vs_dry_db']} dB)")
            trains[part["id"]] = res
            done.append((part, pw / "capture.nam", r, res))
            # la MESURE fait jouer le modèle par la bibliothèque NAM 0.13, qui ne relit PAS l'ancien schéma
            # (capture.nam) : elle prend l'original. Le fichier rangé, lui, est vérifié par le plugin ci-dessus.
            chain.append(("nam", pw / "capture-v07.nam"))
            if res.get("output_db"):                       # le gain retiré à l'entraînement, rendu avant l'étage suivant
                chain.append(("gain", res["output_db"]))
        _set(state="test", msg="Comparing with the plugin…", train=trains)
        t = test(work, plugin, state["chunk"], recipe["full"]["off"], chain)
        _set(state="install", msg="Adding to your library…", test=t)
        core = []
        for part, f, r, res in done:
            pname = name if mode == "full" else f"{name} {part['label']}"
            entry = install(f, {"name": pname, "gear": part["gear"], "vendor": recipe.get("vendor"),
                                "plugin": plugin, "patch": name, "block": block, "mode": mode, "part": part["id"],
                                "set": r.get("set"), "train": res, "test": t,
                                "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "private": True})
            # le bloc se RECONNAÎT dans le Designer (icône, nom choisi) sans changer de moteur : un bloc
            # ampli/pédale/baffle ordinaire, lisible partout (Linux compris), qui porte son ORIGINE
            core.append({"type": part["block"], "ref": entry["id"], "model": entry["models"][0]["id"],
                         "label": pname,
                         # le gain retiré à l'entraînement, rendu par le bloc — sauf sur un bloc que la compile NORMALISE
                         # (amp, amp-nam : compile_rig.NORMALIZED_TYPES), où il s'ajouterait par-dessus la normalisation ;
                         # le baffle qui suit un ampli est linéaire, le niveau n'y change pas le timbre. Une PÉDALE n'est
                         # pas normalisée (« un boost doit booster ») : c'est là que le gain compte, l'ampli qui suit ne l'est pas.
                         **({"params": {"output": round(res["output_db"], 1)}}
                            if (res or {}).get("output_db") and part["block"] not in _normalized() else {}),
                         "origin": {"kind": "vst-capture", "plugin": plugin, "patch": status().get("patch"),
                                    "mode": mode, "part": part["id"], "at": time.strftime("%Y-%m-%d"),
                                    "null_db": round(((t.get("synth") or {}).get("null_db") or 0), 1) or None}})
        (work / "done.json").write_text(json.dumps({"core": core, "at": time.time()}), encoding="utf-8")
        _set(state="done", msg="Capture ready", result={"name": name, "mode": mode, "core": core})
        log.info(f"capture {mode} {name} : {[c['ref'] for c in core]}, train {trains}, test {t}")
    except Exception as e:
        if _cancel.is_set():                      # l'arrêt d'un processus remonte en erreur : c'est l'annulation
            log.info("capture annulée")
            _set(state="cancelled", msg="Capture cancelled", error=None)
            return
        log.warning(f"capture échouée : {e}")
        _set(state="error", msg=str(e), error=str(e))


# ── 6. la chaîne qui remplace le bloc VST : les captures + les sections TRADUITES ──────────────
def _effect_defs():
    try:
        e = json.loads((ROOT / "library" / "catalog" / "effects.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    e = e.get("effects", e)
    return {x.get("type"): x for x in e} if isinstance(e, list) else e


def replacement(block, plugin):
    """[blocs] qui remplacent le bloc VST : gate traduit, la (les) capture(s) du DERNIER job de ce bloc,
    delay et reverb traduits. Les valeurs viennent des paramètres AFFICHÉS du plugin (ce qu'on entend),
    bornées aux plages du bloc GoleM. Chaque traduction approximative le dit (`notes`)."""
    job = status()
    if job.get("block") != block or job.get("state") != "done":
        return {"error": "No finished capture for this block"}
    recipe = recipe_for(plugin) or {}
    shown = job.get("captured_params") or {p.get("name"): str(p.get("display")) for p in _live_params(block)}
    defs = _effect_defs()
    before, after, notes = [], [], []
    for t in recipe.get("translate", []):
        if any(shown.get(k) != v for k, v in (t.get("when") or {}).items()):
            continue
        if any(shown.get(k) == v for k, v in (t.get("unless") or {}).items()):
            continue
        d = defs.get(t["block"]) or {}
        pdefs = {p["id"]: p for p in d.get("params", [])}
        params = {}
        for pid, spec in t["params"].items():
            raw = shown.get(spec["from"])
            if raw is None:
                continue
            pd = pdefs.get(pid, {})
            if spec.get("as") == "text":
                if raw in (pd.get("options") or [raw]):
                    params[pid] = raw
                continue
            try:
                v = float(raw.split()[0]) * spec.get("scale", 1)
            except (ValueError, IndexError):
                continue
            if pd.get("min") is not None and pd.get("max") is not None:
                v = min(max(v, pd["min"]), pd["max"])
            params[pid] = round(v, 3)
        b = {"type": t["block"], "label": t.get("label") or d.get("name"), "params": params}
        (before if t.get("at") == "before" else after).append(b)
        if t.get("approx"):
            notes.append(f"{b['label']}: {t['approx']}")
    return {"blocks": before + list(job["result"]["core"]) + after, "notes": notes}


# ── 7. poser les outils de capture sur ce poste (une fois, depuis le tiroir) ─────────────────────
# Ce que le 2026-10-05 a fait à la main, en tâche de fond : un Python isolé, torch (CUDA si une carte
# NVIDIA RÉPOND, sinon processeur ; macOS : torch standard, qui porte MPS), l'entraîneur NAM ÉPINGLÉ
# (0.13 : la version mesurée), le signal v3 vérifié par son empreinte (l'entraîneur le reconnaît à son
# MD5 — un autre fichier ne doit jamais passer pour lui), la config WaveNet de la MÊME version.
NAM_VERSION = "0.13.0"
V3_MD5 = "36cd1af62985c2fac3e654333e36431e"
V3_URL = "https://drive.usercontent.google.com/download?id=1Pgf8PdE0rKB1TD4TRPKbpNo1ByR3IOm9&export=download&confirm=t"
WAVENET_URL = f"https://raw.githubusercontent.com/sdatkinson/neural-amp-modeler/v{NAM_VERSION}/nam_full_configs/models/wavenet.json"
_setup = {"state": "idle"}


def setup_status():
    return dict(_setup)


def _has_nvidia():
    if sys.platform != "win32" or os.environ.get("GOLEM_NAM_FORCE_CPU"):
        return False
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    r = subprocess.run([exe, "-L"], capture_output=True, text=True, creationflags=NO_WINDOW)
    return r.returncode == 0 and "GPU" in r.stdout


def _download(url, dst, md5=None):
    import hashlib, urllib.request
    tmp = Path(str(dst) + ".part")
    h = hashlib.md5()
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            h.update(b)
    if md5 and h.hexdigest() != md5:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"{Path(dst).name}: unexpected content (checksum mismatch)")
    os.replace(tmp, dst)


def start_setup():
    if sys.platform not in ("win32", "darwin"):
        return {"ok": False, "error": "Capture tools are installed on Windows or macOS"}
    if _setup.get("state") == "running":
        return {"ok": False, "error": "Already installing"}
    _setup.clear()
    _setup.update(state="running", msg="Preparing…", started=time.time(), error=None)
    threading.Thread(target=_setup_worker, daemon=True).start()
    return {"ok": True, "setup": setup_status()}


def _setup_worker():
    def step(msg):
        _setup.update(msg=msg, updated=time.time())
        log.info(f"outils de capture : {msg}")

    def pip(py, *args):
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", *args], capture_output=True, text=True,
                           creationflags=NO_WINDOW)
        if r.returncode:
            raise RuntimeError("pip: " + ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:300])

    try:
        home = train_home()
        home.mkdir(parents=True, exist_ok=True)
        cuda = _has_nvidia()
        venv = home / ("venv-cuda" if cuda else "venv")
        py = _venv_python(venv)
        if not py.exists():
            step("Creating a private Python environment…")
            base = getattr(sys, "_base_executable", None) or sys.executable
            subprocess.run([base, "-m", "venv", str(venv)], check=True, capture_output=True, creationflags=NO_WINDOW)
            pip(py, "--upgrade", "pip")
        step("Downloading PyTorch for " + ("the NVIDIA graphics card (~2.5 GB)…" if cuda
                                           else "this computer's processor…" if sys.platform == "win32"
                                           else "this Mac (Apple GPU)…"))
        if cuda:
            pip(py, "torch", "--index-url", "https://download.pytorch.org/whl/cu128")
        elif sys.platform == "win32":
            pip(py, "torch", "--index-url", "https://download.pytorch.org/whl/cpu")
        else:
            pip(py, "torch")
        step(f"Installing the NAM trainer {NAM_VERSION}…")
        pip(py, f"neural-amp-modeler=={NAM_VERSION}")
        if not (home / "v3_0_0.wav").is_file():
            step("Downloading the NAM training signal (27 MB)…")
            _download(V3_URL, home / "v3_0_0.wav", V3_MD5)
        (home / "cfg").mkdir(exist_ok=True)
        if not (home / "cfg" / "wavenet.json").is_file():
            step("Downloading the WaveNet model settings…")
            _download(WAVENET_URL, home / "cfg" / "wavenet.json")
        env = environment()
        if not env["ready"]:
            raise RuntimeError("still missing: " + ", ".join(env["missing"]))
        _setup.update(state="done", msg=f"Capture tools ready on {env['device']}", updated=time.time())
    except Exception as e:
        log.warning(f"outils de capture : échec : {e}")
        _setup.update(state="error", msg=str(e), error=str(e), updated=time.time())


# ── 8. le FORMAT du fichier : ce que le plugin qui JOUE sait lire ───────────────────────────────
# Mesuré le 2026-10-05 (« j'ai demandé un son high gain et j'ai un son clair ») : l'entraîneur NAM 0.13
# écrit `version 0.7.0`, des couches décrites avec le NOUVEAU schéma (`kernel_sizes`, `gating_mode`,
# `*_film`, `slimmable`…). Le NAM VST3 0.7.13 de Windows ne le lit pas — et laisse passer la guitare À
# SEC, sans une erreur : rendu du VRAI plugin = la DI au dixième de dB (−26,4 dBFS, crête 21 dB), quand
# la bibliothèque NAM, elle, saturait le même fichier. La mesure de l'étape 3 utilisait la bibliothèque :
# elle ne pouvait pas le voir. Une capture WaveNet STANDARD n'utilise aucune nouveauté du schéma : même
# réseau, mêmes 13 802 poids, dans le même ordre — on la réécrit à l'ancien schéma (`version 0.5.x`),
# celui des captures de la bibliothèque qui jouent partout. Toute nouveauté RÉELLE (FiLM, groupes,
# goulot, gating, activations mêlées) refuse la conversion : jamais une traduction approximative.
def legacy_nam(src, dst):
    d = json.loads(Path(src).read_text(encoding="utf-8"))
    if d.get("architecture") != "WaveNet":
        raise RuntimeError(f"cannot convert architecture {d.get('architecture')}")
    layers = []
    for l in d["config"]["layers"]:
        ks, acts, gates = l.get("kernel_sizes") or [], l.get("activation") or [], l.get("gating_mode") or []
        names = {(a or {}).get("type") if isinstance(a, dict) else a for a in acts}
        film = [k for k, v in l.items() if k.endswith("_film") and isinstance(v, dict) and v.get("active")]
        problems = []
        if len(set(ks)) != 1:
            problems.append("mixed kernel sizes")
        if len(names) != 1:
            problems.append("mixed activations")
        if any(g not in (None, "none") for g in gates):
            problems.append("gating")
        if film:
            problems.append("FiLM")
        if l.get("bottleneck") not in (None, l.get("channels")):
            problems.append("bottleneck")
        if (l.get("head1x1") or {}).get("active") or not (l.get("layer1x1") or {"active": True}).get("active"):
            problems.append("1x1 layers")
        if any(l.get(k) not in (None, 1) for k in ("groups_input", "groups_input_mixin")) or \
                (l.get("layer1x1") or {}).get("groups", 1) != 1:
            problems.append("groups")
        if l.get("slimmable") or any(s for s in (l.get("secondary_activation") or [])):
            problems.append("slimmable / secondary activation")
        if problems:
            raise RuntimeError("capture uses new NAM features: " + ", ".join(problems))
        head = l.get("head") or {}
        layers.append({"input_size": l["input_size"], "condition_size": l["condition_size"],
                       "head_size": head.get("out_channels"), "channels": l["channels"], "kernel_size": ks[0],
                       "dilations": l["dilations"], "activation": names.pop(), "gated": False,
                       "head_bias": bool(head.get("bias"))})
    out = dict(d)
    out["version"] = "0.5.4"
    out["config"] = {"layers": layers, "head": d["config"].get("head"), "head_scale": d["config"]["head_scale"]}
    Path(dst).write_text(json.dumps(out), encoding="utf-8")
    return out


# exécuté DANS le venv : le rendu du VRAI plugin NAM doit être la capture (nul contre l'inférence de la
# bibliothèque NAM) et PAS la guitare sèche (nul contre l'entrée). Rend {null_vs_model_db, null_vs_dry_db}.
_PLAYCHECK = r"""
import json, sys
import numpy as np, torch
from nam.models import init_from_nam
cap, x_path, y_path = sys.argv[1:4]
rd = lambda p: np.fromfile(p, dtype="<f4", offset=44).astype(float)
x, y = rd(x_path), rd(y_path)
m = init_from_nam(json.load(open(cap))); m.eval()
with torch.no_grad():
    ref = m(torch.tensor(x, dtype=torch.float32), pad_start=True).numpy().astype(float)
def null(a, b):
    n = min(len(a), len(b)); a, b = a[:n], b[:n]; best = 0.0
    for lag in range(-256, 257, 1):
        a2, b2 = (a[lag:], b[:n - lag]) if lag >= 0 else (a[:n + lag], b[-lag:])
        g = np.dot(a2, b2) / (np.dot(b2, b2) + 1e-30)
        r = 20 * np.log10(np.sqrt(np.mean((a2 - g * b2) ** 2)) / (np.sqrt(np.mean(a2 ** 2)) + 1e-15) + 1e-15)
        best = min(best, r)
    return best
print(json.dumps({"null_vs_model_db": round(null(ref, y), 1), "null_vs_dry_db": round(null(x, y), 1)}))
"""


def playback_check(nam_file, work, reference=None, python_exe=None):
    """La capture JOUE-T-ELLE dans le plugin NAM de cette machine ? (Windows/macOS) Ce que la mesure de la
    bibliothèque NAM ne voit pas : un format que le plugin ne lit pas le fait passer à sec, sans erreur."""
    if sys.platform not in ("win32", "darwin"):
        return {"skipped": "linux"}
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    write_wav(work / "check-in.wav", synth_di(seconds=8))
    # réglé comme le rig le pose (golem_rig load_native_core / load_windows_nam_block) : gate et égaliseur
    # du NAM coupés — à ses défauts, le gate rognait les fins de notes et la mesure accusait la capture
    # ⚠ mesuré le 2026-10-05 : le même rendu sort tantôt le bon son, tantôt un SILENCE complet — le rendu
    # hors ligne part parfois avant que le NAM ait fini de charger son modèle. Un rendu muet sur une
    # entrée qui ne l'est pas n'est pas un verdict : on recommence (3 fois au plus).
    for attempt in range(3):
        r = render("VST3: NeuralAmpModeler", "", {"NoiseGateActive": "off", "ToneStack": "off"},
                   work / "check-in.wav", work, "check-nam", timeout=180, nam_model=str(Path(nam_file).resolve()))
        if r["peak"] > 1e-4:
            break
        log.info(f"vérif de lecture : rendu muet (essai {attempt + 1}), on recommence")
    else:
        return {"ok": False, "null_vs_model_db": 0.0, "null_vs_dry_db": 0.0, "why": "NAM rendered silence 3 times"}
    (work / "_playcheck.py").write_text(_PLAYCHECK, encoding="utf-8")
    py = python_exe
    if py is None:
        py, _d, _k = trainer_python()
    # la bibliothèque NAM 0.13 ne relit PAS l'ancien schéma : la référence est le modèle d'origine
    r = _run([py, work / "_playcheck.py", reference or nam_file, work / "check-in.wav", work / "check-nam.wav"])
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if r.returncode or not lines:
        raise RuntimeError("playback check failed: " + ((r.stdout + r.stderr).strip().splitlines() or ["?"])[-1][:200])
    res = json.loads(lines[-1])
    # le critère : le rendu ressemble au MODÈLE, et bien plus qu'à la guitare sèche. Mesuré le 2026-10-05 :
    # fichier illisible -> modèle −0,8 dB (passe à sec) ; ampli converti -> −30 ; pédale peu saturée -> −23,6
    # (ses graves passent, les filtres internes du plugin pèsent plus) contre −2,9 face au sec
    res["ok"] = res["null_vs_model_db"] <= -18 and res["null_vs_model_db"] < res["null_vs_dry_db"] - 10
    return res


def fix_library():
    """Les captures déjà rangées au nouveau format (avant le 2026-10-05) : réécrites à l'ancien schéma sous
    un NOUVEAU nom (`…-std.nam`, pour que le moteur recharge à coup sûr), l'entrée de catalogue suivie.
    Rend [(id, ancien, nouveau)]."""
    from .store import _read_json, _write_json_atomic
    cat = _read_json(C.CATALOG, {"tones": []}) or {"tones": []}
    done = []
    for t in cat.get("tones", []):
        if t.get("source_group") != "plugin-capture" or t.get("format") != "nam":
            continue
        for m in t.get("models", []):
            f = ROOT / m["file"]
            if not f.is_file() or f.stem.endswith("-std"):
                continue
            if json.loads(f.read_text(encoding="utf-8")).get("version", "").startswith("0.5"):
                continue
            new = f.with_name(f.stem + "-std.nam")
            legacy_nam(f, new)
            pc = playback_check(new, ROOT / "assets" / ".cache" / "playcheck" / f.stem, reference=f)
            if not pc.get("ok"):
                new.unlink(missing_ok=True)
                raise RuntimeError(f"{t['id']}: converted capture does not play correctly ({pc})")
            done.append((t["id"], m["file"], new.relative_to(ROOT).as_posix()))
            m["file"] = new.relative_to(ROOT).as_posix()
    if done:
        _write_json_atomic(C.CATALOG, cat)
    return done
