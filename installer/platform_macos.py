# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que l'installateur fait SOUS macOS (docs/platforms.md, M7 — 2026-10-04) — même interface que
platform_linux.py et platform_windows.py, mêmes sept écrans ; ce module ne connaît que macOS.

Écrit SANS Mac : la recette (docs/private/recette-macos.md §1) est la première fois qu'il tourne. Ce qui change :
  · les droits : pas de mot de passe tapé dans l'écran. UNE fenêtre d'administrateur de macOS (osascript
    « with administrator privileges ») pour le seul script qui écrit dans /Library et /Applications —
    REAPER, le NAM VST3, les moteurs batterie et synthé (provision/macos/install-system.sh). Le pendant
    exact de l'UAC de Windows : PRIVILEGE = "uac" pour l'écran (aucun champ mot de passe) ;
  · un seul profil, Desktop (le kiosque et le mode sans écran sont des machines Linux) ;
  · le bridge se pose par `python -m provision.desktop setup`, comme sous Windows ;
  · les raccourcis sont trois apps dans ~/Applications (provision/desktop.py, mac_shortcuts) ;
  · ce que GoleM ne peut pas télécharger lui-même (Vital officiel : un compte) est DIT à la dernière page.
"""
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from desktop_steps import (DI_URL, LOCAL_STATE, _py_env, free_mb, has_internet,  # noqa: F401 — partagés avec Windows
                           step_source, step_sounds)

NAME = "macos"
PRIVILEGE = "uac"                       # une autorisation du SYSTÈME, pas un mot de passe dans l'écran

STEPS = [
    ("source", "Copy golem to its folder"),
    ("system", "macOS permission, once: Reaper, NAM plugin, drum kits, Vitalium synth, reverbs, boost"),
    ("bridge", "golem bridge: Python environment, Reaper scripts and settings"),
    ("sounds", "Sounds"),
    ("profile", "golem apps in your Applications folder"),
]

PLUGINS = "/Library/Audio/Plug-Ins"
VITAL_URL = "https://vital.audio/"


def default_dir():
    return os.path.join(os.path.expanduser("~"), "golem")


# Les dossiers que macOS protège (TCC) : un processus n'y lit qu'avec l'accord donné à SON responsable. Le bash
# élevé par osascript, golem.app (non signée) et l'agent d'ouverture de session n'en ont pas — « Operation not
# permitted (126) » sur install-system.sh, vu le 2026-10-16 avec un clone sur le Bureau.
TCC_PROTECTED = ("Desktop", "Documents", "Downloads")


def tcc_protected(path):
    """Le dossier protégé qui contient `path` (« Desktop »…), None sinon."""
    home = os.path.realpath(os.path.expanduser("~"))
    p = os.path.realpath(path)
    for name in TCC_PROTECTED:
        root = os.path.join(home, name)
        if p == root or p.startswith(root + os.sep):
            return name
    return None


def pins(src):
    with open(os.path.join(src, "provision", "macos", "pins.json"), encoding="utf-8") as f:
        return json.load(f)


def _manual(src):
    """Ce que l'utilisateur pose lui-même : lu dans pins.json (`manual`), une source, pas deux."""
    try:
        return [[m["name"], m["why"], m.get("url")] for m in pins(src).get("manual", [])]
    except Exception:
        return []


