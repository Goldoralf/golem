#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rend une DI avec NAM VST3 et une IR dans REAPER natif.

Nécessite REAPER et NeuralAmpModeler (0.7.13, ou 0.7.15 golem pour l'A2) déjà
installés. `--model` rend une capture locale au lieu du modèle d'exemple. Les
projets et fichiers générés restent dans --work-dir pour faciliter le diagnostic CI.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
from urllib.request import urlopen
import wave


ROOT = Path(__file__).resolve().parents[1]
MODEL_URL = ("https://raw.githubusercontent.com/sdatkinson/NeuralAmpModelerCore/"
             "0b3d3c97b0859a3a8c92a8628c4dd89a25eb5842/example_models/wavenet.nam")
MODEL_SHA256 = "66bda2b379289eff079c0755588bc9a92760654d9cc9af1b97cf30d0e92b167d"
SAMPLE_RATE = 48000


def lua_string(path):
    return json.dumps(Path(path).resolve().as_posix(), ensure_ascii=False)


def model_fixture(path):
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        return path
    with urlopen(MODEL_URL, timeout=30) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise RuntimeError("empreinte du modèle NAM officiel incorrecte")
    path.write_bytes(data)
    return path


def tone_fixture(path):
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, SAMPLE_RATE, SAMPLE_RATE, "NONE", "not compressed"))
        out.writeframes(b"".join(struct.pack("<h", round(5000 * math.sin(
            2 * math.pi * 440 * i / SAMPLE_RATE))) for i in range(SAMPLE_RATE)))


def ir_fixture(path):
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, SAMPLE_RATE, SAMPLE_RATE, "NONE", "not compressed"))
        out.writeframes(struct.pack("<h", 20000) + b"\0\0" * (SAMPLE_RATE - 1))


