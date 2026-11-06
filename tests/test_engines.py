# SPDX-License-Identifier: GPL-3.0-or-later
"""Moteurs audio — coquille (docs/audio-engine-choice.md) : descripteurs, choix, refus."""
import json
import os
import shutil

import pytest

from bridge import engines as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def root(tmp_path):
    shutil.copytree(os.path.join(ROOT, "config", "engines"), tmp_path / "config" / "engines")
    return str(tmp_path)


@pytest.mark.parametrize("plat", ["linux", "win32", "darwin"])
def test_reaper_seul_selectionnable_partout(plat):
    engines = {e["id"]: e for e in E.descriptors(ROOT, plat)}
    assert set(engines) >= {"reaper", "ardour"}
    assert engines["reaper"]["available"] and not engines["ardour"]["available"]
    assert engines["ardour"]["reason"]                      # la raison s'affiche, jamais vide
    assert E.default_id(ROOT, plat) == "reaper"


def test_capacites_couvrent_toutes_les_fonctions():
    ids = {i for i, _ in E.features(ROOT)}
    for e in E.descriptors(ROOT):
        assert set(e["capabilities"]) == ids, e["id"]
        assert set(e["capabilities"].values()) <= {"yes", "no", "planned"}


def test_choix_absent_ou_indisponible_retombe_sur_le_defaut(root):
    assert E.current(root) == "reaper"                      # rack d'avant la page : pas de fichier
    with open(os.path.join(root, "config", E.CHOICE_FILE), "w") as f:
        json.dump({"engine": "ardour"}, f)                  # écrit à la main : on ne le croit pas
    assert E.current(root) == "reaper"


def test_write_choice_refuse_ce_qui_n_est_pas_disponible(root):
    with pytest.raises(ValueError, match="Coming soon"):
        E.write_choice("ardour", root=root, platform="linux")
    with pytest.raises(ValueError, match="unknown"):
        E.write_choice("bogus", root=root)
    assert E.write_choice("reaper", root=root) == "reaper"
    assert E.current(root) == "reaper"
