-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — golem_apply.lua : OUTILS DEV uniquement (fxprobe, namtest, loadtest, chunkdump,
  dumpfx, projreload), déclenchés par le bridge via presets/.command.json + golem_watch (dofile).

  ⚠ Le moteur legacy (recall LiveConfig, pistes GoleM:<id>, folders, stomp/param, io, whammy) a été
  SUPPRIMÉ (audit 2026-07-07, ~700 lignes) : le recall + le stomp vivent dans golem_rig.lua (modèle
  paths+splits, pistes Sandbox), la Whammy est pilotée par le bridge (bridge/midi_out.py).
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
    _LOGF = root .. "/presets/.apply.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem] " .. tostring(s) .. "\n"); f:close() end
end

----------------------------------------------------------------------- mini JSON
-- décodeur JSON pur-Lua (suffisant pour nos presets : objets/tableaux/strings/nombres/bool/null)
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

----------------------------------------------------------------------- fichiers
local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local runtime = dofile(repo_root() .. "/reaper/Scripts/golem_paths.lua")
runtime.ensure_runtime_dir()

local function read_file(p) local f = io.open(p, "r"); if not f then return nil end local s = f:read("*a"); f:close(); return s end

-- (conservé pour loadtest/namtest : injection d'un .RfxChain dans le chunk d'une piste)
local function load_fxchain(track, rfx_text)
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for line in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = line end

  -- trouve le bloc FXCHAIN existant (profondeur sur '<' / '>')
  local start_i, end_i, depth = nil, nil, 0
  for i, l in ipairs(lines) do
    local t = l:gsub("\r", ""):match("^%s*(.-)%s*$")
    if start_i == nil and t:match("^<FXCHAIN") then start_i = i; depth = 1
    elseif start_i ~= nil then
      if t:sub(1, 1) == "<" then depth = depth + 1
      elseif t == ">" then depth = depth - 1; if depth == 0 then end_i = i; break end end
    end
  end

  local fx_lines = { "<FXCHAIN" }
  for l in (rfx_text):gmatch("(.-)\r?\n") do fx_lines[#fx_lines + 1] = l:gsub("\r", "") end
  fx_lines[#fx_lines + 1] = ">"

  local out = {}
  if start_i and end_i then
    for i = 1, start_i - 1 do out[#out + 1] = lines[i] end
    for _, l in ipairs(fx_lines) do out[#out + 1] = l end
    for i = end_i + 1, #lines do out[#out + 1] = lines[i] end
  else
    -- pas de FXCHAIN existant : insérer avant le 1er sous-bloc <...>, sinon (track vide)
    -- avant le '>' de fermeture du <TRACK.
    local inserted = false
    local close_i = #lines
    for i = #lines, 1, -1 do
      if lines[i]:gsub("%s", ""):gsub("\r", "") == ">" then close_i = i; break end
    end
    for i, l in ipairs(lines) do
      local t = l:gsub("\r", ""):match("^%s*(.-)%s*$")
      if not inserted and ((t:sub(1, 1) == "<" and i > 1) or i == close_i) then
        for _, fl in ipairs(fx_lines) do out[#out + 1] = fl end; inserted = true
      end
      out[#out + 1] = l
    end
  end
  return reaper.SetTrackStateChunk(track, table.concat(out, "\n"), false)
end


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

local function jstr(s) return '"' .. tostring(s):gsub('\\', '\\\\'):gsub('"', '\\"') .. '"' end

-- Écrit presets/.fxdump.json : pour chaque piste GoleM (+ Guitare/Voix), chaque FX et TOUS ses params
-- (index, nom, valeur/min/max natifs, valeur formatée affichée). Sert à câbler `idx`/`pname` dans effects.json.
local function dump_fx(root)
  local rows = {}
  local DUMP_ALL = true                                   -- vrai s'il n'existe AUCUNE piste Sandbox
  for t = 0, reaper.CountTracks(0) - 1 do
    if track_name(reaper.GetTrack(0, t)):find("^Sandbox") then DUMP_ALL = false break end
  end
  -- pistes utilitaires renommées (2026-07-14) : elles doivent rester visibles au fxdump
  local UTIL = { ["Looper"]=true, ["Recording"]=true, ["MIDI Clock"]=true, ["Backing Track"]=true,
                 ["Drums"]=true, ["Sample"]=true }
  local function dumpable(nm)
    return nm:find("^Sandbox") or UTIL[nm] or nm:find("^Backing Track ") ~= nil
  end
  for t = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, t)
    local nm = track_name(tr)
    -- modèle actif = pistes Sandbox (golem_rig) ; fallback : tout dumper si aucune ne matche
    if dumpable(nm) or DUMP_ALL then
      local fxs = {}
      for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
        local _, fxname = reaper.TrackFX_GetFXName(tr, fx, "")
        local np = reaper.TrackFX_GetNumParams(tr, fx)
        local prm = {}
        for p = 0, np - 1 do
          local _, pnm = reaper.TrackFX_GetParamName(tr, fx, p, "")
          local val, mn, mx = reaper.TrackFX_GetParam(tr, fx, p)
          local _, disp = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
          prm[#prm + 1] = string.format('{"i":%d,"name":%s,"val":%.4f,"min":%.4f,"max":%.4f,"disp":%s}',
            p, jstr(pnm), val or 0, mn or 0, mx or 1, jstr(disp or ""))
        end
        -- `enabled` : le bypass RÉEL du FX. Sans lui le dump ne disait pas ce qu'une scène éteint —
        -- or c'est exactement ce qu'on cherche quand une bascule fait un blanc (2026-09-21).
        local _, tag = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
        fxs[#fxs + 1] = string.format('{"fx":%d,"plugin":%s,"tag":%s,"enabled":%s,"nparams":%d,"params":[%s]}',
          fx, jstr(fxname), jstr(tag or ""), tostring(reaper.TrackFX_GetEnabled(tr, fx)), np, table.concat(prm, ","))
      end
      rows[#rows + 1] = string.format('{"track":%s,"fx":[%s]}', jstr(nm), table.concat(fxs, ","))
    end
  end
  local path = root .. "/presets/.fxdump.json"
  local f = io.open(path, "w")
  if f then f:write("[" .. table.concat(rows, ",") .. "]"); f:close()
    log("dump FX écrit : .fxdump.json (" .. #rows .. " pistes)")
  else log("échec écriture .fxdump.json") end
end

-- PEAKS (dev, chasse au bug volume 2026-07-23) : relève le PEAK-HOLD dB de chaque piste (+ Master)
-- avec nom/volume/mute/sends -> presets/.peaks.json. cmd.clear = RAZ des peak-holds (protocole :
-- clear -> l'utilisateur joue -> lecture = le max atteint pendant le jeu, étage par étage).
local function peaks_dump(root, cmd)
  local clear = cmd.clear and true or false
  local rows = {}
  local function vol_db(v) if v <= 0 then return -150 end return 20 * math.log(v, 10) end
  local function one(tr, nm)
    local pl = reaper.Track_GetPeakHoldDB(tr, 0, clear)
    local pr = reaper.Track_GetPeakHoldDB(tr, 1, clear)
    -- Track_GetPeakHoldDB rend une valeur de type "dB/20" (x20 = dB) — mais s'est montrée PLATE
    -- sur 3 sessions (artefact ?) : on relève AUSSI le peak INSTANTANÉ linéaire (Track_GetPeakInfo,
    -- sans ambiguïté d'échelle) -> le bridge échantillonne en boucle et garde le max.
    local il = reaper.Track_GetPeakInfo(tr, 0)
    local ir = reaper.Track_GetPeakInfo(tr, 1)
    local vol = reaper.GetMediaTrackInfo_Value(tr, "D_VOL")
    local mute = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE")
    local nhw = reaper.GetTrackNumSends(tr, 1)
    local nsend = reaper.GetTrackNumSends(tr, 0)
    rows[#rows + 1] = string.format('{"track":%s,"peakL":%.1f,"peakR":%.1f,"instL":%.1f,"instR":%.1f,"vol_db":%.1f,"mute":%d,"hw_sends":%d,"sends":%d}',
      jstr(nm), pl * 20, pr * 20, vol_db(il), vol_db(ir), vol_db(vol), mute, nhw, nsend)
  end
  for t = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, t)
    one(tr, string.format("%02d %s", t + 1, track_name(tr)))
  end
  one(reaper.GetMasterTrack(0), "MASTER")
  local f = io.open(root .. "/presets/.peaks.json", "w")
  if f then f:write("[" .. table.concat(rows, ",") .. "]"); f:close()
    log("peaks écrits : .peaks.json (" .. #rows .. " pistes, clear=" .. tostring(clear) .. ")")
  else log("échec écriture .peaks.json") end
end

-- ── METERS temps réel (tiroirs P3) : {action:"meters", track:<n° 1-based>, fx:<idx>} arme une
-- boucle defer SINGLETON qui écrit /dev/shm/golem-meters.json (~30 Hz, tmpfs = zéro usure SSD) :
-- peak d'entrée piste + GainReduction_dB du FX (rapporté par ReaGate/ReaComp/ReaLimit via
-- TrackFX_GetNamedConfigParm). Désarmement AUTO 10 s après le dernier arm — le navigateur ré-arme
-- toutes les 4 s tant que la feuille est ouverte. Globals _G : le contexte Lua partagé de
-- golem_watch persiste entre les dofile, la boucle survit à la fin de la commande.
local function meters_arm(cmd)
  -- `hold` (s) : durée d'armement. Le défaut de 10 s oblige l'appelant à RÉ-ARMER sans cesse —
  -- et chaque ré-armement prend le SLOT UNIQUE `.command.json`, celui-là même qui porte les
  -- changements de scène. Une sonde à 15 Hz a ainsi fait perdre des scènes au mainteneur pendant qu'il
  -- jouait (2026-09-20) : l'instrument de mesure changeait ce qu'il mesurait. Un diagnostic long
  -- s'arme UNE fois et se tait. Plafond 600 s : une boucle oubliée doit finir par mourir.
  local hold = math.min(math.max(tonumber(cmd.hold) or 10, 1), 600)
  _G._GOLEM_METERS = { tnum = tonumber(cmd.track) or 0, fx = tonumber(cmd.fx) or 0,
                       until_t = reaper.time_precise() + hold }
  -- corps de tick dans un global REDÉFINI à chaque dofile : la boucle defer (immortelle une fois
  -- lancée) exécute toujours la DERNIÈRE version — un edit de ce fichier prend effet au prochain
  -- arm, sans restart Reaper (même esprit que le piège gmem re-attach : la closure d'origine, elle,
  -- ne meurt jamais).
  _G._GOLEM_METERS_BODY = function()
    local M = _G._GOLEM_METERS
    if not (M and reaper.time_precise() < M.until_t) then return end
    local tr = reaper.GetTrack(0, M.tnum - 1)
    if not tr then return end
    local pk = math.max(reaper.Track_GetPeakInfo(tr, 0), reaper.Track_GetPeakInfo(tr, 1))
    local pdb = pk > 0 and (20 * math.log(pk, 10)) or -150
    local ok, gr = reaper.TrackFX_GetNamedConfigParm(tr, M.fx, "GainReduction_dB")
    local f = io.open(runtime.runtime_file("golem-meters.json"), "w")
    if f then
      f:write(string.format('{"peak_db":%.1f,"gr_db":%.1f,"gr_ok":%s,"t":%.2f}',
        pdb, (ok and tonumber(gr)) or 0, ok and "true" or "false", reaper.time_precise()))
      f:close()
    end
  end
  if not _G._GOLEM_METERS_LOOP then
    _G._GOLEM_METERS_LOOP = true
    local function tick()
      local b = _G._GOLEM_METERS_BODY
      if b then pcall(b) end
      reaper.defer(tick)
    end
    tick()
  end
  -- sonde arm-time : un échantillon immédiat dans un fichier SÉPARÉ (la boucle écrase l'autre à
  -- 30 Hz) — sert à diagnostiquer le support GainReduction_dB sans dépendre de l'âge de la boucle.
  do
    local tr = reaper.GetTrack(0, (tonumber(cmd.track) or 0) - 1)
    if tr then
      local ok, gr = reaper.TrackFX_GetNamedConfigParm(tr, tonumber(cmd.fx) or 0, "GainReduction_dB")
      local _, fxn = reaper.TrackFX_GetFXName(tr, tonumber(cmd.fx) or 0, "")
      local f = io.open(runtime.runtime_file("golem-meters-probe.json"), "w")
      if f then f:write(string.format('{"gr_ok":%s,"gr_raw":%s,"fx":%s}',
        ok and "true" or "false", jstr(tostring(gr)), jstr(fxn))); f:close() end
    end
  end
  log("meters: boucle armée (piste " .. tostring(cmd.track) .. " fx " .. tostring(cmd.fx) .. ")")
end

-- ── SONDE DE TROUS (tools/check-scene-gap.py, 2026-09-21) ────────────────────────────────────
-- {action:"gapmeter", on:true, tone:"<piste>", db:-20, tracks:["<piste>", …], hold:s}
-- Pose un TON CONTINU en queue de la piste `tone` (APRÈS ses blocs : aucun index de bloc ne bouge,
-- la livemap et les stomps restent justes) et un golem_gapmeter en queue de chaque piste de
-- `tracks` (slot = rang). Une boucle defer recopie leur gmem dans /dev/shm/golem-gaps.json à chaque
-- tick, avec time_precise, pour que le bridge date les trous. Pourquoi un ton : la journée du
-- 2026-09-20 a montré qu'une mesure qui dépend d'un musicien qui joue ne se répète pas.
-- {action:"gapmeter", on:false} retire tout ce qui porte diag:tone / diag:gap. Un rebuild le fait
-- aussi, mais pas une REUSE de piste : `off` est la seule sortie sûre.
local GAP_NAMES  = { "JS:golem/golem_gapmeter.jsfx", "JS:golem/golem_gapmeter", "JS: golem/golem_gapmeter" }
local TONE_NAMES = { "JS:synthesis/tonegenerator", "JS: synthesis/tonegenerator", "JS:Tone Generator" }

local function gap_add(tr, names, tag, at_head)
  for _, n in ipairs(names) do
    -- at_head : -1000 = instancier EN TÊTE de chaîne (le ton traverse alors les plugins de la piste :
    -- banc LiveConfigs). ⚠ décale les index de FX de cette piste tant que la sonde est là.
    local fx = reaper.TrackFX_AddByName(tr, n, false, at_head and -1000 or -1)
    if fx and fx >= 0 then
      reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", tag)
      return fx
    end
  end
  return -1
end

local function gapmeter(cmd)
  for t = 0, reaper.CountTracks(0) - 1 do                -- jamais deux sondes empilées
    local tr = reaper.GetTrack(0, t)
    for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do
      local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
      if ok and (nm == "diag:gap" or nm == "diag:tone") then reaper.TrackFX_Delete(tr, i) end
    end
  end
  _G._GOLEM_GAPS = nil
  if not cmd.on then log("gapmeter : sondes retirées"); return end

  -- sans `tone` : écoute PASSIVE (le musicien joue, on ne pose que les détecteurs)
  if cmd.tone and cmd.tone ~= "" then
    local ttr = find_track(tostring(cmd.tone))
    if not ttr then log("gapmeter : piste du ton introuvable « " .. tostring(cmd.tone) .. " »"); return end
    local tfx = gap_add(ttr, TONE_NAMES, "diag:tone", cmd.tone_head == true)
    if tfx < 0 then log("gapmeter : Tone Generator introuvable"); return end
    -- valeurs BRUTES (TrackFX_SetParam) : Wet et Dry ont un minimum négatif, donc un taper
    -- bipolaire en normalisé (CLAUDE.md). Dry à -120 : la guitare branchée ne se mêle pas au ton.
    reaper.TrackFX_SetParam(ttr, tfx, 0, tonumber(cmd.db) or -20)
    reaper.TrackFX_SetParam(ttr, tfx, 1, -120)
    reaper.TrackFX_SetParam(ttr, tfx, 2, tonumber(cmd.hz) or 196)
  end

  local slots = {}
  for i, nm in ipairs(cmd.tracks or {}) do
    local tr = find_track(tostring(nm))
    local fx = tr and gap_add(tr, GAP_NAMES, "diag:gap") or -1
    if fx < 0 then
      log("gapmeter : ⚠ " .. tostring(nm) .. (tr and " — golem_gapmeter introuvable (Reaper relancé ?)" or " — piste introuvable"))
    else
      reaper.TrackFX_SetParam(tr, fx, 0, i - 1)             -- slot
      reaper.TrackFX_SetParam(tr, fx, 1, tonumber((cmd.thrs or {})[i]) or tonumber(cmd.thr) or -45)   -- un seuil par détecteur (banc LiveConfigs)
      reaper.TrackFX_SetParam(tr, fx, 2, tonumber(cmd.min_ms) or 10)
      slots[#slots + 1] = { name = tostring(nm), slot = i - 1 }
    end
  end
  _G._GOLEM_GAPS = { slots = slots, until_t = reaper.time_precise() + math.min(math.max(tonumber(cmd.hold) or 300, 5), 900) }
  _G._GOLEM_GAPS_BODY = function()
    local G = _G._GOLEM_GAPS
    if not (G and reaper.time_precise() < G.until_t) then return end
    -- ⚠ un seul gmem[] par contexte Lua (piège gmem re-attach) : on rend l'espace précédent
    -- après lecture, pour ne rien débrancher aux boucles qui n'ont attaché qu'une fois
    local prev = reaper.gmem_attach("golem_gapmeter")
    local rows = {}
    for _, s in ipairs(G.slots) do
      local b = s.slot * 64
      local n = math.floor(reaper.gmem_read(b + 2) or 0)
      local gaps = {}
      for k = math.max(0, n - 24), n - 1 do
        gaps[#gaps + 1] = string.format("[%d,%.1f,%.4f]", k, reaper.gmem_read(b + 8 + k % 24),
                                        reaper.gmem_read(b + 32 + k % 24))
      end
      rows[#rows + 1] = string.format('{"track":%s,"clk":%.4f,"env":%.1f,"n":%d,"max":%.1f,"run":%.1f,"gaps":[%s]}',
        jstr(s.name), reaper.gmem_read(b + 0), reaper.gmem_read(b + 1), n, reaper.gmem_read(b + 3),
        reaper.gmem_read(b + 4), table.concat(gaps, ","))
    end
    reaper.gmem_attach(type(prev) == "string" and prev or "")
    local gap_tmp = runtime.runtime_file("golem-gaps.json.tmp")
    local gap_dst = runtime.runtime_file("golem-gaps.json")
    local f = io.open(gap_tmp, "w")
    if f then
      f:write(string.format('{"t":%.4f,"slots":[%s]}', reaper.time_precise(), table.concat(rows, ",")))
      f:close()
      local ok, err = runtime.replace(gap_tmp, gap_dst)
      if not ok then log("gapmeter : publication impossible : " .. tostring(err)) end
    end
  end
  if not _G._GOLEM_GAPS_LOOP then
    _G._GOLEM_GAPS_LOOP = true
    local function tick()
      local b = _G._GOLEM_GAPS_BODY
      if b then pcall(b) end
      reaper.defer(tick)
    end
    tick()
  end
  log(string.format("gapmeter : %s, %d détecteur(s)", (cmd.tone and cmd.tone ~= "")
                    and string.format("ton %d dB sur « %s »", tonumber(cmd.db) or -20, tostring(cmd.tone))
                    or "écoute passive (sans ton)", #slots))
end

-- ── SONDE D'UN PLUGIN SEUL (tools/check-block-stall.py, 2026-09-21) ──────────────────────────
-- {action:"fxadd", track, plugin, tag} pose UN plugin en queue d'une piste VIVANTE du rig,
-- estampillé golem:<tag> et BYPASSÉ : la commande `stomp` {ids:[tag]} sait alors l'allumer et
-- l'éteindre, exactement comme un bloc. {action:"fxdel", tag} le retire. Sert à répondre à « ce
-- plugin fige-t-il le moteur audio en s'allumant ? » sans toucher à un preset.
local function fxadd_result(ok, name, seq)
  -- le banc lit CE fichier : un plugin qui ne se charge pas ne doit jamais passer pour « ok »
  local f = io.open(runtime.runtime_file("golem-fxadd.json"), "w")
  if f then f:write(string.format('{"ok":%s,"name":%s,"seq":%s}', tostring(ok), jstr(name or ""), jstr(seq or ""))); f:close() end
end

local function fxadd(cmd)
  local tr = find_track(tostring(cmd.track or ""))
  if not tr then log("fxadd : piste introuvable « " .. tostring(cmd.track) .. " »"); fxadd_result(false, "", cmd.seq) return end
  local fx = -1
  for _, nm in ipairs({ tostring(cmd.plugin or ""), table.unpack(cmd.alts or {}) }) do
    fx = reaper.TrackFX_AddByName(tr, nm, false, -1)
    if fx and fx >= 0 then break end
  end
  if not fx or fx < 0 then log("fxadd : plugin introuvable « " .. tostring(cmd.plugin) .. " »"); fxadd_result(false, "", cmd.seq) return end
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "golem:" .. tostring(cmd.tag))
  reaper.TrackFX_SetEnabled(tr, fx, false)
  local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
  fxadd_result(true, nm, cmd.seq)
  log("fxadd : " .. tostring(cmd.plugin) .. " @" .. fx .. " sur « " .. tostring(cmd.track) .. " » (golem:" .. tostring(cmd.tag) .. ")")
end

-- {action:"fxenable", track, fx, on} : allume/éteint un FX par sa POSITION. Les cœurs du rig (ampli
-- NAM, baffle) ne portent pas toujours l'estampille golem:<id> que la commande `stomp` cherche : un
-- banc qui les visait par id ne mesurait RIEN (piège trouvé le 2026-09-21, check-block-stall --rig).
local function fxenable(cmd)
  local tr = find_track(tostring(cmd.track or ""))
  local fx = tonumber(cmd.fx)
  if not tr or not fx or fx < 0 or fx >= reaper.TrackFX_GetCount(tr) then
    log("fxenable : cible introuvable " .. tostring(cmd.track) .. " FX#" .. tostring(cmd.fx)) return
  end
  reaper.TrackFX_SetEnabled(tr, fx, cmd.on == true)
end

local function fxdel(cmd)
  local want, n = "golem:" .. tostring(cmd.tag), 0
  for t = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, t)
    for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do
      local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
      if ok and nm == want then reaper.TrackFX_Delete(tr, i); n = n + 1 end
    end
  end
  log("fxdel : " .. n .. " FX retiré(s) (" .. want .. ")")
end

-- ── BANC D'ESSAI « SWS LiveConfigs » (tools/bench-liveconfigs.py, docs/audit-2026-09-21-latence-scenes.md §6)
-- LiveConfigs n'a AUCUNE API : une config vit dans le fichier projet (<S&M_LIVE_CONFIG …>). Pour en
-- monter une sans l'interface, on sauve le projet COURANT (pistes du rig comprises, qui n'existent
-- qu'en mémoire) dans un fichier jetable, le banc y injecte la config, et on rouvre ce fichier.
-- {op:"save", path, tracks:[noms]} -> écrit le projet + /dev/shm/golem-lcbench.json (GUID des pistes,
--                                     n° des actions SWS) ; `prep` met les branches à volume 1 (c'est
--                                     le MUTE de LiveConfigs qui commande, pas notre D_VOL)
-- {op:"open", path}                -> rouvre ce projet, sans invite
-- La sortie du banc est un redémarrage de Reaper par le rack : le Set d'origine n'est jamais touché.
local function lcbench(root, cmd)
  if cmd.op == "open" then
    log("lcbench : ouverture de " .. tostring(cmd.path))
    reaper.Main_openProject("noprompt:" .. tostring(cmd.path))
    return
  end
  if cmd.op ~= "save" then log("lcbench : op inconnue") return end
  local rows = {}
  for i, nm in ipairs(cmd.tracks or {}) do
    local tr = find_track(tostring(nm))
    if tr then
      if cmd.prep then
        reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1.0)
        reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", i == 1 and 0 or 1)
      end
      rows[#rows + 1] = string.format('{"name":%s,"guid":%s}', jstr(nm), jstr(reaper.GetTrackGUID(tr)))
    else
      rows[#rows + 1] = string.format('{"name":%s,"guid":null}', jstr(nm))
    end
  end
  local ids = {}
  for _, a in ipairs({ "_S&M_NEXT_LIVE_CFG1", "_S&M_PREV_LIVE_CFG1", "_S&M_LIVECFG_APPLY1" }) do
    ids[#ids + 1] = string.format('%s:%d', jstr(a), reaper.NamedCommandLookup(a))
  end
  reaper.Main_SaveProjectEx(0, tostring(cmd.path), 0)
  local f = io.open(runtime.runtime_file("golem-lcbench.json"), "w")
  if f then
    f:write(string.format('{"t":%.3f,"path":%s,"tracks":[%s],"actions":{%s}}', reaper.time_precise(),
                          jstr(cmd.path), table.concat(rows, ","), table.concat(ids, ",")))
    f:close()
  end
  log("lcbench : projet sauvé dans " .. tostring(cmd.path) .. " (" .. #rows .. " piste(s))")
end

-- SONDE (dev) : ajoute un plugin sur une piste scratch, essaie de charger un fichier via plusieurs
-- clés SetNamedConfigParm, relève quels params/clés reflètent le fichier -> presets/.fxprobe.log.
-- SONDE (dev) : une note MIDI dans un instrument de lane SANS clavier branché. La piste est trouvée par
-- l'estampille de son FX (golem:<id>) ; son entrée passe le temps de la note sur le clavier virtuel de REAPER
-- (StuffMIDIMessage mode 0, device 62), puis est REMISE telle quelle. Né le 2026-10-22 pour entendre le piano
-- sfizz VST3 sous Windows sans AKAI : un instrument qui s'instancie n'est pas un instrument qui sonne.
local VKB_INPUT = 4096 + 62 * 32                          -- MIDI, device 62 = clavier virtuel, tous canaux
local function midinote(root, cmd)
  local stamp = "golem:" .. tostring(cmd.block or "")
  local tr
  for i = 0, reaper.CountTracks(0) - 1 do
    local t = reaper.GetTrack(0, i)
    for fx = 0, reaper.TrackFX_GetCount(t) - 1 do
      local _, nm = reaper.TrackFX_GetNamedConfigParm(t, fx, "renamed_name")
      if nm == stamp then tr = t break end
    end
    if tr then break end
  end
  if not tr then log("midinote : aucune piste ne porte " .. stamp) return end
  local saved = reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT")
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", VKB_INPUT)
  local notes = cmd.notes or { 60 }
  local vel, ms = tonumber(cmd.vel) or 100, tonumber(cmd.ms) or 1500
  for _, n in ipairs(notes) do reaper.StuffMIDIMessage(0, 0x90, n, vel) end
  log(string.format("midinote : %s -> %d note(s) vel %d pendant %d ms (entrée %d -> VKB, remise après)",
      stamp, #notes, vel, ms, saved))
  local t0 = reaper.time_precise()
  local function off()
    if reaper.time_precise() - t0 < ms / 1000 then reaper.defer(off) return end
    for _, n in ipairs(notes) do reaper.StuffMIDIMessage(0, 0x80, n, 0) end
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", saved)
    log("midinote : note off, entrée remise à " .. tostring(saved))
  end
  reaper.defer(off)
end

local function fxprobe(root, cmd)
  local out = {}
  local function w(s) out[#out + 1] = s end
  local tr = find_track("GoleM:_probe")
  if not tr then
    local idx = reaper.CountTracks(0); reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx); reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "GoleM:_probe", true)
  end
  for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do reaper.TrackFX_Delete(tr, i) end
  local fx = reaper.TrackFX_AddByName(tr, cmd.plugin or "", false, -1)
  if not fx or fx < 0 then w("plugin introuvable: " .. tostring(cmd.plugin))
  else
    local _, real = reaper.TrackFX_GetFXName(tr, fx, "")
    w("plugin: " .. tostring(real) .. " @" .. fx .. "  fichier: " .. tostring(cmd.file))
    for _, k in ipairs(cmd.keys or {}) do
      local ok = reaper.TrackFX_SetNamedConfigParm(tr, fx, k, cmd.file or "")
      w("  set['" .. k .. "'] -> " .. tostring(ok))
    end
    local base = (cmd.file or ""):match("[^/]+$") or ""
    for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
      local _, pnm = reaper.TrackFX_GetParamName(tr, fx, p, "")
      local _, disp = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
      if disp and disp ~= "" and (disp:find(".nam", 1, true) or disp:find(".wav", 1, true)
          or disp:find(".json", 1, true) or disp:find(".aidax", 1, true) or (base ~= "" and disp:find(base, 1, true))) then
        w("  ★param " .. p .. " '" .. tostring(pnm) .. "' = '" .. disp .. "'")
      end
    end
    for _, k in ipairs(cmd.keys or {}) do
      local ok, val = reaper.TrackFX_GetNamedConfigParm(tr, fx, k)
      if ok and val and val ~= "" then w("  get['" .. k .. "'] = '" .. tostring(val) .. "'") end
    end
  end
  local f = io.open(root .. "/presets/.fxprobe.log", "w")
  if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
  log("fxprobe écrit : .fxprobe.log (" .. #out .. " lignes)")
end

-- sauve + rouvre le projet : force les plugins à RECHARGER leurs fichiers (NAM/IR) au project-open
-- (seul mécanisme fiable — cf. docs/rig-model.md). __startup tourne au démarrage Reaper, pas au load projet
-- -> pas de double veilleur.
local function proj_reload()
  reaper.Main_SaveProject(0, false)                    -- persiste les pistes GoleM (avec les chemins fichiers)
  local _, path = reaper.EnumProjects(-1, "")
  if path and path ~= "" then
    log("proj_reload: réouverture " .. path)
    reaper.Main_openProject(path)
  else
    log("proj_reload: aucun chemin projet — sauve le Set d'abord")
  end
end

-- TEST (dev) : charge un .nam dans un plugin via injection de la ligne S <uri> "path" dans le chunk
-- + SetOffline (force relecture), IN-SESSION (aucun reload). Résultat -> presets/.fxprobe.log.
local function namtest(root, cmd)
  local out = {}
  local function w(s) out[#out + 1] = tostring(s) end
  local plugin = cmd.plugin or "Neural Amp Modeler"
  local file, uri = cmd.file or "", cmd.uri or ""
  local tr = find_track("GoleM:_probe")
  if not tr then
    local idx = reaper.CountTracks(0); reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx); reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "GoleM:_probe", true)
  end
  for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do reaper.TrackFX_Delete(tr, i) end
  local fx = reaper.TrackFX_AddByName(tr, plugin, false, -1)
  if not fx or fx < 0 then w("plugin introuvable: " .. plugin)
  else
    local _, real = reaper.TrackFX_GetFXName(tr, fx, "")
    w("plugin: " .. real .. " @" .. fx)
    local _, chunk = reaper.GetTrackStateChunk(tr, "", false)
    w("--- chunk frais (S / STATE / balises) ---")
    for l in (chunk .. "\n"):gmatch("(.-)\n") do
      local t = l:gsub("\r", "")
      if t:match("^%s*S ") or t:find("STATE", 1, true) or t:match("^%s*<%a") then w("  " .. t) end
    end
    if uri ~= "" and file ~= "" then
      local lines = {}
      for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
      -- format RÉEL relevé au rig : P <uri> <chemin NON quoté> 3
      local sline = 'P ' .. uri .. ' ' .. file .. ' 3'
      local done = false
      for i, l in ipairs(lines) do
        if l:find(uri, 1, true) and l:match("^%s*P ") then
          lines[i] = (l:match("^(%s*)") or "") .. sline; done = true; break
        end
      end
      if not done then
        for i, l in ipairs(lines) do
          if l:find("STATE", 1, true) and l:match("^%s*<") then
            table.insert(lines, i + 1, '        ' .. sline); done = true; break
          end
        end
      end
      w("injection ligne S: " .. tostring(done))
      reaper.SetTrackStateChunk(tr, table.concat(lines, "\n"), false)
      reaper.TrackFX_SetOffline(tr, fx, true); reaper.TrackFX_SetOffline(tr, fx, false)
    end
    w("--- params après (disp non vide) ---")
    for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
      local _, pnm = reaper.TrackFX_GetParamName(tr, fx, p, "")
      local _, disp = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
      if disp and disp ~= "" then w("  p" .. p .. " '" .. pnm .. "' = '" .. disp .. "'") end
    end
    local _, chunk2 = reaper.GetTrackStateChunk(tr, "", false)
    w("--- chunk après (lignes S) ---")
    for l in (chunk2 .. "\n"):gmatch("(.-)\n") do local t = l:gsub("\r", ""); if t:match("^%s*S ") then w("  " .. t) end end
  end
  local f = io.open(root .. "/presets/.fxprobe.log", "w"); if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
  log("namtest écrit .fxprobe.log")
end

-- TEST (dev) : load_fxchain d'un template NAM (modèle baké) sur une piste MONITORÉE + routée Master
-- -> l'utilisateur joue et dit si le modèle est chargé (charge in-session via load_fxchain ?).
local function loadtest(root, cmd)
  local model = cmd.file or (root .. "/assets/models/simple.nam")
  local tpl_path = cmd.template or (root .. "/bridge/templates/nam-head.RfxChain")
  local tr = find_track("GoleM:_probe")
  if not tr then
    local idx = reaper.CountTracks(0); reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx); reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "GoleM:_probe", true)
  end
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", 0)   -- In1 mono
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)    -- sonde : jamais de fichier si une prise perf-rec démarre
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 1)   -- vers Master pour l'écoute
  local ir = cmd.ir or (root .. "/assets/irs/simple.wav")
  local tpl = read_file(tpl_path)
  if tpl then
    tpl = tpl:gsub("%%MODEL%%", (model:gsub("%%", "%%%%")))
    tpl = tpl:gsub("%%IR%%", (ir:gsub("%%", "%%%%")))
    load_fxchain(tr, tpl)
    log("loadtest: chargé sur _probe (In1->[" .. tpl_path:match("[^/]+$") .. "]->Master). JOUE.")
  else log("loadtest: template introuvable " .. tpl_path) end
end

-- DIAG (dev) : liste les paramètres RÉELS d'un FX -> presets/.fxparams.log. Le chunk d'une piste
-- ne montre que la sérialisation d'un JSFX (une ligne de nombres, sans les noms) : quand une
-- écriture de paramètre n'a pas l'air d'atterrir, c'est l'index et le nom vus PAR REAPER qu'il
-- faut lire, pas la ligne sérialisée. Lecture seule.
local function fxparams(root, cmd)
  local out = {}
  local function w(s) out[#out + 1] = s end
  local tr = find_track(cmd.track or "")
  if not tr then
    w("piste introuvable : " .. tostring(cmd.track))
  else
    local needle = (cmd.fx or ""):lower()
    for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
      local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
      if needle == "" or (nm or ""):lower():find(needle, 1, true) then
        -- latence DÉCLARÉE par le plugin (PDC, échantillons) : le seul fait honnête sur ce qu'il coûte
        -- au retour du chanteur — un suréchantillonnage « Quality » se lit ici (bloc Grit, 2026-09-14)
        local _, pdc = reaper.TrackFX_GetNamedConfigParm(tr, fx, "pdc")
        -- ACTIF ou bypassé : un FX bypassé rend les mêmes valeurs de paramètres qu'un FX actif,
        -- et cette ligne était donc muette sur la seule chose qu'on voulait savoir en cherchant
        -- pourquoi une scène coupait le son (2026-09-20).
        local on = reaper.TrackFX_GetEnabled(tr, fx)
        w(string.format("FX %d : %s  (pdc=%s samples, %s)", fx, tostring(nm), tostring(pdc),
          on and "actif" or "BYPASSÉ"))
        for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
          local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
          local v, mn, mx = reaper.TrackFX_GetParam(tr, fx, p)
          local nv = reaper.TrackFX_GetParamNormalized(tr, fx, p)
          local _, disp = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
          w(string.format("  [%d] %-24s val=%-12s norm=%-10s min=%s max=%s  « %s »",
            p, tostring(pn), tostring(v), tostring(nv), tostring(mn), tostring(mx), tostring(disp)))
        end
      end
    end
    if #out == 0 then w("aucun FX ne contient : " .. tostring(cmd.fx)) end
  end
  local f = io.open(root .. "/presets/.fxparams.log", "w")
  if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
  log("fxparams écrit : .fxparams.log (" .. #out .. " lignes)")
end

-- DIAG (dev) : écrit UN paramètre d'un FX, puis le relit -> presets/.fxparams.log. Sert à trancher
-- « l'API refuse cette écriture » contre « l'appelant ne l'a jamais faite » — deux pannes qui se
-- ressemblent parfaitement quand on ne regarde que la valeur finale.
local function fxset(root, cmd)
  local out = {}
  local tr = find_track(cmd.track or "")
  local p = tonumber(cmd.param)
  if not tr then out[1] = "piste introuvable : " .. tostring(cmd.track)
  elseif not p then out[1] = "param manquant (index)"
  else
    local needle = (cmd.fx or ""):lower()
    for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
      local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
      if needle == "" or (nm or ""):lower():find(needle, 1, true) then
        local before = reaper.TrackFX_GetParam(tr, fx, p)
        local ok, how
        if cmd.value ~= nil then                          -- écriture BRUTE (TrackFX_SetParam)
          how = "val " .. tostring(cmd.value)
          ok = reaper.TrackFX_SetParam(tr, fx, p, tonumber(cmd.value) or 0)
        else                                              -- écriture NORMALISÉE
          how = "norm " .. tostring(cmd.norm)
          ok = reaper.TrackFX_SetParamNormalized(tr, fx, p, tonumber(cmd.norm) or 0)
        end
        local after, mn, mx = reaper.TrackFX_GetParam(tr, fx, p)
        out[#out + 1] = string.format("FX %d [%d] : %s -> %s -> %s (retour=%s, min=%s max=%s)",
          fx, p, tostring(before), how, tostring(after), tostring(ok),
          tostring(mn), tostring(mx))
        break
      end
    end
    if #out == 0 then out[1] = "aucun FX ne contient : " .. tostring(cmd.fx) end
  end
  local f = io.open(root .. "/presets/.fxparams.log", "w")
  if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
  log("fxset : " .. tostring(out[1]))
end

-- DIAG (dev) : preset d'un FX. cmd.preset = nom -> TrackFX_SetPreset ; rend toujours le preset
-- courant, l'index/le nombre de presets connus de Reaper et quelques params -> presets/.fxparams.log.
-- Né du bloc Vital sous Windows (Vitalium LV2 : l'état ne passe ni par vst_chunk ni par le chunk).
local function fxpreset(root, cmd)
  local out = {}
  local tr = find_track(cmd.track or "")
  if not tr then out[1] = "piste introuvable : " .. tostring(cmd.track)
  else
    local needle = (cmd.fx or ""):lower()
    for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
      local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
      if needle == "" or (nm or ""):lower():find(needle, 1, true) then
        if cmd.preset then
          out[#out + 1] = "SetPreset '" .. cmd.preset .. "' -> " .. tostring(reaper.TrackFX_SetPreset(tr, fx, cmd.preset))
        end
        local _, cur = reaper.TrackFX_GetPreset(tr, fx, "")
        local idx, n = reaper.TrackFX_GetPresetIndex(tr, fx)
        out[#out + 1] = string.format("FX %d %s : preset='%s' index=%s/%s", fx, nm, tostring(cur), tostring(idx), tostring(n))
        for _, p in ipairs(cmd.params or {}) do
          local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
          out[#out + 1] = string.format("  [%d] %s = %.4f", p, pn, reaper.TrackFX_GetParamNormalized(tr, fx, p))
        end
        break
      end
    end
    if #out == 0 then out[1] = "aucun FX ne contient : " .. tostring(cmd.fx) end
  end
  local f = io.open(root .. "/presets/.fxparams.log", "w")
  if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
  log("fxpreset : " .. tostring(out[#out > 0 and 1 or 1]))
end

-- TEST (dev) : écrit le chunk complet d'une piste -> presets/.chunk.log (pour relever un format d'état).
local function chunkdump(root, cmd)
  local body
  if cmd.find then                                     -- cherche la piste dont le chunk contient `find`
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      local _, chunk = reaper.GetTrackStateChunk(tr, "", false)
      if chunk:find(cmd.find, 1, true) then body = chunk; break end
    end
    if not body then body = "aucune piste ne contient: " .. tostring(cmd.find) end
  else
    local tr = find_track(cmd.track or "GoleM:_probe")
    if tr then local _, chunk = reaper.GetTrackStateChunk(tr, "", false); body = chunk
    else body = "piste introuvable: " .. tostring(cmd.track) end
  end
  local f = io.open(root .. "/presets/.chunk.log", "w"); if f then f:write(body); f:close() end
  log("chunkdump écrit .chunk.log")
end

-- TEST (dev) : lane Keys/Vitalium. Piste GoleM:_keys + FX Vitalium (LV2) + entrée MIDI AKAI.
-- Sans cmd.vital : DUMP du bloc FX -> .chunk.log (relever le format d'état urn:juce:stateBinary).
-- Avec cmd.vital : injecte le JSON .vital (base64) dans l'état du chunk + drop FXID (Reaper
-- ré-instancie et recharge) ; loggue des params avant/après -> preuve du chargement headless.
local B64C = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function b64encode(s)
  local out, n = {}, #s
  for i = 1, n - 2, 3 do
    local a, b, c = s:byte(i, i + 2)
    local v = a * 65536 + b * 256 + c
    out[#out + 1] = B64C:sub(math.floor(v / 262144) % 64 + 1, math.floor(v / 262144) % 64 + 1)
      .. B64C:sub(math.floor(v / 4096) % 64 + 1, math.floor(v / 4096) % 64 + 1)
      .. B64C:sub(math.floor(v / 64) % 64 + 1, math.floor(v / 64) % 64 + 1)
      .. B64C:sub(v % 64 + 1, v % 64 + 1)
  end
  local r = n % 3
  if r == 1 then
    local a = s:byte(n)
    local v = a * 65536
    out[#out + 1] = B64C:sub(math.floor(v / 262144) % 64 + 1, math.floor(v / 262144) % 64 + 1)
      .. B64C:sub(math.floor(v / 4096) % 64 + 1, math.floor(v / 4096) % 64 + 1) .. "=="
  elseif r == 2 then
    local a, b = s:byte(n - 1, n)
    local v = a * 65536 + b * 256
    out[#out + 1] = B64C:sub(math.floor(v / 262144) % 64 + 1, math.floor(v / 262144) % 64 + 1)
      .. B64C:sub(math.floor(v / 4096) % 64 + 1, math.floor(v / 4096) % 64 + 1)
      .. B64C:sub(math.floor(v / 64) % 64 + 1, math.floor(v / 64) % 64 + 1) .. "="
  end
  return table.concat(out)
end

local function vitaltest(root, cmd)
  local out = {}
  local function o(s) out[#out + 1] = tostring(s); log(s) end
  -- 1. piste de test
  local tr = find_track("GoleM:_keys")
  if not tr then
    local idx = reaper.CountTracks(0); reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx); reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "GoleM:_keys", true)
    o("piste GoleM:_keys créée")
  end
  -- 2. entrée MIDI : cherche l'AKAI dans les MIDI inputs de Reaper (doit être activé dans les prefs)
  local mdev = -1
  for i = 0, 127 do
    local ok, name = reaper.GetMIDIInputName(i, "")
    if ok and name and name ~= "" then
      o("midi-in " .. i .. " : " .. name)
      local l = name:lower()
      -- Reaper (ALSA raw) nomme les devices "hw:<id carte>" (AKAI MPK = hw:II). cmd.midiname
      -- (posé par le bridge depuis /proc/asound) prime ; sinon heuristique : hw: hors carte son.
      if cmd.midiname and name == cmd.midiname then mdev = i
      elseif not cmd.midiname and (l:find("mpk") or l:find("akai")
             or (l:find("^hw:") and not l:find("v276"))) then mdev = i end
    end
  end
  if mdev >= 0 then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", 4096 + mdev * 32)   -- device MIDI, tous canaux
    o("recinput <- MIDI dev " .. mdev)
  else
    o("!! AKAI absent des MIDI inputs Reaper (activer le device dans les prefs / reaper.ini)")
  end
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)    -- sonde : jamais de fichier si une prise perf-rec démarre
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 1)
  -- 3. FX Vital(ium) — cmd.plugin surcharge le nom AddByName (ex. "VST3i:Vital" = officiel) ;
  --    sinon cmd.fmt="vst3" teste la voie VST3 Vitalium (vst_chunk à chaud) ; défaut = LV2.
  local names = cmd.plugin and { cmd.plugin }
             or (cmd.fmt == "vst3" and { "VST3i:Vitalium", "VST3:Vitalium", "VSTi:Vitalium", "VST:Vitalium" }
                                    or { "LV2i:Vitalium", "LV2:Vitalium", "Vitalium" })
  local vst_voie = cmd.plugin ~= nil or cmd.fmt == "vst3"
  local fx = reaper.TrackFX_GetByName(tr, vst_voie and "VST3" or "LV2", false)
  if fx < 0 then
    for _, nm in ipairs(names) do
      fx = reaper.TrackFX_AddByName(tr, nm, false, 1)
      o("AddByName '" .. nm .. "' -> " .. fx)
      if fx >= 0 then break end
    end
  else o("Vital(ium) déjà présent (fx " .. fx .. ")") end
  -- voie VST : lit/écrit l'état via vst_chunk (marche À CHAUD, pas de ré-instanciation)
  if vst_voie and fx >= 0 then
    local okg, cur = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
    o("GetNamedConfigParm vst_chunk -> " .. tostring(okg) .. " (" .. tostring(cur and #cur or 0) .. " chars)")
    if okg and cur then
      local f3 = io.open(root .. "/presets/.vstchunk.b64", "w")
      if f3 then f3:write(cur); f3:close(); o("vst_chunk écrit dans .vstchunk.b64") end
    end
    if cmd.setchunk then
      local nb = read_file(cmd.setchunk)
      if nb then
        local oks = reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", nb)
        o("SetNamedConfigParm vst_chunk (" .. #nb .. " chars) -> " .. tostring(oks))
      else o("!! setchunk illisible: " .. tostring(cmd.setchunk)) end
    end
    -- témoins (mêmes noms de params que LV2)
    local np3 = reaper.TrackFX_GetNumParams(tr, fx)
    local W3 = { chorusswitch = true, reverbswitch = true, filter1switch = true, volume = true }
    for pi = 0, math.min(np3 - 1, 2000) do
      local _, pn = reaper.TrackFX_GetParamName(tr, fx, pi, "")
      local key = tostring(pn):lower():gsub("[%s_%-]", "")
      if W3[key] then o(("vst3 [%d] %s = %.4f"):format(pi, pn, reaper.TrackFX_GetParamNormalized(tr, fx, pi))) end
    end
    local f4 = io.open(root .. "/presets/.fxprobe.log", "w")
    if f4 then f4:write(table.concat(out, "\n") .. "\n"); f4:close() end
    log("vitaltest (vst3) écrit .fxprobe.log")
    return
  end
  if fx < 0 then
    o("!! Vitalium introuvable — LV2 pas scanné ?")
  else
    -- params témoins AVANT (pour prouver le chargement d'un preset)
    local np = reaper.TrackFX_GetNumParams(tr, fx)
    o("params: " .. np)
    local WANT = { chorusswitch = true, reverbswitch = true, filter1switch = true, volume = true }
    local witness = {}
    for pi = 0, math.min(np - 1, 2000) do
      local _, pn = reaper.TrackFX_GetParamName(tr, fx, pi, "")
      if pi < 10 then o("  param[" .. pi .. "] = " .. tostring(pn)) end
      local key = tostring(pn):lower():gsub("[%s_%-]", "")
      if WANT[key] then witness[#witness + 1] = pi end
    end
    for _, pi in ipairs(witness) do
      local _, pn = reaper.TrackFX_GetParamName(tr, fx, pi, "")
      o(("avant  [%d] %s = %.4f"):format(pi, pn, reaper.TrackFX_GetParamNormalized(tr, fx, pi)))
    end
    -- 4. bloc FX dans le chunk
    local okc, chunk = reaper.GetTrackStateChunk(tr, "", false)
    if okc then
      local lines = {}
      for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
      local s_i, e_i, depth = nil, nil, 0
      for i2 = 1, #lines do
        local t = lines[i2]:match("^%s*(.-)%s*$")
        if not s_i and t:match("^<LV2") then s_i = i2; depth = 1
        elseif s_i and not e_i then
          if t:sub(1, 1) == "<" then depth = depth + 1
          elseif t == ">" then depth = depth - 1; if depth == 0 then e_i = i2 end end
        end
      end
      o("bloc LV2: lignes " .. tostring(s_i) .. "-" .. tostring(e_i) .. " (chunk " .. #lines .. " lignes, " .. #chunk .. " octets)")
      -- dump du bloc (tronque les lignes énormes pour rester lisible)
      local f = io.open(root .. "/presets/.chunk.log", "w")
      if f and s_i and e_i then
        for k = s_i, e_i do
          local l = lines[k]
          f:write(#l > 300 and (l:sub(1, 300) .. " …(" .. #l .. " chars)") or l, "\n")
        end
        f:close()
        o("bloc écrit dans .chunk.log")
      elseif f then f:write(chunk); f:close() end
      -- 5. injection d'un .vital — format RELEVÉ au chunkdump (instance fraîche) :
      --      <LV2 "LV2i: Vitalium (DISTRHO) (2 out)" urn:distrho:vitalium ""
      --        MIDI lv2_events_in 0 0
      --        P <symbole> <valeur> …          (≈770 ports = TOUS les params du synthé)
      --        <STATE
      --          <X urn:juce:stateBinary http://lv2plug.in/ns/ext/atom#Chunk 3
      --            <base64 multiligne du JSON .vital + NUL>
      --          > > >
      --    On REMPLACE le base64 du sous-bloc <X…stateBinary ET on SUPPRIME les lignes P
      --    (elles re-forceraient les ports de l'ancien état par-dessus le preset chargé),
      --    puis on droppe le FXID -> Reaper ré-instancie et recharge l'état du chunk.
      if cmd.vital and s_i and e_i then
        local jtxt = read_file(cmd.vital)
        if not jtxt then o("!! .vital illisible: " .. tostring(cmd.vital))
        else
          local blob = b64encode(jtxt .. "\0")
          local x_i, xend_i = nil, nil
          for k = s_i, e_i do
            if lines[k]:match("^%s*<X%s+%S*stateBinary") then
              x_i = k
              for j = k + 1, e_i do
                if lines[j]:match("^%s*>%s*$") then xend_i = j; break end
              end
              break
            end
          end
          if not (x_i and xend_i) then o("!! sous-bloc <X …stateBinary introuvable — voir .chunk.log")
          else
            local nout = {}
            for k = 1, #lines do
              local drop = false
              if k > x_i and k < xend_i then drop = true                       -- ancien base64
              elseif k >= s_i and k <= e_i and lines[k]:match("^%s*P%s") then  -- ports de l'ancien état
                drop = true
              end
              if not drop then nout[#nout + 1] = lines[k] end
              if k == x_i then                                                 -- nouveau base64 (lignes de 256)
                for p = 1, #blob, 256 do nout[#nout + 1] = blob:sub(p, p + 255) end
              end
            end
            -- drop la ligne FXID qui suit le bloc -> ré-instanciation (l'état du chunk fait foi)
            local lv_k, fxid_done = nil, false
            for k = 1, #nout do
              if nout[k]:match("^%s*<LV2") then
                lv_k = k
                local depth2 = 1
                for j = k + 1, #nout do
                  local tt = nout[j]:match("^%s*(.-)%s*$")
                  if tt:sub(1, 1) == "<" then depth2 = depth2 + 1
                  elseif tt == ">" then depth2 = depth2 - 1
                    if depth2 == 0 then
                      -- FXID n'est pas forcément adjacent (FLOATPOS/DOCKEDPOS s'intercalent)
                      for m = j + 1, math.min(j + 5, #nout) do
                        local nt = nout[m]:match("^%s*(.-)%s*$")
                        if nt:match("^FXID") then
                          table.remove(nout, m); fxid_done = true; o("FXID droppé @" .. m .. " (ré-instanciation)")
                          break
                        elseif nt:match("^WAK") or nt:sub(1, 1) == "<" or nt == ">" then break end
                      end
                      break
                    end
                  end
                end
                break
              end
            end
            if not lv_k then o("!! <LV2 introuvable pour le drop FXID") end
            if not fxid_done then o("!! FXID non droppé — l'instance vivante gardera l'ancien état") end
            -- PROUVÉ NÉCESSAIRE (spike) : l'état LV2 du chunk n'est chargé qu'à l'INSTANCIATION.
            -- Poser le chunk sur une instance vivante ne recharge rien (même FXID droppé, même
            -- projreload). cmd.stage="two" : on écrit le chunk préparé + on supprime le FX ;
            -- la commande vitalset (cycle suivant, autre bloc d'undo) posera le chunk.
            if cmd.stage == "two" then
              local f2 = io.open(root .. "/presets/.keyschunk.tmp", "w")
              if f2 then f2:write(table.concat(nout, "\n")); f2:close() end
              reaper.TrackFX_Delete(tr, fx)
              o("stage two : FX supprimé, chunk préparé dans .keyschunk.tmp (envoyer vitalset)")
            else
              reaper.TrackFX_Delete(tr, fx)
              o("FX supprimé (instanciation depuis le chunk à venir)")
              local okset = reaper.SetTrackStateChunk(tr, table.concat(nout, "\n"), false)
              o("état injecté (" .. #blob .. " chars b64, P drop) · SetTrackStateChunk -> " .. tostring(okset))
            end
            for _, pi in ipairs(witness) do
              local _, pn = reaper.TrackFX_GetParamName(tr, fx, pi, "")
              o(("après  [%d] %s = %.4f"):format(pi, pn, reaper.TrackFX_GetParamNormalized(tr, fx, pi)))
            end
          end
        end
      end
    else o("!! GetTrackStateChunk KO") end
  end
  local f = io.open(root .. "/presets/.fxprobe.log", "w")
  if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
  log("vitaltest écrit .fxprobe.log")
end

-- RÉCUPÉRATION (dev/rig) : referme et rouvre TOUS les devices audio+MIDI.
-- Cas d'usage prouvé au rig (2026-07-25) : la carte USB est débranchée/ré-énumérée pendant que
-- Reaper tourne. Reaper garde des descripteurs /dev/snd/pcmC*D* marqués « (deleted) », son thread
-- audio ne traite plus RIEN (VU-mètres figés, JSFX free-running gelés, transport bloqué, aucun
-- enregistrement possible) — et Audio_IsRunning() continue pourtant de répondre « oui ».
-- Audio_Quit+Audio_Init relit la config (reaper.ini alsa_indev/alsa_outdev, ici « hw:V276 ») et
-- ré-ouvre le device : ça évite un redémarrage complet de Reaper (perte des pistes de service).
-- ⚠ NON VALIDÉ HORS-RIG : à n'appeler QUE transport arrêté et hors rebuild (la fermeture des
-- devices pendant un chargement de plugin async est un chemin à segfault connu — cf. SETTLE).
local function audio_reset()
  if (reaper.GetPlayState() & 5) ~= 0 then
    log("audio_reset REFUSÉ : le transport tourne (arrête la lecture/l'enregistrement d'abord)")
    return
  end
  reaper.Audio_Quit()
  reaper.Audio_Init()
  log("audio_reset : Audio_Quit + Audio_Init (running=" .. tostring(reaper.Audio_IsRunning()) .. ")")
end

-- DIAG (dev) : photographie de l'état d'ENREGISTREMENT -> presets/.recdiag.json
-- Read-only : ne mute rien. Répond à « pourquoi aucun fichier ? » (transport en record ?
-- quelles pistes armées ? quel record mode ? où écrit Reaper ?).
local function recdiag(root, cmd)
  local ps = reaper.GetPlayState()
  local _, rp = reaper.GetSetProjectInfo_String(0, "RECORD_PATH", "", false)
  local rows = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    local function v(k) return reaper.GetMediaTrackInfo_Value(tr, k) end
    rows[#rows + 1] = string.format(
      '{"i":%d,"name":%s,"recarm":%d,"recmode":%d,"recinput":%d,"recmon":%d,"mainsend":%d,'
      .. '"nchan":%d,"mute":%d,"hw":%d,"sends":%d,"recv":%d,"items":%d,"fdepth":%d}',
      i, jstr(nm), v("I_RECARM"), v("I_RECMODE"), v("I_RECINPUT"), v("I_RECMON"),
      v("B_MAINSEND"), v("I_NCHAN"), v("B_MUTE"),
      reaper.GetTrackNumSends(tr, 1), reaper.GetTrackNumSends(tr, 0),
      reaper.GetTrackNumSends(tr, -1), reaper.CountTrackMediaItems(tr), v("I_FOLDERDEPTH"))
  end
  local body = string.format(
    '{"tag":%s,"ts":%s,"playstate":%d,"playpos":%.3f,"playpos2":%.3f,"cursor":%.3f,"recpath":%s,'
    .. '"metro_toggle":%d,"rec_toggle":%d,"audio_running":%s,"playrate":%.4f,"projlen":%.3f,'
    .. '"srate":%.0f,"latency_out":%.4f,"tempo":%.2f,"tracks":[%s]}',
    jstr(cmd.tag or ""), jstr(os.date("%H:%M:%S")), ps, reaper.GetPlayPosition(),
    reaper.GetPlayPosition2(0), reaper.GetCursorPosition(), jstr(rp),
    reaper.GetToggleCommandState(40364), reaper.GetToggleCommandState(1013),
    tostring((reaper.Audio_IsRunning() or 0) ~= 0), reaper.Master_GetPlayRate(0),
    reaper.GetProjectLength(0), reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false),
    select(1, reaper.GetOutputLatency()), reaper.Master_GetTempo(),
    table.concat(rows, ","))
  local f = io.open(root .. "/presets/.recdiag" .. tostring(cmd.tag or "") .. ".json", "w")
  if f then f:write(body); f:close() end
  log("recdiag écrit (playstate=" .. ps .. ")")
end

local function main()
  local root = repo_root()
  local cmd_raw = read_file(root .. "/presets/.command.json")
  if not cmd_raw then log("aucune commande") return end
  local cmd = json_decode(cmd_raw)
  if not cmd then log("commande illisible") return end
  if not reaper.GetTrack(0, 0) then log("ouvre le Set (cf. p1-wiring)") return end

  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)
  if cmd.action == "extstate" then
    -- outil dev : poser un ExtState (ex. golem/knobsim pour simuler un potard)
    reaper.SetExtState(cmd.section or "golem", cmd.key or "", tostring(cmd.value or ""), false)
    log("extstate " .. tostring(cmd.key) .. " = " .. tostring(cmd.value))
  elseif cmd.action == "click" then
    -- bootstrap click dans le Reaper DÉJÀ lancé (même patron que perf_rec plus bas) : un
    -- golem_watch chargé en mémoire AVANT cette version ne connaît pas l'action « click » et la
    -- route ici. On relaie vers la boucle golem_click et on (re)lance la boucle si son heartbeat
    -- n'est plus frais. En production golem_watch route « click » directement (ProjExtState).
    -- ⚠ L'ANCIENNE branche « metronome » (bascule de l'action 40364) est SUPPRIMÉE : le métronome
    -- NATIF ne tique QUE transport en marche (le bitfield projmetroen n'a aucun bit « while
    -- stopped ») -> sur le rig, monitoré transport à l'arrêt, elle n'a jamais rien émis et son
    -- fichier d'état mentait. Le click vit dans golem_click.lua + golem_click.jsfx (free-running).
    reaper.SetProjExtState(0, "golem", "click_cmd", cmd_raw)
    local _hb = tonumber(reaper.GetExtState("golem", "click_alive")) or 0
    if reaper.time_precise() - _hb > 2.0 then
      reaper.SetExtState("golem", "click_kick", "1", false)      -- une commande fraîche attend d'être exécutée
      local _click = root .. "/reaper/Scripts/golem_click.lua"
      if reaper.file_exists(_click) then dofile(_click) end
    end
  elseif cmd.action == "peaks" then
    peaks_dump(root, cmd)                                -- outil : peak-hold par piste (bug volume)
  elseif cmd.action == "meters" then
    meters_arm(cmd)                                      -- feuille dynamique : IN + GR temps réel
  elseif cmd.action == "fxinventory" then
    -- ce que Reaper a scanné (docs/block-status.md §3) : lecture seule, presets/.fx-inventory.json
    local _inv = root .. "/reaper/Scripts/golem_fxinventory.lua"
    if reaper.file_exists(_inv) then dofile(_inv) end
  elseif cmd.action == "fxadd" then
    fxadd(cmd)
  elseif cmd.action == "fxenable" then
    fxenable(cmd)
  elseif cmd.action == "fxdel" then
    fxdel(cmd)
  elseif cmd.action == "lcbench" then
    lcbench(root, cmd)                                   -- banc d'essai SWS LiveConfigs (dev)
  elseif cmd.action == "gapmeter" then
    gapmeter(cmd)                                        -- diag : trous entre scènes, ton + détecteurs
  elseif cmd.action == "knobs_reload" then
    -- hot-swap de la boucle golem_knobs : le dofile pose un nouveau GEN, l'ancienne meurt au tick
    local kf = root .. "/reaper/Scripts/golem_knobs.lua"
    if reaper.file_exists(kf) then dofile(kf); log("golem_knobs rechargé (hot-swap gen)") end
  elseif cmd.action == "reload" then
    -- hot-swap GÉNÉRIQUE d'une boucle defer (même patron que knobs_reload) : chaque boucle GoleM
    -- pose sa génération dans l'ExtState, donc un simple dofile remplace l'ancienne au tick suivant.
    -- Permet de livrer un correctif de boucle SANS relancer Reaper (les pistes de service, les
    -- loops du looper et l'état du projet survivent). Liste blanche = pas de dofile arbitraire.
    local ALLOWED = { golem_perfrec = true, golem_click = true, golem_backing = true,
                      golem_looper = true, golem_tuner = true, golem_sample = true,
                      golem_drums = true, golem_clock = true, golem_knobs = true,
                      golem_preview = true, golem_watch = true, golem_midi = true,
                      golem_chordseq = true, golem_drumlearn = true }
    local nm = tostring(cmd.script or "")
    if not ALLOWED[nm] then
      log("reload refusé (hors liste blanche) : " .. nm)
    else
      local sf = root .. "/reaper/Scripts/" .. nm .. ".lua"
      if reaper.file_exists(sf) then dofile(sf); log(nm .. " rechargé (hot-swap gen)")
      else log("reload : fichier introuvable " .. sf) end
    end
  elseif cmd.action == "midilist" then
    -- SONDE MIDI (doctrine gear-registry) : ce que Reaper TIENT vraiment.
    --   1. devices in/out : index Reaper + nom + présent ? (⚠ un device ABSENT garde son index :
    --      la liste est persistée dans reaper-midihw-alsa.ini [mididevcache], donc l'index n'est
    --      PAS l'ordre `amidi -l` — c'est l'ordre de PREMIÈRE RENCONTRE.)
    --   2. masques live (SNM_GetIntConfigVar) : midiins/midiouts... = qui est ouvert en exclusif.
    --   3. I_MIDIHWOUT / I_RECINPUT de chaque piste : qui pourrait tenir un device hors masque.
    -- -> /dev/shm/golem-midilist.json (diag AKAI muet 2026-07-23, Volt volée 2026-07-26)
    local rows = {}
    for i = 0, 127 do
      local ok, nm = reaper.GetMIDIInputName(i, "")
      if nm and nm ~= "" then rows[#rows + 1] = string.format('{"dir":"in","i":%d,"name":%s,"present":%s}', i, jstr(nm), tostring(ok and true or false)) end
      local oko, nmo = reaper.GetMIDIOutputName(i, "")
      if nmo and nmo ~= "" then rows[#rows + 1] = string.format('{"dir":"out","i":%d,"name":%s,"present":%s}', i, jstr(nmo), tostring(oko and true or false)) end
    end
    -- ⚠ mesuré 2026-07-26 : get_config_var_string ne sert QUE les vars STRING — il renvoie faux
    -- ("?" ci-dessous) sur les bitmasks midiins/midiouts. Sans SWS (SNM_GetIntConfigVar), les
    -- masques MIDI ne sont NI lisibles NI modifiables à chaud : la vérité terrain est
    -- /proc/asound/card*/midi0 (cf. golem_midi.lua) et la réparation passe par reaper.ini + relance.
    local cfg = {}
    if reaper.get_config_var_string then
      for _, k in ipairs({ "midiins", "midiins_h", "midiins_cs", "midiins_nowarn",
                           "midiouts", "midiouts_h", "midiouts_nowarn" }) do
        local okc, sv = reaper.get_config_var_string(k)
        cfg[#cfg + 1] = string.format('%s:%s', jstr(k), jstr(okc and tostring(sv) or "?"))
      end
    end
    local vars = {}
    if reaper.SNM_GetIntConfigVar then
      for _, k in ipairs({ "midiins", "midiins_h", "midiins_cs", "midiins_nowarn", "midiins_all",
                           "midiouts", "midiouts_h", "midiouts_nowarn", "midiouts_clock" }) do
        vars[#vars + 1] = string.format('%s:%d', jstr(k), math.floor(reaper.SNM_GetIntConfigVar(k, -1)))
      end
    end
    local trs = {}
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      local _, tnm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
      local hw = reaper.GetMediaTrackInfo_Value(tr, "I_MIDIHWOUT")
      local ri = reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT")
      if hw ~= -1 or ri >= 4096 then
        trs[#trs + 1] = string.format('{"n":%d,"name":%s,"hwout":%d,"recin":%d}', i + 1, jstr(tnm), math.floor(hw), math.floor(ri))
      end
    end
    local body = string.format('{"ts":%s,"sws":%s,"has_getcfg":%s,"devices":[%s],"cfg":{%s},"vars":{%s},"tracks":[%s]}',
      jstr(os.date("%H:%M:%S")), tostring(reaper.SNM_GetIntConfigVar ~= nil),
      tostring(reaper.get_config_var_string ~= nil),
      table.concat(rows, ","), table.concat(cfg, ","), table.concat(vars, ","), table.concat(trs, ","))
    local f = io.open(runtime.runtime_file("golem-midilist.json"), "w")
    if f then f:write(body); f:close() end
    log("midilist : " .. #rows .. " device(s) -> " .. runtime.runtime_file("golem-midilist.json"))
  elseif cmd.action == "dumpfx" then
    dump_fx(root)                                        -- outil : relève les params réels des plugins
  elseif cmd.action == "fxprobe" then
    fxprobe(root, cmd)                                   -- sonde (dev) : test de chargement fichier
  elseif cmd.action == "midinote" then
    midinote(root, cmd)                                  -- sonde (dev) : une note dans un instrument de lane, sans clavier
  elseif cmd.action == "projreload" then
    proj_reload()                                        -- save + reopen -> recharge les fichiers NAM/IR
  elseif cmd.action == "namtest" then
    namtest(root, cmd)                                   -- test (dev) : chargement .nam in-session
  elseif cmd.action == "audiodev" then
    -- DIAG : ce que Reaper dit de SON périphérique. Audio_IsRunning() a rendu 1 alors que la
    -- carte était ré-énumérée et que plus rien ne sortait (2026-08-08) : on cherche un témoin
    -- qui, lui, ne mente pas.
    local out = { "Audio_IsRunning = " .. tostring(reaper.Audio_IsRunning()) }
    for _, k in ipairs({ "MODE", "IDENT_IN", "IDENT_OUT", "SRATE", "BSIZE", "NCH_IN", "NCH_OUT",
                         "POSITION", "STATE" }) do
      local ok2, v = reaper.GetAudioDeviceInfo(k, "")
      out[#out + 1] = string.format("%-10s ok=%-5s %s", k, tostring(ok2), tostring(v))
    end
    local f = io.open(root .. "/presets/.audiodev.log", "w")
    if f then f:write(table.concat(out, "\n") .. "\n"); f:close() end
    log("audiodev écrit : .audiodev.log")
  elseif cmd.action == "audio_reset" then
    audio_reset()                                        -- récupération : carte son ré-énumérée
  elseif cmd.action == "recdiag" then
    recdiag(root, cmd)                                   -- diag (dev) : photo de l'état d'enregistrement
  elseif cmd.action == "sample_preview" then
    -- l'ÉCOUTE d'un son depuis l'écran (tiroir Pads, 2026-10-14) : le fichier joue À TRAVERS la piste de la lane
    -- (ses FX, sa sortie vers les enceintes) — pas le navigateur, qui sortirait ailleurs (la carte est tenue par
    -- REAPER). Une écoute coupe la précédente. SWS (CF_Preview) ; sans lui : rien, et le journal le dit.
    if not reaper.CF_CreatePreview then
      log("sample_preview : SWS absent — pas d'écoute")
    else
      reaper.CF_Preview_StopAll()
      local f = tostring(cmd.file or "")
      if f ~= "" then
        local abs = f:sub(1, 1) == "/" or f:match("^%a:[/\\]") or f:sub(1, 2) == "\\\\"   -- C:\…, \\serveur
        local path = abs and f or (root .. "/" .. f)
        local src = reaper.PCM_Source_CreateFromFile(path)
        if src then
          local pv = reaper.CF_CreatePreview(src)
          local tr = cmd.track_idx and reaper.GetTrack(0, math.floor(cmd.track_idx) - 1) or nil
          if tr then reaper.CF_Preview_SetOutputTrack(pv, 0, tr) end
          reaper.CF_Preview_SetValue(pv, "D_VOLUME", 10 ^ ((tonumber(cmd.db) or 0) / 20))
          reaper.CF_Preview_Play(pv)
          log("sample_preview : " .. f:match("[^/]*$") .. (tr and (" -> piste " .. math.floor(cmd.track_idx)) or " -> sortie par défaut"))
        else
          log("sample_preview : fichier illisible " .. path)
        end
      end
    end
  elseif cmd.action == "fxparams" then
    fxparams(root, cmd)                                  -- diag (dev) : paramètres réels d'un FX
  elseif cmd.action == "fxset" then
    fxset(root, cmd)                                     -- diag (dev) : écrire un paramètre, puis le relire
  elseif cmd.action == "trackdel" then
    -- nettoyage (dev) : retire une piste de SONDE (« GoleM:_… » seulement — jamais une lane)
    local tr = find_track(cmd.track or "")
    if tr and (cmd.track or ""):match("^GoleM:_") then reaper.DeleteTrack(tr); log("trackdel : " .. cmd.track)
    else log("trackdel refusé : " .. tostring(cmd.track)) end
  elseif cmd.action == "fxsetall" then
    -- étalonnage (dev) : TOUS les params d'un FX à la même normalisée, piste à volume NUL (une
    -- valeur extrême ne doit pas sortir). Sert à lire les bornes réelles d'un plugin dans son état.
    local tr = find_track(cmd.track or "")
    if tr and (cmd.track or ""):match("^GoleM:_") then
      reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 0)
      local needle = (cmd.fx or ""):lower()
      for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
        local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
        if (nm or ""):lower():find(needle, 1, true) then
          local n = reaper.TrackFX_GetNumParams(tr, fx)
          for p = 0, n - 1 do
            local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
            local l = (pn or ""):lower()
            -- freewheel / bypass d'HÔTE (le dernier param) à 1 : le plugin cesse de lire ses ports,
            -- l'étalonnage ne verrait rien -> toujours 0
            local off = l == "freewheel" or (l == "bypass" and p == n - 1)
            reaper.TrackFX_SetParamNormalized(tr, fx, p, off and 0 or (tonumber(cmd.norm) or 0))
          end
          log("fxsetall : " .. n .. " params -> " .. tostring(cmd.norm))
          break
        end
      end
    else log("fxsetall refusé : " .. tostring(cmd.track)) end
  elseif cmd.action == "fxpreset" then
    fxpreset(root, cmd)                                  -- diag (dev) : poser / lire le preset d'un FX
  elseif cmd.action == "chunkdump" then
    chunkdump(root, cmd)                                 -- test (dev) : dump du chunk d'une piste
  elseif cmd.action == "loadtest" then
    loadtest(root, cmd)                                 -- test (dev) : NAM via load_fxchain, écoute
  elseif cmd.action == "vitaltest" then
    vitaltest(root, cmd)                                -- test (dev) : lane Keys Vitalium + état .vital
  elseif cmd.action == "vitalset" then
    -- stage 2 du spike : pose le chunk préparé (FX supprimé au cycle précédent -> instanciation)
    local tr = find_track("GoleM:_keys")
    local ck = read_file(root .. "/presets/.keyschunk.tmp")
    if tr and ck then
      local okset = reaper.SetTrackStateChunk(tr, ck, false)
      log("vitalset: SetTrackStateChunk -> " .. tostring(okset))
    else log("vitalset: piste ou .keyschunk.tmp manquant") end
  elseif cmd.action == "perf_rec" then
    -- bootstrap perf-rec dans le Reaper DÉJÀ lancé : golem_watch (en mémoire) ne connaît pas encore
    -- cette action et la route ici. On relaie la commande vers la boucle golem_perfrec et on (re)lance
    -- cette boucle si son heartbeat n'est plus frais. En production, golem_watch route perf_rec
    -- directement (ProjExtState) et cette branche n'est jamais atteinte.
    reaper.SetProjExtState(0, "golem", "perf_cmd", cmd_raw)
    local _hb = tonumber(reaper.GetExtState("golem", "perfrec_alive")) or 0
    if reaper.time_precise() - _hb > 2.0 then
      reaper.SetExtState("golem", "perfrec_kick", "1", false)   -- une commande fraîche attend d'être exécutée
      local _perf = root .. "/reaper/Scripts/golem_perfrec.lua"
      if reaper.file_exists(_perf) then dofile(_perf) end
    end
  else
    -- Legacy recall (pistes GoleM:<id> / LiveConfig) DÉBRANCHÉ (audit 2026-07-07) : le recall vit
    -- dans golem_rig.lua (rig_recall via golem_watch), stomp aussi. golem_apply ne garde que les
    -- dev tools ci-dessus. On ne touche plus ni pistes ni ProjExtState ici.
    log("action inconnue, ignorée : " .. tostring(cmd.action or cmd.preset or "?"))
  end
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("golem " .. (cmd.action or cmd.preset or "?") .. "/" .. (cmd.scene or cmd.block or "?"), -1)
  reaper.TrackList_AdjustWindows(false)
end

main()
