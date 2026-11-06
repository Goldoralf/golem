# SPDX-License-Identifier: GPL-3.0-or-later
"""Un rig matérialisé dans un Reaper PRÉCÉDENT n'est pas adoptable (recall.rig_is_live). Sous Windows,
l'heure de démarrage de Reaper était lue dans /proc : l'exception tombait dans le repli « portabilité »
et le bridge ADOPTAIT un rig mort au redémarrage du lanceur (2026-10-02)."""
import json
import os
import sys
import time

import pytest

from bridge import monitors, recall


@pytest.fixture
def livemap(tmp_path, monkeypatch):
    path = tmp_path / ".livemap.json"
    path.write_text(json.dumps({"preset": "p1"}), encoding="utf-8")
    monkeypatch.setattr(recall, "_LIVEMAP_STATE_PATH", str(path))
    monkeypatch.setattr(monitors, "_reaper_pid", lambda: 4242)
    return path


def _stamp(path, t):
    os.utime(path, (t, t))


def test_livemap_plus_vieille_que_reaper_n_est_pas_adoptee(livemap, monkeypatch):
    _stamp(livemap, time.time() - 60)
    monkeypatch.setattr(monitors, "_process_started", lambda pid: time.time() - 10)
    assert recall.rig_is_live("p1") is False


def test_livemap_ecrite_par_ce_reaper_est_adoptee(livemap, monkeypatch):
    _stamp(livemap, time.time() - 5)
    monkeypatch.setattr(monitors, "_process_started", lambda pid: time.time() - 60)
    assert recall.rig_is_live("p1") is True


@pytest.mark.skipif(sys.platform not in ("win32", "linux"), reason="heure de process lisible ici seulement")
def test_heure_de_demarrage_lisible_sur_cet_os():
    started = monitors._process_started(os.getpid())
    assert time.time() - 3600 * 24 * 30 < started <= time.time()
