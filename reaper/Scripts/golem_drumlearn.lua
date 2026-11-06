-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — drumlearn (la piste d'écoute de Calibration ▸ Drums)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_click/knobs). docs/calibration.md,
  addendum du 2026-09-23.

  ── Pourquoi une piste, et pourquoi dans Reaper ──
  Tant que Reaper détient le port rawmidi d'un module, PERSONNE d'autre ne peut l'écouter (aseqdump :
  « Resource temporarily unavailable », mesuré le 2026-09-23). L'apprentissage passe donc par une
  piste de Reaper dont l'entrée est le module, avec drum-tap.jsfx en tête — comme knob-tap sur le
  ROOT de la lane Keys, mais SANS dépendre du preset chargé : la piste « DrumLearn » se crée à la
  demande et se retire à la fin.

  ── Contrôle ──
  golem_watch relaie {"action":"drumlearn",...} en ProjExtState golem/drumlearn_cmd (branche exempte
  de SETTLE : on ne touche qu'à NOTRE piste). Dédup par "seq".
    {"seq":N,"on":true,"dev":"hw:Nitro"}    -> piste + entrée MIDI = le device + JSFX
    {"seq":N,"on":false}                    -> piste retirée
  Le device est le nom EXACT que Reaper donne à l'entrée (GetMIDIInputName), ex. "hw:Nitro" — le
  bridge le résout depuis /proc/asound/cards (vital._hw_of). Aucune heuristique : un module absent
  = « pas d'entrée », dit dans l'état publié (jamais l'AKAI à sa place).

  ── Pièges appliqués (CLAUDE.md) ──
  · piste ARMÉE en I_RECMODE 2 : non armée, elle sort du graphe vivant et le @block s'arrête ;
  · gmem RE-ATTACHÉE à chaque tick : le dernier gmem_attach gagne, sinon on lit l'espace d'un autre ;
  · le tampon est lu par SEQ : la case i = seq % 32 n'est publiée qu'une fois pleine (le JSFX
    incrémente seq en dernier).

  État publié : /dev/shm/golem-drumlearn.json (tmp+rename), lu par GET /api/calibrate/drums/live
    {"on":bool,"dev":"hw:Nitro","seq":N,"clock":N,"events":[{"k":1,"n":36,"v":94,"c":9,"t":..},...]}
  `events` = les 32 derniers, du plus ancien au plus récent ; `k` 1 note-on, 2 CC, 3 aftertouch poly.
]]--

local _LOGF
local function log(s)
  if _LOGF == nil then
    local res = reaper.GetResourcePath()
    local f = io.open(res .. "/golem-root.txt", "r")
    local root = (f and f:read("*l")) or os.getenv("GOLEM_ROOT") or res
    if f then f:close() end
    _LOGF = root .. "/presets/.drumlearn.log"
  end
  local f = io.open(_LOGF, "a")
  if f then f:write(os.date("%H:%M:%S ") .. "[golem-drumlearn] " .. tostring(s) .. "\n"); f:close() end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local root = f:read("*l"); f:close(); if root and root ~= "" then return root end end
  return os.getenv("GOLEM_ROOT") or res
