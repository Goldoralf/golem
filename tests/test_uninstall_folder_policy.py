# SPDX-License-Identifier: GPL-3.0-or-later
"""Le dossier d'installation à la désinstallation (2026-11-19, option a du mainteneur) : effacé entier seulement si
golem l'a créé ; sinon seulement ce que golem y a posé ; sans marqueur, ou dans un dépôt git, rien du tout.
Avant : golem installé dans D:\\Audio emportait les samples de D:\\Audio, et le raccourci d'un clone visait le dépôt."""
import json
import os

from installer import desktop_steps as DS
from provision import uninstall_win as UW


def _install(target, before_files=()):
    """Ce que fait step_source : les entrées d'avant, la copie, puis le marqueur."""
    os.makedirs(target, exist_ok=True)
    for f in before_files:
        (target / f).write_text("mine")
    before = set(os.listdir(target)) if before_files else (None if not os.listdir(target) else set(os.listdir(target)))
    for d in ("provision", "bridge", "presets"):
        (target / d).mkdir(exist_ok=True)
    (target / "README.md").write_text("golem")
    DS.write_install_marker(str(target), before)


def test_un_dossier_neuf_part_entier(tmp_path):
    root = tmp_path / "golem"
    DS.write_install_marker(str(root), None) if False else None
    root.mkdir()
    for d in ("provision", "bridge"):
        (root / d).mkdir()
    DS.write_install_marker(str(root), None)              # le dossier n'existait pas avant la copie
    assert UW.folder_policy(str(root)) == ("all", None)


def test_un_dossier_qui_existait_ne_perd_que_ce_que_golem_y_a_mis(tmp_path):
    root = tmp_path / "Audio"
    _install(root, before_files=("my-samples.wav", "notes.txt"))
    how, paths = UW.folder_policy(str(root))
    names = sorted(os.path.basename(p) for p in paths)
    assert how == "entries"
    assert names == sorted(["provision", "bridge", "presets", "README.md", UW.INSTALL_MARKER])
    assert not any(os.path.basename(p) in ("my-samples.wav", "notes.txt") for p in paths)


def test_sans_marqueur_ou_dans_un_depot_git_rien_ne_part(tmp_path):
    old = tmp_path / "old-install"
    (old / "provision").mkdir(parents=True)
    assert UW.folder_policy(str(old))[0] == "keep"
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    (clone / UW.INSTALL_MARKER).write_text(json.dumps({"fresh": True, "entries": []}))
    how, why = UW.folder_policy(str(clone))
    assert how == "keep" and "git" in why


def test_une_reinstallation_garde_le_premier_verdict_et_ajoute(tmp_path):
    root = tmp_path / "Audio"
    _install(root, before_files=("mine.wav",))
    before = set(os.listdir(root))
    (root / "recordings").mkdir()                          # une nouvelle version pose un dossier de plus
    DS.write_install_marker(str(root), before)
    m = json.loads((root / UW.INSTALL_MARKER).read_text())
    assert m["fresh"] is False and "recordings" in m["entries"] and "mine.wav" not in m["entries"]


def test_un_golem_d_avant_le_marqueur_n_en_recoit_pas_un_faux(tmp_path):
    root = tmp_path / "golem"
    (root / "provision").mkdir(parents=True)
    (root / "mine.wav").write_text("x")
    DS.write_install_marker(str(root), set(os.listdir(root)))   # réinstallé par-dessus un golem sans marqueur
    assert not (root / UW.INSTALL_MARKER).exists()
    assert UW.folder_policy(str(root))[0] == "keep"


def test_une_entree_du_marqueur_n_est_jamais_un_chemin(tmp_path):
    root = tmp_path / "x"
    root.mkdir()
    (root / UW.INSTALL_MARKER).write_text(json.dumps({"fresh": False, "entries": ["..", "a/../../b", "C:\\Windows", "ok"]}))
    how, paths = UW.folder_policy(str(root))
    assert [os.path.basename(p) for p in paths] == ["ok", UW.INSTALL_MARKER]
