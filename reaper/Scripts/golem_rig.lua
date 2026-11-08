-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — rig (P3, modèle "paths + splits")
  Matérialise un plan reaper/FXChains/<preset>.rig.json en pistes Reaper + routage.
  Déclenché par le bridge via presets/.command.json  ->  { "action":"rig_recall", "preset":"<id>" }.

  Ce module N'utilise PAS l'ancien modèle (golem_apply.lua reste seul maître de celui-ci).
  Il réutilise TELS QUELS les helpers éprouvés de golem_apply : json_decode, read_file, log,
  track_name, dblin, find_track, PREFIX, l'estampille d'id via renamed_name (tag_fx/fx_tag),
  et surtout apply_block_params + set_norm_to_target + read_effects (potards par map idx/mode).

  ⚠ Non exécutable hors-Reaper. Points à valider AU RIG (voir en tête de la réponse à l'humain) :
    1) chargement fichier NAM/IR par API (load_block_file) — le plus incertain.
    2) index de retour de CreateTrackSend(tr,nil) réutilisé en catégorie 1 (calqué sur golem_apply).
    3) ordre/fermeture de folder (parent AVANT children, dernier child = I_FOLDERDEPTH -1).
    4) encodage I_RECINPUT mono (canal 0-based = input-1) + monitoring (I_RECMON/I_RECARM).
]]--

-- log : console ReaScript + fichier presets/.golem-rig.log (lu par l'agent de test).
local _logpath = nil
local function log(s)
  if _logpath then local f = io.open(_logpath, "a"); if f then f:write(tostring(s) .. "\n"); f:close() end end
end

-- UN SEUL POINT D'AJOUT D'EFFET (2026-10-24, un testeur Windows) : sur un REAPER neuf, « Auto-float newly created FX
-- windows » ouvrait une fenêtre par effet posé — une dizaine de fenêtres par-dessus golem à chaque reconstruction. On la
-- referme aussitôt (TrackFX_Show 2 = cacher la fenêtre flottante, sans effet si elle n'est pas ouverte) ; seule la
-- fenêtre de plugin que le musicien demande (op « open », plus bas) s'affiche. instantiate 0 = chercher sans ajouter.
local function add_fx(track, name, rec, inst)
  local fx = reaper.TrackFX_AddByName(track, name, rec, inst)
  if fx and fx >= 0 and inst ~= 0 then reaper.TrackFX_Show(track, fx, 2) end
  return fx
end

----------------------------------------------------------------------- mini JSON
-- décodeur JSON pur-Lua (copié verbatim de golem_apply.lua)
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

----------------------------------------------------------------------- fichiers (copiés)
local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end
local runtime = dofile(repo_root() .. "/reaper/Scripts/golem_paths.lua")
local project = dofile(repo_root() .. "/reaper/Scripts/golem_project.lua")

local function read_file(p) local f = io.open(p, "r"); if not f then return nil end local s = f:read("*a"); f:close(); return s end

-- Signature FX d'une piste (P_EXT persistant) : sert à NE PAS reconstruire (clear+build = reload
-- NAM/IR async) une piste dont la chaîne FX est INCHANGÉE entre deux rebuilds -> plus de « delete
-- piste pendant que son IR charge » = plus de crash mediaafx (fix de fond 2026-07-10). djb2 en
-- arithmétique pure (pas de bitops : compatible tout build Lua livré par Reaper).
local function cheap_hash(s)
  local h = 5381
  for i = 1, #s do h = (h * 33 + s:byte(i)) % 4294967296 end
  return h
end
local FXSIG_KEY = "P_EXT:golem_fxsig"
local function get_fxsig(tr) local _, s = reaper.GetSetMediaTrackInfo_String(tr, FXSIG_KEY, "", false); return s end
local function set_fxsig(tr, s) reaper.GetSetMediaTrackInfo_String(tr, FXSIG_KEY, s, true) end
-- ── PISTE MONTÉE INCOMPLÈTE (2026-10-03) ──
-- Un patch drums monté AVANT l'installation d'AVL Drumkits gardait sa piste sans kit pour toujours : la
-- signature ne regarde que le document, donc REUSE à chaque émission, même après l'installation et le
-- redémarrage de Reaper. Une piste dont un plugin a manqué au montage garde sa signature suivie de
-- « |missing@<empreinte de l'inventaire Reaper> » : elle est rebâtie UNE fois, quand l'ensemble des plugins
-- installés change (ce qu'un ajout de plugin + redémarrage produit) — jamais à chaque rappel pendant
-- qu'on joue (la classe de crash mediaafx, cf. SETTLE). _MISSING_N compte les poses ratées.
local _MISSING_N = 0
local function inventory_hash(root)
  local raw = read_file(root .. "/presets/.fx-inventory.json") or ""
  raw = raw:gsub('"at"%s*:%s*[%d%.]+', "")            -- l'heure du scan n'est pas l'ensemble des plugins
  return tostring(cheap_hash(raw))
end
local function sig_matches(root, stored, sig)
  local base, inv = (stored or ""):match("^(.*)|missing@([^|]*)$")
  if not base then return stored == sig end
  return base == sig and inv == inventory_hash(root)
end
local function core_failed(tr)
  local _, value = reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:golem_core_failed", "", false)
  return value == "1"
end

local function dblin(db) return 10 ^ ((db or 0) / 20) end

local function clamp01(x) x = tonumber(x) or 0; if x < 0 then return 0 elseif x > 1 then return 1 else return x end end

local PREFIX = "GoleM:"

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

-- estampille d'id (résolution de bloc par id à l'étape 4 : scènes/stomps). REAPER >= 6.79.
local function tag_fx(track, fx, id)
  reaper.TrackFX_SetNamedConfigParm(track, fx, "renamed_name", "golem:" .. id)
end

------------------------------------------------------ params de blocs (copiés verbatim)
local _effects_cache = nil
-- RÉSOLUTION DESKTOP (Windows 2026-10-01, macOS 2026-10-04 — docs/platforms.md M6) : sur un
-- poste, chaque bloc se résout par la table de SON OS (noms de plugins scannés, ou « unsupported ») au
-- lieu des alias Linux — sous macOS, un bloc Calf ou guitarix aurait cherché un plugin qui n'existe pas,
-- et les blocs NAM « pédale » passaient par le chargeur LV2 du rack : muets.
local _GOS = reaper.GetOS()
local MAC_FX = _GOS:match("^OSX") ~= nil or _GOS:match("^macOS") ~= nil
local DESKTOP_FX = _GOS:match("^Win") ~= nil or MAC_FX
local DESKTOP_TABLE = MAC_FX and "effects-macos.json" or "effects-windows.json"
local function read_effects(root)
  if _effects_cache then return _effects_cache end
  local map = {}
  local ej = read_file(root .. "/library/catalog/effects.json")
  local data = ej and json_decode(ej) or nil
  if data and data.effects then
    for _, e in ipairs(data.effects) do
      local by_id, ni = {}, 0
      for _, pd in ipairs(e.params or {}) do
        if pd.type ~= "bool" and pd.type ~= "enum" then pd.num_index = ni; ni = ni + 1 end
        if pd.id then by_id[pd.id] = pd end
      end
      if e.type then map[e.type] = { plugin = e.plugin, by_id = by_id, params = e.params, engine = e.engine, knobs = e.knobs } end
    end
  else
    log("effects.json illisible : params de blocs ignorés")
  end
  if DESKTOP_FX then
    local wj = read_file(root .. "/library/catalog/" .. DESKTOP_TABLE)
    local wd = wj and json_decode(wj) or nil
    if not (wd and wd.effects) then
      log(DESKTOP_TABLE .. " illisible : résolution desktop désactivée")
    else
      for btype, override in pairs(wd.effects) do
        local e = map[btype]
        if e then
          e.windows_strict = true
          e.unsupported = override.unsupported
          if override.plugin then e.plugin = override.plugin end
          -- Surge XT Effects (2026-10-22) : sous Windows/macOS « FX Type » est un paramètre VST3 normalisé (0..1,
          -- 29 types) et le plugin RÉINITIALISE ses paramètres au prochain bloc audio après un changement de type —
          -- écrits dans le même tick, ils sont effacés (mesuré au banc). D'où un FX_INIT propre à la table et une
          -- seconde passe différée (late_params) après la construction.
          if override.fx_init then e.fx_init = override.fx_init end
          if override.late_params then e.late_params = true end
          for _, pd in ipairs(e.params or {}) do
            local mode = (override.param_modes or {})[pd.id] or override.param_mode
            if mode == "norm" then pd.map = { mode = "norm" } end
          end
          for pid, name in pairs(override.params or {}) do
            local pd = e.by_id[pid]
            if pd then
              pd.name = name
              if override.param_mode == "pow" then
                -- Windows NAM Output couvre ±40 dB même si le potard du catalogue
                -- n'expose que ±20 dB ; employer les bornes natives évite de doubler le gain.
                local bounds = (override.param_ranges or {})[pid] or {}
                pd.map = { mode = "pow", min = bounds.min or pd.min, max = bounds.max or pd.max, exp = 1 }
              else
                pd.map = { mode = pd.map and pd.map.mode or "norm" }
              end
            end
          end
        end
      end
    end
  end
  _effects_cache = map
  return map
end

local function find_param_by_name(track, fx, name)
  if not name or name == "" then return nil end
  local target = name:lower()
  local sub = nil
  for pgo = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
    local _, pnm = reaper.TrackFX_GetParamName(track, fx, pgo, "")
    local low = pnm and pnm:lower()
    if low == target then return pgo end                          -- match EXACT prioritaire
    if low and sub == nil and low:find(target, 1, true) then sub = pgo end
  end
  return sub   -- sinon 1re sous-chaîne (⚠ "hold" matchait "thresHOLD" — corrigé par l'exact d'abord)
end

-- ── UN CONVOLVEUR D'IR NE SE BYPASSE JAMAIS (2026-09-21) ───────────────────────────────
-- Mesuré (tools/check-block-stall.py --rig) : rallumer par TrackFX_SetEnabled le convolveur x42 AVEC
-- son IR fige TOUT le moteur audio ~540 ms (il reconfigure l'IR) — c'était la coupure B→A du
-- 2026-09-20. Son interrupteur INTERNE (paramètre « Enable », le port lv2:enabled du plugin) fait le
-- même effet sonore sans rien reconfigurer : 0 à 2 ms sur 6 bascules, mesuré le même jour. Donc pour
-- un convolveur on passe par lui, et le FX reste TOUJOURS actif pour Reaper. Tout autre plugin :
-- TrackFX_SetEnabled, comme avant. ⚠ Un convolveur encore bypassé par Reaper (rig bâti avant cette
-- règle) est réactivé UNE fois — un dernier gel, puis plus jamais ; un rebuild l'évite.
local function is_ir_convolver(tr, fx)
  local names = {}
  local _, shown = reaper.TrackFX_GetFXName(tr, fx, "")               -- ⚠ rend le nom RENOMMÉ (golem:<id>)
  names[1] = shown
  local ok, orig = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_name")   -- le nom d'origine du plugin
  if ok then names[2] = orig end
  for _, nm in ipairs(names) do
    nm = (nm or ""):lower()
    if nm:find("ir convolver", 1, true) or nm:find("zeroconvolv", 1, true) then return true end
  end
  return false
end

-- Un FX qui s'allume par un PARAMÈTRE, jamais par le bypass : le convolveur x42 (rallumé avec son IR, il
-- fige le moteur ~540 ms — CLAUDE.md) et GoleM Freeze (docs/spectral.md : le gel est un geste, le bypass
-- couperait la queue de relâchement et ferait sauter la latence). Rend le nom du paramètre, ou nil.
local function switch_param_of(tr, fx)
  if is_ir_convolver(tr, fx) then return "Enable" end
  local names = {}
  local _, shown = reaper.TrackFX_GetFXName(tr, fx, ""); names[1] = shown
  local ok, orig = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_name"); if ok then names[2] = orig end
  for _, nm in ipairs(names) do
    if (nm or ""):lower():find("golem freeze", 1, true) then return "Freeze" end
  end
  return nil
end

local function fx_set_on(tr, fx, on)
  if not fx or fx < 0 then return end
  local pname = switch_param_of(tr, fx)
  if pname then
    local p = find_param_by_name(tr, fx, pname)
    if p and p >= 0 then
      if not reaper.TrackFX_GetEnabled(tr, fx) then reaper.TrackFX_SetEnabled(tr, fx, true) end
      reaper.TrackFX_SetParam(tr, fx, p, on and 1 or 0)
      return
    end
  end
  reaper.TrackFX_SetEnabled(tr, fx, on)
end

-- match EXACT seul (aucun repli sous-chaîne) : sert à résoudre un param sur le BON FX quand un bloc
-- porte PLUSIEURS FX estampillés golem:<id> (ex. keys : note-zone + moteur). Un « Transpose » de
-- note-zone ne doit jamais matcher un « Transpose » d'un autre plugin par sous-chaîne.
local function find_param_exact(track, fx, name)
  if not name or name == "" then return nil end
  local target = name:lower()
  for p = 0, reaper.TrackFX_GetNumParams(track, fx) - 1 do
    local _, pnm = reaper.TrackFX_GetParamName(track, fx, p, "")
    if pnm and pnm:lower() == target then return p end
  end
  return nil
end

-- résout (fx, pidx) d'un param DÉF sur une LISTE de FX candidats (les FX d'un bloc). map.idx reste
-- prioritaire et vise TOUJOURS le 1er FX (le moteur ; les params à idx sont écrits pour lui). Sinon :
-- nom EXACT sur chaque FX d'abord (zone -> note-zone, drawbar -> b3-ctl…), puis sous-chaîne, puis
-- num_index de repli sur le 1er FX. Mono-FX (liste à 1) = comportement historique à l'identique.
local function resolve_param(track, fxlist, def, strict)
  local map = def.map
  if not strict and map and map.idx ~= nil then return fxlist[1], map.idx end
  for _, fx in ipairs(fxlist) do local p = find_param_exact(track, fx, def.name); if p then return fx, p end end
  if strict then return nil, nil end
  for _, fx in ipairs(fxlist) do local p = find_param_by_name(track, fx, def.name); if p then return fx, p end end
  return fxlist[1], def.num_index
end

local function index_of(options, value)
  for i, o in ipairs(options or {}) do if o == value then return i - 1 end end
  return 0
end

local function pdisp(track, fx, p)
  local _, d = reaper.TrackFX_GetFormattedParamValue(track, fx, p, "")
  d = d or ""
  -- bornes non numériques des faders/ratios ("-inf" dB, "inf:1") : valeurs sentinelles POUR LA
  -- DICHOTOMIE (sinon pdisp=nil aux extrêmes -> fallback linéaire faux : thresh/makeup/pct_db à côté)
  if d:find("inf", 1, true) then return d:find("-", 1, true) and -150 or 150 end
  return tonumber(d:match("[-+]?%d+%.?%d*"))
end

-- cale un param sur sa valeur AFFICHÉE cible par dichotomie sur la normalisée (16 pas). (copié verbatim)
local function set_norm_to_target(track, fx, p, target, mn, mx)
  reaper.TrackFX_SetParamNormalized(track, fx, p, 0); local v0 = pdisp(track, fx, p)
  reaper.TrackFX_SetParamNormalized(track, fx, p, 1); local v1 = pdisp(track, fx, p)
  if not v0 or not v1 or v0 == v1 then
    reaper.TrackFX_SetParamNormalized(track, fx, p, (mx == mn) and 0 or clamp01((target - mn) / (mx - mn))); return
  end
  local inc = v1 > v0
  local lo, hi = 0, 1
  for _i = 1, 16 do
    local mid = (lo + hi) / 2
    reaper.TrackFX_SetParamNormalized(track, fx, p, mid)
    local v = pdisp(track, fx, p) or target
    if (v < target) == inc then lo = mid else hi = mid end
  end
end

