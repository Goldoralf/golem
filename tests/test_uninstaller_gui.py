# SPDX-License-Identifier: GPL-3.0-or-later
"""Le DÉSINSTALLATEUR graphique (docs/uninstall.md §4) : installer/server.py --uninstall, installer/uninstaller.py.

Rien ici ne lance la vraie désinstallation, la vraie sauvegarde, sudo ni un navigateur : les serveurs de bout en bout
tournent en --dry sur un FAUX système de fichiers (GOLEM_UNINSTALL_FSROOT, tests/uninstall_fixtures.py), et les
commandes du mode réel sont remplacées par des doublures (subprocess.run / Popen)."""
import importlib.util
import json
import zipfile
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from tests.uninstall_fixtures import HOME, INSTALL, machine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "installer", "server.py")

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="le désinstallateur graphique est Linux seulement")


def _server():
    spec = importlib.util.spec_from_file_location("golem_installer_u", SERVER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def srv(tmp_path):
    """Le module serveur, avec un état de désinstallateur NEUF (uninstaller.py est partagé entre les chargements)."""
    m = _server()
    UN = m.UN
    saved = json.loads(json.dumps(UN.U))
    UN._EST.clear()
    yield m
    try:
        m.P.cleanup()
    except Exception:
        pass
    m.P.ASKPASS_BASE = None
    UN.U.clear()
    UN.U.update(saved)
    UN.CTX = None
    m.S.update(sudo_ok=False, sudo_pw=None, log=[], mode="install")


def _wait(cond, secs=15):
    t0 = time.time()
    while time.time() - t0 < secs:
        if cond():
            return True
        time.sleep(0.05)
    return False


# ── la copie de soi dans /tmp ──────────────────────────────────────────────────────────────────────────
def test_la_copie_emporte_le_necessaire_et_part_proprement(srv, tmp_path):
    UN = srv.UN
    tmp = UN.self_copy(ROOT, base=str(tmp_path))
    assert os.path.basename(tmp).startswith("golem-uninstaller-")
    assert oct(os.stat(tmp).st_mode & 0o777) == "0o700"
    for rel in ("installer/server.py", "installer/platform_linux.py", "installer/uninstaller.py", "installer/dry_step.py", "installer/dry_bridge.py",
                "installer/ui/uninstall.html", "installer/ui/uninstaller.js", "installer/ui/installer.css",
                "provision/uninstall.py", "bridge/engines.py", "bridge/reaper_license.py",
                "app/vendor/htm-preact-standalone.module.js", UN.MARKER):
        assert os.path.isfile(os.path.join(tmp, rel)), rel
    assert not os.path.exists(os.path.join(tmp, "presets")) and not os.path.exists(os.path.join(tmp, ".venv"))
    assert UN.remove_tmp(tmp) is True and not os.path.exists(tmp)


def test_remove_tmp_n_efface_que_sa_copie(srv, tmp_path):
    UN = srv.UN
    other = tmp_path / "golem-uninstaller-pas-a-moi"
    other.mkdir()
    (other / "x").write_text("x")
    assert UN.remove_tmp(str(other)) is False and other.exists()           # pas de marqueur
    wrong = tmp_path / "ailleurs"
    wrong.mkdir()
    (wrong / UN.MARKER).write_text("")
    assert UN.remove_tmp(str(wrong)) is False and wrong.exists()           # pas le bon nom
    assert UN.remove_tmp(None) is False


def test_une_copie_incomplete_ne_laisse_rien(srv, tmp_path):
    src = tmp_path / "src"
    (src / "installer").mkdir(parents=True)
    (src / "installer" / "server.py").write_text("")
    base = tmp_path / "t"
    base.mkdir()
    with pytest.raises(FileNotFoundError):
        srv.UN.self_copy(str(src), base=str(base))
    assert list(base.iterdir()) == []


def test_le_premier_passage_se_copie_et_se_relance_depuis_la_copie(srv, tmp_path, monkeypatch):
    base = tmp_path / "t"
    base.mkdir()
    monkeypatch.setattr(srv.UN.tempfile, "tempdir", str(base))
    seen = {}

    class Exec(Exception):
        pass

    def fake_execv(path, argv):
        seen["argv"] = argv
        raise Exec()
    monkeypatch.setattr(srv.os, "execv", fake_execv)
    monkeypatch.setattr(srv.os, "chdir", lambda d: seen.setdefault("cwd", d))
    with pytest.raises(Exec):
        srv.main(["--uninstall", "--dry", "--root", "/home/u/golem", "--port", "8799"])
    (tmp,) = [str(p) for p in base.iterdir()]
    assert seen["cwd"] == tmp                                              # le moteur refuse le dossier d'où l'on part
    a = seen["argv"]
    assert a[0] == sys.executable and a[1] == os.path.join(tmp, "installer", "server.py")
    assert a[a.index("--root") + 1] == "/home/u/golem" and a[a.index("--owned-tmp") + 1] == tmp
    assert "--uninstall" in a and "--dry" in a and a[a.index("--port") + 1] == "8799" and "--open" not in a
    srv.UN.remove_tmp(tmp)


def test_un_relancement_rate_efface_la_copie(srv, tmp_path, monkeypatch):
    base = tmp_path / "t"
    base.mkdir()
    monkeypatch.setattr(srv.UN.tempfile, "tempdir", str(base))

    def boom(path, argv):
        raise OSError("exec format error")
    monkeypatch.setattr(srv.os, "execv", boom)
    monkeypatch.setattr(srv.os, "chdir", lambda d: None)
    with pytest.raises(OSError):
        srv.main(["--uninstall", "--root", "/home/u/golem"])
    assert list(base.iterdir()) == []


# ── de bout en bout, en --dry, sur un faux système de fichiers ───────────────────────────────────────────
class Live:
    def __init__(self, tmp_path, extra_env=None):
        self.fs = machine(tmp_path / "fs")
        self.fs.file(HOME + "/.local/share/applications/golem-uninstall.desktop")
        self.tdir = tmp_path / "t"
        self.tdir.mkdir()
        env = dict(os.environ)
        env.update({"GOLEM_UNINSTALL_FSROOT": self.fs.base, "HOME": HOME, "TMPDIR": str(self.tdir),
                    "GOLEM_RECEIPT": self.fs.p(HOME + "/.local/share/golem/install-receipt.json")})
        env.pop("GOLEM_INSTALLER_DRY", None)
        env.update(extra_env or {})
        self.p = subprocess.Popen([sys.executable, SERVER, "--uninstall", "--dry", "--root", INSTALL, "--port", "0"],
                                  cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.url = None
        t0 = time.time()
        while time.time() - t0 < 20:
            ln = self.p.stdout.readline()
            if "http://127.0.0.1:" in ln:
                self.url = ln.strip()
                break
            if not ln and self.p.poll() is not None:
                break
        assert self.url, "le serveur n'a pas donné son adresse"
        threading.Thread(target=self.p.stdout.read, daemon=True).start()     # ne jamais bloquer sa sortie
        self.base, self.tok = self.url.split("/?t=")

    def copies(self):
        return [p for p in self.tdir.iterdir() if p.name.startswith("golem-uninstaller-")]

    def call(self, path, body=None, token=True):
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json",
                                              **({"X-Golem-Token": self.tok} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw.startswith(b"{") else raw.decode())
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, (json.loads(raw) if raw.startswith(b"{") else raw.decode())

    def state(self):
        return self.call("/api/state")[1]["uninstall"]

    def stop(self):
        if self.p.poll() is None:
            self.p.send_signal(signal.SIGTERM)
        self.p.wait(timeout=10)


@pytest.fixture
def live(tmp_path):
    made = []

    def make(**env):
        lv = Live(tmp_path, env)
        made.append(lv)
        return lv
    yield make
    for lv in made:
        lv.stop()


def test_bout_en_bout_dry_rien_n_est_touche_et_la_copie_part_avec_le_serveur(live):
    lv = live()
    before = lv.fs.snapshot()
    (copy,) = lv.copies()
    assert (copy / "provision" / "uninstall.py").is_file()
    # le jeton : sans lui, rien
    code, body = lv.call("/", token=False)
    assert code == 403 and "uninstaller" in body
    assert lv.call("/api/state", token=False)[0] == 403
    code, page = lv.call("/?t=" + lv.tok, token=False)
    assert code == 200 and "uninstaller.js" in page
    st = lv.call("/api/state")[1]
    assert st["mode"] == "uninstall" and st["dry"] is True and "sudo_pw" not in st and "token" not in st
    assert st["uninstall"]["tmp"] == str(copy)
    # le plan, lu POUR DE VRAI (sur le faux arbre)
    plan = lv.call("/api/uplan")[1]
    ids = {i["id"] for i in plan["items"]}
    assert {"golem:install-folder", "golem:desktop:golem-uninstall.desktop", "system:/etc/sudoers.d/golem-net"} <= ids
    assert plan["golem_groups"][0] == "golem" and "apt" in plan["third_groups"]
    # pas de désinstallation avant la sauvegarde
    code, r = lv.call("/api/uninstall", {})
    assert code == 400 and "back up first" in r["error"]
    # la sauvegarde ne va jamais dans le dossier d'install
    r = lv.call("/api/backup/config", {"dest": INSTALL + "/backups"})[1]
    assert r["ok"] is False and "inside the golem install folder" in r["error"]
    est = lv.call("/api/backup/estimate")[1]
    assert est["simulated"] and est["need"] > 0
    assert lv.call("/api/backup/start", {})[0] == 200
    assert _wait(lambda: lv.state()["backup"]["state"] == "ok")
    # les tiers : une case cochée
    assert lv.call("/api/third", {"third": {"plugins:nam": True, "golem:command": False}})[1]["third"] == {"plugins:nam": True}
    rev = lv.call("/api/review")[1]
    assert rev["gate"] is None and rev["needs_password"] and "plugins:nam" in rev["ids"] and "golem:command" in rev["ids"]
    assert lv.call("/api/sudo", {"password": "golem"})[1]["ok"] is True
    assert lv.call("/api/uninstall", {})[0] == 200
    assert _wait(lambda: lv.state()["run"]["state"] == "done")
    run = lv.state()["run"]
    assert run["ok"] is True and run["failed"] == [] and set(run["chosen"]) == set(rev["ids"])
    assert all(run["items"][i]["ok"] for i in rev["ids"])
    assert set(run["steps"]) >= {"stop", "root", "reaper", "user", "folder", "receipt"}
    assert json.load(open(copy / "select-1.json")) == rev["ids"]          # la sélection passée au moteur
    assert lv.fs.snapshot() == before                                      # --dry : RIEN n'a bougé
    # une seconde désinstallation n'existe pas : seulement Retry
    assert lv.call("/api/uninstall", {})[0] == 400
    # Close : le serveur s'en va, et sa copie avec lui
    assert lv.call("/api/quit", {})[1]["ok"] is True
    lv.p.wait(timeout=10)
    assert lv.copies() == []


def test_sauvegarde_ratee_rien_ne_part(live):
    lv = live(GOLEM_DRY_FAIL="backup")
    lv.call("/api/sudo", {"password": "golem"})
    lv.call("/api/backup/start", {})
    assert _wait(lambda: lv.state()["backup"]["state"] == "fail")
    st = lv.state()
    assert "sha256 mismatch" in st["backup"]["error"] and "failed its verification" in st["gate"]
    code, r = lv.call("/api/uninstall", {})
    assert code == 400 and "failed its verification" in r["error"]
    assert lv.state()["run"]["attempt"] == 0
    lv.stop()                                                              # SIGTERM : même ménage
    assert lv.copies() == []


def test_un_element_qui_echoue_les_autres_continuent_puis_retry(live):
    lv = live(GOLEM_DRY_FAIL_ITEM="golem:command")
    lv.call("/api/backup/config", {"enabled": False})
    lv.call("/api/sudo", {"password": "golem"})
    assert lv.call("/api/uninstall", {})[0] == 200
    assert _wait(lambda: lv.state()["run"]["state"] == "done")
    run = lv.state()["run"]
    assert run["ok"] is False and run["failed"] == ["golem:command"]
    assert run["items"]["golem:install-folder"]["ok"] is True              # les autres ont continué
    assert lv.call("/api/uninstall/retry", {})[0] == 200
    assert _wait(lambda: lv.state()["run"]["state"] == "done" and lv.state()["run"]["attempt"] == 2)
    run = lv.state()["run"]
    assert run["ok"] is True and run["failed"] == [] and run["items"]["golem:command"]["ok"] is True


def test_une_desinstallation_ratee_fait_son_rapport_toute_seule(live, tmp_path):
    """Décision du 2026-10-27 (docs/diagnostics.md §7.1) : le rapport part SANS clic quand une désinstallation échoue —
    en --dry il est construit, jamais envoyé ; le mot de passe n'y est pas ; un Retry en refait un."""
    lv = live(GOLEM_DRY_FAIL_ITEM="golem:command")
    lv.call("/api/backup/config", {"enabled": False})
    lv.call("/api/sudo", {"password": "golem-secret-pw"})
    assert lv.call("/api/uninstall", {})[0] == 200
    assert _wait(lambda: (lv.state().get("report") or {}).get("state") == "dry")
    path = lv.state()["report"]["path"]
    assert path.startswith(str(lv.tdir)) and os.path.isfile(path)
    with zipfile.ZipFile(path) as z:
        rep = json.loads(z.read("report.json"))
        blob = b"".join(z.read(n) for n in z.namelist())
    assert rep["report"]["kind"] == "uninstall" and rep["install"]["failed_items"] == ["golem:command"]
    assert rep["golem"]["dry"] is True and b"golem-secret-pw" not in blob
    assert lv.call("/api/uninstall/retry", {})[0] == 200
    assert _wait(lambda: lv.state()["run"]["attempt"] == 2 and lv.state()["run"]["state"] == "done")
    assert lv.state()["run"]["ok"] is True and not (lv.state().get("report") or {}).get("state")   # réussi : rien


def test_sans_venv_il_faut_confirmer_de_continuer_sans_sauvegarde(live):
    lv = live(GOLEM_DRY_NO_VENV="1")
    st = lv.state()
    assert st["venv"] is False and st["backup"]["enabled"] is False and "confirm" in st["gate"]
    r = lv.call("/api/backup/config", {"enabled": True})[1]
    assert r["ok"] is False and "missing" in r["error"]
    assert lv.call("/api/backup/start", {})[0] == 400
    lv.call("/api/sudo", {"password": "golem"})
    assert lv.call("/api/uninstall", {})[0] == 400
    lv.call("/api/backup/config", {"skip_confirmed": True})
    assert lv.state()["gate"] is None
    assert lv.call("/api/uninstall", {})[0] == 200


# ── le mode RÉEL, commandes remplacées par des doublures ─────────────────────────────────────────────────
def _real(srv, tmp_path, venv=True):
    root = tmp_path / "golem"
    root.mkdir()
    if venv:
        py = root / ".venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)
    copy = tmp_path / "golem-uninstaller-x"
    copy.mkdir()
    srv.S.update(mode="uninstall", dry=False, log=[])
    srv.UN.init(srv.Ctx, str(root), str(copy), dry=False)
    srv.P.ASKPASS_BASE = str(copy)
    srv.UN.U["plan"] = {"mode": "receipt", "root": str(root), "items": [
        {"id": "golem:install-folder", "group": "golem", "default": True, "privilege": "user"},
        {"id": "system:/etc/sudoers.d/golem-net", "group": "system", "default": True, "privilege": "root"},
        {"id": "system:audio-group", "group": "system", "default": False, "privilege": "root"},
        {"id": "plugins:nam", "group": "plugins", "default": True, "privilege": "user"},
        {"id": "plugins:dexed", "group": "plugins", "default": False, "privilege": "user"},
        {"id": "reaper:config", "group": "reaper", "default": False, "privilege": "user"},
    ]}
    return root, copy


def test_la_sauvegarde_tourne_avec_le_venv_dans_le_dossier_d_install(srv, tmp_path, monkeypatch):
    root, copy = _real(srv, tmp_path)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"ok": True, "dest": "/b", "files": [],
                                                                      "verified": {"golem-all-x.zip": 3}}), stderr="")
    monkeypatch.setattr(srv.UN.subprocess, "run", fake_run)
    srv.UN.set_backup({"dest": str(tmp_path / "bk"), "secrets": True})
    assert srv.UN.start_backup() is None
    assert _wait(lambda: srv.UN.U["backup"]["state"] == "ok")
    assert seen["cmd"][:4] == [str(root / ".venv/bin/python"), "-m", "bridge.backup_cli", "full"]
    assert seen["cmd"][seen["cmd"].index("--dest") + 1] == str(tmp_path / "bk")
    assert "--json" in seen["cmd"] and "--secrets" in seen["cmd"] and seen["cwd"] == str(root)


