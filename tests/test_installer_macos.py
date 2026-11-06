# SPDX-License-Identifier: GPL-3.0-or-later
"""L'installateur macOS (docs/platforms.md, 2026-10-04) — ce qui se vérifie sans Mac."""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "installer"))

import platform_macos as M  # noqa: E402

INTERFACE = ("NAME", "PRIVILEGE", "STEPS", "default_dir", "checks", "reaper_detect", "reaper_install",
             "sizes", "ui", "run_step", "open_url")      # la même liste que test_installer_windows.py


def test_same_interface_as_linux_and_windows():
    for attr in INTERFACE:
        assert hasattr(M, attr), attr
    assert M.PRIVILEGE == "uac"                    # une fenêtre du système, aucun mot de passe dans l'écran
    assert [s for s, _ in M.STEPS] == ["source", "system", "bridge", "sounds", "profile"]


def test_server_picks_macos_with_one_platform_test():
    srv = open(os.path.join(ROOT, "installer", "server.py"), encoding="utf-8").read()
    assert '"darwin": "platform_macos"' in srv


def test_the_admin_window_quotes_paths_with_spaces_and_quotes():
    cmd = M.elevated_command("/Users/w/My GoleM/provision/macos/install-system.sh", "/tmp/a b.log",
                             ["--reaper", "--nam"])
    assert cmd[:2] == ["osascript", "-e"]
    script = cmd[2]
    assert script.startswith('do shell script "') and script.endswith("with administrator privileges")
    assert "'/Users/w/My GoleM/provision/macos/install-system.sh'" in script
    assert "--log '/tmp/a b.log' '--reaper' '--nam'" in script


def test_ui_strings_are_english_plain_text():
    u = M.ui()
    blob = json.dumps(u, ensure_ascii=False)
    assert "<b>" not in "".join(u["permission"])          # l'écran échappe : une balise s'afficherait telle quelle
    for word in (" le ", " la ", " les ", " une ", " est "):
        assert word not in blob, word


def test_switches_follow_the_pins(monkeypatch):
    monkeypatch.setattr(M, "reaper_detect", lambda src: {"found": True})
    sw = M.system_switches(ROOT)
    pins = M.pins(ROOT)
    assert "--nam" in sw and "--reaper" not in sw
    assert ("--avldrums" in sw) == ("avldrums" in pins)
    assert ("--vitalium" in sw) == ("pawpaw" in pins)
    assert ("--sfizz" in sw) == ("sfizz" in pins)                  # le lecteur SFZ : piano Keys + kits importés
    # les réverbes et le boost que effects-macos.json nomme (2026-11-04 : muets, rien ne les posait)
    assert "--dragonfly" in sw and "--proteus" in sw


def test_system_script_knows_every_switch():
    sh = open(os.path.join(ROOT, "provision", "macos", "install-system.sh"), encoding="utf-8").read()
    assert sh.startswith("#!/bin/bash\n") and "\r" not in sh
    for sw in ("--log", "--reaper", "--nam", "--avldrums", "--sfizz", "--vitalium", "--dragonfly", "--proteus"):
        assert re.search(rf"^\s*{sw}\)", sh, re.M), sw


def test_manual_installs_are_listed_on_the_last_page():
    """Vital a sa carte (re-vérifiée en direct) ; le reste est une liste, chaque ligne avec son lien."""
    u = M.ui()
    assert u["vital"] is True and u["vital_installer"] == "macOS installer"
    names = [m[0] for m in u["manual"]]
    assert "Surge XT" in names and not any(n.startswith("Vital") for n in names)
    assert "Dragonfly Reverb" not in names and "Proteus" not in names          # posés par l'étape system
    assert all(url and url.startswith("https://") for _, _, url in u["manual"])


def test_only_the_pythons_the_bridge_lock_installs_are_accepted():
    # onnxruntime 1.23.2 (darwin) : wheels cp312 et cp313 seulement — la 3.15 cassait l'étape bridge (2026-11-04)
    assert M.python_ok((3, 12)) and M.python_ok((3, 13))
    assert not M.python_ok((3, 11)) and not M.python_ok((3, 14)) and not M.python_ok((3, 15))
    cmd = open(os.path.join(ROOT, "install-macos.command"), encoding="utf-8").read()
    assert "(3, 12) <= sys.version_info[:2] <= (3, 13)" in cmd


