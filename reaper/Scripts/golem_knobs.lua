-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — knobs (runtime des potards AKAI, feature claviers)
  Boucle defer PERMANENTE (lancée par __startup, patron golem_clock/golem_tuner). Elle :
   1) attache la gmem partagée "golem_knobs" (alimentée par le JSFX knob-tap posé EN TÊTE du ROOT
      de la lane Keys par golem_rig) : gmem[cc]=valeur 0..127 ; gmem[128+cc]=seq (bump par CC reçu) ;
   2) lit presets/.knobmap.json (écrit par golem_rig au build : [{cc,track,stamp,pname}]) et, sur
      changement de seq d'un CC mappé, applique la valeur au param cible en
      TrackFX_SetParamNormalized(val/127) -> la plage native du param est respectée
      (Vital Macro 0..1, dx7-ctl « Patch » 0..31, etc.) ;
   3) cache la résolution (track par nom -> FX par estampille -> param par nom EXACT), invalidée
      quand .knobmap.json change (comparaison de contenu throttlée).

  Pourquoi gmem et pas le fichier : le CC doit piloter un param À LA MAIN, sans latence de round-trip
  fichier ; le JSFX écrit la gmem à l'échantillon près, ce script la poll dans sa boucle defer.

  ── Validation SANS potard physique (mode diag) ──
  ExtState "golem"/"knobsim" = "<cc>:<val>" -> injecte gmem[cc]=val + bump gmem[128+cc] (simule un
  tour de potard), puis efface l'ExtState. Depuis n'importe quel ReaScript / la console :
      reaper.SetExtState("golem","knobsim","1:64",false)   -- CC1 = 64  -> Vital « Macro 1 » ≈ 0.5
  puis un fxdump prouve que le param cible a bougé.

  ⚠ NON exécutable/validable hors-Reaper. À prouver AU RIG : réception CC par knob-tap, gmem
    partagée entre JSFX et ReaScript, noms de params (Vital vérifiés au fxdump ; Dexed à confirmer).
]]--

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
runtime.ensure_runtime_dir()
local MAP  = ROOT .. "/presets/.knobmap.json"
local LOGP = ROOT .. "/presets/.knobs.log"

local function log(s)
  local f = io.open(LOGP, "a"); if f then f:write(os.date("%H:%M:%S ") .. tostring(s) .. "\n"); f:close() end
end

local function read_file(p) local f = io.open(p, "r"); if not f then return nil end local s = f:read("*a"); f:close(); return s end
local function clamp01(x) x = tonumber(x) or 0; if x < 0 then return 0 elseif x > 1 then return 1 else return x end end

