# SPDX-License-Identifier: GPL-3.0-or-later
"""L'EXÉCUTION de la désinstallation (docs/uninstall.md §5) sur un faux système de fichiers (mode --root-fs : les
commandes système sont simulées, seul le script root s'exécute — avec `sh`, sans sudo, sur le faux arbre)."""
import json
import os

import pytest

from provision import uninstall as U
from tests.uninstall_fixtures import HOME, INSTALL, machine, receipt_data


@pytest.fixture
def fs(tmp_path, monkeypatch):
    f = machine(tmp_path / "fs")
    # le reçu du faux arbre (conftest pointe GOLEM_RECEIPT vers un fichier temporaire vide)
    monkeypatch.setenv("GOLEM_RECEIPT", f.p(HOME + "/.local/share/golem/install-receipt.json"))
    return f


@pytest.fixture
def calls(monkeypatch):
    seen = []
    real = U._default_runner

    def runner(ctx, argv, env=None, timeout=900):
        seen.append(list(argv))
        return real(ctx, argv, env=env, timeout=timeout)
    monkeypatch.setattr(U, "run_command", runner)
    return seen


class Rec(U.Reporter):
    def __init__(self):
        super().__init__(as_json=False)
        self.events, self.extras = [], []

    def __call__(self, step, item, ok, msg, **extra):
        self.events.append((step, item, ok, msg))
        self.extras.append(extra)
        if item:
            self.results[item] = bool(ok)
            if extra.get("kept"):
                self.kept.add(item)


def _defaults(ctx):
    return [i["id"] for i in U.build_plan(ctx)["items"] if i["default"]]


def test_tout_par_defaut_dans_l_ordre(fs, calls):
    ctx = fs.ctx()
    rec = Rec()
    assert U.run(ctx, _defaults(ctx), rec) is True
    steps = [e[0] for e in rec.events]
    order = ["stop", "root", "reaper", "user", "folder", "receipt", "done"]
    assert [s for i, s in enumerate(steps) if i == 0 or steps[i - 1] != s] == order     # chaque étape une fois, dans l'ordre
    # le moteur est arrêté AVANT tout : systemctl --user stop, puis stop.sh
    assert calls[0] == ["systemctl", "--user", "stop", "golem-server.service"]
    assert any(c[0].endswith("/provision/stop.sh") for c in calls[:3])
    # UNE passe root (sh, en mode --root-fs)
    assert sum(1 for c in calls if c[0] == "sh") == 1
    for p in ("/etc/sudoers.d/golem-net", "/usr/local/sbin/golem-net", "/etc/systemd/system/golem-net.service",
              "/etc/security/limits.d/95-golem-audio.conf", "/etc/sysctl.d/90-golem-port80.conf",
              HOME + "/.local/bin/golem", HOME + "/.config/REAPER/Scripts/golem", HOME + "/.config/REAPER/FXChains",
              HOME + "/.config/systemd/user/golem-server.service", HOME + "/.cache/golem-build",
              HOME + "/.vst3/GoleM Freeze.vst3", INSTALL):
        assert not fs.exists(p), p
    # ce qui n'est pas à golem, ou décoché, reste
    for p in ("/etc/sudoers.d/someone-else", HOME + "/.config/REAPER/OSC/mine.ReaperOSC", "/elsewhere/mine.ReaperOSC",
              HOME + "/.lv2/neural_amp_modeler.lv2", HOME + "/.config/REAPER/reaper-license.rk", HOME + "/.cargo",
              HOME + "/opt/REAPER"):
        assert fs.exists(p), p
    assert "audio:x:29:u,pulse" in fs.read("/etc/group")                 # décoché sans reçu
    # reaper.ini : seule la surface OSC de golem part, copie gardée
    ini = fs.read(HOME + "/.config/REAPER/reaper.ini")
    assert "GoleM" not in ini and "csurf_cnt=2" in ini and "automute=0" in ini
    assert fs.exists(HOME + "/.config/REAPER/reaper.ini.golem-uninstall")
    # les commandes système n'ont jamais été lancées pour de vrai
    assert all(c[0] in ("sh", "systemctl", "pgrep") or c[0].endswith(".sh") for c in calls)


