-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — watch (veilleur)
  À lancer UNE FOIS dans Reaper (Actions → Load ReaScript → Run). Il tourne en tâche de fond
  (reaper.defer) et applique automatiquement chaque commande envoyée par l'app : dès que
  presets/.command.json change, il (re)exécute golem_apply.lua.

  Avantage : plus besoin de copier le "command ID" ni de mapper une action OSC pour le recall.
  L'app écrit la commande → le veilleur l'applique. (L'OSC reste pour meters/feedback.)

  Anti-double-boucle : chaque instance pose sa génération dans l'ExtState ; une instance qui
  n'est plus la dernière lancée s'arrête d'elle-même (relancer le script = REMPLACER le veilleur).
  ⚠ Le veilleur est chargé en mémoire au démarrage de Reaper : un edit de CE fichier ne prend
  effet qu'après relance du script ou de Reaper (cf. docs/lancement.md, Dépannage).
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
    _LOGF = root .. "/presets/.watch.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-watch] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT = repo_root()
local CMD = ROOT .. "/presets/.command.json"
local APPLY = ROOT .. "/reaper/Scripts/golem_apply.lua"
local RIG = ROOT .. "/reaper/Scripts/golem_rig.lua"      -- nouveau modèle (paths + splits)
local last = nil
local GEN = tostring(reaper.time_precise())              -- génération de CETTE instance
reaper.SetExtState("golem", "watch_gen", GEN, false)     -- la dernière lancée gagne

local function read(p) local f = io.open(p, "r"); if not f then return nil end local s = f:read("*a"); f:close(); return s end

local ACK = ROOT .. "/presets/.command-ack.json"
local function ack(cur)
  -- ACK de consommation (audit 2026-08-12) : write_command côté bridge ATTEND cet accusé
  -- avant d'écraser le slot — ce qui tue la classe « commande gelée écrasée sans trace »
  -- (cf. le pavé is_diag plus bas, panne du 2026-07-26). tmp+rename : jamais d'ack déchiré.
  local seq = cur and cur:match('"seq"%s*:%s*(%-?%d+)') or nil
  if not seq then return end
  -- Windows : os.rename ne remplace pas l'ACK précédent. Un fichier par séquence
  -- supprime le conflit sans introduire de fenêtre où le lecteur voit un JSON partiel.
  local dst = reaper.GetOS():find("Win", 1, true) and (ACK .. "." .. seq) or ACK
  local tmp = dst .. ".tmp"
  local f = io.open(tmp, "w")
  if not f then log("ACK : ouverture impossible " .. tmp); return end
  f:write(string.format('{"seq":%s,"t":%.3f}', seq, reaper.time_precise()))
  f:close()
  local ok, err = os.rename(tmp, dst)
  if not ok then log("ACK : publication impossible " .. dst .. " : " .. tostring(err)) end
end

-- Au démarrage : CONSOMME la commande résiduelle SANS l'exécuter. La rejouer pendant le chargement
-- du projet = chirurgie de pistes/FX pendant que l'audio démarre -> segfault mediaafx (constaté
-- 2026-07-10 au lancement). Le bridge ré-émet une commande fraîche à la première action (le montage
-- du Designer restaure la sandbox, chaque recall/stomp réécrit .command.json) : rien n'est perdu.
last = read(CMD)
if last then
  ack(last)                                              -- consommée (même jetée) = slot libre
  log("commande résiduelle ignorée au démarrage (le bridge ré-émettra à la 1re action)")
end

log("démarré. surveille " .. CMD)

-- INVENTAIRE DES PLUGINS (docs/block-status.md §3) : ce que Reaper a scanné, une fois au démarrage —
-- la liste ne change qu'avec un redémarrage de Reaper. Lecture seule, aucun FX instancié.
do
  local okinv, errinv = pcall(dofile, ROOT .. "/reaper/Scripts/golem_fxinventory.lua")
  if not okinv then log("inventaire des plugins : " .. tostring(errinv)) end
end