-- décodeur JSON pur-Lua (copié verbatim de golem_rig.lua / golem_apply.lua)
local function json_decode(str)
  local pos = 1
  local function skip() pos = str:find("[^ \t\r\n]", pos) or (#str + 1) end
  local parse_val
  local function parse_str()
    pos = pos + 1; local buf = {}
    while pos <= #str do
      local c = str:sub(pos, pos)
      if c == '"' then pos = pos + 1; return table.concat(buf)
      elseif c == "\\" then
        local n = str:sub(pos + 1, pos + 1)
        local map = { n = "\n", t = "\t", r = "\r", ['"'] = '"', ["\\"] = "\\", ["/"] = "/" }
        buf[#buf + 1] = map[n] or n; pos = pos + 2
      else buf[#buf + 1] = c; pos = pos + 1 end
    end
  end
  local function parse_arr()
    pos = pos + 1; local arr = {}; skip()
    if str:sub(pos, pos) == "]" then pos = pos + 1; return arr end
    while true do
      arr[#arr + 1] = parse_val(); skip()
      local c = str:sub(pos, pos); pos = pos + 1
      if c == "]" then break end; skip()
    end
    return arr
  end
  local function parse_obj()
    pos = pos + 1; local obj = {}; skip()
    if str:sub(pos, pos) == "}" then pos = pos + 1; return obj end
    while true do
      skip(); local k = parse_str(); skip(); pos = pos + 1 -- ':'
      skip(); obj[k] = parse_val(); skip()
      local c = str:sub(pos, pos); pos = pos + 1
      if c == "}" then break end
    end
    return obj
  end
  parse_val = function()
    skip(); local c = str:sub(pos, pos)
    if c == '"' then return parse_str()
    elseif c == "{" then return parse_obj()
    elseif c == "[" then return parse_arr()
    elseif c == "t" then pos = pos + 4; return true
    elseif c == "f" then pos = pos + 5; return false
    elseif c == "n" then pos = pos + 4; return nil
    else local s, e = str:find("^-?%d+%.?%d*[eE]?[-+]?%d*", pos); local n = tonumber(str:sub(s, e)); pos = e + 1; return n end
  end
  return parse_val()
end

reaper.gmem_attach("golem_knobs")

-- ── résolution de cible (mise en cache dans l'entrée elle-même) ──
local function track_name(tr)
  local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
  return nm
end
local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    if track_name(tr) == name then return tr end
  end
  return nil
end
local function find_param_exact(tr, fx, name)
  local target = (name or ""):lower()
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, pnm = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if pnm and pnm:lower() == target then return p end
  end
  return nil
end

-- (re)résout une entrée -> renseigne e._tr/_fx/_pi (ou e._pi=nil si introuvable). e._resolved marque
-- la tentative (évite de rescanner ~3000 params de Vital à chaque poll). Invalidé au reload de la map.
local function resolve(e)
  if e._resolved then return end
  e._resolved = true
  e._tr, e._fx, e._pi = nil, nil, nil
  local tr = find_track(e.track)
  if not tr then return end
  -- un bloc keys porte PLUSIEURS FX à la même estampille (note-zone + moteur) ; on scanne TOUS les FX
  -- estampillés e.stamp et on retient le PREMIER qui possède réellement le param (le note-zone n'a ni
  -- « Macro 1 » ni « Patch » -> on continue jusqu'au moteur). Ne PAS s'arrêter au 1er match d'estampille.
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm == e.stamp then
      local pi = find_param_exact(tr, i, e.pname)
      if pi then e._tr, e._fx, e._pi = tr, i, pi; return end
    end
  end
end

-- ── map (rechargée quand le contenu change) ──
local raw_seen   = nil     -- dernier contenu brut de .knobmap.json (compare de reload)
local by_cc      = {}      -- cc -> { entrées }
local last_seq   = {}      -- cc -> dernier seq vu (nil = pas encore amorcé)
local next_check = 0

local function load_map(force)
  if not force and reaper.time_precise() < next_check then return end
  next_check = reaper.time_precise() + 0.75
  local raw = read_file(MAP)
  if raw == raw_seen then return end                 -- inchangé (ou toujours absent)
  raw_seen = raw
  by_cc = {}
  if not raw then log("map absente (" .. MAP .. ") — aucun potard mappé"); return end
  local ok, arr = pcall(json_decode, raw)
  if not ok or type(arr) ~= "table" then log("⚠ map illisible — ignorée"); return end
  local n = 0
  for _, e in ipairs(arr) do
    if e.cc and e.track and e.stamp and e.pname then
      local cc = math.floor(e.cc)
      e._resolved = false                            -- (ré)résolution paresseuse au 1er changement
      by_cc[cc] = by_cc[cc] or {}
      by_cc[cc][#by_cc[cc] + 1] = e
      n = n + 1
    end
  end
  log("map (re)chargée : " .. n .. " CC -> " .. MAP)
end

-- ── mode diag : ExtState golem/knobsim = "cc:val" -> simule un tour de potard via gmem ──
local function pump_diag()
  local v = reaper.GetExtState("golem", "knobsim")
  if v == "" then return end
  reaper.SetExtState("golem", "knobsim", "", false)            -- consomme une fois
  -- forme "n:<num>:<vel>" : simule une NOTE-ON (cases learn 256+, docs/calibration.md) —
  -- permet de valider le stepper de calibration sans mains sur le clavier
  local nn, nv = v:match("^%s*n%s*[:,]%s*(%d+)%s*[:,]%s*(%d+)%s*$")
  if nn then
    reaper.gmem_write(256, tonumber(nn) % 128)
    reaper.gmem_write(257, tonumber(nv) % 128)
    reaper.gmem_write(258, reaper.gmem_read(258) + 1)
    log(string.format("diag knobsim : note %d vel %d (simulée, learn)", tonumber(nn), tonumber(nv)))
    return
  end
  local cc, val = v:match("^%s*(%-?%d+)%s*[:,]%s*(%-?%d+)%s*$")
  cc, val = tonumber(cc), tonumber(val)
  if not cc or not val then log("⚠ knobsim mal formé : '" .. v .. "' (attendu 'cc:val' ou 'n:num:vel')"); return end
  cc = math.floor(cc) % 256
  reaper.gmem_write(cc, math.max(0, math.min(127, math.floor(val))))
  reaper.gmem_write(128 + cc, reaper.gmem_read(128 + cc) + 1)  -- bump seq comme le ferait knob-tap
  reaper.gmem_write(262, cc)                                   -- + compteurs LEARN globaux (calibration)
  reaper.gmem_write(263, reaper.gmem_read(263) + 1)
  log(string.format("diag knobsim : gmem[%d]=%d, seq[%d]=%.0f (simule un potard)",
      cc, math.floor(val), cc, reaper.gmem_read(128 + cc)))
end

-- ── boucle ──
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "knobs_gen", GEN, false)          -- la dernière instance lancée gagne

-- ── écho LIVE vers l'écran (2026-07-23 : « voir bouger les potards depuis l'AKAI ») ──
-- Chaque CC appliqué est publié dans /dev/shm/golem-knobs-live.json (tmpfs) avec le nom du
-- param cible ; les entrées expirent après 2 s (présence dans le fichier ≈ potard en mouvement).
-- La feuille du bloc poll /api/knobs/live et fait suivre le dial (affichage seul, rien n'est écrit).
local function jstr(s) return '"' .. tostring(s or ""):gsub('\\', '\\\\'):gsub('"', '\\"') .. '"' end
local live_vals = {}          -- cc -> {v, t, pname, stamp}
local live_dirty = false
local last_live_write = 0

local function live_flush()
  local now = reaper.time_precise()
  if now - last_live_write < 0.1 then return end
  local rows, changed = {}, live_dirty
  for cc, lv in pairs(live_vals) do
    if now - lv.t > 2.0 then live_vals[cc] = nil; changed = true
    else rows[#rows + 1] = string.format('{"cc":%d,"v":%.4f,"age":%.2f,"pname":%s,"stamp":%s}',
      cc, lv.v, now - lv.t, jstr(lv.pname), jstr(lv.stamp)) end
  end
  if not changed then return end
  last_live_write = now
  live_dirty = false
  local f = io.open(runtime.runtime_file("golem-knobs-live.json"), "w")
  if f then f:write("[" .. table.concat(rows, ",") .. "]"); f:close() end
end

local function tick()
  -- ré-attache notre gmem en tête de tick (contexte __startup partagé : le dernier gmem_attach du boot
  -- gagne, sinon une autre boucle nous vole l'espace — cf. golem_drums pour le détail complet).
  reaper.gmem_attach("golem_knobs")
  load_map(false)
  pump_diag()
  for cc, list in pairs(by_cc) do
    local seq = reaper.gmem_read(128 + cc)
    if last_seq[cc] == nil then
      last_seq[cc] = seq                                       -- AMORÇAGE : on ne clobbe pas l'état de scène au boot
    elseif seq ~= last_seq[cc] then
      last_seq[cc] = seq
      local f = clamp01(reaper.gmem_read(cc) / 127)
      for _, e in ipairs(list) do
        resolve(e)
        if e._pi then reaper.TrackFX_SetParamNormalized(e._tr, e._fx, e._pi, f) end
        live_vals[cc] = { v = f, t = reaper.time_precise(), pname = e.pname, stamp = e.stamp }
        live_dirty = true
      end
    end
  end
  live_flush()
  learn_flush()
end

-- ── flux LEARN (docs/calibration.md) : notes + pitch bend + dernier CC, publiés depuis les
-- cases gmem 256+ (knob-tap étendu) vers /dev/shm/golem-learn.json — le stepper de calibration
-- poll /api/calibrate/live. Écrit SEULEMENT quand un seq bouge (fichier au repos = silence). ──
local lrn = { note = -1, cc = -1, pb = -1 }        -- derniers seq vus
function learn_flush()
  local sn, sc, sp = reaper.gmem_read(258), reaper.gmem_read(263), reaper.gmem_read(261)
  if sn == lrn.note and sc == lrn.cc and sp == lrn.pb then return end
  lrn.note, lrn.cc, lrn.pb = sn, sc, sp
  local LEARN = runtime.runtime_file("golem-learn.json")
  local f = io.open(LEARN .. ".tmp", "w")
  if not f then return end
  f:write(string.format(
    '{"note":{"num":%d,"vel":%d,"ch":%d,"seq":%d},"cc":{"num":%d,"val":%d,"seq":%d},"pb":{"val":%d,"seq":%d},"t":%.3f}',
    reaper.gmem_read(256), reaper.gmem_read(257), reaper.gmem_read(259), sn,      -- ch : 1-16 (0 = knob-tap d'avant)
    reaper.gmem_read(262), reaper.gmem_read(reaper.gmem_read(262)), sc,
    reaper.gmem_read(260), sp, reaper.time_precise()))
  f:close()
  local ok, err = runtime.replace(LEARN .. ".tmp", LEARN)
  if not ok then log("learn : publication impossible : " .. tostring(err)) end
end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "knobs_gen") ~= GEN then return end   -- remplacée : cette boucle meurt
  reaper.SetExtState("golem", "knobs_alive", string.format("%.3f", reaper.time_precise()), false)
  local ok, err = pcall(tick)                                  -- pcall BLINDÉ (leçon perfrec) : un tick ne tue pas la boucle
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

load_map(true)
log("démarré. gmem=golem_knobs ; map=" .. MAP .. " ; diag=ExtState golem/knobsim 'cc:val'")
loop()
