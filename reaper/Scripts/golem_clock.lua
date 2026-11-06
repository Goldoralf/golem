-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — MIDI clock (horloge de synchro arpegiateur AKAI)
  Boucle defer PERMANENTE (lancee par __startup, comme golem_tuner/looper/backing/perfrec).
  Fait tourner une horloge MIDI FREE-RUNNING (24 PPQN, 0xF8) au TEMPO PROJET et la route en dur vers
  la sortie MIDI hardware du clavier AKAI -> son arpegiateur se cale sur le BPM du preset.

  ── Pourquoi (choix "en connaissance de l'API") ──
  Le rig est monitore TRANSPORT A L'ARRET. L'option native "send MIDI clock" de Reaper n'emet QU'EN
  LECTURE -> inutilisable ici. On fabrique donc l'horloge avec un JSFX (reaper/Effects/midi-clock.jsfx)
  dont le @block tourne en permanence (FX temps-reel independant du transport) et emet 0xF8 a
  l'echantillon pres, cale sur `tempo` (tempo projet = BPM du preset, pose au recall par golem_rig).

  ── Topologie ──
  Piste utilitaire PERMANENTE "MIDI Clock" (patron "Recording") :
    - creee au besoin, JAMAIS balayee (ne matche aucun pattern de purge de golem_rig : sweep_legacy=
      GoleM:* ; delete_unwanted/sandbox_idle = "Sandbox #Input <n>") ;
    - aucun audio (B_MAINSEND=0, pas de send hw, pas d'entree) ;
    - JSFX midi-clock en FX0 ;
    - SORTIE MIDI HARDWARE vers l'AKAI : I_MIDIHWOUT = (index_out << 5) | canal, canal 0 = tous
      (bits 0-4 = canal, bits 5-9 = index device de sortie ; -1 = aucune). L'index est resolu PAR NOM
      via GetMIDIOutputName (le nom contient "MPK"/"akai"), miroir de la resolution d'ENTREE de la lane
      Keys dans golem_rig.lua (keys_midi_dev, ~l.1006).

  ── Pilotage ──
  Lancee par __startup.lua. Toggle simple via ExtState golem/clock_on ("0" = off ; defaut ON).
  Quand off : JSFX bypass + I_MIDIHWOUT=-1 (aucune fuite MIDI). Pas d'endpoint bridge en v1.

  ⚠ NON verifiable hors-Reaper. A VALIDER AU RIG :
    - GetNumMIDIOutputs / GetMIDIOutputName : le MPK mini mk2 EXPOSE-T-IL un port de SORTIE MIDI USB
      (= une entree cote clavier) ? Certains MPK n'ont qu'un MIDI-IN vers l'ordi. La liste des sorties
      est LOGUEE au demarrage ; si aucun port AKAI OUT -> l'horloge ne peut pas atteindre le device
      (logue clairement, rien ne casse).
    - La sortie MIDI doit etre ACTIVEE dans reaper.ini (bitmask midiouts*) -> provision/reaper-ini-setup.py
      (redemarrage Reaper requis apres). Sinon I_MIDIHWOUT est inerte.
]]--

local LOGP = nil
local function log(s)
  if LOGP then local f = io.open(LOGP, "a"); if f then f:write(os.date("%H:%M:%S ") .. tostring(s) .. "\n"); f:close() end end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT  = repo_root()
LOGP        = ROOT .. "/presets/.clock.log"
local TRACK     = "MIDI Clock"
local OLD_TRACK = "Sandbox #Clock"       -- ancien nom : migré au vol dans ensure_track
-- noms d'ajout du JSFX (symlink link-reaper.sh : reaper/Effects -> <resource>/Effects/golem)
local JS_NAMES = { "JS:golem/midi-clock", "JS: golem/midi-clock",
                   "JS:golem/midi-clock.jsfx", "GoleM MIDI clock (midi-clock)" }

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

-- ── cartes ALSA : id court ("II") -> nom long ("USB-Audio - MPK Mini Mk II") ──
-- Reaper (ALSA raw) nomme ses sorties "hw:<id de carte>" : AUCUN "MPK"/"akai" dedans. On resout
-- l'id via /proc/asound/cards, sinon on matcherait au petit bonheur (l'ancien repli "premier hw:
-- qui n'est pas la Volt" aurait attrape la Presonus "hw:iTwo" si elle etait listee avant l'AKAI).
local function alsa_cards()
  local by_id, f = {}, io.open("/proc/asound/cards", "r")
  if not f then return by_id end
  local txt = f:read("*a"); f:close()
  for line in txt:gmatch("[^\n]+") do
    local _, id, rest = line:match("^%s*(%d+)%s*%[([^%]]-)%s*%]%s*:%s*(.-)%s*$")
    if id then by_id[id] = rest or "" end
  end
  return by_id
end

