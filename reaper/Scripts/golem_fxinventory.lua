-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — inventaire des plugins (docs/block-status.md §3)
  Ce que REAPER a scanné sur cette machine, pas ce qu'un paquet dit avoir installé : un bloc dont le
  plugin manque n'avait qu'une ligne dans presets/.golem-rig.log, que personne ne lit. Écrit
  presets/.fx-inventory.json = {at, reaper, os, fx:[[nom, ident], …]}.
  LECTURE SEULE : EnumInstalledFX énumère la liste du navigateur de FX, aucun plugin n'est instancié
  (instancier pour tester figerait le moteur — GxEchoCat, CLAUDE.md).
  Appelé par golem_watch au démarrage et par golem_apply sur la commande {action:"fxinventory"}.
]]--

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local function jstr(s)
  s = tostring(s or ""):gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('[%c]', ' ')
  return '"' .. s .. '"'
end

local root = repo_root()
local runtime = dofile(root .. "/reaper/Scripts/golem_paths.lua")
local path = root .. "/presets/.fx-inventory.json"
if not reaper.EnumInstalledFX then                 -- Reaper < 6.37 : on ne sait pas, et on le DIT
  local f = io.open(path, "w")
  if f then f:write('{"error":"EnumInstalledFX unavailable","reaper":' .. jstr(reaper.GetAppVersion()) .. '}'); f:close() end
  return
end
local parts, i = {}, 0
while true do
  local ok, name, ident = reaper.EnumInstalledFX(i)
  if not ok then break end
  parts[#parts + 1] = "[" .. jstr(name) .. "," .. jstr(ident) .. "]"
  i = i + 1
end
local tmp = path .. ".tmp"
local f = io.open(tmp, "w")
if f then
  f:write('{"at":' .. os.time() .. ',"reaper":' .. jstr(reaper.GetAppVersion()) .. ',"os":' .. jstr(reaper.GetOS())
          .. ',"fx":[' .. table.concat(parts, ",") .. ']}')
  f:close()
  runtime.replace(tmp, path)
end
