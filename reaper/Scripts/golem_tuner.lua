-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — tuner (lecteur d'accordeur)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_watch). Elle :
   1) maintient le JSFX "GoleM Tuner" dans la chaîne d'ENTRÉE (input/rec FX) de
      "Sandbox #Input 1" et l'active/désactive selon l'armement (ProjExtState golem/tuner_on,
      posé par golem_watch à réception de {"action":"tuner","on":bool}) ;
   2) quand armé, lit la hauteur détectée en gmem "golem_tuner" et l'écrit, de façon
      atomique (temp+rename), dans presets/.tuner.json — que le bridge surveille.

  Transport = FICHIER, PAS OSC : Reaper (JSFX comme ReaScript) N'A PAS d'oscsend natif ;
  le fichier est l'idiome GoleM (cf. .command.json / .golem-rig.log).

  ── DÉBIT D'ÉCRITURE (correctif 2026-07-26) ──
  L'ancienne version écrivait .tuner.json à CHAQUE nouvelle analyse du JSFX. La v2 du JSFX
  publie ~11-16 analyses/s : autant de temp+rename par seconde, en continu, tant que
  l'accordeur est armé. L'œil ne lit pas une aiguille plus vite que ~10 Hz et le bridge
  ne relit le fichier qu'à 20 Hz (monitors._poll_tuner) : on plafonne donc à MAX_HZ.
  EXCEPTION : un changement d'état note↔silence passe TOUJOURS tout de suite (l'overlay
  /live doit basculer sur « listening… » sans latence perçue).

  ── GÉNÉRATION (correctif 2026-07-26) ──
  Cette boucle est dans la liste blanche `reload` de golem_apply. Sans garde de génération,
  un dofile ajoutait une DEUXIÈME boucle defer en parallèle de la première (double écriture,
  états qui se battent). Même patron que golem_watch/golem_click/golem_drums : la dernière
  lancée gagne, les précédentes meurent au tick suivant.

  ⚠ À valider AU RIG : (a) résolution du nom du JSFX par TrackFX_AddByName ; (b) indices de
  la chaîne rec-FX (offset 0x1000000) ; (c) seuils de détection avec une vraie guitare.
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
    _LOGF = root .. "/presets/.tuner.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-tuner] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local OUT  = ROOT .. "/presets/.tuner.json"
local DIAG = ROOT .. "/presets/.tuner-diag.json"
-- LOT 2 (audit N lanes 2026-09-08) : la piste écoutée n'est plus « Sandbox #Input 1 » en dur —
-- le bridge dit QUELLE entrée porte le bloc tuner (ExtState golem/tuner_in, défaut 1). Sinon les
-- guitares 2 et 3 ne s'accordent jamais.
local function input_track()
  -- le bridge l'envoie par {"action":"extstate"} -> golem_apply -> SetExtState (GLOBAL). On lisait le
  -- ProjExtState : jamais écrit, l'accordeur restait sur l'entrée 1 quelle que soit la lane (2026-10-15).
  local n = tonumber(reaper.GetExtState("golem", "tuner_in"))
  if not n then
    local _, p = reaper.GetProjExtState(0, "golem", "tuner_in")
    n = tonumber(p) or 1
  end
  return "Sandbox #Input " .. tostring(math.floor(n))
end
local last_track_name = nil
local REC_BASE = 0x1000000                    -- offset des FX de chaîne d'entrée (rec/input FX)
local FX_NAMES = { "GoleM Tuner", "JS: GoleM Tuner", "golem_tuner", "JS: golem_tuner" }
local NOTE = { "C","C#","D","D#","E","F","F#","G","G#","A","A#","B" }
local MAX_HZ = 10                             -- plafond d'écriture de .tuner.json
local MIN_DT = 1.0 / MAX_HZ

reaper.gmem_attach("golem_tuner")

-- garde de génération : relancer ce script REMPLACE la boucle au lieu de la doubler
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "tuner_gen", GEN, false)

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

