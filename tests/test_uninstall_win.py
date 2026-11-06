# SPDX-License-Identifier: GPL-3.0-or-later
"""La désinstallation SOUS WINDOWS (docs/uninstall.md §9.3), sans Windows : un FAUX profil Windows dans un dossier
temporaire, ses dossiers donnés par l'environnement (%APPDATA%, %LOCALAPPDATA%, %ProgramFiles%… — un utilisateur
« Jean Paul », des « Program Files » : des espaces partout). Rien ne s'exécute : les lectures PowerShell, powercfg,
taskkill passent par un faux `run_command` ; la passe élevée (UAC) par un faux `elevate` qui joue le script ; le
registre par un faux `uninstall_entries`."""
import json
import os
import stat
import sys

import pytest

from provision import uninstall as U
from provision import uninstall_win as W

GUID_BEFORE = "381b4222-f694-41f0-9685-ff5bb260df2e"
GUID_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
INI = ("[audioconfig]\r\nmode=4\r\n[reaper]\r\nautomute=0\r\nverchk=0\r\ncsurf_0=OSC \"golem\" 3 8000 \"127.0.0.1\" 9000 1024 10 "
       "\"golem\"\r\ncsurf_cnt=1\r\n")


class Win:
    """Un profil Windows : `p("LOCALAPPDATA", "GoleM", "x")` -> le chemin réel dans le faux arbre."""

    def __init__(self, base):
        self.base = str(base)
        self.home = os.path.join(self.base, "Users", "Jean Paul")
        self.env = {
            "USERPROFILE": self.home,
            "APPDATA": os.path.join(self.home, "AppData", "Roaming"),
            "LOCALAPPDATA": os.path.join(self.home, "AppData", "Local"),
            "TEMP": os.path.join(self.home, "AppData", "Local", "Temp"),
            "ProgramData": os.path.join(self.base, "ProgramData"),
            "ProgramFiles": os.path.join(self.base, "Program Files"),
            "CommonProgramFiles": os.path.join(self.base, "Program Files", "Common Files"),
        }

    def p(self, var, *rel):
        return os.path.join(self.env[var] if var in self.env else self.base, *rel)

    def file(self, path, content="x"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        return path

    @property
    def root(self):
        return os.path.join(self.home, "golem")

    @property
    def reaper(self):
        return self.p("APPDATA", "REAPER")

    @property
    def programs(self):
        return self.p("APPDATA", "Microsoft", "Windows", "Start Menu", "Programs")

    @property
    def receipt_path(self):
        return self.p("LOCALAPPDATA", "GoleM", "install-receipt.json")

    def receipt(self, data):
        self.file(self.receipt_path, json.dumps(data))


def machine(base):
    w = Win(base)
    for d in w.env.values():
        os.makedirs(d, exist_ok=True)
    w.file(os.path.join(w.root, "provision", "desktop.py"))
    w.file(os.path.join(w.root, "bridge", "app.py"))
    w.file(os.path.join(w.root, "config", ".power.json"), json.dumps({"before": GUID_BEFORE}))
    obj = w.file(os.path.join(w.root, ".git", "objects", "ab", "cdef"))
    os.chmod(obj, stat.S_IREAD)                          # les objets git sont en lecture seule sous Windows
    w.file(w.p("LOCALAPPDATA", "GoleM", "browser", "Default", "prefs"))
    w.file(w.p("LOCALAPPDATA", "GoleM", "captures", "my-amp-full-1", "train.json"))
    w.file(w.p("LOCALAPPDATA", "golem-installer", "python.exe"))
    w.file(w.p("TEMP", "golem-install-system-1.log"))
    w.file(w.p("TEMP", "not-ours.txt"))
    os.makedirs(os.path.join(w.home, "golem-inbox", ".imported"))
    for name in ("golem.lnk", "golem server.lnk", "Other.lnk"):
        w.file(os.path.join(w.home, "Desktop", name))
    w.file(os.path.join(w.programs, "Stop golem.lnk"))
    w.file(os.path.join(w.programs, "Startup", "golem server.lnk"))
    r = w.reaper
    w.file(os.path.join(r, "Scripts", "golem", "golem_watch.lua"))
    w.file(os.path.join(r, "Effects", "golem", "x.jsfx"))
    w.file(os.path.join(r, "OSC", "golem.ReaperOSC"))
    w.file(os.path.join(r, "OSC", "mine.ReaperOSC"))
    w.file(os.path.join(r, "Scripts", "__startup.lua"), W.STARTUP_HOOK + "\nlocal res = 1\n")
    w.file(os.path.join(r, "Scripts", "__startup.golem-user.lua"), "-- mine\n")
    w.file(os.path.join(r, "golem-root.txt"))
    w.file(os.path.join(r, "golem-runtime.txt"))
    w.file(os.path.join(r, "GoleM", "golem.log"))
    w.file(os.path.join(r, "reaper.ini"), INI)
    w.file(os.path.join(r, "reaper-license.rk"), "LICENCE")
    w.file(w.p("ProgramData", "GoleM", "installers", "reaper.exe"))
    w.file(w.p("ProgramFiles", "REAPER (x64)", "reaper.exe"))
    w.file(w.p("ProgramFiles", "REAPER (x64)", "uninstall.exe"))
    w.file(w.p("ProgramFiles", "REAPER (x64).golem-prev", "reaper.exe"))
    w.file(w.p("CommonProgramFiles", "VST3", "NeuralAmpModeler.vst3", "x"))
    w.file(w.p("CommonProgramFiles", "LV2", "avldrums.lv2", "x"))
    w.file(w.p("CommonProgramFiles", "LV2", "sfizz.lv2", "x"))
    w.file(w.p("CommonProgramFiles", "LV2", "vitalium.lv2", "x"))
    w.file(w.p("LOCALAPPDATA", "Programs", "Common", "VST3", "GoleM", "TapeDelay2.dll"))
    w.file(w.p("LOCALAPPDATA", "Programs", "Python", "Python312", "python.exe"))
    return w


def receipt_data(w, **over):
    pf = w.env["ProgramFiles"]
    cf = w.env["CommonProgramFiles"]
    d = {
        "format": 1, "root": "%USERPROFILE%\\golem",
        "items": [
            {"id": "dir:%ProgramData%", "kind": "dir", "path": os.path.join(w.env["ProgramData"], "GoleM"),
             "owner": "root", "group": "system", "existed": False},
        ],
        "firewall": {"added": ["GoleM - bridge", "GoleM - Reaper, no inbound network", "GoleM - gone"]},
        "prior": {
            "python": {"installed_by_golem": True, "version": "3.12.7",
                       "path": os.path.join(w.env["LOCALAPPDATA"], "Programs", "Python", "Python312", "python.exe")},
            "programs": {
                "vcredist": {"installed_by_golem": True, "uninstall": "C:\\x\\vc_redist.x64.exe /uninstall /quiet"},
                "reaper": {"installed_by_golem": True,
                           "uninstall": "%s\\REAPER (x64)\\uninstall.exe /S" % pf if os.name == "nt"
                           else os.path.join(pf, "REAPER (x64)", "uninstall.exe") + " /S"},
                "nam_vst3": {"installed_by_golem": True, "uninstall_key": "HKEY_LOCAL_MACHINE\\SOFTWARE\\NAM_is1",
                             "uninstall": '"%s" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART'
                                          % os.path.join(pf, "NeuralAmpModeler", "unins000.exe")},
                "avldrums": {"installed_by_golem": False},
                "sfizz": {"installed_by_golem": True, "uninstall": '"%s"' % os.path.join(pf, "sfizz", "unins000.exe")},
                "pawpaw": {"installed_by_golem": True,
                           "uninstall": '"%s" /VERYSILENT' % os.path.join(cf, "PawPaw", "unins000.exe")},
            },
            "reaper": {"installed_by_golem": True},
            "reaper_ini": {"csurf_added": True, "keys": {"automute": "1", "verchk": None}},
            "firewall_deleted": [{"name": "{abc}", "displayname": "python.exe", "program": "C:\\Py 3\\python.exe",
                                  "direction": "Inbound", "action": "Block", "profile": "Public", "protocol": "TCP",
                                  "ports": ["Any"], "enabled": "True"}],
            "power_scheme": {"guid": GUID_BEFORE, "name": "Balanced"},
        },
    }
    d.update(over)
    return d


class Fake:
    """Les commandes : ce qu'elles ont reçu, ce qu'elles rendent."""

    def __init__(self, firewall=("GoleM - bridge", "GoleM - Reaper, no inbound network", "GoleM - golem.local (mDNS)"),
                 active=GUID_PERF, reapers=(), windows=()):
        self.calls, self.firewall, self.active = [], firewall, active
        self.reapers, self.windows = list(reapers), list(windows)

    def __call__(self, ctx, argv, env=None, timeout=900, cwd=None):
        self.calls.append((list(argv), cwd))
        cmd = " ".join(argv)
        if argv[0] == "powercfg":
            if argv[1] == "/getactivescheme":
                return 0, "Power Scheme GUID: %s  (High performance)" % self.active
            self.active = argv[2]
            return 0, ""
        if argv[0] == "powershell" and "Get-NetFirewallRule" in cmd:
            return (0, "\n".join(self.firewall)) if self.firewall is not None else (1, "access denied")
        if argv[0] == "powershell" and "reaper.exe" in cmd:
            return 0, "\n".join("%d\treaper.exe\t%s" % (pid, c) for pid, c in self.reapers)
        if argv[0] == "powershell" and "chrome.exe" in cmd:
            return 0, "\n".join("%d\tchrome.exe\t%s" % (pid, c) for pid, c in self.windows)
        return 0, ""


class Elev:
    """La passe élevée : garde le script, répond à chaque élément comme un PowerShell qui aurait réussi (ou rend
    1223, l'UAC refusée)."""

    def __init__(self, rc=0, fail=()):
        self.scripts, self.rc, self.fail = [], rc, set(fail)

    def __call__(self, ctx, script, logf, on_line):
        with open(script, encoding="utf-8-sig") as f:
            text = f.read()
        self.scripts.append(text)
        if self.rc:
            return self.rc
        import re
        for n in re.findall(r"^Item (\d+) ", text, re.M):
            ok = int(n) not in self.fail
            on_line("@@ITEM %s %d %s\n" % (n, 0 if ok else 1, "done" if ok else "boom"))
        return 0


@pytest.fixture
def win(tmp_path, monkeypatch):
    w = machine(tmp_path / "win")
    for k in ("SystemRoot", "windir", "ProgramFiles(x86)", "ProgramW6432", "CommonProgramW6432", "ALLUSERSPROFILE",
              "TMP", "USERNAME"):
        monkeypatch.delenv(k, raising=False)
    for k, v in w.env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GOLEM_RECEIPT", w.receipt_path)
    monkeypatch.setattr(W, "uninstall_entries", lambda: [])
    # joué SUR Windows, le shell répondrait avec le vrai Bureau et le vrai menu Démarrer : ici le faux profil décide
    monkeypatch.setattr(W, "_shell_folder", lambda csidl: None)
    return w


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(W, "run_command", f)
    return f


@pytest.fixture
def elev(monkeypatch):
    e = Elev()
    monkeypatch.setattr(W, "elevate", e)
    return e


class Rec(U.Reporter):
    def __init__(self):
        super().__init__(as_json=False)
        self.events = []

    def __call__(self, step, item, ok, msg, **extra):
        self.events.append((step, item, ok, msg))
        if item:
            self.results[item] = bool(ok)


def _ids(plan):
    return {i["id"]: i for i in plan["items"]}


def _defaults(plan):
    return [i["id"] for i in plan["items"] if i["default"]]


# ── le contexte ──────────────────────────────────────────────────────────────────────────────────────
def test_les_dossiers_viennent_de_l_environnement(win):
    ctx = W.WinCtx()
    assert ctx.appdata == win.env["APPDATA"] and ctx.programfiles == win.env["ProgramFiles"]
    assert ctx.reaper_dir == win.reaper and ctx.receipt_path == win.receipt_path
    assert ctx.expand("%APPDATA%\\REAPER\\Scripts\\golem") == os.path.join(win.reaper, "Scripts", "golem")
    assert ctx.expand("%LOCALAPPDATA%") == win.env["LOCALAPPDATA"]
    assert ctx.expand("~\\golem-inbox") == os.path.join(win.home, "golem-inbox")
    import inspect
    src = inspect.getsource(W.WinCtx) + inspect.getsource(W.forbidden) + inspect.getsource(W.expected)
    assert "C:" not in src and "Program Files" not in src                   # jamais un dossier Windows en dur


def test_les_chemins_interdits(win):
    ctx = W.WinCtx()
    for p in (win.home, os.path.dirname(win.home), win.env["APPDATA"], win.env["LOCALAPPDATA"], win.env["TEMP"],
              win.env["ProgramData"], win.env["ProgramFiles"], win.env["CommonProgramFiles"],
              os.path.join(win.env["CommonProgramFiles"], "VST3"), os.path.join(win.reaper, "Scripts"),
              os.path.join(win.home, "Desktop"), win.programs, os.path.join(win.programs, "Startup"),
              os.path.join(win.env["LOCALAPPDATA"], "Programs")):
        assert W.forbidden(ctx, p), p
        assert not W.expected(ctx, p, win.root), p
    assert W.expected(ctx, os.path.join(win.home, "Desktop", "golem.lnk"))
    assert not W.expected(ctx, os.path.join(win.home, "Desktop", "Other.lnk"))
    assert not W.expected(ctx, os.path.join(win.env["TEMP"], "not-ours.txt"))
    assert not W.expected(ctx, os.path.join(win.env["ProgramFiles"], "REAPER (x64)"))      # par son désinstalleur seul
    with pytest.raises(U.UninstallError):
        W.safe_remove(ctx, os.path.join(win.home, "Desktop", "Other.lnk"))


# ── le plan ──────────────────────────────────────────────────────────────────────────────────────────
def test_sans_recu_ce_qui_est_a_golem_par_son_nom(win, fake):
    plan = W.build_plan(W.WinCtx())
    assert plan["mode"] == "no-receipt" and plan["root"] == win.root and plan["platform"] == "windows"
    ids = _ids(plan)
    for i in ("golem:install-folder", "golem:local-data", "golem:installer-cache", "golem:tmp", "golem:inbox",
              "golem:shortcut:Desktop/golem.lnk", "golem:shortcut:Desktop/golem server.lnk",
              "golem:shortcut:Programs/Stop golem.lnk", "golem:autostart", "golem:power-plan",
              "reaper-links:Scripts/golem", "reaper-links:Effects/golem", "reaper-links:OSC/golem.ReaperOSC",
              "reaper-links:golem-root.txt", "reaper-links:golem-runtime.txt", "reaper-links:GoleM",
              "reaper-links:Scripts/__startup.lua", "reaper-ini:revert",
              "system:firewall:GoleM - bridge", "system:firewall:GoleM - golem.local (mDNS)",
              "system:programdata", "system:reaper-prev", "plugins:tapedelay2"):
        assert ids[i]["default"] is True and ids[i]["origin"] == "golem-named", i
    assert not any("Other" in i or "mine" in i for i in ids)
    assert ids["golem:tmp"]["paths"] == [os.path.join(win.env["TEMP"], "golem-install-system-1.log")]
    assert ids["reaper-links:Scripts/__startup.lua"]["action"] == "restore"
    assert ids["system:firewall:GoleM - bridge"]["privilege"] == "admin"
    assert ids["golem:power-plan"]["_guid"] == GUID_BEFORE                    # config\.power.json, sans reçu
    # les programmes : présents, mais rien ne dit que golem les a posés -> origine inconnue, décochés
    for p in ("programs:reaper", "programs:nam_vst3", "programs:avldrums", "programs:sfizz", "programs:pawpaw"):
        assert ids[p]["origin"] == "unknown" and ids[p]["default"] is False, p
        assert ids[p]["action"] == "manual"                         # pas de commande au registre (faux) : rien deviné
    assert "toolchain:python" not in ids                            # Python seulement d'après le reçu
    assert ids["reaper:config"]["default"] is False
    assert plan["never_apt"] == list(W.NEVER) and plan["check_yourself"]


def test_avec_recu_les_choix_par_defaut(win, fake):
    win.receipt(receipt_data(win))
    plan = W.build_plan(W.WinCtx())
    ids = _ids(plan)
    assert plan["mode"] == "receipt"
    # programmes : par la commande DU REÇU, cochés sauf REAPER ; « existed » (avldrums) jamais proposé
    assert ids["programs:reaper"]["default"] is False and ids["programs:reaper"]["origin"] == "receipt"
    for p in ("programs:nam_vst3", "programs:sfizz", "programs:pawpaw"):
        assert ids[p]["default"] is True and ids[p]["action"] == "uninstall", p
    assert "programs:avldrums" not in ids
    assert "all the pawpaw plugins" in ids["programs:pawpaw"]["reason"].lower()
    assert ids["programs:nam_vst3"]["_exe"].endswith("unins000.exe") and " " in ids["programs:nam_vst3"]["_exe"]
    assert ids["programs:sfizz"]["_args"] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]   # le silence ajouté
    assert ids["programs:reaper"]["_args"] == ["/S"] and ids["programs:reaper"]["_exe"].endswith("uninstall.exe")
    # le runtime Visual C++ : JAMAIS proposé, même installé par golem
    assert not any("vcredist" in i for i in ids)
    # Python : proposé décoché, désinstallé après la fermeture
    assert ids["toolchain:python"]["default"] is False and ids["toolchain:python"]["action"] in ("uninstall-later", "manual")
    # pare-feu : les règles vues + celles du reçu ; une règle du reçu déjà partie va dans absent
    assert "system:firewall:GoleM - Reaper, no inbound network" in ids and "firewall-name:GoleM - gone" in plan["absent"]
    assert ids["system:firewall:GoleM - bridge"]["origin"] == "receipt"
    assert ids["system:firewall-restore"]["default"] is True and "python.exe" in ids["system:firewall-restore"]["reason"]
    assert ids["golem:power-plan"]["origin"] == "receipt" and ids["golem:power-plan"]["_guid"] == GUID_BEFORE
    assert ids["system:programdata"]["origin"] == "receipt"


