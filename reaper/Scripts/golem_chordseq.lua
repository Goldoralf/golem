-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[
  GoleM — lecteur de STANDARDS (contrat docs/standards.md).

  Boucle defer PERMANENTE (lancée par __startup). Joue la grille d'accords d'un standard :
  le rack tient la section rythmique (accords + walking bass), le musicien joue le thème.

  ── CE QUE CE SCRIPT NE FAIT PAS : DE LA MUSIQUE ──
  Tout le musical (grammaire des symboles, transposition, voicings sans fondamentale,
  conduite des voix, walking bass, patterns de comping) vit dans `bridge/standards.py`,
  en Python, testable sans Reaper — 1382 grilles rendues, 0 symbole illisible. Ici on ne
  fait que TRANSPORTER : lire le fichier de séquence rendu par le bridge, le poser en
  gmem, et laisser golem_chordseq.jsfx l'émettre à l'échantillon près.

  Raison d'être du JSFX : ReaScript ne peut PAS injecter du MIDI dans une instance FX
  précise (StuffMIDIMessage -> bus virtuel GLOBAL). Patron b3-ctl / midi-clock /
  golem_sample_trig / golem_drumseq.

  ── LE FICHIER DE SÉQUENCE (bridge -> ici) ──
  Texte, une ligne par événement — PAS du JSON : un chorus fait déjà ~1500 événements et
  un parseur JSON en Lua les paierait cher à chaque play.
      v 1
      len <ticks>          longueur totale de la grille
      bar <ticks>          longueur d'une mesure
      cin <ticks>          décompte (0 si aucun)
      nev <n>
      <ppq> <note> <vel> <lane>       vel 0 = note-off · lane 0 accords / 1 basse

  ── LES DEUX PISTES ──
  "Standard Keys" : chordseq(lane 0) -> sfizz + Salamander (le piano déjà installé)
  "Standard Bass" : chordseq(lane 1) -> ReaSynth (stock : présent partout, aucun état à
                    charger — un vrai son de contrebasse demanderait une banque qu'on n'a
                    pas, et un synthé honnête vaut mieux qu'un sampler absent).
  Les DEUX instances lisent la MÊME banque gmem et latchent le même nonce dans le même
  cycle audio : elles avancent du même ppq_ps*samplesblock, elles ne peuvent pas dériver.

  État publié : presets/.standard.json (tmp+rename) — lu par le bridge.

  ⚠ NON validable hors-rig : le @block free-running transport à l'arrêt, la réception par
    sfizz/ReaSynth, la cohérence gmem pendant un rechargement en pleine lecture.
]]--

local _LOGF = nil
local function log(s)
  s = "[golem-chordseq] " .. tostring(s)
  if _LOGF then local f = io.open(_LOGF, "a"); if f then f:write(os.date("%H:%M:%S ") .. s .. "\n"); f:close() end end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT = repo_root()
local OUT  = ROOT .. "/presets/.standard.json"
local SEQF = ROOT .. "/presets/.standard.seq"
_LOGF = ROOT .. "/presets/.standard.log"
do local f = io.open(_LOGF, "w"); if f then f:write(os.date("%H:%M:%S ") .. "[golem-chordseq] --- boot ---\n"); f:close() end end

local TRACK_KEYS  = "Standard Keys"
local TRACK_BASS  = "Standard Bass"
-- ⚠ Piste SÉPARÉE de la piste "Drums" du bloc drums : un preset peut porter les deux, et ils
-- se battraient pour la même piste (kit écrasé, notes mêlées). Elles ne se croisent jamais.
local TRACK_DRUMS = "Standard Drums"
-- la pompe manouche (lane 4, docs/standards.md §10) : sa propre piste, jamais la lane guitare
-- du musicien — le guitariste, c'est lui.
local TRACK_GUITAR = "Standard Guitar"

local SEQ_NAMES = { "JS:golem/golem_chordseq", "JS: golem/golem_chordseq",
                    "GoleM chord sequencer (chordseq)", "golem_chordseq" }
-- LV2 d'abord, VST3 ensuite : sfizz_load choisit par fx_type. Sous Windows, REAPER ne lit pas sfizz.lv2 et prend le
-- VST3 ; sous macOS il LIT les LV2 (174 listés sur le premier Mac réel, 2026-11-04) et prendra donc LV2i:sfizz —
-- une voie qui n'a encore jamais joué sur un Mac
local SFIZZ_NAMES = { "LV2i:sfizz (SFZTools)", "LV2i: sfizz (SFZTools)", "LV2i:sfizz",
                      "LV2i: sfizz", "VST3i: sfizz (SFZTools)", "VST3i: sfizz", "sfizz",
                      "http://sfztools.github.io/sfizz" }
