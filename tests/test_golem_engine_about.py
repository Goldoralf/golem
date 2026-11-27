# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings ▸ About ▸ Golem Engine (2026-11-27) : l'épingle montrée est celle du système qui tourne — Linux lit
provision/golem_engine.py VERSION, Windows son pins.json, qui avance à son propre pas."""
import json
import os

from bridge import routes_system as R
from provision import golem_engine as ge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_linux_montre_la_version_du_module(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "linux")
    d = R.golem_engine_about()
    assert d["pinned"] == ge.VERSION
    assert d["license"] == "GPL-2.0-or-later" and d["sources_url"].startswith("https://github.com/Goldoralf/golem-engine")


def test_windows_montre_l_epingle_de_son_pins_json(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "win32")
    want = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json"), encoding="utf-8"))["golem_engine"]["version"]
    assert R.golem_engine_about()["pinned"] == want


# ── le rattrapage après une mise à jour (provision/golem_engine.py needed, docs/update.md §3 bis, 2026-11-27) ──

def _pkg(d, version):
    (d / "golem" / "engine").mkdir(parents=True)
    (d / "golem" / "engine" / "run.sh").write_text("#!/bin/sh\n")
    if version:
        (d / "VERSION").write_text(version + "\n")


def test_un_paquet_installe_en_retard_est_rattrape(tmp_path):
    _pkg(tmp_path / "opt" / "golem-engine", "9.9-g3")
    assert ge.needed(env={}, home=tmp_path, platform="linux") is (ge.VERSION != "9.9-g3")


def test_un_paquet_a_l_epingle_ne_bouge_pas(tmp_path):
    _pkg(tmp_path / "opt" / "golem-engine", ge.VERSION)
    assert ge.needed(env={}, home=tmp_path, platform="linux") is False


def test_jamais_un_arbre_de_dev_ni_un_dossier_force(tmp_path):
    _pkg(tmp_path / "opt" / "golem-engine", "9.9-g1")
    _pkg(tmp_path / "golem-engine", None)                       # l'arbre de dev passe avant le paquet
    assert ge.needed(env={}, home=tmp_path, platform="linux") is False
    assert ge.needed(env={"GOLEM_ENGINE_DIR": "/x"}, home=tmp_path / "rien", platform="linux") is False


def test_jamais_quand_aucun_moteur_n_est_installe(tmp_path):
    # un golem d'avant v0.7 resté sur REAPER : la ligne d'installation ajoute le moteur, pas un redémarrage
    assert ge.needed(env={}, home=tmp_path, platform="linux") is False


def test_windows_compare_a_son_pins_json(tmp_path):
    d = tmp_path / "opt" / "golem-engine"
    (d / "golem" / "engine").mkdir(parents=True)
    (d / "golem" / "engine" / "run.py").write_text("")
    (d / "VERSION").write_text(ge.pinned_version("win32"))
    assert ge.needed(env={}, home=tmp_path, platform="win32") is False
    (d / "VERSION").write_text("9.9-g4")
    assert ge.needed(env={}, home=tmp_path, platform="win32") is True


def test_les_lanceurs_appellent_le_rattrapage():
    start = open(os.path.join(ROOT, "provision", "start.sh"), encoding="utf-8").read()
    assert "golem_engine_catch_up" in start
    assert start.index("golem_engine_catch_up") < start.index('start_golem_engine "$HERE"')
    desk = open(os.path.join(ROOT, "provision", "desktop.py"), encoding="utf-8").read()
    assert "_pending_golem_engine()" in desk
