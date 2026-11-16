# SPDX-License-Identifier: GPL-3.0-or-later
"""Le BANC CPU côté REAPER (reaper/Scripts/golem_preview.lua, op « render » + `bench`) joué tel quel sous lupa sur le
REAPER factice (tests/fakereaper.lua) — docs/cpu-budget.md §2. Ce que ce test prouve : la lane est clonée (jamais la
piste vivante rendue), N rendus chronométrés avec ses FX puis N SANS aucun FX, le résultat publié pour le bridge
(times/base/len/nfx/srate/bsize), les clones effacés, le niveau du clone remis à 0 dB (la lane du banc est coupée
dans sa scène). Ce qu'il ne prouve pas : le temps réel d'un vrai rendu — le chronomètre est ici celui du faux REAPER."""
import json
import os
from pathlib import Path
import shutil

import pytest

lupa = pytest.importorskip("lupa")

ROOT = Path(__file__).resolve().parents[1]
FAKE = (ROOT / "tests" / "fakereaper.lua").read_text(encoding="utf-8")
PREVIEW = (ROOT / "reaper" / "Scripts" / "golem_preview.lua").read_text(encoding="utf-8")

# ce que le faux REAPER ne connaît pas encore : la DI posée en item, les réglages de rendu, et le RENDU lui-même —
# il « dure » 0,1 s + 0,05 s par FX des clones (l'horloge factice avance), et écrit le fichier demandé
STUBS = r"""
local F = FAKE
F.proj_info, F.proj_str, F.renders = {}, {}, {}
function reaper.PCM_Source_CreateFromFile(p) return { path = p } end
function reaper.GetMediaSourceLength(_) return 10.0 end
function reaper.AddMediaItemToTrack(tr) local it = { track = tr, info = {} }; tr.items = tr.items or {}; tr.items[#tr.items + 1] = it; return it end
function reaper.AddTakeToMediaItem(it) it.take = {}; return it.take end
function reaper.SetMediaItemTake_Source(take, src) take.src = src end
function reaper.SetMediaItemInfo_Value(it, k, v) it.info[k] = v end
function reaper.GetSet_LoopTimeRange(_, _, a, b, _) F.loop = { a, b } end
function reaper.GetSetProjectInfo(_, k, v, set) if set then F.proj_info[k] = v end return F.proj_info[k] or 0 end
function reaper.GetSetProjectInfo_String(_, k, v, set) if set then F.proj_str[k] = v end return true, F.proj_str[k] or "" end
function reaper.GetAudioDeviceInfo(k, _) if k == "BSIZE" then return true, "192" elseif k == "SRATE" then return true, "48000" end return false, "" end
local main = reaper.Main_OnCommand
function reaper.Main_OnCommand(cmd, x)
  if cmd ~= 42230 then return main(cmd, x) end
  local nfx = 0
  for _, tr in ipairs(F.tracks) do if tr.name:sub(1, 13) == "GoleM:preview" then nfx = nfx + #tr.fx end end
  F.now = F.now + 0.1 + 0.05 * nfx
  F.renders[#F.renders + 1] = nfx
  local f = io.open(F.proj_str.RENDER_FILE .. "/" .. F.proj_str.RENDER_PATTERN .. ".wav", "w"); f:write("RIFF"); f:close()
end
"""


class Lab:
    def __init__(self, tmp):
        self.root, self.res, self.rt = tmp / "root", tmp / "res", tmp / "rt"
        for d in (self.root / "reaper/Scripts", self.root / "presets", self.res, self.rt):
            d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "reaper/Scripts/golem_paths.lua", self.root / "reaper/Scripts/golem_paths.lua")
        (self.res / "golem-root.txt").write_text(str(self.root), encoding="utf-8")
        (self.res / "golem-runtime.txt").write_text(str(self.rt), encoding="utf-8")
        self.L = lupa.LuaRuntime(unpack_returned_tuples=True)
        g = self.L.globals()
        g.FAKE_OS, g.FAKE_RESOURCE = "Other", str(self.res)
        g.FAKE_INSTALLED = self.L.table_from(["ReaGate", "ReaEQ", "ReaPlugs Volume"])
        g.py_mkdir = lambda p: os.makedirs(p, exist_ok=True)
        self.L.execute(FAKE)
        self.L.execute(STUBS)
        self.F = g.FAKE

    def live_lane(self, fx=("ReaGate", "ReaPlugs Volume")):
        """La lane VIVANTE du banc : « Sandbox #Input 1 », armée, avec ses FX et sa sortie matérielle, au plancher."""
        self.L.execute(f"""
          reaper.InsertTrackAtIndex(0, false)
          local tr = reaper.GetTrack(0, 0)
          reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "Sandbox #Input 1", true)
          reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", 1)
          reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 3e-8)
          reaper.CreateTrackSend(tr, nil)
          for _, n in ipairs({{{", ".join(repr(f).replace("'", '"') for f in fx)}}}) do reaper.TrackFX_AddByName(tr, n, false, -1) end
        """)

    def run(self, cmd, ticks=400):
        self.L.execute(PREVIEW)
        self.L.globals().reaper.SetProjExtState(0, "golem", "preview_cmd", json.dumps(cmd))
        for _ in range(ticks):
            self.F.run_defers()
            self.F.now = self.F.now + 0.05
            out = self.root / "presets/.preview.json"
            if out.exists():
                return json.loads(out.read_text(encoding="utf-8"))
        return None


