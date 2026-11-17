# SPDX-License-Identifier: GPL-3.0-or-later
"""Les processeurs MIDI écrits pour le Golem Engine (DSP Lua d'Ardour, dépôt golem-engine, golem/engine/scripts) rejoués
hors moteur sous lupa : la zone de clavier et l'arpégiateur (docs/ardour-plan.md §7d, lot 2). Sautés là où le moteur
n'est pas construit — ce dépôt ne porte pas ces fichiers."""
import os

import pytest

lupa = pytest.importorskip("lupa")
SCRIPTS = os.path.join(os.environ.get("GOLEM_ENGINE_DIR") or os.path.expanduser("~/golem-engine"), "golem", "engine", "scripts")


def load(name):
    path = os.path.join(SCRIPTS, name)
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("function ardour(t) end")
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read())
    lua.execute("dsp_init(48000)")
    run = lua.eval("""function(ctrl, evs, n)
      CtrlPorts = { array = function() return ctrl end }
      midiin = evs; midiout = {}
      dsp_run(nil, nil, n)
      local o = {}
      for i, e in ipairs(midiout) do o[#o + 1] = string.format("%d:%02X.%d.%d", e.time, e.data[1], e.data[2], e.data[3] or 0) end
      return table.concat(o, " ")
    end""")
    table = lua.eval("function(...) return {...} end")
    event = lua.eval("function(t, a, b, c) return { time = t, data = { a, b, c } } end")
    return (lambda ctrl, evs=(), n=1024: run(table(*ctrl), table(*[event(*e) for e in evs]), n))


def test_la_zone_filtre_transpose_et_laisse_passer_le_reste():
    run = load("golem_zone.lua")
    zone = (48, 72, -12)
    assert run(zone, [(1, 0x90, 60, 100), (2, 0x90, 30, 100), (3, 0xB0, 64, 127)]) == "1:90.48.100 3:B0.64.127"
    # le note-off suit la note ENVOYÉE, même si la transposition a changé entre-temps ; celui d'une note éliminée aussi
    assert run((48, 72, 0), [(1, 0x80, 60, 0), (2, 0x80, 30, 0)]) == "1:80.48.0"
    assert run((72, 48, 0), [(1, 0x90, 50, 90)]) == "1:90.50.90"          # bornes inversées tolérées


def test_l_arpegiateur_deroule_les_notes_tenues_en_mesure():
    run = load("golem_arp.lua")
    on = (1, 4, 3, 0, 0.5, 120)            # doubles-croches à 120 : un pas = 6000 échantillons ; monte puis descend
    assert run(on, [(1, 0x90, 60, 100), (1, 0x90, 64, 90), (1, 0x90, 67, 80), (5, 0xB0, 64, 127)]) == "1:90.60.100 5:B0.64.127"
    notes = []
    for _ in range(40):
        notes += [e.split(":")[1] for e in run(on).split() if e.split(":")[1].startswith("90.")]
    assert notes[:6] == ["90.64.90", "90.67.80", "90.64.90", "90.60.100", "90.64.90", "90.67.80"]   # la vélocité jouée
    run(on, [(1, 0x80, 60, 0), (1, 0x80, 64, 0), (1, 0x80, 67, 0)])
    tail = " ".join(run(on) for _ in range(12))
    assert "90." not in tail                                            # plus rien de tenu : plus de note
    off = (0, 4, 3, 0, 0.5, 120)
    assert run(off, [(3, 0x90, 60, 100)]) == "3:90.60.100"              # coupé : tout passe


