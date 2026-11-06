#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le cœur ampli + baffle sonne-t-il pareil sous Linux et sous Windows/macOS ? — mesuré, pas supposé.

Le rack Linux joue un .nam dans le NAM LV2 de Mike Oliphant et une IR dans le convolveur x42 ;
Windows et macOS jouent les deux dans le NeuralAmpModeler VST3 officiel (bridge/compile_rig.py,
_native_core_for). Deux moteurs, deux convolveurs, les mêmes fichiers. Ce banc rend les MÊMES
signaux à travers les MÊMES fichiers des deux côtés, puis compare échantillon par échantillon.

  1. ./tools/check-core-parity.py fixtures --di <prise.wav> --model a2=<x.nam> --model wavenet=<y.nam> --ir <z.wav> --out F
  2. Linux   : ./tools/check-core-parity.py render-lv2 --fixtures F --out L
     (compile tools/core_render_lv2.c : un hôte LV2 minimal qui charge les binaires mêmes de Reaper)
  3. Windows : python tools\\check-core-parity.py render-native --reaper <reaper.exe> --fixtures F --out W
     (REAPER natif + NeuralAmpModeler VST3, posé comme golem_rig.load_native_core : une instance
     modèle seul, une instance IR seule, porte de bruit / tone stack / normalisation coupées)
  4. ./tools/check-core-parity.py compare L W

