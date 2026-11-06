# SPDX-License-Identifier: GPL-3.0-or-later
"""Recettes de capture : l'IA de golem.fm PROPOSE, le rack MESURE, le musicien VALIDE (docs/plugin-recipes.md).

Ce module est la moitié rack :
- la FICHE d'un plugin (`sheet`) : ses paramètres (nom, valeur affichée, normalisée, bornes), les crans des
  paramètres à pas (lus en balayant, jamais devinés) et sa version, lue dans le FICHIER du plugin ;
- la VÉRIFICATION d'un brouillon (`verify`) : chaque affirmation est rejouée dans un REAPER séparé (sans carte
  son, `plugin_capture.bench_run`) et jugée sur le son — `verified`, `rejected` (avec la mesure) ou `declared`
  (ce que la mesure ne peut pas trancher). « Une nature déclarée ne vaut rien tant qu'elle n'est pas lue. »

Tous les rendus d'une vérification se font dans UNE session REAPER : mesuré le 2026-10-10 sur une suite d'ampli, ~8 s des
~12 s d'un rendu court sont le lancement de REAPER (45 s la première fois, le plugin se charge).
"""
import json
import logging
import math
import os
import re
import sys
import time
from pathlib import Path

from . import config as C
from . import plugin_capture as PC

log = logging.getLogger("golem.plugin_recipes")

LOCAL_DIR = Path(C.CONFIG_DIR) / "plugin-recipes"     # état LOCAL (jamais commité — CLAUDE.md règle 2)
SCHEMA = 2
T_PROBE = 432_000          # le passage de validation du signal v3 : 9 s à 48 kHz
GAP_S, TAIL_S = 0.5, 3.0
STABLE_MAX = 1e-3          # « stable » : 0 au bit près et 0,000013 sur deux suites d'ampli (mesuré 2026-10-10)
MOVES_MIN = PC.SELF_ESR_MAX
AUDIBLE_DB = -40.0         # allumé vs coupé : en dessous, l'interrupteur « ne fait rien »
TAIL_ON_DB, TAIL_OFF_DB = -60.0, -80.0
LINEAR_DB = -40.0
MAX_STEPS = 40


# ── la version, lue dans le fichier du plugin ───────────────────────────────────────────────────
def plugin_version(path):
    """« 1.1.0.0 » : Windows = la ressource de version du .vst3/.dll (mesuré sur deux suites d'ampli : 1.1.0.0 et 1.5.0.0) ;
    macOS = CFBundleShortVersionString de l'Info.plist du bundle. None si le fichier ne la porte pas."""
    p = Path(str(path or ""))
    try:
        if sys.platform == "darwin":
            import plistlib
            # REAPER peut nommer le BINAIRE intérieur (`…/X.vst3/Contents/MacOS/X`) : remonter au bundle
            for anc in [p, *p.parents]:
                if anc.suffix.lower() in (".vst3", ".vst", ".clap", ".component"):
                    p = anc
                    break
            plist = p / "Contents" / "Info.plist"
            if plist.is_file():
                d = plistlib.loads(plist.read_bytes())
                return d.get("CFBundleShortVersionString") or d.get("CFBundleVersion")
            return None
        if sys.platform != "win32":
            return None
        if p.is_dir():                                   # bundle VST3 : le binaire est dedans
            bins = sorted(p.glob("Contents/x86_64-win/*.vst3"))
            p = bins[0] if bins else p
        if not p.is_file():
            return None
        import ctypes
        from ctypes import wintypes
        ver = ctypes.windll.version
        n = ver.GetFileVersionInfoSizeW(str(p), None)
        if not n:
            return None
        buf = ctypes.create_string_buffer(n)
        if not ver.GetFileVersionInfoW(str(p), 0, n, buf):
            return None
        ptr, ln = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(ln)):
            return None
        words = (wintypes.DWORD * 13).from_address(ptr.value)       # VS_FIXEDFILEINFO
        ms, ls = words[2], words[3]                                   # dwFileVersionMS / LS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception as e:                               # une version illisible n'empêche rien
        log.info(f"version de {p} illisible : {e}")
        return None


def plugin_file(plugin):
    """Le chemin du plugin (l'`ident` de la liste REAPER), par son nom exact."""
    from .routes_content import vst_host_plugins
    r = vst_host_plugins()
    for e in (r.get("plugins", []) if isinstance(r, dict) else []):
        if e.get("name") == plugin:
            return e.get("ident")
    return None


def rack_os():
    """La valeur `caps.os` du battement (blockstatus.caps) : « windows » | « darwin » | « linux » — la MÊME source,
    sans recharger tout le catalogue d'effets pour un nom d'OS."""
    import platform
    return platform.system().lower()


def _format(plugin):
    m = re.match(r"^(VST3|VST|CLAP|AU|LV2)i?:", str(plugin or ""))
    return m.group(1) if m else "Other"