def test_avec_recu_restaure_et_supprime_le_recu(fs, calls):
    fs.receipt(receipt_data())
    fs.file(HOME + "/.config/REAPER/Scripts/__startup.lua.golem-orig", "mine")
    ctx = fs.ctx()
    rec = Rec()
    ids = _defaults(ctx)
    assert "system:audio-group" in ids and "apt:guitarix-lv2" in ids
    assert U.run(ctx, ids, rec) is True, rec.events
    # l'original remis à sa place
    assert not os.path.islink(fs.p(HOME + "/.config/REAPER/Scripts/__startup.lua"))
    assert fs.read(HOME + "/.config/REAPER/Scripts/__startup.lua") == "mine"
    # reaper.ini : clés d'avant, surface de golem retirée
    ini = fs.read(HOME + "/.config/REAPER/reaper.ini")
    sec = ini.split("[reaper]\n")[1].split("[other]")[0]
    assert "automute=1" in sec and "midiins" not in sec and "csurf_cnt=2" in sec
    # le groupe audio : retiré par gpasswd (simulé ici) ; la passe root l'a bien demandé
    assert any(e[1] == "system:audio-group" and e[2] for e in rec.events)
    # golem parti, tout réussi : le reçu disparaît, et son dossier avec
    assert not fs.exists(HOME + "/.local/share/golem")


def test_un_echec_n_arrete_pas_les_autres_et_le_recu_garde_le_reste(fs, calls):
    if os.geteuid() == 0:
        pytest.skip("root ignore les permissions")
    fs.receipt(receipt_data())
    ctx = fs.ctx()
    lv2 = fs.p(HOME + "/.lv2")
    os.chmod(lv2, 0o500)                                   # le plugin NAM ne pourra pas partir
    try:
        rec = Rec()
        ok = U.run(ctx, ["plugins:nam", "plugins:freeze", "golem:command", "system:/etc/sudoers.d/golem-net"], rec)
    finally:
        os.chmod(lv2, 0o700)
    assert ok is False
    res = {e[1]: e[2] for e in rec.events if e[1]}
    assert res == {"plugins:nam": False, "plugins:freeze": True, "golem:command": True,
                   "system:/etc/sudoers.d/golem-net": True}
    r = json.loads(fs.read(HOME + "/.local/share/golem/install-receipt.json"))
    rids = {i["id"] for i in r["items"]}
    assert "dir:~/.lv2/neural_amp_modeler.lv2" in rids                    # reste à faire
    assert "file:/etc/sudoers.d/golem-net" not in rids                   # fait
    assert "file:/etc/gone.conf" not in rids                             # absent = fait
    assert r["uninstall"]["failed"] == ["plugins:nam"]
    assert "not-installed-anymore" not in r["apt"]["added"]
    assert r["prior"]["audio_group"] is False                            # pas traité : gardé
    assert rec.events[-1][0] == "done" and rec.events[-1][2] is False


def test_un_lien_n_est_jamais_suivi(fs, calls):
    fs.file("/precious/data/keep.txt", "precious")
    os.makedirs(fs.p(HOME + "/.clap"), exist_ok=True)
    fs.link(HOME + "/.clap/GoleM Freeze.clap", "/precious/data")
    ctx = fs.ctx()
    rec = Rec()
    assert U.run(ctx, ["plugins:freeze"], rec)
    assert not fs.exists(HOME + "/.clap/GoleM Freeze.clap")
    assert fs.read("/precious/data/keep.txt") == "precious"


