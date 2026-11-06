-- SPDX-License-Identifier: GPL-3.0-or-later
-- Report the audio device actually opened by REAPER to the local GoleM bridge.
local res = reaper.GetResourcePath()
local file = io.open(res .. "/golem-runtime.txt", "r")
if not file then return end
local runtime = file:read("*l")
file:close()
if not runtime or runtime == "" then return end

local function quote(value)
  return '"' .. tostring(value or ""):gsub('\\', '\\\\'):gsub('"', '\\"')
    :gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t') .. '"'
end

local last = 0
local snapshot_request = runtime .. "/desktop-audio-snapshot-request.txt"
local function names(count, get_name)
  local result = {}
  for i = 0, math.min(count, 128) - 1 do
    result[#result + 1] = quote(get_name(i) or ("Channel " .. (i + 1)))
  end
  return '[' .. table.concat(result, ',') .. ']'
end
local function tick()
  local requested = io.open(snapshot_request, "r")
  if requested then
    requested:close()
    os.remove(snapshot_request)
    local ok, err = pcall(dofile, res .. "/Scripts/golem/golem_audio_snapshot.lua")
    if not ok then reaper.ShowConsoleMsg("GoleM audio snapshot: " .. tostring(err) .. "\n") end
  end
  local now = reaper.time_precise()
  if now - last >= 2 then
    last = now
    local fields = {}
    for _, key in ipairs({ "MODE", "IDENT_IN", "IDENT_OUT", "BSIZE", "SRATE" }) do
      local ok, value = reaper.GetAudioDeviceInfo(key)
      if ok then fields[#fields + 1] = quote(key) .. ':' .. quote(value) end
    end
    local input_count = tonumber(reaper.GetNumAudioInputs()) or 0
    local output_count = tonumber(reaper.GetNumAudioOutputs()) or 0
    fields[#fields + 1] = quote("INPUT_COUNT") .. ':' .. tostring(input_count)
    fields[#fields + 1] = quote("OUTPUT_COUNT") .. ':' .. tostring(output_count)
    fields[#fields + 1] = quote("INPUT_NAMES") .. ':' .. names(input_count, reaper.GetInputChannelName)
    fields[#fields + 1] = quote("OUTPUT_NAMES") .. ':' .. names(output_count, reaper.GetOutputChannelName)
    local input_latency, output_latency = reaper.GetInputOutputLatency()
    fields[#fields + 1] = quote("INPUT_LATENCY_SAMPLES") .. ':' .. tostring(tonumber(input_latency) or 0)
    fields[#fields + 1] = quote("OUTPUT_LATENCY_SAMPLES") .. ':' .. tostring(tonumber(output_latency) or 0)
    local audio_xrun, media_xrun, current_time = reaper.GetUnderrunTime()
    fields[#fields + 1] = quote("AUDIO_XRUN_TIME") .. ':' .. tostring(tonumber(audio_xrun) or 0)
    fields[#fields + 1] = quote("MEDIA_XRUN_TIME") .. ':' .. tostring(tonumber(media_xrun) or 0)
    fields[#fields + 1] = quote("XRUN_CLOCK") .. ':' .. tostring(tonumber(current_time) or 0)
    local _, project = reaper.EnumProjects(-1)
    fields[#fields + 1] = quote("PROJECT") .. ':' .. quote(project)
    local out = io.open(runtime .. "/desktop-audio.json", "w")
    if out then out:write('{' .. table.concat(fields, ',') .. '}'); out:close() end
  end
  reaper.defer(tick)
end
tick()