# ── le Lua commun : une piste, le plugin dans l'état du musicien, des gestes par VALEUR AFFICHÉE ──────────
_LUA_JSON = r'''
local function jstr(s)
  s = tostring(s or "")
  s = s:gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" elseif c == "\n" then return "\\n" end
    return string.format("\\u%04x", c:byte())
  end)
  return '"' .. s .. '"'
end
'''


def _setup_lua(plugin, chunk):
    return _LUA_JSON + f'''
local f = assert(io.open({{TRACE}}, "w"))
local function say(m) f:write(m .. "\\n"); f:flush() end
local function die(m) say("error=" .. tostring(m)); f:close(); error(m) end
for i = reaper.CountTracks(0) - 1, 0, -1 do reaper.DeleteTrack(reaper.GetTrack(0, i)) end
reaper.InsertTrackAtIndex(0, true)
local tr = reaper.GetTrack(0, 0)
local fx = reaper.TrackFX_AddByName(tr, {PC._lua(plugin)}, false, -1)
if fx < 0 then die("plugin introuvable : " .. {PC._lua(plugin)}) end
{PC._state_lua(chunk, None)}
local NP = reaper.TrackFX_GetNumParams(tr, fx)
local function shown(p) local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, ""); return s end
local function pname(p) local _, s = reaper.TrackFX_GetParamName(tr, fx, p, ""); return s end
'''


def _sheet_lua(plugin, chunk):
    """Lit chaque paramètre (nom, affichage, normalisée, bornes) et, pour ceux À CRANS, la suite des valeurs
    affichées en balayant 0..1 (101 points) — un interrupteur se lit « Inactive/Active », pas « 0/1 »."""
    return _setup_lua(plugin, chunk) + f'''
local t0 = reaper.time_precise()
local function scan()
  for p = 0, NP - 1 do
    local norm = reaper.TrackFX_GetParamNormalized(tr, fx, p)
    local _, mn, mx = reaper.TrackFX_GetParamEx(tr, fx, p)
    local disp = shown(p)
    local seen, order, numeric, lo, hi = {{}}, {{}}, true, "", ""
    for k = 0, 20 do                                     -- 21 points : assez pour reconnaître un paramètre à crans
      reaper.TrackFX_SetParamNormalized(tr, fx, p, k / 20)
      local s = shown(p)
      if k == 0 then lo = s elseif k == 20 then hi = s end   -- l'affichage aux bouts de course (« -96.0 »)
      if not seen[s] then seen[s] = true; order[#order + 1] = s end
      if not tonumber((s:gsub("[^%d%.%-]", ""))) then numeric = false end
    end
    local steps = nil
    if #order <= 12 and (not numeric or #order <= 3) then
      seen, order = {{}}, {{}}
      for k = 0, 100 do
        reaper.TrackFX_SetParamNormalized(tr, fx, p, k / 100)
        local s = shown(p)
        if not seen[s] then seen[s] = true; order[#order + 1] = s end
        if #order > {MAX_STEPS} then break end
      end
      if #order <= {MAX_STEPS} then steps = order end
    end
    reaper.TrackFX_SetParamNormalized(tr, fx, p, norm)   -- rendu tel qu'on l'a trouvé
    local line = '{{"i":' .. p .. ',"name":' .. jstr(pname(p)) .. ',"display":' .. jstr(disp) ..
                 ',"norm":' .. string.format("%.6f", norm) .. ',"min":' .. string.format("%.6g", mn) ..
                 ',"max":' .. string.format("%.6g", mx) ..
                 ',"display_min":' .. jstr(lo) .. ',"display_max":' .. jstr(hi)
    if steps then
      local q = {{}}
      for _, s in ipairs(steps) do q[#q + 1] = jstr(s) end
      line = line .. ',"steps":[' .. table.concat(q, ",") .. ']'
    end
    say("param " .. line .. "}}")
  end
  say("sheet_done")
  f:close()
end
local function tick()
  if reaper.time_precise() - t0 >= 3 then scan(); return end   -- le plugin restaure son état en tâche de fond
  reaper.defer(tick)
end
tick()
'''


def sheet(block, plugin, work=None, timeout=300):
    """La FICHE envoyée à golem.fm (§4) : {plugin, vendor, format, os, plugin_version, params[], steps{}}.
    Lue dans un REAPER séparé, sur l'ÉTAT du bloc du musicien (rien n'est modifié dans son instance)."""
    state = PC._live_state(block)
    work = Path(work or (PC.train_home().parent / "recipes" / _slug(plugin)))
    work.mkdir(parents=True, exist_ok=True)
    lines, _mb = PC.bench_run(work, "sheet", _sheet_lua(plugin, state["chunk"]), timeout, done="sheet_done")
    params, steps = [], {}
    for l in lines:
        if l.startswith("param "):
            d = json.loads(l[6:])
            if re.match(r"(?i)^\s*MIDI[\s_-]*CC\b", d["name"]):      # la matrice MIDI n'est pas un réglage
                continue
            if "steps" in d:
                steps[str(d["i"])] = d.pop("steps")
            params.append(d)
    return {"plugin": plugin, "vendor": PC._vendor(plugin), "format": _format(plugin), "os": rack_os(),
            "plugin_version": plugin_version(plugin_file(plugin)), "params": params, "steps": steps,
            "known_recipe_schema": SCHEMA,
            # un instrument (préfixe « VST3i: ») : golem.fm répond `unsupported` sans appeler son IA
            "instrument": bool(re.match(r"^[A-Z0-9]+i:", str(plugin or "")))}


