# SPDX-License-Identifier: GPL-3.0-or-later
"""Lot 3 de docs/arrangement.md : les blocs EMPILÉS sur le switch de l'arrangement deviennent des cases
« When the song starts » de leurs chansons, et quittent le switch. Une case réglée à la main gagne ; idempotent."""
import json

from bridge import arrangement as A
from bridge import config as C
from bridge import songs as S


def _setup(tmp_path, monkeypatch, song_starts=None):
    pres, sl, so = tmp_path / "presets", tmp_path / "setlists", tmp_path / "songs"
    for d in (pres, sl, so):
        d.mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(pres))
    monkeypatch.setattr(C, "SETLISTS_DIR", str(sl))
    monkeypatch.setattr(C, "SONGS_DIR", str(so))
    monkeypatch.setattr(S, "DIR", str(so), raising=False)
    preset = {"id": "cr", "name": "Paper Kite", "config": {
        "gen": {"blocks": [{"type": "backing-track", "id": "bk", "foot": 4}]},
        "rec": {"blocks": [{"type": "rec", "id": "rec-global", "foot": 4}, {"type": "click", "id": "click-global", "foot": 4}]},
        "arr": {"blocks": [{"type": "arrangement", "id": "arrangement", "foot": 4, "params": {"advance": "bars"}}]}}}
    (pres / "cr.json").write_text(json.dumps(preset))
    (pres / ".sandbox.json").write_text(json.dumps({"preset": preset, "scene": "A"}))
    arr = {"type": "arrangement", "id": "arr-song", "params": {"sections": [{"name": "a", "bars": 4}]}}
    if song_starts is not None:
        arr["params"]["starts"] = song_starts
    S.save({"id": "rs:abc", "rev": 1, "title": "Paper Kite", "kind": "cover", "born": "rack",
            "sheet": {"preset": "cr", "arrangement": arr}}, bump=False)
    return pres


def test_les_blocs_empiles_deviennent_des_cases(tmp_path, monkeypatch):
    pres = _setup(tmp_path, monkeypatch)
    done = A.migrate_stacks_to_starts()
    assert done and done[0]["moved"] == ["backing-track", "click", "rec"] and done[0]["songs"] == 1
    st = S.load("rs:abc")["sheet"]["arrangement"]["params"]["starts"]
    assert st == {"rec": True, "click": True}                     # Backing : déjà par défaut, pas de case
    p = json.loads((pres / "cr.json").read_text())
    feet = {b["id"]: b.get("foot") for lane in ("gen", "rec") for b in p["config"][lane]["blocks"]}
    assert feet == {"bk": None, "rec-global": None, "click-global": None}
    assert p["config"]["arr"]["blocks"][0]["foot"] == 4          # le switch du morceau reste
    sb = json.loads((pres / ".sandbox.json").read_text())["preset"]
    assert all("foot" not in b for b in sb["config"]["rec"]["blocks"])   # le brouillon suit
    assert json.loads((pres / A.MIGRATION_FILE).read_text())["items"][0]["preset"] == "cr"
    assert A.migrate_stacks_to_starts() == []                     # idempotent


def test_une_case_reglee_a_la_main_gagne(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, song_starts={"rec": False})
    A.migrate_stacks_to_starts()
    assert S.load("rs:abc")["sheet"]["arrangement"]["params"]["starts"] == {"rec": False, "click": True}