def test_le_metronome_compte_accentue_et_sait_se_taire():
    path = os.path.join(SCRIPTS, "golem_click.lua")
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("function ardour(t) end")
    lua.execute("""
      SHM = {0, 0}
      self = { shmem = function() return { allocate = function() end, clear = function() end,
                                           atomic_set_int = function(_, i, v) SHM[i + 1] = v end } end }
      ARDOUR = { DSP = { memset = function(buf, v, n) for i = 1, n do buf.a[i] = v end end } }
    """)
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read())
    lua.execute("dsp_init(48000)")
    run = lua.eval("""function(ctrl, n, evs)
      CtrlPorts = { array = function() return ctrl end }
      midiin = evs or {}
      local o1, o2 = { a = {} }, { a = {} }
      o1.array = function() return o1.a end; o2.array = function() return o2.a end
      dsp_run(nil, { o1, o2 }, n)
      local first, peak = 0, 0
      for i = 1, n do local v = math.abs(o1.a[i]); if v > 0 and first == 0 then first = i end; if v > peak then peak = v end end
      return first, peak, SHM[1], SHM[2]
    end""")
    table = lua.eval("function(...) return {...} end")
    # 7/8 en 3+2+2 (masque 41) à 120 : une croche = 12000 échantillons ; un cycle de 12000 = un pas
    on = table(1, 0, 7, 1, 8, 41, 0, 120, 0)
    peaks = [round(run(on, 12000)[1], 2) for _ in range(8)]
    # le « 1 » et les débuts de groupe (pulsations 0, 3, 5) à plein niveau, les autres à -3 dB ; puis la mesure reprend
    assert [p > 0.8 for p in peaks] == [True, False, False, True, False, True, False, True], peaks
    assert all(0.6 < p < 0.75 for p in (peaks[1], peaks[2], peaks[4], peaks[6]))
    first, peak, ticks, tempo = run(on, 12000)
    assert ticks == 9 and tempo == 12000                               # témoins : pas émis, tempo × 100
    # l'horloge muette compte sans sonner ; tout éteint, plus rien n'avance
    first, peak, ticks2, _ = run(table(0, 0, 7, 1, 8, 41, 1, 120, 0), 48000)
    assert peak == 0 and ticks2 > ticks
    assert run(table(0, 0, 7, 1, 8, 41, 0, 120, 0), 48000)[2] == ticks2
    # LE CLICK D'UNE GRILLE (Grid = 1) : il ne compte plus, il SONNE quand la grille lui envoie une note (canal 16)
    grid = table(1, 0, 4, 1, 4, 1, 0, 120, 1)
    event = lua.eval("function(t, a, b, c) return { time = t, data = { a, b, c } } end")
    assert run(grid, 48000)[1] == 0                                     # rien reçu : rien ne sonne, même sur deux temps
    first, peak, ticks3, _ = run(grid, 4800, table(event(1000, 0x9F, 76, 100), event(2000, 0x90, 76, 100)))
    assert first == 1001 and peak > 0.8 and ticks3 == ticks2 + 1        # le « 1 » à sa place (le sinus part de zéro) ; l'autre canal est ignoré
    first, peak, _, _ = run(grid, 4800, table(event(10, 0x9F, 78, 100)))
    assert first == 11 and 0.3 < peak < 0.45                            # une subdivision, à -8 dB


def test_le_sequenceur_de_batterie_varie_a_la_barre_place_un_fill_et_joue_un_morceau():
    path = os.path.join(SCRIPTS, "golem_drumseq.lua")
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("function ardour(t) end")
    lua.execute("""
      MEM = {}
      for i = 1, 256 + 14 * 8192 do MEM[i] = 0 end
      SHM = { allocate = function() end, clear = function() end, to_int = function() return { array = function() return MEM end } end,
              atomic_get_int = function(_, i) return MEM[i + 1] end, atomic_set_int = function(_, i, v) MEM[i + 1] = v end }
      self = { shmem = function() return SHM end }
    """)
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read())
    lua.execute("dsp_init(48000)")
    put, get = lua.eval("function(i, v) MEM[i + 1] = v end"), lua.eval("function(i) return MEM[i + 1] end")
    run = lua.eval("""function(n)
      CtrlPorts = { array = function() return { 120 } end }
      midiin = {}; midiout = {}
      dsp_run(nil, nil, n)
      local o = {}
      for i, e in ipairs(midiout) do o[#o + 1] = e.data[2] end
      return table.concat(o, ",")
    end""")

    def slot(n, events):
        base = 256 + n * 8192
        put(base, len(events)), put(base + 1, 3840), put(base + 2, 3840)
        for k, (tick, note, vel) in enumerate(events):
            for j, v in enumerate((tick, note, vel, 0)):
                put(base + 8 + k * 4 + j, v)

    def cmd(op, s=0):
        put(1, op), put(2, s), put(0, get(0) + 1)                 # le nonce en dernier

    def bars(n):                                                  # une mesure à 120 = 96000 échantillons
        out = []
        for _ in range(n):
            notes = []
            for size in [1024] * 93 + [96000 - 93 * 1024]:
                r = run(size)
                notes += r.split(",") if r else []
            out.append("".join({"36": "K", "38": "S", "42": "h", "45": "T"}[x] for x in notes))
        return out

    slot(0, [[0, 36, 100], [960, 38, 90], [1920, 36, 100], [2880, 38, 90]])
    slot(1, [[0, 42, 80], [1920, 42, 80]])
    slot(2, [[0, 45, 120]])
    put(3, 960)
    cmd(1, 0)
    assert bars(2) == ["KSKS", "KSKS"] and get(8) == 1
    cmd(2, 1)
    assert bars(2) == ["KSKS", "hh"]                              # la variation attend la barre
    cmd(3, 2)
    assert bars(3) == ["hh", "T", "hh"] and get(10) == 0          # le fill une fois, puis le groove
    put(16, 2), put(17, 1)
    for i, v in enumerate((0, 2, 1, 1)):
        put(18 + i, v)
    cmd(4)
    assert bars(4) == ["KSKS", "KSKS", "hh", ""] and get(8) == 0  # A deux fois, B une fois, puis silence net
    cmd(1, 1)
    cmd(0)
    assert bars(1) == [""]


