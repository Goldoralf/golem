# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que l'installateur fait SOUS LINUX (docs/installer.md §3) — le code d'avant le 2026-10-02,
déplacé tel quel derrière l'interface commune (installer/server.py choisit le module, une seule fois).

L'interface, la même pour platform_windows.py :
  NAME, PRIVILEGE ('sudo' | 'uac'), STEPS, default_dir()
  checks(), reaper_detect(src), reaper_install(ctx), sizes(src, target), ui()
  sudo_check(pw, dry), job_env(env, S), keepalive(ctx)        (PRIVILEGE == 'sudo' seulement)
  run_step(sid, ctx), open_url(url)
`ctx` porte l'état et les outils du serveur : ctx.S, ctx.run(cmd, step, cwd, extra_env), ctx.log,
ctx.dry_cmd(name), ctx.wait_bridge(secs).
"""
import grp
import json
import os
import pwd
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time

NAME = "linux"
PRIVILEGE = "sudo"
UNINSTALL = True          # le désinstallateur graphique (server.py --uninstall, docs/uninstall.md §4) existe ici
RECEIPT = True            # le reçu d'installation (docs/uninstall.md §2) : Linux et Windows (§9.2)
DEFAULT_REPO = os.environ.get("GOLEM_REPO", "https://github.com/Goldoralf/golem.git")

STEPS = [
    ("source", "Copy golem to its folder"),
    ("system", "System packages, real-time, Reaper, plugins, bridge, sounds"),
    ("profile", "Launchers: golem and golem server"),
    ("start", "Start the rack"),
]


# LES PHASES de l'écran Install (installer/phases.py) : ce que l'utilisateur lit, et leur durée MESURÉE — install
# complète dans la VM Ubuntu 24.04, 6 cœurs, packs di+piano+guitar, 2026-10-23 : 28 min. Les phases de « system »
# s'ouvrent sur les marqueurs `mark phase …` de provision/install.sh.
BUILD_CORES = 6           # les cœurs de la mesure : la compilation va plus vite à 12, plus lentement à 4
# deux installs VM : 1,85 Mo/s puis 5,1 Mo/s (2026-10-23, extraction comprise) — le réseau varie du simple au triple.
# Ce débit ne sert qu'AVANT : pendant les sons, fetch-assets.sh dit les Mo téléchargés et l'écran prend le débit réel.
SOUNDS_MB_S = 3.0


def phases(S):
    try:
        cores = os.cpu_count() or BUILD_CORES
    except Exception:
        cores = BUILD_CORES
    f = max(0.6, min(2.0, BUILD_CORES / cores))
    sz = sizes(S["src"] or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), S["dir"])
    mb = sum(sz["packs"].get(p, 0) for p in S["packs"])
    gb = f"about {mb / 1024:.1f} GB" if mb >= 1024 else f"about {mb} MB"
    return [
        {"id": "source", "step": "source", "label": "Copy golem to its folder", "est": 5},
        {"id": "packages", "step": "system", "label": "System packages", "est": 150, "learn": False},   # 124 à 220 s : le miroir apt
        {"id": "realtime", "step": "system", "label": "Real-time audio and permissions", "est": 11},
        {"id": "reaper", "step": "system", "label": "REAPER, the audio engine", "est": 10},
        {"id": "plugins", "step": "system", "label": "Ready-made plugins", "est": 85},
        # PRÉCOMPILÉS (Goldoralf/golem-binaries, 2026-10-23) : 18 Mo + leurs bibliothèques, ~30 s. Un plugin qu'il faut
        # compiler (binaire indisponible) ajoute sa durée mesurée par `@@est-add` (provision/lib-prebuilt.sh compiling) ;
        # compilés, les 4 faisaient 756 s à 6 cœurs
        {"id": "build", "step": "system", "label": "Plugins built for golem", "est": round(30 * (0.5 + 0.5 * f))},
        {"id": "golem", "step": "system", "label": "golem itself", "est": 25},
        {"id": "sounds", "step": "system", "label": f"Sounds — {gb}" if mb else "Sounds", "est": round(mb / SOUNDS_MB_S),
         "learn": False},
        {"id": "profile", "step": "profile", "label": "Shortcuts: golem and golem Server", "est": 5},
        {"id": "start", "step": "start", "label": "First start", "est": 30},
    ]


# le ↻ Try again d'un manque non fatal (`soft_fail <id>` dans provision/install.sh) : le script qui l'installe, seul
RETRY = {"zconvo": ("sudo", "install-zconvo.sh"), "nam": ("sudo", "install-nam.sh"), "sfizz": ("sudo", "install-sfizz.sh"),
         "prisma": ("sudo", "install-prisma.sh"), "spectral": ("sudo", "install-spectral.sh"),
         "airwindows": ("python", "airwindows.py")}


def run_retry(rid, ctx):
    how, script = RETRY[rid]
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("retry-" + rid), "retry")
    path = os.path.join(ctx.S["dir"], "provision", script)
    cmd = ["sudo", "-A", path] if how == "sudo" else [sys.executable, path]
    return ctx.run(cmd, "retry", cwd=ctx.S["dir"])


def default_dir():
    return os.path.expanduser("~/golem")


def ui():
    """Les phrases d'écran qui dépendent du système : l'écran n'invente rien, il lit ceci."""
    return {
        "os_label": "Linux",
        "checks_intro": "golem runs on Linux with a real-time audio setup (tested on " + TESTED_LABEL + "). Red lines with a ⛔ stop the install; orange ones only warn.",
        "reaper_platform": "Linux x86_64",
        "reaper_install_note": "official tarball from reaper.fm, checksum verified, unpacked in ~/opt/REAPER — no admin rights needed",
        "reaper_update_note": "Settings ▸ Licenses ▸ Reaper can move the engine to the tested version.",
        "launcher_done": "golem in your applications menu (right-click: golem server, Stop golem) — and the golem command",
        # un seul bouton de fin, comme Windows et macOS : lance `golem desktop` puis ferme l'installateur (finish)
        "finish": "Open golem",
        "next": [
            ["warn", "Restart the computer once", " if the install just gave you the real-time audio rights: they apply after a restart — without it, dropouts."],
            ["", "Settings ▸ Soundcard", ": plug your audio interface, the app adopts it and you name its inputs."],
            ["", "Settings ▸ Calibration", ": the pedalboard (FCB1010) and your MIDI pedals."],
        ],
        # la page « Before you start » (2026-10-23) : la durée vient de phases(), ces phrases disent d'où elle vient
        "before": {
            "measured": "Measured on a 6-core computer with a good connection — a slower one takes longer. The install "
                        "downloads the plugins and the sounds you choose, and builds a few plugins on this computer.",
            "not_before_gig": "Not before a gig: the first start needs a restart of the computer, and a check with your instrument.",
        },
        "done_note": "Your password was not kept. The ⚡ CPU boost and Wi-Fi switching work through two narrow passwordless rules written during the install.",
    }