def test_verification_ratee_refuse_de_desinstaller(srv, tmp_path, monkeypatch):
    _real(srv, tmp_path)
    monkeypatch.setattr(srv.UN.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout=json.dumps({"ok": False, "error": "golem-all-x.zip: sha256 mismatch"}), stderr=""))
    popen = []
    monkeypatch.setattr(srv.UN.subprocess, "Popen", lambda *a, **k: popen.append(a))
    srv.UN.start_backup()
    assert _wait(lambda: srv.UN.U["backup"]["state"] == "fail")
    srv.S.update(sudo_ok=True, sudo_pw="pw")
    err = srv.UN.start_run()
    assert err and "failed its verification" in err and popen == [] and srv.UN.U["run"]["attempt"] == 0
    # un « ok » sans vérification n'est pas une sauvegarde vérifiée
    monkeypatch.setattr(srv.UN.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, stdout=json.dumps({"ok": True}), stderr=""))
    srv.UN.start_backup()
    assert _wait(lambda: srv.UN.U["backup"]["state"] == "fail")
    assert srv.UN.start_run() is not None and popen == []


def test_la_selection_passee_au_moteur(srv, tmp_path, monkeypatch):
    root, copy = _real(srv, tmp_path)
    srv.UN.U["backup"].update(state="ok", result={"dest": str(tmp_path / "bk"), "files": []})
    (tmp_path / "bk").mkdir()
    srv.UN.set_third({"plugins:nam": False, "plugins:dexed": True, "golem:install-folder": False})
    calls = []

    class FakeP:
        def __init__(self, cmd, **kw):
            calls.append((cmd, kw))
            sel = json.load(open(cmd[cmd.index("--select") + 1]))
            lines = [json.dumps({"step": "root", "item": i, "ok": True, "msg": "ok"}) for i in sel]
            lines.append(json.dumps({"step": "done", "item": None, "ok": True, "msg": "all"}))
            self.stdout = iter(ln + "\n" for ln in lines)

        def wait(self):
            return 0
    monkeypatch.setattr(srv.UN.subprocess, "Popen", FakeP)
    assert srv.UN.start_run() == "your password first"                     # un élément root : le mot de passe d'abord
    srv.S.update(sudo_ok=True, sudo_pw="s3cret")
    assert srv.UN.start_run() is None
    assert _wait(lambda: srv.UN.U["run"]["state"] == "done")
    (cmd, kw), = calls
    sel = cmd[cmd.index("--select") + 1]
    assert cmd[:3] == [sys.executable, str(copy / "provision" / "uninstall.py"), "run"]
    assert cmd[cmd.index("--root") + 1] == str(root) and "--yes" in cmd and "--json" in cmd
    assert os.path.dirname(cmd[cmd.index("--log") + 1]) == str(tmp_path / "bk")    # le journal survit, à côté de la sauvegarde
    # le groupe golem tel que le moteur le propose (lecture seule) ; les tiers selon les cases
    assert json.load(open(sel)) == ["golem:install-folder", "system:/etc/sudoers.d/golem-net", "plugins:dexed"]
    assert kw["cwd"] == str(copy)
    env = kw["env"]
    assert env["GOLEM_SUDO_PW"] == "s3cret" and os.path.dirname(os.path.dirname(env["SUDO_ASKPASS"])) == str(copy)
    assert env["GOLEM_UNINSTALLER_COPY"] == str(copy)          # Windows : le veilleur efface la copie après nous
    assert "s3cret" not in open(env["SUDO_ASKPASS"]).read()
    assert srv.UN.U["run"]["ok"] is True


