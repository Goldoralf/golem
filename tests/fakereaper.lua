-- SPDX-License-Identifier: GPL-3.0-or-later
--[[ Un REAPER FACTICE pour jouer le vrai golem_rig.lua sous lupa, sans REAPER (docs/quality-automation.md, lot 4).

  Il ne simule pas le son : il tient la COMPTABILITÉ que l'API expose — pistes dans l'ordre du projet, leurs
  valeurs (I_RECARM, I_FOLDERDEPTH, B_MAINSEND…), leurs chaînes FX (nom, activé, paramètres, config nommée),
  leurs sends (avec I_MIDIFLAGS), leur mémoire P_EXT, les chunks, gmem, ExtState, les defers — et il reproduit
  les pièges documentés (docs/pitfalls/reaper.md) : SetTrackStateChunk EFFACE P_EXT, un send neuf laisse passer
  le MIDI (I_MIDIFLAGS 0), un plugin absent de l'inventaire rend -1, un nouveau send rend son index.

  Chargé AVANT golem_rig.lua : il pose `reaper` (l'API) et `FAKE` (l'état, lisible depuis Python).
  Réglages lus dans les globales posées par le banc : FAKE_OS ("Other" = Linux, "Win64", "OSX64", "macOS-arm64"),
  FAKE_RESOURCE (dossier de ressources), FAKE_INSTALLED (liste des noms de plugins qui existent),
  FAKE_SPECS (nom de plugin -> liste de {name, min, max, def}), py_mkdir (fonction Python).
]]--
local F = { tracks = {}, installed = {}, specs = {}, os = FAKE_OS or "Other", resource = FAKE_RESOURCE or "",
            gmem = {}, gmem_ns = nil, ext = {}, calls = {}, defers = {}, now = 1000.0, bpm = 120, guid_n = 0,
            log = {}, proj = "proj#1", project_path = "" }
FAKE = F
for _, n in ipairs(FAKE_INSTALLED or {}) do F.installed[n] = true end
if FAKE_SPECS then for k, v in pairs(FAKE_SPECS) do F.specs[k] = v end end

