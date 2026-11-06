#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""La désinstallation de golem SOUS WINDOWS (docs/uninstall.md §9.3) — la couche Windows du moteur
provision/uninstall.py : même CLI (`plan` / `run`), même modèle de plan (id, groupe, libellé, chemins, privilège,
origine, défaut, raison, action), même journal JSON ({"step", "item", "ok", "msg"}). Bibliothèque standard
SEULEMENT : elle tourne avec le Python de base, depuis la copie du désinstallateur dans %TEMP%.

Ce qui change par rapport à Linux :
  · les chemins viennent de l'ENVIRONNEMENT (%APPDATA%, %LOCALAPPDATA%, %ProgramData%, %ProgramFiles%,
    %CommonProgramFiles%, %USERPROFILE%, %TEMP%) — jamais un C:\\ écrit en dur ;
  · « root » devient « admin » : UNE passe élevée (UAC, `Start-Process -Verb RunAs`, installer/elevate_win.py — le
    même mécanisme que l'installateur), un script PowerShell généré pour tous les éléments d'administrateur : règles
    du pare-feu de golem retirées, règles supprimées à l'installation recréées (prior.firewall_deleted),
    %ProgramData%\\GoleM, « REAPER (x64).golem-prev », et les PROGRAMMES tiers par le désinstalleur de LEUR éditeur
    (la commande notée dans le reçu, prior.programs.<id>.uninstall) ;
  · l'arrêt : `python -m provision.desktop stop`, puis les fenêtres de golem fermées ; un REAPER de golem encore
    ouvert = refus, rien n'est touché ;
  · le runtime Visual C++ n'est jamais proposé (la base du système, comme NEVER_APT sous Linux) ; Python (posé par le
    bootstrap) est proposé décoché, et sa désinstallation part APRÈS la fermeture du désinstallateur, qui tourne
    dessus — par un VEILLEUR créé par WMI (installer/after_exit_win.py), qui efface aussi la copie du
    désinstallateur ; ses règles du pare-feu partent dans la passe élevée ;
  · d'après le premier cycle en VM (docs/uninstall.md §9.8) : une règle « golem* » n'est cochée que si golem l'a faite
    (reçu, noms fixes) ; le cache de pip et les dossiers communs des plugins (Common Files\\VST3|LV2|CLAP) nés de golem
    sont proposés d'après le reçu.

Les tests remplacent `run_command` (toute commande), `elevate` (la passe élevée), `uninstall_entries` (le registre)
et `schedule_after_exit` (le désinstalleur de Python) ; les chemins viennent de l'environnement — un faux arbre.
"""
import argparse
import datetime
import fnmatch
import glob
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

if __name__.startswith("provision."):
    from provision import uninstall as U
else:                                   # chargé par uninstall.py (sa copie dans %TEMP%) : le moteur commun est là
    import uninstall as U

UninstallError = U.UninstallError
Reporter = U.Reporter
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

GROUPS = ("golem", "reaper-links", "reaper-ini", "system", "programs", "plugins", "reaper", "toolchain")
RECEIPT_NAME = "install-receipt.json"
STARTUP_HOOK = "-- GoleM desktop startup hook"          # la 1re ligne du __startup.lua de golem (provision/desktop.py)

# les règles du pare-feu que provision/windows/install-system.ps1 crée (et ses anciens noms). Une règle n'est COCHÉE
# que si son nom est ici ou dans le reçu (firewall.added) : un nom qui commence par « golem » ne suffit pas — la VM de
# test avait sa propre règle « GoleM sshd », que le premier passage a supprimée (2026-10-16, SSH perdu). Les autres
# règles « golem* » sont listées DÉCOCHÉES, d'origine inconnue
FIREWALL_FIXED = ("GoleM - Reaper, no inbound network", "GoleM - bridge", "GoleM - bridge, private networks",
                  "GoleM - bridge, mobile hotspot", "GoleM - golem.local (mDNS)")

# les programmes tiers que l'installation peut poser, chacun par l'installeur de son éditeur (§9.3, groupe programs) :
# (id du reçu, libellé, famille d'installeur, sondes (variable, chemin relatif), motifs du DisplayName de Windows,
#  coché par défaut quand golem l'a installé, raison)
PROGRAMS = (
    ("reaper", "REAPER", "nsis", (("ProgramFiles", "REAPER (x64)"),), ("REAPER*",), False,
     "golem installed it; you may want to keep it (your settings folder is a separate choice)"),
    ("nam_vst3", "Neural Amp Modeler (VST3)", "inno", (("CommonProgramFiles", "VST3/NeuralAmpModeler.vst3"),),
     ("*Neural*Amp*Modeler*",), True, "the amp and cab plugin golem installed; another audio program may use it"),
    ("avldrums", "AVL Drumkits", "nsis", (("CommonProgramFiles", "LV2/avldrums.lv2"), ("ProgramFiles", "LV2/avldrums.lv2"),
                                          ("APPDATA", "LV2/avldrums.lv2")),
     ("*avl*drum*",), True, "the drum kit plugin golem installed; another audio program may use it"),
    ("sfizz", "sfizz", "inno", (("CommonProgramFiles", "LV2/sfizz.lv2"), ("CommonProgramFiles", "VST3/sfizz.vst3"),
                                ("ProgramFiles", "LV2/sfizz.lv2")),
     ("*sfizz*",), True, "the SFZ sampler golem installed; another audio program may use it"),
    ("pawpaw", "PawPaw plugins (Vitalium)", "inno", (("CommonProgramFiles", "LV2/vitalium.lv2"),
                                                     ("ProgramFiles", "LV2/vitalium.lv2"), ("APPDATA", "LV2/vitalium.lv2")),
     ("*PawPaw*",), True, "golem installed PawPaw for Vitalium; its uninstaller removes ALL the PawPaw plugins, "
                          "not only Vitalium"),
    # le bloc Boost (install-system.ps1 -Proteus, 2026-10-22) : l'installation le notait au reçu, mais il manquait
    # ICI — la désinstallation ne le proposait jamais et le laissait dans Program Files (VM 2026-10-24)
    ("proteus", "Proteus (the Boost block)", "inno", (("CommonProgramFiles", "VST3/Proteus.vst3"),),
     ("Proteus*",), True, "the Boost block plugin golem installed; another audio program may use it"),
)
PROGRAM_ALIASES = {"nam": "nam_vst3", "vitalium": "pawpaw"}
# les dossiers communs des plugins sous %CommonProgramFiles% (prior.common_dirs : existaient-ils avant golem ?)
COMMON_DIRS = ("VST3", "LV2", "CLAP")
# le commutateur silencieux de chaque famille, quand la commande du reçu ne l'a pas (le reçu l'ajoute déjà, §9.2)
SILENT = {"nsis": ["/S"], "inno": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], "burn": ["/quiet", "/norestart"],
          "msi": ["/qn", "/norestart"]}
# JAMAIS proposé (la base du système, comme NEVER_APT) — même si le reçu dit que golem l'a installé
NEVER = ("Microsoft Visual C++ runtime (x64)",)
NEVER_PATTERNS = ("Microsoft Visual C++ * Redistributable*", "Microsoft Visual C++ 20* Runtime*")
PYTHON_PATTERNS = ("Python 3.* (64-bit)", "Python 3.*")
# ce que le désinstallateur ne PEUT PAS savoir (§9.7) : dit sur l'écran Done, jamais supprimé
CHECK_YOURSELF = (
    "Wi-Fi profiles golem may have added: Windows Settings ▸ Network & internet ▸ Wi-Fi ▸ Manage known networks",
    "The mobile hotspot name and password, if golem set them: Windows Settings ▸ Network & internet ▸ Mobile hotspot",
)
POWER_BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
GUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


# ── le contexte : les dossiers de CETTE session Windows, lus dans l'environnement ──────────────────────
def _env(env, *names):
    for n in names:
        v = env.get(n) or env.get(n.upper())
        if v:
            return v
    return None


def _shell_folder(csidl):
    """Un dossier du shell (Bureau, menu Démarrer, Démarrage) tel que Windows le DIT — redirigé (OneDrive) compris.
    None hors de Windows."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return None


class WinCtx:
    def __init__(self, root=None, receipt=None, env=None):
        e = os.environ if env is None else env
        self.fsroot = ""
        self.home = os.path.normpath(_env(e, "USERPROFILE") or os.path.expanduser("~"))
        self.appdata = os.path.normpath(_env(e, "APPDATA") or os.path.join(self.home, "AppData", "Roaming"))
        self.localappdata = os.path.normpath(_env(e, "LOCALAPPDATA") or os.path.join(self.home, "AppData", "Local"))
        self.temp = os.path.normpath(_env(e, "TEMP", "TMP") or os.path.join(self.localappdata, "Temp"))
        pd = _env(e, "ProgramData", "ALLUSERSPROFILE")
        pf = _env(e, "ProgramFiles", "ProgramW6432")
        cf = _env(e, "CommonProgramFiles", "CommonProgramW6432")
        self.programdata = os.path.normpath(pd) if pd else None
        self.programfiles = os.path.normpath(pf) if pf else None
        self.commonfiles = os.path.normpath(cf) if cf else None
        x86 = _env(e, "ProgramFiles(x86)")
        self.programfiles_x86 = os.path.normpath(x86) if x86 else None
        sr = _env(e, "SystemRoot", "windir")
        self.systemroot = os.path.normpath(sr) if sr else None
        self.vars = {"USERPROFILE": self.home, "APPDATA": self.appdata, "LOCALAPPDATA": self.localappdata,
                     "TEMP": self.temp, "PROGRAMDATA": self.programdata, "PROGRAMFILES": self.programfiles,
                     "COMMONPROGRAMFILES": self.commonfiles}
        self.desktop = os.path.normpath(_shell_folder(0x10) or os.path.join(self.home, "Desktop"))
        self.programs = os.path.normpath(_shell_folder(0x02) or os.path.join(
            self.appdata, "Microsoft", "Windows", "Start Menu", "Programs"))
        self.startup = os.path.normpath(_shell_folder(0x07) or os.path.join(self.programs, "Startup"))
        self.reaper_dir = os.path.join(self.appdata, "REAPER")
        self.data_dir = os.path.join(self.localappdata, "GoleM")
        self.root_arg = root
        self.user = _env(e, "USERNAME") or os.path.basename(self.home)
        self.receipt_path = receipt or _env(e, "GOLEM_RECEIPT") or os.path.join(self.data_dir, RECEIPT_NAME)

    def expand(self, p):
        """Un chemin du reçu -> le chemin réel : `%VAR%\\…` (provision/receipt.py, win_relative), `~`, ou absolu."""
        p = str(p or "")
        m = re.match(r"^%([A-Za-z0-9_()]+)%(.*)$", p)
        if m:
            base = self.vars.get(m.group(1).upper())
            if base:
                rest = m.group(2).lstrip("\\/")
                p = os.path.join(base, *re.split(r"[\\/]+", rest)) if rest else base
        elif p == "~" or p.startswith(("~/", "~\\")):
            rest = p[2:]
            p = os.path.join(self.home, *re.split(r"[\\/]+", rest)) if rest else self.home
        return os.path.normpath(p) if p else p

    def tilde(self, p):
        return p

    def exists(self, p):
        return os.path.lexists(p)