def test_retirer_les_reglages_reaper_demande_une_sauvegarde_verifiee(srv, tmp_path):
    _real(srv, tmp_path)
    srv.UN.set_backup({"enabled": False})
    srv.UN.set_third({"reaper:config": True})
    assert "license" in srv.UN.review()["gate"]
    srv.S.update(sudo_ok=True, sudo_pw="pw")
    assert "license" in srv.UN.start_run()


def test_la_destination_ne_peut_pas_etre_dans_le_dossier_d_install(srv, tmp_path):
    root, copy = _real(srv, tmp_path)
    assert "install folder" in srv.UN.set_backup({"dest": str(root / "x")})
    assert "temporary copy" in srv.UN.set_backup({"dest": str(copy / "x")})
    assert srv.UN.set_backup({"dest": str(tmp_path / "ok")}) is None
    assert srv.UN.U["backup"]["dest"] == str(tmp_path / "ok")


# ── la simulation, le lanceur, l'entrée de bureau, l'estimation ───────────────────────────────────────────
def test_la_simulation_parle_comme_le_moteur(tmp_path):
    plan = {"items": [{"id": "system:/etc/x", "privilege": "root", "group": "system", "action": "remove"},
                      {"id": "golem:install-folder", "privilege": "user", "group": "golem", "action": "remove"},
                      {"id": "reaper-ini:revert", "privilege": "user", "group": "reaper-ini", "action": "revert"},
                      {"id": "golem:command", "privilege": "user", "group": "golem", "action": "remove"}]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "sel.json").write_text(json.dumps([i["id"] for i in plan["items"]]))
    dry = os.path.join(ROOT, "installer", "dry_step.py")

    def go(attempt, env=None):
        r = subprocess.run([sys.executable, dry, "uninstall-run", str(tmp_path / "sel.json"), str(tmp_path / "plan.json"),
                            "--attempt", str(attempt)], capture_output=True, text=True, env={**os.environ, **(env or {})})
        return r.returncode, [json.loads(ln) for ln in r.stdout.splitlines()]
    rc, ev = go(1)
    steps = [e["step"] for e in ev]
    assert rc == 0 and steps == ["stop", "stop", "root", "reaper", "user", "folder", "receipt", "done"]
    assert all(set(e) == {"step", "item", "ok", "msg"} for e in ev)
    rc, ev = go(1, {"GOLEM_DRY_FAIL_ITEM": "golem:command"})
    assert rc == 1 and ev[-1]["ok"] is False and [e["item"] for e in ev if not e["ok"]] == ["golem:command", None]
    assert go(2, {"GOLEM_DRY_FAIL_ITEM": "golem:command"})[0] == 0           # Retry passe


