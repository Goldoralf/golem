-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — click (métronome du rig)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_tuner/sample/drums/clock).
  Fait ticquer un métronome TRANSPORT ARRÊTÉ, avec une sortie hardware ROUTABLE.

  ── Pourquoi PAS le métronome natif (choix « en connaissance de l'API ») ──
  Le rig est monitoré transport à l'arrêt (le transport ne roule que pour backing/perf-rec).
  Or le métronome natif est un service du moteur de TRANSPORT : le bitfield projmetroen est
  exhaustif (&1 activé, &2 lecture, &4 enregistrement, &8/&16 count-in) — AUCUN bit « while
  stopped ». play_state==0 => silence, quoi qu'on fasse. Idem pour un item « click source »
  (un media item ne rend qu'en lecture). En prime son routage (metronome_defout) est une
  préférence GLOBALE (reaper.ini), pas un réglage projet, et le routage par projet du dialogue
  n'est exposé par AUCUNE API (pas de clé GetSetProjectInfo, pas de chunk projet lisible).
  => on applique le patron ÉPROUVÉ midi-clock / golem_drumseq : un JSFX free-running dont le
  @block/@sample tourne en permanence (traitement temps-réel indépendant du transport).

  ── Architecture ──
  Piste PERMANENTE « Click » : créée à la PREMIÈRE commande, jamais supprimée (comme Sample/
  Drums/Looper — ne matche AUCUN pattern de purge de golem_rig : sweep_legacy=GoleM:*,
  delete_unwanted=Sandbox #Input N). Sans entrée (I_RECINPUT=-1, I_RECMON=0, I_RECARM=0),
  muette pour le Master (B_MAINSEND=0, le Master = le casque), sortie HARDWARE directe via
  CreateTrackSend(tr,nil) en catégorie 1. UN SEUL FX : golem_click.jsfx, qui synthétise le click.

  ── Routage de sortie (config-pas-code) ──
  Le canal vient de la commande (résolu par le bridge depuis config/patches/hw-*.json) :
    "1-2" -> OUT 1/2 stéréo (I_DSTCHAN 0)   [défaut = la maison, Volt 276]
    "3-4" -> OUT 3/4 stéréo (I_DSTCHAN 2)   [ex. retour batteur sur une 8x8]
    "3"   -> OUT 3 mono     (I_DSTCHAN 2+1024)
  ⚠ Une paire stéréo exige une BASE PAIRE côté Reaper (0-based) : "2-3" n'existe pas, on refuse.
  Le send hardware n'est re-créé QUE si le canal change (purger/recréer à chaque tick glitcherait).

  ── Contrôle ──
  golem_watch relaie {"action":"click",...} en ProjExtState golem/click_cmd (branche exempte de
  SETTLE : on ne touche qu'à NOTRE piste, jamais au graphe des presets). Dédup par "seq".
    {"seq":N,"on":true,"level":-12,"beats":4,"div":1,"sync":true,"out":"1-2","song":false,"anchor":-1}
  `anchor` (s, -1 = aucune) : où commence la mesure 1 de la section en cours sur le transport — le JSFX y recale
  sa phase au départ, au saut et au seek (docs/arrangement.md §4).
  Les sliders sont écrits en VALEUR BRUTE (TrackFX_SetParam), idiome JSFX de golem_rig.

  État publié : presets/.click.json (tmp+rename)
    {"present":true,"on":bool,"level":dB,"beats":N,"div":N,"out":"1-2","ticks":N,"tempo":BPM}
  ticks/tempo sont RELUS des témoins du JSFX (sliders 6/7) = preuve que le thread audio tourne.

  ⚠ NON validable hors-rig : que le @sample d'une piste sans entrée tourne bien transport à
    l'arrêt (même hypothèse que drumseq, validée au son), l'audibilité réelle du send hardware
    sur une paire autre que 1/2, et le recalage sur beat_position au démarrage du transport.
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
    _LOGF = root .. "/presets/.click.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-click] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT  = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
-- la piste ne se crée que dans le projet du golem (golem_project.lua, 2026-11-08)
local project = dofile(ROOT .. "/reaper/Scripts/golem_project.lua")
local OUT   = ROOT .. "/presets/.click.json"
local TRACK = "Click"
-- JSFX (link-reaper.sh symlink reaper/Effects -> <resource>/Effects/golem)
local FX_NAMES = { "JS:golem/golem_click", "JS: golem/golem_click",
                   "GoleM click (metronome)", "golem_click" }
-- contrat de sliders du JSFX (index 0-based, valeurs BRUTES)
-- ⚠ INDEX de sliders : les nouveaux (den/gmask/clock) sont AJOUTÉS À LA SUITE des témoins,
-- jamais intercalés — sinon une instance vivante recevrait le niveau dans le dénominateur.
local P = { on = 0, level = 1, beats = 2, div = 3, sync = 4, ticks = 5, tempo = 6,
            den = 7, gmask = 8, clock = 9,
            -- `grid` (mise en phase sur la grille d'un standard) : indexé ici pour que personne
            -- n'ajoute un slider au mauvais rang, mais VOLONTAIREMENT jamais écrit. Le défaut du
            -- JSFX est « suivre la grille », et c'est ce qu'on veut ; le slider reste accessible
            -- dans l'UI du FX si l'on doit couper l'asservissement pour comprendre quelque chose.
            grid = 10, slaved = 11,
            -- `song` (2026-10-07, docs/bars-format.md) : le click joue les VRAIS temps de la backing (notes 76/77
            -- de l'item MIDI posé sur cette piste par golem_backing). Index 12 = slider13, à la suite.
            song = 12,
            -- `anchor` (2026-10-15, docs/arrangement.md §4) : position du transport (s) de la mesure 1 de la section
            -- en cours, + 1 (0 = aucune). Le JSFX y recale sa phase au départ / saut / seek. Index 13 = slider14.
            anchor = 13 }

-- groups {3,2,2} -> masque de bits des pulsations qui DÉMARRENT un groupe (0, 3, 5 -> 41).
-- Un groupement absent ou incohérent (somme ≠ num) retombe sur 1 = « seule la pulsation 1 »,
-- c'est-à-dire le comportement d'avant : on n'invente jamais un accent que l'utilisateur
-- n'a pas demandé.
local function groups_mask(groups, num)
  if type(groups) ~= "table" or #groups == 0 then return 1 end
  local sum, mask, pos = 0, 0, 0
  for _, g in ipairs(groups) do
    g = math.floor(tonumber(g) or 0)
    if g < 1 then return 1 end
    if pos < 32 then mask = mask + 2 ^ pos end
    pos = pos + g
    sum = sum + g
  end
  if sum ~= num then return 1 end
  return mask
end

-- ── util ──
local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

-- "1-2" / "3-4" / "5" -> I_DSTCHAN (0-based, +1024 = mono), + libellé de log.
-- "NONE" -> -1 : le click reste actif mais N'A AUCUNE sortie (pastille OUT ▸ NONE du Designer).
local function parse_out(sel)
  sel = tostring(sel or "1-2")
  if sel:upper() == "NONE" then return -1, "aucune sortie (NONE)" end
  local a, b = sel:match("^%s*(%d+)%s*%-%s*(%d+)%s*$")
  if a then
    a, b = tonumber(a), tonumber(b)
    if b ~= a + 1 then return nil, "paire non contiguë : " .. sel end
    -- une paire stéréo Reaper commence sur une base PAIRE (0-based) : "2-3" n'existe pas
    if a % 2 == 0 then return nil, "paire stéréo invalide (base 0-based impaire) : " .. sel end
    return a - 1, string.format("OUT %d/%d (stéréo)", a, b)
  end
  local m = tonumber(sel:match("^%s*(%d+)%s*$"))
  if m and m >= 1 then return (m - 1) + 1024, string.format("OUT %d (mono)", m) end
  return nil, "format de sortie inconnu : " .. sel
end

-- ── piste + FX : créés UNE fois, jamais supprimés ──
local function find_fx(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    local low = (nm or ""):lower()
    if low:find("golem_click", 1, true) or low:find("click (metronome)", 1, true) then return i end
  end
  return -1
end

-- ⚠ FRAÎCHEUR DE L'INSTANCE. Reaper NE RECOMPILE PAS une instance JSFX vivante quand le fichier
-- change sur le disque : elle garde l'ancien code, et les sliders ajoutés n'existent tout
-- simplement pas (le chunk de piste les écrit en « - »). Écrire dedans ne fait alors RIEN, EN
-- SILENCE. Piège vécu le 2026-07-30 : le dénominateur du 7/8 partait dans le vide et le click
-- continuait de battre en 4/4 sans le moindre message.
--
-- On ne peut PAS tester ça sur le nombre de params : Reaper ajoute 3 params génériques
-- (Bypass/Wet/Delta) aux sliders — 7 sliders donnent 10, ce qui est exactement le compte de la
-- version à 10 sliders. On teste donc le NOM du dernier slider attendu : sans ambiguïté, et
-- l'échec est du bon côté (on ré-instancie).
-- 2026-10-07 : le dernier slider est désormais `song` (index 12) — une instance compilée avant lui est
-- ré-instanciée, sinon le mode « click du morceau » écrirait dans le vide, en silence.
-- 2026-10-15 : puis `anchor` (index 13) — même raison (et la même instance porte les groupes du click du morceau).
local LAST_SLIDER = 13                       -- index 0-based du slider `anchor`
local LAST_SLIDER_NAME = "Section anchor"

local function fx_stale(tr, fx)
  if (reaper.TrackFX_GetNumParams(tr, fx) or 0) <= LAST_SLIDER then return true end
  local ok, nm = reaper.TrackFX_GetParamName(tr, fx, LAST_SLIDER, "")
  return not (ok and nm and nm:find(LAST_SLIDER_NAME, 1, true))
end

-- ── LE SÉQUENCEUR DEVANT LE CLICK ──────────────────────────────────────────────────────
-- Quand une grille joue, ce sont SES événements qui portent les ticks (lane 3, notes 76/77/78) :
-- une seule horloge au lieu de deux mises d'accord, donc zéro résidu de phase. Il faut donc une
-- instance de golem_chordseq DEVANT golem_click, sur cette piste — elle lit la même banque gmem
-- que le piano et la basse.
-- Elle est posée EN PERMANENCE, comme le reste de cette piste : sans grille chargée elle
-- n'émet rien, et la créer au moment de jouer coûterait une instanciation de FX pendant le son.
local SEQ_NAMES = { "JS:golem/golem_chordseq", "JS: golem/golem_chordseq",
                    "GoleM chord sequencer (chordseq)", "golem_chordseq" }
local LANE_CLICK = 3

local function find_seq(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if (nm or ""):lower():find("chordseq", 1, true) then return i end
  end
  return -1
end

local function ensure_seq(tr)
  local fx = find_seq(tr)
  if fx < 0 then
    for _, nm in ipairs(SEQ_NAMES) do
      local r = reaper.TrackFX_AddByName(tr, nm, false, -1)
      if r and r >= 0 then reaper.TrackFX_Show(tr, r, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
      if r and r >= 0 then fx = find_seq(tr); break end
    end
    if fx < 0 then
      log("⚠ JSFX golem_chordseq introuvable — le click de la grille ne sonnera pas")
      return -1
    end
    log("séquenceur golem_chordseq ajouté sur la piste Click (lane 3 = les ticks)")
  end
  -- il DOIT précéder le click : le MIDI descend la chaîne
  if fx > 0 then
    reaper.TrackFX_CopyToTrack(tr, fx, tr, 0, true)
    fx = find_seq(tr)
  end
  reaper.TrackFX_SetParam(tr, fx, 0, LANE_CLICK)   -- slider1 lane, valeur BRUTE (plage 0..4 depuis la pompe)
  return fx
end

local function ensure_fx(tr)
  local fx = find_fx(tr)
  if fx >= 0 and fx_stale(tr, fx) then
    log("JSFX golem_click périmé (compilé avant l'ajout de sliders) — ré-instanciation")
    reaper.TrackFX_Delete(tr, fx)
    fx = -1
  end
  if fx < 0 then
    for _, nm in ipairs(FX_NAMES) do
      local r = reaper.TrackFX_AddByName(tr, nm, false, -1)
      if r and r >= 0 then reaper.TrackFX_Show(tr, r, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
      if r and r >= 0 then fx = find_fx(tr); break end
    end
    if fx < 0 then log("⚠ JSFX golem_click introuvable (provision/link-reaper.sh fait ? Reaper relancé ?)")
    else log("JSFX golem_click ajouté (permanent)") end
  end
  -- JAMAIS bypassé : le on/off est le slider1, pas le bypass. Trouvé bypassé le 2026-07-30 sans
  -- que rien ne l'ait demandé — le métronome répondait « on » à tout le monde en restant muet.
  if fx and fx >= 0 and not reaper.TrackFX_GetEnabled(tr, fx) then
    log("JSFX golem_click était BYPASSÉ — réactivé")
    reaper.TrackFX_SetEnabled(tr, fx, true)
  end
  return fx
end

-- sortie hardware (dest nil = hardware, catégorie 1 ; purge AVANT création -> index sûr)
local function route_out(tr, dst, label)
  for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
  reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)      -- jamais par le Master (= casque)
  if dst < 0 then                                          -- NONE : sends purgés, on n'en crée aucun
    log("sortie -> " .. tostring(label))
    return true
  end
  local snd = reaper.CreateTrackSend(tr, nil)
  if not snd or snd < 0 then log("⚠ CreateTrackSend (hardware) a échoué"); return false end
  reaper.SetTrackSendInfo_Value(tr, 1, snd, "I_DSTCHAN", dst)
  reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)      -- jamais par le Master (= casque)
  log("sortie -> " .. tostring(label) .. " (I_DSTCHAN " .. dst .. ")")
  return true
end

local cur_tr, cur_fx = nil, -1
local applied_dst = nil                                    -- dernier I_DSTCHAN posé (évite de recréer le send)

-- ⚠ ARMER, SINON LE @sample NE TOURNE JAMAIS (mesuré le 2026-08-07). Reaper ne fait vivre que
-- les pistes de son graphe TEMPS RÉEL : une piste sans entrée, sans item et non armée n'en fait
-- pas partie. Le click était donc MUET dès la création de sa piste — témoins `ticks` et `tempo`
-- à 0, alors que le Lua répondait « on » à tout le monde. Même panne que le standard le même
-- jour, en plus dur : n'ayant jamais sonné, cette piste n'a même pas les ~2 s de queue qui
-- laissaient le premier départ passer. I_RECMODE 2 = « aucun » : vivante dans le graphe, hors
-- d'état d'écrire un fichier (et golem_perfrec neutralise déjà les pistes armées étrangères).
-- Conditionnel : ensure_track passe à CHAQUE tick, on ne salit pas le projet pour rien.
local function ensure_live(tr)
  -- LES ITEMS DE LA PISTE JOUENT PENDANT UNE PRISE : l'item du click du morceau (golem_backing, docs/bars-format.md)
  -- doit sonner pendant qu'une prise perf-rec tourne. AVANT le retour anticipé : une piste déjà armée sort tout
  -- de suite (relecture reascript-engineer, 2026-10-07).
  if reaper.GetMediaTrackInfo_Value(tr, "I_RECMONITEMS") ~= 1 then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMONITEMS", 1)
  end
  if reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") == 1 then return end
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  log("piste ARMÉE (I_RECMODE 2 « aucun ») — sans ça le thread audio ne la traite pas")
end

local function ensure_track()
  if cur_tr and reaper.ValidatePtr2(0, cur_tr, "MediaTrack*") then
    -- ensure_fx à CHAQUE passage, pas seulement quand l'index est invalide : il rattrape aussi
    -- un FX BYPASSÉ (trouvé bypassé le 2026-07-30, sans que rien ne l'ait demandé — le métronome
    -- restait muet en répondant « on » à tout le monde) et une instance périmée.
    ensure_live(cur_tr)
    cur_fx = ensure_fx(cur_tr)
    return cur_tr, cur_fx
  end
  local tr = find_track(TRACK)
  if not tr then
    reaper.PreventUIRefresh(1)
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", TRACK, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)   -- pas d'entrée : audio synthétisé par le JSFX
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)         -- le niveau est DANS le JSFX (slider2)
    reaper.SetMediaTrackInfo_Value(tr, "D_PAN", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
    reaper.PreventUIRefresh(-1)
    applied_dst = nil                                      -- send à (re)poser
    log("piste créée (permanente) : " .. TRACK)
  end
  cur_tr = tr
  ensure_live(tr)
  ensure_seq(tr)                 -- AVANT : il doit rester en tête de chaîne (le MIDI descend)
  cur_fx = ensure_fx(tr)
  return cur_tr, cur_fx
end

-- ── état courant (miroir des sliders) ──
local st = { on = false, level = -12, beats = 4, div = 1, sync = true, out = "1-2",
             den = 4, groups = nil, clock = false, song = false, anchor = -1 }

local function set_param(tr, fx, idx, v)
  if fx and fx >= 0 then reaper.TrackFX_SetParam(tr, fx, idx, v) end
end

local function apply(force)
  local tr, fx = ensure_track()
  if not tr then return end
  local dst, label = parse_out(st.out)
  if dst == nil then
    log("⚠ " .. tostring(label) .. " -> repli OUT 1/2")
    st.out = "1-2"; dst, label = 0, "OUT 1/2 (stéréo)"
  end
  if force or applied_dst ~= dst then
    -- le send hardware n'est re-créé QUE si le canal change (purger/recréer à chaque tick glitcherait)
    if route_out(tr, dst, label) then applied_dst = dst end
  end
  set_param(tr, fx, P.level, st.level)
  set_param(tr, fx, P.beats, st.beats)
  set_param(tr, fx, P.div,   st.div)
  set_param(tr, fx, P.den,   st.den)
  set_param(tr, fx, P.gmask, groups_mask(st.groups, st.beats))
  set_param(tr, fx, P.clock, st.clock and 1 or 0)
  set_param(tr, fx, P.sync,  st.sync and 1 or 0)
  set_param(tr, fx, P.song,  st.song and 1 or 0)
  -- ancre AVANT `on` et avec la mesure : le JSFX lit les deux dans le même bloc (codage s + 1, 0 = aucune)
  set_param(tr, fx, P.anchor, st.anchor >= 0 and st.anchor + 1 or 0)
  set_param(tr, fx, P.on,    st.on and 1 or 0)   -- EN DERNIER : le front 0->1 recale sur le temps 1
end

-- ── commandes (ProjExtState golem/click_cmd, posé par golem_watch) ──
local function jbool(body, key, dflt)
  local v = body:match('"' .. key .. '"%s*:%s*(%a+)')
  if v == "true" then return true elseif v == "false" then return false end
  return dflt
end

local function jnum(body, key, dflt)
  local v = tonumber(body:match('"' .. key .. '"%s*:%s*(%-?%d+%.?%d*)'))
  if v == nil then return dflt end
  return v
end

local last_seq = nil
local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "click_cmd")
  if not body or body == "" then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)') or body   -- pas de seq -> dédup sur le corps entier
  if seq == last_seq then return end
  last_seq = seq
  local op = body:match('"op"%s*:%s*"([^"]+)"') or "set"
  if op ~= "set" then log("op inconnue : " .. tostring(op)); return end
  st.on    = jbool(body, "on",    st.on)
  st.sync  = jbool(body, "sync",  st.sync)
  st.level = math.max(-60, math.min(6,  jnum(body, "level", st.level)))
  st.beats = math.max(1,   math.min(32, math.floor(jnum(body, "beats", st.beats) + 0.5)))
  st.div   = math.max(1,   math.min(4,  math.floor(jnum(body, "div",   st.div)   + 0.5)))
  st.den   = math.max(1,   math.min(16, math.floor(jnum(body, "den",   st.den)   + 0.5)))
  st.clock = jbool(body, "clock", st.clock)
  st.song  = jbool(body, "song",  st.song)       -- le bridge le dit à CHAQUE commande (app._click_cmd)
  -- ancre de section (s, -1 = aucune) : le bridge la dit aussi à CHAQUE commande (app._click_cmd)
  st.anchor = jnum(body, "anchor", st.anchor)
  if st.anchor < 0 then st.anchor = -1 end
  -- groups: [3,2,2] — liste plate d'entiers dans la charge
  local ga = body:match('"groups"%s*:%s*%[(.-)%]')
  if ga then
    local g = {}
    for n in ga:gmatch('(%d+)') do g[#g + 1] = tonumber(n) end
    st.groups = (#g > 0) and g or nil
  end
  st.out   = body:match('"out"%s*:%s*"([^"]*)"') or st.out
  apply(false)
  log(string.format("click %s : %.1f dB, %d/%d, div %d, accents 0x%X, horloge %s, out %s%s%s",
      st.on and "ON" or "OFF", st.level, st.beats, st.den, st.div,
      groups_mask(st.groups, st.beats), st.clock and "libre" or "liée", st.out,
      st.song and ", temps du MORCEAU" or "",
      st.anchor >= 0 and string.format(", ancre %.4f s", st.anchor) or ""))
end

-- ── publication d'état ──
local last_sig, last_pub = nil, 0
local function publish(force)
  local present, ticks, tempo = false, 0, 0
  if cur_tr and reaper.ValidatePtr2(0, cur_tr, "MediaTrack*") and cur_fx >= 0 then
    present = true
    ticks = reaper.TrackFX_GetParam(cur_tr, cur_fx, P.ticks) or 0
    tempo = reaper.TrackFX_GetParam(cur_tr, cur_fx, P.tempo) or 0
  end
  local sig = string.format("%s|%s|%.1f|%d|%d|%s", tostring(present), tostring(st.on),
                            st.level, st.beats, st.div, st.out)
  local now = reaper.time_precise()
  if not (force or sig ~= last_sig or (now - last_pub) > 1.0) then return end
  last_sig, last_pub = sig, now
  write_atomic(OUT, string.format(
    '{"present":%s,"on":%s,"level":%.1f,"beats":%d,"den":%d,"div":%d,"clock":%s,"sync":%s,"out":"%s","ticks":%d,"tempo":%.2f}',
    present and "true" or "false", st.on and "true" or "false", st.level, st.beats, st.den, st.div,
    st.clock and "true" or "false",
    st.sync and "true" or "false", st.out, math.floor(ticks), tempo))
end

-- ── boucle (garde par génération : la dernière instance lancée gagne) ──
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "click_gen", GEN, false)

-- ── l'ADOPTION de la piste dans le projet du golem — et seulement là (golem_project.lua, 2026-11-08) ──
-- Au démarrage si le projet ouvert est le nôtre ; sinon au premier tick où il le devient (premier démarrage : le
-- projet sans chemin ne devient le nôtre qu'au rappel de la bank 00 ; ou le set ouvert après un projet étranger).
-- UNE ADOPTION PAR PROJET (revue du 2026-11-08) : adopter, c'est éteindre le click et reprendre le seq sauvé DANS CE
-- projet sans le rejouer. Lu une seule fois au démarrage, le seq d'un set ouvert ensuite aurait été rejoué — le click
-- s'allumait rien qu'en ouvrant le set. Et une piste perdue DANS le projet adopté (supprimée, annulation) se répare
-- sans rien éteindre : jamais de click coupé en plein morceau.
--
-- ADOPTER le seq résiduel SANS le rejouer (un click_cmd sauvegardé ne doit pas relancer le click
-- au boot), sauf « kick » explicite — consommé une fois. Et si la piste existe déjà avec le JSFX à ON (projet sauvé
-- click allumé), on la RAMÈNE à OFF : l'ouverture est toujours silencieuse.
local kick = reaper.GetExtState("golem", "click_kick") == "1"
if kick then reaper.SetExtState("golem", "click_kick", "", false) end
local adopted = nil                                        -- « pointeur|chemin » du projet adopté
local native_off = false

local function project_key()
  local proj, path = project.current()
  return tostring(proj) .. "|" .. path
end

local function adopt()
  adopted = project_key()
  -- le métronome NATIF ne doit jamais tourner (double click pendant un backing) ; c'est une bascule GLOBALE de
  -- REAPER, pas du projet : coupée une seule fois, pas à chaque set ouvert
  if not native_off then
    native_off = true
    if reaper.GetToggleCommandState(40364) == 1 then
      reaper.Main_OnCommand(40364, 0)
      log("métronome natif éteint (le click GoleM le remplace)")
    end
  end
  if kick then
    kick, last_seq = false, nil
  else
    local _, body = reaper.GetProjExtState(0, "golem", "click_cmd")
    last_seq = body and body:match('"seq"%s*:%s*(%-?%d+)') or nil
  end
  st.on, st.anchor = false, -1                             -- l'état publié dit ce que joue le JSFX : OFF
  cur_tr, cur_fx = nil, -1                                 -- la piste d'un autre projet n'est pas la sienne
  local tr = find_track(TRACK)
  -- ⚠ CRÉÉE DÈS LE DÉMARRAGE (2026-10-08) : elle n'apparaissait qu'à la PREMIÈRE commande click — c'est-à-dire au
  -- départ du premier morceau. Or golem_backing y pose les temps du click du morceau AU CHARGEMENT de la backing
  -- (docs/bars-format.md) : pas de piste, pas de temps, et le premier morceau après un redémarrage de REAPER
  -- partait au tempo fixe. Elle est créée OFF (et le reste) ; la première commande pose sa sortie.
  if not tr then
    ensure_track()
    tr = cur_tr
  end
  if tr then
    cur_tr = tr
    cur_fx = find_fx(tr)
    if cur_fx >= 0 then
      reaper.TrackFX_SetParam(tr, cur_fx, P.on, 0)
      -- une ancre sauvée avec le projet appartient à un morceau d'une autre session : aucune
      if not fx_stale(tr, cur_fx) then reaper.TrackFX_SetParam(tr, cur_fx, P.anchor, 0) end
      log("piste " .. TRACK .. " prête — click forcé OFF au démarrage")
    end
  end
end

local foreign_logged = nil
local function tick()
  if not project.is_golem(ROOT) then
    -- projet étranger : aucune piste créée, aucune commande lue ; l'état publié dit « absent »
    if not foreign_logged then log("projet étranger au golem : piste " .. TRACK .. " non créée") end
    foreign_logged = true
    publish(false)
    return
  end
  if foreign_logged then log("retour dans le projet du golem") end
  foreign_logged = false
  if project_key() ~= adopted then
    adopt()
  elseif not (cur_tr and reaper.ValidatePtr2(0, cur_tr, "MediaTrack*")) then
    cur_tr = nil                                           -- même projet, piste perdue : réparée, état intact
    apply(true)
    log("piste " .. TRACK .. " réparée (état conservé)")
  end
  poll_cmd()
  publish(false)
end

if project.is_golem(ROOT) then adopt() end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "click_gen") ~= GEN then return end   -- remplacée : cette boucle meurt
  reaper.SetExtState("golem", "click_alive", string.format("%.3f", reaper.time_precise()), false)
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
