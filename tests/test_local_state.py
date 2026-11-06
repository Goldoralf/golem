# SPDX-License-Identifier: GPL-3.0-or-later
"""L'état local sorti du dépôt (audit 2026-10-15, lot 4) : une bascule vers une version où ces fichiers ne sont plus
suivis ne les efface pas et n'échoue pas quand ils sont modifiés."""
import os
import shutil
import subprocess

import pytest

from bridge import config as C
from bridge import local_state

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git absent")


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_la_bascule_garde_les_reglages_locaux(tmp_path, monkeypatch):
    root = tmp_path / "golem"
    (root / "config" / "inputmaps").mkdir(parents=True)
    (root / "config" / "click.json").write_text('{"level": -12}')
    (root / "config" / "inputmaps" / "hw-V276.json").write_text('{"card": "hw:V276"}')
    (root / "code.py").write_text("v1")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "avant")
    old = _git(root, "rev-parse", "HEAD")
    _git(root, "rm", "-q", "--cached", "config/click.json", "config/inputmaps/hw-V276.json")
    (root / ".gitignore").write_text("config/click.json\nconfig/inputmaps/\n")
    (root / "code.py").write_text("v2")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "après")
    new = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", old)
    (root / "config" / "click.json").write_text('{"level": 3}')          # le musicien a monté son click

    monkeypatch.setattr(C, "ROOT", str(root))
    assert sorted(local_state.tracked()) == ["config/click.json", "config/inputmaps/hw-V276.json"]
    restore = local_state.preserve()
    _git(root, "checkout", "-q", new)                                    # sans preserve : refusé (click modifié)
    assert sorted(restore()) == ["config/click.json", "config/inputmaps/hw-V276.json"]
    assert (root / "config" / "click.json").read_text() == '{"level": 3}'
    assert (root / "config" / "inputmaps" / "hw-V276.json").exists()
    assert (root / "code.py").read_text() == "v2"
    assert _git(root, "status", "--porcelain") == ""                     # ignorés : plus rien à commiter
    assert local_state.preserve()() == []                                # une fois passé : rien à faire


def test_le_depot_ignore_bien_l_etat_local():
    for p in ("config/click.json", "config/recorder.json", "config/cards/V276.json", "config/inputmaps/hw-V276.json",
              "setlists/mine.json", "reaper/FXChains/x__vital.vitalium.txt", "library/anim-packs/u1/pack.css",
              "assets/samples/.kinds.json", "x.rk", "config/io.json"):
        r = subprocess.run(["git", "-C", C.ROOT, "check-ignore", "-q", "--no-index", p])
        assert r.returncode == 0, p