end
local runtime = dofile(repo_root() .. "/reaper/Scripts/golem_paths.lua")
runtime.ensure_runtime_dir()
local TRACK = "DrumLearn"          -- ne matche AUCUN pattern de purge de golem_rig (GoleM:*, Sandbox #Input N)
local GMEM  = "golem_drumlearn"
local RING, BASE, STRIDE = 32, 16, 8
local FX_NAMES = { "JS:golem/drum-tap", "JS: golem/drum-tap", "JS:golem/drum-tap.jsfx",
                   "GoleM drum tap (drum-tap)" }
local FX_KEY = "drum-tap"
-- ── LE CLAVIER AUSSI (2026-10-03) ──
-- Calibration ▸ Controllers passait par le knob-tap du ROOT de la lane Keys : avec un preset SANS lane
-- Keys (un patch guitare), aucune piste n'écoutait le clavier et « Play the LOWEST key » ne voyait
-- rien — sous Windows comme sous Linux. Même remède que les batteries : une piste d'écoute à la
-- demande, « KeysLearn », avec knob-tap (qui publie note/CC/pitch bend vers golem-learn.json via
-- golem_knobs). Une seule écoute à la fois : la commande dit laquelle ("tap":"knob").
local TAPS = {
  drum = { track = "DrumLearn", key = "drum-tap", names = FX_NAMES },
  knob = { track = "KeysLearn", key = "knob-tap",
           names = { "JS:golem/knob-tap", "JS: golem/knob-tap", "JS:golem/knob-tap.jsfx", "GoleM knob tap (knob-tap)" } },
}
-- ── PROGRAMMER UN CONTRÔLEUR (2026-10-13, l'AKAI MPK Mini Mk II) ──
-- Reaper tient l'AKAI en EXCLUSIF (entrée ET sortie) : pour lire/écrire un de ses programmes (SysEx), la piste
-- « SysexIO » a l'AKAI en entrée ET en sortie matérielle, et sysex-io.jsfx relaie les SysEx par gmem golem_sysex.
-- La commande porte "out" (le nom de SORTIE Reaper) ; un envoi = {"tx":"f0 … f7"} sans rebâtir la piste.
TAPS.sysex = { track = "SysexIO", key = "sysex-io",
               names = { "JS:golem/sysex-io", "JS: golem/sysex-io", "JS:golem/sysex-io.jsfx", "GoleM sysex io (sysex-io)" } }
local TAP = "drum"
local function use_tap(name)
  TAP = TAPS[name] and name or "drum"
  local t = TAPS[TAP]
  TRACK, FX_NAMES, FX_KEY = t.track, t.names, t.key
end

local function midi_out_dev(hint)
  if not hint or hint == "" then return nil end
  for i = 0, 127 do
    local ok, name = reaper.GetMIDIOutputName(i, "")
    if ok and name == hint then return i end
  end
  return nil
end

local SX = "golem_sysex"
local function sysex_send(hex)
  local bytes = {}
  for h in hex:gmatch("%x%x") do bytes[#bytes + 1] = tonumber(h, 16) end
  if #bytes < 2 or bytes[1] ~= 0xF0 or bytes[#bytes] ~= 0xF7 or #bytes > 1000 then
    log("⚠ sysex refusé (" .. #bytes .. " octets, pas F0..F7)"); return
  end
  reaper.gmem_attach(SX)
  for i, b in ipairs(bytes) do reaper.gmem_write(1 + i, b) end          -- [2..] = octets
  reaper.gmem_write(1, #bytes)
  reaper.gmem_write(0, (reaper.gmem_read(0) or 0) + 1)                 -- nonce EN DERNIER
  log("sysex envoyé : " .. #bytes .. " octets (" .. hex:sub(1, 23) .. "…)")
end

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

-- l'index Reaper d'une entrée MIDI par son nom EXACT — pas de repli (jamais l'AKAI pour une batterie)
local function midi_dev(hint)
  if not hint or hint == "" then return nil end
  for i = 0, 127 do
    local ok, name = reaper.GetMIDIInputName(i, "")
    if ok and name == hint then return i end
  end
  return nil
end

local function find_fx(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if (nm or ""):lower():find(FX_KEY, 1, true) then return i end
  end
  return -1
end

local function ensure_fx(tr)
  local fx = find_fx(tr)
  if fx < 0 then
    for _, nm in ipairs(FX_NAMES) do
      local r = reaper.TrackFX_AddByName(tr, nm, false, -1)
      if r and r >= 0 then reaper.TrackFX_Show(tr, r, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
      if r and r >= 0 then fx = find_fx(tr); break end
    end
    if fx < 0 then log("⚠ JSFX " .. FX_KEY .. " introuvable (provision/link-reaper.sh fait ? Reaper relancé ?)"); return -1 end
    log("JSFX " .. FX_KEY .. " posé")
  end
  if not reaper.TrackFX_GetEnabled(tr, fx) then reaper.TrackFX_SetEnabled(tr, fx, true) end
  return fx
end

local st = { on = false, dev = nil, dev_idx = nil, err = nil }
local cur_tr = nil

local function start(dev)
  st.err = nil
  local idx = midi_dev(dev)
  if idx == nil then
    st.on, st.dev, st.dev_idx, st.err = false, dev, nil, "MIDI input not found in Reaper: " .. tostring(dev)
    log("⚠ entrée MIDI introuvable : " .. tostring(dev) .. " — pas de piste (Reaper n'ouvre ses devices qu'au démarrage)")
    return
  end
  local tr = find_track(TRACK)
  if not tr then
    reaper.PreventUIRefresh(1)
    local n = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(n, false)
    tr = reaper.GetTrack(0, n)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", TRACK, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)     -- rien ne sort : on écoute, on ne joue pas
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 0)
    reaper.PreventUIRefresh(-1)
    log("piste créée : " .. TRACK)
  end
  reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", 4096 + idx * 32)   -- device MIDI, tous canaux
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)                  -- « aucun » : vivante, jamais un fichier
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
  if TAP == "sysex" then
    local oi = midi_out_dev(st.out)
    reaper.SetMediaTrackInfo_Value(tr, "I_MIDIHWOUT", oi and (oi << 5) or -1)   -- canal 0 = tel quel
    if not oi then st.err = "MIDI output not found in Reaper: " .. tostring(st.out) end
  end
  ensure_fx(tr)
  cur_tr = tr
  st.on, st.dev, st.dev_idx = true, dev, idx
  if TAP ~= "sysex" then st.err = nil end
  log("écoute ON : " .. TRACK .. " <- dev " .. idx .. " (" .. dev .. ")")
end

local function stop(why)
  for _, t in pairs(TAPS) do                            -- les DEUX pistes possibles : une seule écoute à la fois
    local tr = find_track(t.track)
    if tr then
      reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
      reaper.DeleteTrack(tr)
      log("écoute OFF : piste " .. t.track .. " retirée (" .. tostring(why) .. ")")
    end
  end
  cur_tr = nil
  st.on, st.dev_idx = false, nil
end

-- ── publication : seulement quand quelque chose a bougé ──
local last_seq, last_on, last_err, last_sxn = -1, nil, nil, 0
local function publish(force)
  reaper.gmem_attach(GMEM)                              -- à CHAQUE tick : le dernier attach gagne
  local seq = math.floor(reaper.gmem_read(0) or 0)
  local sx = ""
  local sxn = 0
  if st.on and TAP == "sysex" then
    reaper.gmem_attach(SX)
    sxn = math.floor(reaper.gmem_read(1100) or 0)
    local n = math.floor(reaper.gmem_read(1101) or 0)
    local hx = {}
    for i = 0, math.min(n, 1000) - 1 do hx[#hx + 1] = string.format("%02x", math.floor(reaper.gmem_read(1102 + i) or 0)) end
    sx = string.format(',"sysex":{"n":%d,"sent":%d,"hex":"%s"}', sxn, math.floor(reaper.gmem_read(1099) or 0), table.concat(hx))
    reaper.gmem_attach(GMEM)
  end
  if not force and seq == last_seq and st.on == last_on and st.err == last_err and sxn == (last_sxn or 0) then return end
  last_seq, last_on, last_err, last_sxn = seq, st.on, st.err, sxn
  local parts = {}
  if st.on then
    local n = math.min(seq, RING)
    for k = seq - n, seq - 1 do
      local slot = BASE + (k % RING) * STRIDE
      parts[#parts + 1] = string.format('{"k":%d,"n":%d,"v":%d,"c":%d,"t":%.3f}',
        reaper.gmem_read(slot), reaper.gmem_read(slot + 1), reaper.gmem_read(slot + 2),
        reaper.gmem_read(slot + 3), reaper.gmem_read(slot + 4))
    end
  end
  write_atomic(runtime.runtime_file("golem-drumlearn.json"), string.format(
    '{"on":%s,"tap":"%s","dev":%s,"seq":%d,"clock":%d,"ignored":%d,"err":%s,"events":[%s]%s,"t":%.3f}',
    st.on and "true" or "false", TAP, st.dev and ('"' .. st.dev .. '"') or "null", seq,
    math.floor(reaper.gmem_read(1) or 0), math.floor(reaper.gmem_read(2) or 0),
    st.err and ('"' .. st.err:gsub('"', "'") .. '"') or "null",
    table.concat(parts, ","), sx, reaper.time_precise()))
end

-- ── commandes (ProjExtState golem/drumlearn_cmd, posé par golem_watch) ──
local cmd_seq = nil
local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "drumlearn_cmd")
  if not body or body == "" then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if seq == cmd_seq then return end
  cmd_seq = seq
  local tx = body:match('"tx"%s*:%s*"([%x%s]+)"')
  if tx then                                             -- un ENVOI sur la piste SysexIO déjà posée
    if st.on and TAP == "sysex" then sysex_send(tx) else log("⚠ sysex : aucune piste SysexIO") end
    publish(true)
    return
  end
  local on = body:find('"on"%s*:%s*true') ~= nil
  if on then
    local dev = body:match('"dev"%s*:%s*"([^"]*)"')
    stop("switch")                                      -- l'autre écoute, si elle tournait
    use_tap(body:match('"tap"%s*:%s*"(%w+)"') or "drum")
    st.out = body:match('"out"%s*:%s*"([^"]*)"')
    start(dev)
  else
    stop("command")
  end
  publish(true)
end

local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "drumlearn_gen", GEN, false)

local function tick()
  poll_cmd()
  if st.on and cur_tr and not reaper.ValidatePtr2(0, cur_tr, "MediaTrack*") then
    st.on, st.err = false, "listen track vanished (a rebuild ?)"    -- dit, jamais silencieux
    cur_tr = nil
  end
  publish(false)
end

-- au boot : une commande résiduelle n'est PAS rejouée, et une piste d'écoute laissée par une session
-- précédente est retirée — l'écoute ne survit pas à Reaper, elle appartient à l'écran qui l'a demandée
do
  local _, body = reaper.GetProjExtState(0, "golem", "drumlearn_cmd")
  cmd_seq = body and body:match('"seq"%s*:%s*(%-?%d+)') or nil
  stop("boot")
end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "drumlearn_gen") ~= GEN then return end
  reaper.SetExtState("golem", "drumlearn_alive", string.format("%.3f", reaper.time_precise()), false)
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
log("démarré. piste=" .. TRACK .. " (à la demande) ; gmem=" .. GMEM
    .. " ; sortie=" .. runtime.runtime_file("golem-drumlearn.json"))
loop()
