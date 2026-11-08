-- SPDX-License-Identifier: GPL-3.0-or-later
-- LE PROJET OUVERT EST-IL CELUI DU GOLEM ? (2026-11-08)
--
-- Les boucles de service (golem_clock, golem_click) tournent dans TOUT REAPER, lancées par __startup.lua, et
-- créaient leur piste dans le projet ouvert quel qu'il soit : un projet vierge où l'on voulait seulement rendre une
-- basse recevait une piste « MIDI Clock » (sans envoi au master, armée en « aucun enregistrement ») — l'instrument
-- posé dessus restait muet et ne s'enregistrait pas. Une piste de service ne se crée QUE dans le projet du golem.
--
-- Le projet est celui du golem si :
--   1. il est enregistré sous <racine>/sets/ — les lanceurs n'ouvrent que là (provision/desktop.py, start.sh) ;
--   2. ou, SANS CHEMIN, golem y a monté un rig : golem_rig pose la marque `golem/owner` au rappel (M.mark). C'est le
--      tout premier démarrage (REAPER lancé avec -new) : le bridge y rappelle la bank 00 au boot
--      (recall.boot_recall) ; la marque s'enregistre avec le projet quand il devient golem-set.rpp.
-- Un projet sans chemin et sans rig, ou rangé ailleurs, n'est pas le nôtre : on n'y crée rien.
--
-- ⚠ PAS DE CACHE (revue du 2026-11-08) : REAPER peut garder le même ReaProject* quand un projet en remplace un
-- autre dans le même onglet (File ▸ New) ; un verdict mis en cache sur (pointeur, chemin) aurait dit « golem » au
-- projet vierge suivant pendant sa durée de vie — le bug d'origine. EnumProjects + GetProjExtState à ~30 Hz ne
-- coûtent rien.
local M = {}

local SEC, KEY = "golem", "owner"
local WINDOWS = reaper.GetOS():find("Win", 1, true) ~= nil

-- chemin comparable : barres obliques, sans barre finale ; insensible à la casse sous Windows
local function norm(p)
  p = tostring(p or ""):gsub("\\", "/"):gsub("/+$", "")
  if WINDOWS then p = p:lower() end
  return p
end

-- le projet COURANT : (pointeur, chemin du .rpp ou "" s'il n'a jamais été enregistré)
function M.current()
  if not reaper.EnumProjects then return 0, "" end
  local proj, path = reaper.EnumProjects(-1, "")
  return proj or 0, path or ""
end

-- vrai si `path` désigne un fichier rangé sous <root>/sets/ (sous-dossiers compris)
function M.in_sets(root, path)
  local p, sets = norm(path), norm(root) .. "/sets/"
  return p ~= "" and norm(root) ~= "" and p:sub(1, #sets) == sets
end

function M.is_golem(root)
  local proj, path = M.current()
  if M.in_sets(root, path) then return true end
  if path ~= "" then return false end                      -- rangé ailleurs : jamais le nôtre, marque ou pas
  local _, mark = reaper.GetProjExtState(proj, SEC, KEY)
  return mark == "1"
end

-- golem_rig, au rappel. Seul un projet SANS CHEMIN reçoit la marque : un projet de sets/ n'en a pas besoin, et un
-- projet rangé ailleurs (le rappel arrive pendant que le musicien est sur son onglet à lui) ne doit pas devenir le
-- nôtre pour toujours — le rig s'y monte quand même, comme avant, mais les pistes de service ne le suivent pas.
function M.mark()
  local proj, path = M.current()
  if path ~= "" then return false end
  local _, mark = reaper.GetProjExtState(proj, SEC, KEY)
  if mark ~= "1" then reaper.SetProjExtState(proj, SEC, KEY, "1") end
  return true
end

return M
