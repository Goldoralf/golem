# SPDX-License-Identifier: GPL-3.0-or-later
"""OÙ EST REAPER sous Windows (bridge/reaper_license.py, 2026-10-17) : un REAPER installé sur D: était invisible —
l'installateur ne regardait que « C:\\Program Files\\REAPER (x64) » et en posait un second sur C:."""
import os

import pytest

from bridge import reaper_license as RL


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.delenv("REAPER_BIN", raising=False)
    monkeypatch.setattr(RL, "_registry_dirs", lambda: [])
    return tmp_path


def _exe(d):
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "reaper.exe")
    open(p, "w").close()
    return p


def test_sans_rien_c_est_program_files(win):
    assert RL.windows_exe() == RL.default_windows_exe()
    assert not os.path.isfile(RL.windows_exe())


def test_un_reaper_ailleurs_est_trouve_par_le_registre(win, monkeypatch):
    exe = _exe(str(win / "D" / "Audio" / "REAPER"))
    monkeypatch.setattr(RL, "_registry_dirs", lambda: [str(win / "nulle-part"), os.path.dirname(exe)])
    assert RL.windows_exe() == exe


def test_le_chemin_retenu_passe_avant_program_files(win):
    _exe(str(win / "pf" / "REAPER (x64)"))
    mine = _exe(str(win / "D" / "REAPER"))
    assert RL.remember_windows_exe(os.path.dirname(mine)) == mine          # un DOSSIER suffit
    assert RL.windows_exe() == mine
    assert open(RL.saved_path_file()).read().strip() == mine


def test_on_ne_retient_pas_un_chemin_faux(win):
    with pytest.raises(ValueError):
        RL.remember_windows_exe(str(win / "rien-ici"))
    assert not os.path.exists(RL.saved_path_file())


def test_un_reaper_portable_garde_ses_reglages_dans_son_dossier(win):
    exe = _exe(str(win / "D" / "REAPER-portable"))
    assert RL.portable_dir(exe) is None
    open(os.path.join(os.path.dirname(exe), "reaper.ini"), "w").close()
    assert RL.portable_dir(exe) == os.path.dirname(exe)


def test_as_exe_accepte_un_dossier_ou_l_exe():
    assert RL.as_exe('"D:\\REAPER"').endswith("reaper.exe")
    assert RL.as_exe("D:\\REAPER\\reaper.exe") == "D:\\REAPER\\reaper.exe"
