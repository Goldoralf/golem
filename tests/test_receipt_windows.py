# SPDX-License-Identifier: GPL-3.0-or-later
"""Le reçu d'installation SOUS WINDOWS (docs/uninstall.md §9.2) — ce qui se vérifie sans Windows.

provision/receipt.py simulé en Windows (sys.platform, %LOCALAPPDATA%…), son verrou msvcrt par un faux, les fragments
du bootstrap et du script élevé, et les scripts PowerShell LUS (pas de PowerShell ici : on vérifie leur texte).
Tout se passe dans des dossiers temporaires : GOLEM_RECEIPT est redirigé (tests/conftest.py), rien ne touche la
machine — ni ~/.config/REAPER, ni le vrai reçu."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROV = ROOT / "provision"
PS_SYSTEM = PROV / "windows" / "install-system.ps1"
PS_BOOT = PROV / "bootstrap.ps1"

WIN_ENV = {"USERPROFILE": r"C:\Users\Jean Paul", "APPDATA": r"C:\Users\Jean Paul\AppData\Roaming",
           "LOCALAPPDATA": r"C:\Users\Jean Paul\AppData\Local"}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def R(tmp_path, monkeypatch):
    """receipt.py, reçu dans un fichier temporaire (GOLEM_RECEIPT)."""
    monkeypatch.setenv("GOLEM_RECEIPT", str(tmp_path / "r" / "install-receipt.json"))
    return _load("golem_receipt_win_t", PROV / "receipt.py")


@pytest.fixture
def win(monkeypatch):
    """Simule Windows pour receipt.py : sys.platform et le profil de « Jean Paul »."""
    monkeypatch.setattr(sys, "platform", "win32")
    for k, v in WIN_ENV.items():
        monkeypatch.setenv(k, v)


def _data(R):
    return json.loads(Path(R.receipt_path()).read_text(encoding="utf-8"))


def _ps(path):
    return path.read_text(encoding="utf-8-sig")


# ── le chemin du reçu, par OS ────────────────────────────────────────────────────────────────────
def test_chemin_par_os(monkeypatch, tmp_path):
    monkeypatch.delenv("GOLEM_RECEIPT", raising=False)
    m = _load("golem_receipt_path_t", PROV / "receipt.py")
    monkeypatch.setattr(sys, "platform", "win32")
    for k, v in WIN_ENV.items():
        monkeypatch.setenv(k, v)
    assert m.receipt_path() == r"C:\Users\Jean Paul\AppData\Local\GoleM\install-receipt.json"
    monkeypatch.delenv("LOCALAPPDATA")                       # repli : <profil>\AppData\Local
    assert m.receipt_path() == r"C:\Users\Jean Paul\AppData\Local\GoleM\install-receipt.json"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))         # joué depuis Windows, expanduser lit USERPROFILE, pas HOME
    assert m.receipt_path() == str(tmp_path / "Library" / "Application Support" / "golem" / "install-receipt.json")
    monkeypatch.setattr(sys, "platform", "linux")
    assert m.receipt_path() == str(tmp_path / ".local" / "share" / "golem" / "install-receipt.json")
    monkeypatch.setenv("GOLEM_RECEIPT", str(tmp_path / "x.json"))   # l'override vaut sur chaque OS
    for plat in ("win32", "darwin", "linux"):
        monkeypatch.setattr(sys, "platform", plat)
        assert m.receipt_path() == str(tmp_path / "x.json")


def test_pas_de_sudo_sous_windows(R, win, monkeypatch):
    import os
    monkeypatch.setenv("SUDO_USER", "someone")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
    assert R._sudo_user() is None
    assert R.user_home() == WIN_ENV["USERPROFILE"]


# ── les chemins : %VAR% pour le profil, absolus pour le système ──────────────────────────────────
def test_chemins_relatifs_au_profil_et_retour(R, win):
    cases = {
        r"C:\Users\Jean Paul\AppData\Roaming\REAPER\Scripts\golem": r"%APPDATA%\REAPER\Scripts\golem",
        r"C:\Users\Jean Paul\AppData\Local\GoleM\browser": r"%LOCALAPPDATA%\GoleM\browser",
        r"c:\users\jean paul\appdata\local\GoleM": r"%LOCALAPPDATA%\GoleM",            # NTFS ignore la casse
        r"C:\Users\Jean Paul\OneDrive\Desktop\golem.lnk": r"%USERPROFILE%\OneDrive\Desktop\golem.lnk",
        r"C:\Users\Jean Paul": "%USERPROFILE%",
        r"C:\Program Files\REAPER (x64).golem-prev": r"C:\Program Files\REAPER (x64).golem-prev",
        r"C:\ProgramData\GoleM": r"C:\ProgramData\GoleM",
        r"C:\Users\Jean Paulette\x": r"C:\Users\Jean Paulette\x",                     # un préfixe n'est pas un dossier
    }
    for real, stored in cases.items():
        assert R.tilde(real) == stored, real
    for real, stored in cases.items():
        if real.startswith("c:"):                                                     # (la casse d'origine est perdue)
            continue
        assert R.expand(stored) == real, stored
    assert R.expand(r"%NOPE%\x") == r"%NOPE%\x"                                       # inconnue : laissée telle quelle
    assert R.expand("~\\golem") == r"C:\Users\Jean Paul\golem"


def test_add_sous_windows_proprietaire_et_id(R, win):
    R.add(r"C:\Users\Jean Paul\AppData\Roaming\REAPER\Scripts\__startup.lua", "file", "provision/desktop.py",
          "reaper-links", moved_to=r"C:\Users\Jean Paul\AppData\Roaming\REAPER\Scripts\__startup.golem-user.lua")
    R.add(r"C:\ProgramData\GoleM", "dir", "x", "system")
    items = {it["id"]: it for it in _data(R)["items"]}
    st = items[r"file:%APPDATA%\REAPER\Scripts\__startup.lua"]
    assert st["owner"] == "user"
    assert st["prior"] == {"moved_to": r"%APPDATA%\REAPER\Scripts\__startup.golem-user.lua"}
    assert items[r"dir:C:\ProgramData\GoleM"]["owner"] == "root"                       # administrateur


# ── le verrou msvcrt ─────────────────────────────────────────────────────────────────────────────
class FakeMsvcrt:
    LK_NBLCK, LK_UNLCK, LK_LOCK = 2, 0, 1

    def __init__(self, busy=0):
        self.calls, self.busy = [], busy

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes))
        if mode == self.LK_NBLCK and self.busy:
            self.busy -= 1
            raise OSError(36, "Resource deadlock avoided")


def test_verrou_msvcrt_attend_puis_libere(R, monkeypatch):
    fake = FakeMsvcrt(busy=2)                                # tenu deux fois par un autre écrivain, puis libre
    monkeypatch.setattr(R, "fcntl", None)
    monkeypatch.setattr(R, "msvcrt", fake)
    R.prior("x", 1)
    assert _data(R)["prior"]["x"] == 1
    modes = [m for m, _ in fake.calls]
    assert modes == [fake.LK_NBLCK, fake.LK_NBLCK, fake.LK_NBLCK, fake.LK_UNLCK]
    assert all(n == 1 for _, n in fake.calls)


def test_verrou_msvcrt_abandonne_apres_le_delai(R, monkeypatch):
    fake = FakeMsvcrt(busy=10 ** 6)
    monkeypatch.setattr(R, "fcntl", None)
    monkeypatch.setattr(R, "msvcrt", fake)
    monkeypatch.setattr(R, "LOCK_WAIT", 0.1)
    with pytest.raises(OSError):
        R.prior("x", 1)
    assert not Path(R.receipt_path()).exists()


# ── les fragments ────────────────────────────────────────────────────────────────────────────────
def _frag(R, name, doc, bom=False):
    p = Path(R.receipt_path() + R.PENDING + name + ".json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + json.dumps(doc, indent=4).encode("utf-8"))
    return p


BOOT = {"format": 1, "by": "provision/bootstrap.ps1", "items": [], "append": {},
        "prior": {"python.installed_by_golem": True, "python.version": "3.12.10",
                  "python.path": r"C:\Users\Jean Paul\AppData\Local\Programs\Python\Python312\python.exe"}}


def test_fragment_du_bootstrap_verse_a_la_naissance_du_recu(R):
    f = _frag(R, "bootstrap", BOOT, bom=True)                 # un BOM n'est pas une corruption
    assert R.merge_pending() == 0 and f.exists()              # pas de reçu : rien (règle du bridge)
    assert R.load()["prior"]["python"]["installed_by_golem"] is True   # lu en mémoire, sans rien écrire
    assert f.exists() and not R.exists()
    R.set_root("/x/golem")                                    # l'étape « source » de l'installateur
    d = _data(R)
    assert d["prior"]["python"] == {"installed_by_golem": True, "version": "3.12.10",
                                    "path": BOOT["prior"]["python.path"]}
    assert d["root"] == os.path.abspath("/x/golem") and not f.exists()    # set_root rend un chemin absolu DE L'OS


def test_fragment_le_premier_gagne(R):
    R.prior("python", {"installed_by_golem": True, "version": "3.12.10", "path": "p"})
    _frag(R, "bootstrap", {**BOOT, "prior": {"python.installed_by_golem": False}})
    assert R.merge_pending() == 1
    assert _data(R)["prior"]["python"]["installed_by_golem"] is True


SYSTEM = {"format": 1, "by": "provision/windows/install-system.ps1",
          "items": [{"path": r"C:\ProgramData\GoleM", "kind": "dir", "group": "system", "owner": "root", "existed": False},
                    {"path": r"C:\Program Files\REAPER (x64).golem-prev", "kind": "dir", "group": "system",
                     "owner": "root", "existed": False}],
          "prior": {"programs.reaper.installed_by_golem": True, "programs.reaper.version": "7.79",
                    "programs.reaper.uninstall": r'"C:\Program Files\REAPER (x64)\Uninstall.exe" /S',
                    "reaper.installed_by_golem": True},
          "append": {"firewall.added": ["GoleM - bridge", "GoleM - golem.local (mDNS)"],
                     "prior.firewall_deleted": [{"name": "{A}", "displayname": "python.exe", "program": "p",
                                                 "direction": "Inbound", "action": "Block", "profile": "Public",
                                                 "protocol": "TCP", "ports": ["Any"], "enabled": "True"}]}}


def test_fragment_du_script_eleve(R, win):
    R.set_root("/x/golem")
    R.prior("reaper.license_present", False)                  # l'écran 3, avant le script élevé
    _frag(R, "system-4242", SYSTEM)
    second = json.loads(json.dumps(SYSTEM))                   # un 2e passage (Retry, ou -Firewall depuis la page)
    second["append"]["prior.firewall_deleted"].append({**second["append"]["prior.firewall_deleted"][0], "name": "{B}"})
    second["append"]["firewall.added"] = ["GoleM - bridge"]
    second["prior"]["programs.reaper.installed_by_golem"] = False
    _frag(R, "system-4343", second)
    assert R.merge_pending() == 2
    d = _data(R)
    assert d["prior"]["programs"]["reaper"]["installed_by_golem"] is True               # le premier gagne
    assert d["prior"]["reaper"] == {"license_present": False, "installed_by_golem": True}   # fusion par clé pointée
    assert d["firewall"]["added"] == ["GoleM - bridge", "GoleM - golem.local (mDNS)"]   # dédoublonné
    assert [r["name"] for r in d["prior"]["firewall_deleted"]] == ["{A}", "{B}"]         # par nom
    ids = [it["id"] for it in d["items"]]
    assert ids == [r"dir:C:\ProgramData\GoleM", r"dir:C:\Program Files\REAPER (x64).golem-prev"]
    assert all(it["owner"] == "root" and it["group"] == "system" for it in d["items"])
    assert all(it["by"] == "provision/windows/install-system.ps1" for it in d["items"])
    assert not R.pending_fragments()


def test_fragment_illisible_mis_de_cote(R):
    R.set_root("/x")
    p = Path(R.receipt_path() + R.PENDING + "system-1.json")
    p.write_text("{nope", encoding="utf-8")
    R.prior("y", 1)
    assert not p.exists() and Path(str(p) + ".bad").exists()
    assert _data(R)["prior"]["y"] == 1


# ── bridge/install_receipt : Windows accepté ─────────────────────────────────────────────────────
def test_le_bridge_ecrit_aussi_sous_windows(R, monkeypatch):
    from bridge import install_receipt as IR
    monkeypatch.setattr(IR, "_MOD", None)
    monkeypatch.setattr(sys, "platform", "win32")
    assert IR.prior("reaper.license_present", True) is False          # pas de reçu : rien
    assert IR.path() is None
    R.set_root("/x")
    assert IR.prior("reaper.license_present", True) is True
    assert IR.path() == R.receipt_path()
    _frag(R, "system-9", SYSTEM)
    assert IR.merge_pending() == 1
    monkeypatch.setattr(sys, "platform", "darwin")                     # macOS : plus tard
    assert IR.prior("other", 1) is False


# ── le bootstrap PowerShell (lu, pas exécuté) ────────────────────────────────────────────────────
def test_bootstrap_depose_le_fragment_python():
    raw = PS_BOOT.read_bytes()
    raw.decode("ascii")                                       # irm | iex ET -File : ASCII seulement
    s = raw.decode("ascii")
    assert "pending-bootstrap.json" in s
    for key in ("python.installed_by_golem", "python.version", "python.path"):
        assert f"'{key}'" in s, key
    # vrai SEULEMENT après avoir posé Python soi-même
    assert s.count("$pythonByGolem = $true") == 1
    i_install = s.index("Start-Process $pyExe")
    assert s.index("$pythonByGolem = $true") > i_install
    assert s.index("$pythonByGolem = $false") < s.index("if (-not $python) {")
    # un fragment déjà là n'est jamais remplacé ; sans BOM ; GOLEM_RECEIPT respecté ; jamais fatal
    assert "if (-not (Test-Path $frag))" in s
    code = [ln for ln in s[s.index("2 bis"):].splitlines() if not ln.lstrip().startswith("#")]
    assert "UTF8Encoding($false)" in s and not any("Set-Content" in ln for ln in code)
    assert "$env:GOLEM_RECEIPT" in s and r"'GoleM\install-receipt.json'" in s
    block = s[s.index("2 bis"):s.index("#  3.")]
    assert block.count("try {") == 1 and "catch {" in block and "Die " not in block


# ── le script élevé (lu, pas exécuté) ────────────────────────────────────────────────────────────
COMPONENTS = {"vcredist": "burn", "reaper": "nsis", "nam_vst3": "inno", "avldrums": "nsis", "sfizz": "inno",
              "pawpaw": "inno", "proteus": "inno"}


def test_script_eleve_recoit_le_recu_en_parametre():
    s = _ps(PS_SYSTEM)
    params = s[s.index("param("):s.index("\n)", s.index("param(")) + 2]
    assert "[string]$Receipt = ''" in params
    # jamais résolu en administrateur
    assert "install-receipt.json" not in s
    assert "$env:LOCALAPPDATA" not in s
    assert '"$Receipt.pending-system-$PID.json"' in s
    assert "UTF8Encoding($false)" in s


def test_script_eleve_note_chaque_composant():
    s = _ps(PS_SYSTEM)
    for cid, family in COMPONENTS.items():
        assert re.search(rf"Rcpt-Program '{cid}' \$false", s), f"{cid}: existed"
        m = re.search(rf"Rcpt-Program '{cid}' (\$true|\(\$rc -ne 1638\)).*?UninstallEntry \$before '[^']+' '{family}'",
                      s, re.S)
        assert m, f"{cid}: installed + uninstall command ({family})"
    # la photo des clés Uninstall est prise AVANT chaque installeur, la commande lue APRÈS
    for m in re.finditer(r"\$before = UninstallKeys\n(.*?)UninstallEntry \$before", s, re.S):
        assert re.search(r"\bInstall \$|\bInstall \(", m.group(1)), m.group(0)[:120]
    assert len(re.findall(r"^\s+\$before = UninstallKeys$", s, re.M)) == len(COMPONENTS)
    # QuietUninstallString d'abord, sinon UninstallString + le commutateur connu
    assert "QuietUninstallString" in s and "UninstallString" in s
    assert "nsis = '/S'" in s
    assert "inno = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART'" in s
    assert "burn = '/uninstall /quiet /norestart'" in s
    for root in (r"HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                 r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                 r"HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"):
        assert root in s
    # prior.reaper : même forme que sous Linux
    assert s.count("Rcpt-Prior 'reaper.installed_by_golem'") == 2


def test_script_eleve_exporte_avant_de_supprimer():
    s = _ps(PS_SYSTEM)
    i_export = s.index("Rcpt-Append 'prior.firewall_deleted' (Export-Rule $_)")
    i_remove = s.index("Remove-NetFirewallRule -Name $_.Name")
    assert i_export < i_remove
    exp = s[s.index("function Export-Rule"):s.index("\n}\n", s.index("function Export-Rule"))]
    for field in ("name", "displayname", "program", "direction", "action", "profile", "protocol", "ports", "enabled"):
        assert re.search(rf"\b{field} = ", exp), field
    for rule in ("$name", "$bname", "$mname"):
        assert f"Rcpt-Append 'firewall.added' {rule}" in s, rule


def test_script_eleve_note_golem_prev_et_programdata():
    s = _ps(PS_SYSTEM)
    i_copy = s.index("Copy-Item -Recurse -Force -LiteralPath $ReaperDir -Destination $prev")
    assert s.index("Rcpt-Item $prev 'dir' 'system'", i_copy) - i_copy < 200
    assert "Rcpt-Item $golemData 'dir' 'system' $golemDataExisted" in s
    assert s.index("$golemDataExisted = Test-Path $golemData") < s.index("New-Item -ItemType Directory -Force -Path $dl")


def test_script_eleve_garde_son_bom():
    assert PS_SYSTEM.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.skipif(not shutil.which("pwsh"), reason="pas de PowerShell sur cette machine")
def test_scripts_powershell_s_analysent():
    for p in (PS_SYSTEM, PS_BOOT):
        cmd = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{p}', [ref]$null, [ref]$e); if ($e) {{ $e | ForEach-Object {{ $_.Message }}; exit 1 }}")
        r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, (p.name, r.stdout, r.stderr)


# ── l'installateur Windows : RECEIPT, -Receipt, set-root ─────────────────────────────────────────
@pytest.fixture
def PW(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "installer"))
    import platform_windows
    return platform_windows


def test_installateur_windows_a_un_recu(PW):
    assert PW.RECEIPT is True                     # l'écran 3 note la licence d'avant golem (server._license_prior)


def test_run_elevated_passe_le_recu_et_verse_le_fragment(PW, R, tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))
    R.set_root("/x")
    seen = {}

    def run(cmd, step, **kw):
        seen["cmd"] = cmd
        _frag(R, "system-7", SYSTEM)                          # ce que le script élevé aurait déposé
        return 0
    ctx = SimpleNamespace(S={"dry": False, "src": str(ROOT)}, run=run, log=lambda *a: None)
    assert PW.run_elevated(ctx, "system", ["-Nam"]) == 0
    inner = seen["cmd"][-1]
    assert "'-Receipt'" in inner and R.receipt_path() in inner
    assert not R.pending_fragments()                          # versé dès la fin du script élevé
    assert _data(R)["prior"]["programs"]["reaper"]["version"] == "7.79"


def test_l_etape_source_cree_le_recu_et_verse_le_bootstrap(PW, R, tmp_path, monkeypatch):
    _frag(R, "bootstrap", BOOT)
    target = tmp_path / "golem"
    shutil.copytree(PROV, target / "provision", ignore=shutil.ignore_patterns("windows", "macos", "*.sh"))
    monkeypatch.setattr(PW, "step_source", lambda ctx, src, tgt: 0)
    ctx = SimpleNamespace(S={"dry": False, "src": str(ROOT), "dir": str(target)}, log=lambda *a: None)
    assert PW.run_step("source", ctx) == 0
    d = _data(R)
    assert d["root"] == str(target) and d["prior"]["python"]["installed_by_golem"] is True


# ── provision/desktop.py ────────────────────────────────────────────────────────────────────────
@pytest.fixture
def D(R, tmp_path, monkeypatch):
    """provision.desktop avec le reçu de test, un dossier de ressources REAPER et un %LOCALAPPDATA% temporaires."""
    from provision import desktop
    from bridge import config as C
    monkeypatch.setattr(C, "RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(desktop, "_receipt", lambda: R if R.exists() else None)
    return desktop


def test_configure_ini_note_chaque_cle_ecrite(D, R, tmp_path):
    R.set_root("/x")
    ini = tmp_path / "reaper.ini"
    ini.write_text("[reaper]\nautomute=1\nnorunmute=0\ncsurf_0=Other\ncsurf_cnt=1\n[audioconfig]\nasio_driver=3\n",
                   encoding="latin-1")
    assert D.configure_ini(ini, None, dummy_audio=True, prior=R.prior)
    D.configure_ini(ini, None, dummy_audio=True, prior=R.prior)          # 2e passage : le premier gagne
    ri = _data(R)["prior"]["reaper_ini"]
    assert ri["keys"] == {"verchk": None, "automute": "1", "norunmute": "0"}
    assert ri["csurf_added"] is True and "existed" not in ri
    assert ri["audioconfig"] == {"section_added": False, "keys": {"mode": None}}


def test_configure_ini_sans_fichier(D, R, tmp_path):
    R.set_root("/x")
    D.configure_ini(tmp_path / "new" / "reaper.ini", ("UMC ASIO Driver", 4), prior=R.prior)
    ri = _data(R)["prior"]["reaper_ini"]
    assert ri["existed"] is False
    assert ri["audioconfig"]["section_added"] is True
    assert set(ri["audioconfig"]["keys"]) >= {"mode", "asio_driver", "asio_driver_name"}


def test_setup_note_ce_qu_il_pose(D, R, tmp_path, monkeypatch):
    R.set_root("/x")
    res = tmp_path / "REAPER"
    (res / "Scripts").mkdir(parents=True)
    (res / "Scripts" / "__startup.lua").write_text("-- mon script\n", encoding="utf-8")
    (res / "reaper.ini").write_text("[reaper]\nautomute=1\n", encoding="latin-1")
    venv_py = tmp_path / "venv" / "python"
    venv_py.parent.mkdir()
    venv_py.write_text("")
    monkeypatch.setattr(D, "reaper_running", lambda: False)
    monkeypatch.setattr(D, "resource_dir", lambda: res)
    monkeypatch.setattr(D, "windows_asio_driver", lambda: None)
    monkeypatch.setattr(D, "venv_python", lambda: venv_py)
    monkeypatch.setattr(D, "install_shortcuts", lambda: [])
    monkeypatch.setattr(D.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    D.setup()
    d = _data(R)
    items = {it["path"]: it for it in d["items"]}
    tl = lambda p: R.tilde(str(p))  # noqa: E731
    st = items[tl(res / "Scripts" / "__startup.lua")]
    assert st["prior"] == {"moved_to": tl(res / "Scripts" / "__startup.golem-user.lua")}
    for p in (res / "Scripts" / "golem", res / "Effects" / "golem", res / "OSC" / "golem.ReaperOSC",
              res / "golem-root.txt", res / "golem-runtime.txt", res / "GoleM"):
        assert items[tl(p)]["group"] == "reaper-links", p
        assert items[tl(p)]["by"] == "provision/desktop.py"
    assert items[tl(tmp_path / "local" / "GoleM")]["group"] == "golem"
    assert tl(D.browser_profile()) in items
    assert d["prior"]["reaper_ini"]["keys"]["automute"] == "1"


def test_setup_sans_recu_n_en_cree_pas(D, R, tmp_path, monkeypatch):
    res = tmp_path / "REAPER"
    res.mkdir()
    venv_py = tmp_path / "python"
    venv_py.write_text("")
    for name, val in (("reaper_running", lambda: False), ("resource_dir", lambda: res),
                      ("windows_asio_driver", lambda: None), ("venv_python", lambda: venv_py),
                      ("install_shortcuts", lambda: [])):
        monkeypatch.setattr(D, name, val)
    monkeypatch.setattr(D.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    D.setup()
    assert not R.exists()


def test_python_de_base_pour_le_desinstallateur(D, tmp_path, monkeypatch):
    root = tmp_path / "golem"
    base = tmp_path / "Python312"
    base.mkdir()
    (base / "pythonw.exe").write_text("")
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "pythonw.exe").write_text("")        # celui du venv : jamais
    (root / ".venv" / "pyvenv.cfg").write_text(f"home = {base}\ninclude-system-site-packages = false\n")
    monkeypatch.setattr(sys, "_base_executable", str(root / ".venv" / "Scripts" / "python.exe"), raising=False)
    assert D.base_pythonw(root) == base / "pythonw.exe"
    target, args, workdir = D.uninstall_shortcut(root)
    assert target == base / "pythonw.exe"
    assert args == f'"{root / "installer" / "server.py"}" --uninstall --root "{root}" --open'
    assert workdir == Path.home() and root not in workdir.parents
    (root / ".venv" / "pyvenv.cfg").unlink()                          # sans pyvenv.cfg, et _base_executable du venv
    monkeypatch.setattr(sys, "executable", str(root / ".venv" / "Scripts" / "python.exe"))
    assert D.base_pythonw(root) is None


def test_raccourcis_notes_et_desinstallateur(D, R, tmp_path, monkeypatch):
    R.set_root("/x")
    root = tmp_path / "golem"
    base = tmp_path / "Python312"
    base.mkdir()
    (base / "pythonw.exe").write_text("")
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "pythonw.exe").write_text("")
    (root / ".venv" / "pyvenv.cfg").write_text(f"home = {base}\n")
    monkeypatch.setattr(D, "ROOT", root)
    monkeypatch.setattr(sys, "platform", "win32")
    made = [str(tmp_path / "OneDrive" / "Desktop" / "golem.lnk"),
            str(tmp_path / "Start Menu" / "Programs" / "Uninstall golem.lnk")]
    seen = {}

    def run(cmd, **kw):
        seen["script"] = cmd[-1]
        return SimpleNamespace(returncode=0, stdout="\n".join(made) + "\n", stderr="")
    monkeypatch.setattr(D.subprocess, "run", run)
    assert D.install_shortcuts() == made
    script = seen["script"]
    assert "'Uninstall golem.lnk'" in script
    assert f"$l.TargetPath = '{base / 'pythonw.exe'}'" in script
    assert "--uninstall --root" in script
    assert "GetFolderPath('Programs')" in script and "GetFolderPath('Desktop')" in script
    paths = {it["path"] for it in _data(R)["items"]}
    assert all(R.tilde(p) in paths for p in made)


def test_autostart_note_le_lien(D, R, tmp_path, monkeypatch):
    R.set_root("/x")
    monkeypatch.setattr(sys, "platform", "win32")
    link = tmp_path / "Startup" / "golem server.lnk"
    monkeypatch.setattr(D, "_startup_link", lambda: link)
    monkeypatch.setattr(D.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    D.autostart("on")
    assert any(it["path"] == R.tilde(str(link)) and it["group"] == "golem" for it in _data(R)["items"])


# ── TapeDelay2 et le plan d'alimentation ─────────────────────────────────────────────────────────
def _fake_zip(A, plat, data):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(A.PINS[plat]["member"], data)
    return buf.getvalue()


def test_tapedelay_note_sous_windows_seulement_dans_un_recu_existant(R, tmp_path, monkeypatch):
    import hashlib
    from provision import airwindows as A
    data = b"fake TapeDelay264"
    monkeypatch.setitem(A.PINS["win32"], "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(A, "dest_dir", lambda platform=None: tmp_path / "VST3" / "GoleM")
    A.install("win32", fetch=lambda url: _fake_zip(A, "win32", data), log=lambda *a: None)
    assert not R.exists()                                     # pas de reçu : on n'en crée pas
    (tmp_path / "VST3" / "GoleM" / "TapeDelay264.dll").unlink()
    R.set_root("/x")
    dest = A.install("win32", fetch=lambda url: _fake_zip(A, "win32", data), log=lambda *a: None)
    it = next(i for i in _data(R)["items"] if i["path"] == R.tilde(str(dest)))
    assert it["group"] == "plugins" and it["by"] == "provision/airwindows.py"


def test_le_plan_d_alimentation_d_avant_va_au_recu(monkeypatch, tmp_path):
    from bridge import config as C
    from bridge import desktop_power as P
    from bridge import install_receipt as IR
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    rows = [{"guid": P.BALANCED, "name": "Balanced", "active": True},
            {"guid": P.HIGH_PERF, "name": "High performance", "active": False}]
    monkeypatch.setattr(P, "schemes", lambda: rows)
    monkeypatch.setattr(P, "_powercfg", lambda *a: (0, ""))
    noted = []
    monkeypatch.setattr(IR, "prior", lambda k, v: noted.append((k, v)))
    assert P.set_boost(True)[0]
    assert noted == [("power_scheme", {"guid": P.BALANCED, "name": "Balanced"})]
    assert json.loads((tmp_path / ".power.json").read_text())["before"] == P.BALANCED   # .power.json marche toujours


# ── premier cycle en VM Windows (2026-10-16) : le cache de pip, les dossiers communs des plugins ─────────
def test_setup_note_le_cache_de_pip_avant_le_premier_pip(D, R, tmp_path, monkeypatch):
    R.set_root("/x")
    res = tmp_path / "REAPER"
    res.mkdir()
    venv_py = tmp_path / "venv" / "python"
    venv_py.parent.mkdir()
    venv_py.write_text("")
    for name, val in (("reaper_running", lambda: False), ("resource_dir", lambda: res),
                      ("windows_asio_driver", lambda: None), ("venv_python", lambda: venv_py),
                      ("install_shortcuts", lambda: [])):
        monkeypatch.setattr(D, name, val)
    pip = Path(os.environ["LOCALAPPDATA"]) / "pip"

    def run(argv, *a, **k):
        if "pip" in argv:
            (pip / "cache").mkdir(parents=True, exist_ok=True)       # le pip du venv le crée
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(D.subprocess, "run", run)
    D.setup()
    assert pip.is_dir() and _data(R)["prior"]["pip_cache_existed"] is False
    D.setup()                                                         # un second setup : le premier gagne
    assert _data(R)["prior"]["pip_cache_existed"] is False


def test_bootstrap_note_le_cache_de_pip_et_la_commande_de_python():
    s = PS_BOOT.read_text(encoding="ascii")
    # noté AVANT de poser Python (et bien avant tout pip)
    assert s.index("$pipCacheExisted = ") < s.index("Start-Process $pyExe")
    assert "'pip_cache_existed' = $pipCacheExisted" in s
    # la commande du BUNDLE Python (HKCU, QuietUninstallString), seulement quand le bootstrap l'a posé
    blk = s[s.index("if ($pythonByGolem) {", s.index("2 bis")):]
    assert "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall" in blk
    assert "QuietUninstallString" in blk and "SystemComponent -ne 1" in blk and "$prior['python.uninstall']" in blk


def test_script_eleve_note_les_dossiers_communs_avant_tout_composant():
    s = _ps(PS_SYSTEM)
    i = s.index('Rcpt-Prior "common_dirs.$k"')
    assert "foreach ($k in 'VST3', 'LV2', 'CLAP')" in s and "Join-Path $env:CommonProgramFiles $k" in s
    assert i < s.index("try {\n    # ── RETOUR") and i < s.index('Install $ri @(\'/S\', "/D=$rdir")')