-- renvoie le handle (index rec-FX, déjà offsetté) du tuner dans la chaîne d'ENTRÉE, ou -1.
local function find_tuner_fx(tr)
  local n = reaper.TrackFX_GetRecCount(tr)
  for i = 0, n - 1 do
    local h = REC_BASE + i
    local _, nm = reaper.TrackFX_GetFXName(tr, h, "")
    if nm and nm:lower():find("tuner", 1, true) and nm:lower():find("golem", 1, true) then return h end
  end
  return -1
end

-- garantit le FX présent dans la chaîne d'entrée ; renvoie le handle ou -1.
local function ensure_tuner_fx(tr)
  local h = find_tuner_fx(tr)
  if h >= 0 then return h end
  for _, nm in ipairs(FX_NAMES) do
    local idx = reaper.TrackFX_AddByName(tr, nm, true, -1)   -- true = chaîne d'entrée (rec FX)
    if idx and idx >= 0 then
      log("JSFX ajouté à la chaîne d'entrée via '" .. nm .. "'")
      local h2 = find_tuner_fx(tr)                            -- re-résout pour un handle offsetté sûr
      if h2 >= 0 then reaper.TrackFX_Show(tr, h2, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
      return h2
    end
  end
  log("⚠ JSFX 'GoleM Tuner' introuvable (link Effects/ fait ? nom à ajuster)")
  return -1
end

-- écriture atomique
local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

-- JSON minimal (assez pour ce payload plat)
local function jnum(x) return string.format("%.4g", x) end
local function build_json(t)
  local parts = {}
  parts[#parts+1] = '"on":' .. (t.on and "true" or "false")
  parts[#parts+1] = '"active":' .. (t.active and "true" or "false")
  parts[#parts+1] = '"seq":' .. tostring(t.seq or 0)
  if t.active then
    parts[#parts+1] = '"note":"' .. t.note .. '"'
    parts[#parts+1] = '"octave":' .. tostring(t.octave)
    parts[#parts+1] = '"midi":' .. tostring(t.midi)
    parts[#parts+1] = '"cents":' .. jnum(t.cents)
    parts[#parts+1] = '"freq":' .. jnum(t.freq)
    parts[#parts+1] = '"conf":' .. jnum(t.conf)
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

local last_on = nil          -- dernier état d'armement appliqué au FX
local last_written_seq = -1  -- dernier heartbeat écrit (dédup)
local last_write_t = 0       -- horodatage de la dernière écriture (plafond MAX_HZ)
local last_active = nil      -- dernier état note/silence écrit (le flip passe hors plafond)
local wrote_off = false      -- a-t-on déjà écrit l'état "off" ?
local last_diag_t = 0

-- ── OUTIL DE DEV : forcer Reaper à RELIRE le .jsfx depuis le disque ──────────────
-- Reaper ne recompile un JSFX qu'à l'INSTANCIATION : éditer le fichier ne change rien pour
-- une instance déjà chargée (contrairement aux .lua, rechargeables par dofile). On supprime
-- donc l'instance ; la boucle la ré-ajoute (donc la recompile) au tick suivant.
-- Armement : reaper.SetExtState("golem","tuner_fxreload","1") — via l'action « extstate ».
local function maybe_reload_jsfx(tr)
  if reaper.GetExtState("golem", "tuner_fxreload") ~= "1" then return false end
  reaper.SetExtState("golem", "tuner_fxreload", "0", false)
  local h = find_tuner_fx(tr)
  if h >= 0 then
    reaper.TrackFX_Delete(tr, h)
    log("instance JSFX supprimée -> sera recompilée depuis le disque au ré-ajout")
  end
  last_on = nil                       -- force la ré-évaluation (ré-ajout + (dés)activation)
  return true
end

local function diag(on)
  if reaper.GetExtState("golem", "tuner_diag") ~= "1" then return end
  local now = reaper.time_precise()
  if now - last_diag_t < 1.0 then return end
  last_diag_t = now
  -- gmem[4..6] = témoins du JSFX (hors contrat 0..3) : horloge audio + charge par bloc.
  -- spl/temps mural = santé du thread audio ; itmax = pic d'itérations sur un @block.
  write_atomic(DIAG, string.format(
    '{"on":%s,"t":%.3f,"spl":%.0f,"it":%.0f,"itmax":%.0f,"seq":%.0f}',
    on and "true" or "false", now,
    reaper.gmem_read(4) or 0, reaper.gmem_read(5) or 0,
    reaper.gmem_read(6) or 0, reaper.gmem_read(3) or 0))
end

local function tick()
  -- ré-attache notre gmem en tête de boucle (contexte __startup partagé : le dernier gmem_attach du
  -- boot gagne, sinon une autre boucle nous vole l'espace — cf. golem_drums pour le détail complet).
  reaper.gmem_attach("golem_tuner")
  local _, v = reaper.GetProjExtState(0, "golem", "tuner_on")
  local on = (v == "1")
  local tname = input_track()
  local tr = find_track(tname)
  -- la lane écoutée a changé pendant que l'accordeur est armé : on désarme l'ancienne piste
  if last_track_name and last_track_name ~= tname then
    local old = find_track(last_track_name)
    if old then
      local h = ensure_tuner_fx(old)
      if h >= 0 then reaper.TrackFX_SetEnabled(old, h, false) end
    end
    last_on = nil                                -- force le ré-armement sur la nouvelle piste
  end
  last_track_name = tname

  if tr then maybe_reload_jsfx(tr) end

  -- (dé)armement du JSFX : n'agit que sur transition
  if tr and on ~= last_on then
    local h = ensure_tuner_fx(tr)
    if h >= 0 then reaper.TrackFX_SetEnabled(tr, h, on) end
    last_on = on
  end

  if on then
    wrote_off = false
    local seq  = reaper.gmem_read(3)
    local conf = reaper.gmem_read(2)
    local active = (conf and conf > 0) or false
    local now = reaper.time_precise()
    -- dédup (une analyse = une écriture au plus) + plafond MAX_HZ ; un flip note<->silence
    -- force l'écriture immédiate. Si on saute un tour, last_written_seq n'est PAS avancé :
    -- le tick suivant publiera la valeur la PLUS FRAÎCHE (rien n'est perdu, juste décimé).
    if seq ~= last_written_seq
       and (active ~= last_active or now - last_write_t >= MIN_DT) then
      last_written_seq, last_write_t, last_active = seq, now, active
      if active then
        local midi = reaper.gmem_read(1)
        local freq = reaper.gmem_read(0)
        local m = math.floor(midi + 0.5)
        local cents = 100 * (midi - m)
        write_atomic(OUT, build_json({
          on = true, active = true, seq = seq,
          note = NOTE[(m % 12) + 1], octave = math.floor(m / 12) - 1,
          midi = m, cents = cents, freq = freq, conf = conf,
        }))
      else
        write_atomic(OUT, build_json({ on = true, active = false, seq = seq }))
      end
    end
  elseif not wrote_off then                  -- une seule écriture à l'extinction
    write_atomic(OUT, build_json({ on = false, active = false, seq = 0 }))
    wrote_off = true
    last_written_seq, last_active = -1, nil
  end
  diag(on)
end

-- pcall blindé (leçon perfrec, audit 2026-08-12) : une erreur d'un tick NE TUE JAMAIS la boucle.
local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "tuner_gen") ~= GEN then
    log("boucle remplacée par une instance plus récente — arrêt de celle-ci")
    return                                                 -- pas de defer : la boucle meurt
  end
  reaper.SetExtState("golem", "tuner_alive", string.format("%.3f", reaper.time_precise()), false)
  local ok, err = pcall(tick)
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

log("démarré. armement=ProjExtState golem/tuner_on ; sortie=" .. OUT .. " (plafond " .. MAX_HZ .. " Hz)")
loop()
