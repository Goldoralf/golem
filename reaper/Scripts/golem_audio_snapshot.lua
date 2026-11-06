-- SPDX-License-Identifier: GPL-3.0-or-later
-- One-shot project snapshot before a desktop audio restart.
local f = io.open(reaper.GetResourcePath() .. "/golem-runtime.txt", "r")
if not f then return end
local runtime = f:read("*l")
f:close()
if not runtime or runtime == "" then return end
local active, project = reaper.EnumProjects(-1)
local saved = false
local request = io.open(runtime .. "/desktop-audio-save-path.txt", "r")
if request then
  local target = request:read("*l")
  request:close()
  if target and target ~= "" and (not project or project == "" or not reaper.file_exists(project)) then
    -- ⚠ Main_SaveProjectEx écrit une COPIE : le projet reste sans chemin (mesuré sur Windows le
    -- 2026-10-02, options 8 comme 0). PROJECT restait vide, le bridge concluait « auto-save
    -- failed » et refusait TOUT changement de carte ou de buffer (409) — en laissant un .rpp
    -- orphelin de plus à chaque essai. On rouvre la copie : le projet actif EST ce fichier,
    -- propre, et c'est lui que REAPER rouvrira après le redémarrage audio.
    reaper.Main_SaveProjectEx(active, target, 0)
    if reaper.file_exists(target) then reaper.Main_openProject("noprompt:" .. target) end
    _, project = reaper.EnumProjects(-1)
    saved = not not (project and project ~= "" and reaper.file_exists(target))
  end
end
local function quote(value)
  return '"' .. tostring(value or ""):gsub('\\', '\\\\'):gsub('"', '\\"')
    :gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t') .. '"'
end
local out = io.open(runtime .. "/desktop-audio-snapshot.json", "w")
if out then
  out:write('{"PROJECT":' .. quote(project) .. ',"TRACKS":' .. reaper.CountTracks(0)
    .. ',"AUTO_SAVED":' .. tostring(saved) .. '}')
  out:close()
end