# ── vérifications préalables (écran 1) ────────────────────────────────────────────────
def os_release():
    d = {}
    try:
        for ln in open("/etc/os-release"):
            k, _, v = ln.strip().partition("=")
            d[k] = v.strip('"')
    except Exception:
        pass
    return d


def mem_gb():
    try:
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemTotal:"):
                return round(int(ln.split()[1]) / 1024 / 1024, 1)
    except Exception:
        pass
    return None


def free_mb(path):
    p = path
    while p and not os.path.isdir(p):
        p = os.path.dirname(p)
    try:
        st = os.statvfs(p or "/")
        return int(st.f_bavail * st.f_frsize / 1024 / 1024)
    except Exception:
        return None


def has_internet(host="www.reaper.fm", port=443, timeout=3):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except Exception:
        return False


# Les systèmes où l'install a été MENÉE jusqu'au bout (2026-11-03) : Ubuntu 24.04 (la référence, VM), 26.04 (un
# portable neuf), Debian 13 et Linux Mint 22 (VM, provision/vm/vm.sh GOLEM_VM_DISTRO). (ID, préfixe de VERSION_ID)
TESTED = (("ubuntu", "24.04"), ("ubuntu", "26.04"), ("debian", "13"), ("linuxmint", "22"))
TESTED_LABEL = "Ubuntu 24.04 and 26.04, Debian 13 and Linux Mint 22"


def tested(osr):
    return any(osr.get("ID") == i and osr.get("VERSION_ID", "").startswith(v) for i, v in TESTED)