-- « SETTLE » ANTI-CRASH (bug PRÉ-EXISTANT du rig, révélé au test 2026-07-10 : reproduit AUSSI sans
-- looper). Un rebuild (rig_recall) fait de la chirurgie de pistes/FX ET lance des chargements ASYNC
-- (NAM/IR ZConvolv sur des threads worker). Toucher au graphe FX (autre rebuild, scene_apply, stomp)
-- AVANT que ces chargements soient finis -> use-after-free / double-free -> segfault / free() invalid.
-- Donc : après un rebuild, on GÈLE toute opération rig (rebuild/scène/stomp) pendant SETTLE, le temps
-- que Reaper stabilise. On ne consomme pas la commande (coalescing : la boucle relit la plus récente
-- au tick suivant — chaque preset a son propre <id>.rig.json, appliquer « le dernier » reste cohérent).
-- Le tuner (ProjExtState, aucune chirurgie FX) n'est jamais gelé. Scène-après-scène (hors fenêtre de
-- rebuild) passe librement (validé : les scènes seules ne crashent pas).
local SETTLE = 0.5
local settle_until = -1
-- VÉRIFICATION DIFFÉRÉE des fichiers (2026-09-07) : les modèles NAM se chargent dans un worker LV2
-- asynchrone, donc « le build a réussi » ne dit pas « l'ampli a son modèle ». ~2 s après chaque
-- recall/scène, golem_rig (ExtState rig_verify) relit EN CLAIR ce que chaque plugin a chargé, répare
-- une ligne perdue (une fois), et écrit presets/.rig-check.json -> puce « ⚠ FX FILE » sur /live.
local VERIFY_DELAY = 2.0
local verify_at, verify_retry = -1, 0
-- la vérification ne RÉPARE (ré-instanciation de la lane par SetTrackStateChunk) qu'après un REBUILD : le son
-- vient d'être reconstruit, une seconde réécriture ne coupe rien de plus. Après une simple scène, elle
-- SIGNALE seulement — réparer, c'était un trou (et le gel ~540 ms du x42) en plein morceau (audit 2026-10-15, R1).
local verify_heal = false

