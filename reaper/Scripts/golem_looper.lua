-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — looper (veilleur d'état + intake de commandes fallback)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_tuner). Elle :
   1) publie l'état du looper (JSFX golem_super8 sur la piste "Looper") lu en
      gmem "golem_looper", de façon atomique dans presets/.looper.json — que le bridge
      surveille (états des 4 paires, longueur/position de la loop maîtresse, heartbeat).
      Elle publie AUSSI l'adresse de commande (track/fx/param "GoleM Cmd") pour que le
      bridge pilote le looper en OSC FX_PARAM (chemin temps réel, ~1-2 ms).
   2) FALLBACK de commande : surveille presets/.looper-cmd.json ({"seq":N,"notes":[...]})
      et pousse les notes dans le ring gmem (gmem[100]=wptr, gmem[102..117]) que le JSFX
      draine — utile avant que le bridge connaisse l'adresse OSC, et pour le debug.

  Carte gmem (écrite par golem_super8) :
    [0]=len s · [1]=pos s · [2]=firstrec · [3]=heartbeat
    [8+p*4]=state (0=off/1=play/2=rec) · [9+p*4]=has · [10+p*4]=peak   (p = 0..3, une PAIRE stéréo
    chacune ; ce ne sont plus « GTR/VOX/SYN » : depuis docs/looper.md la source de chaque paire
    est choisie dans le preset, et deux paires peuvent partager la même lane)
  Ring de commandes (écrit ICI, lu par le JSFX) : [100]=wptr · [101]=rptr · [102..117]=notes.
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
    _LOGF = root .. "/presets/.looper.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-looper] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local OUT  = ROOT .. "/presets/.looper.json"
local CMD  = ROOT .. "/presets/.looper-cmd.json"
local LOOPER_TRACK     = "Looper"                -- créée par golem_rig quand preset.looper.enabled
local OLD_LOOPER_TRACK = "Sandbox #Looper"       -- ancien nom : migré (renommé) au vol si présent
local CMD_PARAM_NAME = "GoleM Cmd"            -- slider5 du fork — index résolu PAR NOM, jamais en dur

reaper.gmem_attach("golem_looper")

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr, i end
  end
  return nil, -1
end

