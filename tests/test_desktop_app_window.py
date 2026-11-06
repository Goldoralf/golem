# SPDX-License-Identifier: GPL-3.0-or-later
"""La fenêtre GoleM du lanceur Windows/macOS (provision/desktop.py) rejoue la fonction `geom` de
provision/golem : mêmes tailles par défaut, même mémoire config/.desktop.json, même règle base/forced."""
import json

from provision import desktop


def _geom(tmp_path, monkeypatch, data):
    path = tmp_path / ".desktop.json"
    if data is not None:
        path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(desktop, "GEOM_FILE", path)
    return path


def test_tailles_par_defaut_de_provision_golem():
    assert desktop.SHELLS["device"][1:] == (1024 + 52 + 24, 600 + 52 + 72)
    assert desktop.SHELLS["phone"][1:] == (390 + 28 + 130, 844 + 28 + 96)


def test_sans_memoire_taille_par_defaut_et_aucune_echelle(tmp_path, monkeypatch):
    _geom(tmp_path, monkeypatch, None)
    assert desktop.window_geometry("device", 1100, 724) == (1100, 724, 0)


def test_zoom_utilisateur_rejoue_et_ecrit_forced(tmp_path, monkeypatch):
    path = _geom(tmp_path, monkeypatch, {"device": {"w": 1300, "h": 800, "dpr": 1.25, "base": 1}})
    assert desktop.window_geometry("device", 1100, 724) == (1300, 800, 1.25)
    assert json.loads(path.read_text())["device"]["forced"] == 1.25


def test_ecran_hidpi_sans_zoom_ne_force_rien(tmp_path, monkeypatch):
    _geom(tmp_path, monkeypatch, {"device": {"w": 1300, "h": 800, "dpr": 2, "base": 2}})
    assert desktop.window_geometry("device", 1100, 724)[2] == 0


def test_navigateur_recycle_ne_pretend_pas_forcer(tmp_path, monkeypatch):
    path = _geom(tmp_path, monkeypatch, {"device": {"w": 1300, "h": 800, "dpr": 1.25, "base": 1}})
    assert desktop.window_geometry("device", 1100, 724, reused=True)[2] == 0
    assert json.loads(path.read_text())["device"]["forced"] == 0


def test_reset_oublie_cette_coquille_seulement(tmp_path, monkeypatch):
    path = _geom(tmp_path, monkeypatch, {"device": {"w": 1300, "h": 800}, "phone": {"w": 500, "h": 900}})
    assert desktop.window_geometry("device", 1100, 724, reset=True) == (1100, 724, 0)
    assert list(json.loads(path.read_text())) == ["phone"]


def test_fenetre_ouverte_par_chromium_app_avec_profil_dedie(tmp_path, monkeypatch):
    _geom(tmp_path, monkeypatch, None)
    launched = []
    monkeypatch.setattr(desktop, "app_browser", lambda: "chrome.exe")
    monkeypatch.setattr(desktop, "app_window_pids", lambda: [])
    monkeypatch.setattr(desktop, "browser_profile", lambda: tmp_path / "browser")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda args, **kw: launched.append(args))
    desktop.open_window(8770)
    args = launched[0]
    assert args[1] == "--app=http://127.0.0.1:8770/app/device.html?shell=device"
    assert f"--user-data-dir={tmp_path / 'browser'}" in args
    assert "--window-size=1100,724" in args
    desktop.open_window(8770, "phone", fullscreen=True)
    assert launched[1][1] == "--app=http://127.0.0.1:8770/app/device.html?d=phone&shell=phone"
    assert "--start-fullscreen" in launched[1]