def test_le_lecteur_de_standards_joue_chaque_partie_sur_son_canal_et_ne_laisse_aucune_note():
    path = os.path.join(SCRIPTS, "golem_chordseq.lua")
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("function ardour(t) end")
    lua.execute("""
      MEM = {}
      for i = 1, 64 + 16384 * 4 do MEM[i] = 0 end
      SHM = { allocate = function() end, clear = function() end, to_int = function() return { array = function() return MEM end } end,
              atomic_get_int = function(_, i) return MEM[i + 1] end, atomic_set_int = function(_, i, v) MEM[i + 1] = v end }
      self = { shmem = function() return SHM end }
    """)
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read())
    lua.execute("dsp_init(48000)")
    put, get = lua.eval("function(i, v) MEM[i + 1] = v end"), lua.eval("function(i) return MEM[i + 1] end")
    run = lua.eval("""function(n)
      CtrlPorts = { array = function() return { 120 } end }
      midiin = {}; midiout = {}
      dsp_run(nil, nil, n)
      local o, last = {}, 0
      for i, e in ipairs(midiout) do
        assert(e.time >= last, "événements dans le désordre")
        last = e.time
        o[#o + 1] = string.format("%02X.%d.%d", e.data[1], e.data[2], e.data[3])
      end
      return table.concat(o, " ")
    end""")
    # deux temps : accord (lane 0), basse (1), batterie (2), click (3), pompe (4) ; des notes tenues jusqu'à la fin
    events = [(0, 48, 90, 0), (0, 36, 100, 1), (0, 42, 80, 2), (0, 76, 100, 3), (960, 36, 0, 1), (960, 38, 100, 1), (960, 50, 90, 4)]
    for k, e in enumerate(events):
        for j, v in enumerate(e):
            put(64 + k * 4 + j, v)
    put(16, len(events)), put(17, 1920), put(18, 3840), put(19, 1), put(3, 960)
    put(2, 1), put(1, 1), put(0, 1)                                   # boucle, joue, puis le nonce
    assert run(24000) == "90.48.90 91.36.100 99.42.80 9F.76.100"      # canaux 1, 2, 10 et 16
    second = run(24000)
    assert second.startswith("81.36.0 91.38.100 93.50.90")            # la pompe sur le canal 4
    # fin de grille : tout ce qui sonnait s'arrête (accord, basse, batterie, click, pompe) avant le chorus suivant
    assert {x.split(".")[0] for x in second.split()[3:]} == {"80", "81", "83", "89", "8F"}
    assert run(24000).startswith("90.48.90") and get(8) == 1 and get(9) == 0 and get(10) == 1   # il a rebouclé : un temps joué dans le nouveau chorus
    put(1, 0), put(0, 2)
    assert run(1024) != "" and get(8) == 0 and run(24000) == ""       # stop : les note-off, puis plus rien
    put(2, 0), put(1, 1), put(0, 3)
    run(24000), run(24000)
    assert get(8) == 0                                                 # sans boucle : il s'arrête seul à la fin


