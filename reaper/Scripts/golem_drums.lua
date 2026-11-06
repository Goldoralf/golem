-- SPDX-License-Identifier: GPL-3.0-or-later
-- Copyright (C) 2026 Raphaël Mucchielli, Grégory Beurier and contributors — GoleM (https://golem.fm)
--[[ GoleM — drums (boîte à rythmes au pied, modèle BeatBuddy)
  Boucle defer PERMANENTE (lancée par __startup, après golem_sample). Joue des patterns MIDI de
  batterie EN BOUCLE, synchronisés au TEMPO PROJET, à travers un kit RS5k (samples de batterie).

  ── Architecture (choisie « en connaissance de l'API », cf. golem_drumseq.jsfx) ──
  Piste PERMANENTE « Drums » : créée UNE fois, JAMAIS supprimée (comme Sample/Looper/Recording —
  ne matche AUCUN pattern de purge de golem_rig : sweep_legacy=GoleM:* ; delete_unwanted/
  sandbox_idle=« Sandbox #Input N »). Muette pour le Master (B_MAINSEND=0), sortie hardware
  OUT 1/2 (CreateTrackSend(tr,nil), cat 1, I_DSTCHAN=0) comme le looper/sample.
  Chaîne FX : [0] JSFX golem_drumseq (séquenceur/émetteur) PUIS N ReaSamplOmatic5000 (le kit).

  TEMPO-SYNC : PAS d'item MIDI en boucle (un item n'avance qu'EN LECTURE et se battrait avec le
  backing, qui possède le transport ; le rig est monitoré transport à l'arrêt). Le JSFX golem_drumseq
  fait tourner une tête de lecture PPQ free-running au `tempo` projet (patron midi-clock.jsfx) et
  émet les note-on à l'échantillon près -> boucle batterie indépendante de la timeline de morceau.

  BANQUE DE PATTERNS : ReaScript ne peut pas parser le MIDI dans le JSFX facilement, donc CE script
  parse les .mid (Standard MIDI File) en Lua et remplit la banque gmem « golem_drums » (patron
  gmem golem_super8/looper). Chaque .mid -> un slot { nev, len_ppq (arrondi à la mesure), bar_ppq,
  events=[{ppq,note,vel}] }, résolution interne PPQ_RES=960. patterns[] -> slots 0..P-1 ;
  fills[] -> slots P..P+F-1. On ne charge QUE les note-on (vel>0) : les RS5k du kit sont en oneshot
  (obey note-off OFF) -> chaque frappe sonne jusqu'au bout, les note-off/chokes sont ignorés (v1).

  MOTEURS DE KIT (kit.engine, lu par read_kit dans library/kits/<id>.json) — build_kit aiguille :
    rs5k     : UNE instance RS5k PAR pad, note-filtrée (start==end==note), FILE0=sample (piège pitch :
               "Pitch for start/end note" ≠ 0 st après FILE0 -> forcé 0.5=0 st). Historique/électro.
    sfz      : UN sfizz LV2 chargeant kit.sfz (library/sfz/), velocity+round-robin. Loader chunk_set_sfizf
               recopié de golem_rig (patch atom:Path sfzfile ; chemin SANS espace).
    avldrums : UN avldrums.lv2, kit.bank -> URI LV2 (Black Pearl / Red Zeppelin), batterie acoustique GM.
    drumgizmo: UN drumgizmo.lv2 + le JSFX golem_drummix. Batterie MULTI-MICROS : le plugin sort UN
               MICRO PAR CANAL (16 pour l'Aasimonster) et n'a AUCUN mixeur — la piste passe donc à
               16 canaux le temps de ce moteur, et drummix somme vers 1/2 avec le mix du kit
               (kit.mix[]). Prendre les canaux 1/2 bruts donnerait LES OVERHEADS SEULS, pas la
               batterie. Le kit vit dans l'état LV2 (cf. chunk_set_dgconfig) : aucun paramètre,
               aucune clé SetNamedConfigParm ne le porte.
  MAPPING NOTE = IDENTITÉ dans tous les cas : la note du .mid EST la note GM que l'instrument joue
  (36=kick, 38=snare, 42=hihat…). ⚠ DÉCISION PRODUIT  : suppose kits ET .mid en convention GM.

  Commandes : golem_watch relaie {"action":"drums",...} en ProjExtState golem/drums_cmd (branche
  exempte de SETTLE — on ne touche qu'à NOS propres FX de piste). Dédup par "seq" (bridge/commands.py
  ajoute le nonce). Ops (cf. bridge/drums.py — variation/fill/stop NE renvoient PAS patterns/kit :
  l'état est PERSISTÉ ici depuis le dernier play) :
    play      {seq, block, kit, patterns:[rel.mid], fills:[rel.mid], idx,
               sequence:[{i,times}], seq_mode:"loop"|"once"}  — charge kit+banque ; si sequence
               non vide -> mode SONG (playlist d'étapes {i=index pattern, times, 0=∞}, avance
               auto à la fin de chaque groove, loop|once=silence net) ; sinon démarre idx en boucle
    variation {seq, block, idx}      — bascule patterns[idx] à la prochaine mesure
    fill      {seq, block, fill_idx} — insère fills[fill_idx] une fois puis revient au groove
    stop      {seq, block}           — silence

  MOTEUR SINGULIER : une seule piste Drums, un seul séquenceur -> UN bloc drums joue à la fois.
  Un play d'un autre bloc prend la main (« last play wins », philosophie garde par génération).

  État publié : presets/.drums.json (tmp+rename, heartbeat) — lu par le bridge :
    {"present":true,"blocks":{"<block>":{"playing":bool,"idx":N,"mode":"groove"|"fill"}}}

  ⚠ NON validable hors-rig : @block d'une piste sans entrée transport à l'arrêt (cf. midi-clock),
    réception des note-on par les RS5k, timing gmem, transitions quantifiées à la mesure réelles.
]]--

-- log console + fichier (presets/.drums.log) — la console n'est pas lisible hors-Reaper ; le fichier
-- permet le diagnostic depuis le bridge. Append, tronqué à ~200 lignes au boot (voir plus bas).
local _LOGF = nil
local function log(s)
  s = "[golem-drums] " .. tostring(s)
  if _LOGF then local f = io.open(_LOGF, "a"); if f then f:write(os.date("%H:%M:%S ") .. s .. "\n"); f:close() end end
end

local function repo_root()
  local res = reaper.GetResourcePath()
  local f = io.open(res .. "/golem-root.txt", "r")
  if f then local r = f:read("*l"); f:close(); if r and #r > 0 then return r end end
  return os.getenv("GOLEM_ROOT") or res
end

local ROOT  = repo_root()
local runtime = dofile(ROOT .. "/reaper/Scripts/golem_paths.lua")
local OUT   = ROOT .. "/presets/.drums.json"
local TRACK = "Drums"
_LOGF = ROOT .. "/presets/.drums.log"
do local f = io.open(_LOGF, "w"); if f then f:write(os.date("%H:%M:%S ") .. "[golem-drums] --- boot ---\n"); f:close() end end

-- séquenceur JSFX (link-reaper.sh symlink reaper/Effects -> <resource>/Effects/golem)
local SEQ_NAMES = { "JS:golem/golem_drumseq", "JS: golem/golem_drumseq",
                    "GoleM drum sequencer (drumseq)", "golem_drumseq" }
local RS5K_NAMES = { "ReaSamplOmatic5000", "VSTi: ReaSamplOmatic5000 (Cockos)",
                     "VST: ReaSamplOmatic5000 (Cockos)", "VST3i: ReaSamplOmatic5000" }
-- repli d'index RS5k (réf. golem_rig build_pads_block) si le match par NOM échoue
local RS5K_IDX = { volume = 0, min_vel_gain = 2, note_start = 3, note_end = 4,
                   pitch_start = 5, pitch_end = 6, obey = 11 }

-- ── moteurs alternatifs (kit.engine) ────────────────────────────────────────
-- engine:sfz — 1 sfizz LV2 chargeant un .sfz. Loader recopié de golem_rig (patch atom:Path
-- sfizf via chirurgie de chunk) plutôt que dupliquer le module entier. Chemin sfz SANS espace.
local SFIZZ_NAMES = { "LV2i:sfizz (SFZTools)", "LV2i: sfizz (SFZTools)", "LV2i:sfizz",
                      "LV2i: sfizz", "VST3i: sfizz (SFZTools)", "VST3i: sfizz", "sfizz", "http://sfztools.github.io/sfizz" }
local SFIZZ_URI   = "http://sfztools.github.io/sfizz:sfzfile"

-- base64 (recopie de golem_rig : chaque script garde ses locals)
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
-- engine:avldrums — 1 kit = 1 URI LV2 (pas de bank runtime : on instancie le bon plugin).
-- bank(kit) -> noms candidats AddByName (NOMS EXACTS confirmés après install via lv2info).
-- variantes STÉRÉO (non-Multi = 2 sorties) : collent à la piste Drums stéréo. author=Robin Gareus.
local AVL_NAMES = {
  ["black-pearl"]  = { "LV2i:Black Pearl Drumkit (Robin Gareus)", "LV2i: Black Pearl Drumkit (Robin Gareus)",
                       "LV2i:Black Pearl Drumkit", "http://gareus.org/oss/lv2/avldrums#BlackPearl" },
  ["red-zeppelin"] = { "LV2i:Red Zeppelin Drumkit (Robin Gareus)", "LV2i: Red Zeppelin Drumkit (Robin Gareus)",
                       "LV2i:Red Zeppelin Drumkit", "http://gareus.org/oss/lv2/avldrums#RedZeppelin" },
  ["blonde-bop"]   = { "LV2i:Blonde Bop Drumkit (Robin Gareus)", "LV2i: Blonde Bop Drumkit (Robin Gareus)",
                       "LV2i:Blonde Bop Drumkit", "http://gareus.org/oss/lv2/avldrums#BlondeBop" },
}
-- engine:drumgizmo — 1 drumgizmo.lv2 chargeant un kit MULTI-MICROS (16 sorties, 1 par micro).
-- ⚠ CE PLUGIN N'A NI PARAMÈTRE NI CLÉ SetNamedConfigParm POUR SON KIT (vérifié : fxprobe rend
-- false sur drumkitfile/midimapfile/#config). Le chemin du kit vit UNIQUEMENT dans l'état LV2,
-- sous la forme d'UNE chaîne XML `<config>` portée par la propriété atom#config. Reaper la
-- sérialise dans le chunk de piste en base64 :
--     <STATE
--     <X http://drumgizmo.org/lv2/atom#config http://lv2plug.in/ns/ext/atom#Chunk 3
--     <lignes base64 du XML>
--     >
--     >
-- D'où chunk_set_dgconfig : on fabrique le XML, on l'encode, on remplace le bloc <X, on DROP le
-- FXID (ré-instanciation -> relecture de l'état). Même famille que chunk_set_sfizf, un cran plus bas.
local DG_NAMES  = { "LV2i: DrumGizmo (DrumGizmo Team) (16 out)", "LV2i:DrumGizmo (DrumGizmo Team) (16 out)",
                    "LV2i: DrumGizmo (DrumGizmo Team)", "LV2i:DrumGizmo", "http://drumgizmo.org/lv2" }
local DG_URI    = "http://drumgizmo.org/lv2/atom#config"
local DG_ATOM   = "http://lv2plug.in/ns/ext/atom#Chunk"
local DG_NCH    = 16                 -- sorties du plugin = canaux de la piste pendant ce moteur
local DRUMMIX_NAMES = { "JS:golem/golem_drummix", "JS: golem/golem_drummix",
                        "GoleM drum mixer (drummix)", "golem_drummix" }
-- tags ouvrant un bloc FX dans un chunk de piste (pour chunk_set_sfizf, réf. golem_rig)
local FX_OPEN = { VST = true, AU = true, JS = true, LV2 = true, DX = true, CLAP = true }

-- ── carte gmem "golem_drums" (miroir golem_drumseq.jsfx) ──
local G = { NONCE = 0, OP = 1, SLOT = 2, PPQRES = 3, CHAN = 4, BANKGEN = 5,
           PLAYING = 8, ST_SLOT = 9, MODE = 10, HB = 11, TEMPO = 12, SEQIDX = 13, SEQON = 14,
           SEQLEN = 16, SEQMODE = 17, SEQSTEPS = 18 }
local PPQ_RES     = 960
local SLOT_BASE   = 256     -- (v2 song : 64 -> 256, la région SEQ vit en 16..145)
local SLOT_STRIDE = 8192    -- (v2 : 1024 -> 8192 -> ~2046 note-on/groove, plafond annoncé 2000)
local EV_OFF      = 8
local EV_STRIDE   = 4
local MAX_SLOTS   = 32
local MAX_EV      = math.floor((SLOT_STRIDE - EV_OFF) / EV_STRIDE)   -- 2046
local MAX_STEPS   = 64      -- étapes max d'une séquence (miroir SEQ_MAX du JSFX)
-- notes GM par défaut si un kit fournit une simple LISTE de samples sans note (repli, cf. doc en tête)
local GM_DEFAULT  = { 36, 38, 42, 46, 49, 51, 45, 47, 48, 50, 43, 41, 39, 37, 44, 56 }

reaper.gmem_attach("golem_drums")

-- ── util ──
local function write_atomic(path, s)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "w"); if not f then return false end
  f:write(s); f:close()
  return runtime.replace(tmp, path)
end

local function file_exists(p) local f = io.open(p, "r"); if f then f:close(); return true end return false end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if nm == name then return tr end
  end
  return nil
end

local function find_param_by_name(tr, fx, needle)
  if not needle then return nil end
  local target = needle:lower()
  local sub = nil
  for p = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local _, pn = reaper.TrackFX_GetParamName(tr, fx, p, "")
    local low = pn and pn:lower()
    if low == target then return p end
    if low and sub == nil and low:find(target, 1, true) then sub = p end
  end
  return sub
end

local function set_norm(tr, fx, needle, idx, norm)
  local p = find_param_by_name(tr, fx, needle)
  if not (p and p >= 0) then p = idx end
  reaper.TrackFX_SetParamNormalized(tr, fx, p, norm)
end

-- dichotomie sur la valeur AFFICHÉE (dB) — porté verbatim de golem_rig (pdisp + set_norm_to_target)
local function pdisp(tr, fx, p)
  local _, d = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
  d = d or ""
  if d:find("inf", 1, true) then return d:find("-", 1, true) and -150 or 150 end
  return tonumber(d:match("[-+]?%d+%.?%d*"))
end
local function clamp01(x) return x < 0 and 0 or (x > 1 and 1 or x) end
local function set_db_target(tr, fx, p, target, mn, mx)
  reaper.TrackFX_SetParamNormalized(tr, fx, p, 0); local v0 = pdisp(tr, fx, p)
  reaper.TrackFX_SetParamNormalized(tr, fx, p, 1); local v1 = pdisp(tr, fx, p)
  if not v0 or not v1 or v0 == v1 then
    reaper.TrackFX_SetParamNormalized(tr, fx, p, (mx == mn) and 0 or clamp01((target - mn) / (mx - mn))); return
  end
  local inc = v1 > v0
  local lo, hi = 0, 1
  for _ = 1, 16 do
    local mid = (lo + hi) / 2
    reaper.TrackFX_SetParamNormalized(tr, fx, p, mid)
    local v = pdisp(tr, fx, p) or target
    if (v < target) == inc then lo = mid else hi = mid end
  end
end

local function fx_stamp(tr, fx)
  local _, nm = reaper.TrackFX_GetFXName(tr, fx, "")
  local _, rn = reaper.TrackFX_GetNamedConfigParm(tr, fx, "renamed_name")
  return (rn ~= "" and rn) or nm or ""
end

-- ── piste PERMANENTE + séquenceur en FX0 ──
local function find_seq(tr)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    local _, nm = reaper.TrackFX_GetFXName(tr, i, "")
    if (nm or ""):lower():find("drumseq", 1, true)
       or (nm or ""):lower():find("drum sequencer", 1, true) then return i end
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
    if fx < 0 then log("⚠ JSFX golem_drumseq introuvable (provision/link-reaper.sh fait ? Reaper relancé ?)")
    else log("séquenceur golem_drumseq ajouté (permanent)") end
  end
  -- le séquenceur DOIT précéder les RS5k (le MIDI descend la chaîne) : on le remet en tête si besoin
  if fx and fx > 0 then
    reaper.TrackFX_CopyToTrack(tr, fx, tr, 0, true)          -- ismove=true : déplace à l'index 0
    fx = find_seq(tr)
  end
  return fx
end

local function ensure_track()
  local tr = find_track(TRACK)
  if not tr then
    reaper.PreventUIRefresh(1)
    local idx = reaper.CountTracks(0)
    reaper.InsertTrackAtIndex(idx, false)
    tr = reaper.GetTrack(0, idx)
    reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", TRACK, true)
    reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", -1)     -- pas d'entrée : audio généré par l'instrument
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 0)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 0)
    reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 1)
    reaper.SetMediaTrackInfo_Value(tr, "D_PAN", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", 0)
    -- sortie hardware OUT 1/2, jamais par le Master (même règle que looper/backing/sample)
    for si = reaper.GetTrackNumSends(tr, 1) - 1, 0, -1 do reaper.RemoveTrackSend(tr, 1, si) end
    local hw = reaper.CreateTrackSend(tr, nil)
    reaper.SetTrackSendInfo_Value(tr, 1, hw, "I_DSTCHAN", 0)
    reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", 0)
    reaper.PreventUIRefresh(-1)
    log("piste créée (permanente) : " .. TRACK .. " -> OUT 1/2")
  end
  -- pas de sortie MIDI hardware : on force -1 (idempotent) pour éviter toute fuite MIDI si une
  -- session antérieure l'avait posée.
  reaper.SetMediaTrackInfo_Value(tr, "I_MIDIHWOUT", -1)
  -- ⚠ ARMER, SINON LE @block NE TOURNE PAS. Cette ligne portait l'inverse : « la piste est
  -- traitée au repos via sa sortie AUDIO (OUT 1/2), ce qui suffit à faire tourner le @block
  -- free-running ». MESURÉ FAUX le 2026-08-07 : piste créée, drumseq ajouté, banque chargée,
  -- « play » émis — et gmem[ST_PLAYING] restait à 0. La sortie matérielle ne suffit PAS ;
  -- Reaper ne fait vivre que les pistes de son graphe TEMPS RÉEL, et une piste sans entrée,
  -- sans item et non armée n'en fait pas partie. Comme l'ordre arrive par gmem — invisible de
  -- Reaper — rien ne peut la réveiller. Même panne que le standard et le click le même jour.
  -- I_RECMODE 2 = « aucun » : vivante dans le graphe, hors d'état d'écrire un fichier.
  if reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") ~= 1 then
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", 2)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", 1)
    reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
    log("piste ARMÉE (I_RECMODE 2 « aucun ») — sans ça le thread audio ne la traite pas")
  end
  ensure_seq(tr)
  return tr
end

-- ── parseur Standard MIDI File (pur Lua) ──────────────────────────────────────
-- Renvoie { nev, length, barppq, events={{ppq,note,vel}...} } (résolution PPQ_RES), ou nil.
local function u32(s, i) return s:byte(i)*16777216 + s:byte(i+1)*65536 + s:byte(i+2)*256 + s:byte(i+3) end
local function u16(s, i) return s:byte(i)*256 + s:byte(i+1) end

local function read_vlq(s, i)
  local v = 0
  while true do
    local b = s:byte(i); i = i + 1
    v = v * 128 + (b % 128)
    if b < 128 then break end
  end
  return v, i
end

local function parse_midi(abspath)
  local f = io.open(abspath, "rb"); if not f then return nil, "introuvable" end
  local s = f:read("*a"); f:close()
  if not s or #s < 14 or s:sub(1, 4) ~= "MThd" then return nil, "pas un SMF" end
  local division = u16(s, 13)
  if division >= 0x8000 then return nil, "division SMPTE non supportée" end  -- ticks/noire attendu
  if division < 1 then division = PPQ_RES end
  local scale = PPQ_RES / division

  local events = {}                 -- {ppq(natif), note, vel}
  local max_tick = 0
  local bar_ppq = 4 * PPQ_RES       -- défaut 4/4 (raffiné par le 1er meta time-sig rencontré)
  local got_sig = false

  -- ⚠ Lua est indexé-1 : on démarre le scan au TOUT DÉBUT (pos=1). La boucle saute le chunk MThd
  -- (id ≠ MTrk) et avance pile sur MTrk (byte 15). L'ancien pos=14 (convention indexée-0) ratait le
  -- chunk MTrk d'un octet -> 0 événement parsé -> batterie muette (jamais vu : jamais validé au son).
  local pos = 1
  while pos + 8 <= #s + 1 and pos + 7 <= #s do
    local id = s:sub(pos, pos + 3)
    local len = u32(s, pos + 4)
    local tstart = pos + 8
    pos = tstart + len
    if id == "MTrk" then
      local i = tstart
      local tend = tstart + len
      local abstick = 0
      local running = nil
      while i < tend do
        local delta; delta, i = read_vlq(s, i)
        abstick = abstick + delta
        local b = s:byte(i)
        if b >= 0x80 then running = b; i = i + 1 else b = running end
        if not b then break end
        if b == 0xFF then                                   -- méta : ne fixe PAS le running status
          local mtype = s:byte(i); i = i + 1
          local mlen; mlen, i = read_vlq(s, i)
          if mtype == 0x58 and mlen >= 2 and not got_sig then   -- time signature nn dd cc bb
            local nn = s:byte(i); local dd = s:byte(i + 1)
            bar_ppq = math.floor(nn * (4 / (2 ^ dd)) * PPQ_RES + 0.5)
            if bar_ppq < 1 then bar_ppq = 4 * PPQ_RES end
            got_sig = true
          end
          i = i + mlen
        elseif b == 0xF0 or b == 0xF7 then                  -- sysex : longueur VLQ, ignoré
          local slen; slen, i = read_vlq(s, i); i = i + slen
          running = nil
        else
          local hi = b - (b % 16)
          if hi == 0x90 then                                -- note-on
            local note = s:byte(i); local vel = s:byte(i + 1); i = i + 2
            if vel and vel > 0 then
              events[#events + 1] = { math.floor(abstick * scale + 0.5), note, vel }
            end
          elseif hi == 0x80 or hi == 0xA0 or hi == 0xB0 or hi == 0xE0 then
            i = i + 2                                        -- 2 octets de données, ignorés
          elseif hi == 0xC0 or hi == 0xD0 then
            i = i + 1                                        -- 1 octet de données, ignoré
          else
            break                                           -- flux corrompu : on abandonne cette piste
          end
        end
        if abstick > max_tick then max_tick = abstick end
      end
    end
  end

  table.sort(events, function(a, b) return a[1] < b[1] end)
  local total = math.floor(max_tick * scale + 0.5)
  local bars = math.max(1, math.ceil(total / bar_ppq - 1e-6))
  local length = bars * bar_ppq
  if #events > MAX_EV then
    log(string.format("  ~ %s : %d note-on > %d -> tronqué", abspath:match("[^/]+$"), #events, MAX_EV))
    for k = #events, MAX_EV + 1, -1 do events[k] = nil end
  end
  return { nev = #events, length = length, barppq = bar_ppq, events = events }
end

-- charge un pattern parsé dans le slot gmem s
local function write_slot(s, pat)
  local base = SLOT_BASE + s * SLOT_STRIDE
  reaper.gmem_write(base + 0, pat.nev)
  reaper.gmem_write(base + 1, pat.length)
  reaper.gmem_write(base + 2, pat.barppq)
  reaper.gmem_write(base + 3, 1)
  for k = 1, pat.nev do
    local ev = pat.events[k]
    local ea = base + EV_OFF + (k - 1) * EV_STRIDE
    reaper.gmem_write(ea + 0, ev[1])
    reaper.gmem_write(ea + 1, ev[2])
    reaper.gmem_write(ea + 2, ev[3])
    reaper.gmem_write(ea + 3, 0)
  end
end

-- ── lecture du descripteur de kit ──
-- Renvoie { engine, role, sfz, bank, pads } depuis library/kits/<id>.json.
-- engine par défaut = rs5k (kits historiques sans clé engine). Une LISTE inline de samples
-- (repli) reste rs5k + notes GM. sfz/bank ne concernent que leurs moteurs respectifs.
local function read_kit(kit_id)
  local out = { engine = "rs5k", role = "pad", pads = {} }
  if not kit_id or kit_id == "" then return out end
  if kit_id:find('%.wav') or kit_id:find('%[') or kit_id:find('/') then
    local i = 0
    for rel in kit_id:gmatch('[^",%[%]%s]+') do
      i = i + 1
      out.pads[#out.pads + 1] = { note = GM_DEFAULT[i] or (35 + i), sample = rel, mode = "oneshot", level = 0 }
    end
    return out
  end
  local id = kit_id:gsub('%.json$', '')
  local f = io.open(ROOT .. "/library/kits/" .. id .. ".json", "r")
  if not f then log("  x kit introuvable : " .. tostring(kit_id)); return out end
  local s = f:read("*a"); f:close()
  out.engine = s:match('"engine"%s*:%s*"([^"]*)"') or "rs5k"
  out.role   = s:match('"role"%s*:%s*"([^"]*)"') or "pad"
  out.sfz    = s:match('"sfz"%s*:%s*"([^"]*)"')
  out.bank   = s:match('"bank"%s*:%s*"([^"]*)"')
  out.drumkit = s:match('"drumkit"%s*:%s*"([^"]*)"')
  out.midimap = s:match('"midimap"%s*:%s*"([^"]*)"')
  out.bleed   = tonumber(s:match('"bleed"%s*:%s*([%d%.]+)'))
  -- table `mix` du moteur drumgizmo : un objet {ch,gain,pan} par micro. Lue AVANT la boucle
  -- des pads : les deux moissonnent des objets {...} et se marcheraient dessus.
  local mixblk = s:match('"mix"%s*:%s*%[(.-)%]')
  out.mix = {}
  if mixblk then
    for obj in mixblk:gmatch('{[^{}]-}') do
      local ch = tonumber(obj:match('"ch"%s*:%s*(%d+)'))
      if ch then
        out.mix[#out.mix + 1] = { ch = ch,
          gain = tonumber(obj:match('"gain"%s*:%s*(%-?[%d%.]+)')) or 0,
          pan  = tonumber(obj:match('"pan"%s*:%s*(%-?[%d%.]+)')) or 0 }
      end
    end
  end
  for obj in s:gmatch('{[^{}]-}') do
    local note = tonumber(obj:match('"note"%s*:%s*(%d+)'))
    local sample = obj:match('"sample"%s*:%s*"([^"]*)"')
    if note and sample and sample ~= "" then
      out.pads[#out.pads + 1] = { note = note, sample = sample,
                                  mode = obj:match('"mode"%s*:%s*"([^"]*)"') or "oneshot",
                                  level = tonumber(obj:match('"level"%s*:%s*(%-?[%d%.]+)')) or 0 }
    end
  end
  return out
end

-- retire les FX du kit (estampille "drums:") — le séquenceur (FX0) est préservé
local function remove_kit_fx(tr)
  for i = reaper.TrackFX_GetCount(tr) - 1, 0, -1 do
    if fx_stamp(tr, i):find("^drums:") then reaper.TrackFX_Delete(tr, i) end
  end
end

local function add_first(tr, names)
  for _, nm in ipairs(names or {}) do
    local fx = reaper.TrackFX_AddByName(tr, nm, false, -1)
    if fx and fx >= 0 then reaper.TrackFX_Show(tr, fx, 2) end  -- REAPER neuf : « Auto-float » ouvrirait sa fenêtre (cf. golem_rig.lua add_fx)
    if fx and fx >= 0 then return fx, nm end
  end
  return -1
end

-- injecte/réécrit la ligne P sfzfile dans le bloc FX `fx` puis DROP le FXID (ré-instanciation ->
-- rechargement de l'état). RECOPIE de golem_rig.chunk_set_sfizf (chemin sfz SANS espace).
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
  if not (start_i and end_i) then
    log("  x (sfizz) bloc FX #" .. tostring(fx) .. " introuvable (idx max=" .. tostring(idx) .. ")")
    return false
  end
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
  if lines[end_i + 1] and lines[end_i + 1]:match("FXID") then table.remove(lines, end_i + 1) end
  return reaper.SetTrackStateChunk(track, table.concat(lines, "\n"), false)
end

-- ── engine:drumgizmo — état LV2 (XML base64 dans le chunk) ──────────────────
local B64C = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function b64(data)
  local out, n = {}, #data
  for i = 1, n, 3 do
    local a, b, c = data:byte(i, i + 2)
    local v = a * 65536 + (b or 0) * 256 + (c or 0)
    local s = B64C:sub(math.floor(v / 262144) % 64 + 1, math.floor(v / 262144) % 64 + 1)
             .. B64C:sub(math.floor(v / 4096) % 64 + 1, math.floor(v / 4096) % 64 + 1)
             .. (b and B64C:sub(math.floor(v / 64) % 64 + 1, math.floor(v / 64) % 64 + 1) or "=")
             .. (c and B64C:sub(v % 64 + 1, v % 64 + 1) or "=")
    out[#out + 1] = s
  end
  return table.concat(out)
end

-- Le XML complet, pas seulement les deux chemins : drumgizmo réécrit TOUT son état à la sauvegarde,
-- et un <config> amputé le laisse sur ses valeurs internes. Les valeurs ci-dessous sont celles
-- relevées sur une instance fraîche (chunkdump), à trois exceptions ASSUMÉES :
--   disk_cache_enable=true  : 3 Go de samples, on streame depuis le disque (défaut, gardé explicite) ;
--   enable_bleed_control=true + master_bleed : la diaphonie EST l'intérêt du kit — la garder pilotable ;
--   enable_resampling=true  : le kit est en 44,1 kHz, le rig tourne à 48.
local function dg_config_xml(kitfile, midimap, bleed)
  local v = {
    drumkitfile = kitfile, midimapfile = midimap,
    enable_velocity_modifier = "true", velocity_modifier_falloff = "0.500000",
    velocity_modifier_weight = "0.250000", velocity_stddev = "0.450000",
    sample_selection_f_close = "0.850000", sample_selection_f_diverse = "0.160000",
    sample_selection_f_random = "0.070000", enable_velocity_randomiser = "false",
    velocity_randomiser_weight = "0.100000", enable_resampling = "true",
    resampling_quality = "0.700000", disk_cache_upper_limit = "1073741824",
    disk_cache_chunk_size = "1048576", disk_cache_enable = "true",
    enable_bleed_control = "true", master_bleed = string.format("%f", bleed or 1.0),
    enable_latency_modifier = "false", latency_laid_back_ms = "0.000000",
    latency_stddev = "2.000000", latency_regain = "0.900000",
    enable_powermap = "false", powermap_fixed0_x = "0.000000", powermap_fixed0_y = "0.000000",
    powermap_fixed1_x = "0.500000", powermap_fixed1_y = "0.500000",
    powermap_fixed2_x = "1.000000", powermap_fixed2_y = "1.000000", powermap_shelf = "true",
    enable_voice_limit = "false", voice_limit_max = "15", voice_limit_rampdown = "0.500000",
  }
  -- l'ORDRE compte peu pour le parseur mais on garde celui de l'instance native, pour que
  -- deux dumps se comparent à l'œil sans diff bruyant.
  local order = { "drumkitfile", "midimapfile", "enable_velocity_modifier",
    "velocity_modifier_falloff", "velocity_modifier_weight", "velocity_stddev",
    "sample_selection_f_close", "sample_selection_f_diverse", "sample_selection_f_random",
    "enable_velocity_randomiser", "velocity_randomiser_weight", "enable_resampling",
    "resampling_quality", "disk_cache_upper_limit", "disk_cache_chunk_size", "disk_cache_enable",
    "enable_bleed_control", "master_bleed", "enable_latency_modifier", "latency_laid_back_ms",
    "latency_stddev", "latency_regain", "enable_powermap", "powermap_fixed0_x", "powermap_fixed0_y",
    "powermap_fixed1_x", "powermap_fixed1_y", "powermap_fixed2_x", "powermap_fixed2_y",
    "powermap_shelf", "enable_voice_limit", "voice_limit_max", "voice_limit_rampdown" }
  local t = { '<config version="1.0">' }
  for _, k in ipairs(order) do
    t[#t + 1] = '  <value name="' .. k .. '">' .. tostring(v[k] or "") .. "</value>"
  end
  t[#t + 1] = "</config>"
  return table.concat(t, "\n") .. "\n"
end

-- remplace (ou crée) le bloc <X atom#config ... > du FX `fx` par l'état encodé, puis DROP le FXID.
local function chunk_set_dgconfig(track, fx, xml)
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
  if not (start_i and end_i) then
    log("  x (drumgizmo) bloc FX #" .. tostring(fx) .. " introuvable (idx max=" .. tostring(idx) .. ")")
    return false
  end
  -- corps du nouveau <X : base64 coupé à 280 caractères, la largeur qu'écrit Reaper lui-même.
  local enc = b64(xml)
  local body = { "<X " .. DG_URI .. " " .. DG_ATOM .. " 3" }
  for p = 1, #enc, 280 do body[#body + 1] = enc:sub(p, p + 279) end
  body[#body + 1] = ">"
  -- localise le <X existant DANS ce bloc FX (il est dans <STATE) et le remplace
  local x_start, x_end
  for k = start_i, end_i do
    local t = lines[k]:gsub("\r", ""):match("^%s*(.-)%s*$")
    if not x_start and t:find("^<X " .. DG_URI, 1, false) then x_start = k end
    if x_start and k > x_start and t == ">" then x_end = k; break end
  end
  if x_start and x_end then
    for k = x_end, x_start, -1 do table.remove(lines, k) end
    for k = #body, 1, -1 do table.insert(lines, x_start, body[k]) end
    end_i = end_i - (x_end - x_start + 1) + #body
  else
    -- pas d'état sérialisé (instance jamais sauvée) : on pose <STATE ... > juste avant la fermeture
    local ins = end_i
    table.insert(lines, ins, "<STATE")
    for k = 1, #body do table.insert(lines, ins + k, body[k]) end
    table.insert(lines, ins + #body + 1, ">")
    end_i = end_i + #body + 2
  end
  if lines[end_i + 1] and lines[end_i + 1]:match("FXID") then table.remove(lines, end_i + 1) end
  return reaper.SetTrackStateChunk(track, table.concat(lines, "\n"), false)
end

local function build_kit_drumgizmo(tr, k)
  if not (k.drumkit and k.midimap) then log("  x kit drumgizmo sans drumkit/midimap"); return end
  local kit_abs = ROOT .. "/" .. k.drumkit
  local map_abs = ROOT .. "/" .. k.midimap
  if not file_exists(kit_abs) then log("  x drumkit introuvable : " .. k.drumkit); return end
  if not file_exists(map_abs) then log("  x midimap introuvable : " .. k.midimap); return end

  -- la piste PASSE à 16 canaux : les sorties de drumgizmo sont UN MICRO CHACUNE, et les
  -- canaux 1/2 seuls ne sont pas « la batterie » mais les overheads. build_kit remet 2 en sortant.
  reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", DG_NCH)

  local fx, nm = add_first(tr, DG_NAMES)
  if fx < 0 then log("  x drumgizmo.lv2 introuvable — installé ET Reaper relancé ?"); return end
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "drums:dg")
  if chunk_set_dgconfig(tr, fx, dg_config_xml(kit_abs, map_abs, k.bleed)) then
    log("kit drumgizmo : " .. tostring(nm) .. " -> " .. k.drumkit)
  else
    log("  x kit drumgizmo : échec du patch atom#config")
  end
  reaper.TrackFX_SetEnabled(tr, fx, true)

  -- mixeur 16 -> 2 APRÈS le plugin. Sans lui on n'entend que les overheads.
  local mx = add_first(tr, DRUMMIX_NAMES)
  if mx < 0 then
    log("  x golem_drummix introuvable (link-reaper.sh fait ?) — sortie = overheads SEULS")
  else
    reaper.TrackFX_SetNamedConfigParm(tr, mx, "renamed_name", "drums:mix")
    for _, m in ipairs(k.mix or {}) do
      local ch = tonumber(m.ch)
      if ch and ch >= 1 and ch <= DG_NCH then
        reaper.TrackFX_SetParam(tr, mx, (ch - 1) * 2,     tonumber(m.gain) or 0)
        reaper.TrackFX_SetParam(tr, mx, (ch - 1) * 2 + 1, tonumber(m.pan) or 0)
      end
    end
    reaper.TrackFX_SetEnabled(tr, mx, true)
    log("  mixeur drummix : " .. tostring(#(k.mix or {})) .. " canaux posés")
  end
end

-- ── build par moteur ──
local function build_kit_rs5k(tr, pads)
  local placed = 0
  for _, pad in ipairs(pads) do
    local abspath = ROOT .. "/" .. pad.sample
    if not file_exists(abspath) then
      log("  x sample introuvable : " .. pad.sample)
    else
      local fx = add_first(tr, RS5K_NAMES)
      if fx < 0 then
        log("  x ReaSamplOmatic5000 introuvable (note " .. pad.note .. ")")
      else
        reaper.TrackFX_SetNamedConfigParm(tr, fx, "FILE0", abspath)
        reaper.TrackFX_SetNamedConfigParm(tr, fx, "DONE", "")
        local nn = pad.note / 127
        set_norm(tr, fx, "Note range start", RS5K_IDX.note_start, nn)
        set_norm(tr, fx, "Note range end",   RS5K_IDX.note_end,   nn)
        -- batterie = one-shot : obey note-off OFF -> chaque frappe sonne jusqu'au bout (chokes ignorés v1)
        set_norm(tr, fx, "Obey note-off", RS5K_IDX.obey, 0)
        -- ⚠ PIÈGE RS5k (build_pads_block) : "Pitch for start/end note" ≠ 0 st après FILE0 -> forcé 0.5
        set_norm(tr, fx, "Pitch for start note", RS5K_IDX.pitch_start, 0.5)
        set_norm(tr, fx, "Pitch for end note",   RS5K_IDX.pitch_end,   0.5)
        local vp = find_param_by_name(tr, fx, "Volume"); if not (vp and vp >= 0) then vp = RS5K_IDX.volume end
        set_db_target(tr, fx, vp, pad.level, -60, 12)
        local mvp = find_param_by_name(tr, fx, "Gain for minimum velocity")
        if not (mvp and mvp >= 0) then mvp = RS5K_IDX.min_vel_gain end
        set_db_target(tr, fx, mvp, pad.level, -60, 12)      -- réponse plate en vélocité (v1)
        reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "drums:" .. pad.note)
        reaper.TrackFX_SetEnabled(tr, fx, true)
        placed = placed + 1
      end
    end
  end
  log(string.format("kit rs5k : %d pad(s) RS5k", placed))
end

local function build_kit_sfz(tr, sfz)
  local abspath = ROOT .. "/" .. tostring(sfz)
  if not sfz or not file_exists(abspath) then log("  x .sfz introuvable : " .. tostring(sfz)); return end
  local fx, nm = add_first(tr, SFIZZ_NAMES)
  if fx < 0 then log("  x sfizz introuvable (plugin installé ET Reaper relancé depuis l'install ?)"); return end
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "drums:sfz")
  local okt, ft = reaper.TrackFX_GetNamedConfigParm(tr, fx, "fx_type")
  if okt and ft and ft:find("VST3") then
    -- sfizz en VST3 (Windows/macOS, 2026-10-11) : le .sfz par l'état VST3 — les espaces du chemin ne gênent pas
    local okv, info = sfizz_vst3_set_file(tr, fx, abspath)
    if okv then log("kit sfz : sfizz VST3 (" .. tostring(info) .. ") -> " .. sfz)
    else log("  x kit sfz : état VST3 non posé (" .. tostring(info) .. ")") end
  else
    if abspath:find("%s") then log("  x chemin .sfz avec espace non supporté (ligne P non quotée) : " .. abspath); return end
    if chunk_set_sfizf(tr, fx, abspath) then
      log("kit sfz : sfizz -> " .. sfz)
    else
      log("  x kit sfz : échec du patch sfzfile")
    end
  end
  reaper.TrackFX_SetEnabled(tr, fx, true)
end

local function build_kit_avldrums(tr, bank)
  local names = AVL_NAMES[bank or ""]
  if not names then log("  x banque avldrums inconnue : " .. tostring(bank)); return end
  local fx, nm = add_first(tr, names)
  if fx < 0 then log("  x avldrums.lv2 (" .. tostring(bank) .. ") introuvable — installé ET Reaper relancé ?"); return end
  reaper.TrackFX_SetNamedConfigParm(tr, fx, "renamed_name", "drums:avl")
  reaper.TrackFX_SetEnabled(tr, fx, true)
  log("kit avldrums : " .. tostring(nm))
end

local cur_kit = nil
local function build_kit(tr, kit_id)
  if cur_kit == kit_id then return end
  reaper.PreventUIRefresh(1)
  remove_kit_fx(tr)
  local k = read_kit(kit_id)
  -- la piste revient à 2 canaux pour TOUS les moteurs sauf drumgizmo (qui la passe à 16) :
  -- sinon un kit stéréo hérite des 16 canaux du kit précédent et le mixeur fantôme reste seul
  -- à alimenter les sorties 1/2.
  if k.engine ~= "drumgizmo" then reaper.SetMediaTrackInfo_Value(tr, "I_NCHAN", 2) end
  if k.engine == "drumgizmo" then
    build_kit_drumgizmo(tr, k)
  elseif k.engine == "avldrums" then
    build_kit_avldrums(tr, k.bank)
  elseif k.engine == "sfz" then
    build_kit_sfz(tr, k.sfz)
  else
    build_kit_rs5k(tr, k.pads)
  end
  reaper.PreventUIRefresh(-1)
  cur_kit = kit_id
end

-- ── banque de patterns (par bloc) ──
-- blocks[bid] = { patterns={rel...}, fills={rel...}, P, F, fp } (indices de slot = position dans la liste)
local blocks = {}
local cur_block = nil

local function load_bank(bid, patterns, fills)
  local fp = table.concat(patterns or {}, "\30") .. "\31" .. table.concat(fills or {}, "\30")
  local st = blocks[bid]
  if st and st.fp == fp then return st end
  local slot = 0
  local function load_list(list)
    local first = slot
    for _, rel in ipairs(list or {}) do
      if slot >= MAX_SLOTS then log("  ~ banque pleine (" .. MAX_SLOTS .. " slots) — reste ignoré"); break end
      local pat, err = parse_midi(ROOT .. "/" .. rel)
      if not pat then
        log("  x .mid : " .. rel .. " (" .. tostring(err) .. ")")
        pat = { nev = 0, length = 4 * PPQ_RES, barppq = 4 * PPQ_RES, events = {} }  -- slot muet (silence 1 mesure)
      end
      write_slot(slot, pat)
      slot = slot + 1
    end
    return slot - first
  end
  local P = load_list(patterns)
  local F = load_list(fills)
  reaper.gmem_write(G.BANKGEN, (reaper.gmem_read(G.BANKGEN) or 0) + 1)
  st = { patterns = patterns or {}, fills = fills or {}, P = P, F = F, fp = fp }
  blocks[bid] = st
  log(string.format("banque bloc %s : %d pattern(s) + %d fill(s)", bid, P, F))
  return st
end

-- ── envoi de commande au JSFX (nonce EN DERNIER) ──
-- CANAL 10 (index 9) = canal percussion General MIDI. avldrums (FluidSynth) ne joue les fûts que sur
-- le canal 10 -> émettre sur canal 1 (chan=0) restait muet (aucun pad ne bougeait). Les RS5k filtrent
-- par NOTE (canal ignoré) -> canal 10 marche pour les deux moteurs.
local DRUM_MIDI_CHAN = 9
local function seq_cmd(op, slot)
  reaper.gmem_write(G.OP, op)
  reaper.gmem_write(G.SLOT, slot or 0)
  reaper.gmem_write(G.CHAN, DRUM_MIDI_CHAN)
  reaper.gmem_write(G.NONCE, (reaper.gmem_read(G.NONCE) or 0) + 1)
end

-- ── ops ──
-- sequence = liste {i=index pattern (0-based), times=passages (0=infini)} ; mode "loop"|"once".
-- Écrit la playlist en gmem PUIS envoie op=4 (song). Étapes hors banque ignorées (log).
local function write_sequence(st, sequence, seq_mode)
  local n = 0
  for _, step in ipairs(sequence) do
    if n >= MAX_STEPS then log("  ~ séquence tronquée à " .. MAX_STEPS .. " étapes"); break end
    local i = math.floor(tonumber(step.i) or -1)
    if i >= 0 and i < st.P then
      local t = math.floor(tonumber(step.times) or 1)
      if t < 0 then t = 1 elseif t > 99 then t = 99 end
      reaper.gmem_write(G.SEQSTEPS + n * 2, i)
      reaper.gmem_write(G.SEQSTEPS + n * 2 + 1, t)
      n = n + 1
    else
      log("  ~ étape séquence i=" .. tostring(step.i) .. " hors des " .. st.P .. " pattern(s) — ignorée")
    end
  end
  reaper.gmem_write(G.SEQLEN, n)
  reaper.gmem_write(G.SEQMODE, seq_mode == "once" and 1 or 0)
  return n
end

local function op_play(bid, idx, patterns, fills, kit, sequence, seq_mode)
  if not bid then log("play : block manquant"); return end
  idx = idx or 0
  local tr = ensure_track()
  build_kit(tr, kit)
  local st = load_bank(bid, patterns, fills)
  if idx < 0 or idx >= st.P then log("play : idx " .. idx .. " hors des " .. st.P .. " pattern(s)"); idx = 0 end
  cur_block = bid
  st.idx = idx; st.playing = true; st.mode = 0
  if sequence and #sequence > 0 then
    local n = write_sequence(st, sequence, seq_mode)
    if n > 0 then
      st.seq = true
      seq_cmd(4, 0)                                          -- op=song (playlist depuis l'étape 0)
      log(string.format("song bloc %s : %d étape(s), mode %s", bid, n, seq_mode or "loop"))
      return
    end
    log("song : aucune étape valide — repli play simple")
  end
  st.seq = false
  seq_cmd(1, idx)                                            -- op=play, slot=idx
  log(string.format("play bloc %s idx %d", bid, idx))
end

local function op_variation(bid, idx)
  local st = blocks[bid]
  if not st then log("variation : bloc " .. tostring(bid) .. " sans banque (play d'abord)"); return end
  idx = idx or 0
  if idx < 0 or idx >= st.P then log("variation : idx " .. idx .. " hors plage"); return end
  cur_block = bid; st.idx = idx
  seq_cmd(2, idx)                                            -- op=variation (quantifié mesure côté JSFX)
  log(string.format("variation bloc %s -> idx %d", bid, idx))
end

local function op_fill(bid, fill_idx)
  local st = blocks[bid]
  if not st then log("fill : bloc " .. tostring(bid) .. " sans banque (play d'abord)"); return end
  fill_idx = fill_idx or 0
  if fill_idx < 0 or fill_idx >= st.F then log("fill : fill_idx " .. fill_idx .. " hors plage"); return end
  cur_block = bid
  seq_cmd(3, st.P + fill_idx)                                -- fills logés après les patterns
  log(string.format("fill bloc %s -> fills[%d] (slot %d)", bid, fill_idx, st.P + fill_idx))
end

local function op_stop(bid)
  seq_cmd(0, 0)
  local st = blocks[bid]; if st then st.playing = false; st.mode = 0 end
  log("stop bloc " .. tostring(bid))
end


-- ── mix multi-micros : pose les sliders de golem_drummix (moteur drumgizmo) ──────────────────
-- Appelé au `play` ET par l'op `mix` (l'écran pousse pendant qu'on écoute — la boîte à rythmes ne
-- relit pas le preset). Idempotent, 33 SetParam : rien à étaler, on est loin du thread audio.
local function find_stamp(tr, stamp)
  for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
    if fx_stamp(tr, i) == stamp then return i end
  end
  return -1
end

local function apply_mix(tr, mix, master)
  if not mix or #mix == 0 then return false end
  local mx = find_stamp(tr, "drums:mix")
  if mx < 0 then return false end
  for _, m in ipairs(mix) do
    if m.ch and m.ch >= 1 and m.ch <= DG_NCH then
      reaper.TrackFX_SetParam(tr, mx, (m.ch - 1) * 2,     m.gain or 0)
      reaper.TrackFX_SetParam(tr, mx, (m.ch - 1) * 2 + 1, m.pan or 0)
    end
  end
  if master then reaper.TrackFX_SetParam(tr, mx, DG_NCH * 2, master) end
  return true
end

-- parse [{"ch":1,"gain":-3,"pan":-0.9},...] depuis la charge de commande
local function parse_mix(body)
  local arr = body:match('"mix"%s*:%s*%[(.-)%]')
  if not arr then return nil end
  local out = {}
  for obj in arr:gmatch('{(.-)}') do
    local ch = tonumber(obj:match('"ch"%s*:%s*(%d+)'))
    if ch then
      out[#out + 1] = { ch = ch,
        gain = tonumber(obj:match('"gain"%s*:%s*(%-?[%d%.]+)')) or 0,
        pan  = tonumber(obj:match('"pan"%s*:%s*(%-?[%d%.]+)')) or 0 }
    end
  end
  return #out > 0 and out or nil
end

-- ── commandes (ProjExtState golem/drums_cmd, posé par golem_watch) ──
local last_seq = nil
local function poll_cmd()
  local _, body = reaper.GetProjExtState(0, "golem", "drums_cmd")
  if not body or body == "" then return end
  local seq = body:match('"seq"%s*:%s*(%-?%d+)')
  if seq and seq == last_seq then return end
  last_seq = seq
  local op  = body:match('"op"%s*:%s*"([^"]+)"')
  local bid = body:match('"block"%s*:%s*"([^"]+)"')
  if op == "play" then
    local idx = tonumber(body:match('"idx"%s*:%s*(%-?%d+)')) or 0
    local kit = body:match('"kit"%s*:%s*"([^"]*)"')
    local patterns, fills = {}, {}
    local pa = body:match('"patterns"%s*:%s*%[(.-)%]')
    if pa then for x in pa:gmatch('"([^"]*)"') do patterns[#patterns + 1] = x end end
    local fa = body:match('"fills"%s*:%s*%[(.-)%]')
    if fa then for x in fa:gmatch('"([^"]*)"') do fills[#fills + 1] = x end end
    -- séquence song optionnelle : [{"i":0,"times":4},...] (times absent = 1, 0 = infini)
    local sequence = nil
    local sa = body:match('"sequence"%s*:%s*%[(.-)%]')
    if sa then
      sequence = {}
      for obj in sa:gmatch('{(.-)}') do
        sequence[#sequence + 1] = { i = tonumber(obj:match('"i"%s*:%s*(%-?%d+)')),
                                    times = tonumber(obj:match('"times"%s*:%s*(%-?%d+)')) or 1 }
      end
    end
    local seq_mode = body:match('"seq_mode"%s*:%s*"([^"]+)"')
    op_play(bid, idx, patterns, fills, kit, sequence, seq_mode)
    -- le mix voyage AVEC le play : le kit peut venir d'être (re)construit, ses sliders sont
    -- alors ceux du kit — les écarts du preset ne vivent que dans la commande.
    local mix = parse_mix(body)
    if mix then
      local tr = find_track(TRACK)
      if tr then apply_mix(tr, mix, tonumber(body:match('"master"%s*:%s*(%-?[%d%.]+)'))) end
    end
  elseif op == "variation" then
    op_variation(bid, tonumber(body:match('"idx"%s*:%s*(%-?%d+)')) or 0)
  elseif op == "fill" then
    op_fill(bid, tonumber(body:match('"fill_idx"%s*:%s*(%-?%d+)')) or 0)
  elseif op == "mix" then
    local tr = find_track(TRACK)
    local mix = parse_mix(body)
    if not tr then log("  x mix : piste Drums absente")
    elseif not mix then log("  x mix : charge vide")
    elseif apply_mix(tr, mix, tonumber(body:match('"master"%s*:%s*(%-?[%d%.]+)'))) then
      log("mix posé : " .. #mix .. " canaux")
    else
      log("  x mix : pas de drums:mix sur la piste (kit non multi-micros ?)")
    end
  elseif op == "stop" then
    op_stop(bid)
  else
    log("op inconnue : " .. tostring(op))
  end
end

-- ── publication d'état (réconcilie l'état optimiste avec le témoin gmem du JSFX) ──
local function build_json()
  local playing_jsfx = (reaper.gmem_read(G.PLAYING) or 0) >= 0.5
  local mode_jsfx    = (reaper.gmem_read(G.MODE) or 0) >= 0.5
  local step_jsfx    = math.floor(reaper.gmem_read(G.SEQIDX) or -1)   -- étape courante (-1 hors song)
  local parts = {}
  for bid, st in pairs(blocks) do
    local is_active = (bid == cur_block)
    local playing = is_active and playing_jsfx or false
    local mode = (is_active and playing and mode_jsfx) and "fill" or "groove"
    local step = (is_active and playing) and step_jsfx or -1
    parts[#parts + 1] = string.format('"%s":{"playing":%s,"idx":%d,"mode":"%s","step":%d}',
      bid, playing and "true" or "false", st.idx or 0, mode, step)
  end
  return '{"present":true,"blocks":{' .. table.concat(parts, ",") .. '}}'
end

local last_fp = nil
local function publish(force)
  local playing = (reaper.gmem_read(G.PLAYING) or 0) >= 0.5
  local mode    = (reaper.gmem_read(G.MODE) or 0) >= 0.5
  local slot    = math.floor((reaper.gmem_read(G.ST_SLOT) or -1) + 0.5)
  local sig = string.format("%s|%s|%s|%d", tostring(cur_block), tostring(playing), tostring(mode), slot)
  if force or sig ~= last_fp then
    last_fp = sig
    write_atomic(OUT, build_json())
  end
end

-- ── boucle (garde par génération : la dernière instance lancée gagne) ──
local GEN = tostring(reaper.time_precise())
reaper.SetExtState("golem", "drums_gen", GEN, false)

local function tick()
  -- ⚠ CLÉ (bug gmem partagé) : __startup dofile TOUS les scripts dans UN SEUL contexte -> UN SEUL
  -- gmem[]. gmem_attach RE-POINTE ce gmem[] : le DERNIER attach au boot (golem_knobs) gagnait, donc
  -- cette boucle lisait/écrivait dans « golem_knobs » et non « golem_drums » -> commandes jamais vues
  -- par le JSFX drumseq. Les defer ticks étant séquentiels et atomiques, on RÉ-ATTACHE notre espace en
  -- tête de tick : durant CE tick, gmem[] pointe bien « golem_drums ». (idem knobs/looper/tuner.)
  reaper.gmem_attach("golem_drums")
  poll_cmd()
  publish(false)                                            -- n'écrit que sur changement de signature
end

-- au démarrage : ADOPTER le seq résiduel SANS le rejouer (un drums_cmd sauvegardé ne doit pas
-- relancer une boucle au boot), sauf « kick » explicite d'un bootstrap.
if reaper.GetExtState("golem", "drums_kick") == "1" then
  reaper.SetExtState("golem", "drums_kick", "", false)
  last_seq = nil
else
  local _, body = reaper.GetProjExtState(0, "golem", "drums_cmd")
  last_seq = body and body:match('"seq"%s*:%s*(%-?%d+)') or nil
end

reaper.gmem_write(G.PPQRES, PPQ_RES)                        -- résolution interne (lue par le JSFX)

local err_streak = 0
local function loop()
  if reaper.GetExtState("golem", "drums_gen") ~= GEN then return end   -- remplacée : cette boucle meurt
  reaper.SetExtState("golem", "drums_alive", string.format("%.3f", reaper.time_precise()), false)
  local ok, err = pcall(tick)                               -- une erreur d'un tick NE TUE JAMAIS la boucle
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
