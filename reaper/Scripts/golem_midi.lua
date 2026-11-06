-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — MIDI devices (sentinelle de la doctrine gear-registry)
  Boucle defer PERMANENTE (lancée par __startup, comme golem_tuner/clock/knobs).

  ── Le contrat (docs/gear-registry.md) ──
  Le MIDI de la CARTE SON (Volt 276, ALSA « hw:V276 ») appartient au BRIDGE : entrée = lecteur FCB
  (aseqdump), sortie = Whammy DT (rtmidi/amidi). Reaper ne doit JAMAIS l'ouvrir — le rawmidi ALSA est
  EXCLUSIF : si Reaper le tient, la Whammy est muette (« ALSA error making port connection »).
  Reaper doit tenir EXACTEMENT le contrôleur Keys : entrée = lane Keys/Vital
  (golem_rig keys_midi_dev), sortie = horloge MIDI (golem_clock -> arpégiateur).
  QUEL contrôleur n'est plus codé en dur (l'AKAI historique) : les motifs de nom viennent de
  presets/.keys-midi.json, publié par provision/reaper-ini-setup.py depuis la config (binding
  soundcard.json + profils de calibration) — repli mpk|akai si absent (cf. KEYS_PATTERNS).

  ── Le piège (chassé le 2026-07-26) ──
  L'activation d'un device MIDI vit dans un BITMASK de reaper.ini (midiins/midiouts...) indexé par
  l'INDEX DE DEVICE REAPER. Cet index n'est PAS l'ordre `amidi -l` : Reaper PERSISTE sa liste dans
  ~/.config/REAPER/reaper-midihw-alsa.ini [mididevcache] (in0=virtual, in1=hw:V276, in2=hw:II...),
  dans l'ordre de PREMIÈRE RENCONTRE, et n'en retire jamais un device débranché. Après la valse USB
  (iTwo adoptée puis retour Volt), le bit « AKAI » calculé par provision/reaper-ini-setup.py depuis
  `amidi -l` (AKAI = carte 1 -> position 1) est tombé sur l'index 1 = hw:V276 : Reaper a ouvert la
  SORTIE de la Volt (Whammy muette) et n'a jamais ouvert l'AKAI (lane Keys + horloge mortes).

  ── Le piège du 2026-09-11 (le même, vu d'en face) ──
  Un contrôleur DÉBRANCHÉ n'est plus nommable (« hw:II » seul, plus rien à matcher) : la
  sentinelle criait « no Keys-controller MIDI device seen by Reaper » — la même phrase que pour
  un rack sans config, alors que le geste est un CÂBLE. presets/.keys-midi.json porte désormais
  la MÉMOIRE du device (publiée par reaper-ini-setup.py) : on retrouve son slot, et on dit
  « UNPLUGGED » plutôt qu'une panne. Corollaire : Reaper n'ouvre ses devices MIDI qu'au
  DÉMARRAGE — un clavier branché après coup reste fermé, masque pourtant bon ; d'où le
  midi_reinit SEUL (aucun masque touché, 3 essais bornés) ci-dessous.

  ── Ce que cette boucle peut / ne peut pas (MESURÉ, pas supposé) ──
  Un masque MIDI n'est PAS modifiable à chaud sur ce rig, SWS installé ou non :
    · sans SWS : aucune API. get_config_var_string existe mais ne sert QUE les vars STRING —
      il renvoie false sur midiins/midiouts.
    · avec SWS v2.14.0.7 : SNM_GetIntConfigVar("midiins", -1) renvoie -1, c.-à-d. le défaut qu'on
      lui passe (SWS ne connaît pas ce nom de var), et SNM_SetIntConfigVar + midi_reinit() n'a
      AUCUN effet réel — prouvé au banc d'essai (cf. verdict détaillé plus bas, § apply_masks).
  Cette boucle ne prétend donc pas réparer : elle MESURE la vérité terrain
  (/proc/asound/card*/midi0 : qui tient quoi ; Reaper = /proc/self depuis un ReaScript) et publie
  un diagnostic exploitable dans presets/.midi.json + .midi.log. Le chemin de guérison CERTAIN :
      provision/reaper-ini-setup.py (Reaper FERMÉ) puis relance — c'est ce que fait
      POST /api/system/reaper-restart (pkill -> attente de la mort -> start.sh -> ini -> Reaper).
  Le banc d'essai (ExtState golem/midi_force = "<ins>,<outs>") reste câblé pour re-trancher en 30 s
  si une future version de SWS servait ces vars ; l'auto-réparation se réarme par
  ExtState golem/midi_autoheal = "1".

  Aucun effet de bord audio : lecture de /proc + un fichier d'état. Rechargeable à chaud
  (action « reload » de golem_apply, liste blanche golem_midi).
]]--

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT  = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local STATE = ROOT .. "/presets/.midi.json"
local LOGP  = ROOT .. "/presets/.midi.log"
local PERIOD = 5.0                       -- re-mesure (branchement à chaud) ; publie sur CHANGEMENT