def _slug(text):
    return PC._slug(text) or "plugin"


# ── la VÉRIFICATION d'un brouillon (docs/plugin-recipes.md §6) ───────────────────────────────────────────
def _probe(work):
    """La sonde : le passage de validation du v3 (9 s), 0,5 s, le même passage, puis 3 s de silence (la queue)."""
    path = Path(work) / "probe.wav"
    if not path.is_file():
        x, _ = PC.read_wav(PC.train_home() / "v3_0_0.wav")
        seg = x[:T_PROBE]
        PC.write_wav(path, seg + [0.0] * int(GAP_S * PC.SR) + seg + [0.0] * int(TAIL_S * PC.SR))
    return path


def _lua_value(v):
    if isinstance(v, dict):                              # {"norm": x} : rendre une valeur continue telle quelle
        return "{n=%.6f}" % float(v["norm"])
    return "{d=%s}" % PC._lua(v)


def _batch_lua(plugin, chunk, src, configs, outdir):
    """UNE session REAPER, un rendu par configuration. Chaque configuration donne une valeur à TOUS les
    paramètres cités par la recette : aucun rendu n'hérite de l'état du précédent."""
    cfgs = ",".join("{name=%s,gain=%s,set={%s}}" % (
        PC._lua(c["name"]), repr(float(c.get("gain", 1.0))),
        ",".join(f"[{PC._lua(k)}]={_lua_value(v)}" for k, v in c["set"].items())) for c in configs)
    return _setup_lua(plugin, chunk) + f'''
reaper.SetOnlyTrackSelected(tr)
reaper.SetEditCurPos({PC.PRE_S}, false, false)
if reaper.InsertMedia({PC._lua(src)}, 0) ~= 1 then die("signal illisible") end
local item = reaper.GetTrackMediaItem(tr, 0)
if not item then die("signal non inséré") end
local LEN = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
local idx = {{}}
for p = 0, NP - 1 do idx[pname(p)] = p end
local CFG = {{{cfgs}}}
local function apply(set)
  for k, v in pairs(set) do
    local p = idx[k]
    if p == nil then die("paramètre absent : " .. k) end
    if v.n then reaper.TrackFX_SetParamNormalized(tr, fx, p, v.n)
    elseif v.d == "min" or v.d == "max" then reaper.TrackFX_SetParamNormalized(tr, fx, p, v.d == "min" and 0 or 1)
    else
      local hit = false
      for i = 0, 100 do
        reaper.TrackFX_SetParamNormalized(tr, fx, p, i / 100)
        if shown(p) == v.d then hit = true; break end
      end
      if not hit then die("valeur « " .. v.d .. " » introuvable pour " .. k) end
    end
  end
end
local function check(c)                                  -- relu juste avant le rendu
  for k, v in pairs(c.set) do
    if v.d and v.d ~= "min" and v.d ~= "max" and shown(idx[k]) ~= v.d then
      die(c.name .. " : le plugin a remis " .. k .. " à « " .. shown(idx[k]) .. " »")
    end
  end
end
reaper.GetSetProjectInfo(0, "PROJECT_SRATE", {PC.SR}, true)
reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
reaper.GetSetProjectInfo_String(0, "RENDER_FILE", {PC._lua(outdir)}, true)
reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdyAAAQ==", true)
reaper.GetSet_LoopTimeRange(true, false, 0, {PC.PRE_S} + LEN, false)
reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)
reaper.GetSetProjectInfo(0, "RENDER_SRATE", {PC.SR}, true)
reaper.GetSetProjectInfo(0, "RENDER_TAILFLAG", 0, true)
local t0, k, phase = reaper.time_precise(), 1, 0
local function tick()
  local dt = reaper.time_precise() - t0
  if phase == 0 and dt >= 3 then phase = 1; t0 = reaper.time_precise()   -- l'état du plugin est restauré
  elseif phase == 1 then
    local c = CFG[k]
    if not c then say("rendered"); f:close(); return end
    apply(c.set)
    reaper.SetMediaItemInfo_Value(item, "D_VOL", c.gain)
    phase = 2; t0 = reaper.time_precise()
  elseif phase == 2 and dt >= 0.5 then
    local c = CFG[k]
    check(c)
    reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", c.name, true)
    local r0 = reaper.time_precise()
    reaper.Main_OnCommand(42230, 0)
    say("done " .. c.name .. " " .. string.format("%.3f", reaper.time_precise() - r0))
    k = k + 1; phase = 1
  end
  reaper.defer(tick)
end
tick()
'''