def nam_helpers():
    source = (ROOT / "reaper" / "Scripts" / "golem_rig.lua").read_text(encoding="utf-8")
    try:
        start = source.index('local B64C = "ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        end = source.index("local function load_native_core", start)
    except ValueError as exc:
        raise RuntimeError("helpers NAM absents de golem_rig.lua") from exc
    return source[start:end]


def recording_move_helper():
    source = (ROOT / "reaper" / "Scripts" / "golem_perfrec.lua").read_text(encoding="utf-8")
    start = source.index("local function move_recording(")
    end = source.index("local function find_track(", start)
    return source[start:end]


def state_probe(work):
    """Exercise repeated Lua state publication inside native REAPER on this OS."""
    state = lua_string(work / "state-replace.json")
    src = lua_string(work / "recording-source.wav")
    dst = lua_string(work / "recording-probe" / "recording.wav")
    directory = lua_string(work / "recording-probe")
    helper = lua_string(ROOT / "reaper" / "Scripts" / "golem_paths.lua")
    return f'''
local paths = dofile({helper})
local state = {state}
os.remove(state)
for _, value in ipairs({{"first", "second"}}) do
  local tmp = state .. ".tmp"
  local writer = io.open(tmp, "wb")
  if not writer then die("state tmp inaccessible"); return end
  writer:write(value); writer:close()
  local ok, err = paths.replace(tmp, state)
  if not ok then die("state replace: " .. tostring(err)); return end
end
local reader = io.open(state, "rb")
local current = reader and reader:read("*a")
if reader then reader:close() end
if current ~= "second" then die("second state missing"); return end
os.remove(state)
local function log(_) end
{recording_move_helper()}
reaper.RecursiveCreateDirectory({directory}, 0)
local src, dst = {src}, {dst}
os.remove(src); os.remove(dst)
local wav = io.open(src, "wb")
if not wav then die("recording source inaccessible"); return end
wav:write("audio fixture"); wav:close()
local moved, move_err = move_recording(src, dst)
if not moved then die("recording move: " .. tostring(move_err)); return end
local copied = io.open(dst, "rb")
local recorded = copied and copied:read("*a")
if copied then copied:close() end
if recorded ~= "audio fixture" then die("recording target missing"); return end
local again = io.open(src, "wb")
if not again then die("recording second source inaccessible"); return end
again:write("second fixture"); again:close()
if move_recording(src, dst) then die("recording target overwritten"); return end
local preserved = io.open(src, "rb")
local preserved_data = preserved and preserved:read("*a")
if preserved then preserved:close() end
if preserved_data ~= "second fixture" then die("recording source lost"); return end
local existing = io.open(dst, "rb")
local existing_data = existing and existing:read("*a")
if existing then existing:close() end
if existing_data ~= "audio fixture" then die("recording target changed"); return end
os.remove(src); os.remove(dst)
'''


def project_script(mode, work, model, ir, tone):
    amp_code = (f'local fx, err = add({lua_string(model)}, "", "amp")\n'
                'if not fx then die(err); return end' if mode == "dual" else "")
    project = work / f"native-{mode}.rpp"
    trace = work / f"native-{mode}.txt"
    entered = work / f"native-{mode}-entered.txt"
    body = f'''
local f = assert(io.open({lua_string(trace)}, "w"))
local function die(message)
  f:write("error=" .. tostring(message) .. "\\n")
  f:close()
end
{state_probe(work)}
-- REAPER peut rouvrir le dernier projet malgré -newinst : repartir d'un projet vide.
for i = reaper.CountTracks(0) - 1, 0, -1 do
  reaper.DeleteTrack(reaper.GetTrack(0, i))
end
local master = reaper.GetMasterTrack(0)
for i = reaper.TrackFX_GetCount(master) - 1, 0, -1 do
  reaper.TrackFX_Delete(master, i)
end
reaper.InsertTrackAtIndex(0, true)
local tr = reaper.GetTrack(0, 0)
local item = reaper.AddMediaItemToTrack(tr)
local take = reaper.AddTakeToMediaItem(item)
local source = reaper.PCM_Source_CreateFromFile({lua_string(tone)})
if not source then die("DI introuvable"); return end
reaper.SetMediaItemTake_Source(take, source)
reaper.SetMediaItemInfo_Value(item, "D_LENGTH", 1)
local function add(model, ir, id)
  local fx = reaper.TrackFX_AddByName(tr, "VST3: NeuralAmpModeler", false,
                                      -1000 - reaper.TrackFX_GetCount(tr))
  if fx < 0 then return nil, "VST3 NAM absent" end
  local ok, state = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
  if not ok then return nil, "lecture d'état refusée" end
  local changed, err = nam_state_with_files(state, model, ir)
  if not changed then return nil, err end
  if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", changed) then
    return nil, "écriture d'état refusée"
  end
  local wanted = {{ NoiseGateActive = 0, ToneStack = 0, OutputMode = 0,
                   IRToggle = ir ~= "" and 1 or 0 }}
  local seen = {{}}
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if wanted[name] ~= nil then
      reaper.TrackFX_SetParam(tr, fx, p, wanted[name])
      seen[name] = true
    end
  end
  for name in pairs(wanted) do
    if not seen[name] then return nil, "paramètre absent : " .. name end
  end
  if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "golem:" .. id) then
    return nil, "estampille refusée : " .. id
  end
  local read_ok, readback = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
  if not read_ok then return nil, "relecture d'état refusée" end
  local bytes = unb64(readback)
  local size, kind = string.unpack("<I4I4", bytes)
  if kind ~= 1 or size ~= #bytes - 16 then return nil, "enveloppe VST3 altérée" end
  local payload, pos = bytes:sub(9, 8 + size), 1
  local fields = {{}}
  for n = 1, 4 do
    local len; len, pos = string.unpack("<I4", payload, pos)
    fields[n] = payload:sub(pos, pos + len - 1)
    pos = pos + len
  end
  if fields[3] ~= model or fields[4] ~= ir then return nil, "fichier NAM/IR non rappelé" end
  f:write("fx=" .. fx .. "," .. id .. "\\n")
  return fx
end
{amp_code}
local cab, cab_err = add("", {lua_string(ir) if mode != 'empty' else '""'}, "cab")
if not cab then die(cab_err); return end
local expected = {2 if mode == 'dual' else 1}
if reaper.TrackFX_GetCount(tr) ~= expected then die("nombre de VST incorrect"); return end
reaper.GetSetProjectInfo_String(0, "RENDER_FILE", {lua_string(work)}, true)
reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", "native-{mode}-render", true)
reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "evaw", true)
reaper.GetSet_LoopTimeRange(true, false, 0, 1, false)
reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)
reaper.GetSetProjectInfo(0, "RENDER_SRATE", {SAMPLE_RATE}, true)
reaper.Main_SaveProjectEx(0, {lua_string(project)}, 0)
if not reaper.file_exists({lua_string(project)}) then die("projet non sauvegardé"); return end
f:write("ready\\n")
f:close()
'''
    marker = (f'local probe = io.open({lua_string(entered)}, "w")\n'
              'if probe then probe:write("startup=1\\n"); probe:close() end\n')
    return marker + nam_helpers() + body, project, trace


# 240 s et pas 90 : le TOUT PREMIER lancement de REAPER sur une machine neuve (scan des plugins,
# antivirus) a dépassé 90 s sur la VM Windows le 2026-10-01 — l'outil échouait avec
# « startup=absent », et réussissait à la relance, avec les mêmes RMS que la CI.
def wait_for_project(process, trace, project, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if trace.is_file():
            lines = trace.read_text(encoding="utf-8", errors="replace").splitlines()
            errors = [line for line in lines if line.startswith("error=")]
            if errors:
                raise RuntimeError(errors[-1])
            if "ready" in lines and project.is_file():
                return
        if process.poll() is not None:
            raise RuntimeError(f"REAPER s'est arrêté avant de préparer {project.name} : {process.returncode}")
        time.sleep(0.2)
    entered = trace.with_name(trace.stem + "-entered.txt")
    marker = "present" if entered.is_file() else "absent"
    detail = trace.read_text(encoding="utf-8", errors="replace").strip() if trace.is_file() else "absent"
    if sys.platform == "darwin":
        try:
            subprocess.run(["screencapture", "-x", str(trace.parent / "reaper-screen.png")],
                           capture_output=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError(f"REAPER n'a pas préparé {project.name} après {timeout} s "
                       f"(startup={marker}, trace={detail!r}, processus={process.poll()})")


def first_channel(path):
    with wave.open(str(path), "rb") as rendered:
        frames = rendered.getnframes()
        channels = rendered.getnchannels()
        depth = rendered.getsampwidth()
        rate = rendered.getframerate()
        raw = rendered.readframes(frames)
    if frames < SAMPLE_RATE or rate != SAMPLE_RATE or channels not in (1, 2) or depth not in (2, 3, 4):
        raise RuntimeError(f"format de rendu inattendu : {path}")
    scale = 2 ** (depth * 8 - 1)
    stride = depth * channels
    return [int.from_bytes(raw[i:i + depth], "little", signed=True) / scale
            for i in range(0, SAMPLE_RATE * stride, stride)]


def launch(reaper, config, argument, log_path):
    command = [str(reaper), "-newinst", "-nosplash", "-cfgfile", str(config), *argument]
    with open(log_path, "wb") as output:
        return subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def dismiss_audio_dialog(work, mode, pid):
    script = f'''tell application "System Events"
  set targetProcess to first application process whose unix id is {pid}
  tell targetProcess
    set report to "windows=" & (count of windows as text) & linefeed
    repeat with dialog in windows
      try
        set report to report & "window=" & (name of dialog as text) & linefeed
      end try
      try
        set report to report & "size=" & (size of dialog as text) & ", buttons=" & (count of buttons of dialog as text) & linefeed
      end try
      set directButtonNames to {{}}
      set directTextValues to {{}}
      try
        set directButtonNames to name of every button of dialog
        set report to report & "button-names=" & (directButtonNames as text) & linefeed
      end try
      try
        set directTextValues to value of every static text of dialog
        set report to report & "static-text=" & (directTextValues as text) & linefeed
      end try
      set messageFound to false
      set noButton to missing value
      repeat with elementRef in (entire contents of dialog)
        set axRoleName to ""
        set axElementName to ""
        set axElementValue to ""
        try
          set axRoleName to role of elementRef as text
        end try
        try
          set axElementName to name of elementRef as text
        end try
        try
          set axElementValue to value of elementRef as text
        end try
        if axRoleName is "AXButton" or axRoleName is "AXStaticText" or axElementName contains "audio device" or axElementValue contains "audio device" then
          set report to report & axRoleName & ":" & axElementName & ":" & axElementValue & linefeed
        end if
        if axRoleName is "AXStaticText" and (axElementName contains "You have not yet selected an audio device" or axElementValue contains "You have not yet selected an audio device") then set messageFound to true
        if axRoleName is "AXButton" and axElementName is "No" then set noButton to elementRef
      end repeat
      if messageFound and noButton is not missing value then
        click noButton
        return "dismissed" & linefeed & "method=button" & linefeed & report
      end if
      if (name of dialog as text) is "" and (count of windows) is 2 and (name of window 2 as text) contains "REAPER v7.80 - EVALUATION LICENSE" and (count of buttons of dialog) is 2 and "No" is in directButtonNames and "Yes" is in directButtonNames then
        set dialogSize to size of dialog
        if ((directTextValues as text) contains "You have not yet selected an audio device") or ((item 1 of dialogSize) is greater than 240 and (item 1 of dialogSize) is less than 300 and (item 2 of dialogSize) is greater than 240 and (item 2 of dialogSize) is less than 300) then
          click button "No" of dialog
          return "dismissed" & linefeed & "method=direct-button" & linefeed & report
        end if
      end if
    end repeat
  end tell
end tell
return "not-found" & linefeed & report'''
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True,
                                text=True, timeout=10)
        detail = f"exit={result.returncode}\n{result.stdout}{result.stderr}"
        dismissed = result.returncode == 0 and result.stdout.startswith("dismissed\n")
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail = f"error={exc!r}\n"
        dismissed = False
    (work / f"audio-dialog-{mode}.log").write_text(detail, encoding="utf-8")
    return dismissed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reaper", type=Path, required=True,
                        help="binaire REAPER natif (macOS : REAPER.app/Contents/MacOS/REAPER)")
    parser.add_argument("--work-dir", type=Path, required=True, help="répertoire temporaire inscriptible")
    parser.add_argument("--model", type=Path, help="un .nam à rendre à la place du modèle d'exemple (une capture locale)")
    args = parser.parse_args()
    reaper = args.reaper.resolve()
    if not reaper.is_file():
        raise RuntimeError(f"REAPER absent : {reaper}")
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    config = work / "reaper.ini"
    settings = "[REAPER]\nnolastproject=1\nopenallrecent=0\n"
    if sys.platform == "darwin":
        # macOS stores Core Audio preferences in [REAPER].
        settings += ("coreaudioindevnew=<default system devices>\n"
                     "coreaudiooutdevnew=<default system devices>\n")
    else:
        settings += "[audioconfig]\nmode=0\n"
    config.write_text(settings, encoding="ascii")
    model = args.model.resolve() if args.model else model_fixture(work / "wavenet.nam")
    if not model.is_file():
        raise RuntimeError(f"modèle absent : {model}")
    tone, ir = work / "tone.wav", work / "impulse.wav"
    tone_fixture(tone)
    ir_fixture(ir)
    results = {}
    for mode in ("empty", "ir", "dual"):
        script, project, trace = project_script(mode, work, model, ir, tone)
        script_path = work / "Scripts" / "__startup.lua"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        saved_script = work / f"create-{mode}.lua"
        saved_script.write_text(script, encoding="utf-8")
        shutil.copyfile(saved_script, script_path)
        trace.unlink(missing_ok=True)
        trace.with_name(trace.stem + "-entered.txt").unlink(missing_ok=True)
        project.unlink(missing_ok=True)
        try:
            process = launch(reaper, config, [], work / f"startup-{mode}.log")
            try:
                if sys.platform == "darwin":
                    try:
                        wait_for_project(process, trace, project, timeout=15)
                    except RuntimeError as exc:
                        if process.poll() is not None:
                            raise
                        if not trace.is_file() and not \
                                trace.with_name(trace.stem + "-entered.txt").is_file():
                            # REAPER can show an audio-device chooser before __startup.lua.
                            screenshot = work / "reaper-screen.png"
                            if screenshot.is_file():
                                screenshot.replace(work / f"reaper-screen-before-{mode}.png")
                            if not dismiss_audio_dialog(work, mode, process.pid):
                                raise RuntimeError("invite audio REAPER bloquante ; voir "
                                                   f"audio-dialog-{mode}.log") from exc
                        wait_for_project(process, trace, project)
                else:
                    wait_for_project(process, trace, project)
            finally:
                stop(process)
        finally:
            script_path.unlink(missing_ok=True)
        output = work / f"native-{mode}-render.wav"
        output.unlink(missing_ok=True)
        process = launch(reaper, config, ["-renderproject", str(project)],
                         work / f"render-{mode}.log")
        try:
            try:
                process.wait(timeout=15 if sys.platform == "darwin" else 120)
            except subprocess.TimeoutExpired:
                if sys.platform != "darwin":
                    raise
                try:
                    subprocess.run(["screencapture", "-x", str(work / f"reaper-screen-render-{mode}.png")],
                                   capture_output=True, timeout=5, check=False)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                dismiss_audio_dialog(work, f"render-{mode}", process.pid)
                try:
                    process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    try:
                        subprocess.run(["screencapture", "-x", str(work / f"reaper-screen-render-{mode}-timeout.png")],
                                       capture_output=True, timeout=5, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    raise
        finally:
            stop(process)
        if process.returncode != 0 or not output.is_file():
            raise RuntimeError(f"rendu {mode} absent (REAPER exit {process.returncode})")
        samples = first_channel(output)
        rms = math.sqrt(sum(x * x for x in samples) / len(samples))
        if rms < 1e-5:
            raise RuntimeError(f"rendu {mode} muet (RMS={rms:.6g})")
        results[mode] = samples
        print(f"{mode}: 48 kHz, {len(samples)} échantillons, RMS={rms:.6f}")
    empty, reference, processed = results["empty"], results["ir"], results["dual"]
    rms_empty = math.sqrt(sum(x * x for x in empty) / len(empty))
    rms_ir = math.sqrt(sum(x * x for x in reference) / len(reference))
    if abs(rms_ir / rms_empty - 1) < 0.15:
        raise RuntimeError(f"IR sans effet mesurable (rapport RMS={rms_ir / rms_empty:.3f})")
    difference = math.sqrt(sum((a - b) ** 2 for a, b in zip(reference, processed)) /
                           sum(a * a for a in reference))
    if difference < 0.1:
        raise RuntimeError(f"le modèle NAM ne modifie pas suffisamment le signal ({difference:.3f})")
    print(f"NAM + IR restaurés et audibles ; différence relative au rendu IR seul : {difference:.3f}")


if __name__ == "__main__":
    main()
