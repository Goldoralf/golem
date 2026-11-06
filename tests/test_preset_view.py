# SPDX-License-Identifier: GPL-3.0-or-later
"""La fiche d'un preset, module PUR partagé avec golem.fm (bridge/preset_view.py, docs/shell.md §4 bis) : golem.fm le
vendorise octet pour octet — il ne doit rien lire, rien importer du rack, et le rack doit l'appeler lui-même."""
import ast
import copy
import glob
import json
import os

from bridge import preset_view as PV
from bridge import store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "bridge", "preset_view.py")


def _fixtures():
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tests", "fixtures", "*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if isinstance(d, dict) and d.get("scenes") and ("lanes" in d or "guitar" in d):
            out.append(d)
    # un document v2 (liste de lanes, split, états, lane MIDI, services dans la chaîne) : le cas que golem.fm construit
    out.append({"id": "v2", "lanes_v": 2, "styles": ["djent"], "scenes": [
        {"id": "A", "name": "Intro", "blocks": {"dl": False}},
        {"id": "B", "name": "Riff", "blocks": {"dl": True}, "branches": {"b2": {"mute": True}}}],
        "lanes": [{"id": "guitar-1", "role": "guitar", "in_sel": "1", "chain": {
            "pre": [{"id": "amp", "type": "amp-nam", "variant": "Twin"}, {"id": "lp", "type": "looper", "foot": 3}],
            "split": {"mode": "merge", "branches": [{"id": "b1", "blocks": [{"id": "dl", "type": "delay", "foot": 7}]},
                                                    {"id": "b2", "blocks": [{"id": "rv", "type": "reverb", "foot": 8}]}]},
            "post": []}},
                  {"id": "keys-1", "role": "keys", "midi": True, "chain": {"pre": [{"id": "vt", "type": "vital",
                                                                                   "params": {"preset": "Pad"}}]}}]})
    return out


def test_le_module_est_pur():
    """Bibliothèque standard seulement, aucun import relatif, aucune entrée/sortie : sinon golem.fm ne peut pas le copier."""
    tree = ast.parse(open(SRC, encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            assert n.level == 0, "import relatif"
            mods.add(n.module.split(".")[0])
        elif isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            assert n.func.id not in ("open", "exec", "eval", "__import__"), n.func.id
    assert mods <= {"copy", "json", "re"}, mods


def test_la_fiche_ne_touche_pas_au_document():
    for d in _fixtures():
        before = copy.deepcopy(d)
        PV.summary(d)
        for sc in d.get("scenes") or []:
            PV.stomps(d, sc.get("id"))
        assert d == before


def test_le_rack_et_golem_fm_calculent_la_meme_fiche(monkeypatch):
    """Sans carte, la fiche du module = celle que /api/presets sert (migration du rack comprise)."""
    monkeypatch.setattr(store, "_imap", lambda: {})
    monkeypatch.setattr(store, "save_recorder_cfg_from", lambda p, prev=None: None)      # n'écrit pas config/recorder.json
    docs = _fixtures()
    assert docs
    for d in docs:
        rack = store.preset_summary(store.migrate_config(copy.deepcopy(d)))
        from bridge import genres
        assert PV.summary(d, migrate_styles=genres.migrate_styles) == rack
        # seuls les styles peuvent différer : leur taxonomie est au rack (migrate_styles en paramètre)
        assert {**PV.summary(d), "style": None, "styles": None} == {**rack, "style": None, "styles": None}


def test_stomps_suit_la_scene_et_le_whammy():
    d = {"id": "t", "guitar": {"pre": [{"id": "dl", "type": "delay", "foot": 7, "bypass": True},
                                       {"id": "wh", "type": "whammy-dt", "foot": 8}]},
         "scenes": [{"id": "A", "blocks": {}}, {"id": "B", "blocks": {"dl": True}}]}
    assert PV.stomps(d, "A") == {7: False, 8: False}
    assert PV.stomps(d, "B", whammy_on=True) == {7: True, 8: True}
    assert PV.stomps(None, "A") == {}


def test_les_blocs_permanents_sont_poses_sans_la_machine():
    p = PV.migrate({"id": "x", "guitar": {"pre": [{"id": "r", "type": "rec", "foot": 2}]}, "scenes": []})
    types = [b["type"] for b in p["config"]["rec"]["blocks"]]
    assert types == ["rec", "click", "compo"] and p["config"]["rec"]["blocks"][1]["bypass"] is True
    assert "params" not in p["config"]["rec"]["blocks"][0]                  # les singletons sont hydratés par store
    assert [b["type"] for b in p["config"]["arr"]["blocks"]] == ["arrangement"]
    assert PV.migrate(copy.deepcopy(p)) == p                                # idempotent