local function log(s)
  local f = io.open(LOGP, "a")
  if f then f:write(os.date("%H:%M:%S ") .. tostring(s) .. "\n"); f:close() end
end

-- LINUX SEULEMENT : la vérité terrain de cette sentinelle est ALSA (/proc/asound, /proc/self). Sous macOS et
-- Windows rien de cela n'existe — elle tournait quand même et écrivait « contrôleur Keys in#nil/out#nil (carte nil)
-- tenu par Reaper » (premier Mac réel, 2026-11-04). Hors Linux, REAPER ouvre ses ports par reaper.ini (desktop_midi.py).
local _os = reaper.GetOS()
if _os:find("Win", 1, true) or _os:find("OSX", 1, true) or _os:find("macOS", 1, true) then
  log("non lancée : " .. _os .. " n'a pas /proc/asound — les ports MIDI suivent reaper.ini")
  return
end

local function jstr(s)
  return '"' .. tostring(s or ""):gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', ' ') .. '"'
end
local function slurp(p)
  local f = io.open(p, "r"); if not f then return nil end
  local s = f:read("*a"); f:close(); return s
end

-- ── qui suis-je ? /proc/self DANS le process Reaper = le PID de Reaper ────────────────────
local function reaper_pid()
  local s = slurp("/proc/self/stat")
  return s and tonumber(s:match("^(%d+)")) or nil
end

-- ── cartes ALSA : id court (« II ») -> {num, longname} ────────────────────────────────────
-- /proc/asound/cards, les DEUX lignes :  " 1 [II             ]: USB-Audio - MPK Mini Mk II"
--                                        "                     AKAI MPK Mini Mk II at usb-…"
-- ⚠ la 2e ligne porte le nom CONSTRUCTEUR — celui que la calibration enregistre comme `name`
-- du profil (bridge/controllers.py) : sans elle, un profil calibré ne matcherait JAMAIS.
local function alsa_cards()
  local by_id, last = {}, nil
  local txt = slurp("/proc/asound/cards") or ""
  for line in txt:gmatch("[^\n]+") do
    local num, id, rest = line:match("^%s*(%d+)%s*%[([^%]]-)%s*%]%s*:%s*(.-)%s*$")
    if num then
      by_id[id] = { num = tonumber(num), name = rest or "" }
      last = id
    elseif last then
      local desc = line:match("^%s*(.-)%s+at%s") or line:match("^%s*(.-)%s*$")   -- le chemin USB est du bruit
      if desc and #desc > 0 then by_id[last].name = by_id[last].name .. " " .. desc end
      last = nil
    end
  end
  return by_id
end

-- ── un nom de device Reaper (« hw:II ») -> texte enrichi du nom de carte ALSA ──────────────
-- Reaper (ALSA raw) nomme ses devices « hw:<id de carte> » : AUCUN « MPK »/« akai » dedans.
-- C'est ce qui a fait échouer le 1er correctif (match sur le seul nom Reaper).
local function enrich(name, cards)
  local id = tostring(name or ""):match("^hw:(.+)$")
  local c = id and cards[id]
  if c then return name .. " " .. c.name, c.num end
  return name, nil