def test_golem_uninstall_ouvre_le_desinstallateur_et_dry_run_reste_le_plan_texte():
    sh = open(os.path.join(ROOT, "provision", "golem"), encoding="utf-8").read()
    body = sh[sh.index("uninstall() {"):sh.index("\n}\n", sh.index("uninstall() {"))]
    assert 'uninstall.py" plan --root "$HERE"' in body                      # --dry-run : le plan, en texte
    assert 'exec python3 "$HERE/installer/server.py" --uninstall --root "$HERE" --open' in body
    assert "coming" not in body


def test_l_entree_de_bureau_est_notee_et_retiree():
    sh = open(os.path.join(ROOT, "provision", "install-desktop.sh"), encoding="utf-8").read()
    assert '"$APPS/golem-uninstall.desktop"' in sh and 'receipt_add "$APPS/golem-uninstall.desktop" file golem' in sh
    assert "Name=Uninstall golem" in sh and "Exec=$BIN/golem uninstall" in sh
    from provision import uninstall as Ueng
    import fnmatch
    assert any(fnmatch.fnmatch("~/.local/share/applications/golem-uninstall.desktop", p) for p in Ueng.EXPECTED)


def test_le_plan_porte_l_entree_de_desinstallation(tmp_path):
    from provision import uninstall as Ueng
    fs = machine(tmp_path / "fs")
    fs.file(HOME + "/.local/share/applications/golem-uninstall.desktop")
    plan = Ueng.build_plan(fs.ctx())
    it = next(i for i in plan["items"] if i["id"] == "golem:desktop:golem-uninstall.desktop")
    assert it["group"] == "golem" and it["default"] is True


