# SPDX-License-Identifier: GPL-3.0-or-later
"""Moteurs audio (docs/audio-engine-choice.md) : descripteurs, choix, refus. Le Golem Engine n'est choisissable que
sous Linux ET là où il est construit (platforms.linux.requires) : sans lui, REAPER reste le seul choix, partout."""
import json
import os
import shutil

import pytest

from bridge import engines as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def no_golem_engine(monkeypatch, tmp_path):
    """Une machine SANS Golem Engine construit (le cas d'un rack de musicien aujourd'hui)."""
    monkeypatch.setenv("GOLEM_ENGINE_DIR", str(tmp_path / "no-golem-engine"))


@pytest.fixture
def root(tmp_path):
    shutil.copytree(os.path.join(ROOT, "config", "engines"), tmp_path / "config" / "engines")
    return str(tmp_path)


@pytest.mark.parametrize("plat", ["linux", "win32", "darwin"])
def test_sans_golem_engine_construit_reaper_seul_selectionnable(plat):
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
    with pytest.raises(ValueError, match="not built"):
        E.write_choice("ardour", root=root, platform="linux")
    with pytest.raises(ValueError, match="Linux only"):
        E.write_choice("ardour", root=root, platform="win32")
    with pytest.raises(ValueError, match="unknown"):
        E.write_choice("bogus", root=root)
    assert E.write_choice("reaper", root=root) == "reaper"
    assert E.current(root) == "reaper"


def test_le_golem_engine_construit_se_choisit_sous_linux(root, monkeypatch, tmp_path):
    built = tmp_path / "built"
    (built / "golem" / "engine").mkdir(parents=True)
    (built / "golem" / "engine" / "run.sh").write_text("#!/bin/sh\n")
    monkeypatch.setenv("GOLEM_ENGINE_DIR", str(built))
    assert {e["id"]: e["available"] for e in E.descriptors(root, "linux")}["ardour"] is True
    assert {e["id"]: e["available"] for e in E.descriptors(root, "win32")}["ardour"] is False
    assert E.write_choice("ardour", root=root, platform="linux") == "ardour"
    assert E.current(root, "linux") == "ardour"
    assert E.default_id(root, "linux") == "reaper"                       # le défaut reste REAPER