def _nc(p):
    return os.path.normcase(os.path.normpath(p)) if p else ""


def _inside(p, root):
    if not p or not root:
        return False
    a, b = _nc(p), _nc(root).rstrip("\\/")
    return a == b or a.startswith(b + os.sep)


def _same(a, b):
    return bool(a) and bool(b) and _nc(a) == _nc(b)


# ── LE runner : toute commande passe par ici (les tests le remplacent) ────────────────────────────────
def _default_runner(ctx, argv, env=None, timeout=900, cwd=None):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           timeout=timeout, stdin=subprocess.DEVNULL, cwd=cwd, creationflags=NO_WINDOW)
    except FileNotFoundError:
        return 127, "%s: not found" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "%s: timed out" % argv[0]
    except OSError as e:
        return 126, "%s: %s" % (argv[0], e)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


run_command = _default_runner


def _ps(ctx, script, timeout=60):
    """Une LECTURE PowerShell (pare-feu, processus, plan d'alimentation) : (code, sortie)."""
    return run_command(ctx, ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + script], timeout=timeout)


def _q(s):
    """Une chaîne PowerShell entre apostrophes."""
    return "'" + str(s).replace("'", "''") + "'"


def firewall_rules(ctx):
    """Les noms des règles du pare-feu qui portent le nom de golem ; None si on ne peut pas lire (on le dira). Porter
    ce nom ne suffit pas à être à golem : build_plan ne coche que les noms du reçu et FIREWALL_FIXED."""
    rc, out = _ps(ctx, "Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like "
                       "'golem*' } | ForEach-Object { $_.DisplayName }", timeout=120)
    if rc != 0:
        return None
    return sorted({ln.strip() for ln in out.splitlines() if ln.strip()})


def active_scheme(ctx):
    rc, out = run_command(ctx, ["powercfg", "/getactivescheme"], timeout=20)
    m = GUID_RE.search(out or "") if rc == 0 else None
    return m.group(0).lower() if m else None


def processes(ctx, names):
    """[(pid, nom, ligne de commande)] des processus nommés ; None si on ne peut pas lire."""
    flt = " or ".join("Name='%s'" % n for n in names)
    rc, out = _ps(ctx, "Get-CimInstance Win32_Process -Filter \"%s\" | ForEach-Object { \"$($_.ProcessId)`t$($_.Name)"
                       "`t$($_.CommandLine)\" }" % flt, timeout=60)
    if rc != 0:
        return None
    rows = []
    for ln in out.splitlines():
        parts = ln.split("\t", 2)
        if len(parts) >= 2 and parts[0].strip().isdigit():
            rows.append((int(parts[0]), parts[1].strip(), parts[2] if len(parts) > 2 else ""))
    return rows


def uninstall_entries():
    """Les clés « Uninstall » de Windows (HKLM 64/32 bits, HKCU) : [{name, uninstall, quiet, location, key}]. Lecture
    seule ; [] hors de Windows. Sert quand le reçu n'a pas la commande (sans reçu, ou reçu partiel)."""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    roots = ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "HKLM32"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "HKCU"))
    for hive, path, tag in roots:
        try:
            k = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as s:
                        def val(n):
                            try:
                                return str(winreg.QueryValueEx(s, n)[0])
                            except OSError:
                                return ""
                        name = val("DisplayName")
                        if name:
                            out.append({"name": name, "uninstall": val("UninstallString"),
                                        "quiet": val("QuietUninstallString"), "location": val("InstallLocation"),
                                        "key": "%s\\%s" % (tag, sub), "system": val("SystemComponent") == "1"})
                except OSError:
                    continue
    return out


def _entry(patterns, entries):
    for e in entries:
        if any(fnmatch.fnmatch(e["name"].lower(), p.lower()) for p in patterns):
            return e
    return None


def python_entry(entries, version=None):
    """La clé « Uninstall » du BUNDLE Python (« Python 3.12.10 (64-bit) », HKCU pour une install par utilisateur, avec
    sa QuietUninstallString « "…\\Package Cache\\{guid}\\python-3.12.10-amd64.exe" /uninstall /quiet ») — jamais
    un de ses MSI (« Python 3.12.10 Core Interpreter (64-bit) », SystemComponent=1) : en retirer un casserait Python
    sans le désinstaller. None si rien ne correspond."""
    mm = ".".join(str(version or "3").split(".")[:2])
    bundle = re.compile(r"^python \d+\.\d+\.\d+ \((64|32)-bit\)$", re.I)
    cands = [e for e in entries if not e.get("system") and (e.get("quiet") or e.get("uninstall"))
             and any(fnmatch.fnmatch(e["name"].lower(), p.lower()) for p in ("Python %s.*" % mm,) + PYTHON_PATTERNS)]
    if not cands:
        return None

    def rank(e):
        n = e["name"]
        return (not bundle.match(n), not (version and str(version) in n), not n.lower().startswith("python %s." % mm),
                not e.get("quiet"), not str(e.get("key") or "").startswith("HKCU"))
    return sorted(cands, key=rank)[0]


def python_dir(ctx, py):
    """Le dossier du Python de prior.python (son `path` est l'exécutable ou le dossier)."""
    ppath = ctx.expand((py or {}).get("path") or "")
    return os.path.dirname(ppath) if ppath.lower().endswith(".exe") else ppath


def python_exes(ctx, py):
    """Les programmes de ce Python que Windows vise dans ses règles du pare-feu (python.exe, pythonw.exe), en
    minuscules : les règles se comparent sans casse."""
    d = python_dir(ctx, py)
    return [os.path.normpath(os.path.join(d, n)).lower() for n in ("python.exe", "pythonw.exe")] if d else []


def _rule_program(r):
    p = str(r.get("program") or r.get("Program") or "").strip().strip('"')
    return os.path.normpath(p).lower() if p else ""


# ── la commande d'un désinstalleur d'éditeur ──────────────────────────────────────────────────────────
def split_command(cmd):
    """« "C:\\Program Files\\X\\unins000.exe" /SILENT » ou « C:\\Program Files\\REAPER (x64)\\Uninstall.exe /S »
    (une UninstallString NON citée, espaces compris) -> (exe, [args]). Rend (None, []) si on ne sait pas lire."""
    if isinstance(cmd, dict):
        exe = cmd.get("exe") or cmd.get("path")
        args = cmd.get("args") or []
        return (str(exe) if exe else None), ([str(a) for a in args] if isinstance(args, list) else shlex.split(str(args), posix=False))
    s = str(cmd or "").strip()
    if not s:
        return None, []
    if s.startswith('"'):
        end = s.find('"', 1)
        if end < 0:
            return None, []
        exe, rest = s[1:end], s[end + 1:]
    else:
        m = re.match(r"^(.+?\.exe)(?=\s|$)(.*)$", s, re.I)
        if not m:
            return None, []
        exe, rest = m.group(1), m.group(2)
    args = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in shlex.split(rest, posix=False)]
    return exe.strip(), args


def _with_silent(exe, args, family):
    low = [a.lower() for a in args]
    if os.path.basename(exe).lower() == "msiexec.exe":
        family = "msi"
    want = SILENT.get(family) or []
    if family == "inno" and any(a in low for a in ("/silent", "/verysilent")):
        return args
    if family == "msi" and any(a in low for a in ("/qn", "/quiet", "/passive")):
        return args
    return args + [w for w in want if w.lower() not in low]


# ── la sécurité des chemins ──────────────────────────────────────────────────────────────────────────
def _forbidden_set(ctx):
    base = [ctx.home, ctx.appdata, ctx.localappdata, ctx.temp, ctx.programdata, ctx.programfiles, ctx.commonfiles,
            ctx.programfiles_x86, ctx.systemroot, ctx.desktop, ctx.programs, ctx.startup,
            os.path.dirname(ctx.programs), os.path.join(ctx.localappdata, "Programs"),
            os.path.join(ctx.localappdata, "Programs", "Common"), os.path.join(ctx.localappdata, "Programs", "Common", "VST3"),
            os.path.join(ctx.appdata, "Microsoft"), os.path.join(ctx.localappdata, "Microsoft")]
    base += [os.path.join(ctx.home, d) for d in ("Documents", "Music", "Downloads", "Desktop", "Pictures", "Videos",
                                                 "AppData", "OneDrive")]
    base += [os.path.join(ctx.reaper_dir, d) for d in ("Scripts", "Effects", "OSC", "UserPlugins", "FXChains")]
    if ctx.commonfiles:
        base += [os.path.join(ctx.commonfiles, d) for d in ("VST3", "LV2", "CLAP")]
    if ctx.programfiles:
        base += [os.path.join(ctx.programfiles, d) for d in ("VST3", "LV2", "Common Files")]
    return {_nc(b) for b in base if b}