-- ── resolution de la sortie AKAI par NOM (miroir de keys_midi_dev cote entrees) ──
-- Renvoie (index_out, nom, liste_texte). index=nil si aucun port de sortie AKAI visible.
-- ⚠ un device DEBRANCHE garde son index (cache [mididevcache] de Reaper) : on n'ecarte pas les
-- "(off)" de l'enumeration, sinon les index affiches ne seraient plus ceux des masques.
local function akai_out()
  local list, cards = {}, alsa_cards()
  local hit_i, hit_name
  local n = reaper.GetNumMIDIOutputs()
  for i = 0, n - 1 do
    local ok, name = reaper.GetMIDIOutputName(i, "")
    if name and name ~= "" then
      local id = name:match("^hw:(.+)$")
      local rich = (id and cards[id]) and (name .. " " .. cards[id]) or name
      list[#list + 1] = string.format("%d%s:%s", i, ok and "" or "(off)", rich)
      local l = rich:lower()
      if not hit_i and ok and (l:find("mpk", 1, true) or l:find("akai", 1, true)) then
        hit_i, hit_name = i, rich
      end
    end
  end
  return hit_i, hit_name, table.concat(list, " | ")
end

-- ── JSFX midi-clock en FX0 : trouve ou ajoute ──
local function ensure_fx(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, fxname = reaper.TrackFX_GetFXName(tr, i, "")
    if fxname and fxname:lower():find("midi%-clock") then return i end
  end
  for _, nm in ipairs(JS_NAMES) do
    local fx = reaper.TrackFX_AddByName(tr, nm, false, -1)
    if fx and fx >= 0 then reaper.TrackFX_Show(tr, fx, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
    if fx >= 0 then log("JSFX charge : " .. nm .. " @FX" .. fx); return fx end
  end
  log("⚠ JSFX midi-clock INTROUVABLE (provision/link-reaper.sh fait ? Reaper relance ?) — horloge inerte")
  return -1
end

-- ── piste "MIDI Clock" : creee UNE fois, jamais supprimee ──
local function ensure_track()
  local tr = find_track(TRACK)
  if not tr then
    local old = find_track(OLD_TRACK)                     -- migration : renomme l'ancienne piste (FX/sortie préservés)
    if old then
      reaper.GetSetMediaTrackInfo_String(old, "P_NAME", TRACK, true)
      tr = old
      log("piste migrée : « " .. OLD_TRACK .. " » -> « " .. TRACK .. " »")
    end
  end
  if not tr then
    reaper.PreventUIRefresh(1)
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", TRACK, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)   -- aucune entree
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)    -- jamais vers le Master (piste muette)
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)        -- mute audio OK, mais le FX tourne quand meme
    reaper.PreventUIRefresh(-1)
    log("piste creee (permanente) : " .. TRACK)
  end
  -- ⚠ ARMER, SINON L'HORLOGE NE TOURNE PAS. Meme verrou que standard/click/drums (CLAUDE.md) :
  -- une piste sans entree, sans item et non armee sort du graphe TEMPS REEL de Reaper des
  -- qu'elle se tait, et son @block s'arrete. Mesure du 2026-08-08 : REC 0, temoin `ticks` FIGE
  -- a 2113 sur plusieurs secondes -- l'arpegiateur de l'AKAI ne recevait aucune horloge, en
  -- silence. Le commentaire d'en-tete affirmait pourtant « le @block tourne en permanence ».
  -- I_RECMODE 2 = « aucun » : vivante dans le graphe, hors d'etat d'ecrire un fichier.
  if reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") ~= 1 then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
    log("piste ARMEE (I_RECMODE 2) -- sans ca le thread audio ne la traite pas")
  end
  ensure_fx(tr)
  return tr
end

-- ── etat runtime ──
local applied_on  = nil   -- dernier etat applique (nil = jamais)
local applied_dev = nil   -- dernier index device applique
local dev_idx, dev_name   -- resolus au demarrage (re-tente si absent)
local next_resolve = 0

local function clock_enabled()
  local v = reaper.GetExtState("golem", "clock_on")
  return v ~= "0"                                          -- defaut ON (ExtState vide -> ON)
end

-- (re)applique enable JSFX + sortie hardware selon l'etat courant. Idempotent, logue sur changement.
-- ⚠ LE JSFX RESTE ACTIF, MEME HORLOGE OFF (2026-08-08). Il etait BYPASSE quand off — et un FX
-- bypasse ne tourne pas, donc son compteur `ticks` gelait. Or ce compteur est devenu LE temoin
-- du thread audio (monitors._audio_alive) : le laisser geler, c'etait crier « carte son perdue »
-- a chaque fois que l'utilisateur coupe l'horloge. Le faux positif aurait tue le detecteur.
-- Couper la SORTIE suffit : I_MIDIHWOUT = -1 garantit deja qu'aucun octet ne quitte la piste
-- (aucune entree, aucun receive, B_MAINSEND=0). Le bypass etait une seconde ceinture, payee
-- d'un temoin aveugle.
-- Reserve connue : `send_start` (0xFA une seule fois) verrait son verrou `started` consomme
-- pendant que la sortie est coupee. Sans consequence aujourd'hui — le rack ne l'active jamais,
-- il reste a son defaut « clock only ».
local function apply(tr, on)
  local fx = ensure_fx(tr)
  if fx >= 0 and not reaper.TrackFX_GetEnabled(tr, fx) then
    reaper.TrackFX_SetEnabled(tr, fx, true)                 -- jamais bypasse : cf. ci-dessus
  end
  local target = (on and dev_idx) and (dev_idx * 32) or -1  -- (dev<<5)|canal0 ; -1 = aucune
  reaper.SetMediaTrackInfo_Value(tr, "I_MIDIHWOUT", target)
  if on ~= applied_on or target ~= applied_dev then
    if on and dev_idx then
      log(string.format("horloge ON -> AKAI OUT #%d (%s), I_MIDIHWOUT=%d (canal 0 = tous)",
        dev_idx, tostring(dev_name), target))
    elseif on then
      log("horloge ON mais AUCUN port AKAI OUT resolu -> I_MIDIHWOUT=-1 (le tick n'atteint pas le device)")
    else
      log("horloge OFF (I_MIDIHWOUT=-1 ; le JSFX continue de tourner, il sert de temoin audio)")
    end
    applied_on, applied_dev = on, target
  end
end

-- ── LE TEMOIN DU THREAD AUDIO ────────────────────────────────────────────────────────────
-- Pourquoi ici : cette piste est la SEULE permanente dont le JSFX tourne en @block sans rien
-- attendre de personne, et son slider `ticks` est un compteur monotone. C'est donc le seul
-- endroit du rig qui puisse repondre honnetement a « le thread audio avance-t-il ? ».
--
-- ⚠ Et il FAUT quelqu'un pour y repondre : Audio_IsRunning() a rendu 1 alors que la carte
-- venait d'etre re-enumeree et que PLUS RIEN ne sortait (mesure du 2026-08-08 : toutes les
-- cretes figees au bit pres, treize heures durant, sans un mot nulle part). GetAudioDeviceInfo
-- rend la chaine CONFIGUREE (« ALSA V276 »), pas l'etat reel. Aucun des deux ne voit la panne.
--
-- Ecrit ~1 fois par seconde : le bridge compare deux lectures. `t` avance = la boucle Lua vit ;
-- `ticks` fige avec `t` qui avance = le thread audio est MORT, et c'est ca qu'on veut nommer.
local W_OUT, w_next = ROOT .. "/presets/.clock.json", 0

