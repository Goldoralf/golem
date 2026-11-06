-- SPDX-License-Identifier: GPL-3.0-or-later
-- Régression à froid : capture/relecture VST avec une API REAPER simulée.
-- Depuis la racine : lua tools/check-vst-host.lua
local source, inventory_source, paths_source = ...
if not source then
  local file = assert(io.open("reaper/Scripts/golem_rig.lua", "r"))
  source = file:read("*a"); file:close()
end
local function read_source(path)
  local f = assert(io.open(path, "r")); local s = f:read("*a"); f:close(); return s
end
inventory_source = inventory_source or read_source("reaper/Scripts/golem_fxinventory.lua")
paths_source = paths_source or read_source("reaper/Scripts/golem_paths.lua")
source = source:gsub("\r\n", "\n")
local function section(first, last)
  local a = assert(source:find(first, 1, true))
  local b = assert(source:find(last, a + #first, true))
  return source:sub(a, b - 1)
end
local written, host_bypass = {}, 1
reaper = {
  TrackFX_GetParamFromIdent = function(_, _, ident) assert(ident == ":bypass"); return host_bypass end,
  TrackFX_GetNumParams = function() return 4 end,
  TrackFX_GetParamName = function(_, _, p) return true, ({"Plugin Bypass", "Bypass", "MIDI CC 7", "Gain"})[p + 1] end,
  TrackFX_GetFormattedParamValue = function() return true, "0 dB" end,
  TrackFX_GetParamNormalized = function(_, _, p) return p / 4 end,
  TrackFX_GetNamedConfigParm = function() return true, "golem:test" end,
  GetSetMediaTrackInfo_String = function() return true, "" end,
  TrackFX_SetParamNormalized = function(_, _, p, value) written[p] = value end,
}
local capture = assert(load('local function jstr(s) return string.format("%q", s) end\n' ..
  section("local function vst_host_param_rows", "local function main()") ..
  "\nreturn vst_host_param_rows"))()
for _, names in ipairs({false, true}) do
  local rows = capture({}, 0, names)
  assert(#rows == 2)
  assert(rows[1]:find('"i":0', 1, true)) -- Le bypass du plugin est un vrai paramètre sonore.
  assert(rows[2]:find('"i":3', 1, true))
end
local apply = assert(load(section("local function apply_block_params", "local GAIN_NAMES") ..
  "\nreturn apply_block_params"))()
apply({}, 0, "vst-host", {p0=0.2, p1=0, p3=0.75}, {})
assert(written[0] == 0.2 and written[3] == 0.75 and written[1] == nil)
-- Même si le chunk change le bypass, le fresh build impose le bypass du bloc EN DERNIER.
local phase = section('        if blk.type == "vital" then\n          apply_zone',
                      "        -- ⚠ L'ARP EN DERNIER")
local build = assert(load("return function(blk, apply_block_params, set_block_enabled)\n" ..
  "local tr, fxs, engine, effects = {}, {0}, 0, {}\n" .. phase .. "\nend"))()
local enabled = true
build({type="vst-host", params={_vst_chunk="native"}, bypass=true},
  function() enabled = true end,
  function(_, blk) enabled = not blk.bypass end)
assert(enabled == false)
-- Un hôte sans paramètre spécial ne doit pas perdre un paramètre valide.
host_bypass = -1
written = {}
apply({}, 0, "vst-host", {p1=0.4}, {})
assert(written[1] == 0.4)
print("VST Host: capture, replay and fresh-build bypass OK (mock REAPER)")

-- Publications successives : simuler le refus de remplacement de os.rename sur Windows.
local files, label = {}, "First"
reaper.GetOS = function() return "Win64" end
reaper.GetResourcePath = function() return "root" end
reaper.GetAppVersion = function() return "7" end
reaper.EnumInstalledFX = function(i) if i == 0 then return true, label, label end; return false end
os.rename = function(tmp, dst)
  if files[dst] then return nil, "exists" end
  files[dst], files[tmp] = files[tmp], nil; return true
end
os.remove = function(path) files[path] = nil; return true end
io.open = function(path, mode)
  if mode ~= "w" then return nil end
  local text = ""
  return {write=function(_, part) text = text .. part end,
          close=function() files[path] = text end}
end
local runtime = assert(load(paths_source))()
dofile = function(path) assert(path:find("golem_paths.lua", 1, true)); return runtime end
assert(load(inventory_source))()
assert(files["root/presets/.fx-inventory.json"]:find("First", 1, true))
label = "Second"
assert(load(inventory_source))()
assert(files["root/presets/.fx-inventory.json"]:find("Second", 1, true))
local seen = assert(load("local runtime = ...\nlocal _FX_SEEN={chorus={ok=true,name='Native'}}\n" ..
  "local function read_file() return nil end\nlocal function jstr(s) return string.format('%q', s) end\n" ..
  section("local function write_fx_seen", "-- Le bypass") .. "\nreturn write_fx_seen"))(runtime)
seen("root")
files["root/presets/.rig-plugins.json"] = "old observation"
seen("root")
assert(files["root/presets/.rig-plugins.json"]:find("Native", 1, true))
assert(not files["root/presets/.rig-plugins.json.tmp"])
print("Plugin inventory and observations: Windows replacement OK (mock filesystem)")