def test_l_accordeur_lit_une_basse_cinq_cordes_comme_une_guitare_et_se_tait_dans_le_silence():
    path = os.path.join(SCRIPTS, "golem_tuner.lua")
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("function ardour(t) end")
    lua.execute("""
      MEM = { 0, 0, 0, 0 }
      SHM = { allocate = function() end, clear = function() end, atomic_set_int = function(_, i, v) MEM[i + 1] = v end }
      self = { shmem = function() return SHM end }
    """)
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read())
    lua.execute("dsp_init(48000)")
    # une note riche en harmoniques (fondamentale + 2e + 3e), par cycles de 192 échantillons — le buffer d'un rack
    run = lua.eval("""function(freq, amp, cycles)
      local ph = 0
      for c = 1, cycles do
        local a = {}
        for i = 1, 192 do a[i] = amp * (math.sin(ph) + 0.4 * math.sin(2 * ph) + 0.2 * math.sin(3 * ph)); ph = ph + 2 * math.pi * freq / 48000 end
        local buf = { array = function() return a end, sameinstance = function() return true end }
        dsp_run({ buf }, { buf }, 192)
      end
      return MEM[1] / 1000, MEM[2] / 1000, MEM[3] / 1000, MEM[4]
    end""")
    for freq, midi in ((30.87, 23), (41.20, 28), (82.41, 40), (110.0, 45), (329.63, 64), (659.26, 76)):   # si grave … mi aigu
        f, m, conf, _ = run(freq, 0.1, 400)
        assert abs(f - freq) < 0.05 and round(m) == midi and abs(m - midi) < 0.005 and conf > 0.9, (freq, f, m, conf)
    _, _, conf, seq = run(110.0, 0.0001, 300)                           # sous -62 dBFS : pas de note
    assert conf == 0 and seq > 0


def test_le_lecteur_de_phrase_joue_une_fois_filtre_un_canal_et_arrete_ses_notes():
    path = os.path.join(SCRIPTS, "golem_midiplay.lua")
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("function ardour(t) end")
    lua.execute("""
      MEM = {}
      for i = 1, 64 + 32768 * 4 do MEM[i] = 0 end
      SHM = { allocate = function() end, clear = function() end, to_int = function() return { array = function() return MEM end } end,
              atomic_get_int = function(_, i) return MEM[i + 1] end, atomic_set_int = function(_, i, v) MEM[i + 1] = v end }
      self = { shmem = function() return SHM end }
    """)
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read())
    lua.execute("dsp_init(48000)")
    put, get = lua.eval("function(i, v) MEM[i + 1] = v end"), lua.eval("function(i) return MEM[i + 1] end")
    run = lua.eval("""function(ch, n)
      CtrlPorts = { array = function() return { ch } end }
      midiin = {}; midiout = {}
      dsp_run(nil, nil, n)
      local o = {}
      for i, e in ipairs(midiout) do o[#o + 1] = string.format("%d:%02X.%d.%d", e.time, e.data[1], e.data[2], e.data[3]) end
      return table.concat(o, " ")
    end""")
    for k, e in enumerate([(0, 0x90, 60, 100), (100, 0x99, 36, 110), (2000, 0x80, 60, 0), (5000, 0x90, 62, 90)]):
        for j, v in enumerate(e):
            put(64 + k * 4 + j, v)
    put(16, 4), put(1, 1), put(0, 1)
    assert run(0, 1024) == "1:90.60.100 101:99.36.110"               # à l'échantillon près
    assert run(0, 1024) == "977:80.60.0" and run(0, 4096) == "2953:90.62.90" and get(8) == 0   # une fois, puis fini
    put(0, 2)                                                        # relancé sur le canal 10 seul : la note restée tenue s'arrête d'abord
    assert run(10, 8192) == "1:80.62.0 1:89.36.0 101:99.36.110"
    put(1, 0), put(0, 3)
    assert run(0, 64) == "1:89.36.0" and get(8) == 0                 # stop : plus aucune note tenue