def test_le_pare_feu_illisible_n_est_jamais_absent(win, monkeypatch):
    f = Fake(firewall=None)
    monkeypatch.setattr(W, "run_command", f)
    plan = W.build_plan(W.WinCtx())
    ids = _ids(plan)
    for n in W.FIREWALL_FIXED:
        it = ids["system:firewall:%s" % n]
        assert it["presence"] == "unknown" and it["default"] is True
    assert any("firewall" in w for w in plan["warnings"])


def test_le_plan_d_alimentation_deja_remis_n_est_pas_propose(win, monkeypatch):
    monkeypatch.setattr(W, "run_command", Fake(active=GUID_BEFORE))
    assert "golem:power-plan" not in _ids(W.build_plan(W.WinCtx()))


def test_sans_commande_au_recu_le_programme_n_est_pas_propose(win, fake, monkeypatch):
    d = receipt_data(win)
    d["prior"]["programs"]["sfizz"] = {"installed_by_golem": True, "uninstall": None}
    win.receipt(d)
    monkeypatch.setattr(W, "uninstall_entries", lambda: [
        {"name": "sfizz 1.2.3", "uninstall": "C:\\Program Files\\sfizz\\unins000.exe", "quiet": "", "location": "",
         "key": "HKLM\\x"}])
    plan = W.build_plan(W.WinCtx())
    assert "programs:sfizz" not in _ids(plan)                     # rien deviné, même si le registre en a une
    assert any(w.startswith("sfizz: golem installed it, but no uninstall command") for w in plan["warnings"])


