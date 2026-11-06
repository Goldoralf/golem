# SPDX-License-Identifier: GPL-3.0-or-later
"""La licence REAPER sur cette machine — UNE implémentation, partagée par le bridge (Settings ▸ About,
bridge/routes_system.py) et par l'installateur (écran 3, installer/server.py), qui le charge par son CHEMIN : le
bridge ne tourne pas pendant l'installation. Bibliothèque standard seulement, aucun import du paquet `bridge`.

Le dossier de ressources de REAPER (celui qu'il LIT) vit ici aussi : bridge/config.py le réexporte, pour que
l'installateur et le bridge posent la clé au même endroit, sur les trois systèmes. Et, sous Windows, OÙ EST
REAPER (`windows_exe`) : le même endroit pour l'installateur, le lancement, la mise à jour et le pare-feu.

La licence est un SECRET : ce module ne la rend jamais, ne la journalise jamais. Il dit seulement si un fichier
est là. Validation minimale — du texte, non vide, au plus 64 Ko : on n'invente pas un format qu'on ne peut pas
vérifier (REAPER juge la clé lui-même au démarrage)."""
import os
import sys

FILENAME = "reaper-license.rk"
MAX_BYTES = 64 * 1024
RECEIPT_KEY = "reaper.license_present"


def user_home():
    # os.path.expanduser dépend de l'OS hôte ; HOME/USERPROFILE rendent les
    # simulations d'OS et la règle Lua identiques.
    if sys.platform == "win32":
        return os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.environ.get("HOME") or os.path.expanduser("~")


# ── OÙ EST REAPER, sous Windows (2026-10-17) ─────────────────────────────────────────────────────────────────────
# On ne regardait QUE « C:\Program Files\REAPER (x64) » : un REAPER installé sur D: était invisible, et golem en
# installait un second sur C: (un testeur, le 2026-10-17). L'ordre de recherche :
#   1. REAPER_BIN (bancs, tests) ;
#   2. le chemin RETENU par golem (%LOCALAPPDATA%\GoleM\reaper-path.txt — l'écran « J'ai déjà REAPER ailleurs », ou
#      le dossier choisi quand golem l'a installé) ;
#   3. le registre : la clé que l'installateur de REAPER écrit (HKLM/HKCU\Software\REAPER, valeur par défaut = son
#      dossier), puis les entrées « Ajout/suppression de programmes » REAPER (InstallLocation, ou le dossier de
#      UninstallString) ;
#   4. Program Files, le défaut de l'installateur de REAPER.
# Le premier reaper.exe qui EXISTE gagne ; sinon le chemin par défaut (qui n'existe pas : « pas installé »).
SAVED_NAME = "reaper-path.txt"


def _localappdata():
    return os.environ.get("LOCALAPPDATA") or os.path.join(user_home(), "AppData", "Local")


def saved_path_file():
    return os.path.join(_localappdata(), "GoleM", SAVED_NAME)


def default_windows_exe():
    return os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "REAPER (x64)", "reaper.exe")


def as_exe(path):
    """Un dossier ou un reaper.exe -> le chemin de reaper.exe (sans vérifier qu'il existe)."""
    p = os.path.expandvars(str(path or "").strip().strip('"'))
    return p if p.lower().endswith(".exe") else os.path.join(p, "reaper.exe")


# ⚠ CHEMIN CHAUD (2026-10-19). `resource_dir()` passe par `windows_exe()` depuis le 17/10, et il est appelé à
# chaque lecture de reaper.ini — trois fois par chargement de preset (inputmap → desktop_audio.settings). Or le
# balayage des clés de désinstallation coûte ~10 ms : la page Songs en faisait 3 195, soit 30 s. Le registre ne
# change qu'à l'installation de REAPER, et l'installateur re-vérifie chaque seconde : une mémoire de 2 s suffit.
_REG_TTL_S = 2.0
_REG_CACHE = {"at": 0.0, "dirs": None}


def _registry_dirs():
    """Les dossiers de REAPER que le registre connaît. Vide hors Windows, ou si le registre ne répond pas.
    Mémorisé `_REG_TTL_S` secondes (voir ci-dessus)."""
    import time
    now = time.monotonic()
    if _REG_CACHE["dirs"] is not None and now - _REG_CACHE["at"] < _REG_TTL_S:
        return list(_REG_CACHE["dirs"])
    dirs = _registry_dirs_uncached()
    _REG_CACHE["at"], _REG_CACHE["dirs"] = now, list(dirs)
    return dirs


def _registry_dirs_uncached():
    try:
        import winreg
    except ImportError:
        return []
    out = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (0, getattr(winreg, "KEY_WOW64_64KEY", 0)):
            try:
                with winreg.OpenKey(hive, r"Software\REAPER", 0, winreg.KEY_READ | view) as k:
                    out.append(winreg.QueryValueEx(k, "")[0])
            except OSError:
                pass
            for root in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                         r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                try:
                    with winreg.OpenKey(hive, root, 0, winreg.KEY_READ | view) as k:
                        for i in range(winreg.QueryInfoKey(k)[0]):
                            try:
                                with winreg.OpenKey(k, winreg.EnumKey(k, i)) as e:
                                    name = str(winreg.QueryValueEx(e, "DisplayName")[0])
                                    if not name.upper().startswith("REAPER"):
                                        continue
                                    for val in ("InstallLocation", "UninstallString"):
                                        try:
                                            v = str(winreg.QueryValueEx(e, val)[0]).strip().strip('"')
                                        except OSError:
                                            continue
                                        if v:
                                            out.append(v if val == "InstallLocation" else os.path.dirname(
                                                v.split('" ')[0].split(" /")[0].strip('"')))
                            except OSError:
                                continue
                except OSError:
                    continue
    return [d for d in out if d]


