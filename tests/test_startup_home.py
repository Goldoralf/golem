# SPDX-License-Identifier: GPL-3.0-or-later
"""L'accueil au démarrage (bridge/startup_home.py, maquette mockups/startup-home.html validée le 2026-10-11)."""
import json
import os

import pytest

from bridge import startup_home as SH


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(SH, "PATH", str(tmp_path / ".startup.json"))
    monkeypatch.setattr(SH, "_cache", {"mtime": None, "doc": None})
    from bridge import store, setlists as sl
    presets = {"velvetine": {"id": "velvetine"}, "patch:full-vst": {"id": "patch:full-vst"}}
    monkeypatch.setattr(store, "load_preset", lambda pid: presets.get(pid))
    lists = {"s1": {"id": "s1", "lines": [{"id": "r:s1:a", "preset": "velvetine"}, {"id": "r:s1:b", "preset": "kite", "band_song": "bs1", "title": "Paper Kite"}],
                    "presets": ["velvetine", "kite"]}}
    monkeypatch.setattr(sl, "load", lambda sid: lists.get(sid))
    monkeypatch.setattr(sl, "active_id", lambda: "s1")
    monkeypatch.setattr(sl, "pid_of", lambda ln: ln.get("preset") if isinstance(ln, dict) else ln)
    calls = []
    monkeypatch.setattr(sl, "set_active", lambda sid: calls.append(("setlist", sid)) or {"ok": True})
    from bridge import recall
    monkeypatch.setattr(recall, "do_recall", lambda pid, scene, line=None: calls.append(("recall", pid, scene)) or True)
    monkeypatch.setattr(recall, "do_recall_slot", lambda n, source=None: calls.append(("slot", n)) or True)
    monkeypatch.setattr("bridge.config.PRESETS_DIR", str(tmp_path))
    return calls


def test_par_defaut_la_bank_00_et_un_seul_accueil_a_la_fois(home):
    assert SH.describe() == {"policy": "bank0", "home": None} and SH.plan() is None
    SH.set_home({"kind": "preset", "id": "velvetine", "name": "Velvetine"})
    d = SH.describe()
    assert d["policy"] == "home" and d["home"]["id"] == "velvetine" and d["home"]["missing"] is None
    assert SH.is_home("preset", "velvetine") and not SH.is_home("patch", "velvetine")
    SH.set_home({"kind": "patch", "id": "patch:full-vst", "name": "full vst"})      # remplace
    assert SH.describe()["home"]["kind"] == "patch" and not SH.is_home("preset", "velvetine")
    assert SH.plan() == [("recall", "patch:full-vst", "A")]
    SH.clear_home()
    assert SH.describe() == {"policy": "bank0", "home": None}


def test_une_chanson_une_setlist_une_bank(home):
    SH.set_home({"kind": "song", "setlist": "s1", "line": "r:s1:b", "name": "Paper Kite"})
    assert SH.plan() == [("setlist", "s1"), ("slot", 1)]
    assert SH.apply(SH.plan()) is True and home[-2:] == [("setlist", "s1"), ("slot", 1)]
    SH.set_home({"kind": "setlist", "id": "s1", "name": "Setlist 1"})
    assert SH.plan() == [("setlist", "s1"), ("slot", 0)]
    SH.set_home({"kind": "bank", "slot": 1, "name": "bank 01"})
    assert SH.plan() == [("slot", 1)]
    with pytest.raises(ValueError):
        SH.set_home({"kind": "song", "setlist": "s1"})                  # sans ligne : refusé


def test_un_accueil_disparu_est_dit_et_retombe_sur_la_bank_00(home):
    SH.set_home({"kind": "preset", "id": "gone", "name": "Gone"})
    assert SH.describe()["home"]["missing"] == "not found" and SH.plan() is None
    SH.set_home({"kind": "song", "setlist": "s1", "line": "r:s1:zz", "name": "Lost"})
    assert SH.describe()["home"]["missing"] == "no longer in its setlist" and SH.plan() is None


def test_le_dernier_joue_relit_live_json(home, tmp_path):
    SH.set_policy("last")
    assert SH.plan() is None                                             # rien à l'arrêt : bank 00
    json.dump({"preset": "kite", "scene": "B", "line": "r:s1:b", "setlist": "s1"}, open(tmp_path / ".live.json", "w"))
    assert SH.plan() == [("setlist", "s1"), ("slot", 1)]                 # la ligne existe encore : par la bank
    json.dump({"preset": "velvetine", "scene": "B"}, open(tmp_path / ".live.json", "w"))
    assert SH.plan() == [("recall", "velvetine", "B")]
    with pytest.raises(ValueError):
        SH.set_policy("home")                                            # rien de posé : refusé


def test_la_premiere_bank_est_la_premiere_qui_porte_quelque_chose(home, monkeypatch):
    # une setlist qui commence par un TROU (2026-10-18) : on ouvrait la bank 00, vide — le musicien arrivait sur rien
    from bridge import setlists as sl
    holed = {"id": "s2", "lines": [{"id": "r:s2:a", "preset": ""}, {"id": "r:s2:b", "preset": "velvetine"}]}
    monkeypatch.setattr(sl, "load", lambda sid: {"s2": holed}.get(sid))
    monkeypatch.setattr(sl, "active_id", lambda: "s2")
    assert SH.first_slot() == 1
    SH.set_home({"kind": "setlist", "id": "s2", "name": "S2"})
    assert SH.plan() == [("setlist", "s2"), ("slot", 1)]
    assert SH.first_slot({"lines": []}) == 0 and SH.first_slot({"lines": [{"preset": ""}]}) == 0