-- applique les params d'UN bloc. `fx` = index (mono-FX) OU liste d'index (bloc multi-FX : keys
-- note-zone + moteur). Chaque param est résolu sur le BON FX de la liste (resolve_param).
-- blocs dont les paramètres sont RÉÉCRITS après la construction (table de l'OS : late_params) — voir flush_late_params
local _LATE = {}
_BUILD_GEN = (_BUILD_GEN or 0)              -- génération de construction : une passe différée d'un build dépassé s'abandonne

local function apply_block_params(track, fx, btype, params, effects)
  if not params or not track then return end
  if effects and effects[btype] and effects[btype].late_params and not params._late then
    local first = type(fx) == "table" and fx[1] or fx
    _LATE[#_LATE + 1] = { track = track, fx = fx, btype = btype, params = params,
                          guid = first and first >= 0 and reaper.TrackFX_GetFXGUID(track, first) or nil }
  end
  local fxlist
  if type(fx) == "table" then fxlist = fx else if not fx or fx < 0 then return end; fxlist = { fx } end
  if #fxlist == 0 then return end
  if btype == "capture-module" then
    local engine = fxlist[1]
    local key = "P_EXT:golem_capture_" .. tostring(reaper.TrackFX_GetFXGUID(track, engine))
    local stamp = tostring(params._capture_chunk or "")
    local _, loaded = reaper.GetSetMediaTrackInfo_String(track, key, "", false)
    if loaded ~= stamp then
      local data = read_file(stamp)
      if not data or not reaper.TrackFX_SetNamedConfigParm(track, engine, "clap_chunk", data) then
        log("  x capture module: state rejected")
        reaper.SetMediaTrackInfo_Value(track, "B_MUTE", 1)
        return
      end
      reaper.GetSetMediaTrackInfo_String(track, key, stamp, true)
    end
    for i, v in ipairs(params._capture_values or {}) do
      reaper.TrackFX_SetParamNormalized(track, engine, i - 1, v)
    end
    return
  end
  if btype == "vst-host" then
    local engine = fxlist[1]
    local _, tag = reaper.TrackFX_GetNamedConfigParm(track, engine, "renamed_name")
    local cache_key = "P_EXT:golem_vst_state_" .. tostring(tag or engine):gsub("[^%w_-]", "_")
    local kind = params._clap_chunk and "clap_chunk" or (params._vst_chunk and "vst_chunk")
    local chunk = kind and params["_" .. kind]
    if type(chunk) == "string" and #chunk > 0 then
      local stamp = tostring(reaper.TrackFX_GetFXGUID(track, engine)) .. ":" ..
                    kind .. ":" .. #chunk .. ":" .. cheap_hash(chunk)
      local _, applied = reaper.GetSetMediaTrackInfo_String(track, cache_key, "", false)
      if applied ~= stamp then
        if reaper.TrackFX_SetNamedConfigParm(track, engine, kind, chunk) then
          reaper.GetSetMediaTrackInfo_String(track, cache_key, stamp, true)
        else
          log("  ⚠ vst-host : état " .. kind .. " refusé pour " .. tostring(tag))
        end
      end
    else
      reaper.GetSetMediaTrackInfo_String(track, cache_key, "", true)
    end
    local count = reaper.TrackFX_GetNumParams(track, engine)
    local bypass = reaper.TrackFX_GetParamFromIdent(track, engine, ":bypass")
    for key, value in pairs(params) do
      local n = type(key) == "string" and key:match("^p(%d+)$")
      local p = n and tonumber(n)
      local v = tonumber(value)
      if p and p >= 0 and p < count and p ~= bypass and v and v >= 0 and v <= 1 then
        reaper.TrackFX_SetParamNormalized(track, engine, p, v)
      end
    end
    return
  end
  local schema = effects and effects[btype]
  if not schema then log("  params: pas de schéma pour type '" .. tostring(btype) .. "'"); return end
  for pid, value in pairs(params) do
    local def = schema.by_id[pid]
    if pid:sub(1, 1) == "_" then
      -- métadonnées du compileur (_loud = normalisation de loudness, déjà intégrée à amp.output) :
      -- pas des paramètres, on les saute sans bruit
    elseif pid == "arp" then
      -- paramètre VIRTUEL : il ne vise aucun slider du moteur, il commande l'INSERTION d'un
      -- JSFX midi_arp devant lui (apply_vital_arp). Le laisser passer ici ne faisait rien
      -- d'autre que salir le journal d'un « non résolu » à chaque recall.
    elseif not def then
      log("  params: id '" .. tostring(pid) .. "' inconnu (type " .. tostring(btype) .. ")")
    elseif def.type == "kitref" or def.type == "midilist" then
      -- CONTENU résolu par la compile (le kit d'un drumkit, les patterns d'une boîte à rythmes) :
      -- aucun slider ne le porte. Sans ce garde, resolve_param retombait sur fxlist[1] @p0 et le
      -- `kit` d'un drumkit ÉCRASAIT le slider Slot du traducteur golem_drumtrans (mesuré 2026-09-17).
    else
      local map = def.map
      local pfx, pidx = resolve_param(track, fxlist, def, schema.windows_strict)
      local mode = (map and map.mode) or "norm"
      local nump = pfx and reaper.TrackFX_GetNumParams(track, pfx) or 0
      if not (pfx and pidx and pidx >= 0 and pidx < nump) then
        log("  params: '" .. tostring(pid) .. "' non résolu (nom '" .. tostring(def.name) .. "', idx " .. tostring(pidx) .. ")")
      else
        if def.type == "enum" then
          local i = index_of(def.options or {}, value)
          local tv = def.values and def.values[i + 1]          -- valeur cible par option (ex. stages 4/6/8/12,
          if tv ~= nil then                                    -- subdivisions delay en noires affichées)
            if mode == "norm" then set_norm_to_target(track, pfx, pidx, tv, tonumber(def.min) or 0, tonumber(def.max) or 1)
            else reaper.TrackFX_SetParam(track, pfx, pidx, tv) end
          elseif mode == "raw" then reaper.TrackFX_SetParam(track, pfx, pidx, i)
          else reaper.TrackFX_SetParamNormalized(track, pfx, pidx, i / math.max(1, #(def.options or {}) - 1)) end
        elseif def.type == "bool" then
          local b = (value and value ~= 0) and 1 or 0
          if mode == "raw" then reaper.TrackFX_SetParam(track, pfx, pidx, b)
          else reaper.TrackFX_SetParamNormalized(track, pfx, pidx, b) end
        else
          local mn, mx = tonumber(def.min) or 0, tonumber(def.max) or 1
          local v = tonumber(value)
          if not v then log("  params: '" .. tostring(pid) .. "' valeur non numérique"); v = nil end
          if v ~= nil then
            local curve = map and map.curve
            if curve == "pct_db" then
              -- potard en % -> cible en dB affichés (ports fader ReaDelay/ReaPitch : Wet/Feedback)
              if v <= 0 then reaper.TrackFX_SetParamNormalized(track, pfx, pidx, 0)
              else set_norm_to_target(track, pfx, pidx, 20 * math.log(v / 100, 10), -60, 12) end
            elseif mode == "raw" then
              if v < mn then v = mn elseif v > mx then v = mx end
              if map and map.scale then v = v * map.scale end   -- ex. port 0..1 affiché 0..100%
              reaper.TrackFX_SetParam(track, pfx, pidx, v)
            elseif mode == "pow" then
              -- TAPER CONNU, écrit en NORMALISÉ sans relire (docs/spectral.md, 2026-09-25) : les plugins
              -- nih-plug (CLAP/VST3) et JUCE appliquent un paramètre sur le thread audio, donc la valeur
              -- relue dans le même appel est CELLE D'AVANT — la dichotomie de `set_norm_to_target` lisait
              -- un pas en retard et posait n'importe quoi (Window 32768 pour 2048, Attack 0,1 ms pour 50).
              -- norm = ((v - min) / (max - min)) ^ exp ; `sym` : deux moitiés autour de `center` (nih-plug
              -- SymmetricalSkewed) ; `db` : v est en dB, le port est un gain linéaire. Les bornes ici sont
              -- celles du PLUGIN (map.min/max), pas celles du potard (def.min/max).
              if v < mn then v = mn elseif v > mx then v = mx end
              local pmn, pmx, e = tonumber(map.min) or 0, tonumber(map.max) or 1, tonumber(map.exp) or 1
              if map.db then v = 10 ^ (v / 20); pmn = 10 ^ (pmn / 20); pmx = 10 ^ (pmx / 20) end
              local n
              if map.sym then
                local c = tonumber(map.center) or 0
                if map.db then c = 10 ^ (c / 20) end
                if v >= c then n = 0.5 + 0.5 * (((v - c) / (pmx - c)) ^ e)
                else n = 0.5 - 0.5 * (((c - v) / (c - pmn)) ^ e) end
              else
                n = ((v - pmn) / (pmx - pmn)) ^ e
              end
              reaper.TrackFX_SetParamNormalized(track, pfx, pidx, clamp01(n))
            else
              set_norm_to_target(track, pfx, pidx, v, mn, mx)
            end
          end
        end
        log("  param " .. tostring(btype) .. "." .. tostring(pid) .. " = " .. tostring(value) ..
            " (" .. mode .. " @p" .. pidx .. ")")
      end
    end
  end
end

------------------------------------------------------- trim de merge (calqué golem_apply)
-- gain statique en TÊTE du parent merge (avant les blocks post). D_VOL réservé au niveau de scène.
local GAIN_NAMES = { "Volume Adjustment", "JS: Volume Adjustment", "utility/volume", "Gain", "JS: Gain" }
-- ⚠ BUG VOLUME 2026-07-23 : le JSFX utility/volume a DEUX sliders — [0] "Adjustment (dB)" (le
-- gain) et [1] "Max Volume (dB)" (un PLAFOND DUR = clippeur). L'ancienne recherche « premier nom
-- contenant volume/gain » sautait "Adjustment" et écrivait le pad du split sur… le CLIPPEUR
-- (Max Volume = -3) pendant qu'Adjustment traînait à +6 : +6 dB de gain puis écrêtage dur à
-- -3 dBFS sur tout le bus merge -> grésillement massif, zéro dynamique, sur tous les presets à
-- split. Règle désormais : jamais un slider "max…" pour le gain, et tout "Max Volume" présent est
-- NEUTRALISÉ (borne max du slider = pas de plafond).
local function apply_gain_sliders(tr, fx, gain_db)
  local set_gain = false
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, pnm = reaper.TrackFX_GetParamName(tr, fx, p, "")
    local pl = (pnm or ""):lower()
    if pl:find("max") then
      local _, _, mx = reaper.TrackFX_GetParam(tr, fx, p)
      reaper.TrackFX_SetParam(tr, fx, p, mx or 150)            -- plafond au max = neutre
    elseif not set_gain and (pl:find("adjustment") or pl:find("volume") or pl:find("gain")) then
      reaper.TrackFX_SetParam(tr, fx, p, gain_db)              -- slider en dB (JSFX natif)
      set_gain = true
    end
  end
  return set_gain
end

local function set_merge_gain_fx(parent, gain_db)
  gain_db = gain_db or 0
  for _, nm in ipairs(GAIN_NAMES) do
    local fx = add_fx(parent, nm, false, -1)
    if fx and fx >= 0 then
      reaper.TrackFX_CopyToTrack(parent, fx, parent, 0, true)   -- pousse en position 0 (tête)
      apply_gain_sliders(parent, 0, gain_db)
      tag_fx(parent, 0, "__merge_gain")
      log("  merge_gain " .. gain_db .. " dB (" .. nm .. ") @0")
      return true
    end
  end
  log("  merge_gain: aucun plugin gain résolu -> repli D_VOL parent")
  reaper.SetMediaTrackInfo_Value(parent, "D_VOL", dblin(gain_db))
  return false
end

--------------------------------------------------- ajout d'un bloc FX par nom de plugin
-- résolution du plugin : hint effects.json (plugin) d'abord, puis alias, puis type brut.
local ADD_ALIAS = {
  boost   = { "Proteus", "ZamTube", "GxTS9", "Gxts9sim" },
  comp    = { "ReaComp" },
  gate    = { "ReaGate" },
  eq      = { "ReaEQ" },
  delay   = { "ReaDelay" },
  reverb  = { "Dragonfly Hall Reverb", "ReaVerbate" },
  chorus  = { "Calf Multi Chorus" },
  flanger = { "Calf Flanger" },
  ["chorus-js"] = { "JS: sstillwell/chorus_stereo", "JS: Chorus Stereo [Stillwell]" },
  ["flanger-js"] = { "JS: guitar/flanger", "JS: Flanger" },
  phaser  = { "Calf Phaser" },
  ["phaser-js"] = { "JS: guitar/phaser", "JS: 4-Tap Phaser" },
  ["delay-tape-aw"] = { "VST: TapeDelay2 (airwindows)", "VST: TapeDelay2", "TapeDelay2" },
  tremolo = { "Calf Pulsator" },
  -- JSFX maison (link-reaper.sh : reaper/Effects -> <resource>/Effects/golem). Le chemin JS: charge
  -- le fichier même si le cache JSFX de Reaper ne l'a pas encore vu (Reaper lancé avant sa création).
  killswitch = { "JS:golem/golem_killswitch", "JS: golem/golem_killswitch", "JS:golem/golem_killswitch.jsfx" },
  -- chantier 2 (blocs algo OSS déjà installés) : candidats de nom Reaper (à confirmer sur le rig)
  granular = { "ZamGrains", "ZamGrains (Damien Zammit)", "Zam Grains" },
  limiter  = { "x42-dpl - Digital Peak Limiter Mono", "x42-dpl", "DPL", "Digital Peak Limiter" },
  octaver  = { "Gxoc_2", "Gx_oc_2_", "GxOc2", "gx_oc_2" },   -- vrai nom Reaper = Gxoc_2 (vérifié rig)
  vibrato  = { "GxTubeVibrato", "gxtubevibrato" },
  detune   = { "GxDetune", "Gxdetune", "gx_detune" },
  ringmod    = { "MDA RingMod", "mda RingMod", "RingMod" },
  bitcrusher = { "MDA Degrade", "mda Degrade", "Degrade" },
  rezfilter  = { "MDA RezFilter", "mda RezFilter", "RezFilter" },
  ["pedal-nam"] = { "Neural Amp Modeler", "neural_amp_modeler", "NAM" },
  ["preamp-nam"] = { "Neural Amp Modeler", "neural_amp_modeler", "NAM" },   -- outboard capturé (2026-09-14)
  ["comp-nam"]   = { "Neural Amp Modeler", "neural_amp_modeler", "NAM" },
  grit    = { "VST3: Prisma (unplugred)", "Prisma", "VST3: Prisma" },   -- distorsion multibande (bloc Grit, 2026-09-14)
  ["guitar-drive"] = { "JS: guitar/distortion", "JS: Distortion" },
  -- blocs spectraux (docs/spectral.md, 2026-09-25) : CLAP d'abord (le VST3 de PaulXStretch annonce 18 canaux)
  ["spectral-comp"] = { "CLAP: Spectral Compressor (Robbert van der Helm)", "VST3: Spectral Compressor (Robbert van der Helm)", "Spectral Compressor" },
  stretch = { "CLAP: PaulXStretch (Sonosaurus)", "VST3: PaulXStretch (Sonosaurus) (18ch)", "PaulXStretch" },
  freeze  = { "CLAP: GoleM Freeze (GoleM)", "VST3: GoleM Freeze (GoleM)", "GoleM Freeze" },   -- notre gel spectral (lot 1)
  wah         = { "Gxgcb_95", "Gx_gcb_95_", "GxGcb95", "Wah-Wah" },
  ["wah-color"] = { "GxWahwah", "Gx_colwah_", "GxColwah" },
  autowah     = { "GxAutoWah", "Gx_autowah" },
  pitch   = { "ReaPitch" },
  amp     = { "neural_amp_modeler", "Neural Amp Modeler", "NAM" },
  ["amp-nam"] = { "neural_amp_modeler", "Neural Amp Modeler", "NAM" },
  cab     = { "x42 - IR Convolver Mono", "IR Convolver", "zeroconvolv" },
  volume  = { "Volume Adjustment", "JS: Volume Adjustment", "utility/volume" },
  ["clean-boost"] = { "Volume Adjustment", "JS: Volume Adjustment", "utility/volume" },
  vital   = { "VST3i:Vital", "VST3i:Vitalium", "Vitalium" },   -- lane Keys : Vital officiel d'abord, Vitalium en secours (état .vital : vst_chunk en VST3, chunk de piste en LV2 — chunk_set_vitalium)
}

-- ajoute le plugin du bloc ; renvoie (fx_index, nom_plugin_résolu) ou (-1, nil).
-- Réglages posés UNE fois à l'ajout (pas des potards) : neutralise les défauts pièges des plugins.
local FX_INIT = {
  comp   = { ["Auto Make Up Gain"] = 0 },   -- sinon l'auto se bat avec le potard Makeup (ReaComp)
  ["guitar-drive"] = { ["Channel Mode"] = 2 }, -- le JSFX démarre en Left : inséré sur une lane stéréo, il doit traiter les deux canaux
  chorus = { ["Dry Amount"] = 1.0 },        -- insert série : dry unitaire (défaut Calf = 0.5 !)
  -- utility/volume : Adjustment défaut +6 dB ET « Max Volume (dB) » défaut 0 = PLAFOND DUR à
  -- 0 dBFS (clippeur !) -> les deux neutralisés à l'ajout (bug volume 2026-07-23)
  volume = { ["Adjustment (dB)"] = 0, ["Max Volume (dB)"] = 150 },
  ["clean-boost"] = { ["Adjustment (dB)"] = 0, ["Max Volume (dB)"] = 150 },
  -- Surge XT Effects = UN plugin, effet choisi par « FX Type » (valeur brute 1..31) posée à l'ajout
  ["surge-spring"]      = { ["FX Type"] = 27 },   -- Spring Reverb
  ["surge-freqshift"]   = { ["FX Type"] = 7 },    -- Frequency Shifter
  ["surge-treemonster"] = { ["FX Type"] = 24 },   -- Treemonster (mono-synth)
}

-- CONSTAT des plugins (docs/block-status.md §3) : chaque type posé ou refusé pendant CE build.
-- L'inventaire de Reaper prédit, ceci constate — et le constat l'emporte côté bridge. Écrit après
-- materialize dans presets/.rig-plugins.json (fusionné avec les builds précédents).
local _FX_SEEN = {}

local function add_block_fx(track, block, effects)
  local schema = effects[block.type]
  local host_name = tostring(block.plugin or "")
  if block.type == "vst-host" and (not DESKTOP_FX or not (host_name:match("^VST3?i?:") or host_name:match("^CLAPi?:"))) then
    log("  x vst-host : plugin desktop invalide ou absent")
    return -1, nil
  end
  if DESKTOP_FX and schema and schema.unsupported then
    log("  x bloc " .. tostring(block.type) .. " : " .. (MAC_FX and "macOS" or "Windows") .. " : " .. schema.unsupported)
    return -1, nil
  end
  local tried = {}
  local function attempt(nm)
    if not nm or nm == "" or tried[nm] then return nil end
    tried[nm] = true
    local fx = add_fx(track, nm, false, -1)
    if fx and fx >= 0 then return fx, nm end
    return nil
  end
  local hint = block.type == "vst-host" and block.plugin or (schema and schema.plugin)
  local fx, nm = attempt(hint)
  if not fx and block.type ~= "vst-host" and not (DESKTOP_FX and schema and schema.windows_strict) then
    for _, a in ipairs(ADD_ALIAS[block.type] or {}) do fx, nm = attempt(a); if fx then break end end
  end
  if not fx and block.type ~= "vst-host" and not (DESKTOP_FX and schema and schema.windows_strict) then fx, nm = attempt(block.type) end
  if not fx then
    log("  x bloc " .. tostring(block.type) .. " : aucun plugin résolu")
    _FX_SEEN[tostring(block.type)] = { ok = false }
    _MISSING_N = _MISSING_N + 1
    return -1, nil
  end
  _FX_SEEN[tostring(block.type)] = { ok = true, name = nm }
  for pname, pval in pairs((schema and schema.fx_init) or FX_INIT[block.type] or {}) do   -- init one-shot (cf. FX_INIT ; la table de l'OS peut le remplacer)
    local p = find_param_by_name(track, fx, pname)
    if p then reaper.TrackFX_SetParam(track, fx, p, pval) end
  end
  log("  + " .. tostring(block.type) .. " (" .. tostring(nm) .. ") @" .. fx)
  return fx, nm
end

--------------------------------------------------- bloc « pads » (sampler RS5k, lane Keys)
-- Doctrine « tout est bloc » (docs/blocks-doctrine.md) : le bloc pads pose, sur la piste de la lane
-- Keys, UNE instance ReaSamplOmatic5000 note-filtrée PAR pad garni du kit — pas UN plugin mais N.
-- Le bridge (compile_rig) a résolu le kit en b.kit_pads = { {note, file (chemin ABSOLU), mode, level dB} }.
-- Chaque instance est estampillée "pads:<blockid>:<note>" : identifiable au sweep/à l'inspection, et
-- volontairement HORS de l'espace "golem:<id>" -> exclue de la livemap et du réapply de scène (le bloc
-- pads n'a pas de potards live ; son unique param, le kit, est consommé à la compile).
local RS5K_NAMES = { "ReaSamplOmatic5000", "VSTi: ReaSamplOmatic5000 (Cockos)",
                     "VST: ReaSamplOmatic5000 (Cockos)", "VST3i: ReaSamplOmatic5000" }
-- Repli d'index (réf. mpl_RS5k manager, RS5k récent) si le match par NOM de param échoue :
--   0 Volume · 2 Gain for minimum velocity · 3 Note range start · 4 Note range end · 11 Obey note-offs.
local RS5K_IDX = { volume = 0, min_vel_gain = 2, note_start = 3, note_end = 4,
                    pitch_start = 5, pitch_end = 6, obey = 11 }

-- résout un param RS5k par NOM (needle sous-chaîne) sinon repli d'index, et pose une normalisée.
local function rs5k_set_norm(track, fx, needle, idx, norm)
  local p = find_param_by_name(track, fx, needle)
  if not (p and p >= 0) then p = idx end
  reaper.TrackFX_SetParamNormalized(track, fx, p, norm)
end

local function build_pads_block(track, block, effects)
  local pads = block.kit_pads
  if not pads or #pads == 0 then
    log("  ~ pads " .. tostring(block.id) .. " : kit vide (aucune instance RS5k)")
    return
  end
  local placed = 0
  for _, pad in ipairs(pads) do
    local note = tonumber(pad.note)
    if not note or not pad.file then
      log("  x pads : pad ignoré (note/file manquant)")
    else
      local fx
      for _, nm in ipairs(RS5K_NAMES) do
        fx = add_fx(track, nm, false, -1)
        if fx and fx >= 0 then break end
      end
      if not fx or fx < 0 then
        log("  x pads : ReaSamplOmatic5000 introuvable (note " .. note .. ")")
      else
        -- sample : idiome prouvé RS5k -> "FILE0" = chemin (ABSOLU, posé par le bridge) puis "DONE".
        local okf = reaper.TrackFX_SetNamedConfigParm(track, fx, "FILE0", pad.file)
        reaper.TrackFX_SetNamedConfigParm(track, fx, "DONE", "")
        -- note range = EXACTEMENT la note du pad (start == end). Mapping RS5k linéaire 0..127 -> note/127.
        local nn = note / 127
        rs5k_set_norm(track, fx, "Note range start", RS5K_IDX.note_start, nn)
        rs5k_set_norm(track, fx, "Note range end",   RS5K_IDX.note_end,   nn)
        -- mode : gate = obey note-offs ON (relâcher coupe) ; oneshot = OFF (joue jusqu'au bout).
        -- toggle N'EST PAS natif RS5k (aucun param de bascule re-tap) -> repli oneshot, documenté au log.
        local mode = pad.mode or "gate"
        local obey = (mode == "gate") and 1 or 0
        if mode == "toggle" then
          log("  ~ pads note " .. note .. " : mode 'toggle' non natif RS5k -> repli oneshot (obey note-off OFF)")
        end
        rs5k_set_norm(track, fx, "Obey note-off", RS5K_IDX.obey, obey)
        -- ⚠ PIÈGE RS5k : "Pitch for start/end note" ne valent PAS 0 semiton par défaut après un FILE0
        -- (dump : -69 / +59) -> le sample serait TRANSPOSÉ. On force 0 semiton (norm 0.5) : lecture au
        -- pitch d'origine sur toute la plage (ici une seule note, mais on cale les deux bornes).
        rs5k_set_norm(track, fx, "Pitch for start note", RS5K_IDX.pitch_start, 0.5)
        rs5k_set_norm(track, fx, "Pitch for end note",   RS5K_IDX.pitch_end,   0.5)
        -- niveau du sample (dB) : param Volume (= gain à vélocité max), calé par dichotomie sur la valeur
        -- dB affichée (comme les faders ReaDelay). Puis "Gain for minimum velocity" calé sur le MÊME dB
        -- -> réponse PLATE en vélocité (plein régime, pas de velocity layering v1). Même échelle dB que Volume.
        local level = tonumber(pad.level) or 0
        local vp = find_param_by_name(track, fx, "Volume")
        if not (vp and vp >= 0) then vp = RS5K_IDX.volume end
        set_norm_to_target(track, fx, vp, level, -60, 12)
        local mvp = find_param_by_name(track, fx, "Gain for minimum velocity")
        if not (mvp and mvp >= 0) then mvp = RS5K_IDX.min_vel_gain end
        set_norm_to_target(track, fx, mvp, level, -60, 12)
        -- estampille identifiable (sweep/inspection). Hors "golem:<id>" -> pas de collision avec fx_index_by_tag.
        reaper.TrackFX_SetNamedConfigParm(track, fx, "renamed_name",
          "pads:" .. tostring(block.id) .. ":" .. note)
        reaper.TrackFX_SetEnabled(track, fx, not block.bypass)
        placed = placed + 1
        log(string.format("  + pads note %d (%s) mode=%s obey=%d level=%s FILE0=%s @%d",
          note, tostring((pad.file):match("[^/]+$")), mode, obey, tostring(pad.level), tostring(okf), fx))
      end
    end
  end
  log("  pads " .. tostring(block.id) .. " : " .. placed .. " instance(s) RS5k posée(s)")
end

--------------------------------------------------- bloc « organ » (setBfree B3, lane Keys)
-- Doctrine « tout est bloc » : l'orgue = 2 FX chaînés sur la piste Keys :
--   [1] JSFX golem/b3-ctl : injecteur de CC. Ses sliders SONT des params Reaper -> pilotés par le
--       pipeline scène-first EXISTANT (registration/tirettes/leslie par scène GRATUITES).
--   [2] LV2 b_synth (setBfree) : le moteur COMPLET (tonewheels, vibrato, overdrive, Leslie, reverb),
--       SANS aucun port de contrôle : tout arrive en MIDI CC via le JSFX posé DEVANT.
-- Estampille : le JSFX porte le tag STANDARD golem:<id> -> apply_block_params (PHASE B), scène sans
-- rebuild, stomp, livemap EXP le ciblent SANS code spécial (le param « 10: Leslie » compris). Le
-- b_synth est estampillé HORS de l'espace golem: ("organ:<id>:synth") -> invisible au livemap/scène
-- (il n'a aucun potard ; c'est le JSFX qui porte tous les params du bloc).
local B3_CTL_NAMES = { "JS:golem/b3-ctl", "JS:golem/b3-ctl.jsfx", "JS: golem/b3-ctl",
                       "GoleM B3 control (b3-ctl)" }
-- LV2 instrument : Reaper préfixe "LV2i:". doap:name = "setBfree DSP Tonewheel Organ" ; on tente
-- aussi l'URI brute en dernier recours (Reaper l'accepte parfois). Alias possible dans ADD_ALIAS,
-- mais l'orgue n'emprunte PAS add_block_fx (paire de FX) -> résolution locale.
local B3_SYNTH_NAMES = { "LV2i:setBfree DSP Tonewheel Organ", "LV2i: setBfree DSP Tonewheel Organ",
                         "LV2:setBfree DSP Tonewheel Organ", "setBfree DSP Tonewheel Organ",
                         "http://gareus.org/oss/lv2/b_synth" }

local function add_first(track, names)
  for _, nm in ipairs(names) do
    local fx = add_fx(track, nm, false, -1)
    if fx and fx >= 0 then return fx, nm end
  end
  return -1, nil
end

-- knob-tap : JSFX renifleur de CC pose EN TETE de chaine du ROOT de la lane Keys (piste a l'entree
-- MIDI). Publie les CC en gmem golem_knobs -> golem_knobs.lua pilote le param cible (banque A=vital,
-- B=ep). Passthrough MIDI integral -> la Leslie/arp continuent de recevoir leurs CC. Idempotent :
-- ne pose qu'une instance ; la force a l'index 0 (avant le note-zone du 1er instrument mono-lane).
local KNOB_TAP_NAMES = { "JS:golem/knob-tap", "JS: golem/knob-tap",
                         "JS:golem/knob-tap.jsfx", "GoleM knob tap (knob-tap)" }
local function ensure_knob_tap(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do                       -- deja pose ? (scan inline : fx_index_by_name est defini plus bas)
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if nm and nm:lower():find("knob-tap", 1, true) then return end
  end
  local fx = add_first(tr, KNOB_TAP_NAMES)
  if fx < 0 then
    log("  ⚠ knob-tap JSFX introuvable (provision/link-reaper.sh fait ? Reaper relance ?) — potards AKAI inertes")
    return
  end
  if fx > 0 then reaper.TrackFX_CopyToTrack(tr, fx, tr, 0, true) end   -- MOVE en tete (avant note-zone/moteur)
  log("  + knob-tap @0 (renifleur CC AKAI -> gmem golem_knobs)")
end

--------------------------------------------------- drumkit (lane Drums en MIDI, docs/drums-kit.md lot 2)
-- JSFX golem/golem_drumtrans EN TÊTE de la chaîne du bloc (devant le moteur), estampillé golem:<id>,
-- puis le moteur du kit estampillé drumkit:<id> (hors bande, comme l'orgue/les pads : invisible à
-- livemap et à la ré-application de scène). La TABLE module -> kit et la charleston vivent dans gmem
-- golem_drumtrans (un slot de 256 par bloc, slider Slot) : écrites ICI, au build, depuis le plan
-- (bridge : descripteur du port × kit.notes). Lot 2 = moteur avldrums ; un autre moteur est dit.
-- AVL_NAMES : RECOPIE de golem_drums.lua (pas de module Lua partagé : __startup dofile à plat).
local DRUMTRANS_NAMES = { "JS:golem/golem_drumtrans", "JS:golem/golem_drumtrans.jsfx", "JS: golem/golem_drumtrans",
                          "GoleM drum translator (golem_drumtrans)" }
local DRUMKIT_AVL_NAMES = {
  ["black-pearl"]  = { "LV2i:Black Pearl Drumkit (Robin Gareus)", "LV2i: Black Pearl Drumkit (Robin Gareus)",
                       "LV2i:Black Pearl Drumkit", "http://gareus.org/oss/lv2/avldrums#BlackPearl" },
  ["red-zeppelin"] = { "LV2i:Red Zeppelin Drumkit (Robin Gareus)", "LV2i: Red Zeppelin Drumkit (Robin Gareus)",
                       "LV2i:Red Zeppelin Drumkit", "http://gareus.org/oss/lv2/avldrums#RedZeppelin" },
  ["blonde-bop"]   = { "LV2i:Blonde Bop Drumkit (Robin Gareus)", "LV2i: Blonde Bop Drumkit (Robin Gareus)",
                       "LV2i:Blonde Bop Drumkit", "http://gareus.org/oss/lv2/avldrums#BlondeBop" },
}
local DT_STRIDE, DT_CC, DT_OPEN, DT_CLOSED, DT_BA, DT_BB, DT_POS, DT_NCLOSED, DT_NHALF, DT_NOPEN, DT_NONCE, DT_CHAN =
      256, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138

local function write_drumtrans_gmem(block)
  -- ⚠ un seul gmem[] par contexte Lua : on attache NOTRE espace juste avant d'écrire (piège gmem re-attach)
  reaper.gmem_attach("golem_drumtrans")
  local base = (tonumber(block.drum_slot) or 0) * DT_STRIDE
  local map = block.drum_map or {}
  for n = 0, 127 do reaper.gmem_write(base + n, tonumber(map[n + 1]) or -1) end
  local hh = block.drum_hh or {}
  reaper.gmem_write(base + DT_CC,      tonumber(hh.cc) or -1)
  reaper.gmem_write(base + DT_OPEN,    tonumber(hh.open_value) or 0)
  reaper.gmem_write(base + DT_CLOSED,  tonumber(hh.closed_value) or 127)
  reaper.gmem_write(base + DT_BA,      tonumber(hh.band_a) or 33)
  reaper.gmem_write(base + DT_BB,      tonumber(hh.band_b) or 66)
  reaper.gmem_write(base + DT_POS,     tonumber(hh.positions) or 3)
  reaper.gmem_write(base + DT_NCLOSED, tonumber(hh.closed) or -1)
  reaper.gmem_write(base + DT_NHALF,   tonumber(hh.half) or -1)
  reaper.gmem_write(base + DT_NOPEN,   tonumber(hh.open) or -1)
  reaper.gmem_write(base + DT_CHAN,    tonumber(block.drum_chan) or 10)    -- canal attendu du module (témoin)
  reaper.gmem_write(base + DT_NONCE,   (reaper.gmem_read(base + DT_NONCE) or 0) + 1)   -- ≥ 1 = table posée
end

-- le MOTEUR d'un drumkit (estampille hors bande drumkit:<id>) : c'est LUI que le bypass coupe — le
-- traducteur reste toujours actif (revue 2026-09-17, P2 : « drums off » dans une scène coupait le
-- traducteur et laissait le kit jouer les notes BRUTES du module)
-- L'UNION DES KITS (docs/drums-kit.md lot 2 e, 2026-09-23) : un bloc Drum Kit pose UNE PAIRE PAR KIT que
-- ses scènes utilisent — traducteur `drumtrans:<id>:<kit>`, moteur `drumkit:<id>:<kit>`, et pour drumgizmo
-- le mixeur `drumkit-mix:<id>:<kit>`. La scène en ALLUME une et bypass les autres : un traducteur bypassé
-- laisse passer les notes brutes, un moteur bypassé ne sort rien — zéro rebuild entre deux scènes, et
-- Aasimonster (3 Go) charge une fois. Le kit courant est `blk.kit_id` (bakė par scène).
local function drumkit_fx(tr, id)
  local out, pid = {}, tostring(id)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm then
      local kind, kit = nm:match("^(drumtrans):" .. pid:gsub("%W", "%%%0") .. ":(.+)$")
      if not kind then kind, kit = nm:match("^(drumkit):" .. pid:gsub("%W", "%%%0") .. ":(.+)$") end
      if not kind then kind, kit = nm:match("^(drumkit%-mix):" .. pid:gsub("%W", "%%%0") .. ":(.+)$") end
      if kind then out[#out + 1] = { fx = i, kind = kind, kit = kit } end
    end
  end
  return out
end

local function drumkit_engine(tr, id, kit)
  for _, e in ipairs(drumkit_fx(tr, id)) do
    if e.kind == "drumkit" and (kit == nil or e.kit == tostring(kit)) then return e.fx end
  end
  return nil
end

local function set_block_enabled(tr, blk, fxs, engine_fx)
  if blk.type == "drumkit" then
    local want = tostring(blk.kit_id or "")
    local n_on = 0
    for _, e in ipairs(drumkit_fx(tr, blk.id)) do
      local on = (e.kit == want) and not blk.bypass
      reaper.TrackFX_SetEnabled(tr, e.fx, on)
      if on then n_on = n_on + 1 end
    end
    if n_on == 0 and not blk.bypass then log("  ⚠ drumkit " .. tostring(blk.id) .. " : aucune paire pour le kit « " .. want .. " » (rebuild ?)") end
    return
  end
  fx_set_on(tr, engine_fx, not blk.bypass)                      -- un convolveur : son interrupteur interne
end

-- drumgizmo sur une LANE (2026-09-23, « je veux Aasimonster sur mon kit de batterie électronique »).
-- Défini plus bas (il a besoin de write_chunk, qui garde la mémoire P_EXT des lignes fichier) : porté de
-- golem_drums.lua — même XML <config>, même chirurgie de chunk, même mixeur golem_drummix derrière.
local build_drumkit_dg

local function build_drumkit_block(tr, block, root)
  local engines = block.engines
  if not engines or #engines == 0 then engines = { block } end          -- plan d'avant l'union : un seul kit
  local n_pairs = 0
  for _, e in ipairs(engines) do
    local kit = tostring(e.kit_id or "?")
    local active = (e.kit_id == block.kit_id) and not block.bypass
    local fx, nm = add_first(tr, DRUMTRANS_NAMES)
    if fx < 0 then
      log("  ⚠ golem_drumtrans JSFX introuvable (provision/link-reaper.sh fait ? Reaper relancé ?) — "
          .. "bloc " .. tostring(block.id) .. " matérialisé SANS traduction (notes du module envoyées telles quelles)")
    else
      reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "drumtrans:" .. tostring(block.id) .. ":" .. kit)
      local pi = find_param_by_name(tr, fx, "Slot")
      if pi then reaper.TrackFX_SetParam(tr, fx, pi, tonumber(e.drum_slot) or 0) end
      write_drumtrans_gmem({ drum_slot = e.drum_slot, drum_map = e.drum_map, drum_hh = e.drum_hh, drum_chan = e.drum_chan })
      reaper.TrackFX_SetEnabled(tr, fx, active)
      log(string.format("  + golem_drumtrans %s @%d (drumtrans:%s:%s) slot=%s module=%s (canal %s -> sortie canal 10) kit=%s%s", tostring(nm), fx,
          tostring(block.id), kit, tostring(e.drum_slot), tostring(block.drum_desc), tostring(e.drum_chan or 10), kit,
          active and "  [ACTIF]" or "  [bypass : pas le kit de cette scène]"))
      if e.drum_lost and #e.drum_lost > 0 then log("    ~ le kit ne joue pas : " .. table.concat(e.drum_lost, ", ")) end
    end
    if e.kit_engine == "avldrums" then
      local names = DRUMKIT_AVL_NAMES[e.kit_bank or ""]
      if not names then log("  x drumkit " .. tostring(block.id) .. " : banque avldrums inconnue " .. tostring(e.kit_bank))
      else
        local kfx, knm = add_first(tr, names)
        -- CONSTAT (2026-10-03) : sans lui, l'écran disait « ready » d'un kit sans moteur — Windows sans AVL
        -- Drumkits : les notes arrivaient, rien ne sonnait, et le bloc n'était pas barré
        _FX_SEEN[tostring(block.type)] = (kfx >= 0) and { ok = true, name = knm } or { ok = false }
        if kfx < 0 then _MISSING_N = _MISSING_N + 1 end
        if kfx < 0 then log("  x avldrums.lv2 (" .. tostring(e.kit_bank) .. ") introuvable — installé ET Reaper relancé ?")
        else
          reaper.TrackFX_SetNamedConfigParm(tr, kfx, "renamed_name", "drumkit:" .. tostring(block.id) .. ":" .. kit)
          reaper.TrackFX_SetEnabled(tr, kfx, active)
          log(string.format("  + kit avldrums %s @%d (drumkit:%s:%s)", tostring(knm), kfx, tostring(block.id), kit))
          n_pairs = n_pairs + 1
        end
      end
    elseif e.kit_engine == "drumgizmo" then
      if build_drumkit_dg(tr, e, block.id, root, active) then
        n_pairs = n_pairs + 1
        _FX_SEEN[tostring(block.type)] = { ok = true, name = "drumgizmo" }
      else                                               -- même constat qu'avldrums (2026-10-03)
        _FX_SEEN[tostring(block.type)] = { ok = false }
        _MISSING_N = _MISSING_N + 1
      end
    elseif e.kit_engine then
      log("  x drumkit " .. tostring(block.id) .. " : moteur « " .. tostring(e.kit_engine) .. " » pas encore porté sur une lane (avldrums, drumgizmo) — kit " .. kit .. " sans moteur")
    else
      log("  x drumkit " .. tostring(block.id) .. " : aucun kit résolu (params.kit ?) — bloc sans moteur")
    end
  end
  if #engines > 1 then log("  = union des kits : " .. #engines .. " kit(s) posés, actif = " .. tostring(block.kit_id)) end
end

--------------------------------------------------- note-zone (split/layer clavier, lane Keys P2)
-- JSFX golem/note-zone posé EN TÊTE de la chaîne d'un bloc-instrument keys (devant sfizz/b3-ctl/
-- dx7-ctl/Vital). Filtre les notes hors [Zone Low..Zone High] et applique Transpose ; laisse passer
-- CC/pitchbend/aftertouch/SysEx. Estampille STANDARD golem:<id> — PARTAGÉE avec le moteur : le bloc
-- porte alors DEUX FX golem:<id> et la résolution par NOM (resolve_param) route « Zone Low/High/
-- Transpose » vers ce JSFX et les potards moteur (Volume, tirettes…) vers l'autre. Les 3 params de
-- zone sont RAW (0..127 / -24..24) : SetParam = valeur brute directe (sliders JSFX en plage native).
local NOTE_ZONE_NAMES = { "JS:golem/note-zone", "JS:golem/note-zone.jsfx", "JS: golem/note-zone",
                          "GoleM note-zone (note-zone)" }

local function build_note_zone(track, block)
  local fx, nm = add_first(track, NOTE_ZONE_NAMES)
  if fx < 0 then
    log("  ⚠ note-zone JSFX introuvable (provision/link-reaper.sh fait ? Reaper relancé ?) — "
        .. "bloc " .. tostring(block.id) .. " matérialisé SANS filtre de zone (tout le clavier)")
    return -1
  end
  tag_fx(track, fx, block.id)                                    -- golem:<id> partagé avec le moteur
  local p = block.params or {}
  local function setz(name, val)
    local pi = find_param_by_name(track, fx, name)
    if pi then reaper.TrackFX_SetParam(track, fx, pi, val) end
  end
  setz("Zone Low",  tonumber(p.zone_lo) or 0)
  setz("Zone High", tonumber(p.zone_hi) or 127)
  setz("Transpose", tonumber(p.transpose) or 0)
  reaper.TrackFX_SetEnabled(track, fx, true)                     -- le filtre de zone n'est jamais bypassé
  log(string.format("  + note-zone %s @%d (golem:%s) lo=%s hi=%s tr=%s", tostring(nm), fx,
      tostring(block.id), tostring(p.zone_lo or 0), tostring(p.zone_hi or 127), tostring(p.transpose or 0)))
  return fx
end

local function build_organ_block(track, block, effects)
  local ctl, cn = add_first(track, B3_CTL_NAMES)
  if ctl < 0 then
    log("  x organ " .. tostring(block.id) .. " : JSFX b3-ctl introuvable (provision/link-reaper.sh fait ? Reaper relancé ?)")
    return
  end
  local syn, sn = add_first(track, B3_SYNTH_NAMES)
  if syn < 0 then
    log("  x organ " .. tostring(block.id) .. " : LV2 b_synth (setBfree) NON instanciable — "
        .. "Reaper 7.x n'expose pas les LV2 à port MIDI atom:Sequence (setBfree/sfizz/reasonablesynth) ; "
        .. "les LV2 audio (NAM/AIDA-X) et les LV2i à event-port (Calf) passent. Voir réponse agent.")
    reaper.TrackFX_Delete(track, ctl)                            -- pas de moteur -> retire la couche ctl orpheline
    return
  end
  -- ordre : b3-ctl (index ctl) AVANT b_synth (index ctl+1) -> AddByName append les met déjà en ordre.
  -- Le JSFX = le bloc « organ » officiel : estampille standard -> tout le pipeline le cible par golem:<id>.
  tag_fx(track, ctl, block.id)                                   -- renamed_name = golem:<id>
  reaper.TrackFX_SetNamedConfigParm(track, syn, "renamed_name", "organ:" .. tostring(block.id) .. ":synth")
  -- le moteur reste TOUJOURS actif ; « bypass organ » ne coupe que la couche ctl (registration figée,
  -- PAS de silence : pour taire l'orgue -> mute de lane ou tirettes à 0). Limite documentée (P1).
  reaper.TrackFX_SetEnabled(track, syn, true)
  reaper.TrackFX_SetEnabled(track, ctl, not block.bypass)
  log(string.format("  + organ %s : ctl %s @%d (golem:%s) -> synth %s @%d",
      tostring(block.id), tostring(cn), ctl, tostring(block.id), tostring(sn), syn))
end

----------------------------------------------------- CHARGEMENT FICHIER NAM / IR (POINT DUR)
-- Contexte : l'ancien golem BAKAIT les fichiers via un template .RfxChain (chunk <STATE>) car le
-- set runtime était réputé peu fiable. Ici on veut charger par API. STRATÉGIE À DEUX ÉTAGES :
--
--   ÉTAGE 1 — TrackFX_SetNamedConfigParm avec des clés PLAUSIBLES (loguées, jamais fatales).
--     Pour Ratatouille (LV2), le dump .fxdump.json montre les fichiers exposés en params :
--       idx19 "Neural Model A", idx20 "Neural Model B", idx21 "IR File", idx22 "IR File 1".
--     Et le .RfxChain baké écrit l'état LV2 sous forme :
--       S urn:brummer:ratatouille#Neural_Model "<path.nam>" 3
--       S urn:brummer:ratatouille#irfile      "<path.wav>" 3
--     -> on tente d'abord ces URIs LV2 comme clé de SetNamedConfigParm, puis "param.<idx>.file",
--        puis des clés génériques. ⚠ RIEN de tout ça n'est garanti par la doc ReaScript : à valider.
--
--   ÉTAGE 2 — repli PROUVÉ : chirurgie de chunk sur le bloc FX (format identique au .RfxChain baké).
--     Après l'ajout du FX, son bloc LV2 contient déjà un <STATE> avec les lignes S <uri> ... 3.
--     On DÉCOUVRE l'URI du slot À L'EXÉCUTION (on ne l'écrit pas en dur -> marche pour NAM/IR/etc.),
--     et on remplace la valeur par le chemin voulu. Édition minimale (une ligne), depth-safe.
--
-- POURQUOI ÇA PEUT ÉCHOUER (à mettre en tête des points à valider) :
--   - l'étage 1 peut renvoyer true SANS charger (clé avalée génériquement) — on log le retour.
--   - l'étage 2 suppose que le <STATE> du FX fraîchement ajouté LISTE déjà la propriété fichier
--     (Ratatouille le fait ; neural_amp_modeler / ir.lv2 : NON VÉRIFIÉ — si absent, on log l'échec).
--   - l'appariement slot->URI est heuristique (sous-chaîne "model/neural/nam" vs "ir/cab/conv").

local FX_OPEN = { VST = true, LV2 = true, JS = true, AU = true, CLAP = true, DX = true }

----------------------------------------------------------------- fichiers écrits : mémoire, guérison, vérification
-- POURQUOI (2026-09-07, « sur 4 scènes aucune distortion potable ») : le NAM d'Oliphant charge son
-- modèle dans un worker LV2 ASYNCHRONE ; tant qu'il n'a pas fini, sa sauvegarde d'état ne déclare
-- AUCUN modèle. Or une chirurgie de chunk (la pédale posée en tête d'un cœur fraîchement chargé)
-- relit le chunk quelques ms après la pose du cœur, puis le réécrit : l'ampli est ré-instancié avec
-- un <STATE vide et renaît MUET. Mesuré : cœur baké avec le chemin EVH, chunkdump après build =
-- <STATE vide, « Neural Model » = "". La pédale (dernière écrite, jamais relue) et le baffle x42
-- (chargement synchrone) s'en sortaient — d'où « seule la disto manque » — et la REUSE (signature
-- identique) héritait de l'instance vide pour toujours.
-- Remède en trois temps :
--   1. on se souvient SUR LA PISTE (P_EXT, comme la signature) de chaque ligne fichier que NOUS
--      avons écrite, par FXID (les FXID des templates survivent au chargement — vu au chunkdump) ;
--   2. tout chunk relu pour être réécrit est d'abord GUÉRI : une ligne attendue absente est réinjectée ;
--   3. à la REUSE, à la scène et après le settle (golem_watch -> rig_verify), on VÉRIFIE que chaque
--      fichier attendu est réellement chargé — paramètre « Neural Model » / « Impulse Response » lu
--      en clair, le seul fait honnête — sinon REBUILD, à voix haute, et presets/.rig-check.json
--      pour le bridge (puce « ⚠ FX FILE » sur /live).
local FILES_KEY = "P_EXT:golem_files"          -- "fxid\turi\tligne" par ligne
local FILES_T_KEY = "P_EXT:golem_files_t"      -- time_precise de la dernière écriture (fraîcheur)
local FILES_FRESH = 3.0                        -- s : en dessous, un modèle encore en chargement n'est pas une panne

local function is_state_uri(u)                 -- une propriété fichier : URI (# ou ://) d'un P/S dans <STATE
  return u:find("#", 1, true) ~= nil or u:find("://", 1, true) ~= nil
end

-- découpe un chunk (lignes) en blocs FX : {s, e, fxid, state_i, files = {uri = ligne (trim)}}
local function fx_blocks(lines)
  local blocks, i = {}, 1
  while i <= #lines do
    local t = lines[i]:gsub("\r", ""):match("^%s*(.-)%s*$")
    local tag = t:match("^<(%w+)")
    if tag and FX_OPEN[tag] then
      local b = { s = i, files = {} }
      local depth, j, in_state = 1, i + 1, false
      while j <= #lines do
        local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
        if tt:sub(1, 1) == "<" then
          depth = depth + 1
          if depth == 2 and tt:match("^<STATE") then b.state_i = j; in_state = true end
        elseif tt == ">" then
          if in_state and depth == 2 then in_state = false end
          depth = depth - 1
          if depth == 0 then b.e = j; break end
        elseif in_state then
          local uri = tt:match("^[SP]%s+(%S+)%s+")
          if uri and is_state_uri(uri) then b.files[uri] = tt end
        end
        j = j + 1
      end
      if not b.e then break end
      for k = b.e + 1, math.min(#lines, b.e + 3) do    -- FXID suit la fermeture (après FLOATPOS)
        local id = lines[k]:match("FXID%s+(%b{})")
        if id then b.fxid = id; break end
      end
      blocks[#blocks + 1] = b
      i = b.e + 1
    else
      i = i + 1
    end
  end
  return blocks
end

-- ⚠ un P_EXT ne garde qu'UNE ligne (mesuré : une valeur à \n/\t arrivait VIDE, « vérif : 0 piste »)
-- -> la mémoire voyage en hexadécimal, mono-ligne, sûre quel que soit le chemin.
local function hex_enc(s) return (s:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end
local function hex_dec(s) return (s:gsub("%x%x", function(h) return string.char(tonumber(h, 16)) end)) end
local function ext_get(tr, key)
  local _, s = reaper.GetSetMediaTrackInfo_String(tr, key, "", false)
  return hex_dec(s or "")
end
local function ext_set(tr, key, s)
  reaper.GetSetMediaTrackInfo_String(tr, key, s == "" and "" or hex_enc(s), true)
end

local function files_mem(tr)
  local s = ext_get(tr, FILES_KEY)
  local mem = {}
  for fxid, uri, line in s:gmatch("([^\t\n]+)\t([^\t\n]+)\t([^\n]+)") do
    mem[fxid] = mem[fxid] or {}; mem[fxid][uri] = line
  end
  return mem
end
local function files_mem_set(tr, mem)
  local out = {}
  for fxid, m in pairs(mem) do for uri, line in pairs(m) do out[#out + 1] = fxid .. "\t" .. uri .. "\t" .. line end end
  table.sort(out)
  ext_set(tr, FILES_KEY, table.concat(out, "\n"))
  reaper.GetSetMediaTrackInfo_String(tr, FILES_T_KEY, tostring(reaper.time_precise()), true)
  if #out > 0 then log("    (mémoire) " .. #out .. " ligne(s) fichier retenue(s) sur la piste") end
end
local function files_forget(tr)
  ext_set(tr, FILES_KEY, "")
end

local function file_of_line(line)                       -- « P <uri> <valeur> 3 » -> valeur (déquotée)
  local v = line:match("^[SP]%s+%S+%s+(.-)%s+%d+$") or ""
  return (v:gsub('^"(.*)"$', "%1"))
end

-- écrit le chunk ET retient les lignes fichier qu'il porte. FUSION : ce qu'on écrit gagne, le reste
-- survit — un bloc dont le <STATE est momentanément vide n'est PAS oublié, c'est précisément le bug.
-- Un FXID absent du chunk (FX supprimé, ou FXID volontairement retiré pour ré-instancier) est oublié.
local function write_chunk(tr, lines)
  local mem, seen = files_mem(tr), {}
  for _, b in ipairs(fx_blocks(lines)) do
    if b.fxid then
      seen[b.fxid] = true
      for uri, line in pairs(b.files) do mem[b.fxid] = mem[b.fxid] or {}; mem[b.fxid][uri] = line end
    end
  end
  for fxid in pairs(mem) do if not seen[fxid] then mem[fxid] = nil end end
  -- ⚠ la mémoire s'écrit APRÈS le chunk : SetTrackStateChunk remplace TOUT le chunk de la piste,
  -- P_EXT compris — posée avant, elle était effacée par l'écriture même qu'elle devait protéger
  -- (mesuré : « 1 ligne retenue » à la chirurgie au lieu de 3, « vérif : 0 piste »).
  -- ses FX sont des instances NEUVES (même FXID) : plugin_window le lit, PAR PISTE (une réécriture ailleurs ne
  -- ferme pas une fenêtre ouverte ici)
  GOLEM_CHUNK_GEN = GOLEM_CHUNK_GEN or {}
  local tg = reaper.GetTrackGUID(tr)
  GOLEM_CHUNK_GEN[tg] = (GOLEM_CHUNK_GEN[tg] or 0) + 1
  local ok = reaper.SetTrackStateChunk(tr, table.concat(lines, "\n"), false)
  files_mem_set(tr, mem)
  return ok
end

-- ── drumgizmo sur une lane : état LV2 (XML base64 dans le chunk), 16 canaux, mixeur ──────────────
-- Porté de golem_drums.lua (pas de module Lua partagé : __startup dofile à plat). Ce plugin n'a NI
-- paramètre NI clé SetNamedConfigParm pour son kit : le chemin vit dans l'état LV2, une chaîne XML
-- <config> sous la propriété atom#config, que Reaper sérialise en base64 dans le chunk. On fabrique
-- le XML, on remplace le bloc <X, on DROP le FXID (ré-instanciation -> relecture de l'état), et on
-- écrit par write_chunk : la mémoire P_EXT des lignes fichier des autres blocs survit à l'écriture.
local DG_NAMES = { "LV2i: DrumGizmo (DrumGizmo Team) (16 out)", "LV2i:DrumGizmo (DrumGizmo Team) (16 out)",
                   "LV2i: DrumGizmo (DrumGizmo Team)", "LV2i:DrumGizmo", "http://drumgizmo.org/lv2" }
local DG_URI, DG_ATOM, DG_NCH = "http://drumgizmo.org/lv2/atom#config", "http://lv2plug.in/ns/ext/atom#Chunk", 16
local DRUMMIX_NAMES = { "JS:golem/golem_drummix", "JS: golem/golem_drummix", "GoleM drum mixer (drummix)", "golem_drummix" }
local B64C = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function b64(data)
  local out, n = {}, #data
  for i = 1, n, 3 do
    local a, b, c = data:byte(i, i + 2)
    local v = a * 65536 + (b or 0) * 256 + (c or 0)
    out[#out + 1] = B64C:sub(math.floor(v / 262144) % 64 + 1, math.floor(v / 262144) % 64 + 1)
                 .. B64C:sub(math.floor(v / 4096) % 64 + 1, math.floor(v / 4096) % 64 + 1)
                 .. (b and B64C:sub(math.floor(v / 64) % 64 + 1, math.floor(v / 64) % 64 + 1) or "=")
                 .. (c and B64C:sub(v % 64 + 1, v % 64 + 1) or "=")
  end
  return table.concat(out)
end

-- REAPER wraps the VST3 state as <payload size:uint32><type:uint32=1>
-- <plug-in state><8-byte trailer>. NAM's state starts with four length-prefixed
-- strings (magic, version, model, IR), followed by its parameters. Preserve
-- REAPER's wrapper and NAM's parameter tail when replacing the two paths.
local function unb64(encoded)
  if type(encoded) == "string" then encoded = encoded:gsub("%s+", "") end
  if type(encoded) ~= "string" or #encoded % 4 ~= 0 or encoded:find("[^%w%+/%=]") then return nil end
  local out = {}
  for i = 1, #encoded, 4 do
    local a, b, c, d = encoded:sub(i, i + 3):byte(1, 4)
    local function digit(x)
      if x >= 65 and x <= 90 then return x - 65 end
      if x >= 97 and x <= 122 then return x - 97 + 26 end
      if x >= 48 and x <= 57 then return x - 48 + 52 end
      if x == 43 then return 62 elseif x == 47 then return 63 end
      return nil
    end
    local da, db, dc, dd = digit(a), digit(b), c == 61 and 0 or digit(c), d == 61 and 0 or digit(d)
    if not da or not db or dc == nil or dd == nil then return nil end
    local n = da * 262144 + db * 4096 + dc * 64 + dd
    out[#out + 1] = string.char(math.floor(n / 65536) % 256)
    if c ~= 61 then out[#out + 1] = string.char(math.floor(n / 256) % 256) end
    if d ~= 61 then out[#out + 1] = string.char(n % 256) end
  end
  return table.concat(out)
end

local function nam_state_with_files(encoded, model, ir)
  local data = unb64(encoded)
  if not data then return nil, "vst_chunk base64 invalide" end
  if #data < 16 then return nil, "état VST3 tronqué" end
  local size, kind = string.unpack("<I4I4", data)
  if kind ~= 1 or size ~= #data - 16 then return nil, "enveloppe VST3 inattendue" end
  local prefix, suffix = data:sub(5, 8), data:sub(9 + size)
  data = data:sub(9, 8 + size)
  local fields, pos = {}, 1
  for i = 1, 4 do
    if pos + 3 > #data then return nil, "état NAM tronqué" end
    local len; len, pos = string.unpack("<I4", data, pos)
    if len > #data - pos + 1 then return nil, "longueur NAM invalide" end
    fields[i] = data:sub(pos, pos + len - 1)
    pos = pos + len
  end
  if fields[1] ~= "###NeuralAmpModeler###" then return nil, "plugin NAM officiel attendu" end
  -- 0.7.15 (build golem du tag amont, 2026-10-22) : même en-tête (magie, version, modèle, IR), un paramètre de
  -- plus en queue (« Slim », la taille d'une capture A2) — la chirurgie ne touche que les deux chemins
  if fields[2] ~= "0.7.13" and fields[2] ~= "0.7.15" and fields[2] ~= "0.8.0" then
    return nil, "version NAM non qualifiée : " .. tostring(fields[2])
  end
  local function packstr(s) return string.pack("<I4", #s) .. s end
  local payload = packstr(fields[1]) .. packstr(fields[2]) .. packstr(model or "") ..
                  packstr(ir or "") .. data:sub(pos)
  return b64(string.pack("<I4", #payload) .. prefix .. payload .. suffix)
end

-- ── Le NAM VST3 officiel, réglé COMME le NAM LV2 du rack Linux (mesuré le 2026-10-01) ──────────
-- docs/audit-2026-10-01-parite-coeurs-os.md : le LV2 d'Oliphant étalonne TOUJOURS l'entrée (carte
-- supposée à 12 dBu, contre `input_level_dbu` de la capture) et normalise la sortie (`loudness`).
-- Le VST3 en « Raw / sans étalonnage » donnait +1,3 dB et une AUTRE saturation (nul -5 dB) ; réglé
-- ainsi, même niveau à 0,01 dB et même timbre à 0,06 dB par tiers d'octave.
-- Et le VST3 applique -18 dB FIXES à toute IR (AudioDSPTools ImpulseResponse::_SetWeights, loi
-- 48000/fréquence), le convolveur x42 du rack aucun : l'instance IR seule prend +18 dB à 48 kHz.
-- ⚠ Seul 48 kHz est mesuré ; la compensation suit la loi du VST3 aux autres fréquences, non mesurée.
local NAM_CALIBRATION_DBU = 12

-- « Slim » (NAM 0.7.14+) : la taille à laquelle une capture A2 (SlimmableContainer) joue, 0 = la plus petite,
-- 1 = la capture entière. Le défaut d'une instance NEUVE est 0 : sans ce réglage une A2 jouerait sa version la
-- plus légère. Le rack Linux joue la capture entière. Absent en 0.7.13 (pas d'A2) : rien à régler.
function set_nam_slim(tr, fx)
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if name == "Slim" then reaper.TrackFX_SetParam(tr, fx, p, 1.0) return true end
  end
  return false
end
local function nam_ir_comp_db()
  local ok, rate = reaper.GetAudioDeviceInfo("SRATE", "")
  local sr = ok and tonumber(rate) or 48000
  if not sr or sr <= 0 then sr = 48000 end
  return 18 + 20 * math.log(sr / 48000, 10)
end
NAM_IR_COMP_DB = nil   -- lu par apply_core_params et la livemap, posé au premier cœur natif

-- ⚠ TrackFX_SetParam prend une valeur NORMALISÉE 0-1 sur ce VST3, pas la valeur native : écrire 12
-- dans InputCalibrationLevel posait 60 dBu, écrire 1 dans OutputMode posait « Calibrated » (mesuré
-- le 2026-10-01). Un interrupteur se règle à 0/1 ; le reste se vise par sa valeur AFFICHÉE.
local function set_param_shown(tr, fx, p, target)
  if type(target) == "string" then                       -- énumération : on balaie jusqu'au libellé
    for i = 0, 100 do
      reaper.TrackFX_SetParamNormalized(tr, fx, p, i / 100)
      local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
      if s == target then return true end
    end
    return false
  end
  local lo, hi = 0.0, 1.0                                -- continu et croissant : dichotomie
  for _ = 1, 40 do
    local mid = (lo + hi) / 2
    reaper.TrackFX_SetParamNormalized(tr, fx, p, mid)
    local _, s = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
    if (tonumber(s:match("[-%d%.]+")) or 0) < target then lo = mid else hi = mid end
  end
  reaper.TrackFX_SetParamNormalized(tr, fx, p, hi)
  return true
end

local function load_native_core(tr, files)
  NAM_IR_COMP_DB = NAM_IR_COMP_DB or nam_ir_comp_db()
  local function add_one(model, ir, id)
    local path = model ~= "" and model or ir
    local file = io.open(path, "rb")
    if not file then log("  ⚠ NAM VST3 : fichier introuvable " .. tostring(path)); return false end
    file:close()
    local fx = add_fx(tr, "VST3: NeuralAmpModeler", false,
                                       -1000 - reaper.TrackFX_GetCount(tr))
    if not fx or fx < 0 then log("  ⚠ NAM VST3 officiel absent ; cœur audio non chargé"); return false end
    local ok, state = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
    if not ok then log("  ⚠ NAM VST3 : lecture vst_chunk refusée"); return false end
    local changed, err = nam_state_with_files(state, model, ir)
    if not changed then log("  ⚠ NAM VST3 : " .. err); return false end
    if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", changed) then
      log("  ⚠ NAM VST3 : écriture vst_chunk refusée"); return false
    end
    -- interrupteurs (0/1) puis réglages visés par leur valeur affichée — cf. set_param_shown
    local wanted = { NoiseGateActive = 0, ToneStack = 0, CalibrateInput = 1,
                     IRToggle = ir ~= "" and 1 or 0 }
    local shown = { OutputMode = "Normalized", InputCalibrationLevel = NAM_CALIBRATION_DBU }
    if model == "" then shown.Output = NAM_IR_COMP_DB end   -- instance IR seule (apply_core_params y ajoute `level`)
    local seen = {}
    for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
      local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
      if wanted[name] ~= nil then
        reaper.TrackFX_SetParam(tr, fx, p, wanted[name]); seen[name] = true
      elseif shown[name] ~= nil then
        if not set_param_shown(tr, fx, p, shown[name]) then
          log("  ⚠ NAM VST3 : valeur introuvable " .. name .. " = " .. tostring(shown[name])); return false
        end
        seen[name] = true
      end
    end
    for _, t in ipairs({ wanted, shown }) do
      for name in pairs(t) do
        if not seen[name] then log("  ⚠ NAM VST3 : paramètre absent " .. name); return false end
      end
    end
    set_nam_slim(tr, fx)
    if id then tag_fx(tr, fx, id) end
    log("  NAM VST3 : modèle=" .. tostring(model) .. " IR=" .. tostring(ir))
    return true
  end
  if files.model ~= "" and not add_one(files.model, "", files.amp_id) then return false end
  if files.ir ~= "" and not add_one("", files.ir, files.cab_id or "core-default-ir") then return false end
  return files.model ~= "" or files.ir ~= ""
end

-- Les pédales NAM Windows utilisent le même état VST3 officiel que le cœur natif.
local function load_windows_nam_block(tr, fx, file)
  local handle = file and io.open(file, "rb")
  if not handle then log("  x NAM VST3 : modèle introuvable " .. tostring(file)); return false end
  handle:close()
  local ok, state = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
  if not ok then log("  x NAM VST3 : lecture vst_chunk refusée"); return false end
  local changed, err = nam_state_with_files(state, file, "")
  if not changed then log("  x NAM VST3 : " .. tostring(err)); return false end
  if not reaper.TrackFX_SetNamedConfigParm(tr, fx, "vst_chunk", changed) then
    log("  x NAM VST3 : écriture vst_chunk refusée"); return false
  end
  local wanted = { NoiseGateActive = 0, ToneStack = 0, OutputMode = 0, IRToggle = 0 }
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if wanted[name] ~= nil then reaper.TrackFX_SetParam(tr, fx, p, wanted[name]); wanted[name] = nil end
  end
  for name in pairs(wanted) do log("  x NAM VST3 : paramètre absent " .. name); return false end
  set_nam_slim(tr, fx)
  log("  NAM VST3 : modèle=" .. tostring(file))
  return true
end

-- le XML COMPLET (drumgizmo réécrit tout son état : un <config> amputé le laisse sur ses défauts
-- internes) — valeurs relevées sur une instance fraîche, trois assumées : disk_cache_enable (3 Go
-- streamés depuis le disque), enable_bleed_control (la diaphonie EST l'intérêt du kit), enable_resampling
-- (kit en 44,1 kHz, rig à 48).
local function dg_config_xml(kitfile, midimap, bleed)
  local v = {
    drumkitfile = kitfile, midimapfile = midimap,
    enable_velocity_modifier = "true", velocity_modifier_falloff = "0.500000",
    velocity_modifier_weight = "0.250000", velocity_stddev = "0.450000",
    sample_selection_f_close = "0.850000", sample_selection_f_diverse = "0.160000",
    sample_selection_f_random = "0.070000", enable_velocity_randomiser = "false",
    velocity_randomiser_weight = "0.100000", enable_resampling = "true",
    resampling_quality = "0.700000", disk_cache_upper_limit = "1073741824",
    disk_cache_chunk_size = "1048576", disk_cache_enable = "true",
    enable_bleed_control = "true", master_bleed = string.format("%f", bleed or 1.0),
    enable_latency_modifier = "false", latency_laid_back_ms = "0.000000",
    latency_stddev = "2.000000", latency_regain = "0.900000",
    enable_powermap = "false", powermap_fixed0_x = "0.000000", powermap_fixed0_y = "0.000000",
    powermap_fixed1_x = "0.500000", powermap_fixed1_y = "0.500000",
    powermap_fixed2_x = "1.000000", powermap_fixed2_y = "1.000000", powermap_shelf = "true",
    enable_voice_limit = "false", voice_limit_max = "15", voice_limit_rampdown = "0.500000",
  }
  local order = { "drumkitfile", "midimapfile", "enable_velocity_modifier",
    "velocity_modifier_falloff", "velocity_modifier_weight", "velocity_stddev",
    "sample_selection_f_close", "sample_selection_f_diverse", "sample_selection_f_random",
    "enable_velocity_randomiser", "velocity_randomiser_weight", "enable_resampling",
    "resampling_quality", "disk_cache_upper_limit", "disk_cache_chunk_size", "disk_cache_enable",
    "enable_bleed_control", "master_bleed", "enable_latency_modifier", "latency_laid_back_ms",
    "latency_stddev", "latency_regain", "enable_powermap", "powermap_fixed0_x", "powermap_fixed0_y",
    "powermap_fixed1_x", "powermap_fixed1_y", "powermap_fixed2_x", "powermap_fixed2_y",
    "powermap_shelf", "enable_voice_limit", "voice_limit_max", "voice_limit_rampdown" }
  local t = { '<config version="1.0">' }
  for _, k in ipairs(order) do t[#t + 1] = '  <value name="' .. k .. '">' .. tostring(v[k] or "") .. "</value>" end
  t[#t + 1] = "</config>"
  return table.concat(t, "\n") .. "\n"
end

-- remplace (ou crée) le bloc <X atom#config du FX `fx` par l'état encodé, DROP le FXID, écrit par write_chunk.
local function chunk_set_dgconfig(tr, fx, xml)
  local ok, chunk = reaper.GetTrackStateChunk(tr, "", false)
  if not ok then return false end
  local lines = {}
  for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
  local idx, start_i, end_i, i = -1, nil, nil, 1
  while i <= #lines do
    local t = lines[i]:gsub("\r", ""):match("^%s*(.-)%s*$")
    local tag = t:match("^<(%w+)")
    if tag and FX_OPEN[tag] then
      idx = idx + 1
      if idx == fx then
        start_i = i
        local depth, j = 1, i + 1
        while j <= #lines do
          local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
          if tt:sub(1, 1) == "<" then depth = depth + 1
          elseif tt == ">" then depth = depth - 1; if depth == 0 then end_i = j; break end end
          j = j + 1
        end
        break
      end
    end
    i = i + 1
  end
  if not (start_i and end_i) then log("  x (drumgizmo) bloc FX #" .. tostring(fx) .. " introuvable dans le chunk"); return false end
  local enc = b64(xml)
  local body = { "<X " .. DG_URI .. " " .. DG_ATOM .. " 3" }
  for p = 1, #enc, 280 do body[#body + 1] = enc:sub(p, p + 279) end
  body[#body + 1] = ">"
  local x_start, x_end
  for k = start_i, end_i do
    local t = lines[k]:gsub("\r", ""):match("^%s*(.-)%s*$")
    if not x_start and t:find("^<X " .. DG_URI, 1, false) then x_start = k end
    if x_start and k > x_start and t == ">" then x_end = k; break end
  end
  if x_start and x_end then
    for k = x_end, x_start, -1 do table.remove(lines, k) end
    for k = #body, 1, -1 do table.insert(lines, x_start, body[k]) end
    end_i = end_i - (x_end - x_start + 1) + #body
  else
    local ins = end_i
    table.insert(lines, ins, "<STATE")
    for k = 1, #body do table.insert(lines, ins + k, body[k]) end
    table.insert(lines, ins + #body + 1, ">")
    end_i = end_i + #body + 2
  end
  if lines[end_i + 1] and lines[end_i + 1]:match("FXID") then table.remove(lines, end_i + 1) end
  return write_chunk(tr, lines)
end

build_drumkit_dg = function(tr, block, bid, root, active)
  local kit = tostring(block.kit_id or "?")
  if not (block.kit_drumkit and block.kit_midimap) then log("  x drumkit " .. tostring(bid) .. " : kit drumgizmo sans drumkit/midimap"); return false end
  local kit_abs, map_abs = root .. "/" .. block.kit_drumkit, root .. "/" .. block.kit_midimap
  if not read_file(kit_abs) then log("  x drumkit introuvable : " .. block.kit_drumkit); return false end
  if not read_file(map_abs) then log("  x midimap introuvable : " .. block.kit_midimap); return false end
  -- la piste PASSE à 16 canaux : un micro par sortie ; les canaux 1/2 seuls = les overheads. Le routage
  -- de sortie respecte ce compte (wants_nchan) — le send hardware lit 1/2, où drummix a sommé.
  reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", DG_NCH)
  local fx, nm = add_first(tr, DG_NAMES)
  if fx < 0 then log("  x drumgizmo.lv2 introuvable — installé ET Reaper relancé ?"); return false end
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "drumkit:" .. tostring(bid) .. ":" .. kit)
  if chunk_set_dgconfig(tr, fx, dg_config_xml(kit_abs, map_abs, block.kit_bleed)) then
    log(string.format("  + kit drumgizmo %s (drumkit:%s:%s) -> %s  [3 Go streamés : le kit sonne quand il a fini de charger]%s",
        tostring(nm), tostring(bid), kit, tostring(block.kit_drumkit), active and "" or "  [bypass : pas le kit de cette scène]"))
  else
    log("  x kit drumgizmo : échec du patch atom#config")
  end
  fx = drumkit_engine(tr, bid, kit) or fx                      -- ré-instancié par le chunk : index re-résolu par l'estampille
  reaper.TrackFX_SetEnabled(tr, fx, active)
  local mx = add_first(tr, DRUMMIX_NAMES)                      -- 16 -> 2 APRÈS le plugin, sinon on n'entend que les overheads
  if mx < 0 then log("  x golem_drummix introuvable (link-reaper.sh fait ?) — sortie = overheads SEULS"); return true end
  reaper.TrackFX_SetNamedConfigParm(tr, mx, "renamed_name", "drumkit-mix:" .. tostring(bid) .. ":" .. kit)
  local n = 0
  for _, m in ipairs(block.kit_mix or {}) do
    local ch = tonumber(m.ch)
    if ch and ch >= 1 and ch <= DG_NCH then
      reaper.TrackFX_SetParam(tr, mx, (ch - 1) * 2,     tonumber(m.gain) or 0)
      reaper.TrackFX_SetParam(tr, mx, (ch - 1) * 2 + 1, tonumber(m.pan) or 0)
      n = n + 1
    end
  end
  reaper.TrackFX_SetEnabled(tr, mx, active)
  log("  + mixeur drummix (drumkit-mix:" .. tostring(bid) .. ":" .. kit .. ") : " .. n .. " micros posés")
  return true
end

-- réinjecte, dans un chunk RELU, les lignes fichier attendues qui manquent. Renvoie le nombre guéri.
local function heal_files(tr, lines)
  local mem = files_mem(tr)
  if next(mem) == nil then return 0 end
  local blocks, healed = fx_blocks(lines), 0
  for bi = #blocks, 1, -1 do        -- de la fin vers le début : une insertion ne décale pas les blocs précédents
    local b = blocks[bi]
    local want = b.fxid and mem[b.fxid]
    if want then
      local missing = {}
      for uri, line in pairs(want) do if not b.files[uri] then missing[#missing + 1] = line end end
      table.sort(missing)
      if #missing > 0 then
        local at
        if b.state_i then at = b.state_i + 1
        else table.insert(lines, b.e, "<STATE"); table.insert(lines, b.e + 1, ">"); at = b.e + 1 end
        for k = #missing, 1, -1 do table.insert(lines, at, "    " .. missing[k]) end
        healed = healed + #missing
        for _, line in ipairs(missing) do
          local f = file_of_line(line)
          log("    (guérison) FX " .. b.fxid .. " avait PERDU sa ligne fichier -> réinjectée : " .. (f:match("[^/]+$") or f))
        end
      end
    end
  end
  return healed
end

-- « le fichier attendu est-il réellement chargé ? » — lu EN CLAIR sur le plugin (paramètre
-- Neural Model / Impulse Response, valeur formatée), car le chunk peut mentir pendant un chargement.
-- Renvoie {fx, fxid, uri, kind, expected}. Non strict : ne juge pas une écriture trop fraîche
-- (worker encore au travail).
local function files_issues(tr, strict)
  local mem = files_mem(tr)
  if next(mem) == nil then return {} end
  if not strict then
    local _, ts = reaper.GetSetMediaTrackInfo_String(tr, FILES_T_KEY, "", false)
    local t0 = tonumber(ts)
    local age = t0 and (reaper.time_precise() - t0)
    -- âge NÉGATIF = heure d'une autre session (time_precise repart à chaque lancement) : pas une
    -- écriture fraîche — sinon chaque vérification répondait « rien à signaler » (2026-10-05)
    if age and age >= 0 and age < FILES_FRESH then return {} end
  end
  local by_guid = {}
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do by_guid[reaper.TrackFX_GetFXGUID(tr, i)] = i end
  local issues = {}
  for fxid, m in pairs(mem) do
    local fx = by_guid[fxid]
    if fx then
      for uri, line in pairs(m) do
        local val, lu = file_of_line(line), uri:lower()
        local kind = (lu:find("#ir", 1, true) or lu:find("irfile", 1, true)) and "ir"
                     or ((lu:find("model", 1, true) or lu:find("neural", 1, true)) and "model") or nil
        if kind and val ~= "" and val ~= "None" then
          local got
          for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
            local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
            local pl = (pn or ""):lower()
            if (kind == "model" and pl:find("model", 1, true))
               or (kind == "ir" and (pl:find("impulse", 1, true) or pl:find("ir file", 1, true))) then
              local _, d = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
              got = d or ""
              break
            end
          end
          if got == "" then                        -- nil = le plugin n'expose pas le fichier (sfizz) : pas jugé
            issues[#issues + 1] = { fx = fx, fxid = fxid, uri = uri, kind = kind, expected = val:match("[^/]+$") or val }
          end
        end
      end
    end
  end
  table.sort(issues, function(a, b) return a.fx < b.fx end)
  return issues
end

local function jstr(s)
  return '"' .. tostring(s):gsub('[%c"\\]', function(c) return string.format("\\u%04x", c:byte()) end) .. '"'
end

-- passe de VÉRIFICATION différée (golem_watch, ~2 s après un recall, quand les workers ont fini) :
-- lit en clair ce que chaque plugin a chargé ; si une ligne a été perdue par le chunk, la réinjecte
-- UNE fois (le plugin recharge) ; écrit presets/.rig-check.json pour le bridge. Jamais de chirurgie
-- pendant une prise. Une réparation demande une seconde passe (ExtState rig_verify_retry).
local function verify_files(root, second)
  local issues, checked, repaired = {}, 0, false
  -- CHARGEMENT ENCORE EN COURS ? (Paper Kite, branche B, 2026-10-08→11 : « la ligne est là, le plugin ne charge
  -- pas ce fichier » à chaque rappel, puis les deux modèles chargés à la sonde le 2026-10-12, sans changement de
  -- code). La branche réécrite EN DERNIER recharge ses NAM dans le worker LV2 au moment où cette passe lit
  -- « Neural Model » : une lecture vide n'est pas encore un fichier refusé. Première passe : pas de verdict sur ce
  -- cas, une seconde lecture (golem_watch, +2 s) conclut.
  local waiting = false
  local recording = (reaper.GetPlayState() & 4) ~= 0
  -- réparer = réécrire le chunk = ré-instancier la lane : seulement juste après un rebuild (golem_watch le dit),
  -- jamais après une simple scène, en plein morceau (audit 2026-10-15, R1) — là, on SIGNALE (⚠ FX FILE)
  local may_heal = not recording and reaper.GetExtState("golem", "rig_verify_heal") == "1"
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    if core_failed(tr) then
      checked = checked + 1
      issues[#issues + 1] = { track = track_name(tr), fx = -1, kind = "native_core",
                             expected = "NAM VST3 0.7.13/0.8.0 et fichiers audio", repaired = false }
    end
    local mem = ext_get(tr, FILES_KEY)
    if mem ~= "" then
      checked = checked + 1
      local iss = files_issues(tr, true)
      if #iss > 0 then
        local n = 0
        if may_heal then
          local ok, chunk = reaper.GetTrackStateChunk(tr, "", false)
          if ok then
            local lines = {}
            for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
            n = heal_files(tr, lines)
            if n > 0 then write_chunk(tr, lines); repaired = true end
          end
        end
        if n == 0 and not recording and not second then
          waiting = true
          log("  vérif " .. track_name(tr) .. " : " .. #iss .. " fichier(s) pas encore lu(s) par le plugin -> seconde lecture dans 2 s")
          iss = {}
        end
        for _, is in ipairs(iss) do
          is.track = track_name(tr); is.repaired = (n > 0)
          issues[#issues + 1] = is
          log("⚠ VÉRIF " .. is.track .. " FX#" .. is.fx .. " (" .. is.kind .. ") attendu « " .. is.expected .. " », chargé « » "
              .. (n > 0 and "-> ligne réinjectée, rechargement" or (recording and "-> prise en cours, pas de chirurgie"
                  or (not may_heal and "-> après une scène : signalé, réparé au prochain rappel du preset"
                  or "-> la ligne est là, le plugin ne charge pas ce fichier"))))
        end
      end
    end
  end
  if waiting and #issues == 0 then                              -- rien d'autre à dire : le verdict attend la seconde passe
    reaper.SetExtState("golem", "rig_verify_retry", "1", false)
    log(string.format("vérif fichiers : %d piste(s), verdict à la seconde lecture", checked))
    return
  end
  if waiting then repaired = true end                           -- la seconde passe relira aussi ces pistes-là
  local parts = {}
  for _, is in ipairs(issues) do
    parts[#parts + 1] = string.format('{"track":%s,"fx":%d,"kind":%s,"expected":%s,"repaired":%s}',
      jstr(is.track), is.fx, jstr(is.kind), jstr(is.expected), tostring(is.repaired))
  end
  local body = string.format('{"t":%d,"ok":%s,"checked":%d,"issues":[%s]}', os.time(), tostring(#issues == 0), checked, table.concat(parts, ","))
  local path = root .. "/presets/.rig-check.json"
  local f = io.open(path .. ".tmp", "w")
  if f then f:write(body); f:close(); runtime.replace(path .. ".tmp", path) end
  if repaired then reaper.SetExtState("golem", "rig_verify_retry", "1", false) end
  log(string.format("vérif fichiers : %d piste(s), %d manque(s)%s", checked, #issues, repaired and ", réparé -> seconde passe" or ""))
end

-- étage 2 : réécrit la valeur de la ligne S du slot dans le bloc FX numéro `fx`.
local function chunk_set_lv2_file(track, fx, slot, file)
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
  heal_files(track, lines)                       -- une ligne fichier perdue par un chargement async est remise AVANT la réécriture

  -- localise le fx-ième bloc FX (compte les balises d'ouverture de plugin dans l'ordre)
  local idx, start_i, end_i = -1, nil, nil
  local i = 1
  while i <= #lines do
    local t = lines[i]:gsub("\r", ""):match("^%s*(.-)%s*$")
    local tag = t:match("^<(%w+)")
    if tag and FX_OPEN[tag] then
      idx = idx + 1
      if idx == fx then
        start_i = i
        local depth, j = 1, i + 1
        while j <= #lines do
          local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
          if tt:sub(1, 1) == "<" then depth = depth + 1
          elseif tt == ">" then depth = depth - 1; if depth == 0 then end_i = j; break end end
          j = j + 1
        end
        break
      end
    end
    i = i + 1
  end
  if not (start_i and end_i) then
    log("    (chirurgie) bloc FX #" .. tostring(fx) .. " INTROUVABLE (idx max=" .. tostring(idx) .. ")")
    return false
  end

  local want_ir = (slot == "ir")
  for k = start_i, end_i do
    local raw = lines[k]:gsub("\r", "")
    -- S = état LV2, P = propriété patch (le NAM Oliphant expose #model en ligne P !)
    local ws, typ, uri = raw:match("^(%s*)([SP])%s+(%S+)%s+")
    if uri then
      local u = uri:lower()
      local is_ir = u:find("ir") or u:find("cab") or u:find("conv")
      local is_model = u:find("model") or u:find("neural") or u:find("nam")
      local hit = (want_ir and is_ir) or ((not want_ir) and is_model and not is_ir)
      if hit and not uri:match("1$") then                 -- primaire (évite …Model1 / …irfile1)
        lines[k] = ws .. typ .. " " .. uri .. ' "' .. file .. '" 3'
        return write_chunk(track, lines)
      end
    end
  end
  -- instance FRAÎCHE sans ligne de modèle (NAM ajouté par AddByName, ex. bloc pedal-nam) :
  -- on INSÈRE la ligne P DANS le sous-bloc <STATE (présent mais vide sur une instance neuve).
  -- Format observé au chunkdump : chemin NON quoté, flag 3 — on réplique à l'identique.
  if not want_ir then
    local pline = "P http://github.com/mikeoliphant/neural-amp-modeler-lv2#model " .. file .. " 3"
    log("    (chirurgie) bloc FX #" .. fx .. " lignes " .. start_i .. "-" .. end_i)
    for k = start_i, end_i do
      if lines[k]:gsub("\r", ""):match("^%s*<STATE") then
        table.insert(lines, k + 1, pline)
        local okset = write_chunk(track, lines)
        log("    (chirurgie) P inséré dans <STATE @" .. k .. " -> SetTrackStateChunk=" .. tostring(okset))
        return okset
      end
    end
    log("    (chirurgie) aucun <STATE trouvé dans le bloc")
    -- pas de <STATE du tout : on en crée un juste avant la fermeture du bloc FX
    table.insert(lines, end_i, ">")
    table.insert(lines, end_i, pline)
    table.insert(lines, end_i, "<STATE")
    return write_chunk(track, lines)
  end
  return false
end

-- bloc FX Ratatouille prouvé (extrait de bridge/templates/core.RfxChain), NAM+IR bakés.
local function rata_block(nam, ir)
  local nline = nam and ('"' .. nam .. '"') or "None"
  local iline = ir and ('"' .. ir .. '"') or "None"
  return {
    '<LV2 "LV2: Ratatouille (brummer) (Mono)" urn:brummer:ratatouille ""',
    '  CFG 0 610 419 ""',
    '  <IN_PINS', '  >', '  <OUT_PINS', '    PIN 0 0 1', '  >',
    '  P Knob0 0 Knob1 0 Knob2 0.5 Knob3 0.5 Knob4 0 NormalizeA 0 NormalizeB 0 Knob5 0 NormalizeSlotA 0 NormalizeSlotB 0',
    '  P ENABLE 1 eraseSlotA 0 eraseSlotB 0 eraseIr 0 eraseIr1 0 buffered 0 phase 0',
    '  <STATE',
    '    S urn:brummer:ratatouille#Neural_Model ' .. nline .. ' 3',
    '    S urn:brummer:ratatouille#Neural_Model1 None 3',
    '    S urn:brummer:ratatouille#irfile ' .. iline .. ' 3',
    '    S urn:brummer:ratatouille#irfile1 None 3',
    '  >', '>',
  }
end

-- Remplace TOUT le bloc <LV2…> du FX numéro `fx` par le bloc template (le chunk d'un Ratatouille
-- fraîchement ajouté N'A PAS les lignes S à éditer -> on injecte le bloc prouvé, chemins bakés).
local function chunk_replace_ratatouille(track, fx, nam, ir)
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
  heal_files(track, lines)                       -- une ligne fichier perdue par un chargement async est remise AVANT la réécriture
  local idx, start_i, end_i, i = -1, nil, nil, 1
  while i <= #lines do
    local t = lines[i]:gsub("\r", ""):match("^%s*(.-)%s*$")
    local tag = t:match("^<(%w+)")
    if tag and FX_OPEN[tag] then
      idx = idx + 1
      if idx == fx then
        start_i = i
        local depth, j = 1, i + 1
        while j <= #lines do
          local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
          if tt:sub(1, 1) == "<" then depth = depth + 1
          elseif tt == ">" then depth = depth - 1; if depth == 0 then end_i = j; break end end
          j = j + 1
        end
        break
      end
    end
    i = i + 1
  end
  if not (start_i and end_i) then return false end
  -- saute la ligne FXID qui suit le bloc -> Reaper génère un nouveau GUID et RÉ-INSTANCIE le FX
  -- (sinon il garde l'instance vivante et ne recharge pas les fichiers du chunk).
  local drop_to = end_i
  if lines[end_i + 1] and lines[end_i + 1]:match("FXID") then drop_to = end_i + 1 end
  local out = {}
  for k = 1, start_i - 1 do out[#out + 1] = lines[k] end
  for _, tl in ipairs(rata_block(nam, ir)) do out[#out + 1] = tl end
  for k = drop_to + 1, #lines do out[#out + 1] = lines[k] end
  return write_chunk(track, out)
end

-- étage 1 : tentatives SetNamedConfigParm (clés plausibles), loguées.
local function try_named_file(track, fx, plugin, slot, file)
  local pl = (plugin or ""):lower()
  local keys = {}
  local function push(k) if k then keys[#keys + 1] = k end end
  if pl:find("ratatouille") then
    if slot == "ir" then push("urn:brummer:ratatouille#irfile"); push("param.21.file")
    else push("urn:brummer:ratatouille#Neural_Model"); push("param.19.file") end
  end
  -- génériques (index de repli approximatif + clés « file »)
  push(slot == "ir" and "param.21.file" or "param.19.file")
  push("file"); push("FILE"); push("path")
  for _, k in ipairs(keys) do
    local ok = reaper.TrackFX_SetNamedConfigParm(track, fx, k, file)
    log("    SetNamedConfigParm['" .. k .. "'] -> " .. tostring(ok))
    if ok then return true end
  end
  return false
end

-- charge un fichier dans un slot via la CHIRURGIE DE CHUNK (format prouvé Ratatouille). Loggue.
local function load_via_chunk(track, fx, slot, file, label)
  local okc, res = pcall(chunk_set_lv2_file, track, fx, slot, file)
  if okc and res then log("    " .. label .. " chargé via chunk : " .. tostring(file))
  else log("    ⚠ " .. label .. " NON chargé via chunk (ok=" .. tostring(okc) .. " res=" .. tostring(res) .. ") : " .. tostring(file)) end
  return okc and res
end

-- orchestre le chargement des fichiers d'un bloc sur son FX. Jamais fatal.
local function load_block_file(track, fx, block, plugin)
  if not fx or fx < 0 then return end
  local pl = (plugin or ""):lower()
  -- AMPLI BUNDLE Ratatouille : NAM (model) ET IR (cab) via le chunk PROUVÉ (#Neural_Model / #irfile).
  if block.type == "amp" and pl:find("ratatouille") then
    local okr = chunk_replace_ratatouille(track, fx, block.file, block.cab_file)
    if okr then log("    Ratatouille : NAM+IR bakés (" .. tostring(block.file and block.file:match("[^/]+$")) ..
        " / " .. tostring(block.cab_file and block.cab_file:match("[^/]+$")) .. ")")
    else log("    ⚠ Ratatouille : remplacement de bloc échoué") end
    return
  end
  -- amp-nam / cab (plugins SÉPARÉS) : chargement non résolu (à débloquer en étape B via templates).
  if not block.file then return end
  local slot = (block.type == "cab") and "ir" or "model"
  log("  fichier '" .. tostring(block.file) .. "' -> " .. tostring(plugin) .. " (slot " .. slot .. ")")
  if try_named_file(track, fx, plugin, slot, block.file) then
    log("    (SetNamedConfigParm a renvoyé true — À VÉRIFIER au rig)")
    return
  end
  load_via_chunk(track, fx, slot, block.file, "fichier")
end

--------------------------------------------------- bloc « piano » (sfizz LV2, lane Keys)
-- Doctrine « tout est bloc » : le piano = UN SEUL FX LV2i sfizz sur la piste Keys. Contrairement à
-- l'orgue (moteur setBfree SANS port de contrôle -> JSFX injecteur devant), sfizz EXPOSE son port
-- « Volume » (port LV2 index 4, -80..6 dB) directement -> l'instance porte l'estampille STANDARD
-- golem:<id> et le pipeline params EXISTANT (PHASE B + scène-first) applique « Volume » SANS code
-- spécial (par nom exact, cf. effects.json piano.volume).
--   ⚠ NB : la doctrine « renamed piano:<id> » (analogie organ:<id>:synth) serait FAUSSE ici — le synth
--   d'orgue est hors-golem car il n'a AUCUN potard ; sfizz, lui, PORTE le potard Volume, donc il DOIT
--   rester dans l'espace golem:<id> pour que PHASE B et la scène-first l'atteignent.
--
-- CHARGEMENT DU .sfz — la propriété patch sfizz:sfzfile est un patch:writable atom:Path, EXACTEMENT
-- comme le #model du NAM (chargé par une ligne « P <uri> <path> 3 » dans <STATE>). Deux étages,
-- calqués sur load_block_file :
--   (a) TrackFX_SetNamedConfigParm(clés plausibles) — loggué, jamais fatal (aucune clé garantie doc).
--   (b) repli PROUVÉ : on injecte/réécrit la ligne P dans le <STATE> du bloc FX sfizz et on DROP le
--       FXID pour forcer Reaper à ré-instancier -> il relit l'état et le worker sfizz (work:schedule)
--       charge le sample set (⚠ Salamander = 714 Mo FLAC préchargés : plusieurs secondes).
--   ⚠ chemin sfz NON quoté dans la ligne P (format identique au NAM) : suppose un chemin SANS espace
--     (ROOT + library/sfz sans espace ici). Un .sfz au chemin espacé casserait le parse -> à traiter
--     si ce cas apparaît (quoting + support du parseur de chunk Reaper à valider).
local SFIZZ_NAMES = { "LV2i:sfizz (SFZTools)", "LV2i: sfizz (SFZTools)", "LV2i:sfizz",
                      "LV2i: sfizz", "VST3i: sfizz (SFZTools)", "VST3i: sfizz", "sfizz", "http://sfztools.github.io/sfizz" }
local SFIZZ_URI = "http://sfztools.github.io/sfizz:sfzfile"

-- ── sfizz en VST3 : le .sfz par l'ÉTAT VST3 (Windows/macOS, mesuré le 2026-10-11) ─────────────────────────
-- Sous Windows, REAPER ne lit pas sfizz.lv2 (avldrums.lv2, même dossier, oui) mais instancie « VST3i: sfizz
-- (SFZTools) » : la ligne P de l'état LV2 (chunk_set_sfizf) ne s'y applique pas, le moteur jouait MUET. Son état
-- VST3 (sfizz-ui SfizzVstState, version 5) : u64 version · str8 sfzFile (i32 longueur NUL inclus + octets) ·
-- f32 volume · i32 voix · i32 oversampling · i32 preload · str8 scala · i32 root · f32 tune · f32 stretch ·
-- 4×i32 qualités · i16 sustainCancelsRelease · i32 lastKeyswitch · u32 ccCount + (u16, f32)… — REAPER l'enveloppe
-- en <taille u32><1 u32><état><8 octets>. On ne touche QUE sfzFile (chemin à / ), le reste est gardé tel quel.
-- Mesuré dans un REAPER de banc : chunk relu à l'identique, puis un rendu de 2 s = 1 s de son, 1 s de silence.
local function sfizz_vst3_set_file(track, fx, file)
  local ok, enc = reaper.TrackFX_GetNamedConfigParm(track, fx, "vst_chunk")
  if not ok or not enc or enc == "" then return false, "vst_chunk illisible" end
  local data = unb64(enc)
  if not data or #data < 16 then return false, "état VST3 tronqué" end
  local size, kind = string.unpack("<I4I4", data)
  if kind ~= 1 or size ~= #data - 16 then return false, "enveloppe VST3 inattendue" end
  local st, tail = data:sub(9, 8 + size), data:sub(9 + size)
  if #st < 13 then return false, "état sfizz trop court" end
  local ver = string.unpack("<I8", st)
  local len = string.unpack("<i4", st, 9)
  if len < 0 or 12 + len > #st then return false, "sfzFile illisible" end
  local p = tostring(file):gsub("\\", "/") .. "\0"
  local body = st:sub(1, 8) .. string.pack("<i4", #p) .. p .. st:sub(13 + len)
  local new = string.pack("<I4I4", #body, kind) .. body .. tail
  local oks = reaper.TrackFX_SetNamedConfigParm(track, fx, "vst_chunk", b64(new))
  return oks and true or false, "v" .. tostring(ver)
end

-- injecte/réécrit la ligne P sfzfile dans le bloc FX `fx`, puis DROP le FXID (ré-instanciation ->
-- rechargement de l'état). Renvoie le résultat de SetTrackStateChunk.
local function chunk_set_sfizf(track, fx, file)
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
  heal_files(track, lines)                       -- une ligne fichier perdue par un chargement async est remise AVANT la réécriture
  -- localise le fx-ième bloc FX (même logique depth-safe que chunk_set_lv2_file)
  local idx, start_i, end_i, i = -1, nil, nil, 1
  while i <= #lines do
    local t = lines[i]:gsub("\r", ""):match("^%s*(.-)%s*$")
    local tag = t:match("^<(%w+)")
    if tag and FX_OPEN[tag] then
      idx = idx + 1
      if idx == fx then
        start_i = i
        local depth, j = 1, i + 1
        while j <= #lines do
          local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
          if tt:sub(1, 1) == "<" then depth = depth + 1
          elseif tt == ">" then depth = depth - 1; if depth == 0 then end_i = j; break end end
          j = j + 1
        end
        break
      end
    end
    i = i + 1
  end
  if not (start_i and end_i) then
    log("    (sfizz) bloc FX #" .. tostring(fx) .. " INTROUVABLE (idx max=" .. tostring(idx) .. ")")
    return false
  end
  local pline = "P " .. SFIZZ_URI .. " " .. file .. " 3"
  local placed = false
  -- 1) réécrire une ligne sfzfile déjà présente (instance déjà pourvue d'un state)
  for k = start_i, end_i do
    if lines[k]:gsub("\r", ""):find("sfizz:sfzfile", 1, true) then
      lines[k] = (lines[k]:match("^(%s*)") or "") .. pline
      placed = true
      break
    end
  end
  -- 2) sinon insérer dans le <STATE existant
  if not placed then
    for k = start_i, end_i do
      if lines[k]:gsub("\r", ""):match("^%s*<STATE") then
        table.insert(lines, k + 1, pline)
        end_i = end_i + 1
        placed = true
        break
      end
    end
  end
  -- 3) sinon créer un <STATE juste avant la fermeture du bloc FX
  if not placed then
    table.insert(lines, end_i, "<STATE")
    table.insert(lines, end_i + 1, pline)
    table.insert(lines, end_i + 2, ">")
    end_i = end_i + 3
  end
  -- drop la ligne FXID qui suit le bloc -> Reaper génère un nouveau GUID et RÉ-INSTANCIE (recharge l'état)
  if lines[end_i + 1] and lines[end_i + 1]:match("FXID") then
    table.remove(lines, end_i + 1)
  end
  return write_chunk(track, lines)
end

-- Vitalium LV2 (Windows) : pas de vst_chunk. Le .vital passe par le CHUNK du bloc <LV2 : les lignes
-- P (ports, que l'hôte possède et qui ÉCRASENT l'état) prennent les valeurs du preset, le sous-bloc
-- <X urn:juce:stateBinary> prend le JSON (wavetables, modulations), puis FXID retiré -> ré-instanciation.
-- `file` = sortie de vital.lv2_state (compile) : « P <port> <val> » puis « B <base64> ». Mesuré
-- 2026-10-03 : 0 paramètre différent du .vital, wavetables et modulations identiques — un preset LV2
-- chargé par TrackFX_SetPreset, lui, n'applique QUE les ports (son state:state est ignoré).
local function chunk_set_vitalium(track, fx, file)
  local txt = read_file(file)
  if not txt then log("    (vitalium) état introuvable : " .. tostring(file)); return false end
  local vals, b64 = {}, {}
  for l in txt:gmatch("[^\n]+") do
    local s, v = l:match("^P (%S+) (%S+)")
    if s then vals[s] = v else
      local b = l:match("^B (%S+)")
      if b then b64[#b64 + 1] = b end
    end
  end
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
  heal_files(track, lines)
  local idx, start_i, end_i, i = -1, nil, nil, 1
  while i <= #lines do
    local tag = lines[i]:gsub("\r", ""):match("^%s*<(%w+)")
    if tag and FX_OPEN[tag] then
      idx = idx + 1
      if idx == fx then
        start_i = i
        local depth, j = 1, i + 1
        while j <= #lines do
          local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
          if tt:sub(1, 1) == "<" then depth = depth + 1
          elseif tt == ">" then depth = depth - 1; if depth == 0 then end_i = j; break end end
          j = j + 1
        end
        break
      end
    end
    i = i + 1
  end
  if not (start_i and end_i) or not lines[start_i]:find("<LV2", 1, true) then
    log("    (vitalium) bloc LV2 #" .. tostring(fx) .. " INTROUVABLE")
    return false
  end
  local out, n_p, x_done, k = {}, 0, false, 1
  while k <= #lines do
    local l = lines[k]
    local t = l:gsub("\r", ""):match("^%s*(.-)%s*$")
    if k > start_i and k < end_i and t:match("^P ") then
      local tok, new = {}, {}
      for w in t:sub(3):gmatch("%S+") do tok[#tok + 1] = w end
      for q = 1, #tok - 1, 2 do
        local v = vals[tok[q]]
        if v then n_p = n_p + 1 end
        new[#new + 1] = tok[q]; new[#new + 1] = v or tok[q + 1]
      end
      out[#out + 1] = (l:match("^(%s*)") or "") .. "P " .. table.concat(new, " ")
      k = k + 1
    elseif k > start_i and k < end_i and t:match("^<X%s+urn:juce:stateBinary") then
      out[#out + 1] = l
      for _, b in ipairs(b64) do out[#out + 1] = b end
      local j = k + 1                                         -- saute l'ancien base64 jusqu'au « > »
      while j < end_i and not lines[j]:match("^%s*>%s*$") do j = j + 1 end
      out[#out + 1] = lines[j]
      x_done = true
      k = j + 1
    else
      out[#out + 1] = l
      k = k + 1
    end
  end
  if not x_done then
    log("    (vitalium) <X urn:juce:stateBinary absent du bloc — état non posé")
    return false
  end
  -- FXID qui suit la fermeture du bloc -> retiré : Reaper ré-instancie et relit l'état
  local shift = #out - #lines
  for m = end_i + shift + 1, math.min(end_i + shift + 5, #out) do
    local nt = out[m]:gsub("\r", ""):match("^%s*(.-)%s*$")
    if nt:match("^FXID") then table.remove(out, m); break
    elseif nt:sub(1, 1) == "<" or nt == ">" then break end
  end
  log(string.format("    (vitalium) %d ports + état (%d lignes b64)", n_p, #b64))
  return write_chunk(track, out)
end

-- le MOTEUR d'un bloc instrument porté par plusieurs FX du même nom golem:<id> (note-zone JS, arp
-- JS, moteur) : le seul qui n'est pas un JSFX. VST3 (Vital officiel) ou LV2 (Vitalium, Windows).
local function instrument_engine(tr, fxs)
  local engine = fxs[1]
  for _, fi in ipairs(fxs) do
    local okt, ft = reaper.TrackFX_GetNamedConfigParm(tr, fi, "fx_type")
    if okt and ft and (ft:find("VST") or ft:find("LV2") or ft:find("CLAP")) then engine = fi end
  end
  return engine
end

local function build_piano_block(track, block, effects)
  local fx, nm = add_first(track, SFIZZ_NAMES)
  if fx < 0 then
    log("  x piano " .. tostring(block.id) .. " : LV2i sfizz introuvable — plugin installé ET Reaper "
        .. "relancé DEPUIS l'install ? (piège de session : un plugin ajouté pendant que Reaper tourne "
        .. "reste invisible jusqu'au restart)")
    return
  end
  -- estampille STANDARD : sfizz porte son port « Volume » -> PHASE B + scène-first le ciblent par golem:<id>
  tag_fx(track, fx, block.id)
  local sfz = block.sfz_file
  local okt, ft = reaper.TrackFX_GetNamedConfigParm(track, fx, "fx_type")
  if sfz and sfz ~= "" and okt and ft and ft:find("VST3") then
    -- sfizz en VST3 (Windows/macOS) : le .sfz par l'état VST3, mesuré — pas de ligne P ici
    local okv, info = sfizz_vst3_set_file(track, fx, sfz)
    log(string.format("    (sfizz VST3) vst_chunk sfzFile -> %s (état %s, fichier %s)",
        tostring(okv), tostring(info), tostring(sfz:match("[^/]+$"))))
  elseif sfz and sfz ~= "" then
    -- étage (a) : clés SetNamedConfigParm plausibles (loguées, jamais fatales — aucune n'est garantie)
    for _, k in ipairs({ SFIZZ_URI, "sfizz:sfzfile", "sfzfile", "file", "FILE", "path" }) do
      local okk = reaper.TrackFX_SetNamedConfigParm(track, fx, k, sfz)
      log("    (sfizz a) SetNamedConfigParm['" .. k .. "'] -> " .. tostring(okk))
    end
    -- étage (b) PROUVÉ : ligne P dans <STATE> + drop FXID -> ré-instanciation & rechargement du sample set
    local ok2, res = pcall(chunk_set_sfizf, track, fx, sfz)
    local okc = ok2 and res
    log(string.format("    (sfizz b) chunk P sfzfile -> SetTrackStateChunk=%s (fichier %s)",
        tostring(okc), tostring(sfz:match("[^/]+$"))))
    -- ré-estampille après le drop FXID (l'index est conservé ; le renamed_name vit dans la ligne <LV2 …>
    -- donc survit normalement, mais on ré-applique par sécurité pour garantir la résolution PHASE B).
    tag_fx(track, fx, block.id)
  else
    log("  ⚠ piano " .. tostring(block.id) .. " : aucun b.sfz_file (compile n'a pas résolu params.sfz)")
  end
  reaper.TrackFX_SetEnabled(track, fx, not block.bypass)
  log(string.format("  + piano %s : %s @%d (golem:%s)", tostring(block.id), tostring(nm), fx, tostring(block.id)))
end

--------------------------------------------------- bloc « ep » (Dexed VST3i, lane Keys)
-- Doctrine « tout est bloc », patron ORGAN : l'e-piano = 2 FX chaînés sur la piste Keys :
--   [1] JSFX golem/dx7-ctl : charge la banque DX7 (SysEx bulk dump) + émet le Program Change du
--       patch. Son slider « Patch » EST un param Reaper -> pipeline scène-first -> PATCH PAR SCÈNE
--       SANS REBUILD (le PC part en @block). Estampille STANDARD golem:<id>.
--   [2] VST3i Dexed (Digital Suburban) : le moteur FM DX7. Il N'expose PAS de « programme courant »
--       automatisable -> banque+patch injectés en MIDI par le JSFX DEVANT. Estampillé HORS golem:
--       ("ep:<id>:synth") -> invisible au livemap/scène (ses 145 potards de voix sont pilotés par
--       le patch chargé, pas par le pipeline).
--
-- CHARGEMENT DE LA BANQUE — le .syx (F0 43 00 09 20 00 … 4104 o., relayé par le bridge dans
-- b.dx7_bank) EST un DX7 32-voice bulk dump valide. On ne peut PAS injecter du MIDI dans une
-- instance FX depuis ReaScript (aucune API ; StuffMIDIMessage -> bus virtuel, pas cette instance).
-- Voie éprouvée = JSFX émetteur DEVANT (patron b3-ctl : le @block tourne sur la lane Keys monitorée
-- même à l'arrêt). Le JSFX lit ses octets dans dx7-cart.txt (ints décimaux) que golem_rig écrit
-- dans SON dossier (filename:0 y est relatif) AVANT l'instanciation -> l'@init du JSFX les relit.
-- ⚠ NON validable hors-rig : réception SysEx cartouche + Program Change par Dexed, midisend_buf,
--   file_var .txt en @init. Repli si le MIDI échoue : greffe vst_chunk façon Vital (chunk bâti côté
--   bridge, zlib -> golem pose 'vst_chunk' à chaud) ; mais patch redeviendrait un rebuild.
local DEXED_NAMES = { "VST3i:Dexed", "VST3i: Dexed", "VSTi:Dexed", "VST:Dexed", "Dexed",
                      "VST3i:Dexed (Digital Suburban)" }
local DX7_CTL_NAMES = { "JS:golem/dx7-ctl", "JS: golem/dx7-ctl", "GoleM DX7 control (dx7-ctl)" }

-- écrit la banque .syx (octets -> ints décimaux séparés par virgule) là où le JSFX dx7-ctl la lit :
-- <resource>/Effects/golem/dx7-cart.txt (= filename:0, relatif au dossier du JSFX ; ce dossier est le
-- symlink link-reaper.sh vers reaper/Effects/). Écriture ATOMIQUE (tmp+rename). Renvoie (ok, n_octets).
local function write_dx7_cart(bank_path)
  local fin = io.open(bank_path, "rb")
  if not fin then return false, "syx illisible" end
  local data = fin:read("*a"); fin:close()
  if not data or #data == 0 then return false, "syx vide" end
  local t = {}
  for i = 1, #data do t[i] = tostring(data:byte(i)) end
  local dst = reaper.GetResourcePath() .. "/Effects/golem/dx7-cart.txt"
  local tmp = dst .. ".tmp"
  local fo = io.open(tmp, "w")
  if not fo then return false, "écriture cart impossible" end
  fo:write(table.concat(t, ",")); fo:close()
  os.remove(dst)                                   -- os.rename ne remplace pas sur tous les os -> remove d'abord
  local okr = os.rename(tmp, dst)
  if not okr then return false, "rename cart impossible" end
  return true, #data
end

local function build_ep_block(track, block, effects)
  local bank = block.dx7_bank
  local patch = tonumber(block.dx7_patch) or 0
  -- écrire la cartouche AVANT d'instancier le JSFX (filename:0 relu à SON @init).
  if bank and bank ~= "" then
    local okw, info = write_dx7_cart(bank)
    log(string.format("    (ep) banque %s -> dx7-cart.txt : %s (%s o.)",
        tostring(bank:match("[^/]+$")), tostring(okw), tostring(info)))
  else
    log("  ⚠ ep " .. tostring(block.id) .. " : aucun b.dx7_bank (compile n'a pas résolu params.bank)")
  end
  -- ordre : JSFX ctl AVANT Dexed (comme organ : ctl puis synth ; AddByName append conserve l'ordre)
  local ctl, cn = add_first(track, DX7_CTL_NAMES)
  if ctl < 0 then
    log("  x ep " .. tostring(block.id) .. " : JSFX dx7-ctl introuvable (provision/link-reaper.sh fait ? Reaper relancé ?)")
    return
  end
  local syn, sn = add_first(track, DEXED_NAMES)
  if syn < 0 then
    log("  x ep " .. tostring(block.id) .. " : VST3i Dexed NON instanciable — installé ET Reaper relancé "
        .. "DEPUIS l'install ? (piège de session : un plugin ajouté pendant que Reaper tourne reste "
        .. "invisible jusqu'au restart)")
    reaper.TrackFX_Delete(track, ctl)                          -- pas de moteur -> retire la couche ctl orpheline
    return
  end
  -- le JSFX porte l'estampille STANDARD golem:<id> -> scène-first pilote son slider « Patch » (PC par
  -- scène). Dexed = moteur, estampillé hors golem: -> invisible au livemap/scène.
  tag_fx(track, ctl, block.id)
  reaper.TrackFX_SetNamedConfigParm(track, syn, "renamed_name", "ep:" .. tostring(block.id) .. ":synth")
  -- patch initial sur le slider 0 (« Patch », 0..31) : valeur brute directe (le PC part au 1er @block).
  reaper.TrackFX_SetParam(track, ctl, 0, patch)
  reaper.TrackFX_SetEnabled(track, syn, true)                  -- moteur toujours actif
  reaper.TrackFX_SetEnabled(track, ctl, not block.bypass)      -- bypass ep = fige la couche ctl
  log(string.format("  + ep %s : ctl %s @%d (golem:%s) -> Dexed %s @%d, patch=%d",
      tostring(block.id), tostring(cn), ctl, tostring(block.id), tostring(sn), syn, patch))
end

------------------------------------------------------------------------- routage sortie
-- sortie hardware d'une piste (calqué sur io_hw_route de golem_apply : dest nil = hardware,
-- index de send réutilisé en catégorie 1, I_DSTCHAN 0-based, +1024 = somme mono OUT1).
local function route_out(tr, name, out_ch, mono_on, mono_gain)
  for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
  local snd = reaper.CreateTrackSend(tr, nil)                 -- dest nil => sortie hardware
  if mono_on then
    reaper.SetTrackSendInfo_Value(tr, 1, snd, "I_DSTCHAN", 0 + 1024)   -- OUT1, somme L+R
    if mono_gain and mono_gain ~= 0 then
      reaper.SetTrackSendInfo_Value(tr, 1, snd, "D_VOL", dblin(mono_gain))  -- pad repli mono
    end
    log("  out " .. name .. " -> OUT1 (mono sum, pad " .. tostring(mono_gain) .. " dB)")
  else
    reaper.SetTrackSendInfo_Value(tr, 1, snd, "I_DSTCHAN", out_ch - 1)  -- 0-based ; base paire = paire stéréo
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    log("  out " .. name .. " -> hw ch " .. out_ch .. " (I_DSTCHAN " .. (out_ch - 1) .. ")")
  end
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)          -- jamais via Master
end

-- combien de canaux une piste DOIT garder : 16 si elle porte un mixeur drumgizmo (un micro par canal,
-- drummix somme vers 1/2), 2 sinon. Le routage de sortie forçait 2 — ce qui ne laissait que les overheads.
local function wants_nchan(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm and nm:find("^drumkit%-mix:") then return 16 end
  end
  return 2
end

-- sortie physique (enceintes/baffles) selon le choix de la chaîne dans le Designer :
--   "1"   -> OUT 1 mono          (I_DSTCHAN = 0 + 1024, bit mono)
--   "2"   -> OUT 2 mono          (I_DSTCHAN = 1 + 1024)
--   "1-2" -> OUT 1/2 stéréo      (I_DSTCHAN = 0, piste en 2 canaux)   [défaut]
-- Jamais via le Master (= casque).
local function route_monitor(tr, name, out_sel)
  for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end  -- purge sends hardware
  local snd = reaper.CreateTrackSend(tr, nil)                   -- dest nil => sortie hardware
  -- LOT 2 : N sorties — "N" = OUT N mono, "a-b" = paire stéréo à partir de a (3-4 sur une 8×8),
  -- défaut 1-2. Deux lanes sur la même sortie SE SOMMENT dans le hardware send : c'est voulu, et
  -- chaque lane garde son trim (mixer). Jamais via le Master (= casque).
  local dst, label
  local a, b = tostring(out_sel or ""):match("^(%d+)%-(%d+)$")
  local mono = tostring(out_sel or ""):match("^(%d+)$")
  if a then dst, label = tonumber(a) - 1, "OUT " .. a .. "/" .. b .. " (stéréo)"; reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", wants_nchan(tr))
  elseif mono then dst, label = (tonumber(mono) - 1) + 1024, "OUT " .. mono .. " (mono)"
  else dst, label = 0, "OUT 1/2 (stéréo)"; reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", wants_nchan(tr)) end
  reaper.SetTrackSendInfo_Value(tr, 1, snd, "I_DSTCHAN", dst)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)           -- pas via Master (= casque)
  log("  out " .. name .. " -> " .. label)
end

-- limiteur de SÉCURITÉ (plafond -1 dBFS) en DERNIER FX de toute piste qui sort vers le hardware : les crêtes NAM
-- au-dessus de 0 dBFS écrêtaient le DAC sur les transitoires (mesuré +1,5 dB au merge — bug volume 2026-07-23).
-- ⚠ 2026-10-14 : c'était ReaLimit, qui ANTICIPE de 10 ms (pdc 480 échantillons à 48 kHz, non réglable) — sur
-- CHAQUE lane : 18 ms entre le geste et le son au lieu des 8 de la carte (« j'ai des lag », le mainteneur, en jouant sur une
-- boucle). C'est désormais golem_safety.jsfx : mêmes plafond et relâchement, AUCUNE anticipation (pdc 0). Un
-- ReaLimit `__safety` d'avant est remplacé au rebuild ; ReaLimit ne reste qu'en secours si le JSFX manque.
-- NB : les FX Reaper sont PRÉ-fader -> plafond -1 puis niveau de scène (D_VOL) ; un niveau de scène
-- positif > +1 dB re-dépasserait (cas non rencontré : les levels sont ≤ 0).
local SAFETY_JS = { "JS:golem/golem_safety", "JS: golem/golem_safety", "JS:golem/golem_safety.jsfx" }
local SAFETY_NAMES = { "ReaLimit", "VST: ReaLimit (Cockos)", "VST3: ReaLimit (Cockos)" }
local function is_safety_js(tr, i)
  local ok, ident = reaper.TrackFX_GetNamedConfigParm(tr, i, "fx_ident")
  if ok and ident and ident:find("golem_safety", 1, true) then return true end
  local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
  return (nm or ""):find("Safety limiter", 1, true) ~= nil
end
local function ensure_safety_limiter(tr)
  local n = reaper.TrackFX_GetCount(tr)
  for i = n - 1, 0, -1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm == "golem:__safety" then
      if is_safety_js(tr, i) then
        if i < reaper.TrackFX_GetCount(tr) - 1 then reaper.TrackFX_CopyToTrack(tr, i, tr, reaper.TrackFX_GetCount(tr) - 1, true) end
        return                                                     -- déjà le bon, et en dernier
      end
      reaper.TrackFX_Delete(tr, i)                                 -- un ReaLimit d'avant : 10 ms de trop
      log("  - safety ReaLimit retiré (10 ms d'anticipation)")
    end
  end
  local fx, how = -1, "golem_safety, 0 ms"
  for _, nm in ipairs(SAFETY_JS) do
    fx = add_fx(tr, nm, false, -1)
    if fx and fx >= 0 then break end
  end
  if not fx or fx < 0 then
    how = "ReaLimit de SECOURS, 10 ms — golem_safety introuvable (link-reaper.sh fait ?)"
    for _, nm in ipairs(SAFETY_NAMES) do
      fx = add_fx(tr, nm, false, -1)
      if fx and fx >= 0 then break end
    end
    if not fx or fx < 0 then log("  ⚠ ni golem_safety ni ReaLimit — pas de limiteur de sécurité") return end
    for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
      local _, pnm = reaper.TrackFX_GetParamName(tr, fx, p, "")
      local pl = (pnm or ""):lower()
      if pl:find("thresh") or pl:find("ceiling") then set_norm_to_target(tr, fx, p, -1, -60, 0) end
    end
  end
  local last = reaper.TrackFX_GetCount(tr) - 1
  if fx < last then reaper.TrackFX_CopyToTrack(tr, fx, tr, last, true); fx = last end
  tag_fx(tr, fx, "__safety")
  log("  + safety limiter (" .. how .. ", plafond -1 dB) en dernier")
end

------------------------------------------------------------------- SANDBOX : roots fixes
-- Le rig est matérialisé dans 2 pistes PERMANENTES du projet : "Sandbox #Input 1/2" (les 2 entrées
-- physiques). On NE crée PLUS de piste "GoleM:<id>" (fini l'accumulation). Le root d'un path (piste
-- qui porte l'entrée) est REMAPPÉ sur la piste sandbox de son input ; les sous-pistes d'un split
-- (merge/branches) sont créées TRANSITOIREMENT sous un nom sandbox et supprimées au build suivant.
local SANDBOX_PREFIX = "Sandbox #Input "
local function sandbox_name(input) return SANDBOX_PREFIX .. tostring(input) end

------------------------------------------------------------------------- MIXER (docs/mixer.md)
-- Le trim du mixer vit sur le D_VOL du SEND MATÉRIEL — un champ libre (route_out, qui posait le
-- pad mono dessus, n'est plus appelée) et distinct du D_VOL de PISTE qui porte le niveau de
-- scène. Deux étages, deux propriétaires : preset sur la piste, rig sur le send.
-- Les niveaux vivent dans config/mixer.json (état du rig) : relus à CHAQUE matérialisation pour
-- reposer les trims sur les sends que route_monitor vient de purger/recréer, et appliqués à
-- chaud par l'action mixer_apply (aucun rebuild — même famille que stomp).
local MIXER_SERVICE_TRACKS = { backing = "Backing Track", sample = "Sample", drums = "Drums",
                               looper = "Looper", click = "Click",
                               -- le STANDARD, une tranche par partie (pistes de golem_chordseq.lua, bridge/mixer.py)
                               ["std-keys"] = "Standard Keys", ["std-bass"] = "Standard Bass",
                               ["std-drums"] = "Standard Drums", ["std-guitar"] = "Standard Guitar" }
local MIXER_REC_TRACK = "Recording"          -- la piste du perf-rec (golem_perfrec.lua)

local function read_mixer(root)
  local raw = read_file(root .. "/config/mixer.json")
  if not raw then return {} end
  local ok, d = pcall(json_decode, raw)
  return (ok and d and d.levels) or {}
end

-- l'id de source mixer d'une piste sandbox ("Sandbox #Input 1/merge" -> "in1"), sinon nil
local function mixer_src_of(rname)
  local n = (rname or ""):match("^" .. SANDBOX_PREFIX .. "(%d+)")
  return n and ("in" .. n) or nil
end

-- ── LA DESTINATION D'UN SEND, SANS SWS (2026-09-22) ────────────────────────────────────────────
-- Le rec-follow lisait la destination par `BR_GetMediaTrackSendInfo_Track` (extension SWS). Reaper
-- sert la même chose nativement (`P_DESTTRACK`) : on essaie le natif d'abord, SWS reste en repli, et
-- le journal DIT lequel a servi — une dépendance ne se retire pas sur une intuition.
local _dest_how = nil
local function send_dest(tr, si)
  local ok, dest = pcall(reaper.GetTrackSendInfo_Value, tr, 0, si, "P_DESTTRACK")
  if ok and dest and reaper.ValidatePtr2(0, dest, "MediaTrack*") then
    if _dest_how ~= "native" then _dest_how = "native"; log("  send dest : API native (P_DESTTRACK)") end
    return dest
  end
  if reaper.BR_GetMediaTrackSendInfo_Track then
    local ok2, d2 = pcall(reaper.BR_GetMediaTrackSendInfo_Track, tr, 0, si, 1)
    if ok2 and d2 then
      if _dest_how ~= "sws" then _dest_how = "sws"; log("  send dest : repli SWS (BR_GetMediaTrackSendInfo_Track)") end
      return d2
    end
  end
  if _dest_how ~= "none" then _dest_how = "none"; log("  send dest : ni natif ni SWS — rec-follow sauté") end
  return nil
end

-- applique {db, mute} d'une source sur UNE piste : tous ses sends matériels (un seul
-- aujourd'hui ; N le jour d'une carte multi-sorties), et le send vers la piste Recording
-- s'il existe — LE MIX D'ENREGISTREMENT SUIT LE MIX PRINCIPAL (demande explicite : la prise
-- porte « le mix complet avec les bons niveaux » ; les DI, eux, restent bruts).
-- ⚠ le receive PerfRec est post-fader DE PISTE : sans cette recopie, le trim du send matériel
-- n'atteindrait jamais l'enregistrement.
local function mixer_apply_track(tr, lv)
  if not tr or not lv then return end
  local vol = nil
  if lv.db ~= nil then vol = (lv.db > -60) and dblin(lv.db) or 0 end
  for si = 0, reaper.GetTrackNumSends(tr, 1) - 1 do
    if vol ~= nil then reaper.SetTrackSendInfo_Value(tr, 1, si, "D_VOL", vol) end
    if lv.mute ~= nil then reaper.SetTrackSendInfo_Value(tr, 1, si, "B_MUTE", lv.mute and 1 or 0) end
  end
  -- rec-follow : la destination du send vient de `send_dest` (natif, SWS en repli)
  do
    for si = 0, reaper.GetTrackNumSends(tr, 0) - 1 do
      local dest = send_dest(tr, si)
      if dest and track_name(dest) == MIXER_REC_TRACK then
        if vol ~= nil then reaper.SetTrackSendInfo_Value(tr, 0, si, "D_VOL", vol) end
        if lv.mute ~= nil then reaper.SetTrackSendInfo_Value(tr, 0, si, "B_MUTE", lv.mute and 1 or 0) end
      end
    end
  end
end

-- les pistes d'une source : lanes par préfixe sandbox (root OU sous-piste porteuse du send),
-- services par nom fixe. Une piste absente n'est PAS une erreur — le bloc n'est pas dans ce
-- preset (la piste Click, par ex., n'existe qu'une fois le métronome demandé), la valeur
-- s'appliquera à la prochaine matérialisation.
-- ⚠ Les sous-pistes portent DEUX séparateurs : "/" (children, "…/lane-dirt") et "#" (merge,
-- "…#merge") — et c'est LE MERGE qui porte le send matériel d'un path splitté. Mesuré au dump :
-- ne matcher que "/" ratait la piste de sortie de la lane guitare. Même classe [/#] que le
-- balayeur sweep_legacy (ligne ~1825).
local function mixer_tracks_for(src)
  local out = {}
  local n = src:match("^in(%d+)$")
  if n then
    local prefix = SANDBOX_PREFIX .. n
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      local nm = track_name(tr)
      local sep = nm:sub(#prefix + 1, #prefix + 1)
      if (nm == prefix or ((sep == "/" or sep == "#") and nm:sub(1, #prefix) == prefix))
          and reaper.GetTrackNumSends(tr, 1) > 0 then
        out[#out + 1] = tr
      end
    end
  else
    local tr = MIXER_SERVICE_TRACKS[src] and find_track(MIXER_SERVICE_TRACKS[src])
    if tr then out[#out + 1] = tr end
  end
  return out
end

-- SONDE (read-only) : l'état RÉEL des sends — D_VOL/B_MUTE du send matériel et du send vers
-- Recording, par piste-source. C'est ce que le testeur de rig lit pour vérifier qu'un trim a
-- atterri : un log dit ce qu'on a VOULU faire, la sonde dit ce que Reaper TIENT.
local function mixer_dump(root)
  local rows = {}
  local function lin2db(v) return (v > 0) and (20 * math.log(v, 10)) or -999 end
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local nm = track_name(tr)
    local src = mixer_src_of(nm)
    for s, service in pairs(MIXER_SERVICE_TRACKS) do if nm == service then src = s end end
    if src and reaper.GetTrackNumSends(tr, 1) > 0 then
      local hwv = reaper.GetTrackSendInfo_Value(tr, 1, 0, "D_VOL")
      local hwm = reaper.GetTrackSendInfo_Value(tr, 1, 0, "B_MUTE")
      local rec = "null"
      do
        for si = 0, reaper.GetTrackNumSends(tr, 0) - 1 do
          local dest = send_dest(tr, si)
          if dest and track_name(dest) == MIXER_REC_TRACK then
            rec = string.format('{"db":%.1f,"mute":%d}',
              lin2db(reaper.GetTrackSendInfo_Value(tr, 0, si, "D_VOL")),
              reaper.GetTrackSendInfo_Value(tr, 0, si, "B_MUTE"))
          end
        end
      end
      rows[#rows + 1] = string.format('{"src":"%s","track":"%s","hw_db":%.1f,"hw_mute":%d,"rec":%s}',
        src, nm, lin2db(hwv), hwm, rec)
    end
  end
  local f = io.open(root .. "/presets/.mixerdump.json", "w")
  if f then f:write('{"sends":[' .. table.concat(rows, ",") .. ']}'); f:close() end
  log("mixer_dump : " .. #rows .. " piste(s) sondée(s)")
end

-- action mixer_apply : à chaud, PAS d'Undo_BeginBlock — un drag de fader émet plusieurs fois
-- par seconde, chaque bloc d'undo polluerait l'historique pour un geste continu.
local function handle_mixer(root, cmd)
  local n = 0
  for src, lv in pairs(cmd.levels or {}) do
    local trs = mixer_tracks_for(src)
    for _, tr in ipairs(trs) do
      mixer_apply_track(tr, lv)
      n = n + 1
      -- une ligne PAR piste : c'est ce que le testeur de rig lit pour vérifier sans les yeux
      log("mixer : " .. src .. " -> '" .. track_name(tr) .. "' db=" .. tostring(lv.db)
          .. " mute=" .. tostring(lv.mute))
    end
    if #trs == 0 and lv and (lv.db or 0) ~= 0 then
      log("mixer : " .. src .. " sans piste (absente de ce preset) — s'appliquera au prochain build")
    end
  end
  log("mixer : " .. n .. " piste(s) ajustée(s)")
end

-- Balaie SEULEMENT les pistes legacy "GoleM:*" (résidu de l'ANCIEN modèle, jamais en cours de
-- chargement -> delete sûr au début). Les sous-pistes transitoires ne sont PLUS supprimées ici :
-- elles sont réutilisées par nom, et les obsolètes retirées EN FIN de build (delete_unwanted_subtracks).
local function sweep_legacy()
  local legacy = 0
  for i = reaper.CountTracks(0) - 1, 0, -1 do
    local tr = reaper.GetTrack(0, i)
    if track_name(tr):sub(1, #PREFIX) == PREFIX then
      reaper.DeleteTrack(tr); legacy = legacy + 1
    end
  end
  if legacy > 0 then log("sandbox : " .. legacy .. " piste(s) legacy GoleM:* balayée(s)") end
end

-- ⚠ NE JAMAIS DÉTRUIRE UN FX PENDANT QU'IL CHARGE. Les NAM et l'IR chargent dans un worker LV2
-- asynchrone ; un TrackFX_Delete pendant ce chargement est « la course delete/ZConvolv » (cf. la
-- branche REUSE) — Reaper ABORTE (apport : signal 6, deux fois le 2026-09-07, chaque fois un
-- rebuild lancé < 3 s après le précédent : sauver un patch puis le charger dans le Designer).
-- On attend donc, AVANT de vider la piste, que tout fichier écrit récemment se déclare chargé —
-- au plus FILES_FRESH secondes après l'écriture (un fichier que le plugin refuse ne bloque pas
-- au-delà). Attente ACTIVE : pas de defer possible ici, et le thread audio comme les workers
-- continuent de tourner pendant que le thread principal patiente.
local function wait_loads_done(tr)
  -- ⚠ attente PASSIVE : on n'interroge PAS le plugin pendant qu'il charge (lire « Neural Model »
  -- en boucle sur une instance dont le worker écrit encore, c'est une course de plus — pas ici).
  -- On laisse simplement passer FILES_FRESH s depuis la dernière écriture de fichier sur la piste.
  local _, ts = reaper.GetSetMediaTrackInfo_String(tr, FILES_T_KEY, "", false)
  local t0 = tonumber(ts)
  if not t0 then return end
  local t_in = reaper.time_precise()
  -- ⚠ UNE HEURE D'UNE AUTRE SESSION FIGEAIT REAPER (2026-10-05). `t0` est un time_precise() posé dans
  -- un P_EXT, donc SAUVÉ DANS LE PROJET ; or time_precise repart à chaque lancement (de REAPER ou de
  -- Windows). L'heure d'hier soir était « dans le futur » ce matin : l'attente ci-dessous durait des
  -- heures, un cœur à 100 %, et comme elle tient le thread principal, TOUTES les boucles defer se
  -- taisaient (plus de commandes, plus de télémétrie : « No sound card » alors que le son passait).
  -- Une heure plus grande que maintenant n'est pas une écriture récente : rien ne charge. Et
  -- l'attente ne dépasse jamais FILES_FRESH, quoi que dise la piste.
  if t0 > t_in then return end
  local deadline = math.min(t0 + FILES_FRESH, t_in + FILES_FRESH)
  if t_in >= deadline then return end
  while reaper.time_precise() < deadline do
    local t1 = reaper.time_precise()
    while reaper.time_precise() - t1 < 0.02 do end
  end
  log(string.format("  fichiers écrits il y a < %.0f s sur %s : attendu %.0f ms avant de vider la piste",
      FILES_FRESH, track_name(tr), (reaper.time_precise() - t_in) * 1000))
end

local function clear_track_fx(tr)
  wait_loads_done(tr)
  for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do reaper.TrackFX_Delete(tr, i) end
  files_forget(tr)                                -- la mémoire des fichiers suit les FX : rien à guérir sur une piste vide
end

-- device MIDI de la lane Keys : hint exact d'abord (plan.midi_in, ex. "hw:II" — Reaper en ALSA raw
-- nomme les devices "hw:<id carte>"), sinon heuristique contrôleur (mpk/akai/hw: hors carte son).
local function keys_midi_dev(hint, avoid)
  local fallback
  local skip = {}
  for _, a in ipairs(avoid or {}) do skip[a] = true end          -- devices liés au rôle drums : jamais en repli (P7)
  for i = 0, 127 do
    local ok, name = reaper.GetMIDIInputName(i, "")
    if ok and name and name ~= "" then
      if hint and name == hint then return i, name end
      local l = name:lower()
      if not fallback and not skip[name] and (l:find("mpk") or l:find("akai") or (l:find("^hw:") and not l:find("v276"))) then
        fallback = { i, name }
      end
    end
  end
  if fallback then return fallback[1], fallback[2] end
  return nil
end

local function midi_input_names()
  local t = {}
  for i = 0, 127 do
    local ok, name = reaper.GetMIDIInputName(i, "")
    if ok and name and name ~= "" then t[#t + 1] = i .. "=" .. name end
  end
  return table.concat(t, " · ")
end

-- vide + mute (+ défolder) les roots sandbox qu'aucun path n'utilise ce build.
local function sandbox_idle(used_inputs)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local n = track_name(tr):match("^" .. SANDBOX_PREFIX .. "(%d+)$")
    if n and not used_inputs[tonumber(n)] then
      clear_track_fx(tr)
      reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", 0)
      reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 1)
      log("sandbox In" .. n .. " inutilisé -> vidé + mute")
    end
  end
end

----------------------------------------------------------------- chunk : FXCHAIN (copié de golem_apply)
-- remplace le bloc <FXCHAIN> de la track par un .RfxChain -> les FX naissent DU TEXTE
-- (fichiers NAM/IR chargés à l'instanciation). C'est le mécanisme PROUVÉ (short-summer).
local function load_fxchain(track, rfx_text)
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for line in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = line end
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
    local inserted, close_i = false, #lines
    for i = #lines, 1, -1 do if lines[i]:gsub("%s", ""):gsub("\r", "") == ">" then close_i = i; break end end
    for i, l in ipairs(lines) do
      local t = l:gsub("\r", ""):match("^%s*(.-)%s*$")
      if not inserted and ((t:sub(1, 1) == "<" and i > 1) or i == close_i) then
        for _, fl in ipairs(fx_lines) do out[#out + 1] = fl end; inserted = true
      end
      out[#out + 1] = l
    end
  end
  return write_chunk(track, out)
end

-- index d'un FX par sous-chaîne de son nom (ex. "neural amp"), -1 sinon.
local function fx_index_by_name(tr, needle)
  needle = needle:lower()
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if nm and nm:lower():find(needle, 1, true) then return i end
  end
  return -1
end

-- index d'un FX par son estampille de bloc (renamed_name = golem:<id>), robuste aux déplacements. -1 sinon.
local function fx_index_by_tag(tr, id)
  local want = "golem:" .. id
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm == want then return i end
  end
  return -1
end

-- LE FX D'UN BLOC CŒUR (ampli/baffle) : par ESTAMPILLE d'abord (golem:<id> — un cœur réutilisé ou
-- guéri est renommé, et « neural amp » ne le trouve plus : mesuré le 2026-09-14, Sunfunk lane-b, ampli
-- injoignable par nom donc ni enable ni potards), par NOM ensuite (cœur fondu du template, non
-- estampillé). -1 si absent.
local function core_fx_index(tr, blk)
  local fx = blk.id and fx_index_by_tag(tr, blk.id) or -1
  if fx >= 0 then return fx end
  return fx_index_by_name(tr, (blk.type == "cab") and "ir convolver" or "neural amp")
end

local function apply_core_params(tr, fx, blk, spec, effects)
  if not blk.params then return end
  if not spec.native_core then
    apply_block_params(tr, fx, blk.type, blk.params, effects)
    return
  end
  -- le baffle : `level` s'AJOUTE à la compensation des -18 dB du VST3 (load_native_core)
  local comp = blk.type == "cab" and (NAM_IR_COMP_DB or 18) or 0
  local names = blk.type == "cab" and { level = { "Output", -40 - comp, 40 - comp } } or
                { input = { "Input", -20, 20 }, output = { "Output", -40, 40 } }
  for id, value in pairs(blk.params) do
    if id:sub(1, 1) ~= "_" then
      local info = names[id]
      local p = info and find_param_exact(tr, fx, info[1])
      if p and tonumber(value) then
        local norm = math.max(0, math.min(1, (tonumber(value) - info[2]) / (info[3] - info[2])))
        reaper.TrackFX_SetParamNormalized(tr, fx, p, norm)
      else log("  ⚠ NAM VST3 : potard non mappé " .. tostring(blk.type) .. "." .. tostring(id)) end
    end
  end
end

-- ENABLE d'un bloc CŒUR (ampli/baffle) selon la scène. Mesuré le 2026-09-14 (Sunfunk, scène B « Heavy »
-- muette de saturation) : la bascule sans rebuild et la reprise de FX inchangés ne touchaient JAMAIS à
-- l'enable du cœur — seulement à ses potards. Un ampli éteint par une scène (A : b19 off) restait
-- bypassé dans la suivante qui le voulait actif ; la DI passait dans le baffle, propre. Ici : le NAM
-- (ou l'IR d'un bloc cab) suit blk.bypass, et le BAFFLE PAR DÉFAUT d'une tête isolée (IR fondu au
-- compile, sans bloc cab sur la piste) suit l'ampli — sinon une tête coupée laisserait la DI dans l'IR.
local function apply_core_enabled(tr, spec, blk)
  local fx = core_fx_index(tr, blk)
  if fx < 0 then return false end
  fx_set_on(tr, fx, not blk.bypass)                               -- baffle : interrupteur interne, jamais le bypass
  if blk.type ~= "cab" then
    local explicit_cab = false
    for _, b in ipairs(spec.blocks or {}) do if b.type == "cab" then explicit_cab = true end end
    if not explicit_cab then
      local ir = spec.native_core and fx_index_by_tag(tr, "core-default-ir") or
                 fx_index_by_name(tr, "ir convolver")
      if ir >= 0 then fx_set_on(tr, ir, not blk.bypass) end
    end
  end
  return true
end

-- LISTE des FX d'un bloc (tous les FX estampillés golem:<id> sur la piste). Ordonnée MOTEUR d'abord,
-- note-zone en DERNIER : le repli num_index de resolve_param vise ainsi le moteur (les idx du schéma
-- lui sont destinés), et fxs[1] = le FX à bypasser (bypass bloc = couper le moteur, pas le filtre de
-- zone). Bloc mono-FX (guitare, etc.) -> { fx } : comportement identique à fx_index_by_tag.
local function block_fx_list(tr, id)
  local want = "golem:" .. id
  local synth_sfx = ":" .. id .. ":synth"          -- moteur ep/organ (estampille hors golem:)
  local zone, others, synth = nil, {}, nil
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm == want then
      local _, fxnm = reaper.TrackFX_GetFXName(tr, i, "")
      if fxnm and fxnm:lower():find("note-zone", 1, true) then zone = i else others[#others + 1] = i end
    elseif ok and nm and nm:sub(-#synth_sfx) == synth_sfx then
      synth = i                                    -- session UI ep 2026-07-23 : les potards moteur
    end                                            -- (Cutoff/Resonance/Output Dexed) se résolvent en
  end                                              -- match EXACT sur le synth, APRÈS les FX golem:
  if zone then others[#others + 1] = zone end
  if synth then others[#others + 1] = synth end
  return others
end

-- pose les 3 params de zone (raw) sur le FX note-zone du bloc (le SEUL qui les porte). Utilisé pour
-- Vital (qui court-circuite apply_block_params : son preset vit dans le vst_chunk) et redondant mais
-- inoffensif pour organ/piano/ep (déjà couverts par apply_block_params multi-FX). Idempotent.
-- ── arpégiateur du bloc VITAL (2026-07-24, tiroir Vital uniquement) : JSFX stock
-- midi_arp inséré À LA DEMANDE devant le moteur (estampille golem:<id> -> rejoint la fxlist),
-- self-heal comme le reste. Configs nommées -> sliders (Rate ×BPM : 4 = 1/16, 2 = 1/8 ;
-- Mode 0..3 = Down/Up/Down Alt/Up Alt ; Variant 1 = +12 st = passe d'octave). « Off » = bypass.
local ARP_CONFIGS = {
  -- ⚠ ORDRE ET DÉFAUTS : la liste allait de la plus RAPIDE à la plus lente, donc la première
  -- chose qu'on essayait était la double-croche — « beaucoup trop vite » (à l'oreille,
  -- 2026-08-03). Elle va maintenant du plus doux au plus rapide. La croche est le geste
  -- naturel d'un arpège d'accompagnement ; la double-croche reste là, mais on la choisit.
  ["Up 1/4"]       = { rate = 1, mode = 1, nvar = 0, v1 = 0 },
  ["Up 1/8"]       = { rate = 2, mode = 1, nvar = 0, v1 = 0 },
  ["Down 1/8"]     = { rate = 2, mode = 0, nvar = 0, v1 = 0 },
  ["Up-Down 1/8"]  = { rate = 2, mode = 3, nvar = 0, v1 = 0 },
  ["Up 1/16"]      = { rate = 4, mode = 1, nvar = 0, v1 = 0 },
  ["Down 1/16"]    = { rate = 4, mode = 0, nvar = 0, v1 = 0 },
  ["Up-Down 1/16"] = { rate = 4, mode = 3, nvar = 0, v1 = 0 },
  ["Up 2 oct"]     = { rate = 2, mode = 1, nvar = 1, v1 = 12 },
}
local ARP_NAMES = { "JS:midi/midi_arp", "JS: MIDI Arpeggiator", "midi/midi_arp" }

-- Types qui acceptent un arpégiateur : le geste de l'AKAI (on plaque, l'arp déroule) n'a
-- aucune raison d'être réservé à Vital. Le JSFX stock `midi_arp` se pose devant n'importe
-- quel moteur de clavier.
local ARP_TYPES = { vital = true, piano = true, ep = true, organ = true }

-- `no_insert` : chemin SCÈNE. Une scène est une bascule d'ÉTAT, jamais un rebuild
-- (docs/live-engine.md) — poser un FX y décalerait les index sous les pieds du reste de la
-- matérialisation. Si l'arp n'existe pas encore, on ne le crée donc pas : on le dit et on sort.
local function apply_vital_arp(track, fxs, block, no_insert)
  local want = (block.params or {}).arp
  if want == nil then return end                       -- param jamais touché -> ne rien faire
  local cfg = ARP_CONFIGS[tostring(want)]
  local arp
  for _, fx in ipairs(fxs) do                          -- discriminant : le slider « Rate (x BPM) »
    if find_param_exact(track, fx, "Rate (x BPM)") then arp = fx; break end
  end
  if not cfg then                                      -- Off (ou config inconnue) : bypass
    if arp then reaper.TrackFX_SetEnabled(track, arp, false) end
    return
  end
  if not arp and no_insert then
    log("  (scène) arp demandé mais absent du bloc " .. tostring(block.id) .. " — rebuild requis")
    return
  end
  if not arp then
    local nm
    arp, nm = add_first(track, ARP_NAMES)
    if not arp or arp < 0 then log("  ⚠ arp vital : JSFX midi_arp introuvable"); return end
    tag_fx(track, arp, block.id)
    -- OÙ POSER L'ARP : juste APRÈS le note-zone, DEVANT tout le reste du bloc.
    -- ⚠ L'ancien repère (« le premier FX de type VST ») ne valait que pour Vital : sfizz est
    -- un LV2 et b3-ctl un JSFX, donc pour piano/organ aucun moteur n'était trouvé, l'arp
    -- restait en QUEUE de bloc — derrière l'instrument — et n'arpégeait rien du tout.
    -- Après la zone et pas avant : on arpège ce que la zone laisse passer, pas le clavier
    -- entier (sinon un split ferait arpéger la main gauche du voisin).
    -- ⚠ ON NE CHERCHE PAS PAR NOM : tag_fx RENOMME chaque FX en « golem:<id> », donc
    -- TrackFX_GetFXName rend l'estampille, pas le plugin (mesuré : les deux FX du bloc
    -- piano rendaient « golem:piano-1 »). C'est d'ailleurs l'idiome du fichier — on
    -- discrimine par un PARAMÈTRE unique, comme « Rate (x BPM) » pour l'arp lui-même.
    local first, zone
    for _, fx in ipairs(fxs) do
      if not first or fx < first then first = fx end
      if find_param_exact(track, fx, "Zone Low") then zone = fx end   -- le note-zone
    end
    local want = zone and (zone + 1) or first
    if want and arp ~= want then
      reaper.TrackFX_CopyToTrack(track, arp, track, want, true)     -- move : prend cet index
      arp = want
    end
    log("  + arp (" .. tostring(nm) .. ") @" .. arp .. " (golem:" .. tostring(block.id) .. ")")
  end
  local function seta(name, val)
    local pi = find_param_exact(track, arp, name)
    if pi then reaper.TrackFX_SetParam(track, arp, pi, val) end
  end
  seta("Rate (x BPM)", cfg.rate)
  -- ⚠ « Velocity » vaut 127 PAR DÉFAUT : l'arpégiateur force la vélocité MAXIMALE et ignore
  -- celle des notes qu'on lui envoie. C'était la cause du « beaucoup trop fort » (le mainteneur, à
  -- l'oreille, 2026-08-03) — et la raison pour laquelle baisser la vélocité à la source ne
  -- changeait rien. 0 = « joue la vélocité reçue », donc c'est nous qui décidons.
  seta("Velocity (0=use played velocity)", 0)
  -- et un arpège qui respire : notes tenues à moitié plutôt que collées bout à bout
  seta("Note Length", 0.5)
  seta("Note Length", 0.7)
  seta("Mode", cfg.mode)
  seta("Number Of Variants", cfg.nvar)
  seta("Variant 1", cfg.v1)
  reaper.TrackFX_SetEnabled(track, arp, true)
end

local function apply_zone(track, fxs, block)
  local p = block.params or {}
  for _, fx in ipairs(fxs) do
    -- discriminant FIABLE (bug zone AKAI 2026-07-23) : le note-zone possède un param « Zone Low ».
    -- L'ancien test sur le NOM (« note-zone ») ne matchait plus JAMAIS : le JSFX est renommé
    -- golem:<id> à l'estampillage -> la zone ne s'appliquait qu'au premier build, aucune édition
    -- de feuille ne retombait (sliders figés aux valeurs d'instanciation).
    local pi = find_param_exact(track, fx, "Zone Low")
    if pi then
      local function setz(name, val) local q = find_param_exact(track, fx, name); if q then reaper.TrackFX_SetParam(track, fx, q, val) end end
      setz("Zone Low",  tonumber(p.zone_lo) or 0)
      setz("Zone High", tonumber(p.zone_hi) or 127)
      setz("Transpose", tonumber(p.transpose) or 0)
      return
    end
  end
end

------------------------------------------------------------------------- stomp live (sans rebuild)
-- {"action":"stomp","ids":["delay-1","reverb-1"],"on":bool} : bascule TrackFX_SetEnabled des blocs
-- listés (par leur estampille golem:<id>). Le bridge résout QUELS blocs sont sur le switch pressé
-- (block.foot, assignation libre : plusieurs blocs par switch). Les blocs coupés par la scène restent
-- posés-désactivés au build -> le stomp les rallume sans reconstruire : gapless, adapté au pied.
--
-- VARIANTE (2026-07-30, chef d'orchestre) : {"on_ids":[…],"off_ids":[…]} applique les DEUX sens
-- EN UNE PASSE. Le canal bridge->Reaper n'a qu'UN slot de commande : deux commandes successives
-- se perdraient l'une l'autre, et les espacer ferait arriver le boost 80 ms avant que le delay ne
-- se coupe — audible à une frontière de section. Ce n'est pas un nouveau chemin de
-- matérialisation, c'est la même bascule avec une charge utile qui dit les deux sens.
local function handle_stomp(root, cmd)
  local pairs_ = {}
  if cmd.on_ids or cmd.off_ids then
    if cmd.on_ids  then pairs_[#pairs_ + 1] = { ids = cmd.on_ids,  on = true } end
    if cmd.off_ids then pairs_[#pairs_ + 1] = { ids = cmd.off_ids, on = false } end
  else
    if not cmd.ids or #cmd.ids == 0 then log("stomp : ids absents") return end
    pairs_[1] = { ids = cmd.ids, on = cmd.on == true }
  end
  local hits, n = 0, 0
  for ti = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, ti)
    for _, grp in ipairs(pairs_) do
      for _, bid in ipairs(grp.ids) do
        local parent, slot = tostring(bid):match("^(.-)@capture(%d+)$")
        local fxs = block_fx_list(tr, parent or bid)         -- le contrôle capturé reste dans SON bloc
        if #fxs > 0 then
          if parent then reaper.TrackFX_SetParamNormalized(tr, fxs[1], tonumber(slot), grp.on and 1 or 0)
          else fx_set_on(tr, fxs[1], grp.on) end
          hits = hits + 1
        end
      end
    end
  end
  for _, grp in ipairs(pairs_) do n = n + #grp.ids end
  log("stomp -> " .. n .. " bloc(s), " .. hits .. " FX")
end

------------------------------------------------------------------------- pose FX d'une piste
-- Pose sur `tr` : cœur .RfxChain (ampli+cab bakés), merge-gain (tête), puis FX hors-cœur DANS L'ORDRE
-- logique (les blocs AVANT l'ampli — ex. overdrive — sont posés avant le NAM, pas appendus en fin) +
-- fichiers/estampille/bypass/params. La piste doit être VIDÉE avant (clear_track_fx).
local function build_track_fx(root, tr, spec, effects)
  reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:golem_core_failed", "", true)
  -- lane Keys : le ROOT (piste a l'entree MIDI du clavier) porte le renifleur de potards AKAI EN TETE
  -- (avant tout instrument/note-zone). CC -> gmem golem_knobs -> golem_knobs.lua. spec.midi + input.
  -- pas sur une lane DRUMS : la pédale de charleston (CC4) aurait piloté la Macro 4 de Vital via golem_knobs (revue 2026-09-17, P3)
  if spec.midi and spec.input ~= nil and spec.midi_role ~= "drums" then ensure_knob_tap(tr) end
  -- CŒUR d'abord : load_fxchain REMPLACE tout le <FXCHAIN> -> doit précéder le merge_gain (sinon il l'efface).
  local core = {}
  if spec.native_core then
    local loaded = load_native_core(tr, spec.native_core)
    reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:golem_core_failed", loaded and "" or "1", true)
    if not loaded then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 1) end
    for _, ct in ipairs(spec.core_types or {}) do core[ct] = true end
  elseif spec.rfxchain then
    local rfx = read_file(root .. "/reaper/FXChains/" .. spec.rfxchain)
    if rfx then load_fxchain(tr, rfx); log("  cœur chargé : " .. spec.rfxchain)
    else log("  ⚠ cœur introuvable : " .. spec.rfxchain) end
    for _, ct in ipairs(spec.core_types or {}) do core[ct] = true end
  end
  -- merge : trim de sommation pré-pendu en TÊTE (@0), APRÈS le remplacement du fxchain
  if spec.role == "merge" and spec.merge_gain ~= nil then
    set_merge_gain_fx(tr, spec.merge_gain)
  end

  -- rang logique de l'ampli : les blocs hors-cœur AVANT lui doivent passer avant le NAM.
  local amp_pos
  for i, blk in ipairs(spec.blocks or {}) do
    if blk.type == "amp" or blk.type == "amp-nam" then amp_pos = i; break end
  end
  local pre_slot
  if spec.native_core then
    pre_slot = fx_index_by_tag(tr, spec.native_core.amp_id or "")
    if pre_slot < 0 then pre_slot = fx_index_by_name(tr, "neuralampmodeler") end
  else
    pre_slot = fx_index_by_name(tr, "neural amp")
  end

  -- PHASE A : ajoute les FX hors-cœur (appendus), déplace les pré-ampli avant le NAM, estampille tout de
  -- suite (renamed_name) pour re-résoudre l'index en PHASE B malgré les décalages.
  for i, blk in ipairs(spec.blocks or {}) do
    if effects[blk.type] and (effects[blk.type].engine == "midi" or effects[blk.type].engine == "virtual") then
      log("  ~ " .. tostring(blk.type) .. " : bloc " .. effects[blk.type].engine .. " (géré par le bridge, pas de FX)")
    elseif blk.type == "pads" then
      build_pads_block(tr, blk, effects)                            -- N instances RS5k (une par pad), auto-estampillées
    elseif blk.type == "drumkit" then
      build_drumkit_block(tr, blk, root)                            -- JSFX golem_drumtrans (golem:<id>) + moteur du kit (drumkit:<id>)
    elseif blk.type == "organ" then
      if blk.zone then build_note_zone(tr, blk) end                 -- filtre de zone EN TÊTE (avant le moteur)
      build_organ_block(tr, blk, effects)                           -- paire JSFX b3-ctl (golem:<id>) + LV2 b_synth
    elseif blk.type == "piano" then
      if blk.zone then build_note_zone(tr, blk) end
      build_piano_block(tr, blk, effects)                            -- 1 FX LV2i sfizz (golem:<id>), .sfz chargé par chunk
    elseif blk.type == "ep" then
      if blk.zone then build_note_zone(tr, blk) end
      build_ep_block(tr, blk, effects)                               -- JSFX dx7-ctl (golem:<id>) + VST3i Dexed (banque .syx + PC)
    elseif not core[blk.type] then
      if blk.zone then build_note_zone(tr, blk) end                 -- vital (ou autre instrument keys générique) : zone d'abord
      local fx = add_block_fx(tr, blk, effects)                    -- posé en fin de chaîne
      if fx and fx >= 0 then
        local dest = fx                                            -- index FINAL du bloc (après un éventuel move)
        if amp_pos and i < amp_pos then
          if pre_slot and pre_slot >= 0 then
            reaper.TrackFX_CopyToTrack(tr, fx, tr, pre_slot, true) -- MOVE : avant l'ampli
            dest = pre_slot                                        -- le FX déplacé est MAINTENANT à pre_slot
            pre_slot = pre_slot + 1                                -- le prochain pré-ampli passe juste après
          else
            log("  ⚠ NAM introuvable : bloc pré-ampli '" .. tostring(blk.type) .. "' laissé en fin (ordre faux)")
          end
        end
        if blk.id then tag_fx(tr, dest, blk.id) end                -- estampille l'index FINAL (pas fx périmé)
      end
    end
  end

  -- PHASE B : re-résout par estampille (liste des FX du bloc : moteur + éventuel note-zone), puis
  -- fichier/bypass/params. Le moteur = fxs[1] (fichier, vst_chunk, bypass) ; les params passent la
  -- LISTE à apply_block_params qui route chaque nom sur le bon FX (zone -> note-zone, potards -> moteur).
  for _, blk in ipairs(spec.blocks or {}) do
    if not core[blk.type] and blk.id and blk.type ~= "pads" then    -- pads : posé+réglé en PHASE A (N instances)
      local fxs = block_fx_list(tr, blk.id)
      if #fxs > 0 then
        local engine = fxs[1]
        -- vital pose DEUX FX sous le même nom golem:<id> (note-zone JS @0, moteur VST3 @1) :
        -- le vst_chunk et le bypass visent le MOTEUR — fxs[1] tombait sur le JSFX et
        -- SetNamedConfigParm("vst_chunk") rendait false : preset Vital jamais appliqué
        -- (bug UI 2026-07-19). Discriminant fiable = fx_type (les deux ont le même nom).
        if blk.type == "vital" then engine = instrument_engine(tr, fxs) end
        if blk.file or blk.cab_file then
          local _, plug = reaper.TrackFX_GetFXName(tr, engine, "")
          if DESKTOP_FX and (blk.type == "pedal-nam" or blk.type == "preamp-nam" or blk.type == "comp-nam") then
            if not load_windows_nam_block(tr, engine, blk.file) then
              reaper.GetSetMediaTrackInfo_String(tr, "P_EXT:golem_core_failed", "1", true)
              reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 1)
            end
          else load_block_file(tr, engine, blk, plug) end
        end
        -- état Vital : JSON .vital greffé par compile dans un vst_chunk complet -> posé À CHAUD
        -- (SetNamedConfigParm sur l'instance vivante = seule voie prouvée, spike 2026-07-08).
        -- Moteur LV2 (Vitalium, Windows) : pas de vst_chunk -> chunk de piste (chunk_set_vitalium).
        local okft, eft = false, nil
        if blk.type == "vital" then okft, eft = reaper.TrackFX_GetNamedConfigParm(tr, engine, "fx_type") end
        if blk.type == "vital" and okft and eft and eft:find("LV2") then
          if blk.vitalium_state then
            local okl, res = pcall(chunk_set_vitalium, tr, engine, root .. "/reaper/FXChains/" .. blk.vitalium_state)
            log("  vital (Vitalium LV2): état " .. blk.vitalium_state .. " -> "
                .. (okl and tostring(res) or ("ERREUR " .. tostring(res))))
            tag_fx(tr, engine, blk.id)                             -- par sécurité après le drop FXID (cf. sfizz)
          end
        elseif blk.vital_chunk then
          local b64 = read_file(root .. "/reaper/FXChains/" .. blk.vital_chunk)
          if b64 then
            local okv = reaper.TrackFX_SetNamedConfigParm(tr, engine, "vst_chunk", (b64:gsub("%s+$", "")))
            log("  vital: état " .. blk.vital_chunk .. " -> vst_chunk " .. tostring(okv))
          else
            log("  ⚠ vital: chunk introuvable " .. blk.vital_chunk)
          end
        end
        set_block_enabled(tr, blk, fxs, engine)                    -- bypass = coupe le moteur (le note-zone / le traducteur restent actifs)
        if blk.type == "vital" then
          apply_zone(tr, fxs, blk)                                 -- vital : preset via vst_chunk ; la zone est à part
          -- macros (potards de feuille 2026-07-23) : SEULS params écrits au moteur, APRÈS le
          -- vst_chunk (l'état les écraserait sinon). preset/zone exclus (gérés au-dessus).
          if blk.params then
            local mp = {}
            for k, v in pairs(blk.params) do
                    if k:match("^macro[1-4]$") or k == "fcut" or k == "rmix" or k == "dmix" or k == "vol" then mp[k] = v end
                  end
            if next(mp) then apply_block_params(tr, fxs, blk.type, mp, effects) end
          end
        elseif blk.params then apply_block_params(tr, fxs, blk.type, blk.params, effects) end
        -- VST Host : son état natif (vst_chunk, posé avec ses réglages) peut contenir le bypass de
        -- l'hôte — on REPOSE donc celui du bloc après, il reste la source de vérité.
        -- ⚠ Pour ce bloc SEULEMENT. La proposition d'origine déplaçait ici le bypass de TOUS les
        -- blocs : sur le rack, un bloc éteint par la scène restait alors allumé pendant le
        -- chargement de son fichier et la pose de ses réglages. C'est la fonction où une capture
        -- NAM se charge en tâche de fond pendant qu'on opère sa piste (CLAUDE.md, « le chunk d'une
        -- piste MENT ») : on n'y change pas l'ordre des gestes sans mesure. L'ordre du rack est
        -- celui d'avant le portage.
        if blk.type == "vst-host" then set_block_enabled(tr, blk, fxs, engine) end
        -- ⚠ L'ARP EN DERNIER, et c'est structurel : poser un FX DÉCALE les index de tous ceux
        -- qui suivent, donc `fxs` (calculé plus haut) devient périmé à l'instant de l'insertion.
        -- Tout ce qui s'en sert — zone, vst_chunk, macros, params — doit être passé AVANT.
        if ARP_TYPES[blk.type] then apply_vital_arp(tr, fxs, blk) end
        -- utility/volume RÉUTILISÉ (piste en REUSE, FX_INIT ne repasse pas) : re-neutralise le
        -- plafond « Max Volume (dB) » (défaut 0 dBFS = clippeur — bug volume 2026-07-23)
        if blk.type == "volume" or blk.type == "clean-boost" then
          for p = 0, reaper.TrackFX_GetNumParams(tr, engine) - 1 do
            local _, pnm = reaper.TrackFX_GetParamName(tr, engine, p, "")
            if (pnm or ""):lower():find("max") then
              local _, _, mx = reaper.TrackFX_GetParam(tr, engine, p)
              reaper.TrackFX_SetParam(tr, engine, p, mx or 150)
            end
          end
        end
      end
    end
  end

  -- PHASE C : params des blocs CŒUR (ampli + cab). Le cœur est un RfxChain fondu (NAM + IR bakés) sans
  -- estampille blk.id, donc invisible aux phases A/B ; on localise chaque plugin par NOM et on applique
  -- ses params via le même apply_block_params (match par nom : Input→Input Lvl, Level→Wet Signal Level).
  for _, blk in ipairs(spec.blocks or {}) do
    if core[blk.type] then
      local needle = (blk.type == "cab") and "ir convolver" or "neural amp"
      local fx = core_fx_index(tr, blk)
      if fx >= 0 then
        apply_core_params(tr, fx, blk, spec, effects)
        apply_core_enabled(tr, spec, blk)                        -- l'état de scène du cœur, dès le build
      else log("  ⚠ " .. needle .. " introuvable : bloc '" .. tostring(blk.type) .. "' ignoré") end
    end
  end
end

------------------------------------------------------- LIVE-MAP (pédale EXP -> param en temps réel)
-- Écrit presets/.livemap.json : pour CHAQUE bloc posé, la piste (1-based), l'index FX et, par potard,
-- l'index de param + sa plage NATIVE (pmin/pmax lus au TrackFX_GetParam). Le bridge s'en sert pour
-- pousser la pédale EXP en OSC normalisé (/track/N/fx/M/fxparam/P/value) SANS rebuild ni Lua.
local function livemap_entry(tr, fx, id, btype, effects, out, native_core)
  local schema = effects[btype]
  local tnum = math.floor(reaper.GetMediaTrackInfo_Value(tr, "IP_TRACKNUMBER"))
  local ps = {}
  for _, def in ipairs((schema and schema.params) or {}) do
    if def.type ~= "enum" and def.type ~= "bool" and def.type ~= "kitref" and def.type ~= "midilist" then   -- contenu, pas un slider (P5)
      local map = def.map
      local native_name = native_core and ((btype == "cab" and def.id == "level") and "Output" or
                           (def.id == "input" and "Input" or def.id == "output" and "Output"))
      local pidx
      if native_core then
        pidx = native_name and find_param_exact(tr, fx, native_name)
      else
        if schema and schema.windows_strict then pidx = find_param_exact(tr, fx, def.name)
        else pidx = (map and map.idx) or find_param_by_name(tr, fx, def.name) or def.num_index end
      end
      if pidx and pidx >= 0 and pidx < reaper.TrackFX_GetNumParams(tr, fx) then
        local _, mn, mx = reaper.TrackFX_GetParam(tr, fx, pidx)
        if native_core then
          mn, mx = native_name == "Input" and -20 or -40, native_name == "Input" and 20 or 40
          if btype == "cab" then              -- même décalage qu'apply_core_params : +18 dB de compensation
            local comp = NAM_IR_COMP_DB or 18
            mn, mx = mn - comp, mx - comp
          end
        elseif schema and schema.windows_strict and map and map.mode ~= "raw" then
          mn, mx = tonumber(def.min) or 0, tonumber(def.max) or 1
        end
        ps[#ps + 1] = string.format('"%s":{"p":%d,"pmin":%.6f,"pmax":%.6f}', def.id, pidx, mn or 0, mx or 1)
      end
    end
  end
  out[#out + 1] = string.format('"%s":{"track":%d,"fx":%d,"type":"%s","params":{%s}}',
    id, tnum, fx, btype, table.concat(ps, ","))
end

-- Seconde passe différée (0,35 s : un bloc audio a tourné, le plugin a fini de se reconfigurer) pour les blocs
-- `late_params` ; chaque entrée n'est rejouée qu'une fois (params._late), par le même chemin que la première.
function flush_late_params(effects)
  if #_LATE == 0 then return end
  local todo = _LATE
  _LATE = {}
  local gen = _BUILD_GEN
  local t0 = reaper.time_precise()
  local passes = { 0.35, 1.2 }                            -- deux passes : si le fil audio était figé (IR, NAM) à la première
  local pi = 1
  local function go()
    if gen ~= _BUILD_GEN then return end                   -- un autre build est passé : ses propres passes feront foi
    if reaper.time_precise() - t0 < passes[pi] then reaper.defer(go) return end
    local n = 0
    for _, e in ipairs(todo) do
      if reaper.ValidatePtr2(0, e.track, "MediaTrack*") then
        local fx = e.fx
        if e.guid then                                     -- l'index peut avoir bougé : le FX se retrouve par son GUID
          fx = nil
          for i = 0, reaper.TrackFX_GetCount(e.track) - 1 do
            if reaper.TrackFX_GetFXGUID(e.track, i) == e.guid then fx = i break end
          end
        end
        if fx then
          local p = {}
          for k, v in pairs(e.params) do p[k] = v end
          p._late = true
          apply_block_params(e.track, fx, e.btype, p, effects)
          n = n + 1
        end
      end
    end
    log(string.format("late params : passe %d, %d bloc(s) réécrits", pi, n))
    pi = pi + 1
    if passes[pi] then reaper.defer(go) end
  end
  reaper.defer(go)
end

local function write_livemap(root, plan, created, effects)
  local out = {}
  for _, e in ipairs(created) do
    local tr = e.tr
    for i = 0, reaper.TrackFX_GetCount(tr) - 1 do                    -- blocs estampillés (hors-cœur)
      local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
      local id = ok and nm and nm:match("^golem:(.+)$")
      -- un bloc keys porte 2 FX golem:<id> (note-zone + moteur) : on N'ÉMET la livemap QUE pour le
      -- moteur (potards EXP). Le note-zone est ignoré ici -> pas d'entrée id dupliquée dans le JSON.
      local _, fxnm = reaper.TrackFX_GetFXName(tr, i, "")
      local is_zone = fxnm and fxnm:lower():find("note-zone", 1, true)
      local is_native_core = e.spec.native_core and
                             (id == e.spec.native_core.amp_id or id == e.spec.native_core.cab_id)
      if id and not is_zone and not is_native_core then
        local btype
        for _, b in ipairs(e.spec.blocks or {}) do if b.id == id then btype = b.type; break end end
        if btype then livemap_entry(tr, i, id, btype, effects, out) end
      end
    end
    for _, b in ipairs(e.spec.blocks or {}) do                       -- cœur (NAM/IR, non estampillé)
      if b.id and (b.type == "amp" or b.type == "amp-nam" or b.type == "cab") then
        local fx = core_fx_index(tr, b)
        if fx >= 0 then livemap_entry(tr, fx, b.id, b.type, effects, out, e.spec.native_core) end
      end
    end
  end
  -- tmp + rename (audit 2026-10-15) : le bridge en déduit rebuild ou scene_apply ; une lecture à moitié écrite
  -- faisait un rebuild pour rien
  local dst = root .. "/presets/.livemap.json"
  local f = io.open(dst .. ".tmp", "w")
  if f then
    f:write('{"preset":"' .. tostring(plan.id) .. '","blocks":{' .. table.concat(out, ",") .. '}}')
    f:close()
    runtime.replace(dst .. ".tmp", dst)
    log("livemap : " .. #out .. " bloc(s) -> .livemap.json")
  end
end

------------------------------------------------------ KNOB-MAP (potards AKAI -> params en temps réel)
-- Écrit presets/.knobmap.json : pour chaque bloc keys porteur d'un schéma `knobs` (vital=banque A,
-- ep=banque B dans effects.json), associe chaque CC (config/knobs.json, positionnel avec targets) au
-- param cible RÉSOLU PAR NOM. golem_knobs.lua lit ce fichier, poll la gmem golem_knobs (alimentée par
-- knob-tap sur le root) et pilote le param en TrackFX_SetParamNormalized(val/127). Format (tableau) :
--   [{ "cc":<int>, "track":"<nom piste>", "stamp":"golem:<id>"|"<type>:<id>:synth", "pname":"<param>" }]
-- Résolution : d'abord les FX estampillés golem:<id> du bloc (moteur/note-zone) par NOM EXACT ; sinon
-- l'instance moteur du bloc estampillée "<type>:<id>:synth" (Dexed pour ep, LV2 pour organ) — les
-- params Cutoff/Resonance/Output y vivent, pas sous golem:<id>. Le stamp est robuste aux décalages
-- d'index (golem_knobs re-résout par nom, cache invalidé au mtime du fichier).
local function jstr(x)                                             -- échappe pour le JSON (guillemets/backslash)
  return '"' .. tostring(x):gsub('[%c"\\]', function(c)
    if c == '"' then return '\\"' end
    if c == '\\' then return '\\\\' end
    return string.format('\\u%04x', c:byte())
  end) .. '"'
end

-- (stamp, param_index) du param nommé `pname` pour le bloc `blk` sur la piste `tr`, ou nil.
local function resolve_knob_target(tr, blk, pname)
  local fxs = block_fx_list(tr, blk.id)                            -- FX estampillés golem:<id> (moteur + note-zone)
  for _, fx in ipairs(fxs) do
    local pi = find_param_exact(tr, fx, pname)                     -- nom EXACT (pas de sous-chaîne : Vital a ~3000 params)
    if pi then return "golem:" .. tostring(blk.id), pi end
  end
  local synth = tostring(blk.type) .. ":" .. tostring(blk.id) .. ":synth"   -- ep/organ : moteur hors golem:
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local ok, nm = reaper.TrackFX_GetNamedConfigParm(tr, i, "renamed_name")
    if ok and nm == synth then
      local pi = find_param_exact(tr, i, pname)
      if pi then return synth, pi end
      return nil                                                   -- l'instance synth existe mais pas le param -> log en aval
    end
  end
  return nil
end

local function write_knobmap(root, plan, created, effects)
  -- la calibration LOCALE, sinon la graine suivie (knobs.json est sorti du dépôt le 2026-10-03)
  local cfgraw = read_file(root .. "/config/knobs.json") or read_file(root .. "/config/knobs.default.json")
  local cfg = cfgraw and json_decode(cfgraw) or {}
  local banks = { A = cfg.bankA, B = cfg.bankB }
  local entries, misses = {}, 0
  for _, e in ipairs(created) do
    for _, blk in ipairs(e.spec.blocks or {}) do
      local sch = effects[blk.type]
      local kn = sch and sch.knobs
      if kn and blk.id then
        local ccs = banks[kn.bank]
        if not ccs then log("  ⚠ knobmap : banque '" .. tostring(kn.bank) .. "' absente de config/knobs.json") end
        for i, pname in ipairs(kn.targets or {}) do
          local cc = ccs and ccs[i]
          if cc then
            local stamp, pi = resolve_knob_target(e.tr, blk, pname)
            if stamp then
              entries[#entries + 1] = "{" .. table.concat({
                '"cc":' .. tostring(math.floor(cc)),
                '"track":' .. jstr(track_name(e.tr)),
                '"stamp":' .. jstr(stamp),
                '"pname":' .. jstr(pname) }, ",") .. "}"
            else
              misses = misses + 1
              log(string.format("  ⚠ knobmap : param '%s' introuvable pour bloc %s (%s) sur %s",
                  tostring(pname), tostring(blk.id), tostring(blk.type), track_name(e.tr)))
            end
          end
        end
      end
    end
  end
  local body = "[" .. table.concat(entries, ",") .. "]"
  local dst = root .. "/presets/.knobmap.json"
  local tmp = dst .. ".tmp"
  local f = io.open(tmp, "w")
  if f then
    f:write(body); f:close()
    runtime.replace(tmp, dst)                                   -- os.remove avant : une fenêtre sans fichier (Linux)
    log("knobmap : " .. #entries .. " CC mappé(s)" .. (misses > 0 and (" (" .. misses .. " manqué·s)") or "") .. " -> .knobmap.json")
  else
    log("  ⚠ knobmap : écriture impossible")
  end
end

------------------------------------------------------------------------- LOOPER (Looper)
-- Piste PERMANENTE (tant que preset.looper.enabled) portant UNE instance golem_super8 (fork Super8) :
-- 3 paires stéréo liées = loops GTR/VOX/SYN, alimentées par des sends I_DSTCHAN 0/2/4 depuis les
-- pistes de SORTIE de chaque path. Le FX est PRÉSERVÉ s'il existe déjà (les loops survivent aux
-- rebuilds même-preset) ; la piste est supprimée quand le preset n'a pas de looper. Les commandes
-- arrivent par le slider "GoleM Cmd" (OSC FX_PARAM, cf. bridge/looper.py) — pas de MIDI hardware.
local LOOPER_TRACK     = "Looper"
local OLD_LOOPER_TRACK = "Sandbox #Looper"        -- ancien nom : migré au vol dans ensure_looper
local LOOPER_FX_NAMES = { "JS:golem/golem_super8",                       -- chemin relatif Effects/ (forme sûre, sans espace)
                          "GoleM Super8 looper (golem_super8)",          -- desc (nom du browser FX)
                          "JS: golem/golem_super8", "golem_super8", "JS: golem_super8" }

local function find_looper_fx(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    local low = (nm or ""):lower()
    if low:find("golem", 1, true) and low:find("super8", 1, true) then return i end
  end
  return -1
end

-- La piste looper est PERMANENTE : créée UNE fois, JAMAIS supprimée, le JSFX ajouté UNE fois et
-- JAMAIS retiré. Un preset sans looper la MUTE (pas de suppression). C'est délibéré : supprimer une
-- piste / ré-instancier un gros JSFX à chaque changement de preset = chirurgie lourde qui courait avec
-- les chargements d'IR asynchrones (ZConvolv) du rebuild -> corruption de tas / segfault (2026-07-10).
-- Ainsi le rebuild d'un preset looper redevient aussi léger que celui d'un preset normal (qui, lui,
-- encaisse les rebuilds rapides). Seuls 3 sends sont (re)câblés.
local function ensure_looper(plan, created)
  local tr = find_track(LOOPER_TRACK)
  if not tr then                                          -- migration : renomme l'ancienne piste (loops préservées)
    local old = find_track(OLD_LOOPER_TRACK)
    if old then
      reaper.GetSetMediaTrackInfo_String(old, "P_NAME", LOOPER_TRACK, true)
      tr = old
      log("looper : piste migrée « " .. OLD_LOOPER_TRACK .. " » -> « " .. LOOPER_TRACK .. " »")
    end
  end
  local want = (plan.looper ~= nil)
  if not tr then
    if not want then return end                           -- aucune piste, aucun looper : rien à faire
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", LOOPER_TRACK, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 8)       -- 4 paires stéréo sur les pins 1-8
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)   -- audio via receives, pas d'entrée
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
    log("looper : piste créée (permanente)")
  end

  -- FX permanent : ajouté une seule fois, jamais retiré (loops préservées, zéro ré-instanciation)
  local fx = find_looper_fx(tr)
  if fx < 0 then
    for _, nm in ipairs(LOOPER_FX_NAMES) do
      local r = add_fx(tr, nm, false, -1)
      if r and r >= 0 then fx = find_looper_fx(tr); break end
    end
    if fx < 0 then log("⚠ looper : JSFX golem_super8 introuvable (provision/link-reaper.sh fait ?)")
    else log("looper : golem_super8 ajouté (permanent)") end
  end

  -- receives : toujours purgés d'abord (côté looper)
  for si = reaper.GetTrackNumSends(tr, -1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, -1, si) end

  if not want then
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 1)        -- preset sans looper : piste MUETTE (conservée)
    for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
    return
  end

  reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
  -- ARMÉE en « aucun » (audit 2026-10-15) : ses ordres arrivent par gmem, que REAPER ne voit pas — le motif des
  -- cinq pistes de service sorties du graphe vivant (CLAUDE.md). Si une scène mute toutes ses sources, elle
  -- risquait d'en sortir et de figer ses boucles. I_RECMODE 2 : vivante, hors d'état d'écrire un fichier.
  if reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") ~= 1 or reaper.GetMediaTrackInfo_Value(tr, "I_RECMODE") ~= 2 then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)       -- comme les autres pistes de service (sans entrée : rien à entendre)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  end
  -- ── UN SEND PAR LIGNE DE LA TABLE DE BOUCLES (docs/looper.md §1 et §6) ────────────────────
  -- Avant : la destination était DÉRIVÉE du numéro d'entrée (`PAIR_DST[e.input]`) — une entrée,
  -- une paire, point. Personne n'avait choisi ça, et ça coûtait cher : un guitariste seul avait
  -- une boucle utilisable sur trois (les switches 7 et 8 enregistraient le silence de deux
  -- entrées vides), et « deux boucles de la même source » était INEXPRIMABLE.
  -- Maintenant : la table dit qui alimente quoi. L'ORDRE des lignes fait la paire — ligne n ->
  -- canaux (2n+1)·(2n+2) -> notes du slot n côté bridge. Plusieurs lignes peuvent partager une
  -- source : c'est tout l'objet du contrat.
  -- LOT 2 : la source d'une boucle se résout PAR LE PLAN — un id de path ("guitar", "voice",
  -- "keys", ou celui d'une lane future), un numéro d'entrée ("4"), ou la lettre legacy 1/2/k.
  -- L'ancienne table fermée {1,2,k} rendait une 4e lane inexprimable comme source (audit §3).
  local SRC_IN = { ["1"] = 1, ["2"] = 2, ["k"] = 3 }
  for _, path in ipairs(plan.paths or {}) do
    local pin
    for _, spec in ipairs(path.tracks or {}) do
      if spec.input ~= nil then pin = spec.input; break end
    end
    if pin ~= nil and path.id then SRC_IN[tostring(path.id)] = pin end
  end
  local loops = plan.looper and plan.looper.loops
  if type(loops) ~= "table" or #loops == 0 then          -- vieux plan / rappel direct : le défaut (l'ordre des lignes fait le slot ; sw informatif ici)
    loops = { { sw = 6, src = "1" }, { sw = 7, src = "2" }, { sw = 8, src = "k" } }
    log("looper : plan sans table de boucles -> défaut lanes 1/2/k sur les slots 1/2/3")
  end
  for li, row in ipairs(loops) do
    local want_in = SRC_IN[tostring(row.src or "")] or tonumber(row.src)
    local dst = (li - 1) * 2
    local fed = 0
    for _, e in ipairs(created) do
      local is_child = (e.spec.role == "branch" and e.spec.folder == "child")
      if want_in and e.spec.out and not is_child and e.input ~= nil
         and tonumber(e.input) == want_in then
        -- ⚠ L'INDEX EST LA VALEUR RETOURNÉE PAR CreateTrackSend. C'était la formule
        -- « catégorie 0 » (numHW + numSends - 1) — un NO-OP silencieux, le même piège qui a
        -- coûté 24 prises au perf-rec (CLAUDE.md). Effet ici : I_DSTCHAN n'était JAMAIS appliqué,
        -- donc les paires 2 et 3 arrivaient sur les canaux 1/2 du looper au lieu de 3/4 et 5/6
        -- — tout entrait dans la première boucle. Corrigé et vérifié le 2026-08-08.
        local snd = reaper.CreateTrackSend(e.tr, tr)
        if not snd or snd < 0 then
          log("  ⚠ loop " .. li .. " <- " .. e.rname .. " : CreateTrackSend a échoué")
        else
          reaper.SetTrackSendInfo_Value(e.tr, 0, snd, "I_SENDMODE", 0)  -- post-fader (= ce qu'on entend)
          reaper.SetTrackSendInfo_Value(e.tr, 0, snd, "I_DSTCHAN", dst)
          -- ⚠ AUCUN MIDI SUR CE SEND (31 = « no MIDI »). Un send Reaper transporte le MIDI par
          -- défaut, tous canaux. Or golem_super8 est nativement piloté par des NOTES (36/37,
          -- 41/42, 45/46, 50/51, 21 play-all, 20 kill-all) — exactement la plage des pads d'un
          -- MPK Mini. Les notes du clavier descendaient donc dans le looper par le send de la
          -- lane Keys, et le Super8 les prenait pour des ordres : le pad 3 faisait alterner une
          -- boucle entre play et stop sans fin (vécu le 2026-08-08).
          -- Ce piège DORMAIT : il ne s'est réveillé que le jour où l'AKAI a été réactivé dans
          -- Reaper (masque midiins remis à jour le même après-midi). Le son passe, le MIDI non.
          reaper.SetTrackSendInfo_Value(e.tr, 0, snd, "I_MIDIFLAGS", 31)
          -- on RELIT ce que Reaper a retenu : une écriture de send qui ne prend pas est
          -- silencieuse, et c'est précisément comme ça que ce bug a vécu six semaines.
          local got = reaper.GetTrackSendInfo_Value(e.tr, 0, snd, "I_DSTCHAN")
          local mf = reaper.GetTrackSendInfo_Value(e.tr, 0, snd, "I_MIDIFLAGS")
          fed = fed + 1
          log(string.format("  loop %d (SW%s « %s ») <- %s (paire %d, I_DSTCHAN demandé %d, relu %d · MIDI %s)%s",
                            li, tostring(row.sw), tostring(row.label or row.src),
                            e.rname, dst / 2 + 1, dst, got,
                            (mf == 31) and "coupé" or ("OUVERT (" .. tostring(mf) .. ") !"),
                            (got == dst) and "" or "  <<< L'ÉCRITURE N'A PAS PRIS"))
        end
      end
    end
    -- Une ligne dont la source n'existe pas dans CE preset (lane vide, ou coupée par le mode)
    -- enregistrerait du silence. On ne crée pas le send, et on le DIT : c'est exactement la
    -- panne qu'on vient de supprimer, elle ne doit pas revenir en silence (docs/looper.md §7).
    if fed == 0 then
      log(string.format("  ⚠ loop %d (SW%s) <- « %s » : aucune source dans ce preset — boucle MUETTE",
                        li, tostring(row.sw), tostring(row.src)))
    end
  end

  -- sortie hardware OUT 1/2 stéréo, SANS route_monitor (qui forcerait I_NCHAN=2 — on a besoin de 8).
  -- Le fork replie toutes les paires sur les canaux 1-2 -> le send hw source 1-2 suffit.
  for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
  local hw = reaper.CreateTrackSend(tr, nil)
  reaper.SetTrackSendInfo_Value(tr, 1, hw, "I_DSTCHAN", 0)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
  log("looper : sortie OUT 1/2")
end

-- Signature d'INSTANCIATION FX d'un spec (ce qui, s'il change, impose de re-créer les FX + recharger
-- les fichiers) : role, contenu du .RfxChain (HASH, pas juste le nom — le Designer réécrit le même nom
-- avec de nouveaux fichiers), core_types, et par bloc type/id/file/cab_file/vital_chunk/dx7_bank + merge_gain.
-- NB ep : dx7_bank EST dans la signature (changer de banque = rebuild), PAS dx7_patch (le patch reste un
-- param scène-first -> Program Change à chaud via le JSFX dx7-ctl, zéro rebuild).
-- N'inclut AUCUN potard : une édition de param ne réinstancie pas (donc pas de reload IR).
local function fx_signature(root, spec)
  -- PAS le NOM du .RfxChain (préfixé par preset) mais son CONTENU (hash) : deux presets à chaîne
  -- identique (ex. une copie) partagent la signature -> REUSE au switch -> pas de reload IR (anti-crash).
  local parts = { "role=" .. tostring(spec.role), "mg=" .. tostring(spec.merge_gain) }
  if DESKTOP_FX then
    local backend = read_file(root .. "/library/catalog/" .. DESKTOP_TABLE)
    parts[#parts + 1] = "windows-fx=" .. (backend and tostring(cheap_hash(backend)) or "missing")
  end
  if spec.rfxchain then
    local rfx = read_file(root .. "/reaper/FXChains/" .. spec.rfxchain)
    parts[#parts + 1] = "h=" .. (rfx and tostring(cheap_hash(rfx)) or ("MISS:" .. spec.rfxchain))
  end
  if spec.native_core then
    local c = spec.native_core
    parts[#parts + 1] = "nam-vst3:" .. tostring(c.model) .. ":" .. tostring(c.ir) .. ":" ..
                        tostring(c.amp_id) .. ":" .. tostring(c.cab_id) .. ":" .. tostring(c.default_ir)
  end
  for _, ct in ipairs(spec.core_types or {}) do parts[#parts + 1] = "c:" .. tostring(ct) end
  for _, b in ipairs(spec.blocks or {}) do
    -- kit_pads : concat note:file:mode:level de chaque pad -> un changement de kit (par scène ou édition)
    -- fait bouger la signature -> rebuild de la lane Keys (pas un simple scene_apply). Vide sinon.
    local kp = ""
    if b.kit_pads then
      local seg = {}
      for _, pad in ipairs(b.kit_pads) do
        seg[#seg + 1] = tostring(pad.note) .. ":" .. tostring(pad.file) ..
                        ":" .. tostring(pad.mode) .. ":" .. tostring(pad.level)
      end
      kp = table.concat(seg, ",")
    end
    -- vital_chunk : le NOM du .vital.b64 est DÉTERMINISTE (preset__track__bloc) — le comparer
    -- rendait la signature aveugle à un changement de preset Vital (REUSE -> son inchangé,
    -- bug UI 2026-07-19). Même remède que les .RfxChain : hash du CONTENU.
    local vc = b.vital_chunk or ""
    if b.vital_chunk then
      local raw = read_file(root .. "/reaper/FXChains/" .. b.vital_chunk)
      vc = raw and ("vh:" .. tostring(cheap_hash(raw))) or ("MISS:" .. b.vital_chunk)
    end
    if b.vitalium_state then                                       -- Vitalium LV2 : même piège, même remède
      local raw = read_file(root .. "/reaper/FXChains/" .. b.vitalium_state)
      vc = vc .. (raw and ("|lh:" .. tostring(cheap_hash(raw))) or ("|MISS:" .. b.vitalium_state))
    end
    -- drumkit : kit + banque + descripteur du module + table de traduction -> un kit changé par scène,
    -- ou un autre module branché sur le port, rebâtit la lane (la table vit dans gmem, écrite au build)
    local dk = ""
    if b.type == "drumkit" then
      -- l'ENSEMBLE des kits posés (union) — pas le kit de la scène, qui ne fait que basculer des enables
      local seg = { tostring(b.drum_desc) }
      for _, e in ipairs((b.engines and #b.engines > 0) and b.engines or { b }) do
        seg[#seg + 1] = table.concat({ tostring(e.kit_id), tostring(e.kit_engine), tostring(e.kit_bank), tostring(e.drum_slot),
                                       tostring(e.kit_drumkit), tostring(e.kit_midimap) }, "/")
        for _, n in ipairs(e.drum_map or {}) do seg[#seg + 1] = tostring(n) end
        for _, k in ipairs({ "cc", "open_value", "closed_value", "band_a", "band_b", "positions", "closed", "half", "open" }) do
          seg[#seg + 1] = tostring((e.drum_hh or {})[k])
        end
      end
      dk = table.concat(seg, ",")
    end
    parts[#parts + 1] = table.concat({ "b", b.type or "", b.id or "", b.plugin or "", b.file or "",
                                        b.cab_file or "", vc, b.dx7_bank or "", b.sfz_file or "", kp, dk, b.capture_chunk or "" }, "|")
  end
  return table.concat(parts, "\31")
end

-- FX INCHANGÉS (signature identique) : on ne touche NI l'instanciation NI les fichiers (pas de reload
-- IR/NAM), on ré-applique seulement enable + potards — copie EXACTE de la boucle de reapply_scene
-- (chemin scene_apply prouvé, sans crash). Aucune chirurgie -> rien à libérer pendant un chargement async.
local function apply_track_params(root, tr, spec, effects)
  for _, blk in ipairs(spec.blocks or {}) do
    local is_core = (blk.type == "amp" or blk.type == "amp-nam" or blk.type == "cab")
    local eng = effects[blk.type] and effects[blk.type].engine
    if not is_core and blk.id and eng ~= "midi" and eng ~= "virtual" and blk.type ~= "pads" then
      local fxs = block_fx_list(tr, blk.id)
      if #fxs > 0 then
        local eng2 = fxs[1]
        -- même piège que la matérialisation : fxs[1] = note-zone JS, le MOTEUR est le VST/LV2
        if blk.type == "vital" then eng2 = instrument_engine(tr, fxs) end
        if blk.type == "vital" then
          apply_zone(tr, fxs, blk)
          if blk.params then                                       -- macros par scène (cf. matérialisation)
            local mp = {}
            for k, v in pairs(blk.params) do
                    if k:match("^macro[1-4]$") or k == "fcut" or k == "rmix" or k == "dmix" or k == "vol" then mp[k] = v end
                  end
            if next(mp) then apply_block_params(tr, fxs, blk.type, mp, effects) end
          end
        elseif blk.params then apply_block_params(tr, fxs, blk.type, blk.params, effects) end
        if ARP_TYPES[blk.type] then apply_vital_arp(tr, fxs, blk, true) end   -- scène : reconfig seule
        set_block_enabled(tr, blk, fxs, eng2)                      -- le MOTEUR ; le note-zone / le traducteur restent actifs
      end
    end
  end
  for _, blk in ipairs(spec.blocks or {}) do
    if (blk.type == "amp" or blk.type == "amp-nam" or blk.type == "cab") then
      local fx = core_fx_index(tr, blk)
      if fx >= 0 then apply_core_params(tr, fx, blk, spec, effects) end
      apply_core_enabled(tr, spec, blk)                          -- enable du cœur (mesuré 2026-09-14)
    end
  end
end

-- Supprime, EN FIN de build, les sous-pistes transitoires que le NOUVEAU plan n'utilise plus. Appelé
-- après la reconstruction : ces pistes n'ont PAS été touchées ce build (aucun IR rechargé) -> aucun
-- ZConvolv en vol -> DeleteTrack sûr (contrairement à l'ancien delete-au-début qui causait le crash).
local function delete_unwanted_subtracks(wanted)
  local n = 0
  for i = reaper.CountTracks(0) - 1, 0, -1 do
    local tr = reaper.GetTrack(0, i)
    local nm = track_name(tr)
    if nm:match("^" .. SANDBOX_PREFIX .. "%d+[/#]") and not wanted[nm] then
      reaper.DeleteTrack(tr); n = n + 1
    end
  end
  if n > 0 then log("sandbox : " .. n .. " sous-piste(s) obsolète(s) supprimée(s) (fin de build)") end
  return n
end

-- Remet les sous-pistes dans l'ordre canonique EN FIN de projet, ordre de created[] (parent merge
-- d'abord, puis les enfants) : la disposition exacte de l'ancien delete+recreate, indispensable au
-- folder (PASSE 2 pose ensuite les I_FOLDERDEPTH). FX-neutre. Appelé UNIQUEMENT si la topologie change.
-- ⚠ ReorderSelectedTracks(idx) insère AVANT `idx` ; idx = nb de pistes => insère APRÈS la dernière = fin.
-- (le -1 initial déplaçait vers l'AVANT et inversait l'ordre -> folder cassé, corrigé 2026-07-10.)
local function reorder_subtracks(created)
  for _, e in ipairs(created) do                          -- aplatit d'abord : pas de folder-depth périmé qui traîne des enfants au déplacement
    if e.spec.input == nil then reaper.SetMediaTrackInfo_Value(e.tr, "I_FOLDERDEPTH", 0) end
  end
  for _, e in ipairs(created) do
    if e.spec.input == nil then                           -- les roots restent en place
      reaper.SetOnlyTrackSelected(e.tr)
      reaper.ReorderSelectedTracks(reaper.CountTracks(0), 0)   -- à la fin (index = nb de pistes)
    end
  end
end

----------------------------------------------------- ZONES CLAVIER : dépliage en dossier (lane Keys P2)
-- Une piste midi:true portant PLUSIEURS blocs-instruments (vital/piano/organ/ep) empilerait ses
-- moteurs EN SÉRIE sur une seule piste -> ils se marchent dessus (le 2e mixe/écrase l'audio du 1er).
-- On DÉPLIE alors la spec en DOSSIER, calqué sur les splits guitare (root monitoré -> sends -> pistes
-- de folder) :
--   * ROOT (= la piste d'entrée, Sandbox #Input N) : garde l'entrée MIDI armée+monitorée, PERD son
--     `out`, et envoie son MIDI monitoré à chaque enfant (midi_sends_to). C'est la voie FIABLE pour un
--     rig monitoré à l'arrêt : une seule piste arme le device, le MIDI descend par send track->track
--     (les enfants NON armés jouent quand même — routage MIDI standard Reaper).
--   * MERGE parent (sous-piste, folder ouvert) : porte le `out` -> somme des enfants vers le hardware.
--   * Un ENFANT par bloc-instrument (sous-piste, folder child, B_MAINSEND=1) : chaîne = note-zone
--     (golem:<id>) EN TÊTE puis le moteur du bloc comme d'habitude. pads (audio, mais pas de zone) a
--     aussi sa propre enfant ; les blocs midi/virtual (gérés par le bridge) restent sur le root.
-- UN SEUL bloc-instrument : pas de dossier (mono-piste conservée) mais la note-zone est quand même
-- posée en tête (blk.zone) pour offrir lo/hi/transpose. Le dépliage est fait ICI, à la matérialisation
-- (le bridge/compile n'en sait rien) ; il tourne aussi dans reapply_scene pour que les scènes trouvent
-- les enfants. Idempotent & déterministe (mêmes noms d'un recall à l'autre).
local KEYS_INSTR = { vital = true, piano = true, organ = true, ep = true, drumkit = true }
-- drumkit : instrument d'une lane Drums (docs/drums-kit.md lot 2) — pas de note-zone (le traducteur
-- golem_drumtrans est SA tête de chaîne), donc exclu des `b.zone = true` ci-dessous.
local NO_ZONE = { drumkit = true }
local function expand_keys(plan, effects)
  for _, path in ipairs((plan and plan.paths) or {}) do
    local nt = {}
    for _, spec in ipairs(path.tracks or {}) do
      local ninstr, npads = 0, 0
      if spec.midi then for _, b in ipairs(spec.blocks or {}) do
        if KEYS_INSTR[b.type] then ninstr = ninstr + 1 elseif b.type == "pads" then npads = npads + 1 end
      end end
      -- PADS + INSTRUMENT (2026-10-13) : quand le contrôleur sépare ses pads par CANAL (spec.midi_ch, l'AKAI
      -- programmé par le rack), les pads ont LEUR sous-piste et chacun reçoit SON canal — sinon un pad jouait
      -- aussi une note dans Vital (même piste, mêmes notes). Sans canaux connus : comportement d'avant.
      local split_pads = spec.midi_ch and ninstr >= 1 and npads >= 1
      if ninstr >= 2 or split_pads then
        local rootspec = {}
        for k, v in pairs(spec) do rootspec[k] = v end          -- garde input/midi/midi_in/name
        rootspec.role = "main"; rootspec.out = nil; rootspec.out_sel = nil; rootspec.level = nil
        rootspec.folder = nil; rootspec.folder_of = nil
        rootspec.blocks = {}; rootspec.midi_sends_to = {}; rootspec.midi_send_ch = {}
        local mch = spec.midi_ch or {}
        local merge = { name = spec.name .. "/merge", role = "merge", folder = "parent",
                        out = spec.out, out_sel = spec.out_sel, level = spec.level, blocks = {} }
        nt[#nt + 1] = rootspec
        nt[#nt + 1] = merge
        for _, b in ipairs(spec.blocks or {}) do
          if KEYS_INSTR[b.type] then
            if not NO_ZONE[b.type] then b.zone = true end
            local child = { name = spec.name .. "/" .. tostring(b.id or b.type), role = "branch",
                            folder = "child", folder_of = merge.name, blocks = { b } }
            rootspec.midi_sends_to[#rootspec.midi_sends_to + 1] = child.name
            rootspec.midi_send_ch[child.name] = tonumber(mch.keys)
            nt[#nt + 1] = child
          elseif b.type == "pads" then                          -- audio mais pas de zone : sa propre enfant
            local child = { name = spec.name .. "/" .. tostring(b.id or b.type), role = "branch",
                            folder = "child", folder_of = merge.name, blocks = { b } }
            rootspec.midi_sends_to[#rootspec.midi_sends_to + 1] = child.name
            rootspec.midi_send_ch[child.name] = tonumber(mch.pads)
            nt[#nt + 1] = child
          else
            -- midi/virtual/mode : pas d'audio -> reste sur le root. Un effet AUDIO (comp, reverb…) va sur le MERGE :
            -- il traite la somme des instruments, comme sur la piste unique d'avant le dépliage. Avant 2026-10-13 il
            -- restait sur le root, qui ne porte que du MIDI : le compresseur de Loop Station ne traitait plus rien.
            local eng = effects and effects[b.type] and effects[b.type].engine
            if eng == "midi" or eng == "virtual" or eng == "mode" or not effects then
              rootspec.blocks[#rootspec.blocks + 1] = b
            else
              merge.blocks[#merge.blocks + 1] = b
            end
          end
        end
      else
        if spec.midi then for _, b in ipairs(spec.blocks or {}) do if KEYS_INSTR[b.type] and not NO_ZONE[b.type] then b.zone = true end end end
        -- une seule sorte de son sur la piste : son ENTRÉE n'écoute que son canal (les pads de l'AKAI programmé ne
        -- jouent plus de notes dans un patch Vital seul ; une lane de pads seule n'entend plus le clavier)
        if spec.midi and spec.midi_ch then
          if ninstr >= 1 and npads == 0 then spec.midi_in_ch = tonumber(spec.midi_ch.keys)
          elseif npads >= 1 and ninstr == 0 then spec.midi_in_ch = tonumber(spec.midi_ch.pads) end
        end
        nt[#nt + 1] = spec
      end
    end
    path.tracks = nt
  end
end

------------------------------------------------------------------------- MATÉRIALISATION (sandbox)
-- Matérialise le plan dans les 2 roots fixes "Sandbox #Input 1/2". Les sous-pistes d'un split sont
-- RÉUTILISÉES par nom d'un build à l'autre (comme les roots) : on ne reconstruit les FX (clear+build =
-- reload NAM/IR async) QUE si leur signature a changé, et on ne supprime les sous-pistes obsolètes
-- qu'EN FIN de build (jamais pendant qu'un IR charge). Sortie -> Master. Roots inutilisés vidés+mutés.
local function materialize(root, plan, mono_on)
  _BUILD_GEN = _BUILD_GEN + 1
  if not plan or not plan.paths then log("plan vide"); return end
  local effects = read_effects(root)
  local mixer_lv = read_mixer(root)                     -- trims du rig, reposés sur les sends recréés
  local mono_gain = (plan.mono_fallback and plan.mono_fallback.gain) or 0
  if mono_on == nil then mono_on = plan.mono_fallback and plan.mono_fallback.on == true end

  expand_keys(plan, effects)                            -- lane Keys : déplie en dossier si >=2 blocs-instruments (P2)

  sweep_legacy()                                        -- balaie uniquement les pistes legacy GoleM:* (sûr)

  ----------------------------------------- PASSE 1 : acquisition pistes (root ET sous-pistes RÉUTILISÉS) + FX gaté
  local created = {}          -- { {tr, spec, rname, sends[], folder_of} } dans l'ordre de création
  local names = {}            -- nom REMAPPÉ -> MediaTrack (pour sends_to / folder)
  local used_inputs = {}
  local wanted = {}           -- noms remappés utilisés CE build (les autres sous-pistes -> supprimées en fin)
  local any_fresh = false     -- une piste a été CRÉÉE ce build -> la topologie a changé (réordonner)
  for _, path in ipairs(plan.paths) do
    -- base = nom du root du path (la piste qui porte l'entrée) ; sroot = piste sandbox de cet input
    local base, input
    for _, spec in ipairs(path.tracks or {}) do
      if spec.input ~= nil then base, input = spec.name, spec.input; break end
    end
    if not base then log("path sans entrée, ignoré : " .. tostring(path.id))
    else
      local sroot = sandbox_name(input)
      used_inputs[input] = true
      local function remap(nm) return nm and (sroot .. nm:sub(#base + 1)) or nm end

      for _, spec in ipairs(path.tracks or {}) do
        local rname = remap(spec.name)
        local tr, fresh = nil, false
        if spec.input ~= nil then
          tr = find_track(sroot)                          -- RÉUTILISE le root (jamais recréé s'il existe)
          if not tr then
            -- LOT 2 (audit N lanes 2026-09-08) : un root MANQUANT est créé, audio comme MIDI. Avant,
            -- seule la lane MIDI l'était : un chemin audio `input=4` était jeté en silence — le
            -- projet golem-set.rpp ne porte que trois roots, et c'est le PLAN qui doit dire combien.
            local idx = reaper.CountTracks(0)
            reaper.InsertTrackAtIndex(idx, false)
            tr = reaper.GetTrack(0, idx); fresh = true
            log("root sandbox créé : " .. sroot .. (spec.midi and " (lane MIDI)" or (" (lane audio, In " .. tostring(input) .. ")")))
          end
          if not tr then log("⚠ root sandbox absent dans le projet : " .. sroot)
          else
            if not spec.midi then
              -- LOT 2 : la liaison entrée physique -> piste vient du PLAN, plus de la ligne REC du
              -- .rpp (elle n'était jamais écrite pour l'audio : audit 2026-09-08 §3 couplage 6).
              -- Mono : canal 0-based = input-1. (Les paires stéréo viendront avec le patch, lot 4.)
              -- LOT 5 : une paire stéréo (in_sel "3-4") = 1024 + canal 0-based du premier
              local want = tonumber(input) and (tonumber(input) - 1) or 0
              if spec.stereo then want = 1024 + want end
              if reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT") ~= want then
                reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", want)
                log("  in audio " .. sroot .. " <- In " .. tostring(input) .. (spec.stereo and " (paire stéréo)" or " (mono)"))
              end
            end
            if spec.midi then                             -- lane Keys / Drums : l'entrée est un contrôleur MIDI
              local dev, dname = keys_midi_dev(spec.midi_in, spec.midi_avoid)
              -- docs/drums-kit.md lot 2 : une lane DRUMS ne prend JAMAIS l'heuristique mpk/akai/hw: —
              -- sans son module branché elle reste sans entrée, et le dit (sinon l'AKAI jouait la batterie)
              if spec.midi_strict and (not dev or not spec.midi_in or dname ~= spec.midi_in) then
                log("  ⚠ lane Drums : module MIDI absent (hint " .. tostring(spec.midi_in) .. ") — entrée laissée VIDE"
                    .. (dev and (", pas de repli sur " .. tostring(dname)) or "") .. " · entrées MIDI vues : " .. midi_input_names())
                dev = nil
              end
              if dev then
                local ich = tonumber(spec.midi_in_ch) or 0       -- 0 = tous canaux ; 1-16 = ce canal seulement
                reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", 4096 + dev * 32 + ich)
                log("  in MIDI " .. sroot .. " <- dev " .. dev .. " (" .. tostring(dname) .. ")"
                    .. (ich > 0 and (" canal " .. ich) or ""))
              else
                log("  ⚠ contrôleur MIDI introuvable (hint " .. tostring(spec.midi_in) .. ") — lane Keys sans entrée")
              end
            end
            reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
            reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)   -- monitoring d'entrée live
            reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)  -- monitor-only : une entrée n'écrit jamais de fichier (perf-rec propre)
            reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
          end
        else
          tr = find_track(rname)                          -- SOUS-PISTE : RÉUTILISÉE par nom (plus de delete/recreate)
          if not tr then
            local idx = reaper.CountTracks(0)             -- absente -> créée (append, réordonnée plus bas)
            reaper.InsertTrackAtIndex(idx, false)
            tr = reaper.GetTrack(0, idx); fresh = true
          end
          reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)
          reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
          reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
        end
        if tr then
          reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", rname, true)
          names[rname] = tr
          wanted[rname] = true
          if fresh then any_fresh = true end
          local sends = {}
          for _, dn in ipairs(spec.sends_to or {}) do sends[#sends + 1] = remap(dn) end
          local midi_sends = {}                          -- lane Keys : MIDI du root vers chaque enfant-instrument
          local midi_send_ch = {}
          for _, dn in ipairs(spec.midi_sends_to or {}) do
            midi_sends[#midi_sends + 1] = remap(dn)
            midi_send_ch[remap(dn)] = (spec.midi_send_ch or {})[dn]
          end
          created[#created + 1] = { tr = tr, spec = spec, rname = rname, input = input, midi_send_ch = midi_send_ch,
                                    sends = sends, midi_sends = midi_sends, folder_of = remap(spec.folder_of) }
          -- GATE FX : reconstruit (clear+build => reload NAM/IR async) UNIQUEMENT si la signature a changé.
          -- Recall identique/même-forme -> signature stable -> ZÉRO chirurgie FX -> rien à libérer pendant
          -- un chargement async (la course delete/ZConvolv disparaît). ANTI-CRASH.
          local sig = fx_signature(root, spec)
          local expects_fx = spec.rfxchain or spec.native_core or (spec.blocks and #spec.blocks > 0)
          -- signature identique MAIS un fichier attendu (modèle NAM, IR) non chargé : on le DIT (log +
          -- passe rig_verify -> puce « ⚠ FX FILE »), on ne REBÂTIT PAS. Rebâtir pendant que ça joue est
          -- la classe de crash mediaafx (cf. SETTLE), et ne charge pas mieux un fichier que le plugin
          -- refuse ; la ligne perdue, elle, est couverte par heal_files et la réparation de rig_verify.
          -- (Le rebuild forcé a existé une journée, 2026-09-07 : retiré après des pertes de son en jeu.)
          local same_sig = sig_matches(root, get_fxsig(tr), sig)
          if not fresh and same_sig then
            for _, is in ipairs(files_issues(tr, false)) do
              log("⚠ FICHIER NON CHARGÉ sur " .. rname .. " FX#" .. is.fx .. " (" .. is.kind .. ", attendu « " .. is.expected .. " ») — REUSE conservée, voir rig_verify")
            end
          end
          if fresh or not same_sig or core_failed(tr) or
             (expects_fx and reaper.TrackFX_GetCount(tr) == 0) then
            clear_track_fx(tr)                            -- SEUL endroit qui détruit des FX ; jamais sur une reuse identique
            local missing_before = _MISSING_N
            build_track_fx(root, tr, spec, effects)
            if _MISSING_N > missing_before then           -- un plugin a manqué : rebâtie quand l'inventaire change
              set_fxsig(tr, sig .. "|missing@" .. inventory_hash(root))
              log("  ~ piste " .. rname .. " incomplète — rebâtie automatiquement quand un plugin sera installé")
            else
              set_fxsig(tr, sig)
            end
            log("piste " .. rname .. " REBUILD (" .. reaper.TrackFX_GetCount(tr) .. " FX, role " .. tostring(spec.role) .. ")")
          else
            apply_track_params(root, tr, spec, effects)   -- FX préservés : enable + potards seulement
            log("piste " .. rname .. " REUSE (sig identique)")
          end
          -- drumkit : la table de traduction vit en gmem (mémoire du PROCESSUS, jamais dans le .rpp) —
          -- après un redémarrage de Reaper la piste REUSE avec des slots à zéro : tout se traduisait en
          -- note 0 (revue 2026-09-17, P1). On la réécrit à chaque matérialisation, quelle que soit la branche.
          for _, blk in ipairs(spec.blocks or {}) do
            if blk.type == "drumkit" then
              write_drumtrans_gmem(blk)
              log(string.format("  drumtrans gmem slot %s réécrit (%s)", tostring(blk.drum_slot), tostring(blk.drum_desc)))
            end
          end
        end
      end
    end
  end

  local removed = delete_unwanted_subtracks(wanted)        -- obsolètes retirées EN FIN (post-FX, sûr)
  if any_fresh or removed > 0 then reorder_subtracks(created) end  -- réordonne SEULEMENT si topologie changée

  ----------------------------------------- PASSE 2 : routage (sends pre, folder, sortie -> Master, niveau)
  for _, e in ipairs(created) do
    local tr, spec = e.tr, e.spec
    for si = reaper.GetTrackNumSends(tr, 0) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 0, si) end  -- purge sends stale (root réutilisé)
    -- purge AUSSI les sends HARDWARE périmés (cat 1) : un root qui portait un OUT direct (preset
    -- sans split) le GARDAIT en passant à un preset à split -> la DI crue sortait aux enceintes en
    -- parallèle du son d'ampli (clean « qui gratte », niveaux sommés — bug volume 2026-07-23).
    -- route_monitor recrée le HWOUT pour les pistes qui doivent réellement sortir (spec.out).
    for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
    reaper.SetMediaTrackInfo_Value(tr, "D_PAN", 0)
    local is_child = (spec.role == "branch" and spec.folder == "child")
    reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", 0)                -- défaut (ajusté plus bas)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", is_child and 1 or 0) -- child = somme au parent ; sinon on décide via `out`
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", (core_failed(tr) or
      (spec.role == "branch" and spec.mute == true)) and 1 or 0)
    if spec.role == "branch" then
      -- union : la branche que la scène ne joue pas se tait par un MUTE DE PISTE (le contrat ;
      -- voir la note du bloc `mutes` dans scene_apply). Son volume reste à 0 dB : il est le levier
      -- du NIVEAU, pas du silence. Elle continue d'être traitée (reaper.ini norunmute=0, figé au
      -- provisionnement) : rien ne se réveille quand on la rétablit.
      reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1.0)
    end

    -- role pre : envoie sa sortie (post-fader) aux branches
    for _, dn in ipairs(e.sends or {}) do
      local dest = names[dn] or find_track(dn)
      if dest then
        local s = reaper.CreateTrackSend(tr, dest)
        reaper.SetTrackSendInfo_Value(tr, 0, s, "I_SENDMODE", 0)          -- post-fader
        -- audio SEUL : un send Reaper transporte le MIDI par défaut, tous canaux — le piège
        -- super8 a dormi six semaines avant de mordre (CLAUDE.md). Règle : 31 sur tout send
        -- qui ne doit porter que du son (audit 2026-08-12).
        reaper.SetTrackSendInfo_Value(tr, 0, s, "I_MIDIFLAGS", 31)
        log("  send " .. e.rname .. " -> " .. dn)
      else
        log("  ⚠ send : destination introuvable '" .. tostring(dn) .. "'")
      end
    end

    -- folder parent (merge) : ouvre le dossier
    if spec.role == "merge" and spec.folder == "parent" then
      reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", 1)
      if not spec.out then log("  ⚠ merge sans 'out' : " .. e.rname .. " n'atteint pas le Master (muet)") end
    end

    -- SANDBOX : sortie vers les ENCEINTES = sorties physiques (route_out), pas le Master (= casque).
    -- Un child de folder n'est JAMAIS routé en sortie (il somme au parent bus via B_MAINSEND=1).
    if spec.out and not is_child then
      route_monitor(tr, e.rname, spec.out_sel)                           -- sortie physique selon le choix (OUT 1/2/1·2)
      ensure_safety_limiter(tr)                                          -- brickwall -1 dBFS (protège le DAC/baffles)
      if spec.level ~= nil then reaper.SetMediaTrackInfo_Value(tr, "D_VOL", dblin(spec.level)) end
      -- trim mixer : route_monitor vient de purger/recréer le send matériel (D_VOL revenu à
      -- l'unité) — on repose le niveau du rig, sinon chaque recall effacerait le mix de la salle
      mixer_apply_track(tr, mixer_lv[mixer_src_of(e.rname)])
    elseif spec.out and is_child then
      log("  ⚠ child de folder porte un 'out' (ignoré, somme au parent) : " .. e.rname)
    end
  end

  -- ferme chaque folder : le DERNIER child (ordre de création) porte I_FOLDERDEPTH = -1
  local last_child = {}
  for ci, e in ipairs(created) do
    if e.spec.role == "branch" and e.spec.folder == "child" and e.folder_of then
      if not names[e.folder_of] then
        log("  ⚠ child '" .. e.rname .. "' : parent folder '" .. e.folder_of .. "' absent (folder cassé)")
      end
      last_child[e.folder_of] = ci
    end
  end
  for _, ci in pairs(last_child) do
    reaper.SetMediaTrackInfo_Value(created[ci].tr, "I_FOLDERDEPTH", -1)
  end

  -- SENDS MIDI root -> enfants-instruments (lane Keys en dossier). Après la boucle PASSE 2 (qui purge
  -- les sends catégorie 0 en tête de chaque piste) : ces sends survivent. MIDI seul (I_SRCCHAN = -1 =
  -- pas d'audio ; I_MIDIFLAGS = 0 = tous canaux). Le root est monitoré -> le MIDI live descend aux
  -- enfants qui sonnent leur moteur sans être armés (routage instrument standard Reaper).
  for _, e in ipairs(created) do
    for _, dn in ipairs(e.midi_sends or {}) do
      local dest = names[dn] or find_track(dn)
      if dest then
        local s = reaper.CreateTrackSend(e.tr, dest)
        reaper.SetTrackSendInfo_Value(e.tr, 0, s, "I_SRCCHAN", -1)     -- MIDI seul (aucun canal audio)
        -- I_MIDIFLAGS : 5 bits du bas = canal SOURCE (0 = tous, 1-16 = celui-là) — le tri pads/clavier
        local ch = tonumber((e.midi_send_ch or {})[dn]) or 0
        reaper.SetTrackSendInfo_Value(e.tr, 0, s, "I_MIDIFLAGS", ch)
        log("  midi " .. e.rname .. " -> " .. dn .. (ch > 0 and (" (canal " .. ch .. ")") or ""))
      else
        log("  ⚠ midi send : destination introuvable '" .. tostring(dn) .. "'")
      end
    end
  end

  sandbox_idle(used_inputs)                              -- roots non utilisés : vidés + mutés

  ensure_looper(plan, created)                           -- piste looper (créée/préservée/supprimée selon le plan)

  write_livemap(root, plan, created, effects)            -- bloc -> piste/fx/param (pédale EXP temps réel)
  flush_late_params(effects)                              -- Surge XT & co : les paramètres, une fois le type posé

  write_knobmap(root, plan, created, effects)            -- CC AKAI -> piste/fx/param (potards keys temps réel)

  -- trims mixer des pistes de SERVICE (Click, Sample, Drums, Looper, Backing Track) : leurs
  -- sends persistent dans le projet, mais un niveau posé AVANT que la piste n'existe n'avait
  -- jamais été appliqué — la matérialisation est le moment où on rattrape.
  for src, nm in pairs(MIXER_SERVICE_TRACKS) do
    local lv = mixer_lv[src]
    if lv then
      local tr = find_track(nm)
      if tr then mixer_apply_track(tr, lv) end
    end
  end

  log("rig '" .. tostring(plan.id) .. "' -> sandbox : " .. #created .. " piste(s)")
end

------------------------------------------------------- SCÈNE sans rebuild (bascule d'état pure)
-- {"action":"scene_apply","preset":id,"scene":sid} : le bridge n'envoie ceci QUE si la « forme » du
-- plan est identique entre l'ancienne et la nouvelle scène (mêmes pistes/FX/fichiers/son Vital) —
-- seuls changent bypass, potards et niveaux. On ré-applique donc ces états sur les pistes DÉJÀ
-- posées : zéro TrackFX_Add/Delete, zéro routage -> aucune chirurgie de FX pendant l'audio (c'est
-- justement ce qui faisait GPF le thread mediaafx sur des recalls rapides). Absolu & idempotent :
-- chaque bloc reçoit l'état complet de la scène cible (pas un diff), donc robuste à l'historique.
-- Fallback : si le rig n'est pas réellement matérialisé (roots vides = Reaper relancé sans build),
-- retourne false -> main() retombe sur materialize(). Jamais pire que l'existant.
local function reapply_scene(root, plan)
  if not plan or not plan.paths then return false end
  local effects = read_effects(root)
  expand_keys(plan, effects)                             -- même dépliage en dossier qu'à la matérialisation : les scènes trouvent les enfants keys

  local function path_root(path)                         -- (base, input) = piste porteuse de l'entrée
    for _, spec in ipairs(path.tracks or {}) do
      if spec.input ~= nil then return spec.name, spec.input end
    end
  end

  -- garde « rig live » : les pistes attendues du plan doivent exister ET porter AU TOTAL des FX.
  -- (Un root pre PEUT être vide si tous les FX vivent dans les branches — ex. split merge. On somme
  -- donc sur toutes les pistes du plan ; total 0 = Reaper relancé sans build -> fallback rebuild.)
  local total_fx = 0
  for _, path in ipairs(plan.paths) do
    local base, input = path_root(path)
    if not base then return false end
    local sroot = sandbox_name(input)
    local function remap0(nm) return nm and (sroot .. nm:sub(#base + 1)) or nm end
    for _, spec in ipairs(path.tracks or {}) do
      local tr = find_track(remap0(spec.name))
      if tr then
        total_fx = total_fx + reaper.TrackFX_GetCount(tr)
        -- un fichier attendu non chargé se DIT ici (la passe rig_verify le montre à l'écran) mais ne
        -- force plus un rebuild : une scène doit rester une bascule d'état, jamais une chirurgie FX.
        for _, is in ipairs(files_issues(tr, false)) do
          log("scene_apply : ⚠ fichier non chargé sur " .. track_name(tr) .. " (FX#" .. is.fx .. " " .. is.kind .. " « " .. is.expected .. " ») — scène appliquée quand même")
        end
      end
    end
  end
  if total_fx == 0 then
    log("scene_apply : rig non matérialisé (0 FX) -> rebuild")
    return false
  end

  local touched, muted = 0, {}
  -- ── LES MUTES DE BRANCHE SE FONT EN DERNIER, ET DANS L'ORDRE (2026-09-20) ────────────────
  -- Le mécanisme : les pistes sont traitées dans l'ordre du plan, `lane-a` avant `lane-b`. Si
  -- chaque branche est coupée ou rétablie AU MOMENT où on la traite, alors en A→B on coupe
  -- lane-a, puis on règle tous les blocs de lane-b (des dizaines d'écritures), et seulement
  -- ensuite on la rétablit : le thread audio joue le silence pendant ce temps-là. En B→A c'est
  -- l'inverse, les deux branches se chevauchent. On collecte donc les mutes pendant la boucle et
  -- on les applique après, RÉTABLISSEMENTS D'ABORD : un chevauchement d'1 ms ne s'entend pas.
  -- ⚠ Les chiffres qui ont justifié ce correctif (« un trou de 60 à 182 ms », crête-mètre à 30 Hz)
  -- ont été relevés pendant que GxEchoCat figeait le moteur : ils ne mesurent pas ce mécanisme.
  -- Le mécanisme, lui, est réel et le correctif reste juste.
  local mutes = {}
  for _, path in ipairs(plan.paths) do
    local base, input = path_root(path)
    local sroot = sandbox_name(input)
    local function remap(nm) return nm and (sroot .. nm:sub(#base + 1)) or nm end
    for _, spec in ipairs(path.tracks or {}) do
      local tr = find_track(remap(spec.name))
      if tr then
        -- ── UNE BRANCHE MUETTE NE CHANGE PAS L'ÉTAT DE SES PLUGINS (2026-09-20) ──────────
        -- C'est le contrat (docs/live-engine.md), rappelé : « dans un preset tout doit
        -- être chargé, et juste en mute, pas désactivé ». Le code faisait les deux — il taisait la
        -- branche ET bypassait ses blocs —, deux leviers pour un seul état. On garde le mute seul :
        -- les plugins d'une branche muette restent actifs, la bascule ne réveille rien. Prix : les
        -- deux branches tournent en permanence (CPU négligeable sur ce rack).
        -- Pourquoi c'est plus qu'une question d'élégance : RÉACTIVER un plugin n'est pas gratuit
        -- pour tous. Mesuré le 2026-09-21 (tools/check-block-stall.py --rig, fichiers chargés) :
        --   · le CONVOLVEUR D'IR x42 fige TOUT le moteur ~540 ms quand on le rallume avec son IR
        --     (à vide : 0 ms — c'est la reconfiguration de l'IR). C'était la « coupure de B vers A
        --     et de C vers A » du 2026-09-20 : le baffle de lane-a, éteint en B et C, se rallumait.
        --     Cette règle l'a guérie ;
        --   · les captures NAM (Fender, JCM800, Big Muff) : 0 ms — le modèle reste en mémoire sous
        --     bypass. « Un NAM rallumé recharge son modèle » était FAUX ;
        --   · GxEchoCat (delay de la voix) : ~520 ms — le blanc de A vers B (audit 2026-09-21 §0).
        -- Une branche qui ne rallume jamais rien est à l'abri des trois.
        -- La garde ne vaut que pour une branche MUETTE. Dans une branche active, un bypass
        -- demandé par la scène reste un bypass.
        local branch_muted = (spec.role == "branch" and spec.mute == true)
        if branch_muted then muted[#muted + 1] = spec.name:match("([^/]+)$") end
        -- blocs hors-cœur (estampillés golem:<id>) : enabled + potards de la scène
        for _, blk in ipairs(spec.blocks or {}) do
          local is_core = (blk.type == "amp" or blk.type == "amp-nam" or blk.type == "cab")
          local eng = effects[blk.type] and effects[blk.type].engine
          if blk.type == "drumkit" and blk.id then
            -- UNION DES KITS : les paires de tous les kits sont posées ; la scène en allume une, par estampilles
            if not branch_muted then set_block_enabled(tr, blk, {}, nil) end
            touched = touched + 1
          elseif not is_core and blk.id and eng ~= "midi" and eng ~= "virtual" and blk.type ~= "pads" then
            local fxs = block_fx_list(tr, blk.id)
            if #fxs > 0 then
              -- potards AVANT l'enable : un bloc rallumé par la scène ne traite jamais un cycle avec
              -- ses anciens réglages (point de vigilance docs/live-engine.md). apply_block_params reçoit
              -- la LISTE -> la zone de scène (Zone Low/High/Transpose) se pose sur le note-zone SANS
              -- rebuild (sliders repositionnés), les potards moteur sur le moteur.
              if blk.type == "vital" then
                apply_zone(tr, fxs, blk)
                if blk.params then                                 -- macros par scène (cf. matérialisation)
                  local mp = {}
                  for k, v in pairs(blk.params) do
                    if k:match("^macro[1-4]$") or k == "fcut" or k == "rmix" or k == "dmix" or k == "vol" then mp[k] = v end
                  end
                  if next(mp) then apply_block_params(tr, fxs, blk.type, mp, effects) end
                end
              elseif blk.params then apply_block_params(tr, fxs, blk.type, blk.params, effects) end
              if ARP_TYPES[blk.type] then apply_vital_arp(tr, fxs, blk, true) end  -- scène : reconfig seule
              -- vital : fxs[1] est le note-zone JS (bypassé, il laisse passer le MIDI) -> viser le MOTEUR
              local eng_s = blk.type == "vital" and instrument_engine(tr, fxs) or fxs[1]
              if not branch_muted then set_block_enabled(tr, blk, fxs, eng_s) end
              touched = touched + 1
            end
          end
        end
        -- params ET enable du CŒUR (ampli/cab, non estampillés) : localisés par nom. L'enable manquait :
        -- un ampli éteint par une scène ne se rallumait plus sans rebuild (Sunfunk « Heavy », 2026-09-14)
        for _, blk in ipairs(spec.blocks or {}) do
          if (blk.type == "amp" or blk.type == "amp-nam" or blk.type == "cab") then
            local fx = core_fx_index(tr, blk)
            if fx >= 0 then apply_core_params(tr, fx, blk, spec, effects) end
            -- le CŒUR d'une branche muette reste CHARGÉ : c'est lui qui coûte le plus cher à
            -- rallumer (NAM = worker asynchrone, convolver = rechargement d'IR)
            if not branch_muted and apply_core_enabled(tr, spec, blk) then touched = touched + 1 end
          end
        end
        -- mute de lane par scène (union) : la branche muette/active bascule sans rebuild.
        -- C'est LE geste qui fait taire une branche — ses plugins, eux, ne bougent plus (ci-dessus).
        -- ⚠ MAIS PAS ICI : on le COLLECTE, on l'applique après la boucle (voir `mutes`).
        if spec.role == "branch" then
          mutes[#mutes + 1] = { tr = tr, mute = branch_muted }
        end
        -- niveau du path (dB) porté sur la piste de sortie (pas un child de folder)
        if spec.out and spec.level ~= nil and not (spec.role == "branch" and spec.folder == "child") then
          reaper.SetMediaTrackInfo_Value(tr, "D_VOL", dblin(spec.level))
        end
      end
    end
  end
  -- ── UNE BRANCHE SE TAIT PAR UN MUTE DE PISTE (retour au contrat, 2026-09-21) ─────────
  -- Un levier = un sens : `B_MUTE` dit « cette branche se tait », `D_VOL` reste son NIVEAU
  -- (0 dB ici) — le jour où une scène réglera le niveau d'une branche, les deux ne se marcheront
  -- pas dessus. Du 2026-09-20 au 2026-09-21 la branche s'est tue par `D_VOL = 0`, sur une cause
  -- FAUSSE (« Reaper cesse de traiter une piste mutée, et un NAM rallumé recharge son modèle ») :
  -- sur ce rack les pistes muettes sont traitées (reaper.ini norunmute=0, désormais FIGÉ par
  -- provision/reaper-ini-setup.py), et rallumer un NAM coûte 0 ms. Le blanc était GxEchoCat.
  -- Mesuré avant/après (tools/check-scene-gap.py + check-scene-click.py) : docs/live-engine.md.
  -- DÉMUTER D'ABORD, COUPER ENSUITE : jamais d'instant où aucune branche ne sonne.
  for _, m in ipairs(mutes) do
    if not m.mute and not core_failed(m.tr) then
      reaper.SetMediaTrackInfo_Value(m.tr, "D_VOL", 1.0)
      reaper.SetMediaTrackInfo_Value(m.tr, "B_MUTE", 0)
    end
  end
  for _, m in ipairs(mutes) do
    if m.mute then
      reaper.SetMediaTrackInfo_Value(m.tr, "D_VOL", 1.0)
      reaper.SetMediaTrackInfo_Value(m.tr, "B_MUTE", 1)
    end
  end
  log("scène appliquée SANS rebuild (" .. touched .. " bloc(s)"
      .. (#muted > 0 and ", lane(s) mutée(s): " .. table.concat(muted, ", ") or "") .. ")")
  return true
end

----------------------------------------------------------------------- main
-- fusionne le constat de ce build dans presets/.rig-plugins.json : {types:{<type>:{ok, name, at}}}
local function write_fx_seen(root)
  if next(_FX_SEEN) == nil then return end
  local path = root .. "/presets/.rig-plugins.json"
  local prev = read_file(path)
  local d = prev and json_decode(prev) or nil
  local types = (type(d) == "table" and type(d.types) == "table") and d.types or {}
  local now = os.time()
  for t, v in pairs(_FX_SEEN) do types[t] = { ok = v.ok, name = v.name, at = now } end
  local parts = {}
  for t, v in pairs(types) do
    if type(v) == "table" then
      parts[#parts + 1] = jstr(t) .. ':{"ok":' .. tostring(v.ok == true) .. ',"name":' .. jstr(v.name or "")
                          .. ',"at":' .. tostring(tonumber(v.at) or now) .. '}'
    end
  end
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w")
  if not f then return end
  f:write('{"types":{' .. table.concat(parts, ",") .. '}}')
  f:close()
  runtime.replace(tmp, path)
end

-- Le bypass hôte appartient au bloc, pas au son capturé dans le plugin.
local function vst_host_param_rows(tr, fx, with_names)
  local rows = {}
  local bypass = reaper.TrackFX_GetParamFromIdent(tr, fx, ":bypass")
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, name = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if p ~= bypass and not (name or ""):match("^%s*[Mm][Ii][Dd][Ii][%s_-]*[Cc][Cc]%f[^%a]") then
      local norm = reaper.TrackFX_GetParamNormalized(tr, fx, p)
      if with_names then
        local _, display = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
        local has_step, step, _, _, toggle = reaper.TrackFX_GetParameterStepSizes(tr, fx, p)
        rows[#rows + 1] = string.format('{"i":%d,"name":%s,"value":%.8f,"display":%s,"step":%.9f,"toggle":%s}',
          p, jstr(name or ""), tonumber(norm) or 0, jstr(display or ""), has_step and (tonumber(step) or 0) or 0,
          tostring(toggle == true))
      else
        rows[#rows + 1] = string.format('{"i":%d,"value":%.8f}', p, tonumber(norm) or 0)
      end
    end
  end
  return rows
end

local function main()
  local root = repo_root()
  _logpath = root .. "/presets/.golem-rig.log"                 -- (re)démarre le log fichier de ce run
  local vpass = reaper.GetExtState("golem", "rig_verify")
  if vpass == "1" or vpass == "2" then                          -- passe différée (golem_watch, après le settle) :
    reaper.DeleteExtState("golem", "rig_verify", false)         -- le log n'est PAS tronqué, la vérif se lit à la suite du build
    local okv, errv = xpcall(function() verify_files(root, vpass == "2") end, debug.traceback)
    if not okv then log("✗ VÉRIF ERREUR :\n" .. tostring(errv)) end
    return
  end
  local raw = read_file(root .. "/presets/.command.json")
  local cmd = raw and json_decode(raw)
  -- le journal ne repart à zéro que pour un RAPPEL (audit 2026-10-15) : un stomp, un fader ou une fenêtre de plugin
  -- effaçait le journal du rebuild — celui qu'on lit pour trouver un rebuild qui ne finit pas (CLAUDE.md)
  if not cmd or cmd.action == "rig_recall" or cmd.action == "scene_apply" then
    local t = io.open(_logpath, "w"); if t then t:write("") t:close() end
  end
  if not raw then log("aucune commande") return end
  if not cmd then log("commande illisible") return end
  -- un RAPPEL fait de ce projet celui du golem : les boucles de service (horloge, click) n'installent leur piste
  -- que là (golem_project.lua, 2026-11-08) — c'est ce qui couvre le premier démarrage, projet sans chemin
  if cmd.action == "rig_recall" then project.mark() end
  if cmd.action == "capture_params" then
    for ti = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, ti)
      local fxs = block_fx_list(tr, tostring(cmd.block or ""))
      if #fxs > 0 then
        for slot, value in pairs(cmd.values or {}) do
          local p = tonumber(slot)
          if p and p >= 0 and p < 32 and type(value) == "number" and value >= 0 and value <= 1 then
            reaper.TrackFX_SetParamNormalized(tr, fxs[1], p, value)
          end
        end
      end
    end
    return
  end
  if cmd.action == "vst_list" then
    local rows = {}
    if reaper.EnumInstalledFX then
      for i = 0, 20000 do
        local ok, name, ident = reaper.EnumInstalledFX(i)
        if not ok then break end
        if tostring(name):match("^VST3?i?:") or tostring(name):match("^CLAPi?:") then
          rows[#rows + 1] = '{"name":' .. jstr(name) .. ',"ident":' .. jstr(ident or "") .. '}'
        end
      end
    end
    local f = io.open(root .. "/presets/.vst-host-list.json", "w")
    if f then f:write('{"seq":' .. jstr(cmd.seq or "") .. ',"plugins":[' .. table.concat(rows, ",") .. ']}'); f:close() end
    return
  end
  -- ── FENÊTRE D'ORIGINE D'UN INSTRUMENT (Vital, 2026-10-14 : « ouvrir la fenêtre, sauvegarde quand on la
  -- ferme ») : l'état est lu À L'OUVERTURE puis À LA FERMETURE, et le bridge n'est prévenu que s'ils diffèrent.
  -- La fermeture est guettée ici, par une boucle `defer` qui s'éteint seule : REAPER est le seul à savoir si la
  -- fenêtre est encore là (TrackFX_GetOpen) — l'app ne voit pas un clic sur la croix d'une fenêtre qui n'est pas la
  -- sienne. L'état part dans un FICHIER à part (.b64), sans le plafond de 1 Mo de vst_state : un Vital avec ses
  -- tables d'onde le dépasse (mesuré ce jour-là : « Plugin did not provide a supported native state »).
  -- Si l'instance change pendant que la fenêtre est ouverte (un rebuild), la boucle dit « lost » et ne lit
  -- RIEN : l'état d'une instance neuve serait celui du preset, pas la retouche du musicien.
  -- op = "open" (ouvre + guette) | "close" (ferme ; la boucle d'open range) | "peek" (lit l'état seul, diagnostic).
  if cmd.action == "plugin_window" then
    local id = tostring(cmd.block or "")
    if not id:match("^[%w_-]+$") then return end
    -- un bloc clavier porte DEUX FX sous la même étiquette (la zone de notes en JSFX, puis le moteur) : viser le moteur
    local function find()
      local jt, jf
      for ti = 0, reaper.CountTracks(0) - 1 do
        local tr = reaper.GetTrack(0, ti)
        for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
          local ok, tag = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
          if ok and tag == "golem:" .. id then
            local _, ft = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_type")
            if ft ~= "JS" then return tr, fx end
            jt, jf = jt or tr, jf or fx
          end
        end
      end
      return jt, jf
    end
    local base = root .. "/presets/.plugin-window-" .. id
    local seq = tostring(cmd.seq or "")
    local function publish(state, extra)
      local f = io.open(base .. ".json", "w")
      if f then f:write('{"seq":' .. jstr(seq) .. ',"block":' .. jstr(id) .. ',"state":' .. jstr(state) ..
        (extra or "") .. '}'); f:close() end
    end
    local function read_state(tr, fx)
      local _, ftype = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_type")
      local kind = (ftype or ""):find("CLAP") and "clap_chunk" or "vst_chunk"
      if (ftype or ""):find("LV2") then return nil, "LV2 plugins do not expose their state here" end
      local got, v = reaper.TrackFX_GetNamedConfigParm(tr, fx, kind)
      if got and v and #v > 0 then return v, nil, kind end
      return nil, "the plugin did not give its state"
    end
    local tr, fx = find()
    if not tr then publish("missing"); return end
    if cmd.op == "close" then                                       -- golem ferme la fenêtre (vue intégrée, Linux) :
      reaper.TrackFX_Show(tr, fx, 2); return                        -- la boucle d'« open » voit la fermeture et range l'état
    end
    local first, err0, kind0 = read_state(tr, fx)
    if cmd.op == "peek" then
      if first then local f = io.open(base .. ".b64", "w"); if f then f:write(first); f:close() end end
      local _, ftype = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_type")
      publish("peek", ',"bytes":' .. tostring(first and #first or 0) .. ',"fx_type":' .. jstr(ftype or "") ..
        ',"error":' .. jstr(err0 or ""))
      return
    end
    local guid = reaper.TrackFX_GetFXGUID(tr, fx)
    -- le GUID ne suffit pas (audit 2026-10-15) : une réécriture de chunk garde les FXID, donc une instance RECRÉÉE
    -- a le même GUID — et son état neuf (ou les potards d'une scène) passait pour une retouche du musicien
    local function gen_of(t) return (GOLEM_CHUNK_GEN or {})[reaper.GetTrackGUID(t)] or 0 end
    local gen0 = gen_of(tr)
    reaper.TrackFX_Show(tr, fx, 3)                                  -- fenêtre flottante
    publish("open", ',"readable":' .. tostring(first ~= nil) .. ',"error":' .. jstr(err0 or ""))
    GOLEM_PLUGIN_WINDOWS = GOLEM_PLUGIN_WINDOWS or {}
    GOLEM_PLUGIN_WINDOWS[id] = seq                                  -- une réouverture remplace la boucle précédente
    local next_t = reaper.time_precise() + 0.4
    local function poll()
      if GOLEM_PLUGIN_WINDOWS[id] ~= seq then return end
      if reaper.time_precise() < next_t then reaper.defer(poll); return end
      next_t = reaper.time_precise() + 0.4
      local t2, f2 = find()
      if not t2 or reaper.TrackFX_GetFXGUID(t2, f2) ~= guid or gen_of(t2) ~= gen0 then
        GOLEM_PLUGIN_WINDOWS[id] = nil; publish("lost"); return
      end
      if reaper.TrackFX_GetOpen(t2, f2) then reaper.defer(poll); return end
      GOLEM_PLUGIN_WINDOWS[id] = nil
      local now, err, kind = read_state(t2, f2)
      local changed = now ~= nil and now ~= first
      if changed then local f = io.open(base .. ".b64", "w"); if f then f:write(now); f:close() end end
      publish("closed", ',"changed":' .. tostring(changed) .. ',"kind":' .. jstr(kind or kind0 or "") ..
        ',"error":' .. jstr(err or ""))
    end
    reaper.defer(poll)
    return
  end
  if cmd.action == "vst_open" then
    local id = tostring(cmd.block or "")
    if id:match("^[%w_-]+$") then
      for ti = 0, reaper.CountTracks(0) - 1 do
        local tr = reaper.GetTrack(0, ti)
        for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
          local ok, tag = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
          if ok and tag == "golem:" .. id then
            reaper.TrackFX_Show(tr, fx, 3)
            return
          end
        end
      end
    end
    log("vst_open : instance absente " .. id)
    return
  end
  if cmd.action == "vst_params" then
    local id = tostring(cmd.block or "")
    local rows, found = {}, false
    if id:match("^[%w_-]+$") then
      for ti = 0, reaper.CountTracks(0) - 1 do
        local tr = reaper.GetTrack(0, ti)
        for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
          local ok, tag = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
          if ok and tag == "golem:" .. id then
            found = true
            rows = vst_host_param_rows(tr, fx, true)
            break
          end
        end
        if found then break end
      end
    end
    local f = io.open(root .. "/presets/.vst-host-params.json", "w")
    if f then f:write('{"seq":' .. jstr(cmd.seq or "") .. ',"found":' .. tostring(found) ..
      ',"params":[' .. table.concat(rows, ",") .. ']}'); f:close() end
    return
  end
  if cmd.action == "vst_state" then
    local id = tostring(cmd.block or "")
    local found, kind, chunk, rows, err = false, nil, nil, {}, nil
    if id:match("^[%w_-]+$") then
      for ti = 0, reaper.CountTracks(0) - 1 do
        local tr = reaper.GetTrack(0, ti)
        for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do
          local ok, tag = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
          if ok and tag == "golem:" .. id then
            found = true
            local _, name = reaper.TrackFX_GetFXName(tr, fx, "")
            -- Surge XT plante REAPER à la relecture de son grand vst_chunk (docs/standards.md).
            if (name or ""):lower():find("surge xt", 1, true) then
              err = "Native state capture unavailable for Surge XT"
            else
              local okt, ftype = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_type")
              kind = okt and ftype and ftype:find("CLAP") and "clap_chunk" or "vst_chunk"
              local got, value = reaper.TrackFX_GetNamedConfigParm(tr, fx, kind)
              if got and value and #value <= 1048576 then chunk = value
              else err = "Plugin did not provide a supported native state" end
            end
            rows = vst_host_param_rows(tr, fx, false)
            break
          end
        end
        if found then break end
      end
    end
    local f = io.open(root .. "/presets/.vst-host-state.json", "w")
    if f then f:write('{"seq":' .. jstr(cmd.seq or "") .. ',"found":' .. tostring(found) ..
      ',"kind":' .. jstr(kind or "") .. ',"chunk":' .. jstr(chunk or "") ..
      ',"error":' .. jstr(err or "") .. ',"params":[' .. table.concat(rows, ",") .. ']}'); f:close() end
    return
  end
  if cmd.action == "fx_onoff" then                             -- banc : LE chemin du moteur, sur un FX désigné
    local tr = find_track(tostring(cmd.track or ""))            -- par sa position (tools/check-block-stall.py)
    if tr then fx_set_on(tr, tonumber(cmd.fx), cmd.on == true) end
    return
  end
  if cmd.action == "stomp" then                                -- toggle live d'un bloc, sans rebuild
    -- PAS de bloc Undo (audit 2026-10-15) : un point d'annulation « tout » sérialise l'état de chaque FX (des Mo
    -- pour un Vital) sur le fil principal, à chaque pied — de la latence de scène et de la RAM sur un concert
    handle_stomp(root, cmd)
    return
  end
  if cmd.action == "mixer_apply" then                          -- trims de sortie, sans rebuild
    handle_mixer(root, cmd)
    return
  end
  if cmd.action == "mixer_dump" then                           -- sonde read-only (vérification)
    mixer_dump(root)
    return
  end
  if cmd.action ~= "rig_recall" and cmd.action ~= "scene_apply" then
    log("action ignorée par golem_rig : " .. tostring(cmd.action)) return
  end
  local id = cmd.preset
  if not id then log(tostring(cmd.action) .. " : preset absent") return end
  -- même nom de fichier que compile_rig.file_stem : `:` (id `patch:<id>`) est interdit sous Windows
  local pj = read_file(root .. "/reaper/FXChains/" .. id:gsub(":", "~") .. ".rig.json")
  if not pj then log("pas de " .. id .. ".rig.json") return end
  local plan = json_decode(pj)
  if not plan then log(id .. ".rig.json illisible") return end

  -- TEMPO PROJET = BPM du preset. Pose au recall (rig_recall ET scene_apply) pour que l'horloge MIDI
  -- free-running (golem_clock / piste "MIDI Clock") et les delays sync-BPM suivent le tempo du
  -- morceau. Le plan compile ne porte pas le bpm -> on le lit dans la source presets/<id>.json.
  -- (Sans ceci, l'arpegiateur AKAI se calerait sur le tempo projet par defaut, pas sur le preset.)
  -- ⚠ La LIGNE de setlist peut surcharger le tempo (docs/setlists.md §9.3) : `cmd.bpm`, joint par le
  -- bridge quand le rappel vient d'une ligne. Le preset n'est jamais réécrit.
  do
    local lbpm = tonumber(cmd.bpm)
    if lbpm and lbpm >= 20 and lbpm <= 400 then
      reaper.SetCurrentBPM(0, lbpm, false)
      log("tempo projet <- " .. lbpm .. " BPM (" .. (cmd.bpm_from == "preset" and "document joué" or "ligne de setlist")
          .. ", " .. id .. ")")
    else
      local praw = read_file(root .. "/presets/" .. id .. ".json")
      if praw then
        local ok, pj2 = pcall(json_decode, praw)
        local bpm = ok and pj2 and tonumber(pj2.bpm)
        if bpm and bpm >= 20 and bpm <= 400 then
          reaper.SetCurrentBPM(0, bpm, false)
          log("tempo projet <- " .. bpm .. " BPM (preset " .. id .. ")")
        end
      end
    end
  end

  -- scene_apply : bascule d'état sur les pistes existantes (pas de rebuild) ; fallback rebuild si non-live
  if cmd.action == "scene_apply" then                          -- pas de bloc Undo : voir stomp
    local applied = reapply_scene(root, plan)
    if applied then return end                                 -- sinon on enchaîne sur le rebuild ci-dessous
  end
  -- UN REBUILD A LIEU (rig_recall, ou une scène qui y retombe) : golem_watch arme son SETTLE en le lisant.
  -- Audit 2026-10-15 (R2) : il ne l'armait que sur l'action « rig_recall » — une scène retombée en rebuild
  -- laissait un stomp toucher, 30 ms après, des FX dont le NAM/l'IR chargeaient encore (classe du 2026-07-10).
  -- Posé AVANT la chirurgie : même une matérialisation qui échoue a déjà ré-instancié des FX.
  reaper.SetExtState("golem", "rig_rebuilt", "1", false)

  reaper.Undo_BeginBlock()
  reaper.PreventUIRefresh(1)
  local mono_on = plan.mono_fallback and plan.mono_fallback.on == true
  -- xpcall : une erreur de matérialisation atterrit DANS le log fichier avec sa traceback
  -- (le pcall de golem_watch l'avalait -> diagnostic aveugle, bug volume 2026-07-23)
  local okm, errm = xpcall(function() materialize(root, plan, mono_on) end, debug.traceback)
  reaper.PreventUIRefresh(-1)
  reaper.Undo_EndBlock("golem rig " .. tostring(id), -1)
  reaper.TrackList_AdjustWindows(false)
  pcall(write_fx_seen, root)
  if not okm then
    log("✗ MATERIALIZE ERREUR :\n" .. tostring(errm))
    -- Le rig n'est PLUS garanti : la livemap est invalidée pour que la prochaine émission du bridge
    -- fasse un REBUILD (rig_is_live -> false), jamais un scene_apply sur un build à moitié fait.
    -- Vécu le 2026-09-23 : après une erreur (ROOT nil), deux applies de suite sont passés en
    -- « scène appliquée SANS rebuild » sur une piste sans moteur — l'écran disait Aasimonster, Reaper
    -- n'avait rien. L'ancienne livemap (build précédent, même preset) faisait croire au rig vivant.
    local lm = root .. "/presets/.livemap.json"
    local f = io.open(lm .. ".tmp", "w")
    if f then
      f:write('{"preset":"","error":"materialize failed","t":' .. tostring(reaper.time_precise()) .. '}'); f:close()
      runtime.replace(lm .. ".tmp", lm)
    end
  end
end

main()
