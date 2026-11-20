# SPDX-License-Identifier: GPL-3.0-or-later
"""Le FILL avant la variation (2026-11-20, demande golem-fm validée par Raph) : l'op fill existait sans rien pour
l'appeler. Désormais le maintien qui passe à la variation suivante joue d'abord le fill du bloc — à la prochaine barre,
en entier — puis la variation ; sans fill, rien ne change. Un seul message : op fill + then_idx, le séquenceur (JSFX,
Lua du Golem Engine) repart sur ce groove-là au lieu du courant."""
import json
from pathlib import Path
import shutil
import struct
import sys
from unittest import mock

import pytest

from bridge import drums

ROOT = Path(__file__).resolve().parents[1]


def _ctl(playing=True, idx=0):
    sent = []
    dc = drums.DrumControl(sent.append)
    dc._state["d"] = {"playing": playing, "idx": idx}
    return dc, sent


def _hold(dc, **kw):
    t = [100.0]
    with mock.patch.object(drums._time, "monotonic", lambda: t[0]), \
            mock.patch.object(drums.threading, "Timer", mock.MagicMock()):
        dc.on_edge(1, True, block="d", **kw)
        t[0] += drums.VAR_S + 0.1
        dc.on_edge(1, False)


def test_le_maintien_joue_le_fill_puis_la_variation_suivante():
    dc, sent = _ctl(idx=0)
    _hold(dc, patterns=["a", "b", "c"], fills=["f"])
    assert sent == [{"action": "drums", "op": "fill", "block": "d", "fill_idx": 0, "then_idx": 1}]
    assert dc.snapshot()["d"]["idx"] == 1


def test_le_fill_est_celui_du_groove_qu_on_quitte():
    dc, sent = _ctl(idx=1)
    _hold(dc, patterns=["a", "b", "c"], fills=["f0", "f1"])
    assert sent[-1]["fill_idx"] == 1 and sent[-1]["then_idx"] == 2
    dc._state["d"]["idx"] = 2
    _hold(dc, patterns=["a", "b", "c"], fills=["f0", "f1"])               # 2 % 2 : le premier fill, retour au groove 0
    assert sent[-1]["fill_idx"] == 0 and sent[-1]["then_idx"] == 0


def test_sans_fill_la_variation_reste_celle_d_aujourd_hui():
    dc, sent = _ctl(idx=0)
    _hold(dc, patterns=["a", "b"], fills=[])
    assert sent == [{"action": "drums", "op": "variation", "block": "d", "idx": 1}]


def test_a_l_arret_l_ecran_lance_la_variation_sans_fill():
    """Rien ne joue : un fill serait ignoré par le séquenceur ; la variation, elle, lance le groove."""
    dc, sent = _ctl(playing=False, idx=0)
    dc.variation("d", ["a", "b"], ["f"])
    assert sent == [{"action": "drums", "op": "variation", "block": "d", "idx": 1}]


def test_l_ecran_passe_par_le_meme_fill():
    dc, sent = _ctl(idx=0)
    dc.variation("d", ["a", "b"], ["f"])
    assert sent[-1]["op"] == "fill" and sent[-1]["then_idx"] == 1
    src = (ROOT / "bridge" / "app.py").read_text(encoding="utf-8")
    assert '_drums_ctl.variation(drm.get("block"), drm.get("patterns"), drm.get("fills"))' in src


def test_les_libelles_disent_le_fill():
    """La note du bloc ne promet plus « tap = FILL » (le tap arrête depuis le 2026-10-13)."""
    cat = json.loads((ROOT / "library" / "catalog" / "effects.json").read_text(encoding="utf-8"))
    effects = cat["effects"] if isinstance(cat["effects"], list) else list(cat["effects"].values())
    note = next(e for e in effects if isinstance(e, dict) and e.get("type") == "drums")["note"]
    assert "tap = FILL" not in note and "EN COURS+tap = STOP" in note and "fill" in note.lower()


# ── le vrai golem_drums.lua (REAPER) sous lupa : ce qu'il écrit au séquenceur ──────────────────────────────────────
lupa = pytest.importorskip("lupa")
FAKE = (ROOT / "tests" / "fakereaper.lua").read_text(encoding="utf-8")


def _smf(notes, ppq=480):
    ev = b""
    for n in notes:
        ev += b"\x00" + bytes([0x99, n, 100]) + bytes([0x83, 0x60]) + bytes([0x89, n, 0])
    ev += b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(ev)) + ev


@pytest.fixture
def reaper_drums(tmp_path):
    root, res = tmp_path / "root", tmp_path / "res"
    for d in (root / "reaper/Scripts", root / "presets", root / "library/grooves", res):
        d.mkdir(parents=True, exist_ok=True)
    for f in ("golem_paths.lua", "golem_drums.lua"):
        shutil.copy2(ROOT / "reaper/Scripts" / f, root / "reaper/Scripts" / f)
    (res / "golem-root.txt").write_text(str(root), encoding="utf-8")
    (res / "golem-runtime.txt").write_text(str(tmp_path / "rt"), encoding="utf-8")
    for name, notes in (("a", [36]), ("b", [38]), ("c", [42]), ("f", [49])):
        (root / f"library/grooves/{name}.mid").write_bytes(_smf(notes))
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    g = L.globals()
    g.FAKE_OS = "Win64" if sys.platform == "win32" else "Other"
    g.FAKE_RESOURCE = str(res).replace("\\", "/")
    g.FAKE_INSTALLED = L.table_from(["JS:golem/golem_drumseq"])
    L.execute(FAKE)
    L.execute((root / "reaper/Scripts/golem_drums.lua").read_text(encoding="utf-8"))
    F = g.FAKE
    seq = [0]

    def send(**cmd):
        seq[0] += 1
        g.reaper.SetProjExtState(0, "golem", "drums_cmd", json.dumps({"action": "drums", "block": "d1", "seq": seq[0], **cmd}))
        F.run_defers()
        mem = F.gmem["golem_drums"]
        return {"op": int(mem[1]), "slot": int(mem[2]), "ret": int(mem[6] or 0)}
    send(op="play", kit="", idx=0, patterns=[f"library/grooves/{n}.mid" for n in "abc"], fills=["library/grooves/f.mid"])
    return send


def test_reaper_un_fill_qui_mene_a_une_variation_dit_ou_revenir(reaper_drums):
    assert reaper_drums(op="fill", fill_idx=0, then_idx=2) == {"op": 3, "slot": 3, "ret": 3}   # fill = slot 3, retour au 2
    assert reaper_drums(op="fill", fill_idx=0) == {"op": 3, "slot": 3, "ret": 0}               # fill seul : groove courant
    assert reaper_drums(op="variation", idx=1)["op"] == 2


def test_les_deux_sequenceurs_lisent_le_retour_du_fill():
    jsfx = (ROOT / "reaper" / "Effects" / "golem_drumseq.jsfx").read_text(encoding="utf-8")
    assert "CTL_RET=6" in jsfx and jsfx.count("return_slot = pending_ret > 0 ? pending_ret - 1 : cur_slot") == 2
