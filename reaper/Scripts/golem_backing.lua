-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — backing tracks (veilleur d'état + exécuteur de commandes)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_tuner/golem_looper).
  Joue les stems golem.fm (6 mp3 alignés : vocals/drums/bass/guitar/piano/other)
  sur un bus permanent « Backing Track » + 6 pistes enfants, mixés en dur vers
  OUT 1/2 avec le rig live. Cf. plan polished-watching-meadow (conception validée).

  Commandes : golem_watch relaie {"action":"backing",...} en ProjExtState
  golem/backing_cmd (branche exempte de SETTLE — on ne touche JAMAIS au graphe FX,
  seulement aux ITEMS de nos propres pistes ; le bridge séquence lui-même à +0,7 s
  d'un rig_recall). Ops :
    load   {seq, slug, dir, mix{stem:{mute,vol}}}  — dir = dossier absolu des stems
    unload {seq}
    seek   {seq, pos}
    mix    {seq, stem, mute, vol}
    mute   {seq, on}                — coupe/rétablit le bus SANS toucher au transport
  play/pause/stop passent NORMALEMENT en OSC /action (1007/1008/1016 + 40042 — latence
  pied minimale) SAUF pendant une prise perf-rec : ces actions sont des commandes de
  TRANSPORT GLOBAL, et golem_perfrec enregistre en mode "output" sur le MÊME transport —
  1016 (stop) en particulier CLÔT l'item en cours d'enregistrement (régression 2026-07-26,
  retour utilisateur : « je lance l'enregistrement, le backing se lance, je le coupe » ->
  prise tronquée à la seconde près). bridge/backing.py route alors ici (op "mute") au lieu
  d'OSC quand presets/.perf.json dit recording=true — cf. golem_perfrec pour le pendant
  « auto-mute au démarrage d'une prise si le backing n'était pas DÉJÀ en lecture ».

  État publié : presets/.backing.json (tmp+rename, fingerprint + 4 Hz quand ça joue)
  {present, slug, playing, paused, pos, len, stems:{name:{mute,vol}}}.

  Invariants (spike golem-reascript 2026-07-10) :
   - pistes créées UNE fois (au premier load), JAMAIS supprimées — muettes si inutilisées.
     Le nom « Backing Track… » ne matche AUCUN pattern de purge de golem_rig (vérifié).
   - on ne manipule que des ITEMS (jamais de pistes, jamais de FX) -> aucun risque
     vis-à-vis des chargements NAM/IR asynchrones.
   - mute/volume par NOM de piste ICI (jamais d'index OSC absolu côté bridge : l'index
     des enfants bouge avec les sous-pistes de preset).
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
    _LOGF = root .. "/presets/.backing.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-backing] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local OUT  = ROOT .. "/presets/.backing.json"
local BUS     = "Backing Track"
local OLD_BUS = "Sandbox #Backing"     -- ancien nom : migré au vol (bus + stems) dans ensure_tracks
-- ordre fixe (les 6 stems séparés du vocabulaire de golem.fm) — les noms de pistes en découlent
local STEMS = { "vocals", "drums", "bass", "guitar", "piano", "other" }
local IS_SIX = {}
for _, s in ipairs(STEMS) do IS_SIX[s] = true end
-- ── UNE PISTE PAR STEM (plan-song-sharing lot 1.6, 2026-10-08) ──────────────────────────────────────
-- Un original enregistré au golem a UN STEM PAR INSTRUMENT, sans plafond (golem-format.md §5) : `guitar-1`,
-- `guitar-2`, `voice-1`… Les six pistes permanentes restent (karaoké, suivi de tab et mix enregistrés les nomment) ;
-- tout autre stem reçoit SA piste « Backing Track <nom> », créée à la demande et, comme les six, jamais supprimée —
-- vide et muette quand la chanson suivante n'en a pas. `extra` = ces noms.
-- ⚠ AJOUTÉE EN FIN DE PROJET, reliée au bus par un ENVOI — pas insérée dans son dossier (relecture reascript,
-- 2026-10-08) : insérer après le bus DÉCALAIT toutes les pistes suivantes, dont les sous-pistes de lane, et la
-- livemap de la pédale EXP (numéros de piste absolus, écrits au build) visait alors la piste VOISINE jusqu'au
-- rebuild suivant. En fin de projet rien ne bouge ; l'envoi (audio seul : I_MIDIFLAGS 31, CLAUDE.md) passe par le
-- bus, donc sa coupure (op mute, perf-rec) la coupe aussi, quelle que soit la forme du dossier.
local NAME = "[%w%-_]+"                    -- un nom de stem : lettres, chiffres, tiret, souligné
local extra = {}                           -- noms des pistes de stem hors des six (redérivés du projet)

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr, i end
  end
  return nil, -1
end

local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

local function jnum(x) return string.format("%.4g", x or 0) end

-- ── pistes : bus + 6 enfants, créés UNE fois (paresseusement, au premier load) ──
local function stem_track_name(stem) return BUS .. " " .. stem end

-- migration douce : nouveau bus absent + ancien présent -> RENOMMER le bus + ses 6 stems (jamais de
-- doublon ; items déjà chargés préservés). Ne CRÉE rien.
local function migrate_tracks()
  if find_track(BUS) then return end
  local old = find_track(OLD_BUS)
  if not old then return end
  reaper.GetSetMediaTrackInfo_String(old, "P_NAME", BUS, true)
  for _, stem in ipairs(STEMS) do
    local ot = find_track(OLD_BUS .. " " .. stem)
    if ot then reaper.GetSetMediaTrackInfo_String(ot, "P_NAME", stem_track_name(stem), true) end
  end
  log("pistes migrées : « " .. OLD_BUS .. " » (+ stems) -> « " .. BUS .. " »")
end

local function ensure_tracks()
  migrate_tracks()
  local bus = find_track(BUS)
  if bus then return bus end
  reaper.PreventUIRefresh(1)
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, false)
  bus = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(bus, "P_NAME", BUS, true)
  reaper.SetMediaTrackInfo_Value(bus, "I_NCHAN", 2)
  reaper.SetMediaTrackInfo_Value(bus, "I_RECINPUT", -1)
  reaper.SetMediaTrackInfo_Value(bus, "I_RECMON", 0)
  reaper.SetMediaTrackInfo_Value(bus, "I_RECARM", 0)
  reaper.SetMediaTrackInfo_Value(bus, "D_VOL", 1)
  reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", 1)         -- muet tant que rien n'est chargé
  reaper.SetMediaTrackInfo_Value(bus, "I_FOLDERDEPTH", 1)  -- parent du dossier stems
  for si, stem in ipairs(STEMS) do
    local ci = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(ci, false)
    local tr = reaper.GetTrack(0, ci)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", stem_track_name(stem), true)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
    -- dernier enfant ferme le dossier ; les enfants sortent par le parent (B_MAINSEND=1 défaut)
    reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", si == #STEMS and -1 or 0)
  end
  -- sortie hardware OUT 1/2, jamais par le Master (même règle que looper/rig)
  for si = reaper.GetTrackNumSends(bus, 1) - 1, 0, -1 do reaper.RemoveTrackSend(bus, 1, si) end
  local hw = reaper.CreateTrackSend(bus, nil)
  reaper.SetTrackSendInfo_Value(bus, 1, hw, "I_DSTCHAN", 0)
  reaper.SetMediaTrackInfo_Value(bus, "B_MAINSEND", 0)
  reaper.PreventUIRefresh(-1)
  log("pistes créées (permanentes) : " .. BUS .. " + " .. #STEMS .. " stems")
  return bus
end

-- la piste d'un stem HORS des six : AJOUTÉE en fin de projet (aucun index existant ne bouge), sans envoi au
-- Master, un envoi audio vers le bus. Rend la piste.
local function ensure_stem_track(name)
  local tr = find_track(stem_track_name(name))
  if tr then return tr end
  local bus = find_track(BUS)
  if not bus then return nil end
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, false)
  tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", stem_track_name(name), true)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
  reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", 0)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)          -- jamais vers le Master
  local si = reaper.CreateTrackSend(tr, bus)                  -- index = la valeur RETOURNÉE (CLAUDE.md)
  reaper.SetTrackSendInfo_Value(tr, 0, si, "I_MIDIFLAGS", 31) -- audio seul : un send porte le MIDI par défaut
  local seen = false
  for _, x in ipairs(extra) do if x == name then seen = true end end
  if not seen then extra[#extra + 1] = name end
  log("piste de stem créée : " .. stem_track_name(name))
  return tr
end

-- les noms des pistes de stem hors des six, relus dans le projet (au démarrage du script)
local function scan_extra()
  extra = {}
  local pre = BUS .. " "
  for i = 0, reaper.CountTracks(0) - 1 do
    local _, nm = reaper.GetSetMediaTrackInfo_String(reaper.GetTrack(0, i), "P_NAME", "", false)
    if nm:sub(1, #pre) == pre then
      local name = nm:sub(#pre + 1)
      if not IS_SIX[name] and name:match("^" .. NAME .. "$") then extra[#extra + 1] = name end
    end
  end
end

-- toutes les pistes de stem : les six, puis les autres TRIÉES (un ordre stable, avant comme après un redémarrage)
local function all_stems()
  local out = {}
  for _, s in ipairs(STEMS) do out[#out + 1] = s end
  local ex = {}
  for _, s in ipairs(extra) do ex[#ex + 1] = s end
  table.sort(ex)
  for _, s in ipairs(ex) do out[#out + 1] = s end
  return out
end

-- les stems PUBLIÉS : les six, et les autres seulement s'ils portent un item (la chanson chargée) — une piste
-- extra d'une chanson précédente, vide et muette, n'a rien à faire dans l'état d'aujourd'hui
local function published_stems()
  local out = {}
  for _, s in ipairs(all_stems()) do
    local keep = IS_SIX[s]
    if not keep then
      local tr = find_track(stem_track_name(s))
      keep = tr ~= nil and reaper.CountTrackMediaItems(tr) > 0
    end
    if keep then out[#out + 1] = s end
  end
  return out
end

-- ── items : séquence validée par le spike (jamais InsertMedia — sélection/curseur) ──
local function clear_items(tr)
  for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do
    reaper.DeleteTrackMediaItem(tr, reaper.GetTrackMediaItem(tr, i))
  end
end

local function load_stem(tr, path)
  local f = io.open(path, "r")
  if not f then return 0 end
  f:close()
  local item = reaper.AddMediaItemToTrack(tr)
  local take = reaper.AddTakeToMediaItem(item)
  local src  = reaper.PCM_Source_CreateFromFile(path)      -- ownership -> take, ne pas libérer
  reaper.SetMediaItemTake_Source(take, src)
  local len  = reaper.GetMediaSourceLength(src)
  reaper.SetMediaItemInfo_Value(item, "D_POSITION", 0)
  reaper.SetMediaItemInfo_Value(item, "D_LENGTH", len)
  reaper.SetMediaItemInfo_Value(item, "B_LOOPSRC", 0)      -- défaut 1 -> OFF obligatoire
  return len
end

-- ── LE CLICK DU MORCEAU (docs/bars-format.md, 2026-10-07) ─────────────────────────────────────────────
-- Un groupe joué sans click n'a pas UN tempo (Paper Kite : 85 -> 89 BPM). Le bridge écrit les VRAIS temps de
-- la backing (`ticks` = fichier « ms accent » par ligne, tiré de la carte des mesures de golem.fm) ; on les pose
-- en notes 76 (le « 1 ») / 77 sur UN item MIDI de la piste Click, à la position 0 comme les stems. Ils suivent
-- donc le transport à l'échantillon — pause, retour en arrière, prise — sans horloge à mettre d'accord.
-- golem_click (slider `song`) les joue à la place de son compteur, exactement comme la grille d'un standard.
-- L'item porte P_EXT:golem = golem_songclick : c'est lui, et lui seul, qu'on retire au chargement suivant.
local CLICK_TRACK = "Click"
local SONGCLICK_TAG = "golem_songclick"
-- ⚠ LA PISTE CLICK N'EXISTE PAS FORCÉMENT AU CHARGEMENT (2026-10-08, premier test au rig : « le click ne se lance
-- pas ») : golem_click ne la crée qu'à sa PREMIÈRE commande, et au démarrage de REAPER la backing est rechargée
-- AVANT. On RETIENT les temps et on les pose dès que la piste apparaît (tick). Et on PUBLIE le nombre de temps
-- réellement posés (`songclick` dans .backing.json) : le bridge n'active le mode « morceau » du click QUE s'il y en
-- a — sinon le JSFX attendrait des notes qui n'existent pas, en silence.
local songclick_n = 0           -- temps posés sur la piste Click (publié)
local songclick_pending = nil   -- {path, len} : à poser dès que la piste Click existe

-- ── LES GROUPES D'ACCENTS (3+2+2) DANS LE CLICK DU MORCEAU (2026-10-15, docs/bars-format.md §5) ──
-- Le fichier de temps ne dit que « le 1 » (accent 1) ou « un autre temps » (0) ; le groupement vit dans
-- l'ARRANGEMENT (signature de la section), pas dans la carte des mesures. On n'invente donc rien ici : on porte
-- l'INDEX du temps dans la mesure, en VÉLOCITÉ (index + 1, 1..99), et golem_click.jsfx accentue le temps dont le
-- bit du masque de groupes (poussé par le bridge avec la mesure de la section) est à 1. Un temps lu avant le
-- premier « 1 » (levée coupée à 0 s) n'a pas d'index sûr : vélocité 100 = « inconnu », comme les items d'avant —
-- le JSFX compte alors lui-même depuis le dernier 76.
-- PURE (aucun appel reaper) : tests/test_click_phase.py l'exécute telle quelle sous lupa. Ne pas la renommer
-- sans le test. Rend {{t = s, note = 76|77, vel = 1..100}, …} et le nombre de lignes ignorées.
local function songclick_parse(text)
  local out, skipped, k = {}, 0, nil
  for line in (text .. "\n"):gmatch("([^\n]*)\n") do
    local ms, acc = line:match("^(%d+)%s+(%d)")
    if ms then
      if acc == "1" then k = 0 elseif k then k = k + 1 end
      out[#out + 1] = { t = tonumber(ms) / 1000.0, note = (acc == "1") and 76 or 77,
                        vel = (k and k < 99) and (k + 1) or 100 }
    elseif line:match("%S") then skipped = skipped + 1 end    -- ms négatif (levée avant 0) : rien ne s'y place
  end
  return out, skipped
end

local function clear_songclick()
  songclick_n = 0
  local tr = find_track(CLICK_TRACK)
  if not tr then return end
  for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    local _, tag = reaper.GetSetMediaItemInfo_String(it, "P_EXT:golem", "", false)
    if tag == SONGCLICK_TAG then reaper.DeleteTrackMediaItem(tr, it) end
  end
end

local function load_songclick(path, len)
  clear_songclick()
  songclick_pending = nil
  if not path or path == "" then return end
  local tr = find_track(CLICK_TRACK)
  if not tr then
    songclick_pending = { path, len }
    log("piste « " .. CLICK_TRACK .. " » pas encore créée : les temps du click seront posés dès qu'elle existe")
    return
  end
  local f = io.open(path, "r")
  if not f then log("⚠ temps du click illisibles : " .. path) return end
  local ticks, skipped = songclick_parse(f:read("*a") or "")
  f:close()
  if skipped > 0 then log(string.format("click du morceau : %d temps avant 0 s ignorés", skipped)) end
  if #ticks == 0 then log("⚠ fichier de temps vide : " .. path) return end
  local last = ticks[#ticks].t + 1.0
  if len and len > last then last = len end
  local item = reaper.CreateNewMIDIItemInProj(tr, 0, last, false)     -- en SECONDES (qnIn = false)
  if not item then log("⚠ item MIDI du click non créé") return end
  -- base de temps TEMPS : un changement de tempo du projet (rappel d'un preset) ne doit pas déplacer les temps
  reaper.SetMediaItemInfo_Value(item, "C_BEATATTACHMODE", 0)
  reaper.GetSetMediaItemInfo_String(item, "P_EXT:golem", SONGCLICK_TAG, true)
  local take = reaper.GetActiveTake(item)
  for _, tk in ipairs(ticks) do
    local p0 = reaper.MIDI_GetPPQPosFromProjTime(take, tk.t)
    local p1 = reaper.MIDI_GetPPQPosFromProjTime(take, tk.t + 0.03)
    -- canal 16 (index 15) = les temps du MORCEAU : le JSFX ne les confond pas avec la grille d'un standard.
    -- vélocité = index du temps + 1 (groupes d'accents, songclick_parse)
    reaper.MIDI_InsertNote(take, false, false, p0, p1, 15, tk.note, tk.vel, true)   -- noSort
  end
  reaper.MIDI_Sort(take)
  -- ⚠ FIGER LE TEMPS (relecture reascript-engineer, 2026-10-07). C_BEATATTACHMODE ne règle que la base de temps de
  -- l'ITEM : le CONTENU d'une source MIDI reste en PPQ et suit le tempo du projet — que golem_rig change au rappel
  -- ET à chaque scene_apply (SetCurrentBPM). Sans ceci, tous les temps glisseraient dès qu'un BPM change. On
  -- fige la source au tempo T de la création : le PPQ calculé à T ne bouge plus. Et jamais de boucle de source.
  reaper.SetMediaItemInfo_Value(item, "B_LOOPSRC", 0)
  local T = reaper.Master_GetTempo()
  if reaper.BR_SetMidiTakeTempoInfo then                       -- SWS : (take, ignoreProjTempo, bpm, num, den)
    reaper.BR_SetMidiTakeTempoInfo(take, true, T, 4, 4)
  else                                                         -- sans SWS : chunk de l'ITEM (aucun FX touché)
    local ok, ck = reaper.GetItemStateChunk(item, "", false)
    if ok then
      local n
      ck, n = ck:gsub("IGNTEMPO %d+ [%d%.]+", string.format("IGNTEMPO 1 %.6f", T), 1)
      if n == 0 then ck = ck:gsub("(<SOURCE MIDI\r?\n)", string.format("%%1IGNTEMPO 1 %.6f 4 4\n", T), 1) end
      reaper.SetItemStateChunk(item, ck, false)
    end
  end
  songclick_n = #ticks
  log(string.format("click du morceau : %d temps posés sur la piste %s (%.1f s)", #ticks, CLICK_TRACK, last))
end

-- ── état runtime (redérivable : survit à un restart du script) ──
local cur_slug = nil       -- persisté en ProjExtState pour l'affichage après reload
local cur_len  = 0
local mix_state = {}       -- stem -> {mute=0/1, vol=num} (miroir de ce qu'on a appliqué)

local function count_songclick()
  -- au (re)démarrage du script : l'item du click du morceau est peut-être déjà là (projet sauvé)
  local tr = find_track(CLICK_TRACK)
  if not tr then return 0 end
  for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    local _, tag = reaper.GetSetMediaItemInfo_String(it, "P_EXT:golem", "", false)
    if tag == SONGCLICK_TAG then
      local tk = reaper.GetActiveTake(it)
      local _, n = reaper.MIDI_CountEvts(tk)
      return n or 0
    end
  end
  return 0
end

local function derive_state()
  songclick_n = count_songclick()
  -- redérive slug/len/mix depuis le projet (au (re)démarrage du script)
  local _, slug = reaper.GetProjExtState(0, "golem", "backing_slug")
  cur_slug = (slug ~= "" and slug) or nil
  cur_len = 0
  scan_extra()
  for _, stem in ipairs(all_stems()) do
    local tr = find_track(stem_track_name(stem))
    if tr then
      if reaper.CountTrackMediaItems(tr) > 0 then
        local it = reaper.GetTrackMediaItem(tr, 0)
        local l = reaper.GetMediaItemInfo_Value(it, "D_LENGTH")
        if l > cur_len then cur_len = l end
      end
      mix_state[stem] = {
        mute = math.floor(reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") + 0.5),
        vol  = reaper.GetMediaTrackInfo_Value(tr, "D_VOL"),
      }
    end
  end
  if cur_len == 0 then cur_slug = nil end
end

local function apply_mix(stem, mute, vol)
  local tr = find_track(stem_track_name(stem))
  if not tr then return end
  if mute ~= nil then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", mute) end
  if vol  ~= nil then reaper.SetMediaTrackInfo_Value(tr, "D_VOL", vol) end
  mix_state[stem] = {
    mute = math.floor(reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") + 0.5),
    vol  = reaper.GetMediaTrackInfo_Value(tr, "D_VOL"),
  }
end

-- ── commandes (ProjExtState golem/backing_cmd, posé par golem_watch) ──
local last_seq = nil
-- LE SAUT DE SECTION DE LA PAGE RÉPÈTE (docs/live-pages.md §6.2, 2026-10-15), fait ICI, dans Reaper :
--   vers l'arrière ou sur place : boucle native [to, at] armée tout de suite (le saut tombe à l'échantillon) ; elle est
--   LEVÉE par ce script au premier rebouclage constaté — pas après un aller-retour par le bridge.
--   vers l'avant : seek quand le transport atteint `at` (gigue du defer, ~30 ms).
local jump_lift = false          -- une boucle de SAUT est armée : on la lève au rebouclage
local jump_fwd = nil             -- { at, to } : seek à faire en atteignant `at`
local was_rolling = false        -- le transport tournait (lecture ou pause) au tick précédent
local last_pos = nil             -- position du tick précédent (discontinuités)
local force_pub = false         -- publier au prochain tick, sans throttle (les locals last_pub/last_fp sont déclarés plus bas)

-- un saut armé n'appartient qu'à la chanson et à la lecture où on l'a armé (audit 2026-10-15) : sans ça, un saut en
-- avant armé dans la chanson N partait à la même seconde de la N+1, et la boucle de saut d'une lecture arrêtée se
-- rejouait au Play suivant. Levé au chargement, au déchargement, au seek et à l'ARRÊT du transport.
local function clear_jump(why)
  if jump_lift then
    reaper.GetSetRepeatEx(0, 0)
    reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)
  end
  if jump_lift or jump_fwd then log("saut armé levé (" .. why .. ")") end
  jump_lift, jump_fwd = false, nil
end

local function op_load(body)
  local slug = body:match('"slug"%s*:%s*"([^"]*)"')
  local dir  = body:match('"dir"%s*:%s*"([^"]*)"')
  if not slug or not dir then log("load : slug/dir manquants") return end
  clear_jump("chargement")
  local bus = ensure_tracks()
  reaper.PreventUIRefresh(1)
  reaper.Undo_BeginBlock()
  cur_len = 0
  -- backing LOCAL (2026-09-15) : {"files":{"vocals":"/abs/x.wav",...}} — un stem par emplacement,
  -- n'importe quel format que Reaper lit ; sans `files`, les six mp3 golem.fm du dossier.
  local files = body:match('"files"%s*:%s*({[^{}]*})')
  -- les stems HORS des six annoncés par `files` reçoivent leur piste AVANT la boucle (lot 1.6)
  if files then
    for name in files:gmatch('"(' .. NAME .. ')"%s*:%s*"') do
      if not IS_SIX[name] then ensure_stem_track(name) end
    end
  end
  for _, stem in ipairs(all_stems()) do
    local tr = find_track(stem_track_name(stem))
    if tr then
      clear_items(tr)
      local path = files and files:match('"' .. stem:gsub("%-", "%%-") .. '"%s*:%s*"([^"]*)"')
      if files and not path then path = nil                       -- emplacement vide : piste vide
      elseif not files then path = IS_SIX[stem] and (dir .. "/" .. stem .. ".mp3") or nil end
      if path then
        local len = load_stem(tr, path)
        if len > cur_len then cur_len = len end
      end
      -- REMISE À L'ÉTAT PAR DÉFAUT avant le mix de la commande (relecture reascript, 2026-10-08) : le bridge
      -- n'envoie qu'un mix PARTIEL (les stems touchés par l'utilisateur) — sans ceci, une piste coupée une fois
      -- (extra sans fichier, ou `vocals` d'un karaoké) restait coupée à la chanson suivante.
      -- Avec fichier : 0 dB non muette ; extra sans fichier : muette ; une des six sans fichier : vide, sans effet.
      apply_mix(stem, (path or IS_SIX[stem]) and 0 or 1, 1)
    end
  end
  -- mix initial : {"mix":{"guitar":{"mute":1,"vol":1},...}} — défaut tout à 0 dB non muté
  for stem in body:gmatch('"(' .. NAME .. ')"%s*:%s*{[^{}]-"mute"') do
    local obj = body:match('"' .. stem:gsub("%-", "%%-") .. '"%s*:%s*({[^{}]*})')
    if obj then
      local mute = tonumber(obj:match('"mute"%s*:%s*(%d+)'))
      local vol  = tonumber(obj:match('"vol"%s*:%s*([%d%.]+)'))
      apply_mix(stem, mute, vol)
    end
  end
  load_songclick(body:match('"ticks"%s*:%s*"([^"]*)"'), cur_len)    -- absent : l'item d'avant est retiré
  reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", 0)
  reaper.SetEditCurPos(0, false, false)
  reaper.GetSetRepeatEx(0, 0)                            -- nouvelle chanson : boucle A/B annulée
  reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)
  reaper.Undo_EndBlock("GoleM backing load " .. slug, -1)
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  reaper.UpdateTimeline()
  cur_slug = slug
  reaper.SetProjExtState(0, "golem", "backing_slug", slug)
  log("load " .. slug .. " (len " .. string.format("%.1f", cur_len) .. " s)")
end

local function op_unload()
  clear_jump("déchargement")
  local bus = find_track(BUS)
  if not bus then return end
  if reaper.GetPlayState() & 1 == 1 then reaper.Main_OnCommand(1016, 0) end
  reaper.PreventUIRefresh(1)
  for _, stem in ipairs(all_stems()) do
    local tr = find_track(stem_track_name(stem))
    if tr then clear_items(tr) end
  end
  clear_songclick()
  reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", 1)
  reaper.GetSetRepeatEx(0, 0)
  reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)
  reaper.PreventUIRefresh(-1)
  reaper.UpdateArrange()
  cur_slug = nil; cur_len = 0
  reaper.SetProjExtState(0, "golem", "backing_slug", "")
  log("unload")
end

local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "backing_cmd")
  if not body or body == "" then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if not seq or seq == last_seq then return end
  last_seq = seq
  local op = body:match('"op"%s*:%s*"([^"]+)"')
  if op == "load" then op_load(body)
  elseif op == "unload" then op_unload()
  elseif op == "seek" then
    local pos = tonumber(body:match('"pos"%s*:%s*([%d%.]+)')) or 0
    clear_jump("seek")                                   -- AVANT : la boucle d'un saut levée n'avale pas le seek
    reaper.SetEditCurPos(pos, false, true)               -- seekplay=true : suit aussi en lecture
  elseif op == "jump" then
    local at = tonumber(body:match('"at"%s*:%s*([%d%.]+)'))
    local to = tonumber(body:match('"to"%s*:%s*([%d%.]+)'))
    if at and to then
      local ps0 = reaper.GetPlayState()
      local p0 = (ps0 & 1) == 1 and reaper.GetPlayPosition2() or nil
      if p0 and p0 >= at - 0.005 then
        -- ARMÉ TROP TARD : la frontière est passée (le moteur a déjà appliqué la cible) — on rejoint la cible tout de
        -- suite, à la même distance de son début ; une boucle armée ici ne serait jamais levée (relecture ingé son)
        reaper.SetEditCurPos(to + (p0 - at), false, true)
        jump_lift, jump_fwd = false, nil
        force_pub = true
        log(string.format("saut armé trop tard (%.2f > %.2f s) : seek immédiat vers %.2f s", p0, at, to + (p0 - at)))
      elseif to < at then
        reaper.GetSet_LoopTimeRange(true, true, to, at, false)
        reaper.GetSetRepeatEx(0, 1)
        jump_lift, jump_fwd = true, nil
        log(string.format("saut armé : boucle %.2f -> %.2f s (levée au rebouclage)", to, at))
      else
        reaper.GetSetRepeatEx(0, 0)
        reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)
        jump_lift, jump_fwd = false, { at = at, to = to }
        log(string.format("saut armé : à %.2f s, seek vers %.2f s", at, to))
      end
    end
  elseif op == "loop" then
    -- boucle A/B : repeat NATIF Reaper (échantillon-précis, aucun glitch au bouclage)
    jump_lift, jump_fwd = false, nil                   -- une boucle (ou sa levée) remplace un saut armé
    if body:find('"off"', 1, true) then
      reaper.GetSetRepeatEx(0, 0)
      reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)
      log("loop OFF")
    else
      local a = tonumber(body:match('"a"%s*:%s*([%d%.]+)'))
      local b = tonumber(body:match('"b"%s*:%s*([%d%.]+)'))
      if a and b and b > a then
        reaper.GetSet_LoopTimeRange(true, true, a, b, false)
        reaper.GetSetRepeatEx(0, 1)
        -- si le curseur est hors de la boucle, on rentre dedans tout de suite
        local ps = reaper.GetPlayState()
        local pos = (ps & 3) ~= 0 and reaper.GetPlayPosition() or reaper.GetCursorPosition()
        if pos < a or pos >= b then reaper.SetEditCurPos(a, false, true) end
        log(string.format("loop A/B : %.2f -> %.2f s", a, b))
      end
    end
  elseif op == "mix" then
    local stem = body:match('"stem"%s*:%s*"(' .. NAME .. ')"')
    if stem then
      apply_mix(stem,
        tonumber(body:match('"mute"%s*:%s*(%d+)')),
        tonumber(body:match('"vol"%s*:%s*([%d%.]+)')))
    end
  elseif op == "mute" then
    -- coupe/rétablit le BUS (silence) sans jamais toucher au transport (cf. en-tête) :
    -- utilisé par bridge/backing.py à la place d'OSC play/pause/stop pendant une prise perf-rec.
    local bus = find_track(BUS)
    if bus then
      local on = body:find('"on"%s*:%s*true') ~= nil
      reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", on and 1 or 0)
      log("mute (perf-rec actif) : " .. (on and "ON" or "OFF"))
    end
  end
end

-- ── publication d'état ──
local function loop_state()
  -- boucle A/B active ? (repeat natif + time selection non vide)
  local rep = reaper.GetSetRepeatEx(0, -1)
  local a, b = reaper.GetSet_LoopTimeRange(false, true, 0, 0, false)
  local on = rep == 1 and b > a
  return on, a or 0, b or 0
end

-- FINS DE CHANSON (docs/karaoke.md §2.3, 2026-10-06) : un compteur, publié. Vu du bridge, la fin
-- (stop + retour à 0 ci-dessous) ressemblait trait pour trait à un stop demandé — or golem.fm enchaîne
-- sa playlist sur la FIN, jamais sur une pause ni un stop. Le compteur ne bouge qu'ici.
local ends = 0

local function build_json(present, playing, paused, pos)
  if not present then return '{"present":false,"ends":' .. ends .. '}' end
  local stems = {}
  for _, stem in ipairs(published_stems()) do
    local m = mix_state[stem] or { mute = 0, vol = 1 }
    stems[#stems+1] = string.format('"%s":{"mute":%d,"vol":%s}', stem, m.mute, jnum(m.vol))
  end
  local lon, la, lb = loop_state()
  if jump_lift then lon = false end                   -- la boucle d'un SAUT armé n'est pas une boucle A/B : ne pas l'afficher
  return string.format(
    '{"present":true,"slug":"%s","playing":%s,"paused":%s,"pos":%s,"len":%s,"loop":{"on":%s,"a":%s,"b":%s},"stems":{%s},"ends":%d,"songclick":%d}',
    cur_slug or "", playing and "true" or "false", paused and "true" or "false",
    jnum(pos), jnum(cur_len), lon and "true" or "false", jnum(la), jnum(lb),
    table.concat(stems, ","), ends, songclick_n)
end

local last_fp = nil
local last_pub = 0
local wrote_off = false

-- garde par génération (patron golem_click) : ce script est dans la liste blanche `reload`
-- de golem_apply — sans cette garde, un hot-swap lançait une DEUXIÈME boucle concurrente
-- qui se disputait .backing.json (le bug mesuré sur le looper le 2026-08-09).
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "backing_gen", GEN, false)

local function tick()
  poll_cmd()
  if songclick_pending and find_track(CLICK_TRACK) then        -- la piste Click vient d'apparaître
    local p = songclick_pending
    reaper.PreventUIRefresh(1)
    load_songclick(p[1], p[2])
    reaper.PreventUIRefresh(-1)
  end

  local present = cur_slug ~= nil and cur_len > 0
  if not present then
    if not wrote_off then
      write_atomic(OUT, build_json(false))
      wrote_off = true; last_fp = nil
    end
    return
  end
  wrote_off = false

  local ps = reaper.GetPlayState()                        -- &1 play, &2 pause
  local playing = (ps & 1) == 1
  local paused  = (ps & 2) == 2
  -- position : playhead si le transport est engagé (lecture OU pause), curseur d'édition sinon
  local pos = (ps & 3) ~= 0 and reaper.GetPlayPosition() or reaper.GetCursorPosition()

  -- fin de chanson : stop + retour à 0 (ceinture-bretelles avec « stop at end of project »)
  -- SAUF si une boucle A/B tourne : le repeat natif rembobine tout seul, on ne le tue pas.
  local lon, la, lb = loop_state()
  -- perf_rec actif : NE PAS couper le transport en fin de morceau (ça finaliserait l'enregistrement).
  local _, _perf = reaper.GetProjExtState(0, "golem", "perf_rec")
  if playing and not paused and not lon and _perf ~= "1" and pos >= cur_len - 0.02 then
    reaper.Main_OnCommand(1016, 0)                        -- stop
    reaper.Main_OnCommand(40042, 0)                       -- go to start
    playing = false; pos = 0
    ends = ends + 1
    log("fin de chanson — stop + rewind")
  end

  -- ── LE SAUT DE SECTION (§6.2) ──
  if (ps & 3) == 0 and was_rolling then clear_jump("transport arrêté") end
  was_rolling = (ps & 3) ~= 0
  local jumped = false
  if playing and not paused then
    -- la position « traitée » (GetPlayPosition2), pas celle qu'on entend, avec un tick defer de marge (~35 ms) : couper
    -- la fin de la section s'entend moins qu'une attaque de la suivante (relecture de l'ingénieur du son)
    if jump_fwd and reaper.GetPlayPosition2() >= jump_fwd.at - 0.035 then
      reaper.SetEditCurPos(jump_fwd.to, false, true)
      log(string.format("saut : %.2f -> %.2f s", pos, jump_fwd.to))
      pos = jump_fwd.to; jump_fwd = nil; jumped = true
    elseif jump_lift and last_pos and pos < last_pos - 0.05 then
      reaper.GetSetRepeatEx(0, 0)                         -- rebouclé : la boucle de SAUT a fait son travail
      reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)
      jump_lift = false; jumped = true
      log(string.format("saut fait (rebouclage à %.2f s) — boucle levée", pos))
    end
  end
  -- une DISCONTINUITÉ (saut, rebouclage, seek) se publie TOUT DE SUITE, sans le throttle de 0,2 s : l'arrangement
  -- se recale dessus, et chaque dixième de seconde d'avance est un dixième de seconde de mauvaise scène évité
  if force_pub or jumped or (last_pos and (pos < last_pos - 0.05 or pos > last_pos + 0.5)) then
    last_pub = 0; last_fp = nil; force_pub = false
  end
  last_pos = pos

  -- pos QUANTIFIÉ à 0,25 s dans le fingerprint : un seek (même en pause/stop) republie,
  -- et la lecture publie naturellement à 4 Hz (le fp change tous les 0,25 s de musique).
  local fp = string.format("%s|%s|%s|%d|%s|%d|%d|%d|%d", cur_slug, tostring(playing), tostring(paused),
                           math.floor(pos * 4), tostring(lon), math.floor(la * 4), math.floor(lb * 4), ends, songclick_n)
  for _, stem in ipairs(published_stems()) do
    local m = mix_state[stem] or { mute = 0, vol = 1 }
    fp = fp .. string.format("|%d,%.3f", m.mute, m.vol)
  end

  local now = reaper.time_precise()
  -- en lecture : throttle 0,2 s (le fp bouge tous les 0,25 s) ; à l'arrêt/en pause : publication immédiate
  if fp ~= last_fp and (not playing or now - last_pub >= 0.2) then
    last_fp = fp; last_pub = now
    write_atomic(OUT, build_json(true, playing, paused, pos))
  end
end

-- pcall blindé (leçon perfrec, audit 2026-08-12) : une erreur d'un tick NE TUE JAMAIS la boucle.
local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "backing_gen") ~= GEN then return end  -- remplacée : cette boucle meurt
  local ok, err = pcall(tick)
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

migrate_tracks()
derive_state()
-- ⚠ NE PAS REJOUER LA DERNIÈRE COMMANDE AU DÉMARRAGE (vécu le 2026-10-08, rechargement à chaud du lot 1.6) :
-- `last_seq` repartait à nil, et poll_cmd réexécutait la commande restée dans ProjExtState — un « mute ON »
-- d'une prise finie depuis dix minutes : le bus du backing est redevenu MUET, sans un geste de personne.
-- L'état est relu du projet (derive_state) ; la commande déjà là est donc considérée comme lue.
do
  local _, body0 = reaper.GetProjExtState(0, "golem", "backing_cmd")
  last_seq = body0 and body0:match('"seq"%s*:%s*(%-?%d+)') or nil
end
log("démarré. bus=" .. BUS .. " ; sortie=" .. OUT ..
    (cur_slug and (" ; chanson rechargée: " .. cur_slug) or ""))
loop()