def test_l_estimation_de_la_sauvegarde_n_ecrit_rien(tmp_path, monkeypatch, capsys):
    from bridge import backup_cli as CLI, config as C
    monkeypatch.setattr(C, "ROOT", str(tmp_path / "rack"))
    monkeypatch.setattr(CLI, "estimate", lambda secrets=False: 5_000_000 + (1000 if secrets else 0))
    dest = tmp_path / "bk"
    assert CLI.main(["estimate", "--dest", str(dest), "--secrets"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["ok"] and r["bytes"] == 5_001_000 and r["need"] > r["bytes"] and r["free"] > 0
    assert r["inside_install"] is False and not dest.exists()
    r = CLI.estimate_report(str(tmp_path / "rack" / "x"))
    assert r["inside_install"] is True


def test_la_simulation_dit_les_paquets_et_leurs_dependances(tmp_path):
    plan = {"items": [{"id": "apt:x42-plugins", "privilege": "root", "group": "apt", "action": "purge"},
                      {"id": "golem:command", "privilege": "user", "group": "golem", "action": "remove"}],
            "apt_deps": ["libx42-a", "libx42-b"]}
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "sel.json").write_text(json.dumps([i["id"] for i in plan["items"]]))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "installer", "dry_step.py"), "uninstall-run",
                        str(tmp_path / "sel.json"), str(tmp_path / "plan.json")], capture_output=True, text=True)
    ev = [json.loads(ln) for ln in r.stdout.splitlines()]
    assert r.returncode == 0 and [e["step"] for e in ev] == ["stop", "stop", "apt", "apt", "user", "receipt", "done"]
    assert ev[3] == {"step": "apt", "item": None, "ok": True, "msg": "2 dependencies removed (dry)", "deps": 2}


def test_l_ecran_des_tiers_a_tout_cocher_par_groupe():
    js = open(os.path.join(ROOT, "installer", "ui", "uninstaller.js"), encoding="utf-8").read()
    assert "'Select all' : 'Select none'" in js and "selected</span>" in js and "setGroup(its" in js
    assert "['apt', 'System packages']" in js                              # l'étape apt du moteur a sa ligne
    assert "R.deps_removed" in js