local SFIZZ_URI = "http://sfztools.github.io/sfizz:sfzfile"
local SYNTH_NAMES = { "VSTi: ReaSynth (Cockos)", "VST3i: ReaSynth (Cockos)", "ReaSynth" }
-- Kit de la section rythmique : UN plugin LV2 = un kit acoustique complet (notes General
-- MIDI). On ne reprend PAS la machinerie de kits du bloc drums (RS5k, DrumGizmo multi-micros,
-- SFZ — ~200 lignes) : le groove d'un standard ne varie pas, il n'a besoin ni de fills ni de
-- micros séparés. La boîte à rythmes garde ce métier, entier.
-- Noms EXACTS confirmés par lv2info (miroir de golem_drums.AVL_NAMES).
local AVL_NAMES = {
  ["black-pearl"]  = { "LV2i:Black Pearl Drumkit (Robin Gareus)", "LV2i: Black Pearl Drumkit (Robin Gareus)",
                       "LV2i:Black Pearl Drumkit", "http://gareus.org/oss/lv2/avldrums#BlackPearl" },
  ["red-zeppelin"] = { "LV2i:Red Zeppelin Drumkit (Robin Gareus)", "LV2i: Red Zeppelin Drumkit (Robin Gareus)",
                       "LV2i:Red Zeppelin Drumkit", "http://gareus.org/oss/lv2/avldrums#RedZeppelin" },
  ["blonde-bop"]   = { "LV2i:Blonde Bop Drumkit (Robin Gareus)", "LV2i: Blonde Bop Drumkit (Robin Gareus)",
                       "LV2i:Blonde Bop Drumkit", "http://gareus.org/oss/lv2/avldrums#BlondeBop" },
}
local cur_kit = nil                       -- banque montée sur la piste (évite de rebâtir)
local FX_OPEN = { VST = true, AU = true, JS = true, LV2 = true, DX = true, CLAP = true }

-- ── arpégiateur : LE GESTE DE L'AKAI, et il est déjà codé ──────────────────────
-- motion=arp -> le chordseq TIENT l'accord (note-on sans note-off tant qu'il ne change pas)
-- et le JSFX stock `midi_arp` le déroule. Exactement ce qu'on fait sur l'AKAI : on plaque,
-- l'arp déroule. Zéro DSP nouveau. Configs RECOPIÉES de golem_rig.ARP_CONFIGS (même table,
-- même discriminant « Rate (x BPM) ») pour qu'un réglage veuille dire la même chose partout.
local ARP_NAMES = { "JS:midi/midi_arp", "JS: MIDI Arpeggiator", "midi/midi_arp" }
local ARP_CONFIGS = {
  -- ⚠ ORDRE ET DÉFAUTS : la liste allait de la plus RAPIDE à la plus lente, donc la première
  -- chose qu'on essayait était la double-croche — « beaucoup trop vite » (à l'oreille,
  -- 2026-08-03). Elle va maintenant du plus doux au plus rapide. La croche est le geste
  -- naturel d'un arpège d'accompagnement ; la double-croche reste là, mais on la choisit.
  ["Up 1/4"]       = { rate = 1, mode = 1, nvar = 0, v1 = 0 },
  ["Up 1/8"]       = { rate = 2, mode = 1, nvar = 0, v1 = 0 },
  ["Down 1/8"]     = { rate = 2, mode = 0, nvar = 0, v1 = 0 },
  ["Up-Down 1/8"]  = { rate = 2, mode = 3, nvar = 0, v1 = 0 },
  ["Up 1/16"]      = { rate = 4, mode = 1, nvar = 0, v1 = 0 },
  ["Down 1/16"]    = { rate = 4, mode = 0, nvar = 0, v1 = 0 },
  ["Up-Down 1/16"] = { rate = 4, mode = 3, nvar = 0, v1 = 0 },
  ["Up 2 oct"]     = { rate = 2, mode = 1, nvar = 1, v1 = 12 },
}

-- piano déjà installé (library/sfz/) — chemin SANS espace, contrainte du loader sfizz
local PIANO_SFZ = ROOT .. "/library/sfz/SalamanderGrandPiano-SFZ+FLAC-V3+20200602/SalamanderGrandPiano-V3+20200602.sfz"
-- la pompe : Shinyguitar (Karoryfer, CC0, posé par fetch-assets), une archtop prise AU MICRO.
-- On ne charge PAS son main.sfz : il démarre sur le micro magnétique (cc100 = 0) et filtre
-- tout à 1250 Hz. Notre enveloppe ne garde que le programme acoustique à DEUX voix — c'est le
-- doublage du contrat (deux prises différentes, écartées gauche/droite par cc108). Le son validé
-- à l'oreille le 2026-10-17 (le rendu « sec ») était UNE voix ; la seconde est la même banque.
-- Écrite ici, à côté de la banque, pour que les chemins relatifs marchent sur les trois systèmes.
local GUITAR_DIR = ROOT .. "/library/sfz/Shinyguitar"
local GUITAR_SFZ = ROOT .. "/library/sfz/golem-pompe.sfz"
local GUITAR_WRAP = table.concat({
  "// golem — la pompe (golem_chordseq.lua l'écrit ; ne pas éditer à la main)",
  "<control>",
  "default_path=Shinyguitar/Samples/",
  "set_cc100=127", "set_cc107=38", "set_cc108=70",
  "#include \"Shinyguitar/Programs/acoustic_two.sfz\"", "" }, "\n")