def ui():
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return {
        "os_label": "macOS",
        "checks_intro": "golem runs on a Mac with Apple silicon and macOS 14 or later, with a class-compliant USB audio interface. Red lines with a ⛔ stop the install; orange ones only warn.",
        "reaper_platform": "macOS (Apple silicon)",
        "reaper_install_note": "official disk image from reaper.fm, checksum verified, copied to /Applications — macOS asks an administrator's permission once",
        "reaper_update_note": "update Reaper from reaper.fm when a golem release has validated the new version.",
        "launcher_done": 'golem, golem Server and Stop golem, in the Applications folder of your home (Launchpad and Spotlight find them)',
        "connect": "form",
        "finish": "Open golem",
        "permission": [
            "Installing needs macOS' permission, once: a macOS window asks for an administrator's password to install Reaper in /Applications and the plugins golem plays (NAM, AVL Drumkits, sfizz, Vitalium, Dragonfly Reverb, Proteus) in /Library/Audio/Plug-Ins. Approve it when it appears.",
            "That is the only part that runs as administrator. golem itself is copied to your folder and always runs as you; golem never sees nor keeps the password — macOS asks for it."],
        "next": [
            ["", "Settings ▸ Soundcard", ": pick your audio interface (Core Audio) — until then golem uses the Mac's default input and output."],
            ["", "Settings ▸ Calibration", ": the pedalboard and your MIDI pedals (CoreMIDI sees class-compliant devices without a driver)."],
            ["warn", "A2 amp captures", " don't play on macOS yet: the official NAM plugin cannot read that format. golem marks those blocks and offers a non-A2 capture."],
        ],
        "first_run": "golem starts when you close the installer below. The first start takes a minute or two (Reaper scans your plugins). Until Reaper is licensed, it shows its evaluation window at every start — close it; golem keeps running behind it. macOS may ask once whether Python may control « System Events » (to hide Reaper): allow it.",
        "done_note": "Only Reaper (in /Applications) and the plugins golem plays (NAM, AVL Drumkits, sfizz, Vitalium, Dragonfly Reverb, Proteus, in /Library/Audio/Plug-Ins) were installed with administrator rights. golem itself runs as you, in its folder.",
        "vital": True,
        "vital_installer": "macOS installer",
        "manual": _manual(src),
    }


def vital_status():
    """Le Vital OFFICIEL (VST3, compte vital.audio) s'il est là, sinon Vitalium (posé par PawPaw).
    Relu à chaque appel : l'écran Done re-vérifie pendant que l'utilisateur installe."""
    roots = [PLUGINS, os.path.expanduser("~" + PLUGINS)]
    return {"official": any(os.path.exists(os.path.join(r, "VST3", "Vital.vst3")) for r in roots),
            "vitalium": any(os.path.isdir(os.path.join(r, "LV2", "vitalium.lv2")) for r in roots),
            "download_url": VITAL_URL}


# ── vérifications préalables (écran 1) ────────────────────────────────────────────────
def _sysctl(name):
    try:
        return subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def mem_gb():
    v = _sysctl("hw.memsize")
    return round(int(v) / 1024 ** 3, 1) if v.isdigit() else None


def is_admin_member():
    """Le compte est-il administrateur ? Sinon macOS demandera le nom ET le mot de passe d'un admin."""
    try:
        return "admin" in subprocess.run(["id", "-Gn"], capture_output=True, text=True, timeout=5).stdout.split()
    except Exception:
        return None