def test_un_paquet_garde_n_est_pas_un_echec(srv, tmp_path, monkeypatch):
    """`kept` (un paquet d'avant golem en a besoin) : ni dans failed (pas de Retry), mais dans kept."""
    lines = [{"step": "apt", "item": "apt:byod", "ok": False, "msg": "kept: needed by old (installed before golem)",
              "kept": True},
             {"step": "apt", "item": "apt:x42-plugins", "ok": True, "msg": "purged"},
             {"step": "apt", "item": None, "ok": True, "msg": "4 dependencies removed", "deps": 4},
             {"step": "done", "item": None, "ok": True, "msg": "everything chosen was removed"}]

    class P:
        def __init__(self, cmd, **kw):
            self.stdout = iter(json.dumps(x) + "\n" for x in lines)

        def wait(self):
            return 0
    monkeypatch.setattr(srv.UN.subprocess, "Popen", P)
    tmp = tmp_path / "copy"
    tmp.mkdir()
    srv.UN.U.update(tmp=str(tmp), root=str(tmp_path / "golem"))
    srv.UN._do_run(["apt:byod", "apt:x42-plugins"], 1)
    R = srv.UN.U["run"]
    assert R["failed"] == [] and R["ok"] is True and R["kept"] == ["apt:byod"] and R["deps_removed"] == 4
    assert R["steps"]["apt"] == {"n": 3, "fail": 0}


# ── Windows (docs/uninstall.md §9.4) : ce qui se vérifie sans Windows ──────────────────────────────────────────
def test_la_copie_emporte_ce_qu_il_faut_a_windows(srv, tmp_path):
    UN = srv.UN
    tmp = UN.self_copy(ROOT, base=str(tmp_path))
    for rel in ("installer/platform_windows.py", "installer/desktop_steps.py", "installer/elevate_win.py",
                "installer/after_exit_win.py", "provision/desktop.py", "provision/uninstall_win.py",
                "bridge/reaper_license.py"):
        assert os.path.isfile(os.path.join(tmp, rel)), rel
    # la copie suffit : platform_windows s'y importe (desktop_steps, elevate_win), le moteur y trouve sa couche Windows
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, 'installer'); import platform_windows, "
                        "elevate_win; import importlib.util as u; s = u.spec_from_file_location('w', "
                        "'provision/uninstall.py'); m = u.module_from_spec(s); s.loader.exec_module(m); m._windows()"],
                       cwd=tmp, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    UN.remove_tmp(tmp)


def test_windows_se_relance_detache_avec_le_python_de_base(srv, tmp_path, monkeypatch):
    base = tmp_path / "t"
    base.mkdir()
    monkeypatch.setattr(srv.UN.tempfile, "tempdir", str(base))
    monkeypatch.setattr(srv.UN, "DETACHED", True)
    monkeypatch.setattr(srv.UN.sys, "_base_executable", "/py/base/python", raising=False)
    monkeypatch.setattr(srv.os, "chdir", lambda d: None)
    monkeypatch.setattr(srv.os, "execv", lambda *a: pytest.fail("no exec on Windows"))
    started = []

    class Popen:
        def __init__(self, argv, **kw):
            started.append((argv, kw))
    monkeypatch.setattr(srv.UN.subprocess, "Popen", Popen)
    with pytest.raises(SystemExit) as e:
        srv.main(["--uninstall", "--root", "/home/u/golem", "--open"])
    assert e.value.code == 0
    ((argv, kw),) = started
    (tmp,) = [str(p) for p in base.iterdir()]
    assert argv[0] == "/py/base/python" and argv[1] == os.path.join(tmp, "installer", "server.py")
    assert "--owned-tmp" in argv and "--open" in argv and kw["cwd"] == tmp
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    assert kw["creationflags"] == flags and kw["stdin"] == subprocess.DEVNULL
    assert os.path.isfile(os.path.join(tmp, "installer", "server.py"))      # la copie reste : c'est elle qui sert
    srv.UN.remove_tmp(tmp)


def test_le_python_de_base_jamais_pythonw(srv, tmp_path, monkeypatch):
    d = tmp_path / "py"
    d.mkdir()
    (d / "python.exe").write_text("")
    monkeypatch.setattr(srv.UN, "DETACHED", True)
    monkeypatch.setattr(srv.UN.sys, "_base_executable", str(d / "pythonw.exe"), raising=False)
    assert srv.UN.base_python() == str(d / "python.exe")
    monkeypatch.setattr(srv.UN, "DETACHED", False)
    assert srv.UN.base_python() == sys.executable


def test_windows_pas_de_mot_de_passe_l_invite_de_windows(srv, tmp_path, monkeypatch):
    root, copy = _real(srv, tmp_path)
    srv.UN.init(srv.Ctx, str(root), str(copy), dry=False, privilege="uac")
    srv.UN.U["plan"]["items"].append({"id": "programs:nam_vst3", "group": "programs", "default": True,
                                      "privilege": "admin"})
    srv.UN.U["plan"]["check_yourself"] = ["Wi-Fi profiles"]
    srv.UN.U["backup"].update(state="ok", result={"dest": str(tmp_path / "bk"), "files": []})
    rv = srv.UN.review()
    assert rv["needs_password"] is False and rv["needs_uac"] is True and rv["check_yourself"] == ["Wi-Fi profiles"]
    assert "programs:nam_vst3" in rv["ids"]
    seen = {}

    class FakeP:
        def __init__(self, cmd, **kw):
            seen["env"] = kw["env"]
            self.stdout = iter([json.dumps({"step": "done", "item": None, "ok": True, "msg": "all"}) + "\n"])

        def wait(self):
            return 0
    monkeypatch.setattr(srv.UN.subprocess, "Popen", FakeP)
    assert srv.UN.start_run() is None                    # pas de « your password first » : Windows demande lui-même
    assert _wait(lambda: srv.UN.U["run"]["state"] == "done")
    assert seen["env"]["GOLEM_UNINSTALL_WAIT_PID"] == str(os.getpid())   # Python ne part qu'après le désinstallateur