def test_sans_recu_le_registre_donne_la_commande_jamais_cochee(win, fake, monkeypatch):
    monkeypatch.setattr(W, "uninstall_entries", lambda: [
        {"name": "sfizz 1.2.3", "uninstall": "C:\\Program Files\\sfizz\\unins000.exe", "quiet": "", "location": "",
         "key": "HKLM\\x"}])
    it = _ids(W.build_plan(W.WinCtx()))["programs:sfizz"]
    assert it["action"] == "uninstall" and it["default"] is False and it["origin"] == "unknown"
    assert it["_exe"] == "C:\\Program Files\\sfizz\\unins000.exe" and "/VERYSILENT" in it["_args"]


def test_split_command():
    assert W.split_command('"C:\\Program Files\\X\\unins000.exe" /SILENT') == ("C:\\Program Files\\X\\unins000.exe", ["/SILENT"])
    assert W.split_command("C:\\Program Files\\REAPER (x64)\\Uninstall.exe /S") == \
        ("C:\\Program Files\\REAPER (x64)\\Uninstall.exe", ["/S"])
    assert W.split_command("MsiExec.exe /X{1234-5678}") == ("MsiExec.exe", ["/X{1234-5678}"])
    assert W.split_command({"exe": "C:\\a b\\u.exe", "args": ["/S"]}) == ("C:\\a b\\u.exe", ["/S"])
    assert W.split_command("") == (None, []) and W.split_command("not a command") == (None, [])
    assert W._with_silent("MsiExec.exe", ["/X{1}"], "inno") == ["/X{1}", "/qn", "/norestart"]
    assert W._with_silent("u.exe", ["/VERYSILENT"], "inno") == ["/VERYSILENT"]