-- ── carte gmem "golem_chordseq" (miroir golem_chordseq.jsfx) ──
local G = { NONCE = 0, OP = 1, LOOP = 2, PPQRES = 3, CHANK = 4, CHANB = 5, BANKGEN = 6, ARMED = 7,
            PLAYING = 8, BAR = 9, BEAT = 10, HB = 11, TEMPO = 12,
            PPQ = 13, LATCH = 14, REM = 15, T0 = 21, FIRST = 22,
            NEV = 16, LEN = 17, BARPPQ = 18, LOADED = 19, CIN = 20 }
local EV_BASE, EV_STRIDE, MAX_EV = 64, 5, 16384
local PPQ_RES = 960

reaper.gmem_attach("golem_chordseq")

local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  os.remove(path)
  return os.rename(tmp, path) and true or false
end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

local function find_fx(tr, needle)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if (nm or ""):lower():find(needle, 1, true) then return i end
  end
  return -1
end

local function add_first(tr, names)
  for _, nm in ipairs(names or {}) do
    local fx = reaper.TrackFX_AddByName(tr, nm, false, -1)
    if fx and fx >= 0 then reaper.TrackFX_Show(tr, fx, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
    if fx and fx >= 0 then return fx, nm end
  end
  return -1
end

local function set_param_by_name(tr, fx, needle, val)
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, nm = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if (nm or ""):lower():find(needle, 1, true) then
      reaper.TrackFX_SetParamNormalized(tr, fx, p, val); return true
    end
  end
  return false
end

-- ── loader sfizz (RECOPIE de golem_rig/golem_drums : patch de la ligne P atom:Path) ──
local function chunk_set_sfizf(track, fx, file)
  local ok, chunk = reaper.GetTrackStateChunk(track, "", false)
  if not ok then return false end
  local lines = {}
  for l in (chunk .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
  local idx, start_i, end_i, i = -1, nil, nil, 1
  while i <= #lines do
    local t = lines[i]:gsub("\r", ""):match("^%s*(.-)%s*$")
    local tag = t:match("^<(%w+)")
    if tag and FX_OPEN[tag] then
      idx = idx + 1
      if idx == fx then
        start_i = i
        local depth, j = 1, i + 1
        while j <= #lines do
          local tt = lines[j]:gsub("\r", ""):match("^%s*(.-)%s*$")
          if tt:sub(1, 1) == "<" then depth = depth + 1
          elseif tt == ">" then depth = depth - 1; if depth == 0 then end_i = j; break end end
          j = j + 1
        end
        break
      end
    end
    i = i + 1
  end
  if not (start_i and end_i) then log("  x (sfizz) bloc FX introuvable"); return false end
  local pline = "P " .. SFIZZ_URI .. " " .. file .. " 3"
  local placed = false
  for k = start_i, end_i do
    if lines[k]:gsub("\r", ""):find("sfizz:sfzfile", 1, true) then
      lines[k] = (lines[k]:match("^(%s*)") or "") .. pline; placed = true; break
    end
  end
  if not placed then
    for k = start_i, end_i do
      if lines[k]:gsub("\r", ""):match("^%s*<STATE") then
        table.insert(lines, k + 1, pline); end_i = end_i + 1; placed = true; break
      end
    end
  end
  if not placed then
    table.insert(lines, end_i, "<STATE"); table.insert(lines, end_i + 1, pline)
    table.insert(lines, end_i + 2, ">"); end_i = end_i + 3
  end
  -- DROP du FXID : force la ré-instanciation, donc la relecture de l'état
  for k = start_i, end_i do
    if lines[k]:gsub("\r", ""):match("^%s*FXID") then table.remove(lines, k); break end
  end
  return reaper.SetTrackStateChunk(track, table.concat(lines, "\n"), false)
end

-- base64 (recopie de golem_drums/golem_rig : chaque script garde ses locals)
local B64C = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function b64(data)
  local out, n = {}, #data
  for i = 1, n, 3 do
    local a, b, c = data:byte(i, i + 2)
    local v = a * 65536 + (b or 0) * 256 + (c or 0)
    out[#out + 1] = B64C:sub(math.floor(v / 262144) % 64 + 1, math.floor(v / 262144) % 64 + 1)
                 .. B64C:sub(math.floor(v / 4096) % 64 + 1, math.floor(v / 4096) % 64 + 1)
                 .. (b and B64C:sub(math.floor(v / 64) % 64 + 1, math.floor(v / 64) % 64 + 1) or "=")
                 .. (c and B64C:sub(v % 64 + 1, v % 64 + 1) or "=")
  end
  return table.concat(out)
end
local function unb64(encoded)
  if type(encoded) == "string" then encoded = encoded:gsub("%s+", "") end
  if type(encoded) ~= "string" or #encoded % 4 ~= 0 or encoded:find("[^%w%+/%=]") then return nil end
  local out = {}
  for i = 1, #encoded, 4 do
    local a, b, c, d = encoded:sub(i, i + 3):byte(1, 4)
    local function digit(x)
      if x >= 65 and x <= 90 then return x - 65 end
      if x >= 97 and x <= 122 then return x - 97 + 26 end
      if x >= 48 and x <= 57 then return x - 48 + 52 end
      if x == 43 then return 62 elseif x == 47 then return 63 end
      return nil
    end
    local da, db, dc, dd = digit(a), digit(b), c == 61 and 0 or digit(c), d == 61 and 0 or digit(d)
    if not da or not db or dc == nil or dd == nil then return nil end
    local n = da * 262144 + db * 4096 + dc * 64 + dd
    out[#out + 1] = string.char(math.floor(n / 65536) % 256)
    if c ~= 61 then out[#out + 1] = string.char(math.floor(n / 256) % 256) end
    if d ~= 61 then out[#out + 1] = string.char(n % 256) end
  end
  return table.concat(out)
end

-- ── sfizz en VST3 : le .sfz par l'ÉTAT VST3 (Windows/macOS, mesuré le 2026-10-11) ─────────────────────────
-- Sous Windows, REAPER ne lit pas sfizz.lv2 (avldrums.lv2, même dossier, oui) mais instancie « VST3i: sfizz
-- (SFZTools) » : la ligne P de l'état LV2 (chunk_set_sfizf) ne s'y applique pas, le moteur jouait MUET. Son état
-- VST3 (sfizz-ui SfizzVstState, version 5) : u64 version · str8 sfzFile (i32 longueur NUL inclus + octets) ·
-- f32 volume · i32 voix · i32 oversampling · i32 preload · str8 scala · i32 root · f32 tune · f32 stretch ·
-- 4×i32 qualités · i16 sustainCancelsRelease · i32 lastKeyswitch · u32 ccCount + (u16, f32)… — REAPER l'enveloppe
-- en <taille u32><1 u32><état><8 octets>. On ne touche QUE sfzFile (chemin à / ), le reste est gardé tel quel.
-- Mesuré dans un REAPER de banc : chunk relu à l'identique, puis un rendu de 2 s = 1 s de son, 1 s de silence.
local function sfizz_vst3_set_file(track, fx, file)
  local ok, enc = reaper.TrackFX_GetNamedConfigParm(track, fx, "vst_chunk")
  if not ok or not enc or enc == "" then return false, "vst_chunk illisible" end
  local data = unb64(enc)
  if not data or #data < 16 then return false, "état VST3 tronqué" end
  local size, kind = string.unpack("<I4I4", data)
  if kind ~= 1 or size ~= #data - 16 then return false, "enveloppe VST3 inattendue" end
  local st, tail = data:sub(9, 8 + size), data:sub(9 + size)
  if #st < 13 then return false, "état sfizz trop court" end
  local ver = string.unpack("<I8", st)
  local len = string.unpack("<i4", st, 9)
  if len < 0 or 12 + len > #st then return false, "sfzFile illisible" end
  local p = tostring(file):gsub("\\", "/") .. "\0"
  local body = st:sub(1, 8) .. string.pack("<i4", #p) .. p .. st:sub(13 + len)
  local new = string.pack("<I4I4", #body, kind) .. body .. tail
  local oks = reaper.TrackFX_SetNamedConfigParm(track, fx, "vst_chunk", b64(new))
  return oks and true or false, "v" .. tostring(ver)
end

-- charge un .sfz dans sfizz, quel que soit son format ; rend true si un chargement a été LANCÉ
-- (false = déjà chargé, ou échec — loggé). `force` : recharger même si le chemin est déjà là.
local function sfizz_load(tr, fx, file, force)
  local okt, ft = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_type")
  if okt and ft and ft:find("VST3") then
    local p = tostring(file):gsub("\\", "/")
    local okc, enc = reaper.TrackFX_GetNamedConfigParm(tr, fx, "vst_chunk")
    local cur = okc and enc and unb64(enc) or ""
    if not force and cur:find(p, 1, true) then return false end
    local okv, info = sfizz_vst3_set_file(tr, fx, file)
    if not okv then log("⚠ sfizz VST3 : " .. tostring(info)) end
    return okv
  end
  local ok, chunk = reaper.GetTrackStateChunk(tr, "", false)
  if not force and ok and chunk:find(file, 1, true) then return false end
  return chunk_set_sfizf(tr, fx, file)
end

-- ── les deux pistes de la section rythmique ────────────────────────────────────
local REBUILD = false
local function ensure_seq(tr, lane)
  local fx = find_fx(tr, "chordseq")
  if REBUILD and fx >= 0 then reaper.TrackFX_Delete(tr, fx); fx = -1 end
  if fx < 0 then
    add_first(tr, SEQ_NAMES)
    fx = find_fx(tr, "chordseq")
    if fx < 0 then
      log("⚠ JSFX golem_chordseq introuvable (provision/link-reaper.sh fait ? Reaper relancé ?)")
      return -1
    end
    log("séquenceur golem_chordseq ajouté sur " .. tostring(lane))
  end
  -- il DOIT précéder l'instrument : le MIDI descend la chaîne
  if fx > 0 then
    reaper.TrackFX_CopyToTrack(tr, fx, tr, 0, true)
    fx = find_fx(tr, "chordseq")
  end
  -- valeur BRUTE, pas normalisée : la plage du slider a grandi (0..3 -> 0..4 avec la pompe), et
  -- lane/3 normalisé aurait envoyé le clic sur la lane de la guitare.
  reaper.TrackFX_SetParam(tr, fx, 0, lane)                    -- slider1 lane, plage 0..4
  return fx
end

-- LE TRIM DU MIXER de /live (bridge/mixer.py, source « std-keys »…) sur le send matériel d'une piste NEUVE : golem_rig le
-- repose à chaque matérialisation et mixer_apply à chaud, mais une piste créée au premier play partait à 0 dB jusque-là.
-- Lecture par motif de config/mixer.json ({"levels": {"std-keys": {"db": -6.0, "mute": false}}}) : ce script n'a pas
-- de décodeur JSON, et la forme est celle que mixer._save écrit.
local MIXER_SRC = { ["Standard Keys"] = "std-keys", ["Standard Bass"] = "std-bass",
                    ["Standard Drums"] = "std-drums", ["Standard Guitar"] = "std-guitar" }

local function apply_mixer_trim(tr, name, hw)
  local src = MIXER_SRC[name]
  local f = src and io.open(ROOT .. "/config/mixer.json", "r")
  if not f then return end
  local raw = f:read("*a"); f:close()
  local body = raw:match('"' .. src:gsub("%-", "%%-") .. '"%s*:%s*(%b{})')
  if not body then return end
  local db = tonumber(body:match('"db"%s*:%s*(%-?[%d%.]+)'))
  if db then reaper.SetTrackSendInfo_Value(tr, 1, hw, "D_VOL", db > -60 and 10 ^ (db / 20) or 0) end
  if body:match('"mute"%s*:%s*true') then reaper.SetTrackSendInfo_Value(tr, 1, hw, "B_MUTE", 1) end
  log("trim mixer " .. src .. " posé sur " .. name)
end

local function ensure_track(name, lane, build_instrument)
  local tr = find_track(name)
  if not tr then
    reaper.PreventUIRefresh(1)
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", name, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
    -- sortie hardware OUT 1/2, jamais par le Master (même règle que drums/looper/backing)
    for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
    local hw = reaper.CreateTrackSend(tr, nil)               -- ⚠ l'index est la valeur RETOURNÉE
    reaper.SetTrackSendInfo_Value(tr, 1, hw, "I_DSTCHAN", 0)
    apply_mixer_trim(tr, name, hw)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
    reaper.PreventUIRefresh(-1)
    log("piste créée (permanente) : " .. name .. " -> OUT 1/2")
  end
  reaper.SetMediaTrackInfo_Value(tr, "I_MIDIHWOUT", -1)      -- aucune fuite MIDI hardware
  -- ⚠ ARMER, SINON LE @block NE TOURNE PAS (mesuré le 2026-08-07, bug « le standard ne démarre
  -- plus »). Reaper ne fait vivre que les pistes de son graphe TEMPS RÉEL : une piste sans
  -- entrée, sans item et non armée en sort dès qu'elle se tait (~2 s de queue). Le @block
  -- s'arrête donc, et comme l'ORDRE DE PLAY ARRIVE PAR gmem — un canal que Reaper ne voit pas —
  -- plus rien ne peut la réveiller : verrou définitif. Symptôme : gmem[ST_HB] figé, latch bloqué
  -- à 1, le Lua journalise pourtant chaque « play ». Le monitoring SEUL ne suffit pas (vérifié).
  -- I_RECMODE 2 = « aucun » : armée pour exister, hors d'état d'écrire le moindre fichier.
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
  reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
  ensure_seq(tr, lane)
  build_instrument(tr)
  return tr
end

local function build_piano(tr)
  local fx = find_fx(tr, "sfizz")
  if fx < 0 then
    add_first(tr, SFIZZ_NAMES)
    fx = find_fx(tr, "sfizz")
    if fx < 0 then log("⚠ sfizz introuvable — pas de piano"); return end
  end
  local f = io.open(PIANO_SFZ, "r")
  if not f then log("⚠ Salamander absent : " .. PIANO_SFZ); return end
  f:close()
  -- IDEMPOTENT : un sfizz déjà posé mais SANS banque (échec précédent) doit être rechargé,
  -- pas ignoré. On ne repatche que si le chunk ne porte pas déjà ce chemin.
  if sfizz_load(tr, fx, PIANO_SFZ) then log("piano chargé (Salamander)") end
end

local function build_guitar(tr)
  local fx = find_fx(tr, "sfizz")
  if fx < 0 then
    add_first(tr, SFIZZ_NAMES)
    fx = find_fx(tr, "sfizz")
    if fx < 0 then log("⚠ sfizz introuvable — pas de pompe"); return end
  end
  local d = io.open(GUITAR_DIR .. "/Programs/acoustic_two.sfz", "r")
  if not d then log("⚠ Shinyguitar absent : " .. GUITAR_DIR .. " (provision/fetch-assets.sh)"); return end
  d:close()
  local f = io.open(GUITAR_SFZ, "r")
  local have = f and f:read("*a") or nil
  if f then f:close() end
  -- une enveloppe RÉÉCRITE doit être rechargée : sfizz garde l'ancienne tant qu'on ne le ré-instancie pas
  local rewrote = have ~= GUITAR_WRAP
  if rewrote and not write_atomic(GUITAR_SFZ, GUITAR_WRAP) then
    log("⚠ impossible d'écrire " .. GUITAR_SFZ .. " — pas de pompe"); return
  end
  if not sfizz_load(tr, fx, GUITAR_SFZ, rewrote) then return end
  -- étagement posé au CHARGEMENT seulement (un réglage à la main survit aux play suivants) :
  -- deux voix crêtent à -3,7 dB au rendu hors ligne, le piano vers -9 ; -6 dB la ramène au
  -- niveau de l'accompagnement. Pas encore mesuré au rack.
  reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 0.5)
  log("pompe chargée (Shinyguitar, deux voix)")
end

-- le niveau de la basse dépend de qui l'entoure : sous le piano -10 dB (mesuré) ; avec la pompe seule,
-- -4 dB — la pompe accentue 2 et 4 à +7,5 dB et masquait la contrebasse (à l'oreille, 2026-10-17)
local BASS_VOL_COMBO, BASS_VOL_POMPE = 0.316, 0.631
local bass_vol = BASS_VOL_COMBO

local function build_bass(tr)
  local fx = find_fx(tr, "reasynth")
  if fx < 0 then
    add_first(tr, SYNTH_NAMES)
    fx = find_fx(tr, "reasynth")
    if fx < 0 then log("⚠ ReaSynth introuvable — pas de basse"); return end
  end
  -- IDEMPOTENT (même piège que le piano) : un « return si déjà présent » sautait l'étagement,
  -- et la basse restait au niveau d'usine de ReaSynth, 5 dB AU-DESSUS du piano.
  -- une basse, pas un pad : attaque courte, extinction franche, une octave plus bas
  set_param_by_name(tr, fx, "attack", 0.0)
  set_param_by_name(tr, fx, "decay", 0.25)
  set_param_by_name(tr, fx, "sustain", 0.55)
  set_param_by_name(tr, fx, "release", 0.12)
  set_param_by_name(tr, fx, "square", 0.35)
  -- étagement : mesuré à -6,5 dB crête contre -9 dB pour le piano, la basse écrasait
  -- l'accompagnement. -10 dB la remet DESSOUS, là où une contrebasse s'entend sans couvrir.
  reaper.SetMediaTrackInfo_Value(tr, "D_VOL", bass_vol)
  log(string.format("basse chargée (ReaSynth, %.0f dB)", 20 * math.log(bass_vol, 10)))
end

local function find_param_exact(tr, fx, name)
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, nm = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if nm == name then return p end
  end
  return nil
end

local function find_arp(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    if find_param_exact(tr, i, "Rate (x BPM)") then return i end
  end
  return -1
end

-- `want` = nom de config ARP_CONFIGS, ou nil/"Off" pour bypasser (on ne SUPPRIME pas : un
-- ajout/retrait de FX à chaque play ferait de la chirurgie inutile en pleine lecture).
local function apply_arp(tr, want)
  local cfg = want and ARP_CONFIGS[tostring(want)] or nil
  local arp = find_arp(tr)
  if not cfg then
    if arp >= 0 then reaper.TrackFX_SetEnabled(tr, arp, false) end
    return
  end
  if arp < 0 then
    add_first(tr, ARP_NAMES)
    arp = find_arp(tr)
    if arp < 0 then log("⚠ JSFX midi_arp introuvable — pas d'arpège"); return end
    -- il doit être ENTRE le chordseq et l'instrument : juste après le séquenceur
    local seq = find_fx(tr, "chordseq")
    if seq >= 0 and arp ~= seq + 1 then
      reaper.TrackFX_CopyToTrack(tr, arp, tr, seq + 1, true)
      arp = find_arp(tr)
    end
    log("+ arpégiateur (" .. tostring(want) .. ")")
  end
  reaper.TrackFX_SetEnabled(tr, arp, true)
  local function seta(name, val)
    local pi = find_param_exact(tr, arp, name)
    if pi then reaper.TrackFX_SetParam(tr, arp, pi, val) end
  end
  seta("Rate (x BPM)", cfg.rate)
  -- ⚠ « Velocity » vaut 127 PAR DÉFAUT : l'arpégiateur force la vélocité MAXIMALE et ignore
  -- celle des notes qu'on lui envoie. C'était la cause du « beaucoup trop fort » (le mainteneur, à
  -- l'oreille, 2026-08-03) — et la raison pour laquelle baisser la vélocité à la source ne
  -- changeait rien. 0 = « joue la vélocité reçue », donc c'est nous qui décidons.
  seta("Velocity (0=use played velocity)", 0)
  -- et un arpège qui respire : notes tenues à moitié plutôt que collées bout à bout
  seta("Note Length", 0.5)
  seta("Mode", cfg.mode)
  seta("Note variation", cfg.nvar)
  seta("Variation 1", cfg.v1)
end

local function build_drums(kit)
  return function(tr)
    local want = AVL_NAMES[kit or "black-pearl"] and (kit or "black-pearl") or "black-pearl"
    -- changer de banque = changer de PLUGIN (avldrums n'a pas de sélecteur runtime) :
    -- on ne reconstruit que si la banque demandée diffère de celle qui est montée.
    if cur_kit == want and find_fx(tr, "drumkit") >= 0 then return end
    for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do
      if find_param_exact(tr, i, "Rate (x BPM)") == nil and find_fx(tr, "chordseq") ~= i then
        local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
        if (nm or ""):lower():find("drumkit", 1, true) then reaper.TrackFX_Delete(tr, i) end
      end
    end
    if add_first(tr, AVL_NAMES[want]) < 0 then
      log("⚠ avldrums introuvable — pas de batterie (banque " .. want .. ")")
      return
    end
    cur_kit = want
    log("kit chargé (" .. want .. ")")
  end
end

-- ── la banque : fichier de séquence -> gmem ────────────────────────────────────
local bankgen = 0

local function load_seq(path)
  local f = io.open(path, "r")
  if not f then log("⚠ séquence introuvable : " .. tostring(path)); return nil end
  local body = f:read("*a"); f:close()
  local len = tonumber(body:match("\nlen%s+(%d+)")) or tonumber(body:match("^len%s+(%d+)"))
  local bar = tonumber(body:match("\nbar%s+(%d+)"))
  local cin = tonumber(body:match("\ncin%s+(%d+)")) or 0
  if not (len and bar) then log("⚠ séquence sans en-tête len/bar"); return nil end

  local n, truncated = 0, false
  for a, b, c, d in body:gmatch("\n(%d+) (%d+) (%d+) (%d+)") do
    if n >= MAX_EV then truncated = true; break end
    local ea = EV_BASE + n * EV_STRIDE
    reaper.gmem_write(ea + 0, tonumber(a))
    reaper.gmem_write(ea + 1, tonumber(b))
    reaper.gmem_write(ea + 2, tonumber(c))
    reaper.gmem_write(ea + 3, tonumber(d))
    reaper.gmem_write(ea + 4, 0)
    n = n + 1
  end
  if truncated then log("⚠ séquence TRONQUÉE à " .. MAX_EV .. " événements (grille trop longue)") end
  reaper.gmem_write(G.NEV, n)
  reaper.gmem_write(G.LEN, len)
  reaper.gmem_write(G.BARPPQ, bar)
  reaper.gmem_write(G.CIN, cin)
  reaper.gmem_write(G.LOADED, 1)
  bankgen = bankgen + 1
  reaper.gmem_write(G.BANKGEN, bankgen)
  return { nev = n, len = len, bar = bar, truncated = truncated }
end

-- ── commandes ─────────────────────────────────────────────────────────────────
local nonce = 0
local last_seq_id = nil
local cur = { playing = false, slug = nil, nev = 0, bars = 0 }

-- LE TEMPO D'UNE PRISE DE STANDARD (docs/compo.md §11) : la cible porte son bpm, qui devient le tempo du
-- projet le temps de la prise (grille, clic, delays, arpégiateur), puis le tempo d'avant revient. Seulement s'il
-- est encore celui de la prise : un rappel survenu entre-temps a posé le sien, on ne l'écrase pas.
local held_bpm = nil                      -- { prev = tempo d'avant, take = tempo de la prise }
local function release_bpm()
  if not held_bpm then return end
  if math.abs(reaper.Master_GetTempo() - held_bpm.take) < 0.01 then
    reaper.SetCurrentBPM(0, held_bpm.prev, false)
    log(string.format("tempo projet rendu : %.2f BPM", held_bpm.prev))
  end
  held_bpm = nil
end

local function bump(op, loop_on)
  reaper.gmem_write(G.OP, op)
  reaper.gmem_write(G.LOOP, loop_on and 1 or 0)
  nonce = nonce + 1
  reaper.gmem_write(G.NONCE, nonce)                          -- EN DERNIER : c'est le front
end

local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "standard_cmd")
  if not body or body == "" then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if seq and seq == last_seq_id then return end
  last_seq_id = seq
  local op = body:match('"op"%s*:%s*"([^"]+)"')

  if op == "play" then
    release_bpm()
    local slug = body:match('"standard"%s*:%s*"([^"]*)"')
    local arm = body:find('"arm"%s*:%s*true') ~= nil
    local file = body:match('"file"%s*:%s*"([^"]*)"') or SEQF
    local loop_on = not body:find('"loop"%s*:%s*false')
    local keys  = not body:find('"keys"%s*:%s*false')
    local bass  = not body:find('"bass"%s*:%s*false')
    local drums = body:find('"drums"%s*:%s*true') ~= nil
    local guitar = body:find('"guitar"%s*:%s*true') ~= nil
    REBUILD = body:find('"rebuild"%s*:%s*true') ~= nil
    local info = load_seq(file)
    if not info then bump(0, false); return end
    if keys then
      local trk = ensure_track(TRACK_KEYS, 0, build_piano)
      apply_arp(trk, body:match('"arp"%s*:%s*"([^"]*)"'))
    end
    bass_vol = (guitar and not keys) and BASS_VOL_POMPE or BASS_VOL_COMBO
    if bass then ensure_track(TRACK_BASS, 1, build_bass) end
    if drums then ensure_track(TRACK_DRUMS, 2, build_drums(body:match('"kit"%s*:%s*"([^"]*)"'))) end
    if guitar then ensure_track(TRACK_GUITAR, 4, build_guitar) end
    -- une lane désactivée doit se TAIRE, pas rester sur son dernier accord
    for _, t in ipairs({ { TRACK_KEYS, keys }, { TRACK_BASS, bass }, { TRACK_DRUMS, drums },
                         { TRACK_GUITAR, guitar } }) do
      local tr = find_track(t[1])
      if tr then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", t[2] and 0 or 1) end
    end
    local bpm = tonumber(body:match('"bpm"%s*:%s*([%d%.]+)'))
    if arm and bpm and bpm >= 20 and bpm <= 400 then
      held_bpm = { prev = reaper.Master_GetTempo(), take = bpm }
      reaper.SetCurrentBPM(0, bpm, false)
    end
    -- armé (op 2) : la grille attend le transport de la prise, et partira avec lui
    bump(arm and 2 or 1, loop_on)
    cur = { playing = true, slug = slug, nev = info.nev, bars = math.floor(info.len / info.bar) }
    log(string.format("%s %s — %d événements, %d mesures%s%s", arm and "armée" or "play", tostring(slug),
                      info.nev, cur.bars, loop_on and " (boucle)" or "", held_bpm and (" à " .. held_bpm.take .. " BPM") or ""))
  elseif op == "stop" then
    bump(0, false)
    cur.playing = false
    release_bpm()
    log("stop")
  end
end

-- ── publication d'état ────────────────────────────────────────────────────────
local last_fp = nil
local function publish(force)
  local armed = (reaper.gmem_read(G.ARMED) or 0) >= 0.5
  -- armée, le JSFX se dit « playing » pour faire taire le compteur du click : ici, elle ne joue pas encore
  local playing = not armed and (reaper.gmem_read(G.PLAYING) or 0) >= 0.5
  local bar = math.floor((reaper.gmem_read(G.BAR) or -1) + 0.5)
  local sig = string.format("%s|%s|%s|%d|%d", tostring(cur.slug), tostring(playing), tostring(armed), bar,
    math.floor((reaper.gmem_read(G.HB) or 0) / 60))
  if not force and sig == last_fp then return end
  last_fp = sig
  write_atomic(OUT, string.format(
    '{"present":true,"playing":%s,"armed":%s,"standard":%s,"bar":%d,"bars":%d,"events":%d,"hb":%d,"tempo":%.2f,"beat":%d,"g_nev":%d,"g_len":%d,"g_bar":%d,"g_loaded":%d,"ppq":%d,"latch":%d,"blk":%d,"t0":%.6f,"first":%d}',
    playing and "true" or "false", armed and "true" or "false",
    cur.slug and ('"' .. cur.slug .. '"') or "null", bar, cur.bars, cur.nev,
    math.floor(reaper.gmem_read(G.HB) or 0), reaper.gmem_read(G.TEMPO) or 0,
    math.floor(reaper.gmem_read(G.BEAT) or -1), math.floor(reaper.gmem_read(G.NEV) or 0),
    math.floor(reaper.gmem_read(G.LEN) or 0), math.floor(reaper.gmem_read(G.BARPPQ) or 0),
    math.floor(reaper.gmem_read(G.LOADED) or 0),
    math.floor(reaper.gmem_read(G.PPQ) or -1), math.floor(reaper.gmem_read(G.LATCH) or -1),
    math.floor(reaper.gmem_read(G.REM) or -1), reaper.gmem_read(G.T0) or -1,
    math.floor(reaper.gmem_read(G.FIRST) or -1)))
end

-- ── boucle (garde par génération : la dernière instance lancée gagne) ──────────
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "chordseq_gen", GEN, false)

local function tick()
  -- ⚠ __startup dofile TOUS les scripts dans UN SEUL contexte -> UN SEUL gmem[]. gmem_attach
  -- RE-POINTE ce gmem[] : sans ré-attache en tête de tick, le dernier attach du boot gagne et
  -- cette boucle écrirait dans l'espace d'un autre script (piège vécu avec golem_drums).
  reaper.gmem_attach("golem_chordseq")
  poll_cmd()
  publish(false)
end

-- au boot : ADOPTER la commande résiduelle SANS la rejouer (un standard ne doit pas
-- démarrer tout seul au lancement de Reaper).
do
  local _, body = reaper.GetProjExtState(0, "golem", "standard_cmd")
  last_seq_id = body and body:match('"seq"%s*:%s*(%-?%d+)') or nil
end

reaper.gmem_write(G.PPQRES, PPQ_RES)
reaper.gmem_write(G.CHANK, 0)
reaper.gmem_write(G.CHANB, 1)

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "chordseq_gen") ~= GEN then return end
  reaper.SetExtState("golem", "chordseq_alive", string.format("%.3f", reaper.time_precise()), false)
  local ok, err = pcall(tick)                                -- une erreur de tick NE TUE PAS la boucle
  if not ok then
    err_streak = err_streak + 1
    if err_streak <= 5 or err_streak % 100 == 0 then log("⚠ tick #" .. err_streak .. " : " .. tostring(err)) end
  else
    err_streak = 0
  end
  reaper.defer(loop)
end

publish(true)
log("démarré. pistes=" .. TRACK_KEYS .. " / " .. TRACK_BASS .. " ; sortie=" .. OUT)
loop()