def checks():
    osr = os_release()
    known = tested(osr)
    # golem doit s'installer sur N'IMPORTE QUEL Linux (décision du 2026-11-03) ; les voies testées sont TESTED. Ce qui
    # BLOQUE n'est pas la version mais le gestionnaire de paquets : install.sh parle apt (Ubuntu, Debian, Mint, Pop!_OS…).
    # Une autre version ou une autre distribution apt est ORANGE — un paquet absent y est écarté et dit
    # (provision/lib-packages.sh) ; sans apt, l'install mourrait en phase 1 : rouge, avec la raison.
    apt = shutil.which("apt-get") is not None
    pretty = osr.get("PRETTY_NAME") or "unknown Linux"
    arch = os.uname().machine
    mem = mem_gb()
    net = has_internet()
    home_free = free_mb(os.path.expanduser("~"))
    return [
        {"id": "os", "label": "Linux system", "ok": known, "blocking": not apt,
         "detail": pretty + ("" if known else
                             " — golem is tested on " + TESTED_LABEL + "; it installs here too, and says what does not"
                             if apt else
                             " — golem's Linux install uses apt (Ubuntu, Debian, Mint, Pop!_OS…); this system has none")},
        {"id": "arch", "label": "64-bit x86", "ok": arch == "x86_64", "blocking": True,
         "detail": arch + ("" if arch == "x86_64" else " — Reaper and the neural plugins ship for x86_64 only")},
        {"id": "mem", "label": "Memory", "ok": bool(mem and mem >= 7.5), "blocking": False,
         "detail": (f"{mem} GB" if mem else "?") + ("" if mem and mem >= 7.5 else " — 8 GB recommended (NAM + Vital + Salamander)")},
        {"id": "disk", "label": "Free space in your home", "ok": bool(home_free and home_free >= 4000), "blocking": False,
         "detail": (f"{home_free / 1024:.1f} GB free" if home_free else "?") + ("" if home_free and home_free >= 4000 else " — 4 GB minimum without the optional sound packs")},
        {"id": "net", "label": "Internet", "ok": net, "blocking": True,
         "detail": "reaper.fm reachable" if net else "no route — Reaper, plugins and sounds are downloaded during the install"},
        {"id": "sudo", "label": "Administrator rights (sudo)", "ok": shutil.which("sudo") is not None, "blocking": True,
         "detail": "sudo present — your password is asked once, in the install screen" if shutil.which("sudo") else "sudo is missing"},
        {"id": "python", "label": "Python 3", "ok": sys.version_info >= (3, 10), "blocking": True,
         "detail": sys.version.split()[0]},
    ]


# ── Reaper (écran 2) ──────────────────────────────────────────────────────────────────
def reaper_pinned(src):
    try:
        t = open(os.path.join(src, "provision", "install-reaper.sh")).read()
        m = re.search(r'REAPER_VERSION="\$\{REAPER_VERSION:-([\d.]+)\}"', t)
        return m.group(1) if m else None
    except Exception:
        return None


def reaper_detect(src):
    cands = [os.path.expanduser("~/opt/REAPER/reaper"), shutil.which("reaper") or "", "/opt/REAPER/reaper"]
    path = next((c for c in cands if c and os.path.isfile(c)), None)
    version = None
    if path:
        for probe in (os.path.join(os.path.dirname(path), "whatsnew.txt"),):
            try:
                first = open(probe, errors="ignore").readline()
                m = re.search(r"v?(\d+\.\d+)", first)
                if m:
                    version = m.group(1)
                    break
            except Exception:
                pass
    return {"found": bool(path), "path": path, "version": version, "pinned": reaper_pinned(src),
            "download_url": "https://www.reaper.fm/download.php", "buy_url": "https://www.reaper.fm/purchase.php"}


def reaper_install(ctx):
    src = ctx.S["src"]
    return ctx.run([os.path.join(src, "provision", "install-reaper.sh")], "reaper", cwd=src)


# ── taille (écran 4) ──────────────────────────────────────────────────────────────────
def manifest(src):
    try:
        with open(os.path.join(src, "provision", "components.json")) as f:
            return [c for c in json.load(f).get("components", []) if isinstance(c, dict)]
    except Exception:
        return []


PACK_LABELS = {"di": "golem reference DIs (guitar, bass) — for the preset previews",
               "piano": "Salamander grand piano", "drums": "The Aasimonster drum kit (multi-mic)",
               "guitar": "Shinyguitar — the gypsy rhythm guitar of the Standard block"}