# ── le looper (golem_looper.lua) : le contrat de golem_super8, simulé sur un faux hôte ───────────────────────────────
_LOOPER_HOST = r"""
function ardour(t) end
MEM = {}
local function view(off) -- un « pointeur » dans MEM : array() rend une table-proxy 1-based
  local v = { off = off }
  function v:array() return setmetatable({}, { __index = function(_, i) return MEM[off + i] or 0 end, __newindex = function(_, i, x) MEM[off + i] = x end }) end
  function v:offset(k) return view(off + k) end
  return v
end
SHM = { allocate = function(_, n) SIZE = n end, to_int = function(_, o) return view(o) end, to_float = function(_, o) return view(o) end }
self = { shmem = function() return SHM end }
ARDOUR = { DSP = {
  memset = function(d, x, n) local a = d:array() for i = 1, n do a[i] = x end end,
  copy_vector = function(d, s, n) local a, b = d:array(), s:array() for i = 1, n do a[i] = b[i] end end,
  mix_buffers_no_gain = function(d, s, n) local a, b = d:array(), s:array() for i = 1, n do a[i] = a[i] + b[i] end end,
  mix_buffers_with_gain = function(d, s, n, g) local a, b = d:array(), s:array() for i = 1, n do a[i] = a[i] + b[i] * g end end,
  compute_peak = function(s, n, c) local b = s:array() for i = 1, n do if math.abs(b[i]) > c then c = math.abs(b[i]) end end return c end,
} }
IO = 10000000   -- les tampons d'entrée/sortie, loin de la mémoire du looper
CTRL = { 0, 0, 0, 0, 0, 0, 0, 1 }
CtrlPorts = { array = function() return CTRL end }
function run(n, vals)   -- vals[paire] = valeur constante en entrée ; rend la sortie gauche (premier, dernier, max)
  local ins, outs = {}, {}
  for c = 1, 8 do ins[c] = view(IO + c * 10000); local a = ins[c]:array(); local x = vals[(c + 1) // 2] or 0; for i = 1, n do a[i] = x end end
  outs[1], outs[2] = view(IO + 100000), view(IO + 110000)
  dsp_run(ins, outs, n)
  local o, mx = outs[1]:array(), 0
  for i = 1, n do if math.abs(o[i]) > mx then mx = math.abs(o[i]) end end
  return o[1], o[n], mx
end
function S(i) return MEM[i + 1] or 0 end
"""


def _looper(rate=1000):
    path = os.path.join(SCRIPTS, "golem_looper.lua")
    if not os.path.isfile(path):
        pytest.skip("Golem Engine not built on this machine")
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(_LOOPER_HOST)
    with open(path, encoding="utf-8") as f:
        lua.execute(f.read().replace("local MAX_S = 120", "local MAX_S = 60"))
    lua.execute(f"dsp_init({rate})")
    g, seq = lua.globals(), [0]

    def cmd(n):
        seq[0] += 1
        g.CTRL[1] = seq[0] * 128 + n

    def run(blocks, **pairs):                      # blocs de 100 échantillons ; p1=0.5 : la paire 1 reçoit 0,5
        out = None
        for _ in range(blocks):
            out = lua.eval("run")(100, lua.table_from({int(k[1:]): v for k, v in pairs.items()}))
        return out

    def state():
        return {"len": g.S(0), "pos": g.S(1), "first": g.S(2), "ci": g.S(4), "ci_slot": g.S(5),
                "st": [g.S(8 + p * 4) for p in range(4)], "has": [g.S(9 + p * 4) for p in range(4)]}
    return g, cmd, run, state


