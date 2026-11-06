# SPDX-License-Identifier: GPL-3.0-or-later
"""La FENÊTRE de l'installateur sous Linux (installer/platform_linux.py open_app, 2026-11-03) et le Chromium que
l'install pose pour la fenêtre golem. Portable Ubuntu 26.04 / GNOME Wayland / Firefox snap : xdg-open ouvrait
l'installateur en ONGLET d'arrière-plan d'un Firefox déjà ouvert, et le terminal disait « open this link ». Désormais
un Chromium `--app`, sinon Firefox en nouvelle instance sur un profil dédié et nu, sinon xdg-open."""
import os
import sys

import pytest

from provision import uninstall as U
from tests.uninstall_fixtures import HOME, machine, receipt_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _linux():
    if sys.platform != "linux":
        pytest.skip("installateur Linux")
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    import platform_linux
    return platform_linux


def _fake(monkeypatch, m, tmp_path, browsers, snaps=()):
    """`browsers` : les noms trouvés dans le PATH ; `snaps` : les /snap/<nom> présents. Rend la liste des argv lancés."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GOLEM_BROWSER", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(m.shutil, "which", lambda n: f"/usr/bin/{n}" if n in browsers else None)
    real_isdir = os.path.isdir
    monkeypatch.setattr(m.os.path, "isdir", lambda p: p in {f"/snap/{s}" for s in snaps} or
                        (not str(p).startswith("/snap/") and real_isdir(p)))
    launched = []

    class P:
        def __init__(self, argv, **kw):
            launched.append(argv)
            self.kw = kw
    monkeypatch.setattr(m.subprocess, "Popen", P)
    return launched


def test_chromium_ouvre_une_fenetre_app_sur_un_profil_dedie(monkeypatch, tmp_path):
    m = _linux()
    launched = _fake(monkeypatch, m, tmp_path, {"chromium", "firefox"}, snaps={"chromium"})
    w = m.open_app("http://127.0.0.1:1/?t=x")
    assert w is not None
    argv = launched[0]
    assert argv[0] == "/usr/bin/chromium" and "--app=http://127.0.0.1:1/?t=x" in argv
    # snap : le profil sous ~/snap/chromium/common, jamais sous un dossier caché du home
    assert f"--user-data-dir={tmp_path}/snap/chromium/common/golem-installer" in argv


def test_sans_chromium_firefox_en_nouvelle_instance_nue(monkeypatch, tmp_path):
    m = _linux()
    launched = _fake(monkeypatch, m, tmp_path, {"firefox"}, snaps={"firefox"})
    assert m.open_app("http://127.0.0.1:1/") is not None
    argv = launched[0]
    prof = f"{tmp_path}/snap/firefox/common/golem-installer"
    assert argv[:4] == ["/usr/bin/firefox", "--new-instance", "--profile", prof]   # pas un onglet du Firefox ouvert
    assert argv[-1] == "http://127.0.0.1:1/"
    user_js = open(os.path.join(prof, "user.js")).read()
    assert "toolkit.legacyUserProfileCustomizations.stylesheets" in user_js and "browser.aboutwelcome.enabled" in user_js
    assert "#nav-bar" in open(os.path.join(prof, "chrome", "userChrome.css")).read()  # ni barre d'adresse ni onglets


def test_firefox_hors_snap_garde_son_profil_dans_xdg_data(monkeypatch, tmp_path):
    m = _linux()
    launched = _fake(monkeypatch, m, tmp_path, {"firefox"})
    m.open_app("http://x/")
    assert launched[0][3] == f"{tmp_path}/share/golem/installer-browser/firefox"


def test_sans_navigateur_un_onglet_et_none(monkeypatch, tmp_path):
    m = _linux()
    launched = _fake(monkeypatch, m, tmp_path, set())
    assert m.open_app("http://x/") is None
    assert launched == [["xdg-open", "http://x/"]]


# ── la désinstallation : Chromium seulement s'il a été posé par golem ; les profils snap dédiés ──

@pytest.fixture
def fs(tmp_path, monkeypatch):
    f = machine(tmp_path / "fs")
    monkeypatch.setenv("GOLEM_RECEIPT", f.p(HOME + "/.local/share/golem/install-receipt.json"))
    return f


def _ids(plan):
    return {i["id"]: i for i in plan["items"]}


def test_chromium_pose_par_golem_est_propose_decoche(fs):
    d = receipt_data()
    d["prior"]["chromium"] = {"installed_by_golem": True}
    fs.receipt(d)
    fs.file("/snap/chromium/current/x")
    it = _ids(U.build_plan(fs.ctx()))["system:chromium-snap"]
    assert it["default"] is False and it["privilege"] == "root" and it["action"] == "snap-remove"
    script, refused = U.root_script(fs.ctx(), [it], None, set())
    assert not refused and "snap remove chromium" in script


def test_chromium_deja_la_avant_golem_n_est_pas_propose(fs):
    d = receipt_data()
    d["prior"]["chromium"] = {"installed_by_golem": False}
    fs.receipt(d)
    fs.file("/snap/chromium/current/x")
    assert "system:chromium-snap" not in _ids(U.build_plan(fs.ctx()))


def test_les_profils_snap_dedies_partent_avec_golem(fs):
    fs.receipt(receipt_data())
    fs.file(HOME + "/snap/firefox/common/golem-installer/user.js")
    fs.file(HOME + "/snap/chromium/common/golem-browser/Default/Prefs")
    fs.file(HOME + "/snap/firefox/common/.mozilla/firefox/mine/places.sqlite")       # celui de l'utilisateur
    it = _ids(U.build_plan(fs.ctx()))["golem:snap-profiles"]
    assert it["default"] is True
    assert sorted(it["paths"]) == ["~/snap/chromium/common/golem-browser", "~/snap/firefox/common/golem-installer"]


# ── sudo-rs (Ubuntu 25.10+) n'utilise SUDO_ASKPASS qu'avec -A : le shim `sudo` du job (2026-11-03) ──

def test_job_env_met_le_shim_sudo_A_en_tete_du_path(monkeypatch, tmp_path):
    m = _linux()
    real = tmp_path / "bin" / "sudo"
    real.parent.mkdir()
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    monkeypatch.setattr(m, "ASKPASS_BASE", str(tmp_path))
    monkeypatch.setattr(m, "_ASKPASS_DIR", None)
    monkeypatch.setenv("PATH", f"{real.parent}:/usr/bin")
    env = m.job_env({"PATH": f"{real.parent}:/usr/bin"}, {"sudo_pw": "pw"})
    d = m._ASKPASS_DIR
    try:
        assert env["PATH"].split(os.pathsep)[0] == d and env["SUDO_ASKPASS"] == os.path.join(d, "askpass")
        shim = open(os.path.join(d, "sudo")).read()
        assert f"exec {real} -A \"$@\"" in shim                  # chemin RÉSOLU en dur, jamais un `sudo` nu
        assert oct(os.stat(d).st_mode & 0o777) == "0o700"
        # rejoué (chaque étape appelle job_env) : le shim n'apparaît qu'une fois, et le vrai sudo n'est pas le shim
        env2 = m.job_env(dict(env), {"sudo_pw": "pw"})
        assert env2["PATH"].split(os.pathsep).count(d) == 1
        assert m._real_sudo(env2["PATH"]) == str(real)
    finally:
        m.cleanup()
    assert not os.path.exists(d)                                   # parti avec l'askpass


def test_sans_mot_de_passe_ni_shim_ni_path_touche(monkeypatch):
    m = _linux()
    env = m.job_env({"PATH": "/usr/bin"}, {"sudo_pw": ""})
    assert env["PATH"] == "/usr/bin" and "SUDO_ASKPASS" not in env


# ── « Open golem » (écran Done) : la fenêtre golem desktop, pas un onglet, et l'installateur se ferme (2026-11-03) ──

def test_finish_lance_golem_desktop_detache_sans_le_mot_de_passe(monkeypatch, tmp_path):
    m = _linux()
    (tmp_path / "provision").mkdir()
    (tmp_path / "provision" / "golem").write_text("#!/bin/sh\n")
    monkeypatch.setenv("GOLEM_SUDO_PW", "secret")
    monkeypatch.setenv("SUDO_ASKPASS", "/tmp/x/askpass")
    seen = {}
    monkeypatch.setattr(m.subprocess, "Popen", lambda argv, **kw: seen.update(argv=argv, **kw))

    class Ctx:
        S = {"dry": False, "dir": str(tmp_path)}
    assert m.finish(Ctx) is True
    assert seen["argv"] == [str(tmp_path / "provision" / "golem"), "desktop"]
    assert seen["start_new_session"] is True                       # survit à l'installateur
    assert "GOLEM_SUDO_PW" not in seen["env"] and "SUDO_ASKPASS" not in seen["env"]
    # le dossier du shim sudo, s'il est dans le PATH hérité, n'est pas transmis
    monkeypatch.setattr(m, "_ASKPASS_DIR", str(tmp_path / "shim"))
    monkeypatch.setenv("PATH", f"{tmp_path / 'shim'}:/usr/bin")
    m.finish(Ctx)
    assert seen["env"]["PATH"] == "/usr/bin"
    assert m.ui()["finish"] == "Open golem"                         # l'écran Done montre le bouton de fin


def test_finish_sans_golem_installe_refuse(tmp_path):
    m = _linux()

    class Ctx:
        S = {"dry": False, "dir": str(tmp_path)}
    assert m.finish(Ctx) is False


# ── le redémarrage de fin : seulement quand l'install vient de donner le groupe audio à une session qui ne l'a pas ──

def _groups(monkeypatch, m, members, session_gids, gid=29):
    import collections
    G = collections.namedtuple("G", "gr_gid gr_mem")
    U_ = collections.namedtuple("U", "pw_name pw_gid")
    monkeypatch.setattr(m.grp, "getgrnam", lambda n: G(gid, members))
    monkeypatch.setattr(m.pwd, "getpwuid", lambda uid: U_("alex", 1000))
    monkeypatch.setattr(m.os, "getgroups", lambda: session_gids)


def test_redemarrage_du_seulement_si_la_session_n_a_pas_encore_audio(monkeypatch):
    m = _linux()
    _groups(monkeypatch, m, ["alex"], [1000, 27])                 # ajouté par l'install, session d'avant
    assert m.restart_needed() is True
    _groups(monkeypatch, m, ["alex"], [1000, 27, 29])             # déjà dans audio (ou session neuve)
    assert m.restart_needed() is False
    _groups(monkeypatch, m, [], [1000])                           # pas membre du tout : rien à redémarrer
    assert m.restart_needed() is False


def test_restart_arrete_golem_puis_redemarre(monkeypatch, tmp_path):
    m = _linux()
    (tmp_path / "provision").mkdir()
    (tmp_path / "provision" / "golem").write_text("#!/bin/sh\n")
    calls = []

    class R:
        returncode, stderr = 0, ""
    monkeypatch.setattr(m.subprocess, "run", lambda argv, **kw: (calls.append(argv), R())[1])

    class Ctx:
        S = {"dry": False, "dir": str(tmp_path)}
        log = staticmethod(lambda *a: None)
    assert m.restart(Ctx) == (True, None)
    assert calls == [[str(tmp_path / "provision" / "golem"), "stop"], ["systemctl", "reboot"]]   # golem d'abord


def test_restart_refuse_est_dit(monkeypatch, tmp_path):
    m = _linux()

    class R:
        returncode, stderr = 1, "Access denied"
    monkeypatch.setattr(m.subprocess, "run", lambda argv, **kw: R())

    class Ctx:
        S = {"dry": False, "dir": str(tmp_path)}
    assert m.restart(Ctx) == (False, "Access denied")