def render_many(plugin, chunk, configs, work, timeout=900):
    """{nom: échantillons} — tous les rendus d'une vérification dans UNE session REAPER."""
    work = Path(work)
    out = PC._bench_dir(work) / "renders"
    out.mkdir(exist_ok=True)
    for c in configs:
        (out / f"{c['name']}.wav").unlink(missing_ok=True)
    PC.bench_run(work, "verify", _batch_lua(plugin, chunk, _probe(work).resolve(), configs, out.resolve()), timeout)
    res = {}
    for c in configs:
        x, rate = PC.read_wav(out / f"{c['name']}.wav")
        if rate != PC.SR:
            raise RuntimeError(f"render at {rate} Hz, expected {PC.SR}")
        res[c["name"]] = x[PC.PRE_S * rate:]
    return res


# ── les mesures (sur la sonde : passage, 0,5 s, passage, 3 s de silence) ───────────────────────────────
def _energy(x):
    return sum(v * v for v in x)


def m_self_esr(y):
    n2 = T_PROBE + int(GAP_S * PC.SR)
    a, b = y[:T_PROBE], y[n2:n2 + T_PROBE]
    den = _energy(b)
    return _energy([u - v for u, v in zip(a, b)]) / den if den > 0 else 0.0


def m_tail_db(y):
    """L'énergie des 3 s finales (plus rien n'entre) sous celle du signal, en dB par échantillon."""
    sig_end = 2 * T_PROBE + int(GAP_S * PC.SR)
    sig, tail = y[:sig_end], y[sig_end + int(0.05 * PC.SR):]        # 50 ms : la fin d'une note n'est pas une queue
    es, et = _energy(sig) / max(len(sig), 1), _energy(tail) / max(len(tail), 1)
    return -200.0 if et <= 0 or es <= 0 else 10 * math.log10(et / es)


def m_null_db(a, b, scale=1.0):
    """L'écart entre deux rendus, sous le niveau du second (dB) : −200 = identiques."""
    n = min(len(a), len(b))
    den = _energy(b[:n])
    num = sum((a[i] - scale * b[i]) ** 2 for i in range(n))
    return -200.0 if num <= 0 or den <= 0 else 10 * math.log10(num / (den * scale * scale))


def m_peak(y):
    return max((abs(v) for v in y), default=0.0)


# ── le plan : quelles configurations, pour quelles affirmations ──────────────────────────────────────────
def _claims(draft):
    """[(groupe, affirmation)] : tout ce que le brouillon affirme et que le rack doit juger."""
    full = draft.get("full") or {}
    out = [("refuse", r) for r in full.get("refuse") or []] + [("captured", c) for c in full.get("captured") or []]
    out += [("part", p) for p in (draft.get("split") or {}).get("parts") or []]
    out += [("translate", t) for t in draft.get("translate") or []]
    return out


def _switch(claim):
    w = claim.get("when") or {}
    return claim.get("switch") or (list(w)[-1] if w else None)


def check_draft(draft, sht):
    """Les règles de §5 (sinon `invalid`) : noms et valeurs présents dans la fiche, ids uniques, why/confidence."""
    names = {p["name"]: p for p in sht["params"]}
    steps = {n: sht["steps"].get(str(p["i"])) for n, p in names.items()}
    errors, ids = [], set()

    def value_ok(k, v, where):
        if k not in names:
            errors.append(f"{where}: unknown parameter « {k} »")
        elif v not in ("min", "max") and steps.get(k) is not None and v not in steps[k]:
            errors.append(f"{where}: « {v} » is not a value of « {k} » ({', '.join(steps[k])})")
        elif v not in ("min", "max") and not isinstance(v, str):
            errors.append(f"{where}: « {k} » needs a displayed value")
        elif v not in ("min", "max") and steps.get(k) is None and v not in (
                names[k].get("display"), names[k].get("display_min"), names[k].get("display_max")):
            errors.append(f"{where}: « {v} » is not a value « {k} » shows (current, min or max)")

    for k, v in ((draft.get("full") or {}).get("off") or {}).items():
        value_ok(k, v, "full.off")
    for grp, c in _claims(draft):
        cid = c.get("id")
        where = f"{grp}:{cid or c.get('label') or c.get('block')}"
        if not cid:
            errors.append(f"{where}: missing id")
        elif cid in ids:
            errors.append(f"{where}: duplicate id")
        ids.add(cid)
        if not c.get("why") or c.get("confidence") not in ("high", "medium", "low"):
            errors.append(f"{where}: missing why/confidence")
        for key in ("when", "when_any", "unless", "off", "loss_if"):
            for k, v in (c.get(key) or {}).items():
                value_ok(k, v, f"{where}.{key}")
        sw = _switch(c)
        if grp in ("refuse", "captured") and sw and steps.get(sw) is None:
            errors.append(f"{where}: switch « {sw} » is not a switch (no steps)")
    return errors


def _off_value(sht, name, on_value):
    """L'AUTRE cran d'un interrupteur à deux crans ; None si le paramètre n'en a pas exactement deux."""
    p = next((p for p in sht["params"] if p["name"] == name), None)
    st = sht["steps"].get(str(p["i"])) if p else None
    if not st or len(st) != 2 or on_value not in st:
        return None
    return st[0] if st[1] == on_value else st[1]