local reaper = {}
_G.reaper = reaper
local function count(name) F.calls[name] = (F.calls[name] or 0) + 1 end
local function guid() F.guid_n = F.guid_n + 1; return string.format("{FAKE-GUID-%04d}", F.guid_n) end
local function note(s) F.log[#F.log + 1] = s end

-- ── pistes ──────────────────────────────────────────────────────────────────────────────────────────
local function new_track()
  return { name = "", guid = guid(), ext = {}, fx = {}, sends = {}, hw = {}, selected = false, chunk_lines = nil,
           info = { I_RECARM = 0, I_RECMODE = 0, I_RECMON = 0, I_RECINPUT = 0, B_MAINSEND = 1, I_FOLDERDEPTH = 0,
                    D_VOL = 1.0, D_PAN = 0.0, B_MUTE = 0, B_SOLO = 0, I_NCHAN = 2, I_AUTOMODE = 0, B_PHASE = 0,
                    I_SOLO = 0, B_SHOWINMIXER = 1, B_SHOWINTCP = 1, I_PERFFLAGS = 0, I_FXEN = 1 } }
end
local function index_of(tr) for i, t in ipairs(F.tracks) do if t == tr then return i end end return nil end

function reaper.CountTracks(_) count("CountTracks"); return #F.tracks end
function reaper.GetTrack(_, i) count("GetTrack"); return F.tracks[i + 1] end
function reaper.InsertTrackAtIndex(i, _) count("InsertTrackAtIndex"); table.insert(F.tracks, i + 1, new_track()) end
function reaper.DeleteTrack(tr) count("DeleteTrack"); local i = index_of(tr); if i then table.remove(F.tracks, i) end
  for _, t in ipairs(F.tracks) do                                   -- un send vers une piste effacée disparaît
    for k = #t.sends, 1, -1 do if t.sends[k].dest == tr then table.remove(t.sends, k) end end
  end
end
function reaper.ValidatePtr2(_, ptr, _) return index_of(ptr) ~= nil end
function reaper.GetTrackGUID(tr) return tr.guid end
function reaper.SetOnlyTrackSelected(tr) for _, t in ipairs(F.tracks) do t.selected = (t == tr) end end
function reaper.ReorderSelectedTracks(before, make_prev_folder)
  count("ReorderSelectedTracks")
  local sel, rest = {}, {}
  for i, t in ipairs(F.tracks) do if t.selected then sel[#sel + 1] = t else rest[#rest + 1] = t end end
  -- `before` est un index dans la liste AVANT déplacement : on le convertit en position parmi les restantes
  local pos = 0
  for i = 1, math.min(before, #F.tracks) do if not F.tracks[i].selected then pos = pos + 1 end end
  local out = {}
  for i = 1, pos do out[#out + 1] = rest[i] end
  for _, t in ipairs(sel) do out[#out + 1] = t end
  for i = pos + 1, #rest do out[#out + 1] = rest[i] end
  F.tracks = out
  if make_prev_folder == 1 and pos >= 1 then rest[pos].info.I_FOLDERDEPTH = 1 end
end
function reaper.TrackList_AdjustWindows(_) end
function reaper.PreventUIRefresh(_) end
function reaper.Undo_BeginBlock() end
function reaper.Undo_EndBlock(_, _) end

function reaper.GetSetMediaTrackInfo_String(tr, key, val, set)
  count("GetSetMediaTrackInfo_String")
  if key == "P_NAME" then
    if set then tr.name = val end
    return true, tr.name
  elseif key:sub(1, 6) == "P_EXT:" then
    local k = key:sub(7)
    if set then tr.ext[k] = val; return true, val end
    return tr.ext[k] ~= nil, tr.ext[k] or ""
  elseif key == "GUID" then
    return true, tr.guid
  end
  return false, ""
end
function reaper.SetMediaTrackInfo_Value(tr, key, v) count("SetMediaTrackInfo_Value"); tr.info[key] = v; return true end
function reaper.GetMediaTrackInfo_Value(tr, key)
  if key == "P_PARTRACK" or key == "P_PROJECT" then return nil end
  if key == "IP_TRACKNUMBER" then return index_of(tr) or 0 end        -- 1-based, comme REAPER (0 = pas dans le projet)
  return tr.info[key] or 0
end
function reaper.GetParentTrack(tr)
  local i = index_of(tr); if not i then return nil end
  local depth = 0
  for k = i - 1, 1, -1 do
    local t = F.tracks[k]
    depth = depth + (t.info.I_FOLDERDEPTH or 0)
    if (t.info.I_FOLDERDEPTH or 0) == 1 and depth >= 1 then return t end
  end
  return nil
end

-- ── sends ───────────────────────────────────────────────────────────────────────────────────────────
local SEND_DEFAULTS = { D_VOL = 1.0, D_PAN = 0.0, B_MUTE = 0, B_PHASE = 0, B_MONO = 0, I_SENDMODE = 0,
                        I_SRCCHAN = 0, I_DSTCHAN = 0, I_MIDIFLAGS = 0, I_AUTOMODE = 0 }   -- MIDI PASSE par défaut
local function new_send(dest)
  local s = { dest = dest }
  for k, v in pairs(SEND_DEFAULTS) do s[k] = v end
  return s
end
function reaper.CreateTrackSend(src, dest)
  count("CreateTrackSend")
  if dest == nil then src.hw[#src.hw + 1] = new_send(nil); return #src.hw - 1 end
  src.sends[#src.sends + 1] = new_send(dest); return #src.sends - 1
end
local function send_list(tr, cat)
  if cat == 0 then return tr.sends elseif cat == 1 then return tr.hw end
  local recv = {}
  for _, t in ipairs(F.tracks) do for _, s in ipairs(t.sends) do if s.dest == tr then recv[#recv + 1] = s end end end
  return recv
end
function reaper.GetTrackNumSends(tr, cat) return #send_list(tr, cat) end
function reaper.GetTrackSendInfo_Value(tr, cat, idx, key)
  local s = send_list(tr, cat)[idx + 1]; if not s then return 0 end
  if key == "P_DESTTRACK" then return s.dest elseif key == "P_SRCTRACK" then return tr end
  return s[key] or 0
end
function reaper.SetTrackSendInfo_Value(tr, cat, idx, key, v)
  count("SetTrackSendInfo_Value")
  local s = send_list(tr, cat)[idx + 1]; if not s then return false end
  s[key] = v; return true
end
function reaper.RemoveTrackSend(tr, cat, idx)
  count("RemoveTrackSend")
  local l = send_list(tr, cat); if l[idx + 1] then table.remove(l, idx + 1); return true end
  return false
end
function reaper.BR_GetMediaTrackSendInfo_Track(tr, cat, idx, _) local s = send_list(tr, cat)[idx + 1]; return s and s.dest or nil end

-- ── FX ──────────────────────────────────────────────────────────────────────────────────────────────
local function generic_specs(n)
  local out = {}
  for i = 1, n do out[i] = { name = "P" .. i, min = 0, max = 1, def = 0.5 } end
  return out
end
local function specs_for(name)
  if F.specs[name] then return F.specs[name] end
  local short = name:gsub("^%u+3?i?: ", "")                         -- « JS: x » -> « x », « VST3: X (V) » -> « X (V) »
  if F.specs[short] then return F.specs[short] end
  return generic_specs(6)
end
local function new_fx(name)
  local fx = { name = name, enabled = true, cfg = {}, guid = guid(), state = "", params = {} }
  for _, sp in ipairs(specs_for(name)) do
    fx.params[#fx.params + 1] = { name = sp.name, min = sp.min or 0, max = sp.max or 1, val = sp.def or sp.min or 0 }
  end
  return fx
end
local function installed(name)
  if F.installed[name] then return true end
  local short = name:gsub("^JS: ", "JS:"):gsub("^JS:", "")
  if F.installed["JS:" .. short] or F.installed["JS: " .. short] then return true end
  -- un JSFX de golem se demande par son chemin sous Effects/ (« JS:golem/golem_safety », avec ou sans .jsfx) :
  -- l'inventaire factice le connaît par le nom de fichier
  local base = short:match("([^/]+)$") or short
  base = base:gsub("%.jsfx$", "")
  return F.installed[base] or false
end
function reaper.TrackFX_AddByName(tr, name, _rec, inst)
  count("TrackFX_AddByName")
  if inst == nil or inst == 0 or inst > 0 then
    for i, fx in ipairs(tr.fx) do if fx.name == name then return i - 1 end end
    if inst == nil or inst == 0 then return -1 end
  end
  if not installed(name) then return -1 end
  tr.fx[#tr.fx + 1] = new_fx(name)
  return #tr.fx - 1
end
function reaper.TrackFX_GetCount(tr) return #tr.fx end
function reaper.TrackFX_Delete(tr, i) count("TrackFX_Delete"); if tr.fx[i + 1] then table.remove(tr.fx, i + 1); return true end return false end
function reaper.TrackFX_GetFXName(tr, i, _) local fx = tr.fx[i + 1]; if not fx then return false, "" end
  return true, (fx.cfg.renamed_name and fx.cfg.renamed_name ~= "") and fx.cfg.renamed_name or fx.name end
function reaper.TrackFX_GetEnabled(tr, i) local fx = tr.fx[i + 1]; return fx and fx.enabled or false end
function reaper.TrackFX_SetEnabled(tr, i, on) count("TrackFX_SetEnabled"); local fx = tr.fx[i + 1]; if fx then fx.enabled = on and true or false end end
function reaper.TrackFX_GetNumParams(tr, i) local fx = tr.fx[i + 1]; return fx and #fx.params or 0 end
function reaper.TrackFX_GetParamName(tr, i, p, _) local fx = tr.fx[i + 1]; local pr = fx and fx.params[p + 1]
  if not pr then return false, "" end return true, pr.name end
function reaper.TrackFX_GetParam(tr, i, p) local fx = tr.fx[i + 1]; local pr = fx and fx.params[p + 1]
  if not pr then return 0, 0, 1 end return pr.val, pr.min, pr.max end
function reaper.TrackFX_SetParam(tr, i, p, v) count("TrackFX_SetParam"); local fx = tr.fx[i + 1]; local pr = fx and fx.params[p + 1]
  if not pr then return false end pr.val = v; return true end
function reaper.TrackFX_GetParamNormalized(tr, i, p) local fx = tr.fx[i + 1]; local pr = fx and fx.params[p + 1]
  if not pr then return 0 end if pr.max == pr.min then return 0 end return (pr.val - pr.min) / (pr.max - pr.min) end
function reaper.TrackFX_SetParamNormalized(tr, i, p, n) count("TrackFX_SetParamNormalized"); local fx = tr.fx[i + 1]; local pr = fx and fx.params[p + 1]
  if not pr then return false end pr.val = pr.min + (pr.max - pr.min) * n; return true end
function reaper.TrackFX_GetFormattedParamValue(tr, i, p, _) local fx = tr.fx[i + 1]; local pr = fx and fx.params[p + 1]
  if not pr then return false, "" end return true, tostring(pr.val) end
function reaper.TrackFX_GetParameterStepSizes(_, _, _) return false, 0, 0, 0, false end
function reaper.TrackFX_GetParamFromIdent(_, _, _) return -1 end
function reaper.TrackFX_GetFXGUID(tr, i) local fx = tr.fx[i + 1]; return fx and fx.guid or nil end
function reaper.TrackFX_Show(_, _, _) end
function reaper.TrackFX_GetOpen(_, _) return false end
function reaper.TrackFX_GetNamedConfigParm(tr, i, key)
  count("TrackFX_GetNamedConfigParm")
  local fx = tr.fx[i + 1]; if not fx then return false, "" end
  if fx.cfg[key] ~= nil then return true, fx.cfg[key] end
  if key == "fx_ident" or key == "original_name" or key == "fx_name" then return true, fx.name end
  if key == "fx_type" then return true, (fx.name:match("^(%u+3?i?):") or "VST") end
  if key == "vst_chunk" or key == "chunk" then return true, fx.state end
  if key == "renamed_name" then return true, "" end
  return false, ""
end
function reaper.TrackFX_SetNamedConfigParm(tr, i, key, val)
  count("TrackFX_SetNamedConfigParm")
  local fx = tr.fx[i + 1]; if not fx then return false end
  if key == "vst_chunk" or key == "chunk" then fx.state = val else fx.cfg[key] = val end
  return true
end
function reaper.TrackFX_CopyToTrack(src, i, dst, j, move)
  count("TrackFX_CopyToTrack")
  local fx = src.fx[i + 1]; if not fx then return end
  local cp = { name = fx.name, enabled = fx.enabled, cfg = {}, guid = guid(), state = fx.state, params = {} }
  for k, v in pairs(fx.cfg) do cp.cfg[k] = v end
  for k, pr in ipairs(fx.params) do cp.params[k] = { name = pr.name, min = pr.min, max = pr.max, val = pr.val } end
  table.insert(dst.fx, math.min(j + 1, #dst.fx + 1), cp)
  if move then table.remove(src.fx, i + 1) end
end
function reaper.EnumInstalledFX(i)
  local names = {}
  for n in pairs(F.installed) do names[#names + 1] = n end
  table.sort(names)
  local n = names[i + 1]
  if not n then return false, "", "" end
  return true, n, n
end

-- ── chunks : le texte que REAPER montrerait, et le PIÈGE (SetTrackStateChunk efface P_EXT) ─────────
local function fx_header(fx)
  local kind, rest = fx.name:match("^(%u+3?i?): (.*)$")
  if kind == "JS" then return '<JS ' .. rest .. ' ""' end
  if kind == "LV2" or kind == "LV2i" then return '<LV2 "' .. fx.name .. '" ""' end
  if kind then return '<VST "' .. fx.name .. '" ' .. rest:gsub("%W", "") .. '.dll 0 "" 0<' .. fx.guid .. '> ""' end
  return '<VST "' .. fx.name .. '" ' .. fx.name:gsub("%W", "") .. '.dll 0 "" 0<' .. fx.guid .. '> ""'
end
function reaper.GetTrackStateChunk(tr, _, _)
  count("GetTrackStateChunk")
  local L = { "<TRACK " .. tr.guid, 'NAME "' .. tr.name .. '"', "REC " .. (tr.info.I_RECARM or 0) .. " " .. (tr.info.I_RECINPUT or 0) .. " " .. (tr.info.I_RECMON or 0) .. " " .. (tr.info.I_RECMODE or 0) .. " 0 0 0 0",
              "MAINSEND " .. (tr.info.B_MAINSEND or 1) .. " 0", "ISBUS " .. (tr.info.I_FOLDERDEPTH or 0) .. " 0" }
  if #tr.fx > 0 then
    L[#L + 1] = "<FXCHAIN"
    for _, fx in ipairs(tr.fx) do
      L[#L + 1] = "BYPASS " .. (fx.enabled and 0 or 1) .. " 0 0"
      L[#L + 1] = fx_header(fx)
      if fx.state ~= "" then for line in (fx.state .. "\n"):gmatch("([^\n]*)\n") do L[#L + 1] = line end end
      L[#L + 1] = ">"
      L[#L + 1] = "FLOATPOS 0 0 0 0"
      L[#L + 1] = "FXID " .. fx.guid
      L[#L + 1] = "WAK 0 0"
    end
    L[#L + 1] = ">"
  end
  L[#L + 1] = ">"
  return true, table.concat(L, "\n")
end
function reaper.SetTrackStateChunk(tr, chunk, _)
  count("SetTrackStateChunk")
  tr.ext = {}                                   -- LE PIÈGE : la mémoire P_EXT ne survit pas à un chunk posé
  tr.chunk_lines = {}
  for line in (chunk .. "\n"):gmatch("([^\n]*)\n") do tr.chunk_lines[#tr.chunk_lines + 1] = line end
  -- on relit l'état des FX dans l'ordre : BYPASS, en-tête, lignes d'état jusqu'au « > » fermant
  local fxs, cur, in_state = {}, nil, false
  for _, line in ipairs(tr.chunk_lines) do
    local byp = line:match("^BYPASS (%d)")
    if byp then cur = { enabled = byp == "0", state_lines = {} }
    elseif cur and not in_state and line:match("^<") then
      cur.header = line; in_state = true
    elseif cur and in_state then
      if line == ">" then in_state = false; fxs[#fxs + 1] = cur; cur = nil
      else cur.state_lines[#cur.state_lines + 1] = line end
    end
  end
  for k, parsed in ipairs(fxs) do
    local fx = tr.fx[k]
    if fx then fx.enabled = parsed.enabled; fx.state = table.concat(parsed.state_lines, "\n") end
  end
  return true
end

-- ── gmem, ExtState, horloge, defer, divers ──────────────────────────────────────────────────────────
function reaper.gmem_attach(ns) F.gmem_ns = ns; F.gmem[ns] = F.gmem[ns] or {} end
function reaper.gmem_write(i, v) count("gmem_write"); local ns = F.gmem_ns or "_"; F.gmem[ns] = F.gmem[ns] or {}; F.gmem[ns][i] = v end
function reaper.gmem_read(i) local ns = F.gmem_ns or "_"; return (F.gmem[ns] or {})[i] or 0 end
function reaper.SetExtState(sec, key, val, _) F.ext[sec .. "/" .. key] = val end
function reaper.GetExtState(sec, key) return F.ext[sec .. "/" .. key] or "" end
function reaper.DeleteExtState(sec, key, _) F.ext[sec .. "/" .. key] = nil end
function reaper.HasExtState(sec, key) return F.ext[sec .. "/" .. key] ~= nil end
-- l'ExtState de PROJET appartient à un projet : 0 (ou nil) = le projet courant, F.proj
local function proj_key(p, sec, key) return "proj:" .. tostring((p == 0 or p == nil) and F.proj or p) .. ":" .. sec .. "/" .. key end
function reaper.SetProjExtState(p, sec, key, val) F.ext[proj_key(p, sec, key)] = val; return 1 end
function reaper.GetProjExtState(p, sec, key) local v = F.ext[proj_key(p, sec, key)]; return v and 1 or 0, v or "" end
function reaper.time_precise() F.now = F.now + 0.001; return F.now end
function reaper.defer(fn) F.defers[#F.defers + 1] = fn end
function reaper.SetCurrentBPM(_, bpm, _) F.bpm = bpm end
function reaper.Master_GetTempo() return F.bpm end
function reaper.GetPlayState() return 0 end
function reaper.GetOS() return F.os end
function reaper.GetResourcePath() return F.resource end
function reaper.GetAudioDeviceInfo(_, _) return false, "" end
function reaper.GetMIDIInputName(_, _) return false, "" end
function reaper.GetNumMIDIInputs() return 0 end
function reaper.GetNumMIDIOutputs() return 0 end
function reaper.GetMIDIOutputName(_, _) return false, "" end
-- le projet courant : `F.project_path` vide = jamais enregistré ; `F.proj` change quand on « ouvre » un autre projet
function reaper.EnumProjects(idx, _) if idx == -1 then return F.proj, F.project_path end return nil, "" end
function reaper.GetToggleCommandState(cmd) return (F.toggles or {})[cmd] or 0 end
function reaper.Main_OnCommand(cmd, _) count("Main_OnCommand"); F.last_command = cmd
  if F.toggles and F.toggles[cmd] then F.toggles[cmd] = 1 - F.toggles[cmd] end end
function reaper.ShowConsoleMsg(s) note(tostring(s)) end
function reaper.file_exists(p) local f = io.open(p, "r"); if f then f:close(); return true end return false end
function reaper.RecursiveCreateDirectory(p, _) if py_mkdir then py_mkdir(p) end return 0 end
function reaper.GetAppVersion() return "7.80/fake" end
function reaper.APIExists(name) return reaper[name] ~= nil end

-- ── ce que le banc lit ──────────────────────────────────────────────────────────────────────────────
function F.run_defers()
  local d = F.defers; F.defers = {}
  for _, fn in ipairs(d) do fn() end
  return #d
end
function F.snapshot()
  local out = {}
  for i, tr in ipairs(F.tracks) do
    local fx = {}
    for k, f in ipairs(tr.fx) do fx[k] = { name = f.name, enabled = f.enabled, renamed = f.cfg.renamed_name or "" } end
    local sends = {}
    for k, s in ipairs(tr.sends) do sends[k] = { dest = s.dest.name, midiflags = s.I_MIDIFLAGS, mute = s.B_MUTE, vol = s.D_VOL } end
    out[i] = { name = tr.name, fx = fx, sends = sends, hw = #tr.hw, info = tr.info, ext = tr.ext }
  end
  return out
end