def sizes(src, target_dir):
    comps = manifest(src)
    packs, required = {}, []
    for c in comps:
        if c.get("pack"):
            packs[c["pack"]] = packs.get(c["pack"], 0) + int(c.get("mb") or 0)
            if c.get("required") and c["pack"] not in required:
                required.append(c["pack"])           # le pack DI : toujours pris, pas une case à cocher
    plugins = sum(int(c.get("mb") or 0) for c in comps if c.get("kind") == "plugin" and not c.get("pack"))
    fixed = {"system": 900, "reaper": 40, "plugins": plugins + 250, "bridge": 350, "repo": 60}
    return {"fixed": fixed, "packs": packs, "required_packs": required, "free_mb": free_mb(target_dir),
            "fixed_labels": [["system", "System packages (audio, plugins, tools)"], ["reaper", "Reaper"],
                             ["plugins", "Neural plugins (NAM, AIDA-X, Ratatouille…)"], ["bridge", "golem bridge (Python)"],
                             ["repo", "golem code"]],
            "pack_labels": PACK_LABELS, "packs_unavailable": {}}


# ── sudo : vérifier, garder en mémoire, askpass sans fichier de mot de passe ──────────
_ASKPASS_DIR = None
# le dossier où naît l'askpass : /tmp par défaut ; le désinstallateur le met dans SA copie de /tmp
# (installer/uninstaller.py), sinon le moteur verrait un `golem-installer-*` parmi les restes à effacer
ASKPASS_BASE = None


def _real_sudo(path=None):
    """Le VRAI sudo, résolu dans un PATH qui ne contient pas le shim (sinon le shim s'appellerait en boucle)."""
    parts = [d for d in (path if path is not None else os.environ.get("PATH", "")).split(os.pathsep)
             if d and not (_ASKPASS_DIR and os.path.abspath(d) == os.path.abspath(_ASKPASS_DIR))]
    return shutil.which("sudo", path=os.pathsep.join(parts))


def _askpass():
    """Un helper askpass qui imprime $GOLEM_SUDO_PW — le mot de passe vit dans l'ENVIRONNEMENT du
    job, jamais sur le disque. À côté, dans le même dossier 0700, un SHIM `sudo` (job_env le met en tête du PATH).

    sudo-rs (Ubuntu 25.10+, /usr/bin/sudo → /usr/lib/cargo/bin/sudo) N'UTILISE SUDO_ASKPASS QU'AVEC -A, quand le
    sudo classique s'en sert de lui-même faute de terminal. Portable Ubuntu 26.04, 2026-11-03 : `sudo -v` de
    install.sh demandait le mot de passe sur le terminal qui avait lancé ./install-linux.sh, l'écran disait « Nothing
    new for 3 min » — et lancé d'une icône, sans terminal, l'install restait bloquée pour toujours. Le shim ajoute -A
    à TOUS les sudo des scripts (bash, Python, tiers) sans qu'on puisse en oublier un ; -A est compris par les deux."""
    global _ASKPASS_DIR
    if _ASKPASS_DIR and os.path.isfile(os.path.join(_ASKPASS_DIR, "askpass")):
        return os.path.join(_ASKPASS_DIR, "askpass")
    real = _real_sudo()                     # résolu UNE fois, avant que le dossier du shim n'existe
    _ASKPASS_DIR = tempfile.mkdtemp(prefix="golem-installer-", **({"dir": ASKPASS_BASE} if ASKPASS_BASE else {}))
    os.chmod(_ASKPASS_DIR, 0o700)
    p = os.path.join(_ASKPASS_DIR, "askpass")
    with open(p, "w") as f:
        f.write('#!/bin/sh\nprintf "%s\\n" "$GOLEM_SUDO_PW"\n')
    os.chmod(p, 0o700)
    if real:
        shim = os.path.join(_ASKPASS_DIR, "sudo")
        with open(shim, "w") as f:
            # chemin ABSOLU du vrai sudo, écrit en dur : jamais un `sudo` nu, qui rappellerait ce shim
            f.write("#!/bin/sh\n# golem installer : -A pour sudo-rs (installer/platform_linux.py _askpass)\n"
                    "exec %s -A \"$@\"\n" % shlex.quote(real))
        os.chmod(shim, 0o700)
    return p