def plan(draft, sht):
    """([configuration], {id: test}). Chaque configuration est COMPLÈTE sur toutes les clés citées par la recette :
    les clés qu'elle ne touche pas reprennent la valeur du musicien (sa normalisée)."""
    full = draft.get("full") or {}
    keys = set(full.get("off") or {})
    for _g, c in _claims(draft):
        for key in ("when", "when_any", "off"):
            keys |= set(c.get(key) or {})
        if c.get("switch"):
            keys.add(c["switch"])
    user = {p["name"]: {"norm": p["norm"]} for p in sht["params"] if p["name"] in keys}
    # « quiet » : full.off + chaque `refuse` et chaque `translate` coupés à leur interrupteur
    quiet = dict(user)
    quiet.update(full.get("off") or {})
    off_of = {}
    for grp, c in _claims(draft):
        sw = _switch(c)
        if grp in ("refuse", "translate", "captured") and sw:
            off_of[c["id"]] = _off_value(sht, sw, (c.get("when") or {}).get(sw, "Active"))
        if grp in ("refuse", "translate") and sw and off_of.get(c["id"]):
            quiet[sw] = off_of[c["id"]]
    configs = [{"name": "quiet", "set": quiet}]
    tests = {}
    for grp, c in _claims(draft):
        cid = c["id"]
        if grp == "part":
            cfg = dict(user)
            cfg.update(c.get("off") or {})
            configs.append({"name": f"part-{cid}", "set": cfg})
            if c.get("ir"):
                configs.append({"name": f"part-{cid}-half", "set": cfg, "gain": 0.5})
            tests[cid] = ("part", c)
            continue
        sw, off = _switch(c), off_of.get(cid)
        if not sw or not off:
            tests[cid] = ("declared", c, "its switch has no on/off position to test")
            continue
        on = dict(quiet)
        on.update(c.get("when") or {})
        if grp == "captured":                             # allumé vs coupé, le reste au calme
            off_cfg = dict(on)
            off_cfg[sw] = off
            configs += [{"name": f"on-{cid}", "set": on}, {"name": f"off-{cid}", "set": off_cfg}]
        else:                                             # refuse / translate : allumé seul vs « quiet »
            configs.append({"name": f"on-{cid}", "set": on})
        tests[cid] = (grp, c)
    return configs, tests


def judge(tests, renders):
    """Les verdicts de §6.1, chacun avec SA mesure."""
    q = renders["quiet"]
    q_esr, q_tail = m_self_esr(q), m_tail_db(q)
    verified, rejected, declared = [], [], []
    measures = {"quiet": {"self_esr": round(q_esr, 6), "tail_db": round(q_tail, 1)}}

    def rej(cid, why, **m):
        rejected.append({"id": cid, "measure": m, "why": why})

    if q_esr > STABLE_MAX or q_tail > TAIL_OFF_DB:
        rej("full", "with everything listed off, the sound still moves or rings: an effect the recipe doesn't know is on",
            self_esr=round(q_esr, 6), tail_db=round(q_tail, 1))
    for cid, t in tests.items():
        grp, c = t[0], t[1]
        if grp == "declared":
            declared.append(f"{cid}:{t[2]}")
            continue
        if grp == "part":
            y = renders[f"part-{cid}"]
            pk, esr = m_peak(y), m_self_esr(y)
            m = {"peak": round(pk, 4), "self_esr": round(esr, 6)}
            if pk < 1e-3:
                rej(cid, "this part renders silence", **m)
            elif pk >= 0.999 and not c.get("ir"):         # un rendu IR est en flottant : seule sa linéarité compte
                rej(cid, "this part clips", **m)
            elif esr > STABLE_MAX:
                rej(cid, "this part still moves over time", **m)
            elif c.get("ir"):
                lin = m_null_db(y, renders[f"part-{cid}-half"], scale=2.0)
                m["linear_db"] = round(lin, 1)
                if lin < LINEAR_DB:
                    verified.append(cid)
                else:
                    rej(cid, "this part is not linear: something besides the cab is still on", **m)
            else:
                verified.append(cid)
            measures[cid] = m
            continue
        on = renders[f"on-{cid}"]
        esr, tail = m_self_esr(on), m_tail_db(on)
        m = {"self_esr": round(esr, 6), "tail_db": round(tail, 1)}
        if grp == "refuse":
            audible = m_null_db(on, q)
            m["on_vs_off_db"] = round(audible, 1)
            if audible < AUDIBLE_DB:
                rej(cid, "has no audible effect", **m)
            elif c.get("kind") == "pitch":
                verified.append(cid)                     # audible, et il bloque à raison ; la HAUTEUR n'est pas mesurée
                declared.append(f"{cid}:nature")
            elif esr > MOVES_MIN or tail > TAIL_ON_DB:
                verified.append(cid)
            else:
                rej(cid, "doesn't move the sound: it could be captured", **m)
        elif grp == "translate":
            if c.get("block") in ("delay", "reverb"):
                if tail > TAIL_ON_DB:
                    verified.append(cid)
                else:
                    rej(cid, "leaves no tail: not a delay or reverb", **m)
            else:
                declared.append(f"{cid}:nature")
        elif grp == "captured":
            audible = m_null_db(on, renders[f"off-{cid}"])
            m["on_vs_off_db"] = round(audible, 1)
            if audible < AUDIBLE_DB:
                # mesuré le 2026-10-10 (une suite d'ampli, EQ réglé à plat) : un élément CAPTURÉ qui ne s'entend pas avec CES réglages
                # n'est pas une affirmation fausse — il ne change rien à la capture. Seul un `refuse` inaudible est faux.
                declared.append(f"{cid}:inaudible with your settings")
            elif esr > STABLE_MAX or tail > TAIL_OFF_DB:
                rej(cid, "moves or rings: it can't be captured", **m)
            else:
                verified.append(cid)
                declared.append(f"{cid}:nature")
        measures[cid] = m
    return verified, rejected, declared, measures


