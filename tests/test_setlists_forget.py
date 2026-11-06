# SPDX-License-Identifier: GPL-3.0-or-later
"""Un preset supprimé quitte les setlists : son emplacement devient libre, les banks suivantes ne
bougent pas (2026-09-08). Un preset simplement absent (pas encore synchronisé) n'est PAS touché."""
import json
import os

from bridge import setlists, store


def test_forget_libere_sans_decaler(tmp_path, monkeypatch):
    from bridge import config as C
    monkeypatch.setattr(C, "SETLISTS_DIR", str(tmp_path))
    json.dump({"id": "fcb-banks", "name": "Repertoire", "presets": ["a", "b", "c", "b"]}, open(tmp_path / "fcb-banks.json", "w"))
    assert setlists.forget_preset("b") == 2
    d = json.load(open(tmp_path / "fcb-banks.json"))
    assert d["presets"] == ["a", "", "c", ""]                       # liste DÉRIVÉE : "" = libre
    assert [ln.get("preset") for ln in d["lines"]] == ["a", None, "c", None]
    assert setlists.forget_preset("zz") == 0


def test_load_preset_none_est_un_emplacement_libre():
    assert store.load_preset(None) is None
    assert store.load_preset("") is None