# ── le script élevé ──────────────────────────────────────────────────────────────────────────────────
def test_un_seul_script_eleve_pour_tout_ce_qui_demande_l_administrateur(win, fake, elev):
    win.receipt(receipt_data(win))
    ctx = W.WinCtx()
    plan = W.build_plan(ctx)
    admin = [i for i in plan["items"] if i["privilege"] == "admin" and i["default"]]
    script, refused, todo = W.admin_script(ctx, admin, plan["root"], [])
    assert refused == []
    # les règles et les dossiers d'abord, les programmes ensuite (§5)
    groups = [i["group"] for i in todo]
    assert groups == sorted(groups, key=lambda g: g == "programs")
    pf = win.env["ProgramFiles"]
    # chaque chemin entre apostrophes : « Program Files », « Jean Paul » restent UN argument
    assert "RemoveTree '%s'" % os.path.join(win.env["ProgramData"], "GoleM") in script
    assert "RemoveTree '%s'" % os.path.join(pf, "REAPER (x64).golem-prev") in script
    assert "DropRule 'GoleM - Reaper, no inbound network'" in script
    nam = os.path.join(pf, "NeuralAmpModeler", "unins000.exe")
    assert "Vendor '%s' @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')" % nam in script
    # les sondes (le programme parti ?) : des chemins pour Test-Path -LiteralPath, entre apostrophes ; puis la clé
    assert "@('%s') 'HKEY_LOCAL_MACHINE\\SOFTWARE\\NAM_is1'" % os.path.join(
        win.env["CommonProgramFiles"], "VST3", "NeuralAmpModeler.vst3") in script
    # la règle de Windows supprimée à l'install : recréée telle quelle, une seule fois
    assert "PutRule @{ DisplayName = 'python.exe'; Direction = 'Inbound'; Action = 'Block'; Profile = 'Public'; " \
           "Program = 'C:\\Py 3\\python.exe'; Protocol = 'TCP'; Enabled = 'True' }" in script
    assert "$ErrorActionPreference = 'Stop'" in script and "@@ITEM" in script
    assert script.count("\nItem ") == len(todo)


def test_une_apostrophe_dans_un_chemin_est_doublee(win):
    ctx = W.WinCtx()
    it = {"id": "system:x", "group": "system", "action": "remove-rule", "_rule": "GoleM - l'autre"}
    script, _r, _t = W.admin_script(ctx, [it], None, [])
    assert "DropRule 'GoleM - l''autre'" in script


def test_un_chemin_hors_de_l_ensemble_est_refuse_avant_le_script(win):
    ctx = W.WinCtx()
    it = {"id": "system:programdata", "group": "system", "action": "remove", "_paths": [win.env["ProgramData"]]}
    script, refused, todo = W.admin_script(ctx, [it], None, [])
    assert refused and refused[0][0] == "system:programdata" and not todo and "RemoveTree" not in script.split("#")[-1]


# ── l'exécution ──────────────────────────────────────────────────────────────────────────────────────
def test_tout_par_defaut_dans_l_ordre(win, fake, elev, monkeypatch):
    win.receipt(receipt_data(win))
    later = []
    monkeypatch.setattr(W, "schedule_after_exit", lambda ctx, pid, python=None, copy_dir=None:
                        later.append(python) or (True, "log", "ok"))
    ctx = W.WinCtx()
    plan = W.build_plan(ctx)
    rec = Rec()
    assert W.run(ctx, _defaults(plan), rec) is True, [e for e in rec.events if not e[2]]
    steps = [e[0] for e in rec.events]
    order = ["stop", "root", "programs", "reaper", "user", "folder", "receipt", "done"]
    assert [s for i, s in enumerate(steps) if i == 0 or steps[i - 1] != s] == order
    # l'arrêt d'abord : `python -m provision.desktop stop` DANS le dossier d'install, puis les fenêtres
    stop = next(n for n, c in enumerate(fake.calls) if c[0][1:] == ["-m", "provision.desktop", "stop"])
    assert fake.calls[stop][1] == win.root
    writes = [n for n, c in enumerate(fake.calls) if c[0][0] in ("taskkill",) or c[0][:2] == ["powercfg", "/setactive"]]
    assert writes and min(writes) > stop
    # UNE passe élevée
    assert len(elev.scripts) == 1
    for p in (win.root, win.p("LOCALAPPDATA", "golem-installer"), os.path.join(win.home, "golem-inbox"),
              os.path.join(win.home, "Desktop", "golem.lnk"), os.path.join(win.programs, "Stop golem.lnk"),
              os.path.join(win.programs, "Startup", "golem server.lnk"), os.path.join(win.reaper, "Scripts", "golem"),
              os.path.join(win.reaper, "OSC", "golem.ReaperOSC"), os.path.join(win.reaper, "GoleM"),
              win.p("LOCALAPPDATA", "Programs", "Common"), win.p("LOCALAPPDATA", "GoleM"),
              win.p("TEMP", "golem-install-system-1.log")):
        assert not os.path.lexists(p), p
    # ce qui n'est pas à golem, ou décoché, reste
    for p in (os.path.join(win.home, "Desktop", "Other.lnk"), os.path.join(win.reaper, "OSC", "mine.ReaperOSC"),
              os.path.join(win.reaper, "reaper-license.rk"), win.p("TEMP", "not-ours.txt"),
              win.p("LOCALAPPDATA", "Programs", "Python", "Python312", "python.exe"),
              win.p("ProgramFiles", "REAPER (x64)", "reaper.exe")):
        assert os.path.lexists(p), p
    # le startup de l'utilisateur est remis à sa place
    assert open(os.path.join(win.reaper, "Scripts", "__startup.lua")).read() == "-- mine\n"
    # reaper.ini : clés d'avant, surface OSC retirée, CRLF gardé, copie gardée
    ini = open(os.path.join(win.reaper, "reaper.ini"), newline="", encoding="latin-1").read()
    assert "csurf" not in ini and "automute=1\r\n" in ini and "verchk" not in ini and "\r\n" in ini
    assert os.path.exists(os.path.join(win.reaper, "reaper.ini.golem-uninstall"))
    assert fake.active == GUID_BEFORE                               # le plan d'alimentation d'avant golem
    assert later == []                                              # Python décoché : rien de programmé
    assert not os.path.exists(win.receipt_path)                     # tout est fait, golem est parti