def cleanup():
    """Retire le dossier de l'askpass quand l'installateur se ferme (docs/uninstall.md §8 : il restait dans /tmp).
    Le mot de passe n'y a jamais été écrit, mais un dossier `golem-installer-*` orphelin par installation, c'est
    une trace de plus. Appelé par server.py à chaque sortie (bouton, fenêtre, Ctrl-C, signal) ; idempotent."""
    global _ASKPASS_DIR
    d, _ASKPASS_DIR = _ASKPASS_DIR, None
    if d:
        shutil.rmtree(d, ignore_errors=True)


def _receipt_root(ctx, target):
    """Reçu d'install (docs/uninstall.md §2) : le dossier d'installation, dès que la source y est. Jamais fatal."""
    rp = os.path.join(target, "provision", "receipt.py")
    if ctx.S["dry"] or not os.path.isfile(rp):
        return
    try:
        subprocess.run([sys.executable, rp, "set-root", target], capture_output=True, timeout=20)
    except Exception:
        pass


def job_env(env, S):
    if S["sudo_pw"]:
        env["SUDO_ASKPASS"] = _askpass()
        env["GOLEM_SUDO_PW"] = S["sudo_pw"]
        if os.path.isfile(os.path.join(_ASKPASS_DIR, "sudo")):
            rest = [d for d in env.get("PATH", os.defpath).split(os.pathsep) if d and d != _ASKPASS_DIR]
            env["PATH"] = os.pathsep.join([_ASKPASS_DIR] + rest)      # le shim d'abord (sudo -A, cf. _askpass)
    env["DEBIAN_FRONTEND"] = "noninteractive"
    return env


def sudo_check(pw, dry):
    if dry:
        return pw == "golem" or len(pw) > 0, None if pw else "empty password"
    try:
        r = subprocess.run(["sudo", "-k", "-S", "-p", "", "-v"], input=pw + "\n", capture_output=True, text=True, timeout=20)
        return r.returncode == 0, (r.stderr.strip() or None) if r.returncode else None
    except Exception as e:
        return False, str(e)


def keepalive(ctx):
    while ctx.S["sudo_pw"] and not ctx.S["done"]:
        try:
            subprocess.run(["sudo", "-A", "-n", "-v"], env=ctx.job_env(), capture_output=True, timeout=20)
        except Exception:
            pass
        time.sleep(50)


# ── les étapes ────────────────────────────────────────────────────────────────────────
def step_source(ctx, src, target):
    src = os.path.abspath(src); target = os.path.abspath(target)
    if src == target:
        ctx.log("→ installing in place (the installer runs from the target folder)", "source")
        return 0
    if os.path.isdir(os.path.join(target, "provision")):
        ctx.log(f"→ {target} already holds golem — kept, updated from the installer's copy", "source")
    os.makedirs(os.path.dirname(target) or "/", exist_ok=True)
    if ctx.S["dry"]:
        return ctx.run(ctx.dry_cmd("source"), "source")
    if os.path.isdir(os.path.join(src, ".git")) and shutil.which("git"):
        if os.path.isdir(os.path.join(target, ".git")):
            rc = ctx.run(["git", "-C", target, "pull", "--ff-only", src], "source")
        else:
            rc = ctx.run(["git", "clone", "--quiet", src, target], "source")
            if rc == 0:
                ctx.run(["git", "-C", target, "remote", "set-url", "origin", DEFAULT_REPO], "source")
        return rc
    # archive extraite (bootstrap sans git) : copie ; `git` arrive avec les paquets, l'update recréera le dépôt
    rc = ctx.run(["rsync", "-a", "--exclude", ".venv", src + "/", target + "/"], "source") if shutil.which("rsync") \
        else ctx.run(["cp", "-a", src + "/.", target + "/"], "source")
    return rc