def checks():
    ver = platform.mac_ver()[0] or "?"
    major = int(ver.split(".")[0]) if ver.split(".")[0].isdigit() else 0
    arch = platform.machine()
    mem = mem_gb()
    net = has_internet()
    home_free = free_mb(os.path.expanduser("~"))
    admin = is_admin_member()
    return [
        {"id": "os", "label": "macOS 14 or later", "ok": major >= 14, "blocking": True,
         "detail": f"macOS {ver}" + ("" if major >= 14 else " — golem is built for macOS 14 (Sonoma) and later")},
        {"id": "arch", "label": "Apple silicon", "ok": arch == "arm64", "blocking": False,
         "detail": arch + ("" if arch == "arm64" else " — golem is tested on Apple silicon; an Intel Mac may work, untested")},
        {"id": "mem", "label": "Memory", "ok": bool(mem and mem >= 7.5), "blocking": False,
         "detail": (f"{mem} GB" if mem else "?") + ("" if mem and mem >= 7.5 else " — 8 GB recommended")},
        {"id": "disk", "label": "Free space in your home", "ok": bool(home_free and home_free >= 3000), "blocking": False,
         "detail": (f"{home_free / 1024:.1f} GB free" if home_free else "?") + ("" if home_free and home_free >= 3000 else " — 3 GB minimum")},
        {"id": "net", "label": "Internet", "ok": net, "blocking": True,
         "detail": "reaper.fm reachable" if net else "no route — Reaper, the plugins and Python packages are downloaded during the install"},
        {"id": "admin", "label": "Administrator approval", "ok": admin is not False, "blocking": False,
         "detail": "macOS asks your password once, in the install screen" if admin is not False
         else "this account is not an administrator — macOS will ask for an administrator's name and password once"},
        {"id": "clt", "label": "Apple Command Line Tools", "ok": clt_ok(), "blocking": True,
         "detail": "installed" if clt_ok() else "missing — run « xcode-select --install » in Terminal, accept, then start the installer again"},
        {"id": "python", "label": "Python 3.12 or 3.13", "ok": python_ok(), "blocking": True,
         "detail": sys.version.split()[0] + ("" if python_ok() else " — install Python 3.13 from python.org (3.14 and later lack onnxruntime)")},
    ]


# Les Python que le lock du bridge sait installer sur macOS : onnxruntime 1.23.2 (épinglé pour darwin dans
# bridge/requirements.txt) n'a de wheels arm64 que cp312 et cp313 — en 3.15, l'étape bridge échouait APRÈS la
# fenêtre d'administrateur (mesuré le 2026-11-04). Même borne dans install-macos.command.
PY_MIN, PY_MAX = (3, 12), (3, 13)