-- migration douce : nouveau nom absent + ancien présent -> RENOMMER (jamais de doublon). Ici on ne
-- CRÉE pas la piste (c'est golem_rig), on suit juste l'ancien état d'un projet non encore migré.
local function migrate_name()
  if find_track(LOOPER_TRACK) then return end
  local old = find_track(OLD_LOOPER_TRACK)
  if old then
    reaper.GetSetMediaTrackInfo_String(old, "P_NAME", LOOPER_TRACK, true)
    log("piste migrée : « " .. OLD_LOOPER_TRACK .. " » -> « " .. LOOPER_TRACK .. " »")
  end
end

-- le FX golem_super8 dans la chaîne normale de la piste ; renvoie (fxIdx, cmdParamIdx) ou (-1,-1)
local function find_looper_fx(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    local low = (nm or ""):lower()
    if low:find("golem", 1, true) and low:find("super8", 1, true) then
      for p = 0, reaper.TrackFX_GetNumParams(tr, i) - 1 do
        local _, pn = reaper.TrackFX_GetParamName(tr, i, p, "")
        if pn == CMD_PARAM_NAME then return i, p end
      end
      return i, -1
    end
  end
  return -1, -1
end

-- écriture atomique (temp+rename)
local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

local function jnum(x) return string.format("%.4g", x or 0) end

local function build_json(t)
  if not t.present then return '{"present":false}' end
  local slots = {}
  for i = 1, 4 do
    local s = t.slots[i]
    slots[#slots+1] = string.format('{"st":%d,"has":%d,"peak":%s}', s.st, s.has, jnum(s.peak))
  end
  return string.format(
    '{"present":true,"track":%d,"fx":%d,"cmd_param":%d,"seq":%d,"len":%s,"pos":%s,"firstrec":%d,"countin":%d,"countin_slot":%d,"slots":[%s]}',
    t.track, t.fx, t.cmd_param, t.seq, jnum(t.len), jnum(t.pos), t.firstrec, t.countin, t.countin_slot,
    table.concat(slots, ","))
end

-- ── fallback de commande : .looper-cmd.json -> ring gmem ──
local last_cmd_seq = nil
-- ⚠ NE PAS REJOUER LA DERNIÈRE COMMANDE AU DÉMARRAGE (audit 2026-10-15 ; même piège que golem_backing le
-- 2026-10-08) : le bridge n'efface jamais .looper-cmd.json, et un `nil` ici réinjectait au premier tick les
-- notes de la dernière commande — un REC ou un PLAY de boucle sans un geste. Celle qui est là est déjà lue.
do
  local f0 = io.open(CMD, "r")
  if f0 then
    local body0 = f0:read("*a") or ""; f0:close()
    last_cmd_seq = body0:match('"seq"%s*:%s*(%-?%d+)')
  end
end
local function poll_cmd_file()
  local f = io.open(CMD, "r"); if not f then return end
  local body = f:read("*a"); f:close()
  if not body or #body == 0 then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if not seq or seq == last_cmd_seq then return end
  last_cmd_seq = seq
  -- le calage de la 1re boucle (docs/looper.md, addendum 2026-10-14), posé AVANT les notes : valeurs BRUTES des
  -- sliders « GoleM Tempo » / « GoleM Mode » (cmd+1, cmd+2) — le JSFX les lit à son @slider, avant la file
  local tempo = tonumber(body:match('"tempo"%s*:%s*([%d%.]+)') or "")
  local mode = tonumber(body:match('"mode"%s*:%s*(%d+)') or "")
  if tempo and mode then
    local tr = find_track(LOOPER_TRACK)
    if tr then
      local fx, cmdp = find_looper_fx(tr)
      if fx >= 0 and cmdp >= 0 then
        reaper.TrackFX_SetParam(tr, fx, cmdp + 1, tempo)
        reaper.TrackFX_SetParam(tr, fx, cmdp + 2, mode)
      end
    end
  end
  local arr = body:match('"notes"%s*:%s*%[([^%]]*)%]') or ""
  local w = reaper.gmem_read(100)
  for n in arr:gmatch("%-?%d+") do
    reaper.gmem_write(102 + (w % 16), tonumber(n))
    w = w + 1
  end
  reaper.gmem_write(100, w)                  -- bump wptr APRÈS avoir posé les notes
end

local last_fp = nil          -- fingerprint (états/has/présence) : publie sur changement
local last_pub = 0           -- horodatage de la dernière publication (cadence quand actif)
local wrote_off = false

-- GÉNÉRATION (patron de golem_click/golem_tuner) : ce script est dans la liste blanche du
-- hot-swap `{"action":"reload","script":"golem_looper"}`, et il n'avait PAS la garde. Mesuré le
-- 2026-08-09 : après un reload, DEUX boucles tournaient et se disputaient .looper.json — la
-- nouvelle publiait 4 slots, l'ancienne les réécrivait à 3, en alternance. Un reload censé livrer
-- un correctif livrait un état qui clignote entre deux versions du code.
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "looper_gen", GEN, false)

local function tick()
  -- ré-attache notre gmem en tête de boucle (contexte __startup partagé : le dernier gmem_attach du
  -- boot gagne, sinon une autre boucle nous vole l'espace — cf. golem_drums pour le détail complet).
  reaper.gmem_attach("golem_looper")
  poll_cmd_file()
  migrate_name()

  local tr, tidx = find_track(LOOPER_TRACK)
  if not tr then
    if not wrote_off then
      write_atomic(OUT, build_json({ present = false }))
      wrote_off = true; last_fp = nil
    end
    return
  end
  local fx, cmdp = find_looper_fx(tr)
  if fx < 0 then return end
  wrote_off = false

  local t = {
    present = true, track = tidx + 1, fx = fx, cmd_param = cmdp,
    seq = reaper.gmem_read(3), len = reaper.gmem_read(0), pos = reaper.gmem_read(1),
    firstrec = math.floor(reaper.gmem_read(2) + 0.5), slots = {},
    -- le décompte de la 1re boucle (golem_super8 [4] = temps restants, [5] = paire 1-4) — docs/looper.md
    countin = math.floor(reaper.gmem_read(4) + 0.5), countin_slot = math.floor(reaper.gmem_read(5) + 0.5),
  }
  local active = (t.len or 0) > 0 or t.firstrec ~= 0
  local fp = string.format("%d|%d|%d|%d|%d", t.track, t.fx, t.firstrec, t.countin, t.countin_slot)
  for p = 0, 3 do
    local st  = math.floor(reaper.gmem_read(8 + p*4) + 0.5)
    local has = math.floor(reaper.gmem_read(9 + p*4) + 0.5)
    t.slots[p+1] = { st = st, has = has, peak = reaper.gmem_read(10 + p*4) }
    if st ~= 0 then active = true end
    fp = fp .. string.format("|%d,%d", st, has)
  end

  local now = reaper.time_precise()
  -- au moins une fois par seconde même au repos : après un rappel, le bridge oublie l'adresse (l'index de la piste
  -- a pu changer) et n'en reprend qu'une publiée APRÈS — sans ça, un rig reconstruit à l'identique le laissait sur le
  -- canal fichier pour toujours
  if fp ~= last_fp or (active and now - last_pub >= 0.25) or now - last_pub >= 1.0 then
    last_fp = fp; last_pub = now
    write_atomic(OUT, build_json(t))
  end
end

-- pcall blindé (leçon perfrec, audit 2026-08-12) : une erreur d'un tick NE TUE JAMAIS la boucle
-- (un defer qui lève = chaîne morte silencieuse, et le looper n'avait pas ce filet).
local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "looper_gen") ~= GEN then return end   -- remplacée : cette boucle meurt
  local ok, err = pcall(tick)
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

log("démarré. piste=" .. LOOPER_TRACK .. " ; sortie=" .. OUT .. " ; cmd fallback=" .. CMD)
loop()