function publish_witness(tr)
  local now = reaper.time_precise()
  if now < w_next then return end
  w_next = now + 1.0
  local fx = tr and ensure_fx(tr)
  local ticks = (fx and fx >= 0) and reaper.TrackFX_GetParam(tr, fx, 1) or -1
  local f = io.open(W_OUT .. ".tmp", "w")
  if not f then return end
  f:write(string.format('{"ticks":%d,"t":%.3f,"on":%s}', math.floor(ticks), now,
                        clock_enabled() and "true" or "false"))
  f:close()
  os.remove(W_OUT); os.rename(W_OUT .. ".tmp", W_OUT)
end

-- ── boucle ──
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "clock_gen", GEN, false)      -- la derniere instance lancee gagne

local function tick()
  local tr = find_track(TRACK) or ensure_track()
  -- resolution device : au demarrage, puis re-tente toutes ~2 s tant qu'absent (branchement a chaud)
  if not dev_idx and reaper.time_precise() >= next_resolve then
    dev_idx, dev_name = akai_out()
    next_resolve = reaper.time_precise() + 2.0
    if dev_idx then applied_dev = nil end                 -- force re-application (device apparu)
  end
  apply(tr, clock_enabled())
  publish_witness(tr)
end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "clock_gen") ~= GEN then return end   -- remplacee : cette boucle meurt
  reaper.SetExtState("golem", "clock_alive", string.format("%.3f", reaper.time_precise()), false)
  -- pcall BLINDE (lecon perfrec) : une erreur d'un tick NE TUE JAMAIS la boucle.
  local ok, err = pcall(tick)
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

-- ── demarrage : logue la liste des sorties MIDI (deliverable de validation) ──
do
  local i, name, listing = akai_out()
  dev_idx, dev_name = i, name
  log("sorties MIDI (" .. reaper.GetNumMIDIOutputs() .. ") : " .. (listing ~= "" and listing or "(aucune)"))
  if dev_idx then log("AKAI OUT resolu : #" .. dev_idx .. " (" .. tostring(dev_name) .. ")")
  else log("⚠ aucun port AKAI OUT (le MPK mini mk2 n'a peut-etre pas de MIDI-IN USB) — horloge sans destination") end
end

ensure_track()
log("demarre. piste=" .. TRACK .. " ; toggle ExtState golem/clock_on (defaut ON) ; log=" .. LOGP)
loop()