def ensure_git_repo(ctx, target, src):
    """UNE INSTALL VENUE D'UNE ARCHIVE DEVIENT UN DÉPÔT GIT (2026-11-06). Sans git (une Ubuntu neuve n'en a pas), le
    bootstrap télécharge l'archive de la release, et un dossier sans .git ne pouvait JAMAIS se mettre à jour par
    System ▸ About (« Update to … » vit de `git fetch --tags` / `git checkout <tag>`). git arrive avec les paquets
    système (provision/packages.txt) : juste après, le dossier devient le dépôt de la release installée — le tag seul,
    profondeur 1, `git reset` qui aligne l'index sans toucher aux fichiers, puis ce qu'une archive aurait omis. La
    version se lit dans le nom du cache du bootstrap (golem-<tag>). Jamais fatal : au pire, la mise à jour passe par
    l'archive de la release (bridge/release_update)."""
    if ctx.S["dry"] or os.path.isdir(os.path.join(target, ".git")) or not shutil.which("git"):
        return
    base = os.path.basename(os.path.abspath(src or ""))
    ref = base[len("golem-"):] if base.startswith("golem-") else ""
    # le zip « Source code » d'une release GitHub s'extrait dans golem-0.6.1, SANS le v du tag
    if re.fullmatch(r"\d+(\.\d+)+", ref):
        ref = "v" + ref
    if not ref:
        ctx.log("→ not a git checkout and no release name — System ▸ About updates from the release archives", "system")
        return
    tag = ref.startswith("v")
    steps = [["-c", "init.defaultBranch=main", "init", "-q"], ["remote", "add", "origin", DEFAULT_REPO],
             ["fetch", "-q", "--depth", "1", "origin", f"refs/tags/{ref}:refs/tags/{ref}" if tag else ref],
             ["reset", "-q", ref if tag else "FETCH_HEAD"]]
    for args in steps:
        if ctx.run(["git", "-C", target, *args], "system") != 0:
            shutil.rmtree(os.path.join(target, ".git"), ignore_errors=True)   # pas de dépôt à moitié fait
            ctx.log("→ could not link this folder to the golem repository — System ▸ About will update it from the "
                    "release archives instead (the install itself is fine)", "system")
            return
    gone = subprocess.run(["git", "-C", target, "ls-files", "-d", "-z"], capture_output=True, text=True).stdout
    gone = [g for g in gone.split("\0") if g]
    if gone:
        ctx.run(["git", "-C", target, "checkout", "-q", "--", *gone], "system")
    ctx.log(f"✓ linked to the golem repository at {ref} — updates come from System ▸ About", "system")


def step_profile(ctx, target):
    """Les deux lanceurs (golem desktop / golem server), toujours posés (docs/installer.md §4, FIXÉ 2026-10-16).
    Plus de « boîte dédiée » ici : démarrer avec l'ordinateur et verrouiller la machine sont des gestes de l'app
    (System ▸ Dashboard), jamais un choix d'installation."""
    S = ctx.S
    ctx.write_engine(target)                     # écran Engine (coquille : Reaper seul sélectionnable)
    ctx.write_first_run(target)                  # écran « What do you play? » (bridge/first_run.py)
    if S["dry"]:
        return ctx.run(ctx.dry_cmd("profile"), "profile")
    return ctx.run([os.path.join(target, "provision", "install-desktop.sh")], "profile", cwd=target)