def forbidden(ctx, p):
    if not p or not os.path.isabs(p):
        return True
    p = os.path.normpath(p)
    if _nc(p) in _forbidden_set(ctx):
        return True
    if os.path.dirname(p) == p or _inside(ctx.home, p):            # une racine de lecteur, $HOME ou un ancêtre
        return True
    return False


def _golem_lnk(p):
    n = os.path.basename(p).lower()
    return n.endswith(".lnk") and "golem" in n


def expected(ctx, p, root=None, rpaths=()):
    """Ce chemin est-il un de ceux que golem a posés (calculé ICI, jamais lu dans une sélection) ?"""
    if forbidden(ctx, p):
        return False
    name = os.path.basename(p).lower()
    if root and _inside(p, root):
        return True
    for base in (ctx.data_dir, os.path.join(ctx.localappdata, "golem-installer"), ctx.reaper_dir,
                 os.path.join(ctx.localappdata, "Programs", "Common", "VST3", "GoleM"), os.path.join(ctx.home, "golem-inbox")):
        if _inside(p, base):
            return True
    if _same(os.path.dirname(p), ctx.temp) and name.startswith("golem-"):
        return True
    if any(_same(os.path.dirname(p), d) for d in (ctx.desktop, ctx.programs, ctx.startup)) and _golem_lnk(p):
        return True
    if ctx.programdata and _inside(p, os.path.join(ctx.programdata, "GoleM")):
        return True
    if ctx.programfiles and _same(p, os.path.join(ctx.programfiles, "REAPER (x64).golem-prev")):
        return True
    if any(_same(p, r) for r in rpaths):
        # un chemin du reçu : dans le profil, jamais un enfant direct du profil
        return _inside(p, ctx.home) and not _same(os.path.dirname(p), ctx.home)
    return False


def _rmtree(p):
    """rmtree qui passe les fichiers en LECTURE SEULE (les objets de .git le sont sous Windows : sans ça, le dossier
    d'install ne part pas). Ne suit aucun lien ni jonction."""
    def fix(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            raise
    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=fix)
    else:
        shutil.rmtree(p, onerror=fix)


def _is_link(p):
    return os.path.islink(p) or bool(getattr(os.path, "isjunction", lambda _p: False)(p))


def safe_remove(ctx, p, root=None, rpaths=()):
    p = os.path.normpath(p)
    if not expected(ctx, p, root, rpaths):
        raise UninstallError("refused: %s is not in the expected set" % p)
    if not os.path.lexists(p):
        return "already absent"
    if _is_link(p):
        try:
            os.unlink(p)
        except OSError:
            os.rmdir(p)                                            # une jonction se retire comme un dossier vide
        return "link removed"
    if os.path.isdir(p):
        _rmtree(p)
        return "folder removed"
    try:
        os.unlink(p)
    except PermissionError:
        os.chmod(p, stat.S_IWRITE)
        os.unlink(p)
    return "file removed"


def _remove_empty_tree(ctx, p, root=None):
    """Retire `p` s'il ne contient QUE des dossiers vides — pour un dossier hors de l'ensemble attendu."""
    if forbidden(ctx, p) or (root and (_inside(root, p) or _inside(p, root))):
        raise UninstallError("refused: %s" % p)
    if _is_link(p):
        raise UninstallError("refused: %s is a link" % p)
    if not os.path.isdir(p):
        return "already absent"
    dirs = []
    for r, ds, fs in os.walk(p):
        if fs:
            raise UninstallError("%s holds files: left as is" % p)
        dirs.append(r)
    for d in sorted(dirs, key=len, reverse=True):
        os.rmdir(d)
    return "empty folder removed"


def _count_files(p):
    return sum(len(fs) for _r, _ds, fs in os.walk(p))


# ── le reçu ──────────────────────────────────────────────────────────────────────────────────────────
def _dotted(d, key):
    cur = d
    for k in key.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _programs_prior(prior):
    """prior.programs.<id> (provision/windows/install-system.ps1, §9.2) ; aussi prior.components (ancien nom)."""
    out = {}
    for key in ("components", "programs"):
        for k, v in (prior.get(key) or {}).items() if isinstance(prior.get(key), dict) else ():
            if isinstance(v, dict):
                out[PROGRAM_ALIASES.get(k, k)] = dict(v)
    rp = prior.get("reaper")
    if isinstance(rp, dict) and rp.get("installed_by_golem") is not None:
        r = out.setdefault("reaper", {})
        for k in ("installed_by_golem", "uninstall", "path", "version"):
            if rp.get(k) is not None and r.get(k) is None:
                r[k] = rp[k]
    return out


def _installed_by_golem(c):
    if not isinstance(c, dict):
        return None
    if c.get("installed_by_golem") is not None:
        return bool(c["installed_by_golem"])
    if c.get("state") in ("installed", "existed"):
        return c["state"] == "installed"
    if c.get("installed") is not None:
        return bool(c["installed"])
    if c.get("existed") is not None:
        return not c["existed"]
    return None


def _firewall_receipt(receipt):
    """(noms créés, règles supprimées à recréer) d'après le reçu."""
    fw = receipt.get("firewall") if isinstance(receipt.get("firewall"), dict) else {}
    prior = receipt.get("prior") or {}
    added = [str(x) for x in (fw.get("added") or []) if isinstance(x, str)]
    added += [str(x) for x in (prior.get("firewall_created") or []) if isinstance(x, str)]
    deleted = [r for r in (prior.get("firewall_deleted") or fw.get("deleted") or []) if isinstance(r, dict)]
    return list(dict.fromkeys(added)), deleted


def _power_prior(ctx, receipt, root):
    """(GUID, d'où il vient) du plan d'alimentation d'avant golem : prior.power_scheme du reçu, sinon
    config\\.power.json (bridge/desktop_power.py)."""
    ps = ((receipt or {}).get("prior") or {}).get("power_scheme")
    if isinstance(ps, dict):
        ps = ps.get("guid") or ps.get("before")
    if isinstance(ps, str) and GUID_RE.fullmatch(ps.strip()):
        return ps.strip().lower(), "receipt"
    if root:
        try:
            with open(os.path.join(root, "config", ".power.json"), encoding="utf-8") as f:
                b = (json.load(f) or {}).get("before")
            if isinstance(b, str) and GUID_RE.fullmatch(b.strip()):
                return b.strip().lower(), "golem-named"
        except (OSError, ValueError, AttributeError):
            pass
    return None, None


