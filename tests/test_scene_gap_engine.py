# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/check-scene-gap.py sous le Golem Engine : les sondes GoleM FX Gapmeter (golem-fx) envoient leurs mesures en
OSC/UDP ; l'écouteur en refait l'instantané que golem_apply.lua écrit sous REAPER (golem-gaps.json)."""
import importlib.util
import socket
import struct
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("check_scene_gap", ROOT / "tools" / "check-scene-gap.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _osc(addr, tags, *args):
    def pad(b):
        b += b"\0"
        return b + b"\0" * (-len(b) % 4)
    out = pad(addr.encode()) + pad(("," + tags).encode())
    for t, v in zip(tags, args):
        out += struct.pack(">i", v) if t == "i" else struct.pack(">d", v)
    return out


def test_l_ecouteur_refait_l_instantane_de_reaper():
    m = _tool()
    lst = m.GapListener(["G#merge", "G/lane-a"])
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(_osc("/gfx/gapmeter", "idddid", 0, 12.5, -20.0, 0.0, 1, 30.0), ("127.0.0.1", lst.port))
    s.sendto(_osc("/gfx/gapmeter", "idddid", 1, 12.48, -25.0, 4.0, 0, 0.0), ("127.0.0.1", lst.port))
    s.sendto(_osc("/gfx/gap", "iidd", 0, 0, 12.2, 30.0), ("127.0.0.1", lst.port))
    for _ in range(100):
        snap = lst.snapshot()
        if snap and len(snap["slots"]) == 2 and snap["slots"][0]["gaps"]:
            break
        time.sleep(0.01)
    rows = {r["track"]: r for r in snap["slots"]}
    assert rows["G#merge"]["clk"] == 12.5 and rows["G#merge"]["n"] == 1 and rows["G#merge"]["max"] == 30.0
    assert rows["G#merge"]["gaps"] == [[0, 30.0, 12.2]]                      # [indice, durée ms, fin s]
    assert rows["G/lane-a"]["env"] == -25.0 and rows["G/lane-a"]["run"] == 4.0