def test_python_est_desinstalle_apres_la_fermeture(win, fake, elev, monkeypatch):
    d = receipt_data(win)
    d["prior"]["python"]["uninstall"] = '"%s" /uninstall' % win.p("LOCALAPPDATA", "Package Cache", "py.exe")
    win.receipt(d)
    later = []
    log = win.p("TEMP", "golem-after-uninstall-1.log")
    monkeypatch.setattr(W, "schedule_after_exit", lambda ctx, pid, python=None, copy_dir=None:
                        later.append((python, pid, copy_dir)) or (True, log, "waiter started (pid 9)"))
    monkeypatch.setenv("GOLEM_UNINSTALL_WAIT_PID", "4242")
    copy = win.p("TEMP", "golem-uninstaller-abc")
    os.makedirs(copy)
    monkeypatch.setenv("GOLEM_UNINSTALLER_COPY", copy)
    ctx = W.WinCtx()
    rec = Rec()
    W.run(ctx, ["toolchain:python"], rec)
    pydir = win.p("LOCALAPPDATA", "Programs", "Python", "Python312")
    # UN veilleur : le désinstalleur de Python ET la copie du désinstallateur, après la fin du processus 4242
    assert later == [({"exe": win.p("LOCALAPPDATA", "Package Cache", "py.exe"),
                       "args": ["/uninstall", "/quiet", "/norestart"], "dir": pydir}, 4242, copy)]
    assert rec.results["toolchain:python"] is True
    assert any(e[1] == "toolchain:python" and log in e[3] for e in rec.events)      # l'écran Done cite son journal


def test_un_reaper_de_golem_ouvert_refuse_tout(win, monkeypatch, elev):
    f = Fake(reapers=[(77, '"%s" "%s"' % (win.p("ProgramFiles", "REAPER (x64)", "reaper.exe"),
                                           os.path.join(win.root, "sets", "golem.rpp")))])
    monkeypatch.setattr(W, "run_command", f)
    ctx = W.WinCtx()
    rec = Rec()
    plan = W.build_plan(ctx)
    assert W.run(ctx, _defaults(plan), rec) is False
    assert elev.scripts == [] and os.path.isdir(win.root) and os.path.isdir(os.path.join(win.reaper, "Scripts", "golem"))
    assert rec.events[-1][0] == "done" and "REAPER of golem" in rec.events[-1][3]


def test_un_reaper_a_soi_n_empeche_que_reaper_ini(win, monkeypatch, elev):
    f = Fake(reapers=[(78, '"C:\\Program Files\\REAPER (x64)\\reaper.exe" "D:\\mes projets\\a.rpp"')])
    monkeypatch.setattr(W, "run_command", f)
    ctx = W.WinCtx()
    rec = Rec()
    W.run(ctx, ["reaper-ini:revert", "reaper-links:Scripts/golem"], rec)
    assert rec.results["reaper-links:Scripts/golem"] is True and rec.results["reaper-ini:revert"] is False


def test_uac_refusee_echec_dit_et_rejouable(win, fake, monkeypatch):
    monkeypatch.setattr(W, "elevate", Elev(rc=1223))
    ctx = W.WinCtx()
    rec = Rec()
    ids = ["system:programdata", "system:firewall:GoleM - bridge", "golem:shortcut:Desktop/golem.lnk"]
    assert W.run(ctx, ids, rec) is False
    msgs = {e[1]: e[3] for e in rec.events if e[1]}
    assert "not granted" in msgs["system:programdata"] and "Retry" in msgs["system:programdata"]
    assert rec.results["golem:shortcut:Desktop/golem.lnk"] is True        # le reste continue
    # Retry : les éléments ratés sont encore au plan
    plan = W.build_plan(ctx)
    assert {"system:programdata", "system:firewall:GoleM - bridge"} <= set(_ids(plan))


def test_un_element_rate_garde_le_recu(win, fake, monkeypatch):
    win.receipt(receipt_data(win))
    ctx = W.WinCtx()
    plan = W.build_plan(ctx)
    admin = [i for i in plan["items"] if i["privilege"] == "admin" and i["default"]]
    nam = next(n for n, i in enumerate([x for x in admin if x["group"] != "programs"]
                                       + [x for x in admin if x["group"] == "programs"]) if i["id"] == "programs:nam_vst3")
    monkeypatch.setattr(W, "elevate", Elev(fail={nam}))
    rec = Rec()
    W.run(ctx, _defaults(plan), rec)
    assert rec.results["programs:nam_vst3"] is False
    r = json.load(open(win.receipt_path))
    assert r["uninstall"]["failed"] == ["programs:nam_vst3"]
    assert "nam_vst3" in r["prior"]["programs"] and "sfizz" not in r["prior"]["programs"]   # fait = consommé
    assert "power_scheme" not in r["prior"] and "firewall_deleted" not in r["prior"]
    assert r["firewall"]["added"] == []                              # retirées (vues) ou déjà parties (absent)
    assert "vcredist" in r["prior"]["programs"]                      # jamais proposé : il reste noté


