-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — perf rec (enregistrement de performance)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_tuner/looper/backing).
  Capture dans un .wav le MIX STÉRÉO que le musicien entend (guitare + looper + pads +
  backing) pour réécoute maison dans la Library (onglet Loops).

  ── Technique (choisie « en connaissance de l'API », cf. réponse à l'humain) ──
  Dans ce rig, TOUT sort en dur vers OUT 1/2 (sends hardware, B_MAINSEND=0) : le Master
  Reaper est vide, il n'existe aucun bus de sommation à enregistrer. On reconstruit donc
  le mix sur une piste dédiée PERMANENTE « Recording » :
    - elle REÇOIT (post-fader) de CHAQUE piste qui possède un send hardware (= exactement
      les pistes qui atteignent OUT 1/2 = le mix entendu ; les enfants de folder somment au
      parent et n'ont pas de send hw -> jamais comptés deux fois) ;
    - record mode 3 = « output (stereo, latency compensated) » : on enregistre la SORTIE
      post-fader de la piste (= la somme des receives), pas une entrée physique ;
    - monitoring OFF (I_RECMON=0) + aucune sortie (B_MAINSEND=0, pas de send hw) -> zéro
      double audio ; le musicien n'entend rien de plus.
  Les receives sont re-scellées à chaque tick si l'ensemble des pistes-source change
  (self-heal après un recall/rebuild de preset : un recall pendant l'enregistrement ne
  casse rien, la piste suit le nouveau son).

  ⚠ Reaper n'écrit sur disque QUE si le transport est en RECORD. On engage donc le
  transport record. Pour que SEULE PerfRec produise un fichier, toute autre piste armée
  (les entrées Sandbox #Input, armées pour le monitoring live) est forcée en record mode 2
  (« none / input monitoring only ») : elles continuent de monitorer, elles n'écrivent pas.
  (golem_rig pose déjà I_RECMODE=2 sur les roots d'entrée -> pas de fichier parasite même si
  un recall recrée une entrée pendant l'enregistrement.) Le backing partage le transport :
  golem_backing NE coupe PAS le transport en fin de morceau tant que perf_rec est actif.

  Commande : golem_watch relaie {"action":"perf_rec","on":bool} en ProjExtState
  golem/perf_cmd (dédup par "seq"). État publié : presets/.perf.json (tmp+rename)
  {"recording":bool,"file":"recordings/…wav","started_at":"ISO"} — lu par le bridge (poll).

  Invariants : la piste « Recording » ne matche AUCUN pattern de purge de golem_rig
  (sweep_legacy=GoleM:* ; delete_unwanted/sandbox_idle=Sandbox #Input N) -> jamais balayée.

  ── CHIEN DE GARDE « transport figé » (régression 2026-07-25, diagnostiquée au rig) ──
  Reaper n'écrit un fichier QUE si le transport AVANCE. Si le moteur audio est arrêté (carte son
  débranchée / ré-énumérée : Reaper garde des descripteurs /dev/snd/pcmC*D* « (deleted) », le
  thread audio ne tourne plus), la séquence marche « sur le papier » : GetPlayState() rend bien
  5 (play|record), la piste est armée en recmode 3… et la position de lecture NE BOUGE PAS.
  Zéro échantillon capturé -> Reaper ne crée AUCUN fichier -> on finissait par mentir :
  « aucun item/source enregistré », comme si le routage était en cause.
  ⚠ Audio_IsRunning() N'EST PAS un témoin fiable : mesuré à 1 (vrai) avec le device mort.
  Le SEUL témoin sûr est l'AVANCÉE de GetPlayPosition(). On la surveille : pas un pas en
  STALL_AFTER secondes -> on abandonne la prise et on DIT pourquoi (log + .perf.json "error"),
  au lieu de laisser le musicien jouer 6 minutes dans le vide.
  (Le rig n'utilise jamais le pre-roll/count-in natif — golem_click éteint le métronome natif au
  boot — donc « position figée » ne peut pas être un décompte légitime.)
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

local ROOT    = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
LOGP          = ROOT .. "/presets/.perf.log"
local STATUS  = ROOT .. "/presets/.perf.json"
local REC_DIR = ROOT .. "/recordings"
local TRACK     = "Recording"
local OLD_TRACK = "Sandbox #PerfRec"   -- ancien nom : migré au vol dans ensure_track

local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

-- REAPER enregistre normalement dans REC_DIR. Si la source est sur un autre
-- volume, os.rename échoue ; copier par blocs sans écraser une prise existante.
local function move_recording(src, dst)
  if src == dst then return true end
  local existing = io.open(dst, "rb")
  if existing then existing:close(); return false, "destination déjà présente" end
  local ok, err = os.rename(src, dst)
  if ok then return true end
  local input = io.open(src, "rb")
  if not input then return false, err end
  local size = input:seek("end")
  if not size or not input:seek("set", 0) then input:close(); return false, "taille source inconnue" end
  local partial = dst .. ".partial"
  local output = io.open(partial, "wb")
  if not output then input:close(); return false, err end
  local copied, remaining = true, size
  while remaining > 0 do
    local chunk = input:read(math.min(1024 * 1024, remaining))
    if not chunk or #chunk == 0 or not output:write(chunk) then copied = false; break end
    remaining = remaining - #chunk
  end
  input:close()
  if not output:close() then copied = false end
  if not copied then os.remove(partial); return false, "copie incomplète" end
  ok, err = os.rename(partial, dst)
  if not ok then os.remove(partial); return false, err end
  local removed, remove_err = os.remove(src)
  if not removed then log("⚠ source non supprimée après copie : " .. tostring(remove_err)) end
  return true
end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

local function iso_now() return os.date("%Y-%m-%dT%H:%M:%S") end
local function jstr(s) return '"' .. tostring(s or ""):gsub('\\', '\\\\'):gsub('"', '\\"') .. '"' end

-- ── état runtime (redérivable : survit à un restart du script via ProjExtState) ──
local recording   = false
local cur_file    = nil        -- chemin relatif "recordings/…wav" (ou DOSSIER en multi)
local cur_started = nil
local pending     = 0          -- ticks restants pour finaliser (item enregistré dispo)
local last_recv_sig = nil
local last_seq    = nil
local rec_sources = nil        -- {in1,in2,usb} du bloc Rec du preset actif (nil = tout)
local rec_mode    = "mix"      -- mix | tracks | tracks_di (bloc Rec, figé à op_start)
local rec_keep_mix = true      -- coche « Song mix » : garder AUSSI le mix stéréo en multipiste
local MPREFIX     = "Recording:"   -- pistes multi (une par source, + "Recording:DI …")
local rec_t0      = nil        -- horodatage de l'engagement du record (fenêtre du chien de garde)
local BUS         = "Backing Track"   -- doit rester en phase avec golem_backing.lua (BUS)
local prior_repeat = nil       -- repeat AVANT la prise (restauré au stop)
local prior_loop_a, prior_loop_b = nil, nil
local bus_muted_by_us = false  -- on a coupé le bus Backing pour cette prise -> à rétablir au stop
-- UNE PRISE PART DE ZÉRO (2026-09-21 : « la chanson ne se lance jamais au début, ça part un
-- peu quand ça veut »). Rien ne ramenait jamais le curseur : la prise démarrait là où la dernière
-- pause l'avait laissé (mesuré : backing en pause à 12,4 s -> départ à 12,4 s). Si le transport
-- est à l'arrêt, on part de 0 et on y revient au stop. S'il JOUE déjà (on enregistre par-dessus
-- un backing lancé exprès), on ne saute pas : ce serait couper ce que le musicien écoute.
-- Le looper n'en souffre pas : golem_super8 tourne en Sync=off (slider 1, jamais écrit par le
-- rack), il ne lit play_position qu'en Sync=project/playback.
local from_zero = false
-- DÉPART DIFFÉRÉ (décompte du bloc Rec) : {t = time_precise du départ, backing = bool}. Le bridge
-- envoie `in_ms` ; c'est CETTE boucle qui décompte, ce qui absorbe la gigue du chemin de commande
-- (même patron que les samples pré-armés de l'arrangement).
local start_at = nil
local last_pos    = 0          -- dernière position de lecture vue
local last_move_t = 0          -- dernier instant où elle a BOUGÉ
local moved       = false      -- le transport a-t-il avancé au moins une fois dans cette prise ?
local stall_msg   = nil        -- prise MORT-NÉE (rien capté du tout) -> aucun fichier à annoncer
local warn_msg    = nil        -- prise INCOMPLÈTE (moteur mort en cours de route) -> on garde
local STALL_AFTER = 3.0        -- s sans le moindre mouvement du transport = moteur audio mort
local GRACE       = 1.0        -- s de grâce : CSurf_OnRecord met un instant à prendre au thread audio

-- ── sources (bloc Rec, presets/.perfsrc.json écrit par le bridge au recall) ──
-- Filtre par ENTRÉE : une piste-source « Sandbox #Input N… » n'est reçue que si son entrée
-- est cochée (1->in1, 2->in2, 3+->usb). Les pistes hors patron (Sandbox #Backing, #Looper)
-- restent TOUJOURS dans le mix. Fichier absent = tout (comportement historique).
local function read_sources()
  local f = io.open(ROOT .. "/presets/.perfsrc.json", "r")
  if not f then return nil, "mix", true end       -- 3e valeur : sans elle rec_keep_mix tomberait à nil (= faux)
  local s = f:read("*a"); f:close()
  local t = {}
  for k, v in s:gmatch('"(%w+)"%s*:%s*(%a+)') do t[k] = (v == "true") end   -- bools nus seulement
  -- BUG (2026-07-26) : %w ne couvre PAS "_" en Lua -> "tracks_di" ne matchait JAMAIS, mode
  -- retombait en silence sur "mix" (perte du multi-piste ET du DI malgré perfsrc.json correct).
  local mode = s:match('"mode"%s*:%s*"([%w_]+)"') or "mix"
  -- coche « Song mix » du bloc Rec : garder AUSSI le mix stéréo en multipiste. Absent = true
  -- (on ne perd jamais le mix par défaut). t["mix"] est déjà lu par le gmatch des booléens nus.
  local keep_mix = (t["mix"] ~= false)
  t["mix"] = nil                                   -- ce n'est PAS une source, ne pas polluer src_allowed
  return (next(t) and t or nil), mode, keep_mix
end

-- Pistes de SERVICE jamais gravées : le métronome ne doit JAMAIS finir dans une prise.
-- (Drums/Sample, eux, RESTENT dans le mix : c'est voulu, ils font partie du jeu.)
-- ⚠ Sans ça, la piste « Click » serait avalée automatiquement : « source » = toute piste
-- ayant un send hardware, et src_allowed() laisse passer tout nom hors « Sandbox #Input N ».
-- ⚠ NE PAS confondre avec is_rec_track() (= NOS pistes d'enregistrement, qui doivent rester
-- ARMÉES). Une piste de service, elle, doit être neutralisée par scan() si elle est armée :
-- l'exclure de is_rec_track() reviendrait à lui laisser le droit d'écrire un fichier parasite.
local NEVER_REC = { ["Click"] = true }

local function src_allowed(nm)
  if NEVER_REC[nm] then return false end
  if not rec_sources then return true end
  local inp = tonumber(nm:match("^Sandbox #Input (%d+)"))
  if not inp then return true end
  -- LOT 4 (audit N lanes) : une clé PAR ENTRÉE (`in4`…) quand le bridge l'a écrite ; sinon le
  -- triplet historique (1→in1, 2→in2, ≥3→usb) — un bridge ancien reste lisible.
  local per = rec_sources["in" .. tostring(inp)]
  if per ~= nil then return per ~= false end
  local key = (inp == 1) and "in1" or (inp == 2) and "in2" or "usb"
  return rec_sources[key] ~= false
end

-- ── piste PerfRec : créée UNE fois, jamais supprimée ──
local function ensure_track()
  local tr = find_track(TRACK)
  if tr then return tr end
  local old = find_track(OLD_TRACK)                        -- migration : renomme l'ancienne piste (receives préservés)
  if old then
    reaper.GetSetMediaTrackInfo_String(old, "P_NAME", TRACK, true)
    log("piste migrée : « " .. OLD_TRACK .. " » -> « " .. TRACK .. " »")
    return old
  end
  reaper.PreventUIRefresh(1)
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, false)
  tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", TRACK, true)
  reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)   -- pas d'entrée physique (mode output)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)      -- monitoring OFF (pas de double audio)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)      -- armée (indispensable pour capturer)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 3)     -- output (stereo, latency compensated)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)    -- jamais vers le Master
  reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
  reaper.SetMediaTrackInfo_Value(tr, "D_PAN", 0)
  reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
  reaper.PreventUIRefresh(-1)
  log("piste créée (permanente) : " .. TRACK)
  return tr
end

-- ── scan : neutralise toute piste armée (sauf PerfRec) + signature des pistes-source ──
-- « source » = piste avec un send hardware (catégorie 1) = piste qui atteint OUT 1/2.
-- NOS pistes d'enregistrement (les seules qui restent armées) — cf. NEVER_REC ci-dessus.
local function is_rec_track(nm)
  return nm == TRACK or nm:sub(1, #MPREFIX) == MPREFIX
end

local function scan(perfrec)
  local sig = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if tr ~= perfrec and not is_rec_track(nm) then           -- nos pistes multi restent armées
      if reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") == 1 then
        reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)   -- monitor-only : n'écrit aucun fichier
      end
      -- la signature doit décrire EXACTEMENT l'ensemble que rebuild_receives va monter
      -- (sinon le click qui apparaît/disparaît déclenche un remontage inutile en pleine prise)
      if reaper.GetTrackNumSends(tr, 1) > 0 and src_allowed(nm) then
        sig[#sig + 1] = nm
      end
    end
  end
  return table.concat(sig, "\30")
end

-- (re)monte les receives post-fader de toutes les pistes-source vers PerfRec.
local function rebuild_receives(perfrec)
  for i = reaper.GetTrackNumSends(perfrec, -1) - 1, 0, -1 do reaper.RemoveTrackSend(perfrec, -1, i) end
  local n = 0
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    if tr ~= perfrec and reaper.GetTrackNumSends(tr, 1) > 0 then
      local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
      if src_allowed(nm) then                                             -- coches IN 1/IN 2/USB du bloc Rec
        -- ⚠ index corrigé 2026-07-27 (cf. add_receive) : le « quirk cat 0 » n'existe pas —
        -- send_index_selftest() prouve que la catégorie 0 indexe les sends de PISTE seuls.
        -- Sans conséquence ICI (on écrivait les valeurs par défaut, donc le no-op ne se voyait
        -- pas), mais c'est le même motif qui a rendu le DI inopérant : on applique le bon.
        local numHW = reaper.GetTrackNumSends(tr, 1)                     -- durcissement : figé AVANT création
        local s = reaper.CreateTrackSend(tr, perfrec)                     -- send tr -> PerfRec (= receive côté PerfRec)
        reaper.SetTrackSendInfo_Value(tr, 0, s, "I_SENDMODE", 0)          -- post-fader (= ce qu'on entend)
        reaper.SetTrackSendInfo_Value(tr, 0, s, "I_DSTCHAN", 0)           -- vers ch 1/2 de PerfRec
        -- audio SEUL (piège super8) : le root Keys porte le MIDI live du clavier, qui n'a rien
        -- à faire dans un receive d'enregistrement — la « DI » MIDI a SES pistes Recording:MIDI,
        -- branchées sur le device, pas sur ce send (audit 2026-08-12).
        reaper.SetTrackSendInfo_Value(tr, 0, s, "I_MIDIFLAGS", 31)
        -- LE MIX D'ENREGISTREMENT SUIT LE MIX PRINCIPAL (docs/mixer.md) : « post-fader » ne
        -- couvre que le fader de PISTE — le trim du mixer, lui, vit sur le D_VOL du send
        -- MATÉRIEL et n'atteindrait jamais la prise sans cette recopie. On hérite aussi du
        -- mute : une source coupée aux enceintes ne réapparaît pas en douce dans la prise.
        reaper.SetTrackSendInfo_Value(tr, 0, s, "D_VOL",
          reaper.GetTrackSendInfo_Value(tr, 1, 0, "D_VOL"))
        reaper.SetTrackSendInfo_Value(tr, 0, s, "B_MUTE",
          reaper.GetTrackSendInfo_Value(tr, 1, 0, "B_MUTE"))
        -- GARDE-FOU (durcissement 2026-07-26, audit AKAI muet) : cf. add_receive — un send HW
        -- écrasé par erreur ici rend `tr` muette aux enceintes sans aucun autre symptôme.
        if reaper.GetTrackNumSends(tr, 1) ~= numHW then
          log("⚠⚠ rebuild_receives : nb de sends HW de '" .. nm .. "' a changé pendant la pose du receive (" ..
              numHW .. " -> " .. reaper.GetTrackNumSends(tr, 1) .. ") — piste possiblement MUETTE aux enceintes, vérifier son HWOUT")
        end
        n = n + 1
      end
    end
  end
  return n
end

local function ensure(perfrec, force)
  local sig = scan(perfrec)                        -- neutralise les armées à chaque appel
  if force or sig ~= last_recv_sig then
    local n = rebuild_receives(perfrec)
    last_recv_sig = sig
    log("receives (re)montés : " .. n .. " source(s) -> " .. TRACK)
  end
end

-- ── mode MULTI (tracks / tracks_di — 2026-07-23) : une piste d'enregistrement par SOURCE
-- (receive post-fader, comme le mix) ; tracks_di ajoute, pour chaque piste d'ENTRÉE (Sandbox
-- #Input N…), une piste receive PRE-FX = la DI brute avant la chaîne d'effets. Pistes
-- "Recording:<src>" / "Recording:DI <src>" créées à op_start, supprimées à la finalisation
-- (les .wav restent). En multi, la piste mix "Recording" est désarmée. ──
-- DI = tap PRE-FX (avant toute la chaîne). N'a de sens QUE pour une entrée AUDIO physique
-- (guitare/voix) : capturer le signal cru avant pédales/ampli permet le reamp. Sur une piste
-- Keys (root MIDI -> Vital), le pre-FX tombe AVANT le synthé lui-même -> silence garanti. Bug
-- trouvé 2026-07-26 (audit AKAI muet) : `di` matchait TOUT `Sandbox #Input N`, y compris la
-- lane Keys, créant une piste "DI Sandbox #Input 3" qui n'enregistrait jamais rien d'utile.
-- Discriminant = I_RECINPUT : golem_rig encode un device MIDI en 4096 + dev*32 (cf. materialize
-- keys_midi_dev) ; une entrée AUDIO reste < 4096 (numéro de canal carte son direct).
local function is_di_capable(tr, nm)
  if not nm:match("^Sandbox #Input %d+$") then return false end
  return reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT") < 4096
end

-- Le BACKING n'a pas de piste séparée en multipiste (2026-07-27) : ce fichier existe déjà,
-- il vient de golem.fm, et le dupliquer à chaque prise ne crée AUCUNE information — juste du
-- volume. Il reste évidemment DANS LE MIX (c'est ce qu'on entendait), et take.json porte
-- désormais le lien vers la chanson : on sait quoi rejouer par-dessus.
local NO_OWN_TRACK = { [BUS] = true }

local function list_sources(perfrec)
  local out = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if tr ~= perfrec and not is_rec_track(nm) and not NO_OWN_TRACK[nm]
       and reaper.GetTrackNumSends(tr, 1) > 0 and src_allowed(nm) then
      out[#out + 1] = { tr = tr, nm = nm }
    end
  end
  return out
end

-- BUG (2026-07-26, régression multi/DI) : le DI était accroché à `list_sources` (filtre = piste
-- qui a un send HW). Une entrée SPLITTÉE (guitare -> clean/dirt) n'a PLUS de send HW sur son ROOT
-- (seul le folder-parent #merge en a un) : le root guitare n'apparaissait donc JAMAIS dans
-- list_sources -> aucune chance d'être DI-capable, malgré is_di_capable() écrite pour l'accepter.
-- Résultat : zéro DI sur la guitare (le cas d'usage n°1 du DI/reamp) dès qu'un preset a un split.
-- Fix : le DI ne dépend PAS de « qui a un send HW » (ça, c'est pour le fichier MIX par source) ;
-- il dépend UNIQUEMENT « existe-t-il un root d'entrée AUDIO physique, coché dans le bloc Rec ? »
-- -> on scanne les roots "Sandbox #Input N" indépendamment de list_sources.
local function di_candidates()
  local out = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if src_allowed(nm) and is_di_capable(tr, nm) then
      out[#out + 1] = { tr = tr, nm = nm }
    end
  end
  return out
end

local function make_rec_track(name)
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, false)
  local tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", name, true)
  reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 3)     -- output (stereo, latency compensated)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
  reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
  return tr
end

local function add_receive(src, dst, premode)
  local numHW = reaper.GetTrackNumSends(src, 1)          -- figé AVANT création (durcissement, voir garde ci-dessous)
  -- ⚠ BUG CORRIGÉ 2026-07-27 — LE DI N'ÉTAIT PAS UN DI. L'index était calculé
  -- `numHW + GetTrackNumSends(src,0) - 1` (prétendu « quirk cat 0 »). Or l'autotest
  -- send_index_selftest() le prouve : en catégorie 0, Reaper indexe les sends de PISTE SEULS
  -- (numHW=1, numSends=1 -> CreateTrackSend retourne 0 ; à l'index 1 il n'y a rien, et la
  -- sortie hardware reste intacte). Sur « Sandbox #Input 1 », qui A une sortie hardware,
  -- l'index valait donc 1 : les deux SetTrackSendInfo_Value ci-dessous étaient des NO-OP
  -- SILENCIEUX, le send DI restait en post-fader et capturait le signal TRAITÉ.
  -- Constaté : DI-Sandbox-Input-1.wav et Input-1.wav IDENTIQUES OCTET POUR OCTET sur les
  -- 24 prises existantes. On utilise désormais l'index RETOURNÉ par CreateTrackSend, qui est
  -- l'autorité (même idiome que golem_rig ligne ~1973).
  local s = reaper.CreateTrackSend(src, dst)
  reaper.SetTrackSendInfo_Value(src, 0, s, "I_SENDMODE", premode and 1 or 0)        -- 1 = PRE-FX (DI)
  reaper.SetTrackSendInfo_Value(src, 0, s, "I_DSTCHAN", 0)
  reaper.SetTrackSendInfo_Value(src, 0, s, "I_MIDIFLAGS", 31)   -- audio SEUL (piège super8, audit 2026-08-12)
  -- Le DI est la matière première de la transcription et de golem.fm : on ne SUPPOSE pas que
  -- le mode a été posé, on le RELIT. Un no-op silencieux est précisément ce qui a coûté 24 prises.
  local got = reaper.GetTrackSendInfo_Value(src, 0, s, "I_SENDMODE")
  local want = premode and 1 or 0
  if math.floor(got + 0.5) ~= want then
    local _, nm = reaper.GetSetMediaTrackInfo_String(src, "P_NAME", "", false)
    log(("⚠⚠ add_receive '%s' : I_SENDMODE voulu=%d mais relu=%s (index %d) — %s")
        :format(nm, want, tostring(got), s, premode and "LE DI NE SERA PAS UN DI" or "routage suspect"))
  end
  -- GARDE-FOU (durcissement 2026-07-26, audit AKAI muet) : si l'index `s` retombait par erreur sur
  -- le send HARDWARE (au lieu du nouveau send piste-à-piste), les 2 lignes ci-dessus écraseraient
  -- son I_SENDMODE/I_DSTCHAN -> la piste sort MUETTE aux enceintes SANS AUCUN autre symptôme
  -- (FX intacts, meters internes normaux — exactement le piège chassé ce jour-là). Signature =
  -- le nombre de sends HW n'a plus de raison de bouger ici ; s'il bouge, quelque chose a touché
  -- le mauvais objet -> log fort, jamais silencieux.
  if reaper.GetTrackNumSends(src, 1) ~= numHW then
    local _, nm = reaper.GetSetMediaTrackInfo_String(src, "P_NAME", "", false)
    log("⚠⚠ add_receive : nb de sends HW de '" .. nm .. "' a changé pendant la pose du receive (" ..
        numHW .. " -> " .. reaper.GetTrackNumSends(src, 1) .. ") — piste possiblement MUETTE aux enceintes, vérifier son HWOUT")
  end
end

local function drop_multi_tracks()
  for i = reaper.CountTracks(0) - 1, 0, -1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm:sub(1, #MPREFIX) == MPREFIX then reaper.DeleteTrack(tr) end
  end
end

-- ── MIDI = LA « DI » D'UN INSTRUMENT MIDI (2026-07-27) ───────────────────────────────
-- Sur une lane Keys, le pre-FX tombe AVANT le synthé : une « DI » audio y est du silence garanti
-- (cf. is_di_capable). Le vrai équivalent du DI, c'est le FLUX MIDI : les notes, la vélocité et
-- la pédale, avant que Vital n'en fasse un son. On capte donc l'entrée du contrôleur sur une
-- piste dédiée, en parallèle du root (qui, lui, continue de piloter le synthé : recmon 0 et
-- B_MAINSEND 0 sur la piste de capture -> aucun double déclenchement, aucun double audio).
local MPREFIX_MIDI = "Recording:MIDI "

local function midi_candidates()
  local out = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    -- même discriminant que is_di_capable, à l'envers : >= 4096 = device MIDI (golem_rig encode
    -- l'entrée d'une lane Keys en 4096 + dev*32).
    if nm:match("^Sandbox #Input %d+$") and src_allowed(nm)
       and reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT") >= 4096 then
      out[#out + 1] = { tr = tr, nm = nm, inp = reaper.GetMediaTrackInfo_Value(tr, "I_RECINPUT") }
    end
  end
  return out
end

local function make_midi_rec_track(name, recinput)
  local idx = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(idx, false)
  local tr = reaper.GetTrack(0, idx)
  reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", name, true)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", recinput)   -- MÊME device MIDI que le root
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 0)           -- 0 = enregistre l'ENTRÉE (donc du MIDI)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)            -- le root monitore déjà : pas de doublon
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
  reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
  return tr
end

local function build_multi(perfrec)
  drop_multi_tracks()
  local n = 0
  for _, s in ipairs(list_sources(perfrec)) do
    add_receive(s.tr, make_rec_track(MPREFIX .. s.nm), false)
    n = n + 1
  end
  if rec_mode == "tracks_di" then
    for _, s in ipairs(di_candidates()) do
      add_receive(s.tr, make_rec_track(MPREFIX .. "DI " .. s.nm), true)
      n = n + 1
    end
  end
  -- ⚠ LA CAPTURE MIDI NE DÉPEND PLUS DU MODE (docs/drums-kit.md lot 3, 2026-09-18) : elle était
  -- rangée avec le DI, donc absente en « mix » et en « tracks » — or ce n'est pas une variante du DI,
  -- c'est ce que le musicien a JOUÉ, la seule trace qui se relit en notes. Elle ne coûte rien quand
  -- personne ne joue : depuis ce jour, un fichier SANS NOTE n'est pas écrit du tout.
  for _, s in ipairs(midi_candidates()) do
    make_midi_rec_track(MPREFIX_MIDI .. s.nm, s.inp)
    log("  MIDI capté <- " .. s.nm .. " (recinput " .. tostring(s.inp) .. ")")
    n = n + 1
  end
  return n
end

-- self-heal MULTI (revue reascript 2026-07-23) : un recall/rebuild pendant la prise arrache les
-- receives cat-0 des pistes Recording:* (golem_rig purge les sends des roots réutilisés) -> sans
-- ceci, la piste enregistre du SILENCE sans trace. On re-scelle par NOM (les sources renaissent
-- avec le même nom) ; source disparue = loguée UNE fois (prise incomplète, mais dite).
local warned_lost = {}
local function heal_multi()
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    -- ⚠ les pistes de capture MIDI n'ont AUCUN receive à re-sceller : elles lisent directement
    -- l'entrée matérielle du contrôleur (I_RECINPUT). Sans cette exclusion, l'auto-réparation
    -- cherchait une piste-source nommée « MIDI Sandbox #Input 3 » et criait « source disparue »
    -- à chaque prise clavier — fausse alerte constatée au rig le 2026-07-27.
    if nm:sub(1, #MPREFIX_MIDI) == MPREFIX_MIDI then
      -- rien à faire : capture directe, pas de receive
    elseif nm:sub(1, #MPREFIX) == MPREFIX and reaper.GetTrackNumSends(tr, -1) == 0 then
      local src_nm = nm:sub(#MPREFIX + 1)
      local di = src_nm:match("^DI (.+)$")
      if di then src_nm = di end
      local src = find_track(src_nm)
      if src then
        add_receive(src, tr, di ~= nil)
        log("multi : receive re-scellé <- " .. src_nm .. (di and " (DI)" or ""))
      elseif not warned_lost[nm] then
        warned_lost[nm] = true
        log("⚠ multi : source « " .. src_nm .. " » disparue (recall pendant REC ?) — cette piste restera partielle")
      end
    end
  end
end

-- ── publication d'état ──
local function publish()
  -- "error" : additif (le bridge ne lit que recording/file/started_at) — c'est le canal par
  -- lequel l'UI peut enfin dire « la prise a échoué et voilà pourquoi » au lieu de rien.
  local s = string.format('{"recording":%s,"file":%s,"started_at":%s,"error":%s}',
    recording and "true" or "false",
    jstr(recording and cur_file or (cur_file or "")), jstr(cur_started or ""),
    jstr(stall_msg or warn_msg or ""))
  write_atomic(STATUS, s)
end

-- ── démarrage ──
local function op_start(want_backing)
  if recording then log("start ignoré (déjà en cours)"); return end
  local t_in = reaper.time_precise()                                      -- témoin : combien coûte la préparation
  reaper.RecursiveCreateDirectory(REC_DIR, 0)
  rec_sources, rec_mode, rec_keep_mix = read_sources()                    -- coches + mode + « Song mix », figés pour la prise
  local ts = os.date("%Y%m%d-%H%M%S")
  cur_file    = (rec_mode == "mix") and ("recordings/perf-" .. ts .. ".wav")
                or ("recordings/perf-" .. ts)                             -- multi : un DOSSIER par prise
  cur_started = iso_now()
  reaper.PreventUIRefresh(1)
  reaper.GetSetProjectInfo_String(0, "RECORD_PATH", REC_DIR, true)       -- écrit ici (chemin absolu)
  local tr = ensure_track()
  for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do                   -- purge items d'une prise précédente
    reaper.DeleteTrackMediaItem(tr, reaper.GetTrackMediaItem(tr, i))
  end
  -- ── AUTO-MUTE backing (2026-07-26, retour utilisateur : « je lance l'enregistrement, le
  -- backing se lance, je le coupe, ça tronque la prise ») : CSurf_OnRecord() ci-dessous engage
  -- aussi PLAY -> si une chanson est chargée sur la piste Backing Track, ses items sonnent MÊME SI
  -- golem_backing affiche "paused" (le transport, lui, ne ment pas). On ne coupe QUE si le
  -- transport n'était PAS déjà en lecture avant la prise : s'il jouait déjà, le backing tourne
  -- VOLONTAIREMENT (cas d'usage réel : jouer par-dessus et le capter) -> on n'y touche jamais.
  local was_playing = (reaper.GetPlayState() & 1) == 1
  bus_muted_by_us = false
  from_zero = not was_playing
  if from_zero then
    -- ⚠ EN PAUSE, Reaper reprend à la position de PAUSE, pas au curseur d'édition : mesuré le
    -- 2026-09-21, départ à 16,8 s malgré le SetEditCurPos(0). On sort donc de la pause d'abord
    -- (1016 est sans danger ICI : on n'enregistre pas encore, donc aucun prompt modal).
    if (reaper.GetPlayState() & 2) ~= 0 then reaper.Main_OnCommand(1016, 0) end
    reaper.SetEditCurPos(0, false, false)
  end
  if want_backing then
    -- LE MÊME GESTE lance la prise ET le backing (bloc Rec + bloc Backing sur un switch, 2026-09-21) :
    -- la lecture est VOULUE même si le transport ne tourne pas encore — c'est la prise qui va le
    -- lancer. On ne coupe pas, et on rouvre le bus s'il était resté coupé d'une prise précédente.
    local bus = find_track(BUS)
    if bus and reaper.GetMediaTrackInfo_Value(bus, "B_MUTE") == 1 then
      reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", 0)
      log("backing voulu par le geste : bus rouvert pour la prise")
    end
  elseif not was_playing then
    local bus = find_track(BUS)
    if bus and reaper.GetMediaTrackInfo_Value(bus, "B_MUTE") == 0 then
      reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", 1)
      bus_muted_by_us = true
      log("backing coupé pour la prise (transport à l'arrêt avant record = lecture non voulue)")
    end
  end
  -- ── chien de garde repeat/boucle (2026-07-26, ceinture) : une boucle A/B (golem_backing) encore
  -- active COUPE l'item enregistré à la fin de la boucle (Reaper empile les tours en TAKES sur un
  -- item minuscule = durée de la boucle, pas de la prise). Figé AVANT, coupé pour la prise, restauré
  -- au stop (la boucle de travail du musicien doit survivre à une prise, jamais pendant qu'on capte).
  prior_repeat = reaper.GetSetRepeatEx(0, -1)
  prior_loop_a, prior_loop_b = reaper.GetSet_LoopTimeRange(false, true, 0, 0, false)
  reaper.GetSetRepeatEx(0, 0)                                             -- repeat OFF : pas de prises en boucle
  reaper.GetSet_LoopTimeRange(true, true, 0, 0, false)                    -- neutralise la région/boucle active
  log(string.format("état avant prise : was_playing=%s repeat=%s loop=[%.2f,%.2f]",
      tostring(was_playing), tostring(prior_repeat), prior_loop_a or 0, prior_loop_b or 0))
  if rec_mode == "mix" then
    drop_multi_tracks()                                                   -- reliquats éventuels d'une prise multi
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)                     -- ré-affirme (au cas où)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 3)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
    ensure(tr, true)                                                      -- receives + neutralisation des armées
  else
    -- MULTI : la piste mix n'écrivait RIEN — on n'avait donc jamais « ce que ça donnait ».
    -- Elle est désormais armée AUSSI, si la coche « Song mix » du bloc Rec est mise.
    -- ⚠ ensure() (qui remonte les receives du mix) appelle scan() et doit passer AVANT
    -- build_multi, sinon il neutraliserait les pistes Recording:* fraîchement armées.
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", rec_keep_mix and 1 or 0)
    if rec_keep_mix then
      reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 3)
      reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
      reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
      ensure(tr, true)                                                    -- receives du mix (scan inclus)
    else
      scan(tr)                                                            -- neutralise les autres pistes armées
    end
    warned_lost = {}                                                      -- alertes « source perdue » : par prise
    local n = build_multi(tr)
    log("multi : " .. n .. " piste(s) d'enregistrement (" .. rec_mode ..
        ", mix " .. (rec_keep_mix and "GARDÉ" or "non") .. ")")
  end
  reaper.PreventUIRefresh(-1)
  if (reaper.GetPlayState() & 4) == 0 then reaper.CSurf_OnRecord() end    -- engage le transport record
  log(string.format("préparation de la prise : %.0f ms avant le départ du transport", (reaper.time_precise() - t_in) * 1000))
  rec_t0      = reaper.time_precise()                                     -- témoins du chien de garde
  last_pos    = reaper.GetPlayPosition()
  last_move_t = rec_t0
  moved       = false
  stall_msg, warn_msg = nil, nil
  recording   = true
  reaper.SetProjExtState(0, "golem", "perf_rec", "1")
  reaper.SetProjExtState(0, "golem", "perf_file", cur_file)
  reaper.SetProjExtState(0, "golem", "perf_started", cur_started)
  reaper.SetProjExtState(0, "golem", "perf_mode", rec_mode)               -- survit à un restart du script
  publish()
  log("REC start (" .. rec_mode .. ") -> " .. cur_file)
end

-- ── arrêt : stop le transport (finalise le .wav), finalisation différée d'un tick ──
local function op_stop()
  if not recording then log("stop ignoré (pas d'enregistrement)"); return end
  -- ⚠ PAS 1016 (Transport: Stop) : en record, il ouvre le prompt MODAL « save/delete/rename
  -- recorded files » qui gèle le script (bug chassé au log : mort silencieuse dans op_stop).
  -- 40667 = « Transport: Stop (save all recorded media) » : ferme le wav SANS dialogue.
  -- ⚠ NE RIEN toucher d'autre ICI (2026-07-26, régression trouvée en test) : modifier une piste
  -- (mute) ou l'état repeat/boucle JUSTE APRÈS 40667, dans le même tick, a fait perdre l'item tout
  -- juste fermé par Reaper (0 fichier récupéré, systématique) — vraisemblablement le même bloc
  -- undo/état-projet que la fermeture d'enregistrement. La restauration attend donc `finalize()`
  -- (quelques ticks plus tard, l'item est stable) — cf. tout en haut de `finalize`.
  if (reaper.GetPlayState() & 4) ~= 0 then reaper.Main_OnCommand(40667, 0) end
  recording = false
  reaper.SetProjExtState(0, "golem", "perf_rec", "0")
  pending = 60                                                            -- attend que l'item enregistré soit dispo
  log("REC stop demandé (finalisation en cours)")
end

-- récupère le .wav de la prise, le renomme en recordings/perf-…wav, retire l'item (le fichier reste).
-- ── écriture d'un Standard MIDI File (format 0) ──────────────────────────────────────────
-- Reaper n'a AUCUNE API pour « enregistrer le MIDI dans un .mid » : il crée un item MIDI dans
-- le projet. On lit donc les événements bruts et on écrit le fichier nous-mêmes — une vingtaine
-- de lignes, zéro dépendance, et on maîtrise la base de temps.
-- MIDI_GetAllEvts rend une suite de : offset int32 LE (ticks depuis l'évt précédent) · flag u8 ·
-- longueur int32 LE · octets du message.
local function vlq(n)                                   -- delta-time à longueur variable (norme SMF)
  local b = { n % 128 }
  n = math.floor(n / 128)
  while n > 0 do table.insert(b, 1, (n % 128) + 128); n = math.floor(n / 128) end
  return string.char(table.unpack(b))
end

local function be32(n) return string.pack(">I4", n) end

local function write_midi_file(take, path, bpm)
  local ok, buf = reaper.MIDI_GetAllEvts(take, "")
  if not ok or not buf or #buf == 0 then return false, "aucun événement" end
  -- ticks par noire de CETTE prise (dépend du réglage projet, ne pas supposer 960)
  local ppq = math.floor((reaper.MIDI_GetPPQPosFromProjQN(take, 1)
                        - reaper.MIDI_GetPPQPosFromProjQN(take, 0)) + 0.5)
  if ppq < 24 then ppq = 960 end
  local ev, pos, pending, nev, nnotes = {}, 1, 0, 0, 0
  -- tempo (méta) en tête : la partition doit retomber sur la bonne grille
  local us = math.floor(60000000 / (bpm and bpm > 0 and bpm or 120) + 0.5)
  ev[#ev + 1] = vlq(0) .. "\255\81\3" .. string.pack(">I3", us)
  while pos + 8 <= #buf + 1 do
    local off, flag, len = string.unpack("<i4B i4", buf, pos)
    pos = pos + 9
    local msg = buf:sub(pos, pos + len - 1)
    pos = pos + len
    pending = pending + off
    -- on saute les méta INTERNES de Reaper (0xFF … notation, texte de piste) : elles n'ont pas
    -- de sens hors du projet et pollueraient le fichier. Les messages de jeu passent tous.
    if len > 0 and msg:byte(1) ~= 0xFF then
      ev[#ev + 1] = vlq(pending) .. msg
      pending = 0
      nev = nev + 1
      -- ⚠ COMPTER LES NOTES, PAS LES ÉVÉNEMENTS (2026-09-18) : Reaper ferme tout item MIDI par un
      -- CC123 (all-notes-off). `nev == 0` ne se produisait donc JAMAIS, et on écrivait un fichier de
      -- 39 octets — bien formé, sans une seule frappe. Constaté sur CE dépôt : 14 prises MIDI depuis
      -- le 2026-08-02, 14 fois « 1 événement », zéro note ; et deux docs affirmaient « la capture
      -- existe, rien à transcrire ». Bonne forme, mauvaise nature (CLAUDE.md).
      if (msg:byte(1) & 0xF0) == 0x90 and (msg:byte(3) or 0) > 0 then nnotes = nnotes + 1 end
    end
  end
  if nnotes == 0 then return false, "aucune note jouée (" .. nev .. " événement(s) : le module n'a rien envoyé)" end
  ev[#ev + 1] = vlq(pending) .. "\255\47\0"             -- End of Track
  local trk = table.concat(ev)
  local f = io.open(path, "wb")
  if not f then return false, "ouverture impossible" end
  f:write("MThd" .. be32(6) .. string.pack(">I2I2I2", 0, 1, ppq))
  f:write("MTrk" .. be32(#trk) .. trk)
  f:close()
  return true, nnotes
end

local function safe_name(nm)
  nm = nm:gsub("^" .. MPREFIX, ""):gsub("^Sandbox #", ""):gsub("[^%w%-. ]", ""):gsub("%s+", "-")
  return (nm == "" and "track") or nm
end

local function finalize()
  -- restaure backing/repeat MAINTENANT (pas dans op_stop, cf. sa note) : quelques ticks après le
  -- 40667, l'item est déjà stable -> aucun risque de le faire disparaître.
  if bus_muted_by_us then
    local bus = find_track(BUS)
    if bus then reaper.SetMediaTrackInfo_Value(bus, "B_MUTE", 0) end
    bus_muted_by_us = false
    log("backing rétabli après la prise")
  end
  if from_zero then                                                       -- prête pour la prise suivante
    reaper.SetEditCurPos(0, false, false)
    from_zero = false
  end
  if prior_repeat == 1 then
    reaper.GetSet_LoopTimeRange(true, true, prior_loop_a or 0, prior_loop_b or 0, false)
    reaper.GetSetRepeatEx(0, 1)
    log(string.format("repeat/boucle restaurés (%.2f -> %.2f)", prior_loop_a or 0, prior_loop_b or 0))
  end
  if stall_msg then
    -- prise abandonnée par le chien de garde : AUCUN échantillon n'a pu être capturé.
    -- On nettoie les pistes multi et on n'annonce SURTOUT pas de fichier (sinon le bridge
    -- écrirait un manifeste take.json pour un .wav qui n'existe pas).
    drop_multi_tracks()
    reaper.UpdateArrange()
    log("⚠ prise abandonnée : " .. stall_msg)
    cur_file = nil
    pending  = 0
    publish()
    return
  end
  if rec_mode ~= "mix" then
    -- MULTI : un dossier par prise, un .wav par piste Recording:* (DI comprises)
    local dir = ROOT .. "/" .. (cur_file or ("recordings/perf-" .. os.date("%Y%m%d-%H%M%S")))
    reaper.RecursiveCreateDirectory(dir, 0)
    local moves = {}
    for i = 0, reaper.CountTracks(0) - 1 do
      local tr = reaper.GetTrack(0, i)
      local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
      if nm:sub(1, #MPREFIX_MIDI) == MPREFIX_MIDI then
        -- piste de capture MIDI : pas de .wav à déplacer, on ÉCRIT un .mid depuis les événements
        local n = reaper.CountTrackMediaItems(tr)
        if n == 0 then
          log("  " .. nm .. " : aucun item MIDI (rien joué au clavier ?)")
        else
          local it = reaper.GetTrackMediaItem(tr, n - 1)
          for k = 0, n - 1 do
            local cand = reaper.GetTrackMediaItem(tr, k)
            if reaper.GetMediaItemInfo_Value(cand, "D_LENGTH") > reaper.GetMediaItemInfo_Value(it, "D_LENGTH") then it = cand end
          end
          local take = reaper.GetActiveTake(it)
          local base = safe_name((nm:gsub("^" .. MPREFIX_MIDI, "")))
          local tgt = dir .. "/MIDI-" .. base .. ".mid"
          if take then
            local okw, info = write_midi_file(take, tgt, reaper.Master_GetTempo())
            if okw then log("  " .. nm .. " : " .. info .. " note(s) jouée(s) -> " .. tgt)
            else log("  " .. nm .. " : pas de .mid écrit (" .. tostring(info) .. ")") end
          end
        end
      elseif nm:sub(1, #MPREFIX) == MPREFIX then
        local n = reaper.CountTrackMediaItems(tr)
        if n > 0 then
          local it = reaper.GetTrackMediaItem(tr, n - 1)
          if n > 1 then
            log("⚠⚠ finalize multi : " .. n .. " items sur '" .. nm .. "' (attendu 1, probable split xrun/glitch) — on garde le PLUS LONG, pas juste le dernier")
            for k = 0, n - 1 do
              local cand = reaper.GetTrackMediaItem(tr, k)
              if reaper.GetMediaItemInfo_Value(cand, "D_LENGTH") > reaper.GetMediaItemInfo_Value(it, "D_LENGTH") then it = cand end
            end
          end
          log("  " .. nm .. " : item retenu = " .. string.format("%.2f", reaper.GetMediaItemInfo_Value(it, "D_LENGTH")) .. " s (n=" .. n .. ")")
          local take = reaper.GetActiveTake(it) or reaper.GetMediaItemTake(it, 0)
          local src = take and reaper.GetMediaItemTake_Source(take)
          local sf = src and reaper.GetMediaSourceFileName(src, "")
          if sf and sf ~= "" then moves[#moves + 1] = { sf = sf, tgt = dir .. "/" .. safe_name(nm) .. ".wav" } end
        end
      end
    end
    -- le MIX complet, s'il a été gardé : la piste « Recording » ne porte PAS le préfixe
    -- MPREFIX, elle échappe donc à la boucle ci-dessus. On récupère son item séparément et on
    -- le range dans le même dossier sous le nom « Mix.wav ».
    if rec_keep_mix then
      local mx = find_track(TRACK)
      local n = mx and reaper.CountTrackMediaItems(mx) or 0
      if n > 0 then
        local it = reaper.GetTrackMediaItem(mx, n - 1)
        for k = 0, n - 1 do                                 -- même garde qu'ailleurs : on garde le PLUS LONG
          local cand = reaper.GetTrackMediaItem(mx, k)
          if reaper.GetMediaItemInfo_Value(cand, "D_LENGTH") > reaper.GetMediaItemInfo_Value(it, "D_LENGTH") then it = cand end
        end
        log("  " .. TRACK .. " (mix) : item retenu = " ..
            string.format("%.2f", reaper.GetMediaItemInfo_Value(it, "D_LENGTH")) .. " s (n=" .. n .. ")")
        local take = reaper.GetActiveTake(it) or reaper.GetMediaItemTake(it, 0)
        local src = take and reaper.GetMediaItemTake_Source(take)
        local sf = src and reaper.GetMediaSourceFileName(src, "")
        if sf and sf ~= "" then moves[#moves + 1] = { sf = sf, tgt = dir .. "/Mix.wav" } end
      end
      for i = (mx and reaper.CountTrackMediaItems(mx) or 0) - 1, 0, -1 do    -- piste mix laissée propre
        reaper.DeleteTrackMediaItem(mx, reaper.GetTrackMediaItem(mx, i))
      end
    end
    drop_multi_tracks()                                     -- libère les items AVANT de déplacer les fichiers
    reaper.UpdateArrange()
    local moved = 0
    for _, m in ipairs(moves) do
      local ok, err = move_recording(m.sf, m.tgt)
      if ok then moved = moved + 1
      else log("⚠ multi : déplacement échoué : " .. tostring(m.sf) .. " : " .. tostring(err)) end
    end
    if moved > 0 then log("finalisé (multi) : " .. moved .. " fichier(s) -> " .. tostring(cur_file))
    else log("⚠ finalisation multi : aucun fichier récupéré") end
    pending = 0
    publish()
    return
  end
  local tr = find_track(TRACK)
  local srcfile
  if tr then
    local n = reaper.CountTrackMediaItems(tr)
    if n > 0 then
      local it = reaper.GetTrackMediaItem(tr, n - 1)
      if n > 1 then
        log("⚠⚠ finalize mix : " .. n .. " items sur '" .. TRACK .. "' (attendu 1, probable split xrun/glitch) — on garde le PLUS LONG, pas juste le dernier")
        for k = 0, n - 1 do
          local cand = reaper.GetTrackMediaItem(tr, k)
          if reaper.GetMediaItemInfo_Value(cand, "D_LENGTH") > reaper.GetMediaItemInfo_Value(it, "D_LENGTH") then it = cand end
        end
      end
      log("  " .. TRACK .. " : item retenu = " .. string.format("%.2f", reaper.GetMediaItemInfo_Value(it, "D_LENGTH")) .. " s (n=" .. n .. ")")
      local take = reaper.GetActiveTake(it) or reaper.GetMediaItemTake(it, 0)
      if take then
        local src = reaper.GetMediaItemTake_Source(take)
        if src then srcfile = reaper.GetMediaSourceFileName(src, "") end
      end
    end
    for i = reaper.CountTrackMediaItems(tr) - 1, 0, -1 do                 -- retire les items (le projet reste propre)
      reaper.DeleteTrackMediaItem(tr, reaper.GetTrackMediaItem(tr, i))
    end
    reaper.UpdateArrange()
  end
  local target = ROOT .. "/" .. (cur_file or ("recordings/perf-" .. os.date("%Y%m%d-%H%M%S") .. ".wav"))
  if srcfile and srcfile ~= "" then
    local ok, err = move_recording(srcfile, target)
    if ok then log("finalisé : " .. srcfile:match("[^/]+$") .. " -> " .. tostring(cur_file))
    else log("⚠ finalisation : déplacement échoué : " .. tostring(err)) end
  else
    log("⚠ finalisation : aucun item/source enregistré (fichier introuvable sur " .. TRACK .. ")")
  end
  pending = 0
  publish()
end

-- ── commandes (ProjExtState golem/perf_cmd, posé par golem_watch ou le bootstrap apply) ──
local last_body = nil
local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "perf_cmd")
  if not body or body == "" then return end
  if body ~= last_body then log("cmd vue : " .. body); last_body = body end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if seq and seq == last_seq then return end
  last_seq = seq
  if body:find('"on"%s*:%s*true') then
    local want = body:find('"backing"%s*:%s*true') ~= nil
    local in_ms = tonumber(body:match('"in_ms"%s*:%s*(%-?[%d%.]+)')) or 0
    if in_ms > 0 and not recording then
      start_at = { t = reaper.time_precise() + in_ms / 1000, backing = want }
      log(string.format("départ différé de %.0f ms (décompte)", in_ms))
    else
      start_at = nil
      op_start(want)
    end
  elseif start_at then
    start_at = nil                                                        -- second appui PENDANT le décompte : on annule
    log("décompte annulé : aucune prise lancée")
  else
    op_stop()
  end
end

-- ── boucle ──
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "perfrec_gen", GEN, false)   -- la dernière instance lancée gagne

-- ── chien de garde : le transport avance-t-il VRAIMENT ? (cf. en-tête) ──
-- Défini APRÈS op_stop/finalize : il s'en sert pour couper court proprement.
-- Deux cas, deux traitements — ne JAMAIS jeter ce qui a pu être capté :
--   • le transport n'a JAMAIS bougé  -> prise mort-née, aucun fichier n'existe : on abandonne
--     et on publie l'erreur (avant : « aucun item/source enregistré », qui accusait le routage) ;
--   • il a bougé PUIS s'est figé (carte arrachée en plein morceau) -> il y a de l'audio sur le
--     disque : on finalise NORMALEMENT et on marque la prise « incomplète ».
local function abort_take(msg)
  log("⚠ " .. msg)
  if moved then
    warn_msg = msg .. " — prise INCOMPLÈTE (ce qui a été capté avant est conservé)"
    op_stop()                                              -- finalisation normale : on sauve
  else
    stall_msg = msg .. " — Reaper n'a écrit AUCUN fichier"
    log("   → vérifier la carte (aplay -l / /proc/asound/cards), puis commande « audio_reset » "
        .. "(Audio_Quit+Audio_Init) ou relancer Reaper")
    op_stop(); pending = 1                                 -- finalisation au tick suivant
  end
end

local function watchdog()
  if not recording or pending > 0 or not rec_t0 then return end
  local now = reaper.time_precise()
  if now - rec_t0 < GRACE then return end                  -- le record n'a pas encore pris : on ne juge pas
  local ps = reaper.GetPlayState()
  if (ps & 4) == 0 then
    abort_take("le transport est sorti du mode RECORD (stop manuel ? autre script ?)")
    return
  end
  if (ps & 2) ~= 0 then last_move_t = now; return end      -- en pause : figé, mais légitime
  local pos = reaper.GetPlayPosition()
  if math.abs(pos - last_pos) >= 0.05 then                 -- ça tourne : on réarme la fenêtre
    last_pos, last_move_t, moved = pos, now, true
    return
  end
  if now - last_move_t > STALL_AFTER then
    abort_take(string.format(
      "moteur audio figé : la position de lecture n'a pas bougé en %.1f s "
      .. "(carte son débranchée ou ré-énumérée ?)", now - last_move_t))
  end
end

local function tick()
  poll_cmd()
  if start_at and reaper.time_precise() >= start_at.t then
    local want = start_at.backing
    start_at = nil
    op_start(want)
  end
  watchdog()
  if pending > 0 then
    local ready = false
    if rec_mode ~= "mix" then
      -- TOUTES les pistes multi doivent avoir leur item (revue : ANY finalisait trop tôt et
      -- perdait en silence les pistes retardataires) ; pending==1 reste le filet de sortie.
      local total, with_item = 0, 0
      for i = 0, reaper.CountTracks(0) - 1 do
        local tr = reaper.GetTrack(0, i)
        local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
        if nm:sub(1, #MPREFIX) == MPREFIX then
          total = total + 1
          if reaper.CountTrackMediaItems(tr) > 0 then with_item = with_item + 1 end
        end
      end
      ready = (total > 0 and with_item == total)
    else
      local tr = find_track(TRACK)
      ready = (tr and reaper.CountTrackMediaItems(tr) > 0) and true or false
    end
    if ready or pending == 1 then finalize()
    else pending = pending - 1 end
  elseif recording and rec_mode == "mix" then
    ensure(find_track(TRACK) or ensure_track(), false)                    -- self-heal receives après recall
  elseif recording then
    heal_multi()                                                          -- self-heal des receives multi
  end
end

-- ── AUTOTEST d'indexation des sends (dev) ────────────────────────────────────────────────
-- Question à trancher UNE FOIS : en catégorie 0, Set/GetTrackSendInfo_Value indexe-t-il les
-- sends de piste seuls, ou les sorties HARDWARE d'abord ? La doc dit « 0 = sends » (catégories
-- séparées) ; un commentaire de golem_rig affirme l'inverse depuis le bug looper 2026-07-19.
-- Les deux ne peuvent pas être vrais, et le DI en dépend directement. On mesure au lieu d'arbitrer.
-- Armement : reaper.SetExtState("golem","perfrec_sendtest","1") — pistes jetables, supprimées ici.
local function send_index_selftest()
  if reaper.GetExtState("golem", "perfrec_sendtest") ~= "1" then return end
  reaper.SetExtState("golem", "perfrec_sendtest", "0", false)
  local n = reaper.CountTracks(0)
  reaper.InsertTrackAtIndex(n, false); local a = reaper.GetTrack(0, n)
  reaper.InsertTrackAtIndex(n + 1, false); local b = reaper.GetTrack(0, n + 1)
  reaper.GetSetMediaTrackInfo_String(a, "P_NAME", "ZZ selftest src", true)
  reaper.GetSetMediaTrackInfo_String(b, "P_NAME", "ZZ selftest dst", true)
  reaper.CreateTrackSend(a, nil)                       -- dst nil = SORTIE HARDWARE (le cas qui piège)
  local numHW = reaper.GetTrackNumSends(a, 1)
  local ret = reaper.CreateTrackSend(a, b)             -- retourne l'index du send créé
  local numS = reaper.GetTrackNumSends(a, 0)
  local naive, quirk = numS - 1, numHW + numS - 1
  reaper.SetTrackSendInfo_Value(a, 0, ret, "I_SENDMODE", 1)     -- pose PRE-FX à l'index RETOURNÉ
  log("── autotest index des sends ──")
  log(("  numHW=%d  numSends=%d  CreateTrackSend a retourné %d  (naïf=%d, « quirk »=%d)")
      :format(numHW, numS, ret, naive, quirk))
  log(("  relecture I_SENDMODE : à l'index retourné=%s | à l'index naïf=%s | à l'index quirk=%s")
      :format(tostring(reaper.GetTrackSendInfo_Value(a, 0, ret, "I_SENDMODE")),
              tostring(reaper.GetTrackSendInfo_Value(a, 0, naive, "I_SENDMODE")),
              tostring(reaper.GetTrackSendInfo_Value(a, 0, quirk, "I_SENDMODE"))))
  log(("  sortie HARDWARE (cat 1, idx 0) I_SENDMODE=%s I_DSTCHAN=%s — doit être restée intacte")
      :format(tostring(reaper.GetTrackSendInfo_Value(a, 1, 0, "I_SENDMODE")),
              tostring(reaper.GetTrackSendInfo_Value(a, 1, 0, "I_DSTCHAN"))))
  reaper.DeleteTrack(b); reaper.DeleteTrack(a)
  log("── fin autotest (pistes jetables supprimées) ──")
end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "perfrec_gen") ~= GEN then return end    -- remplacée : cette boucle meurt
  reaper.SetExtState("golem", "perfrec_alive", string.format("%.3f", reaper.time_precise()), false)
  pcall(send_index_selftest)
  -- pcall : une erreur d'un tick NE TUE JAMAIS la boucle (un defer qui lève = chaîne morte
  -- en silence -> stop perdu, enregistrement fantôme). On logue et on continue.
  local ok, err = pcall(tick)
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

-- ── état initial (redérivé du projet) ──
local function derive_state()
  local _, r = reaper.GetProjExtState(0, "golem", "perf_rec")
  local _, f = reaper.GetProjExtState(0, "golem", "perf_file")
  local _, s = reaper.GetProjExtState(0, "golem", "perf_started")
  local _, m = reaper.GetProjExtState(0, "golem", "perf_mode")
  rec_mode    = (m ~= "" and m) or "mix"
  recording   = (r == "1")
  cur_file    = (f ~= "" and f) or nil
  cur_started = (s ~= "" and s) or nil
  -- désync : le flag dit « rec » mais le transport ne l'est plus (Reaper relancé, stop manuel) -> corrige
  if recording and (reaper.GetPlayState() & 4) == 0 then
    recording = false
    reaper.SetProjExtState(0, "golem", "perf_rec", "0")
  end
end

derive_state()

-- résiduel vs bootstrap : un « kick » (posé par le bootstrap golem_apply juste avant de nous lancer)
-- signifie qu'une commande FRAÎCHE attend d'être exécutée. Sans kick (lancement par __startup au boot),
-- on ADOPTE le seq résiduel sans le rejouer (sinon un perf_cmd sauvegardé relancerait un REC au boot).
if reaper.GetExtState("golem", "perfrec_kick") == "1" then
  reaper.SetExtState("golem", "perfrec_kick", "", false)
  last_seq = nil                                                          -- -> poll_cmd exécutera la commande en attente
else
  local _, body = reaper.GetProjExtState(0, "golem", "perf_cmd")
  last_seq = body and body:match('"seq"%s*:%s*(%-?%d+)') or nil
end

publish()
log("démarré. piste=" .. TRACK .. " ; statut=" .. STATUS .. (recording and " ; REC en cours (redérivé)" or ""))
loop()
