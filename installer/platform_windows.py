# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que l'installateur fait SOUS WINDOWS (docs/installer.md §8) — même interface que
platform_linux.py, mêmes sept écrans ; ce module ne connaît que Windows.

Ce qui change, et pourquoi :
  · les droits : pas de mot de passe. UNE autorisation Windows (UAC) pour un script élevé qui pose ce
    qui va dans Program Files — le runtime Visual C++, Reaper, le NAM VST3 (provision/windows/
    install-system.ps1). GoleM lui-même tourne en utilisateur, comme sous Linux ;
  · un seul profil, Desktop : le kiosque et le mode sans écran sont des machines Linux ;
  · le bridge se pose par le setup du portage (`python -m provision.desktop setup`) ;
  · le pack batterie n'est pas proposé : son bloc ne joue pas encore sous Windows (le piano l'est depuis le 2026-10-22) ; le pack
    guitar (la pompe du bloc Standard, sfizz VST3) l'est.
"""
import ctypes
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time

import elevate_win  # noqa: E402  — l'élévation UAC, partagée avec le désinstallateur
from desktop_steps import (DI_URL, LOCAL_STATE, _py_env, free_mb, has_internet,  # noqa: F401 — partagés avec macOS
                           step_source, step_sounds)

NAME = "windows"
PRIVILEGE = "uac"
# le reçu d'installation (docs/uninstall.md §9.2) : %LOCALAPPDATA%\GoleM\install-receipt.json — l'écran 3 y
# note la licence REAPER d'avant golem (server.py, _license_prior).
RECEIPT = True
# le désinstallateur graphique (docs/uninstall.md §9.4) : server.py --uninstall, le moteur provision/uninstall_win.py
UNINSTALL = True
# la fenêtre d'application du désinstallateur : son profil vit dans SA copie (%TEMP%) — server.py le pose ; celui de
# l'installateur est dans %LOCALAPPDATA%\GoleM, que la désinstallation supprime
APP_PROFILE = None
# l'installateur-application tourne sous pythonw : sans ce drapeau, chaque sonde (powershell, whoami)
# ouvre sa console noire — l'écran Reaper en relance une à chaque rafraîchissement (2026-10-02)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

STEPS = [
    ("source", "Copy golem to its folder"),
    ("system", "Windows permission, once: Visual C++ runtime, Reaper, NAM plugin, drum kits, Vitalium synth, firewall"),
    ("bridge", "golem bridge: Python environment, Reaper scripts and settings"),
    ("sounds", "Sounds"),
    ("profile", "Start menu and desktop shortcuts"),
]

# LES PHASES de l'écran Install (installer/phases.py) : une par étape, des libellés COURTS, et leurs durées MESURÉES
# — install complète dans la VM Windows 11 (6 vCPU, 2026-10-24) : 4 min 34. « learn » faux = surtout du
# téléchargement : ça n'apprend rien de la vitesse de la machine (et l'étape système attend aussi un clic sur l'UAC).
SOUNDS_MB_S = 3.0          # le même départ que Linux ; le réseau varie du simple au triple


def phases(S):
    sz = sizes(S["src"] or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), S["dir"])
    mb = sum(sz["packs"].get(p, 0) for p in S["packs"] if p != "di")      # les DI ne sont pas encore publiées
    gb = f"about {mb / 1024:.1f} GB" if mb >= 1024 else f"about {mb} MB"
    return [
        {"id": "source", "step": "source", "label": "Copy golem to its folder", "est": 5},
        {"id": "system", "step": "system", "label": "Windows permission, then REAPER's plugins", "est": 105, "learn": False},
        {"id": "bridge", "step": "bridge", "label": "golem itself", "est": 60},
        {"id": "sounds", "step": "sounds", "label": f"Sounds — {gb}" if mb else "Sounds", "est": round(mb / SOUNDS_MB_S),
         "learn": False},
        {"id": "profile", "step": "profile", "label": "Shortcuts: golem and golem Server", "est": 5},
    ]

def default_dir():
    return os.path.join(os.path.expanduser("~"), "golem")


def pins(src):
    with open(os.path.join(src, "provision", "windows", "pins.json"), encoding="utf-8") as f:
        return json.load(f)


def ui():
    return {
        "os_label": "Windows 10/11",
        "checks_intro": "golem runs on Windows 10 or 11, 64-bit, with your audio interface's ASIO driver. Red lines with a ⛔ stop the install; orange ones only warn.",
        "reaper_platform": "Windows x64",
        "reaper_install_note": "official installer from reaper.fm, checksum verified, installed in Program Files — Windows asks your permission once",
        "reaper_update_note": "the installer keeps your Reaper as is; Settings ▸ Licenses ▸ Reaper moves it to the tested version, and keeps yours one tap away.",
        "launcher_done": 'the golem and golem Server icons, on your desktop and in the Start menu (and Stop golem there)',
        # l'écran Connect en deux champs (connect_status / connect_save), et un seul bouton de fin (finish)
        "connect": "form",
        "finish": "Open golem",
        "next": [
            ["", "Settings ▸ Soundcard", ": “Configure ASIO…” picks your audio interface's ASIO driver (until then golem runs without a sound card)."],
            ["", "Settings ▸ Calibration", ": the pedalboard and your MIDI pedals — your interface's own driver must expose its MIDI ports (a Universal Audio Volt needs the UA driver)."],
            ["warn", "A2 amp captures", " don't play on Windows yet: the official NAM plugin cannot read that format. golem marks those blocks and offers a non-A2 capture."],
        ],
        "first_run": "golem starts when you close the installer below. The first start takes a minute or two (Reaper scans your plugins). Until Reaper is licensed, it shows its « About REAPER » evaluation window at every start — close it; golem keeps running behind it.",
        "done_note": "Only the Visual C++ runtime, Reaper, the plugins golem plays (NAM, AVL Drumkits, Vitalium) and one firewall rule (Reaper accepts nothing from the network) were installed with administrator rights. golem itself runs as you, in its folder.",
        # la carte Vital de l'écran Done (vital_status, re-vérifiée en direct)
        "vital": True,
    }


# ── Vital officiel : un compte vital.audio, donc un geste de l'utilisateur ─────────────────────────
VITAL_URL = "https://vital.audio/"


def vital_status():
    """Ce que le bloc vital jouera : le Vital OFFICIEL (VST3, que seul l'utilisateur peut télécharger —
    compte gratuit sur vital.audio) s'il est installé, sinon Vitalium (posé par -Vitalium). Lu sur le
    disque à chaque appel : l'écran Done re-vérifie pendant que l'utilisateur installe."""
    common = os.environ.get("COMMONPROGRAMFILES", r"C:\Program Files\Common Files")
    official = os.path.join(common, "VST3", "Vital.vst3")
    return {"official": os.path.exists(official),
            "vitalium": os.path.isdir(os.path.join(common, "LV2", "vitalium.lv2")),
            "download_url": VITAL_URL}


# ── vérifications préalables (écran 1) ────────────────────────────────────────────────
class _MEM(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def mem_gb():
    try:
        m = _MEM()
        m.dwLength = ctypes.sizeof(_MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullTotalPhys / 1024 ** 3, 1)
    except Exception:
        return None


def is_admin_member():
    """Le compte peut-il approuver une élévation lui-même ? (groupe Administrateurs, SID S-1-5-32-544).
    Sinon UAC demandera les identifiants d'un administrateur : ça marche aussi, mais il faut le dire."""
    try:
        out = subprocess.run(["whoami", "/groups"], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
        return "S-1-5-32-544" in out
    except Exception:
        return None


def checks():
    build = getattr(sys.getwindowsversion(), "build", 0) if hasattr(sys, "getwindowsversion") else 0
    win11 = build >= 22000
    arch = platform.machine()
    mem = mem_gb()
    net = has_internet()
    home_free = free_mb(os.path.expanduser("~"))
    admin = is_admin_member()
    return [
        {"id": "os", "label": "Windows 10/11", "ok": build >= 19041, "blocking": True,
         "detail": f"Windows {'11' if win11 else '10'} (build {build})" + ("" if build >= 19041 else " — Windows 10 2004 or later is needed")},
        {"id": "arch", "label": "64-bit x86", "ok": arch in ("AMD64", "x86_64"), "blocking": True,
         "detail": arch + ("" if arch in ("AMD64", "x86_64") else " — the neural plugins golem uses ship for x64 only")},
        {"id": "mem", "label": "Memory", "ok": bool(mem and mem >= 7.5), "blocking": False,
         "detail": (f"{mem} GB" if mem else "?") + ("" if mem and mem >= 7.5 else " — 8 GB recommended")},
        {"id": "disk", "label": "Free space in your home", "ok": bool(home_free and home_free >= 3000), "blocking": False,
         "detail": (f"{home_free / 1024:.1f} GB free" if home_free else "?") + ("" if home_free and home_free >= 3000 else " — 3 GB minimum")},
        {"id": "net", "label": "Internet", "ok": net, "blocking": True,
         "detail": "reaper.fm reachable" if net else "no route — Reaper, the NAM plugin and Python packages are downloaded during the install"},
        {"id": "admin", "label": "Administrator approval (UAC)", "ok": admin is not False, "blocking": False,
         "detail": "Windows asks your permission once, in the install screen" if admin is not False
         else "this account is not an administrator — Windows will ask for an administrator's password once"},
        {"id": "python", "label": "Python 3.12", "ok": sys.version_info[:2] >= (3, 10), "blocking": True,
         "detail": sys.version.split()[0] + ("" if sys.version_info[:2] == (3, 12) else " — golem is tested with Python 3.12")},
    ]


# ── Reaper (écran 2) ──────────────────────────────────────────────────────────────────
def _where(src=None):
    """bridge/reaper_license.py de la source, chargé par son CHEMIN (le bridge ne tourne pas pendant
    l'installation) : c'est LUI qui sait où est REAPER, pour l'installateur comme pour golem ensuite."""
    root = src or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("golem_reaper_where",
                                                  os.path.join(root, "bridge", "reaper_license.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def reaper_exe(src=None):
    """Le reaper.exe de cette machine, OÙ QU'IL SOIT (registre, chemin retenu, Program Files) — pas seulement
    « C:\\Program Files » : un REAPER sur D: était invisible et golem en installait un second (2026-10-17)."""
    try:
        return _where(src).windows_exe()
    except Exception:
        return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "REAPER (x64)", "reaper.exe")


def reaper_locate(src, path):
    """« J'ai déjà REAPER ailleurs » : retient le dossier (ou le reaper.exe) indiqué. ValueError s'il n'y est pas."""
    return _where(src).remember_windows_exe(path)


def exe_version(path):
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(Get-Item -LiteralPath '{path}').VersionInfo.ProductVersion"],
                           capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        return r.stdout.strip() or None
    except Exception:
        return None


def reaper_detect(src):
    # GoleM lance Reaper depuis Program Files (provision/desktop.py, reaper_binary) : c'est là qu'on regarde
    exe = reaper_exe(src)
    path = exe if os.path.isfile(exe) else None
    try:
        pinned = pins(src)["reaper"]["version"]
    except Exception:
        pinned = None
    default_dir = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "REAPER (x64)")
    return {"found": bool(path), "path": path, "version": exe_version(path) if path else None, "pinned": pinned,
            "download_url": "https://www.reaper.fm/download.php", "buy_url": "https://www.reaper.fm/purchase.php",
            # l'écran propose les deux gestes qui manquaient : « je l'ai ailleurs » et « installe-le là »
            "can_locate": True, "default_dir": default_dir}


def reaper_install(ctx):
    """Installe REAPER — dans le dossier choisi à l'écran (`S.reaper_dir`), sinon Program Files ; puis le
    RETIENT, pour que golem le lance de là."""
    d = (ctx.S.get("reaper_dir") or "").strip().strip('"')
    rc = run_elevated(ctx, "reaper", ["-Reaper"] + (["-ReaperDir", d] if d else []))
    if rc == 0 and d and not ctx.S["dry"]:
        try:
            reaper_locate(ctx.S["src"], d)
        except Exception as e:
            ctx.log(f"⚠ REAPER installed but not found in {d}: {e}", "reaper")
    return rc


# ── taille (écran 4) ──────────────────────────────────────────────────────────────────
def sizes(src, target_dir):
    return {"fixed": {"vcredist": 25, "reaper": 70, "plugins": 30, "drums_engine": 160, "synth_engine": 230, "bridge": 450, "repo": 60},
            "fixed_labels": [["vcredist", "Microsoft Visual C++ runtime"], ["reaper", "Reaper"],
                             ["plugins", "NAM plugin (the amp and cab core)"], ["drums_engine", "AVL Drumkits (the drum kit block)"], ["synth_engine", "Vitalium and the PawPaw LV2 plugins (the Vital synth block)"], ["bridge", "golem bridge (Python environment)"],
                             ["repo", "golem code"]],
            "packs": {"di": 30, "piano": 450, "drums": 2300, "guitar": 442}, "required_packs": ["di"],
            # piano : proposé depuis le 2026-10-22 (sfizz VST3 + chargeur par l'état VST3, docs/platforms.md §5)
            "packs_unavailable": {"drums": "the multi-mic drum kit block does not play on Windows yet"},
            "free_mb": free_mb(target_dir),
            "pack_labels": {"di": "golem reference DIs (guitar, bass) — for the preset previews",
                            "piano": "Salamander grand piano", "drums": "The Aasimonster drum kit (multi-mic)",
                            "guitar": "Shinyguitar — the gypsy rhythm guitar of the Standard block"}}


# ── le reçu d'installation (docs/uninstall.md §9.2) ──────────────────────────────────
def _receipt(src):
    """provision/receipt.py de la source, chargé par son chemin ; None s'il manque. Jamais fatal."""
    try:
        spec = importlib.util.spec_from_file_location("golem_receipt_win", os.path.join(src, "provision", "receipt.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None


def _receipt_root(ctx, target):
    """Le reçu naît avec la source (comme sous Linux, platform_linux._receipt_root) : set-root, qui verse au passage
    le fragment du bootstrap (prior.python). Jamais fatal."""
    if ctx.S["dry"]:
        return
    R = _receipt(target)
    if R is None:
        return
    try:
        R.set_root(target)
    except Exception as e:
        ctx.log(f"⚠ install receipt not created ({e})", "source")


# ── l'élévation : UN script, UNE autorisation, son journal lu en direct ──────────────
_ps_quote = elevate_win.ps_quote


def run_elevated(ctx, step, switches):
    """Lance provision/windows/install-system.ps1 ÉLEVÉ (UAC) et verse son journal dans celui de
    l'installateur. Un processus élevé n'a pas de sortie lisible par son parent non élevé : il écrit
    un fichier, qu'on lit pendant qu'il tourne. Refuser l'autorisation = échec dit, Retry possible."""
    S = ctx.S
    if S["dry"]:
        return ctx.run(ctx.dry_cmd(step), step)
    script = os.path.join(S["src"], "provision", "windows", "install-system.ps1")
    logf = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")), f"golem-install-{step}-{int(time.time())}.log")
    open(logf, "w", encoding="utf-8").close()
    # chaque argument est re-cité pour Start-Process (qui JOINT ArgumentList par des espaces) : un dossier
    # « C:\Users\Jean Paul\… » ne doit pas devenir deux arguments — elevate_win le fait, pour l'installateur ET le
    # désinstallateur (provision/uninstall_win.py) : UN mécanisme d'élévation
    args = ["-Log", logf, *switches]
    # le reçu de L'UTILISATEUR, résolu ICI (non élevé) et passé en paramètre : élevé par un autre compte
    # administrateur, le script verrait le %LOCALAPPDATA% de l'administrateur (docs/uninstall.md §9.2)
    R = _receipt(S["src"])
    rcpt = None
    if R is not None:
        try:
            rcpt = R.receipt_path()
        except Exception:
            rcpt = None
    if rcpt:
        args += ["-Receipt", rcpt]
    ctx.log("→ Windows asks your permission once (UAC) — approve it to continue", step)
    rc = elevate_win.run(script, args, logf, lambda ln: ctx.log(ln, step), lambda argv: ctx.run(argv, step))
    if rcpt:
        try:
            R.merge_pending()            # ce que le script élevé a noté, versé tout de suite (pas « au prochain passage »)
        except Exception:
            pass
    if rc == 1223:
        ctx.log("✗ the install needs that permission — tap Retry and approve the Windows prompt", step)
    return rc


# ── les étapes ────────────────────────────────────────────────────────────────────────
def step_bridge(ctx, target):
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("bridge"), "bridge")
    # le setup du portage : venv, dépendances, scripts et JSFX dans les ressources de Reaper, OSC et
    # Dummy Audio dans reaper.ini — et il vérifie que python-rtmidi SE CHARGE (le runtime C++ en dépend)
    # python.exe, pas le pythonw.exe de l'installateur : les commandes console du setup (venv, pip) héritent d'une vraie
    # sortie au lieu d'en chercher une (lancé sans fenêtre : CREATE_NO_WINDOW, installer/server.py `run`)
    return ctx.run([_console_python(sys.executable), "-m", "provision.desktop", "setup"], "bridge", cwd=target,
                   extra_env=_py_env())


def launcher_path(target):
    return os.path.join(target, "golem.cmd")


def _console_python(exe):
    """Le Python de BASE en console (python.exe), jamais celui d'un venv : le désinstallateur supprime le venv."""
    if exe == sys.executable:
        exe = getattr(sys, "_base_executable", None) or exe
    if os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        return alt if os.path.isfile(alt) else exe
    return exe


def launcher_script(target, python):
    """golem.cmd. `golem.cmd uninstall [--dry]` ouvre le désinstallateur graphique (docs/uninstall.md §9.4) avec le
    Python de base, DEPUIS %TEMP% (la console ne garde pas ouvert le dossier qu'on supprime) ; `uninstall --dry-run`
    imprime le plan (le moteur ne touche à rien)."""
    base = _console_python(python)
    return ("@echo off\r\nrem GoleM en console (depannage) - les raccourcis passent par pythonw, sans console\r\n"
            'if /i "%~1"=="uninstall" goto uninstall\r\n'
            f'cd /d "{target}"\r\nset PYTHONUTF8=1\r\n'
            f'"{python}" -m provision.desktop start %*\r\n'
            "if errorlevel 1 pause\r\n"
            "exit /b\r\n"
            ":uninstall\r\n"
            "rem le desinstallateur (docs/uninstall.md 9.4) : il se copie dans %TEMP% et repart de la\r\n"
            'cd /d "%TEMP%"\r\nset PYTHONUTF8=1\r\n'
            'if /i "%~2"=="--dry-run" goto plan\r\n'
            f'"{base}" "{target}\\installer\\server.py" --uninstall --root "{target}" --open %2 %3\r\n'
            "exit /b\r\n"
            ":plan\r\n"
            f'"{base}" "{target}\\provision\\uninstall.py" plan --root "{target}"\r\n'
            "exit /b\r\n")


def step_profile(ctx, target):
    S = ctx.S
    # plus de profil (docs/installer.md §4, 2026-10-06) : deux usages, GoleM et GoleM Server
    ctx.write_engine(target)                     # écran Engine (coquille : Reaper seul sélectionnable)
    ctx.write_first_run(target)                  # écran « What do you play? » (bridge/first_run.py)
    if S["dry"]:
        return ctx.run(ctx.dry_cmd("profile"), "profile")
    # golem.cmd : le lanceur EN CONSOLE, pour qui veut lire ce qui se passe (dépannage) — et `golem.cmd uninstall`
    with open(launcher_path(target), "w", encoding="utf-8") as f:
        f.write(launcher_script(target, sys.executable))
    # les raccourcis (Bureau, menu Démarrer, « Stop GoleM ») : la MÊME fonction que le setup du
    # portage (provision/desktop.py, install_shortcuts) — une seule définition de l'icône GoleM
    # plus de boîte dédiée ici (docs/installer.md §4, FIXÉ 2026-10-16) : « Start golem with this computer » est un
    # interrupteur de l'app (System ▸ Dashboard) — les deux usages, golem et golem server, sont toujours posés
    return ctx.run([sys.executable, "-m", "provision.desktop", "shortcuts"], "profile", cwd=target,
                   extra_env=_py_env())


# ── la fin : GoleM ne démarre QU'ICI ────────────────────────────────────────────────────
# Avant, une étape « start » lançait GoleM dès la dernière étape d'installation : sa fenêtre s'ouvrait
# par-dessus l'installateur, deux écrans AVANT la fin (2026-10-02). L'écran Connect n'a plus
# besoin du rig (connect_save écrit les clés sans lui) : GoleM part au bouton de l'écran Done, qui
# ferme l'installateur dans le même geste.
def bridge_python():
    """L'exécutable qui ÉCOUTE sur le port du bridge : le python.exe du Python de base (le venv en descend ;
    provision/desktop.py lance `python -m uvicorn`). L'installateur, lui, tourne sous pythonw.exe : la règle du
    pare-feu le visait, et Windows demandait « Autoriser Python ? » au premier lancement (VM 2026-10-24)."""
    base = getattr(sys, "_base_executable", None) or sys.executable
    py = os.path.join(os.path.dirname(base), "python.exe")
    return py if os.path.isfile(py) else base


def finish(ctx):
    """Lance GoleM exactement comme l'icône du Bureau : pythonw, sans console, fenêtre applicative.
    DÉTACHÉ : il survit à l'installateur, qui se ferme juste après."""
    if ctx.S["dry"]:
        ctx.log("(dry run) golem would start now", None)
        return True
    target = ctx.S["dir"]
    pythonw = os.path.join(target, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(pythonw):
        return False
    subprocess.Popen([pythonw, "-m", "provision.desktop", "start"], cwd=target,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return True


# ── l'écran Connect : deux clés, rien d'autre ───────────────────────────────────────────
# Il chargeait l'app entière dans un cadre (Settings ▸ API) : on pouvait y naviguer partout, et il
# fallait que GoleM tourne. Deux champs suffisent ; le reste (l'appairage par QR, la connexion OAuth
# de TONE3000) reste dans l'app, qui le sait faire. On écrit par la fonction de l'app elle-même, dans
# le Python de GoleM : `provision.desktop connect`, les secrets par l'entrée standard.
def _connect(ctx, body):
    target = ctx.S["dir"]
    python = os.path.join(target, ".venv", "Scripts", "python.exe")
    if ctx.S["dry"] or not os.path.isfile(python):
        return {"golem_token": {"set": False, "hint": ""}, "t3k_key": {"set": False, "hint": ""},
                **({"dry": True} if ctx.S["dry"] else {"error": "golem is not installed yet"})}
    r = subprocess.run([python, "-m", "provision.desktop", "connect"], input=json.dumps(body),
                       capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=target,
                       env={**os.environ, **_py_env()}, creationflags=NO_WINDOW)
    if r.returncode != 0:
        return {"error": (r.stderr.strip().splitlines() or ["could not save"])[-1]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def connect_status(ctx):
    return _connect(ctx, {})


def connect_save(ctx, body):
    return _connect(ctx, {"golem_token": body.get("golem_token") or "", "t3k_key": body.get("t3k_key") or ""})


def run_step(sid, ctx):
    S = ctx.S
    src, target = S["src"], S["dir"]
    if sid == "source":
        rc = step_source(ctx, src, target)
        if rc == 0:
            _receipt_root(ctx, os.path.abspath(target))
        return rc
    if sid == "system":
        # -BridgePython : le Python de base, celui qui ouvrira le port du bridge (le venv du setup en
        # descend) — la règle « GoleM ouvert aux réseaux privés » le vise, lui et le port 8770
        # -Avldrums (2026-10-03) : le moteur du bloc drumkit — sans lui un patch drums ne sonne pas
        # -Vitalium (2026-10-03) : le moteur du bloc vital tant que le Vital officiel n'est pas là (il
        # demande un compte vital.audio : l'écran Done le propose, on ne peut pas le télécharger pour toi)
        # -Sfizz (2026-10-11) : le lecteur SFZ — le piano Keys ET les kits de batterie importés (VST3, lu par
        # l'état VST3 : docs/drums-kit.md §8) ; l'interrupteur existait sans que l'installeur le passe
        # -Proteus (2026-10-22) : le bloc boost — la table Windows le nommait, rien ne l'installait
        switches = ["-Vcredist", "-Nam", "-Avldrums", "-Vitalium", "-Sfizz", "-Proteus", "-Firewall",
                    "-BridgePython", bridge_python()]
        # OÙ EST REAPER, dit au script élevé (il ne regardait que Program Files) : le pare-feu vise CE reaper.exe,
        # et une installation demandée ici va dans le dossier choisi à l'écran
        found = reaper_detect(src)
        if found["found"]:
            switches += ["-ReaperDir", os.path.dirname(found["path"])]
        else:
            switches.append("-Reaper")
            if (S.get("reaper_dir") or "").strip():
                switches += ["-ReaperDir", S["reaper_dir"].strip().strip('"')]
        rc = run_elevated(ctx, "system", switches)
        if rc == 0 and not found["found"] and (S.get("reaper_dir") or "").strip() and not S["dry"]:
            try:                                    # installé ailleurs que Program Files : golem le lancera de là
                reaper_locate(src, S["reaper_dir"].strip().strip('"'))
            except Exception as e:
                ctx.log(f"⚠ REAPER not found in {S['reaper_dir']} after install: {e}", "system")
        return rc
    if sid == "bridge":
        return step_bridge(ctx, target)
    if sid == "sounds":
        return step_sounds(ctx, target)
    if sid == "profile":
        return step_profile(ctx, target)
    return 1


def open_url(url):
    """Un lien EXTERNE (reaper.fm, l'achat de licence) : le navigateur de l'utilisateur, en onglet."""
    os.startfile(url)


def close_app(window):
    """Ferme la fenêtre ouverte par open_app — Chrome y a des processus enfants : tout l'arbre."""
    subprocess.run(["taskkill", "/PID", str(window.pid), "/T", "/F"], capture_output=True,
                   timeout=10, creationflags=NO_WINDOW)


# la taille de l'installateur : son rail d'étapes se replie sous 900 px (installer.css)
APP_W, APP_H = 1120, 780


def _work_area():
    """(x, y, largeur, hauteur) de la zone UTILE de l'écran principal (sans la barre des tâches), en pixels logiques
    — ceux de --window-size, le processus n'étant pas « DPI aware ». None si l'API ne répond pas."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):     # SPI_GETWORKAREA
            return r.left, r.top, r.right - r.left, r.bottom - r.top
    except (AttributeError, OSError, ValueError):
        pass
    return None


def window_geometry(area=None):
    """Taille et position de la fenêtre : 1120×780, ramenée à la zone utile et centrée dedans. VM Windows 2026-10-24
    (écran 1280×800) : la barre des tâches cachait Back et Next — un portable 1366×768 aussi."""
    area = area or _work_area()
    if not area:
        return [f"--window-size={APP_W},{APP_H}"]
    x, y, aw, ah = area
    w, h = min(APP_W, aw - 16), min(APP_H, ah - 16)
    return [f"--window-size={w},{h}", f"--window-position={x + (aw - w) // 2},{y + (ah - h) // 2}"]


_OPEN_PROFILE = None       # le profil de la fenêtre ouverte par open_app (app_alive le cherche)


def app_alive():
    """La fenêtre vit-elle encore ? Un navigateur porte notre profil sur sa ligne de commande (VM Windows, 2026-10-16 :
    quand un autre Edge tourne déjà — la fenêtre de golem —, le processus qu'on lance PASSE LA MAIN et se termine tout
    de suite, fenêtre ouverte ; le serveur le croyait fermé, s'arrêtait et vidait sa copie : « Uninstall golem » ne
    montrait rien, ou « not found »). True en cas de doute : on ne ferme pas sur une lecture ratée."""
    if not _OPEN_PROFILE:
        return False
    marker = ("--user-data-dir=" + _OPEN_PROFILE).replace('"', "").casefold()
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
             "ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return any(marker in ln.replace('"', "").casefold() for ln in out.splitlines())


def open_app(url):
    """L'installateur dans SA fenêtre d'application, comme GoleM (provision/desktop.py, open_window) :
    Chromium `--app` — ni onglets ni barre d'adresse — avec un profil à lui. Profil DÉDIÉ, et pas celui
    de l'app : le processus du navigateur est alors le nôtre et vit exactement autant que la fenêtre,
    ce qui permet au serveur de s'arrêter quand on la ferme (server.py). Sans Chrome ni Edge : un onglet.
    Rend le processus de la fenêtre, ou None."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from provision import desktop
    browser = desktop.app_browser()
    if browser is None:
        open_url(url)
        return None
    profile = APP_PROFILE or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "GoleM", "installer-browser")
    os.makedirs(profile, exist_ok=True)
    global _OPEN_PROFILE
    _OPEN_PROFILE = profile
    return subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}",
                             *window_geometry(), "--no-first-run",
                             "--no-default-browser-check", "--disable-features=Translate"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

# ── LES CAPTURES D'USINE (installer/server.py factory_start) : golem en SERVEUR, sans fenêtre ───────────────────────
# Le compte TONE3000 se connecte par un retour sur le bridge : il faut golem. On le lance comme `golem server` (aucune
# fenêtre par-dessus l'installateur — la raison pour laquelle golem ne démarrait qu'à l'écran Done), DÉTACHÉ ; le bouton
# de l'écran Done ouvrira ensuite la fenêtre sur ce même golem (provision.desktop start : « already running »).
# UN SEUL GOLEM, ET LA BONNE QUESTION (PC Windows neuf, 2026-11-03) : chaque clic sur « Sign in to TONE3000 &
# download them » lançait un NOUVEAU `golem server` sans regarder si golem tournait déjà — quatre clics, quatre
# lanceurs, chacun resté bloqué derrière l'installateur sur la boîte « golem is running without a window ». Et la
# sonde lisait /api/factory/captures en 1 s avec un `except Exception` qui avalait tout : un golem vivant mais lent
# passait pour « not started ». On demande à /api/health, on ne lance que si personne ne répond, et le lanceur
# n'ouvre aucune boîte (GOLEM_NO_DIALOG : il n'a pas d'écran à qui parler, l'installateur dit la suite).
def bridge_start(ctx):
    """None si golem répond (ou vient de démarrer), sinon la raison."""
    import time
    target = ctx.S["dir"]
    pythonw = os.path.join(target, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(pythonw):
        return "golem is not installed yet"
    if golem_answers():
        return None
    subprocess.Popen([pythonw, "-m", "provision.desktop", "server"], cwd=target,
                     env={**os.environ, "GOLEM_NO_DIALOG": "1"},
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                     | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if golem_answers():
            return None
        time.sleep(1)
    return "golem did not start within 90 s"


def golem_answers(port=8770):
    """golem répond-il ? /api/health est la route qui ne fait rien d'autre."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False