def test_le_venv_de_windows(srv, tmp_path, monkeypatch):
    monkeypatch.setattr(srv.UN.os, "name", "nt")
    try:
        assert srv.UN.venv_rel() == os.path.join(".venv", "Scripts", "python.exe")
    finally:
        monkeypatch.undo()
    assert srv.UN.venv_rel() == os.path.join(".venv", "bin", "python")


def test_golem_cmd_uninstall():
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    import platform_windows as PW
    assert PW.UNINSTALL is True
    cmd = PW.launcher_script(r"C:\Users\Jean Paul\golem", r"C:\Py\python.exe")
    lines = cmd.split("\r\n")
    assert lines[2] == 'if /i "%~1"=="uninstall" goto uninstall'
    i = lines.index(":uninstall")
    assert lines[i + 1].startswith("rem") and lines[i + 2] == 'cd /d "%TEMP%"'     # jamais depuis le dossier supprimé
    assert r'"C:\Py\python.exe" "C:\Users\Jean Paul\golem\installer\server.py" --uninstall --root "C:\Users\Jean Paul\golem" --open %2 %3' in lines
    assert r'"C:\Py\python.exe" "C:\Users\Jean Paul\golem\provision\uninstall.py" plan --root "C:\Users\Jean Paul\golem"' in lines
    assert '"C:\\Py\\python.exe" -m provision.desktop start %*' in lines             # le lanceur, inchangé


def test_la_fenetre_du_desinstallateur_a_son_profil_dans_la_copie(srv, tmp_path, monkeypatch):
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    import platform_windows as PW
    monkeypatch.setattr(srv, "P", PW)
    monkeypatch.setattr(PW, "APP_PROFILE", None)
    monkeypatch.setattr(srv.UN, "init", lambda *a, **k: None)
    copy = tmp_path / "golem-uninstaller-x"
    copy.mkdir()

    class A:
        root, owned_tmp, open, port = str(tmp_path / "golem"), str(copy), False, 0
    assert srv.start_uninstall(A, dry=True) is True
    assert PW.APP_PROFILE == os.path.join(str(copy), "browser")
    srv.S.update(mode="install")


def test_le_serveur_detache_ecrit_en_utf8_et_survit_a_cp1252(monkeypatch):
    """VM Windows, 2026-10-16 : le processus détaché écrivait dans DEVNULL en cp1252 ; « → » le tuait au premier print,
    il effaçait sa copie et « Uninstall golem » ne s'ouvrait jamais."""
    import io
    import sys
    from installer import uninstaller as UN
    seen = {}
    monkeypatch.setattr(UN, "DETACHED", True)
    monkeypatch.setattr(UN.subprocess, "Popen", lambda argv, **kw: seen.update(kw))
    assert UN.relaunch_detached(["py", "server.py"], "/tmp/x") is True
    assert seen["env"]["PYTHONUTF8"] == "1"
    # et une sortie cp1252 ne lève plus : le serveur la rend tolérante au démarrage
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    out.reconfigure(errors="replace")
    print("golem uninstaller \u2192 open this link", file=out)
    monkeypatch.setattr(sys, "stdout", out)


# ── premier cycle en VM Windows (2026-10-16) : la copie restait dans %TEMP% ────────────────────────────
def test_windows_la_copie_qui_resiste_est_confiee_au_veilleur(srv, tmp_path, monkeypatch):
    UN = srv.UN
    tmp = UN.self_copy(ROOT, base=str(tmp_path))
    os.makedirs(os.path.join(tmp, "browser", "Default"))
    UN.U["tmp"] = tmp
    monkeypatch.setattr(UN, "DETACHED", True)
    monkeypatch.setattr(UN, "remove_tmp", lambda t: False)            # le profil du navigateur encore verrouillé
    handed = []
    monkeypatch.setattr(UN, "hand_over", lambda t: handed.append((t, os.getcwd())))
    here = os.getcwd()
    try:
        os.chdir(tmp)                                                 # le serveur détaché a sa copie pour cwd
        UN.cleanup()
        assert handed == [(tmp, str(tmp_path))]                       # sorti de la copie AVANT, puis confiée
    finally:
        os.chdir(here)
        monkeypatch.undo()
        UN.remove_tmp(tmp)


def test_windows_la_copie_partie_rien_a_confier_et_linux_inchange(srv, tmp_path, monkeypatch):
    UN = srv.UN
    handed = []
    monkeypatch.setattr(UN, "hand_over", lambda t: handed.append(t))
    tmp = UN.self_copy(ROOT, base=str(tmp_path))
    UN.U["tmp"] = tmp
    monkeypatch.setattr(UN, "DETACHED", True)
    UN.cleanup()
    assert not os.path.exists(tmp) and handed == []
    tmp = UN.self_copy(ROOT, base=str(tmp_path))
    UN.U["tmp"] = tmp
    monkeypatch.setattr(UN, "DETACHED", False)
    monkeypatch.setattr(UN, "remove_tmp", lambda t: False)
    UN.cleanup()
    assert handed == []                                               # Linux : jamais de veilleur
    monkeypatch.undo()
    UN.remove_tmp(tmp)


