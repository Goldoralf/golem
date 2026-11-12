-- SPDX-License-Identifier: GPL-3.0-or-later
-- Une session du Golem Engine pour UN cas du banc de parité (tools/check-engine-parity.py) :
--   luasession engine-render-case.lua <session-dir> <case.json>
-- Une piste audio mono « gtr », le bloc posé EXACTEMENT comme golem_watch.lua le pose sur le rack (new_audio_track 1/1,
-- plugin ajouté, réglages d'ajout `init`, puis les paramètres : label exact puis sous-chaîne, valeur brute, ou `norm`
-- converti avec les bornes du port). La DI est posée ensuite par golem-place, le rendu fait par l'export d'Ardour.

io.stdout:setvbuf ("no")
local SESSION, CASE = arg[1], arg[2]
local function rd (p) local f = assert (io.open (p)); local s = f:read ("a"); f:close (); return s end
-- le cas, en Lua (écrit par le script Python : `return { … }`)
local c = load (rd (CASE)) ()

AudioEngine:set_backend ("None (Dummy)", "golem-render", "")
assert (create_session (SESSION, "bench", 48000), "session")
local tr
for t in Session:new_audio_track (1, 1, ARDOUR.RouteGroup (), 1, "gtr", ARDOUR.PresentationInfo.max_order,
	ARDOUR.TrackMode.Normal, true):iter () do tr = t end

local function params_of (pl)
	local out = {}
	for i = 0, pl:parameter_count () - 1 do
		local port, r = pl:nth_parameter (i, true)
		if not r[2] then break end
		if pl:parameter_is_input (port) and pl:parameter_is_control (port) then
			local _, d = pl:get_parameter_descriptor (port, ARDOUR.ParameterDescriptor ())
			out[#out + 1] = { i = i, label = pl:parameter_label (port), lower = d[2].lower, upper = d[2].upper }
		end
	end
	return out
end
local function find (ps, label)
	for _, p in ipairs (ps) do if p.label == label then return p end end
	local l = label:lower ()
	for _, p in ipairs (ps) do if p.label:lower ():find (l, 1, true) then return p end end
	return nil
end
local function set_params (p, entries)
	local ps = params_of (p:to_insert ():plugin (0))
	for _, e in ipairs (entries or {}) do
		local q = find (ps, e.label)
		if not q then print ("param introuvable : " .. e.label)
		else
			local v = e.value
			if v == nil and e.norm ~= nil then v = q.lower + e.norm * (q.upper - q.lower) end
			if v < q.lower then v = q.lower elseif v > q.upper then v = q.upper end
			ARDOUR.LuaAPI.set_processor_param (p, q.i, v)
			print (string.format ("param %s = %s", e.label, tostring (ARDOUR.LuaAPI.get_processor_param (p, q.i))))
		end
	end
end

if c.plugin then
	local p
	if c.plugin.lv2 then p = ARDOUR.LuaAPI.new_plugin (Session, c.plugin.lv2, ARDOUR.PluginType.LV2, "")
	elseif c.plugin.vst3 then p = ARDOUR.LuaAPI.new_plugin (Session, c.plugin.vst3, ARDOUR.PluginType.VST3, "")
	else p = ARDOUR.LuaAPI.new_luaproc (Session, c.plugin.lua) end
	assert (not p:isnil (), "plugin absent")
	-- la stéréo comme sur le rack : le module du veilleur (lancé depuis le dossier du Golem Engine)
	local CHAIN = dofile ("golem/engine/golem_chain.lua")
	CHAIN.add (tr, p, 1)
	-- une piste passée en STÉRÉO a un 2e port de sortie que rien ne relie (Ardour ne relie qu'à la création) : au
	-- master, canal par canal — sinon l'export rend la droite muette (gfx-rotary, 2026-11-12)
	local out, min = tr:output (), Session:master_out ():input ()
	for k = 1, out:n_ports ():n_audio () - 1 do
		if k < min:n_ports ():n_audio () then out:audio (k):connect (min:audio (k):name ()) end
	end
	set_params (p, c.init)
	set_params (p, c.params)
	if c.enabled == false then p:to_insert ():deactivate () end
	-- laisser tourner le moteur : un VST3 ACTIF reçoit ses réglages par la file du prochain cycle audio, pas par son
	-- contrôleur (nih-plug ignore setParamNormalized pendant le traitement) ; sauvegarder avant = l'état du plugin
	-- garde ses valeurs par défaut et les impose au rechargement (mesuré 2026-11-12, golem Gate : Attack 3 au lieu de 15)
	ARDOUR.LuaAPI.usleep (300000)
	for _, q in ipairs (params_of (p:to_insert ():plugin (0))) do      -- tous les ports, pour comparer à REAPER
		print (string.format ("all %s = %s", q.label, tostring (ARDOUR.LuaAPI.get_processor_param (p, q.i))))
	end
end
Session:save_state ("", false, false, false, false, false)
print ("built")