def clt_ok():
    """Les Command Line Tools (ou Xcode) : python-rtmidi 1.5.8 n'a AUCUN wheel macOS, pip le compile à l'étape
    bridge. Sans eux, /usr/bin/clang n'est qu'un relais qui ouvre la fenêtre d'installation d'Apple, et pip
    échoue — après la fenêtre d'administrateur (audit macOS, 2026-11-04). `xcode-select -p` rend le dossier
    des outils actifs ; un dossier disparu (Xcode effacé) compte comme absent."""
    try:
        r = subprocess.run(["xcode-select", "-p"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    path = r.stdout.strip()
    return r.returncode == 0 and bool(path) and os.path.isdir(path)


def python_ok(version=None):
    return PY_MIN <= tuple((version or sys.version_info)[:2]) <= PY_MAX


# ── Reaper (écran 2) ──────────────────────────────────────────────────────────────────
REAPER_APP = "/Applications/REAPER.app"


def app_version(app):
    """« 7.82 » — pas « 7.82.0_3385784u », la chaîne brute de REAPER 7.82 (2026-11-04) : l'écran la comparait telle
    quelle au pin (« 7.79 ») et la montrait ainsi. Le « .0 » final tombe : le pin s'écrit major.minor."""
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            raw = str(plistlib.load(f).get("CFBundleShortVersionString") or "")
    except Exception:
        return None
    m = re.match(r"(\d+(?:\.\d+){1,2})", raw.strip())
    if not m:
        return raw or None
    v = m.group(1)
    return v[:-2] if v.count(".") == 2 and v.endswith(".0") else v


def reaper_detect(src):
    path = REAPER_APP if os.path.isdir(REAPER_APP) else None
    try:
        pinned = pins(src)["reaper"]["version"]
    except Exception:
        pinned = None
    return {"found": bool(path), "path": path, "version": app_version(path) if path else None, "pinned": pinned,
            "download_url": "https://www.reaper.fm/download.php", "buy_url": "https://www.reaper.fm/purchase.php"}


def reaper_install(ctx):
    return run_elevated(ctx, "reaper", ["--reaper"])


# ── taille (écran 4) ──────────────────────────────────────────────────────────────────
def sizes(src, target_dir):
    return {"fixed": {"reaper": 70, "plugins": 40, "drums_engine": 160, "synth_engine": 300, "bridge": 400, "repo": 60},
            "fixed_labels": [["reaper", "Reaper"], ["plugins", "NAM plugin (the amp and cab core)"],
                             ["drums_engine", "AVL Drumkits (the drum kit block)"],
                             ["synth_engine", "Vitalium and the PawPaw plugins (the Vital synth block)"],
                             ["bridge", "golem bridge (Python environment)"], ["repo", "golem code"]],
            "packs": {"di": 30, "piano": 450, "drums": 2300, "guitar": 442}, "required_packs": ["di"],
            "packs_unavailable": {"piano": "the piano block does not play on macOS yet",
                                  "drums": "the multi-mic drum kit block does not play on macOS yet"},
            "free_mb": free_mb(target_dir),
            "pack_labels": {"di": "golem reference DIs (guitar, bass) — for the preset previews",
                            "piano": "Salamander grand piano", "drums": "The Aasimonster drum kit (multi-mic)",
                            "guitar": "Shinyguitar — the gypsy rhythm guitar of the Standard block"}}


# ── l'élévation : UN script, UNE fenêtre d'administrateur, son journal lu en direct ───
def _sh_quote(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def _as_quote(s):
    """Une chaîne AppleScript : guillemets et barres obliques inverses échappés."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def elevated_command(script, logf, switches):
    """La commande osascript qui lance provision/macos/install-system.sh en administrateur. Le script
    écrit son journal dans `logf` (le processus élevé n'a pas de sortie lisible par l'installateur)."""
    shell = " ".join([_sh_quote("/bin/bash"), _sh_quote(script), "--log", _sh_quote(logf),
                      *(_sh_quote(s) for s in switches)])
    return ["osascript", "-e",
            f"do shell script {_as_quote(shell)} with prompt {_as_quote('golem installs Reaper and its plugins.')} "
            "with administrator privileges"]


def _stage_system_script(src):
    """Copie install-system.sh et pins.json dans un dossier temporaire de l'utilisateur ($TMPDIR) et le rend
    (run_elevated l'efface après osascript). La source peut être dans un dossier protégé (TCC) — un zip ouvert
    dans les Téléchargements : le bash élevé n'a pas le droit d'y lire, même en root. copyfile ne recopie pas
    com.apple.quarantine, xattr l'ôte quand même. Le script root vit un instant dans un dossier que
    l'utilisateur peut modifier — acceptable : il approuve la fenêtre et pouvait déjà modifier l'original ;
    mkdtemp (0700, nom imprévisible), copié juste avant osascript, effacé juste après."""
    here = os.path.join(src, "provision", "macos")
    stage = tempfile.mkdtemp(prefix="golem-system-")
    for name in ("install-system.sh", "pins.json"):
        shutil.copyfile(os.path.join(here, name), os.path.join(stage, name))
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", stage], capture_output=True)
    return stage


def run_elevated(ctx, step, switches):
    """Lance provision/macos/install-system.sh avec la fenêtre d'administrateur de macOS, et verse son
    journal dans celui de l'installateur. Annuler la fenêtre = échec dit (osascript rend -128), Retry possible."""
    S = ctx.S
    if S["dry"]:
        return ctx.run(ctx.dry_cmd(step), step)
    logf = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"golem-install-{step}-{int(time.time())}.log")
    open(logf, "w", encoding="utf-8").close()
    ctx.log("→ macOS asks for an administrator's password once — approve it to continue", step)
    stop = threading.Event()

    def tail():
        pos = 0
        while True:
            try:
                with open(logf, encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    for ln in f:
                        ctx.log(ln, step)
                    pos = f.tell()
            except OSError:
                pass
            if stop.is_set():
                return
            time.sleep(0.5)
    t = threading.Thread(target=tail, daemon=True)
    t.start()
    stage = _stage_system_script(S["src"])
    try:
        rc = ctx.run(elevated_command(os.path.join(stage, "install-system.sh"), logf, switches), step)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    time.sleep(0.6)
    stop.set()
    t.join(timeout=3)
    if rc != 0 and any("-128" in (ln.get("line") or "") for ln in S["log"][-5:]):
        ctx.log("✗ the install needs that permission — tap Retry and approve the macOS window", step)
    return rc


# ── les étapes ────────────────────────────────────────────────────────────────────────
def venv_python(target):
    return os.path.join(target, ".venv", "bin", "python")


def step_bridge(ctx, target):
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("bridge"), "bridge")
    return ctx.run([sys.executable, "-m", "provision.desktop", "setup"], "bridge", cwd=target, extra_env=_py_env())


def step_profile(ctx, target):
    # plus de profil (docs/installer.md §4, 2026-10-06) : deux usages, GoleM et GoleM Server
    ctx.write_engine(target)                     # écran Engine (coquille : Reaper seul sélectionnable)
    ctx.write_first_run(target)                  # écran « What do you play? » (bridge/first_run.py)
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("profile"), "profile")
    # les apps GoleM : la MÊME fonction que le setup (provision/desktop.py, mac_shortcuts)
    # plus de boîte dédiée ici (docs/installer.md §4, FIXÉ 2026-10-16) : un interrupteur de l'app (System ▸ Dashboard)
    return ctx.run([venv_python(target), "-m", "provision.desktop", "shortcuts"], "profile", cwd=target,
                   extra_env=_py_env())


def finish(ctx):
    """Lance GoleM comme GoleM.app, DÉTACHÉ : il survit à l'installateur, qui se ferme juste après."""
    if ctx.S["dry"]:
        ctx.log("(dry run) golem would start now", None)
        return True
    target = ctx.S["dir"]
    python = venv_python(target)
    if not os.path.isfile(python):
        return False
    log = open(os.path.expanduser("~/Library/Logs/GoleM-launcher.log"), "a")
    subprocess.Popen([python, "-m", "provision.desktop", "start"], cwd=target, start_new_session=True,
                     stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **_py_env()})
    return True


def _connect(ctx, body):
    target = ctx.S["dir"]
    python = venv_python(target)
    if ctx.S["dry"] or not os.path.isfile(python):
        return {"golem_token": {"set": False, "hint": ""}, "t3k_key": {"set": False, "hint": ""},
                **({"dry": True} if ctx.S["dry"] else {"error": "golem is not installed yet"})}
    r = subprocess.run([python, "-m", "provision.desktop", "connect"], input=json.dumps(body),
                       capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=target,
                       env={**os.environ, **_py_env()})
    if r.returncode != 0:
        return {"error": (r.stderr.strip().splitlines() or ["could not save"])[-1]}
    return json.loads(r.stdout.strip().splitlines()[-1])


def connect_status(ctx):
    return _connect(ctx, {})


def connect_save(ctx, body):
    return _connect(ctx, {"golem_token": body.get("golem_token") or "", "t3k_key": body.get("t3k_key") or ""})


def system_switches(src):
    """Ce que l'étape system pose : chaque moteur que macOS peut recevoir de GoleM (pins.json)."""
    p = pins(src)
    sw = ["--nam"]
    if "avldrums" in p:
        sw.append("--avldrums")
    if "pawpaw" in p:
        sw.append("--vitalium")
    if "sfizz" in p:                                   # le piano Keys et les kits SFZ importés (docs/drums-kit.md §8)
        sw.append("--sfizz")
    if "dragonfly" in p:                               # les trois réverbes (2026-11-04 : muettes sans elles)
        sw.append("--dragonfly")
    if "proteus" in p:                                 # le bloc boost
        sw.append("--proteus")
    if not reaper_detect(src)["found"]:
        sw.append("--reaper")
    return sw


def run_step(sid, ctx):
    S = ctx.S
    src, target = S["src"], S["dir"]
    if sid == "source":
        where = tcc_protected(src)
        if where and os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(target)):
            ctx.log(f"→ {src} is in your {where} folder, which macOS protects: golem is copied to {target}"
                    " (without its git history) and runs from there", "source")
        return step_source(ctx, src, target)
    if sid == "system":
        found = reaper_detect(src)
        if found["found"]:
            # un REAPER déjà là est GARDÉ (golem ne remplace pas le moteur de quelqu'un) — et le journal le dit
            note = "" if not found["pinned"] or found["version"] == found["pinned"] else f" (golem is tested with {found['pinned']})"
            ctx.log(f"→ Reaper {found['version'] or '?'} already installed — kept{note}", "system")
        return run_elevated(ctx, "system", system_switches(src))
    if sid == "bridge":
        return step_bridge(ctx, target)
    if sid == "sounds":
        return step_sounds(ctx, target)
    if sid == "profile":
        return step_profile(ctx, target)
    return 1