# ── l'écran Done : « Continue on a tablet » (installer/server.py tablet_start) ───────────────────────────────────────
# golem tourne déjà (étape « start ») ; s'il ne répond plus, `golem server` le relance SANS fenêtre, détaché.
def bridge_start(ctx):
    """Lance golem server ; rend None (la page attend qu'il réponde) ou la raison d'un échec immédiat."""
    launcher = os.path.join(ctx.S["dir"], "provision", "golem")
    if not os.path.isfile(launcher):
        return "golem is not installed in " + ctx.S["dir"]
    subprocess.Popen([launcher, "server"], cwd=ctx.S["dir"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    return None


def run_step(sid, ctx):
    S = ctx.S
    src, target = S["src"], S["dir"]
    if sid == "source":
        rc = step_source(ctx, src, target)
        if rc == 0:
            _receipt_root(ctx, os.path.abspath(target))
        return rc
    if sid == "system":
        if S["dry"]:
            return ctx.run(ctx.dry_cmd("system"), sid)
        args = [os.path.join(target, "provision", "install.sh")]
        if not S["packs"]:
            args.append("--light")                  # rien à télécharger : dev
        rc = ctx.run(args, sid, cwd=target, extra_env={"GOLEM_PACKS": ",".join(S["packs"])})
        if rc == 0:
            ensure_git_repo(ctx, target, src)       # git vient d'arriver avec les paquets : la mise à jour depuis About
        return rc
    if sid == "profile":
        return step_profile(ctx, target)
    if sid == "start":
        if S["dry"]:
            return ctx.run(ctx.dry_cmd("start"), sid)
        rc = ctx.run([os.path.join(target, "provision", "start.sh")], sid, cwd=target)
        if rc == 0:
            rc = 0 if ctx.wait_bridge(90) else 1
            ctx.log("✓ bridge answers on :8770" if rc == 0 else "✗ the bridge did not answer within 90 s — see /tmp/golem-bridge.log", sid)
        return rc
    return 1


def finish(ctx):
    """« Open golem » de l'écran Done : `golem desktop`, exactement comme l'icône — l'app dans SA fenêtre Chromium,
    pas un onglet. Avant (portable Ubuntu 26.04, 2026-11-03) Linux n'avait pas de finish : le bouton ouvrait
    /app/ dans le navigateur et l'installateur restait ouvert. DÉTACHÉ (nouvelle session, sans nos tuyaux) : il
    survit à l'installateur, qui se ferme quand golem répond (server.py /api/finish)."""
    if ctx.S["dry"]:
        ctx.log("(dry run) golem would start now", None)
        return True
    launcher = os.path.join(ctx.S["dir"], "provision", "golem")
    if not os.path.isfile(launcher):
        return False
    env = {k: v for k, v in os.environ.items() if k not in ("SUDO_ASKPASS", "GOLEM_SUDO_PW", "GOLEM_INSTALLER")}
    # jamais le shim sudo de l'installateur (-A sans askpass casserait les sudo de golem : net.sh, autostart…)
    if _ASKPASS_DIR:
        env["PATH"] = os.pathsep.join(d for d in env.get("PATH", os.defpath).split(os.pathsep)
                                      if d and os.path.abspath(d) != os.path.abspath(_ASKPASS_DIR))
    subprocess.Popen([launcher, "desktop"], cwd=ctx.S["dir"], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True


# ── LE REDÉMARRAGE DE FIN (2026-11-03, portable Ubuntu 26.04) ──────────────────────────────────────────────────────
# install.sh ajoute l'utilisateur au groupe `audio` et pose ses limites temps réel : elles ne valent que pour une
# NOUVELLE session. « Log out and back in » ne suffisait pas : le bridge et le REAPER que l'installateur a lancés (écran
# Connect, setsid nohup) SURVIVENT à la déconnexion, et `golem desktop` les réutilise ensuite (« déjà actif ») — un
# REAPER sans rtprio, du son qui craque. D'où : on le dit seulement quand c'est vrai, on propose de redémarrer, et on
# arrête d'abord ce que l'installateur a démarré (docs/pitfalls/install.md).
def restart_needed():
    """Vrai si l'utilisateur est membre de `audio` dans /etc/group mais que CETTE session (le processus de
    l'installateur, lancé avant l'install) ne porte pas encore ce groupe. Déjà dans audio avant : rien à redémarrer."""
    try:
        g = grp.getgrnam("audio")
        me = pwd.getpwuid(os.getuid())
    except KeyError:
        return False
    member = me.pw_name in g.gr_mem or me.pw_gid == g.gr_gid
    return member and g.gr_gid not in os.getgroups()


def stop_golem(ctx):
    """`golem stop` : le bridge et REAPER que l'installateur a démarrés ne doivent pas survivre à la session."""
    if ctx.S["dry"]:
        ctx.log("(dry run) golem would stop now", None)
        return
    launcher = os.path.join(ctx.S["dir"], "provision", "golem")
    if os.path.isfile(launcher):
        try:
            subprocess.run([launcher, "stop"], cwd=ctx.S["dir"], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=60)
        except Exception:
            pass


def restart(ctx):
    """« Restart now » : golem arrêté, puis `systemctl reboot` — sans sudo depuis une session graphique (logind/polkit
    l'accorde à la session active). (ok, raison) ; un refus (autre session ouverte…) est dit, jamais avalé."""
    stop_golem(ctx)
    if ctx.S["dry"]:
        ctx.log("(dry run) the computer would restart now", None)
        return True, None
    try:
        r = subprocess.run(["systemctl", "reboot"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return False, str(e)
    return r.returncode == 0, (r.stderr.strip() or None) if r.returncode else None


def open_url(url):
    """Un lien EXTERNE (TONE3000, docs…) : le navigateur par défaut, un onglet suffit."""
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── L'INSTALLATEUR DANS SA FENÊTRE (2026-11-03, portable Ubuntu 26.04 / GNOME Wayland / Firefox snap) ────────────────
# Avant : xdg-open seul. L'URL partait en ONGLET dans le Firefox déjà ouvert, et GNOME (Wayland) ne passe pas au
# premier plan une fenêtre qu'un autre programme réveille : l'onglet existait, derrière le terminal, et le terminal
# disait « open this link » — l'utilisateur cliquait à la main. Une NOUVELLE fenêtre d'un NOUVEAU processus, elle,
# arrive devant. D'où, comme Windows et macOS : un Chromium `--app` (même ordre que provision/golem), sinon Firefox en
# nouvelle instance sur un profil dédié, sinon xdg-open. Profil DÉDIÉ dans les deux cas : le processus est le nôtre et
# vit autant que la fenêtre, ce qui permet au serveur de s'arrêter quand on la ferme (server.py close_with_window).
APP_W, APP_H = 1120, 780
CHROMIUMS = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser")
# premier lancement d'un profil Firefox neuf : ni page d'accueil, ni bandeau des données, ni « navigateur par défaut ? »
FIREFOX_PREFS = {
    "browser.aboutwelcome.enabled": False,
    "browser.shell.checkDefaultBrowser": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "trailhead.firstrun.didSeeAboutWelcome": True,
    "browser.tabs.warnOnClose": False,
    "browser.sessionstore.resume_from_crash": False,
    # une FENÊTRE d'application, comme le `--app` de Chromium : le profil lit son userChrome.css (FIREFOX_CHROME)
    "toolkit.legacyUserProfileCustomizations.stylesheets": True,
    "browser.tabs.inTitlebar": 0,
}
# ni onglets, ni barre d'adresse, ni barre de favoris : la page seule, dans sa fenêtre (décision du 2026-11-03 : « une vraie
# fenêtre d'installation comme sous Windows »). Ce profil ne sert qu'à l'installateur : rien de l'utilisateur n'y vit.
FIREFOX_CHROME = """#TabsToolbar, #nav-bar, #PersonalToolbar, #titlebar, #sidebar-box, #sidebar-main,
#notifications-toolbar, .browserContainer > findbar { visibility: collapse !important; }
"""


def _profile_dir(name, exe=None):
    """Le profil dédié du navigateur `name`. Un navigateur en SNAP ne peut écrire ni dans ~/.local ni dans aucun
    dossier caché du home (interface `home`) : son profil va sous ~/snap/<nom>/common, qu'il possède. Même règle
    que provision/golem (appdir) : le binaire mène à /usr/bin/snap, ou /snap/<nom> existe."""
    snap = "chromium" if name.startswith("chromium") else name
    real = os.path.realpath(exe) if exe else ""
    if real == "/usr/bin/snap" or os.path.isdir(f"/snap/{snap}"):
        return os.path.expanduser(f"~/snap/{snap}/common/golem-installer")
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "golem", "installer-browser", name)


def _app_browser():
    """(nom, exécutable) du navigateur de la fenêtre : GOLEM_BROWSER, un Chromium, Firefox — ou None."""
    override = os.environ.get("GOLEM_BROWSER")
    if override:
        exe = shutil.which(override)
        return (os.path.basename(override), exe) if exe else None
    for name in CHROMIUMS + ("firefox",):
        exe = shutil.which(name)
        if exe:
            return name, exe
    return None


def _write_firefox_profile(profile):
    """user.js (premier lancement muet, feuilles de style du profil) et chrome/userChrome.css (fenêtre nue)."""
    lines = [f"user_pref({json.dumps(k)}, {json.dumps(v)});" for k, v in FIREFOX_PREFS.items()]
    with open(os.path.join(profile, "user.js"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.makedirs(os.path.join(profile, "chrome"), exist_ok=True)
    with open(os.path.join(profile, "chrome", "userChrome.css"), "w", encoding="utf-8") as f:
        f.write(FIREFOX_CHROME)


def open_app(url):
    """L'installateur dans SA fenêtre, au premier plan. Rend le processus de la fenêtre, ou None (onglet xdg-open)."""
    found = _app_browser()
    if found is None:
        open_url(url)
        return None
    name, exe = found
    profile = _profile_dir(name, exe)
    try:
        os.makedirs(profile, exist_ok=True)
    except OSError:
        open_url(url)
        return None
    if "firefox" in name:
        _write_firefox_profile(profile)
        argv = [exe, "--new-instance", "--profile", profile, "--width", str(APP_W), "--height", str(APP_H), url]
    else:
        argv = [exe, f"--app={url}", f"--user-data-dir={profile}", f"--window-size={APP_W},{APP_H}",
                "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"]
    try:
        return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        open_url(url)
        return None


def close_app(window):
    window.terminate()