def bench_fault(renders):
    """Le banc a-t-il SONNÉ ? Rend la raison s'il n'a pas reçu la sonde — jamais un verdict sur la recette.
    ⚠ 2026-10-10 (une suite d'ampli, job 3) : lancée à la seconde où golem redémarrait, une vérification a rendu le bruit de
    fond seul (−148 dB, self_esr ≈ 2 = deux bruits indépendants, parties muettes) ; l'ack « rejected » est parti,
    l'IA de golem.fm en a tiré « unsupported ». Rejouée au calme, la MÊME mesure : verified, 9 sur 9."""
    q = renders.get("quiet") or []
    sig = q[:2 * T_PROBE + int(GAP_S * PC.SR)]
    lvl = _energy(sig) / max(len(sig), 1)
    if lvl <= 0 or 10 * math.log10(lvl) < -100:
        return "the plugin received no signal on the test bench"
    if m_self_esr(q) > 0.5 or m_tail_db(q) > -20:
        return "the test bench rendered noise, not the plugin"
    return None


def verify(draft, sht, plugin, chunk, work=None, retry_s=30):
    """Le `result` de l'ack (§6.2) : {status, verified, rejected, declared, errors, probe_s, renders, measures}."""
    t0 = time.time()
    errors = check_draft(draft, sht)
    if errors:
        return {"status": "invalid", "verified": [], "rejected": [], "declared": [], "errors": errors, "probe_s": 0}
    work = Path(work or (PC.train_home().parent / "recipes" / _slug(plugin)))
    work.mkdir(parents=True, exist_ok=True)
    configs, tests = plan(draft, sht)
    renders = render_many(plugin, chunk, configs, work)
    fault = bench_fault(renders)
    if fault:                                            # une fois encore, après une pause ; puis « pas pu mesurer »
        log.warning(f"recette {plugin} : {fault} — nouvelle mesure dans {retry_s} s")
        time.sleep(retry_s)
        renders = render_many(plugin, chunk, configs, work)
        fault = bench_fault(renders)
        if fault:
            raise RuntimeError(fault)                    # ack ok:false — jamais un « rejected » tiré d'un banc muet
    verified, rejected, declared, measures = judge(tests, renders)
    bad = {r["id"] for r in rejected}
    parts = {p["id"] for p in (draft.get("split") or {}).get("parts") or []}
    if "full" in bad or not verified:
        status = "rejected"
    elif bad:
        status = "partial"
    else:
        status = "verified"
    if parts & bad:                                      # une capture par effet incomplète serait fausse
        declared.append("split:dropped")
    return {"status": status, "verified": verified, "rejected": rejected, "declared": declared, "errors": [],
            "probe_s": round(time.time() - t0, 1), "renders": len(configs), "measures": measures,
            "rack": {"os": rack_os()}}


# ── les ÉCHANGES avec golem.fm (§2-§8) et l'état LOCAL d'une recette ────────────────────────────────────
# Un fichier par plugin, `config/plugin-recipes/<slug>.json` : {plugin, os, plugin_version, block, request_id,
# state, draft, verification, error, updated}. `state` : analyzing → verifying → to-validate → validated, ou
# unsupported | failed | rejected. Seule une recette `validated` sert à la capture (`recipe_for`).
API = "/api/ext/golem/plugin-recipes"
import threading as _threading
_lock = _threading.Lock()


def _path(plugin):
    return LOCAL_DIR / f"{_slug(plugin)}.json"


