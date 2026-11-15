# SPDX-License-Identifier: GPL-3.0-or-later
"""Le FILET de la boîte à rythmes (2026-11-15) : un kit dont la table n'est pas General MIDI reçoit les grooves (GM)
traduits par le nom des pièces. Le bridge met `notemap` dans le play (drums.gm_notemap), golem_drums réécrit les notes
en chargeant la banque. Le vrai golem_drums.lua tourne sous lupa sur le REAPER factice (tests/fakereaper.lua)."""
import json
from pathlib import Path
import shutil
import struct
import sys

import pytest

lupa = pytest.importorskip("lupa")

ROOT = Path(__file__).resolve().parents[1]
FAKE = (ROOT / "tests" / "fakereaper.lua").read_text(encoding="utf-8")
SLOT_BASE, EV_OFF, EV_STRIDE = 256, 8, 4


def _smf(notes, ppq=480):
    """Un .mid format 0 : une noire par note, canal 10."""
    ev = b""
    for n in notes:
        ev += b"\x00" + bytes([0x99, n, 100]) + bytes([0x83, 0x60]) + bytes([0x89, n, 0])
    ev += b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(ev)) + ev


@pytest.fixture
def drums(tmp_path):
    root, res = tmp_path / "root", tmp_path / "res"
    for d in (root / "reaper/Scripts", root / "presets", root / "library/grooves", res):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("golem_paths.lua", "golem_drums.lua"):
        shutil.copy2(ROOT / "reaper/Scripts" / f, root / "reaper/Scripts" / f)
    (res / "golem-root.txt").write_text(str(root), encoding="utf-8")
    (res / "golem-runtime.txt").write_text(str(tmp_path / "rt"), encoding="utf-8")
    (root / "library/grooves/rock.mid").write_bytes(_smf([36, 48, 52, 50]))
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = L.globals()
    g.FAKE_OS = "Win64" if sys.platform == "win32" else "Other"
    g.FAKE_RESOURCE = str(res).replace("\\", "/")
    g.FAKE_INSTALLED = L.table_from(["JS:golem/golem_drumseq"])
    L.execute(FAKE)
    L.execute((root / "reaper/Scripts/golem_drums.lua").read_text(encoding="utf-8"))
    F = g.FAKE

    def play(seq, **extra):
        cmd = {"action": "drums", "op": "play", "block": "d1", "kit": "", "patterns": ["library/grooves/rock.mid"],
               "fills": [], "idx": 0, "seq": seq, **extra}
        L.globals().reaper.SetProjExtState(0, "golem", "drums_cmd", json.dumps(cmd))
        F.run_defers()
        mem = F.gmem["golem_drums"]
        nev = int(mem[SLOT_BASE])
        return [int(mem[SLOT_BASE + EV_OFF + k * EV_STRIDE + 1]) for k in range(nev)]
    return play


def test_un_kit_gm_joue_les_notes_du_groove_telles_quelles(drums):
    assert drums(1) == [36, 48, 52, 50]


def test_un_kit_non_gm_recoit_les_notes_traduites_et_une_piece_absente_se_tait(drums):
    assert drums(1, notemap={"48": 45, "52": 60, "50": -1}) == [36, 45, 60]


def test_changer_de_traduction_recharge_la_banque(drums):
    assert drums(1, notemap={"52": 60}) == [36, 48, 60, 50]
    assert drums(2) == [36, 48, 52, 50]                       # même groove, kit GM : la banque est relue
