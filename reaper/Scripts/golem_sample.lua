-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — sample (lanceur de one-shots au pied)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_tuner/looper/backing/perfrec).
  Joue des samples audio one-shot déclenchés par commande (au pied), via ReaSamplOmatic5000
  (RS5k) — le MÊME plugin que les kits de pads (bridge/kits.py). Plusieurs blocs « sample »
  coexistent, chacun avec son switch ; chaque bloc a ses propres RS5k sur UNE piste partagée.

  ── Architecture (choisie « en connaissance de l'API ») ──
  Piste PERMANENTE « Sample » : créée UNE fois, JAMAIS supprimée (comme Looper/Recording/
  Backing Track — ne matche AUCUN pattern de purge de golem_rig : sweep_legacy=GoleM:*,
  delete_unwanted=Sandbox #Input N). Muette pour le Master (B_MAINSEND=0), sortie hardware
  OUT 1/2 (CreateTrackSend(tr,nil), cat 1, I_DSTCHAN=0) comme le looper.

  DÉCLENCHEMENT — ReaScript ne peut PAS injecter de MIDI dans une instance FX précise
  (StuffMIDIMessage -> bus virtuel GLOBAL, cf. golem_rig.lua l.893). On applique le patron
  ÉPROUVÉ b3-ctl/dx7-ctl/super8 : un ÉMETTEUR JSFX (golem_sample_trig) EN TÊTE de la chaîne
  FX de la piste, piloté par ses sliders (= vrais params Reaper). On écrit s_off/s_on/s_chan
  puis on bump s_nonce (EN DERNIER) via TrackFX_SetParamNormalized ; le JSFX émet
  note-off(off) puis note-on(on,127) vers les RS5k en aval.

  UN RS5k PAR SAMPLE d'un bloc (patron pads : N instances, une par pad), note-filtré sur une
  note MIDI unique allouée globalement. Preload => déclenchement instantané, zéro reload FILE0
  au pied. Chaque instance : Obey note-off = ON => note tenue (on n'émet jamais le note-off
  tant que le sample doit sonner) joue jusqu'au bout (aucun loop) ; note-off explicite (stop
  ou nouveau play) coupe avant la fin. Estampille "sample:<blockid>:<idx>:<note>" (hors espace
  golem:<id> -> invisible au livemap/scène, comme les pads).

  Commandes : golem_watch relaie {"action":"sample",...} en ProjExtState golem/sample_cmd
  (branche exempte de SETTLE — on ne touche qu'à NOS propres FX de piste, jamais au graphe des
  presets ; le bridge séquence lui-même). Dédup par "seq". Ops :
    play {seq, block, idx, samples:[rel,...]}  — coupe le sample courant DU BLOC puis joue idx
    stop {seq, block}                          — coupe le sample courant DU BLOC

  État publié : presets/.sample.json (tmp+rename, fingerprint + heartbeat) — lu par le bridge :
    {"present":true,"blocks":{"<block>":{"playing":bool,"idx":N}}}

  ⚠ NON validable hors-rig : réception des note-on/off par RS5k via l'émetteur, timing
    SetParamNormalized -> @block, durée de sample (PCM_Source) vs fin réelle du one-shot.
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
    _LOGF = root .. "/presets/.sample.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-sample] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT   = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local OUT    = ROOT .. "/presets/.sample.json"
local TRACK  = "Sample"
-- émetteur JSFX (link-reaper.sh symlink reaper/Effects -> <resource>/Effects/golem)
local TRIG_NAMES = { "JS:golem/golem_sample_trig", "JS: golem/golem_sample_trig",
                     "GoleM sample trigger (sample-trig)", "golem_sample_trig" }
local RS5K_NAMES = { "ReaSamplOmatic5000", "VSTi: ReaSamplOmatic5000 (Cockos)",
                     "VST: ReaSamplOmatic5000 (Cockos)", "VST3i: ReaSamplOmatic5000" }
-- repli d'index RS5k (réf. golem_rig build_pads_block) si le match par NOM échoue
local RS5K_IDX = { volume = 0, note_start = 3, note_end = 4, pitch_start = 5, pitch_end = 6, obey = 11 }

-- ── util ──
local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

local function file_exists(p) local f = io.open(p, "r"); if f then f:close(); return true end return false end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

local function find_param_by_name(tr, fx, needle)
  if not needle then return nil end
  local target = needle:lower()
  local sub = nil
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
    local low = pn and pn:lower()
    if low == target then return p end
    if low and sub == nil and low:find(target, 1, true) then sub = p end
  end
  return sub
end

local function set_norm(tr, fx, needle, idx, norm)
  local p = find_param_by_name(tr, fx, needle)
  if not (p and p >= 0) then p = idx end
  reaper.TrackFX_SetParamNormalized(tr, fx, p, norm)
end

-- ⚠ UN SLIDER JSFX À MINIMUM NÉGATIF EST BIPOLAIRE POUR REAPER, PAS LINÉAIRE. Sur
-- `slider2:s_on=-1<-1,127,1>`, la normalisée 0.5 vaut ZÉRO : [0 ; 0.5] couvre -1→0 et
-- [0.5 ; 1] couvre 0→127. La formule (v-min)/(max-min) écrit donc n'importe quoi — pour la
-- note 3 elle envoyait 4/128 = 0.031, ce que Reaper lisait comme -1. Le JSFX voyait s_on < 0
-- et traitait CHAQUE déclenchement comme un « stop » : le bloc sample était intégralement
-- muet, et les note-off manquaient de la même façon. Mesuré le 2026-08-07 (balayage : 0.6→25,
-- 0.8→76, 0.99→124, 0.3→0, 0.2→-1 — la loi bipolaire au point près). Le nonce, lui, marchait :
-- son minimum est 0, donc pas de taper.
-- On écrit la VALEUR BRUTE : elle ne dépend d'aucun taper, et se lit comme le contrat.
local function set_val(tr, fx, needle, idx, value)
  local p = find_param_by_name(tr, fx, needle)
  if not (p and p >= 0) then p = idx end
  reaper.TrackFX_SetParam(tr, fx, p, value)
end

local function fx_stamp(tr, fx)
  local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
  local _, rn = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
  return (rn ~= "" and rn) or nm or ""
end

-- ── piste PERMANENTE + émetteur : créés UNE fois ──
local function find_trig(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if (nm or ""):lower():find("sample_trig", 1, true)
       or (nm or ""):lower():find("sample trigger", 1, true) then return i end
  end
  return -1
end

local function ensure_trig(tr)
  local fx = find_trig(tr)
  if fx < 0 then
    for _, nm in ipairs(TRIG_NAMES) do
      local r = reaper.TrackFX_AddByName(tr, nm, false, -1)
      if r and r >= 0 then reaper.TrackFX_Show(tr, r, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
      if r and r >= 0 then fx = find_trig(tr); break end
    end
    if fx < 0 then log("⚠ émetteur golem_sample_trig introuvable (provision/link-reaper.sh fait ?)")
    else log("émetteur golem_sample_trig ajouté (permanent)") end
  end
  -- l'émetteur DOIT précéder les RS5k (MIDI descend la chaîne) : on le remet en tête si besoin
  if fx > 0 then
    reaper.TrackFX_CopyToTrack(tr, fx, tr, 0, true)   -- ismove=true : déplace à l'index 0
    fx = find_trig(tr)
  end
  if fx and fx >= 0 then
    reaper.TrackFX_SetParamNormalized(tr, fx, find_param_by_name(tr, fx, "channel") or 3, 0)  -- canal MIDI 0
  end
  return fx
end

local function ensure_track()
  local tr = find_track(TRACK)
  if not tr then
    reaper.PreventUIRefresh(1)
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", TRACK, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)   -- pas d'entrée : audio généré par les RS5k
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
    reaper.SetMediaTrackInfo_Value(tr, "D_PAN", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
    -- sortie hardware OUT 1/2, jamais par le Master (même règle que looper/backing/rig)
    for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
    local hw = reaper.CreateTrackSend(tr, nil)
    reaper.SetTrackSendInfo_Value(tr, 1, hw, "I_DSTCHAN", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
    reaper.PreventUIRefresh(-1)
    log("piste créée (permanente) : " .. TRACK .. " -> OUT 1/2")
  end
  -- ⚠ ARMER, SINON L'ÉMETTEUR NE PART JAMAIS. `fire` pose des sliders puis un nonce, et c'est le
  -- @block du JSFX qui lit ce front pour émettre la note — il faut donc que Reaper TRAITE la
  -- piste. Or il ne fait vivre que les pistes de son graphe temps réel : sans entrée, sans item
  -- et non armée, celle-ci n'en fait pas partie, et l'ordre arrive par un canal (les sliders du
  -- FX) qui ne la réveille pas. MESURÉ le 2026-08-07 : play d'un sample de 10,87 s, crête de la
  -- piste restée au plancher — pas un échantillon émis. Même panne que le standard, le click et
  -- la boîte à rythmes le même jour. I_RECMODE 2 = « aucun » : vivante dans le graphe, hors
  -- d'état d'écrire un fichier.
  if reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") ~= 1 then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
    log("piste ARMÉE (I_RECMODE 2 « aucun ») — sans ça le thread audio ne la traite pas")
  end
  ensure_trig(tr)
  return tr
end

-- ── état runtime par bloc (redérivable : les RS5k persistent sur la piste) ──
-- blocks[bid] = { fp, samples={rel...}, notes={[idx]=note}, lens={[idx]=sec},
--                 held=note|nil, held_idx=idx|nil, held_until=t|nil }
local blocks = {}
local note_cursor = 0        -- allocation globale de notes MIDI (0..127), avance à chaque instance
local function alloc_note()
  local n = note_cursor % 128
  note_cursor = note_cursor + 1
  return n
end

-- retire les RS5k d'un bloc (estampille "sample:<bid>:") — l'émetteur (index 0) est préservé
local function remove_block_fx(tr, bid)
  local needle = "sample:" .. bid .. ":"
  for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do
    if fx_stamp(tr, i):find(needle, 1, true) then reaper.TrackFX_Delete(tr, i) end
  end
end

-- (re)construit les instances RS5k d'un bloc à partir de samples[] (chemins RELATIFS au repo)
local function build_block(tr, bid, samples)
  reaper.PreventUIRefresh(1)
  remove_block_fx(tr, bid)
  local notes, lens = {}, {}
  local placed = 0
  for i, rel in ipairs(samples) do
    local idx0 = i - 1                                   -- idx du contrat = 0-based
    local abspath = ROOT .. "/" .. rel
    if not file_exists(abspath) then
      log("  x sample introuvable : " .. rel)
    else
      -- durée du sample (pour éteindre l'état "playing" à la fin naturelle) — source jetable
      local len = 0
      local src = reaper.PCM_Source_CreateFromFile(abspath)
      if src then len = reaper.GetMediaSourceLength(src); reaper.PCM_Source_Destroy(src) end
      local fx
      for _, nm in ipairs(RS5K_NAMES) do
        fx = reaper.TrackFX_AddByName(tr, nm, false, -1)
        if fx and fx >= 0 then reaper.TrackFX_Show(tr, fx, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
        if fx and fx >= 0 then break end
      end
      if not fx or fx < 0 then
        log("  x ReaSamplOmatic5000 introuvable (bloc " .. bid .. " idx " .. idx0 .. ")")
      else
        reaper.TrackFX_SetNamedConfigParm(tr, fx, "FILE0", abspath)   -- idiome prouvé RS5k
        reaper.TrackFX_SetNamedConfigParm(tr, fx, "DONE", "")
        local note = alloc_note()
        local nn = note / 127
        set_norm(tr, fx, "Note range start", RS5K_IDX.note_start, nn)
        set_norm(tr, fx, "Note range end",   RS5K_IDX.note_end,   nn)
        set_norm(tr, fx, "Obey note-off",    RS5K_IDX.obey, 1)        -- ON : note-off = coupe avant la fin
        -- ⚠ PIÈGE RS5k (cf. build_pads_block) : "Pitch for start/end note" ne valent PAS 0 semiton
        -- après un FILE0 -> le sample serait transposé. On force 0 semiton (norm 0.5).
        set_norm(tr, fx, "Pitch for start note", RS5K_IDX.pitch_start, 0.5)
        set_norm(tr, fx, "Pitch for end note",   RS5K_IDX.pitch_end,   0.5)
        reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name",
          "sample:" .. bid .. ":" .. idx0 .. ":" .. note)
        reaper.TrackFX_SetEnabled(tr, fx, true)
        notes[idx0] = note; lens[idx0] = len
        placed = placed + 1
      end
    end
  end
  reaper.PreventUIRefresh(-1)
  blocks[bid] = { fp = table.concat(samples, "\30"), samples = samples,
                  notes = notes, lens = lens, held = nil, held_idx = nil, held_until = nil }
  log(string.format("bloc %s : %d instance(s) RS5k (notes %s)", bid, placed,
      (function() local t = {} for _, n in pairs(notes) do t[#t+1] = n end return table.concat(t, ",") end)()))
end

-- ── émission via l'émetteur (off puis on ; nonce EN DERNIER) ──
local nonce = 0
local function fire(tr, off, on, in_ms)
  local fx = ensure_trig(tr)
  if not fx or fx < 0 then log("⚠ fire : émetteur absent"); return end
  -- PRÉ-ARMEMENT (arrangement) : « joue dans N ms », décompté par le JSFX dans le thread
  -- audio. 0 = chemin du pied, inchangé. Écrit AVANT le nonce, comme les autres sliders.
  set_val(tr, fx, "trigger delay", 4, math.max(0, math.min(10000, in_ms or 0)))
  set_val(tr, fx, "off note", 0, off)                    -- valeur BRUTE : voir set_val (taper bipolaire)
  set_val(tr, fx, "on note",  1, on)
  nonce = (nonce + 1) % 1000000
  set_val(tr, fx, "nonce", 2, nonce)                     -- EN DERNIER : le front déclenche l'émission
end

-- ── ops ──
local function op_play(bid, idx, samples, in_ms, ring)
  if not bid then log("play : block manquant"); return end
  if not idx then log("play : idx manquant"); return end
  local tr = ensure_track()
  local fp = table.concat(samples or {}, "\30")
  local st = blocks[bid]
  if (not st) or st.fp ~= fp then
    if not samples or #samples == 0 then log("play : samples[] manquant (bloc " .. bid .. " inconnu)"); return end
    build_block(tr, bid, samples)
    st = blocks[bid]
  end
  local note = st.notes[idx]
  if note == nil then log("play : idx " .. tostring(idx) .. " hors plage (bloc " .. bid .. ")"); return end
  -- `ring` (lane d'arrangement, §18) : on NE COUPE PAS ce qui sonne. La monophonie est la loi
  -- du PIED (un switch = une voix), pas celle de la lane où un riser doit continuer pendant
  -- que l'impact tombe. off = -1 -> aucun note-off émis.
  local off = ring and -1 or (st.held or -1)
  fire(tr, off, note, in_ms)
  st.held = note; st.held_idx = idx
  local len = st.lens[idx] or 0
  local pre = math.max(0, (in_ms or 0)) / 1000
  st.held_until = len > 0 and (reaper.time_precise() + pre + len + 0.05) or nil   -- nil = pas d'extinction auto
  log(string.format("play bloc %s idx %d (note %d, %.2fs)", bid, idx, note, len))
end

local function op_stop(bid)
  if not bid then log("stop : block manquant"); return end
  local st = blocks[bid]
  if not st or not st.held then return end
  local tr = ensure_track()
  fire(tr, st.held, -1)                                   -- note-off seul (on=-1)
  st.held = nil; st.held_idx = nil; st.held_until = nil
  log("stop bloc " .. bid)
end

-- ── commandes (ProjExtState golem/sample_cmd, posé par golem_watch) ──
local last_seq = nil
local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "sample_cmd")
  if not body or body == "" then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if seq and seq == last_seq then return end
  last_seq = seq
  local op  = body:match('"op"%s*:%s*"([^"]+)"')
  local bid = body:match('"block"%s*:%s*"([^"]+)"')
  if op == "play" then
    local idx = tonumber(body:match('"idx"%s*:%s*(%-?%d+)'))
    local samples = {}
    local arr = body:match('"samples"%s*:%s*%[(.-)%]')
    if arr then for s in arr:gmatch('"([^"]*)"') do samples[#samples + 1] = s end end
    local in_ms = tonumber(body:match('"in_ms"%s*:%s*(%-?%d+)')) or 0
    local ring  = body:match('"ring"%s*:%s*true') ~= nil
    op_play(bid, idx, samples, in_ms, ring)
  elseif op == "stop" then
    op_stop(bid)
  else
    log("op inconnue : " .. tostring(op))
  end
end

-- ── publication d'état ──
local function build_json()
  local parts = {}
  for bid, st in pairs(blocks) do
    parts[#parts + 1] = string.format('"%s":{"playing":%s,"idx":%d}',
      bid, st.held ~= nil and "true" or "false", st.held_idx or -1)
  end
  return '{"present":true,"blocks":{' .. table.concat(parts, ",") .. '}}'
end

local last_fp = nil
local function publish(force)
  local fp = {}
  for bid, st in pairs(blocks) do fp[#fp + 1] = bid .. "=" .. (st.held_idx or -1) end
  table.sort(fp)
  local sig = table.concat(fp, "|")
  if force or sig ~= last_fp then
    last_fp = sig
    write_atomic(OUT, build_json())
  end
end

-- ── boucle (garde par génération : la dernière instance lancée gagne) ──
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "sample_gen", GEN, false)

local function tick()
  poll_cmd()
  -- extinction "playing" à la fin naturelle du one-shot (RS5k a déjà cessé de sonner ; on nettoie l'état)
  local now = reaper.time_precise()
  local changed = false
  for _, st in pairs(blocks) do
    if st.held and st.held_until and now > st.held_until then
      st.held = nil; st.held_idx = nil; st.held_until = nil; changed = true
    end
  end
  if changed then publish(false) end
  publish(false)   -- heartbeat léger (n'écrit que sur changement de signature)
end

-- au démarrage : ADOPTER le seq résiduel SANS le rejouer (un sample_cmd sauvegardé ne doit pas
-- relancer un one-shot au boot), sauf « kick » explicite d'un bootstrap.
if reaper.GetExtState("golem", "sample_kick") == "1" then
  reaper.SetExtState("golem", "sample_kick", "", false)
  last_seq = nil
else
  local _, body = reaper.GetProjExtState(0, "golem", "sample_cmd")
  last_seq = body and body:match('"seq"%s*:%s*(%-?%d+)') or nil
end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "sample_gen") ~= GEN then return end   -- remplacée : cette boucle meurt
  reaper.SetExtState("golem", "sample_alive", string.format("%.3f", reaper.time_precise()), false)
  -- pcall : une erreur d'un tick NE TUE JAMAIS la boucle (defer qui lève = chaîne morte silencieuse)
  local ok, err = pcall(tick)
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

publish(true)
log("démarré. piste=" .. TRACK .. " ; sortie=" .. OUT)
loop()
