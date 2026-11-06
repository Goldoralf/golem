# SPDX-License-Identifier: GPL-3.0-or-later
"""Cet ordinateur, depuis l'app (docs/installer.md §4, FIXÉ 2026-10-16) : `profile` suit la fenêtre, « Show on this
computer » (ui.can_show), « Start golem with this computer » (autostart SANS durcissement) et « Lock down this
machine » (Linux, mot de passe par askpass). Tout est simulé : aucune fenêtre, aucun sudo, aucun systemctl réel."""
import asyncio
import json
import os
import subprocess
import sys
import time

import pytest

from bridge import auth, machine
from bridge import config as C
from bridge import routes_machine as R



class Req:
    """Le stub de tests/test_audit_2026_10_15_security.py (docs/howto/add-api-route.md)."""
    def __init__(self, method, path, tok="", client="192.168.0.25", host="192.168.0.22:8770", origin=None):
        self.method = method
        self.headers = {"host": host, **({"x-golem-token": tok} if tok else {}), **({"origin": origin} if origin else {})}
        self.cookies, self.query_params = {}, {}
        self.url = type("U", (), {"path": path, "hostname": host.split(":")[0]})()
        self.client = type("C", (), {"host": client})()


DEVS = {"musician": {"id": "m"}, "guest": {"id": "g", "expires": 9e12, "person": "guest:bob"},
        "admin": {"id": "a", "admin": True}}

PROV = os.path.join(C.ROOT, "provision")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    machine._reset_for_tests()
    monkeypatch.delenv("GOLEM_MACHINE_DRY", raising=False)
    monkeypatch.delenv("GOLEM_LAUNCH", raising=False)

    def no_proc(*a, **k):
        raise AssertionError(f"a real process was started: {a}")
    monkeypatch.setattr(subprocess, "Popen", no_proc)
    monkeypatch.setattr(subprocess, "run", no_proc)
    yield
    machine._reset_for_tests()


@pytest.fixture
def devs(monkeypatch):
    monkeypatch.setattr(auth, "_device_by_token", lambda t: DEVS.get(t))


# l'écran du rack : seul client admis à envoyer le mot de passe (audit 2026-11-04, M5)
_LOCAL = type("Req", (), {"client": type("C", (), {"host": "127.0.0.1"})()})()


def _body(r):
    if isinstance(r, dict):
        return r, 200
    return json.loads(r.body), r.status_code


# ── paliers ─────────────────────────────────────────────────────────────────────────────────────
ROUTES = (("POST", "/api/ui/show"), ("GET", "/api/system/autostart"), ("POST", "/api/system/autostart"),
          ("GET", "/api/system/harden"), ("POST", "/api/system/harden"))


@pytest.mark.parametrize("method,path", ROUTES)
def test_seul_l_admin_et_l_ordinateur_passent(devs, method, path):
    assert auth.allowed_http(Req(method, path)) is False                       # LAN, jamais appairé
    assert auth.allowed_http(Req(method, path, "musician")) is False           # appairé, pas admin
    assert auth.allowed_http(Req(method, path, "guest")) is False              # invité
    assert auth.allowed_http(Req(method, path, "admin")) is True               # appareil principal
    assert auth.allowed_http(Req(method, path, client="127.0.0.1", host="localhost:8770")) is True   # l'ordinateur


def test_les_routes_sont_sous_le_palier_admin():
    for _, path in ROUTES:
        assert path in auth.ADMIN_PATHS, path
    for path in ("/api/system/autostart", "/api/system/harden"):
        assert path in auth.SENSITIVE_GET, path                               # sinon un GET ne serait pas gardé
    paths = {r.path for r in R.router.routes}
    assert {p for _, p in ROUTES} <= paths