def test_un_parent_lien_est_refuse(fs, calls):
    # ~/.vst3 est un lien vers ailleurs : supprimer « dedans » toucherait la cible
    fs.file("/shared/vst3/GoleM Freeze.vst3/x", "shared")
    os.rename(fs.p(HOME + "/.vst3"), fs.p(HOME + "/.vst3-old"))
    fs.link(HOME + "/.vst3", "/shared/vst3")
    ctx = fs.ctx()
    rec = Rec()
    assert U.run(ctx, ["plugins:freeze"], rec) is False
    assert "symbolic link" in [e for e in rec.events if e[1] == "plugins:freeze"][0][3]
    assert fs.read("/shared/vst3/GoleM Freeze.vst3/x") == "shared"


def test_chemins_dangereux_refuses(fs):
    ctx = fs.ctx()
    for p in ("/", HOME, "/etc", "/usr", "/home", HOME + "/.config", HOME + "/.lv2", "/etc/sudoers.d",
              HOME + "/.bashrc", "/etc/passwd", "/tmp"):
        with pytest.raises(U.UninstallError):
            U.safe_remove(ctx, p, INSTALL)
    assert os.path.exists(fs.p("/etc/group"))


def test_dossier_d_install_refuse_si_on_tourne_dedans(fs, calls, monkeypatch):
    monkeypatch.setattr(U, "_self_paths", lambda: [fs.p(INSTALL + "/provision/uninstall.py")])
    rec = Rec()
    assert U.run(fs.ctx(), ["golem:install-folder", "golem:command"], rec) is False
    ev = [e for e in rec.events if e[1] == "golem:install-folder"][0]
    assert ev[0] == "folder" and not ev[2] and "inside the install folder" in ev[3]
    assert fs.exists(INSTALL) and not fs.exists(HOME + "/.local/bin/golem")


def test_id_inconnu_refuse_avant_tout(fs, calls):
    with pytest.raises(U.UninstallError):
        U.run(fs.ctx(), ["golem:command", "apt:pipewire"], Rec())
    assert calls == [] and fs.exists(HOME + "/.local/bin/golem")


