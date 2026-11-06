# SPDX-License-Identifier: GPL-3.0-or-later
"""L'installateur Windows (docs/installer.md §8) — ce qui se vérifie sans Windows.

Les deux modules de plateforme portent la MÊME interface (installer/server.py ne connaît aucun OS) ;
le bootstrap PowerShell copie le pin de Python et ne doit pas diverger de provision/windows/pins.json ;
un .ps1 lancé par `-File` sous Windows PowerShell 5.1 sans BOM est lu en cp1252 — et l'UTF-8 de « ✓ »
contient 0x93, qu'il prend pour un guillemet : le script ne s'analyse plus."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

INTERFACE = ("NAME", "PRIVILEGE", "STEPS", "default_dir", "checks", "reaper_detect", "reaper_install",
             "sizes", "ui", "run_step", "open_url")


def _src(name):
    return open(os.path.join(ROOT, "installer", name), encoding="utf-8").read()


def test_both_platforms_expose_the_same_interface():
    import platform_linux
    for attr in INTERFACE:
        assert hasattr(platform_linux, attr), attr
    win = _src("platform_windows.py")                 # importable seulement sous Windows (ctypes.windll)
    for attr in INTERFACE:
        assert re.search(rf"^(def {attr}\(|{attr} = )", win, re.M), attr


def test_server_knows_no_operating_system():
    import ast
    tree = ast.parse(_src("server.py"))
    tree.body = tree.body[1:]                         # la docstring du module explique le principe : on lit le CODE
    srv = ast.unparse(tree)
    # la porte unique : un seul test de plateforme, celui qui choisit le module
    assert srv.count("sys.platform") == 1
    import re
    # des MOTS, pas des sous-chaînes : « apt » se cache dans « captures » (/api/factory/captures, 2026-10-13)
    for word in ("sudo -", "apt", "powershell", "Program Files", "xdg-open"):
        assert not re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", srv), word


def test_linux_steps_unchanged():
    import platform_linux
    assert [s for s, _ in platform_linux.STEPS] == ["source", "system", "profile", "start"]
    # plus de profil (2026-10-06), et plus de « boîte dédiée » à l'installation (docs/installer.md §4, FIXÉ 2026-10-16) :
    # démarrer avec l'ordinateur et verrouiller la machine sont des réglages de l'app
    assert "profiles" not in platform_linux.ui() and "autostart_note" not in platform_linux.ui()
    for name in ("platform_linux.py", "platform_windows.py", "platform_macos.py"):   # pas importables ici : on lit le code
        src = _src(name)
        assert '"profiles"' not in src and '"autostart_note"' not in src, name
        assert 'S["autostart"]' not in src and '"autostart", "on"' not in src and "harden.sh" not in src, name


def test_bootstrap_python_pin_matches_pins_json():
    pins = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json")))
    boot = open(os.path.join(ROOT, "provision", "bootstrap.ps1"), encoding="ascii").read()   # ASCII : lisible par irm|iex ET -File
    assert f"$pyVersion = '{pins['python']['version']}'" in boot
    assert f"$pyUrl = '{pins['python']['url']}'" in boot
    assert f"$pySha = '{pins['python']['sha256']}'" in boot


def test_pins_are_complete():
    pins = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json")))
    for k in ("python", "reaper", "nam_vst3"):
        assert re.fullmatch(r"[0-9a-f]{64}", pins[k]["sha256"]), k
        assert pins[k]["url"].startswith("https://"), k
    assert pins["vcredist"]["signer"] == "Microsoft Corporation"


def test_elevated_script_has_a_bom():
    raw = open(os.path.join(ROOT, "provision", "windows", "install-system.ps1"), "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")


def test_dry_step_runs_and_can_fail():
    step = os.path.join(ROOT, "installer", "dry_step.py")
    r = subprocess.run([sys.executable, step, "source"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "dry" in r.stdout
    r = subprocess.run([sys.executable, step, "start"], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "GOLEM_DRY_FAIL": "start"})
    assert r.returncode == 3


def test_la_fenetre_tient_dans_la_zone_utile_de_l_ecran():
    # VM 2026-10-24, écran 1280×800 : la barre des tâches (48 px) cachait Back et Next
    import importlib
    W = importlib.import_module("platform_windows")
    assert W.window_geometry((0, 0, 1280, 752)) == ["--window-size=1120,736", "--window-position=80,8"]
    assert W.window_geometry((0, 0, 1920, 1032)) == ["--window-size=1120,780", "--window-position=400,126"]
