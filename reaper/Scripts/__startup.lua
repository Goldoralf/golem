-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — __startup
  Reaper exécute automatiquement Scripts/__startup.lua au démarrage.
  Ici : on lance le veilleur (golem_watch.lua) si le pointeur repo existe, pour que
  l'utilisateur n'ait RIEN à charger à la main. (lié par link-reaper.sh)
]]--
local res = reaper.GetResourcePath()
local os_name = reaper.GetOS()

-- GARDE DES BOUCLES defer (2026-10-05). Tous les scripts ci-dessous sont chargés par dofile dans CE
-- contexte Lua : une seule erreur dans un callback defer arrêtait TOUTES les boucles d'un coup, sans
-- une ligne nulle part (Windows, 07:20:46 puis à chaque rebuild : plus de commandes, plus de
-- télémétrie, le son passait toujours — l'écran disait « No sound card » ; la cause était une attente
-- active, pas une erreur, mais l'erreur aurait fait pareil et sans un mot). Chaque callback passe
-- désormais par xpcall : l'erreur est écrite (presets/.lua-errors.log, trace comprise), seule la
-- boucle fautive s'arrête. Pas de relance automatique : un callback ponctuel rejoué à 30 Hz
-- remplirait le journal ; on veut le NOM de la panne, pas la masquer.
local note, trace
do
  local rf = io.open(res .. "/golem-root.txt", "r")
  local groot = rf and rf:read("*l")
  if rf then rf:close() end
  local errlog = (groot and #groot > 0) and (groot .. "/presets/.lua-errors.log") or (res .. "/golem-lua-errors.log")
  note = function(msg)
    local f = io.open(errlog, "a")
    if f then f:write(os.date("%Y-%m-%d %H:%M:%S") .. " " .. msg .. "\n"); f:close() end
  end
  trace = (debug and debug.traceback) or tostring
  local raw_defer = reaper.defer
  reaper.defer = function(fn)
    return raw_defer(function()
      local ok, err = xpcall(fn, trace)
      if not ok then note(tostring(err)) end
    end)
  end
end

-- MÊME GARDE AU CHARGEMENT (2026-11-04, audit macOS). La garde defer ne couvre que les boucles : une erreur
-- au niveau supérieur d'un script (syntaxe, nil) remontait jusqu'ici, n'écrivait rien dans .lua-errors.log
-- et ARRÊTAIT ce fichier — le veilleur cassé, l'accordeur, le looper, le MIDI… ne se chargeaient plus.
-- Chaque script se charge seul : son erreur est notée sous son nom, les suivants se chargent quand même.
local function golem_load(path)
  local ok, err = xpcall(function() return dofile(path) end, trace)
  if not ok then note("load " .. path .. ": " .. tostring(err)) end
end

if os_name:match("^Win") or os_name:match("^OSX") or os_name:match("^macOS") then
  local probe = res .. "/Scripts/golem/golem_desktop_audio.lua"
  if reaper.file_exists(probe) then golem_load(probe) end
end
local f = io.open(res .. "/golem-root.txt", "r")
if f then
  local root = f:read("*l"); f:close()
  if root and #root > 0 then
    local watch = root .. "/reaper/Scripts/golem_watch.lua"
    if reaper.file_exists(watch) then
      golem_load(watch)
    end
    -- accordeur de scène : boucle de lecture permanente (hauteur -> presets/.tuner.json)
    local tuner = root .. "/reaper/Scripts/golem_tuner.lua"
    if reaper.file_exists(tuner) then
      golem_load(tuner)
    end
    -- looper : veilleur d'état (gmem golem_looper -> presets/.looper.json) + fallback de commande
    local looper = root .. "/reaper/Scripts/golem_looper.lua"
    if reaper.file_exists(looper) then
      golem_load(looper)
    end
    -- backing tracks : exécuteur de commandes (items/mix) + état -> presets/.backing.json
    local backing = root .. "/reaper/Scripts/golem_backing.lua"
    if reaper.file_exists(backing) then
      golem_load(backing)
    end
    -- perf rec : enregistrement du mix stéréo entendu -> recordings/*.wav + presets/.perf.json
    local perfrec = root .. "/reaper/Scripts/golem_perfrec.lua"
    if reaper.file_exists(perfrec) then
      golem_load(perfrec)
    end
    -- sample : lanceur de one-shots au pied (RS5k sur piste "Sample") -> presets/.sample.json
    local sample = root .. "/reaper/Scripts/golem_sample.lua"
    if reaper.file_exists(sample) then
      golem_load(sample)
    end
    -- drums : boîte à rythmes au pied (JSFX golem_drumseq + RS5k sur piste "Drums") -> presets/.drums.json
    local drums = root .. "/reaper/Scripts/golem_drums.lua"
    if reaper.file_exists(drums) then
      golem_load(drums)
    end
    -- click : métronome free-running (JSFX golem_click sur piste "Click") -> presets/.click.json
    local click = root .. "/reaper/Scripts/golem_click.lua"
    if reaper.file_exists(click) then
      golem_load(click)
    end
    -- standard : lecteur de grilles d'accords (JSFX golem_chordseq sur les pistes
    -- "Standard Keys"/"Standard Bass") -> presets/.standard.json
    local chordseq = root .. "/reaper/Scripts/golem_chordseq.lua"
    if reaper.file_exists(chordseq) then
      golem_load(chordseq)
    end
    -- preview : guide sonore (re-amp DI de réf -> render stem par scène) -> presets/.preview.json
    local preview = root .. "/reaper/Scripts/golem_preview.lua"
    if reaper.file_exists(preview) then
      golem_load(preview)
    end
    -- horloge MIDI : tick 24 PPQN free-running au tempo projet -> arpegiateur AKAI (presets/.clock.log)
    local clock = root .. "/reaper/Scripts/golem_clock.lua"
    if reaper.file_exists(clock) then
      golem_load(clock)
    end
    -- potards AKAI : boucle de poll gmem golem_knobs (knob-tap) -> params keys (presets/.knobmap.json)
    local knobs = root .. "/reaper/Scripts/golem_knobs.lua"
    if reaper.file_exists(knobs) then
      golem_load(knobs)
    end
    -- drumlearn : piste d'écoute à la demande de Calibration ▸ Drums (drum-tap.jsfx) -> /dev/shm/golem-drumlearn.json
    local drumlearn = root .. "/reaper/Scripts/golem_drumlearn.lua"
    if reaper.file_exists(drumlearn) then
      golem_load(drumlearn)
    end
    -- devices MIDI : sentinelle de la doctrine gear-registry (Reaper tient EXACTEMENT l'AKAI,
    -- JAMAIS le MIDI de la carte son qui appartient au bridge) -> presets/.midi.json + .midi.log
    local midi = root .. "/reaper/Scripts/golem_midi.lua"
    if reaper.file_exists(midi) then
      golem_load(midi)
    end
  end
end