local function tick()
  if reaper.GetExtState("golem", "watch_gen") ~= GEN then
    log("veilleur remplacé par une instance plus récente — arrêt de celle-ci")
    return "stop"                                        -- pas de defer : la boucle meurt
  end
  local now0 = reaper.time_precise()
  if verify_at >= 0 and now0 >= verify_at and now0 >= settle_until then
    verify_at = -1
    -- "1" = première passe, "2" = la seconde : seule la seconde peut conclure qu'un modèle ne charge pas
    reaper.SetExtState("golem", "rig_verify", verify_retry > 0 and "2" or "1", false)
    reaper.SetExtState("golem", "rig_verify_heal", verify_heal and "1" or "0", false)
    local okv, errv = pcall(dofile, RIG)
    if not okv then log("erreur vérif fichiers: " .. tostring(errv)) end
    -- la seconde passe d'un rebuild garde le droit de réparer : on ne le retire qu'à la DERNIÈRE passe
    if verify_retry >= 1 or reaper.GetExtState("golem", "rig_verify_retry") ~= "1" then verify_heal = false end
    if reaper.GetExtState("golem", "rig_verify_retry") == "1" then
      reaper.DeleteExtState("golem", "rig_verify_retry", false)
      settle_until = reaper.time_precise() + SETTLE        -- une réparation ré-instancie des FX : même gel qu'un rebuild
      if verify_retry < 1 then verify_retry = verify_retry + 1; verify_at = reaper.time_precise() + VERIFY_DELAY end
    end
  end
  local cur = read(CMD)
  if cur and cur ~= last then
    local action = cur:match('"action"%s*:%s*"([^"]+)"')
    -- ⚠ BUG CORRIGÉ 2026-07-26 : le test était `action == "tuner" OU la charge contient la
    -- sous-chaîne "tuner"`. Or {"action":"reload","script":"golem_tuner"} contient "tuner" :
    -- le hot-swap POURTANT EN LISTE BLANCHE dans golem_apply n'atteignait JAMAIS golem_apply,
    -- il était routé ici et, faute de `"on":true`, DÉSARMAIT l'accordeur en silence. Idem pour
    -- {"action":"extstate","key":"tuner_diag",...} et tout preset/piste dont le nom contient
    -- « tuner ». L'action est déjà parsée juste au-dessus : on s'y tient, strictement.
    local is_tuner = (action == "tuner")
    -- backing : items/transport sur SES propres pistes, AUCUNE chirurgie FX -> jamais gelé
    -- (le bridge séquence lui-même à +0,7 s d'un rig_recall, cf. bridge/backing.py)
    local is_backing = (action == "backing")
    -- perf-rec : relais brut vers golem_perfrec (aucune chirurgie FX -> jamais gelé)
    local is_perf = (action == "perf_rec")
    -- sample : lanceur de one-shots (RS5k sur la piste "Sample") — on ne touche qu'à NOS propres FX
    -- de piste, jamais au graphe des presets -> jamais gelé (relais brut vers golem_sample.lua)
    local is_sample = (action == "sample")
    -- drums : boîte à rythmes (JSFX golem_drumseq + RS5k sur la piste "Drums") — on ne touche
    -- qu'à NOS propres FX de piste, jamais au graphe des presets -> jamais gelé (relais golem_drums.lua)
    local is_drums = (action == "drums")
    -- standard : lecteur de grilles (JSFX golem_chordseq sur SES pistes « Standard … ») — on ne
    -- touche qu'à NOS propres pistes, jamais au graphe des presets -> jamais gelé
    local is_standard = (action == "standard")
    -- preview : render stem d'un clone jetable (le bridge séquence hors des recalls)
    local is_preview = (action == "preview")
    -- click : métronome free-running (JSFX golem_click sur la piste "Click") — on ne touche qu'à
    -- NOTRE piste, jamais au graphe des presets -> jamais gelé (relais golem_click.lua)
    local is_click = (action == "click")
    -- drumlearn : la piste d'écoute de Calibration ▸ Drums (drum-tap.jsfx sur la piste « DrumLearn »)
    -- — on ne touche qu'à NOTRE piste, jamais au graphe des presets -> jamais gelé (relais golem_drumlearn.lua)
    local is_drumlearn = (action == "drumlearn")
    -- midi_reinit (2026-10-03, réparation MIDI auto sous Windows) : un appareil rebranché pendant que REAPER
    -- tourne reste une prise morte ; le bridge le voit réapparaître et demande à REAPER de rouvrir ses
    -- appareils. Aucun masque touché, aucune piste : passe même pendant le gel post-rebuild.
    local is_midi_reinit = (action == "midi_reinit")
    -- diag LECTURE SEULE (dumpfx/peaks/meters/midilist/recdiag/chunkdump) : aucune chirurgie FX,
    -- juste TrackFX_GetCount/GetParam -> fichier. BUG TROUVÉ 2026-07-26 (AKAI muet, roots à 0 FX
    -- au fxdump après un rebuild pourtant réussi) : gelées comme les autres, elles restaient
    -- coincées dans .command.json (slot UNIQUE) jusqu'à settle_until ; une commande EXEMPTÉE
    -- arrivée entre-temps (tuner/backing/click/… déclenchée par le bridge à +0,7-0,8 s d'un
    -- rig_recall, cf. app.py _do_recall) écrase alors le fichier ET `last` AVANT que la commande
    -- gelée n'ait eu son tour -> le dumpfx en attente disparaît SANS TRACE, .fxdump.json reste
    -- périmé indéfiniment (le rig est en réalité intact — faux négatif de diagnostic, pas un bug
    -- audio). Écriture pure -> aucun risque à les laisser passer PENDANT le settle (rien à libérer).
    local is_diag = (action == "dumpfx" or action == "peaks" or action == "meters"
                      or action == "midilist" or action == "recdiag" or action == "chunkdump")
    -- gèle toute op RIG (rebuild/scène/stomp) tant que le dernier rebuild n'a pas « settlé »
    if not (is_tuner or is_backing or is_perf or is_sample or is_drums or is_standard or is_preview or is_click or is_drumlearn or is_midi_reinit or is_diag) and settle_until >= 0 and reaper.time_precise() < settle_until then
      return                                             -- pas encore stable : réessai au tick suivant (commande fraîche)
    end
    last = cur
    ack(cur)                                             -- consommée : le bridge peut réécrire le slot
    if action == "rig_recall" then settle_until = reaper.time_precise() + SETTLE end
    if action == "rig_recall" or action == "scene_apply" then   -- vérif des fichiers une fois les workers finis
      verify_at = reaper.time_precise() + VERIFY_DELAY; verify_retry = 0
    end
    -- accordeur : commande légère {"action":"tuner","on":bool} -> arme via ProjExtState
    -- (lu par la boucle golem_tuner.lua). Pas de dofile : ni golem_apply ni golem_rig ne la gèrent.
    if is_tuner then
      local on = cur:find('"on"%s*:%s*true') ~= nil
      reaper.SetProjExtState(0, "golem", "tuner_on", on and "1" or "0")
      log("tuner " .. (on and "ON" or "OFF"))
    elseif is_backing then
      -- backing : relais brut vers la boucle golem_backing.lua (dédup par "seq" côté lecteur)
      reaper.SetProjExtState(0, "golem", "backing_cmd", cur)
    elseif is_perf then
      -- perf-rec : relais brut vers la boucle golem_perfrec.lua (dédup par "seq" côté lecteur)
      reaper.SetProjExtState(0, "golem", "perf_cmd", cur)
    elseif is_sample then
      -- sample : relais brut vers la boucle golem_sample.lua (dédup par "seq" côté lecteur)
      reaper.SetProjExtState(0, "golem", "sample_cmd", cur)
    elseif is_drums then
      -- drums : relais brut vers la boucle golem_drums.lua (dédup par "seq" côté lecteur)
      reaper.SetProjExtState(0, "golem", "drums_cmd", cur)
    elseif is_standard then
      -- standard : relais brut vers la boucle golem_chordseq.lua (dédup par "seq" côté lecteur)
      reaper.SetProjExtState(0, "golem", "standard_cmd", cur)
    elseif is_preview then
      -- preview : relais brut vers la boucle golem_preview.lua (dédup par "seq"+"scene")
      reaper.SetProjExtState(0, "golem", "preview_cmd", cur)
    elseif is_click then
      -- click : relais brut vers la boucle golem_click.lua (dédup par "seq")
      reaper.SetProjExtState(0, "golem", "click_cmd", cur)
    elseif is_drumlearn then
      -- drumlearn : relais brut vers la boucle golem_drumlearn.lua (dédup par "seq")
      reaper.SetProjExtState(0, "golem", "drumlearn_cmd", cur)
    elseif is_midi_reinit then
      if reaper.midi_reinit then reaper.midi_reinit(); log("midi_reinit : REAPER rouvre ses appareils MIDI (" .. (cur:match('"why"%s*:%s*"([^"]*)"') or "?") .. ")")
      else log("midi_reinit indisponible dans cette version de REAPER") end
    else
      -- rig_recall + stomp + mixer_apply = nouveau modèle (golem_rig / pistes Sandbox) ; le reste
      -- (dev tools) -> golem_apply. Motifs ENTRE GUILLEMETS : le routage par sous-chaîne nue a déjà
      -- détourné des presets nommés « tuner » (piège golem_watch, CLAUDE.md).
      local script = (cur:find('"rig_recall"', 1, true) or cur:find('"stomp"', 1, true)
                      or action == "vst_list" or action == "vst_open" or action == "vst_params" or action == "vst_state"
                      or cur:find('"mixer_apply"', 1, true)
                      or cur:find('"mixer_dump"', 1, true)) and RIG or APPLY
      reaper.DeleteExtState("golem", "rig_rebuilt", false)
      local ok, err = pcall(dofile, script)  -- applique la commande
      if not ok then log("erreur apply: " .. tostring(err)) end
      -- golem_rig a REBÂTI (une scène peut y retomber) : même gel qu'un rig_recall, et la vérif pourra réparer
      if reaper.GetExtState("golem", "rig_rebuilt") == "1" then
        reaper.DeleteExtState("golem", "rig_rebuilt", false)
        settle_until = reaper.time_precise() + SETTLE
        verify_heal = true
      end
    end
  end
end

-- la boucle survit à une erreur de son propre tick (audit 2026-10-15) : sans ce pcall, une exception tuait le
-- veilleur SEUL — plus une commande lue, alors que les autres boucles continuaient de dire « vivant »
local function loop()
  local ok, r = pcall(tick)
  if not ok then log("erreur du veilleur (il continue) : " .. tostring(r)) end
  if r ~= "stop" then reaper.defer(loop) end
end

loop()