end

-- Le contrôleur Keys n'est plus codé en dur sur l'AKAI (audit 2026-08-12 §3, chantier ②) :
-- provision/reaper-ini-setup.py publie les noms déclarés en config (binding soundcard.json +
-- profils de calibration) dans presets/.keys-midi.json — un fichier PLAT que ce Lua sait lire.
-- REPLI si absent/illisible : l'ancien motif mpk|akai (rack jamais calibré = l'AKAI d'origine,
-- qui ne doit JAMAIS régresser). Lu UNE fois au chargement, comme SOUNDCARD_ID : le script est
-- relancé à chaque démarrage de Reaper, juste après que start.sh a rafraîchi le sidecar.
local KEYS_PATTERNS = (function()
  local txt = slurp(ROOT .. "/presets/.keys-midi.json") or ""
  local arr = txt:match('"patterns"%s*:%s*%[(.-)%]')
  local pats = {}
  if arr then
    for s in arr:gmatch('"(.-)"') do if #s > 0 then pats[#pats + 1] = s:lower() end end
  end
  if #pats == 0 then pats = { "mpk", "akai" } end
  return pats
end)()
-- UN CLAVIER EST-IL ATTENDU ? Oui si la config en déclare un (le sidecar porte des motifs : un binding Soundcard ou un
-- profil calibré). Sur le repli mpk|akai, personne n'a rien déclaré : un golem sans clavier n'a rien à signaler — Health
-- disait « no Keys-controller MIDI-IN device seen » sur un golem neuf avec une batterie et sans clavier (2026-10-22).
-- Le lanceur écrit le sidecar MÊME en repli (motifs mpk|akai, source « repli … ») : c'est sa `source` qui le dit.
local KEYS_DECLARED = (function()
  local src = (slurp(ROOT .. "/presets/.keys-midi.json") or ""):match('"source"%s*:%s*"(.-)"') or ""
  return src:sub(1, 6) == "config"
end)()
-- Mémoire des devices, publiée par provision/reaper-ini-setup.py (cf. keys_memory() côté Python).
-- Un contrôleur DÉBRANCHÉ n'est plus NOMMABLE : Reaper n'a plus que « hw:II » et
-- /proc/asound/cards ne l'enrichit plus — plus rien à matcher. Son index de cache Reaper, lui,
-- ne bouge jamais. Sert ici à DIRE LA VÉRITÉ : « débranché » (rebranche-le) n'est pas
-- « jamais vu » (rien n'est configuré), et les deux n'appellent pas le même geste.
local KEYS_DEVICES = (function()
  local txt = slurp(ROOT .. "/presets/.keys-midi.json") or ""
  local d = txt:match('"devices"%s*:%s*{(.-)}') or ""
  return { ["in"] = d:match('"in"%s*:%s*"(.-)"'), ["out"] = d:match('"out"%s*:%s*"(.-)"') }
end)()

local function is_keys(txt) txt = tostring(txt):lower()
  for _, p in ipairs(KEYS_PATTERNS) do
    if txt:find(p, 1, true) ~= nil then return true end
  end
  return false end

-- La CARTE SON n'est pas codée en dur (doctrine gear-registry : la carte se change) : on lit le
-- device actif dans config/io.json (« hw:V276 ») et on compare l'id ALSA. Repli = heuristique nom.
local SOUNDCARD_ID = (function()
  local txt = slurp(ROOT .. "/config/io.json") or ""
  local dev = txt:match('"device"%s*:%s*"hw:([^"]+)"')
  return dev and dev:lower() or nil
end)()
local function is_soundcard(name, txt)
  local id = tostring(name or ""):match("^hw:(.+)$")
  if SOUNDCARD_ID and id and id:lower() == SOUNDCARD_ID then return true end
  txt = tostring(txt or name):lower()
  return txt:find("volt", 1, true) ~= nil or txt:find("v276", 1, true) ~= nil
end

-- ── index de device Reaper du contrôleur Keys, PAR NOM (in et out séparés — ils peuvent différer) ──
-- ⚠ on énumère jusqu'à 127 et on garde AUSSI les devices absents (retval false) : un device
-- débranché conserve son index dans le cache, ne pas le sauter (sinon décalage).
local function resolve(cards)
  local r = { in_idx = nil, in_name = nil, in_card = nil, out_idx = nil, out_name = nil, out_card = nil,
              volt_in = nil, volt_out = nil, list = {} }
  local raw = { ["in"] = {}, ["out"] = {} }        -- index -> nom BRUT (« hw:II »), pour la mémoire
  for i = 0, 127 do
    local oki, nmi = reaper.GetMIDIInputName(i, "")
    if nmi and nmi ~= "" then
      local rich, card = enrich(nmi, cards)
      r.list[#r.list + 1] = string.format('{"dir":"in","i":%d,"name":%s,"present":%s}', i, jstr(rich), tostring(oki and true or false))
      raw["in"][i] = nmi
      if not r.in_idx and is_keys(rich) then r.in_idx, r.in_name, r.in_card = i, rich, card end
      if not r.volt_in and is_soundcard(nmi, rich) then r.volt_in = i end
    end
    local oko, nmo = reaper.GetMIDIOutputName(i, "")
    if nmo and nmo ~= "" then
      local rich, card = enrich(nmo, cards)
      r.list[#r.list + 1] = string.format('{"dir":"out","i":%d,"name":%s,"present":%s}', i, jstr(rich), tostring(oko and true or false))
      raw["out"][i] = nmo
      if not r.out_idx and is_keys(rich) then r.out_idx, r.out_name, r.out_card = i, rich, card end
      if not r.volt_out and is_soundcard(nmo, rich) then r.volt_out = i end
    end
  end
  -- repli MÉMOIRE : le contrôleur est DÉBRANCHÉ (rien à matcher). On retrouve son slot par le nom
  -- mémorisé ; `gone` dit que le device EXISTE dans Reaper mais n'est plus sur le bus. Pas de
  -- `*_card` : sans carte ALSA, il n'y a pas d'owner à interroger — donc aucune fausse anomalie.
  for _, dir in ipairs({ "in", "out" }) do
    local want = KEYS_DEVICES[dir]
    if not r[dir .. "_idx"] and want and want ~= "" then
      for i, nm in pairs(raw[dir]) do
        if nm == want and not is_soundcard(nm, nm) then      -- la carte son n'est JAMAIS le clavier
          r[dir .. "_idx"], r[dir .. "_name"], r[dir .. "_gone"] = i, nm, true
          break
        end
      end
    end
  end
  return r
end

-- ── vérité terrain : /proc/asound/card<n>/midi0 -> {in_owner=pid|nil, out_owner=pid|nil} ───
-- (« Owner PID » n'apparaît QUE tant que le port rawmidi est ouvert : c'est l'exclusivité ALSA.)
local function rawmidi_owners(cardnum)
  if not cardnum then return {} end
  local txt = slurp(string.format("/proc/asound/card%d/midi0", cardnum))
  if not txt then return {} end
  local res, sect = {}, nil
  for line in txt:gmatch("[^\n]+") do
    if line:match("^Output") then sect = "out"
    elseif line:match("^Input") then sect = "in"
    else
      local pid = line:match("^%s*Owner PID%s*:%s*(%d+)")
      if pid and sect then res[sect .. "_owner"] = tonumber(pid) end
      local tx = line:match("^%s*Tx bytes%s*:%s*(%d+)")
      if tx then res.tx = tonumber(tx) end
      local rx = line:match("^%s*Rx bytes%s*:%s*(%d+)")
      if rx then res.rx = tonumber(rx) end
    end
  end
  return res
end

-- ── réparation à chaud (SWS requis) ──────────────────────────────────────────────────────
-- ⚠ MESURÉ 2026-07-26, SWS v2.14.0.7 : SNM_GetIntConfigVar("midiins", -1) renvoie -1, c.-à-d. la
-- VALEUR PAR DÉFAUT qu'on lui passe : SWS ne connaît PAS ces noms de vars (sa table de config vars
-- est curatée). Conséquence directe : la RELECTURE d'un masque ne vaut RIEN comme critère — s'en
-- servir pour décider « faut-il réparer ? » déclenchait un midi_reinit toutes les 5 s (constaté :
-- 8 réparations en 40 s, l'horloge AKAI ré-initialisée en boucle).
-- Donc, règle de la maison : le SEUL critère de réparation est la VÉRITÉ TERRAIN (les owners
-- /proc/asound/card*/midi0, cf. issues[]), et le SEUL juge du succès est cette même vérité au tick
-- suivant. On ne relit jamais un masque.
--
-- ⛔ VERDICT DU BANC D'ESSAI (2026-07-26, SWS v2.14.0.7) : SNM_SetIntConfigVar sur ces masques
-- est SANS EFFET RÉEL. Protocole : masque de sortie forcé à 0 (midiins=4, midiouts=0) +
-- midi_reinit(), puis échantillonnage de /proc/asound/card1/midi0 chaque seconde pendant 30 s.
-- Résultat : la sortie AKAI est restée OUVERTE et détenue par Reaper, et l'horloge a continué à
-- émettre sans un octet de retard (Tx +48 o/s, continu, aucun trou au moment du reinit).
-- SWS ne connaît tout simplement pas ces noms de vars (Get renvoie le défaut de l'appelant).
-- => l'auto-réparation est donc DÉSARMÉE PAR DÉFAUT : on n'expédie pas un remède mesuré inopérant.
-- Le seul chemin de guérison CERTAIN reste : provision/reaper-ini-setup.py (Reaper fermé) puis
-- relance — POST /api/system/reaper-restart. Le banc d'essai (ExtState golem/midi_force) et
-- apply_masks() restent en place pour re-tester en 30 s si une version de SWS gagne ces vars ;
-- réarmement : ExtState golem/midi_autoheal = "1".

-- Un masque est-il SÛR ? (ne doit JAMAIS activer un device de la carte son : son MIDI appartient au
-- bridge — FCB en entrée, Whammy en sortie). Garde-fou de la doctrine, y compris pour le canal de
-- forçage manuel ci-dessous.
local function mask_is_safe(mask, dir, cards)
  for i = 0, 31 do
    if (mask & (1 << i)) ~= 0 then
      local nm = dir == "in" and select(2, reaper.GetMIDIInputName(i, ""))
                             or select(2, reaper.GetMIDIOutputName(i, ""))
      local rich = enrich(nm or "", cards)
      if is_soundcard(nm or "", rich) then return false, i, rich end
    end
  end
  return true
end

-- Pose les masques + midi_reinit. Retourne (true, texte) ou (false, raison). AUCUNE relecture.
local function apply_masks(want_i, want_o, cards, why)
  if not reaper.SNM_SetIntConfigVar then return false, "SWS absent" end
  local ok_i, bad_i, nm_i = mask_is_safe(want_i, "in", cards)
  if not ok_i then return false, string.format("REFUS : le masque IN activerait #%d (%s) = carte son", bad_i, nm_i) end
  local ok_o, bad_o, nm_o = mask_is_safe(want_o, "out", cards)
  if not ok_o then return false, string.format("REFUS : le masque OUT activerait #%d (%s) = carte son", bad_o, nm_o) end
  reaper.SNM_SetIntConfigVar("midiins", want_i)
  reaper.SNM_SetIntConfigVar("midiins_cs", 0)          -- un clavier ne pilote JAMAIS d'actions Reaper
  reaper.SNM_SetIntConfigVar("midiins_nowarn", want_i) -- boot kiosk : aucune modale si débranché
  reaper.SNM_SetIntConfigVar("midiouts", want_o)
  reaper.SNM_SetIntConfigVar("midiouts_nowarn", want_o)
  if reaper.midi_reinit then reaper.midi_reinit() end
  return true, string.format("masques posés (%s) : midiins=%d, midiouts=%d (+ midi_reinit)", why, want_i, want_o)
end

-- ── état runtime ──
local PID = reaper_pid()
local last_body, next_at = nil, 0
local HEAL_COOLDOWN = 60.0        -- ≥ 60 s entre deux tentatives : midi_reinit n'est pas gratuit
local heal_last, heal_pending, heal_tries = -1e9, nil, 0
local RESCAN_COOLDOWN, RESCAN_MAX = 20.0, 3   -- re-scan d'un device branché à chaud (borné)
local rescan_last, rescan_tries = -1e9, 0

local function measure()
  local cards = alsa_cards()
  local res   = resolve(cards)

  local akai = rawmidi_owners(res.in_card or res.out_card)
  res.in_owner, res.out_owner = akai.in_owner, akai.out_owner   -- exposés pour le log du banc d'essai
  local volt_card
  do  -- carte son : on prend la carte du 1er device « volt/v276 » vu par Reaper, sinon /proc
    local nm = res.volt_out ~= nil and select(2, reaper.GetMIDIOutputName(res.volt_out, "")) or nil
    local _, c = enrich(nm or "", cards)
    volt_card = c
    if not volt_card then for id, c2 in pairs(cards) do if is_soundcard("hw:" .. id, id .. " " .. c2.name) then volt_card = c2.num end end end
  end
  local volt = rawmidi_owners(volt_card)

  -- ⚠ chaînes AFFICHÉES (title de la puce « NO MIDI » sur /live) -> ANGLAIS, règle 4
  local issues = {}
  -- DÉBRANCHÉ ≠ JAMAIS VU. Le premier se répare avec un câble, le second avec une config : les
  -- confondre envoyait le mainteneur relancer Reaper alors que son clavier n'était pas au bout du fil.
  local gone = res.in_gone or res.out_gone
  if gone then
    issues[#issues + 1] = "Keys controller UNPLUGGED (" .. tostring(res.in_name or res.out_name)
      .. ") — plug it back in, Reaper keeps its MIDI slot"
  end
  if not res.in_idx and (KEYS_DECLARED or gone) then issues[#issues + 1] = "no Keys-controller MIDI-IN device seen by Reaper" end
  if not res.out_idx and (KEYS_DECLARED or gone) then issues[#issues + 1] = "no Keys-controller MIDI-OUT device seen by Reaper" end
  if volt.out_owner and PID and volt.out_owner == PID then
    issues[#issues + 1] = "REAPER HOLDS THE SOUND CARD'S MIDI OUT -> Whammy mute"
  end
  if volt.in_owner and PID and volt.in_owner == PID then
    issues[#issues + 1] = "REAPER HOLDS THE SOUND CARD'S MIDI IN -> pedalboard mute"
  end
  if res.in_card and not akai.in_owner then
    issues[#issues + 1] = "Keys controller input opened by NOBODY -> Keys lane dead (stale midiins mask)"
  end
  if res.out_card and not akai.out_owner then
    issues[#issues + 1] = "Keys controller output opened by NOBODY -> MIDI clock dead (stale midiouts mask)"
  end

  local body = string.format(
    '{"ts":%s,"reaper_pid":%s,"sws":%s,"ok":%s,'
    .. '"akai":{"card":%s,"in_idx":%s,"out_idx":%s,"name":%s,"in_owner":%s,"out_owner":%s,"unplugged":%s},'
    .. '"soundcard":{"card":%s,"in_owner":%s,"out_owner":%s,"tx":%s},'
    .. '"issues":[%s],"fix":%s,"devices":[%s]}',
    jstr(os.date("%Y-%m-%d %H:%M:%S")), tostring(PID or "null"),
    tostring(reaper.SNM_SetIntConfigVar ~= nil), tostring(#issues == 0),
    tostring(res.in_card or "null"), tostring(res.in_idx or "null"), tostring(res.out_idx or "null"),
    jstr(res.in_name or res.out_name or ""), tostring(akai.in_owner or "null"), tostring(akai.out_owner or "null"),
    tostring(gone and true or false),
    tostring(volt_card or "null"), tostring(volt.in_owner or "null"), tostring(volt.out_owner or "null"),
    tostring(volt.tx or "null"),
    (function() local q = {} for _, s in ipairs(issues) do q[#q + 1] = jstr(s) end return table.concat(q, ",") end)(),
    jstr(#issues == 0 and "" or (gone and #issues == 1
      and "plug the Keys controller back in — Reaper keeps its MIDI slot, nothing to restart"
      or "run provision/reaper-ini-setup.py (Reaper closed) then restart — POST /api/system/reaper-restart"
      .. " (hot repair MEASURED INEFFECTIVE: SWS does not serve midiins/midiouts)")),
    table.concat(res.list, ","))
  -- signature = le FOND (sans l'horodatage) : sert à ne logger QUE sur changement d'état
  local sig = string.format("%s|%s|%s|%s|%s|%s|%s", tostring(res.in_idx), tostring(res.out_idx),
    tostring(akai.in_owner), tostring(akai.out_owner), tostring(volt.in_owner), tostring(volt.out_owner),
    tostring(gone))
  return body, issues, res, sig, cards
end

-- ── boucle (GEN : la dernière instance lancée gagne — hot-swap par « reload ») ─────────────
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "midi_gen", GEN, false)

local function tick()
  if reaper.time_precise() < next_at then return end
  local now = reaper.time_precise()
  next_at = now + PERIOD
  local body, issues, res, sig, cards = measure()

  -- ── canal de FORÇAGE (banc d'essai) : ExtState golem/midi_force = "<ins>,<outs>" ──
  -- Posé via l'action dev « extstate » de golem_apply. Sert à PROUVER l'effet réel de
  -- SNM_SetIntConfigVar : on casse volontairement un masque, on regarde les owners bouger,
  -- puis l'auto-réparation ci-dessous recolle. Le garde-fou carte son s'applique aussi ici.
  local force = reaper.GetExtState("golem", "midi_force")
  if force and force ~= "" then
    reaper.DeleteExtState("golem", "midi_force", false)     -- consommé : une seule fois
    local fi, fo = force:match("^%s*(-?%d+)%s*,%s*(-?%d+)%s*$")
    if fi then
      local ok, txt = apply_masks(tonumber(fi), tonumber(fo), cards, "FORÇAGE manuel")
      log((ok and "⚙ " or "⚠ ") .. txt)
      heal_pending = { t = now, issues = #issues, forced = true }
    else
      log("⚠ midi_force illisible (attendu « ins,outs ») : " .. tostring(force))
    end
    return
  end

  -- ── verdict de la tentative précédente : jugé UNIQUEMENT sur les owners ──
  if heal_pending and now - heal_pending.t >= 3.0 then
    if heal_pending.forced then
      -- banc d'essai : on mesure l'EFFET du masque forcé sur les owners (le « succès » d'un
      -- forçage, c'est que la réalité BOUGE — pas qu'elle soit conforme).
      log(string.format("⚙ forçage : anomalies %d -> %d ; AKAI in_owner=%s out_owner=%s",
        heal_pending.issues, #issues, tostring(res.in_owner), tostring(res.out_owner)))
      heal_pending = nil
    elseif heal_pending.rescan then
      if #issues == 0 then
        log(string.format("✓ midi_reinit EFFICACE : le contrôleur branché à chaud est ouvert (%d essai(s))", rescan_tries))
        rescan_tries = 0
      else
        log(string.format("⚠ midi_reinit SANS EFFET (%d/%d) — Reaper n'ouvre ses devices qu'au démarrage ; "
          .. "chemin sûr = POST /api/system/reaper-restart", rescan_tries, RESCAN_MAX))
      end
    elseif #issues == 0 then
      log(string.format("✓ réparation à chaud EFFICACE : les owners sont revenus au contrat (%d essai(s))", heal_tries))
      heal_tries = 0
    else
      log(string.format("⚠ réparation à chaud SANS EFFET sur les owners (%d essai(s)) — chemin sûr = "
        .. "provision/reaper-ini-setup.py + relance Reaper", heal_tries))
    end
    heal_pending = nil
  end

  -- ── BRANCHEMENT À CHAUD : Reaper n'ouvre ses devices MIDI qu'au DÉMARRAGE ────────────────
  -- Le geste quotidien de la maison : on démarre le rig, PUIS on branche le clavier — il reste
  -- fermé alors que le masque est bon (« opened by NOBODY »). On ne touche ici à AUCUN masque
  -- (SNM_SetIntConfigVar est mesuré inopérant) : on demande à Reaper de RE-SCANNER, rien d'autre.
  -- Sûreté : midi_reinit n'ouvre que ce que reaper.ini autorise déjà — si un masque désignait la
  -- carte son, Reaper la tiendrait DÉJÀ. Ce remède n'ajoute aucun risque pour Whammy/pédalier.
  -- Borné à 3 essais : si Reaper ne rescanne pas, on se tait et le fix redevient la relance.
  local ghost = (res.in_card and not res.in_owner) or (res.out_card and not res.out_owner)
  if not ghost then rescan_tries = 0 end
  if ghost and not heal_pending and reaper.midi_reinit and rescan_tries < RESCAN_MAX
     and (now - rescan_last) >= RESCAN_COOLDOWN then
    rescan_last, rescan_tries = now, rescan_tries + 1
    reaper.midi_reinit()
    log(string.format("→ contrôleur Keys présent mais fermé : midi_reinit seul (essai #%d/%d, aucun masque touché)",
      rescan_tries, RESCAN_MAX))
    heal_pending = { t = now, issues = #issues, rescan = true }
  end

  -- ── auto-réparation : SEULEMENT si la vérité terrain dénonce un écart, et avec cooldown ──
  -- (inutile de toucher aux masques si l'AKAI est simplement débranché : rien à ouvrir.)
  local armed = reaper.GetExtState("golem", "midi_autoheal") == "1"   -- désarmé par défaut (cf. verdict)
  local fixable = armed and (res.in_idx ~= nil or res.out_idx ~= nil) and #issues > 0
  if fixable and not heal_pending and reaper.SNM_SetIntConfigVar and (now - heal_last) >= HEAL_COOLDOWN then
    heal_last, heal_tries = now, heal_tries + 1
    local want_i = res.in_idx  and (res.in_idx  <= 31) and (1 << res.in_idx)  or 0
    local want_o = res.out_idx and (res.out_idx <= 31) and (1 << res.out_idx) or 0
    local ok, txt = apply_masks(want_i, want_o, cards, "auto-réparation, essai #" .. heal_tries)
    log((ok and "→ " or "⚠ ") .. txt)
    if ok then heal_pending = { t = now, issues = #issues } end
  end
  -- écriture ATOMIQUE (temp + rename) à CHAQUE mesure : `ts` est la preuve de vie de la sentinelle
  local tmp = STATE .. ".tmp"
  local f = io.open(tmp, "w")
  if f then f:write(body); f:close(); runtime.replace(tmp, STATE) end
  -- le LOG, lui, ne parle que sur CHANGEMENT d'état (sinon 3 lignes toutes les 5 s à vie)
  if sig ~= last_body then
    if #issues == 0 then
      log(string.format("OK — contrôleur Keys in#%s/out#%s (carte %s) tenu par Reaper ; carte son laissée au bridge",
        tostring(res.in_idx), tostring(res.out_idx), tostring(res.in_card)))
    else
      for _, msg in ipairs(issues) do log("⚠ " .. msg) end
    end
    last_body = sig
  end
end

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "midi_gen") ~= GEN then return end   -- remplacée : cette boucle meurt
  reaper.SetExtState("golem", "midi_alive", string.format("%.3f", reaper.time_precise()), false)
  local ok, err = pcall(tick)                                          -- une erreur ne tue JAMAIS la boucle
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else err_streak = 0 end
  reaper.defer(loop)
end

log("démarré (pid Reaper=" .. tostring(PID) .. ", SWS=" .. tostring(reaper.SNM_SetIntConfigVar ~= nil)
  .. ", motifs Keys=[" .. table.concat(KEYS_PATTERNS, ", ") .. "]) -> " .. STATE)
loop()
