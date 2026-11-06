#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le moteur de désinstallation de golem (docs/uninstall.md §3, §5) — bibliothèque standard SEULEMENT : il tourne
avec le python3 du système, sans le venv de golem (qu'il va justement supprimer).

    python3 provision/uninstall.py plan [--root DIR] [--json]
    python3 provision/uninstall.py run --items ID… | --select FILE [--yes] [--json] [--log FILE]

`plan` ne touche à RIEN : il lit le reçu d'installation (~/.local/share/golem/install-receipt.json, §2) et la
machine, et liste chaque élément qu'il toucherait — id, groupe, libellé, chemins, privilège, origine
(`receipt` · `golem-named` · `unknown`), choix par défaut, raison, action. Seuls les éléments PRÉSENTS sur la
machine sont listés ; les éléments du reçu qui n'existent plus vont dans `absent` (ids du reçu), jamais dans
`items` — ils sont considérés comme faits et sortent du reçu réécrit.

Sans reçu (machine installée avant le reçu, install à la main) : seul ce qui est à golem PAR SON NOM est coché
(golem-*, le dossier d'install, les liens REAPER qui pointent DANS ce dossier) ; ce qui est partagé est listé
`unknown` et décoché ; apt n'est PAS proposé du tout — deviner là, c'est perdre son pipewire.

`run` exécute exactement les ids choisis, dans l'ordre du §5 (1 la sauvegarde est faite par l'appelant ;
2 arrêt du moteur ; 3 une seule passe root, puis les paquets apt et leurs dépendances ; 4 REAPER ; 5 plugins,
toolchain, intégration utilisateur ; 6 le dossier d'install EN DERNIER ; 7 le reçu).

APT (§3) : les éléments sont les paquets que golem a demandés EXPLICITEMENT — apt.requested ∩ apt.added (et les
.deb), ou, pour un reçu d'avant apt.requested, apt.added ∩ « manuels » (/var/lib/apt/extended_states, ce que lit
`apt-mark showmanual`). Le reste de apt.added = les dépendances : jamais des éléments ; au `run`, après la purge
des explicites choisis, `apt-get -s autoremove --purge` ∩ apt.added est purgé (jamais un autoremove nu : il
retirerait des paquets automatiques d'avant golem). Chaque purge est d'abord SIMULÉE : un paquet dont la purge
emporterait un paquet d'avant golem sort du lot, gardé, avec sa raison. Un élément qui échoue n'arrête pas les autres. Une ligne de journal
par action ; avec --json, une ligne JSON par action sur stdout : {"step", "item", "ok", "msg"}.

Le dossier d'install n'est JAMAIS supprimé si le répertoire courant ou ce script vit dedans : l'interface
graphique se copie d'abord dans /tmp (docs/uninstall.md §4).

GARDE-FOUS : on ne supprime qu'un chemin de l'ensemble attendu (calculé ici, jamais lu dans la sélection) ;
jamais /, $HOME, /etc, /usr… ; jamais à travers un lien symbolique (on supprime le LIEN, pas sa cible) ;
`--root-fs PREFIX` (ou GOLEM_UNINSTALL_FSROOT) préfixe chaque chemin absolu pour que les tests travaillent
sur un faux système de fichiers — dans ce mode les commandes système sont SIMULÉES (seul `sh` s'exécute,
sans sudo). Toutes les commandes passent par `run_command`, que les tests remplacent.
"""
import argparse
import datetime
import fnmatch
import glob
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

RECEIPT = "~/.local/share/golem/install-receipt.json"
SHARE_DIR = "~/.local/share/golem"
REAPER_DIR = "~/.config/REAPER"

# dossiers que l'install peut créer pour y poser des fichiers ; retirés en fin de désinstallation s'ils sont VIDES
# (du plus profond au moins profond : un parent vidé par son enfant part au même passage)
CONTAINER_DIRS = ("~/.lv2", "~/.vst3", "~/.clap", "~/.vst/airwindows", "~/.vst", "~/opt/reaper-versions", "~/opt",
                  "~/.config/REAPER/UserPlugins", "~/.config/systemd/user", "~/.config/systemd",
                  "~/.local/share/icons/hicolor/512x512/apps", "~/.local/share/icons/hicolor/512x512",
                  "~/.local/share/icons/hicolor/180x180/apps", "~/.local/share/icons/hicolor/180x180",
                  "~/.cache/golem-build", "~/.gnome/apps", "~/.gnome", "~/.config/menus/applications-merged",
                  "~/.config/menus")

# l'intégration bureau que l'installeur de REAPER écrit (`install-reaper.sh --integrate-user-desktop`, via
# xdg-desktop-menu / xdg-icon-resource / xdg-mime) : elle part AVEC REAPER (élément reaper:app) — 3e cycle en VM,
# 2026-10-16 : icônes, entrée ~/.gnome/apps et paquet MIME restaient
REAPER_DESKTOP = ("~/.local/share/applications/cockos-reaper*.desktop", "~/.gnome/apps/cockos-reaper*.desktop",
                  "~/.local/share/icons/hicolor/*/apps/cockos-reaper*.png",
                  "~/.local/share/icons/hicolor/*/apps/cockos-reamote*.png",
                  "~/.local/share/mime/packages/application-x-reaper.xml",
                  "~/.local/share/mime/packages/cockos-reaper*.xml")
# les caches que les outils du bureau régénèrent à partir des entrées ci-dessus (et de celles de golem)
DESKTOP_CACHES = ("~/.local/share/applications/mimeinfo.cache", "~/.local/share/applications/defaults.list",
                  "~/.local/share/icons/hicolor/icon-theme.cache", "~/.local/share/mime",
                  "~/.config/menus/applications-merged/xdg-desktop-menu-dummy.menu")
# le dossier surveillé du bridge (bridge/inbox.py) : son défaut ; config/inbox.json du dossier d'install peut le déplacer
INBOX_DEFAULT = "~/golem-inbox"

GROUPS = ("golem", "reaper-links", "reaper-ini", "system", "dedicated", "plugins", "reaper", "apt", "toolchain")

# LA BASE DU SYSTÈME : jamais proposée, même si le reçu dit qu'apt l'a ajoutée (§3)
NEVER_APT = ("pipewire", "pipewire-*", "libpipewire*", "wireplumber", "libwireplumber*", "alsa-*", "alsa",
             "libasound2*", "pulseaudio-utils", "git", "git-*", "curl", "wget", "unzip", "python3", "python3-*",
             "network-manager", "avahi-daemon", "ufw", "build-essential")
# paquets « plugin audio » : cochés par défaut ; tout le reste (ffmpeg, jq, xvfb, dépendances de build) décoché
AUDIO_APT = ("*lv2*", "*plugins*", "*-plugin", "x42-*", "lsp-*", "calf-*", "guitarix*", "dragonfly-*", "zam-*",
             "sfizz*", "avldrums*", "drumgizmo*", "surge-xt", "proteus", "byod", "setbfree", "*ladspa*", "*vst*",
             "invada-*", "swh-*", "mda-*", "caps", "infamous-*")
# les paquets de COMPILATION que golem demande pour bâtir ses plugins (install-zconvo/nam/prisma/spectral.sh) : en-têtes
# et outils, rien ne joue avec. COCHÉS par défaut (2026-10-24) : ils n'existaient pas avant golem (seuls
# requested ∩ added deviennent des éléments) — la VM Linux en gardait une vingtaine, avec leurs ~500 dépendances.
# build-essential reste dans NEVER_APT (d'autres logiciels compilent avec).
BUILD_APT = ("*-dev", "cmake", "cmake-data", "pkg-config", "pkgconf", "pkgconf-bin")

# les plugins que golem pose ou compile (§3, groupe plugins) : (slug, libellé, chemins, à golem par son nom)
PLUGINS = (
    ("nam", "Neural Amp Modeler (patched)", ("~/.lv2/neural_amp_modeler.lv2",), False),
    ("zconvo", "zeroconvo convolver (fixed build)", ("~/.lv2/zeroconvo.lv2",), False),
    ("freeze", "golem Freeze", ("~/.clap/GoleM Freeze.clap", "~/.vst3/GoleM Freeze.vst3"), True),
    ("prisma", "Prisma", ("~/.vst3/Prisma.vst3",), False),
    ("spectral-compressor", "Spectral Compressor", ("~/.clap/Spectral Compressor.clap",
                                                     "~/.vst3/Spectral Compressor.vst3"), False),
    ("paulxstretch", "PaulXStretch", ("~/.vst3/PaulXStretch.vst3", "~/.clap/PaulXStretch.clap"), False),
    ("dexed", "Dexed", ("~/.vst3/Dexed.vst3",), False),
    ("aida-x", "AIDA-X", ("~/.lv2/AIDA-X.lv2",), False),
    ("ratatouille", "Ratatouille", ("~/.lv2/Ratatouille.lv2",), False),
    ("aether", "Aether", ("~/.lv2/aether.lv2",), False),
    ("tapedelay2", "Airwindows TapeDelay2", ("~/.vst/airwindows/TapeDelay2.so",), False),
)

# les fichiers système à golem PAR LEUR NOM : (motif, groupe, action, libellé)
SYSTEM_GLOBS = (
    ("/etc/sudoers.d/golem-*", "system", "remove", "sudo rule"),
    ("/usr/local/sbin/golem-*", "system", "remove", "root helper script"),
    ("/etc/systemd/system/golem-*.service", "system", "disable", "system service"),
    ("/etc/security/limits.d/95-golem-audio.conf", "system", "remove", "real-time limits"),
    ("/etc/NetworkManager/dnsmasq-shared.d/golem-*.conf", "system", "remove", "access point DNS file"),
    ("/etc/lightdm/lightdm.conf.d/50-golem.conf", "system", "remove", "old kiosk autologin"),
    ("/etc/ssh/sshd_config.d/golem-*.conf", "dedicated", "remove", "ssh hardening"),
    ("/etc/sysctl.d/90-golem-*.conf", "dedicated", "remove", "kernel setting"),
    ("/etc/udev/rules.d/90-golem-*.rules", "dedicated", "remove", "USB autosuspend rule"),
)
# les noms FIXES que l'install écrit sous ces motifs. Un dossier root illisible sans root (/etc/sudoers.d est en
# 0750 : 3e cycle en VM, 2026-10-16, les deux règles sudo étaient données pour « absentes » et restaient) ne se
# liste pas : ces noms-là, et ceux du reçu, y sont alors listés « présence inconnue » et retirés par `rm -f`.
GOLEM_FIXED_ROOT = ("/etc/sudoers.d/golem-net", "/etc/sudoers.d/golem-perf", "/usr/local/sbin/golem-net",
                    "/usr/local/sbin/golem-perf-mode", "/etc/systemd/system/golem-net.service",
                    "/etc/systemd/system/golem-perf.service", "/etc/security/limits.d/95-golem-audio.conf",
                    "/etc/NetworkManager/dnsmasq-shared.d/golem-name.conf", "/etc/lightdm/lightdm.conf.d/50-golem.conf",
                    "/etc/ssh/sshd_config.d/golem-harden.conf", "/etc/sysctl.d/90-golem-port80.conf",
                    "/etc/udev/rules.d/90-golem-usb-power.rules")
# les règles ufw que provision/harden.sh ajoute (OpenSSH n'est retiré que si le reçu prouve qu'il n'y était pas)
UFW_GOLEM_RULES = ("8770/tcp", "80/tcp", "5353/udp")
UFW_RECEIPT_ONLY = ("OpenSSH",)
# les commandes système qu'un script root peut lancer — simulées en mode --root-fs
SYS_CMDS = ("systemctl", "nmcli", "ufw", "loginctl", "gpasswd", "apt-get", "dpkg-query", "sysctl", "udevadm", "snap")

# les profils de navigateur DÉDIÉS d'un navigateur en snap (il ne peut écrire dans aucun dossier caché du home) :
# la fenêtre golem (provision/golem appdir) et celle de l'installateur (installer/platform_linux.py _profile_dir)
SNAP_PROFILES = ("~/snap/chromium/common/golem-browser", "~/snap/chromium/common/golem-installer",
                 "~/snap/firefox/common/golem-installer")

# l'ensemble ATTENDU : un chemin supprimé correspond à l'un de ces motifs (composant par composant), ou est le
# dossier d'install, ou est déclaré par le reçu (et passe quand même les interdits)
EXPECTED = (
    "~/.local/bin/golem", "~/.local/share/applications/golem*.desktop",
    "~/.local/share/icons/hicolor/*/apps/golem*.png", SHARE_DIR, SHARE_DIR + "/*",
    "~/.cache/golem-installer", "~/.cache/golem-build", "/tmp/golem-*", "/dev/shm/golem*",
    "~/.config/systemd/user/golem*",
    REAPER_DIR, REAPER_DIR + "/Scripts/golem", REAPER_DIR + "/Effects/golem", REAPER_DIR + "/FXChains",
    REAPER_DIR + "/Scripts/__startup.lua", REAPER_DIR + "/OSC/*.ReaperOSC",
    "~/.lv2/*.lv2", "~/.vst3/*.vst3", "~/.clap/*.clap", "~/.vst/airwindows/*.so",
    "~/opt/REAPER", "~/opt/reaper-versions", "~/.local/share/applications/cockos-reaper*.desktop",
    "~/.cargo", "~/.rustup", INBOX_DEFAULT,
) + SNAP_PROFILES + REAPER_DESKTOP + DESKTOP_CACHES + tuple(g[0] for g in SYSTEM_GLOBS) + ("/etc/apt/apt.conf.d/20auto-upgrades",)

# jamais supprimés, quoi qu'en dise un reçu ou une sélection
FORBIDDEN = ("/", "/bin", "/boot", "/dev", "/dev/shm", "/etc", "/home", "/lib", "/lib64", "/opt", "/proc", "/root",
             "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/usr/bin", "/usr/lib", "/usr/local", "/usr/local/bin",
             "/usr/local/sbin", "/usr/share", "/var", "/var/lib", "/etc/sudoers.d", "/etc/systemd",
             "/etc/systemd/system", "/etc/security", "/etc/security/limits.d", "/etc/sysctl.d", "/etc/udev",
             "/etc/udev/rules.d", "/etc/ssh", "/etc/ssh/sshd_config.d", "/etc/NetworkManager", "/etc/apt",
             "/etc/apt/apt.conf.d")
FORBIDDEN_HOME = ("", ".config", ".local", ".local/bin", ".local/share", ".local/share/applications",
                  ".local/share/icons", ".cache", ".lv2", ".vst3", ".clap", ".vst", "opt", ".config/systemd",
                  ".config/systemd/user", ".ssh", "Documents", "Desktop", "Music", "Downloads")


class UninstallError(Exception):
    pass


# ── le contexte : où est la machine, qui est l'utilisateur ───────────────────────────────────────────
class Ctx:
    def __init__(self, fsroot=None, home=None, user=None, root=None, receipt=None):
        fs = fsroot if fsroot is not None else os.environ.get("GOLEM_UNINSTALL_FSROOT", "")
        self.fsroot = os.path.abspath(fs).rstrip("/") if fs else ""
        self.home = os.path.normpath(home or os.environ.get("HOME") or os.path.expanduser("~"))
        self.user = user or os.environ.get("USER") or os.environ.get("LOGNAME") or _whoami()
        self.root_arg = root
        # GOLEM_RECEIPT (comme provision/receipt.py) : un autre fichier de reçu — tests, VM ; un chemin RÉEL
        self.receipt_path = receipt or os.environ.get("GOLEM_RECEIPT") or self.phys(RECEIPT)

    def expand(self, p):
        """`~` -> le HOME logique ; normalisé."""
        p = str(p)
        if p == "~" or p.startswith("~/"):
            p = self.home + p[1:]
        return os.path.normpath(p)

    def phys(self, p):
        """Chemin logique (absolu) -> chemin réel sur le disque (préfixé en mode --root-fs)."""
        p = self.expand(p)
        return self.fsroot + p if self.fsroot else p

    def logical(self, phys_path):
        p = os.path.normpath(phys_path)
        if self.fsroot and (p == self.fsroot or p.startswith(self.fsroot + "/")):
            p = p[len(self.fsroot):] or "/"
        return p

    def tilde(self, p):
        p = self.expand(p)
        return "~" + p[len(self.home):] if p == self.home or p.startswith(self.home + "/") else p

    def exists(self, p):
        return os.path.lexists(self.phys(p))

    def presence(self, p):
        """True / False / None : None = on ne PEUT PAS savoir sans root (un dossier parent fermé, EACCES). Jamais
        « absent » parce que stat échoue : c'est ainsi que les règles sudo restaient (2026-10-16)."""
        try:
            os.lstat(self.phys(p))
            return True
        except (FileNotFoundError, NotADirectoryError):
            return False
        except OSError:
            return None

    def listable(self, d):
        """Faux seulement si le dossier existe et qu'on ne peut pas le lire (un dossier absent ne cache rien)."""
        try:
            os.listdir(self.phys(d))
            return True
        except (FileNotFoundError, NotADirectoryError):
            return True
        except OSError:
            return False


def _whoami():
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        return "user"


# ── LE runner : toute commande passe par ici (les tests le remplacent) ────────────────────────────────
def _default_runner(ctx, argv, env=None, timeout=900):
    """Lance `argv`, rend (code, sortie). En mode --root-fs, rien de système ne s'exécute : seul `sh` (le script
    root, joué sur le faux arbre) tourne — un test ne peut pas désactiver un vrai service par accident."""
    if ctx.fsroot and argv[0] != "sh":
        return 0, "simulated: " + " ".join(argv)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, env=env, timeout=timeout, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return 127, "%s: not found" % argv[0]
    except subprocess.TimeoutExpired:
        return 124, "%s: timed out" % argv[0]
    except OSError as e:
        return 126, "%s: %s" % (argv[0], e)
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


run_command = _default_runner


# ── lecture du reçu et de la machine ─────────────────────────────────────────────────────────────────
def load_receipt(ctx):
    """(reçu | None, avertissement | None). Un reçu illisible = mode sans reçu, et on le DIT."""
    p = ctx.receipt_path
    if not os.path.isfile(p):
        return None, None
    try:
        with open(p, encoding="utf-8") as f:
            r = json.load(f)
        if not isinstance(r, dict):
            raise ValueError("not an object")
        return r, None
    except (OSError, ValueError) as e:
        return None, "install receipt unreadable (%s): working without it" % e


def _match(pattern, path):
    """Motif comparé composant par composant (un `*` ne traverse jamais un `/`)."""
    a, b = pattern.strip("/").split("/"), path.strip("/").split("/")
    return len(a) == len(b) and all(fnmatch.fnmatchcase(y, x) for x, y in zip(a, b))


def _read_link(ctx, p):
    """Cible LOGIQUE d'un lien (absolue, normalisée), ou None."""
    try:
        t = os.readlink(ctx.phys(p))
    except OSError:
        return None
    if not os.path.isabs(t):
        t = os.path.join(os.path.dirname(ctx.phys(p)), t)
    return ctx.logical(os.path.normpath(t))


def _inside(p, root):
    return bool(root) and (p == root or p.startswith(root.rstrip("/") + "/"))


def _looks_like_install(ctx, root):
    return bool(root) and os.path.isfile(ctx.phys(os.path.join(root, "provision", "golem"))) \
        and os.path.isdir(ctx.phys(os.path.join(root, "bridge")))


def find_install_root(ctx, receipt):
    """Le dossier d'install : --root, le reçu, la cible de ~/.local/bin/golem, ~/golem — le premier qui EST une
    install de golem (provision/golem + bridge/)."""
    cands = []
    if ctx.root_arg:
        cands.append(ctx.expand(os.path.abspath(ctx.root_arg) if not ctx.root_arg.startswith("~") else ctx.root_arg))
    if receipt and receipt.get("root"):
        cands.append(ctx.expand(receipt["root"]))
    t = _read_link(ctx, "~/.local/bin/golem")
    if t and t.endswith("/provision/golem"):
        cands.append(os.path.dirname(os.path.dirname(t)))
    cands.append(ctx.expand("~/golem"))
    for c in cands:
        if _looks_like_install(ctx, c) and not _forbidden(ctx, c):
            return c
    return None


def _group_members(ctx, group):
    try:
        with open(ctx.phys("/etc/group"), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split(":")
                if len(parts) >= 4 and parts[0] == group:
                    return [u for u in parts[3].split(",") if u]
    except OSError:
        pass
    return []


def _installed_pkgs(ctx):
    """Les paquets installés, lus dans /var/lib/dpkg/status (lisible sans root, et sans lancer dpkg)."""
    out, name = set(), None
    try:
        with open(ctx.phys("/var/lib/dpkg/status"), encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("Package:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("Status:") and name and line.split(":", 1)[1].strip().endswith(" installed"):
                    out.add(name)
    except OSError:
        return None
    return out


def _auto_pkgs(ctx):
    """Les paquets qu'apt a installés comme DÉPENDANCES (« Auto-Installed: 1 » dans /var/lib/apt/extended_states :
    exactement ce que lisent `apt-mark showauto` / `showmanual`). Un paquet installé absent de cet ensemble est
    « manuel ». Fichier absent ou illisible -> ensemble vide (apt-mark dirait alors : tout est manuel)."""
    out, name, auto = set(), None, False
    try:
        with open(ctx.phys("/var/lib/apt/extended_states"), encoding="utf-8", errors="replace") as f:
            for line in list(f) + [""]:
                line = line.strip()
                if not line:
                    if name and auto:
                        out.add(name)
                    name, auto = None, False
                elif line.startswith("Package:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("Auto-Installed:"):
                    auto = line.split(":", 1)[1].strip() == "1"
    except OSError:
        return set()
    return out


def _never_apt(pkg):
    return any(fnmatch.fnmatchcase(pkg, n) for n in NEVER_APT)


def _nm_has_golem_ap(ctx):
    for p in glob.glob(ctx.phys("/etc/NetworkManager/system-connections") + "/golem-ap*"):
        if os.path.exists(p):
            return True
    if ctx.fsroot:
        return False
    rc, out = run_command(ctx, ["nmcli", "-t", "-f", "NAME", "connection", "show"], timeout=15)
    return rc == 0 and "golem-ap" in out.splitlines()


def _ufw_enabled(ctx):
    try:
        with open(ctx.phys("/etc/ufw/ufw.conf"), encoding="utf-8") as f:
            return any(line.strip().lower() == "enabled=yes" for line in f)
    except OSError:
        return False


# ── reaper.ini : la retouche chirurgicale ────────────────────────────────────────────────────────────
def _csurf_is_golem(value):
    """Une surface OSC est la nôtre si son nom contient golem, ou si elle lit le motif `golem` (.ReaperOSC)."""
    v = value.strip()
    if not v.upper().startswith("OSC"):
        return False
    quoted = v.split('"')[1::2]
    return bool(quoted) and ("golem" in quoted[0].lower() or quoted[-1].lower() == "golem")


def ini_revert(text, keys=None, remove_csurf=False):
    """Rend (nouveau texte, [changements]). Dans la section [reaper] : chaque clé de `keys` remise à sa valeur
    d'avant (None = la clé n'existait pas : on la retire) ; la surface OSC de golem retirée si `remove_csurf`,
    les suivantes renumérotées et csurf_cnt corrigé (retiré s'il tombe à 0). Fonction PURE."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower() == "[reaper]"), None)
    if start is None:
        return text, []
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    sec = lines[start + 1:end]
    changes = []
    for k, v in (keys or {}).items():
        idx = [i for i, ln in enumerate(sec) if "=" in ln and ln.split("=", 1)[0].strip() == k]
        if v is None:
            if idx:
                sec = [ln for i, ln in enumerate(sec) if i not in idx]
                changes.append("%s removed" % k)
        else:
            want = "%s=%s" % (k, v)
            if idx:
                if any(sec[i] != want for i in idx):
                    sec[idx[0]] = want
                    sec = [ln for i, ln in enumerate(sec) if i not in idx[1:]]
                    changes.append("%s set back to %s" % (k, v))
            else:
                sec.insert(0, want)
                changes.append("%s set back to %s" % (k, v))
    if remove_csurf:
        entries = []
        for i, ln in enumerate(sec):
            k = ln.split("=", 1)[0].strip() if "=" in ln else ""
            if k.startswith("csurf_") and k[6:].isdigit():
                entries.append((int(k[6:]), i, ln.split("=", 1)[1]))
        golem = [e for e in entries if _csurf_is_golem(e[2])]
        if golem:
            drop = {e[1] for e in golem}
            keep = sorted((e for e in entries if e[1] not in drop), key=lambda e: e[0])
            renum = {e[1]: "csurf_%d=%s" % (n, e[2]) for n, e in enumerate(keep)}
            new = []
            for i, ln in enumerate(sec):
                if i in drop:
                    continue
                new.append(renum.get(i, ln))
            sec = new
            cnt = [i for i, ln in enumerate(sec) if ln.split("=", 1)[0].strip() == "csurf_cnt"]
            if keep:
                if cnt:
                    sec[cnt[0]] = "csurf_cnt=%d" % len(keep)
                else:
                    sec.append("csurf_cnt=%d" % len(keep))
            else:
                sec = [ln for i, ln in enumerate(sec) if i not in cnt]
            changes.append("golem OSC surface removed")
    if not changes:
        return text, []
    out = lines[:start + 1] + sec + lines[end:]
    nl = "\r\n" if "\r\n" in text else "\n"          # le reaper.ini de Windows est en CRLF : on le garde
    return nl.join(out) + (nl if text.endswith("\n") or not text else ""), changes


def _ini_plan(ctx, receipt):
    """(clés, retirer_csurf, changements prévus) — ou None si reaper.ini n'existe pas ou que rien ne changerait."""
    p = ctx.phys(REAPER_DIR + "/reaper.ini")
    if not os.path.isfile(p):
        return None
    if receipt is not None:
        ri = (receipt.get("prior") or {}).get("reaper_ini") or {}
        keys, csurf = dict(ri.get("keys") or {}), bool(ri.get("csurf_added"))
        if ri.get("existed") is False:
            # golem a CRÉÉ reaper.ini : ses clés n'existaient pas — on les retire (le fichier, lui, reste)
            keys = {k: None for k in keys}
    else:
        keys, csurf = {}, True
    with open(p, encoding="latin-1") as f:
        text = f.read()
    _new, changes = ini_revert(text, keys, csurf)
    return (keys, csurf, changes) if changes else None


# ── la sécurité des chemins ──────────────────────────────────────────────────────────────────────────
def _forbidden(ctx, p):
    p = os.path.normpath(p)
    if not os.path.isabs(p) or p in FORBIDDEN:
        return True
    home = ctx.home
    if p == home or _inside(home, p):                    # $HOME ou l'un de ses ancêtres
        return True
    if any(p == os.path.normpath(os.path.join(home, h)) for h in FORBIDDEN_HOME):
        return True
    return len(p.strip("/").split("/")) < 2


def _expected(ctx, p, root=None, receipt_paths=()):
    """Ce chemin fait-il partie de l'ensemble attendu ?"""
    if _forbidden(ctx, p):
        return False
    if root and p == root:
        return True
    if any(_match(ctx.expand(pat), p) for pat in EXPECTED):
        return True
    if p in receipt_paths:
        # un chemin du reçu : jamais un enfant direct de $HOME (hors motifs ci-dessus), et assez profond
        return os.path.dirname(p) != ctx.home and len(p.strip("/").split("/")) >= 3
    return False


def _through_link(ctx, p):
    """Vrai si un composant ENTRE l'ancre ($HOME, ou la racine) et le parent de `p` est un lien symbolique :
    supprimer `p` irait alors toucher ailleurs que là où l'on croit."""
    anchor = ctx.home if _inside(p, ctx.home) else "/"
    cur = anchor
    rest = os.path.relpath(os.path.dirname(p), anchor)
    if rest == ".":
        return False
    for part in rest.split("/"):
        cur = os.path.join(cur, part)
        if os.path.islink(ctx.phys(cur)):
            return True
    return False


def safe_remove(ctx, p, root=None, receipt_paths=()):
    """Supprime `p` (logique) s'il est attendu. Un lien : le LIEN, jamais sa cible. Un dossier : sans suivre aucun
    lien. Rend un message ; lève UninstallError si c'est refusé."""
    p = ctx.expand(p)
    if not _expected(ctx, p, root, receipt_paths):
        raise UninstallError("refused: %s is not in the expected set" % p)
    if _through_link(ctx, p):
        raise UninstallError("refused: %s is reached through a symbolic link" % p)
    real = ctx.phys(p)
    try:
        st = os.lstat(real)
    except FileNotFoundError:
        return "already absent"
    if stat.S_ISLNK(st.st_mode):
        os.unlink(real)
        return "link removed"
    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(real)                                  # rmtree ne suit pas les liens (ni en haut, ni dedans)
        return "folder removed"
    os.unlink(real)
    return "file removed"


def _remove_empty_tree(ctx, p, root=None):
    """Retire `p` s'il ne contient QUE des dossiers vides (de bas en haut) ; un fichier dedans -> refus, rien touché.
    Pour un dossier hors de l'ensemble attendu (le dossier surveillé déplacé par l'utilisateur) : vide, il ne porte
    rien à personne."""
    p = ctx.expand(p)
    if _forbidden(ctx, p) or (root and (_inside(root, p) or _inside(p, root))) or _through_link(ctx, p):
        raise UninstallError("refused: %s" % p)
    real = ctx.phys(p)
    if os.path.islink(real):
        raise UninstallError("refused: %s is a symbolic link" % p)
    if not os.path.isdir(real):
        return "already absent"
    dirs = []
    for r, ds, fs in os.walk(real):
        if fs or any(os.path.islink(os.path.join(r, d)) for d in ds):
            raise UninstallError("%s holds files: left as is" % p)
        dirs.append(r)
    for d in sorted(dirs, key=len, reverse=True):
        os.rmdir(d)
    return "empty folder removed"


def _count_files(real):
    n = 0
    for _r, ds, fs in os.walk(real):
        n += len(fs) + sum(1 for d in ds if os.path.islink(os.path.join(_r, d)))
    return n


def _inbox_item(ctx, root):
    """Le dossier surveillé du bridge (bridge/inbox.py) : ~/golem-inbox, ou celui de config/inbox.json. Coché s'il est
    vide (ses sous-dossiers .imported/.refused vides compris) ; décoché s'il garde des fichiers — ce sont ceux de
    l'utilisateur."""
    path, custom = ctx.expand(INBOX_DEFAULT), False
    if root:
        try:
            with open(ctx.phys(os.path.join(root, "config", "inbox.json")), encoding="utf-8") as f:
                d = (json.load(f) or {}).get("dir")
            if isinstance(d, str) and d.strip():
                d = d.strip()
                d = ctx.expand(d) if d.startswith("~") else os.path.normpath(d)
                if os.path.isabs(d):
                    path, custom = d, d != ctx.expand(INBOX_DEFAULT)
        except (OSError, ValueError, AttributeError):
            pass
    real = ctx.phys(path)
    if not os.path.lexists(real) or _forbidden(ctx, path) or (root and (_inside(path, root) or _inside(root, path))):
        return None                                  # dans le dossier d'install : il part avec lui
    if os.path.islink(real):
        n, what = 0, "a link to the folder golem watches for shared songs"
    elif os.path.isdir(real):
        n = _count_files(real)
        what = "the folder golem watches for shared songs (.golem files)"
    else:
        return None
    if n:
        reason = ("%s; it holds %d file%s (yours, or songs golem filed in .imported/.refused): it stays — delete it "
                  "yourself once you have what you need" % (what, n, "" if n == 1 else "s"))
    else:
        reason = "%s; it is empty" % what
    return _item("golem:inbox", "golem", "Song inbox folder", [ctx.tilde(path)], "user", "golem-named", n == 0,
                 reason, "remove", _paths=[path], _inbox_custom=custom)


def _defaults_list_ours(ctx, text):
    """defaults.list ne porte QUE des associations vers cockos-reaper*/golem* dont l'entrée .desktop n'existe plus
    (ou aucune) ? Alors il est à nous ; sinon c'est celui de l'utilisateur et on n'y touche pas."""
    apps = ctx.phys("~/.local/share/applications")
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith(("#", "[")):
            continue
        if "=" not in ln:
            return False
        for d in [x.strip() for x in ln.split("=", 1)[1].split(";") if x.strip()]:
            if not (d.startswith(("cockos-reaper", "golem")) and d.endswith(".desktop")):
                return False
            if os.path.lexists(os.path.join(apps, d)):
                return False
    return True


def desktop_refresh(ctx, root=None, rpaths=()):
    """Après le retrait d'entrées de menu, d'icônes ou de types de fichiers : les bases du bureau sont mises à jour
    (update-desktop-database, update-mime-database, gtk-update-icon-cache — par le runner), et un cache qui ne
    décrit plus RIEN part, avec les dossiers devenus vides. Prudence : un defaults.list qui porte une association
    d'un autre logiciel n'est jamais touché. Rend la liste de ce qui a été fait."""
    done = []

    def rm(p):
        if ctx.exists(p):
            safe_remove(ctx, p, root, rpaths)
            done.append("%s removed" % ctx.tilde(p))
    apps = ctx.expand("~/.local/share/applications")
    if os.path.isdir(ctx.phys(apps)):
        if glob.glob(ctx.phys(apps) + "/*.desktop"):
            run_command(ctx, ["update-desktop-database", ctx.phys(apps)], timeout=60)
            done.append("menu database updated")
        else:
            rm(apps + "/mimeinfo.cache")
        dl = apps + "/defaults.list"
        if os.path.isfile(ctx.phys(dl)):
            try:
                with open(ctx.phys(dl), encoding="utf-8", errors="replace") as f:
                    if _defaults_list_ours(ctx, f.read()):
                        rm(dl)
            except OSError:
                pass
    menus = ctx.expand("~/.config/menus/applications-merged")
    dummy = menus + "/xdg-desktop-menu-dummy.menu"
    if ctx.exists(dummy) and not [n for n in os.listdir(ctx.phys(menus)) if n != os.path.basename(dummy)] \
            and not glob.glob(ctx.phys(apps) + "/*.desktop") and not glob.glob(ctx.phys("~/.gnome/apps") + "/*.desktop"):
        rm(dummy)
    mime = ctx.expand("~/.local/share/mime")
    if os.path.isdir(ctx.phys(mime)) and not os.path.islink(ctx.phys(mime)):
        pk = ctx.phys(mime + "/packages")
        if os.path.isdir(pk) and [n for n in os.listdir(pk) if not os.path.isdir(os.path.join(pk, n))]:
            run_command(ctx, ["update-mime-database", ctx.phys(mime)], timeout=120)
            done.append("file types database updated")
        else:
            rm(mime)                      # tout le reste est GÉNÉRÉ à partir de packages/ : il ne décrit plus rien
    hic = ctx.expand("~/.local/share/icons/hicolor")
    if os.path.isdir(ctx.phys(hic)) and not os.path.islink(ctx.phys(hic)):
        cache = os.path.basename(DESKTOP_CACHES[2])
        icons = [1 for r, _ds, fs in os.walk(ctx.phys(hic)) for n in fs if not (r == ctx.phys(hic) and n == cache)]
        if icons:
            if ctx.exists(hic + "/" + cache):
                run_command(ctx, ["gtk-update-icon-cache", "-f", "-t", ctx.phys(hic)], timeout=60)
                done.append("icon cache updated")
        else:
            rm(hic + "/" + cache)
            for r, _ds, _fs in sorted(os.walk(ctx.phys(hic)), key=lambda x: -len(x[0])):
                try:
                    os.rmdir(r)
                except OSError:
                    pass
    return done


# ── LE PLAN ──────────────────────────────────────────────────────────────────────────────────────────
def _item(id, group, label, paths, privilege, origin, default, reason, action, presence="present", **extra):
    # presence : "present" (vu sur la machine) ou "unknown" (dans un dossier root illisible : retiré s'il y est)
    d = {"id": id, "group": group, "label": label, "paths": list(paths), "privilege": privilege,
         "origin": origin, "default": bool(default), "reason": reason, "action": action, "presence": presence}
    d.update(extra)
    return d


def _receipt_group(ctx, path, declared):
    """Le groupe du PLAN d'un élément du reçu, lu dans son chemin (le groupe du reçu ne sert qu'en repli)."""
    if _inside(path, ctx.expand(REAPER_DIR)):
        return "reaper-links"
    if any(_inside(path, ctx.expand(d)) for d in ("~/.lv2", "~/.vst3", "~/.clap", "~/.vst")):
        return "plugins"
    if any(_inside(path, ctx.expand(d)) for d in ("~/.cargo", "~/.rustup")):
        return "toolchain"
    if any(_inside(path, ctx.expand(d)) for d in ("~/opt/REAPER", "~/opt/reaper-versions")):
        return "reaper"
    if any(path.startswith(d) for d in ("/etc/ssh/", "/etc/sysctl.d/", "/etc/udev/", "/etc/apt/apt.conf.d/")):
        return "dedicated"
    if path.startswith(("/etc/", "/usr/", "/var/")):
        return "system"
    return declared if declared in GROUPS else "golem"


def build_plan(ctx):
    receipt, warn = load_receipt(ctx)
    mode = "receipt" if receipt is not None else "no-receipt"
    root = find_install_root(ctx, receipt)
    prior = (receipt or {}).get("prior") or {}
    items, absent, warnings = [], [], [w for w in (warn,) if w]
    ritems = [r for r in ((receipt or {}).get("items") or []) if isinstance(r, dict) and r.get("path")]
    by_path = {ctx.expand(r["path"]): r for r in ritems}
    by_id = {r.get("id"): r for r in ritems if r.get("id")}
    rpaths = set(by_path)
    used = set()                                       # chemins du reçu déjà portés par un élément

    def origin_of(paths, named=True):
        hit = [by_path[p] for p in paths if p in by_path]
        used.update(p for p in paths if p in by_path)
        if hit:
            return "receipt", [h.get("id") for h in hit if h.get("id")]
        return ("golem-named" if named else "unknown"), []

    def add(it):
        if any(x["id"] == it["id"] for x in items):
            return
        # « déjà là avant golem » (prior.existed) : listé, jamais coché
        if any(((by_id.get(r) or {}).get("prior") or {}).get("existed") for r in it.get("_rids") or []
               if isinstance((by_id.get(r) or {}).get("prior"), dict)):
            it["default"], it["reason"] = False, "already here before golem"
        items.append(it)

    # ── golem ──
    if root:
        o, rid = origin_of([root])
        add(_item("golem:install-folder", "golem", "golem install folder", [ctx.tilde(root)], "user", o, True,
                  "the application itself: code, settings, presets and local backups (back them up first)",
                  "remove", _paths=[root], _rids=rid, _step="folder"))
    else:
        warnings.append("no golem install folder found (looked at --root, the receipt, ~/.local/bin/golem, ~/golem)")
    cmd = ctx.expand("~/.local/bin/golem")
    if ctx.exists(cmd):
        t = _read_link(ctx, cmd)
        ours = (t and root and _inside(t, root)) or cmd in rpaths
        if ours or (t and t.endswith("/provision/golem")):
            o, rid = origin_of([cmd])
            add(_item("golem:command", "golem", "golem command", [ctx.tilde(cmd)], "user", o, True,
                      "the `golem` command in your PATH", "remove", _paths=[cmd], _rids=rid))
    for pat, label, slug in (("~/.local/share/applications/golem*.desktop", "Desktop entry", "desktop"),
                             ("~/.local/share/icons/hicolor/*/apps/golem*.png", "golem icon", "icon")):
        for real in sorted(glob.glob(ctx.phys(pat))):
            p = ctx.logical(real)
            o, rid = origin_of([p])
            add(_item("golem:%s:%s" % (slug, os.path.basename(p)), "golem", "%s (%s)" % (label, os.path.basename(p)),
                      [ctx.tilde(p)], "user", o, True, "desktop integration of golem", "remove", _paths=[p], _rids=rid))
    for real in sorted(glob.glob(ctx.phys("~/.config/systemd/user") + "/golem*")):
        p = ctx.logical(real)
        o, rid = origin_of([p])
        add(_item("golem:user-unit:%s" % os.path.basename(p), "golem", "Start-at-boot service (%s)" % os.path.basename(p),
                  [ctx.tilde(p)], "user", o, True, "starts golem when the machine boots", "disable",
                  _paths=[p], _rids=rid, _unit=os.path.basename(p)))
    linger_on = os.path.exists(ctx.phys("/var/lib/systemd/linger/%s" % ctx.user))
    if linger_on:
        if "linger" in prior:
            if prior.get("linger") is False:
                add(_item("golem:linger", "golem", "Services without login (linger)", [], "root", "receipt", True,
                          "golem turned it on; it was off before", "revert", _prior_keys=["linger"]))
        else:
            add(_item("golem:linger", "golem", "Services without login (linger)", [], "root", "unknown", False,
                      "on, but nothing says golem turned it on", "revert"))
    share = ctx.expand(SHARE_DIR)
    if os.path.isdir(ctx.phys(share)):
        inner = [n for n in os.listdir(ctx.phys(share)) if n != os.path.basename(RECEIPT)]
        if inner:
            add(_item("golem:share-dir", "golem", "golem data folder (browser profile)", [ctx.tilde(share)], "user",
                      "golem-named", True, "the launcher's browser profile and golem's own data", "remove",
                      _paths=[share], _keep_receipt=True))
    snaps = [ctx.expand(p) for p in SNAP_PROFILES if ctx.exists(ctx.expand(p))]
    if snaps:
        add(_item("golem:snap-profiles", "golem", "Browser profiles of the golem window and installer",
                  [ctx.tilde(p) for p in snaps], "user", "golem-named", True,
                  "golem's own browser profiles (your browser and its data are not touched)", "remove", _paths=snaps))
    for name in ("golem-installer", "golem-build"):
        p = ctx.expand("~/.cache/" + name)
        if ctx.exists(p):
            o, rid = origin_of([p])
            add(_item("golem:cache:%s" % name, "golem", "Cache (%s)" % name, [ctx.tilde(p)], "user", o, True,
                      "temporary files of the installer and the plugin builds", "remove", _paths=[p], _rids=rid))
    tmp = []
    for pat in ("/tmp/golem-*", "/dev/shm/golem*"):
        for real in sorted(glob.glob(ctx.phys(pat))):
            p = ctx.logical(real)
            try:
                mine = os.lstat(real).st_uid == os.getuid()
            except OSError:
                mine = False
            if mine and not os.path.basename(p).startswith("golem-uninstall"):
                tmp.append(p)
    if tmp:
        add(_item("golem:tmp", "golem", "Temporary files and logs", [ctx.tilde(p) for p in tmp], "user", "golem-named",
                  True, "logs and leftovers in /tmp and /dev/shm", "remove", _paths=tmp))
    inbox = _inbox_item(ctx, root)
    if inbox:
        add(inbox)

    # ── reaper-links ──
    rdir = ctx.expand(REAPER_DIR)
    cands = [rdir + "/Scripts/golem", rdir + "/Effects/golem", rdir + "/FXChains", rdir + "/Scripts/__startup.lua"]
    cands += sorted(ctx.logical(x) for x in glob.glob(ctx.phys(rdir + "/OSC") + "/*.ReaperOSC"))
    cands += sorted(p for p, r in by_path.items() if _receipt_group(ctx, p, r.get("group")) == "reaper-links"
                    and p not in cands)
    for p in cands:
        if not os.path.islink(ctx.phys(p)):
            continue
        t = _read_link(ctx, p)
        rec = by_path.get(p)
        if not (rec or (root and t and _inside(t, root))):
            continue
        o, rid = origin_of([p])
        moved = ((rec or {}).get("prior") or {}).get("moved_to") if isinstance((rec or {}).get("prior"), dict) else None
        orig = ctx.expand(moved) if moved else p + ".golem-orig"
        restore = orig if ctx.exists(orig) else None
        reason = "golem's link into its install folder"
        if restore:
            reason += "; your original is put back"
        elif ctx.exists(p + ".bak"):
            reason += "; a .bak exists next to it but nothing says it is yours from before golem: left as is"
        add(_item("reaper-links:%s" % os.path.relpath(p, rdir), "reaper-links",
                  "REAPER link %s" % os.path.relpath(p, rdir), [ctx.tilde(p)], "user", o, True, reason,
                  "restore" if restore else "remove", _paths=[p], _rids=rid, _restore=restore))

    # ── reaper-ini ──
    ip = _ini_plan(ctx, receipt)
    if ip:
        keys, csurf, changes = ip
        add(_item("reaper-ini:revert", "reaper-ini", "REAPER settings golem changed", [ctx.tilde(rdir + "/reaper.ini")],
                  "user", "receipt" if receipt is not None else "golem-named", True,
                  "; ".join(changes) + ("" if receipt is not None else " (no receipt: only golem's OSC surface)"),
                  "revert", _keys=keys, _csurf=csurf, _prior_keys=["reaper_ini"]))

    # ── system + dedicated (fichiers à golem par leur nom) ──
    for pat, group, action, label in SYSTEM_GLOBS:
        found = [ctx.logical(real) for real in sorted(glob.glob(ctx.phys(pat)))]
        unsure = []
        if not ctx.listable(os.path.dirname(pat)):
            # dossier fermé sans root (/etc/sudoers.d en 0750) : glob n'y voit rien. Les noms fixes de golem et ceux
            # du reçu y sont cherchés un par un ; ce qu'on ne peut pas voir est « présence inconnue », jamais absent
            for p in dict.fromkeys([q for q in GOLEM_FIXED_ROOT + tuple(sorted(rpaths)) if _match(pat, q)]):
                pr = ctx.presence(p)
                if pr and p not in found:
                    found.append(p)
                elif pr is None:
                    unsure.append(p)
        for p in found + unsure:
            o, rid = origin_of([p])
            add(_item("%s:%s" % (group, p), group, "%s (%s)" % (label[0].upper() + label[1:], os.path.basename(p)),
                      [p], "root", o, True, "written by the golem install" if p in found else
                      "can't be checked without root (its folder is closed to you): removed if present", action,
                      presence="present" if p in found else "unknown", _paths=[p], _rids=rid,
                      _unit=os.path.basename(p) if action == "disable" else None))
    if _nm_has_golem_ap(ctx):
        add(_item("system:nm:golem-ap", "system", "Wi-Fi access point connection (golem-ap)", [], "root", "golem-named",
                  True, "the access point golem raises when no known network is around", "remove-nm"))
    if ctx.user in _group_members(ctx, "audio"):
        if "audio_group" in prior:
            if prior.get("audio_group") is False:
                add(_item("system:audio-group", "system", "Membership of the audio group", [], "root", "receipt", True,
                          "golem added you; you were not in it before (takes effect at next login)", "revert",
                          _prior_keys=["audio_group"]))
        else:
            add(_item("system:audio-group", "system", "Membership of the audio group", [], "root", "unknown", False,
                      "you may have been in it before golem", "revert"))
    # ufw : le reçu dit ce qu'il y avait avant ; sans reçu, seulement si golem a durci cette machine
    hardened = any(i["group"] == "dedicated" for i in items)
    if "ufw" in prior and isinstance(prior.get("ufw"), dict):
        pu = prior["ufw"]
        before = {str(x).split()[0] for x in (pu.get("rules") or []) if str(x).split()}   # lignes de `ufw status`
        rules = [r for r in UFW_GOLEM_RULES + UFW_RECEIPT_ONLY if r not in before]
        add(_item("dedicated:ufw", "dedicated", "Firewall rules", ["/etc/ufw"], "root", "receipt", True,
                  "golem's rules deleted" + ("; firewall turned off, as it was before" if not pu.get("active") else ""),
                  "revert", _rules=rules, _disable=not pu.get("active"), _prior_keys=["ufw"]))
    elif _ufw_enabled(ctx) and hardened:
        add(_item("dedicated:ufw", "dedicated", "Firewall rules", ["/etc/ufw"], "root", "unknown", False,
                  "golem's rules deleted; the firewall stays on (nothing says it was off before)", "revert",
                  _rules=list(UFW_GOLEM_RULES), _disable=False))
    if "auto_upgrades" in prior:
        au = prior.get("auto_upgrades")
        add(_item("dedicated:auto-upgrades", "dedicated", "Automatic updates", ["/etc/apt/apt.conf.d/20auto-upgrades"],
                  "root", "receipt", True, "restored to the file that was there before golem" if au is not None
                  else "golem's file removed: there was none before", "restore", _content=au,
                  _prior_keys=["auto_upgrades"]))
    timers = prior.get("apt_timers")
    if isinstance(timers, dict) and timers:
        on = [u for u, v in timers.items() if v == "enabled"]
        add(_item("dedicated:apt-timers", "dedicated", "Automatic update timers", [], "root", "receipt", True,
                  ("turned back on: %s" % ", ".join(sorted(on))) if on else "unmasked; they stay off, as before",
                  "restore", _timers={str(k): str(v) for k, v in timers.items()}, _prior_keys=["apt_timers"]))
    av = prior.get("avahi_enabled", None)
    if "avahi_enabled" in prior and av not in (True, "enabled", "static", "indirect", "alias", "enabled-runtime"):
        add(_item("dedicated:avahi", "dedicated", "Name service on the network (avahi)", [], "root", "receipt", True,
                  "golem turned it on; it was %s before" % ("off" if av in (False, "disabled") else "not set up"),
                  "disable", _unit="avahi-daemon.service",
                  _prior_keys=["avahi_enabled"]))
    if prior.get("governor"):
        add(_item("dedicated:governor", "dedicated", "CPU governor", [], "root", "receipt", True,
                  "set back to %s" % prior["governor"], "revert", _governor=str(prior["governor"]),
                  _prior_keys=["governor"]))

    # ── plugins ──
    for slug, label, paths, named in PLUGINS:
        ps = [ctx.expand(p) for p in paths if ctx.exists(p)]
        if not ps:
            continue
        o, rid = origin_of(ps, named)
        default = o in ("receipt", "golem-named")
        add(_item("plugins:%s" % slug, "plugins", label, [ctx.tilde(p) for p in ps], "user", o, default,
                  "golem placed it" if o == "receipt" else "golem's own plugin" if o == "golem-named"
                  else "may have been here before golem", "remove", _paths=ps, _rids=rid))
    # ── reaper ──
    rp = prior.get("reaper") or {}
    if receipt is not None and rp.get("installed_by_golem"):
        base = ctx.expand(rp.get("path") or "~/opt/REAPER")
        # l'intégration bureau d'abord (le désinstalleur de REAPER vit dans `base`), le programme ensuite
        ps = [ctx.logical(x) for pat in REAPER_DESKTOP for x in sorted(glob.glob(ctx.phys(pat)))]
        ps += [p for p in (base, ctx.expand("~/opt/reaper-versions")) if ctx.exists(p)]
        if ps and _expected(ctx, base):
            _o, rid = origin_of(ps)                 # le ~/opt/REAPER du reçu est porté ici, pas en double
            add(_item("reaper:app", "reaper", "REAPER %s" % (rp.get("version") or ""), [ctx.tilde(p) for p in ps],
                      "user", "receipt", False, "golem installed it; you may want to keep it (its menu entry, "
                      "icons and file types go with it)", "remove",
                      _paths=ps, _rids=rid, _prior_keys=["reaper"], _base=base))
    if ctx.exists(rdir):
        o = "receipt" if rp.get("installed_by_golem") else "unknown"
        add(_item("reaper:config", "reaper", "REAPER settings folder", [ctx.tilde(rdir)], "user", o, False,
                  "your REAPER settings, scripts and licence (the licence is backed up first)"
                  + ("" if rp.get("license_present") is not False or not ctx.exists(rdir + "/reaper-license.rk")
                     else "; the licence was added after golem"), "remove", _paths=[rdir]))
    # ── Chromium, la fenêtre golem (2026-11-03) : un SNAP, posé par install.sh seulement s'il manquait. Listé
    # seulement si le reçu dit « posé par golem » ; décoché, comme REAPER : l'utilisateur a pu s'en servir depuis ──
    cp = prior.get("chromium") or {}
    if receipt is not None and cp.get("installed_by_golem") is True and ctx.exists("/snap/chromium"):
        add(_item("system:chromium-snap", "system", "Chromium (snap)", ["/snap/chromium"], "root", "receipt", False,
                  "golem installed it for its window; you may use it as a browser too", "snap-remove"))
    # ── apt (reçu seulement) : les EXPLICITES sont des éléments ; les dépendances partent avec eux, au run ──
    apt_deps, apt_ours, apt_model = [], [], None
    if receipt is not None:
        apt = receipt.get("apt") or {}
        debs = [d for d in (apt.get("debs") or []) if isinstance(d, str)]
        added = [a for a in (apt.get("added") or []) if isinstance(a, str)]
        req = apt.get("requested")
        requested = {r for r in req if isinstance(r, str)} if isinstance(req, list) else None
        apt_model = "requested" if requested is not None else "manual"
        installed = _installed_pkgs(ctx)
        auto = _auto_pkgs(ctx)
        apt_ours = list(dict.fromkeys(added + debs))
        for pkg in apt_ours:
            if _never_apt(pkg):
                continue
            if installed is not None and pkg not in installed:
                absent.append("apt:%s" % pkg)
                continue
            unasked = False
            if pkg not in debs:
                if requested is not None and pkg in requested:
                    pass
                elif pkg in auto:
                    apt_deps.append(pkg)            # une dépendance : retirée avec ce qui l'a tirée, jamais un élément
                    continue
                elif requested is not None:
                    # « manuel » pour apt, mais aucun script de golem ne l'a demandé : proposé, jamais coché
                    unasked = True
            audio = pkg in debs or any(fnmatch.fnmatchcase(pkg, a) for a in AUDIO_APT)
            build = not audio and any(fnmatch.fnmatchcase(pkg, b) for b in BUILD_APT)
            add(_item("apt:%s" % pkg, "apt", pkg, [], "root", "receipt", (audio or build) and not unasked,
                      "installed on purpose, but no golem script asked for it" if unasked
                      else "audio plugin package golem installed" if audio
                      else "build files golem installed to compile its plugins" if build
                      else "general tool golem installed; other software may use it",
                      "purge", _pkg=pkg))
    # ── toolchain ──
    tc = prior.get("toolchain")
    rust = (isinstance(tc, dict) and (tc.get("rust_installed_by_golem") or tc.get("rust"))) or (isinstance(tc, (list, tuple)) and "rust" in tc) or tc == "rust" \
        or any(_receipt_group(ctx, p, r.get("group")) == "toolchain" for p, r in by_path.items())
    if receipt is not None and rust:
        ps = [ctx.expand(p) for p in ("~/.cargo", "~/.rustup") if ctx.exists(p)]
        if ps:
            o, rid = origin_of(ps)
            # cochée quand le reçu dit que GOLEM l'a posée (comme les paquets de compilation) ; une Rust d'avant golem
            # n'arrive ici que par un chemin du reçu, et reste décochée
            mine = isinstance(tc, dict) and tc.get("rust_installed_by_golem") is True
            add(_item("toolchain:rust", "toolchain", "Rust toolchain", [ctx.tilde(p) for p in ps], "user", "receipt",
                      mine, "golem installed it to build plugins; you may use it", "remove", _paths=ps, _rids=rid))

    # les éléments du reçu que rien n'a portés : listés s'ils existent, sinon « absents »
    for p, r in by_path.items():
        if p in used:
            continue
        g = _receipt_group(ctx, p, r.get("group"))
        pr = ctx.presence(p)
        if pr is False:
            absent.append(r.get("id") or p)
            continue
        if g == "reaper-links":
            continue                                        # un lien du reçu qui n'est plus un lien : on n'y touche pas
        if not _expected(ctx, p, root, rpaths):
            warnings.append("receipt entry refused (outside what golem may remove): %s" % p)
            continue
        priv = "root" if g in ("system", "dedicated") or r.get("owner") == "root" or pr is None else "user"
        add(_item("%s:%s" % (g, ctx.tilde(p)), g, os.path.basename(p), [ctx.tilde(p)], priv, "receipt",
                  g not in ("reaper", "toolchain", "apt"), "recorded by %s" % (r.get("by") or "the install")
                  + ("" if pr else "; can't be checked without root: removed if present"),
                  "remove", presence="present" if pr else "unknown", _paths=[p],
                  _rids=[r.get("id")] if r.get("id") else []))
    items.sort(key=lambda it: GROUPS.index(it["group"]))
    return {"mode": mode, "root": root, "receipt": ctx.receipt_path if receipt is not None else None,
            "items": items, "absent": absent, "warnings": warnings, "never_apt": list(NEVER_APT),
            "apt_model": apt_model, "apt_deps": apt_deps, "_apt_ours": apt_ours}


def public(plan):
    """Le plan sans les champs internes (`_…`)."""
    return {**{k: v for k, v in plan.items() if not k.startswith("_")},
            "items": [{k: v for k, v in it.items() if not k.startswith("_")} for it in plan["items"]]}


def plan_text(plan):
    out = ["golem uninstall plan — %s mode%s" % (plan["mode"], "" if not plan["root"] else ", install folder %s" % plan["root"])]
    for w in plan["warnings"]:
        out.append("  ! " + w)
    for g in GROUPS:
        its = [i for i in plan["items"] if i["group"] == g]
        if not its:
            continue
        out.append("")
        out.append("[%s]" % g)
        for i in its:
            out.append("  [%s] %-38s %-8s %-11s %s" % ("x" if i["default"] else " ", i["id"], i["action"], i["origin"],
                                                       i["label"]))
            for p in i["paths"]:
                out.append("        %s" % p)
            out.append("        %s%s" % (i["reason"], " (needs your password)" if i["privilege"] == "root" else ""))
    if plan.get("apt_deps"):
        out.append("")
        out.append("Dependencies golem's packages pulled in (%d): removed with them when nothing installed before "
                   "golem needs them" % len(plan["apt_deps"]))
    if plan["absent"]:
        out.append("")
        out.append("Already gone (in the receipt): %s" % ", ".join(plan["absent"]))
    out.append("")
    out.append("Never offered (system base): %s" % ", ".join(plan["never_apt"]))
    return "\n".join(out)


# ── L'EXÉCUTION ──────────────────────────────────────────────────────────────────────────────────────
class Reporter:
    def __init__(self, as_json=False, log=None):
        self.as_json, self.log, self.results, self.kept = as_json, log, {}, set()

    def __call__(self, step, item, ok, msg, **extra):
        # extra : `kept` (gardé exprès, ni fait ni raté — un paquet dont un paquet d'avant golem a besoin),
        # `deps` (le nombre de dépendances retirées)
        if item:
            self.results[item] = bool(ok)
            if extra.get("kept"):
                self.kept.add(item)
        line = {"step": step, "item": item, "ok": bool(ok), "msg": msg}
        line.update(extra)
        if self.as_json:
            print(json.dumps(line), flush=True)
        else:
            print("%s %-8s %s%s" % ("ok  " if ok else "FAIL", step, (item + ": ") if item else "", msg), flush=True)
        if self.log:
            try:
                with open(self.log, "a", encoding="utf-8") as f:
                    f.write("%s [%s] %s %s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), step,
                                                   item or "-", "OK" if ok else "FAILED", msg))
            except OSError:
                pass


def _self_paths():
    """Là où ce processus vit : le répertoire courant et ce script (les tests le remplacent)."""
    return [os.getcwd(), os.path.abspath(__file__)]


def _q(s):
    return shlex.quote(str(s))


def _root_actions(ctx, it, root, rpaths):
    """Les lignes shell d'un élément root. Chaque chemin est VÉRIFIÉ ici, avant d'entrer dans le script."""
    a, sh = it["action"], []
    for p in it.get("_paths") or []:
        if not _expected(ctx, p, root, rpaths):
            raise UninstallError("refused: %s is not in the expected set" % p)
        if _through_link(ctx, p):
            raise UninstallError("refused: %s is reached through a symbolic link" % p)
    paths = [ctx.phys(p) for p in it.get("_paths") or []]
    if a == "disable":
        sh += ["systemctl disable --now %s || true" % _q(it["_unit"])]
        sh += ["rm -f -- %s" % _q(p) for p in paths]
        sh += ["systemctl daemon-reload || true"]
    elif a == "remove" and paths and it.get("presence") == "unknown":
        # présence inconnue (dossier fermé sans root) : `rm -f`, idempotent, et on DIT ce qu'on a trouvé
        for p in paths:
            sh.append("if [ -e %s ] || [ -L %s ]; then rm -f -- %s; echo removed; else echo 'was not there'; fi"
                      % (_q(p), _q(p), _q(p)))
    elif a == "remove" and paths:
        for p, lp in zip(paths, it["_paths"]):
            sh.append(("rm -rf --one-file-system -- %s" if os.path.isdir(p) and not os.path.islink(p) else "rm -f -- %s") % _q(p))
            if lp.startswith("/etc/ssh/"):
                sh.append("systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true")
            elif lp.startswith("/etc/sysctl.d/"):
                if "port80" in lp:
                    sh.append("sysctl -q -w net.ipv4.ip_unprivileged_port_start=1024 || true")
                sh.append("sysctl -q --system >/dev/null 2>&1 || true")
            elif lp.startswith("/etc/udev/"):
                sh.append("udevadm control --reload-rules || true")
    elif a == "snap-remove":
        sh.append("snap remove chromium")
    elif a == "remove-nm":
        sh.append("nmcli connection delete golem-ap")
    elif it["id"] == "system:audio-group":
        sh.append("gpasswd -d %s audio" % _q(ctx.user))
    elif it["id"] == "golem:linger":
        sh.append("loginctl disable-linger %s" % _q(ctx.user))
    elif it["id"] == "dedicated:ufw":
        sh += ["ufw delete allow %s >/dev/null || true" % _q(r) for r in it.get("_rules") or []]
        if it.get("_disable"):
            sh.append("ufw --force disable")
    elif it["id"] == "dedicated:auto-upgrades":
        f = ctx.phys("/etc/apt/apt.conf.d/20auto-upgrades")
        if it.get("_content") is None:
            sh.append("rm -f -- %s" % _q(f))
        else:
            sh.append("printf '%%s' %s > %s" % (_q(it["_content"]), _q(f)))
    elif it["id"] == "dedicated:apt-timers":
        sh.append("systemctl unmask apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true")
        for unit, state in sorted((it.get("_timers") or {}).items()):
            if state == "enabled":
                sh.append("systemctl enable --now %s >/dev/null 2>&1 || true" % _q(unit))
            elif state == "masked":
                sh.append("systemctl mask %s >/dev/null 2>&1 || true" % _q(unit))
    elif it["id"] == "dedicated:governor":
        sh.append('for f in %s/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do [ -e "$f" ] && echo %s > "$f"; '
                  'done; true' % (_q(ctx.fsroot) if ctx.fsroot else "", _q(it["_governor"])))
    else:
        raise UninstallError("no root action for %s" % it["id"])
    return sh


def root_script(ctx, items, root, rpaths):
    """(script, [(id, message de refus)]) — UNE passe root : chaque élément dans un sous-shell `set -e`, son code
    rendu sur une ligne `@@ITEM id code`. Les paquets apt n'y sont PAS : ils ont leur étape (_run_apt), qui simule
    avant de purger."""
    lines = ["#!/bin/sh", "# généré par provision/uninstall.py (docs/uninstall.md §5, étape 3) — jetable", "set -u",
             "export DEBIAN_FRONTEND=noninteractive"]
    if ctx.fsroot:
        lines += ['%s() { echo "simulated: %s $*"; }' % (c.replace("-", "_"), c) for c in SYS_CMDS]
    refused = []
    for it in [i for i in items if i["group"] != "apt"]:
        try:
            body = _root_actions(ctx, it, root, rpaths)
        except UninstallError as e:
            refused.append((it["id"], str(e)))
            continue
        lines.append("out=$( ( set -e; %s ) 2>&1 ); rc=$?" % "; ".join(body))
        lines.append('printf "@@ITEM %%s %%s %%s\\n" %s "$rc" "$(printf "%%s" "$out" | tail -n 1)"' % _q(it["id"]))
    return "\n".join(lines) + "\n", refused


def _run_root(ctx, items, root, rpaths, report):
    if not items:
        return
    script, refused = root_script(ctx, items, root, rpaths)
    for iid, msg in refused:
        report("root", iid, False, msg)
    todo = [i for i in items if i["id"] not in {r[0] for r in refused}]
    if not todo:
        return
    d = tempfile.mkdtemp(prefix="golem-uninstall-root-")
    os.chmod(d, 0o700)
    path = os.path.join(d, "root.sh")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    try:
        if ctx.fsroot or os.geteuid() == 0:
            argv = ["sh", path]
        elif not shutil.which("sudo"):
            for i in todo:
                report("root", i["id"], False, "sudo is not available: root items cannot be removed")
            return
        elif os.environ.get("SUDO_ASKPASS"):
            argv = ["sudo", "-A", "sh", path]
        else:
            argv = ["sudo", "sh", path]       # sans askpass, sudo demande au terminal (s'il y en a un)
        rc, out = run_command(ctx, argv, timeout=3600)
        seen = {}
        for line in (out or "").splitlines():
            if line.startswith("@@ITEM "):
                parts = line.split(" ", 3)
                if len(parts) >= 3:
                    seen[parts[1]] = (parts[2] == "0", parts[3] if len(parts) > 3 else "")
        for i in todo:
            if i["id"] in seen:
                ok, msg = seen[i["id"]]
                report("root", i["id"], ok, msg or ("done" if ok else "failed"))
            else:
                hint = "" if os.environ.get("SUDO_ASKPASS") or ctx.fsroot else " (no SUDO_ASKPASS set: sudo needs a terminal)"
                report("root", i["id"], False, "the elevated pass did not run (exit %s)%s: %s"
                       % (rc, hint, (out or "").strip().splitlines()[-1] if (out or "").strip() else "no output"))
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── apt : les explicites choisis, puis leurs dépendances — chaque purge SIMULÉE d'abord ────────────────────
APT_OPTS = ["-o", "DPkg::Lock::Timeout=300"]
APT_ROUNDS = 3


def _last(out):
    lines = [ln for ln in (out or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


def _sim_removed(out):
    """Les paquets qu'une simulation `apt-get -s` retirerait : ses lignes « Purg X [...] » / « Remv X [...] »
    (jamais traduites). `X:arch` est ramené à `X`, comme dans le reçu."""
    out_ = []
    for ln in (out or "").splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[0] in ("Purg", "Remv"):
            name = parts[1].split(":", 1)[0]
            if name not in out_:
                out_.append(name)
    return out_


def _apt_sim(ctx, args):
    """`apt-get -s …` : sans root, sans verrou, ne touche à rien. Rend (code, sortie)."""
    return run_command(ctx, ["apt-get", "-s"] + list(args), env={**os.environ, "LC_ALL": "C"}, timeout=300)


def _elevated(ctx, argv):
    """La ligne d'une commande root, DEBIAN_FRONTEND sur la ligne même (sudo efface l'environnement) ; None sans sudo."""
    cmd = ["env", "DEBIAN_FRONTEND=noninteractive"] + list(argv)
    if ctx.fsroot or os.geteuid() == 0:
        return cmd
    if not shutil.which("sudo"):
        return None
    return (["sudo", "-A"] if os.environ.get("SUDO_ASKPASS") else ["sudo"]) + cmd


def _apt_installed(ctx, pkgs):
    """Ceux de `pkgs` encore INSTALLÉS (dpkg-query ; une config restante ne compte pas)."""
    if not pkgs:
        return set()
    _rc, out = run_command(ctx, ["dpkg-query", "-W", "-f=${Package} ${db:Status-Status}\n"] + list(pkgs), timeout=60)
    left = set()
    for ln in (out or "").splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1] == "installed" and parts[0] in pkgs:
            left.add(parts[0])
    return left


def _needed_by(foreign):
    return "needed by %s (installed before golem)" % (", ".join(foreign[:3]) + (" +%d" % (len(foreign) - 3)
                                                                                 if len(foreign) > 3 else ""))


def apt_screen(ctx, pkgs, ours):
    """Simule la purge de `pkgs` avant de la faire. Rend (lot sûr, {paquet: raison de le garder}, {paquet: erreur}).
    Un paquet dont la purge emporterait un paquet que golem n'a PAS ajouté (`ours` = apt.added + debs : l'utilisateur
    l'avait avant) sort du lot. Le lot entier d'abord ; s'il emporte un étranger, un paquet à la fois pour savoir lequel."""
    batch, kept, errors = list(dict.fromkeys(pkgs)), {}, {}
    for _ in range(len(batch) + 1):
        if not batch:
            break
        rc, out = _apt_sim(ctx, ["purge"] + batch)
        foreign = [p for p in _sim_removed(out) if p not in ours] if rc == 0 else []
        if rc == 0 and not foreign:
            return batch, kept, errors
        nxt = []
        for p in batch:
            rc1, out1 = _apt_sim(ctx, ["purge", p])
            if rc1 != 0:
                errors[p] = "apt simulation failed: %s" % _last(out1)
                continue
            f = [x for x in _sim_removed(out1) if x not in ours]
            if f:
                kept[p] = _needed_by(f)
            else:
                nxt.append(p)
        if nxt == batch:
            # ensemble ils emportent un paquet d'avant golem (ou apt refuse le lot), aucun seul ne le fait :
            # on ne purge rien plutôt que de deviner
            for p in batch:
                if foreign:
                    kept[p] = _needed_by(foreign)
                else:
                    errors[p] = "apt simulation failed: %s" % _last(out)
            return [], kept, errors
        batch = nxt
    return batch, kept, errors


def _apt_purge(ctx, pkgs):
    argv = _elevated(ctx, ["apt-get"] + APT_OPTS + ["purge", "-y"] + list(pkgs))
    if argv is None:
        return 127, "sudo is not available: packages cannot be removed"
    return run_command(ctx, argv, timeout=3600)


def _run_apt(ctx, items, plan, report):
    """Étape apt (§5) : purge les paquets explicites choisis, puis les dépendances que golem a ajoutées et que plus
    rien ne retient. Rend la liste des dépendances retirées."""
    if not items:
        return []
    ours = set(plan.get("_apt_ours") or [])
    by_pkg = {i["_pkg"]: i for i in items}
    # les explicites que l'utilisateur garde (non cochés) : leurs dépendances restent, et eux jamais purgés ici
    held = {i["_pkg"] for i in plan["items"] if i["group"] == "apt"} - set(by_pkg)
    batch, kept, errors = apt_screen(ctx, list(by_pkg), ours)
    for p, why in kept.items():
        report("apt", by_pkg[p]["id"], False, "kept: " + why, kept=True)
    for p, msg in errors.items():
        report("apt", by_pkg[p]["id"], False, msg)
    held |= set(kept) | set(errors)
    if not batch:
        return []
    rc, out = _apt_purge(ctx, batch)
    left = _apt_installed(ctx, batch)
    for p in batch:
        ok = p not in left
        report("apt", by_pkg[p]["id"], ok, "purged" if ok else "still installed (apt-get exit %s: %s)" % (rc, _last(out)))
    # les dépendances : ce qu'apt retirerait en autoremove ∩ ce que golem a ajouté — jamais un autoremove nu
    removed, tried = [], set()
    for _round in range(APT_ROUNDS):
        rc, out = _apt_sim(ctx, ["autoremove", "--purge"])
        if rc != 0:
            report("apt", None, False, "dependencies: apt simulation failed: %s" % _last(out))
            break
        cands = [p for p in _sim_removed(out) if p in ours and p not in held and p not in tried and not _never_apt(p)]
        if not cands:
            break
        tried.update(cands)
        dbatch, dkept, derr = apt_screen(ctx, cands, ours)
        for p, why in dkept.items():
            report("apt", None, True, "dependency %s kept: %s" % (p, why))
        for p, msg in derr.items():
            report("apt", None, False, "dependency %s: %s" % (p, msg))
        if not dbatch:
            break
        rc, out = _apt_purge(ctx, dbatch)
        left = _apt_installed(ctx, dbatch)
        removed += [p for p in dbatch if p not in left]
        if left:
            report("apt", None, False, "%d dependencies could not be removed (apt-get exit %s): %s"
                   % (len(left), rc, ", ".join(sorted(left))))
    report("apt", None, True, "%d dependenc%s removed" % (len(removed), "y" if len(removed) == 1 else "ies"),
           deps=len(removed))
    return removed


def _reaper_running(ctx):
    rc, _out = run_command(ctx, ["pgrep", "-x", "reaper"], timeout=10)
    return rc == 0 and not ctx.fsroot


def revert_ini(ctx, keys, csurf):
    return revert_ini_file(ctx.phys(REAPER_DIR + "/reaper.ini"), keys, csurf)


def revert_ini_file(p, keys, csurf):
    """reaper.ini (chemin réel) remis : clés d'avant, surface OSC de golem retirée ; copie gardée, écriture atomique.
    Partagé avec Windows (provision/uninstall_win.py)."""
    with open(p, encoding="latin-1", newline="") as f:
        text = f.read()
    new, changes = ini_revert(text, keys, csurf)
    if not changes:
        return "nothing to change"
    shutil.copy2(p, p + ".golem-uninstall")
    fd, tmp = tempfile.mkstemp(prefix=".reaper.ini.", dir=os.path.dirname(p))
    try:
        with os.fdopen(fd, "w", encoding="latin-1", newline="") as f:
            f.write(new)
        shutil.copymode(p, tmp)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return "; ".join(changes) + " (copy kept as reaper.ini.golem-uninstall)"


def _reaper_desktop_uninstall(ctx, it):
    """Le désinstalleur de REAPER lui-même pour son intégration bureau (`uninstall-reaper.sh --remove-user-desktop
    --quiet` : non interactif, il ne touche qu'aux entrées cockos-reaper). Il passe par les outils xdg, que l'étape
    apt a pu retirer : les fichiers sont ENSUITE retirés un par un quoi qu'il rende (chemins de l'élément)."""
    script = os.path.join(it.get("_base") or ctx.expand("~/opt/REAPER"), "uninstall-reaper.sh")
    if not os.path.isfile(ctx.phys(script)):
        return []
    rc, _out = run_command(ctx, ["/bin/sh", ctx.phys(script), "--remove-user-desktop", "--quiet"], timeout=120)
    return ["REAPER's own uninstaller removed its desktop integration" if rc == 0
            else "REAPER's own uninstaller failed (exit %s): its files are removed one by one" % rc]


def _user_action(ctx, it, root, rpaths):
    a = it["action"]
    if it["id"] == "reaper-ini:revert":
        if _reaper_running(ctx):
            raise UninstallError("REAPER is running: it would rewrite reaper.ini when it quits")
        return revert_ini(ctx, it.get("_keys") or {}, it.get("_csurf"))
    if a == "disable":
        run_command(ctx, ["systemctl", "--user", "disable", "--now", it["_unit"]], timeout=60)
        msg = safe_remove(ctx, it["_paths"][0], root, rpaths)
        run_command(ctx, ["systemctl", "--user", "daemon-reload"], timeout=60)
        return msg
    if it.get("_keep_receipt"):
        base = it["_paths"][0]
        n = 0
        for name in sorted(os.listdir(ctx.phys(base))):
            if name != os.path.basename(RECEIPT):
                safe_remove(ctx, base + "/" + name, root, rpaths)
                n += 1
        if not os.path.exists(ctx.receipt_path):
            try:
                os.rmdir(ctx.phys(base))
            except OSError:
                pass
        return "%d entries removed" % n
    if it["id"] == "golem:inbox":
        p = it["_paths"][0]
        # déplacé par l'utilisateur (config/inbox.json) : hors de l'ensemble attendu, on n'enlève qu'un dossier VIDE
        return _remove_empty_tree(ctx, p, root) if it.get("_inbox_custom") else safe_remove(ctx, p, root, rpaths)
    msgs = []
    if it["id"] == "reaper:app":
        msgs += _reaper_desktop_uninstall(ctx, it)
    for p in it.get("_paths") or []:
        msgs.append(safe_remove(ctx, p, root, rpaths))
    if a == "restore" and it.get("_restore"):
        src, dst = ctx.expand(it["_restore"]), it["_paths"][0]
        if not _expected(ctx, dst, root, rpaths) or _forbidden(ctx, src):
            raise UninstallError("refused: cannot restore %s" % src)
        if os.path.lexists(ctx.phys(dst)):
            raise UninstallError("cannot put the original back: %s is in the way" % dst)
        os.rename(ctx.phys(src), ctx.phys(dst))
        msgs.append("original put back")
    if it["id"] == "plugins:tapedelay2":
        try:
            os.rmdir(ctx.phys("~/.vst/airwindows"))
        except OSError:
            pass
    return ", ".join(msgs) or "done"


def _rewrite_receipt(ctx, receipt, plan, done, failed, removed_pkgs=()):
    """Le reçu après un passage : supprimé si tout est fait et golem parti ; sinon réécrit avec ce qui reste."""
    p = ctx.receipt_path
    done_rids, done_prior, done_pkgs = set(), set(), set(removed_pkgs)
    for it in plan["items"]:
        if it["id"] in done:
            done_rids.update(it.get("_rids") or [])
            done_prior.update(it.get("_prior_keys") or [])
            if it.get("_pkg"):
                done_pkgs.add(it["_pkg"])
    done_rids.update(plan["absent"])
    done_pkgs.update(a[4:] for a in plan["absent"] if a.startswith("apt:"))
    r = json.loads(json.dumps(receipt))
    r["items"] = [i for i in (r.get("items") or []) if isinstance(i, dict) and i.get("id") not in done_rids
                  and ctx.expand(i.get("path") or "") not in done_rids]
    apt = r.get("apt") or {}
    for k in ("added", "debs", "requested"):
        if isinstance(apt.get(k), list):
            apt[k] = [x for x in apt[k] if x not in done_pkgs]
    pr = r.get("prior") or {}
    for k in done_prior:
        pr.pop(k, None)
    r["uninstall"] = {"updated": datetime.datetime.now().isoformat(timespec="seconds"), "failed": sorted(failed)}
    fd, tmp = tempfile.mkstemp(prefix=".install-receipt.", dir=os.path.dirname(p))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def run(ctx, ids, report):
    """Exécute les ids choisis dans l'ordre du §5. Rend True si tout a réussi."""
    receipt, _w = load_receipt(ctx)
    plan = build_plan(ctx)
    by_id = {i["id"]: i for i in plan["items"]}
    unknown = [i for i in ids if i not in by_id]
    if unknown:
        raise UninstallError("not in the plan (absent, or not golem's): %s" % ", ".join(unknown))
    chosen = [by_id[i] for i in dict.fromkeys(ids)]
    root = plan["root"]
    rpaths = {ctx.expand(r["path"]) for r in ((receipt or {}).get("items") or []) if isinstance(r, dict) and r.get("path")}

    # 2. arrêter le moteur (autostart off, puis REAPER et le bridge)
    run_command(ctx, ["systemctl", "--user", "stop", "golem-server.service"], timeout=60)
    if root and os.path.isdir(ctx.phys(root)):
        for argv, label in (([ctx.phys(root + "/provision/autostart/install-autostart.sh"), "--off"], "autostart off"),
                            ([ctx.phys(root + "/provision/stop.sh")], "engine stopped")):
            if os.path.isfile(argv[0]):
                rc, out = run_command(ctx, argv, timeout=120)
                report("stop", None, rc == 0, label if rc == 0 else "%s: exit %s %s" % (label, rc, out[-200:]))
            else:
                report("stop", None, True, "%s: %s absent, skipped" % (label, os.path.basename(argv[0])))
    else:
        report("stop", None, True, "install folder absent: nothing to stop")

    # 3. une seule passe root, puis les paquets apt (simulés avant d'être purgés) et leurs dépendances
    _run_root(ctx, [i for i in chosen if i["privilege"] == "root" and i["group"] != "apt"], root, rpaths, report)
    removed_deps = _run_apt(ctx, [i for i in chosen if i["group"] == "apt"], plan, report)

    # 4. REAPER, 5. plugins, toolchain, intégration utilisateur
    order = (("reaper", ("reaper-links", "reaper-ini", "reaper")), ("user", ("plugins", "toolchain", "golem")))
    for step, groups in order:
        for g in groups:
            for it in chosen:
                if it["group"] != g or it["privilege"] != "user" or it.get("_step") == "folder":
                    continue
                try:
                    report(step, it["id"], True, _user_action(ctx, it, root, rpaths))
                except (UninstallError, OSError) as e:
                    report(step, it["id"], False, str(e))

    # 6. le dossier d'install, EN DERNIER
    for it in chosen:
        if it.get("_step") != "folder":
            continue
        real_root = os.path.realpath(ctx.phys(root))
        inside = [s for s in _self_paths() if _inside(os.path.realpath(s), real_root)]
        if inside:
            report("folder", it["id"], False, "refused: the uninstaller runs from inside the install folder (%s) — "
                   "copy it elsewhere first (the graphical uninstaller runs from /tmp)" % inside[0])
            continue
        try:
            report("folder", it["id"], True, safe_remove(ctx, root, root, rpaths))
        except (UninstallError, OSError) as e:
            report("folder", it["id"], False, str(e))

    # 6 ter. les dossiers CONTENEURS que l'install a pu créer pour y poser ses fichiers (premier cycle en VM, 2026-10-15 :
    # ~/.lv2, ~/.vst3, ~/.clap, ~/opt restaient, vides). Seulement s'ils sont VIDES : un dossier vide ne porte rien à
    # personne, un dossier qui contient encore quelque chose (un plugin à toi, REAPER gardé) n'est jamais touché.
    # 6 bis. les bases du bureau, si une entrée de menu, une icône ou un type de fichier est parti (3e cycle en VM,
    # 2026-10-16 : mimeinfo.cache, icon-theme.cache, la base MIME et le menu « dummy » de xdg restaient)
    desk = (ctx.expand("~/.local/share/applications"), ctx.expand("~/.local/share/icons"),
            ctx.expand("~/.local/share/mime"), ctx.expand("~/.gnome/apps"))
    if any(report.results.get(it["id"]) and any(_inside(p, d) for p in it.get("_paths") or [] for d in desk)
           for it in chosen):
        try:
            did = desktop_refresh(ctx, root, rpaths)
            report("folder", None, True, "desktop databases: %s" % (", ".join(did) or "nothing to do"))
        except (UninstallError, OSError) as e:
            report("folder", None, False, "desktop databases: %s" % e)
    emptied = []
    for d in CONTAINER_DIRS:
        try:
            os.rmdir(ctx.phys(ctx.expand(d)))
            emptied.append(d)
        except OSError:
            pass
    if emptied:
        report("folder", None, True, "empty folders removed: %s" % ", ".join(emptied))

    # 7. le reçu
    done = {k for k, v in report.results.items() if v}
    kept = set(getattr(report, "kept", ()))
    failed = {i["id"] for i in chosen if not report.results.get(i["id"]) and i["id"] not in kept}
    all_ok = not failed
    if receipt is None:
        report("receipt", None, True, "no install receipt: nothing to update")
    else:
        golem_gone = not root or not os.path.exists(ctx.phys(root))
        try:
            if all_ok and golem_gone:
                os.unlink(ctx.receipt_path)
                try:
                    os.rmdir(ctx.phys(SHARE_DIR))
                except OSError:
                    pass
                report("receipt", None, True, "receipt deleted: golem is uninstalled")
            else:
                _rewrite_receipt(ctx, receipt, plan, done, failed, removed_deps)
                report("receipt", None, True, "receipt rewritten with what remains (%d failed)" % len(failed))
        except OSError as e:
            report("receipt", None, False, "receipt: %s" % e)
    note = (", except %d package(s) kept: software installed before golem needs them" % len(kept)) if kept else ""
    report("done", None, all_ok, ("everything chosen was removed" + note) if all_ok
           else "%d item(s) failed: %s" % (len(failed), ", ".join(sorted(failed))))
    return all_ok


def _read_selection(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except ValueError:
        return [ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("#")]
    if isinstance(data, dict):
        data = data.get("items") or data.get("ids") or []
    out = []
    for x in data:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict) and x.get("id") and x.get("selected", x.get("default", True)):
            out.append(x["id"])
    return out


def _windows():
    """provision/uninstall_win.py, chargé à côté de CE fichier (la copie du désinstallateur dans %TEMP%, ou le dépôt)."""
    if __name__.startswith("provision."):
        from provision import uninstall_win
        return uninstall_win
    import importlib.util
    spec = importlib.util.spec_from_file_location("golem_uninstall_win",
                                                  os.path.join(os.path.dirname(os.path.abspath(__file__)), "uninstall_win.py"))
    m = importlib.util.module_from_spec(spec)
    # le moteur commun, déjà chargé : celui-ci (chargé par son chemin sans être inscrit : ses globales)
    import types
    sys.modules.setdefault("uninstall", sys.modules.get(__name__) or types.SimpleNamespace(**globals()))
    spec.loader.exec_module(m)
    return m


def main(argv=None):
    ap = argparse.ArgumentParser(prog="uninstall.py", description="Uninstall golem (docs/uninstall.md).")
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
    if sys.platform == "win32":
        # Windows : la même CLI, le même modèle de plan, une autre couche (docs/uninstall.md §9.3)
        return _windows().main(argv)
    a = ap.parse_args(argv)
    ctx = Ctx(fsroot=a.root_fs, root=a.root)
    if a.cmd == "plan":
        plan = build_plan(ctx)
        print(json.dumps(public(plan), indent=1) if a.json else plan_text(plan))
        return 0
    ids = a.items or _read_selection(a.select)
    if not ids:
        print("nothing selected", file=sys.stderr)
        return 2
    if not a.yes:
        if not sys.stdin.isatty() or a.json:
            print("refused: pass --yes (no terminal to confirm on)", file=sys.stderr)
            return 2
        plan = build_plan(ctx)
        pick = public({**plan, "items": [i for i in plan["items"] if i["id"] in ids]})
        print(plan_text(pick))
        if input("\nRemove these %d item(s)? Type yes: " % len(pick["items"])).strip().lower() != "yes":
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