# ── profile suit la fenêtre ───────────────────────────────────────────────────────────────────────
def test_profile_suit_la_fenetre(monkeypatch):
    assert machine.profile() == "desktop"                                      # avant toute fenêtre : GOLEM_LAUNCH
    monkeypatch.setenv("GOLEM_LAUNCH", "server")
    assert machine.profile() == "server"
    machine.window_opened()
    assert machine.profile() == "desktop" and machine.windows() == 1
    machine.window_opened()
    machine.window_closed()
    assert machine.profile() == "desktop"                                      # il en reste une
    machine.window_closed()
    t = time.monotonic()
    assert machine.profile(now=t) == "desktop"                                 # un ↻ ne bascule pas
    assert machine.profile(now=t + machine.GRACE_S + 0.1) == "server"          # la dernière s'est fermée
    machine.window_opened()
    assert machine.profile() == "desktop"


def test_seule_une_fenetre_de_l_ordinateur_compte():
    assert machine.is_window_ws("device", "127.0.0.1") and machine.is_window_ws("ui", "::1")
    assert not machine.is_window_ws("device", "192.168.0.25")                  # une tablette qui prétend
    assert not machine.is_window_ws(None, "127.0.0.1") and not machine.is_window_ws("phone", "127.0.0.1")


def test_l_etat_porte_profile_et_ui(monkeypatch):
    monkeypatch.setattr(machine, "can_show", lambda max_age=5.0: {"ok": False, "why": machine.NO_SESSION})
    from bridge.state import state
    snap = state.snapshot()
    assert snap["profile"] in ("desktop", "server")
    assert snap["ui"]["can_show"] == {"ok": False, "why": machine.NO_SESSION}
    from bridge import rigstatus
    assert rigstatus._profile() == machine.profile()


# ── can_show ──────────────────────────────────────────────────────────────────────────────────────
def _linux(monkeypatch, env, sysenv=None, session=None):
    monkeypatch.setattr(sys, "platform", "linux")
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(machine, "_systemd_user_env", lambda: dict(sysenv or {}))
    monkeypatch.setattr(machine, "_graphical_session", lambda: session)


def test_linux_sans_session_pas_d_ecran(monkeypatch):
    _linux(monkeypatch, {})
    assert machine.can_show(max_age=0) == {"ok": False, "why": machine.NO_SESSION}
    _linux(monkeypatch, {"DISPLAY": ":99"})                                    # l'Xvfb de REAPER n'est pas un écran
    assert machine.can_show(max_age=0)["ok"] is False
    _linux(monkeypatch, {"DISPLAY": "localhost:10.0"})                         # ssh -X : un écran ailleurs
    assert machine.can_show(max_age=0)["ok"] is False


