-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — capture (P1 skeleton)
  Sérialise l'état courant de la track Guitare (chaîne FX) vers un fichier, pour que le
  bridge le versionne en preset JSON (pipeline "Capturer", cf. docs/rig-control-layer.md).

  P1 : exporte le chunk FX brut. La conversion chunk -> preset JSON propre arrive en P2.
  Enregistrement : Actions → Load ReaScript → ce fichier.
]]--

-- Journal FICHIER — plus de console ReaScript.
-- Elle ouvrait une SECONDE fenêtre Reaper en permanence (« ReaScript console output »), alors
-- que tout est déjà lisible dans presets/*.log — c'est de là que le bridge lit les journaux.
-- Un utilisateur de GoleM ne lit jamais Reaper : il n'a pas à voir deux fenêtres s'ouvrir.
local _LOGF
local function log(s)
  if _LOGF == nil then                        -- résolu au 1er appel : ROOT n'existe pas encore ici
    local res = reaper.GetResourcePath()
    local f = io.open(res .. "/golem-root.txt", "r")
    local root = (f and f:read("*l")) or os.getenv("GOLEM_ROOT") or res
    if f then f:close() end
    _LOGF = root .. "/presets/.capture.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or (reaper.GetResourcePath())
end

local gtr = reaper.GetTrack(0, 0)   -- track 1 = Guitare
if not gtr then log("track Guitare introuvable") return end

local ok, chunk = reaper.GetTrackStateChunk(gtr, "", false)
if not ok then log("GetTrackStateChunk a échoué") return end

local root = repo_root()
local path = root .. "/presets/.capture.dump"   -- brut ; le bridge le transforme en JSON (P2)
local f = io.open(path, "w")
if not f then log("écriture impossible : " .. path) return end
f:write(chunk); f:close()
log("capture écrite : " .. path .. " (" .. #chunk .. " octets)")