Les cas : `none` (rien : calibre l'hôte), `ir` (IR seule), `amp-<m>` (modèle seul), `dual-<m>`
(modèle puis IR), pour chaque signal (`di` : une vraie prise ; `sweep` : balayage 20 Hz-20 kHz à -24
puis -6 dBFS). Le rapport donne, par cas : l'écart de niveau, le décalage, et la PROFONDEUR DU NUL
(résidu après alignement et égalisation du gain : -60 dB = identique à l'oreille, -20 dB = entendu).

Né du 2026-10-01 : golem.fm voulait savoir si une annonce du Store sonne pareil hors de l'OS de son
auteur. La réponse était « jamais mesuré » ; elle ne l'est plus.
"""
import argparse
import importlib.util
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SR = 48000
SIGNALS = ("di", "sweep")
PRE_S = 2                 # secondes de pré-roulement des rendus natifs, retirées à la lecture


# ── WAV ───────────────────────────────────────────────────────────────────────
def write_f32(path, x):
    data = struct.pack(f"<{len(x)}f", *x)
    head = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 3, 1, SR, SR * 4, 4, 32) + b"data" + struct.pack("<I", len(data)))
    Path(path).write_bytes(head + data)


def read_first_channel(path):
    """Premier canal d'un WAV PCM 16/24/32 ou float32, en flottants."""
    raw = Path(path).read_bytes()
    pos, fmt, ch, rate, bits = 12, None, 1, SR, 16
    while pos + 8 <= len(raw):
        cid, size = raw[pos:pos + 4], struct.unpack("<I", raw[pos + 4:pos + 8])[0]
        body = raw[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt, ch, rate = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
            if fmt == 0xFFFE:
                fmt = struct.unpack("<H", body[24:26])[0]
        elif cid == b"data":
            width = bits // 8
            frame = width * ch
            n = len(body) // frame
            if fmt == 3 and bits == 32:
                allv = struct.unpack(f"<{n * ch}f", body[:n * frame])
                return list(allv[::ch]), rate
            scale = float(2 ** (bits - 1))
            return [int.from_bytes(body[i:i + width], "little", signed=True) / scale
                    for i in range(0, n * frame, frame)], rate
        pos += 8 + size + (size & 1)
    raise RuntimeError(f"{path} : pas de données")


def cases(fixtures):
    models = json.loads((Path(fixtures) / "models.json").read_text())
    out = []
    for sig in SIGNALS:
        out += [(sig, "none", None), (sig, "ir", None)]
        for m in models:
            out += [(sig, f"amp-{m}", m), (sig, f"dual-{m}", m)]
    return out


# ── 1. les fixtures ───────────────────────────────────────────────────────────
def cmd_fixtures(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    x, rate = read_first_channel(a.di)
    if rate != SR:
        raise SystemExit("la DI doit être à 48 kHz")
    x = [v * 10 ** (a.di_gain / 20) for v in x[:SR * a.di_seconds]]
    write_f32(out / "di.wav", x)

    def sweep(amp, secs=8, f1=20.0, f2=20000.0):
        k = secs / math.log(f2 / f1)
        return [amp * math.sin(2 * math.pi * f1 * k * (math.exp(t / SR / k) - 1)) for t in range(secs * SR)]
    sil = [0.0] * SR
    write_f32(out / "sweep.wav", sweep(10 ** (-24 / 20)) + sil + sweep(10 ** (-6 / 20)) + sil)
    models = {}
    for spec in a.model:
        name, path = spec.split("=", 1)
        shutil.copyfile(path, out / f"{name}.nam")
        models[name] = Path(path).name
    shutil.copyfile(a.ir, out / "ir.wav")
    (out / "models.json").write_text(json.dumps(models, indent=1))
    print(f"fixtures dans {out} : di ({len(x) / SR:.0f} s), sweep, IR, modèles {list(models)}")


# ── 2. Linux : les binaires LV2 du rack, hors Reaper ──────────────────────────
def cmd_render_lv2(a):
    out, fx = Path(a.out), Path(a.fixtures)
    out.mkdir(parents=True, exist_ok=True)
    host = out / "core_render_lv2"
    subprocess.run(["cc", "-O2", "-pthread", str(ROOT / "tools" / "core_render_lv2.c"), "-o", str(host), "-ldl"],
                   check=True)
    for sig, case, model in cases(fx):
        dst = out / f"{sig}-{case}.wav"
        src = fx / f"{sig}.wav"
        if case == "none":
            shutil.copyfile(src, dst)
            continue
        if case == "ir":
            argv = ["ir", src, dst, fx / "ir.wav"]
        elif case.startswith("amp-"):
            argv = ["amp", src, dst, fx / f"{model}.nam"]
        else:
            argv = ["dual", src, dst, fx / f"{model}.nam", fx / "ir.wav"]
        r = subprocess.run([str(host), *map(str, argv)], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"{sig}-{case} : {r.stderr.strip()[-300:]}")
        print(f"{sig}-{case} rendu")
    (out / "engine.json").write_text(json.dumps({"os": sys.platform, "amp": "neural_amp_modeler LV2 (Oliphant)",
                                                 "ir": "x42 zeroconvo CfgMono"}, indent=1))


# ── 3. Windows / macOS : REAPER natif + NAM VST3, comme golem_rig ─────────────
def _native_bench():
    spec = importlib.util.spec_from_file_location("check_native_nam", ROOT / "tools" / "check-native-nam.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _lua(path):
    return json.dumps(Path(path).resolve().as_posix(), ensure_ascii=False)


def native_script(bench, fx, work, calibrated=False, amp_engine="vst3"):
    # --calibrated : ce que fait le NAM LV2 du rack Linux (nam_plugin.cpp) — étalonnage d'entrée
    # à 12 dBu d'après `input_level_dbu`, sortie normalisée d'après `loudness`
    # ⚠ TrackFX_SetParam prend une valeur NORMALISÉE 0-1 sur ce VST3 (12 donnait 60 dBu, 1 donnait
    # « Calibrated ») : les réglages non binaires se visent par leur valeur AFFICHÉE (`shown`).
    # Et sur l'instance IR seule, +18 dB : le NAM officiel applique -18 dB fixes à TOUTE IR
    # (AudioDSPTools, ImpulseResponse::_SetWeights, à 48 kHz), le x42 du rack aucun.
    calib = ('wanted.CalibrateInput = 1; shown.OutputMode = "Normalized"; shown.InputCalibrationLevel = 12; '
             'if model == "" then shown.Output = 18 end' if calibrated else "")
    trace = work / "create.txt"
    blocks = []
    for sig, case, model in cases(fx):
        project = work / f"{sig}-{case}.rpp"
        nam = _lua(fx / f"{model}.nam") if model else '""'
        ir = _lua(fx / "ir.wav")
        if case == "none":
            chain = ""
        elif case == "ir":
            chain = f'if not add("", {ir}, "cab") then return end'
        elif case.startswith("amp-"):
            chain = f'if not add({nam}, "", "amp") then return end'
        else:
            chain = (f'if not add({nam}, "", "amp") then return end\n'
                     f'if not add("", {ir}, "cab") then return end')
        blocks.append(f'''
clear()
local tr = new_track({_lua(fx / f"{sig}.wav")})
if not tr then return end
CUR = tr
{chain}
save({_lua(project)}, "{sig}-{case}")
''')
    body = f'''
local f = assert(io.open({_lua(trace)}, "w"))
local function die(m) f:write("error=" .. tostring(m) .. "\\n"); f:close(); error(m) end
local LEN = 0
local PRE = {PRE_S}       -- pré-roulement : un plugin qui charge son fichier en tâche de fond a le temps
AMP_ENGINE = "{amp_engine}"
function clear()
  for i = reaper.CountTracks(0) - 1, 0, -1 do reaper.DeleteTrack(reaper.GetTrack(0, i)) end
  local master = reaper.GetMasterTrack(0)
  for i = reaper.TrackFX_GetCount(master) - 1, 0, -1 do reaper.TrackFX_Delete(master, i) end
end
function new_track(path)
  reaper.InsertTrackAtIndex(0, true)
  local tr = reaper.GetTrack(0, 0)
  local item = reaper.AddMediaItemToTrack(tr)
  local take = reaper.AddTakeToMediaItem(item)
  local src = reaper.PCM_Source_CreateFromFile(path)
  if not src then die("signal introuvable " .. path) end
  reaper.SetMediaItemTake_Source(take, src)
  LEN = reaper.GetMediaSourceLength(src)
  reaper.SetMediaItemInfo_Value(item, "D_LENGTH", LEN)
  reaper.SetMediaItemInfo_Value(item, "D_POSITION", PRE)
  -- ⚠ REAPER pose des fondus automatiques sur un item neuf : sans ça, le cas « none » ne
  -- s'annulait qu'à -38 dB contre l'entrée (mesuré le 2026-10-01)
  for _, k in ipairs({{"D_FADEINLEN", "D_FADEOUTLEN", "D_FADEINLEN_AUTO", "D_FADEOUTLEN_AUTO"}}) do
    reaper.SetMediaItemInfo_Value(item, k, 0)
  end
  return tr
end
-- exactement golem_rig.load_native_core : une instance par fichier, porte/tone stack/normalisation coupées
-- le NAM LV2 de Mike Oliphant (celui du rack Linux), modèle posé comme golem_rig le pose :
-- une ligne « P …#model <fichier> 3 » dans le <STATE de son bloc
function add_lv2_amp(tr, model)
  local fx = reaper.TrackFX_AddByName(tr, "LV2: Neural Amp Modeler", false, -1000 - reaper.TrackFX_GetCount(tr))
  if fx < 0 then die("NAM LV2 absent") end
  local ok, chunk = reaper.GetTrackStateChunk(tr, "", false)
  if not ok then die("chunk illisible") end
  local lines = {{}}
  for l in (chunk .. "\\n"):gmatch("(.-)\\n") do lines[#lines + 1] = l end
  local lv2 = nil
  for i, l in ipairs(lines) do if l:match("^%s*<LV2") then lv2 = i end end
  if not lv2 then die("bloc LV2 introuvable dans le chunk") end
  local at, close, depth = nil, nil, 1
  for i = lv2 + 1, #lines do
    local t = lines[i]:match("^%s*(.-)%s*$")
    if depth == 1 and t:match("^<STATE") then at = i end
    if t:sub(1, 1) == "<" then depth = depth + 1
    elseif t == ">" then depth = depth - 1; if depth == 0 then close = i; break end end
  end
  local pline = "P http://github.com/mikeoliphant/neural-amp-modeler-lv2#model " .. model .. " 3"
  if at then table.insert(lines, at + 1, pline)
  elseif close then            -- sous Windows, une instance neuve n'a pas de <STATE : on le crée
    table.insert(lines, close, ">"); table.insert(lines, close, pline); table.insert(lines, close, "<STATE")
  else die("fin du bloc LV2 introuvable") end
  if not reaper.SetTrackStateChunk(tr, table.concat(lines, "\\n"), false) then die("SetTrackStateChunk refusé") end
  f:write("lv2 amp " .. model .. "\\n")
  return fx
end
function add(model, ir, id)
  local tr = CUR
  if model ~= "" and AMP_ENGINE == "lv2" then return add_lv2_amp(tr, model) end
  local fx = reaper.TrackFX_AddByName(tr, "VST3: NeuralAmpModeler", false, -1000 - reaper.TrackFX_GetCount(tr))
  if fx < 0 then die("VST3 NAM absent") end
  local ok, state = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
  if not ok then die("lecture d'état refusée") end
  local changed, err = nam_state_with_files(state, model, ir)
  if not changed then die(err) end
  if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", changed) then die("écriture d'état refusée") end
  local wanted = {{ NoiseGateActive = 0, ToneStack = 0, OutputMode = 0, IRToggle = ir ~= "" and 1 or 0 }}
  local shown = {{}}
  {calib}
  for k in pairs(shown) do wanted[k] = nil end
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if wanted[name] ~= nil then reaper.TrackFX_SetParam(tr, fx, p, wanted[name]) end
    local target = shown[name]
    if type(target) == "string" then            -- énumération : on balaie jusqu'au libellé
      for i = 0, 100 do
        reaper.TrackFX_SetParamNormalized(tr, fx, p, i / 100)
        local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
        if s == target then break end
      end
    elseif type(target) == "number" then        -- continu et croissant : dichotomie sur l'affiché
      local lo, hi = 0.0, 1.0
      for _ = 1, 40 do
        local mid = (lo + hi) / 2
        reaper.TrackFX_SetParamNormalized(tr, fx, p, mid)
        local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
        if (tonumber(s:match("[-%d%.]+")) or 0) < target then lo = mid else hi = mid end
      end
      reaper.TrackFX_SetParamNormalized(tr, fx, p, hi)
    end
    local _, shown = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")   -- relu APRÈS l'écriture
    f:write("param " .. id .. " " .. name .. " = " .. tostring(shown) .. "\\n")
  end
  return fx
end
function save(project, name)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE", {SR}, true)
  reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 1, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", {_lua(work)}, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", name .. "-render", true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "ZXZhdyAAAQ==", true)   -- WAV 32 bits flottants
  reaper.GetSet_LoopTimeRange(true, false, 0, PRE + LEN, false)
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)
  reaper.GetSetProjectInfo(0, "RENDER_SRATE", {SR}, true)
  reaper.GetSetProjectInfo(0, "RENDER_TAILFLAG", 0, true)
  reaper.Main_SaveProjectEx(0, project, 0)
  f:write("saved " .. name .. "\\n")
end
{"".join(blocks)}
f:write("ready\\n")
f:close()
'''
    return bench.nam_helpers() + body.replace("{PRE_S}", str(PRE_S)), trace


def cmd_render_native(a):
    bench = _native_bench()
    fx, out = Path(a.fixtures).resolve(), Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    reaper = Path(a.reaper).resolve()
    config = out / "reaper.ini"
    config.write_text("[REAPER]\nnolastproject=1\nopenallrecent=0\n[audioconfig]\nmode=4\n", encoding="ascii")
    script, trace = native_script(bench, fx, out, a.calibrated, a.amp_engine)
    startup = out / "Scripts" / "__startup.lua"
    startup.parent.mkdir(parents=True, exist_ok=True)
    startup.write_text(script, encoding="utf-8")
    trace.unlink(missing_ok=True)
    last = out / f"{cases(fx)[-1][0]}-{cases(fx)[-1][1]}.rpp"
    last.unlink(missing_ok=True)
    proc = bench.launch(reaper, config, [], out / "create.log")
    try:
        bench.wait_for_project(proc, trace, last, timeout=600)
    finally:
        bench.stop(proc)
        startup.unlink(missing_ok=True)
    for sig, case, _m in cases(fx):
        name = f"{sig}-{case}"
        rendered = out / f"{name}-render.wav"
        rendered.unlink(missing_ok=True)
        proc = bench.launch(reaper, config, ["-renderproject", str(out / f"{name}.rpp")], out / f"render-{name}.log")
        try:
            proc.wait(timeout=300)
        finally:
            bench.stop(proc)
        if not rendered.is_file():
            raise SystemExit(f"{name} : pas de rendu (REAPER exit {proc.returncode})")
        x, _ = read_first_channel(rendered)
        write_f32(out / f"{name}.wav", x[PRE_S * SR:])
        print(f"{name} rendu")
    (out / "engine.json").write_text(json.dumps({"os": sys.platform, "amp": "NeuralAmpModeler VST3",
                                                 "ir": "NeuralAmpModeler VST3 (IR seule)"}, indent=1))


# ── 4. la comparaison ─────────────────────────────────────────────────────────
def _metrics(a, b):
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    # décalage : corrélation croisée par FFT, ±4096 échantillons
    size = 1 << int(np.ceil(np.log2(2 * n)))
    xc = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    lags = np.concatenate([xc[:4097], xc[-4096:]])
    k = int(np.argmax(np.abs(lags)))
    lag = k if k <= 4096 else k - len(lags)
    if lag > 0:
        a2, b2 = a[lag:], b[:n - lag]
    elif lag < 0:
        a2, b2 = a[:n + lag], b[-lag:]
    else:
        a2, b2 = a, b
    rms = lambda v: float(np.sqrt(np.mean(v * v)) + 1e-15)
    level = 20 * np.log10(rms(b2) / rms(a2))
    g = float(np.dot(a2, b2) / (np.dot(b2, b2) + 1e-30))      # b recalé sur a, au sens des moindres carrés
    null = 20 * np.log10(rms(a2 - g * b2) / rms(a2))
    raw_null = 20 * np.log10(rms(a2 - b2) / rms(a2))
    # écart spectral par tiers d'octave, 40 Hz-16 kHz, après égalisation du gain
    win = np.hanning(8192)
    def psd(v):
        frames = [v[i:i + 8192] * win for i in range(0, len(v) - 8192, 4096)]
        return np.mean([np.abs(np.fft.rfft(fr)) ** 2 for fr in frames], axis=0)
    pa, pb = psd(a2), psd(g * b2)
    freqs = np.fft.rfftfreq(8192, 1 / SR)
    worst, where = 0.0, 0.0
    fc = 40.0
    while fc < 16000:
        sel = (freqs >= fc / 2 ** (1 / 6)) & (freqs < fc * 2 ** (1 / 6))
        ea, eb = pa[sel].sum(), pb[sel].sum()
        if ea > 1e-12 * pa.sum():
            d = 10 * np.log10((eb + 1e-30) / (ea + 1e-30))
            if abs(d) > abs(worst):
                worst, where = float(d), fc
        fc *= 2 ** (1 / 3)
    return {"lag": lag, "level_db": float(level), "gain_db": float(-20 * np.log10(abs(g) + 1e-30)),
            "null_db": float(null), "raw_null_db": float(raw_null), "band_db": worst, "band_hz": where}


def cmd_compare(a):
    A, B = Path(a.a), Path(a.b)
    ea = json.loads((A / "engine.json").read_text()) if (A / "engine.json").exists() else {}
    eb = json.loads((B / "engine.json").read_text()) if (B / "engine.json").exists() else {}
    print(f"A = {A} ({ea.get('os')}: {ea.get('amp')} + {ea.get('ir')})")
    print(f"B = {B} ({eb.get('os')}: {eb.get('amp')} + {eb.get('ir')})")
    print(f"{'cas':22} {'décalage':>9} {'niveau B-A':>11} {'nul brut':>9} {'nul égalisé':>12} {'pire tiers d’oct.':>20}")
    rows = {}
    for p in sorted(A.glob("*.wav")):
        q = B / p.name
        if not q.exists() or p.name.endswith("-render.wav"):
            continue
        x, _ = read_first_channel(p)
        y, _ = read_first_channel(q)
        m = _metrics(x, y)
        rows[p.stem] = m
        print(f"{p.stem:22} {m['lag']:>6} éch {m['level_db']:>+8.2f} dB {m['raw_null_db']:>+6.1f} dB {m['null_db']:>+9.1f} dB"
              f" {m['band_db']:>+8.2f} dB @ {m['band_hz']:>5.0f} Hz")
    if a.json:
        Path(a.json).write_text(json.dumps({"a": ea, "b": eb, "cases": rows}, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fixtures")
    p.add_argument("--di", required=True)
    p.add_argument("--di-gain", type=float, default=-6.0)
    p.add_argument("--di-seconds", type=int, default=20)
    p.add_argument("--model", action="append", required=True, help="nom=fichier.nam")
    p.add_argument("--ir", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("render-lv2")
    p.add_argument("--fixtures", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("render-native")
    p.add_argument("--reaper", required=True)
    p.add_argument("--calibrated", action="store_true",
                   help="NAM VST3 réglé comme le NAM LV2 du rack (étalonnage 12 dBu, sortie normalisée, IR +18 dB)")
    p.add_argument("--amp-engine", choices=("vst3", "lv2"), default="vst3",
                   help="lv2 = le NAM LV2 d'Oliphant pour le modèle (celui du rack Linux), l'IR restant au VST3")
    p.add_argument("--fixtures", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("compare")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--json")
    a = ap.parse_args()
    {"fixtures": cmd_fixtures, "render-lv2": cmd_render_lv2, "render-native": cmd_render_native,
     "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    main()