def test_linux_boot_sans_session_meme_avec_un_display_herite(monkeypatch, tmp_path):
    sock = tmp_path / "wayland-0"
    sock.write_text("")
    _linux(monkeypatch, {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": str(tmp_path)}, session=False)
    assert machine.can_show(max_age=0)["ok"] is False                          # logind : aucune session graphique


def test_linux_session_wayland_joignable(monkeypatch, tmp_path):
    (tmp_path / "wayland-0").write_text("")
    _linux(monkeypatch, {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": str(tmp_path)}, session=True)
    assert machine.can_show(max_age=0) == {"ok": True, "why": None}


def test_linux_session_ouverte_apres_le_boot(monkeypatch, tmp_path):
    # golem parti au boot (linger) sans DISPLAY ; l'utilisateur s'est connecté depuis : systemd --user le publie
    (tmp_path / "wayland-0").write_text("")
    _linux(monkeypatch, {}, sysenv={"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": str(tmp_path)}, session=True)
    env = machine.linux_display_env()
    assert env["WAYLAND_DISPLAY"] == "wayland-0" and machine.can_show(max_age=0)["ok"]


def test_windows_et_macos_session_de_l_utilisateur(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert machine.can_show(max_age=0)["ok"] is True
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SESSIONNAME", "Console")
    monkeypatch.setenv("USERNAME", "alex")
    assert machine.can_show(max_age=0)["ok"] is True
    monkeypatch.setenv("SESSIONNAME", "Services")
    assert machine.can_show(max_age=0)["ok"] is False


# ── POST /api/ui/show ─────────────────────────────────────────────────────────────────────────────
def test_show_refuse_sans_ecran_avec_la_raison(monkeypatch):
    _linux(monkeypatch, {})
    r, code = _body(asyncio.run(R.ui_show({})))
    assert code == 409 and r == {"ok": False, "why": machine.NO_SESSION}


def test_show_dry_n_ouvre_rien(monkeypatch):
    monkeypatch.setenv("GOLEM_MACHINE_DRY", "1")
    monkeypatch.setattr(machine, "can_show", lambda max_age=5.0: {"ok": True, "why": None})
    r, code = _body(asyncio.run(R.ui_show({})))
    assert code == 200 and r["ok"] and r["dry"]


def test_show_linux_lance_golem_window_sur_la_session(monkeypatch, tmp_path):
    (tmp_path / "wayland-0").write_text("")
    _linux(monkeypatch, {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": str(tmp_path)}, session=True)
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: calls.append((argv, k)))
    assert machine.show()["ok"] is True
    argv, k = calls[0]
    assert argv == [os.path.join(C.ROOT, "provision", "golem"), "window"]
    assert k["env"]["WAYLAND_DISPLAY"] == "wayland-0" and k["start_new_session"] is True


def test_show_windows_reutilise_open_window(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(machine, "can_show", lambda max_age=5.0: {"ok": True, "why": None})
    from provision import desktop
    opened = []
    monkeypatch.setattr(desktop, "open_window", lambda port, *a, **k: opened.append(port))
    assert machine.show(8770)["ok"] and opened == [8770]


def test_golem_window_ouvre_seulement_la_fenetre():
    src = open(os.path.join(PROV, "golem"), encoding="utf-8").read()
    line = next(ln for ln in src.splitlines() if ln.strip().startswith("window)"))
    assert "desktop" in line and "start" not in line                           # la pile n'est pas relancée


# ── autostart ─────────────────────────────────────────────────────────────────────────────────────
def test_autostart_linux_lance_le_script_sans_durcir(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "✅ golem démarrera avec la machine", ""

    def fake_run(argv, **k):
        calls.append(argv)
        return Done()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(machine, "autostart_status", lambda: {"on": True, "hint": machine.LINUX_HINT})
    r, code = _body(asyncio.run(R.autostart_post({"on": True})))
    assert code == 200 and r["ok"] and r["on"]
    assert calls[0] == [os.path.join(PROV, "autostart", "install-autostart.sh")]
    asyncio.run(R.autostart_post({"on": False}))
    assert calls[1][-1] == "--off"
    assert not any("harden" in " ".join(c) for c in calls)


def test_autostart_linux_echec_dit_pourquoi(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")

    class Fail:
        returncode, stdout, stderr = 3, "▶ Service\n✗ could not let golem start without a sign-in", ""
    monkeypatch.setattr(subprocess, "run", lambda argv, **k: Fail())
    monkeypatch.setattr(machine, "autostart_status", lambda: {"on": False})
    r, code = _body(asyncio.run(R.autostart_post({"on": True})))
    assert code == 500 and not r["ok"] and "sign-in" in r["why"]


def test_autostart_corps_invalide():
    r, code = _body(asyncio.run(R.autostart_post({"on": "yes"})))
    assert code == 400


def test_autostart_windows_par_provision_desktop_et_l_ouverture_de_session(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    from provision import desktop
    link = tmp_path / "golem server.lnk"
    monkeypatch.setattr(desktop, "_startup_link", lambda: link)

    def fake(state):
        (link.write_text("x") if state == "on" else link.unlink(missing_ok=True))
        return "autostart: " + state
    monkeypatch.setattr(desktop, "autostart", fake)
    r = machine.autostart_set(True)
    assert r["ok"] and r["on"] and "automatic sign-in" in r["hint"] and r["message"] == "autostart: on"
    assert machine.autostart_status()["on"] is True
    assert machine.autostart_set(False)["on"] is False


def test_autostart_dry(monkeypatch):
    monkeypatch.setenv("GOLEM_MACHINE_DRY", "1")
    assert machine.autostart_set(True)["on"] is True and machine.autostart_status()["on"] is True


def test_l_autostart_ne_durcit_plus():
    src = open(os.path.join(PROV, "autostart", "install-autostart.sh"), encoding="utf-8").read()
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "harden" not in code and "golem-perf" not in code and "governor" not in code
    # le linger sans sudo d'abord (lancé par l'app, personne au terminal), jamais d'invite
    assert 'loginctl enable-linger "$USER" 2>/dev/null ||' in code
    hard = open(os.path.join(PROV, "harden.sh"), encoding="utf-8").read()
    assert "golem-perf.service" in hard
    assert hard.index("receipt prior governor") < hard.index("systemctl enable --now golem-perf.service")
    assert hard.index("receipt_add /etc/systemd/system/golem-perf.service") < hard.index("sudo install -m 644")


# ── verrouiller la machine ────────────────────────────────────────────────────────────────────────
def test_harden_linux_seulement(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    r, code = _body(asyncio.run(R.harden_post(_LOCAL, {"password": "x"})))
    assert code == 409 and "Linux" in r["why"]
    assert machine.harden_status()["available"] is False


def test_harden_mot_de_passe_vide_ou_faux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    r, code = _body(asyncio.run(R.harden_post(_LOCAL, {})))
    assert code == 400
    monkeypatch.setattr(machine, "sudo_check", lambda pw: (False, "wrong password"))
    r, code = _body(asyncio.run(R.harden_post(_LOCAL, {"password": "nope"})))
    assert code == 400 and r["error"] == "wrong password"


def test_harden_dry(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("GOLEM_MACHINE_DRY", "1")
    r, code = _body(asyncio.run(R.harden_post(_LOCAL, {"password": "x"})))
    assert code == 200 and r["applied"] and r["dry"]


def test_harden_le_mot_de_passe_ne_touche_jamais_le_disque(monkeypatch, caplog):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(machine, "sudo_check", lambda pw: (True, None))
    SECRET = "s3cr3t-Pa55"
    seen = {}

    class Proc:
        def __init__(self, argv, **k):
            seen["argv"], seen["env"] = argv, k["env"]
            helper = k["env"]["SUDO_ASKPASS"]
            seen["helper"], seen["helper_txt"] = helper, open(helper).read()
            seen["mode"] = os.stat(os.path.dirname(helper)).st_mode & 0o777
            self.stdout = iter(["▶ Pare-feu\n", "✅ Durcissement appliqué.\n"])

        def wait(self):
            return 0
    monkeypatch.setattr(subprocess, "Popen", Proc)
    caplog.set_level("DEBUG")
    r = machine.harden_start(SECRET)
    assert r["ok"]
    for _ in range(100):
        if machine.harden_status()["phase"] != "running":
            break
        time.sleep(0.02)
    st = machine.harden_status()
    assert st["phase"] == "done" and st["log"][-1].startswith("✅")
    assert seen["argv"] == [os.path.join(PROV, "harden.sh")]
    assert SECRET not in " ".join(seen["argv"])
    assert seen["env"]["GOLEM_SUDO_PW"] == SECRET and seen["env"]["GOLEM_KIOSK_OK"] == "1"
    assert SECRET not in seen["helper_txt"] and "$GOLEM_SUDO_PW" in seen["helper_txt"]
    if os.name == "posix":                                   # Windows n'a pas de bits de mode
        assert seen["mode"] == 0o700
    assert not os.path.exists(seen["helper"])                                  # le helper part avec le job
    assert SECRET not in caplog.text and SECRET not in json.dumps(st)


def test_harden_statut_par_les_fichiers_poses(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    mark = tmp_path / "90-golem-usb-power.rules"
    monkeypatch.setattr(machine, "HARDEN_MARKERS", (str(mark),))
    monkeypatch.setattr(machine, "_receipt_says_hardened", lambda: False)
    assert machine.harden_status()["applied"] is False
    mark.write_text("x")
    assert machine.harden_status()["applied"] is True