def test_le_banc_rend_n_fois_avec_puis_n_fois_sans_fx_et_publie_les_temps(tmp_path):
    lab = Lab(tmp_path)
    lab.live_lane()
    di = tmp_path / "di.wav"
    di.write_bytes(b"RIFF")
    out = tmp_path / "bench.wav"
    got = lab.run({"action": "preview", "seq": 7, "op": "render", "scene": "cpu-7", "di": str(di), "out": str(out),
                   "tail": 0.25, "chain": "Sandbox #Input 1", "tree": True, "settle": 0.5, "bench": 3, "sr": 48000})
    assert got and got["done"] is True and "error" not in got, got
    times = [float(x) for x in got["times"].split(",")]
    base = [float(x) for x in got["base"].split(",")]
    assert len(times) == 3 and len(base) == 3
    assert min(times) > max(base), "avec les FX du clone, chaque rendu est plus long que sans"
    assert abs(times[0] - (0.1 + 0.05 * 2)) < 0.01 and abs(base[0] - 0.1) < 0.01
    assert got["nfx"] == 2 and got["len"] == pytest.approx(10.25)
    assert got["srate"] == 48000 and got["bsize"] == 192
    assert list(lab.F.renders.values()) == [2, 2, 2, 0, 0, 0], "3 rendus avec les 2 FX, puis 3 sans aucun FX"
    names = [t.name for t in lab.F.tracks.values()]
    assert names == ["Sandbox #Input 1"], "les clones sont effacés, la lane vivante reste"
    live = lab.F.tracks[1]
    assert len(live.fx) == 2 and live.info["I_RECARM"] == 1, "la piste vivante n'est jamais touchée"
    assert not out.exists(), "le WAV du banc ne reste pas"


def test_le_clone_du_banc_rend_a_niveau_et_desarme(tmp_path):
    lab = Lab(tmp_path)
    lab.live_lane()
    # on regarde le clone au premier rendu : niveau remis à 0 dB, désarmé, au master (le master est vide)
    lab.L.execute(r"""
      local F = FAKE
      local inner = reaper.Main_OnCommand
      function reaper.Main_OnCommand(cmd, x)
        if cmd == 42230 and not F.clone_seen then
          for _, tr in ipairs(F.tracks) do
            if tr.name == "GoleM:preview" then F.clone_seen = { vol = tr.info.D_VOL, arm = tr.info.I_RECARM, main = tr.info.B_MAINSEND } end
          end
        end
        return inner(cmd, x)
      end
    """)
    di = tmp_path / "di.wav"
    di.write_bytes(b"RIFF")
    got = lab.run({"action": "preview", "seq": 8, "op": "render", "scene": "cpu-8", "di": str(di),
                   "out": str(tmp_path / "b.wav"), "tail": 0.25, "chain": "Sandbox #Input 1", "tree": True,
                   "settle": 0.5, "bench": 2})
    assert got and not got.get("error"), got
    seen = lab.F.clone_seen
    assert seen.vol == 1 and seen.arm == 0 and seen.main == 1


def test_un_rendu_ordinaire_ne_publie_pas_de_temps(tmp_path):
    """Sans `bench`, l'op « render » reste celle des démos : un rendu, le WAV, aucun chronomètre."""
    lab = Lab(tmp_path)
    lab.live_lane()
    di = tmp_path / "di.wav"
    di.write_bytes(b"RIFF")
    out = tmp_path / "demo.wav"
    got = lab.run({"action": "preview", "seq": 9, "op": "render", "scene": "A", "di": str(di), "out": str(out),
                   "tail": 1.0, "chain": "Sandbox #Input 1", "tree": True, "settle": 0.5})
    assert got and got["wav"] == str(out) and "times" not in got
    assert list(lab.F.renders.values()) == [2] and out.exists()