def test_looper_la_premiere_boucle_pose_la_longueur_et_les_autres_la_suivent():
    g, cmd, run, state = _looper()
    cmd(36)
    run(10, p1=0.5)
    assert state()["st"] == [2, 0, 0, 0] and state()["first"] == 1 and state()["len"] == 1000    # la longueur court
    cmd(37)
    run(10)
    s = state()
    assert s["len"] == 1000 and s["first"] == 0 and s["st"] == [1, 0, 0, 0] and s["has"] == [1, 0, 0, 0]
    assert run(1)[2] == pytest.approx(0.5, abs=0.01)                     # la boucle joue ce qu'elle a reçu (son premier bloc : le fondu d'entrée)
    cmd(41)                                                              # une deuxième boucle, sur 300 échantillons seulement
    run(3, p2=0.25)
    cmd(42)
    run(7)
    assert state()["len"] == 1000 and state()["st"] == [1, 1, 0, 0]
    assert run(2)[2] == pytest.approx(0.75, abs=0.01)                    # dans sa région : les deux boucles
    assert run(3)[2] == pytest.approx(0.5)                               # hors de sa région : du silence, pas la mémoire brute
    cmd(37)
    run(5)
    assert state()["st"] == [0, 1, 0, 0]                                 # play sur une boucle qui joue : stop
    cmd(21)
    run(1)
    assert state()["st"] == [1, 1, 0, 0]                                 # tout jouer : celles qui ont du contenu
    cmd(21)
    run(1)
    assert state()["st"] == [0, 0, 0, 0]                                 # tout arrêter


def test_looper_overdub_niveau_effacement():
    g, cmd, run, state = _looper()
    cmd(36)
    run(10, p1=0.5)
    cmd(37)
    run(10)
    cmd(36)                                                              # rec sur une boucle qui joue : une couche
    run(1, p1=0.1)
    assert state()["st"][0] == 2 and state()["first"] == 0               # « dub » : firstrec ne revient pas
    run(9, p1=0.1)
    cmd(36)
    run(10)
    assert state()["st"][0] == 1 and run(5)[2] == pytest.approx(0.6, abs=0.01)   # la couche s'ajoute
    g.CTRL[4] = -60                                                      # « GoleM Loop 1 dB » : muette
    run(3)
    assert run(1)[2] == 0
    g.CTRL[4] = -6
    run(3)
    assert run(1)[2] == pytest.approx(0.6 * 10 ** (-6 / 20), abs=0.01)   # le niveau s'applique à la lecture
    cmd(24)
    run(1)
    assert state()["len"] == 0 and state()["has"] == [0, 0, 0, 0]        # la dernière boucle effacée : plus de longueur
    cmd(36)
    run(10, p1=0.5)
    cmd(20)
    run(1)
    assert state() == {"len": 0, "pos": 0, "first": 0, "ci": 0, "ci_slot": 0, "st": [0, 0, 0, 0], "has": [0, 0, 0, 0]}


def test_looper_decompte_et_calage_a_la_barre():
    g, cmd, run, state = _looper()                                      # 120 BPM, 4 temps, 1000 Hz : mesure = 2000
    g.CTRL[2], g.CTRL[3] = 120, 43                                       # calage + décompte
    cmd(36)
    out = run(1, p1=0.5)
    assert state()["ci"] == 4 and state()["ci_slot"] == 1 and state()["st"][0] == 0 and out[2] > 0.1   # le tic du décompte
    run(19, p1=0.5)
    assert state()["st"][0] == 0 and state()["len"] == 0                 # la mesure n'est pas finie : rien n'enregistre
    run(18, p1=0.5)
    assert state()["st"][0] == 2 and state()["len"] == 1800              # partie sur le 1
    cmd(37)                                                              # fermée un peu tôt : elle attend la barre
    run(1, p1=0.5)
    assert state()["st"][0] == 2
    run(2, p1=0.5)
    assert state()["len"] == 2000 and state()["st"][0] == 1 and state()["pos"] == 100
    cmd(20)
    run(1)
    g.CTRL[3] = 45                                                       # calage + rec→dub, sans décompte
    cmd(41)
    run(22, p2=0.5)
    cmd(42)                                                              # fermée un peu tard : coupée à la barre, en phase
    run(1, p2=0.5)
    s = state()
    assert s["len"] == 2000 and s["pos"] == 300 and s["st"][1] == 2 and s["first"] == 0   # et la couche s'enchaîne
    cmd(36)                                                              # un décompte ne part que sur un looper VIDE
    g.CTRL[3] = 43
    run(1)
    assert state()["ci"] == 0 and state()["st"][0] == 2