def test_the_pinned_reverbs_and_boost_are_the_plugins_the_macos_table_names():
    table = open(os.path.join(ROOT, "library", "catalog", "effects-macos.json"), encoding="utf-8").read()
    sh = open(os.path.join(ROOT, "provision", "macos", "install-system.sh"), encoding="utf-8").read()
    for plugin in ("Dragonfly Hall Reverb", "Dragonfly Plate Reverb", "Dragonfly Room Reverb", "Proteus"):
        assert plugin in table
    for bundle in ("DragonflyHallReverb", "DragonflyPlateReverb", "DragonflyRoomReverb", "Proteus.vst3"):
        assert bundle in sh
    pins = M.pins(ROOT)
    for key in ("dragonfly", "proteus"):
        assert re.fullmatch(r"[0-9a-f]{64}", pins[key]["sha256"]) and pins[key]["url"].endswith(".dmg")


def test_the_command_line_tools_are_a_blocking_check(monkeypatch, tmp_path):
    # python-rtmidi n'a pas de wheel macOS : sans les CLT, pip échoue à l'étape bridge (audit 2026-11-04)
    from subprocess import CompletedProcess
    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: CompletedProcess(a, 0, stdout=f"{tmp_path}\n", stderr=""))
    assert M.clt_ok()
    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: CompletedProcess(a, 0, stdout=f"{tmp_path}/gone\n", stderr=""))
    assert not M.clt_ok()
    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: CompletedProcess(a, 2, stdout="", stderr="error"))
    assert not M.clt_ok()


def test_a_clone_in_a_protected_folder_is_not_installed_in_place(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("Desktop", "Documents", "Downloads"):
        assert M.tcc_protected(str(tmp_path / name / "golem")) == name
    assert M.tcc_protected(str(tmp_path / "golem")) is None
    assert M.tcc_protected(str(tmp_path / "Desktopish" / "golem")) is None
    server = open(os.path.join(ROOT, "installer", "server.py"), encoding="utf-8").read()
    assert 'getattr(P, "tcc_protected"' in server


def test_the_elevated_script_runs_from_a_private_copy(monkeypatch, tmp_path):
    # le bash élevé ne lit pas un dossier protégé (« Operation not permitted (126) », 2026-10-16)
    calls = []
    monkeypatch.setattr(M.subprocess, "run", lambda *a, **k: calls.append(a[0]))
    monkeypatch.setattr(M.tempfile, "tempdir", str(tmp_path))
    stage = M._stage_system_script(ROOT)
    assert sorted(os.listdir(stage)) == ["install-system.sh", "pins.json"]
    assert stage.startswith(str(tmp_path)) and oct(os.stat(stage).st_mode)[-3:] == "700"
    assert calls and calls[0][:3] == ["xattr", "-dr", "com.apple.quarantine"]


def test_the_reaper_version_is_compared_as_major_minor(tmp_path):
    # REAPER 7.82 macOS écrit « 7.82.0_3385784u » : comparé tel quel au pin, l'écran avertissait même à 7.79 exact
    import plistlib
    app = tmp_path / "REAPER.app"
    (app / "Contents").mkdir(parents=True)
    for raw, want in (("7.82.0_3385784u", "7.82"), ("7.79", "7.79"), ("7.79.1", "7.79.1"), ("weird", "weird")):
        with open(app / "Contents" / "Info.plist", "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": raw}, f)
        assert M.app_version(str(app)) == want


def test_the_golem_nam_build_rolls_back_and_belongs_to_root():
    sh = open(os.path.join(ROOT, "provision", "macos", "install-system.sh"), encoding="utf-8").read()
    assert 'mv "$vst.golem-prev" "$vst"' in sh and 'chown -R root:wheel "$vst"' in sh
    # le témoin s'écrit APRÈS la copie réussie
    assert sh.index('chown -R root:wheel "$vst"') < sh.index('> "$mark"')


def test_la_fenetre_de_l_installateur_se_suit_par_son_profil(monkeypatch):
    """app_alive (2026-11-04) : la fenêtre vit tant qu'un navigateur porte NOTRE profil — même quand le processus
    lancé a passé la main ; aucune fenêtre ouverte par nous = False ; une lecture ratée = True (on ne ferme pas)."""
    import subprocess
    from installer import platform_macos as M
    monkeypatch.setattr(M, "_OPEN_PROFILE", None)
    assert M.app_alive() is False
    monkeypatch.setattr(M, "_OPEN_PROFILE", "/Users/x/Library/Application Support/GoleM/installer-browser")
    ps = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --app=http://127.0.0.1:1 " \
         "--user-data-dir=/Users/x/Library/Application Support/GoleM/installer-browser --no-first-run\n"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=ps))
    assert M.app_alive() is True
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="/sbin/launchd\n"))
    assert M.app_alive() is False

    def boom(*a, **k):
        raise OSError("ps")
    monkeypatch.setattr(subprocess, "run", boom)
    assert M.app_alive() is True