def windows_candidates():
    """Les reaper.exe possibles, dans l'ordre de confiance (cf. plus haut)."""
    out = []
    env = os.environ.get("REAPER_BIN")
    if env:
        out.append(env)
    try:
        with open(saved_path_file(), encoding="utf-8") as f:
            saved = f.read().strip()
        if saved:
            out.append(as_exe(saved))
    except OSError:
        pass
    out += [as_exe(d) for d in _registry_dirs()]
    out.append(default_windows_exe())
    seen, uniq = set(), []
    for p in out:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def windows_exe():
    """Le reaper.exe de cette machine : le premier candidat qui existe, sinon le chemin par défaut."""
    for p in windows_candidates():
        if os.path.isfile(p):
            return p
    return default_windows_exe()


def remember_windows_exe(path):
    """Retient l'emplacement de REAPER (dossier ou reaper.exe). Rend le reaper.exe, ou lève ValueError s'il
    n'existe pas : on ne retient pas un chemin faux."""
    exe = as_exe(path)
    if not os.path.isfile(exe):
        raise ValueError(f"no reaper.exe in {path}")
    f = saved_path_file()
    os.makedirs(os.path.dirname(f), exist_ok=True)
    tmp = f + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(exe + "\n")
    os.replace(tmp, f)
    return exe


def portable_dir(exe=None):
    """Un REAPER PORTABLE garde ses réglages dans SON dossier (reaper.ini posé à côté de reaper.exe) : c'est là
    qu'il lit scripts, effets et licence, pas %APPDATA%. None pour une installation normale."""
    exe = exe or windows_exe()
    d = os.path.dirname(exe)
    return d if os.path.isfile(os.path.join(d, "reaper.ini")) else None


def resource_dir():
    """Le dossier de ressources de REAPER : ~/.config/REAPER sous Linux, %APPDATA%\\REAPER (Windows — ou le
    dossier d'un REAPER PORTABLE), ~/Library/Application Support/REAPER (macOS). GOLEM_REAPER_RESOURCE_DIR le
    remplace (tests, bancs)."""
    override = os.environ.get("GOLEM_REAPER_RESOURCE_DIR")
    if override:
        if not os.path.isabs(override):
            raise ValueError("GOLEM_REAPER_RESOURCE_DIR doit être un chemin absolu")
        return override
    if sys.platform == "win32":
        port = portable_dir()
        if port:
            return port
        base = os.environ.get("APPDATA") or os.path.join(user_home(), "AppData", "Roaming")
        return os.path.join(base, "REAPER")
    # posixpath, pas os.path : ces deux systèmes écrivent « / » — même quand le test les joue depuis Windows
    import posixpath
    if sys.platform == "darwin":
        return posixpath.join(user_home(), "Library", "Application Support", "REAPER")
    return posixpath.join(user_home(), ".config", "REAPER")


def path(resource=None):
    """Calculé à l'appel : un chemin figé à l'import poserait la clé là où REAPER ne regarde jamais."""
    return os.path.join(resource or resource_dir(), FILENAME)


def present(resource=None):
    return os.path.isfile(path(resource))


def clean(text):
    """(licence nettoyée, None) ou (None, erreur en anglais — montrée à l'écran). Jamais le contenu dans l'erreur."""
    if text is None:
        text = ""
    if not isinstance(text, str):
        return None, "the license must be text"
    t = text.strip()
    if not t:
        return None, "empty license"
    if "\x00" in t:
        return None, "this is not a text file — pick the .rk file REAPER gave you"
    if len(t.encode("utf-8", "replace")) > MAX_BYTES:
        return None, "this is larger than 64 KB — a REAPER license is a short text; check the file"
    return t, None


def write(text, resource=None, prior=None):
    """Écrit <ressources>/reaper-license.rk (mode 0600, atomique) ; crée le dossier s'il manque. REAPER l'importe à
    son prochain démarrage. `prior(key, value)` : le reçu d'installation (docs/uninstall.md §2) — y avait-il une
    licence AVANT golem ? noté avant d'écrire, le premier gagne ; un reçu raté ne fait jamais échouer l'écriture.
    Lève ValueError (message de clean) si le texte est refusé. Rend le chemin écrit."""
    lic, err = clean(text)
    if err:
        raise ValueError(err)
    p = path(resource)
    if prior is not None:
        try:
            prior(RECEIPT_KEY, os.path.isfile(p))
        except Exception:
            pass
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    # 0600 dès la création : le secret n'existe jamais lisible par d'autres, même un instant
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(lic + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p
