# SPDX-License-Identifier: GPL-3.0-or-later
"""LE BANC DU PREMIER USAGE d'un plugin du bloc VST Host, sous Linux (2026-11-09, docs/platforms.md §6.1, lot 3).

Un bloc d'usine a été mesuré avant d'être offert (tools/check-block-stall.py, quarantaine dans effects.json). Un plugin
choisi par le musicien dans la liste de REAPER, non : ReaPitch fige tout le moteur 435 ms à l'allumage, GxEchoCat
520 ms, GxDetune corrompt le tas de REAPER. Avant qu'un plugin JAMAIS ESSAYÉ entre dans le rig qui joue, golem le
charge dans un REAPER SÉPARÉ (son propre dossier -cfgfile, audio factice, l'écran virtuel : rien ne sonne, rien ne
s'affiche, le REAPER du rack n'est pas touché), l'allume et l'éteint plusieurs fois en mesurant l'horloge audio :
  · REAPER séparé mort          → « crashed REAPER »                     → quarantaine (par nom de plugin)
  · trace figée (fil principal) → « froze REAPER »                       → quarantaine
  · horloge audio arrêtée       → « stopped the audio engine for N ms »   → quarantaine
  · sinon                       → ok, le bloc entre dans le rig (recall.reapply_sandbox)
Le verdict est gardé par plugin dans config/vst-trials.json (état local du rack, CLAUDE.md règle 2) : un plugin n'est
essayé qu'une fois. Tant qu'il n'a pas de verdict, rig._drop_quarantined le retire du rig EN LE DISANT, et blockstatus
le montre « being tested ». Windows/macOS : inchangés (pas de banc) — le contrat est celui de Linux."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time

from . import config as C
from .golog import get

log = get("plugin-trial")

TRIALS = os.path.join(C.CONFIG_DIR, "vst-trials.json")
METER = """desc:golem trial meter (le plus long intervalle entre deux passages du fil audio)
options:gmem=golem_trial
@init
tm_last = 0;
@block
tm_t = time_precise();
gmem[1] > 0 ? ( gmem[0] = 0; gmem[1] = 0; tm_last = 0; );
tm_last > 0 && tm_t - tm_last > gmem[0] ? gmem[0] = tm_t - tm_last;
tm_last = tm_t;
gmem[2] += 1;
"""
STALL_MS = 50             # au-delà, un trou s'entend (budget d'une scène : 40 ms ; bruit du banc mesuré le 2026-11-09 : 12 ms ; GxEchoCat : 520 ms)
LOAD_TIMEOUT_S = 90       # une grosse suite peut mettre longtemps à se charger la première fois
FROZEN_S = 15             # trace immobile aussi longtemps = le fil principal du REAPER séparé ne tourne plus
CYCLES = 4                # allumages / extinctions mesurés

_lock = threading.Lock()
_running = {}             # plugin -> thread


def applies():
    """Le banc ne concerne que Linux (docs/platforms.md §6.1) ; GOLEM_VST_TRIAL=0 le coupe (dépannage)."""
    return sys.platform.startswith("linux") and os.environ.get("GOLEM_VST_TRIAL", "1") != "0"


def _read():
    try:
        with open(TRIALS, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def verdict(plugin):
    """{ok, at, why?, stall_ms?} si ce plugin a déjà été essayé ici, sinon None."""
    v = _read().get(str(plugin or ""))
    return v if isinstance(v, dict) and "ok" in v else None


def failed(plugin):
    """La raison (anglais, pour le musicien) si le banc a refusé ce plugin, sinon None."""
    v = verdict(plugin)
    return (v.get("why") or "failed its first test") if v and not v.get("ok") else None


def pending(plugin):
    """Vrai si ce plugin doit encore passer le banc avant de jouer (Linux, pas de verdict)."""
    return applies() and bool(plugin) and verdict(plugin) is None


def running(plugin):
    with _lock:
        t = _running.get(plugin)
        return bool(t and t.is_alive())


def _record(plugin, ok, why=None, **extra):
    from .store import _write_json_atomic
    with _lock:
        d = _read()
        d[plugin] = {"ok": bool(ok), "at": int(time.time()), **({"why": why} if why else {}), **extra}
        _write_json_atomic(TRIALS, d, indent=1)


def start(plugin, on_done=None):
    """Lance l'essai en tâche de fond s'il n'a ni verdict ni essai en cours. `on_done(plugin, ok)` à la fin."""
    if not pending(plugin):
        return False
    with _lock:
        t = _running.get(plugin)
        if t and t.is_alive():
            return False

        def run():
            ok = False
            try:
                ok, why, extra = trial(plugin)
                _record(plugin, ok, why, **extra)
                (log.info if ok else log.warning)(f"banc « {plugin} » : {'ok' if ok else 'REFUSÉ — ' + str(why)} {extra}")
            except Exception as e:                       # le banc n'a pas pu mesurer : pas de verdict, on réessaiera
                log.warning(f"banc « {plugin} » : pas de mesure ({e})")
            finally:
                with _lock:
                    _running.pop(plugin, None)
            if on_done:
                try:
                    on_done(plugin, ok)
                except Exception as e:
                    log.warning(f"banc « {plugin} » : suite non faite ({e})")

        t = threading.Thread(target=run, name="golem-vst-trial", daemon=True)
        _running[plugin] = t
        t.start()
    return True


