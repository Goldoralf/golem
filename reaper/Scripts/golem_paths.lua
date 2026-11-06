-- SPDX-License-Identifier: GPL-3.0-or-later
-- Chemins de l'IPC fugitif, identiques aux règles de bridge/config.py.
-- Le Linux du rack garde /dev/shm ; les postes de travail utilisent un dossier utilisateur.
local paths = {}
local cached_runtime_dir
local next_pointer_check = 0

function paths.runtime_dir()
  -- Les boucles persistantes peuvent démarrer avant le bridge. Relire le pointeur
  -- au plus une fois par seconde leur permet de rejoindre son chemin ensuite.
  local now = reaper.time_precise()
  if now >= next_pointer_check then
    next_pointer_check = now + 1
    local ptr = io.open(reaper.GetResourcePath() .. "/golem-runtime.txt", "r")
    if ptr then
      local dir = ptr:read("*l")
      ptr:close()
      if dir and dir ~= "" then cached_runtime_dir = (dir:gsub("\\", "/")) end
    end
  end
  if cached_runtime_dir then return cached_runtime_dir end
  local override = os.getenv("GOLEM_RUNTIME_DIR")
  if override and override ~= "" then
    local osname = reaper.GetOS()
    local drive = override:match("^%a:") and (override:sub(3, 3) == "/" or override:sub(3, 3) == "\\")
    local unc = override:sub(1, 2) == "\\\\" or override:sub(1, 2) == "//"
    local absolute = osname:find("Win", 1, true) and (drive or unc)
      or override:sub(1, 1) == "/"
    assert(absolute, "GOLEM_RUNTIME_DIR doit être un chemin absolu")
    cached_runtime_dir = (override:gsub("\\", "/"))
    return cached_runtime_dir
  end
  local platform = reaper.GetOS()
  if platform:find("Win", 1, true) then
    local base = os.getenv("LOCALAPPDATA") or ((os.getenv("USERPROFILE") or ".") .. "/AppData/Local")
    cached_runtime_dir = (base:gsub("\\", "/")) .. "/GoleM/runtime"
    return cached_runtime_dir
  end
  if platform:find("OSX", 1, true) or platform:find("macOS", 1, true) then
    cached_runtime_dir = (os.getenv("HOME") or ".") .. "/Library/Caches/GoleM/runtime"
    return cached_runtime_dir
  end
  cached_runtime_dir = "/dev/shm"
  return cached_runtime_dir
end

function paths.runtime_file(name)
  assert(name and name ~= "" and not name:find("/", 1, true)
         and not name:find("\\", 1, true) and name ~= "." and name ~= "..",
         "nom de fichier runtime invalide")
  return paths.runtime_dir() .. "/" .. name
end

function paths.ensure_runtime_dir()
  if reaper.RecursiveCreateDirectory then
    return reaper.RecursiveCreateDirectory(paths.runtime_dir(), 0)
  end
  return false
end

function paths.replace(tmp, dst)
  local ok, err = os.rename(tmp, dst)
  if ok or not reaper.GetOS():find("Win", 1, true) then return ok, err end
  -- Lua ne dispose pas de MoveFileExW : sur Windows, os.rename refuse un fichier
  -- cible existant. Les états publiés tolèrent une brève absence à la lecture.
  os.remove(dst)
  return os.rename(tmp, dst)
end

return paths