def load(plugin):
    try:
        return json.loads(_path(plugin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(plugin, **kw):
    from .store import _write_json_atomic
    with _lock:
        doc = load(plugin) or {"plugin": plugin}
        doc.update(kw, updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(str(_path(plugin)), doc, indent=1)
    return doc


def _by_request(request_id):
    for f in LOCAL_DIR.glob("*.json") if LOCAL_DIR.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("request_id") == request_id:
            return d
    return None


def _http(method, path, body=None, timeout=30):
    """(status, corps JSON ENTIER) — `golemfm._req` ne garde que le message d'une erreur ; golem.fm y met un
    `code` (`unsupported`, `schema`, `ai_quota`) que le tiroir doit lire."""
    import urllib.error
    import urllib.request
    from .golemfm import _cfg
    base, token = _cfg()
    if not base or not token:
        return 0, {"error": "not paired with golem.fm"}
    req = urllib.request.Request(base + path, method=method)
    req.add_header("Authorization", "Bearer " + token)
    if body is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(body).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": str(e)}
        # FastAPI range l'erreur sous `detail` (golem.fm, 2026-10-10) : {"detail": {"code"|"error", "message"}}
        # ou {"detail": "<phrase>"} — remonté au premier niveau, là où le tiroir le lit
        d = body.get("detail") if isinstance(body, dict) else None
        if isinstance(d, dict):
            return e.code, dict(d, error=d.get("error") or d.get("message"))
        if isinstance(d, str):
            return e.code, {"error": d}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}


def applied(draft, verification, edits=None):
    """La recette qui SERT : le brouillon privé de ses affirmations rejetées par la mesure ET de celles que le musicien
    a retirées, avec ses noms à lui (`edits` : [{id, label}] ou [{id, removed: true}]) ; un split dont une partie
    manque est retiré entier (une capture par effet incomplète serait fausse)."""
    bad = {r["id"] for r in (verification or {}).get("rejected") or []}
    bad |= {e["id"] for e in edits or [] if e.get("removed")}
    names = {e["id"]: str(e["label"])[:60] for e in edits or [] if e.get("label") and not e.get("removed")}
    d = json.loads(json.dumps(draft))
    for _g, c in _claims(d):
        if c.get("id") in names:
            c["label"] = names[c["id"]]
            if c.get("show"):
                c["show"] = names[c["id"]]
    full = d.setdefault("full", {})
    for key in ("refuse", "captured"):
        full[key] = [c for c in full.get(key) or [] if c.get("id") not in bad]
    d["translate"] = [t for t in d.get("translate") or [] if t.get("id") not in bad]
    if any(p.get("id") in bad for p in (d.get("split") or {}).get("parts") or []):
        d.pop("split", None)
    return d


def validated_recipe(plugin):
    """La recette VALIDÉE par le musicien sur ce rack, prête pour `plugin_capture` ; sinon None."""
    doc = load(plugin)
    if not doc or doc.get("state") != "validated" or not doc.get("draft"):
        return None
    return applied(doc["draft"], doc.get("verification"), doc.get("edits"))


def analyze(block, plugin):
    """Le geste « Analyze this plugin » : fiche (REAPER séparé), puis une recette déjà validée ailleurs (①), sinon
    une demande d'analyse (②). Rend l'état local. Lent (~11 s de fiche) : à appeler hors de la boucle d'événements."""
    # une analyse NEUVE oublie la demande d'avant : sinon le tiroir, en relisant l'état pendant la fiche, interrogeait
    # golem.fm sur l'ANCIEN request_id et recopiait son `failed` (vu le 2026-10-10 au rejeu d'une suite d'ampli)
    _save(plugin, state="analyzing", step="sheet", block=block, error=None, draft=None, verification=None, edits=[],
          request_id=None, shared=False, waiting=None)
    try:
        state = PC._live_state(block)
        sht = sheet(block, plugin)
    except Exception as e:
        return _save(plugin, state="failed", error=f"could not read the plugin: {e}")
    work = PC.train_home().parent / "recipes" / _slug(plugin)
    work.mkdir(parents=True, exist_ok=True)
    (work / "sheet.json").write_text(json.dumps(sht), encoding="utf-8")
    (work / "state.json").write_text(json.dumps(state), encoding="utf-8")   # l'état mesuré, même si le bloc change
    _save(plugin, os=sht["os"], plugin_version=sht["plugin_version"], step="ai",
          sheet_counts={"params": len(sht["params"]), "switches": len(sht["steps"])})
    from urllib.parse import urlencode
    q = urlencode({"plugin": plugin, "os": sht["os"], "version": sht["plugin_version"] or ""})
    st, body = _http("GET", f"{API}?{q}")
    if st == 200 and isinstance(body, dict) and body.get("recipe"):
        rid = f"shared-{int(time.time())}"
        _save(plugin, state="verifying", step="measure", request_id=rid, shared=True,
              shared_validations=(body.get("validated") or {}).get("count"))
        _start_verify(plugin, body["recipe"], rid, ack_job=None)
        return load(plugin)
    if st == 409 and (body or {}).get("code") == "unsupported":
        return _save(plugin, state="unsupported", error=(body or {}).get("error"))
    if sht.get("instrument"):
        return _save(plugin, state="unsupported", error="instruments are not captured")
    st, body = _http("POST", f"{API}/analyze", sht, timeout=60)
    if st == 202 and (body or {}).get("request_id"):
        return _save(plugin, state="analyzing", request_id=body["request_id"], error=None)
    code = (body or {}).get("code") or (body or {}).get("error")
    if st == 409 and code == "unsupported":
        return _save(plugin, state="unsupported", error=(body or {}).get("error"))
    why = {"ai_quota": "golem.fm's AI quota for this month is used up", "ai_off": "golem.fm's AI is off right now",
           "schema": "this golem is too old for golem.fm's recipes"}.get(code) or f"golem.fm answered {st}: {code}"
    return _save(plugin, state="failed", error=why)


def poll(plugin):
    """Une demande sans job (IA en panne, refus de l'IA) ne se lit que par GET /analyze/{id} (golem.fm, 2026-10-10)."""
    doc = load(plugin)
    if not doc or doc.get("state") != "analyzing" or not doc.get("request_id"):
        return doc
    st, body = _http("GET", f"{API}/analyze/{doc['request_id']}")
    s = (body or {}).get("status") if st == 200 else None
    if s in ("unsupported", "failed"):
        return _save(plugin, state=s, error=(body or {}).get("error") or s)
    return doc


def on_job(job):
    """Job `plugin-recipe` {request_id, plugin, sha} : le brouillon arrive. La vérification tourne À CÔTÉ de la file
    (≈1 min, et elle attend que le rack soit libre) ; elle envoie l'ack elle-même. Rend ASYNC_ACK."""
    rid, plugin = job.get("request_id"), job.get("plugin")
    doc = _by_request(rid) or (load(plugin) if plugin else None)
    if not doc:
        raise RuntimeError(f"unknown request {rid}")
    from . import tones_jobs as _tj
    from .tones_jobs import _blob_bytes
    draft = json.loads(_blob_bytes(job, f".plugin-recipe-{_slug(doc['plugin'])}.tmp").decode("utf-8"))
    _save(doc["plugin"], state="verifying", step="measure", request_id=rid,
          claims=len(_claims(draft)), shared=False)
    _start_verify(doc["plugin"], draft, rid, ack_job=_tj.job_id(job))
    return ASYNC_ACK


ASYNC_ACK = object()      # tones_jobs : « l'ack partira plus tard, de la vérification »


def _start_verify(plugin, draft, rid, ack_job):
    def run():
        result, err = None, None
        try:
            from .reamp import busy_reason
            # jamais pendant une prise, en Gig, un morceau qui joue ou se charge — mais SANS les 10 min sans geste du
            # reamp : ce REAPER séparé ne prend pas le moteur, et la demande vient d'un geste (mesuré le 2026-10-10 :
            # la première analyse réelle attendait derrière son propre POST)
            while (why := busy_reason(idle=False)):
                _save(plugin, waiting=why)
                time.sleep(15)
            _save(plugin, waiting=None)
            work = PC.train_home().parent / "recipes" / _slug(plugin)
            sht = json.loads((work / "sheet.json").read_text(encoding="utf-8"))
            chunk = json.loads((work / "state.json").read_text(encoding="utf-8"))["chunk"]
            result = verify(draft, sht, plugin, chunk, work)
            result["request_id"] = rid
            usable = result["status"] in ("verified", "partial")
            _save(plugin, state="to-validate" if usable else result["status"], draft=draft, verification=result,
                  error=None if usable else "the measures rejected this recipe")
        except Exception as e:
            err = str(e)[:500]
            log.warning(f"recette {plugin} : vérification impossible ({err})")
            _save(plugin, state="failed", error=f"the measure could not run: {err}")
        if ack_job is not None:                          # §6.2 : ok dès que la mesure a eu lieu
            from .tones_jobs import _req, async_done
            body = {"ok": True, "result": result} if result else {"ok": False, "error": err}
            try:
                _req("POST", f"/api/ext/tones/jobs/{ack_job}/ack", body=body)
            finally:
                async_done(ack_job)
        elif result and result.get("rejected") and load(plugin).get("shared"):
            report(plugin, result["rejected"])           # une recette partagée qui ne tient pas ici (§8)
    _threading.Thread(target=run, daemon=True, name=f"recipe-verify-{_slug(plugin)}").start()


def validate(plugin, edits=None):
    """« This matches my plugin » : la recette sert sur ce rack, et part sur golem.fm pour les autres (§8)."""
    doc = load(plugin)
    if not doc or doc.get("state") != "to-validate":
        raise ValueError("nothing to validate for this plugin")
    doc = _save(plugin, state="validated", edits=list(edits or []), validated_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    st, body = _http("POST", API, {"plugin": plugin, "format": _format(plugin), "os": doc.get("os"),
                                   "plugin_version": doc.get("plugin_version"), "recipe": doc["draft"],
                                   "verification": doc.get("verification"), "edits": doc["edits"],
                                   "validated_at": doc["validated_at"]})
    return _save(plugin, shared_status=st, shared_error=None if st in (200, 201) else (body or {}).get("error"))


def report(plugin, rejected):
    doc = load(plugin) or {}
    return _http("POST", f"{API}/report", {"plugin": plugin, "format": _format(plugin), "os": doc.get("os"),
                                           "plugin_version": doc.get("plugin_version"), "rejected": rejected})


def forget(plugin):
    """Retirer la recette locale (le musicien la refuse, ou veut relancer l'analyse)."""
    _path(plugin).unlink(missing_ok=True)