@pytest.mark.skipif(not hasattr(U.os, "geteuid"), reason="the root pass is POSIX (sudo)")
def test_passe_root_avec_askpass_ou_sans(monkeypatch):
    seen = []

    def fake(ctx, argv, env=None, timeout=900):
        seen.append(argv)
        return 0, "@@ITEM system:audio-group 0 done\n"
    monkeypatch.setattr(U, "run_command", fake)
    monkeypatch.setattr(U.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(U.shutil, "which", lambda n: "/usr/bin/" + n)
    ctx = U.Ctx(fsroot="", home="/home/u", user="u")
    it = {"id": "system:audio-group", "group": "system", "action": "revert", "privilege": "root"}
    rec = Rec()
    monkeypatch.setenv("SUDO_ASKPASS", "/tmp/x/askpass")
    U._run_root(ctx, [it], None, set(), rec)
    assert seen[-1][:3] == ["sudo", "-A", "sh"] and rec.results == {"system:audio-group": True}
    monkeypatch.delenv("SUDO_ASKPASS")
    U._run_root(ctx, [it], None, set(), rec)
    assert seen[-1][:2] == ["sudo", "sh"]
    monkeypatch.setattr(U.shutil, "which", lambda n: None)
    rec2 = Rec()
    U._run_root(ctx, [it], None, set(), rec2)
    assert rec2.results == {"system:audio-group": False} and "sudo is not available" in rec2.events[0][3]


def test_script_root_sans_sortie_tous_en_echec(fs, monkeypatch):
    monkeypatch.setattr(U, "run_command", lambda ctx, argv, env=None, timeout=900: (1, "sudo: a password is required"))
    rec = Rec()
    U.run(fs.ctx(), ["system:/etc/sudoers.d/golem-net", "golem:command"], rec)
    ev = {e[1]: e for e in rec.events if e[1]}
    assert ev["system:/etc/sudoers.d/golem-net"][2] is False and "password is required" in ev["system:/etc/sudoers.d/golem-net"][3]
    assert ev["golem:command"][2] is True                                # l'échec root n'arrête pas le reste


def test_progression_json_en_ligne_de_commande(fs, calls, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HOME", HOME)
    monkeypatch.setenv("USER", "u")
    log = tmp_path / "u.log"
    sel = tmp_path / "sel.json"
    sel.write_text(json.dumps({"items": [{"id": "golem:command", "selected": True},
                                         {"id": "golem:install-folder", "selected": False}]}))
    rc = U.main(["--root-fs", fs.base, "run", "--select", str(sel), "--yes", "--json", "--log", str(log)])
    assert rc == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert all(set(x) == {"step", "item", "ok", "msg"} for x in lines)
    assert any(x["item"] == "golem:command" and x["ok"] for x in lines)
    assert lines[-1]["step"] == "done" and lines[-1]["ok"] is True
    assert fs.exists(INSTALL)
    assert "golem:command OK" in log.read_text()
    # sans --yes et sans terminal : refus
    assert U.main(["--root-fs", fs.base, "run", "--items", "golem:icon:golem.png", "--json"]) == 2


def test_machine_dediee_remise_comme_avant(fs, calls):
    d = receipt_data()
    d["prior"].update(ufw={"active": False, "rules": ["OpenSSH"]}, auto_upgrades='APT::Periodic::Update-Package-Lists "1";\n',
                      governor="powersave")
    fs.receipt(d)
    fs.file("/etc/ufw/ufw.conf", "ENABLED=yes\n")
    fs.file("/etc/apt/apt.conf.d/20auto-upgrades", 'APT::Periodic::Update-Package-Lists "0";\n')
    ctx = fs.ctx()
    plan = {i["id"]: i for i in U.build_plan(ctx)["items"]}
    assert plan["dedicated:ufw"]["default"] and "turned off" in plan["dedicated:ufw"]["reason"]
    script, refused = U.root_script(ctx, [plan["dedicated:ufw"]], INSTALL, set())
    assert not refused and "ufw delete allow 8770/tcp" in script and "OpenSSH" not in script
    assert "ufw --force disable" in script
    rec = Rec()
    assert U.run(ctx, ["dedicated:ufw", "dedicated:auto-upgrades", "dedicated:governor"], rec), rec.events
    assert fs.read("/etc/apt/apt.conf.d/20auto-upgrades") == 'APT::Periodic::Update-Package-Lists "1";\n'
    r = json.loads(fs.read(HOME + "/.local/share/golem/install-receipt.json"))     # golem toujours là : réécrit
    assert "ufw" not in r["prior"] and "auto_upgrades" not in r["prior"] and "governor" not in r["prior"]
    assert r["prior"]["audio_group"] is False


def test_minuteries_apt_et_avahi(fs):
    d = receipt_data()
    d["prior"].update(apt_timers={"apt-daily.timer": "enabled", "apt-daily-upgrade.timer": "masked"},
                      avahi_enabled="disabled")
    fs.receipt(d)
    ctx = fs.ctx()
    plan = {i["id"]: i for i in U.build_plan(ctx)["items"]}
    script, refused = U.root_script(ctx, [plan["dedicated:apt-timers"], plan["dedicated:avahi"]], INSTALL, set())
    assert not refused
    assert "systemctl enable --now apt-daily.timer" in script and "systemctl mask apt-daily-upgrade.timer" in script
    assert "systemctl disable --now avahi-daemon.service" in script
    d["prior"]["avahi_enabled"] = "enabled"
    fs.receipt(d)
    assert "dedicated:avahi" not in {i["id"] for i in U.build_plan(ctx)["items"]}


# ── apt : un FAUX apt (simulation, purge, dpkg-query), branché à la place du runner ───────────────────────────
class FakeApt:
    """Un apt minimal : `deps` = qui dépend de qui ; `auto` = installés comme dépendances. purge X retire X et tout
    ce qui dépend de X ; autoremove retire les automatiques que plus rien d'installé (manuel) ne retient."""

    def __init__(self, installed, deps, auto):
        self.installed, self.deps, self.auto = set(installed), deps, set(auto)
        self.calls = []

    def _closure_purge(self, pkgs):
        gone, todo = set(), [p for p in pkgs if p in self.installed]
        while todo:
            p = todo.pop()
            if p in gone:
                continue
            gone.add(p)
            todo += [q for q in self.installed if p in self.deps.get(q, ()) and q not in gone]
        return gone

    def _autoremovable(self):
        keep, todo = set(), [p for p in self.installed if p not in self.auto]
        while todo:
            p = todo.pop()
            if p in keep:
                continue
            keep.add(p)
            todo += [d for d in self.deps.get(p, ()) if d in self.installed]
        return self.installed - keep

    def __call__(self, ctx, argv, env=None, timeout=900):
        self.calls.append(list(argv))
        a = list(argv)
        if a[:2] == ["apt-get", "-s"]:
            verb, pkgs = a[2], a[3:]
            gone = self._autoremovable() if verb == "autoremove" else self._closure_purge(pkgs)
            return 0, "NOTE: This is only a simulation!\n" + "".join("Purg %s [1.0]\n" % p for p in sorted(gone))
        if "apt-get" in a and "purge" in a and "-s" not in a:
            assert a[:2] == ["env", "DEBIAN_FRONTEND=noninteractive"]       # --root-fs : pas de sudo, la ligne porte le frontend
            pkgs = a[a.index("-y") + 1:]
            self.installed -= self._closure_purge(pkgs)
            return 0, "purged"
        if a[0] == "dpkg-query":
            return 0, "".join("%s installed\n" % p for p in a[3:] if p in self.installed)
        return 0, "simulated: " + " ".join(a)


def _apt_fs(fs, apt):
    fs.receipt(receipt_data(apt=apt))
    names = set(apt["added"]) | set(apt.get("debs") or []) | {"pipewire", "git", "old-tool", "libshared"}
    fs.file("/var/lib/dpkg/status", "".join("Package: %s\nStatus: install ok installed\n\n" % p for p in sorted(names)))


def test_apt_explicites_puis_leurs_dependances(fs, monkeypatch):
    added = ["x42-plugins", "libx42-a", "libx42-b", "ffmpeg", "libav", "guitarix-lv2", "libgx"]
    _apt_fs(fs, {"added": added, "debs": [], "requested": ["x42-plugins", "ffmpeg", "guitarix-lv2"]})
    fs.file("/var/lib/apt/extended_states", "".join("Package: %s\nAuto-Installed: 1\n\n" % p
                                                     for p in ("libx42-a", "libx42-b", "libav", "libgx", "libshared",
                                                               "stale-auto")))
    apt = FakeApt(installed=set(added) | {"pipewire", "old-tool", "libshared", "stale-auto"},
                  deps={"x42-plugins": ["libx42-a", "libshared"], "libx42-a": ["libx42-b"], "ffmpeg": ["libav"],
                        "guitarix-lv2": ["libgx"], "old-tool": ["libshared"]},
                  auto={"libx42-a", "libx42-b", "libav", "libgx", "libshared", "stale-auto"})
    monkeypatch.setattr(U, "run_command", apt)
    ctx = fs.ctx()
    rec = Rec()
    # ffmpeg (outil général) décoché : lui et sa dépendance restent
    assert U.run(ctx, ["apt:x42-plugins", "apt:guitarix-lv2"], rec) is True, rec.events
    assert {"x42-plugins", "guitarix-lv2", "libx42-a", "libx42-b", "libgx"}.isdisjoint(apt.installed)
    assert {"ffmpeg", "libav", "pipewire", "old-tool", "libshared"} <= apt.installed
    # jamais un autoremove nu : un automatique d'avant golem (stale-auto) reste, libshared (d'avant) aussi
    assert "stale-auto" in apt.installed
    assert not any(c[:1] == ["env"] and "autoremove" in c for c in apt.calls)
    # UNE purge des explicites, simulée avant ; puis les dépendances, simulées avant
    purges = [c for c in apt.calls if c[:1] == ["env"]]
    assert len(purges) == 2
    assert sorted(purges[0][purges[0].index("-y") + 1:]) == ["guitarix-lv2", "x42-plugins"]
    assert sorted(purges[1][purges[1].index("-y") + 1:]) == ["libgx", "libx42-a", "libx42-b"]
    for real in purges:                                          # chaque purge réelle a sa simulation juste avant
        pk = sorted(real[real.index("-y") + 1:])
        before = apt.calls[:apt.calls.index(real)]
        assert any(c[:3] == ["apt-get", "-s", "purge"] and sorted(c[3:]) == pk for c in before)
    summary = [(e, x) for e, x in zip(rec.events, rec.extras) if e[0] == "apt" and e[1] is None]
    assert summary[-1][0][3] == "3 dependencies removed" and summary[-1][1] == {"deps": 3}
    # le reçu (golem toujours là) oublie les paquets partis, garde ffmpeg et sa dépendance
    r = json.loads(fs.read(HOME + "/.local/share/golem/install-receipt.json"))
    assert sorted(r["apt"]["added"]) == ["ffmpeg", "libav"] and r["apt"]["requested"] == ["ffmpeg"]


def test_apt_une_dependance_d_un_paquet_d_avant_golem_est_gardee(fs, monkeypatch):
    # byod est à golem, mais old-player (là AVANT golem) dépend de byod : le purger emporterait old-player
    added = ["byod", "libbyod", "x42-plugins"]
    _apt_fs(fs, {"added": added, "debs": [], "requested": ["byod", "x42-plugins"]})
    fs.file("/var/lib/apt/extended_states", "Package: libbyod\nAuto-Installed: 1\n\n")
    apt = FakeApt(installed=set(added) | {"old-player"},
                  deps={"byod": ["libbyod"], "old-player": ["byod"]}, auto={"libbyod"})
    monkeypatch.setattr(U, "run_command", apt)
    rec = Rec()
    assert U.run(fs.ctx(), ["apt:byod", "apt:x42-plugins"], rec) is True, rec.events
    assert {"byod", "libbyod", "old-player"} <= apt.installed and "x42-plugins" not in apt.installed
    ev = [e for e in rec.events if e[1] == "apt:byod"][0]
    assert ev[2] is False and ev[3] == "kept: needed by old-player (installed before golem)"
    assert rec.kept == {"apt:byod"}
    # aucune purge réelle n'a nommé byod
    assert not any(c[:1] == ["env"] and "byod" in c for c in apt.calls)
    assert rec.events[-1][0] == "done" and "1 package(s) kept" in rec.events[-1][3]
    r = json.loads(fs.read(HOME + "/.local/share/golem/install-receipt.json"))
    assert "byod" in r["apt"]["added"] and "libbyod" in r["apt"]["added"]


def test_apt_une_dependance_qui_emporterait_un_paquet_d_avant_est_gardee(fs, monkeypatch):
    added = ["x42-plugins", "libx42"]
    _apt_fs(fs, {"added": added, "debs": [], "requested": ["x42-plugins"]})
    fs.file("/var/lib/apt/extended_states", "Package: libx42\nAuto-Installed: 1\n\n")
    # old-auto (d'avant golem, automatique) dépend de libx42 ; plus rien de manuel ne retient ni l'un ni l'autre
    apt = FakeApt(installed=set(added) | {"old-auto"}, deps={"x42-plugins": ["libx42"], "old-auto": ["libx42"]},
                  auto={"libx42", "old-auto"})
    monkeypatch.setattr(U, "run_command", apt)
    rec = Rec()
    assert U.run(fs.ctx(), ["apt:x42-plugins"], rec) is True
    assert "x42-plugins" not in apt.installed and {"libx42", "old-auto"} <= apt.installed
    assert any(e[0] == "apt" and e[1] is None and e[3] == "dependency libx42 kept: needed by old-auto (installed before golem)"
               for e in rec.events)
    assert [e[3] for e in rec.events if e[0] == "apt" and e[1] is None][-1] == "0 dependencies removed"


def test_apt_json_porte_kept_et_deps(fs, monkeypatch, capsys):
    added = ["byod", "x42-plugins", "libx42"]
    _apt_fs(fs, {"added": added, "debs": [], "requested": ["byod", "x42-plugins"]})
    fs.file("/var/lib/apt/extended_states", "Package: libx42\nAuto-Installed: 1\n\n")
    apt = FakeApt(installed=set(added) | {"old-player"}, deps={"old-player": ["byod"], "x42-plugins": ["libx42"]},
                  auto={"libx42"})
    monkeypatch.setattr(U, "run_command", apt)
    monkeypatch.setenv("HOME", HOME)
    monkeypatch.setenv("USER", "u")
    assert U.main(["--root-fs", fs.base, "run", "--items", "apt:byod", "apt:x42-plugins", "--yes", "--json"]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [x for x in lines if x["item"] == "apt:byod"][0]["kept"] is True
    assert [x for x in lines if x.get("deps") is not None][0]["deps"] == 1


def test_les_dossiers_conteneurs_vides_partent_les_pleins_restent(fs, calls):
    """Premier cycle en VM (2026-10-15) : ~/.lv2, ~/.vst3, ~/.clap, ~/opt restaient, vides. Un conteneur VIDE part ;
    un conteneur qui garde quelque chose (un plugin décoché, REAPER gardé) n'est jamais touché."""
    ctx = fs.ctx()
    os.makedirs(fs.p(HOME + "/.clap"), exist_ok=True)                 # vide une fois Freeze retiré
    for f in os.listdir(fs.p(HOME + "/.clap")):
        if "Freeze" not in f:
            os.remove(os.path.join(fs.p(HOME + "/.clap"), f))
    assert U.run(ctx, _defaults(ctx), Rec()) is True
    assert not fs.exists(HOME + "/.clap")
    assert fs.exists(HOME + "/.lv2/neural_amp_modeler.lv2")         # décoché : ~/.lv2 garde son contenu
    assert fs.exists(HOME + "/opt/REAPER")


# ── 3e cycle en VM (2026-10-16) ──────────────────────────────────────────────────────────────────────────────
def test_sudoers_illisible_retire_par_la_passe_root(fs, monkeypatch):
    """/etc/sudoers.d est fermé à l'utilisateur : le plan liste les règles « présence inconnue », la passe root les
    retire (`rm -f`, idempotent) — celle qui n'y est pas est dite « was not there », sans échec."""
    if os.geteuid() == 0:
        pytest.skip("root lit tout")
    fs.receipt(receipt_data())
    real = U._default_runner

    def runner(ctx, argv, env=None, timeout=900):
        if argv[0] == "sh":                                  # la passe root : root, lui, voit dans le dossier
            os.chmod(fs.p("/etc/sudoers.d"), 0o755)
        return real(ctx, argv, env=env, timeout=timeout)
    monkeypatch.setattr(U, "run_command", runner)
    os.chmod(fs.p("/etc/sudoers.d"), 0)
    try:
        ctx = fs.ctx()
        rec = Rec()
        ids = ["system:/etc/sudoers.d/golem-net", "system:/etc/sudoers.d/golem-perf"]
        assert U.run(ctx, ids, rec) is True, rec.events
    finally:
        os.chmod(fs.p("/etc/sudoers.d"), 0o755)
    assert not fs.exists("/etc/sudoers.d/golem-net") and fs.exists("/etc/sudoers.d/someone-else")
    msgs = {e[1]: e[3] for e in rec.events if e[0] == "root"}
    assert msgs["system:/etc/sudoers.d/golem-net"] == "removed"
    assert msgs["system:/etc/sudoers.d/golem-perf"] == "was not there"


def test_dossier_surveille_vide_retire_plein_garde(fs, calls):
    os.makedirs(fs.p(HOME + "/golem-inbox/.refused"))
    ctx = fs.ctx()
    assert "golem:inbox" in _defaults(ctx)
    assert U.run(ctx, ["golem:inbox"], Rec()) is True
    assert not fs.exists(HOME + "/golem-inbox")
    # déplacé par config/inbox.json : seulement s'il est VIDE, même choisi à la main
    fs.file(INSTALL + "/config/inbox.json", json.dumps({"dir": HOME + "/Inbox"}))
    fs.file(HOME + "/Inbox/mine.golem")
    assert "golem:inbox" not in _defaults(ctx)
    rec = Rec()
    assert U.run(ctx, ["golem:inbox"], rec) is False
    assert fs.exists(HOME + "/Inbox/mine.golem")
    assert any("holds files" in e[3] for e in rec.events if e[1] == "golem:inbox")
    os.remove(fs.p(HOME + "/Inbox/mine.golem"))
    assert U.run(ctx, ["golem:inbox"], Rec()) is True and not fs.exists(HOME + "/Inbox")


def _reaper_receipt(fs):
    from tests.test_uninstall_plan import _reaper_desktop
    fs.receipt(receipt_data())
    _reaper_desktop(fs)


def test_reaper_retire_avec_son_integration_et_les_caches(fs, calls):
    _reaper_receipt(fs)
    ctx = fs.ctx()
    ids = _defaults(ctx) + ["reaper:app"]
    rec = Rec()
    assert U.run(ctx, ids, rec) is True, rec.events
    script = fs.p(HOME + "/opt/REAPER/uninstall-reaper.sh")
    assert ["/bin/sh", script, "--remove-user-desktop", "--quiet"] in calls     # le désinstalleur de REAPER d'abord
    sh = HOME + "/.local/share"
    for p in (HOME + "/opt", sh + "/applications/cockos-reaper.desktop", sh + "/applications/mimeinfo.cache",
              sh + "/applications/defaults.list", HOME + "/.gnome", HOME + "/.config/menus", sh + "/mime",
              sh + "/icons/hicolor"):
        assert not fs.exists(p), p
    assert any("desktop databases" in e[3] for e in rec.events)


def test_reaper_garde_son_integration_les_caches_sont_mis_a_jour(fs, calls):
    _reaper_receipt(fs)
    ctx = fs.ctx()
    assert U.run(ctx, _defaults(ctx), Rec()) is True                 # REAPER gardé (décoché)
    sh = HOME + "/.local/share"
    for p in (sh + "/applications/cockos-reaper.desktop", sh + "/applications/mimeinfo.cache",
              sh + "/applications/defaults.list", HOME + "/.gnome/apps/cockos-reaper.desktop", sh + "/mime/mime.cache",
              sh + "/icons/hicolor/icon-theme.cache", HOME + "/.config/menus/applications-merged/xdg-desktop-menu-dummy.menu"):
        assert fs.exists(p), p
    assert not fs.exists(sh + "/icons/hicolor/180x180")               # l'icône de golem, elle, est partie
    assert any(c[0] == "update-desktop-database" for c in calls)
    assert any(c[0] == "update-mime-database" for c in calls)
    assert any(c[0] == "gtk-update-icon-cache" for c in calls)


def test_les_bases_du_bureau_de_l_utilisateur_ne_sont_jamais_effacees(fs, calls):
    _reaper_receipt(fs)
    sh = HOME + "/.local/share"
    fs.file(sh + "/applications/defaults.list", "[Default Applications]\ntext/plain=org.gnome.TextEditor.desktop\n")
    fs.file(sh + "/mime/packages/mine.xml")
    ctx = fs.ctx()
    assert U.run(ctx, _defaults(ctx) + ["reaper:app"], Rec()) is True
    assert fs.exists(sh + "/applications/defaults.list")             # une association à toi : intouché
    assert fs.exists(sh + "/mime/packages/mine.xml") and fs.exists(sh + "/mime/mime.cache")
    assert not fs.exists(sh + "/mime/packages/application-x-reaper.xml")
    assert any(c[0] == "update-mime-database" for c in calls)
    assert not fs.exists(sh + "/applications/mimeinfo.cache")        # plus aucune entrée de menu : le cache part
