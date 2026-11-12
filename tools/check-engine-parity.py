#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Un bloc sonne-t-il pareil sous REAPER et sous le Golem Engine ? — mesuré (docs/ardour-plan.md §4).

La MÊME DI (library/di-refs/guitar/<signal>.wav) traverse chaque bloc des deux côtés, réglé avec les MÊMES valeurs :
  - REAPER : une instance ISOLÉE (dossier de ressources jetable, audio factice), le plugin ajouté par le nom du
    catalogue, les réglages d'ajout de golem_rig (FX_INIT) puis les paramètres posés par le code de golem_rig recopié
    tel quel (raw : TrackFX_SetParam ; norm : la valeur AFFICHÉE visée par dichotomie ; enum/bool : normalisés) ;
    rendu hors ligne (-renderproject) ;
  - Golem Engine : une session à pilote factice, le bloc posé comme golem_watch.lua le pose (tools/
    engine-render-case.lua), la DI placée (golem-place), rendu par l'export d'Ardour.
Comparaison (check-core-parity.py) : décalage, écart de niveau RELATIF au cas `none` (l'hôte sans bloc), profondeur du
NUL après alignement et égalisation du gain, pire tiers d'octave. Seuil T1 (même binaire) : nul ≤ -50 dB — au-delà
c'est un défaut de correspondance des réglages, pas une différence de son.

Les valeurs : chaque paramètre à 30 % de sa course du catalogue (pas le défaut : un défaut égal à celui du plugin
cacherait un mauvais branchement), une énumération sur sa 2e option, un booléen à vrai.

  xvfb-run -a ./tools/check-engine-parity.py [types…] [--signal crunch] [--seconds 6] [--keep]
(xvfb-run : REAPER ouvre une fenêtre ; sans lui elle apparaîtrait sur l'écran de la machine.) Aucun son, aucune carte, aucun fichier du rack : tout dans un dossier temporaire. REAPER isolé : le rack ne le voit pas.
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SR = 48000
PRE_S = 2                    # = export-preroll d'Ardour (2 s de silence traités avant le rendu) : les LFO partent en phase
TAIL_S = 2                   # queue des deux côtés (delay, reverb)
NULL_MAX = -50.0
# blocs dont la sortie dépend d'une PHASE libre (LFO lancé à la création du plugin, échantillonneur, grains, réverbe
# modulée) : leur nul ne prouve rien (mesuré 2026-11-12 : trémolo, même fréquence, même profondeur, phase décalée) ->
# critères de §4 pour les sons comparables : niveau ≤ 0,5 dB, chaque tiers d'octave ≤ 1 dB
MODULATED = {"chorus", "flanger", "phaser", "tremolo", "rotary", "vibrato", "ringmod", "bitcrusher", "granular",
             "reverb", "reverb-room", "reverb-shimmer"}
LEVEL_MAX, BAND_MAX = 0.5, 1.0
INERT_DB = -60.0             # sortie REAPER à moins de -60 dB de la DI : le bloc ne fait rien avec ces valeurs
SKIP = {"drumkit", "piano"}  # instruments : bancs MIDI (lanes keys/drums), pas une DI


def _mod(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


CP = _mod("check_core_parity", "check-core-parity.py")


def cases(types, catalog, table):
    """[{type, name, plugin, init, params (plan moteur), reaper_params [{id,value}]}] — `none` d'abord."""
    from bridge.engine import ardour_plan as P
    out = [{"type": "none", "plugin": None, "signal": "di"}, {"type": "none-noise", "plugin": None, "signal": "noise"}]
    for t, spec in sorted(table.items()):
        if t in SKIP or (types and t not in types):
            continue
        plug = P.plugin_of(spec)
        if "lua" in plug or spec.get("files"):
            continue                           # DSP Lua = pas le binaire de REAPER ; fichiers (NAM, IR) : prouvés en A0
        cat = catalog.get(t) or {}
        values = {}
        for d in cat.get("params") or []:
            pid, kind = d.get("id"), d.get("type")
            if not pid or pid in (spec.get("absent") or {}) or kind in ("kitref", "midilist"):
                continue
            if kind == "enum":
                opts = d.get("options") or []
                if not opts:
                    continue
                values[pid] = opts[1] if len(opts) > 1 else opts[0]
            elif kind == "bool":
                values[pid] = True
            else:
                lo, hi = float(d.get("min", 0)), float(d.get("max", 1))
                values[pid] = round(lo + 0.3 * (hi - lo), 4)
        blk, _sk = P.plan_block({"id": t, "type": t, "params": values}, catalog, table)
        out.append({"type": t, "signal": "noise" if t in MODULATED else "di",
                    "name": cat.get("plugin"), "plugin": plug, "init": blk.get("init") or [],
                    "params": blk["params"], "values": values, "golem_fx": bool(spec.get("golem_fx"))})
    return out


def pink_noise(n, seed=20261112):
    """Bruit ROSE à -18 dBFS RMS, graine fixe : un signal STATIONNAIRE. Pour un bloc à phase libre (LFO lancé à la
    création du plugin, différent à chaque rendu — mesuré 2026-11-12), seul un signal stationnaire donne un spectre
    moyen indépendant de la phase ; une DI de guitare ne l'est pas (où en est le balayage quand la note frappe)."""
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(n)
    f = np.fft.rfft(w)
    k = np.arange(len(f), dtype=float)
    k[0] = 1.0
    x = np.fft.irfft(f / np.sqrt(k), n)
    return list(x / np.sqrt(np.mean(x * x)) * 10 ** (-18 / 20))


def rig_tables():
    """ADD_ALIAS et FX_INIT de reaper/Scripts/golem_rig.lua, LUS dans le fichier (pas recopiés) : les noms que golem_rig
    essaie pour poser un bloc (« ReaPlugs Volume » n'existe pas, il pose « Volume Adjustment ») et ses réglages d'ajout
    (le plafond « Max Volume » du JSFX neutralisé) — le côté REAPER du banc pose le bloc comme le rack."""
    src = (ROOT / "reaper" / "Scripts" / "golem_rig.lua").read_text(encoding="utf-8")

    def table(name):
        m = re.search(rf"^local {name} = \{{\n(.*?)^\}}", src, re.S | re.M)
        return m.group(1) if m else ""
    key = r'^\s*(?:\["([^"]+)"\]|([\w]+))\s*=\s*\{(.*)\},?\s*(?:--.*)?$'
    alias, init = {}, {}
    for line in table("ADD_ALIAS").splitlines():
        m = re.match(key, line)
        if m:
            alias[m.group(1) or m.group(2)] = re.findall(r'"([^"]+)"', m.group(3))
    for line in table("FX_INIT").splitlines():
        m = re.match(key, line)
        if m:
            init[m.group(1) or m.group(2)] = {k: float(v) for k, v in re.findall(r'\["([^"]+)"\]\s*=\s*([-\d.]+)', m.group(3))}
    return alias, init


def _lua_str(s):
    return json.dumps(str(s), ensure_ascii=False)


def _lua_val(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(float(v))
    if isinstance(v, str):
        return _lua_str(v)
    if isinstance(v, list):
        return "{" + ", ".join(_lua_val(x) for x in v) + "}"
    if isinstance(v, dict):
        return "{" + ", ".join(f"[{_lua_str(k)}] = {_lua_val(x)}" for k, x in v.items()) + "}"
    return "nil"


# ── REAPER : le code de golem_rig.lua recopié (resolve_param, set_norm_to_target, la boucle des paramètres) ─────────
REAPER_LIB = r'''
local function clamp01(x) if x < 0 then return 0 elseif x > 1 then return 1 end return x end
local function find_param_exact(track, fx, name)
  for p = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
    local _, n = reaper.TrackFX_GetParamName(track, fx, p, ""); if n == name then return p end
  end
end
local function find_param_by_name(track, fx, name)
  local l = name:lower()
  for p = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
    local _, n = reaper.TrackFX_GetParamName(track, fx, p, ""); if n:lower():find(l, 1, true) then return p end
  end
end
local function pdisp(track, fx, p)
  local _, d = reaper.TrackFX_GetFormattedParamValue(track, fx, p, "")
  d = d or ""
  if d:find("inf", 1, true) then return d:find("-", 1, true) and -150 or 150 end
  return tonumber(d:match("[-+]?%d+%.?%d*"))
end
local function set_norm_to_target(track, fx, p, target, mn, mx)
  reaper.TrackFX_SetParamNormalized(track, fx, p, 0); local v0 = pdisp(track, fx, p)
  reaper.TrackFX_SetParamNormalized(track, fx, p, 1); local v1 = pdisp(track, fx, p)
  if not v0 or not v1 or v0 == v1 then
    reaper.TrackFX_SetParamNormalized(track, fx, p, (mx == mn) and 0 or clamp01((target - mn) / (mx - mn))); return
  end
  local inc = v1 > v0
  local lo, hi = 0, 1
  for _i = 1, 16 do
    local mid = (lo + hi) / 2
    reaper.TrackFX_SetParamNormalized(track, fx, p, mid)
    local v = pdisp(track, fx, p) or target
    if (v < target) == inc then lo = mid else hi = mid end
  end
end
local function index_of(options, value)
  for i, o in ipairs(options or {}) do if o == value then return i - 1 end end
  return 0
end
function apply(track, fx, defs, values)
  for pid, value in pairs(values) do
    local def = defs[pid]
    local map = def.map
    -- golem_rig.resolve_param : le nom exact, une sous-chaîne, puis le RANG numérique du catalogue (num_index)
    local p = find_param_exact(track, fx, def.name) or find_param_by_name(track, fx, def.name) or def.num_index
    local mode = (map and map.mode) or "norm"
    if not p then TRACE:write("param introuvable " .. def.name .. "\n")
    elseif def.type == "enum" then
      local i = index_of(def.options or {}, value)
      local tv = def.values and def.values[i + 1]
      if tv ~= nil then
        if mode == "norm" then set_norm_to_target(track, fx, p, tv, tonumber(def.min) or 0, tonumber(def.max) or 1)
        else reaper.TrackFX_SetParam(track, fx, p, tv) end
      elseif mode == "raw" then reaper.TrackFX_SetParam(track, fx, p, i)
      else reaper.TrackFX_SetParamNormalized(track, fx, p, i / math.max(1, #(def.options or {}) - 1)) end
    elseif def.type == "bool" then
      local b = (value and value ~= 0) and 1 or 0
      if mode == "raw" then reaper.TrackFX_SetParam(track, fx, p, b)
      else reaper.TrackFX_SetParamNormalized(track, fx, p, b) end
    else
      local mn, mx = tonumber(def.min) or 0, tonumber(def.max) or 1
      local v = tonumber(value)
      if mode == "raw" then
        if v < mn then v = mn elseif v > mx then v = mx end
        if map and map.scale then v = v * map.scale end
        reaper.TrackFX_SetParam(track, fx, p, v)
      else
        set_norm_to_target(track, fx, p, v, mn, mx)
      end
    end
    if p then
      local _, shown = reaper.TrackFX_GetFormattedParamValue(track, fx, p, "")
      TRACE:write("param " .. def.name .. " = " .. tostring(shown) .. "\n")
    end
  end
end
'''


def reaper_script(cs, catalog, work, di, length):
    blocks = []
    for c in cs:
        project = work / "reaper" / f"{c['type']}.rpp"
        if c["plugin"] is None:
            chain = ""
        else:
            defs = {d["id"]: d for d in (catalog.get(c["type"]) or {}).get("params") or [] if d.get("id")}
            # num_index comme golem_rig.lua (le repli de resolve_param) : le rang parmi les paramètres ni bool ni enum
            ni = 0
            for d in (catalog.get(c["type"]) or {}).get("params") or []:
                if d.get("type") not in ("bool", "enum"):
                    if d.get("id"):
                        defs[d["id"]] = {**d, "num_index": ni}
                    ni += 1
            used = {k: defs[k] for k in c["values"]}
            alias, fx_init = rig_tables()
            names = [c["name"]] + [n for n in alias.get(c["type"], []) if n != c["name"]]
            # golem_rig : ses réglages d'ajout (FX_INIT) ; à défaut, ceux de la table du moteur (même binaire)
            init = fx_init.get(c["type"]) or {e["label"]: e["value"] for e in c["init"]}
            chain = f'''
local fx = -1
for _, n in ipairs({_lua_val(names)}) do
  fx = reaper.TrackFX_AddByName(tr, n, false, -1)
  if fx >= 0 then break end
end
if fx < 0 then TRACE:write("error=plugin absent {c['name']}\\n"); TRACE:close(); return end
for pname, pval in pairs({_lua_val(init)}) do
  local p = find_param_by_name(tr, fx, pname); if p then reaper.TrackFX_SetParam(tr, fx, p, pval) end
end
apply(tr, fx, {_lua_val(used)}, {_lua_val(c["values"])})
for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
  local _, n = reaper.TrackFX_GetParamName(tr, fx, p, ""); local v = reaper.TrackFX_GetParam(tr, fx, p)
  TRACE:write("all {c['type']} " .. n .. " = " .. tostring(v) .. "\\n")
end'''
        blocks.append(f'''
clear()
local tr = new_track({_lua_str(di[c["signal"]])})
{chain}
save({_lua_str(project)}, {_lua_str(c["type"])})
''')
    return REAPER_LIB + f'''
TRACE = assert(io.open({_lua_str(work / "reaper" / "create.txt")}, "w"))
local LEN = {length}
function clear()
  for i = reaper.CountTracks(0) - 1, 0, -1 do reaper.DeleteTrack(reaper.GetTrack(0, i)) end
end
function new_track(path)
  reaper.InsertTrackAtIndex(0, true)
  local tr = reaper.GetTrack(0, 0)
  local item = reaper.AddMediaItemToTrack(tr)
  local take = reaper.AddTakeToMediaItem(item)
  local src = reaper.PCM_Source_CreateFromFile(path)
  reaper.SetMediaItemTake_Source(take, src)
  reaper.SetMediaItemInfo_Value(item, "D_LENGTH", LEN)
  reaper.SetMediaItemInfo_Value(item, "D_POSITION", {PRE_S})
  for _, k in ipairs({{"D_FADEINLEN", "D_FADEOUTLEN", "D_FADEINLEN_AUTO", "D_FADEOUTLEN_AUTO"}}) do
    reaper.SetMediaItemInfo_Value(item, k, 0)
  end
  return tr
end
function save(project, name)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", {SR}, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", {_lua_str(work / "reaper")}, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", name .. "-render", true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdyAAAQ==", true)
  reaper.GetSet_LoopTimeRange(true, false, 0, {PRE_S} + LEN + {TAIL_S}, false)
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)
  reaper.GetSetProjectInfo(0, "RENDER_SRATE", {SR}, true)
  reaper.GetSetProjectInfo(0, "RENDER_TAILFLAG", 0, true)
  reaper.Main_SaveProjectEx(0, project, 0)
  TRACE:write("saved " .. name .. "\\n")
end
''' + "".join(blocks) + '\nTRACE:write("ready\\n")\nTRACE:close()\n'


def reaper_binary():
    if os.environ.get("REAPER_BIN"):
        return Path(os.environ["REAPER_BIN"])
    for cand in [shutil.which("reaper"), Path.home() / "opt/REAPER/reaper", "/opt/REAPER/reaper"]:
        if cand and Path(cand).is_file():
            return Path(cand)
    raise SystemExit("REAPER introuvable (REAPER_BIN)")


def render_reaper(cs, catalog, work, di, length):
    native = _mod("check_native_nam", "check-native-nam.py")
    res = work / "reaper"
    (res / "Scripts").mkdir(parents=True)
    # audio factice sous Linux : [reaper] linux_audio_mode=2 (mesuré, tools/check-rig-materialize.py)
    (res / "reaper.ini").write_text("[REAPER]\nnolastproject=1\nopenallrecent=0\nlinux_audio_mode=2\n"
                                    "linux_audio_srate=48000\n[audioconfig]\nmode=4\n", encoding="ascii")
    (res / "Scripts" / "__startup.lua").write_text(reaper_script(cs, catalog, work, di, length), encoding="utf-8")
    # démarrage À CHAUD (comme check-rig-materialize) : les caches de plugins et la licence du REAPER de la machine,
    # sinon un dossier vierge rescanne tout au lancement ; lus, jamais réécrits
    real = Path.home() / ".config" / "REAPER"
    for n in ("reaper-vstplugins64.ini", "reaper-vstshells64.ini", "reaper-clap-linux-x86_64.ini", "reaper-license.rk"):
        if (real / n).is_file():
            shutil.copy2(real / n, res / n)
    reaper = reaper_binary()
    last = res / f"{cs[-1]['type']}.rpp"
    proc = native.launch(reaper, res / "reaper.ini", [], res / "create.log")
    try:
        native.wait_for_project(proc, res / "create.txt", last, timeout=600)
    finally:
        native.stop(proc)
    out = {}
    for c in cs:
        t = c["type"]
        rendered = res / f"{t}-render.wav"
        proc = native.launch(reaper, res / "reaper.ini", ["-renderproject", str(res / f"{t}.rpp")], res / f"render-{t}.log")
        try:
            proc.wait(timeout=300)
        finally:
            native.stop(proc)
        if not rendered.is_file():
            print(f"  REAPER {t} : pas de rendu")
            continue
        x, _ = CP.read_first_channel(rendered)
        out[t] = x[PRE_S * SR:]
    return out


def render_engine(cs, work, di, engine_dir):
    env_sh = Path(engine_dir) / "golem" / "dev" / "env.sh"
    b = Path(engine_dir) / "build"
    env = dict(os.environ, LANG="C.UTF-8", LC_ALL="C.UTF-8")
    out = {}
    for c in cs:
        t = c["type"]
        d = work / "engine" / t
        d.parent.mkdir(parents=True, exist_ok=True)
        case = work / "engine" / f"{t}.lua"
        case.write_text("return " + _lua_val({k: v for k, v in c.items() if k in ("plugin", "init", "params")
                                              and v is not None}), encoding="utf-8")
        wav = work / "engine" / f"{t}.wav"
        cmd = (f'source "{env_sh}" >/dev/null 2>&1; cd "{engine_dir}"; '
               f'timeout 90 "{b}/luasession/luasession" "{ROOT}/tools/engine-render-case.lua" "{d}" "{case}" && '
               f'timeout 60 "{b}/golem/golem-place" "{d}" bench gtr "{di[c['signal']]}" {TAIL_S} && '
               f'timeout 120 "{b}/session_utils/golem-engine9-export" -b float -o "{wav}" "{d}" bench')
        p = subprocess.run(["bash", "-c", cmd], env=env, capture_output=True, text=True)
        (work / "engine" / f"{t}.log").write_text(p.stdout + p.stderr, encoding="utf-8")
        if not wav.is_file():
            print(f"  Golem Engine {t} : pas de rendu (voir {work / 'engine' / (t + '.log')})")
            continue
        x, _ = CP.read_first_channel(wav)
        out[t] = x
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("types", nargs="*")
    ap.add_argument("--signal", default="crunch", help="DI de library/di-refs/guitar (défaut crunch)")
    ap.add_argument("--seconds", type=float, default=6.0, help="durée de DI rendue (défaut 6 s)")
    ap.add_argument("--engine-dir", default=os.environ.get("GOLEM_ENGINE_DIR") or os.path.expanduser("~/golem-engine"))
    ap.add_argument("--keep", action="store_true", help="garder le dossier de travail")
    ap.add_argument("--json", help="écrire le rapport ici")
    a = ap.parse_args()
    from bridge.engine import ardour_plan as P
    catalog, table = P.load_catalog(), P.load_table()
    cs = cases(set(a.types) or None, catalog, table)
    work = Path(tempfile.mkdtemp(prefix="golem-engine-parity-"))
    try:
        src = ROOT / "library" / "di-refs" / "guitar" / f"{a.signal}.wav"
        x, _ = CP.read_first_channel(src)
        x = x[:int(a.seconds * SR)]
        di = {"di": work / "di.wav", "noise": work / "noise.wav"}
        CP.write_f32(di["di"], x)
        CP.write_f32(di["noise"], pink_noise(len(x)))
        length = len(x) / SR
        t0 = time.time()
        print(f"{len(cs) - 1} bloc(s), DI {a.signal} {length:.1f} s — travail {work}")
        rr = render_reaper(cs, catalog, work, di, length)
        print(f"  REAPER : {len(rr)} rendu(s) en {time.time() - t0:.0f} s")
        t1 = time.time()
        ee = render_engine(cs, work, di, a.engine_dir)
        print(f"  Golem Engine : {len(ee)} rendu(s) en {time.time() - t1:.0f} s")
        report, fails = [], []
        base = CP._metrics(rr["none"], ee["none"]) if "none" in rr and "none" in ee else None
        if base:
            print(f"  hôte (sans bloc) : décalage {base['lag']}, niveau {base['level_db']:+.2f} dB, nul {base['null_db']:.1f} dB")
        for c in cs[2:]:
            t = c["type"]
            if t not in rr or t not in ee:
                fails.append(t)
                report.append({"type": t, "error": "no render"})
                continue
            m = CP._metrics(rr[t], ee[t])
            rel = m["level_db"] - (base["level_db"] if base else 0.0)
            ref = "none-noise" if c["signal"] == "noise" else "none"
            dry = np.asarray(rr[ref], float)
            wet = np.asarray(rr[t], float)
            k = min(len(dry), len(wet))
            dry, wet = dry[:k], wet[:k]
            effect = 20 * np.log10(np.sqrt(np.mean((wet - dry) ** 2)) / (np.sqrt(np.mean(dry ** 2)) + 1e-15) + 1e-15)
            silent = np.sqrt(np.mean(wet ** 2)) < 1e-4
            if silent or effect < INERT_DB:
                verdict = "inconclusive"             # rien à comparer : silence, ou la DI telle quelle des deux côtés
                why = "silent with these values" if silent else "the block leaves the DI untouched with these values"
            elif c.get("golem_fx"):
                # un effet golem-fx : un son NOUVEAU (pas un clone) — la distance à l'original REAPER est dite, pas jugée
                verdict, why = "info", "golem-fx effect: distance to the REAPER original, for information"
            elif t in MODULATED:
                ok = abs(rel) <= LEVEL_MAX and abs(m["band_db"]) <= BAND_MAX
                verdict, why = ("ok" if ok else "fail"), "free phase: level and third-octaves judged, not the null"
            else:
                verdict, why = ("ok" if m["null_db"] <= NULL_MAX else "fail"), ""
            tag = {"ok": "ok  ", "fail": "FAIL", "inconclusive": "??  ", "info": "fx  "}[verdict]
            print(f"  {tag}  {t:<16} nul {m['null_db']:7.1f} dB  niveau {rel:+6.2f} dB  effet {effect:6.1f} dB  "
                  f"pire tiers {m['band_db']:+.1f} dB @ {m['band_hz']:.0f} Hz" + (f"  — {why}" if why else ""))
            report.append({"type": t, **m, "level_rel_db": rel, "effect_db": effect, "verdict": verdict, "why": why,
                           "values": c["values"]})
            if verdict == "fail":
                fails.append(t)
        if a.json:
            Path(a.json).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print("OK" if not fails else f"{len(fails)} bloc(s) en échec : {', '.join(fails)}")
        return 0 if not fails else 1
    finally:
        if a.keep:
            print(f"gardé : {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
