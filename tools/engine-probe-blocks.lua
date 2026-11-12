-- SPDX-License-Identifier: GPL-3.0-or-later
-- Sonde des blocs du Golem Engine (tools/check-engine-blocks.py la lance dans luasession, pilote factice) :
--   luasession engine-probe-blocks.lua <session-dir> <in.json> <out.json>
-- Pour chaque bloc de in.json ({type, lv2|lua, labels[], init[{label,value}]}) : instanciation chronométrée sur une piste
-- audio mono, chaque paramètre résolu par la règle de golem_rig (label exact, puis sous-chaîne sans casse), une valeur
-- écrite puis relue, deux bascules on/off pendant que le moteur tourne, les xruns comptés. Aucune carte, aucun son.

io.stdout:setvbuf ("no")
local SESSION, IN, OUT = arg[1], arg[2], arg[3]
AudioEngine:set_backend ("None (Dummy)", "golem-probe", "")
assert (create_session (SESSION, "probe", 48000), "session")

local function rd (p) local f = assert (io.open (p)); local s = f:read ("a"); f:close (); return s end
-- JSON minimal (entrée produite par le script Python : objets, tableaux, chaînes, nombres, booléens)
local function decode (s)
	local i = 1
	local function ws () i = s:find ("[^%s]", i) or #s + 1 end
	local val
	local function str ()
		local j, out = i + 1, {}
		while true do
			local c = s:sub (j, j)
			if c == '"' then i = j + 1; return table.concat (out) end
			if c == "\\" then
				local n = s:sub (j + 1, j + 1)
				if n == "u" then out[#out + 1] = utf8.char (tonumber (s:sub (j + 2, j + 5), 16)); j = j + 6
				else out[#out + 1] = ({ n = "\n", t = "\t", r = "\r", b = "\b", f = "\f" })[n] or n; j = j + 2 end
			else out[#out + 1] = c; j = j + 1 end
		end
	end
	function val ()
		ws ()
		local c = s:sub (i, i)
		if c == "{" then
			local t = {}; i = i + 1; ws ()
			if s:sub (i, i) == "}" then i = i + 1; return t end
			while true do
				ws (); local k = str (); ws (); i = i + 1
				t[k] = val (); ws ()
				local d = s:sub (i, i); i = i + 1
				if d == "}" then return t end
			end
		elseif c == "[" then
			local t = {}; i = i + 1; ws ()
			if s:sub (i, i) == "]" then i = i + 1; return t end
			while true do
				t[#t + 1] = val (); ws ()
				local d = s:sub (i, i); i = i + 1
				if d == "]" then return t end
			end
		elseif c == '"' then return str ()
		elseif s:sub (i, i + 3) == "true" then i = i + 4; return true
		elseif s:sub (i, i + 4) == "false" then i = i + 5; return false
		elseif s:sub (i, i + 3) == "null" then i = i + 4; return nil
		else local n = s:match ("^-?[%d%.eE+-]+", i); i = i + #n; return tonumber (n) end
	end
	return val ()
end
local function enc (v)
	local t = type (v)
	if t == "table" then
		if #v > 0 or next (v) == nil then
			local o = {}; for _, x in ipairs (v) do o[#o + 1] = enc (x) end; return "[" .. table.concat (o, ",") .. "]"
		end
		local o = {}; for k, x in pairs (v) do o[#o + 1] = enc (tostring (k)) .. ":" .. enc (x) end
		return "{" .. table.concat (o, ",") .. "}"
	elseif t == "string" then return '"' .. v:gsub ('[%c"\\]', function (c) return string.format ("\\u%04x", c:byte ()) end) .. '"'
	elseif t == "number" then return (v ~= v or v == math.huge or v == -math.huge) and "null" or tostring (v)
	elseif t == "boolean" then return tostring (v) end
	return "null"
end
local function now () return ARDOUR.LuaAPI.monotonic_time () / 1e6 end

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
	for _, p in ipairs (ps) do if p.label == label then return p, "exact" end end
	local l = label:lower ()
	for _, p in ipairs (ps) do if p.label:lower ():find (l, 1, true) then return p, "substring" end end
	return nil
end

local blocks = decode (rd (IN))
local results = {}
for _, b in ipairs (blocks) do
	local r = { type = b.type, plugin = b.lv2 or b.vst3 or b.lua, params = {}, missing = {} }
	local tr
	for t in Session:new_audio_track (1, 1, ARDOUR.RouteGroup (), 1, "p-" .. b.type, ARDOUR.PresentationInfo.max_order,
		ARDOUR.TrackMode.Normal, true):iter () do tr = t end
	local t0 = now ()
	local p
	if b.lv2 then p = ARDOUR.LuaAPI.new_plugin (Session, b.lv2, ARDOUR.PluginType.LV2, "")
	elseif b.vst3 then p = ARDOUR.LuaAPI.new_plugin (Session, b.vst3, ARDOUR.PluginType.VST3, "")
	else p = ARDOUR.LuaAPI.new_luaproc (Session, b.lua) end
	if p:isnil () then
		r.error = "plugin not found"
	else
		tr:add_processor_by_index (p, -1, nil, true)
		r.add_ms = math.floor ((now () - t0) * 1000)
		local pi = p:to_insert ()
		r.audio_in = pi:natural_input_streams ():n_audio ()      -- les entrées/sorties du plugin lui-même : stéréo ?
		r.audio_out = pi:natural_output_streams ():n_audio ()
		local ps = params_of (p:to_insert ():plugin (0))
		r.labels = {}
		for _, x in ipairs (ps) do r.labels[#r.labels + 1] = x.label end
		for _, w in ipairs (b.labels or {}) do
			local q, how = find (ps, w.label)
			if not q then
				r.missing[#r.missing + 1] = w.pid .. " « " .. w.label .. " »"
			else
				-- une valeur DANS la plage du catalogue quand elle est connue, sinon le milieu de la plage du port
				local v = w.value
				if v == nil then v = q.lower + 0.37 * (q.upper - q.lower) end
				if v < q.lower then v = q.lower elseif v > q.upper then v = q.upper end
				ARDOUR.LuaAPI.set_processor_param (p, q.i, v)
				local back = ARDOUR.LuaAPI.get_processor_param (p, q.i)
				r.params[#r.params + 1] = { pid = w.pid, label = w.label, port_label = q.label, how = how,
					lower = q.lower, upper = q.upper, wrote = v, read = back,
					ok = math.abs ((back or 0) - v) <= 1e-3 * math.max (1, math.abs (v)) }
			end
		end
		local x0 = Session:get_xrun_count ()
		local tt = now ()
		for k = 1, 2 do
			p:to_insert ():deactivate (); ARDOUR.LuaAPI.usleep (150000)
			p:to_insert ():activate (); ARDOUR.LuaAPI.usleep (150000)
		end
		r.toggle_ms = math.floor ((now () - tt) * 1000)
		r.xruns = Session:get_xrun_count () - x0
	end
	results[#results + 1] = r
	print (string.format ("%-18s %s", b.type, r.error or ("ok, " .. #r.missing .. " missing")))
end
local f = assert (io.open (OUT, "w")); f:write (enc (results)); f:close ()