def test_le_dossier_d_install_est_refuse_depuis_dedans(win, fake, elev, monkeypatch):
    monkeypatch.setattr(W, "_self_paths", lambda: [os.path.join(win.root, "provision")])
    rec = Rec()
    W.run(W.WinCtx(), ["golem:install-folder"], rec)
    assert rec.results["golem:install-folder"] is False and os.path.isdir(win.root)


def test_la_cli_passe_a_windows(win, fake, elev, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "win32")
    assert U.main(["plan", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["platform"] == "windows" and not any(k.startswith("_") for i in plan["items"] for k in i)
    assert U.main(["plan"]) == 0
    out = capsys.readouterr().out
    assert "[programs]" in out and "Check yourself" in out


def test_seules_les_fenetres_de_golem_sont_fermees(win, monkeypatch):
    data = win.p("LOCALAPPDATA", "GoleM")
    f = Fake(windows=[(10, '"chrome.exe" --app=http://x --user-data-dir="%s"' % os.path.join(data, "browser")),
                      (11, '"chrome.exe" --user-data-dir="%s"' % os.path.join(data, "installer-browser")),
                      (12, '"chrome.exe" --profile-directory=Default'),
                      (13, '"msedge.exe" --user-data-dir="%s"' % os.path.join(win.env["TEMP"], "golem-uninstaller-x",
                                                                                 "browser"))])
    monkeypatch.setattr(W, "run_command", f)
    assert W.close_windows(W.WinCtx()) == 2
    killed = [c[0][2] for c in f.calls if c[0][0] == "taskkill"]
    assert killed == ["10", "11"]                         # ni le navigateur à soi, ni la fenêtre du désinstallateur


def test_audioconfig_remis(win):
    text = "[audioconfig]\r\nmode=4\r\nasio_driver=2\r\n[reaper]\r\nx=1\r\n"
    assert W.audioconfig_revert(text, {"section_added": True})[0] == "[reaper]\r\nx=1\r\n"
    new, ch = W.audioconfig_revert(text, {"section_added": False, "keys": {"mode": "3", "asio_driver": None}})
    assert new == "[audioconfig]\r\nmode=3\r\n[reaper]\r\nx=1\r\n" and len(ch) == 2
    assert W.audioconfig_revert(text, None) == (text, [])


def test_recu_reel_chemins_relatifs_fragments_et_audioconfig(win, fake, elev, monkeypatch):
    """Le reçu tel que provision/receipt.py l'écrit sous Windows : chemins du profil en %VAR%, un fragment en attente
    (versé en mémoire par receipt.load), [audioconfig] noté par provision/desktop.py."""
    d = receipt_data(win)
    d["items"] += [
        {"id": "dir:%APPDATA%\\REAPER\\Scripts\\golem", "kind": "dir", "path": "%APPDATA%\\REAPER\\Scripts\\golem",
         "owner": "user", "group": "reaper-links"},
        {"id": "file:%APPDATA%\\REAPER\\Scripts\\__startup.lua", "kind": "file",
         "path": "%APPDATA%\\REAPER\\Scripts\\__startup.lua", "owner": "user", "group": "reaper-links",
         "prior": {"moved_to": "%APPDATA%\\REAPER\\Scripts\\__startup.golem-user.lua"}},
        {"id": "dir:%LOCALAPPDATA%\\GoleM\\browser", "kind": "dir", "path": "%LOCALAPPDATA%\\GoleM\\browser",
         "owner": "user", "group": "golem"},
        {"id": "file:%USERPROFILE%\\Desktop\\golem.lnk", "kind": "file", "path": "%USERPROFILE%\\Desktop\\golem.lnk",
         "owner": "user", "group": "golem"},
    ]
    d["prior"]["reaper_ini"]["audioconfig"] = {"section_added": True}
    if os.sep == "/":                                             # le faux arbre est en chemins POSIX
        for it in d["items"]:
            it["path"] = it["path"].replace("\\", "/")
            it["id"] = it["id"].replace("\\", "/")
        d["items"][-3]["prior"]["moved_to"] = d["items"][-3]["prior"]["moved_to"].replace("\\", "/")
    del d["prior"]["power_scheme"]
    win.receipt(d)
    os.unlink(os.path.join(win.root, "config", ".power.json"))
    win.file(win.receipt_path + ".pending-system-42.json", json.dumps(
        {"format": 1, "items": [], "append": {}, "prior": {"power_scheme.guid": GUID_BEFORE}}))
    plan = W.build_plan(W.WinCtx())
    ids = _ids(plan)
    assert ids["reaper-links:Scripts/golem"]["origin"] == "receipt"
    assert ids["reaper-links:Scripts/__startup.lua"]["action"] == "restore"
    assert ids["golem:local-data"]["_rids"] and ids["golem:shortcut:Desktop/golem.lnk"]["origin"] == "receipt"
    assert not plan["warnings"], plan["warnings"]
    assert "[audioconfig] removed" in ids["reaper-ini:revert"]["reason"]
    # le plan d'alimentation n'est QUE dans le fragment : receipt.load l'a versé en mémoire
    assert ids["golem:power-plan"]["origin"] == "receipt" and ids["golem:power-plan"]["_guid"] == GUID_BEFORE
    rec = Rec()
    nam_fail = Elev(fail={0})
    monkeypatch.setattr(W, "elevate", nam_fail)
    W.run(W.WinCtx(), [i for i in _defaults(plan)], rec)
    ini = open(os.path.join(win.reaper, "reaper.ini"), newline="", encoding="latin-1").read()
    assert "[audioconfig]" not in ini and ini.startswith("[reaper]\r\n")
    assert not os.path.exists(win.receipt_path + ".pending-system-42.json")    # versé, puis effacé à la réécriture


# ── premier cycle en VM Windows (2026-10-16) ─────────────────────────────────────────────────────────
def test_une_regle_nommee_golem_qui_n_est_pas_a_golem_n_est_jamais_cochee(win, monkeypatch, elev):
    # la VM avait sa propre règle « GoleM sshd » : le premier passage l'a supprimée (SSH perdu)
    f = Fake(firewall=("GoleM - bridge", "GoleM sshd", "GoleM - custom"))
    monkeypatch.setattr(W, "run_command", f)
    ids = _ids(W.build_plan(W.WinCtx()))                              # sans reçu : seuls les noms fixes
    assert ids["system:firewall:GoleM - bridge"]["default"] is True
    for n in ("GoleM sshd", "GoleM - custom"):
        it = ids["system:firewall:%s" % n]
        assert it["default"] is False and it["origin"] == "unknown"
        assert it["reason"] == "named like golem's rules, but golem did not create it"
    d = receipt_data(win)
    d["firewall"]["added"].append("GoleM - custom")                    # avec reçu : firewall.added compte aussi
    win.receipt(d)
    plan = W.build_plan(W.WinCtx())
    ids = _ids(plan)
    assert ids["system:firewall:GoleM - custom"]["default"] is True and ids["system:firewall:GoleM - custom"]["origin"] == "receipt"
    assert ids["system:firewall:GoleM sshd"]["default"] is False
    # tout par défaut : la règle de l'utilisateur n'entre jamais dans le script élevé
    monkeypatch.setattr(W, "schedule_after_exit", lambda *a, **k: (True, "log", "ok"))
    W.run(W.WinCtx(), _defaults(plan), Rec())
    assert "GoleM sshd" not in elev.scripts[0] and "DropRule 'GoleM - custom'" in elev.scripts[0]


def _py_rules(win):
    py = win.p("LOCALAPPDATA", "Programs", "Python", "Python312", "python.exe")
    return [{"name": "{q1}", "displayname": "python.exe", "program": py.upper(), "direction": "Inbound",
             "action": "Allow", "profile": "Private", "protocol": "TCP", "ports": ["Any"], "enabled": "True"},
            {"name": "{q2}", "displayname": "other.exe", "program": "C:\\Tools\\other.exe", "direction": "Inbound",
             "action": "Block", "profile": "Public", "protocol": "Any", "enabled": "True"}]


def test_python_retire_emporte_ses_regles_et_ne_les_recree_pas(win, fake, elev, monkeypatch):
    d = receipt_data(win)
    d["prior"]["python"]["uninstall"] = '"C:\\PC\\py.exe" /uninstall /quiet'
    d["prior"]["firewall_deleted"] = _py_rules(win)
    win.receipt(d)
    monkeypatch.setattr(W, "schedule_after_exit", lambda *a, **k: (True, "log", "ok"))
    ctx = W.WinCtx()
    plan = W.build_plan(ctx)
    assert "not the ones for golem's Python" in _ids(plan)["system:firewall-restore"]["reason"]
    rec = Rec()
    W.run(ctx, ["toolchain:python", "system:firewall-restore"], rec)
    script = elev.scripts[0]
    pydir = win.p("LOCALAPPDATA", "Programs", "Python", "Python312")
    exes = [os.path.normpath(os.path.join(pydir, n)).lower() for n in ("python.exe", "pythonw.exe")]
    assert "DropProgramRules @('%s', '%s')" % tuple(exes) in script
    # la règle de ce Python (casse différente) n'est PAS recréée ; l'autre si
    assert "DisplayName = 'other.exe'" in script and "DisplayName = 'python.exe'" not in script
    assert rec.results["toolchain:python:firewall"] is True and rec.results["system:firewall-restore"] is True


def test_python_retire_seule_regle_a_recreer_dite_sans_echec(win, fake, elev, monkeypatch):
    d = receipt_data(win)
    d["prior"]["python"]["uninstall"] = '"C:\\PC\\py.exe" /uninstall /quiet'
    d["prior"]["firewall_deleted"] = _py_rules(win)[:1]
    win.receipt(d)
    monkeypatch.setattr(W, "schedule_after_exit", lambda *a, **k: (True, "log", "ok"))
    rec = Rec()
    assert W.run(W.WinCtx(), ["toolchain:python", "system:firewall-restore"], rec) is True
    msg = next(e[3] for e in rec.events if e[1] == "system:firewall-restore")
    assert "Python being removed" in msg and "PutRule @" not in elev.scripts[0]


def test_python_garde_rien_ne_change_pour_ses_regles(win, fake, elev, monkeypatch):
    d = receipt_data(win)
    d["prior"]["firewall_deleted"] = _py_rules(win)
    win.receipt(d)
    W.run(W.WinCtx(), ["system:firewall-restore"], Rec())
    script = elev.scripts[0]
    assert "DropProgramRules @(" not in script.split("PutRule($h)")[-1]
    assert "DisplayName = 'python.exe'" in script and "DisplayName = 'other.exe'" in script


def test_la_commande_de_python_est_celle_du_bundle(win, fake, monkeypatch):
    # sans commande au reçu (bootstrap d'avant) : le registre — le BUNDLE en HKCU, jamais un de ses MSI
    win.receipt(receipt_data(win))
    pc = "C:\\Users\\Jean Paul\\AppData\\Local\\Package Cache\\{1234}\\python-3.12.7-amd64.exe"
    monkeypatch.setattr(W, "uninstall_entries", lambda: [
        {"name": "Python 3.12.7 Core Interpreter (64-bit)", "uninstall": "MsiExec.exe /I{AAA}", "quiet": "",
         "location": "", "key": "HKCU\\{AAA}", "system": True},
        {"name": "Python 3.12.7 Standard Library (64-bit)", "uninstall": "MsiExec.exe /I{BBB}", "quiet": "",
         "location": "", "key": "HKCU\\{BBB}", "system": False},
        {"name": "Python 3.12.7 (64-bit)", "uninstall": '"%s" /modify' % pc, "quiet": '"%s" /uninstall /quiet' % pc,
         "location": "", "key": "HKCU\\{1234}", "system": False}])
    it = _ids(W.build_plan(W.WinCtx()))["toolchain:python"]
    assert it["action"] == "uninstall-later" and it["_exe"] == pc
    assert it["_args"] == ["/uninstall", "/quiet", "/norestart"]


def test_le_veilleur_qui_ne_part_pas_est_un_echec_dit(win, fake, monkeypatch):
    d = receipt_data(win)
    d["prior"]["python"]["uninstall"] = '"C:\\PC\\py.exe" /uninstall /quiet'
    win.receipt(d)
    monkeypatch.setattr(W, "schedule_after_exit", lambda *a, **k: (False, "the.log", "the waiter could not start: x"))
    rec = Rec()
    W.run(W.WinCtx(), ["toolchain:python"], rec)
    assert rec.results["toolchain:python"] is False
    assert "could not start" in next(e[3] for e in rec.events if e[1] == "toolchain:python")


def test_schedule_after_exit_passe_par_wmi(win, monkeypatch):
    seen = []

    def runner(ctx, argv, env=None, timeout=900, cwd=None):
        seen.append(argv)
        return 0, "@@WAITER 0 5555"
    monkeypatch.setattr(W, "run_command", runner)
    ok, log, msg = W.schedule_after_exit(W.WinCtx(), 4242, python={"exe": "C:\\PC\\py.exe", "args": ["/uninstall"],
                                                                     "dir": "C:\\Py"})
    assert ok and "5555" in msg and log.startswith(win.env["TEMP"]) and log.endswith(".log")
    assert "Invoke-CimMethod -ClassName Win32_Process -MethodName Create" in seen[0][-1]
    ps1 = log[:-4] + ".ps1"
    text = open(ps1, encoding="utf-8-sig").read()
    assert "$wait = 4242" in text and "$exe = 'C:\\PC\\py.exe'" in text


def test_le_cache_de_pip_ne_de_golem(win, fake, elev, monkeypatch):
    pip = win.p("LOCALAPPDATA", "pip")
    win.file(os.path.join(pip, "cache", "http-v2", "0", "x"))
    assert "toolchain:pip-cache" not in _ids(W.build_plan(W.WinCtx()))           # sans reçu : jamais
    d = receipt_data(win)
    d["prior"]["pip_cache_existed"] = True
    win.receipt(d)
    assert "toolchain:pip-cache" not in _ids(W.build_plan(W.WinCtx()))           # là avant golem : jamais
    d["prior"]["pip_cache_existed"] = False
    win.receipt(d)
    it = _ids(W.build_plan(W.WinCtx()))["toolchain:pip-cache"]
    assert it["default"] is False and it["group"] == "toolchain" and it["paths"] == [pip]
    assert it["reason"].startswith("pip's download cache, created by golem's install")
    rec = Rec()
    W.run(W.WinCtx(), ["toolchain:pip-cache"], rec)
    assert rec.results["toolchain:pip-cache"] is True and not os.path.exists(pip)


def test_les_dossiers_communs_crees_pour_golem_partent_vides_en_dernier(win, fake, elev, monkeypatch):
    os.makedirs(win.p("CommonProgramFiles", "CLAP"))
    assert "system:common-dirs" not in _ids(W.build_plan(W.WinCtx()))          # sans reçu : jamais touchés
    d = receipt_data(win)
    d["prior"]["common_dirs"] = {"VST3": False, "LV2": True, "CLAP": False}
    win.receipt(d)
    ctx = W.WinCtx()
    plan = W.build_plan(ctx)
    it = _ids(plan)["system:common-dirs"]
    vst3, clap = win.p("CommonProgramFiles", "VST3"), win.p("CommonProgramFiles", "CLAP")
    assert it["paths"] == [vst3, clap] and it["default"] is True and it["action"] == "remove-empty-dirs"
    admin = [i for i in plan["items"] if i["privilege"] == "admin" and i["default"]]
    script, refused, todo = W.admin_script(ctx, admin, plan["root"], [])
    assert refused == [] and todo[-1]["id"] == "system:common-dirs"              # APRÈS les désinstalleurs
    assert "(@((DropEmptyDir '%s'), (DropEmptyDir '%s')) -join '; ')" % (vst3, clap) in script
    # jamais un autre dossier, même dans la liste
    bad = dict(it, _dirs=[win.p("CommonProgramFiles", "Microsoft Shared")])
    _s, refused, _t = W.admin_script(ctx, [bad], None, [])
    assert refused and "not a common plugin folder" in refused[0][1]


def _after_exit():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "golem_after_exit_t", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "installer",
                                           "after_exit_win.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_le_veilleur_attend_desinstalle_python_puis_efface_la_copie_marquee():
    A = _after_exit()
    text = A.script(4242, "C:\\Users\\Jean Paul\\AppData\\Local\\Temp\\golem-after-uninstall-1.log",
                    python={"exe": "C:\\Users\\Jean Paul\\AppData\\Local\\Package Cache\\{1}\\python-3.12.10-amd64.exe",
                            "args": ["/uninstall", "/quiet", "/norestart"], "dir": "C:\\Py 3"},
                    copy_dir="C:\\Users\\Jean Paul\\AppData\\Local\\Temp\\golem-uninstaller-abc")
    # l'ordre : attendre le désinstallateur, PUIS Python, PUIS la copie ; s'effacer à la fin
    w, py, cp = text.index("Get-Process -Id $wait"), text.index("Start-Process -FilePath $exe"), text.index("$copy = ")
    assert w < py < cp < text.rindex("Remove-Item -LiteralPath $PSCommandPath")
    assert "$wait = 4242" in text and "$a = @('/uninstall', '/quiet', '/norestart')" in text
    assert "python uninstaller exit code" in text and "python folder gone" in text and "uninstaller copy removed" in text
    # la copie : SEULEMENT avec son nom ET son marqueur
    assert "-Filter 'golem-uninstaller-*'" in text and "$mk = '.golem-uninstaller'" in text
    assert text.index("Where-Object { $_.Name -ne $mk }") < text.index("Remove-Item -LiteralPath $d -Recurse")  # marqueur en dernier
    assert "$log = 'C:\\Users\\Jean Paul\\AppData\\Local\\Temp\\golem-after-uninstall-1.log'" in text
    only_copy = A.script(1, "l.log", copy_dir="C:\\T\\golem-uninstaller-x")
    assert "Start-Process" not in only_copy and "$copy = " in only_copy
    # créé par WMI : hors de l'arbre et du job du désinstallateur, cwd %TEMP% (jamais la copie)
    la = A.launcher("C:\\T\\golem-after-uninstall-1.ps1", "C:\\T")
    assert "Invoke-CimMethod -ClassName Win32_Process -MethodName Create" in la and "CurrentDirectory = 'C:\\T'" in la
    assert "Start-Process" not in la and "Popen" not in la


def test_le_veilleur_qui_ne_demarre_pas_ne_laisse_que_son_journal(tmp_path):
    A = _after_exit()
    ok, log, msg = A.schedule(7, str(tmp_path), copy_dir=str(tmp_path / "golem-uninstaller-x"),
                              runner=lambda argv: (1, "@@WAITER 9 0"))
    assert not ok and "could not start" in msg
    assert sorted(os.listdir(tmp_path)) == [os.path.basename(log)] and "could not start" in open(log).read()
    ok, log, msg = A.schedule(7, str(tmp_path), runner=lambda argv: (0, "@@WAITER 0 321"))
    assert ok and msg == "waiter started (pid 321)" and os.path.isfile(log[:-4] + ".ps1")


def test_chaque_programme_que_l_installation_note_est_connu_du_desinstallateur():
    # Proteus (bloc Boost, 2026-10-22) était noté au reçu par install-system.ps1 mais absent de PROGRAMS : la
    # désinstallation ne le proposait jamais et le laissait dans Program Files (VM Windows 2026-10-24)
    import re
    from provision import uninstall_win as U
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "provision", "windows", "install-system.ps1"), encoding="utf-8").read()
    noted = set(re.findall(r"Rcpt-Program '([a-z0-9_]+)'", src))
    known = {p[0] for p in U.PROGRAMS} | set(U.PROGRAM_ALIASES)
    noted.discard("vcredist")                       # la base du système : JAMAIS proposé (U.NEVER), c'est voulu
    assert noted and noted <= known, noted - known
