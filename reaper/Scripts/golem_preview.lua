-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — preview (guide sonore d'un preset, docs/preset-preview.md)
  Boucle defer PERMANENTE (lancée par __startup, comme tuner/looper/backing/perfrec/sample/drums).

  RÔLE : rendre, SUR COMMANDE, une prise WAV de la chaîne guitare/basse LIVE (scène courante),
  en re-ampant une phrase DI de référence. Le BRIDGE pilote le pas-à-pas des scènes (il applique
  chaque scène via le moteur testé PUIS envoie une commande "render") ; ce script ne fait QU'une
  chose par commande : cloner la chaîne live courante, y jouer le DI, capturer le wet, publier
  le WAV. Zéro logique de scène ici.

  ── Architecture (choisie « en connaissance de l'API », cf. feasibility agent) ──
  Le Master Reaper est VIDE (toutes les pistes sortent par un send HARDWARE, B_MAINSEND=0) —
  donc un render du Master = SILENCE. On rend un STEM de piste (render selected-tracks stems).

  ISOLATION (ne jamais polluer le son live que le mainteneur entend) :
    - piste CLONE jetable « GoleM:preview » : FX copiés de « Sandbox #Input 1 » via
      TrackFX_CopyToTrack (copie le CHUNK d'état -> NAM + IR déjà chargés, pas de reload async) ;
    - AUCUN send hardware + B_MAINSEND=0 -> physiquement inaudible ;
    - render OFFLINE (passe non-temps-réel, ne touche pas le transport live) ;
    - nom « GoleM:preview » -> matche le préfixe purgé par golem_rig.sweep_legacy (auto-nettoyé
      si un orphelin traîne). Le bridge séquence : jamais de rig_recall pendant un job preview.

  Commande : golem_watch relaie {"action":"preview",...} en ProjExtState golem/preview_cmd.
  Dédup par (seq, scene). Op unique :
    render {seq, scene, di:"<abs.wav>", out:"<abs.wav>", tail:5.0}

  État publié : presets/.preview.json (tmp+rename) — lu par le bridge :
    {"seq":N,"scene":"A","done":true,"wav":"<out>"}  |  {...,"error":"…"}

  ⚠ NON validable hors-rig (à confirmer sur le rig, cf. agent) :
    - render OFFLINE stem PENDANT le monitoring live sans xrun (LE point pivot) ;
    - valeur exacte du bitflag RENDER_SETTINGS « selected-tracks stems » ;
    - que TrackFX_CopyToTrack porte bien l'état NAM + le chemin IR x42 ;
    - split : le clone d'un dossier (merge gain + B_MUTE par branche) reproduit la somme.
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
    _LOGF = root .. "/presets/.preview.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-preview] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT  = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local OUT   = ROOT .. "/presets/.preview.json"
local CHAIN = "Sandbox #Input 1"       -- piste de la chaîne principale (guitare/basse) live
local CLONE = "GoleM:preview"          -- piste clone jetable (préfixe auto-purgé par sweep_legacy)

-- ── util JSON minimal (lecture de commande + écriture d'état) ──
local function jstr(s) return '"' .. tostring(s):gsub('\\', '\\\\'):gsub('"', '\\"') .. '"' end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

local function publish(tbl)
  local parts = {}
  for k, v in pairs(tbl) do
    local val = (type(v) == "boolean") and tostring(v) or (type(v) == "number" and tostring(v) or jstr(v))
    parts[#parts + 1] = jstr(k) .. ":" .. val
  end
  local tmp = OUT .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return end
  f:write("{" .. table.concat(parts, ",") .. "}"); f:close()
  runtime.replace(tmp, OUT)
end

-- ── cœur : clone la chaîne live + joue le DI + render WAV ──
-- Toutes les pistes clones portent le préfixe CLONE (« GoleM:preview », « GoleM:preview/2 »…) :
-- sweep_legacy de golem_rig les purge si un orphelin traîne.
local function is_clone(nm) return nm == CLONE or nm:sub(1, #CLONE + 1) == CLONE .. "/" end

local function delete_clone()
  for i = reaper.CountTracks(0) - 1, 0, -1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if is_clone(nm) then reaper.DeleteTrack(tr) end
  end
end

-- Les pistes d'UNE lane, dans l'ordre du projet (docs/reamp.md §5) : la racine « Sandbox #Input N »,
-- et avec `tree` ses sous-pistes — branches « …/<id> », dossier « …/merge » (golem_rig nomme ses
-- sous-pistes « racine/… » ou « racine#… »). Sans `tree` : la racine seule (preview d'avant).
local function lane_tracks(chain, tree)
  local out = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == chain or (tree and (nm:sub(1, #chain + 1) == chain .. "/" or nm:sub(1, #chain + 1) == chain .. "#")) then
      out[#out + 1] = tr
    end
  end
  return out
end

-- Le chunk d'une piste, NETTOYÉ pour un clone : ni ses sorties matérielles (HWOUT), ni ses retours
-- (AUXRECV : ils pointent les pistes LIVE, donc l'entrée du guitariste), ni ses GUID (TRACKID/FXID :
-- deux pistes au même GUID, et la mémoire P_EXT de golem_rig est indexée par FXID).
local function clone_chunk(tr)
  local ok, ch = reaper.GetTrackStateChunk(tr, "", false)
  if not ok then return nil end
  local keep = {}
  for line in (ch .. "\n"):gmatch("([^\n]*)\n") do
    local t = line:match("^%s*(%S+)")
    if t ~= "HWOUT" and t ~= "AUXRECV" and t ~= "TRACKID" and t ~= "FXID" then keep[#keep + 1] = line end
  end
  return table.concat(keep, "\n")
end

local SEND_KEYS = { "D_VOL", "D_PAN", "B_MUTE", "B_PHASE", "B_MONO", "I_SENDMODE", "I_SRCCHAN", "I_DSTCHAN", "I_MIDIFLAGS" }

-- 1er temps : clone la lane, pose la DI, arme la sélection de temps. Le rendu attend `settle` s :
-- le clone recharge ses plugins depuis leur chunk, et NAM charge son modèle dans un worker
-- ASYNCHRONE (CLAUDE.md, « le chunk MENT pendant qu'un plugin charge ») — rendre tout de suite,
-- c'était risquer un ampli sans modèle.
-- Une RÉFÉRENCE MIDI (claviers, batterie — 2026-11-03) : le bridge a lu le .mid et l'a daté EN SECONDES
-- (bridge/preview.midi_events) ; on pose ces événements sur un item MIDI neuf, à leurs temps réels. Ni le tempo
-- du projet (le click, les delays du rig en dépendent) ni celui du fichier n'ont à se croiser : la position se
-- convertit par MIDI_GetPPQPosFromProjTime.
--   len <secondes>
--   n <début> <fin> <canal> <note> <vélocité>
--   c <temps> <statut 0xB0/0xE0…> <canal> <d1> <d2>
local function read_midi_events(path)
  local f = io.open(path, "r")
  if not f then return nil end
  local ev = { len = 0, list = {} }
  for line in f:lines() do
    local k = line:sub(1, 1)
    if k == "l" then
      ev.len = tonumber(line:match("^len%s+([%d%.]+)")) or 0
    elseif k == "n" then
      local a, b, ch, p, v = line:match("^n%s+([%d%.]+)%s+([%d%.]+)%s+(%d+)%s+(%d+)%s+(%d+)")
      if a then ev.list[#ev.list + 1] = { "n", tonumber(a), tonumber(b), tonumber(ch), tonumber(p), tonumber(v) } end
    elseif k == "c" then
      local t, st, ch, d1, d2 = line:match("^c%s+([%d%.]+)%s+(%d+)%s+(%d+)%s+(%d+)%s+(%d+)")
      if t then ev.list[#ev.list + 1] = { "c", tonumber(t), tonumber(st), tonumber(ch), tonumber(d1), tonumber(d2) } end
    end
  end
  f:close()
  if ev.len <= 0 then return nil end
  return ev
end

local function lay_midi(track, ev)
  local item = reaper.CreateNewMIDIItemInProj(track, 0, ev.len, false)
  local take = item and reaper.GetActiveTake(item)
  if not take then return false end
  for _, e in ipairs(ev.list) do
    if e[1] == "n" then
      reaper.MIDI_InsertNote(take, false, false, reaper.MIDI_GetPPQPosFromProjTime(take, e[2]),
        reaper.MIDI_GetPPQPosFromProjTime(take, e[3]), e[4], e[5], e[6], true)
    else
      reaper.MIDI_InsertCC(take, false, false, reaper.MIDI_GetPPQPosFromProjTime(take, e[2]), e[3], e[4], e[5], e[6])
    end
  end
  reaper.MIDI_Sort(take)
  return true
end

-- ── LE RENDU D'UN BLOC (drum machine, standard — docs/preset-preview.md §8, 2026-11-06) ──
-- Ce que joue un bloc ne passe par aucune lane : la piste « Drums » (golem_drums) ou les pistes « Standard … »
-- (golem_chordseq) portent leur séquenceur JSFX PUIS l'instrument. Le bridge a d'abord posé les instruments sans rien
-- jouer (op « load ») et écrit 8 mesures de notes datées en secondes, une liste par piste. Chaque piste est clonée
-- par son chunk (le kit, le piano, l'arpégiateur, le mix multi-micros, le nombre de canaux), SANS son séquenceur —
-- il lirait la banque gmem partagée avec la piste vivante —, démutée, envoyée au master vide, et joue sa liste.
--   chains = "Standard Keys|Standard Bass"   midis = "<fichier>|<fichier>"   strip = "chordseq|drumseq"
local function split_bar(s)
  local t = {}
  for x in (s or ""):gmatch("[^|]+") do t[#t + 1] = x end
  return t
end

-- Un instrument qui CHARGE encore écrit un chunk sans son état (CLAUDE.md : « le chunk ment pendant qu'un plugin
-- charge ») : sfizz LV2 sans son fichier sfz, drumgizmo sans sa config de kit. Le clone hériterait d'un instrument
-- vide, et le rendu serait muet ou tardif. On refuse plutôt : le bridge refait, plus patient (relecture du 2026-11-06).
local function still_loading(chunk)
  local low = chunk:lower()
  if low:find("<lv2[^\n]*sfizz") and not low:find("sfzfile", 1, true) then return "sfizz" end
  if low:find("<lv2[^\n]*drumgizmo") and not low:find("atom#config", 1, true) then return "drumgizmo" end
  return nil
end

-- Le clone naît DÉSARMÉ : le chunk de la source porte « REC 1 … 1 2 » (armée, monitorée), et entre le
-- SetTrackStateChunk et un I_RECARM=0, le clone serait une piste du graphe vivant — chaque plugin s'y active sur le
-- thread audio du live. On met à 0 le 1er champ (armement) et le 3e (monitoring) avant de poser le chunk.
local function unarmed(chunk)
  return (chunk:gsub("\n(%s*)REC (%S+) (%S+) (%S+)", function(ind, _a, inp, _m) return "\n" .. ind .. "REC 0 " .. inp .. " 0" end, 1))
end

local function prepare_block_inner(cmd, parts, strip, desc)
  for k, p in ipairs(parts) do
    reaper.InsertTrackAtIndex(reaper.CountTracks(0), false)
    local cl = reaper.GetTrack(0, reaper.CountTracks(0) - 1)
    reaper.SetTrackStateChunk(cl, p.chunk, false)
    reaper.GetSetMediaTrackInfo_String(cl, "P_NAME", k == 1 and CLONE or (CLONE .. "/" .. k), true)
    reaper.SetMediaTrackInfo_Value(cl, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(cl, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(cl, "B_MUTE", 0)    -- une partie coupée sur la piste vivante joue ici
    reaper.SetMediaTrackInfo_Value(cl, "I_FOLDERDEPTH", 0)
    reaper.SetMediaTrackInfo_Value(cl, "B_MAINSEND", 1) -- le master est vide : seuls les clones y arrivent
    for fx = reaper.TrackFX_GetCount(cl) - 1, 0, -1 do
      local _, nm = reaper.TrackFX_GetFXName(cl, fx, "")
      nm = (nm or ""):lower()
      for _, s in ipairs(strip) do
        if nm:find(s:lower(), 1, true) then reaper.TrackFX_Delete(cl, fx); break end
      end
    end
    -- sans instrument (kit introuvable, plugin absent), le rendu serait muet deux fois : on le dit
    if reaper.TrackFX_GetCount(cl) == 0 then return nil, "pas d'instrument sur " .. p.name end
    if not lay_midi(cl, p.ev) then return nil, "item MIDI non créé" end
    local _, fx0 = reaper.TrackFX_GetFXName(cl, 0, "")
    desc[#desc + 1] = ("%s (%d FX, 1er : %s, %d évts)"):format(p.name, reaper.TrackFX_GetCount(cl), tostring(fx0 or "-"), #p.ev.list)
  end
  return true
end

local function prepare_block(cmd)
  local chains, midis, strip = split_bar(cmd.chains), split_bar(cmd.midis), split_bar(cmd.strip)
  if #strip == 0 then strip = { "drumseq", "chordseq" } end   -- jamais un séquenceur dans un clone
  if #chains == 0 or #chains ~= #midis then return nil, "chains/midis incohérents" end
  local parts, len = {}, 0
  for k, name in ipairs(chains) do
    local tr = find_track(name)
    if not tr then return nil, "piste " .. name .. " absente" end
    local ev = read_midi_events(midis[k])
    if not ev then return nil, "MIDI illisible : " .. tostring(midis[k]) end
    local chunk = clone_chunk(tr)
    if not chunk then return nil, "chunk illisible : " .. name end
    local busy = still_loading(chunk)
    if busy then return nil, busy .. " encore en chargement sur " .. name end
    parts[k] = { ev = ev, name = name, chunk = unarmed(chunk) }
    if ev.len > len then len = ev.len end
  end
  local desc = {}
  reaper.PreventUIRefresh(1)
  delete_clone()                                       -- un orphelin d'un job précédent
  -- l'UI se rafraîchit de nouveau quoi qu'il arrive dans la boucle (une erreur Lua laissait le compteur monté)
  local okc, res, err = pcall(prepare_block_inner, cmd, parts, strip, desc)
  reaper.PreventUIRefresh(-1)
  if not okc or not res then delete_clone(); return nil, okc and err or tostring(res) end
  log(("render bloc %s : %s"):format(tostring(cmd.scene), table.concat(desc, " · ")))
  return { len = len }
end

local function prepare(cmd)
  if cmd.chains then return prepare_block(cmd) end
  local chain = cmd.chain or CHAIN
  local src = lane_tracks(chain, cmd.tree)
  if #src == 0 then return nil, "piste " .. chain .. " absente" end
  local di_src, di_len, midi
  if cmd.midi then
    midi = read_midi_events(cmd.midi)
    if not midi then return nil, "MIDI illisible : " .. tostring(cmd.midi) end
    di_len = midi.len
  else
    di_src = reaper.PCM_Source_CreateFromFile(cmd.di)
    if not di_src then return nil, "DI illisible : " .. tostring(cmd.di) end
    di_len = reaper.GetMediaSourceLength(di_src)
  end

  reaper.PreventUIRefresh(1)
  delete_clone()                                       -- un orphelin d'un job précédent
  local map, clones, outs = {}, {}, 0
  for k, tr in ipairs(src) do
    reaper.InsertTrackAtIndex(reaper.CountTracks(0), false)
    local cl = reaper.GetTrack(0, reaper.CountTracks(0) - 1)
    if cmd.tree then
      local chunk = clone_chunk(tr)
      if chunk then reaper.SetTrackStateChunk(cl, chunk, false) end
    else                                               -- preview d'avant : les FX de la racine seule
      for fx = 0, reaper.TrackFX_GetCount(tr) - 1 do reaper.TrackFX_CopyToTrack(tr, fx, cl, fx, false) end
    end
    reaper.GetSetMediaTrackInfo_String(cl, "P_NAME", k == 1 and CLONE or (CLONE .. "/" .. k), true)
    reaper.SetMediaTrackInfo_Value(cl, "I_RECARM", 0)   -- jamais l'entrée live dans un clone
    reaper.SetMediaTrackInfo_Value(cl, "I_RECMON", 0)
    map[tostring(tr)] = cl
    clones[k] = { src = tr, cl = cl, hw = reaper.GetTrackNumSends(tr, 1) > 0 }
  end
  -- les sends INTERNES à la lane (racine -> branches), recréés entre clones ; l'index d'un send est
  -- la valeur RETOURNÉE par CreateTrackSend (CLAUDE.md, piège « catégorie 0 »)
  for _, c in ipairs(clones) do
    for s = 0, reaper.GetTrackNumSends(c.src, 0) - 1 do
      local dest = reaper.GetTrackSendInfo_Value(c.src, 0, s, "P_DESTTRACK")
      local dcl = dest and map[tostring(dest)]
      if dcl then
        local idx = reaper.CreateTrackSend(c.cl, dcl)
        for _, key in ipairs(SEND_KEYS) do
          reaper.SetTrackSendInfo_Value(c.cl, 0, idx, key, reaper.GetTrackSendInfo_Value(c.src, 0, s, key))
        end
      end
    end
  end
  -- la SORTIE : la piste qui portait le send matériel (le merge d'une lane splittée, la racine
  -- sinon) part au master — vide et sans sortie matérielle, donc muet aux baffles. Un enfant de
  -- dossier garde son envoi au parent ; toute autre piste de premier niveau n'envoie rien au master.
  for _, c in ipairs(clones) do
    if c.hw then outs = outs + 1; reaper.SetMediaTrackInfo_Value(c.cl, "B_MAINSEND", 1)
    elseif not reaper.GetParentTrack(c.cl) then reaper.SetMediaTrackInfo_Value(c.cl, "B_MAINSEND", 0) end
  end
  if not cmd.tree then outs = 1; reaper.SetMediaTrackInfo_Value(clones[1].cl, "B_MAINSEND", 1) end
  -- un dossier ouvert par le dernier clone se referme sur lui (les clones sont en fin de projet)
  local depth = 0
  for _, c in ipairs(clones) do depth = depth + reaper.GetMediaTrackInfo_Value(c.cl, "I_FOLDERDEPTH") end
  if depth > 0 then
    local last = clones[#clones].cl
    reaper.SetMediaTrackInfo_Value(last, "I_FOLDERDEPTH", reaper.GetMediaTrackInfo_Value(last, "I_FOLDERDEPTH") - depth)
  end
  -- ce qu'on a copié, au journal : une démo muette se lit ici (racine muette ? instrument absent ?)
  do
    local r = clones[1]
    local _, fx0 = reaper.TrackFX_GetFXName(r.cl, 0, "")
    log(("render %s/%s : %d piste(s), racine mute=%d, %d FX (1er : %s)%s"):format(tostring(cmd.scene), chain, #clones,
      math.floor(reaper.GetMediaTrackInfo_Value(r.src, "B_MUTE")), reaper.TrackFX_GetCount(r.cl), tostring(fx0 or "-"),
      midi and (", MIDI " .. #midi.list .. " évts") or ""))
  end
  -- la DI (ou la référence MIDI, jouée par l'instrument de la lane) entre par la racine clonée
  if midi then
    if not lay_midi(clones[1].cl, midi) then
      reaper.PreventUIRefresh(-1); delete_clone(); return nil, "item MIDI non créé"
    end
  else
    local item = reaper.AddMediaItemToTrack(clones[1].cl)
    local take = reaper.AddTakeToMediaItem(item)
    reaper.SetMediaItemTake_Source(take, di_src)
    reaper.SetMediaItemInfo_Value(item, "D_POSITION", 0)
    reaper.SetMediaItemInfo_Value(item, "D_LENGTH", di_len)
  end
  reaper.PreventUIRefresh(-1)
  if outs == 0 then delete_clone(); return nil, "la lane " .. chain .. " n'a pas de sortie" end
  return { len = di_len }
end

-- 2e temps : le rendu hors ligne (master = les clones seuls), puis on efface les clones.
local function finish(cmd, prep)
  local out, tail = cmd.out, tonumber(cmd.tail) or 5.0
  reaper.GetSet_LoopTimeRange(true, false, 0, prep.len + tail, false)
  -- Reaper traite RENDER_FILE comme un DOSSIER et RENDER_PATTERN comme le nom -> on découpe `out`
  -- (.../<scene>.wav) en dir + nom-sans-extension, sinon il crée un dossier <scene>.wav/ (corrigé).
  local out_dir  = out:match("^(.*)/[^/]*$") or out
  local out_name = out:match("/([^/]*)%.[%w]+$") or out:match("/([^/]*)$") or "preview"
  local old_sr = reaper.GetSetProjectInfo(0, "RENDER_SRATE", 0, false)
  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, true)      -- 0 = master mix
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 2, true)    -- 2 = time selection
  reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", 2, true)      -- stéréo (cab x42 + delays/reverbs)
  if tonumber(cmd.sr) then reaper.GetSetProjectInfo(0, "RENDER_SRATE", tonumber(cmd.sr), true) end
  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", out_dir, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", out_name, true)
  -- ⚠ le fichier de sortie d'un rendu PRÉCÉDENT s'efface AVANT (2026-10-01). S'il existe, Reaper
  -- ouvre une boîte MODALE « Render Warning — File already exists » : son thread principal s'arrête,
  -- plus aucune commande n'est lue (golem_watch gelé, 4 min 19 s mesurées) jusqu'à ce que quelqu'un
  -- clique — sur un rack sans écran Reaper, personne. Et le contrôle `file_exists` plus bas
  -- répondait « rendu fait » sur ce vieux fichier (daté du 09-28) : présent ne veut pas dire produit.
  os.remove(out)
  reaper.Main_OnCommand(42230, 0)                             -- render using most recent settings
  reaper.GetSetProjectInfo(0, "RENDER_SRATE", old_sr, true)
  delete_clone()
  if reaper.file_exists and reaper.file_exists(out) then return nil, out end
  local f = io.open(out, "rb"); if f then f:close(); return nil, out end
  return "render vide (offline à valider sur le rig)"
end

-- ── boucle defer : lit la commande relayée, dédup (seq, scene) ──
local last_key = ""
local pending = nil          -- { cmd, prep, at } : un clone qui laisse charger ses plugins

-- garde par génération (patron golem_click) : ce script est dans la liste blanche `reload`
-- de golem_apply — sans cette garde, un hot-swap lançait une DEUXIÈME boucle concurrente
-- (deux renders pour une commande, le bug looper du 2026-08-09).
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "preview_gen", GEN, false)

local function parse(cur)
  local seq = tonumber(cur:match('"seq"%s*:%s*(%d+)')) or 0
  return {
    seq = seq,
    op = cur:match('"op"%s*:%s*"([^"]+)"'),
    scene = cur:match('"scene"%s*:%s*"([^"]+)"'),
    di = cur:match('"di"%s*:%s*"([^"]+)"'),
    out = cur:match('"out"%s*:%s*"([^"]+)"'),
    tail = cur:match('"tail"%s*:%s*([%d%.]+)'),
    -- ⚠ `chain` N'ÉTAIT PAS LU avant le 2026-09-28 : toute preview clonait « Sandbox #Input 1 »,
    -- même quand le bridge demandait l'entrée 2 (voix). Trouvé en préparant le reamp.
    chain = cur:match('"chain"%s*:%s*"([^"]+)"'),
    tree = cur:match('"tree"%s*:%s*true') ~= nil,
    sr = cur:match('"sr"%s*:%s*(%d+)'),
    settle = tonumber(cur:match('"settle"%s*:%s*([%d%.]+)')) or 0,
    midi = cur:match('"midi"%s*:%s*"([^"]+)"'),
    chains = cur:match('"chains"%s*:%s*"([^"]+)"'),
    midis = cur:match('"midis"%s*:%s*"([^"]+)"'),
    strip = cur:match('"strip"%s*:%s*"([^"]+)"'),
  }
end

local function done(cmd, err, wav)
  if err then publish({ seq = cmd.seq, scene = cmd.scene, done = true, error = tostring(err) })
  else publish({ seq = cmd.seq, scene = cmd.scene, done = true, wav = wav or cmd.out }) end
end

local function poll()
  if pending then
    if reaper.time_precise() < pending.at then return end
    local p = pending; pending = nil
    local okr, e_or_nil, w = pcall(finish, p.cmd, p.prep)
    if not okr then delete_clone() end
    done(p.cmd, e_or_nil, w)
    return
  end
  local ok, cur = reaper.GetProjExtState(0, "golem", "preview_cmd")
  if ok == 1 and cur and #cur > 0 then
    local cmd = parse(cur)
    local key = tostring(cmd.seq) .. ":" .. tostring(cmd.scene)
    if key ~= last_key and cmd.op == "render" and (cmd.di or cmd.chains) and cmd.out then
      last_key = key
      local okp, prep, perr = pcall(prepare, cmd)
      if not okp then delete_clone(); done(cmd, prep); return end
      if not prep then done(cmd, perr); return end
      pending = { cmd = cmd, prep = prep, at = reaper.time_precise() + (cmd.settle or 0) }
    end
  end
end

-- pcall blindé (leçon perfrec, audit 2026-08-12) : do_render était gardé mais parse/publish
-- restaient à nu — une erreur d'un tick NE TUE JAMAIS la boucle.
local err_streak = 0
local function tick()
  if reaper.GetExtState("golem", "preview_gen") ~= GEN then return end  -- remplacée : cette boucle meurt
  local okt, err = pcall(poll)
  if not okt then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(tick)
end

log("preview loop armée")
tick()