def test_le_journal_du_veilleur_va_a_l_ecran_done(srv, tmp_path, monkeypatch):
    root, copy = _real(srv, tmp_path)
    srv.UN.U["backup"].update(state="ok", result={"dest": str(tmp_path / "bk"), "files": []})
    (tmp_path / "bk").mkdir()
    srv.S.update(sudo_ok=True, sudo_pw="x")

    class FakeP:
        def __init__(self, cmd, **kw):
            self.stdout = iter(json.dumps(x) + "\n" for x in (
                {"step": "user", "item": "toolchain:python", "ok": True, "msg": "scheduled", "after_log": "C:\\T\\a.log"},
                {"step": "done", "item": None, "ok": True, "msg": "all"}))

        def wait(self):
            return 0
    monkeypatch.setattr(srv.UN.subprocess, "Popen", FakeP)
    assert srv.UN.start_run() is None
    assert _wait(lambda: srv.UN.U["run"]["state"] == "done")
    assert srv.UN.public()["run"]["after_log"] == "C:\\T\\a.log"
    js = open(os.path.join(ROOT, "installer", "ui", "uninstaller.js"), encoding="utf-8").read()
    assert "R.after_log" in js


def test_la_copie_garde_son_marqueur_tant_qu_un_fichier_resiste(tmp_path, monkeypatch):
    """VM Windows, 2026-10-16 : effacée d'un bloc, une copie dont le navigateur tenait le profil perdait son marqueur au
    premier essai — et plus rien ne reconnaissait le reste. Le marqueur part EN DERNIER."""
    import os
    from installer import uninstaller as UN
    t = UN.self_copy(UN.ROOT_DIR if hasattr(UN, "ROOT_DIR") else os.path.dirname(os.path.dirname(UN.__file__)),
                     base=str(tmp_path))
    locked = os.path.join(t, "browser", "Cookies")
    os.makedirs(os.path.dirname(locked))
    open(locked, "w").close()
    real = UN.shutil.rmtree

    def stuck(p, ignore_errors=False):                     # le profil du navigateur résiste
        if os.path.basename(p) == "browser":
            return
        real(p, ignore_errors=ignore_errors)
    monkeypatch.setattr(UN.shutil, "rmtree", stuck)
    monkeypatch.setattr(UN.time, "sleep", lambda s: None)
    assert UN.remove_tmp(t) is False
    assert os.path.isfile(os.path.join(t, UN.MARKER))     # le reste est encore reconnaissable
    monkeypatch.setattr(UN.shutil, "rmtree", real)
    assert UN.remove_tmp(t) is True and not os.path.exists(t)


def test_sous_windows_la_copie_n_a_pas_l_acl_proprietaire_seul_de_mkdtemp(tmp_path, monkeypatch):
    """VM Windows, 2026-10-16 : mkdtemp (Python 3.12) pose une ACL sans héritage ; Edge, lancé alors que la fenêtre de
    golem tournait, ne pouvait pas écrire son profil dans la copie — aucune fenêtre. Sous Windows : un mkdir ordinaire."""
    import os
    from installer import uninstaller as UN
    monkeypatch.setattr(UN.os, "name", "nt")
    monkeypatch.setattr(UN.tempfile, "mkdtemp", lambda **k: pytest.fail("mkdtemp used on Windows"))
    made = []
    real = os.mkdir
    monkeypatch.setattr(UN.os, "mkdir", lambda p, *a: (made.append((p, a)), real(p))[1])
    t = UN.self_copy(os.path.dirname(os.path.dirname(UN.__file__)), base=str(tmp_path))
    assert made and made[0][1] == () and os.path.basename(t).startswith(UN.TMP_PREFIX)
    UN.remove_tmp(t)


def test_le_veilleur_ne_vide_jamais_la_copie_d_un_desinstallateur_vivant(tmp_path):
    """VM Windows, 2026-10-16 : le veilleur d'un essai raté a vidé la copie d'un désinstallateur en train de tourner.
    Le marqueur porte le pid du serveur ; le veilleur saute toute copie dont le serveur vit."""
    import os
    from installer import after_exit_win as A
    from installer import uninstaller as UN
    t = UN.self_copy(os.path.dirname(os.path.dirname(UN.__file__)), base=str(tmp_path))
    UN.init(None, str(tmp_path), t, True)
    assert "pid=%d" % os.getpid() in open(os.path.join(t, UN.MARKER), encoding="utf-8").read()
    text = A.script(4242, r"C:\T\log.txt", copy_dir=r"C:\T\golem-uninstaller-x")
    assert text.index("$wait = 4242") < text.index("Get-Process -Id $_")
    assert "left as is" in text
    UN.U["tmp"] = None
    UN.remove_tmp(t)


def test_la_fenetre_vit_tant_qu_un_navigateur_porte_son_profil(monkeypatch):
    """VM Windows, 2026-10-16 : l'Edge lancé passait la main à un Edge déjà ouvert (la fenêtre de golem) et se terminait ;
    le serveur croyait sa fenêtre fermée et s'arrêtait. On cherche le profil sur les lignes de commande."""
    from installer import platform_windows as PW
    monkeypatch.setattr(PW, "_OPEN_PROFILE", r"C:\Users\Jean Paul\AppData\Local\Temp\golem-uninstaller-ab\browser")
    rows = {"out": 'msedge.exe --app=x --user-data-dir="C:\\Users\\Jean Paul\\AppData\\Local\\Temp\\golem-uninstaller-ab\\browser"\n'}
    monkeypatch.setattr(PW.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": rows["out"]})())
    assert PW.app_alive() is True
    rows["out"] = "msedge.exe --user-data-dir=C:\\Users\\Jean Paul\\AppData\\Local\\GoleM\\browser\n"   # la fenêtre de golem
    assert PW.app_alive() is False