def _receipt_mod():
    """provision/receipt.py, chargé à côté de ce fichier (la copie du désinstallateur l'emporte) ; None s'il manque."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location(
            "golem_receipt_u", os.path.join(os.path.dirname(os.path.abspath(__file__)), "receipt.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


def load_receipt(ctx):
    """(reçu | None, avertissement | None) — par receipt.load(), qui VERSE EN MÉMOIRE les fragments en attente
    (<reçu>.pending-*.json : le bootstrap, le script élevé — §9.2) sans rien écrire. Pas de fichier = pas de reçu."""
    if not os.path.isfile(ctx.receipt_path):
        return None, None
    R = _receipt_mod()
    if R is not None and hasattr(R, "load"):
        old = os.environ.get("GOLEM_RECEIPT")
        os.environ["GOLEM_RECEIPT"] = ctx.receipt_path
        try:
            r = R.load()
            if isinstance(r, dict):
                return r, None
        except Exception:
            pass
        finally:
            if old is None:
                os.environ.pop("GOLEM_RECEIPT", None)
            else:
                os.environ["GOLEM_RECEIPT"] = old
    return U.load_receipt(ctx)


# ── reaper.ini : la section [audioconfig] (Windows seulement) ────────────────────────────────────────
def audioconfig_revert(text, spec):
    """prior.reaper_ini.audioconfig = {section_added, keys: {clé: valeur d'avant | None}} (provision/desktop.py,
    configure_ini) -> (texte, [changements]). section_added : golem a créé la section, elle part entière ; sinon
    chaque clé reprend sa valeur d'avant (None = elle n'existait pas : retirée). Fonction PURE ; CRLF gardé."""
    if not isinstance(spec, dict):
        return text, []
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower() == "[audioconfig]"), None)
    if start is None:
        return text, []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    changes = []
    if spec.get("section_added"):
        out = lines[:start] + lines[end:]
        changes.append("[audioconfig] removed (golem added it)")
    else:
        sec = lines[start + 1:end]
        for k, v in (spec.get("keys") or {}).items():
            idx = [i for i, ln in enumerate(sec) if "=" in ln and ln.split("=", 1)[0].strip() == k]
            if v is None:
                if idx:
                    sec = [ln for i, ln in enumerate(sec) if i not in idx]
                    changes.append("audio %s removed" % k)
            else:
                want = "%s=%s" % (k, v)
                if idx and any(sec[i] != want for i in idx):
                    sec[idx[0]] = want
                    sec = [ln for i, ln in enumerate(sec) if i not in idx[1:]]
                    changes.append("audio %s set back" % k)
                elif not idx:
                    sec.append(want)
                    changes.append("audio %s set back" % k)
        out = lines[:start + 1] + sec + lines[end:]
    if not changes:
        return text, []
    return nl.join(out) + (nl if text.endswith("\n") else ""), changes


def _ini_new(text, keys, csurf, audio):
    new, ch = U.ini_revert(text, keys, csurf)
    new, ch2 = audioconfig_revert(new, audio)
    return new, ch + ch2


def revert_ini(path, keys, csurf, audio):
    with open(path, encoding="latin-1", newline="") as f:
        text = f.read()
    new, changes = _ini_new(text, keys, csurf, audio)
    if not changes:
        return "nothing to change"
    shutil.copy2(path, path + ".golem-uninstall")
    fd, tmp = tempfile.mkstemp(prefix=".reaper.ini.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="latin-1", newline="") as f:
            f.write(new)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return "; ".join(changes) + " (copy kept as reaper.ini.golem-uninstall)"


# ── LE PLAN ──────────────────────────────────────────────────────────────────────────────────────────
def _looks_like_install(root):
    return bool(root) and os.path.isfile(os.path.join(root, "provision", "desktop.py")) \
        and os.path.isdir(os.path.join(root, "bridge"))


def find_install_root(ctx, receipt):
    cands = []
    if ctx.root_arg:
        cands.append(os.path.abspath(os.path.expanduser(ctx.root_arg)))
    if receipt and receipt.get("root"):
        cands.append(ctx.expand(receipt["root"]))
    cands.append(os.path.join(ctx.home, "golem"))
    for c in cands:
        if _looks_like_install(c) and not forbidden(ctx, c):
            return os.path.normpath(c)
    return None


def _item(*a, **kw):
    return U._item(*a, **kw)


def _inbox_item(ctx, root):
    path, custom = os.path.join(ctx.home, "golem-inbox"), False
    if root:
        try:
            with open(os.path.join(root, "config", "inbox.json"), encoding="utf-8") as f:
                d = (json.load(f) or {}).get("dir")
            if isinstance(d, str) and d.strip():
                d = ctx.expand(d.strip())
                if os.path.isabs(d):
                    path, custom = d, not _same(d, os.path.join(ctx.home, "golem-inbox"))
        except (OSError, ValueError, AttributeError):
            pass
    if not os.path.isdir(path) or forbidden(ctx, path) or (root and (_inside(path, root) or _inside(root, path))):
        return None
    n = _count_files(path)
    what = "the folder golem watches for shared songs (.golem files)"
    reason = ("%s; it holds %d file%s (yours, or songs golem filed in .imported/.refused): it stays — delete it "
              "yourself once you have what you need" % (what, n, "" if n == 1 else "s")) if n else "%s; it is empty" % what
    return _item("golem:inbox", "golem", "Song inbox folder", [path], "user", "golem-named", n == 0, reason, "remove",
                 _paths=[path], _inbox_custom=custom)


def build_plan(ctx):
    receipt, warn = load_receipt(ctx)
    mode = "receipt" if receipt is not None else "no-receipt"
    root = find_install_root(ctx, receipt)
    prior = (receipt or {}).get("prior") or {}
    items, absent, warnings = [], [], [w for w in (warn,) if w]
    ritems = [r for r in ((receipt or {}).get("items") or []) if isinstance(r, dict) and r.get("path")]
    by_path = {_nc(ctx.expand(r["path"])): r for r in ritems}
    rpaths = [ctx.expand(r["path"]) for r in ritems]
    used = set()

    def origin_of(paths, named=True):
        hit = [by_path[_nc(p)] for p in paths if _nc(p) in by_path]
        used.update(_nc(p) for p in paths if _nc(p) in by_path)
        if hit:
            return "receipt", [h.get("id") for h in hit if h.get("id")]
        return ("golem-named" if named else "unknown"), []

    def add(it):
        if any(x["id"] == it["id"] for x in items):
            return
        for r in it.get("_rids") or []:
            rec = next((x for x in ritems if x.get("id") == r), None)
            pr = (rec or {}).get("prior")
            if (isinstance(pr, dict) and pr.get("existed")) or (rec or {}).get("existed"):
                it["default"], it["reason"] = False, "already here before golem"
        items.append(it)

    # ── golem ──
    if root:
        o, rid = origin_of([root])
        add(_item("golem:install-folder", "golem", "golem install folder", [root], "user", o, True,
                  "the application itself: code, settings, presets and local backups (back them up first)",
                  "remove", _paths=[root], _rids=rid, _step="folder"))
    else:
        warnings.append("no golem install folder found (looked at --root, the receipt, %s)"
                        % os.path.join(ctx.home, "golem"))
    if os.path.isdir(ctx.data_dir):
        inner = [n for n in os.listdir(ctx.data_dir) if not n.startswith(RECEIPT_NAME)]
        if inner:
            _o, rid = origin_of([ctx.data_dir] + [ctx.expand(r["path"]) for r in ritems
                                                  if _inside(ctx.expand(r["path"]), ctx.data_dir)])
            add(_item("golem:local-data", "golem", "golem data folder (browser profiles, runtime, captures)",
                      [ctx.data_dir], "user", "golem-named", True,
                      "golem's own data: its window profiles, runtime files, NAM training environment and capture "
                      "work (the backup carries the captures)", "remove", _paths=[ctx.data_dir], _keep_receipt=True,
                      _rids=rid))
    cache = os.path.join(ctx.localappdata, "golem-installer")
    if os.path.lexists(cache):
        o, rid = origin_of([cache])
        add(_item("golem:installer-cache", "golem", "Installer cache", [cache], "user", o, True,
                  "what the bootstrap downloaded", "remove", _paths=[cache], _rids=rid))
    tmp = sorted(p for p in glob.glob(os.path.join(ctx.temp, "golem-*"))
                 if not os.path.basename(p).lower().startswith("golem-uninstall"))
    if tmp:
        add(_item("golem:tmp", "golem", "Temporary files and logs", tmp, "user", "golem-named", True,
                  "install logs and leftovers in %TEMP%", "remove", _paths=tmp))
    inbox = _inbox_item(ctx, root)
    if inbox:
        add(inbox)
    for where, folder in (("Desktop", ctx.desktop), ("Start menu", ctx.programs)):
        for p in sorted(glob.glob(os.path.join(folder, "*.lnk"))):
            if _golem_lnk(p):
                o, rid = origin_of([p])
                add(_item("golem:shortcut:%s/%s" % ("Desktop" if where == "Desktop" else "Programs", os.path.basename(p)),
                          "golem", "%s shortcut (%s)" % (where, os.path.basename(p)[:-4]), [p], "user", o, True,
                          "a golem shortcut", "remove", _paths=[p], _rids=rid))
    starts = [p for p in sorted(glob.glob(os.path.join(ctx.startup, "*.lnk"))) if _golem_lnk(p)]
    if starts:
        o, rid = origin_of(starts)
        add(_item("golem:autostart", "golem", "Start golem server when you sign in", starts, "user", o, True,
                  "autostart turned off: golem no longer starts with your session", "remove", _paths=starts, _rids=rid))
    guid, src = _power_prior(ctx, receipt, root)
    if guid:
        cur = active_scheme(ctx)
        if cur != guid:
            add(_item("golem:power-plan", "golem", "Power plan", [], "user", "receipt" if src == "receipt" else "golem-named",
                      True, "set back to the plan that was active before golem (%s)" % guid, "revert", _guid=guid,
                      _prior_keys=["power_scheme"] if src == "receipt" else []))
        elif src == "receipt":
            absent.append("prior:power_scheme")

    # ── reaper-links (copiés dans le dossier de ressources de REAPER, pas des liens) ──
    rdir = ctx.reaper_dir
    for rel, label in (("Scripts/golem", "golem's REAPER scripts"), ("Effects/golem", "golem's JSFX effects"),
                       ("OSC/golem.ReaperOSC", "golem's OSC pattern"), ("golem-root.txt", "where golem lives"),
                       ("golem-runtime.txt", "golem's runtime folder"), ("GoleM", "golem's logs and lock in REAPER")):
        p = os.path.join(rdir, *rel.split("/"))
        if os.path.lexists(p):
            o, rid = origin_of([p])
            add(_item("reaper-links:%s" % rel, "reaper-links", "REAPER: %s" % rel, [p], "user", o, True, label, "remove",
                      _paths=[p], _rids=rid))
    st = os.path.join(rdir, "Scripts", "__startup.lua")
    if os.path.isfile(st):
        try:
            with open(st, encoding="utf-8", errors="replace") as f:
                ours = f.readline().startswith(STARTUP_HOOK)
        except OSError:
            ours = False
        if ours:
            rec = by_path.get(_nc(st)) or {}
            moved = (rec.get("prior") or {}).get("moved_to") if isinstance(rec.get("prior"), dict) else rec.get("moved_to")
            orig = ctx.expand(moved) if moved else os.path.join(rdir, "Scripts", "__startup.golem-user.lua")
            restore = orig if os.path.isfile(orig) and expected(ctx, orig, root, rpaths) else None
            o, rid = origin_of([st])
            if restore:
                used.add(_nc(restore))
            add(_item("reaper-links:Scripts/__startup.lua", "reaper-links", "REAPER startup script", [st], "user", o, True,
                      "golem's startup hook" + ("; your own startup script is put back" if restore else ""),
                      "restore" if restore else "remove", _paths=[st], _rids=rid, _restore=restore))

    # ── reaper-ini ──
    ini = os.path.join(rdir, "reaper.ini")
    if os.path.isfile(ini):
        if receipt is not None:
            ri = prior.get("reaper_ini") or {}
            keys, csurf = dict(ri.get("keys") or {}), bool(ri.get("csurf_added", True))
            audio = ri.get("audioconfig") if isinstance(ri.get("audioconfig"), dict) else None
            if ri.get("existed") is False:
                keys = {k: None for k in keys}
        else:
            keys, csurf, audio = {}, True, None
        with open(ini, encoding="latin-1", newline="") as f:
            _new, changes = _ini_new(f.read(), keys, csurf, audio)
        if changes:
            add(_item("reaper-ini:revert", "reaper-ini", "REAPER settings golem changed", [ini], "user",
                      "receipt" if receipt is not None else "golem-named", True,
                      "; ".join(changes) + ("" if receipt is not None else " (no receipt: only golem's OSC surface)"),
                      "revert", _ini=ini, _keys=keys, _csurf=csurf, _audio=audio, _prior_keys=["reaper_ini"]))

    # ── system (administrateur) ──
    added, deleted = _firewall_receipt(receipt or {})
    live = firewall_rules(ctx)
    names = list(dict.fromkeys(list(FIREWALL_FIXED) + added))
    if live is None:
        warnings.append("the firewall could not be read: golem's rules are removed if present")
        for n in names:
            add(_item("system:firewall:%s" % n, "system", "Firewall rule « %s »" % n, [], "admin",
                      "receipt" if n in added else "golem-named", True, "can't be checked: removed if present",
                      "remove-rule", presence="unknown", _rule=n))
    else:
        ours = {n.lower() for n in names}
        for n in live:
            if n.lower() in ours:
                add(_item("system:firewall:%s" % n, "system", "Firewall rule « %s »" % n, [], "admin",
                          "receipt" if n in added else "golem-named", True, "a firewall rule golem created",
                          "remove-rule", _rule=n))
            else:
                # un nom « golem* » qui n'est ni dans le reçu ni parmi les noms de golem : pas à nous, jamais coché
                add(_item("system:firewall:%s" % n, "system", "Firewall rule « %s »" % n, [], "admin", "unknown",
                          False, "named like golem's rules, but golem did not create it", "remove-rule", _rule=n))
        absent += ["firewall-name:%s" % n for n in added if n not in live]
    py = prior.get("python") if isinstance(prior.get("python"), dict) else {}
    pyexes = python_exes(ctx, py) if receipt is not None and py.get("installed_by_golem") else []
    if deleted:
        shown = ", ".join(sorted({str(r.get("displayname") or r.get("DisplayName") or r.get("name") or "?")
                                  for r in deleted}))
        for_py = [r for r in deleted if _rule_program(r) in pyexes]
        add(_item("system:firewall-restore", "system", "Firewall rules golem deleted at install", [], "admin", "receipt",
                  True, "put back as they were: %s" % shown + (
                      "; not the ones for golem's Python if you remove it (they would point to a removed program)"
                      if for_py else ""),
                  "restore-rules", _rules=deleted, _prior_keys=["firewall_deleted"]))
    if ctx.programdata:
        pdg = os.path.join(ctx.programdata, "GoleM")
        if os.path.isdir(pdg):
            o, rid = origin_of([pdg])
            add(_item("system:programdata", "system", "Installer cache for all users", [pdg], "admin", o, True,
                      "the installers golem downloaded (ProgramData)", "remove", _paths=[pdg], _rids=rid))
    if ctx.programfiles:
        prev = os.path.join(ctx.programfiles, "REAPER (x64).golem-prev")
        if os.path.isdir(prev):
            o, rid = origin_of([prev])
            add(_item("system:reaper-prev", "system", "Previous REAPER kept after an engine update", [prev], "admin", o,
                      True, "the copy golem kept to roll back an engine update", "remove", _paths=[prev], _rids=rid))
    # les dossiers communs des plugins (Common Files\VST3, LV2, CLAP) que les installeurs des éditeurs ont CRÉÉS pour
    # golem (prior.common_dirs, install-system.ps1) : leurs désinstalleurs les laissent vides. Retirés dans la passe
    # élevée APRÈS les programmes, et seulement s'ils sont vides. Sans reçu : jamais touchés
    cd = prior.get("common_dirs")
    if receipt is not None and isinstance(cd, dict) and ctx.commonfiles:
        made = [os.path.join(ctx.commonfiles, k) for k in COMMON_DIRS if cd.get(k) is False]
        here = [d for d in made if os.path.isdir(d) and not _is_link(d)]
        if here:
            add(_item("system:common-dirs", "system", "Plugin folders created for golem (Common Files)", here, "admin",
                      "receipt", True, "the vendor installers created them for golem; each is removed only if it is "
                      "empty once the plugins are uninstalled — one that still holds a plugin stays",
                      "remove-empty-dirs", _dirs=here, _prior_keys=["common_dirs"]))
        elif made:
            absent.append("prior:common_dirs")

    # ── programs : chacun par le désinstalleur de son éditeur ──
    progs = _programs_prior(prior)
    entries = None

    def registry():
        nonlocal entries
        if entries is None:
            try:
                entries = uninstall_entries()
            except Exception:
                entries = []
        return entries
    for pid, label, family, probes, pats, dflt, why in PROGRAMS:
        ps = [os.path.join(ctx.vars.get(v.upper()) or "", *rel.split("/")) for v, rel in probes
              if ctx.vars.get(v.upper())]
        c = progs.get(pid)
        # le dossier que le REÇU a noté : un REAPER installé par golem ailleurs que Program Files (D:\…, 2026-10-17)
        # n'était jamais trouvé, donc jamais proposé
        if c is not None and c.get("path") and all(not _same(c["path"], p) for p in ps):
            ps.append(c["path"])
        present = [p for p in ps if os.path.exists(p)]
        by_golem = _installed_by_golem(c) if c is not None else None
        if receipt is not None and c is not None:
            if not by_golem:
                continue                                    # « existed » : déjà là avant golem, jamais proposé
            if not present:
                absent.append("programs:%s" % pid)
                continue
            exe, args = split_command(c.get("uninstall"))
            if not exe:
                # le reçu n'a pas sa commande (introuvable au registre juste après l'installation) : on ne devine pas
                warnings.append("%s: golem installed it, but no uninstall command was recorded — it is not offered; "
                                "remove it from Windows Settings ▸ Apps if you want" % label)
                continue
            add(_item("programs:%s" % pid, "programs", label, present, "admin", "receipt", dflt, why, "uninstall",
                      _exe=exe, _args=_with_silent(exe, args, family), _probes=present,
                      _key=c.get("uninstall_key") or "",
                      _prior_keys=["programs.%s" % pid, "components.%s" % pid] + (["reaper"] if pid == "reaper" else [])))
        elif present:
            e = _entry(pats, registry())
            exe, args = split_command((e or {}).get("quiet") or (e or {}).get("uninstall")) if e else (None, [])
            add(_item("programs:%s" % pid, "programs", label, present, "admin", "unknown", False,
                      "nothing records that golem installed it" + ("" if exe else
                                                                    "; no uninstall command found: Windows Settings ▸ Apps"),
                      "uninstall" if exe else "manual", _exe=exe, _args=_with_silent(exe, args, family) if exe else [],
                      _probes=present))

    # ── plugins : TapeDelay2 (provision/airwindows.py, sans droits) ──
    td = os.path.join(ctx.localappdata, "Programs", "Common", "VST3", "GoleM")
    if os.path.isdir(td):
        o, rid = origin_of([td] + [os.path.join(td, n) for n in os.listdir(td)])
        add(_item("plugins:tapedelay2", "plugins", "Airwindows TapeDelay2", [td], "user", o, True,
                  "golem placed it in its own folder", "remove", _paths=[td], _rids=rid))

    # ── reaper : le dossier de réglages (REAPER lui-même est un programme) ──
    if os.path.isdir(rdir):
        rp = prior.get("reaper") or {}
        add(_item("reaper:config", "reaper", "REAPER settings folder", [rdir], "user",
                  "receipt" if rp.get("installed_by_golem") else "unknown", False,
                  "your REAPER settings, scripts and licence (the licence is backed up first)", "remove", _paths=[rdir]))

    # ── toolchain : le Python du bootstrap ──
    if receipt is not None and py.get("installed_by_golem"):
        pdir = python_dir(ctx, py)
        if pdir and os.path.exists(pdir):
            exe, args = split_command(py.get("uninstall"))
            if not exe:
                e = python_entry(registry(), py.get("version"))
                if e:
                    exe, args = split_command(e.get("quiet") or e.get("uninstall"))
            add(_item("toolchain:python", "toolchain", "Python %s" % (py.get("version") or ""), [pdir], "user", "receipt",
                      False, "the bootstrap installed it for golem; other scripts may use it. It is uninstalled once "
                      "this uninstaller has closed (it runs on it), with the firewall rules Windows made for it"
                      + ("" if exe else "; no uninstall command found: Windows Settings ▸ Apps"),
                      "uninstall-later" if exe else "manual", _exe=exe, _args=_with_silent(exe, args, "burn") if exe else [],
                      _pydir=pdir, _pyexes=pyexes, _prior_keys=["python"]))
        else:
            absent.append("prior:python")
    # le cache de pip (%LOCALAPPDATA%\pip) : né du pip du venv pendant le setup. Proposé seulement quand le reçu dit
    # qu'il n'existait pas avant golem (prior.pip_cache_existed: false) ; sans reçu, jamais
    pip = os.path.join(ctx.localappdata, "pip")
    if receipt is not None and prior.get("pip_cache_existed") is False and os.path.isdir(pip) and not _is_link(pip):
        add(_item("toolchain:pip-cache", "toolchain", "pip download cache", [pip], "user", "receipt", False,
                  "pip's download cache, created by golem's install; other Python tools may use it", "remove",
                  _paths=[pip], _extra_ok=[pip], _prior_keys=["pip_cache_existed"]))
    elif receipt is not None and prior.get("pip_cache_existed") is False:
        absent.append("prior:pip_cache_existed")

    # les éléments du reçu que rien n'a portés : listés s'ils existent, sinon « absents »
    for r in ritems:
        p = ctx.expand(r["path"])
        if _nc(p) in used:
            continue
        if not os.path.lexists(p):
            absent.append(r.get("id") or r["path"])
            continue
        if not expected(ctx, p, root, rpaths):
            warnings.append("receipt entry refused (outside what golem may remove): %s" % p)
            continue
        g = "reaper-links" if _inside(p, rdir) else "golem"
        add(_item("%s:%s" % (g, p), g, os.path.basename(p), [p], "user", "receipt", True,
                  "recorded by %s" % (r.get("by") or "the install"), "remove", _paths=[p],
                  _rids=[r.get("id")] if r.get("id") else []))
    items.sort(key=lambda it: GROUPS.index(it["group"]))
    return {"mode": mode, "root": root, "receipt": ctx.receipt_path if receipt is not None else None,
            "platform": "windows", "items": items, "absent": absent, "warnings": warnings, "never_apt": list(NEVER),
            "apt_model": None, "apt_deps": [], "check_yourself": list(CHECK_YOURSELF), "_apt_ours": []}


# ── LA PASSE ÉLEVÉE : UN script PowerShell, UNE autorisation ───────────────────────────────────────────
PS_HEAD = r"""# généré par provision/uninstall_win.py (docs/uninstall.md §9.3) — jetable, lancé ÉLEVÉ une seule fois
param([Parameter(Mandatory = $true)][string]$Log)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# le journal PARTAGÉ en lecture : le désinstallateur (non élevé) le lit pendant qu'on l'écrit
$script:ls = [IO.File]::Open($Log, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
$script:lw = New-Object IO.StreamWriter($script:ls, (New-Object Text.UTF8Encoding($false)))
$script:lw.AutoFlush = $true
function Say($l) { $script:lw.WriteLine($l) }
# un élément : son résultat sur UNE ligne « @@ITEM <n> <code> <message> » ; un échec n'arrête pas les autres
function Item($n, [scriptblock]$b) {
    try { $r = @(& $b) | Select-Object -Last 1; Say ("@@ITEM {0} 0 {1}" -f $n, $r) }
    catch { Say ("@@ITEM {0} 1 {1}" -f $n, ($_.Exception.Message -replace "`r?`n", ' ')) }
}
function RemoveTree($p) {
    if (-not (Test-Path -LiteralPath $p)) { return 'was not there' }
    Remove-Item -LiteralPath $p -Recurse -Force
    if (Test-Path -LiteralPath $p) { throw "still there: $p" }
    'folder removed'
}
function DropRule($name) {
    $r = @(Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)
    if (-not $r.Count) { return 'was not there' }
    $r | Remove-NetFirewallRule
    "removed ($($r.Count))"
}
# les règles ENTRANTES que Windows a faites pour un programme (« TCP Query User{…}python.exe ») : quand ce Python
# part, elles viseraient un programme disparu. La comparaison des chemins est sans casse (-contains)
function DropProgramRules([string[]]$progs) {
    $rules = @(Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue |
        Where-Object { $_.Program -and ($progs -contains ([string]$_.Program).Trim('"')) } |
        Get-NetFirewallRule -ErrorAction SilentlyContinue | Where-Object { [string]$_.Direction -eq 'Inbound' })
    if (-not $rules.Count) { return 'no firewall rule for this Python' }
    $names = @($rules | ForEach-Object { $_.DisplayName } | Sort-Object -Unique) -join ', '
    $rules | Remove-NetFirewallRule
    "removed $($rules.Count) rule(s): $names"
}
# un dossier commun des plugins créé pour golem : retiré SEULEMENT s'il est vide (les désinstalleurs sont passés)
function DropEmptyDir($p) {
    if (-not (Test-Path -LiteralPath $p)) { return "$p was not there" }
    if (@(Get-ChildItem -LiteralPath $p -Force -ErrorAction SilentlyContinue).Count) { return "$p kept: it still holds plugins" }
    Remove-Item -LiteralPath $p -Force
    if (Test-Path -LiteralPath $p) { throw "still there: $p" }
    "$p removed (empty)"
}
function PutRule($h) {
    if (Get-NetFirewallRule -DisplayName $h.DisplayName -ErrorAction SilentlyContinue) { return 0 }
    New-NetFirewallRule @h | Out-Null
    1
}
$GOLEM_MARKS = @('golem-nam-version.txt', '.golem-nam-version')
# le désinstalleur d'un ÉDITEUR, silencieux. Jugé SUR PIÈCE, pas sur son code : un NSIS se copie dans %TEMP% et rend
# la main tout de suite — on attend que ses fichiers soient partis
function Vendor($exe, [string[]]$a, [string[]]$probes, $key) {
    if ([IO.Path]::IsPathRooted($exe) -and -not (Test-Path -LiteralPath $exe)) { throw "uninstaller not found: $exe" }
    $p = Start-Process -FilePath $exe -ArgumentList $a -Wait -PassThru
    # attente BORNÉE (90 s) : ses fichiers partis, et sa clé « Uninstall » aussi quand le reçu la donne
    for ($i = 0; $i -lt 90; $i++) {
        # ce que GOLEM a posé dans le dossier d'un éditeur — le témoin du NAM 0.7.15 (install-system.ps1) : son
        # désinstalleur ne le connaît pas, le dossier restait avec ce seul fichier et l'élément était dit en échec
        # (VM 2026-10-24). On le retire quand il n'y a PLUS QUE lui.
        foreach ($d in @($probes | Where-Object { Test-Path -LiteralPath $_ -PathType Container })) {
            $files = @(Get-ChildItem -LiteralPath $d -Recurse -Force -File -ErrorAction SilentlyContinue)
            if ($files.Count -and -not @($files | Where-Object { $GOLEM_MARKS -notcontains $_.Name }).Count) {
                Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        $left = @($probes | Where-Object { Test-Path -LiteralPath $_ })
        if ($key -and (Test-Path -LiteralPath "Registry::$key")) { $left += "registry key $key" }
        if (-not $left.Count) { return "uninstalled by its own uninstaller (exit $($p.ExitCode))" }
        Start-Sleep -Seconds 1
    }
    throw "still there after its uninstaller (exit $($p.ExitCode)): $($left -join ', ')"
}
"""


def _ps_args(args):
    """ArgumentList de Start-Process : JOINTE par des espaces — un argument qui en contient est mis entre guillemets."""
    out = []
    for a in args:
        a = str(a)
        out.append(_q('"%s"' % a if (" " in a and not a.startswith('"')) else a))
    return "@(" + ", ".join(out) + ")" if out else "@()"


RULE_KEYS = (("displayname", "DisplayName"), ("display_name", "DisplayName"), ("DisplayName", "DisplayName"),
             ("direction", "Direction"), ("action", "Action"), ("profile", "Profile"), ("program", "Program"),
             ("protocol", "Protocol"), ("enabled", "Enabled"), ("description", "Description"))


def _rule_hash(r):
    """Une règle exportée (prior.firewall_deleted) -> la table de New-NetFirewallRule. None si elle n'a pas de nom."""
    h = {}
    for k, ps in RULE_KEYS:
        v = r.get(k)
        if v not in (None, "", []) and ps not in h:
            h[ps] = str(v)
    if "DisplayName" not in h and r.get("name"):
        h["DisplayName"] = str(r["name"])
    if "DisplayName" not in h:
        return None
    ports = r.get("ports") or r.get("local_port") or r.get("localport")
    if isinstance(ports, (str, int)):
        ports = [ports]
    ports = [str(p) for p in (ports or []) if str(p) and str(p).lower() != "any"]
    if h.get("Protocol", "").lower() in ("any", ""):
        h.pop("Protocol", None)
        ports = []
    parts = ["%s = %s" % (k, _q(v)) for k, v in h.items()]
    if ports:
        parts.append("LocalPort = @(%s)" % ", ".join(_q(p) for p in ports))
    return "@{ " + "; ".join(parts) + " }"


def _admin_body(ctx, it, root, rpaths):
    a = it["action"]
    if a == "remove-rule":
        return "DropRule %s" % _q(it["_rule"])
    if a == "restore-rules":
        hs = [h for h in (_rule_hash(r) for r in it.get("_rules") or []) if h]
        if not hs:
            raise UninstallError("no rule in the receipt can be put back")
        return "$n = 0; " + "; ".join("$n += (PutRule %s)" % h for h in hs) + "; \"$n rule(s) put back\""
    if a == "remove":
        for p in it.get("_paths") or []:
            if not expected(ctx, p, root, rpaths):
                raise UninstallError("refused: %s is not in the expected set" % p)
            if _is_link(p):
                raise UninstallError("refused: %s is a link" % p)
        return "; ".join("RemoveTree %s" % _q(p) for p in it["_paths"])
    if a == "drop-program-rules":
        progs = [str(p) for p in it.get("_programs") or [] if p]
        if not progs:
            raise UninstallError("no program to look for")
        return "DropProgramRules @(%s)" % ", ".join(_q(p) for p in progs)
    if a == "remove-empty-dirs":
        ok = {_nc(os.path.join(ctx.commonfiles, k)) for k in COMMON_DIRS} if ctx.commonfiles else set()
        dirs = it.get("_dirs") or []
        for p in dirs:
            if _nc(p) not in ok:
                raise UninstallError("refused: %s is not a common plugin folder" % p)
            if _is_link(p):
                raise UninstallError("refused: %s is a link" % p)
        if not dirs:
            raise UninstallError("no folder")
        return "(@(%s) -join '; ')" % ", ".join("(DropEmptyDir %s)" % _q(p) for p in dirs)
    if a == "uninstall":
        if not it.get("_exe"):
            raise UninstallError("no uninstall command")
        return "Vendor %s %s %s %s" % (_q(it["_exe"]), _ps_args(it.get("_args") or []),
                                       "@(%s)" % ", ".join(_q(p) for p in it.get("_probes") or []),
                                       _q(it.get("_key") or ""))
    raise UninstallError("no administrator action for %s" % it["id"])


def admin_script(ctx, items, root, rpaths):
    """(script, [(id, refus)], [éléments dans l'ordre du script]) — les règles et dossiers d'abord, les programmes
    ensuite (§5 : la passe système, puis les « paquets »), et EN DERNIER les dossiers communs des plugins vidés par
    leurs désinstalleurs."""
    last = [i for i in items if i["action"] == "remove-empty-dirs"]
    rest = [i for i in items if i["action"] != "remove-empty-dirs"]
    ordered = [i for i in rest if i["group"] != "programs"] + [i for i in rest if i["group"] == "programs"] + last
    lines, refused, todo = [PS_HEAD], [], []
    for it in ordered:
        try:
            body = _admin_body(ctx, it, root, rpaths)
        except UninstallError as e:
            refused.append((it["id"], str(e)))
            continue
        lines.append("Item %d { %s }" % (len(todo), body))
        todo.append(it)
    lines.append("Say '@@END'")
    lines.append("$script:lw.Dispose()")
    lines.append("exit 0")
    return "\n".join(lines) + "\n", refused, todo


def _elevate_mod():
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("golem_elevate_win", os.path.join(here, "installer", "elevate_win.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def elevate(ctx, script, logf, on_line):
    """Lance `script` ÉLEVÉ (UAC) par le mécanisme de l'installateur (installer/elevate_win.py) ; chaque ligne de son
    journal passe à on_line. Rend le code (1223 = autorisation refusée). Les tests remplacent cette fonction."""
    ew = _elevate_mod()
    return ew.run(script, ["-Log", logf], logf, on_line, lambda argv: run_command(ctx, argv, timeout=3600)[0])


def _run_elevated(ctx, items, root, rpaths, report):
    if not items:
        return
    script, refused, todo = admin_script(ctx, items, root, rpaths)
    for iid, msg in refused:
        report("programs" if iid.startswith("programs:") else "root", iid, False, msg)
    if not todo:
        return
    d = tempfile.mkdtemp(prefix="golem-uninstall-elev-")
    path, logf = os.path.join(d, "uninstall-admin.ps1"), os.path.join(d, "uninstall-admin.log")
    with open(path, "w", encoding="utf-8-sig") as f:              # le BOM : PowerShell 5.1 lit sinon en cp1252
        f.write(script)
    open(logf, "w", encoding="utf-8").close()
    seen = {}

    def on_line(ln):
        ln = ln.rstrip("\r\n")
        if ln.startswith("@@ITEM "):
            parts = ln.split(" ", 3)
            if len(parts) >= 3 and parts[1].isdigit():
                seen[int(parts[1])] = (parts[2] == "0", parts[3] if len(parts) > 3 else "")
        elif ln.strip() and ln != "@@END":
            print("  " + ln, flush=True)
    try:
        print("→ Windows asks your permission once (UAC) — approve it to continue", flush=True)
        rc = elevate(ctx, path, logf, on_line)
    except Exception as e:                                       # jamais un plantage : un échec dit
        rc = 1
        print("✗ the elevated pass could not start: %s" % e, flush=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    for n, it in enumerate(todo):
        step = "programs" if it["group"] == "programs" else "root"
        if n in seen:
            ok, msg = seen[n]
            report(step, it["id"], ok, msg or ("done" if ok else "failed"))
        elif rc == 1223:
            report(step, it["id"], False, "Windows permission was not granted — Retry and approve the Windows prompt")
        else:
            report(step, it["id"], False, "the elevated pass did not run it (exit %s)" % rc)


def _python_firewall(admin, chosen, report):
    """Python retiré (toolchain:python choisi) : ses règles du pare-feu partent dans la passe élevée (un élément de
    plus, « toolchain:python:firewall »), et les règles supprimées à l'installation qui le visaient ne sont PAS
    recréées (elles viseraient un programme disparu). Python gardé : rien ne change. Rend (éléments élevés, éléments
    ajoutés)."""
    py = next((i for i in chosen if i["id"] == "toolchain:python"), None)
    exes = (py or {}).get("_pyexes") or []
    if not py or not exes:
        return admin, []
    out = []
    for it in admin:
        if it["action"] == "restore-rules":
            keep = [r for r in it.get("_rules") or [] if _rule_program(r) not in exes]
            if not keep:
                report("root", it["id"], True, "nothing to put back: these rules were for the Python being removed")
                continue
            it = dict(it, _rules=keep)
        out.append(it)
    fw = _item("toolchain:python:firewall", "system", "Firewall rules Windows made for golem's Python", [], "admin",
               "receipt", True, "inbound rules for %s" % " or ".join(exes), "drop-program-rules", _programs=exes)
    return out + [fw], [fw]


# ── l'arrêt : golem d'abord, et un REAPER de golem ouvert = refus ─────────────────────────────────────
def venv_python(root):
    p = os.path.join(root, ".venv", "Scripts", "python.exe")
    return p if os.path.isfile(p) else None


def golem_reapers(ctx, root):
    """Les REAPER de golem encore ouverts ([pid]) — golem ouvre toujours un projet de son dossier sets\\ ; None si on
    ne peut pas lire les processus. Un REAPER ouvert par le musicien lui-même n'y figure pas."""
    rows = processes(ctx, ["reaper.exe"])
    if rows is None:
        return None
    sets = _nc(os.path.join(root, "sets")) if root else None
    return [pid for pid, _n, cmd in rows if sets and sets in _nc(cmd.replace('"', ""))]


def any_reaper(ctx):
    rows = processes(ctx, ["reaper.exe"])
    return bool(rows) if rows is not None else False


def close_windows(ctx):
    """Ferme les fenêtres de golem (et de son installateur) : les navigateurs DÉDIÉS, dont la ligne de commande porte
    --user-data-dir=<%LOCALAPPDATA%\\GoleM\\…>. Jamais le navigateur personnel, jamais la fenêtre du désinstallateur
    (son profil vit dans sa copie, %TEMP%). Rend le nombre de processus fermés."""
    marker = ("--user-data-dir=" + ctx.data_dir + os.sep).lower()
    rows = processes(ctx, ["chrome.exe", "msedge.exe"]) or []
    n = 0
    for pid, _name, cmd in rows:
        if marker in cmd.replace('"', "").lower():
            rc, _out = run_command(ctx, ["taskkill", "/PID", str(pid), "/T", "/F"], timeout=15)
            n += rc == 0
    return n


def _stop(ctx, root, report):
    """§5 étape 2. Rend False si un REAPER de golem tourne encore : rien ne sera touché."""
    if root and os.path.isdir(root):
        py = venv_python(root) or sys.executable
        rc, out = run_command(ctx, [py, "-m", "provision.desktop", "stop"], timeout=180, cwd=root)
        last = [ln for ln in (out or "").splitlines() if ln.strip()]
        report("stop", None, rc == 0, (last[-1] if last else "golem stopped") if rc == 0
               else "golem stop: exit %s %s" % (rc, last[-1] if last else ""))
    else:
        report("stop", None, True, "install folder absent: nothing to stop")
    n = close_windows(ctx)
    report("stop", None, True, "%d golem window process%s closed" % (n, "" if n == 1 else "es"))
    pids = golem_reapers(ctx, root)
    if pids:
        report("stop", None, False, "REAPER of golem is still running (pid %s) — it may be asking to save its project: "
               "answer it or close it, then Retry" % ", ".join(str(p) for p in pids))
        return False
    if pids is None:
        report("stop", None, True, "the running programs could not be read: going on")
    return True


# ── les actions de l'utilisateur ─────────────────────────────────────────────────────────────────────
def _after_exit_mod():
    import importlib.util
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("golem_after_exit_win",
                                                  os.path.join(here, "installer", "after_exit_win.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _uninstaller_copy(ctx):
    """La copie du désinstallateur graphique (GOLEM_UNINSTALLER_COPY, posé par installer/uninstaller.py) : un dossier
    golem-uninstaller-* directement dans %TEMP%, sinon None — le veilleur l'efface après la fermeture."""
    c = os.environ.get("GOLEM_UNINSTALLER_COPY") or ""
    if c and _same(os.path.dirname(os.path.normpath(c)), ctx.temp) \
            and os.path.basename(os.path.normpath(c)).startswith("golem-uninstaller-") and os.path.isdir(c):
        return os.path.normpath(c)
    return None


def schedule_after_exit(ctx, wait_pid, python=None, copy_dir=None):
    """Le VEILLEUR (installer/after_exit_win.py) : créé par WMI, hors de l'arbre de processus et de tout job, il
    attend que `wait_pid` (le désinstallateur, qui tourne sur ce Python) soit parti, lance le désinstalleur de Python
    (python = {exe, args, dir}), puis efface la copie du désinstallateur (copy_dir, si elle porte son marqueur). Rend
    (ok, journal %TEMP%\\golem-after-uninstall-<horodatage>.log, message). Les tests remplacent cette fonction."""
    m = _after_exit_mod()
    return m.schedule(wait_pid, ctx.temp, python=python, copy_dir=copy_dir,
                      runner=lambda argv: run_command(ctx, argv, timeout=60))


def _user_action(ctx, it, root, rpaths):
    a = it["action"]
    if a == "manual":
        raise UninstallError(it["reason"])
    if it["id"] == "reaper-ini:revert":
        if any_reaper(ctx):
            raise UninstallError("REAPER is running: it would rewrite reaper.ini when it quits")
        return revert_ini(it["_ini"], it.get("_keys") or {}, it.get("_csurf"), it.get("_audio"))
    if it["id"] == "golem:power-plan":
        rc, out = run_command(ctx, ["powercfg", "/setactive", it["_guid"]], timeout=30)
        if rc != 0:
            raise UninstallError("powercfg: %s" % (out or "exit %s" % rc))
        return "power plan set back (%s)" % it["_guid"]
    if it["id"] == "toolchain:python":
        wait = int(os.environ.get("GOLEM_UNINSTALL_WAIT_PID") or os.getppid())
        ok, log, msg = schedule_after_exit(ctx, wait, python={"exe": it["_exe"], "args": it.get("_args") or [],
                                                              "dir": it.get("_pydir") or ""},
                                           copy_dir=_uninstaller_copy(ctx))
        if not ok:
            raise UninstallError("Python could not be scheduled for removal (%s); its log: %s" % (msg, log))
        return ("scheduled: Python is uninstalled once this uninstaller has closed (log: %s)" % log), {"after_log": log}
    if it["id"] == "toolchain:pip-cache":
        return ", ".join(safe_remove(ctx, p, root, list(rpaths) + list(it.get("_extra_ok") or []))
                         for p in it.get("_paths") or [])
    if it.get("_keep_receipt"):
        base, n = it["_paths"][0], 0
        for name in sorted(os.listdir(base)):
            if not name.startswith(RECEIPT_NAME):
                safe_remove(ctx, os.path.join(base, name), root, rpaths)
                n += 1
        if not os.path.exists(ctx.receipt_path):
            try:
                os.rmdir(base)
            except OSError:
                pass
        return "%d entries removed" % n
    if it["id"] == "golem:inbox":
        p = it["_paths"][0]
        return _remove_empty_tree(ctx, p, root) if it.get("_inbox_custom") else safe_remove(ctx, p, root, rpaths)
    msgs = [safe_remove(ctx, p, root, rpaths) for p in it.get("_paths") or []]
    if a == "restore" and it.get("_restore"):
        src, dst = it["_restore"], it["_paths"][0]
        if not expected(ctx, src, root, rpaths):
            raise UninstallError("refused: cannot restore %s" % src)
        if os.path.lexists(dst):
            raise UninstallError("cannot put the original back: %s is in the way" % dst)
        os.rename(src, dst)
        msgs.append("your startup script put back")
    return ", ".join(msgs) or "done"


def _self_paths():
    return [os.getcwd(), os.path.abspath(__file__)]


# ── le reçu après un passage ─────────────────────────────────────────────────────────────────────────
def _pop_dotted(d, key):
    parts = key.split(".")
    cur = d
    for k in parts[:-1]:
        cur = cur.get(k) if isinstance(cur, dict) else None
        if cur is None:
            return
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def _rewrite_receipt(ctx, receipt, plan, done, failed):
    done_rids, done_prior = set(), set()
    for it in plan["items"]:
        if it["id"] in done:
            done_rids.update(it.get("_rids") or [])
            done_prior.update(it.get("_prior_keys") or [])
            if it["id"].startswith("system:firewall:"):
                done_prior.add("firewall-name:" + it["_rule"])
    for a in plan["absent"]:
        if a.startswith("firewall-name:"):
            done_prior.add(a)
        elif a.startswith("prior:"):
            done_prior.add(a[6:])
        elif a.startswith("programs:"):
            done_prior.update(("programs." + a[9:], "components." + a[9:]))
        else:
            done_rids.add(a)
    r = json.loads(json.dumps(receipt))
    r["items"] = [i for i in (r.get("items") or []) if isinstance(i, dict) and i.get("id") not in done_rids
                  and i.get("path") not in done_rids]
    pr = r.setdefault("prior", {})
    for k in done_prior:
        if k.startswith("firewall-name:"):
            fw = r.get("firewall")
            if isinstance(fw, dict) and isinstance(fw.get("added"), list):
                fw["added"] = [x for x in fw["added"] if x != k[14:]]
        else:
            _pop_dotted(pr, k)
    r["uninstall"] = {"updated": datetime.datetime.now().isoformat(timespec="seconds"), "failed": sorted(failed)}
    fd, tmp = tempfile.mkstemp(prefix=".install-receipt.", dir=os.path.dirname(ctx.receipt_path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, ensure_ascii=False)
    os.replace(tmp, ctx.receipt_path)
    # les fragments en attente étaient VERSÉS (en mémoire, receipt.load) dans ce qu'on vient d'écrire : les garder
    # les ferait revenir — « le premier gagne » rendrait des priors déjà consommés
    for frag in glob.glob(ctx.receipt_path + ".pending-*.json"):
        try:
            os.unlink(frag)
        except OSError:
            pass


def _delete_receipt(ctx):
    """Le reçu ET ce qui l'accompagne (son verrou, des fragments en attente), puis %LOCALAPPDATA%\\GoleM s'il est vide."""
    os.unlink(ctx.receipt_path)
    for p in glob.glob(ctx.receipt_path + ".*"):
        try:
            os.unlink(p)
        except OSError:
            pass
    try:
        os.rmdir(os.path.dirname(ctx.receipt_path))
    except OSError:
        pass


# ── L'EXÉCUTION (§5) ─────────────────────────────────────────────────────────────────────────────────
def run(ctx, ids, report):
    receipt, _w = load_receipt(ctx)
    plan = build_plan(ctx)
    by_id = {i["id"]: i for i in plan["items"]}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise UninstallError("not in the plan (absent, or not golem's): %s" % ", ".join(unknown))
    chosen = [by_id[i] for i in dict.fromkeys(ids)]
    root = plan["root"]
    rpaths = [ctx.expand(r["path"]) for r in ((receipt or {}).get("items") or []) if isinstance(r, dict) and r.get("path")]

    # 2. arrêter golem ; un REAPER de golem encore ouvert = refus, rien n'est touché
    if not _stop(ctx, root, report):
        for it in chosen:
            report("stop", it["id"], False, "not done: REAPER of golem is still running")
        report("done", None, False, "nothing removed: REAPER of golem is still running")
        return False

    # 3. UNE passe élevée : système (pare-feu, ProgramData, golem-prev), puis les programmes par leur éditeur
    admin, synth = _python_firewall([i for i in chosen if i["privilege"] == "admin"], chosen, report)
    _run_elevated(ctx, admin, root, rpaths, report)

    # 4. REAPER, 5. plugins, toolchain, intégration utilisateur
    for step, groups in (("reaper", ("reaper-links", "reaper-ini", "reaper")), ("user", ("plugins", "toolchain", "golem"))):
        for g in groups:
            for it in chosen:
                if it["group"] != g or it["privilege"] != "user" or it.get("_step") == "folder":
                    continue
                try:
                    res = _user_action(ctx, it, root, rpaths)
                    msg, extra = res if isinstance(res, tuple) else (res, {})
                    report(step, it["id"], True, msg, **extra)
                except (UninstallError, OSError) as e:
                    report(step, it["id"], False, str(e))

    # 6. le dossier d'install, EN DERNIER
    for it in chosen:
        if it.get("_step") != "folder":
            continue
        inside = [s for s in _self_paths() if _inside(os.path.realpath(s), os.path.realpath(root))]
        if inside:
            report("folder", it["id"], False, "refused: the uninstaller runs from inside the install folder (%s) — "
                   "copy it elsewhere first (the graphical uninstaller runs from %%TEMP%%)" % inside[0])
            continue
        try:
            report("folder", it["id"], True, safe_remove(ctx, root, root, rpaths))
        except (UninstallError, OSError) as e:
            report("folder", it["id"], False, "%s (a file may still be open: close golem's windows and Retry)" % e)
    emptied = []
    for d in (os.path.join(ctx.localappdata, "Programs", "Common", "VST3"), os.path.join(ctx.localappdata, "Programs", "Common")):
        try:
            os.rmdir(d)
            emptied.append(d)
        except OSError:
            pass
    if emptied:
        report("folder", None, True, "empty folders removed: %s" % ", ".join(emptied))

    # 7. le reçu
    done = {k for k, v in report.results.items() if v}
    failed = {i["id"] for i in chosen + synth if not report.results.get(i["id"])}
    all_ok = not failed
    if receipt is None:
        report("receipt", None, True, "no install receipt: nothing to update")
    else:
        golem_gone = not root or not os.path.exists(root)
        try:
            if all_ok and golem_gone:
                _delete_receipt(ctx)
                report("receipt", None, True, "receipt deleted: golem is uninstalled")
            else:
                _rewrite_receipt(ctx, receipt, plan, done, failed)
                report("receipt", None, True, "receipt rewritten with what remains (%d failed)" % len(failed))
        except OSError as e:
            report("receipt", None, False, "receipt: %s" % e)
    report("done", None, all_ok, "everything chosen was removed" if all_ok
           else "%d item(s) failed: %s" % (len(failed), ", ".join(sorted(failed))))
    return all_ok


def public(plan):
    return U.public(plan)


def plan_text(plan):
    out = U.plan_text({**plan, "items": []}).splitlines()[:1 + len(plan["warnings"])]
    for g in GROUPS:
        its = [i for i in plan["items"] if i["group"] == g]
        if not its:
            continue
        out += ["", "[%s]" % g]
        for i in its:
            out.append("  [%s] %-44s %-12s %-11s %s" % ("x" if i["default"] else " ", i["id"], i["action"], i["origin"],
                                                        i["label"]))
            out += ["        %s" % p for p in i["paths"]]
            out.append("        %s%s" % (i["reason"], " (Windows asks your permission)" if i["privilege"] == "admin" else ""))
    if plan["absent"]:
        out += ["", "Already gone (in the receipt): %s" % ", ".join(plan["absent"])]
    out += ["", "Never offered (system base): %s" % ", ".join(plan["never_apt"]),
            "", "Check yourself (not recorded, never deleted):"] + ["  - " + c for c in plan.get("check_yourself") or []]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="uninstall.py", description="Uninstall golem (docs/uninstall.md §9).")
    ap.add_argument("--root-fs", default=None, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="list what would be removed — touches nothing")
    p.add_argument("--root", help="the golem install folder")
    p.add_argument("--json", action="store_true")
    r = sub.add_parser("run", help="remove the chosen items")
    r.add_argument("--root", help="the golem install folder")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--items", nargs="+", metavar="ID")
    g.add_argument("--select", metavar="FILE", help="JSON list of ids (or a plan with items[].id/selected)")
    r.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    r.add_argument("--json", action="store_true", help="JSON-lines progress on stdout")
    r.add_argument("--log", metavar="FILE")
    a = ap.parse_args(argv)
    if a.root_fs:
        print("--root-fs is for the Linux engine's tests only", file=sys.stderr)
        return 2
    ctx = WinCtx(root=a.root)
    if a.cmd == "plan":
        plan = build_plan(ctx)
        print(json.dumps(public(plan), indent=1) if a.json else plan_text(plan))
        return 0
    ids = a.items or U._read_selection(a.select)
    if not ids:
        print("nothing selected", file=sys.stderr)
        return 2
    if not a.yes:
        if not sys.stdin.isatty() or a.json:
            print("refused: pass --yes (no terminal to confirm on)", file=sys.stderr)
            return 2
        plan = build_plan(ctx)
        print(plan_text(public({**plan, "items": [i for i in plan["items"] if i["id"] in ids]})))
        if input("\nRemove these %d item(s)? Type yes: " % len(ids)).strip().lower() != "yes":
            print("cancelled")
            return 1
    try:
        ok = run(ctx, ids, Reporter(as_json=a.json, log=a.log))
    except UninstallError as e:
        if a.json:
            print(json.dumps({"step": "plan", "item": None, "ok": False, "msg": str(e)}))
        else:
            print(str(e), file=sys.stderr)
        return 2
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