def open_url(url):
    """Un lien EXTERNE : le navigateur par défaut de l'utilisateur."""
    subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def close_app(window):
    window.terminate()


APP_W, APP_H = 1120, 780


_OPEN_PROFILE = None       # le profil de la fenêtre ouverte par open_app (app_alive le cherche)


def app_alive():
    """La fenêtre vit-elle encore ? Comme sous Windows (platform_windows.app_alive) : un navigateur porte notre profil sur
    sa ligne de commande. Le processus lancé PASSE LA MAIN quand ce profil est déjà ouvert (un installateur relancé),
    se termine tout de suite fenêtre ouverte, et le serveur se croyait fermé (audit du premier Mac réel, 2026-11-04).
    True en cas de doute : on ne ferme pas sur une lecture ratée."""
    if not _OPEN_PROFILE:
        return False
    try:
        out = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return any("--user-data-dir=" + _OPEN_PROFILE in ln for ln in out.splitlines())


def open_app(url):
    """L'installateur dans SA fenêtre d'application (Chrome/Edge `--app`, profil dédié), comme sous
    Windows : le processus vit autant que la fenêtre, le serveur s'arrête quand on la ferme. Sans
    navigateur Chromium : un onglet du navigateur par défaut."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    from provision import desktop
    browser = desktop.app_browser()
    if browser is None:
        open_url(url)
        return None
    global _OPEN_PROFILE
    profile = os.path.expanduser("~/Library/Application Support/GoleM/installer-browser")
    os.makedirs(profile, exist_ok=True)
    _OPEN_PROFILE = profile
    return subprocess.Popen([browser, f"--app={url}", f"--user-data-dir={profile}",
                             f"--window-size={APP_W},{APP_H}", "--no-first-run",
                             "--no-default-browser-check", "--disable-features=Translate"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# ── LES CAPTURES D'USINE (installer/server.py factory_start) : golem en SERVEUR, sans fenêtre ───────────────────────
# Même règle que Windows : `golem server` détaché, le bouton de l'écran Done ouvrira la fenêtre sur ce golem.
# Et la même garde que Windows (platform_windows.bridge_start, 2026-11-03) : /api/health, un seul lancement, pas de
# notification depuis un lanceur sans écran.
def bridge_start(ctx):
    """None si golem répond (ou vient de démarrer), sinon la raison."""
    import time
    target = ctx.S["dir"]
    python = venv_python(target)
    if not os.path.isfile(python):
        return "golem is not installed yet"
    if golem_answers():
        return None
    log = open(os.path.expanduser("~/Library/Logs/GoleM-launcher.log"), "a")
    subprocess.Popen([python, "-m", "provision.desktop", "server"], cwd=target, start_new_session=True,
                     stdout=log, stderr=subprocess.STDOUT,
                     env={**os.environ, **_py_env(), "GOLEM_NO_DIALOG": "1"})
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