def _lua(s):
    return json.dumps(str(s))                          # une chaîne JSON est une chaîne Lua valide (échappements \" \\)


def script(plugin, trace):
    """Le Lua joué au démarrage du REAPER séparé : charge, allume/éteint, mesure l'horloge audio, écrit la trace."""
    return f'''local TRACE, PLUGIN, CYCLES = {_lua(trace)}, {_lua(plugin)}, {CYCLES}
local function w(s) local f = io.open(TRACE, "a"); if f then f:write(s .. "\\n"); f:close() end end
w("start")
reaper.InsertTrackAtIndex(0, false)
local tr = reaper.GetTrack(0, 0)
-- le MÈTRE d'abord (un JSFX qui note le plus long intervalle entre deux @block, dans gmem) : un blocage du fil audio
-- s'y lit même quand l'audio factice rattrape son retard ensuite, et même quand le fil principal est figé avec lui
reaper.TrackFX_AddByName(tr, "JS:golem_trial_meter", false, -1)
local fx = reaper.TrackFX_AddByName(tr, PLUGIN, false, -1)
if not fx or fx < 0 then w("error=the plugin did not load"); return end
reaper.TrackFX_SetEnabled(tr, fx, false)
-- comme une piste du rig : armée, monitoring, « aucun enregistrement » (docs/pitfalls/reaper.md) — sinon REAPER
-- calcule ses effets EN AVANCE sur d'autres fils et un blocage du plugin passe inaperçu
reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
w("loaded")
reaper.gmem_attach("golem_trial")
reaper.OnPlayButton()
local t0 = reaper.time_precise()
local step, next_step = 0, t0 + 1.5                    -- 1,5 s de rodage, puis un geste toutes les 0,6 s
local function tick()
  local t = reaper.time_precise()
  if t >= next_step then
    step = step + 1
    if step == 1 then reaper.gmem_write(1, 1) end      -- fin du rodage : le mètre repart de zéro
    if step > CYCLES * 2 then
      reaper.OnStopButton()
      local blocks = reaper.gmem_read(2)
      if blocks < 10 then w("error=the test engine processed no audio"); return end
      w(string.format("stall_ms=%d", math.floor(reaper.gmem_read(0) * 1000 + 0.5)))
      w("done")
      return
    end
    reaper.TrackFX_SetEnabled(tr, fx, step % 2 == 1)
    w("toggle " .. step)
    next_step = t + 0.6
  end
  w("beat")
  reaper.defer(tick)
end
reaper.defer(tick)
'''


def reaper_binary():
    if os.environ.get("REAPER_BIN"):
        return Path(os.environ["REAPER_BIN"])
    found = shutil.which("reaper")
    for cand in ([Path(found)] if found else []) + [Path.home() / "opt/REAPER/reaper", Path("/opt/REAPER/reaper")]:
        if cand.is_file():
            return cand
    raise RuntimeError("REAPER not found")


def _bench_dir(work):
    """Un dossier REAPER vierge : audio factice (Linux : linux_audio_mode=2, mesuré sur 7.82), licence et caches de
    plugins de la machine (sans eux, une boîte « EVALUATION » modale ou un rescan complet — plugin_capture)."""
    from .reaper_license import resource_dir
    bench = Path(work) / "reaper"
    (bench / "Scripts").mkdir(parents=True, exist_ok=True)
    (bench / "reaper.ini").write_text("[REAPER]\nnolastproject=1\nopenallrecent=0\nsplashfast=1\nverchk=0\n"
                                      "linux_audio_mode=2\nlinux_audio_srate=48000\n", encoding="ascii")
    real = Path(resource_dir())
    names = ["reaper-license.rk"] + [p.name for p in real.glob("reaper-*plugins*.ini")] + \
            [p.name for p in real.glob("reaper-clap-*.ini")]
    for n in dict.fromkeys(names):
        if (real / n).is_file():
            shutil.copyfile(real / n, bench / n)
    (bench / "Effects").mkdir(exist_ok=True)
    (bench / "Effects" / "golem_trial_meter.jsfx").write_text(METER, encoding="utf-8")
    return bench


def _display():
    """L'écran virtuel du rack (Xvfb, GOLEM_XVFB_DISPLAY, :99 — provision/start.sh) s'il tourne, sinon None : le banc ne
    s'ouvre JAMAIS sur l'écran de l'utilisateur (même quand `golem desktop --dev` y met le REAPER du rack)."""
    d = os.environ.get("GOLEM_XVFB_DISPLAY", ":99")
    n = d.lstrip(":").split(".")[0]
    return d if n.isdigit() and os.path.exists(f"/tmp/.X11-unix/X{n}") else None


def trial(plugin, timeout_s=None):
    """Rend (ok, why, extra). Lève une exception si le banc n'a pas pu mesurer (REAPER absent, pas d'écran)."""
    from .plugin_capture import _launch, _stop
    display = _display()
    if not display:
        raise RuntimeError("no virtual display for the test REAPER")
    with tempfile.TemporaryDirectory(prefix="golem-vst-trial-") as work:
        bench = _bench_dir(work)
        trace = bench / "trial.trace.txt"
        (bench / "Scripts" / "__startup.lua").write_text(script(plugin, trace), encoding="utf-8")
        env_display = os.environ.get("DISPLAY")
        os.environ["DISPLAY"] = display                  # _launch hérite de l'environnement du bridge
        try:
            proc = _launch(reaper_binary(), bench / "reaper.ini", [], bench / "trial.log")
        finally:
            if env_display is None:
                os.environ.pop("DISPLAY", None)
            else:
                os.environ["DISPLAY"] = env_display
        try:
            return _watch(proc, trace, timeout_s or LOAD_TIMEOUT_S)
        finally:
            _stop(proc)


def _watch(proc, trace, load_timeout):
    t0 = time.monotonic()
    last_size, last_move, loaded = -1, t0, False
    while True:
        text = trace.read_text(encoding="utf-8", errors="replace") if trace.is_file() else ""
        if "error=" in text:
            # un plugin INTROUVABLE (désinstallé, nom périmé) ou un moteur sans audio : rien n'est jugé — pas de
            # verdict gardé, blockstatus dit déjà « plugin not installed », et on réessaiera
            raise RuntimeError(text.split("error=", 1)[1].strip().splitlines()[0])
        if "done" in text.splitlines():
            stall = next((int(ln.split("=", 1)[1]) for ln in text.splitlines() if ln.startswith("stall_ms=")), 0)
            if stall > STALL_MS:
                return False, f"stopped the audio engine for {stall} ms when switched on or off", {"stall_ms": stall}
            return True, None, {"stall_ms": stall}
        if proc.poll() is not None:
            return False, "crashed REAPER", {}
        loaded = loaded or "loaded" in text
        now = time.monotonic()
        if len(text) != last_size:
            last_size, last_move = len(text), now
        if not loaded and now - t0 > load_timeout:
            if not text:
                raise RuntimeError("the test REAPER did not start")   # pas un verdict sur le plugin
            return False, f"did not load within {load_timeout} s", {}
        if loaded and now - last_move > FROZEN_S:
            return False, "froze REAPER", {}
        time.sleep(0.2)
